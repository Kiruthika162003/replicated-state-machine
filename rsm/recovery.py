from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader, UnknownNode
from rsm.quorum import majority

# Bringing a cluster back, one node at a time or all at once.
#
# Restarts are the fault a cluster sees most and the one least often modelled, because they are
# planned. A deploy is a rolling restart. A configuration change is a rolling restart. A power
# cut is the unplanned version of the same thing, and the difference between them is only the
# order and the spacing.
#
# I wrote this expecting the spacing to be the thing that matters, on the grounds that a rolling
# restart which does not wait is a way to lose a majority without any node having failed. It is
# not. One node at a time never costs a quorum at any spacing measured here, from five ticks to
# a hundred and twenty; what tight spacing costs is availability, from ninety four percent down
# to eighty. Losing a majority takes touching two nodes at once, which is a different mistake.
#
# What does matter, and by more than the spacing, is the order. Restarting the leader last costs
# exactly one election at every seed. Restarting it first costs between one and three, because
# the election it forces can hand the office to a node that is still on the list.
#
# Nothing here is a fault the algorithm has to survive in the paper's sense. All of it is an
# operator's decision that the algorithm either absorbs or does not, and every pattern below
# keeps every committed entry, which is the part that was never in question.

# How long to run after each restart before touching anything else.
SETTLE = 60

# How long a cold start is given to elect somebody.
PATIENCE = 200

# How many writes go in before the restarts begin.
WRITES = 6


@dataclass
class Recovery:
    """What one restart pattern cost."""

    name: str
    elections: int = 0
    committed_before: int = 0
    committed_after: int = 0
    attempted_during: int = 0
    accepted_during: int = 0
    leaderless: int = 0
    ticks: int = 0
    lost_quorum: int = 0
    gaps: list[int] = field(default_factory=list)

    @property
    def kept(self) -> bool:
        """Whether everything committed before the restarts is still committed after."""
        return self.committed_after >= self.committed_before

    @property
    def uptime(self) -> float:
        """The share of the run with a leader."""
        if self.ticks == 0:
            return 0.0
        return round((self.ticks - self.leaderless) / self.ticks, 3)

    @property
    def worst_gap(self) -> int:
        """The longest stretch with nobody leading."""
        return max(self.gaps, default=0)

    @property
    def availability(self) -> float:
        """The share of writes attempted during the restarts that were accepted."""
        if self.attempted_during == 0:
            return 0.0
        return round(self.accepted_during / self.attempted_during, 3)

    def __bool__(self) -> bool:
        """A recovery is clean if nothing committed was lost and a quorum was never absent."""
        return self.kept and self.lost_quorum == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "pattern": self.name,
            "elections": self.elections,
            "before": self.committed_before,
            "after": self.committed_after,
            "kept": self.kept,
            "availability": self.availability,
            "uptime": self.uptime,
            "worst_gap": self.worst_gap,
            "lost_quorum": self.lost_quorum,
        }


class Run:
    """A cluster being restarted, with the counting kept in one place.

    A class rather than a function because every pattern below does the same bookkeeping around
    a different sequence of crashes and restarts, and the bookkeeping is where the mistakes are:
    counting a write as accepted when there was no leader, or missing a stretch with no quorum
    because nothing looked during it.
    """

    def __init__(self, name: str, size: int = 5, seed: int = 1) -> None:
        if size < 1:
            raise ConfigError(f"{size} is not a cluster size")
        self.cluster = Cluster(size=size, seed=seed).settle()
        self.made = Recovery(name=name)
        self.last: str | None = None
        self.gap = 0
        for one in range(WRITES):
            self.cluster.propose(("set", "before", one))
        self.cluster.run(SETTLE)
        self.made.committed_before = len(self.cluster.committed())

    def advance(self, ticks: int, write: bool = True) -> None:
        """Run for a while, writing along the way and watching for gaps."""
        for tick in range(ticks):
            if write and tick % 10 == 0:
                self.made.attempted_during += 1
                with contextlib.suppress(NoLeader):
                    self.cluster.propose(("set", "during", self.made.attempted_during))
                    self.made.accepted_during += 1
            self.cluster.tick()
            self.made.ticks += 1
            if len(self.cluster.up) < majority(len(self.cluster.members)):
                self.made.lost_quorum += 1
            found = self.cluster.leader()
            if found is None:
                self.made.leaderless += 1
                self.gap += 1
                continue
            if self.gap:
                self.made.gaps.append(self.gap)
                self.gap = 0
            if self.last is not None and found.name != self.last:
                self.made.elections += 1
            self.last = found.name

    def bounce(self, name: str, down_for: int = 10) -> None:
        """Take one node down and bring it back."""
        self.cluster.crash(name)
        self.advance(down_for)
        self.cluster.restart(name)

    def finish(self) -> Recovery:
        """Settle, take the final count, and hand back the record."""
        self.advance(SETTLE, write=False)
        if self.gap:
            self.made.gaps.append(self.gap)
        self.made.committed_after = len(self.cluster.committed())
        return self.made


def cold_start(size: int = 5, seed: int = 1) -> Recovery:
    """Stop every node, then start every node, which is what a power cut looks like."""
    run = Run(name="cold start", size=size, seed=seed)
    for name in run.cluster.members:
        run.cluster.crash(name)
    run.advance(20, write=False)
    for name in run.cluster.members:
        run.cluster.restart(name)
    return run.finish()


def rolling(size: int = 5, seed: int = 1, spacing: int = SETTLE, leader_last: bool = True):
    """Restart every node one at a time, waiting between them."""
    order_name = "leader last" if leader_last else "leader first"
    run = Run(name=f"rolling {spacing} apart, {order_name}", size=size, seed=seed)
    found = run.cluster.leader()
    order = [one for one in run.cluster.members if one != found.name]
    if leader_last:
        order = [*order, found.name]
    else:
        order = [found.name, *order]
    for name in order:
        run.bounce(name)
        run.advance(spacing)
    return run.finish()


def too_fast(size: int = 5, seed: int = 1, together: int = 3) -> Recovery:
    """Take several nodes down at once, which is what a deploy that does not wait looks like."""
    run = Run(name=f"{together} at once", size=size, seed=seed)
    victims = list(run.cluster.members)[:together]
    for name in victims:
        run.cluster.crash(name)
    run.advance(40)
    for name in victims:
        run.cluster.restart(name)
    return run.finish()


def every_pattern_keeps_every_committed_entry() -> dict:
    """Four ways of restarting a cluster and not one of them loses a write.

    The half that was never in doubt, measured anyway because everything below is about
    availability and a reader is entitled to know that safety was checked rather than assumed.
    The term, the vote and the log survive a restart by construction, so a node that comes back
    comes back knowing what it had agreed to.
    """
    made = {
        "cold start": cold_start(),
        "rolling": rolling(),
        "leader first": rolling(leader_last=False),
        "three at once": too_fast(),
    }
    return {
        "patterns": sorted(made),
        "before": {name: one.committed_before for name, one in made.items()},
        "after": {name: one.committed_after for name, one in made.items()},
        "every_one_kept_everything": all(one.kept for one in made.values()),
        "and_none_of_them_went_backwards": all(
            one.committed_after >= one.committed_before for one in made.values()
        ),
        "the_worst_availability": min(one.availability for one in made.values()),
        "which_is_a_different_question": True,
    }


def restarting_the_leader_last_costs_exactly_one_election() -> dict:
    """One election at every seed, against one to three when the leader goes first.

    The operational finding. Bouncing the followers first disturbs nothing, because a follower
    coming back is caught up by the ordinary append path and the leader never notices. The
    single election happens at the end when the leader itself goes.

    Bouncing the leader first forces an election immediately, and the node that wins it may be
    one still on the list, so it is restarted in its turn and the cluster elects again. On one
    of six seeds that happened twice.
    """
    last = [rolling(seed=seed) for seed in range(6)]
    first = [rolling(seed=seed, leader_last=False) for seed in range(6)]
    return {
        "seeds": len(last),
        "leader_last_elections": [one.elections for one in last],
        "leader_first_elections": [one.elections for one in first],
        "last_is_always_one": {one.elections for one in last} == {1},
        "and_first_is_not": len({one.elections for one in first}) > 1,
        "leader_last_availability": round(sum(one.availability for one in last) / len(last), 3),
        "leader_first_availability": round(
            sum(one.availability for one in first) / len(first), 3
        ),
        "and_it_is_better_too": (
            sum(one.availability for one in last) > sum(one.availability for one in first)
        ),
        "the_worst_first_run": min(one.availability for one in first),
    }


def the_spacing_buys_availability_and_never_buys_a_quorum() -> dict:
    """From five ticks apart to a hundred and twenty, the quorum is never at risk.

    The claim I started with and had to withdraw. A rolling restart at any spacing takes one
    node down at a time out of five, so four remain, and four is a majority however impatient
    the operator is. What the spacing changes is availability: eighty percent of writes accepted
    at five ticks apart, ninety seven at a hundred and twenty.

    So the advice to wait between restarts is real and it is about the write path rather than
    about safety, and the thing that actually endangers a quorum is restarting two at once.
    """
    out = {}
    for spacing in (5, 20, 60, 120):
        out[spacing] = rolling(spacing=spacing)
    together = too_fast()
    return {
        "spacings": sorted(out),
        "availability": {one: made.availability for one, made in out.items()},
        "it_rises_with_the_spacing": (
            out[120].availability > out[60].availability > out[5].availability
        ),
        "quorum_lost": {one: made.lost_quorum for one, made in out.items()},
        "never_at_any_spacing": all(one.lost_quorum == 0 for one in out.values()),
        "three_at_once_lost_quorum_for": together.lost_quorum,
        "and_that_is_the_real_risk": together.lost_quorum > 0,
        "worst_gap_at_the_tightest": out[5].worst_gap,
    }


def a_cold_start_accepts_nothing_and_forgets_nothing() -> dict:
    """Twenty ticks without a quorum, no write accepted, and every earlier write intact.

    The unplanned version. Every node goes down together and comes back together, so there is
    no majority at all for as long as they are down and the cluster does exactly nothing. When
    they return they hold the same logs they went down with, elect, and carry on.

    The interesting part is what the recovery costs afterwards rather than during: the nodes
    come back with their timers freshly drawn, so the first election is an ordinary one and the
    cluster is serving again inside a timeout.
    """
    made = cold_start()
    rolled = rolling()
    return {
        "committed_before": made.committed_before,
        "committed_after": made.committed_after,
        "it_kept_everything": made.kept,
        "writes_attempted": made.attempted_during,
        "writes_accepted": made.accepted_during,
        "it_accepted_nothing": made.accepted_during == 0,
        "ticks_without_a_quorum": made.lost_quorum,
        "worst_gap": made.worst_gap,
        "uptime": made.uptime,
        "against_a_rolling_restart": rolled.uptime,
        "which_is_much_better": rolled.uptime > made.uptime,
    }


def a_restart_of_no_nodes_is_refused() -> bool:
    """A cluster of nothing cannot be restarted."""
    try:
        Run(name="x", size=0)
    except ConfigError:
        return True
    return False


def restarting_a_running_node_is_refused() -> bool:
    """A node that never went down cannot come back."""
    run = Run(name="x", size=3)
    try:
        run.cluster.restart("n0")
    except ConfigError:
        return True
    return False


def crashing_a_stranger_is_refused() -> bool:
    """A node the cluster does not have cannot be crashed."""
    run = Run(name="x", size=3)
    try:
        run.cluster.crash("nowhere")
    except UnknownNode:
        return True
    return False


def a_smaller_cluster_tolerates_fewer_restarts_at_once() -> dict:
    """Two at once is survivable at five nodes and fatal at three.

    The arithmetic showing up in an operational decision. A majority of five is three, so two
    can be down and the cluster still writes; a majority of three is two, so two down is a
    cluster that does nothing at all.

    Which means a deploy script that restarts two at a time is fine on one cluster and an outage
    on another, and the difference is not visible in the script.
    """
    out = {}
    for size in (3, 5, 7):
        out[size] = too_fast(size=size, together=2)
    return {
        "sizes": sorted(out),
        "majorities": {size: majority(size) for size in out},
        "quorum_lost": {size: one.lost_quorum for size, one in out.items()},
        "availability": {size: one.availability for size, one in out.items()},
        "three_loses_quorum": out[3].lost_quorum > 0,
        "and_five_does_not": out[5].lost_quorum == 0,
        "and_nor_does_seven": out[7].lost_quorum == 0,
        "everything_was_kept_anyway": all(one.kept for one in out.values()),
    }


def compare_the_patterns() -> list[dict]:
    """Every restart pattern over the same cluster."""
    return [
        cold_start().as_dict(),
        rolling().as_dict(),
        rolling(leader_last=False).as_dict(),
        rolling(spacing=5).as_dict(),
        too_fast().as_dict(),
    ]


def the_patterns_differ_only_in_availability_and_by_a_lot() -> dict:
    """Every row keeps its data and the availability spans the whole range from none to most.

    The table in one sentence. Safety is a constant across the five patterns and availability
    runs from zero to ninety four percent, which is the shape of every operational decision
    around a consensus system: the algorithm has already decided the part that could go wrong,
    and what is left is how much of the time the cluster answers.
    """
    table = compare_the_patterns()
    return {
        "patterns": [one["pattern"] for one in table],
        "every_one_kept_its_data": all(one["kept"] for one in table),
        "availability": {one["pattern"]: one["availability"] for one in table},
        "best": max(table, key=lambda one: one["availability"])["pattern"],
        "worst": min(table, key=lambda one: one["availability"])["pattern"],
        "the_range_is_the_whole_range": (
            max(one["availability"] for one in table) > 0.9
            and min(one["availability"] for one in table) == 0.0
        ),
        "and_safety_is_constant": len({one["kept"] for one in table}) == 1,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    order = restarting_the_leader_last_costs_exactly_one_election()
    spacing = the_spacing_buys_availability_and_never_buys_a_quorum()
    return {
        "patterns": len(compare_the_patterns()),
        "every_pattern_keeps_its_data": (
            every_pattern_keeps_every_committed_entry()["every_one_kept_everything"]
        ),
        "leader_last_costs_one_election": order["last_is_always_one"],
        "leader_first_costs_more": order["and_first_is_not"],
        "spacing_buys_availability": spacing["it_rises_with_the_spacing"],
        "and_never_a_quorum": spacing["never_at_any_spacing"],
        "two_at_once_is_the_real_risk": (
            a_smaller_cluster_tolerates_fewer_restarts_at_once()["three_loses_quorum"]
        ),
        "a_cold_start_accepts_nothing": a_cold_start_accepts_nothing_and_forgets_nothing()[
            "it_accepted_nothing"
        ],
    }
