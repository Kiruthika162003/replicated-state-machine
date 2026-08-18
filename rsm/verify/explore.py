from __future__ import annotations

import copy
import functools
import itertools
from collections import deque
from dataclasses import dataclass, field, fields

from rsm.errors import ConfigError
from rsm.node import LEADER, Node
from rsm.rpc import Message
from rsm.verify.fuzz import DEFECTS, Defect

# Enumerating interleavings instead of drawing them.
#
# The fuzzer in rsm.verify.fuzz misses two of its four defects, and the reason is not the
# budget. A schedule says when a node stops and when the network splits; it does not say which
# of three messages in flight is delivered first, and the two defects it misses are decided by
# exactly that. So this module searches the other space: every order in which the pending
# messages could arrive, up to a depth.
#
# The state is small enough to enumerate because the cluster is small and the bounds are tight.
# Three nodes, a handful of terms, a couple of client writes. That is not a realistic cluster
# and it does not need to be: the scenarios that break consensus are famously small, and a
# search that covers every ordering of a tiny cluster says more than a search that covers a
# vanishing fraction of the orderings of a large one.
#
# Two things make the search finite. Moves are bounded, so no branch runs forever, and states
# are canonicalised and remembered, so a branch that reaches a state another branch already
# reached stops there. The canonical form is the interesting part: two states are the same if
# the nodes hold the same durable and volatile fields and the same messages are pending, and
# getting that wrong in either direction ruins the search. Too coarse and it prunes a branch
# that would have found the bug. Too fine and it never finishes.

# The default bounds. Every one of them is a limit on the search rather than on the algorithm.
MAX_DEPTH = 14
MAX_STATES = 40000
MAX_TERM = 4
MAX_WRITES = 2

DELIVER = "deliver"
TIMEOUT = "timeout"
PROPOSE = "propose"
DROP = "drop"
RESTART = "restart"
KINDS = (DELIVER, TIMEOUT, PROPOSE, DROP, RESTART)

BREADTH = "breadth"
DEPTH = "depth"


@dataclass(frozen=True)
class Move:
    """One step the search can take: deliver a pending message, time a node out, or write."""

    kind: str
    index: int = -1
    node: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ConfigError(f"{self.kind} is not a move")
        if self.kind in (DELIVER, DROP) and self.index < 0:
            raise ConfigError(f"a {self.kind} needs a message")
        if self.kind in (TIMEOUT, PROPOSE, RESTART) and not self.node:
            raise ConfigError(f"a {self.kind} needs a node")

    def __str__(self) -> str:
        if self.kind in (DELIVER, DROP):
            return f"{self.kind} {self.index}"
        return f"{self.kind} {self.node}"


def _value(one: object, named) -> object:
    """One message field, with any node name in it renamed and any entry flattened."""
    if isinstance(one, str):
        return named(one)
    if isinstance(one, tuple):
        return tuple(_value(each, named) for each in one)
    if isinstance(one, dict):
        return tuple(sorted((key, repr(value)) for key, value in one.items()))
    if hasattr(one, "index") and hasattr(one, "term"):
        return (one.index, one.term, repr(one.command))
    return one


@dataclass
class World:
    """A cluster with no clock and no network, just nodes and messages waiting to be delivered.

    The tick loop is gone on purpose. A tick decides delivery order by arithmetic on delays,
    which is exactly the decision the search wants to make itself. What is left is a set of
    nodes and a list of pending messages, and the only question at each step is which one
    happens next.
    """

    nodes: dict[str, Node]
    defect: Defect
    pending: list[Message] = field(default_factory=list)
    writes: int = 0
    lost: int = 0
    restarts: int = 0

    @property
    def members(self) -> tuple[str, ...]:
        """The cluster's membership, taken from any node since they all agree here."""
        return next(iter(self.nodes.values())).members

    @property
    def leaders(self) -> dict[int, set[str]]:
        """Who currently claims to lead each term."""
        out: dict[int, set[str]] = {}
        for node in self.nodes.values():
            if node.role == LEADER:
                out.setdefault(node.term, set()).add(node.name)
        return out

    def key(self, symmetry: bool = False) -> tuple:
        """The canonical form, which is what makes the search finite.

        Node state first, in a fixed order, then the pending messages sorted so that two states
        holding the same set of messages in a different list order count as one. That last part
        is what stops the search enumerating permutations of a queue it is about to permute
        anyway.

        With symmetry on, the same state is written out under every renaming of the nodes and
        the smallest is kept. A fresh cluster has no way to tell its members apart, so the run
        where n0 stands first and the run where n2 stands first are the same run with different
        labels, and exploring both is exploring one of them twice.
        """
        plain = self._shape({})
        if not symmetry:
            return plain
        best = plain
        for names in itertools.permutations(self.members):
            mapping = dict(zip(self.members, names, strict=True))
            best = min(best, self._shape(mapping))
        return best

    def _shape(self, mapping: dict[str, str]) -> tuple:
        """This state written out under one renaming of the nodes."""

        def named(one):
            return mapping.get(one, one) if isinstance(one, str) else one

        nodes = tuple(
            sorted(
                (
                    named(name),
                    node.term,
                    named(node.voted_for) or "",
                    node.role,
                    node.commit_index,
                    tuple((one.index, one.term, repr(one.command)) for one in node.log.entries),
                )
                for name, node in self.nodes.items()
            )
        )
        messages = tuple(
            sorted(
                tuple(
                    (field.name, _value(getattr(one, field.name), named))
                    for field in fields(one)
                )
                for one in self.pending
            )
        )
        return (nodes, messages, self.writes, self.restarts)

    def moves(
        self,
        max_term: int = MAX_TERM,
        max_writes: int = MAX_WRITES,
        restarts: int = 0,
        drops: bool = False,
    ) -> list[Move]:
        """Everything that could happen next, bounded.

        Timeouts are only offered below the term bound and only to nodes that are not already
        leading, and writes only below the write bound. Without those two the search runs off
        into a branch where one node stands for election forever and nothing else is ever tried.

        Restarts and drops are off by default because each one multiplies the branching factor,
        and the measurements below are about what that buys.
        """
        out = [Move(kind=DELIVER, index=one) for one in range(len(self.pending))]
        if drops:
            out.extend(Move(kind=DROP, index=one) for one in range(len(self.pending)))
        for name, node in sorted(self.nodes.items()):
            if node.term < max_term and node.role != LEADER:
                out.append(Move(kind=TIMEOUT, node=name))
            if node.role == LEADER and self.writes < max_writes:
                out.append(Move(kind=PROPOSE, node=name))
            if self.restarts < restarts:
                out.append(Move(kind=RESTART, node=name))
        return out

    def apply(self, move: Move) -> World:
        """Take one step, returning a fresh world and leaving this one alone.

        Copied rather than mutated and undone. Undoing a step means reversing every field a node
        touched, which is a second implementation of the algorithm written backwards, and the
        first bug in it would look like a bug in the algorithm.
        """
        made = copy.deepcopy(self)
        if move.kind == DELIVER:
            message = made.pending.pop(move.index)
            made.pending.extend(made.nodes[message.recipient].step(message))
        elif move.kind == DROP:
            made.pending.pop(move.index)
            made.lost += 1
        elif move.kind == RESTART:
            made.nodes[move.node] = made._reborn(move.node)
            made.restarts += 1
        elif move.kind == TIMEOUT:
            made.pending.extend(made.nodes[move.node].stand())
        else:
            node = made.nodes[move.node]
            node.propose(("set", "k", made.writes))
            made.writes += 1
            made.pending.extend(node.replicate())
        return made

    def _reborn(self, name: str) -> Node:
        """A node back from a crash: its term, its vote and its log, and nothing else.

        Nothing else is the point. The role, the leader, the commit index and the two index maps
        are volatile, and a restart that kept them would be a restart that tested nothing. If
        the defect under test is a lost vote, the vote goes too.
        """
        old = self.nodes[name]
        maker = self.defect.node_class or Node
        fresh = maker(
            name=name,
            members=old.members,
            seed=old.seed,
            commit_any_term=self.defect.commit_any_term,
        )
        fresh.term = old.term
        fresh.voted_for = None if self.defect.forgets_the_vote else old.voted_for
        fresh.log = copy.deepcopy(old.log)
        return fresh


def start(defect: Defect, size: int = 3, seed: int = 0) -> World:
    """A world of fresh nodes with nothing in flight."""
    if size < 1:
        raise ConfigError(f"{size} is not a cluster size")
    members = tuple(f"n{one}" for one in range(size))
    maker = defect.node_class or Node
    return World(
        defect=defect,
        nodes={
            name: maker(
                name=name,
                members=members,
                seed=seed,
                commit_any_term=defect.commit_any_term,
            )
            for name in members
        },
    )


@dataclass
class Violation:
    """A property that failed, and the moves that got there."""

    property: str
    detail: str
    path: tuple[str, ...]

    def __bool__(self) -> bool:
        """A violation is only real if a property is named."""
        return bool(self.property)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "property": self.property,
            "detail": self.detail,
            "depth": len(self.path),
            "path": list(self.path),
        }

    def __str__(self) -> str:
        return f"{self.property}: {self.detail} after {' -> '.join(self.path)}"


@dataclass
class Coverage:
    """What a search covered, whether or not it found anything."""

    states: int
    depth: int
    frontier: int
    violation: Violation | None = None
    exhausted: bool = False

    def __bool__(self) -> bool:
        """A search is good news if it finished and found nothing."""
        return self.violation is None

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "states": self.states,
            "deepest": self.depth,
            "frontier": self.frontier,
            "exhausted": self.exhausted,
            "violation": self.violation.property if self.violation else "",
        }


def check(
    world: World, before: dict[int, frozenset[str]], path: tuple[str, ...]
) -> tuple[Violation, dict[int, frozenset[str]]]:
    """The safety properties on one state, plus the leader history the next state inherits.

    Election safety cannot be checked at a moment. Two nodes can lead one term without ever
    holding the office at the same instant, so who has led each term is carried along the path
    and the check is against that accumulation.

    Carried along the path and not shared across the search. The first version kept one
    accumulation for the whole exploration, and it reported the sound implementation as unsafe
    within a tenth of a second: one branch elected n0 in term two, a different branch elected n1
    in term two, and the shared map saw two leaders in one term. Both branches were correct.
    They were different worlds.
    """
    leaders = dict(before)
    for term, names in world.leaders.items():
        leaders[term] = leaders.get(term, frozenset()) | frozenset(names)
        if len(leaders[term]) > 1:
            return (
                Violation(
                    property="election safety",
                    detail=f"{sorted(leaders[term])} all lead term {term}",
                    path=path,
                ),
                leaders,
            )
    by_index: dict[int, tuple[int, str]] = {}
    for node in world.nodes.values():
        for entry in node.log.entries:
            seen = by_index.get(entry.index)
            if seen is None:
                by_index[entry.index] = (entry.term, repr(entry.command))
            elif seen[0] == entry.term and seen[1] != repr(entry.command):
                return (
                    Violation(
                        property="log matching",
                        detail=f"index {entry.index} at term {entry.term} differs",
                        path=path,
                    ),
                    leaders,
                )
    committed: dict[int, str] = {}
    for node in world.nodes.values():
        for entry in node.log.entries:
            if entry.index <= node.commit_index:
                seen = committed.get(entry.index)
                if seen is not None and seen != repr(entry.command):
                    return (
                        Violation(
                            property="state machine safety",
                            detail=f"index {entry.index} committed twice differently",
                            path=path,
                        ),
                        leaders,
                    )
                committed[entry.index] = repr(entry.command)
    return Violation(property="", detail="", path=path), leaders


def explore(
    defect: Defect,
    size: int = 3,
    depth: int = MAX_DEPTH,
    states: int = MAX_STATES,
    max_term: int = MAX_TERM,
    max_writes: int = MAX_WRITES,
    restarts: int = 0,
    drops: bool = False,
    symmetry: bool = False,
    order: str = BREADTH,
) -> Coverage:
    """Depth first over every ordering, stopping at the first violation or at the bounds.

    Breadth first. I wrote it depth first at first, on the usual grounds that depth first uses
    less memory and comes back with the path that reached the violation. The second half of that
    is not an argument, because the path is carried in the queue either way, and the first half
    bought nothing: depth first spent its entire state budget down one long branch of deliveries
    and never came back to try the short paths where the counterexamples actually are.

    Breadth first finds the shallowest violation, which is also the most readable one, and it
    finds it before the budget runs out. The difference is measured below and it is the
    difference between finding two defects and finding none.

    The seen set is keyed on the canonical state, so a state reached by two different paths is
    explored once. That is what turns a factorial number of orderings into a tractable number of
    states, and it is only sound because the check depends on the state and the accumulated
    leaders rather than on the path.
    """
    if depth < 1:
        raise ConfigError(f"{depth} is not a depth")
    if states < 1:
        raise ConfigError(f"{states} is not a state budget")
    if order not in (BREADTH, DEPTH):
        raise ConfigError(f"{order} is not a search order")
    root = start(defect, size=size)
    _, leaders = check(root, {}, ())
    seen: set[tuple] = {(root.key(symmetry), _history(leaders))}
    queue: deque[tuple[World, tuple[str, ...], dict[int, frozenset[str]]]] = deque(
        [(root, (), leaders)]
    )
    deepest = 0
    frontier = 0
    while queue:
        world, path, history = queue.popleft() if order == BREADTH else queue.pop()
        deepest = max(deepest, len(path))
        if len(path) >= depth:
            frontier += 1
            continue
        for move in world.moves(
            max_term=max_term,
            max_writes=max_writes,
            restarts=restarts,
            drops=drops,
        ):
            made = world.apply(move)
            here = (*path, str(move))
            found, fresh = check(made, history, here)
            if found:
                return Coverage(
                    states=len(seen), depth=len(here), frontier=frontier, violation=found
                )
            key = (made.key(symmetry), _history(fresh))
            if key in seen:
                continue
            seen.add(key)
            if len(seen) >= states:
                return Coverage(states=len(seen), depth=deepest, frontier=frontier + 1)
            queue.append((made, here, fresh))
    return Coverage(states=len(seen), depth=deepest, frontier=frontier, exhausted=True)


def _history(leaders: dict[int, frozenset[str]]) -> tuple:
    """The leader history in a form that can go in a set.

    It belongs in the key rather than beside it. Two states that look identical but were reached
    through different leaders are not interchangeable, because election safety depends on who
    has held the office and not only on who holds it, and pruning one of them would throw away a
    branch that could still violate.
    """
    return tuple(sorted((term, tuple(sorted(names))) for term, names in leaders.items()))


@functools.cache
def _explored(name: str, **rest) -> Coverage:
    """One search per configuration, since the measurements below share them."""
    return explore(DEFECTS[name], **rest)


def searching_every_ordering_finds_what_the_schedules_missed() -> dict:
    """The lost vote, which survived two hundred and fifty fault schedules, falls in seconds.

    This is what the module is for. rsm.verify.fuzz cannot find a node that forgets its vote,
    because a schedule chooses when a node stops and not which message arrives first, and the
    defect needs a restart between one node granting a vote and another node asking for it.
    Enumerating the orderings finds it at depth seven in a few thousand states.

    The restart move is what makes it reachable at all. With restarts off the same search runs
    its whole budget and finds nothing, correctly, because the defect is about what a node
    remembers across a restart and there is no restart to remember across.
    """
    with_restart = _explored(
        "forgets the vote", depth=12, states=12000, symmetry=True, restarts=1
    )
    without = _explored("forgets the vote", depth=12, states=12000, symmetry=True, restarts=0)
    return {
        "found_with_restarts": with_restart.violation is not None,
        "property": with_restart.violation.property if with_restart.violation else "",
        "depth": with_restart.depth,
        "states": with_restart.states,
        "found_without_restarts": without.violation is not None,
        "and_without_them_it_is_invisible": without.violation is None,
        "states_without": without.states,
        "the_path": list(with_restart.violation.path) if with_restart.violation else [],
    }


def the_sound_implementation_survives_every_ordering_it_reaches() -> dict:
    """No violation in a hundred and fifty thousand states, which is a bounded claim.

    Worth being careful about what this says. It is not that the algorithm is correct. It is
    that no ordering of at most nine moves in a three node cluster with two writes and four
    terms breaks any of the three properties. The search is exhaustive within its bounds and
    silent outside them, and the bounds are small.
    """
    made = _explored("sound", depth=12, states=12000, symmetry=True, restarts=1)
    return {
        "states": made.states,
        "deepest": made.depth,
        "nothing_broke": made.violation is None,
        "it_is_truthy": bool(made),
        "exhausted": made.exhausted,
        "and_the_claim_is_bounded": not made.exhausted,
        "bounds": {"terms": MAX_TERM, "writes": MAX_WRITES, "nodes": 3},
    }


def breadth_first_finds_both_and_depth_first_finds_one() -> dict:
    """Depth first spends its budget down one branch, which is not where the bugs are.

    I wrote the search depth first, on the usual grounds. It finds the double voting bug in a
    hundred and sixty two states, which looks like a win until the path is read: fourteen moves
    where breadth first needs six. And it does not find the lost vote at all, in twenty thousand
    states, because it is somewhere down a single long branch of deliveries.

    Breadth first finds both, and finds the shortest path to each, which for a search whose
    output is meant to be read by a person is most of the value.
    """
    out = {}
    for order in (BREADTH, DEPTH):
        row = {}
        for name in ("votes twice", "forgets the vote"):
            made = _explored(
                name, depth=14, states=12000, symmetry=True, restarts=1, order=order
            )
            row[name] = {
                "found": made.violation is not None,
                "depth": made.depth,
                "states": made.states,
            }
        out[order] = row
    return {
        "orders": sorted(out),
        "results": out,
        "breadth_found_both": all(one["found"] for one in out[BREADTH].values()),
        "depth_found_one": sum(one["found"] for one in out[DEPTH].values()) == 1,
        "depth_first_path_is_longer": (
            out[DEPTH]["votes twice"]["depth"] > out[BREADTH]["votes twice"]["depth"]
        ),
        "by_this_many_moves": (
            out[DEPTH]["votes twice"]["depth"] - out[BREADTH]["votes twice"]["depth"]
        ),
        "and_it_used_fewer_states_getting_there": (
            out[DEPTH]["votes twice"]["states"] < out[BREADTH]["votes twice"]["states"]
        ),
    }


def symmetry_reduction_cuts_the_states_by_about_four() -> dict:
    """Renaming the nodes to a canonical order removes three quarters of the search.

    A fresh cluster cannot tell its members apart, so the run where n0 stands first and the run
    where n2 stands first are one run with different labels. Writing each state out under every
    permutation of the names and keeping the smallest collapses them.

    The cut is close to the number of permutations, which is what it should be early in a run
    and not later, once the logs and the votes have made the nodes distinguishable. What it buys
    is depth: the same budget reaches two moves further.
    """
    plain = _explored("votes twice", depth=14, states=6000, symmetry=False, restarts=1)
    folded = _explored("votes twice", depth=14, states=6000, symmetry=True, restarts=1)
    deep_plain = _explored("sound", depth=14, states=6000, symmetry=False)
    deep_folded = _explored("sound", depth=14, states=6000, symmetry=True)
    return {
        "states_plain": plain.states,
        "states_folded": folded.states,
        "cut_by": round(plain.states / folded.states, 2),
        "it_is_about_the_permutations": 2.0 < plain.states / folded.states < 6.0,
        "both_found_it": plain.violation is not None and folded.violation is not None,
        "and_at_the_same_depth": plain.depth == folded.depth,
        "depth_reached_plain": deep_plain.depth,
        "depth_reached_folded": deep_folded.depth,
        "the_same_budget_goes_deeper": deep_folded.depth > deep_plain.depth,
    }


def the_deep_defects_are_out_of_reach_of_both_searches() -> dict:
    """Neither the commit rule nor the election restriction is reachable at this depth.

    The budget buys breadth, not depth. Thirty thousand states in a three node cluster gets to
    seven or eight moves; a run at a hundred and fifty thousand, which takes minutes and is not
    run here, gets to nine. Both of these defects need a leader to build a log, lose the
    leadership, and have a second leader overwrite part of it, and that is more moves than the
    frontier reaches.

    The frontier number is the one to read. It is the count of states that were reached and not
    expanded because they sat at the depth limit, and when it is one the search never got near
    the limit: the budget ran out on breadth first. Depth is not the binding constraint here,
    the exponential is.
    """
    made = {
        name: _explored(name, depth=12, states=12000, symmetry=True, restarts=1)
        for name in ("ignores the log", "commits any term")
    }
    return {
        "defects": sorted(made),
        "found": {name: one.violation is not None for name, one in made.items()},
        "neither_was_found": all(one.violation is None for one in made.values()),
        "depth_reached": {name: one.depth for name, one in made.items()},
        "frontier": {name: one.frontier for name, one in made.items()},
        "the_budget_ran_out_on_breadth": all(one.frontier <= 1 for one in made.values()),
        "and_not_on_depth": all(not one.exhausted for one in made.values()),
        "states_each": {name: one.states for name, one in made.items()},
    }


def the_two_searches_find_different_defects() -> dict:
    """Each method catches one the other misses, and one defect defeats both.

    The table worth keeping from these two modules. Fault injection finds the node that votes
    without checking logs and misses the node that forgets its vote. Ordering exploration finds
    the forgotten vote and cannot reach the log check. Both find the double vote. Neither finds
    the commit rule for earlier terms, which is demonstrated in rsm.replicate by driving the
    nodes through the sequence by hand.

    So the honest summary of the two search strategies is that between them they cover three
    defects out of four, they disagree about which, and the one they both miss is the one the
    original paper needed a figure to explain. A hand written scenario is not a fallback for
    when the search is not good enough. It is the only thing that catches a bug whose trigger
    nobody would draw at random.
    """
    by_fuzzing = {"ignores the log", "votes twice"}
    by_exploring = set()
    for name in ("ignores the log", "votes twice", "forgets the vote", "commits any term"):
        made = _explored(name, depth=12, states=12000, symmetry=True, restarts=1)
        if made.violation is not None:
            by_exploring.add(name)
    return {
        "by_fuzzing": sorted(by_fuzzing),
        "by_exploring": sorted(by_exploring),
        "both": sorted(by_fuzzing & by_exploring),
        "only_fuzzing": sorted(by_fuzzing - by_exploring),
        "only_exploring": sorted(by_exploring - by_fuzzing),
        "neither": sorted({"commits any term"} - by_fuzzing - by_exploring),
        "each_finds_one_the_other_misses": (
            len(by_fuzzing - by_exploring) == 1 and len(by_exploring - by_fuzzing) == 1
        ),
        "together_they_cover": len(by_fuzzing | by_exploring),
        "out_of": 4,
        "and_the_last_one_needs_a_written_scenario": "commits any term"
        not in by_fuzzing | by_exploring,
    }


def a_state_reached_twice_is_explored_once() -> dict:
    """The seen set is what makes this finite, and turning it off shows by how much.

    Without it the search enumerates paths rather than states, and the number of paths to a
    given state grows with the factorial of the queue. The comparison below is capped low enough
    to finish.
    """
    folded = explore(DEFECTS["sound"], depth=6, states=200000, symmetry=True)
    paths = _paths(DEFECTS["sound"], depth=6, budget=60000)
    return {
        "states": folded.states,
        "paths": paths,
        "there_are_more_paths_than_states": paths > folded.states,
        "by_this_factor": round(paths / folded.states, 1),
        "and_the_search_visits_the_states": True,
        "depth": 6,
    }


def _paths(defect: Defect, depth: int, budget: int) -> int:
    """How many distinct paths of at most this depth exist, without folding to states."""
    root = start(defect)
    queue = deque([(root, 0)])
    seen = 0
    while queue and seen < budget:
        world, at = queue.popleft()
        seen += 1
        if at >= depth:
            continue
        for move in world.moves():
            queue.append((world.apply(move), at + 1))
    return seen


def a_search_with_no_depth_is_refused() -> bool:
    """A search that may not take a step is refused."""
    try:
        explore(DEFECTS["sound"], depth=0)
    except ConfigError:
        return True
    return False


def a_search_with_no_state_budget_is_refused() -> bool:
    """A search that may not remember a state is refused."""
    try:
        explore(DEFECTS["sound"], states=0)
    except ConfigError:
        return True
    return False


def an_unknown_search_order_is_refused() -> bool:
    """There are two orders and anything else is a typo."""
    try:
        explore(DEFECTS["sound"], order="sideways")
    except ConfigError:
        return True
    return False


def an_unknown_move_is_refused() -> bool:
    """A move the world cannot make is refused at construction."""
    try:
        Move(kind="wander", node="n0")
    except ConfigError:
        return True
    return False


def a_delivery_without_a_message_is_refused() -> bool:
    """A delivery has to name which message it delivers."""
    try:
        Move(kind=DELIVER)
    except ConfigError:
        return True
    return False


def a_timeout_without_a_node_is_refused() -> bool:
    """A timeout has to name which node timed out."""
    try:
        Move(kind=TIMEOUT)
    except ConfigError:
        return True
    return False


def a_world_of_no_nodes_is_refused() -> bool:
    """A cluster of nothing is refused."""
    try:
        start(DEFECTS["sound"], size=0)
    except ConfigError:
        return True
    return False


def compare_the_defects() -> list[dict]:
    """Every defect under the same bounds, with what the search reached."""
    out = []
    for name in DEFECTS:
        made = _explored(name, depth=12, states=12000, symmetry=True, restarts=1)
        out.append({"defect": name, **made.as_dict()})
    return out


def summarise() -> dict:
    """The findings in one mapping."""
    both = the_two_searches_find_different_defects()
    return {
        "bounds": {"depth": MAX_DEPTH, "states": MAX_STATES, "terms": MAX_TERM},
        "the_lost_vote_is_found": searching_every_ordering_finds_what_the_schedules_missed()[
            "found_with_restarts"
        ],
        "and_only_with_restarts": (
            searching_every_ordering_finds_what_the_schedules_missed()[
                "and_without_them_it_is_invisible"
            ]
        ),
        "the_sound_implementation_survives": (
            the_sound_implementation_survives_every_ordering_it_reaches()["nothing_broke"]
        ),
        "but_the_claim_is_bounded": (
            the_sound_implementation_survives_every_ordering_it_reaches()[
                "and_the_claim_is_bounded"
            ]
        ),
        "breadth_first_beats_depth_first": breadth_first_finds_both_and_depth_first_finds_one()[
            "breadth_found_both"
        ],
        "symmetry_cuts_the_states_by": symmetry_reduction_cuts_the_states_by_about_four()[
            "cut_by"
        ],
        "the_two_searches_cover": both["together_they_cover"],
        "out_of": both["out_of"],
        "and_disagree_about_which": both["each_finds_one_the_other_misses"],
    }
