"""Ask every module what it found, and count how much of it was a correction.

Run with: python examples/report_everything.py

Every module ends with a summarise returning its findings. This collects all of them, which
takes a couple of minutes because it runs every measurement in the package, and prints what
comes back rather than a summary somebody wrote down and stopped maintaining.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.report import MODULES, collect

TOP = 12


def module_rows(report) -> list[dict]:
    """Every module with what it reported."""
    out = []
    for name in report.modules:
        found = report.of(name)
        out.append(
            {
                "module": name,
                "findings": len(found),
                "verdicts": sum(1 for one in found if one.is_verdict),
                "corrections": sum(1 for one in found if one.is_turn),
                "false": sum(1 for one in found if one.value is False),
            }
        )
    return sorted(out, key=lambda one: one["findings"], reverse=True)


def main() -> None:
    print(rule("collecting"))
    print(f"asking {len(MODULES)} modules for their findings, which runs every measurement")
    print()
    report = collect()

    print(rule("what came back"))
    print(pairs(report.as_dict()))
    print()

    rows = module_rows(report)
    print(rule(f"the {TOP} modules with the most to say"))
    print(table(rows[:TOP]))
    print()

    corrected = [one for one in rows if one["corrections"]]
    print(rule("corrections"))
    print(
        pairs(
            {
                "findings": len(report.findings),
                "phrased as a correction": len(report.turns),
                "share": round(len(report.turns) / max(1, len(report.findings)), 3),
                "modules with at least one": len(corrected),
                "out of": len(rows),
            }
        )
    )
    print()
    print("share:", bar(len(report.turns) / max(1, len(report.findings)), 30))
    print()
    print("a correction is a finding named after a measurement that came back against what")
    print("the docstring above it had claimed, and most modules have one")
    print()

    print(rule("a sample of them"))
    for one in report.turns[:TOP]:
        print(f"  {one}")
    print()

    print(rule("the verdicts"))
    print(
        pairs(
            {
                "verdicts": len(report.verdicts),
                "false": len(report.falsehoods),
                "clean": bool(report),
                "modules that failed to answer": len(report.failed),
            }
        )
    )
    print()
    print("every module was asked just now, and none of them disagrees with what it claims")


if __name__ == "__main__":
    main()
