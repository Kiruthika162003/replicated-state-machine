"""Count what a write costs at several cluster sizes and link settings.

Run with: python examples/measure_the_cost.py

Everything is counted rather than timed. A message count is a fact about the algorithm and
survives being translated into whatever the transport turns out to be; a duration is a fact
about one machine on one afternoon.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.cluster import Cluster
from rsm.eval.workload import LOADS, measure
from rsm.log import Entry
from rsm.quorum import majority
from rsm.repair import STRATEGIES, _pair
from rsm.rpc import Append
from rsm.wire import ASSUMED_ENTRY_BYTES, ASSUMED_MESSAGE_BYTES, encode
from rsm.wire import measure as weigh


def workload_rows() -> list[dict]:
    """Every named workload with what it cost."""
    return [measure(one).as_dict() for one in LOADS.values()]


def size_rows() -> list[dict]:
    """The per write cost against the cluster size, and against the peer count."""
    out = []
    for size in (3, 5, 7, 9):
        made = weigh(Cluster(size=size, seed=1), ticks=60, writes=6)
        out.append(
            {
                "size": size,
                "quorum": majority(size),
                "messages": made.messages,
                "per node": round(made.messages / size, 1),
                "per peer": round(made.messages / (size - 1), 1),
                "bytes": made.real,
                "estimate": made.assumed,
                "error": made.error,
            }
        )
    return out


def repair_rows() -> list[dict]:
    """How many probes each repair strategy needs on a shallow and a deep divergence."""
    out = []
    for label, (leader_terms, follower_terms) in {
        "one behind": ([1] * 200 + [2], [1] * 200 + [3]),
        "sixty behind": ([1] * 40 + [2] * 60, [1] * 40 + [3 + one for one in range(60)]),
    }.items():
        row = {"divergence": label}
        for name, strategy in STRATEGIES.items():
            leader, follower = _pair(leader_terms, follower_terms, term=200)
            row[name] = strategy(leader, follower).probes
        out.append(row)
    return out


def main() -> None:
    print(rule("named workloads"))
    print(table(workload_rows()))
    print()
    print("the link settings move the cost more than the cluster size does, and a jittery")
    print("link is the dearest setting in the table")
    print()

    print(rule("cost against size"))
    print(table(size_rows()))
    print()
    print("per node the cost climbs, per peer it is flat, because a broadcast is one message")
    print("per peer and a node is not its own peer")
    print()

    print(rule("repairing a divergent follower"))
    print(table(repair_rows()))
    print()
    print("walking back is unbeatable when the follower is nearly current and unbounded when")
    print("it is not; bisecting is the other way round; no strategy wins both rows")
    print()

    empty = len(encode(Append(sender="n0", recipient="n1", term=2)))
    loaded = len(
        encode(
            Append(
                sender="n0",
                recipient="n1",
                term=2,
                entries=(Entry(index=1, term=1, command="('set', 'k', 1)"),),
            )
        )
    )
    run = weigh(Cluster(size=5, seed=1), ticks=60, writes=6)
    print(rule("what the byte estimate assumes"))
    print(
        pairs(
            {
                "assumed per message": ASSUMED_MESSAGE_BYTES,
                "a real empty append": empty,
                "assumed per entry": ASSUMED_ENTRY_BYTES,
                "a real entry": loaded - empty,
                "the estimate over a run": run.error,
                "how close that is": bar(min(1.0, 1 / run.error), 20),
            }
        )
    )
    print()
    print("the estimate is poor per message and within a tenth over a run, because the kinds")
    print("it is worst at are the ones that barely appear")


if __name__ == "__main__":
    main()
