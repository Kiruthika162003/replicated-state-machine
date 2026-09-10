"""Five safety properties, checked across a healthy run, a partition, and a crash and restart.

Run with: python examples/check_every_scenario.py

A single clean run proves little on its own, since a checker that never rejects anything would
pass it too. What makes a sweep like this one evidence is a checker that is known to reject a
constructed violation, run here against several honestly different scenarios and coming back
clean on all of them: nothing here is exercising the invariants against a version of the
checker that could not have caught a real breach.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.verify.invariants import (
    compare_the_scenarios,
    no_fault_in_this_package_breaks_a_property,
)


def main() -> None:
    print(rule("three scenarios, checked against five safety properties"))
    print(table(compare_the_scenarios()))
    print()

    verdict = no_fault_in_this_package_breaks_a_property()
    print(rule("what held, and whether the checker can fail at all"))
    print(f"scenarios checked              {verdict['scenarios']}")
    print(f"breaches per scenario          {verdict['breaches']}")
    print(f"every scenario is clean        {verdict['they_are_all_clean']}")
    print(f"every property held everywhere {verdict['every_property_held_everywhere']}")
    print(f"and the checker can fail       {verdict['and_the_checker_can_fail']}")

    if not verdict["they_are_all_clean"]:
        raise SystemExit("expected every scenario to hold all five properties")
    if not verdict["and_the_checker_can_fail"]:
        raise SystemExit("expected the checker to reject a constructed violation")


if __name__ == "__main__":
    main()
