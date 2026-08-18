"""Remove one rule at a time and see which searches notice.

Run with: python examples/break_it_on_purpose.py

Four defects, each one rule of the algorithm taken out by subclassing the shipped node. Two
search strategies, one drawing fault schedules and one enumerating message orderings. Between
them they catch three of the four, they disagree about which three, and the one they both miss
is the one the original paper needed a figure to explain.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.verify.explore import explore
from rsm.verify.fuzz import BUDGET, DEFECTS, search, shrink

DEFECT_NAMES = ("ignores the log", "votes twice", "commits any term", "forgets the vote")


def fuzz_rows() -> list[dict]:
    """What drawing fault schedules found."""
    out = []
    for name in ("sound", *DEFECT_NAMES):
        made = search(DEFECTS[name], budget=BUDGET)
        out.append(
            {
                "defect": name,
                "caught": "yes" if made else "no",
                "seeds": made.runs,
                "broke": ", ".join(made.properties) or "nothing",
            }
        )
    return out


def explore_rows() -> list[dict]:
    """What enumerating orderings found."""
    out = []
    for name in ("sound", *DEFECT_NAMES):
        made = explore(DEFECTS[name], depth=12, states=12000, symmetry=True, restarts=1)
        out.append(
            {
                "defect": name,
                "caught": "yes" if made.violation else "no",
                "states": made.states,
                "depth": made.depth,
                "broke": made.violation.property if made.violation else "nothing",
            }
        )
    return out


def main() -> None:
    print(rule("drawing fault schedules"))
    print(table(fuzz_rows()))
    print()
    print("a schedule says when a node stops and when the network splits; it says nothing")
    print("about which of the messages in flight arrives first")
    print()

    print(rule("enumerating message orderings"))
    print(table(explore_rows()))
    print()
    print("which is the other space, and it catches a different defect")
    print()

    caught_by_fuzz = {one["defect"] for one in fuzz_rows() if one["caught"] == "yes"}
    caught_by_search = {one["defect"] for one in explore_rows() if one["caught"] == "yes"}
    print(rule("between them"))
    print(
        pairs(
            {
                "found by fault injection": ", ".join(sorted(caught_by_fuzz)),
                "found by ordering search": ", ".join(sorted(caught_by_search)),
                "found by both": ", ".join(sorted(caught_by_fuzz & caught_by_search)),
                "found by neither": ", ".join(
                    sorted(set(DEFECT_NAMES) - caught_by_fuzz - caught_by_search)
                ),
                "coverage": bar(len(caught_by_fuzz | caught_by_search) / len(DEFECT_NAMES), 24),
            }
        )
    )
    print()
    print("the one they both miss is the commit rule for entries from earlier terms, which")
    print("rsm.replicate catches by driving the nodes through the sequence by hand")
    print()

    print(rule("and the reproduction, cut down"))
    for name in ("ignores the log", "votes twice"):
        found = search(DEFECTS[name], budget=BUDGET)
        smaller = shrink(found)
        print(f"  {name}")
        print(
            f"    {len(found.schedule.faults)} faults over {found.schedule.ticks} ticks "
            f"becomes {len(smaller.schedule.faults)} over {smaller.schedule.ticks}"
        )
        if smaller.schedule.faults:
            for one in smaller.schedule.faults:
                print(f"      {one}")
        else:
            print("      nothing at all: a healthy cluster breaks it on its own")
    print()
    print("shrinking is usually sold as making reports shorter. what it did to the second")
    print("one was correct the diagnosis")


if __name__ == "__main__":
    main()
