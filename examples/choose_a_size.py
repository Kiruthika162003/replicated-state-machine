"""Size a cluster three ways and watch the three answers disagree.

Run with: python examples/choose_a_size.py

Quorum arithmetic says one thing, the binomial availability formula says another, and running
the cluster says a third. All three are right about what they measure, and only one of them is
about what a client experiences.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.eval.availability import SIZES, binomial, watch
from rsm.eval.tuning import WEIGHTINGS, sweep
from rsm.quorum import Rule, majority, raft, tolerates


def arithmetic_rows() -> list[dict]:
    """What the quorum rule says about each size."""
    return [
        {
            "size": size,
            "majority": majority(size),
            "tolerates": tolerates(size),
            "write waits for": raft(size).write_cost,
            "gain over the last": tolerates(size) - tolerates(size - 1) if size > 1 else 0,
        }
        for size in (1, 2, 3, 4, 5, 6, 7, 8, 9)
    ]


def formula_rows() -> list[dict]:
    """What the binomial says, given a node that is up ninety five percent of the time."""
    return [
        {
            "size": size,
            "each node up": 0.95,
            "majority up": binomial(size, 0.95),
            "unavailability": round(1 - binomial(size, 0.95), 6),
        }
        for size in SIZES
    ]


def measured_rows() -> list[dict]:
    """What the cluster actually did under repeated failures."""
    out = []
    for size in SIZES:
        runs = [watch(f"{size}", size=size, seed=seed) for seed in range(4)]
        measured = sum(one.write_availability for one in runs) / len(runs)
        predicted = sum(one.predicted for one in runs) / len(runs)
        out.append(
            {
                "size": size,
                "nodes up": round(sum(one.node_availability for one in runs) / len(runs), 3),
                "formula says": round(predicted, 6),
                "writes landed": round(measured, 4),
                "understated by": round((1 - measured) / max(1e-9, 1 - predicted), 1),
            }
        )
    return out


def main() -> None:
    print(rule("what the quorum arithmetic says"))
    print(table(arithmetic_rows()))
    print()
    print("every even size tolerates what the odd one below it does and costs a write")
    print("acknowledgement more, so half the sizes in the table buy nothing")
    print()

    print(rule("what the binomial says"))
    print(table(formula_rows()))
    print()
    print("more nodes, exponentially better, which is the argument everybody makes")
    print()

    print(rule("what the cluster did"))
    print(table(measured_rows()))
    print()
    print("the formula improves without limit and the cluster stops at about ninety nine")
    print("percent, because what is left when a majority is up is the election after a")
    print("leader dies, and that does not shrink with the cluster")
    print()

    made = sweep()
    print(rule("and what a sweep would recommend"))
    print(pairs({name: made.best(one)["setting"] for name, one in WEIGHTINGS.items()}))
    print()
    print("every objective picks the smallest cluster, because no run in the sweep has a")
    print("failure in it and an objective can only value what the runs exercise")
    print()

    print(rule("the flexible rules nobody uses"))
    print(
        table(
            [
                {
                    "rule": name,
                    **Rule(size=5, election=election, commit=commit, name=name).as_dict(),
                }
                for name, election, commit in (
                    ("majority", 3, 3),
                    ("cheap writes", 4, 2),
                    ("cheap elections", 2, 4),
                )
            ]
        )
    )
    print()
    print("all three are safe, all three cost four in total, and the choice is only where to")
    print("pay it")
    print()
    print("safe:", bar(1.0, 20), "for every row above")


if __name__ == "__main__":
    main()
