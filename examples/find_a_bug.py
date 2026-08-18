"""Fuzz a deliberately broken node until it breaks, then cut the reproduction down.

Run with: python examples/find_a_bug.py

This is the workflow the verify package is for. Take a node with one rule removed, draw random
fault schedules until one of them breaks a safety property, and then shrink that schedule until
nothing more can come out of it. The shrunk schedule is usually short enough to read as a
sentence, which is the difference between a bug report and a stack trace.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.verify.fuzz import BUDGET, DEFECTS, search, shrink

WATCHED = ("sound", "ignores the log", "votes twice", "commits any term", "forgets the vote")


def found_row(name: str) -> dict:
    """One line saying whether the search caught this defect and how quickly."""
    made = search(DEFECTS[name], budget=BUDGET)
    return {
        "defect": name,
        "caught": "yes" if made else "no",
        "seeds tried": made.runs,
        "property": ", ".join(made.properties) or "none",
    }


def main() -> None:
    print(rule("searching"))
    print(f"drawing up to {BUDGET} random fault schedules against each defect")
    print()
    print(table([found_row(name) for name in WATCHED]))
    print()
    print("the two it misses are decided by which message arrives first, which a fault")
    print("schedule does not control at all; rsm.verify.explore searches that space instead")
    print()

    for name in ("ignores the log", "votes twice"):
        found = search(DEFECTS[name], budget=BUDGET)
        smaller = shrink(found)
        print(rule(f"shrinking: {name}"))
        print(
            pairs(
                {
                    "found on seed": found.schedule.seed,
                    "faults before": len(found.schedule.faults),
                    "ticks before": found.schedule.ticks,
                    "faults after": len(smaller.schedule.faults),
                    "ticks after": smaller.schedule.ticks,
                    "runs spent shrinking": smaller.runs,
                    "still fails": bool(smaller),
                }
            )
        )
        print()
        print("  the reproduction:")
        if smaller.schedule.faults:
            for one in smaller.schedule.faults:
                print(f"    {one}")
        else:
            print("    nothing at all: a healthy cluster breaks it on its own")
        print()

    print(rule("what this is worth"))
    print("the double vote arrives wrapped in six faults and needs none of them, so the")
    print("unshrunk report would have sent somebody looking at partitions for a bug that")
    print("happens in the first thirty ticks of a cluster nothing is wrong with")


if __name__ == "__main__":
    main()
