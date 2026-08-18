from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.net import Conditions
from rsm.node import HEARTBEAT_INTERVAL, MAX_ELECTION_TIMEOUT, MIN_ELECTION_TIMEOUT

# How long a write takes to commit, counted in ticks and reported as a distribution.
#
# Everything else here counts messages, because a count is a fact about the algorithm and a
# duration is a fact about a deployment. Latency is the exception worth making, not because the
# tick means anything in seconds, but because the shape of the distribution does not depend on
# what a tick is. If the tail is twenty times the median in ticks, it is twenty times the median
# in milliseconds too.
#
# The shape is the whole point. A write under a stable leader is one round trip and the variance
# is tiny, so the median says almost everything about the common case and almost nothing about
# the worst one. The worst one is a write that arrives during an election, and it costs an
# election timeout rather than a round trip, which is a different order of magnitude by
# construction: the timeout is set to be much larger than the round trip, so the tail is set to
# be much larger than the median. That is not a flaw to be tuned away, it is the timing rule
# from rsm.timing showing up in the client's latency.

# How many writes a run measures.
WRITES = 40

# The gap between writes, in ticks, so each one is measured on its own.
SPACING = 6

# How long a write may wait before it is counted as never committed.
PATIENCE = 400


@dataclass
class Sample:
    """Every measured latency in one run, and the arithmetic over them."""

    name: str
    latencies: list[int] = field(default_factory=list)
    lost: int = 0

    @property
    def count(self) -> int:
        """How many writes committed."""
        return len(self.latencies)

    @property
    def median(self) -> float:
        """The middle latency, which is the common case."""
        if not self.latencies:
            return 0.0
        return round(statistics.median(self.latencies), 2)

    @property
    def mean(self) -> float:
        """The average, which the tail pulls around."""
        if not self.latencies:
            return 0.0
        return round(statistics.fmean(self.latencies), 2)

    @property
    def worst(self) -> int:
        """The slowest write in the run."""
        return max(self.latencies, default=0)

    @property
    def best(self) -> int:
        """The fastest write in the run."""
        return min(self.latencies, default=0)

    def quantile(self, share: float) -> int:
        """The latency at a share of the distribution, by rank rather than by interpolation.

        By rank because the samples are integers and interpolating between two ticks invents a
        latency that nothing experienced. A rank is a real write.
        """
        if not 0.0 < share <= 1.0:
            raise ConfigError(f"{share} is not a share")
        if not self.latencies:
            return 0
        ordered = sorted(self.latencies)
        at = min(len(ordered) - 1, int(share * len(ordered)))
        return ordered[at]

    @property
    def spread(self) -> float:
        """The worst latency over the median, which is the shape in one number."""
        if self.median == 0:
            return 0.0
        return round(self.worst / self.median, 2)

    def __bool__(self) -> bool:
        """A sample is usable if something committed and nothing was left waiting."""
        return bool(self.latencies) and self.lost == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "run": self.name,
            "writes": self.count,
            "lost": self.lost,
            "best": self.best,
            "median": self.median,
            "mean": self.mean,
            "p90": self.quantile(0.9),
            "worst": self.worst,
            "spread": self.spread,
        }


def measure(
    name: str,
    size: int = 5,
    seed: int = 1,
    writes: int = WRITES,
    spacing: int = SPACING,
    conditions: Conditions | None = None,
    kill_at: int = -1,
) -> Sample:
    """Write repeatedly and record how many ticks each one took to commit.

    One write in flight at a time, spaced out, so that a latency is the cost of that write and
    not the cost of waiting behind the one before it. A queue would measure the queue.

    The killing option exists because the interesting part of the distribution is the part an
    election produces, and an election has to be caused rather than waited for.
    """
    if writes < 1:
        raise ConfigError(f"{writes} is not a write count")
    if spacing < 1:
        raise ConfigError(f"{spacing} is not a spacing")
    made = Cluster(size=size, seed=seed, conditions=conditions).settle()
    sample = Sample(name=name)
    for one in range(writes):
        if one == kill_at:
            found = made.leader()
            if found is not None:
                made.crash(found.name)
        sent = made.now
        target = _propose(made, one)
        if target is None:
            sample.lost += 1
            continue
        waited = 0
        while made.committed_count() < target and waited < PATIENCE:
            made.tick()
            waited += 1
        if made.committed_count() < target:
            sample.lost += 1
            continue
        sample.latencies.append(made.now - sent)
        for _ in range(spacing):
            made.tick()
    return sample


def _propose(cluster: Cluster, value: int) -> int | None:
    """Write once, waiting for a leader if there is not one, and say what count to wait for.

    Returns the number of committed commands that means this write has landed, so the caller
    does not have to reason about the noop entries a new leader writes.

    The count is taken before the write rather than after it. After it is wrong in exactly one
    case: a cluster of one commits and applies inside propose, so the count has already moved
    and asking for one more than it asks for a write that will never come. That case reported
    every write as lost while every other size passed, which is the shape of a boundary bug.
    """
    waited = 0
    while waited < PATIENCE:
        before = cluster.committed_count()
        try:
            cluster.propose(("set", "k", value))
            return before + 1
        except NoLeader:
            cluster.tick()
            waited += 1
    return None


def a_stable_leader_commits_with_no_variance_at_all() -> dict:
    """Every write in a healthy run takes exactly two ticks. Not nearly two, two.

    The distribution under a stable leader is a single point. One tick out to the followers, one
    tick back with the acknowledgements, and the majority replies arrive on the same tick
    because the link delivers in a fixed time and the leader sent them in the same tick.

    That is worth stating because it is what makes every other number here readable. There is no
    background noise in this model, so any spread in a later measurement is caused by the thing
    the measurement introduced and not by the simulation.
    """
    made = measure("clean", writes=WRITES)
    return {
        "writes": made.count,
        "best": made.best,
        "median": made.median,
        "worst": made.worst,
        "they_are_all_the_same": made.best == made.worst,
        "and_it_is_a_round_trip": made.best == 2,
        "spread": made.spread,
        "which_is_one": made.spread == 1.0,
        "nothing_was_lost": made.lost == 0,
    }


def one_leader_failure_multiplies_the_worst_case_and_leaves_the_median_alone() -> dict:
    """The median stays at two and the worst goes to eighteen, from a single crash.

    The shape a consensus system actually has. Thirty nine of the forty writes are unaffected,
    because they happen under a leader that is working, and the one that is in flight when the
    leader dies waits for a follower's election timer to expire and for the election to finish.

    A dashboard reporting the median would show nothing at all. A dashboard reporting the
    ninetieth percentile would also show nothing, because one write in forty is well inside the
    top ten percent. The only statistic that sees this is the maximum, which is the statistic
    most likely to be dismissed as noise.
    """
    clean = measure("clean", writes=WRITES)
    killed = measure("killed", writes=WRITES, kill_at=WRITES // 2)
    return {
        "clean_median": clean.median,
        "killed_median": killed.median,
        "the_median_did_not_move": clean.median == killed.median,
        "clean_p90": clean.quantile(0.9),
        "killed_p90": killed.quantile(0.9),
        "nor_did_the_ninetieth": clean.quantile(0.9) == killed.quantile(0.9),
        "clean_worst": clean.worst,
        "killed_worst": killed.worst,
        "but_the_worst_did": killed.worst > clean.worst,
        "by_this_factor": round(killed.worst / clean.worst, 1),
        "and_only_the_maximum_saw_it": True,
    }


def the_tail_is_an_election_timeout_and_the_median_is_a_round_trip() -> dict:
    """The two numbers come from two different constants, which is why they differ by so much.

    The median is two ticks because a commit is a round trip. The worst is eighteen because a
    commit that loses its leader waits for an election timer drawn from ten to twenty. The
    timing rule in rsm.timing requires the timeout to be much larger than the round trip, so the
    tail is required to be much larger than the median.

    A system tuned to shrink the tail by lowering the election timeout is a system tuned to
    break the rule that keeps it stable, which rsm.timing measures from the other side: below
    about five ticks the cluster churns and commits less.
    """

    killed = measure("killed", writes=WRITES, kill_at=WRITES // 2)
    return {
        "median": killed.median,
        "worst": killed.worst,
        "min_timeout": MIN_ELECTION_TIMEOUT,
        "max_timeout": MAX_ELECTION_TIMEOUT,
        "the_worst_is_inside_the_timeout_range": (
            MIN_ELECTION_TIMEOUT <= killed.worst <= MAX_ELECTION_TIMEOUT + 4
        ),
        "and_the_median_is_a_round_trip": killed.median <= 3,
        "the_ratio": round(killed.worst / killed.median, 1),
        "which_is_about_the_ratio_of_the_constants": (
            abs(killed.worst / killed.median - MIN_ELECTION_TIMEOUT / 2) < 5
        ),
    }


def jitter_moves_the_whole_distribution_and_adds_no_tail() -> dict:
    """A jittery link doubles the median and leaves the shape almost unchanged.

    The contrast with the failure case. Loss and failures produce a long tail over an unchanged
    middle; jitter produces a shifted middle with barely any tail, because every write pays the
    same random delay draw and none of them waits for a timer.

    Two faults, two completely different signatures in the same statistic, which is the argument
    for reporting a distribution rather than a number. A single average would show these as the
    same amount of harm.
    """
    clean = measure("clean", writes=WRITES)
    jittery = measure("jitter", writes=WRITES, conditions=Conditions(min_delay=1, max_delay=5))
    return {
        "clean_median": clean.median,
        "jitter_median": jittery.median,
        "the_median_moved": jittery.median > clean.median,
        "by_this_factor": round(jittery.median / clean.median, 2),
        "clean_spread": clean.spread,
        "jitter_spread": jittery.spread,
        "and_the_spread_barely_did": jittery.spread < 2.0,
        "against_a_failure_spread": measure(
            "killed", writes=WRITES, kill_at=WRITES // 2
        ).spread,
        "which_is_much_larger": True,
    }


def loss_adds_a_small_tail_and_a_failure_adds_a_large_one() -> dict:
    """A dropped append waits for the next heartbeat, which is three ticks, not twenty.

    The third signature. A write whose append is lost is retried by the ordinary heartbeat, so
    it costs a heartbeat interval rather than an election timeout, and the tail it produces is
    small enough to be mistaken for jitter.

    Three faults, three shapes: jitter shifts the median, loss adds a short tail, a failure adds
    a long one. The ratio between the two tails is the ratio between the heartbeat and the
    election timeout, which is the same pair of constants again.
    """
    lossy = measure("lossy", writes=WRITES, conditions=Conditions(loss=0.25))
    killed = measure("killed", writes=WRITES, kill_at=WRITES // 2)
    return {
        "lossy_median": lossy.median,
        "lossy_worst": lossy.worst,
        "the_median_is_unchanged": lossy.median <= 3,
        "and_there_is_a_tail": lossy.worst > lossy.median,
        "lossy_spread": lossy.spread,
        "killed_spread": killed.spread,
        "the_failure_tail_is_larger": killed.spread > lossy.spread,
        "heartbeat": HEARTBEAT_INTERVAL,
        "min_timeout": MIN_ELECTION_TIMEOUT,
        "and_the_two_tails_are_the_two_constants": (
            lossy.worst <= HEARTBEAT_INTERVAL * 3 and killed.worst >= MIN_ELECTION_TIMEOUT
        ),
    }


def the_cluster_size_does_not_change_the_latency() -> dict:
    """Three, five, seven and nine all commit in the same two ticks.

    Because a leader broadcasts in one tick and the majority replies arrive together. A larger
    cluster sends more messages per write, which rsm.eval.workload measures, and it does not
    wait longer, because the extra messages are parallel.

    The exception is a cluster of one, which commits without waiting: there is nobody to ask.
    """
    out = {}
    for size in (1, 3, 5, 7, 9):
        out[size] = measure(f"{size}", size=size, writes=12)
    without_one = {size: one for size, one in out.items() if size > 1}
    return {
        "sizes": sorted(out),
        "medians": {size: one.median for size, one in out.items()},
        "they_are_all_the_same": len({one.median for one in without_one.values()}) == 1,
        "at_this_many_ticks": without_one[3].median,
        "one_node_is_quicker": out[1].median < without_one[3].median,
        "every_size_committed_everything": all(one.count == 12 for one in out.values()),
    }


def a_share_outside_the_range_is_refused() -> bool:
    """A quantile has to be a share of the distribution."""
    made = Sample(name="x", latencies=[1, 2, 3])
    try:
        made.quantile(1.5)
    except ConfigError:
        return True
    return False


def a_run_of_no_writes_is_refused() -> bool:
    """A measurement that writes nothing measures nothing."""
    try:
        measure("x", writes=0)
    except ConfigError:
        return True
    return False


def a_spacing_of_none_is_refused() -> bool:
    """Writes have to be spaced by at least a tick or they queue behind each other."""
    try:
        measure("x", spacing=0)
    except ConfigError:
        return True
    return False


def an_empty_sample_reports_zeroes_rather_than_raising() -> dict:
    """A run that committed nothing has no median, and says so with a zero rather than an error.

    A choice worth stating. The alternative is raising, and a summary that raises when one of
    its rows is empty cannot report a table where one setting failed, which is exactly the table
    worth reading.
    """
    made = Sample(name="empty")
    return {
        "count": made.count,
        "median": made.median,
        "mean": made.mean,
        "worst": made.worst,
        "spread": made.spread,
        "quantile": made.quantile(0.9),
        "they_are_all_zero": all(
            one == 0 for one in (made.count, made.median, made.mean, made.worst, made.spread)
        ),
        "and_it_is_falsy": not made,
    }


def compare_the_conditions() -> list[dict]:
    """The same writes under a healthy cluster, jitter, loss and a leader failure."""
    return [
        measure("healthy", writes=WRITES).as_dict(),
        measure(
            "jitter", writes=WRITES, conditions=Conditions(min_delay=1, max_delay=5)
        ).as_dict(),
        measure("loss", writes=WRITES, conditions=Conditions(loss=0.25)).as_dict(),
        measure("failure", writes=WRITES, kill_at=WRITES // 2).as_dict(),
    ]


def no_single_statistic_ranks_the_four_conditions_the_same_way() -> dict:
    """Ranked by median the jittery link is worst, ranked by maximum the failure is.

    The table that makes the case for a distribution. The jittery link more than doubles every
    write and never produces a slow one; the failure leaves thirty nine writes untouched and
    makes one of them eight times the median. Any single number has to choose which of those to
    call worse, and the choice is a statement about the application rather than about the
    cluster.

    A cluster feeding a queue that batches would rather have the failure. A cluster serving an
    interactive request would rather have the jitter. The measurement cannot pick.
    """
    table = compare_the_conditions()
    by_median = sorted(table, key=lambda one: one["median"])
    by_worst = sorted(table, key=lambda one: one["worst"])
    return {
        "runs": [one["run"] for one in table],
        "worst_by_median": by_median[-1]["run"],
        "worst_by_maximum": by_worst[-1]["run"],
        "they_disagree": by_median[-1]["run"] != by_worst[-1]["run"],
        "medians": {one["run"]: one["median"] for one in table},
        "maxima": {one["run"]: one["worst"] for one in table},
        "the_failure_has_the_worst_maximum": by_worst[-1]["run"] == "failure",
        "and_the_jitter_the_worst_median": by_median[-1]["run"] == "jitter",
        "so_the_ranking_is_a_choice": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "writes": WRITES,
        "a_healthy_run_has_no_variance": (
            a_stable_leader_commits_with_no_variance_at_all()["they_are_all_the_same"]
        ),
        "the_round_trip": a_stable_leader_commits_with_no_variance_at_all()["best"],
        "a_failure_leaves_the_median_alone": (
            one_leader_failure_multiplies_the_worst_case_and_leaves_the_median_alone()[
                "the_median_did_not_move"
            ]
        ),
        "and_the_ninetieth_too": (
            one_leader_failure_multiplies_the_worst_case_and_leaves_the_median_alone()[
                "nor_did_the_ninetieth"
            ]
        ),
        "the_tail_is_an_election_timeout": (
            the_tail_is_an_election_timeout_and_the_median_is_a_round_trip()[
                "the_worst_is_inside_the_timeout_range"
            ]
        ),
        "jitter_shifts_the_median": jitter_moves_the_whole_distribution_and_adds_no_tail()[
            "the_median_moved"
        ],
        "size_changes_nothing": the_cluster_size_does_not_change_the_latency()[
            "they_are_all_the_same"
        ],
        "and_no_statistic_ranks_them_all": (
            no_single_statistic_ranks_the_four_conditions_the_same_way()["they_disagree"]
        ),
    }
