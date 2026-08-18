"""Four ways to answer a read, and what each of them does when the leader is stranded.

Run with: python examples/read_without_lying.py

A write is safe because it goes through the log. A read is only safe if it can establish that
the node answering it is still the leader, and there are four ways to try. Three of them are
correct and they differ in what they cost and what they refuse.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.lease import LEASE, Lease, _write_then_read
from rsm.node import HEARTBEAT_INTERVAL, MIN_ELECTION_TIMEOUT

LENGTHS = (5, 10, 15, 20, 25, 40)
DRIFTS = (0, 4, 8, 12)


def strategy_rows() -> list[dict]:
    """Each strategy over the same partition."""
    out = []
    for name in ("local", "lease", "through"):
        made = _write_then_read(name)
        out.append(
            {
                "strategy": name,
                "answered": made.served,
                "refused": made.refused,
                "stale": made.stale,
                "correct": "yes" if made else "no",
            }
        )
    return out


def length_rows() -> list[dict]:
    """The lease length swept past the point where it stops being sound."""
    return [
        {
            "lease": length,
            "answered": _write_then_read("lease", length=length).served,
            "stale": _write_then_read("lease", length=length).stale,
            "under the timeout": "yes" if length < MIN_ELECTION_TIMEOUT * 2 else "no",
        }
        for length in LENGTHS
    ]


def drift_rows() -> list[dict]:
    """A clock that runs slow, and the difference between unsound and wrong."""
    out = []
    for drift in DRIFTS:
        made = _write_then_read("lease", length=10, drift=drift)
        out.append(
            {
                "drift": drift,
                "answered": made.served,
                "outside the lease": made.unsound,
                "actually stale": made.stale,
            }
        )
    return out


def main() -> None:
    print(rule("the same partition, three strategies"))
    print(table(strategy_rows()))
    print()
    print("the local read answers everything and is wrong most of the time, with no error")
    print("and no refusal to say so; the other two are correct and refuse instead")
    print()

    print(rule("how long a lease may be"))
    print(table(length_rows()))
    print()
    print("the boundary is the longest election timeout, which is the whole safety argument:")
    print("a lease is sound only while nobody else could have been elected yet")
    print()

    print(rule("what a wrong clock costs"))
    print(table(drift_rows()))
    print()
    print("the number of answers given outside the lease is exactly the drift, and whether")
    print("any of them is wrong is a different question with a later answer")
    print()

    shipped = Lease(holder="n0", granted_at=0)
    print(rule("the shipped setting"))
    print(
        pairs(
            {
                "lease": LEASE,
                "heartbeat": HEARTBEAT_INTERVAL,
                "shortest timeout": MIN_ELECTION_TIMEOUT,
                "renewable": LEASE > HEARTBEAT_INTERVAL,
                "expires at": shipped.expires_at,
                "margin against the timeout": MIN_ELECTION_TIMEOUT * 2 - LEASE,
            }
        )
    )
    print()
    print("longer than a heartbeat so it can be renewed before it lapses, and far shorter")
    print("than an election timeout so a clock that is wrong by a little is still safe")


if __name__ == "__main__":
    main()
