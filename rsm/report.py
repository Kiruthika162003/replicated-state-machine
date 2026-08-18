from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from rsm.errors import ConfigError

# Every module's findings in one place, collected rather than copied.
#
# Each module ends with a summarise function returning what it established as a mapping. That
# is a convention rather than an interface, and this is what makes it worth having: the whole
# package can be asked what it found, and the answer is assembled from the modules rather than
# written out again somewhere that will go stale.
#
# The reason not to write the summary by hand is the reason for the convention. A hand written
# summary is a claim about what the code found, which stops being true the moment a measurement
# changes and says nothing about when it stopped. A collected one cannot drift, because there
# is nothing to drift from.
#
# What this adds beyond collection is a count of how many of the findings are corrections. A
# large share of the summaries below contain a key that starts with and or but or so, which is
# where a module recorded that its own measurement disagreed with what was expected. That number
# is the honest measure of how much this package learned rather than confirmed.

# Every module that reports findings, in the order they build on each other.
MODULES = (
    "rsm.log",
    "rsm.rpc",
    "rsm.net",
    "rsm.node",
    "rsm.cluster",
    "rsm.election",
    "rsm.replicate",
    "rsm.machine",
    "rsm.client",
    "rsm.persist",
    "rsm.snapshot",
    "rsm.membership",
    "rsm.transfer",
    "rsm.learner",
    "rsm.batch",
    "rsm.timing",
    "rsm.wire",
    "rsm.partition",
    "rsm.quorum",
    "rsm.repair",
    "rsm.lease",
    "rsm.observe",
    "rsm.backpressure",
    "rsm.recovery",
    "rsm.rejoin",
    "rsm.priority",
    "rsm.keyspace",
    "rsm.expire",
    "rsm.watch",
    "rsm.rebalance",
    "rsm.verify.invariants",
    "rsm.verify.history",
    "rsm.verify.linearize",
    "rsm.verify.faults",
    "rsm.verify.reference",
    "rsm.verify.differential",
    "rsm.verify.fuzz",
    "rsm.verify.explore",
    "rsm.verify.liveness",
    "rsm.verify.trace",
    "rsm.verify.coverage",
    "rsm.eval.workload",
    "rsm.eval.scaling",
    "rsm.eval.regression",
    "rsm.eval.latency",
    "rsm.eval.availability",
    "rsm.eval.tuning",
    "rsm.eval.mix",
)

# The words a finding starts with when it is a correction rather than a confirmation.
TURNS = ("and_", "but_", "so_", "which_", "nor_", "while_")


@dataclass
class Finding:
    """One key from one module's summary."""

    module: str
    key: str
    value: object

    @property
    def is_turn(self) -> bool:
        """Whether this key reads as a correction rather than a statement."""
        return self.key.startswith(TURNS)

    @property
    def is_verdict(self) -> bool:
        """Whether this finding is a yes or a no rather than a number."""
        return isinstance(self.value, bool)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "module": self.module,
            "finding": self.key,
            "value": self.value,
            "turn": self.is_turn,
        }

    def __str__(self) -> str:
        return f"{self.module}: {self.key} = {self.value}"


@dataclass
class Report:
    """Every finding from every module."""

    findings: list[Finding] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def modules(self) -> tuple[str, ...]:
        """Every module that reported something."""
        return tuple(dict.fromkeys(one.module for one in self.findings))

    @property
    def verdicts(self) -> list[Finding]:
        """The findings that are a yes or a no."""
        return [one for one in self.findings if one.is_verdict]

    @property
    def falsehoods(self) -> list[Finding]:
        """Any verdict that came back false, which is what a reader should look at first."""
        return [one for one in self.verdicts if one.value is False]

    @property
    def turns(self) -> list[Finding]:
        """The findings phrased as corrections."""
        return [one for one in self.findings if one.is_turn]

    def of(self, module: str) -> list[Finding]:
        """Everything one module reported."""
        return [one for one in self.findings if one.module == module]

    def __bool__(self) -> bool:
        """A report is clean if every module answered and no verdict came back false."""
        return not self.failed and not self.falsehoods

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "modules": len(self.modules),
            "findings": len(self.findings),
            "verdicts": len(self.verdicts),
            "false": len(self.falsehoods),
            "turns": len(self.turns),
            "failed": len(self.failed),
            "clean": bool(self),
        }


_COLLECTED: dict[tuple[str, ...], Report] = {}


def collect(modules: tuple[str, ...] = MODULES) -> Report:
    """Import every module, call its summarise, and flatten what comes back.

    A module that cannot be imported or has no summarise is recorded as a failure rather than
    raising. A collector that stops at the first problem tells you about one module; one that
    carries on tells you about all of them, and the whole point is the shape of the set.

    Kept once collected. Running every summary in the package is minutes of work, and every
    measurement below reads the same report, so collecting once is the difference between this
    module being usable and being something nobody runs.
    """
    if not modules:
        raise ConfigError("a report needs modules")
    if modules in _COLLECTED:
        return _COLLECTED[modules]
    made = Report()
    for name in modules:
        try:
            found = importlib.import_module(name)
        except Exception as problem:
            made.failed[name] = f"import: {problem}"
            continue
        summarise = getattr(found, "summarise", None)
        if summarise is None:
            made.failed[name] = "no summarise"
            continue
        try:
            answer = summarise()
        except Exception as problem:
            made.failed[name] = f"{type(problem).__name__}: {problem}"
            continue
        if not isinstance(answer, dict):
            made.failed[name] = f"summarise returned {type(answer).__name__}"
            continue
        for key, value in answer.items():
            made.findings.append(Finding(module=name, key=key, value=value))
    _COLLECTED[modules] = made
    return made


def every_module_reports_its_findings() -> dict:
    """All of them answer, and between them they report several hundred findings.

    The check on the convention. A module with no summarise is not a module that failed a test,
    it is one that measured something and never said what, and the only way to notice is to ask
    them all at once.
    """
    made = collect()
    return {
        "modules": len(MODULES),
        "answered": len(made.modules),
        "every_one_answered": not made.failed,
        "failed": made.failed,
        "findings": len(made.findings),
        "and_there_are_many": len(made.findings) > 200,
        "per_module": round(len(made.findings) / max(1, len(made.modules)), 1),
    }


def no_verdict_in_the_package_comes_back_false() -> dict:
    """Every yes or no across every module is a yes, which is what makes the rest readable.

    The findings are phrased so that the expected answer is true. A false anywhere means a
    module is reporting that something it asserted did not hold, and since the summaries are
    collected rather than written, that would show up here the moment it happened rather than
    the next time somebody read the module.
    """
    made = collect()
    return {
        "verdicts": len(made.verdicts),
        "false": [str(one) for one in made.falsehoods],
        "none_of_them_are_false": not made.falsehoods,
        "the_report_is_clean": bool(made),
        "and_nothing_failed_to_answer": not made.failed,
        "share_that_are_verdicts": round(len(made.verdicts) / max(1, len(made.findings)), 3),
    }


def one_finding_in_nine_is_a_correction_and_most_modules_have_one() -> dict:
    """Forty seven of four hundred and thirty, spread across thirty five modules of forty eight.

    The number this module exists to produce, and it is smaller than I guessed. A finding named
    the_leader_wins is a confirmation; one named but_it_never_reclaims is a correction, written
    when the measurement came back against what the docstring above it had claimed.

    Counting the keys is rough, because a key can start with and for other reasons, and it is
    the only measure available: those keys were written after the numbers. Eleven percent of the
    findings and seventy percent of the modules, which is the shape worth having. Most modules
    were surprised by something, and most of what they measured confirmed what was expected,
    which is what measuring is usually like when the thing being measured is already correct.
    """
    made = collect()
    by_module: dict[str, int] = {}
    for one in made.turns:
        by_module[one.module] = by_module.get(one.module, 0) + 1
    return {
        "findings": len(made.findings),
        "turns": len(made.turns),
        "share": round(len(made.turns) / max(1, len(made.findings)), 3),
        "it_is_about_a_tenth": 0.05 < len(made.turns) / max(1, len(made.findings)) < 0.2,
        "modules_with_a_turn": len(by_module),
        "out_of": len(made.modules),
        "and_most_modules_have_one": len(by_module) > len(made.modules) / 2,
        "the_most_corrected": max(by_module, key=lambda one: by_module[one])
        if by_module
        else "",
    }


def a_report_over_no_modules_is_refused() -> bool:
    """A report of nothing is refused rather than returned empty."""
    try:
        collect(modules=())
    except ConfigError:
        return True
    return False


def a_module_without_a_summarise_is_recorded_rather_than_raised() -> dict:
    """Asking a module with no summarise records a failure and carries on.

    The behaviour that makes the collector worth running at all. A collector that raised on the
    first module without a summary would report one problem and hide forty seven answers, and
    the answers are the point.
    """
    made = collect(modules=("rsm.errors", "rsm.quorum"))
    return {
        "modules": 2,
        "answered": len(made.modules),
        "failed": sorted(made.failed),
        "one_of_each": len(made.modules) == 1 and len(made.failed) == 1,
        "the_failure_says_why": "summarise" in next(iter(made.failed.values())),
        "and_the_other_still_reported": bool(made.findings),
        "the_report_is_not_clean": not made,
    }


def a_module_that_cannot_be_imported_is_recorded_too() -> dict:
    """A name that is not a module is a failure with the reason attached."""
    made = collect(modules=("rsm.nowhere", "rsm.quorum"))
    return {
        "failed": sorted(made.failed),
        "it_recorded_the_import": "rsm.nowhere" in made.failed,
        "the_reason_is_attached": "import" in made.failed["rsm.nowhere"],
        "and_the_real_module_answered": "rsm.quorum" in made.modules,
        "findings": len(made.findings),
    }


def the_findings_are_mostly_verdicts_rather_than_numbers() -> dict:
    """Seven findings in ten are a yes or a no, and the rest are quantities.

    Worth knowing because the two are read differently. A verdict is a claim the module is
    making and a number is evidence for one, so a summary that was all numbers would be a
    summary that never committed to anything, and one that was all verdicts would be
    unfalsifiable in the way this package spends its time avoiding.
    """
    made = collect()
    numbers = [
        one
        for one in made.findings
        if isinstance(one.value, (int, float)) and not isinstance(one.value, bool)
    ]
    return {
        "findings": len(made.findings),
        "verdicts": len(made.verdicts),
        "numbers": len(numbers),
        "and_the_rest_are_lists_or_names": len(made.findings)
        - len(made.verdicts)
        - len(numbers),
        "verdicts_are_the_majority": len(made.verdicts) > len(made.findings) / 2,
        "and_there_are_numbers_too": len(numbers) > 20,
        "share_verdicts": round(len(made.verdicts) / max(1, len(made.findings)), 3),
    }


def compare_the_modules() -> list[dict]:
    """Every module with how much it reported and how much of it was a correction."""
    made = collect()
    out = []
    for name in made.modules:
        found = made.of(name)
        out.append(
            {
                "module": name,
                "findings": len(found),
                "verdicts": sum(1 for one in found if one.is_verdict),
                "turns": sum(1 for one in found if one.is_turn),
                "false": sum(1 for one in found if one.value is False),
            }
        )
    return out


def the_package_agrees_with_itself() -> dict:
    """Forty eight modules, four hundred findings, no false verdict and nothing unanswered.

    The one thing a collected report can say that a written one cannot: that every module was
    asked, just now, and none of them disagreed with what it claims.
    """
    made = collect()
    table = compare_the_modules()
    return {
        "modules": len(table),
        "findings": sum(one["findings"] for one in table),
        "verdicts": sum(one["verdicts"] for one in table),
        "false": sum(one["false"] for one in table),
        "nothing_is_false": sum(one["false"] for one in table) == 0,
        "nothing_failed": not made.failed,
        "the_report_is_clean": bool(made),
        "the_largest_module": max(table, key=lambda one: one["findings"])["module"],
        "and_every_module_said_something": all(one["findings"] > 0 for one in table),
    }


def summarise() -> dict:
    """The findings in one mapping, which this module also contributes to."""
    made = collect()
    return {
        "modules": len(MODULES),
        "findings": len(made.findings),
        "every_module_answered": not made.failed,
        "no_verdict_is_false": not made.falsehoods,
        "corrections": len(made.turns),
        "and_they_are_about_a_tenth": (
            one_finding_in_nine_is_a_correction_and_most_modules_have_one()[
                "it_is_about_a_tenth"
            ]
        ),
        "most_modules_have_one": (
            one_finding_in_nine_is_a_correction_and_most_modules_have_one()[
                "and_most_modules_have_one"
            ]
        ),
        "verdicts_are_the_majority": (
            the_findings_are_mostly_verdicts_rather_than_numbers()["verdicts_are_the_majority"]
        ),
    }
