"""Count what a cluster costs while nothing is happening, and find where that stops mattering.

Run with: python examples/price_an_idle_cluster.py

Every other measurement in this package is per write. A leader with nothing to replicate still
beats at every follower forever, and for a cluster that takes a hundred writes a day the
heartbeats are not a rounding error on the bill, they are the bill.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.idle import RATES, Floor, measure
from rsm.node import HEARTBEAT_INTERVAL


def floor_rows() -> list[dict]:
    """The predicted floor against the measured one, at each size."""
    out = []
    for size in (1, 3, 5, 7, 9):
        made = Floor(size=size)
        found = measure(size=size) if size > 1 else {"per_tick": 0.0, "messages": 0}
        out.append(
            {
                "size": size,
                "peers": made.peers,
                "predicted": made.per_tick,
                "measured": found["per_tick"],
                "over a window": made.per_window,
                "crossover": made.crossover() if made.peers else "none",
            }
        )
    return out


def heartbeat_rows() -> list[dict]:
    """What the heartbeat interval does to the floor and to the crossover."""
    return [
        {
            "heartbeat": beat,
            "floor per tick": Floor(size=5, heartbeat=beat).per_tick,
            "bytes per tick": Floor(size=5, heartbeat=beat).bytes_per_tick,
            "crossover": Floor(size=5, heartbeat=beat).crossover(),
            "safe": "yes" if beat <= 5 else "no",
        }
        for beat in (1, 2, 3, 5, 8, 12)
    ]


def rate_rows() -> list[dict]:
    """How much of the bill is the floor, at several write rates."""
    made = Floor(size=5)
    cost = 2 * made.peers
    out = []
    for rate in RATES:
        total = made.per_tick + (rate / 100) * cost
        out.append(
            {
                "writes per hundred ticks": rate,
                "total per tick": round(total, 3),
                "floor share": round(made.per_tick / total, 3),
                "bar": bar(made.per_tick / total, 24),
            }
        )
    return out


def main() -> None:
    print(rule("the floor, predicted and measured"))
    print(table(floor_rows()))
    print()
    print("one node has no peers and so no floor, and no crossover either, because there is")
    print("nothing for the writes to be compared against; it is also the only configuration")
    print("here that tolerates nothing")
    print()

    print(rule("what the heartbeat does to it"))
    print(table(heartbeat_rows()))
    print()
    print("the only setting that moves the floor, and timing.py puts the safe limit at five")
    print("against a timeout of ten, so it can be cut to two fifths and no further")
    print()

    print(rule("how much of the bill it is"))
    print(table(rate_rows()))
    print()
    made = Floor(size=5)
    print(
        pairs(
            {
                "shipped heartbeat": HEARTBEAT_INTERVAL,
                "floor at five nodes": made.per_tick,
                "crossover rate": made.crossover(),
                "which is a hundred over the heartbeat": round(100 / HEARTBEAT_INTERVAL, 2),
            }
        )
    )
    print()
    print("most clusters live at the left of that table and are tuned as though they lived at")
    print("the right")


if __name__ == "__main__":
    main()
