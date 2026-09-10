"""Neither a sequential workload nor a concurrent one alone exercises every checker.

Run with: python examples/cover_two_shapes.py

A differential check runs the implementation against a reference model and asks whether they
agree, but which checkers actually fire depends on the shape of the workload driving them. A
sequential run and a concurrent run each reach a different subset of the three checkers this
module wires up, and the argument for running both, rather than picking whichever is simpler
to write, is that only their union reaches all three.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.verify.differential import (
    compare_the_shapes,
    the_two_shapes_together_cover_the_three_checkers,
)


def main() -> None:
    print(rule("what each workload shape is checked by"))
    print(table(compare_the_shapes()))
    print()

    verdict = the_two_shapes_together_cover_the_three_checkers()
    print(rule("whether either shape alone is enough"))
    print(f"shapes                        {verdict['shapes']}")
    print(f"checkers each one ran         {verdict['ran_each']}")
    print(f"neither covers everything     {verdict['neither_covers_everything']}")
    print(f"together they do              {verdict['together_they_do']}")
    print(f"coverage fraction, each shape {verdict['coverage_each']}")
    print(f"and both passed               {verdict['and_both_passed']}")

    if not verdict["neither_covers_everything"]:
        raise SystemExit("expected neither workload shape alone to reach every checker")
    if not verdict["together_they_do"]:
        raise SystemExit("expected the two shapes together to reach every checker")


if __name__ == "__main__":
    main()
