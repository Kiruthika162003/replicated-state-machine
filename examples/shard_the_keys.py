"""Split the keyspace, watch the throughput multiply, and lose atomicity at the first split.

Run with: python examples/shard_the_keys.py

Sharding is the standard answer to a throughput ceiling and it works. What it costs is not a
number that can be tuned: any two writes inside one group are ordered against each other, and
across two groups they are not, and that is gone as soon as there are two groups.
"""

from __future__ import annotations

import contextlib

from examples.common import pairs, rule, table
from rsm.errors import NoLeader
from rsm.keyspace import Federation, Keyspace
from rsm.rebalance import PHASES, Move, run_move

KEYS = 120


def group_rows() -> list[dict]:
    """Each group count with what it committed and what it cost."""
    keys = [f"k{one}" for one in range(KEYS)]
    out = []
    for groups in (1, 2, 4, 8):
        space = Keyspace(groups=groups)
        fed = Federation(keyspace=space)
        for index, key in enumerate(keys):
            with contextlib.suppress(NoLeader):
                fed.write(key, index)
            if index % 10 == 0:
                fed.tick(2)
        fed.tick(40)
        out.append(
            {
                "groups": groups,
                "nodes": groups * fed.size,
                "committed": fed.committed(),
                "messages": fed.messages(),
                "per write": round(fed.messages() / max(1, fed.committed()), 1),
                "balance": space.balance(keys),
                "atomic": "yes" if groups == 1 else "no",
            }
        )
    return out


def move_rows() -> list[dict]:
    """The phases a range passes through, and who owns it in each."""
    made = Move(keys=("a", "b"), source=0, destination=1)
    out = []
    for phase in PHASES:
        made.phase = phase
        out.append(
            {
                "phase": phase,
                "owner": made.owner,
                "serving": "yes" if made.serving else "no",
            }
        )
    return out


def main() -> None:
    print(rule("splitting the keyspace"))
    print(table(group_rows()))
    print()
    print("more groups commit the same writes in parallel and send fewer messages, because")
    print("there is no traffic between groups at all")
    print()

    space = Keyspace(groups=4)
    keys = [f"k{one}" for one in range(KEYS)]
    print(rule("where the keys land"))
    print(pairs({f"group {one}": count for one, count in space.spread(keys).items()}))
    print()
    print(f"balance: {space.balance(keys)} times the fair share in the largest group")
    print()

    print(rule("moving a range between groups"))
    print(table(move_rows()))
    print()
    print("nobody owns it during the copy, which is the point: an unavailable range is a")
    print("refusal a client can handle, and two owners is two clients told different things")
    print()

    safe, move = run_move("phased")
    unsafe, _ = run_move("both sides", unsafe=True)
    print(rule("what the freeze buys"))
    print(
        pairs(
            {
                "phased availability": safe.availability,
                "phased moments with two owners": safe.two_owners,
                "both sides availability": unsafe.availability,
                "both sides moments with two owners": unsafe.two_owners,
                "range size in bytes": move.nbytes,
                "unavailable for": move.unavailable_for,
            }
        )
    )
    print()
    print("serving from both sides during the copy is the obvious optimisation, and what it")
    print("removes is the only thing supplying an order between the two groups")


if __name__ == "__main__":
    main()
