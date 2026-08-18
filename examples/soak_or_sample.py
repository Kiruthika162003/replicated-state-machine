"""Spend the same ticks two ways and count what each one reached.

Run with: python examples/soak_or_sample.py

The usual way to gain confidence in a distributed system is to run it for a long time under
faults. This spends the same budget on many short runs instead, and the short runs win by more
than twice, because the interesting part of a cluster's life is its first twenty ticks.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.chart import Series, bars
from rsm.verify.coverage import grid
from rsm.verify.soak import BUDGET, many_short_runs, one_long_run


def length_rows() -> list[dict]:
    """The same budget split into runs of several lengths."""
    out = [
        {
            "way": "one long run",
            **_row(one_long_run()),
        }
    ]
    for each in (20, 60, 150, 400):
        out.append({"way": f"runs of {each}", **_row(many_short_runs(each=each))})
    return out


def _row(made) -> dict:
    """One soak as a table row."""
    return {
        "runs": made.runs,
        "ticks": made.ticks,
        "cells": len(made.cells),
        "coverage": made.coverage,
        "last found": made.last_discovery,
        "wasted": made.wasted,
        "breaches": made.breaches,
    }


def main() -> None:
    long_run = one_long_run()
    short = many_short_runs()

    print(rule("the same budget, two ways"))
    print(
        table(
            [{"way": "one long run", **_row(long_run)}, {"way": "twenty short", **_row(short)}]
        )
    )
    print()
    print(
        pairs(
            {
                "grid size": len(grid()),
                "long run coverage": bar(long_run.coverage, 30),
                "short runs coverage": bar(short.coverage, 30),
                "the same ticks": long_run.ticks == short.ticks,
                "neither broke anything": long_run.breaches == short.breaches == 0,
            }
        )
    )
    print()
    print("the long run stops finding things at tick", long_run.last_discovery, "and runs to")
    print(long_run.ticks, "so more than half its budget is spent after its last discovery")
    print()

    print(rule("every split, against the single run"))
    rows = length_rows()
    print(table(rows))
    print()
    made = Series(
        name="cells reached, against run length",
        values=[float(one["cells"]) for one in rows],
        labels=[one["way"].rjust(13) for one in rows],
    )
    for one in bars(made, 34):
        print(f"  {one}")
    print()
    print("runs of twenty are too short to finish an election and reach almost nothing; runs")
    print("of sixty are the best of these; and every split beats the single long run")
    print()

    print(rule("what this does not say"))
    print("nothing here argues against soaking. it argues that a soak tests for what")
    print(f"accumulates over time rather than what varies between runs, and that in {BUDGET}")
    print("ticks of this package nothing accumulates")


if __name__ == "__main__":
    main()
