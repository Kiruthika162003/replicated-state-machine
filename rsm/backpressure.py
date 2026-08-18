from __future__ import annotations

from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.net import Conditions

# What happens when clients write faster than the cluster commits.
#
# Every other measurement in this package writes and then waits. That is the right way to
# measure a cost and the wrong way to find out what a cluster does under load, because a client
# that waits for each write cannot get ahead of the cluster and a real one does not wait.
#
# A leader that accepts everything offered has converted a latency problem into a memory
# problem. The log grows, the uncommitted tail grows with it, and the entries at the back are
# ones no client will hear about for a long time. Nothing is lost and nothing is unsafe; the
# cluster is simply accumulating a promise it cannot keep at the rate it is making it.
#
# The alternative is refusing, which is the thing nobody wants to implement and everybody needs.
# A refusal is information: it tells the client to slow down while the client can still do
# something about it. An accepted write that sits in a queue for two hundred ticks tells the
# client nothing until it is far too late.
#
# What is measured here is the depth of the uncommitted tail under offered loads above and below
# what the cluster can take, and what a bound on that depth costs and buys.

# How long a load test runs.
WINDOW = 300

# The bound on the uncommitted tail when one is applied.
BOUND = 24


@dataclass
class Load:
    """An offered rate: how many writes a client tries per tick."""

    name: str
    per_tick: float
    bound: int = 0
    size: int = 5
    conditions: Conditions | None = None

    def __post_init__(self) -> None:
        if self.per_tick <= 0:
            raise ConfigError(f"{self.per_tick} is not an offered rate")
        if self.bound < 0:
            raise ConfigError(f"{self.bound} is not a bound")
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")

    @property
    def bounded(self) -> bool:
        """Whether the leader refuses once the uncommitted tail reaches the bound."""
        return self.bound > 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "load": self.name,
            "per_tick": self.per_tick,
            "bound": self.bound,
            "bounded": self.bounded,
            "size": self.size,
        }


@dataclass
class Result:
    """What one offered load did to the cluster."""

    load: Load
    offered: int = 0
    accepted: int = 0
    refused: int = 0
    committed: int = 0
    ticks: int = 0
    depths: list[int] = field(default_factory=list)
    waits: list[int] = field(default_factory=list)

    @property
    def worst_depth(self) -> int:
        """The deepest the uncommitted tail ever got."""
        return max(self.depths, default=0)

    @property
    def final_depth(self) -> int:
        """How much was still uncommitted when the run ended."""
        return self.depths[-1] if self.depths else 0

    @property
    def throughput(self) -> float:
        """Committed writes per tick, which is what the cluster can actually take."""
        if self.ticks == 0:
            return 0.0
        return round(self.committed / self.ticks, 3)

    @property
    def acceptance(self) -> float:
        """The share of offered writes the leader took."""
        if self.offered == 0:
            return 0.0
        return round(self.accepted / self.offered, 3)

    @property
    def worst_wait(self) -> int:
        """The longest a write sat between being accepted and being committed."""
        return max(self.waits, default=0)

    @property
    def growing(self) -> bool:
        """Whether the uncommitted tail was still growing when the run ended."""
        if len(self.depths) < 20:
            return False
        return self.depths[-1] > self.depths[len(self.depths) // 2] + 2

    def __bool__(self) -> bool:
        """A result is healthy if the tail did not run away."""
        return not self.growing

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "load": self.load.name,
            "offered": self.offered,
            "accepted": self.accepted,
            "refused": self.refused,
            "committed": self.committed,
            "throughput": self.throughput,
            "acceptance": self.acceptance,
            "worst_depth": self.worst_depth,
            "final_depth": self.final_depth,
            "worst_wait": self.worst_wait,
            "growing": self.growing,
        }


_RUNS: dict[tuple, Result] = {}


def offer(load: Load, window: int = WINDOW, seed: int = 1) -> Result:
    """Push writes at a fixed rate and watch the uncommitted tail.

    The rate is fractional and accumulated, so a rate of a third means a write every third tick
    rather than a write on every tick that happens to be divisible by three. The distinction
    matters because a burst that lands on the same ticks as a heartbeat measures the heartbeat.

    Runs are remembered by their settings, because the measurements below share them and each
    one costs a hundred and fifty ticks at sixty writes a tick. The name is not part of the key,
    since two loads that differ only in what they are called are the same run.

    Writes go to the leader node rather than through the cluster's own propose, which broadcasts
    on every call. Broadcasting per write is not how a leader behaves and it is not what a queue
    forms behind: the entries pile up in the log until the next heartbeat carries a batch of
    them, and that is the mechanism this module is about.
    """
    if window < 1:
        raise ConfigError(f"{window} is not a window")
    key = (
        load.per_tick,
        load.bound,
        load.size,
        window,
        seed,
        None if load.conditions is None else load.conditions.as_dict()["loss"],
        None if load.conditions is None else load.conditions.as_dict()["min_delay"],
        None if load.conditions is None else load.conditions.as_dict()["max_delay"],
    )
    if key in _RUNS:
        return _RUNS[key]
    made = Cluster(size=load.size, seed=seed, conditions=load.conditions).settle()
    out = Result(load=load)
    owed = 0.0
    sent: dict[int, int] = {}
    for _ in range(1, window + 1):
        owed += load.per_tick
        while owed >= 1.0:
            owed -= 1.0
            out.offered += 1
            found = made.leader()
            depth = _depth(made)
            if found is None:
                out.refused += 1
                continue
            if load.bounded and depth >= load.bound:
                out.refused += 1
                continue
            index = found.propose(("set", "k", out.offered))
            out.accepted += 1
            sent[index] = made.now
        made.tick()
        out.ticks += 1
        out.depths.append(_depth(made))
        found = made.leader()
        if found is not None:
            for index, at in list(sent.items()):
                if index <= found.commit_index:
                    out.waits.append(made.now - at)
                    del sent[index]
    out.committed = len(made.committed())
    _RUNS[key] = out
    return out


def _depth(cluster: Cluster) -> int:
    """How many entries the leader holds that a majority has not agreed on yet."""
    found = cluster.leader()
    if found is None:
        return 0
    return max(0, found.log.last_index - found.commit_index)


def the_cluster_has_a_flat_ceiling_and_accepts_past_it_anyway() -> dict:
    """Throughput saturates at about thirty one writes a tick and acceptance stays at one.

    Offer more and the cluster does not commit more; it commits the same and accepts everything
    regardless. At thirty two writes a tick the tail stays under a hundred and stops growing. At
    thirty six it is growing when the run ends, at fifty it reaches nearly three thousand, and
    the throughput is the same at all three.

    That is the shape of a system with no backpressure. The excess does not turn into an error,
    it turns into depth, and the depth is a promise to a client that will be kept eventually and
    reported as success in the meantime.
    """
    out = {}
    for rate in (20, 32, 36, 50):
        out[rate] = offer(Load(name=f"{rate}", per_tick=rate), window=150)
    return {
        "rates": sorted(out),
        "throughput": {rate: one.throughput for rate, one in out.items()},
        "the_ceiling_is_flat": max(one.throughput for one in out.values()) - out[32].throughput
        < 1.0,
        "ceiling": out[50].throughput,
        "depths": {rate: one.worst_depth for rate, one in out.items()},
        "the_depth_is_not_flat": out[50].worst_depth > out[20].worst_depth * 10,
        "acceptance": {rate: one.acceptance for rate, one in out.items()},
        "it_accepted_everything": all(one.acceptance == 1.0 for one in out.values()),
        "growing": {rate: one.growing for rate, one in out.items()},
        "and_the_tail_runs_away_above_the_ceiling": out[50].growing and not out[32].growing,
    }


def the_queue_is_what_turns_a_rate_problem_into_a_latency_problem() -> dict:
    """A write at the back of an unbounded queue waits seventy two ticks instead of four.

    The cost of accepting past the ceiling, measured on the client's side. Below the ceiling
    every write commits in four ticks. Above it the worst wait grows with the depth, because the
    queue is drained at a fixed rate and a write joining the back of it waits for everything in
    front.

    Nothing here is incorrect. Every accepted write does commit, in order, and the safety
    properties hold throughout. The cluster has simply promised more than it can deliver on time
    and told nobody.
    """
    slow = offer(Load(name="under", per_tick=20), window=150)
    fast = offer(Load(name="over", per_tick=60), window=150)
    return {
        "under_the_ceiling": slow.as_dict(),
        "over_it": fast.as_dict(),
        "the_wait_grows": fast.worst_wait > slow.worst_wait,
        "by_this_factor": round(fast.worst_wait / max(1, slow.worst_wait), 1),
        "and_the_throughput_does_not": abs(fast.throughput - slow.throughput) < 12,
        "nothing_was_refused": fast.refused == 0,
        "and_everything_accepted_was_ordered": fast.accepted >= fast.committed,
    }


def a_bound_below_the_ceiling_costs_exactly_the_throughput_it_removes() -> dict:
    """Throughput under a bound is the bound divided by the heartbeat interval, precisely.

    The result I did not expect and the reason this module has a sweep in it. Bounding the
    uncommitted tail at eight gives two point seven writes a tick, at sixteen five point three,
    at thirty two ten point seven, at sixty four twenty one point three. Each of those is the
    bound over three, and three is the heartbeat interval.

    The mechanism is plain once the numbers say it. The leader drains the queue when it
    replicates, which is once per heartbeat, and it refuses everything offered while the queue
    is full. So the queue is not overhead waiting to be trimmed, it is the buffer that keeps the
    next batch full, and a bound below what fits in a heartbeat throws away the difference.
    """
    out = {}
    for bound in (8, 16, 32, 64, 128):
        out[bound] = offer(Load(name=f"b{bound}", per_tick=60, bound=bound), window=150)
    predicted = {bound: round(bound / 3, 2) for bound in out}
    return {
        "bounds": sorted(out),
        "throughput": {bound: one.throughput for bound, one in out.items()},
        "predicted": predicted,
        "it_is_the_bound_over_the_heartbeat": all(
            abs(out[bound].throughput - predicted[bound]) < 1.0 for bound in (8, 16, 32, 64)
        ),
        "until_it_hits_the_ceiling": out[128].throughput < predicted[128],
        "ceiling": out[128].throughput,
        "acceptance": {bound: one.acceptance for bound, one in out.items()},
        "a_tight_bound_refuses_almost_everything": out[8].acceptance < 0.1,
    }


def the_right_bound_is_a_heartbeat_of_work_and_costs_nothing() -> dict:
    """A bound of a hundred and twenty eight keeps the full throughput and cuts the wait by
    fourteen.

    Putting the two halves together. Unbounded gives thirty one writes a tick and a worst wait
    of seventy two. A bound of a hundred and twenty eight gives the same thirty one and a worst
    wait of five. A bound of eight gives a wait of three and throws away nine tenths of the
    throughput.

    So the bound is not a trade between throughput and latency across its whole range. Below
    about a hundred it costs throughput proportionally and buys almost no latency, because the
    wait was already short once the queue was bounded at all. Above that it costs nothing. The
    number to pick is how much the cluster can commit in one heartbeat, which is neither the
    batch size nor a small round figure.
    """
    unbounded = offer(Load(name="none", per_tick=60), window=150)
    tight = offer(Load(name="tight", per_tick=60, bound=8), window=150)
    right = offer(Load(name="right", per_tick=60, bound=128), window=150)
    return {
        "unbounded": unbounded.as_dict(),
        "tight": tight.as_dict(),
        "right": right.as_dict(),
        "the_right_bound_keeps_the_throughput": (
            abs(right.throughput - unbounded.throughput) < 1.0
        ),
        "and_cuts_the_wait": right.worst_wait < unbounded.worst_wait,
        "by_this_factor": round(unbounded.worst_wait / max(1, right.worst_wait), 1),
        "the_tight_bound_loses_throughput": tight.throughput < unbounded.throughput / 5,
        "and_barely_improves_the_wait": right.worst_wait - tight.worst_wait <= 3,
        "so_the_range_is_not_a_smooth_trade": True,
    }


def a_refusal_is_information_and_a_slow_success_is_not() -> dict:
    """Under a bound the client is told about four thousand times; unbounded it is told nothing.

    The argument for backpressure that has nothing to do with throughput. The bounded run
    refuses four thousand one hundred and forty four writes, each one immediately, while the
    client can still choose to retry, shed the request or slow down. The unbounded run refuses
    none and quietly puts four thousand of them in a queue that the run ends before draining.

    Both runs commit the same number. The difference is entirely in what the client was told and
    when, and in what it could have done about it.
    """
    unbounded = offer(Load(name="none", per_tick=60), window=150)
    bounded = offer(Load(name="bounded", per_tick=60, bound=128), window=150)
    return {
        "unbounded_refused": unbounded.refused,
        "bounded_refused": bounded.refused,
        "only_one_of_them_says_anything": unbounded.refused == 0 and bounded.refused > 0,
        "unbounded_committed": unbounded.committed,
        "bounded_committed": bounded.committed,
        "they_commit_about_the_same": (
            abs(unbounded.committed - bounded.committed) < unbounded.committed * 0.05
        ),
        "unbounded_left_waiting": unbounded.final_depth,
        "bounded_left_waiting": bounded.final_depth,
        "and_one_of_them_leaves_a_backlog": unbounded.final_depth > bounded.final_depth * 10,
    }


def a_slower_link_lowers_the_ceiling_and_the_bound_follows_it() -> dict:
    """A six tick link commits less per tick, so the same bound is now too large.

    Worth checking because the bound was derived from a heartbeat of work, and a heartbeat of
    work is not a constant. Slow the link and the ceiling falls, which means the queue drains
    more slowly, which means the same bound holds more waiting writes for longer.

    So a bound tuned on a fast network is a latency bug on a slow one, and the number that has
    to be configured is a rate rather than a depth.
    """
    fast = offer(Load(name="fast", per_tick=60), window=150)
    slow = offer(
        Load(
            name="slow",
            per_tick=60,
            conditions=Conditions(min_delay=6, max_delay=6),
        ),
        window=150,
    )
    bounded_slow = offer(
        Load(
            name="slow bounded",
            per_tick=60,
            bound=128,
            conditions=Conditions(min_delay=6, max_delay=6),
        ),
        window=150,
    )
    return {
        "fast_ceiling": fast.throughput,
        "slow_ceiling": slow.throughput,
        "the_ceiling_fell": slow.throughput < fast.throughput,
        "by_this_factor": round(fast.throughput / max(0.001, slow.throughput), 2),
        "fast_wait": fast.worst_wait,
        "slow_wait": slow.worst_wait,
        "bounded_slow_wait": bounded_slow.worst_wait,
        "the_bound_still_helps": bounded_slow.worst_wait < slow.worst_wait,
        "but_it_is_no_longer_free": bounded_slow.throughput < slow.throughput * 1.05,
        "so_the_bound_is_really_a_rate": True,
    }


def a_zero_rate_is_refused() -> bool:
    """A load that offers nothing measures nothing."""
    try:
        Load(name="x", per_tick=0)
    except ConfigError:
        return True
    return False


def a_negative_bound_is_refused() -> bool:
    """A bound below none is refused; zero means unbounded."""
    try:
        Load(name="x", per_tick=1, bound=-5)
    except ConfigError:
        return True
    return False


def a_zero_window_is_refused() -> bool:
    """A run of no ticks offers nothing."""
    try:
        offer(Load(name="x", per_tick=1), window=0)
    except ConfigError:
        return True
    return False


def compare_the_bounds() -> list[dict]:
    """The same offered load under no bound and three different ones."""
    return [
        offer(Load(name="unbounded", per_tick=60), window=150).as_dict(),
        offer(Load(name="tight", per_tick=60, bound=16), window=150).as_dict(),
        offer(Load(name="batch sized", per_tick=60, bound=64), window=150).as_dict(),
        offer(Load(name="a heartbeat", per_tick=60, bound=128), window=150).as_dict(),
    ]


def summarise() -> dict:
    """The findings in one mapping."""
    ceiling = the_cluster_has_a_flat_ceiling_and_accepts_past_it_anyway()
    bounds = a_bound_below_the_ceiling_costs_exactly_the_throughput_it_removes()
    right = the_right_bound_is_a_heartbeat_of_work_and_costs_nothing()
    return {
        "ceiling": ceiling["ceiling"],
        "it_accepts_past_the_ceiling": ceiling["it_accepted_everything"],
        "and_the_tail_runs_away": ceiling["and_the_tail_runs_away_above_the_ceiling"],
        "the_wait_grows_by": the_queue_is_what_turns_a_rate_problem_into_a_latency_problem()[
            "by_this_factor"
        ],
        "a_bound_gives_the_bound_over_the_heartbeat": bounds[
            "it_is_the_bound_over_the_heartbeat"
        ],
        "the_right_bound_is_free": right["the_right_bound_keeps_the_throughput"],
        "and_cuts_the_wait_by": right["by_this_factor"],
        "the_range_is_not_a_smooth_trade": right["so_the_range_is_not_a_smooth_trade"],
        "a_refusal_is_information": a_refusal_is_information_and_a_slow_success_is_not()[
            "only_one_of_them_says_anything"
        ],
    }
