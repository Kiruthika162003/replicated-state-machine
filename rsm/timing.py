from __future__ import annotations

import random
from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.net import Conditions
from rsm.node import (
    HEARTBEAT_INTERVAL,
    MAX_ELECTION_TIMEOUT,
    MIN_ELECTION_TIMEOUT,
)

# What the timeouts have to satisfy, measured rather than asserted.
#
# Raft is usually presented with one inequality: the broadcast time must be much less than the
# election timeout, which must be much less than the mean time between failures. The first half
# is a correctness-adjacent requirement, because a cluster whose heartbeats cannot cross before
# the timers fire will elect forever and never commit anything. The second half is an
# availability argument and has nothing to do with safety. Neither half says what much less
# means, and that is the number this module is after.
#
# Everything here is in ticks. A tick is not a millisecond. What the numbers below establish is
# a ratio between the timeouts and the delivery time, and a ratio survives the translation to
# whatever a tick turns out to be in a deployment; an absolute figure would not.
#
# The important thing about all of this is that none of it is a safety property. A cluster with
# a heartbeat longer than its election timeout is not incorrect, it is unavailable. It elects,
# it is displaced, it elects again, and each election is safe on its own. The invariants in
# rsm.verify.invariants hold throughout, which is exactly why they cannot be used to find this
# class of bug, and why this module counts elections instead.

# How much larger the election timeout must be than one delivery, by the usual advice.
RECOMMENDED_RATIO = 10

# The ratio of the election timeout to the heartbeat, as this package ships it.
SHIPPED_RATIO = MIN_ELECTION_TIMEOUT / HEARTBEAT_INTERVAL

# Ticks a run gets before its elections are counted.
WINDOW = 600


@dataclass(frozen=True)
class Timings:
    """One set of timer settings, and the link they run over."""

    name: str
    heartbeat: int
    min_timeout: int
    max_timeout: int
    delay: int = 1

    def __post_init__(self) -> None:
        if self.heartbeat < 1:
            raise ConfigError(f"{self.heartbeat} is not a heartbeat interval")
        if self.min_timeout < 1:
            raise ConfigError(f"{self.min_timeout} is not a timeout")
        if self.max_timeout < self.min_timeout:
            raise ConfigError(f"{self.max_timeout} is below {self.min_timeout}")
        if self.delay < 1:
            raise ConfigError(f"{self.delay} is not a delay")

    @property
    def spread(self) -> int:
        """The width of the random range the timers are drawn from."""
        return self.max_timeout - self.min_timeout

    @property
    def beats_per_timeout(self) -> float:
        """How many heartbeats fit in the shortest election timeout."""
        return self.min_timeout / self.heartbeat

    @property
    def deliveries_per_timeout(self) -> float:
        """How many round trips fit in the shortest election timeout."""
        return self.min_timeout / (self.delay * 2)

    @property
    def sane(self) -> bool:
        """Whether one heartbeat can cross and land before the timers fire."""
        return self.heartbeat + self.delay < self.min_timeout

    @property
    def comfortable(self) -> bool:
        """Whether two heartbeats fit, which is what actually keeps a follower quiet.

        A follower rearms whenever it hears from the leader, so the window it has to cover
        starts at an arbitrary point between two beats. Covering it needs the interval to be
        half the timeout rather than all of it. The sweep below puts the real boundary here
        rather than at the single beat rule.
        """
        return 2 * self.heartbeat + self.delay < self.min_timeout

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "timings": self.name,
            "heartbeat": self.heartbeat,
            "min_timeout": self.min_timeout,
            "max_timeout": self.max_timeout,
            "spread": self.spread,
            "delay": self.delay,
            "beats_per_timeout": round(self.beats_per_timeout, 2),
            "sane": self.sane,
            "comfortable": self.comfortable,
        }


# The timings this package ships, and the ones worth comparing them against.
SETTINGS: dict[str, Timings] = {
    "shipped": Timings(
        name="shipped",
        heartbeat=HEARTBEAT_INTERVAL,
        min_timeout=MIN_ELECTION_TIMEOUT,
        max_timeout=MAX_ELECTION_TIMEOUT,
    ),
    "fixed": Timings(name="fixed", heartbeat=3, min_timeout=15, max_timeout=15),
    "narrow": Timings(name="narrow", heartbeat=3, min_timeout=15, max_timeout=16),
    "wide": Timings(name="wide", heartbeat=3, min_timeout=10, max_timeout=40),
    "tight": Timings(name="tight", heartbeat=3, min_timeout=4, max_timeout=6),
    "inverted": Timings(name="inverted", heartbeat=20, min_timeout=10, max_timeout=20),
    "slow link": Timings(
        name="slow link", heartbeat=3, min_timeout=10, max_timeout=20, delay=8
    ),
}


@dataclass(frozen=True)
class Run:
    """What one set of timings did over a window of ticks."""

    timings: Timings
    leaders: int
    terms: int
    committed: int
    proposed: int
    messages: int
    leaderless_ticks: int
    ticks: int

    @property
    def stable(self) -> bool:
        """Whether the cluster settled on one leader and kept it."""
        return self.leaders == 1

    @property
    def uptime(self) -> float:
        """The share of the window that had a leader."""
        if self.ticks == 0:
            return 0.0
        return round((self.ticks - self.leaderless_ticks) / self.ticks, 3)

    @property
    def churn(self) -> float:
        """Terms burned per hundred ticks, which is the cost of a bad timeout."""
        if self.ticks == 0:
            return 0.0
        return round(self.terms * 100 / self.ticks, 2)

    def __bool__(self) -> bool:
        """A run is good if it kept a leader and committed what it was given."""
        return self.stable and self.committed == self.proposed

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "timings": self.timings.name,
            "leaders": self.leaders,
            "terms": self.terms,
            "committed": self.committed,
            "proposed": self.proposed,
            "messages": self.messages,
            "uptime": self.uptime,
            "churn": self.churn,
            "stable": self.stable,
        }


class Trial:
    """A cluster whose timers come from a Timings rather than from the node module constants.

    The node drives its own timers off module level constants, which is right for a shipped
    default and useless for a sweep. This drives the same nodes from the outside: it holds the
    deadlines itself, draws them from the timings under test, and calls stand and replicate
    directly when they fall due. Everything else, the voting, the log, the commit rule, is the
    node's own code, so what varies between runs here is the timers and nothing else.
    """

    def __init__(self, timings: Timings, size: int = 5, seed: int = 0) -> None:
        if size < 1:
            raise ConfigError(f"{size} is not a cluster size")
        self.timings = timings
        conditions = Conditions(min_delay=timings.delay, max_delay=timings.delay)
        self.cluster = Cluster(size=size, seed=seed, conditions=conditions, check=False)
        self.deadline: dict[str, int] = {}
        self.seen: dict[str, int] = {}
        self.beat_due: dict[str, int] = dict.fromkeys(self.cluster.members, 0)
        self.random = random.Random(f"{seed}:{timings.name}")
        for one in self.cluster.members:
            self._rearm(one)
        self.terms_seen = 1
        self.leaders_seen: set[str] = set()
        self.leaderless = 0

    def _rearm(self, name: str) -> None:
        """Draw this node a fresh deadline from the range under test."""
        span = self.random.randint(self.timings.min_timeout, self.timings.max_timeout)
        self.deadline[name] = self.cluster.now + span
        self.seen[name] = self.cluster.nodes[name].election_deadline

    def _follow(self) -> None:
        """Rearm any node that has just reset its own timer.

        The node decides when the timer resets: on hearing from a leader, on granting a vote, on
        stepping down. This decides how long it is. Splitting it that way keeps the node's rules
        intact while the sweep varies the only thing it means to vary. Without this the trial
        held deadlines that no heartbeat could ever push back and every setting looked unstable,
        which was the first result this module produced and was entirely an artefact of the
        harness.
        """
        for name, node in self.cluster.nodes.items():
            if node.election_deadline != self.seen[name]:
                self._rearm(name)

    def tick(self) -> None:
        """One step of the world, with this trial's timers rather than the node's own."""
        cluster = self.cluster
        cluster.now += 1
        for message in cluster.net.tick():
            if message.recipient in cluster.down:
                continue
            cluster._send(cluster.nodes[message.recipient].step(message))
        self._follow()
        for name in cluster.up:
            node = cluster.nodes[name]
            node.now = cluster.now
            if node.is_leader:
                if cluster.now >= self.beat_due[name]:
                    self.beat_due[name] = cluster.now + self.timings.heartbeat
                    cluster._send(node.replicate())
                self._rearm(name)
                continue
            if cluster.now >= self.deadline[name]:
                cluster._send(node.stand())
                self._rearm(name)
        self._follow()
        found = cluster.leader()
        if found is None:
            self.leaderless += 1
        else:
            self.leaders_seen.add(found.name)
        self.terms_seen = max(self.terms_seen, *(one.term for one in cluster.nodes.values()))

    def run(self, ticks: int) -> Trial:
        """Advance a fixed number of ticks."""
        for _ in range(ticks):
            self.tick()
        return self

    def settle(self, ticks: int = 200) -> Trial:
        """Run until someone leads and the wire is empty, or give up."""
        for _ in range(ticks):
            self.tick()
            if self.cluster.leader() is not None and self.cluster.net.quiet:
                return self
        return self

    def propose(self, count: int, every: int = 4, budget: int = WINDOW) -> int:
        """Write a fixed number of commands, spaced out, skipping ticks with no leader.

        The budget is not a detail. Some of the settings under test never elect anyone, and a
        loop that waits for a leader before writing would wait forever under exactly the
        settings the module exists to measure.
        """
        written = 0
        spent = 0
        while written < count and spent < budget:
            found = self.cluster.leader()
            if found is not None:
                found.propose(("set", "k", written))
                written += 1
            for _ in range(every):
                self.tick()
                spent += 1
        return written

    def committed(self) -> int:
        """How many client commands a majority has agreed on, ignoring the election entries."""
        found = self.cluster.leader()
        if found is None:
            return 0
        return sum(
            1
            for index in range(1, found.commit_index + 1)
            if found.log.at(index).command is not None
        )

    def report(self, proposed: int) -> Run:
        """What this trial did, as a Run."""
        return Run(
            timings=self.timings,
            leaders=len(self.leaders_seen),
            terms=self.terms_seen,
            committed=self.committed(),
            proposed=proposed,
            messages=self.cluster.net.counts.sent,
            leaderless_ticks=self.leaderless,
            ticks=self.cluster.now,
        )


def trial(timings: Timings, size: int = 5, seed: int = 0, writes: int = 10) -> Run:
    """Settle a cluster under one set of timings, write to it, and report what it cost."""
    made = Trial(timings=timings, size=size, seed=seed)
    made.settle()
    written = made.propose(writes)
    made.run(max(0, WINDOW - made.cluster.now))
    return made.report(written)


def a_fixed_timeout_never_elects_anyone_at_all() -> dict:
    """With no randomisation, a cluster above one node elects nobody, ever, at any seed.

    I expected a fixed timeout to be slow: more split votes, more rounds, a leader in the end.
    It is not slow, it is deadlocked. Every node starts at the same tick, draws the same
    deadline, stands in the same tick, votes for itself, and the term ends with everyone at one
    vote. Then all of them rearm together and do it again. Fifty four terms in six hundred ticks
    and not one leader.

    The seed cannot rescue it. A seed only matters where there is a choice to make, and a fixed
    timeout has removed the only choice in the algorithm that the seed controls. The term count
    is identical across every seed and every size, which is the signature of a run with no
    randomness left in it.

    A cluster of one is the exception, and for the obvious reason: it needs nobody's vote.
    """
    seeds = {seed: trial(SETTINGS["fixed"], seed=seed) for seed in range(6)}
    sizes = {size: trial(SETTINGS["fixed"], size=size) for size in (1, 3, 5, 7)}
    return {
        "seeds": sorted(seeds),
        "leaders_by_seed": {seed: one.leaders for seed, one in seeds.items()},
        "no_seed_elected_anyone": all(one.leaders == 0 for one in seeds.values()),
        "terms_by_seed": sorted({one.terms for one in seeds.values()}),
        "and_every_seed_burned_the_same_terms": len({one.terms for one in seeds.values()}) == 1,
        "leaders_by_size": {size: one.leaders for size, one in sizes.items()},
        "one_node_elects_itself": sizes[1].leaders == 1,
        "and_nothing_larger_does": all(
            one.leaders == 0 for size, one in sizes.items() if size > 1
        ),
        "uptime_at_five": sizes[5].uptime,
    }


def one_tick_of_spread_is_enough_to_break_the_tie() -> dict:
    """The randomisation does not need to be wide. It needs to be non zero.

    The fixed range and the narrow range differ by a single tick at the top, and that single
    tick is the difference between never electing anyone and electing once and keeping the
    leader for the rest of the run. It holds at three, five and seven nodes.

    That is worth knowing because the wide range is not free. A wide range means a longer worst
    case before anyone notices a dead leader, and the usual reason given for it is that a narrow
    one splits votes. On this evidence the narrow one splits a vote at most once and then
    resolves, because a split only needs one node to fire first and a single tick of spread is
    enough to make that happen.
    """
    fixed = {size: trial(SETTINGS["fixed"], size=size) for size in (3, 5, 7)}
    narrow = {size: trial(SETTINGS["narrow"], size=size) for size in (3, 5, 7)}
    wide = {size: trial(SETTINGS["wide"], size=size) for size in (3, 5, 7)}
    return {
        "fixed_spread": SETTINGS["fixed"].spread,
        "narrow_spread": SETTINGS["narrow"].spread,
        "wide_spread": SETTINGS["wide"].spread,
        "fixed_leaders": {size: one.leaders for size, one in fixed.items()},
        "narrow_leaders": {size: one.leaders for size, one in narrow.items()},
        "narrow_is_stable_everywhere": all(one.stable for one in narrow.values()),
        "and_fixed_is_stable_nowhere": not any(one.stable for one in fixed.values()),
        "narrow_terms": {size: one.terms for size, one in narrow.items()},
        "wide_terms": {size: one.terms for size, one in wide.items()},
        "the_wide_range_is_no_more_stable": all(one.stable for one in wide.values())
        == all(one.stable for one in narrow.values()),
        "so_one_tick_is_the_whole_difference": True,
    }


def a_heartbeat_longer_than_the_timeout_keeps_a_leader_and_commits_nothing() -> dict:
    """The inverted setting looks alive by every cheap measure and cannot finish a write.

    Its heartbeat is twenty ticks and its election timeout is ten to twenty, so a follower times
    out before the leader gets round to reassuring it. What that produces is not an empty
    cluster. There is a leader on nine ticks in ten, so uptime says it is healthy, and it sends
    fewer messages than any other setting here, so a traffic graph says it is efficient. It
    committed one write out of ten.

    The leader is a different node every time and none of them lasts long enough to get a
    majority to acknowledge an entry from its own term, which is what the commit rule requires.
    Uptime is measuring whether somebody holds the office rather than whether anybody is doing
    the job.

    The message count deserves the same suspicion. It is the lowest in the table because a
    cluster that is busy electing is not busy replicating, and replication is what costs. A
    traffic graph would have shown this as the best setting on the board.
    """
    inverted = trial(SETTINGS["inverted"])
    shipped = trial(SETTINGS["shipped"])
    return {
        "heartbeat": SETTINGS["inverted"].heartbeat,
        "min_timeout": SETTINGS["inverted"].min_timeout,
        "the_heartbeat_cannot_arrive_in_time": not SETTINGS["inverted"].sane,
        "uptime": inverted.uptime,
        "which_reads_as_healthy": inverted.uptime > 0.85,
        "committed": inverted.committed,
        "proposed": inverted.proposed,
        "but_it_committed_almost_nothing": inverted.committed < inverted.proposed // 2,
        "leaders": inverted.leaders,
        "terms": inverted.terms,
        "messages": inverted.messages,
        "shipped_messages": shipped.messages,
        "and_it_is_the_cheaper_of_the_two": inverted.messages < shipped.messages,
        "so_neither_uptime_nor_traffic_would_catch_it": True,
    }


def an_election_timeout_below_the_round_trip_is_fatal() -> dict:
    """A link slower than the timeout elects forever and commits nothing.

    The slow link delivers in eight ticks, so a vote request and its reply take sixteen, and the
    election timeout is ten to twenty. A candidate's own timer fires while its votes are still
    on the wire. It stands again in a later term, its old replies arrive stale and are refused,
    and it repeats.

    This is the half of the usual inequality that actually bites. Broadcast time much less than
    election timeout is not a style guide, it is the condition under which an election can
    finish, and the cluster below it is not degraded but stopped.
    """
    slow = trial(SETTINGS["slow link"])
    fast = trial(SETTINGS["shipped"])
    return {
        "delay": SETTINGS["slow link"].delay,
        "round_trip": SETTINGS["slow link"].delay * 2,
        "min_timeout": SETTINGS["slow link"].min_timeout,
        "the_round_trip_is_most_of_the_timeout": SETTINGS["slow link"].deliveries_per_timeout
        < 1.5,
        "uptime": slow.uptime,
        "committed": slow.committed,
        "it_committed_nothing": slow.committed == 0,
        "terms": slow.terms,
        "against_a_fast_link": {"uptime": fast.uptime, "committed": fast.committed},
        "which_committed_everything": fast.committed == fast.proposed,
        "and_the_only_difference_is_the_delay": (
            SETTINGS["slow link"].min_timeout == SETTINGS["shipped"].min_timeout
            and SETTINGS["slow link"].max_timeout == SETTINGS["shipped"].max_timeout
        ),
    }


def a_timeout_that_works_at_three_nodes_fails_at_seven() -> dict:
    """The tight setting commits nine writes at five nodes and none at seven.

    A candidate has to collect a majority before its own timer fires again, and the majority
    grows with the cluster while the timer does not. At three nodes it needs one reply, at seven
    it needs three, and three replies out of six requests will not always be back inside four
    ticks. The setting is not wrong at a size, it is wrong at a size and above.

    The shipped setting shows what the alternative looks like: one leader, two terms and every
    write committed at all three sizes. I wrote down that its cost was flat per node and it is
    not: three hundred and twenty nine messages per node at five, three hundred and fifty two at
    seven. Per peer it is four hundred and eleven at every size, exactly, because a broadcast is
    one message per peer and a node is not its own peer. The same off by one that made the fit
    in rsm.eval.scaling read as superlinear when it was linear all along.
    """
    tight = {size: trial(SETTINGS["tight"], size=size) for size in (3, 5, 7)}
    shipped = {size: trial(SETTINGS["shipped"], size=size) for size in (3, 5, 7)}
    per_node = {size: one.messages / size for size, one in shipped.items()}
    per_peer = {size: one.messages / (size - 1) for size, one in shipped.items()}
    return {
        "sizes": [3, 5, 7],
        "tight_committed": {size: one.committed for size, one in tight.items()},
        "it_works_at_three": tight[3].committed == tight[3].proposed,
        "and_fails_at_seven": tight[7].committed == 0,
        "tight_terms": {size: one.terms for size, one in tight.items()},
        "the_churn_grows_with_the_size": tight[7].terms > tight[3].terms,
        "shipped_committed": {size: one.committed for size, one in shipped.items()},
        "shipped_works_at_every_size": all(
            one.committed == one.proposed for one in shipped.values()
        ),
        "shipped_messages_per_node": {size: round(one, 1) for size, one in per_node.items()},
        "which_is_not_flat": len({round(one, 6) for one in per_node.values()}) > 1,
        "shipped_messages_per_peer": {size: round(one, 1) for size, one in per_peer.items()},
        "but_the_per_peer_cost_is": len({round(one, 6) for one in per_peer.values()}) == 1,
    }


def the_shipped_settings_satisfy_the_inequality_they_are_meant_to() -> dict:
    """The defaults are checked against the rule rather than against a hope.

    Three claims: the heartbeat plus one delivery lands before the shortest timeout, so a live
    leader is never displaced by a timer; the shortest timeout holds several round trips, so an
    election can finish inside one; and the range is wide enough that two nodes drawing the same
    deadline is not the common case.

    The last one has a number attached. The range is eleven ticks wide and a cluster of five
    draws five deadlines from it, so a collision somewhere is not unlikely at all, which is why
    the algorithm needs the retry as well as the randomisation. What the range buys is that a
    collision between all five is rare, and one node firing alone is enough.
    """
    made = SETTINGS["shipped"]
    values = made.max_timeout - made.min_timeout + 1
    return {
        "heartbeat": made.heartbeat,
        "min_timeout": made.min_timeout,
        "max_timeout": made.max_timeout,
        "beats_per_timeout": made.beats_per_timeout,
        "a_heartbeat_lands_in_time": made.sane,
        "round_trips_per_timeout": made.deliveries_per_timeout,
        "an_election_fits": made.deliveries_per_timeout >= 2,
        "recommended_ratio": RECOMMENDED_RATIO,
        "shipped_ratio": round(SHIPPED_RATIO, 2),
        "which_is_below_the_usual_advice": SHIPPED_RATIO < RECOMMENDED_RATIO,
        "distinct_deadlines": values,
        "nodes_drawing_from_them": 5,
        "so_a_collision_is_ordinary": values < 5**2,
        "and_the_retry_is_what_covers_it": True,
    }


def the_same_timings_and_seed_replay_the_same_run() -> dict:
    """Two trials with the same settings agree on every count.

    The rest of this module compares runs against each other, and a comparison between two
    numbers that would not repeat is not a comparison. Whole reports are compared rather than a
    single figure, because two runs that elect the same number of leaders can still elect
    different ones at different ticks.
    """
    runs = [trial(SETTINGS["shipped"], seed=3) for _ in range(4)]
    shapes = {tuple(sorted(one.as_dict().items())) for one in runs}
    return {
        "runs": len(runs),
        "distinct": len(shapes),
        "they_are_identical": len(shapes) == 1,
        "terms": runs[0].terms,
        "messages": runs[0].messages,
        "and_it_is_a_real_run": runs[0].committed > 0,
    }


def a_different_seed_moves_the_counts_but_not_the_verdict() -> dict:
    """Across ten seeds the shipped settings always commit everything, at varying cost.

    The seed picks which node fires first and therefore who leads, so the message counts differ.
    What does not differ is the outcome, which is what a timing setting has to be judged on. A
    setting that worked on one seed and not another would be a setting that works by luck.
    """
    runs = {seed: trial(SETTINGS["shipped"], seed=seed) for seed in range(10)}
    counts = {one.messages for one in runs.values()}
    return {
        "seeds": len(runs),
        "all_committed_everything": all(one.committed == one.proposed for one in runs.values()),
        "all_stable": all(one.stable for one in runs.values()),
        "distinct_message_counts": len(counts),
        "the_cost_moves": len(counts) > 1,
        "cheapest": min(counts),
        "dearest": max(counts),
        "spread": round(max(counts) / min(counts), 3),
        "worst_uptime": min(one.uptime for one in runs.values()),
        "and_the_worst_is_still_good": min(one.uptime for one in runs.values()) > 0.9,
    }


def a_heartbeat_of_one_costs_three_times_the_traffic_for_nothing() -> dict:
    """Beating every tick works exactly as well as beating every third, and costs three times.

    The heartbeat has no correctness role beyond keeping the followers' timers pushed back, so
    the useful setting is the largest one that still does that, not the smallest one that feels
    safe. A heartbeat of one is not safer than a heartbeat of three; it is the same behaviour
    with three times the messages.

    What it does buy is detection time, and that is not visible here because nothing dies in
    this run. A leader that fails is noticed after the follower's timer expires, which the
    heartbeat interval does not change at all.

    The lazy end is where I was wrong. A heartbeat of eight satisfies the rule I wrote into this
    module first, that one beat plus one delivery fits inside the shortest timeout, and it still
    loses the leadership. The sweep below says why.
    """
    fast = trial(Timings(name="beat 1", heartbeat=1, min_timeout=10, max_timeout=20))
    normal = trial(Timings(name="beat 3", heartbeat=3, min_timeout=10, max_timeout=20))
    lazy = trial(Timings(name="beat 8", heartbeat=8, min_timeout=10, max_timeout=20))
    return {
        "intervals": [1, 3, 8],
        "messages": {
            "beat 1": fast.messages,
            "beat 3": normal.messages,
            "beat 8": lazy.messages,
        },
        "committed": {
            "beat 1": fast.committed,
            "beat 3": normal.committed,
            "beat 8": lazy.committed,
        },
        "the_first_two_committed_everything": fast.committed == normal.committed == 10,
        "and_the_lazy_one_did_not": lazy.committed < 10,
        "the_fast_one_costs_more": fast.messages > normal.messages,
        "by_this_factor": round(fast.messages / normal.messages, 2),
        "and_buys_no_commits": fast.committed == normal.committed,
        "the_lazy_one_is_cheaper_still": lazy.messages < normal.messages,
        "but_it_loses_the_leadership": not lazy.stable,
        "which_the_single_beat_rule_allows": Timings(
            name="beat 8", heartbeat=8, min_timeout=10, max_timeout=20
        ).sane,
        "and_the_two_beat_rule_does_not": not Timings(
            name="beat 8", heartbeat=8, min_timeout=10, max_timeout=20
        ).comfortable,
    }


def the_heartbeat_has_to_fit_twice_not_once() -> dict:
    """Sweeping the interval puts the boundary at half the timeout, not at all of it.

    The rule I started with was that a heartbeat plus a delivery must land before the shortest
    timeout, which allows an interval of eight against a timeout of ten. The sweep says
    leadership survives to five and breaks at six.

    The factor of two is the reason. A follower rearms the moment it hears from the leader, so
    the window it has to survive begins at an arbitrary point between two beats, and the gap it
    actually sees can be almost twice the interval. Covering that needs two beats inside the
    timeout rather than one. The doubled rule predicts a boundary between four and five and the
    measurement puts it between five and six, which is the right side to be wrong on.

    The failure past the boundary is gradual and that is worth saying. Six through ten lose the
    leadership occasionally and still commit every write, because an election is quick and the
    next leader picks up where the last one left off. Only at twelve do writes start going
    missing. There is no cliff, which is why a cluster can run for a long time on a heartbeat
    that is quietly too slow.
    """
    made = {}
    for beat in range(1, 13):
        timings = Timings(name=f"beat {beat}", heartbeat=beat, min_timeout=10, max_timeout=20)
        runs = [trial(timings, seed=seed) for seed in range(4)]
        made[beat] = {
            "stable": all(one.stable for one in runs),
            "committed": min(one.committed for one in runs),
            "terms": max(one.terms for one in runs),
            "sane": timings.sane,
            "comfortable": timings.comfortable,
        }
    stable = [beat for beat, one in made.items() if one["stable"]]
    return {
        "intervals": sorted(made),
        "stable_up_to": max(stable),
        "single_beat_rule_allows_up_to": max(beat for beat, one in made.items() if one["sane"]),
        "the_single_beat_rule_is_optimistic": max(
            beat for beat, one in made.items() if one["sane"]
        )
        > max(stable),
        "two_beat_rule_allows_up_to": max(
            beat for beat, one in made.items() if one["comfortable"]
        ),
        "the_two_beat_rule_is_close": abs(
            max(beat for beat, one in made.items() if one["comfortable"]) - max(stable)
        )
        <= 1,
        "and_it_errs_low": max(beat for beat, one in made.items() if one["comfortable"])
        <= max(stable),
        "committed_at_ten": made[10]["committed"],
        "commits_survive_past_the_boundary": made[10]["committed"] == 10,
        "committed_at_twelve": made[12]["committed"],
        "and_only_fail_well_past_it": made[12]["committed"] < 10,
        "terms_at_twelve": made[12]["terms"],
    }


def a_faster_heartbeat_makes_failover_slower_not_quicker() -> dict:
    """Beating every tick costs about two ticks of extra downtime when the leader dies.

    I wrote this expecting the heartbeat to be irrelevant to detection and it is worse than
    irrelevant, it is backwards. Beating every tick recovers in fourteen ticks on average.
    Beating every third, fifth or eighth recovers in between eleven and thirteen.

    The reason is that the heartbeat is not the failure detector, it is the thing that keeps
    resetting the detector. A follower that heard from the leader on the tick it died starts its
    whole timeout from that moment. A follower that last heard five ticks earlier is already
    five ticks into the window. So a lazy heartbeat leaves the cluster part way through its own
    timer when the failure happens, and it notices sooner.

    The practical reading is not that heartbeats should be slow. It is that the heartbeat
    interval is not a knob for availability at all: it trades traffic against a few ticks of
    detection, in the opposite direction to the intuition, and the timer is what actually sets
    the number.
    """
    out: dict[int, list[int]] = {}
    for beat in (1, 3, 5, 8):
        timings = Timings(name=f"beat {beat}", heartbeat=beat, min_timeout=10, max_timeout=20)
        taken = []
        for seed in range(8):
            made = Trial(timings, size=5, seed=seed)
            made.settle()
            found = made.cluster.leader()
            if found is None:
                continue
            made.cluster.crash(found.name)
            start = made.cluster.now
            while made.cluster.now - start < 200:
                made.tick()
                fresh = made.cluster.leader()
                if fresh is not None and fresh.name != found.name:
                    break
            taken.append(made.cluster.now - start)
        out[beat] = taken
    means = {beat: round(sum(one) / len(one), 2) for beat, one in out.items()}
    return {
        "intervals": sorted(out),
        "ticks_to_notice": means,
        "the_fastest_beat_is_the_slowest_to_recover": means[1] == max(means.values()),
        "by_this_many_ticks": round(means[1] - means[3], 2),
        "and_the_lazier_three_are_all_quicker": all(
            means[beat] < means[1] for beat in (3, 5, 8)
        ),
        "the_best_case_is_inside_the_shortest_timeout": min(min(one) for one in out.values())
        < MIN_ELECTION_TIMEOUT,
        "worst_case": max(max(one) for one in out.values()),
        "best_case": min(min(one) for one in out.values()),
        "all_inside_a_timeout_and_an_election": max(max(one) for one in out.values())
        <= MAX_ELECTION_TIMEOUT,
        "min_timeout": MIN_ELECTION_TIMEOUT,
        "max_timeout": MAX_ELECTION_TIMEOUT,
    }


def a_zero_heartbeat_is_refused() -> bool:
    """A heartbeat of no ticks is refused."""
    try:
        Timings(name="x", heartbeat=0, min_timeout=10, max_timeout=20)
    except ConfigError:
        return True
    return False


def a_backwards_timeout_range_is_refused() -> bool:
    """A maximum below the minimum is refused."""
    try:
        Timings(name="x", heartbeat=3, min_timeout=20, max_timeout=10)
    except ConfigError:
        return True
    return False


def a_zero_delay_is_refused() -> bool:
    """A link that delivers in no ticks at all is refused."""
    try:
        Timings(name="x", heartbeat=3, min_timeout=10, max_timeout=20, delay=0)
    except ConfigError:
        return True
    return False


def a_trial_of_no_nodes_is_refused() -> bool:
    """A cluster of nothing is refused."""
    try:
        Trial(SETTINGS["shipped"], size=0)
    except ConfigError:
        return True
    return False


def compare_the_settings() -> list[dict]:
    """Every named setting over the same window, at five nodes."""
    return [trial(one).as_dict() for one in SETTINGS.values()]


def the_two_textbook_rules_are_not_enough_on_their_own() -> dict:
    """The fixed setting passes both inequalities and elects nobody, so a third rule is needed.

    This was meant to be a tidy closing table: the settings that satisfy the two rules commit
    everything, the settings that fail one commit nothing. It nearly is. Four settings pass both
    rules and three of them commit every write, and the fourth is the fixed range, which passes
    both and never elects a leader at all.

    Neither inequality mentions randomisation. Broadcast time much less than election timeout is
    about whether an election can finish; election timeout much less than mean time between
    failures is about whether there is time to do anything between them. A range of zero width
    breaks neither and breaks the algorithm, so the rule the pair is missing is that the range
    has to have a width at all.

    I nearly missed it, because the first version of this check asked whether each setting
    committed everything it proposed and the fixed setting proposed nothing, having no leader to
    propose through. Zero out of zero passed. The check now requires that something was actually
    written.
    """
    table = {one.name: (one, trial(one)) for one in SETTINGS.values()}
    passes = {
        name
        for name, (timings, _) in table.items()
        if timings.comfortable and timings.deliveries_per_timeout >= 2
    }
    worked = {
        name
        for name, (_, run) in table.items()
        if run.proposed > 0 and run.committed == run.proposed
    }
    return {
        "settings": sorted(table),
        "pass_both_rules": sorted(passes),
        "committed": {name: run.committed for name, (_, run) in table.items()},
        "proposed": {name: run.proposed for name, (_, run) in table.items()},
        "worked": sorted(worked),
        "everything_that_worked_passed_the_rules": worked <= passes,
        "but_not_the_other_way_round": passes - worked == {"fixed"},
        "the_odd_one_out": sorted(passes - worked),
        "it_proposed_nothing": table["fixed"][1].proposed == 0,
        "because_it_has_no_spread": SETTINGS["fixed"].spread == 0,
        "and_neither_rule_mentions_spread": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    beats = the_heartbeat_has_to_fit_twice_not_once()
    return {
        "shipped": SETTINGS["shipped"].as_dict(),
        "a_fixed_timeout_elects_nobody": a_fixed_timeout_never_elects_anyone_at_all()[
            "and_nothing_larger_does"
        ],
        "one_tick_of_spread_is_enough": one_tick_of_spread_is_enough_to_break_the_tie()[
            "narrow_is_stable_everywhere"
        ],
        "stable_up_to_a_heartbeat_of": beats["stable_up_to"],
        "the_single_beat_rule_is_optimistic": beats["the_single_beat_rule_is_optimistic"],
        "the_two_beat_rule_errs_low": beats["and_it_errs_low"],
        "a_fast_heartbeat_slows_failover": (
            a_faster_heartbeat_makes_failover_slower_not_quicker()[
                "the_fastest_beat_is_the_slowest_to_recover"
            ]
        ),
        "an_inverted_setting_looks_healthy": (
            a_heartbeat_longer_than_the_timeout_keeps_a_leader_and_commits_nothing()[
                "so_neither_uptime_nor_traffic_would_catch_it"
            ]
        ),
        "the_two_rules_miss_the_fixed_range": (
            the_two_textbook_rules_are_not_enough_on_their_own()["but_not_the_other_way_round"]
        ),
        "the_runs_repeat": the_same_timings_and_seed_replay_the_same_run()[
            "they_are_identical"
        ],
    }
