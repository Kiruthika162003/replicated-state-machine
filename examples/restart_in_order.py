"""Five ways to restart a cluster, all equally safe and nowhere near equally available.

Run with: python examples/restart_in_order.py

Restarting nodes one at a time never loses committed data in any of the five patterns tried
here, which is the algorithm doing what it is supposed to do regardless of the order an
operator chooses. What the algorithm has not decided is how much of the restart the cluster
spends unable to answer, and that number runs from zero straight up to most of it, entirely on
the strength of one operational choice: whether the leader restarts last.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.recovery import (
    compare_the_patterns,
    the_patterns_differ_only_in_availability_and_by_a_lot,
)


def main() -> None:
    print(rule("five restart patterns over the same cluster"))
    print(table(compare_the_patterns()))
    print()

    verdict = the_patterns_differ_only_in_availability_and_by_a_lot()
    print(rule("what actually varies across them"))
    print(f"patterns tried              {verdict['patterns']}")
    print(f"every one kept its data     {verdict['every_one_kept_its_data']}")
    print(f"best for availability       {verdict['best']}")
    print(f"worst for availability      {verdict['worst']}")
    print(f"availability by pattern     {verdict['availability']}")
    print(f"the range spans zero to most {verdict['the_range_is_the_whole_range']}")
    print(f"and safety never varies     {verdict['and_safety_is_constant']}")

    if not verdict["and_safety_is_constant"]:
        raise SystemExit("expected every restart pattern to keep its committed data")
    if not verdict["the_range_is_the_whole_range"]:
        raise SystemExit("expected availability to span nearly the whole range")


if __name__ == "__main__":
    main()
