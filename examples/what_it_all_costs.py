"""One costing sheet for a cluster, from the floor to the read strategy.

Run with: python examples/what_it_all_costs.py

Every module in this package prices one thing. This puts the prices side by side for a single
imagined deployment, because the interesting question is never what a write costs, it is which
of the costs is the one that matters for the workload in front of you.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.batch import ship
from rsm.chart import Series, bars
from rsm.eval.mix import LEASE, LOCAL, READ_INDEX, THROUGH_THE_LOG, Mix
from rsm.idle import Floor
from rsm.node import HEARTBEAT_INTERVAL, MAX_BATCH
from rsm.quorum import majority, raft
from rsm.rejoin import by_entries, by_snapshot, crossover
from rsm.rpc import Append, RequestVote, Vote
from rsm.wire import encode

SIZE = 5
READS = 0.9


def message_rows() -> list[dict]:
    """What each kind of message costs on the wire."""
    made = [
        RequestVote(sender="n0", recipient="n1", term=3, last_index=4, last_term=2),
        Vote(sender="n1", recipient="n0", term=3, granted=True),
        Append(sender="n0", recipient="n1", term=3, previous_index=4, previous_term=2),
    ]
    return [{"message": one.kind, "bytes": len(encode(one))} for one in made] + [
        {"message": f"append of {MAX_BATCH}", "bytes": ship(MAX_BATCH, batch=MAX_BATCH).nbytes}
    ]


def strategy_rows() -> list[dict]:
    """What a read costs under each strategy, at ninety percent reads."""
    return [
        {
            "strategy": one,
            "per read": Mix(reads=READS, strategy=one, size=SIZE).read_cost,
            "per operation": Mix(reads=READS, strategy=one, size=SIZE).cost,
            "read share of the bill": Mix(
                reads=READS, strategy=one, size=SIZE
            ).read_share_of_cost,
            "can be stale": "no" if Mix(reads=READS, strategy=one).correct else "yes",
        }
        for one in (LOCAL, LEASE, READ_INDEX, THROUGH_THE_LOG)
    ]


def catch_up_rows() -> list[dict]:
    """What it costs to catch a returning node up, by how far behind it is."""
    return [
        {
            "behind": behind,
            "by entries": by_entries(behind).nbytes,
            "by snapshot": by_snapshot(400).nbytes,
            "cheaper": "entries"
            if by_entries(behind).nbytes < by_snapshot(400).nbytes
            else "snapshot",
        }
        for behind in (0, 10, 100, 292, 1000)
    ]


def main() -> None:
    floor = Floor(size=SIZE)
    print(rule(f"a cluster of {SIZE}, doing nothing"))
    print(
        pairs(
            {
                "majority": majority(SIZE),
                "tolerates": raft(SIZE).survives,
                "heartbeat": HEARTBEAT_INTERVAL,
                "idle messages per tick": floor.per_tick,
                "idle bytes per tick": floor.bytes_per_tick,
                "crossover write rate": floor.crossover(),
            }
        )
    )
    print()
    print("below that write rate the cluster is mostly paying to exist")
    print()

    print(rule("what a message costs"))
    print(table(message_rows()))
    print()
    print("batching sixty four entries into one append removes the framing sixty three times")
    print()

    print(rule(f"what a read costs, at {int(READS * 100)} percent reads"))
    print(table(strategy_rows()))
    print()
    made = Series(
        name="share of the bill the reads are",
        values=[one["read share of the bill"] for one in strategy_rows()],
        labels=[one["strategy"].rjust(16) for one in strategy_rows()],
    )
    for one in bars(made, 30):
        print(f"  {one}")
    print()
    print("the free one is the one that can be stale, and the cheapest correct one needs a")
    print("clock assumption that nothing else in the package needs")
    print()

    print(rule("what a returning node costs"))
    print(table(catch_up_rows()))
    print()
    print(f"the crossing is at {crossover(400)} entries for a state of four hundred keys, and")
    print("compaction decides whether the entry path exists at all")
    print()

    print(rule("which of these matters"))
    for label, share in (
        ("a store taking one write per hundred ticks", 0.97),
        ("a store at the crossover rate", 0.5),
        ("a store taking a hundred writes per hundred ticks", 0.25),
    ):
        print(f"  {label}")
        print(f"    idle share of the bill {bar(share, 30)} {share}")
    print()
    print("most clusters are the first line and are sized and tuned as though they were the")
    print("third")


if __name__ == "__main__":
    main()
