"""Why the election timeout is spread over ten ticks rather than two or a hundred.

Run with: python examples/pick_the_spread.py

A randomised spread on the election timer is what keeps two nodes from timing out in the same
tick and splitting the vote. Too little spread and collisions are common; too much and every
extra tick is a tick a real failure goes undetected. The shipped value is not a round number
chosen for looks, it is the point on the curve where most of the fall in collision rate has
already happened and the flat part has barely started.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.election import compare_the_spreads, the_shipped_spread_sits_where_the_curve_bends


def main() -> None:
    print(rule("collision rate and worst case detection time, by spread"))
    print(table(compare_the_spreads()))
    print()

    verdict = the_shipped_spread_sits_where_the_curve_bends()
    print(rule("where the shipped spread sits on that curve"))
    print(f"shipped spread                {verdict['shipped']} ticks")
    print(f"its collision rate            {verdict['its_collision_rate']}")
    print(f"at a spread of two            {verdict['at_two_it_is']}")
    print(f"at a spread of a hundred      {verdict['at_a_hundred_it_is']}")
    print(f"most of the fall is below it  {verdict['most_of_the_fall_is_below_it']}")
    print(f"ten times the spread saves    {verdict['and_ten_times_the_spread_saves_this']}")
    print(f"for this many extra ticks     {verdict['for_this_many_extra_ticks']}")

    if not verdict["most_of_the_fall_is_below_it"]:
        raise SystemExit("expected the shipped spread to sit past the steep part of the curve")


if __name__ == "__main__":
    main()
