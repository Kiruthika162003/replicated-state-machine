"""One thing from each part of the package, in the order they build on each other.

Run with: python examples/tour.py

A tour rather than a demonstration. Each section is two or three lines from a module that has a
great deal more to say, and the point is the order: a log, then agreement about a log, then what
agreement costs, then what it does not give you.
"""

from __future__ import annotations

from examples.common import pairs, rule
from rsm.cluster import Cluster
from rsm.idle import Floor
from rsm.keyspace import Keyspace
from rsm.log import written
from rsm.quorum import majority, raft
from rsm.rejoin import crossover
from rsm.repair import STRATEGIES, _pair
from rsm.rpc import Vote
from rsm.timing import SETTINGS
from rsm.wire import encode


def main() -> None:
    print(rule("a log"))
    made = written([1, 1, 2, 2, 3])
    print(
        pairs(
            {
                "entries": len(made),
                "last": str(made.entries[-1]),
                "term at three": made.term_at(3),
                "it matches at three": made.matches(3, 2),
                "and not at the wrong term": made.matches(3, 1),
            }
        )
    )
    print()

    print(rule("agreement about it"))
    cluster = Cluster(size=5, seed=1).settle()
    for one in range(4):
        cluster.propose(("set", "k", one))
    cluster.run(40)
    found = cluster.leader()
    print(
        pairs(
            {
                "leader": found.name,
                "term": found.term,
                "committed": len(cluster.committed()),
                "everyone agrees": cluster.agreed(),
                "majority of five": majority(5),
                "and it tolerates": raft(5).survives,
            }
        )
    )
    print()

    print(rule("what it costs"))
    print(
        pairs(
            {
                "messages so far": cluster.net.counts.sent,
                "per committed write": round(
                    cluster.net.counts.sent / max(1, len(cluster.committed())), 1
                ),
                "idle floor per tick": Floor(size=5).per_tick,
                "a vote on the wire": len(encode(Vote(sender="a", recipient="b", term=1))),
                "the shipped heartbeat": SETTINGS["shipped"].heartbeat,
            }
        )
    )
    print()

    print(rule("what goes wrong and what fixes it"))
    leader, _ = _pair([1] * 40 + [2] * 60, [1] * 40 + [3] * 60, term=200)
    probes = {
        name: fn(*_pair([1] * 40 + [2] * 60, [1] * 40 + [3] * 60, 200)).probes
        for name, fn in STRATEGIES.items()
    }
    print(
        pairs(
            {
                "a follower sixty entries adrift": leader.log.last_index,
                **{f"repaired by {name}": one for name, one in probes.items()},
                "or replaced by a snapshot past": crossover(400),
            }
        )
    )
    print()

    print(rule("and what agreement does not give you"))
    space = Keyspace(groups=4)
    other = "beta"
    while space.group_of(other) == space.group_of("alpha"):
        other += "x"
    print(
        pairs(
            {
                "groups": space.groups,
                "alpha lives in": space.group_of("alpha"),
                f"{other} lives in": space.group_of(other),
                "a write to both is atomic": False,
                "because two logs have no order between them": True,
            }
        )
    )
    print()
    print("every module in the package is one of these five sentences with the measurements")
    print("attached; run rsm.cli.main report for what all of them found")


if __name__ == "__main__":
    main()
