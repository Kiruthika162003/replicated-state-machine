"""Offer writes faster than the cluster can commit and watch the queue decide the latency.

Run with: python examples/push_too_hard.py

A leader that accepts everything has turned a rate problem into a memory problem. Nothing is
lost and nothing is unsafe; the cluster has promised more than it can deliver on time and told
nobody. The interesting part is what bounding the queue costs, which is not what it looks like.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.backpressure import Load, offer
from rsm.node import HEARTBEAT_INTERVAL

RATES = (5, 20, 32, 36, 50, 60)
BOUNDS = (8, 16, 32, 64, 128, 256)
WINDOW = 150


def rate_rows() -> list[dict]:
    """Offered rate against what the cluster actually committed."""
    out = []
    for rate in RATES:
        made = offer(Load(name=f"{rate}", per_tick=rate), window=WINDOW)
        out.append(
            {
                "offered": rate,
                "committed": made.throughput,
                "accepted": made.acceptance,
                "worst depth": made.worst_depth,
                "worst wait": made.worst_wait,
                "still growing": "yes" if made.growing else "no",
            }
        )
    return out


def bound_rows() -> list[dict]:
    """The same overload under a range of queue bounds."""
    out = []
    for bound in BOUNDS:
        made = offer(Load(name=f"b{bound}", per_tick=60, bound=bound), window=WINDOW)
        out.append(
            {
                "bound": bound,
                "predicted": round(bound / HEARTBEAT_INTERVAL, 2),
                "committed": made.throughput,
                "accepted": made.acceptance,
                "worst wait": made.worst_wait,
                "throughput": bar(made.throughput / 32, 20),
            }
        )
    return out


def main() -> None:
    print(rule("offering more than the cluster can take"))
    print(table(rate_rows()))
    print()
    print("the ceiling is flat and acceptance stays at one, so the excess becomes depth and")
    print("the depth becomes the wait of whatever joins the back of it")
    print()

    print(rule("bounding the queue"))
    print(table(bound_rows()))
    print()
    print("throughput under a bound is the bound over the heartbeat interval of")
    print(f"{HEARTBEAT_INTERVAL}, because the leader drains the queue once per heartbeat and")
    print("refuses everything offered in between")
    print()

    unbounded = offer(Load(name="none", per_tick=60), window=WINDOW)
    right = offer(Load(name="right", per_tick=60, bound=128), window=WINDOW)
    print(rule("the bound that costs nothing"))
    print(
        pairs(
            {
                "unbounded throughput": unbounded.throughput,
                "bounded throughput": right.throughput,
                "unbounded worst wait": unbounded.worst_wait,
                "bounded worst wait": right.worst_wait,
                "unbounded refusals": unbounded.refused,
                "bounded refusals": right.refused,
                "unbounded backlog at the end": unbounded.final_depth,
                "bounded backlog at the end": right.final_depth,
            }
        )
    )
    print()
    print("both commit the same number of writes; the difference is entirely in what the")
    print("client was told and when, and in what it could have done about it")


if __name__ == "__main__":
    main()
