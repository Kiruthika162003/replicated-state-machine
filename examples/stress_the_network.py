"""Loss and jitter are independent knobs on the simulated network, not two names for one thing.

Run with: python examples/stress_the_network.py

Every later measurement in this package that varies packet loss while holding delay fixed, or
the other way round, is only measuring one thing at a time if the simulator's two settings do
not secretly interact. This runs the same traffic under four combinations of the two and checks
that adding jitter to a lossy link leaves the loss rate where it was, and that a link with only
jitter loses nothing at all.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.net import compare_the_conditions, loss_and_jitter_are_independent_settings


def main() -> None:
    print(rule("the same traffic pattern under four link conditions"))
    print(table(compare_the_conditions()))
    print()

    verdict = loss_and_jitter_are_independent_settings()
    print(rule("whether loss and jitter interact"))
    print(f"loss rate, lossy alone         {verdict['lossy_rate']}")
    print(f"loss rate, lossy and jittery   {verdict['both_rate']}")
    print(f"the two rates agree            {verdict['the_rates_agree']}")
    print(f"the reliable link loses none   {verdict['the_reliable_link_loses_nothing']}")
    print(f"the jittery only link too      {verdict['and_the_jittery_one_does_too']}")
    print(f"every condition sent the same  {verdict['every_condition_sent_the_same']}")

    if not verdict["the_rates_agree"]:
        raise SystemExit("expected jitter to leave the loss rate where it was")
    if not (
        verdict["the_reliable_link_loses_nothing"] and verdict["and_the_jittery_one_does_too"]
    ):
        raise SystemExit("expected only the two lossy conditions to drop anything")


if __name__ == "__main__":
    main()
