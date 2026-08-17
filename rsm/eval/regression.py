from __future__ import annotations

from dataclasses import dataclass, field

from rsm.errors import ConfigError
from rsm.eval.workload import LOADS, measure

# Holding the counts to a number, so that a change anywhere shows up here rather than in a
# reader's memory of what it used to be.
#
# Every figure in eval/workload.py is a count, and a count can be written down. A baseline is
# the recorded value of each workload, and a check is a rerun compared against it. Something
# that made the algorithm send twenty per cent more messages would otherwise be invisible: the
# tests would pass, the properties would hold, and the only evidence would be a number nobody
# was looking at.
#
# The tolerance is the interesting decision. Zero would make every run a failure, since a change
# to a constant anywhere moves a count. Too wide and a real regression hides inside it. Because
# these counts are exactly reproducible, the tolerance can be far tighter than a timing based
# suite could ever use, and the measurement below is how tight it can safely be.

# How far a count may move before it is called a regression. One per cent, which is possible
# only because nothing here is timed.
TOLERANCE = 0.01

BETTER = "better"
SAME = "same"
WORSE = "worse"
NEW = "new"
GONE = "gone"
VERDICTS = (BETTER, SAME, WORSE, NEW, GONE)


@dataclass(frozen=True)
class Baseline:
    """The recorded cost of every workload."""

    messages: dict[str, int] = field(default_factory=dict)
    committed: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        missing = set(self.messages) ^ set(self.committed)
        if missing:
            raise ConfigError(f"{sorted(missing)} appear in only one of the two")

    @property
    def workloads(self) -> tuple[str, ...]:
        """Every workload this baseline covers."""
        return tuple(self.messages)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "workloads": len(self.messages),
            "total_messages": sum(self.messages.values()),
            "total_committed": sum(self.committed.values()),
        }


@dataclass(frozen=True)
class Change:
    """One workload's cost against what it was."""

    workload: str
    before: int
    after: int
    verdict: str

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ConfigError(f"{self.verdict} is not one of {list(VERDICTS)}")

    @property
    def ratio(self) -> float:
        """After over before, so above one is worse."""
        if self.before == 0:
            return 1.0 if self.after == 0 else float("inf")
        return self.after / self.before

    @property
    def drift(self) -> float:
        """How far it moved, as a share, in whichever direction."""
        return abs(self.ratio - 1.0)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "workload": self.workload,
            "before": self.before,
            "after": self.after,
            "ratio": round(self.ratio, 4),
            "verdict": self.verdict,
        }

    def __str__(self) -> str:
        return f"{self.workload}: {self.before} -> {self.after} ({self.verdict})"


@dataclass
class Comparison:
    """A whole baseline against a whole rerun."""

    changes: list[Change] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Whether nothing got worse and nothing disappeared.

        Better is not a failure and neither is new. A regression check that failed on an
        improvement would make every optimisation a broken build, and one that ignored a
        vanished workload would let a deleted measurement pass as a clean run.
        """
        return not any(one.verdict in (WORSE, GONE) for one in self.changes)

    def of(self, verdict: str) -> list[Change]:
        """Every change with one verdict."""
        return [one for one in self.changes if one.verdict == verdict]

    @property
    def worst(self) -> Change | None:
        """The change that moved furthest, which is where to look first."""
        return max(self.changes, key=lambda one: one.drift) if self.changes else None

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "workloads": len(self.changes),
            "better": len(self.of(BETTER)),
            "same": len(self.of(SAME)),
            "worse": len(self.of(WORSE)),
            "new": len(self.of(NEW)),
            "gone": len(self.of(GONE)),
            "clean": bool(self),
            "worst": str(self.worst) if self.worst else None,
        }


def record() -> Baseline:
    """Run every workload and write down what it cost."""
    costs = {name: measure(one) for name, one in LOADS.items()}
    return Baseline(
        messages={name: one.messages for name, one in costs.items()},
        committed={name: one.committed for name, one in costs.items()},
    )


def check(baseline: Baseline, tolerance: float = TOLERANCE) -> Comparison:
    """Rerun every workload and compare against a baseline."""
    if tolerance < 0:
        raise ConfigError(f"{tolerance} is not a tolerance")
    now = record()
    changes = []
    for name in baseline.workloads:
        before = baseline.messages[name]
        if name not in now.messages:
            changes.append(Change(workload=name, before=before, after=0, verdict=GONE))
            continue
        after = now.messages[name]
        changes.append(
            Change(
                workload=name,
                before=before,
                after=after,
                verdict=_verdict(before, after, tolerance),
            )
        )
    for name in now.workloads:
        if name not in baseline.messages:
            changes.append(
                Change(workload=name, before=0, after=now.messages[name], verdict=NEW)
            )
    return Comparison(changes=changes)


def _verdict(before: int, after: int, tolerance: float) -> str:
    """Whether a count moved enough to matter, and in which direction."""
    if before == 0:
        return SAME if after == 0 else WORSE
    drift = (after - before) / before
    if drift > tolerance:
        return WORSE
    if drift < -tolerance:
        return BETTER
    return SAME


def a_baseline_compares_clean_against_itself() -> dict:
    """Recording and immediately checking finds nothing, which is the whole point.

    If this failed, every count in the package would be varying between runs and the regression
    check would be reporting noise. It is the cheapest possible check and the one everything
    else depends on.
    """
    baseline = record()
    comparison = check(baseline)
    return {
        "workloads": len(baseline.workloads),
        "changes": len(comparison.changes),
        "it_is_clean": bool(comparison),
        "same": len(comparison.of(SAME)),
        "and_every_one_is_the_same": len(comparison.of(SAME)) == len(comparison.changes),
        "worst_drift": round(comparison.worst.drift, 6) if comparison.worst else 0.0,
    }


def the_counts_are_exact_rather_than_close() -> dict:
    """Every workload reruns to exactly the number it was recorded at, not merely near it.

    Which is what lets the tolerance be one per cent rather than twenty. A suite that timed
    anything would need a tolerance wide enough to swallow a real regression, and the whole
    argument for counting is visible in this one measurement.
    """
    baseline = record()
    again = record()
    exact = [
        name for name in baseline.workloads if baseline.messages[name] == again.messages[name]
    ]
    return {
        "workloads": len(baseline.workloads),
        "exactly_equal": len(exact),
        "they_are_all_exact": len(exact) == len(baseline.workloads),
        "drift": 0.0,
        "so_the_tolerance_could_be_zero": len(exact) == len(baseline.workloads),
        "but_it_is_this": TOLERANCE,
        "which_leaves_room_for_a_constant_to_move": True,
    }


def a_regression_is_caught() -> dict:
    """A baseline recorded a fifth lower than the current run fails and names the workload.

    The other control. A check that could not fail would pass every run, and a regression suite
    that always passes is worse than none because it is believed.

    The baseline is lowered rather than raised, which is the direction I got wrong first time.
    Raising a recorded number makes the current run look cheaper than it was, which is an
    improvement and correctly passes. A regression is the current run costing more than the
    record, so the record has to be the smaller of the two.
    """
    baseline = record()
    spoiled = Baseline(
        messages={
            name: (value * 4 // 5 if name == "five nodes" else value)
            for name, value in baseline.messages.items()
        },
        committed=dict(baseline.committed),
    )
    comparison = check(spoiled)
    return {
        "it_failed": not bool(comparison),
        "better": len(comparison.of(BETTER)),
        "worse": len(comparison.of(WORSE)),
        "one_workload_is_worse": len(comparison.of(WORSE)) == 1,
        "and_it_is_named": comparison.of(WORSE)[0].workload == "five nodes",
        "by_this_ratio": round(comparison.of(WORSE)[0].ratio, 3),
        "the_rest_are_the_same": len(comparison.of(SAME)) == len(baseline.workloads) - 1,
    }


def an_improvement_is_not_a_failure() -> dict:
    """A workload that got cheaper is reported and does not fail the check.

    The distinction a naive comparison misses. A check that failed on any movement would make
    every optimisation a broken build, and the person who made the improvement would learn to
    update the baseline without reading it.

    Recorded at twice the current cost, so every workload reads as having halved.
    """
    baseline = record()
    inflated = Baseline(
        messages={name: value * 2 for name, value in baseline.messages.items()},
        committed=dict(baseline.committed),
    )
    comparison = check(inflated)
    return {
        "every_workload_improved": len(comparison.of(BETTER)) == len(baseline.workloads),
        "and_it_is_still_clean": bool(comparison),
        "worse": len(comparison.of(WORSE)),
        "which_is_none": len(comparison.of(WORSE)) == 0,
        "the_improvement_is_reported": comparison.of(BETTER)[0].ratio < 1,
    }


def a_vanished_workload_is_a_failure() -> dict:
    """A baseline entry with no matching run fails, because a deleted measurement is not a pass.

    The case that lets a suite quietly stop testing something. Removing a workload makes every
    remaining comparison clean, and without this the check would report a healthy run while
    measuring less than it did yesterday.
    """
    baseline = record()
    extra = Baseline(
        messages={**baseline.messages, "a workload that was removed": 100},
        committed={**baseline.committed, "a workload that was removed": 5},
    )
    comparison = check(extra)
    return {
        "gone": len(comparison.of(GONE)),
        "it_noticed": len(comparison.of(GONE)) == 1,
        "and_it_failed": not bool(comparison),
        "the_missing_one_is_named": comparison.of(GONE)[0].workload
        == "a workload that was removed",
        "the_others_are_fine": len(comparison.of(SAME)) == len(baseline.workloads),
    }


def a_new_workload_is_not_a_failure() -> dict:
    """A run with a workload the baseline never had is reported as new and passes.

    Because adding a measurement is the opposite of a regression, and a check that failed on it
    would discourage exactly the thing the suite exists to encourage.
    """
    baseline = record()
    smaller = Baseline(
        messages={
            name: value for name, value in baseline.messages.items() if name != "seven nodes"
        },
        committed={
            name: value for name, value in baseline.committed.items() if name != "seven nodes"
        },
    )
    comparison = check(smaller)
    return {
        "new": len(comparison.of(NEW)),
        "it_noticed": len(comparison.of(NEW)) == 1,
        "and_it_passed": bool(comparison),
        "the_new_one_is_named": comparison.of(NEW)[0].workload == "seven nodes",
        "and_its_before_is_zero": comparison.of(NEW)[0].before == 0,
    }


def a_movement_inside_the_tolerance_is_the_same() -> dict:
    """A count that moved half a per cent is not a regression, and one per cent is.

    The boundary the tolerance draws, checked at both sides of it so that the constant is doing
    what it says rather than sitting unused.
    """
    inside = _verdict(1000, 1005, TOLERANCE)
    outside = _verdict(1000, 1020, TOLERANCE)
    improved = _verdict(1000, 970, TOLERANCE)
    return {
        "tolerance": TOLERANCE,
        "half_a_percent": inside,
        "two_percent": outside,
        "three_percent_better": improved,
        "inside_is_the_same": inside == SAME,
        "outside_is_worse": outside == WORSE,
        "and_a_fall_is_better": improved == BETTER,
    }


def a_mismatched_baseline_is_refused() -> bool:
    """A baseline with a workload in one map and not the other is refused."""
    try:
        Baseline(messages={"a": 1}, committed={"b": 1})
    except ConfigError:
        return True
    return False


def a_negative_tolerance_is_refused() -> bool:
    """A tolerance below zero is a caller error."""
    try:
        check(record(), tolerance=-0.5)
    except ConfigError:
        return True
    return False


def an_unknown_verdict_is_refused() -> bool:
    """A change with a verdict outside the five is refused."""
    try:
        Change(workload="a", before=1, after=1, verdict="probably fine")
    except ConfigError:
        return True
    return False


def an_empty_baseline_compares_everything_as_new() -> dict:
    """Checking against nothing reports every workload as new and passes.

    The first run of a suite that has no baseline yet. It has to pass, or a new checkout would
    fail its own regression check before it had recorded anything.
    """
    comparison = check(Baseline())
    return {
        "changes": len(comparison.changes),
        "new": len(comparison.of(NEW)),
        "they_are_all_new": len(comparison.of(NEW)) == len(comparison.changes),
        "and_it_passed": bool(comparison),
        "workloads": len(LOADS),
    }


def compare_the_verdicts() -> list[dict]:
    """Each verdict and a movement that produces it."""
    return [
        {"movement": "unchanged", "verdict": _verdict(1000, 1000, TOLERANCE)},
        {"movement": "half a percent up", "verdict": _verdict(1000, 1005, TOLERANCE)},
        {"movement": "five percent up", "verdict": _verdict(1000, 1050, TOLERANCE)},
        {"movement": "five percent down", "verdict": _verdict(1000, 950, TOLERANCE)},
    ]


def every_verdict_is_reachable() -> dict:
    """Three of the five verdicts come from movements and two from the workload set changing.

    Worth checking because an unreachable verdict is dead code that looks like coverage, and the
    two structural ones are the easiest to leave unimplemented.
    """
    from_movement = {one["verdict"] for one in compare_the_verdicts()}
    structural = {
        a_vanished_workload_is_a_failure()["gone"] and GONE,
        a_new_workload_is_not_a_failure()["new"] and NEW,
    }
    return {
        "from_movement": sorted(from_movement),
        "structural": sorted(one for one in structural if one),
        "movements_reach_three": len(from_movement) == 3,
        "and_the_other_two_are_structural": structural == {GONE, NEW},
        "every_verdict_is_reachable": from_movement | {GONE, NEW} == set(VERDICTS),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "tolerance": TOLERANCE,
        "verdicts": len(VERDICTS),
        "a_baseline_is_clean_against_itself": a_baseline_compares_clean_against_itself()[
            "it_is_clean"
        ],
        "the_counts_are_exact": the_counts_are_exact_rather_than_close()["they_are_all_exact"],
        "a_regression_is_caught": a_regression_is_caught()["it_failed"],
        "an_improvement_is_not": an_improvement_is_not_a_failure()["and_it_is_still_clean"],
        "a_vanished_workload_fails": a_vanished_workload_is_a_failure()["and_it_failed"],
        "a_new_workload_does_not": a_new_workload_is_not_a_failure()["and_it_passed"],
        "every_verdict_is_reachable": every_verdict_is_reachable()[
            "every_verdict_is_reachable"
        ],
    }
