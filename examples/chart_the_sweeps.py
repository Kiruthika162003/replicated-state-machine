"""Draw the sweeps that the tables only list, and show what the axis decides.

Run with: python examples/chart_the_sweeps.py

Three of the findings in this package are shapes rather than numbers: the throughput ceiling,
the idle floor and the gap between predicted and measured availability. A table of twelve
numbers hides a shape about as often as it shows one.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.backpressure import Load, offer
from rsm.chart import Series, bars, logarithmic, sparkline
from rsm.eval.availability import SIZES, watch
from rsm.idle import Floor

WIDTH = 44


def draw(series: Series, width: int = WIDTH, log: bool = False) -> None:
    """One chart, with its name above it."""
    print(f"  {series.name}")
    rows = logarithmic(series, width) if log else bars(series, width)
    for one in rows:
        print(f"    {one}")


def throughput() -> Series:
    """What the cluster commits as the offered rate rises past its ceiling."""
    rates = (5, 20, 32, 40, 60)
    return Series(
        name="committed per tick, against offered",
        values=[
            offer(Load(name=f"{one}", per_tick=one), window=150).throughput for one in rates
        ],
        labels=[str(one).rjust(3) for one in rates],
    )


def depth() -> Series:
    """What the uncommitted tail does over the same rates."""
    rates = (5, 20, 32, 40, 60)
    return Series(
        name="worst uncommitted depth, against offered",
        values=[
            float(offer(Load(name=f"{one}", per_tick=one), window=150).worst_depth)
            for one in rates
        ],
        labels=[str(one).rjust(3) for one in rates],
    )


def floor() -> Series:
    """The idle cost against the cluster size."""
    sizes = (1, 3, 5, 7, 9)
    return Series(
        name="idle messages per tick, against size",
        values=[Floor(size=one).per_tick for one in sizes],
        labels=[str(one).rjust(3) for one in sizes],
    )


def error() -> Series:
    """How far the availability formula is from the measured value."""
    values = []
    for size in SIZES:
        runs = [watch(f"{size}", size=size, seed=seed) for seed in range(4)]
        measured = sum(one.write_availability for one in runs) / len(runs)
        predicted = sum(one.predicted for one in runs) / len(runs)
        values.append(round((1 - measured) / max(1e-9, 1 - predicted), 1))
    return Series(
        name="how far the formula is out, against size",
        values=values,
        labels=[str(one).rjust(3) for one in SIZES],
    )


def beats() -> Series:
    """What the heartbeat interval does to the idle floor."""
    intervals = (1, 2, 3, 5, 8)
    return Series(
        name="idle messages per tick, against heartbeat",
        values=[Floor(size=5, heartbeat=one).per_tick for one in intervals],
        labels=[str(one).rjust(3) for one in intervals],
    )


def main() -> None:
    print(rule("the ceiling"))
    draw(throughput())
    print()
    draw(depth())
    print()
    print("  the first is flat past thirty two and the second is not, which is the whole of")
    print("  what happens when a cluster is offered more than it can take")
    print()

    print(rule("the floor"))
    draw(floor())
    print()
    draw(beats())
    print()
    print("  linear in the peers and inverse in the heartbeat, and one node has no floor")
    print()

    print(rule("the same series, two axes"))
    made = error()
    draw(made)
    print()
    draw(made, log=True)
    print()
    print(f"  the values span {made.orders} orders of magnitude, so the linear axis has three")
    print("  empty rows and the logarithmic one has the shape")
    print()

    print(rule("all of them at a glance"))
    print(
        table(
            [
                {
                    "series": one.name,
                    "points": len(one),
                    "orders": one.orders,
                    "shape": sparkline(one),
                }
                for one in (throughput(), depth(), floor(), beats(), error())
            ]
        )
    )
    print()
    print("a sparkline cannot be read for a value and can be read for a shape, which is the")
    print("only thing a column in a table has room for")


if __name__ == "__main__":
    main()
