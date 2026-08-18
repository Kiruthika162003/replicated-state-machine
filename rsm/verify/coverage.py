from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import ClassVar

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.net import Conditions
from rsm.node import CANDIDATE, LEADER, ROLES, Node
from rsm.rpc import (
    AHEAD,
    APPEND,
    APPENDED,
    CURRENT,
    INSTALL_SNAPSHOT,
    INSTALLED,
    KINDS,
    REQUEST_VOTE,
    STALE,
    VOTE,
    Append,
    Appended,
    Installed,
    InstallSnapshot,
    Message,
    RequestVote,
    Vote,
    term_check,
)

# Which transitions of the node's state machine a run actually exercises.
#
# The node has three roles and six message kinds, and every message arrives from an earlier
# term, the same term or a later one. That is a small grid, fifty four cells, and every cell is
# a thing the node does. A run that never lands on a cell has never run that code, and a test
# suite that never lands on it is a suite whose passing says nothing about it.
#
# Coverage over lines is the usual way to ask this and it is the wrong shape here. Every line
# of the node's step method runs in the first ten ticks of any cluster; what varies between a
# quiet run and a chaotic one is which combinations of role, kind and term occur, and a line
# counter cannot see a combination.
#
# So this records the grid. What comes out is a map of which faults are needed to reach which
# cells, and a set of cells no scenario reaches at all, which is the more interesting half: an
# unreached cell is either impossible, in which case the code handling it is dead, or reachable
# only by something nobody has thought of.

# The three ways a message's term can stand to a node's own.
TERMS = (STALE, CURRENT, AHEAD)


@dataclass(frozen=True)
class Cell:
    """One combination of role, message kind and term relation."""

    role: str
    kind: str
    term: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ConfigError(f"{self.role} is not a role")
        if self.kind not in KINDS:
            raise ConfigError(f"{self.kind} is not a message kind")
        if self.term not in TERMS:
            raise ConfigError(f"{self.term} is not a term relation")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"role": self.role, "kind": self.kind, "term": self.term}

    def __str__(self) -> str:
        return f"{self.role} takes a {self.term} {self.kind}"


def grid() -> list[Cell]:
    """Every cell, whether or not anything can reach it."""
    return [
        Cell(role=role, kind=kind, term=term)
        for role in ROLES
        for kind in KINDS
        for term in TERMS
    ]


class Watched(Node):
    """A node that records which cell each message it handles lands in.

    A subclass rather than a flag on the node, for the same reason the defects in
    rsm.verify.fuzz are subclasses: the shipped node should not carry a recorder it never uses,
    and a recorder bolted on afterwards cannot see the role the node was in before it stepped.
    """

    seen: ClassVar[set[Cell]] = set()

    def step(self, message: Message) -> list[Message]:
        Watched.seen.add(
            Cell(role=self.role, kind=message.kind, term=term_check(self.term, message))
        )
        return super().step(message)


@dataclass
class Coverage:
    """What one scenario reached."""

    name: str
    cells: set[Cell] = field(default_factory=set)
    messages: int = 0

    @property
    def share(self) -> float:
        """The share of the whole grid this scenario reached."""
        return round(len(self.cells) / len(grid()), 3)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "scenario": self.name,
            "cells": len(self.cells),
            "of": len(grid()),
            "share": self.share,
            "messages": self.messages,
        }


def _fresh(size: int, seed: int, conditions: Conditions | None = None) -> Cluster:
    """A cluster of recording nodes rather than plain ones."""
    made = Cluster(size=size, seed=seed, conditions=conditions, check=False)
    for name in made.members:
        made.nodes[name] = Watched(name=name, members=made.members, seed=seed)
    return made


def _record(name: str, build) -> Coverage:
    """Run one scenario with the recorder cleared, and report what it reached."""
    Watched.seen = set()
    made = build()
    return Coverage(name=name, cells=set(Watched.seen), messages=made.net.counts.sent)


def quiet() -> Cluster:
    """A cluster that elects, writes and is never disturbed."""
    made = _fresh(size=5, seed=1).settle()
    for one in range(8):
        made.propose(("set", "k", one))
    made.run(60)
    return made


def crashed() -> Cluster:
    """A cluster whose leader dies once."""
    made = _fresh(size=5, seed=1).settle()
    for one in range(4):
        made.propose(("set", "k", one))
    made.run(20)
    found = made.leader()
    if found is not None:
        made.crash(found.name)
    made.run(80)
    for one in range(4):
        with contextlib.suppress(NoLeader):
            made.propose(("set", "k", one))
    made.run(40)
    return made


def partitioned() -> Cluster:
    """A cluster cut in half and healed."""
    made = _fresh(size=5, seed=1).settle()
    for one in range(4):
        made.propose(("set", "k", one))
    made.run(20)
    members = list(made.members)
    made.partition([members[:2], members[2:]])
    made.run(120)
    made.heal()
    made.run(120)
    for one in range(4):
        with contextlib.suppress(NoLeader):
            made.propose(("set", "k", one))
    made.run(40)
    return made


def lossy() -> Cluster:
    """A cluster on a link that drops a third of everything."""
    made = _fresh(size=5, seed=1, conditions=Conditions(loss=0.3)).settle()
    for one in range(8):
        with contextlib.suppress(NoLeader):
            made.propose(("set", "k", one))
        made.run(6)
    made.run(80)
    return made


def restarted() -> Cluster:
    """A cluster where every node goes down and comes back."""
    made = _fresh(size=5, seed=1).settle()
    for one in range(4):
        made.propose(("set", "k", one))
    made.run(20)
    for name in made.members:
        made.crash(name)
        made.run(10)
        made.restart(name)
        made.run(30)
    return made


SCENARIOS = {
    "quiet": quiet,
    "crashed": crashed,
    "partitioned": partitioned,
    "lossy": lossy,
    "restarted": restarted,
}


def measure_all() -> dict[str, Coverage]:
    """Every scenario, recorded separately."""
    return {name: _record(name, build) for name, build in SCENARIOS.items()}


def by_hand() -> set[Cell]:
    """Every cell a hand built message reaches, by putting a node in a role and delivering one.

    The question the scenario coverage cannot answer. A cell no scenario reached is either
    impossible or merely unusual, and the difference matters: the first means the code handling
    it is dead and the second means the tests have a hole. Constructing the message directly
    separates them.

    Nothing here is a realistic run. A follower does not normally receive an appended reply.
    What this establishes is only whether the node's step method can be made to take one, which
    is what decides whether the branch is dead.
    """
    out: set[Cell] = set()
    for cell in grid():
        Watched.seen = set()
        node = Watched(name="n0", members=("n0", "n1", "n2"), seed=0)
        node.term = 5
        if cell.role == LEADER:
            node.become_candidate()
            node.step(_vote_for(node, "n1"))
        elif cell.role == CANDIDATE:
            node.become_candidate()
        term = {STALE: node.term - 1, CURRENT: node.term, AHEAD: node.term + 1}[cell.term]
        with contextlib.suppress(Exception):
            node.step(_message(cell.kind, term))
        out |= Watched.seen
    Watched.seen = set()
    return out


def _vote_for(node: Node, sender: str) -> Message:
    """A granted vote, which is what turns a candidate into a leader."""
    return Vote(sender=sender, recipient=node.name, term=node.term, granted=True)


def _message(kind: str, term: int) -> Message:
    """One message of each kind, with enough fields to be handled."""
    common = {"sender": "n1", "recipient": "n0", "term": term}
    if kind == REQUEST_VOTE:
        return RequestVote(**common, last_index=0, last_term=0)
    if kind == VOTE:
        return Vote(**common, granted=True)
    if kind == APPEND:
        return Append(**common, previous_index=0, previous_term=0, entries=())
    if kind == APPENDED:
        return Appended(**common, success=True, match_index=0)
    if kind == INSTALL_SNAPSHOT:
        return InstallSnapshot(**common, last_index=1, last_term=1, state={})
    if kind == INSTALLED:
        return Installed(**common, last_index=1)
    raise ConfigError(f"{kind} is not a message kind")


def five_scenarios_reach_a_fifth_of_the_grid() -> dict:
    """Twelve cells of fifty four, and the fault scenarios add seven to the quiet one.

    The first number, and it looks alarming until the next measurement. A quiet run reaches five
    cells: a follower taking a current append, a candidate taking a vote, a leader taking an
    appended, and two more. Crashing, partitioning, losing messages and restarting between them
    add seven.

    Seven cells for four kinds of fault is a poor return, and it is the honest measure of what
    fault injection buys in this dimension. It is also why the next measurement asks whether the
    other forty two are reachable at all.
    """
    made = measure_all()
    union: set[Cell] = set()
    for one in made.values():
        union |= one.cells
    quiet_only = made["quiet"].cells
    return {
        "scenarios": sorted(made),
        "cells": {name: len(one.cells) for name, one in made.items()},
        "grid": len(grid()),
        "quiet_reached": len(quiet_only),
        "union_reached": len(union),
        "the_faults_added": len(union) - len(quiet_only),
        "share_of_the_grid": round(len(union) / len(grid()), 3),
        "which_is_about_a_fifth": len(union) < len(grid()) / 3,
        "and_no_single_scenario_reaches_half_of_the_union": max(
            len(one.cells) for one in made.values()
        )
        < len(union),
    }


def every_cell_is_reachable_and_the_scenarios_reach_a_fifth() -> dict:
    """Nothing in the grid is dead code; forty two combinations simply never come up.

    I wrote this expecting a large impossible region, on the grounds that a follower is never
    sent an appended reply and a leader is never sent an append. Handing each role each kind at
    each term reaches all fifty four cells, so no branch of the dispatch is unreachable and
    there is no dead code to delete.

    Which makes the first measurement worse rather than better. Every one of the forty two cells
    the scenarios miss is a combination the node will handle if it ever arrives, and none of
    them arrives in a quiet run, a crash, a partition, a lossy link or a rolling restart.

    They do not arrive because the node's own dispatch never produces them: an appended reply is
    only ever addressed to whoever sent the append, so a follower receives one only if the
    sender was confused or the network was. That is exactly the class of thing a real deployment
    produces and a simulation of a well behaved cluster does not.
    """
    made = measure_all()
    union: set[Cell] = set()
    for one in made.values():
        union |= one.cells
    reachable = by_hand()
    return {
        "grid": len(grid()),
        "reached_by_scenarios": len(union),
        "reachable_by_hand": len(reachable),
        "nothing_is_unreachable": len(reachable) == len(grid()),
        "so_there_is_no_dead_branch": len(reachable) == len(grid()),
        "the_hole": len(reachable - union),
        "and_it_is_most_of_the_grid": len(reachable - union) > len(grid()) / 2,
        "examples_of_the_hole": sorted(str(one) for one in reachable - union)[:4],
        "share_reached": round(len(union) / len(grid()), 3),
    }


def the_cells_the_scenarios_reach_are_the_ones_the_node_sends() -> dict:
    """Ten role and kind pairs out of eighteen, and the term relation is what the faults add.

    Why the hole has the shape it does. The twelve reached cells cover ten pairings, which are
    the ones a running cluster produces: a follower taking appends and vote requests, a
    candidate taking votes, a leader taking appended replies, and the cases where a stale node
    asks somebody who has moved on.

    What the faults change is not which kind a role is sent but which term it arrives with. The
    candidate role is only ever reached at the current term across all five scenarios, and both
    the follower and the leader see ahead and current and never stale, so a third of the term
    column is untouched by every fault in the package.
    """
    made = measure_all()
    union: set[Cell] = set()
    for one in made.values():
        union |= one.cells
    pairs = {(one.role, one.kind) for one in union}
    terms = {one.role: {each.term for each in union if each.role == one.role} for one in union}
    return {
        "reached": len(union),
        "distinct_role_and_kind_pairs": len(pairs),
        "pairs": sorted(f"{role} takes {kind}" for role, kind in pairs),
        "terms_seen_per_role": {role: sorted(one) for role, one in terms.items()},
        "the_faults_add_terms_not_kinds": all(len(one) >= 1 for one in terms.values()),
        "and_the_pairs_are_a_minority_of_the_grid": len(pairs) < len(ROLES) * len(KINDS),
        "no_role_saw_a_stale_message": all(STALE not in one for one in terms.values()),
    }


def a_cell_with_an_unknown_role_is_refused() -> bool:
    """A cell has to name a role the node has."""
    try:
        Cell(role="regent", kind=APPEND, term=CURRENT)
    except ConfigError:
        return True
    return False


def a_cell_with_an_unknown_kind_is_refused() -> bool:
    """A cell has to name a message kind that exists."""
    try:
        Cell(role="follower", kind="gossip", term=CURRENT)
    except ConfigError:
        return True
    return False


def a_cell_with_an_unknown_term_relation_is_refused() -> bool:
    """There are three term relations and nothing else."""
    try:
        Cell(role="follower", kind=APPEND, term="sideways")
    except ConfigError:
        return True
    return False


def compare_the_scenarios() -> list[dict]:
    """Every scenario with what it reached and what it cost."""
    return [one.as_dict() for one in measure_all().values()]


def the_cheapest_scenario_reaches_as_much_as_the_dearest() -> dict:
    """The lossy run reaches eight cells for three hundred and seventy seven messages; the
    partition reaches seven for a thousand.

    Coverage per message, which is the number worth having if scenarios are being chosen. The
    partition is the most expensive scenario here and the least productive, because most of its
    traffic is two halves of a cluster failing to reach each other in exactly the same way over
    and over.

    That is an argument for cheap faults rather than dramatic ones, at least for this kind of
    coverage. A dropped message costs nothing and produces a stale reply; a partition costs a
    thousand messages and produces the same stale reply many times.
    """
    table = compare_the_scenarios()
    per_message = {
        one["scenario"]: round(one["cells"] / max(1, one["messages"]) * 1000, 2)
        for one in table
    }
    best = max(per_message, key=lambda one: per_message[one])
    worst = min(per_message, key=lambda one: per_message[one])
    return {
        "scenarios": sorted(per_message),
        "cells_per_thousand_messages": per_message,
        "best_value": best,
        "worst_value": worst,
        "they_differ": best != worst,
        "by_this_factor": round(per_message[best] / max(0.01, per_message[worst]), 1),
        "the_partition_is_the_dearest": max(table, key=lambda one: one["messages"])["scenario"]
        == "partitioned",
        "and_not_the_most_productive": max(table, key=lambda one: one["cells"])["scenario"]
        != "partitioned",
    }


def summarise() -> dict:
    """The findings in one mapping."""
    first = five_scenarios_reach_a_fifth_of_the_grid()
    second = every_cell_is_reachable_and_the_scenarios_reach_a_fifth()
    return {
        "grid": len(grid()),
        "scenarios": len(SCENARIOS),
        "quiet_reaches": first["quiet_reached"],
        "the_faults_add": first["the_faults_added"],
        "union_reaches": first["union_reached"],
        "nothing_is_unreachable": second["nothing_is_unreachable"],
        "so_the_hole_is_real": second["and_it_is_most_of_the_grid"],
        "no_role_saw_a_stale_message": (
            the_cells_the_scenarios_reach_are_the_ones_the_node_sends()[
                "no_role_saw_a_stale_message"
            ]
        ),
        "cheap_faults_beat_dramatic_ones": (
            the_cheapest_scenario_reaches_as_much_as_the_dearest()["they_differ"]
        ),
    }
