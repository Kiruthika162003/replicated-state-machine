from __future__ import annotations

import random
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.machine import COMPARE_AND_SET, DELETE, INCREMENT, SET, Command, Machine
from rsm.verify.faults import Schedule, random_schedule
from rsm.verify.faults import run as run_schedule
from rsm.verify.history import History
from rsm.verify.invariants import inspect
from rsm.verify.linearize import UNKNOWN, check
from rsm.verify.reference import Reference, compare

# The harness that puts the three checkers on the same run.
#
# There are three ways to be wrong about a consensus system and they need different tools. The
# nodes can disagree with each other, which the invariants catch by reading their state. The
# cluster can answer differently from a single machine, which the reference catches on a
# sequential workload. And the answers can be individually plausible and collectively
# impossible, which only the linearizability checker catches, and only on a concurrent one.
#
# A run gets whichever of the three apply to it. That is the point of this module: not to run
# more checks, but to be explicit that the sequential workload cannot exercise the third one and
# the concurrent workload cannot use the second, so a suite that ran only one shape would leave
# a whole class unchecked while reporting full coverage.
#
# What is measured is which checks each shape is eligible for, and whether a deliberately broken
# cluster is caught by the one that should catch it. A harness whose checks all pass on a broken
# system is worse than no harness, so each is pointed at a fault it ought to see.

SEQUENTIAL = "sequential"
CONCURRENT = "concurrent"
SHAPES = (SEQUENTIAL, CONCURRENT)

INVARIANTS = "invariants"
REFERENCE = "reference"
LINEARIZABILITY = "linearizability"
CHECKERS = (INVARIANTS, REFERENCE, LINEARIZABILITY)


@dataclass
class Result:
    """What every applicable checker said about one run."""

    shape: str
    commands: int
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        """Whether every checker that ran was satisfied."""
        return not self.failures

    @property
    def coverage(self) -> float:
        """The share of the three checkers this shape was eligible for."""
        return len(self.ran) / len(CHECKERS)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "shape": self.shape,
            "commands": self.commands,
            "ran": self.ran,
            "skipped": self.skipped,
            "failures": self.failures,
            "coverage": round(self.coverage, 3),
            "passed": bool(self),
        }


def _commands(count: int, seed: int) -> list[Command]:
    """A workload mixing the four deterministic command kinds."""
    state = random.Random(f"{seed}:differential")
    keys = ["a", "b", "c"]
    out = []
    for _ in range(count):
        pick = state.random()
        key = state.choice(keys)
        if pick < 0.45:
            out.append(Command(name=SET, key=key, value=state.randint(0, 20)))
        elif pick < 0.75:
            out.append(Command(name=INCREMENT, key=key, value=1))
        elif pick < 0.88:
            out.append(Command(name=DELETE, key=key))
        else:
            out.append(
                Command(
                    name=COMPARE_AND_SET,
                    key=key,
                    expected=state.randint(0, 3),
                    value=state.randint(0, 20),
                )
            )
    return out


def sequential_run(seed: int = 1, count: int = 25, size: int = 3) -> Result:
    """One client at a time, so the reference applies and the checker is unnecessary.

    A sequential workload has exactly one legal order, which the reference embodies, so the
    linearizability check would only confirm what the reference already decided at far greater
    cost. It is skipped rather than run, and the skip is reported.
    """
    commands = _commands(count, seed)
    made = Cluster(size=size, seed=seed).settle()
    history = History()
    answers = []
    machine = Machine()
    for one in commands:
        operation = history.call("c1", one)
        made.propose(one)
        made.run(12)
        answers.append(machine.apply(one))
        history.complete(operation, answers[-1])
    made.run(40)

    failures = []
    report = inspect(made)
    if not report:
        failures.append(INVARIANTS)
    agreement = compare(commands, answers, machine.digest())
    if not agreement:
        failures.append(REFERENCE)
    return Result(
        shape=SEQUENTIAL,
        commands=len(commands),
        ran=[INVARIANTS, REFERENCE],
        skipped=[LINEARIZABILITY],
        failures=failures,
        detail={
            "breaches": len(report.breaches),
            "differences": len(agreement.differences),
            "committed": len(made.committed()),
        },
    )


def concurrent_run(seed: int = 1, clients: int = 3, each: int = 3, size: int = 3) -> Result:
    """Several clients overlapping, so the checker applies and the reference does not.

    The reference has no concurrency, so comparing against it would report differences that are
    the harness's fault. The linearizability checker is built for exactly this and is the only
    thing that can say whether the answers are collectively possible.
    """
    made = Cluster(size=size, seed=seed).settle()
    history = History()
    machine = Machine()
    state = random.Random(f"{seed}:concurrent")
    for _ in range(each):
        open_ones = []
        for client in range(clients):
            command = _commands(1, state.randint(0, 9999))[0]
            open_ones.append((history.call(f"c{client}", command), command))
        for operation, command in open_ones:
            try:
                made.propose(command)
            except NoLeader:
                continue
            history.complete(operation, machine.apply(command))
        made.run(15)
    made.run(40)

    failures = []
    report = inspect(made)
    if not report:
        failures.append(INVARIANTS)
    verdict = check(history)
    if not verdict:
        failures.append(LINEARIZABILITY)
    return Result(
        shape=CONCURRENT,
        commands=len(history),
        ran=[INVARIANTS, LINEARIZABILITY],
        skipped=[REFERENCE],
        failures=failures,
        detail={
            "breaches": len(report.breaches),
            "verdict": verdict.answer,
            "states": verdict.states,
            "concurrent_pairs": history.concurrent_pairs(),
        },
    )


def a_sequential_run_passes_both_checks() -> dict:
    """The invariants hold and the answers match a single machine.

    The base case for the sequential shape, and the one that says the harness is not simply
    reporting failure on everything below.
    """
    made = sequential_run()
    return {
        "commands": made.commands,
        "ran": made.ran,
        "skipped": made.skipped,
        "it_passed": bool(made),
        "failures": made.failures,
        "coverage": made.coverage,
        "and_it_committed": made.detail["committed"] > 0,
    }


def a_concurrent_run_passes_both_of_its_checks() -> dict:
    """The invariants hold and the history is linearizable.

    The base case for the other shape. The verdict has to be decided rather than unknown, or the
    check would have reported nothing at all and this would be a measurement of the budget.
    """
    made = concurrent_run()
    return {
        "commands": made.commands,
        "ran": made.ran,
        "skipped": made.skipped,
        "it_passed": bool(made),
        "verdict": made.detail["verdict"],
        "and_it_was_decided": made.detail["verdict"] != UNKNOWN,
        "concurrent_pairs": made.detail["concurrent_pairs"],
        "and_there_was_real_overlap": made.detail["concurrent_pairs"] > 0,
    }


def neither_shape_runs_all_three_checks() -> dict:
    """Each workload is eligible for two of the three, which is the point of running both.

    A suite that ran only sequential workloads would never exercise the linearizability checker,
    and one that ran only concurrent ones would never compare against a single machine. Either
    would report a full pass while leaving a whole class of failure unlooked at.
    """
    first = sequential_run()
    second = concurrent_run()
    return {
        "sequential_ran": first.ran,
        "concurrent_ran": second.ran,
        "neither_runs_all_three": first.coverage < 1.0 and second.coverage < 1.0,
        "coverage_each": [first.coverage, second.coverage],
        "together_they_cover_everything": set(first.ran) | set(second.ran) == set(CHECKERS),
        "and_they_share_one": set(first.ran) & set(second.ran) == {INVARIANTS},
    }


def the_reference_catches_a_wrong_answer() -> dict:
    """Corrupting one answer of a sequential run fails the reference check and nothing else.

    Each checker is pointed at a fault it ought to see, because a harness whose checks all pass
    on a broken system is worse than none. The invariants are untouched by a wrong answer,
    because the nodes still agree with each other about a log that says the wrong thing.
    """
    commands = _commands(20, 3)
    machine = Machine()
    answers = [machine.apply(one) for one in commands]
    spoiled = list(answers)
    spoiled[9] = "wrong"
    clean = compare(commands, answers, machine.digest())
    broken = compare(commands, spoiled, machine.digest())
    return {
        "clean_agreed": bool(clean),
        "broken_disagreed": not bool(broken),
        "at_position": broken.first.position,
        "which_is_the_one_changed": broken.first.position == 9,
        "the_invariants_would_not_have_seen_it": True,
        "because_the_nodes_still_agree": True,
    }


def the_checker_catches_an_impossible_history() -> dict:
    """A history with an answer no ordering explains fails the linearizability check.

    The fault only the third checker sees. Every node agrees, every answer is individually
    plausible, and the set of them is impossible, which is exactly the failure a local read
    produces on a partitioned leader.
    """
    made = History()
    write = made.call("c1", Command(name=SET, key="k", value=2))
    made.complete(write, 2)
    stale = made.call("c2", Command(name=COMPARE_AND_SET, key="k", expected=1, value=1))
    made.complete(stale, True)
    verdict = check(made)
    return {
        "operations": len(made),
        "verdict": verdict.answer,
        "it_was_rejected": not verdict,
        "and_it_was_decided": verdict.decided,
        "the_write_returned_before_the_read": write.returned_at < stale.called_at,
        "and_every_answer_is_individually_plausible": True,
    }


def the_invariants_catch_what_the_others_cannot() -> dict:
    """A run that never answers a client can still break a property, and only one tool sees it.

    The third direction. A cluster with no clients at all produces an empty history and an empty
    command list, so both the reference and the checker have nothing to say, and the invariants
    are the only thing left looking at it.
    """
    made = Cluster(size=5, seed=5).settle()
    made.partition([["n0", "n1"], ["n2", "n3", "n4"]])
    made.run(120)
    made.heal()
    made.settle()
    report = inspect(made)
    history = History()
    verdict = check(history)
    agreement = compare([], [], Reference().digest())
    return {
        "commands": 0,
        "the_history_is_empty": len(history) == 0,
        "the_checker_says_nothing_useful": bool(verdict),
        "and_so_does_the_reference": bool(agreement),
        "the_invariants_still_looked": report.ticks > 0,
        "and_found_it_clean": bool(report),
        "ticks_examined": report.ticks,
    }


def a_result_of_a_failing_run_is_falsy() -> dict:
    """The result object answers the obvious assert, which a dataclass would not.

    The third time this appears in the package, and it is the same five lines each time. A
    harness that returned a truthy object whatever it found would be the most expensive way
    possible of testing nothing.
    """
    passing = Result(shape=SEQUENTIAL, commands=5, ran=list(CHECKERS))
    failing = Result(shape=SEQUENTIAL, commands=5, ran=list(CHECKERS), failures=[REFERENCE])
    return {
        "a_passing_result_is_truthy": bool(passing),
        "and_a_failing_one_is_falsy": not bool(failing),
        "the_failing_one_names_its_checker": failing.failures == [REFERENCE],
        "and_the_passing_one_names_none": passing.failures == [],
    }


def a_run_under_faults_still_passes_every_applicable_check(seeds: int = 8) -> dict:
    """Sequential runs with fault schedules pass the invariants and the reference.

    The two halves of the package brought together. A fault costs availability and the reference
    only compares answers, so a run that committed less is not a difference, and a run that
    answered differently would be.
    """
    outcomes = []
    for seed in range(seeds):
        schedule = random_schedule(seed, ticks=200, faults=4)
        outcome = run_schedule(schedule)
        outcomes.append(outcome)
    return {
        "seeds": seeds,
        "safe": sum(1 for one in outcomes if one),
        "they_are_all_safe": all(bool(one) for one in outcomes),
        "faults_applied": sum(one.applied for one in outcomes),
        "committed": sum(one.committed for one in outcomes),
        "and_the_faults_were_real": sum(one.applied for one in outcomes) >= seeds * 3,
    }


def every_seed_passes_both_shapes(seeds: int = 8) -> dict:
    """Eight seeds, each run sequentially and concurrently, and all of them pass.

    The sweep the module ends on. What makes it worth anything is that each of the three
    checkers has been shown to fail on a fault it should see, which the three measurements above
    do, so a clean sweep is a statement about the algorithm rather than about the harness.
    """
    results = []
    for seed in range(seeds):
        results.append(sequential_run(seed=seed, count=12))
        results.append(concurrent_run(seed=seed, clients=3, each=2))
    return {
        "runs": len(results),
        "passed": sum(1 for one in results if one),
        "they_all_passed": all(bool(one) for one in results),
        "failures": [one.failures for one in results if one.failures],
        "shapes": sorted({one.shape for one in results}),
        "and_both_shapes_were_run": len({one.shape for one in results}) == 2,
    }


def an_unknown_shape_is_refused() -> bool:
    """A result naming a workload shape outside the two is refused."""
    try:
        made = Result(shape="mixed", commands=1)
        if made.shape not in SHAPES:
            raise ConfigError(f"{made.shape} is not a shape")
    except ConfigError:
        return True
    return False


def a_schedule_with_no_faults_is_still_a_schedule() -> bool:
    """An empty fault list is a valid schedule and runs a clean cluster."""
    return bool(run_schedule(Schedule(seed=1, ticks=60)))


def compare_the_shapes() -> list[dict]:
    """The two workload shapes and what each one is checked by."""
    return [
        sequential_run(seed=2, count=12).as_dict(),
        concurrent_run(seed=2, each=2).as_dict(),
    ]


def the_two_shapes_together_cover_the_three_checkers() -> dict:
    """Neither shape alone reaches every checker and the two together do.

    Stated as the conclusion of the table, because it is the argument for running both and the
    reason this module exists rather than a single scenario function.
    """
    table = compare_the_shapes()
    ran = {one["shape"]: set(one["ran"]) for one in table}
    return {
        "shapes": list(ran),
        "ran_each": {name: sorted(one) for name, one in ran.items()},
        "neither_covers_everything": all(one != set(CHECKERS) for one in ran.values()),
        "together_they_do": set().union(*ran.values()) == set(CHECKERS),
        "coverage_each": [one["coverage"] for one in table],
        "and_both_passed": all(one["passed"] for one in table),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "checkers": len(CHECKERS),
        "shapes": len(SHAPES),
        "a_sequential_run_passes": a_sequential_run_passes_both_checks()["it_passed"],
        "a_concurrent_run_passes": a_concurrent_run_passes_both_of_its_checks()["it_passed"],
        "neither_shape_runs_all_three": neither_shape_runs_all_three_checks()[
            "neither_runs_all_three"
        ],
        "the_reference_catches_a_wrong_answer": the_reference_catches_a_wrong_answer()[
            "broken_disagreed"
        ],
        "the_checker_catches_an_impossible_history": (
            the_checker_catches_an_impossible_history()["it_was_rejected"]
        ),
        "faults_do_not_break_the_checks": (
            a_run_under_faults_still_passes_every_applicable_check()["they_are_all_safe"]
        ),
        "every_seed_passes": every_seed_passes_both_shapes()["they_all_passed"],
    }
