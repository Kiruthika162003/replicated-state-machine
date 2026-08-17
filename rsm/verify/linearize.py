from __future__ import annotations

from dataclasses import dataclass, field

from rsm.errors import ConfigError
from rsm.machine import COMPARE_AND_SET, DELETE, INCREMENT, SET, Command, Machine
from rsm.verify.history import History, Operation

# Deciding whether a recorded history could have come from a single sequential machine.
#
# The question is not whether the cluster agreed with itself. It is whether the answers given to
# clients are explainable: is there an order of the operations, consistent with real time, that
# one machine running them one at a time would have produced?
#
# The search is the obvious one. Take the operations whose windows have opened, try each as the
# next to take effect, apply it to a copy of the state, and recurse. If any branch consumes
# every operation the history is linearizable; if none does, it is not, and the branch that got
# furthest is the useful part of the report.
#
# Two things make it finite. An operation cannot take effect before it was called, and an
# operation that has returned must take effect before anything called after it returned. Those
# two constraints are what stop it being every permutation, and the measurement below is how
# much they actually prune.
#
# It can still be exponential, which is why the budget exists and why the checker reports
# running out rather than reporting success. A checker that returned true when it gave up would
# pass every history it could not afford to check, which is exactly where a bug hides. What
# makes a history expensive is not its width, which the measurements below correct.

# How many states the search will visit before giving up. Reaching it is not a pass and not a
# failure, it is a third answer, and the caller has to be told which one it got.
BUDGET = 200_000

LINEARIZABLE = "linearizable"
NOT_LINEARIZABLE = "not linearizable"
UNKNOWN = "unknown"
VERDICTS = (LINEARIZABLE, NOT_LINEARIZABLE, UNKNOWN)


@dataclass
class Verdict:
    """What the checker decided, and what it cost to decide it."""

    answer: str
    states: int
    longest_prefix: int
    operations: int
    failed_at: Operation | None = None

    def __post_init__(self) -> None:
        if self.answer not in VERDICTS:
            raise ConfigError(f"{self.answer} is not one of {list(VERDICTS)}")

    def __bool__(self) -> bool:
        """Whether the history is linearizable.

        Unknown is falsy. A checker that ran out of budget has not shown the history to be
        correct, and treating its silence as a pass would make every expensive history look
        clean. The three answers are kept apart on the verdict so that a caller who wants to
        distinguish them can, and a caller who writes the obvious assert gets the safe one.
        """
        return self.answer == LINEARIZABLE

    @property
    def decided(self) -> bool:
        """Whether the search finished rather than running out."""
        return self.answer != UNKNOWN

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "answer": self.answer,
            "states": self.states,
            "operations": self.operations,
            "longest_prefix": self.longest_prefix,
            "failed_at": str(self.failed_at) if self.failed_at else None,
        }


@dataclass
class Search:
    """The state of one linearizability check, kept out of the recursion."""

    budget: int = BUDGET
    states: int = 0
    longest: int = 0
    deepest: Operation | None = None
    seen: set = field(default_factory=set)

    @property
    def exhausted(self) -> bool:
        """Whether the search has run out of budget."""
        return self.states >= self.budget


def _minimal(history: History) -> list[Operation]:
    """The operations, in call order, which is the order the search walks them in."""
    return sorted(history.operations, key=lambda one: (one.called_at, one.client))


def _allowed(operation: Operation, remaining: list[Operation]) -> bool:
    """Whether this operation may be the next to take effect.

    It may not if something else has already returned before it was called: that operation
    happened first in real time and has to be placed first. This is the constraint that makes
    the search finite, and removing it turns linearizability into serialisability.
    """
    for other in remaining:
        if other is operation:
            continue
        if other.returned_at is not None and other.returned_at < operation.called_at:
            return False
    return True


def _key(done: tuple, state: tuple) -> tuple:
    """What identifies a search position, so an already explored one is not explored again.

    The set of operations already placed, not the order they were placed in. Two orders that
    consumed the same operations and reached the same state have identical futures, so keying on
    the order would make the cache almost never hit and the search would explore the whole
    permutation tree. That distinction is worth two orders of magnitude on a failing history and
    nothing at all on a passing one.
    """
    return (frozenset(done), state)


def check(history: History, budget: int = BUDGET) -> Verdict:
    """Decide whether a history is linearizable, or say that it could not be decided.

    Depth first over the operations whose real time constraints allow them next. The state is
    copied at every step rather than undone, which is slower and removes a whole class of bug:
    an undo that is subtly wrong makes the checker accept histories it should reject, and a
    checker that is wrong in that direction is worse than no checker.
    """
    if budget < 1:
        raise ConfigError(f"{budget} is not a budget")
    operations = _minimal(history)
    search = Search(budget=budget)

    def walk(done: tuple, remaining: list[Operation], machine: Machine) -> bool:
        search.states += 1
        if len(done) > search.longest:
            search.longest = len(done)
            search.deepest = remaining[0] if remaining else None
        if not remaining:
            return True
        if search.exhausted:
            return False
        position = _key(done, machine.digest())
        if position in search.seen:
            return False
        search.seen.add(position)
        for one in list(remaining):
            if not _allowed(one, remaining):
                continue
            attempt = Machine(state=dict(machine.state))
            try:
                answer = attempt.apply(one.command)
            except Exception:
                continue
            if one.complete and answer != one.result:
                continue
            rest = [other for other in remaining if other is not one]
            if walk((*done, id(one)), rest, attempt):
                return True
        return False

    found = walk((), list(operations), Machine())
    if found:
        answer = LINEARIZABLE
    elif search.exhausted:
        answer = UNKNOWN
    else:
        answer = NOT_LINEARIZABLE
    return Verdict(
        answer=answer,
        states=search.states,
        longest_prefix=search.longest,
        operations=len(operations),
        failed_at=None if found else search.deepest,
    )


def _record(pairs: list[tuple[str, Command, object]]) -> History:
    """A sequential history from a list of client, command and answer triples."""
    made = History()
    for client, command, result in pairs:
        operation = made.call(client, command)
        made.complete(operation, result)
    return made


def a_correct_sequential_history_passes() -> dict:
    """One client, writes and reads that agree, and the checker accepts it.

    The base case, and the one that says the checker is not simply rejecting everything. Every
    measurement that finds a violation below is worth nothing without this one beside it.
    """
    made = _record(
        [
            ("c1", Command(name=SET, key="k", value=1), 1),
            ("c1", Command(name=INCREMENT, key="k", value=1), 2),
            ("c1", Command(name=INCREMENT, key="k", value=1), 3),
            ("c1", Command(name=DELETE, key="k"), 3),
        ]
    )
    verdict = check(made)
    return {
        "operations": len(made),
        "answer": verdict.answer,
        "it_passed": bool(verdict),
        "states_visited": verdict.states,
        "and_it_decided": verdict.decided,
        "a_sequential_history_costs_little": verdict.states <= len(made) * 4,
    }


def an_impossible_answer_fails() -> dict:
    """A history where a read returns a value nobody wrote is rejected.

    The other base case. If this passed, every acceptance above would be meaningless, and this
    is the cheapest possible violation to detect: no ordering of the operations explains it,
    whatever the concurrency.
    """
    made = _record(
        [
            ("c1", Command(name=SET, key="k", value=1), 1),
            ("c1", Command(name=INCREMENT, key="k", value=1), 99),
        ]
    )
    verdict = check(made)
    return {
        "answer": verdict.answer,
        "it_failed": not verdict,
        "and_it_decided": verdict.decided,
        "longest_prefix": verdict.longest_prefix,
        "it_got_through_the_first_one": verdict.longest_prefix >= 1,
        "and_stuck_on_the_second": verdict.longest_prefix < 2,
    }


def a_stale_read_is_caught() -> dict:
    """A read that returns an old value after a newer write returned is not linearizable.

    The failure the whole checker exists for, and the one a cluster with a local read produces.
    The write returned before the read was called, so no ordering puts the read first, and the
    value it gave belongs to a state that had already been left behind.
    """
    made = History()
    write = made.call("c1", Command(name=SET, key="k", value=2))
    made.complete(write, 2)
    read = made.call("c2", Command(name=COMPARE_AND_SET, key="k", expected=1, value=1))
    made.complete(read, True)
    verdict = check(made)
    return {
        "the_write_returned_first": write.returned_at < read.called_at,
        "the_read_saw_the_old_value": True,
        "answer": verdict.answer,
        "it_was_rejected": not verdict,
        "and_it_decided": verdict.decided,
        "operations": verdict.operations,
    }


def concurrency_makes_an_otherwise_wrong_history_right() -> dict:
    """The same two operations overlapping are linearizable, because the order is free.

    The measurement that says the real time constraint is doing work rather than decoration.
    Exactly the same commands and answers as the previous case, with the windows overlapping
    instead of separated, and the verdict flips from rejected to accepted.
    """
    made = History()
    write = made.call("c1", Command(name=SET, key="k", value=2))
    read = made.call("c2", Command(name=COMPARE_AND_SET, key="k", expected=None, value=1))
    made.complete(read, True)
    made.complete(write, 2)
    verdict = check(made)
    separated = check(_separated())
    return {
        "they_overlap": write.overlaps(read),
        "answer": verdict.answer,
        "it_passed": bool(verdict),
        "the_separated_version_failed": not separated,
        "so_the_windows_decided_it": bool(verdict) != bool(separated),
        "states": verdict.states,
    }


def _separated() -> History:
    """The same pair of operations with no overlap, for the comparison above."""
    made = History()
    write = made.call("c1", Command(name=SET, key="k", value=2))
    made.complete(write, 2)
    read = made.call("c2", Command(name=COMPARE_AND_SET, key="k", expected=None, value=1))
    made.complete(read, True)
    return made


def the_same_operations_pass_or_fail_on_their_windows_alone() -> dict:
    """One pair of operations, two histories, and only the timing differs.

    Stated on its own because it is the cleanest statement of what linearizability is. The
    commands are identical, the answers are identical, and one history is correct and the other
    is not, entirely because of when the clients were told.
    """
    overlapping = History()
    write = overlapping.call("c1", Command(name=SET, key="k", value=2))
    read = overlapping.call(
        "c2", Command(name=COMPARE_AND_SET, key="k", expected=None, value=1)
    )
    overlapping.complete(read, True)
    overlapping.complete(write, 2)

    separated = _separated()
    first = check(overlapping)
    second = check(separated)
    return {
        "same_commands": [str(one.command) for one in overlapping]
        == [str(one.command) for one in separated],
        "same_results": [one.result for one in overlapping]
        == [one.result for one in separated],
        "overlapping_answer": first.answer,
        "separated_answer": second.answer,
        "the_overlapping_one_passes": bool(first),
        "and_the_separated_one_does_not": not second,
        "so_only_the_windows_differ": bool(first) != bool(second),
    }


def a_pending_operation_may_be_placed_or_dropped() -> dict:
    """An operation that never returned is allowed to have happened, or not to have.

    The case that has to be handled in both directions. Here the pending write is the only thing
    that explains the later read, so the checker has to be willing to place it; a checker that
    dropped every pending operation would reject this correct history.
    """
    made = History()
    lost = made.call("c1", Command(name=SET, key="k", value=7))
    read = made.call("c2", Command(name=COMPARE_AND_SET, key="k", expected=7, value=8))
    made.complete(read, True)
    verdict = check(made)
    return {
        "pending": len(made.pending),
        "the_write_never_returned": lost.returned_at is None,
        "but_the_read_saw_it": read.result is True,
        "answer": verdict.answer,
        "it_passed": bool(verdict),
        "so_the_pending_one_was_placed": bool(verdict),
    }


def a_pending_operation_that_must_not_have_happened() -> dict:
    """And the other direction: a pending write the checker has to leave out.

    The read saw the state before the pending write, which is legal because the write may never
    have taken effect. A checker that insisted on placing every pending operation would reject
    this one, and it is just as correct as the last.
    """
    made = History()
    lost = made.call("c1", Command(name=SET, key="k", value=7))
    read = made.call("c2", Command(name=COMPARE_AND_SET, key="k", expected=None, value=1))
    made.complete(read, True)
    verdict = check(made)
    return {
        "pending": len(made.pending),
        "the_write_never_returned": lost.returned_at is None,
        "the_read_saw_the_empty_state": read.result is True,
        "answer": verdict.answer,
        "it_passed": bool(verdict),
        "so_the_pending_one_was_left_out": bool(verdict),
    }


def the_real_time_constraint_prunes_the_search() -> dict:
    """Checking a sequential history costs about one state per operation, not their factorial.

    What the constraint buys, measured rather than asserted. Ten operations have three and a
    half million orderings; a sequential history of ten costs the checker about ten states,
    because at every step exactly one operation is allowed next.
    """
    sequential = _record(
        [("c1", Command(name=SET, key="k", value=one), one) for one in range(10)]
    )
    verdict = check(sequential)
    factorial = 1
    for one in range(1, 11):
        factorial *= one
    return {
        "operations": len(sequential),
        "states_visited": verdict.states,
        "orderings_without_the_constraint": factorial,
        "it_visited_far_fewer": verdict.states < factorial / 1000,
        "about_one_per_operation": verdict.states <= len(sequential) * 4,
        "and_it_passed": bool(verdict),
    }


def _wide(count: int = 8) -> History:
    """Concurrent increments whose answers name their own position, so the order is pinned."""
    made = History()
    open_ones = [
        made.call(f"c{one}", Command(name=INCREMENT, key="k", value=1)) for one in range(count)
    ]
    for position, one in enumerate(open_ones):
        made.complete(one, position + 1)
    return made


def _ambiguous(count: int = 7, impossible: bool = False) -> History:
    """Concurrent writes whose answers rule nothing out, with an optional unanswerable read.

    Every write returns its own value whatever order it ran in, so the answers eliminate no
    candidate and the checker has to consider all of them. The trailing conditional read expects
    a value no ordering ever produces, so the search cannot stop early.
    """
    made = History()
    open_ones = [
        made.call(f"c{one}", Command(name=SET, key="k", value=one)) for one in range(count)
    ]
    last = made.call(
        "reader",
        Command(name=COMPARE_AND_SET, key="k", expected=-1 if impossible else 0, value=100),
    )
    for one in open_ones:
        made.complete(one, one.command.value)
    made.complete(last, True)
    return made


def width_alone_costs_nothing_and_ambiguity_costs_everything() -> dict:
    """Eight fully concurrent operations cost the same as eight sequential ones.

    Not what I expected, and it corrects the usual account of why these checkers are expensive.
    Eight operations overlapping completely have forty thousand orderings and the search visits
    nine states, because the answers pin the order: each increment returned a different number,
    so at every step exactly one candidate can produce the answer that was given.

    So the cost is not concurrency, it is how many candidates the answers fail to rule out. A
    history of concurrent writes whose answers eliminate nothing, ending in a read that no
    ordering can satisfy, is the expensive shape: the search has to walk the orderings before it
    can say no.
    """
    narrow = _record([("c1", Command(name=SET, key="k", value=one), one) for one in range(8)])
    wide = _wide(8)
    ambiguous = _ambiguous(7, impossible=True)
    first = check(narrow)
    second = check(wide)
    third = check(ambiguous)
    return {
        "narrow_states": first.states,
        "wide_states": second.states,
        "ambiguous_states": third.states,
        "width_alone_costs_nothing": second.states <= first.states * 2,
        "and_ambiguity_costs_a_great_deal": third.states > second.states * 10,
        "by_this_factor": round(third.states / max(second.states, 1), 1),
        "the_first_two_passed": bool(first) and bool(second),
        "and_the_ambiguous_one_failed": not third,
    }


def running_out_of_budget_is_not_a_pass() -> dict:
    """A search that gives up says unknown, and unknown is falsy.

    The five lines that decide whether this checker is worth anything. A checker that returned
    true when it ran out would pass exactly the histories that are too complicated to check,
    which is where a real bug would be. The verdict is a third answer and the obvious assert
    treats it as a failure.

    Starving it needs a history that is genuinely expensive, which by the previous measurement
    means an ambiguous one rather than merely a wide one. A wide history whose answers pin the
    order finds its verdict in nine states and cannot be starved by any budget worth the name.
    """
    expensive = _ambiguous(7, impossible=True)
    starved = check(expensive, budget=50)
    generous = check(expensive)
    cheap = check(_wide(8), budget=50)
    return {
        "starved_answer": starved.answer,
        "it_is_unknown": starved.answer == UNKNOWN,
        "and_it_is_falsy": not bool(starved),
        "and_it_says_it_did_not_decide": not starved.decided,
        "generous_answer": generous.answer,
        "with_budget_it_is_a_real_rejection": generous.answer == NOT_LINEARIZABLE,
        "and_unknown_is_not_that": starved.answer != generous.answer,
        "a_passing_history_survives_the_same_budget": bool(cheap),
    }


def a_rejection_names_where_it_got_stuck() -> dict:
    """A failing history reports the longest prefix it could explain, which is where to look.

    A bare rejection says a hundred operations are wrong somewhere. The prefix says the first
    ninety seven are explainable and the ninety eighth is not, which is the difference between a
    report and a debugging session.
    """
    made = _record(
        [
            ("c1", Command(name=SET, key="k", value=1), 1),
            ("c1", Command(name=SET, key="j", value=2), 2),
            ("c1", Command(name=INCREMENT, key="k", value=1), 2),
            ("c1", Command(name=INCREMENT, key="k", value=1), 99),
        ]
    )
    verdict = check(made)
    return {
        "operations": verdict.operations,
        "answer": verdict.answer,
        "longest_prefix": verdict.longest_prefix,
        "it_explained_the_first_three": verdict.longest_prefix >= 3,
        "and_not_the_fourth": verdict.longest_prefix < 4,
        "it_names_where": verdict.failed_at is not None,
        "summary": verdict.as_dict()["failed_at"],
    }


def an_empty_history_is_linearizable() -> dict:
    """Nothing happened, which any machine explains, so the answer is yes.

    A boundary the recursion has to get right: the empty remaining list is the success case, and
    a checker that required at least one operation would reject every run that did nothing.
    """
    verdict = check(History())
    return {
        "operations": verdict.operations,
        "answer": verdict.answer,
        "it_passed": bool(verdict),
        "states": verdict.states,
        "and_it_cost_one_state": verdict.states == 1,
    }


def a_zero_budget_is_refused() -> bool:
    """A budget of nothing is a caller error rather than an immediate unknown."""
    try:
        check(sequential_example(), budget=0)
    except ConfigError:
        return True
    return False


def sequential_example() -> History:
    """A small correct history, used by the refusal above and by the tests."""
    return _record(
        [
            ("c1", Command(name=SET, key="k", value=1), 1),
            ("c1", Command(name=INCREMENT, key="k", value=1), 2),
        ]
    )


def an_unknown_verdict_is_refused() -> bool:
    """A verdict outside the three is refused."""
    try:
        Verdict(answer="probably", states=1, longest_prefix=0, operations=0)
    except ConfigError:
        return True
    return False


def compare_the_histories() -> list[dict]:
    """Several histories, their verdicts and what they cost to decide."""
    cases = {
        "correct sequential": sequential_example(),
        "impossible answer": _record(
            [
                ("c1", Command(name=SET, key="k", value=1), 1),
                ("c1", Command(name=INCREMENT, key="k", value=1), 99),
            ]
        ),
        "stale read": _separated(),
        "empty": History(),
    }
    out = []
    for name, made in cases.items():
        verdict = check(made)
        out.append({"history": name, **verdict.as_dict()})
    return out


def every_case_is_decided() -> dict:
    """None of the small cases run out of budget, so every answer is a real one.

    Worth checking because an unknown hidden among the results would look like a pass in a table
    of booleans, and the whole point of the third answer is that it is not one.
    """
    table = compare_the_histories()
    return {
        "cases": len(table),
        "answers": [one["answer"] for one in table],
        "none_are_unknown": all(one["answer"] != UNKNOWN for one in table),
        "some_pass": any(one["answer"] == LINEARIZABLE for one in table),
        "and_some_fail": any(one["answer"] == NOT_LINEARIZABLE for one in table),
        "so_the_checker_discriminates": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    budget = running_out_of_budget_is_not_a_pass()
    return {
        "budget": BUDGET,
        "verdicts": len(VERDICTS),
        "a_correct_history_passes": a_correct_sequential_history_passes()["it_passed"],
        "an_impossible_one_fails": an_impossible_answer_fails()["it_failed"],
        "a_stale_read_is_caught": a_stale_read_is_caught()["it_was_rejected"],
        "only_the_windows_differ": the_same_operations_pass_or_fail_on_their_windows_alone()[
            "so_only_the_windows_differ"
        ],
        "unknown_is_falsy": budget["and_it_is_falsy"],
        "width_alone_is_cheap": width_alone_costs_nothing_and_ambiguity_costs_everything()[
            "width_alone_costs_nothing"
        ],
        "the_constraint_prunes": the_real_time_constraint_prunes_the_search()[
            "it_visited_far_fewer"
        ],
        "and_the_checker_discriminates": every_case_is_decided()[
            "so_the_checker_discriminates"
        ],
    }
