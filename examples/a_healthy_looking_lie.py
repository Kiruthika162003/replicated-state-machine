"""Of seven ways to cut a cluster's links, one produces a health check that is exactly wrong.

Run with: python examples/a_healthy_looking_lie.py

Whether a node believes it has a leader is cheap to measure and easy to export as a health
signal. It is also wrong in exactly the case that matters most: a leader that can send but not
receive keeps believing it leads, keeps its term flat, shows no failover, and commits nothing at
all, which is a hundred percent uptime by the easy signal and zero percent by the one that
counts. The other broken shapes at least dip in uptime or trigger a visible failover; this one
does not, and that is what makes it worth a table rather than a sentence.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.partition import compare_the_cuts, only_one_cut_in_the_table_is_genuinely_misleading


def main() -> None:
    print(rule("seven ways to cut the same cluster's links"))
    print(table(compare_the_cuts()))
    print()

    verdict = only_one_cut_in_the_table_is_genuinely_misleading()
    print(rule("which of the broken runs actually lies about its health"))
    print(f"runs                          {verdict['runs']}")
    print(f"healthy by the commit index   {verdict['healthy']}")
    print(f"broken by the commit index    {verdict['broken']}")
    print(f"looks healthy anyway          {verdict['inverted']}")
    print(f"exactly one such run          {verdict['there_is_exactly_one']}")
    print(f"and it is the deaf leader     {verdict['and_it_is_the_deaf_leader']}")
    print(f"its reported uptime           {verdict['its_uptime']}")
    print(f"its actual commits            {verdict['its_commits']}")

    if not verdict["there_is_exactly_one"]:
        raise SystemExit("expected exactly one cut to invert the health signal")
    if not verdict["and_it_is_the_deaf_leader"]:
        raise SystemExit("expected the deafened leader to be the inverted case")


if __name__ == "__main__":
    main()
