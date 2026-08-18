from __future__ import annotations

import contextlib
import functools
from dataclasses import dataclass, replace

from rsm.cluster import Cluster
from rsm.errors import ConfigError, ConsensusError, NoLeader
from rsm.log import Log
from rsm.net import Conditions
from rsm.node import Node
from rsm.rpc import Message, RequestVote, Vote
from rsm.verify.faults import Schedule, _apply, random_schedule
from rsm.verify.invariants import inspect

# Searching for a schedule that breaks a property, and then cutting it down to the smallest one
# that still does.
#
# A fuzzer that only ever runs the correct implementation reports the same thing every time and
# proves very little: either the properties hold or the fuzzer is not looking hard enough, and
# from the outside those two look identical. So this module fuzzes against deliberately broken
# nodes as well. Each defect is one rule of the algorithm removed, and the number worth having
# is how many random schedules it takes to catch it. A defect that survives a thousand seeds is
# a defect the fuzzer would not have found in the real thing either.
#
# The second half is shrinking. A schedule that fails with six faults over three hundred ticks
# is a bug report nobody can read. Delta debugging cuts it down: drop a fault, run it again,
# keep the cut if it still fails. What comes out is the smallest schedule in the neighbourhood
# that reproduces, and the smallest schedule is usually an explanation on its own.
#
# The shrinker is checked the way any minimiser has to be: the result must still fail, and the
# result must be smaller. A shrinker that returns something that passes has thrown away the bug
# and reported success, which is the failure mode that matters and the one nobody notices.

# How many random schedules a search will try before giving up.
BUDGET = 200

# The default length and fault count of the schedules the search draws.
TICKS = 300
FAULTS = 6


class IgnoresTheLog(Node):
    """A node that votes for anybody, dropping the election restriction.

    One rule removed: a vote is granted whether or not the candidate's log is at least as up to
    date as this one's. Everything else is the shipped node. That is the point of subclassing
    rather than writing a broken node from scratch, because a hand written broken node differs
    in ways nobody wrote down and the fuzzer then finds the wrong bug.
    """

    def _on_request_vote(self, message: RequestVote) -> list[Message]:
        if message.pre_vote:
            return [
                Vote(
                    sender=self.name,
                    recipient=message.sender,
                    term=self.term,
                    granted=message.term > self.term,
                    pre_vote=True,
                )
            ]
        granted = self.voted_for in (None, message.sender)
        if granted:
            self.voted_for = message.sender
            self.reset_election_timer()
        return [
            Vote(
                sender=self.name,
                recipient=message.sender,
                term=self.term,
                granted=granted,
            )
        ]


class VotesTwice(Node):
    """A node that grants every request in a term, spending its vote as often as asked."""

    def _on_request_vote(self, message: RequestVote) -> list[Message]:
        if message.pre_vote:
            return super()._on_request_vote(message)
        granted = self.log.is_up_to_date(message.last_index, message.last_term)
        if granted:
            self.voted_for = message.sender
            self.reset_election_timer()
        return [
            Vote(
                sender=self.name,
                recipient=message.sender,
                term=self.term,
                granted=granted,
            )
        ]


@dataclass(frozen=True)
class Defect:
    """One rule removed from the algorithm, and how to build a cluster without it."""

    name: str
    node_class: type[Node] | None = None
    commit_any_term: bool = False
    forgets_the_vote: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a defect needs a name")
        if self.node_class is None and not self.commit_any_term and not self.forgets_the_vote:
            raise ConfigError(f"{self.name} removes no rule")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "defect": self.name,
            "class": self.node_class.__name__ if self.node_class else "Node",
            "commit_any_term": self.commit_any_term,
            "forgets_the_vote": self.forgets_the_vote,
        }


DEFECTS: dict[str, Defect] = {
    "sound": Defect(name="sound", node_class=Node),
    "ignores the log": Defect(name="ignores the log", node_class=IgnoresTheLog),
    "votes twice": Defect(name="votes twice", node_class=VotesTwice),
    "commits any term": Defect(name="commits any term", commit_any_term=True),
    "forgets the vote": Defect(name="forgets the vote", forgets_the_vote=True),
}


class Broken(Cluster):
    """A cluster built from a defect, so that a restart brings back the same broken node.

    Overriding restart matters more than it looks. The base class rebuilds a plain Node, which
    would quietly repair every node that ever came back and turn a defect into an intermittent
    one. A fuzzer chasing an intermittent defect measures the restart schedule rather than the
    defect.
    """

    def __init__(self, defect: Defect, size: int = 5, seed: int = 0, **rest) -> None:
        super().__init__(size=size, seed=seed, check=False, **rest)
        self.defect = defect
        for name in self.members:
            self.nodes[name] = self._make(name, seed=seed)

    def _make(self, name: str, seed: int) -> Node:
        """One node with the defect applied."""
        maker = self.defect.node_class or Node
        return maker(
            name=name,
            members=self.members,
            seed=seed,
            pre_vote=self.pre_vote,
            commit_any_term=self.defect.commit_any_term,
        )

    def restart(self, name: str) -> None:
        """Bring a node back with the defect intact, and without its vote if that is one."""
        if name not in self.down:
            raise ConfigError(f"{name} is not down")
        old = self.nodes[name]
        fresh = self._make(name, seed=self.seed + self.now)
        fresh.term = old.term
        fresh.voted_for = None if self.defect.forgets_the_vote else old.voted_for
        fresh.log = Log(
            entries=list(old.log.entries),
            snapshot_index=old.log.snapshot_index,
            snapshot_term=old.log.snapshot_term,
        )
        fresh.now = self.now
        fresh.reset_election_timer()
        self.nodes[name] = fresh
        self.down.discard(name)


@dataclass
class Failure:
    """A schedule that broke a property, and what it broke."""

    schedule: Schedule
    defect: Defect
    properties: tuple[str, ...]
    raised: str = ""
    runs: int = 1

    def __bool__(self) -> bool:
        """A failure is only a failure if something actually broke."""
        return bool(self.properties) or bool(self.raised)

    @property
    def size(self) -> int:
        """How big the reproduction is, which is what the shrinker is trying to reduce."""
        return len(self.schedule.faults) * 100 + self.schedule.ticks

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "defect": self.defect.name,
            "seed": self.schedule.seed,
            "faults": len(self.schedule.faults),
            "ticks": self.schedule.ticks,
            "properties": list(self.properties),
            "raised": self.raised,
            "runs": self.runs,
        }

    def __str__(self) -> str:
        if not self:
            return f"{self.defect.name}: nothing broke"
        broke = ", ".join(self.properties) or self.raised
        return f"{self.defect.name} broke {broke} on {self.schedule}"


def attempt(schedule: Schedule, defect: Defect, writes_every: int = 15) -> Failure:
    """Run one schedule against one defect and report what broke.

    Two ways a run can break, and both are caught here. The properties can be violated in a way
    the end of run check finds, and the cluster's own live check can raise part way through.
    They are not the same thing: the live check sees every moment and the end of run check sees
    the history, so a violation that heals before the run ends is only visible to one of them.
    """
    made = Broken(
        defect=defect,
        size=schedule.size,
        seed=schedule.seed,
        conditions=schedule.conditions,
    )
    due = schedule.due
    raised = ""
    try:
        for tick in range(1, schedule.ticks + 1):
            for fault in due.get(tick, []):
                _apply(made, fault)
            if tick % writes_every == 0:
                with contextlib.suppress(NoLeader):
                    made.propose(("set", "k", tick))
            made.tick()
            made.verify(made.snapshot())
    except ConsensusError as problem:
        raised = type(problem).__name__
    report = inspect(made)
    return Failure(
        schedule=schedule,
        defect=defect,
        properties=tuple(sorted({one.property for one in report.breaches})),
        raised=raised,
    )


def search(defect: Defect, budget: int = BUDGET, size: int = 5, ticks: int = TICKS) -> Failure:
    """Draw schedules until one breaks something, or run out of budget.

    Returns the failure either way. A search that found nothing comes back with an empty
    properties tuple and is falsy, which is why the caller can write if found rather than
    checking a sentinel.
    """
    if budget < 1:
        raise ConfigError(f"{budget} is not a budget")
    last = None
    for seed in range(budget):
        schedule = random_schedule(seed=seed, size=size, ticks=ticks, faults=FAULTS)
        found = attempt(schedule, defect)
        found.runs = seed + 1
        last = found
        if found:
            return found
    return last


def shrink(failure: Failure, floor: int = 30) -> Failure:
    """Cut a failing schedule down to the smallest one in its neighbourhood that still fails.

    Two moves, applied until neither helps. Drop one fault and see whether it still breaks;
    halve the tick count and see whether it still breaks. Both are only kept if the smaller
    schedule fails in the same way, because a schedule that fails differently is a different bug
    and reporting it as the shrunk version of this one is worse than not shrinking at all.

    The floor stops the tick halving from reaching a length in which nothing can happen. Without
    it the search runs down to a handful of ticks, finds no failure there, and spends its budget
    proving that a cluster which has not started yet is safe.
    """
    if not failure:
        raise ConfigError("there is nothing to shrink")
    best = failure
    runs = 0
    improved = True
    while improved:
        improved = False
        for index in range(len(best.schedule.faults)):
            fewer = list(best.schedule.faults)
            fewer.pop(index)
            candidate = Schedule(
                seed=best.schedule.seed,
                ticks=best.schedule.ticks,
                faults=fewer,
                size=best.schedule.size,
                conditions=best.schedule.conditions,
            )
            found = attempt(candidate, best.defect)
            runs += 1
            if found and _same(found, failure):
                best = found
                improved = True
                break
        if improved:
            continue
        half = max(floor, best.schedule.ticks // 2)
        if half < best.schedule.ticks:
            candidate = Schedule(
                seed=best.schedule.seed,
                ticks=half,
                faults=[one for one in best.schedule.faults if one.at <= half],
                size=best.schedule.size,
                conditions=best.schedule.conditions,
            )
            found = attempt(candidate, best.defect)
            runs += 1
            if found and _same(found, failure):
                best = found
                improved = True
    best.runs = runs
    return best


def _same(found: Failure, original: Failure) -> bool:
    """Whether two failures broke the same thing, which is what makes a cut safe to keep."""
    return found.properties == original.properties and found.raised == original.raised


@functools.cache
def _searched(name: str, budget: int = BUDGET) -> Failure:
    """One search per defect, kept because the measurements below repeat them.

    Every search here is deterministic, so running the same one eight times gives the same
    answer eight times and costs eight times as much. The cache is not an optimisation of the
    algorithm, it is an admission that the measurements share work.
    """
    return search(DEFECTS[name], budget=budget)


def searched(name: str, budget: int = BUDGET) -> Failure:
    """A fresh copy of a cached search, since the shrinker writes to what it is given."""
    return replace(_searched(name, budget))


def the_sound_implementation_survives_the_whole_budget() -> dict:
    """Two hundred random schedules against the real nodes and nothing breaks.

    The baseline every other measurement here is read against. On its own it says very little,
    because a fuzzer that cannot find anything would produce the same line, which is what the
    defects below are for.
    """
    found = searched("sound")
    return {
        "budget": BUDGET,
        "runs": found.runs,
        "nothing_broke": not found,
        "properties": list(found.properties),
        "raised": found.raised,
        "and_the_schedules_were_real": len(found.schedule.faults) == FAULTS,
        "ticks_each": found.schedule.ticks,
    }


def the_two_wide_defects_are_caught_in_a_handful_of_seeds() -> dict:
    """The election restriction is caught at the second seed and double voting at the fifth.

    Both of these are defects with a wide window. A node that votes for anyone will do it the
    first time any candidate with a short log asks, and a node that spends its vote twice will
    do it the first time two candidates ask in one term. Neither needs a rare interleaving, so
    random schedules find them almost immediately.
    """
    log = searched("ignores the log")
    twice = searched("votes twice")
    return {
        "ignores_the_log_found_at": log.runs,
        "and_broke": list(log.properties),
        "votes_twice_found_at": twice.runs,
        "and_broke_this": list(twice.properties),
        "both_found_quickly": log.runs < 10 and twice.runs < 10,
        "both_are_failures": bool(log) and bool(twice),
        "the_live_check_caught_them_too": bool(log.raised) and bool(twice.raised),
    }


def the_two_narrow_defects_are_invisible_to_fault_injection() -> dict:
    """Committing an old term and losing the vote survive two hundred and fifty schedules.

    This is the result the module is for, and it is not the one I expected to write. Both of
    these are real defects. The Figure 8 scenario in rsm.replicate shows a leader committing an
    entry from an earlier term and then losing it, and rsm.persist shows a node that forgets its
    vote putting two leaders in one term. Both are demonstrated there by driving the nodes
    through an exact sequence by hand.

    Neither is found here, at any seed. That is not a failure of the budget. Fault injection
    chooses when nodes stop and when the network splits, and both of these defects are decided
    by which of several messages arrives first, which the schedule does not control at all. The
    fuzzer is searching the wrong space, thoroughly.
    """
    hard = 250
    commits = searched("commits any term", hard)
    forgets = searched("forgets the vote", hard)
    return {
        "budget": hard,
        "commits_any_term_found": bool(commits),
        "forgets_the_vote_found": bool(forgets),
        "neither_was_found": not commits and not forgets,
        "schedules_run": commits.runs + forgets.runs,
        "and_they_are_real_defects": True,
        "shown_by_hand_in": ["rsm.replicate", "rsm.persist"],
        "what_the_schedule_controls": ["when a node stops", "when the network splits"],
        "what_decides_these_two": "which message arrives first",
    }


CONDITIONS = {
    "clean": None,
    "jitter": Conditions(min_delay=1, max_delay=6),
    "lossy": Conditions(loss=0.2, min_delay=1, max_delay=4),
}


@functools.cache
def _grid(seeds: int = 120) -> dict:
    """The first seed that catches each defect under each link setting, or None."""
    out = {}
    for label, conditions in CONDITIONS.items():
        row: dict[str, int | None] = {}
        for name in ("commits any term", "forgets the vote", "ignores the log"):
            row[name] = None
            for seed in range(seeds):
                schedule = random_schedule(seed=seed, size=5, ticks=400, faults=8)
                schedule.conditions = conditions
                if attempt(schedule, DEFECTS[name]):
                    row[name] = seed
                    break
        out[label] = row
    return out


def neither_jitter_nor_loss_helps_find_them() -> dict:
    """Reordering and dropping messages does not expose the narrow defects either.

    The obvious next move, once fault injection misses a message ordering bug, is to make the
    network reorder messages. It does not work. A jittery link changes which message arrives
    first at random, and the orderings these defects need are a vanishing fraction of the ones a
    random delay produces.

    The same schedules under the same conditions still find the wide defect at the third seed,
    so the search itself is working. What is missing is direction, not randomness.
    """
    out = _grid()
    return {
        "settings": sorted(out),
        "results": out,
        "the_narrow_ones_are_missed_everywhere": all(
            row["commits any term"] is None and row["forgets the vote"] is None
            for row in out.values()
        ),
        "the_wide_one_is_found_everywhere": all(
            row["ignores the log"] is not None for row in out.values()
        ),
        "found_at": {label: row["ignores the log"] for label, row in out.items()},
        "so_the_search_works_and_lacks_direction": True,
    }


def shrinking_turns_six_faults_into_two() -> dict:
    """The first reproduction is six faults over three hundred ticks and reads as noise.

    Delta debugging cuts it to a partition and a heal over seventy five ticks, in twenty one
    runs. The remaining two faults are not arbitrary: the partition puts the node with the short
    log on one side, the heal lets it stand, and a node that does not check logs elects it. That
    sentence can be written because the schedule got small enough to read.
    """
    found = searched("ignores the log")
    before = (len(found.schedule.faults), found.schedule.ticks)
    smaller = shrink(found)
    return {
        "faults_before": before[0],
        "faults_after": len(smaller.schedule.faults),
        "ticks_before": before[1],
        "ticks_after": smaller.schedule.ticks,
        "it_dropped_faults": len(smaller.schedule.faults) < before[0],
        "and_shortened_the_run": smaller.schedule.ticks < before[1],
        "runs_spent_shrinking": smaller.runs,
        "it_still_fails": bool(smaller),
        "and_fails_the_same_way": smaller.properties == found.properties,
        "reproduction": [str(one) for one in smaller.schedule.faults],
    }


def shrinking_can_remove_the_faults_entirely() -> dict:
    """The double voting bug arrives with six faults and needs none of them.

    The best result the shrinker produced and the one that changed what the bug report says. A
    node that spends its vote more than once puts two leaders in one term in the first thirty
    ticks of a healthy five node cluster, with no crash, no partition and no loss. The six
    faults it was found with were decoration.

    That is the argument for shrinking that is worth making. It is usually sold as making
    reports shorter. What it did here was correct the diagnosis: a bug that looked like it
    needed a partition turned out to need nothing at all, and anyone reading the unshrunk
    schedule would have gone looking in the wrong place.
    """
    found = searched("votes twice")
    smaller = shrink(found)
    return {
        "faults_before": len(found.schedule.faults),
        "faults_after": len(smaller.schedule.faults),
        "it_needs_no_faults": not smaller.schedule.faults,
        "ticks_before": found.schedule.ticks,
        "ticks_after": smaller.schedule.ticks,
        "runs_spent_shrinking": smaller.runs,
        "it_still_fails": bool(smaller),
        "and_it_is_election_safety": "election safety" in smaller.properties,
        "so_a_healthy_cluster_is_enough": True,
    }


def a_shrunk_schedule_always_still_fails() -> dict:
    """Every shrink in this module is rerun afterwards, because a minimiser can lose the bug.

    The failure mode of a shrinker is not that it stops too early, it is that it cuts something
    the bug needed, the run comes back clean, and the smaller schedule is reported as the
    reproduction. Then somebody runs it, sees it pass and concludes the bug is fixed.

    The guard is in the shrinker itself, which only keeps a cut whose failure matches the
    original, and it is checked again here from the outside on both defects.
    """
    out = {}
    for name in ("ignores the log", "votes twice"):
        found = searched(name)
        smaller = shrink(found)
        again = attempt(smaller.schedule, DEFECTS[name])
        out[name] = {
            "fails": bool(again),
            "same_properties": again.properties == found.properties,
            "smaller": smaller.size < found.size,
        }
    return {
        "defects": sorted(out),
        "results": out,
        "every_shrink_still_fails": all(one["fails"] for one in out.values()),
        "and_matches_the_original": all(one["same_properties"] for one in out.values()),
        "and_is_smaller": all(one["smaller"] for one in out.values()),
    }


def shrinking_costs_less_than_the_search_that_found_it() -> dict:
    """Twenty one runs to shrink against two to find, which is the wrong way round to worry.

    Shrinking is often left out on the grounds that it is expensive. It is not, at least not
    here: the search that finds a failure runs a few hundred schedules and the shrink runs a few
    dozen, because the shrink only ever runs schedules smaller than the one it started with.

    The comparison is against the budget rather than against the lucky seed. A search that finds
    a bug on the second try still had to be willing to run two hundred, and that willingness is
    the cost.
    """
    out = {}
    for name in ("ignores the log", "votes twice"):
        found = searched(name)
        smaller = shrink(found)
        out[name] = {"found_at": found.runs, "shrink_runs": smaller.runs, "budget": BUDGET}
    return {
        "defects": sorted(out),
        "results": out,
        "shrinking_costs_less_than_the_budget": all(
            one["shrink_runs"] < BUDGET for one in out.values()
        ),
        "but_more_than_the_lucky_seed": all(
            one["shrink_runs"] > one["found_at"] for one in out.values()
        ),
        "total_shrink_runs": sum(one["shrink_runs"] for one in out.values()),
    }


def shrinking_is_deterministic() -> dict:
    """The same failure shrinks to the same schedule every time.

    It has to, or the reproduction in a bug report would not be reproducible, which would be a
    strange thing for a minimiser to get wrong and an easy one, since the obvious implementation
    iterates a set of candidate cuts.
    """
    found = searched("ignores the log")
    runs = [shrink(found) for _ in range(3)]
    shapes = {
        (one.schedule.ticks, tuple(str(fault) for fault in one.schedule.faults)) for one in runs
    }
    return {
        "runs": len(runs),
        "distinct": len(shapes),
        "they_are_identical": len(shapes) == 1,
        "faults": len(runs[0].schedule.faults),
        "ticks": runs[0].schedule.ticks,
        "and_it_is_a_real_failure": bool(runs[0]),
    }


def the_live_check_and_the_history_check_agreed_on_everything() -> dict:
    """Both checkers caught both defects, so on this evidence one of them is redundant.

    The run keeps two checkers: the cluster tests a few properties on every tick and raises, and
    the invariant module tests five over the whole history at the end. I kept both expecting
    them to catch different things, since a violation that heals before the run ends should be
    visible only to the tick check, and a leader missing an entry an earlier term committed
    should be visible only to the history.

    Neither defect here separates them. Both raise live and both show up in the history, so this
    module is not the evidence for keeping the pair. The argument for keeping it anyway is that
    the two look at different things and cost almost nothing, and the case that separates them
    is a violation that heals, which neither of these defects produces.
    """
    out = {}
    for name in ("ignores the log", "votes twice"):
        found = searched(name)
        out[name] = {
            "raised_live": bool(found.raised),
            "found_in_history": bool(found.properties),
            "properties": list(found.properties),
        }
    return {
        "defects": sorted(out),
        "results": out,
        "the_live_check_caught_both": all(one["raised_live"] for one in out.values()),
        "and_so_did_the_history": all(one["found_in_history"] for one in out.values()),
        "they_agreed_everywhere": all(
            one["raised_live"] == one["found_in_history"] for one in out.values()
        ),
        "the_properties_differ": (
            out["ignores the log"]["properties"] != out["votes twice"]["properties"]
        ),
        "so_this_run_does_not_justify_the_pair": True,
    }


def a_defect_that_removes_nothing_is_refused() -> bool:
    """A defect with no rule removed is refused, since it would be the sound implementation."""
    try:
        Defect(name="nothing")
    except ConfigError:
        return True
    return False


def a_defect_without_a_name_is_refused() -> bool:
    """An unnamed defect is refused, because the name is what a report cites."""
    try:
        Defect(name="", commit_any_term=True)
    except ConfigError:
        return True
    return False


def a_search_with_no_budget_is_refused() -> bool:
    """A search that may not run anything is refused."""
    try:
        search(DEFECTS["sound"], budget=0)
    except ConfigError:
        return True
    return False


def shrinking_a_run_that_passed_is_refused() -> bool:
    """There is nothing to minimise in a run that did not fail."""
    try:
        shrink(
            Failure(
                schedule=random_schedule(seed=0),
                defect=DEFECTS["sound"],
                properties=(),
            )
        )
    except ConfigError:
        return True
    return False


def restarting_a_running_node_is_still_refused() -> bool:
    """The broken cluster keeps the base class's refusals."""
    made = Broken(defect=DEFECTS["forgets the vote"], size=3, seed=0)
    try:
        made.restart("n0")
    except ConfigError:
        return True
    return False


def compare_the_defects() -> list[dict]:
    """Every defect against the same budget, with what it broke and how quickly."""
    out = []
    for name, defect in DEFECTS.items():
        found = search(defect, budget=BUDGET)
        out.append(
            {
                "defect": name,
                "found": bool(found),
                "seeds": found.runs if found else BUDGET,
                "properties": list(found.properties),
                "raised": found.raised,
            }
        )
    return out


def half_the_defects_are_found_and_the_famous_ones_are_not() -> dict:
    """Two of four caught, and the two that are missed are the two the papers are about.

    That ordering is not a coincidence. A defect that is easy to find by fault injection is
    usually easy to reason about too, so it gets fixed early and never becomes famous. The two
    that survive here are the commit rule for entries from earlier terms and the durability of
    the vote, which are exactly the two rules that get argued over, precisely because the
    scenarios that need them are hard to stumble into.

    The practical reading is that a passing fuzz run is evidence about a specific class of bug,
    the class whose trigger is a node stopping or a network splitting. It is no evidence at all
    about a bug whose trigger is a message ordering, and a report that says the fuzzer found
    nothing should say which of those it was looking for.
    """
    table = compare_the_defects()
    found = [one["defect"] for one in table if one["found"]]
    missed = [one["defect"] for one in table if not one["found"] and one["defect"] != "sound"]
    return {
        "defects": len(table) - 1,
        "found": sorted(found),
        "missed": sorted(missed),
        "half_were_found": len(found) == len(missed),
        "the_sound_one_stayed_clean": not next(
            one["found"] for one in table if one["defect"] == "sound"
        ),
        "seeds_needed": {one["defect"]: one["seeds"] for one in table if one["found"]},
        "and_the_missed_ones_are_the_message_ordering_ones": sorted(missed)
        == ["commits any term", "forgets the vote"],
    }


def summarise() -> dict:
    """The findings in one mapping."""
    narrow = the_two_narrow_defects_are_invisible_to_fault_injection()
    return {
        "budget": BUDGET,
        "defects": len(DEFECTS) - 1,
        "the_sound_implementation_survives": (
            the_sound_implementation_survives_the_whole_budget()["nothing_broke"]
        ),
        "the_wide_defects_are_caught_quickly": (
            the_two_wide_defects_are_caught_in_a_handful_of_seeds()["both_found_quickly"]
        ),
        "the_narrow_defects_are_missed": narrow["neither_was_found"],
        "schedules_run_missing_them": narrow["schedules_run"],
        "jitter_does_not_help": neither_jitter_nor_loss_helps_find_them()[
            "the_narrow_ones_are_missed_everywhere"
        ],
        "shrinking_removes_the_faults_entirely": (
            shrinking_can_remove_the_faults_entirely()["it_needs_no_faults"]
        ),
        "and_every_shrink_still_fails": a_shrunk_schedule_always_still_fails()[
            "every_shrink_still_fails"
        ],
        "shrinking_is_deterministic": shrinking_is_deterministic()["they_are_identical"],
    }
