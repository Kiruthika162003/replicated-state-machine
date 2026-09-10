"""Adding a voter directly can raise the quorum before it has caught up; a learner never does.

Run with: python examples/join_as_a_learner.py

A direct add makes the new node a voter immediately, and whether that raises the quorum depends
on nothing but the parity of the starting size: a majority of four and of five are both three,
so a fifth voter is free and a seventh is free, but a fourth and a sixth are not. A learner
joins with no vote at all, so it never raises the quorum, at any size, which is the general
answer rather than the one that happens to work for whichever size a cluster starts at.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.learner import (
    compare_the_joining_paths,
    joining_as_a_learner_never_raises_the_quorum_early,
)


def main() -> None:
    print(rule("quorum before joining, as a direct voter, and as a learner"))
    print(table(compare_the_joining_paths()))
    print()

    verdict = joining_as_a_learner_never_raises_the_quorum_early()
    print(rule("which sizes a direct add makes pay"))
    print(f"sizes swept                  {verdict['sizes']}")
    print(f"a direct add raises it at    {verdict['raised_by_a_direct_add']}")
    print(f"a direct add is free at      {verdict['free_for_a_direct_add']}")
    print(f"it does not always raise it  {verdict['it_does_not_always_raise_it']}")
    print(f"the ones that pay are odd    {verdict['the_ones_that_pay_are_odd']}")
    print(f"the learner path never does  {verdict['the_learner_path_never_raises_it']}")

    if not verdict["the_learner_path_never_raises_it"]:
        raise SystemExit("expected the learner path to never raise the quorum early")
    if not verdict["it_does_not_always_raise_it"]:
        raise SystemExit("expected some starting sizes to make a direct add free")


if __name__ == "__main__":
    main()
