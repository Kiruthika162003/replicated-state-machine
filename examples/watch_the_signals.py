"""Run five faults past five health signals and print which cells are blank.

Run with: python examples/watch_the_signals.py

Every signal here is one a real deployment exports. The question is not whether they can be
computed but which of them would have told somebody that the cluster had stopped working, and
the answer is that the cheapest one to publish is the one that says the least.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.observe import SIGNALS, matrix, readings


def signal_rows() -> list[dict]:
    """The raw numbers, one row per scenario."""
    return [one.as_dict() for one in readings().values()]


def detection_rows() -> list[dict]:
    """The matrix, with a mark where the signal moved enough to notice."""
    made = matrix()
    return [
        {"fault": name, **{signal: "x" if row[signal] else "." for signal in SIGNALS}}
        for name, row in made.items()
    ]


def main() -> None:
    runs = readings()
    print(rule("what each run actually did"))
    print(table(signal_rows()))
    print()

    print(rule("which signals noticed"))
    print(table(detection_rows()))
    print()
    print("x means the signal moved by more than a fifth in the direction that means trouble")
    print()

    real = [name for name, one in runs.items() if one.commit_rate < 0.95]
    handled = [
        name for name, one in runs.items() if name != "healthy" and one.commit_rate >= 0.95
    ]
    print(rule("reading the matrix"))
    print(
        pairs(
            {
                "faults that lost writes": ", ".join(real),
                "faults the cluster handled": ", ".join(handled),
            }
        )
    )
    print()

    deaf = runs["deaf leader"]
    print(rule("the row worth staring at"))
    print(
        pairs(
            {
                "leader present": deaf.leader_uptime,
                "term rate": deaf.term_rate,
                "message rate": deaf.message_rate,
                "replica lag": deaf.worst_lag,
                "healthy replica lag": runs["healthy"].worst_lag,
                "commit rate": deaf.commit_rate,
            }
        )
    )
    print()
    print("a leader that cannot hear keeps the office at full uptime with a flat term, and")
    print("its replica lag is lower than a healthy cluster's, because a commit index that")
    print("never moves is one that nobody can fall behind")


if __name__ == "__main__":
    main()
