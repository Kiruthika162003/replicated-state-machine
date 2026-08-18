"""Watch a cold cluster elect a leader, one tick at a time.

Run with: python examples/elect_a_leader.py

The point of printing every tick rather than the outcome is that the outcome is boring and
identical every time, and the ticks are where the algorithm is. A cold cluster spends the first
ten ticks doing nothing at all, because every node is waiting out a randomised timer, and the
election itself takes two.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.cluster import Cluster
from rsm.node import CANDIDATE, LEADER, MAX_ELECTION_TIMEOUT, MIN_ELECTION_TIMEOUT

SIZE = 5
SEED = 3
TICKS = 30


def roles(cluster: Cluster) -> dict:
    """What every node believes it is right now, as one row."""
    return {
        "tick": cluster.now,
        **{
            name: _short(cluster.nodes[name].role, cluster.nodes[name].term)
            for name in cluster.members
        },
        "in flight": cluster.net.in_flight,
    }


def _short(role: str, term: int) -> str:
    """A role and a term in one small cell."""
    letter = {LEADER: "L", CANDIDATE: "C"}.get(role, "f")
    return f"{letter}{term}"


def deadlines(cluster: Cluster) -> dict:
    """The tick each node will stand at if it has not heard from a leader by then."""
    return {name: cluster.nodes[name].election_deadline for name in cluster.members}


def main() -> None:
    made = Cluster(size=SIZE, seed=SEED)
    print(rule("the timers, drawn before anything happens"))
    print(pairs(deadlines(made)))
    print()
    print(f"every timer is drawn from {MIN_ELECTION_TIMEOUT} to {MAX_ELECTION_TIMEOUT} ticks")
    print("the smallest one is the node that will stand first, and it stands alone")
    print()

    rows = [roles(made)]
    for _ in range(TICKS):
        made.tick()
        rows.append(roles(made))

    print(rule("the run, one row per tick"))
    print(table(rows))
    print()
    print("f is a follower, C a candidate, L a leader, and the number is the term")
    print()

    found = made.leader()
    print(rule("what happened"))
    print(
        pairs(
            {
                "leader": found.name if found else "nobody",
                "term": found.term if found else 0,
                "elections": made.elections,
                "messages": made.net.counts.sent,
                "first entry": str(found.log.at(1)) if found and len(found.log) else "none",
                "it is empty": found.log.at(1).is_noop if found and len(found.log) else False,
            }
        )
    )
    print()
    print("the leader's first act is to append an entry with no command in it, which is how")
    print("it establishes that its own term has an entry to commit")


if __name__ == "__main__":
    main()
