"""Give keys a lifetime, and see the replicas disagree the moment their clocks do.

Run with: python examples/expire_a_lock.py

A lock that releases when its holder dies is the reason coordination services exist. The obvious
way to build it reads a clock inside the state machine, which is the one thing a replicated
state machine must not do, and the failure is invisible until the clocks disagree by a tick.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.expire import LEASE, SWEEP, Lease, Store, run


def arrangement_rows() -> list[dict]:
    """Both arrangements, with and without clock skew."""
    out = []
    for label, by_clock, skew in (
        ("clock, aligned", True, 0),
        ("clock, skewed", True, 4),
        ("log, aligned", False, 0),
        ("log, skewed", False, 4),
    ):
        made = run(label, by_clock=by_clock, skew=skew)
        out.append(
            {
                "arrangement": label,
                "entries": made.entries,
                "cost": made.cost,
                "divergences": made.divergences,
                "worst delay": made.worst_delay,
                "agreed": "yes" if made.agreed else "no",
            }
        )
    return out


def sweep_rows() -> list[dict]:
    """How the sweep interval trades delay against nothing."""
    out = []
    for sweep in (2, 5, 10, 20):
        made = run(f"sweep {sweep}", by_clock=False, sweep=sweep)
        out.append(
            {
                "sweep": sweep,
                "entries": made.entries,
                "worst delay": made.worst_delay,
                "agreed": "yes" if made.agreed else "no",
            }
        )
    return out


def replicas_at(tick: int, skew: int) -> list[dict]:
    """What each replica holds at one tick, under clock driven expiry."""
    stores = [Store(name=f"r{one}", by_clock=True) for one in range(3)]
    for store in stores:
        store.grant(Lease(key="lock", value="held", granted_at=0, length=LEASE))
    for index, store in enumerate(stores):
        store.tick(tick + index * skew)
    return [
        {
            "replica": store.name,
            "its clock": store.now,
            "holds the lock": "yes" if store.keys() else "no",
        }
        for store in stores
    ]


def main() -> None:
    print(rule("one lock, three replicas, four ticks of skew"))
    print(table(replicas_at(tick=LEASE - 2, skew=4)))
    print()
    print("every replica applied the same entries in the same order and they disagree about")
    print("whether the lock is held, because the state depends on when each one looked")
    print()

    print(rule("both arrangements, with and without skew"))
    print(table(arrangement_rows()))
    print()
    print("the row that fails is the one that will ship: with the clocks aligned the clock")
    print("version diverges not at all, and a few milliseconds of skew is a third of the run")
    print()

    print(rule("what the log version costs"))
    print(table(sweep_rows()))
    print()
    print("a shorter sweep shortens the delay and writes the same entries, because the")
    print("entries are one per expiry however often the leader looks")
    print()

    clock = run("clock", by_clock=True, skew=4)
    log = run("log", by_clock=False, skew=4)
    print(rule("the price of agreeing"))
    print(
        pairs(
            {
                "clock entries": clock.entries,
                "log entries": log.entries,
                "ratio": round(log.entries / max(1, clock.entries), 2),
                "clock divergences": clock.divergences,
                "log divergences": log.divergences,
                "sweep": SWEEP,
                "worst delay under the log": log.worst_delay,
            }
        )
    )
    print()
    print("agreement:", bar(1.0 if log.agreed else 0.0, 20), "under the log")
    print("agreement:", bar(1 - clock.divergences / max(1, clock.ticks), 20), "under the clock")


if __name__ == "__main__":
    main()
