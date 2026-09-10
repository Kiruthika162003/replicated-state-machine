"""A preference for one node is nearly free on a steady cluster and expensive on a flapping one.

Run with: python examples/prefer_a_node.py

Ranking one node ahead of the others by delaying everyone else's election timer gets that node
almost all of the leadership for a few percent of availability, on a cluster that otherwise
just runs. The same configuration, pointed at a preferred node that keeps crashing and coming
back, spends a quarter of the availability reclaiming leadership every time it returns. It is
the same knob in both cases, and the table is what makes the difference a number rather than a
warning in a docstring nobody reads until the flapping node is in production.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.priority import (
    FLAT,
    RANKED,
    Run,
    compare_the_schemes,
    the_preference_is_free_on_a_steady_cluster_and_dear_on_a_flapping_one,
)


def main() -> None:
    print(rule("the two schemes"))
    print(pairs({"flat": FLAT.as_dict(), "ranked": RANKED.as_dict()}))
    print()

    print(rule("five runs: steady and flapping, flat and ranked, with and without a reclaim"))
    print(table(compare_the_schemes()))
    print()
    print("share is the fraction of the run the preferred node spent leading, availability is")
    print("the fraction of attempted writes that committed, and transfers counts how many")
    print("times a reclaim handed leadership back rather than waiting for an election")
    print()

    verdict = the_preference_is_free_on_a_steady_cluster_and_dear_on_a_flapping_one()
    print(rule("the same configuration, two very different bills"))
    print(
        pairs(
            {
                "cost on a steady cluster": verdict["steady_cost"],
                "cost on a flapping cluster": verdict["flapping_cost"],
                "the flapping case costs more": verdict["the_flapping_case_costs_more"],
                "by this factor": verdict["by_this_factor"],
                "steady share of leadership": verdict["steady_share"],
                "flapping share of leadership": verdict["flapping_share"],
                "and it gets less for more cost": verdict["and_it_gets_less_for_it"],
            }
        )
    )

    if not verdict["the_flapping_case_costs_more"]:
        raise SystemExit("expected the flapping cluster to cost more availability")

    single = Run(RANKED).go("spot check")
    if not bool(single):
        raise SystemExit("expected the preferred node to lead most of a steady run")


if __name__ == "__main__":
    main()
