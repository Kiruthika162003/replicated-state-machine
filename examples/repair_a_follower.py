"""Search for the point where two logs stopped agreeing, four different ways.

Run with: python examples/repair_a_follower.py

A new leader does not know how much of each follower's log it shares. It has one probe, an
append with no entries, and repairing a follower is a search using it. The paper describes two
of the four searches here, and which of them wins depends entirely on how far behind the
follower is.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.node import MAX_BATCH
from rsm.repair import STRATEGIES, _pair, probe

CASES = {
    "current": ([1] * 200, [1] * 200),
    "one behind": ([1] * 200 + [2], [1] * 200 + [3]),
    "deep, one term": ([1] * 40 + [2] * 60, [1] * 40 + [3] * 60),
    "deep, alternating": ([1] * 40 + [2] * 60, [1] * 40 + [3 + one for one in range(60)]),
}


def strategy_rows() -> list[dict]:
    """Probes per strategy per case."""
    out = []
    for label, (leader_terms, follower_terms) in CASES.items():
        row = {"divergence": label}
        for name, strategy in STRATEGIES.items():
            leader, follower = _pair(leader_terms, follower_terms, term=200)
            row[name] = strategy(leader, follower).probes
        out.append(row)
    return out


def depth_rows() -> list[dict]:
    """How each strategy grows as the divergence deepens."""
    out = []
    for depth in (1, 5, 20, 60, 120):
        leader = [1] * 40 + [2] * depth
        follower = [1] * 40 + [3] * depth
        row = {"behind": depth}
        for name, strategy in STRATEGIES.items():
            left, right = _pair(leader, follower, term=depth + 10)
            row[name] = strategy(left, right).probes
        out.append(row)
    return out


def main() -> None:
    print(rule("one probe"))
    leader, follower = _pair([1] * 10 + [2], [1] * 10 + [3], term=20)
    print(
        pairs(
            {
                "leader's last index": leader.log.last_index,
                "probe at the end": probe(leader, follower, 11).success,
                "probe at ten": probe(leader, follower, 10).success,
                "so they agree up to": 10,
                "an empty append changes nothing": len(follower.log),
            }
        )
    )
    print()
    print("an append with no entries is a question: accepting it proves agreement at that")
    print("index, and refusing says only that the entry after it cannot be placed")
    print()

    print(rule("probes needed, by divergence"))
    print(table(strategy_rows()))
    print()
    print("walking back is unbeatable when the follower is nearly current and unbounded when")
    print("it is not; the conflict optimisation ties it exactly when the terms alternate")
    print()

    print(rule("how they grow"))
    print(table(depth_rows()))
    print()
    print("bisection is bounded by the log length, not the divergence, and the batch of")
    print(f"{MAX_BATCH} is what makes the entry path a staircase rather than a line")
    print()

    print(rule("the shape of it"))
    for name, strategy in STRATEGIES.items():
        left, right = _pair([1] * 40 + [2] * 60, [1] * 40 + [3 + one for one in range(60)], 200)
        probes = strategy(left, right).probes
        print(f"  {name.ljust(10)} {bar(min(1.0, probes / 61), 30)} {probes}")
    print()
    print("no strategy wins every row, and the hybrid is never far behind the winner")


if __name__ == "__main__":
    main()
