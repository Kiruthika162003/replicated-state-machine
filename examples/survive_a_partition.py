"""Cut a cluster in half, write to both sides, and watch the minority get nowhere.

Run with: python examples/survive_a_partition.py

Two things worth seeing here. The minority side cannot elect anybody however long it runs, so it
cannot accept a write at all, which is the availability half of the trade. And when the
partition heals, the side that was cut off adopts the other side's log without anybody deciding
that it should; the term is enough.
"""

from __future__ import annotations

import contextlib

from examples.common import pairs, rule, table
from rsm.cluster import Cluster
from rsm.errors import NoLeader

SIZE = 5
SEED = 1
SETTLE = 40
SPLIT = 120
HEAL = 120


def state(cluster: Cluster, label: str) -> dict:
    """One row describing where the cluster is."""
    found = cluster.leader()
    return {
        "phase": label,
        "tick": cluster.now,
        "leader": found.name if found else "nobody",
        "term": max(one.term for one in cluster.nodes.values()),
        "committed": len(cluster.committed()),
        "agreed": cluster.agreed(),
    }


def logs(cluster: Cluster) -> list[dict]:
    """Every node's log, so the two sides can be compared entry by entry."""
    return [
        {
            "node": name,
            "last": cluster.nodes[name].log.last_index,
            "term": cluster.nodes[name].log.last_term,
            "commit": cluster.nodes[name].commit_index,
            "entries": " ".join(str(one) for one in cluster.nodes[name].log.entries[-6:]),
        }
        for name in cluster.members
    ]


def main() -> None:
    made = Cluster(size=SIZE, seed=SEED).settle()
    rows = [state(made, "settled")]
    for one in range(3):
        made.propose(("set", "before", one))
    made.run(SETTLE)
    rows.append(state(made, "wrote three"))

    old = made.leader()
    majority = [one for one in made.members if one != old.name][:3]
    minority = [one for one in made.members if one not in majority]
    print(rule("splitting"))
    print(pairs({"minority": ", ".join(minority), "majority": ", ".join(majority)}))
    print()
    made.partition([minority, majority])

    stranded = 0
    for one in range(6):
        made.run(SPLIT // 6)
        if old.is_leader:
            old.propose(("set", "stranded", one))
            stranded += 1
        with contextlib.suppress(NoLeader):
            made.propose(("set", "during", one))
    rows.append(state(made, "split"))

    print(rule("during the split"))
    print(table(logs(made)))
    print()
    print(
        pairs(
            {
                "the old leader still thinks it leads": old.is_leader,
                "writes it accepted": stranded,
                "writes it committed": max(0, old.commit_index - 4),
                "its term": old.term,
                "the new term": max(one.term for one in made.nodes.values()),
            }
        )
    )
    print()
    print("a stranded leader does not step down, because nothing reaches it to say so")
    print("it accepts writes and commits none of them, and its term stops moving")
    print()

    made.heal()
    made.run(HEAL)
    for one in range(3):
        with contextlib.suppress(NoLeader):
            made.propose(("set", "after", one))
    made.run(SETTLE)
    rows.append(state(made, "healed"))

    print(rule("after healing"))
    print(table(logs(made)))
    print()
    print(rule("the run"))
    print(table(rows))
    print()
    print("the stranded side accepted writes that never committed, and lost them on healing")
    print("the healed cluster agrees on one log, and nothing that was committed is missing")


if __name__ == "__main__":
    main()
