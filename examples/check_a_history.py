"""Record what clients saw and ask whether any single ordering explains it.

Run with: python examples/check_a_history.py

A history is a list of calls and returns with the ticks they happened at. It is linearizable if
there is some order of the operations, consistent with the real time order of non overlapping
ones, that a single copy of the state machine could have produced. The checker searches for that
order, and the interesting part is that it can also come back with neither yes nor no.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.machine import COMPARE_AND_SET, SET, Command
from rsm.verify.history import History
from rsm.verify.linearize import LINEARIZABLE, UNKNOWN, check


def show(history: History) -> str:
    """A history as a table of calls, so the overlaps are visible."""
    return table(
        [
            {
                "client": one.client,
                "operation": str(one.command),
                "called": one.called_at,
                "returned": "pending" if one.returned_at is None else one.returned_at,
                "saw": "" if one.result is None else str(one.result),
            }
            for one in history.operations
        ]
    )


def _write(made: History, client: str, key: str, value: object) -> None:
    """One completed write."""
    made.complete(made.call(client, Command(name=SET, key=key, value=value)), value)


def _read(made: History, client: str, key: str, value: object, saw: bool = True) -> None:
    """One completed read, expressed as a compare and set that changes nothing.

    This machine has no get. A compare and set whose expected value equals the value it would
    write is a read: it returns whether the key currently holds that value and leaves the state
    exactly as it found it either way. That is a real operation rather than a special case in
    the checker, which is the point.
    """
    made.complete(
        made.call(client, Command(name=COMPARE_AND_SET, key=key, value=value, expected=value)),
        saw,
    )


def _overlapping_writes(made: History) -> None:
    """Two writes called before either returns, which is what makes the order a choice."""
    left = made.call("a", Command(name=SET, key="k", value=1))
    right = made.call("b", Command(name=SET, key="k", value=2))
    made.complete(left, 1)
    made.complete(right, 2)


def sequential() -> History:
    """Two writes and a read, none of them overlapping."""
    made = History()
    _write(made, "a", "k", 1)
    _write(made, "a", "k", 2)
    _read(made, "a", "k", 2)
    return made


def overlapping() -> History:
    """Two writes in flight at once, and a read that saw the first of them."""
    made = History()
    _overlapping_writes(made)
    _read(made, "c", "k", 1)
    return made


def impossible() -> History:
    """A read that returns a value nothing ever wrote."""
    made = History()
    _write(made, "a", "k", 1)
    _read(made, "b", "k", 9)
    return made


def stale() -> History:
    """A read that returns an old value after a newer write has already returned."""
    made = History()
    _write(made, "a", "k", 1)
    _write(made, "a", "k", 2)
    _read(made, "b", "k", 1)
    return made


def main() -> None:
    for name, builder in (
        ("sequential", sequential),
        ("overlapping writes", overlapping),
        ("a value nobody wrote", impossible),
        ("a stale read", stale),
    ):
        made = builder()
        verdict = check(made)
        print(rule(name))
        print(show(made))
        print()
        print(
            pairs(
                {
                    "verdict": verdict.answer,
                    "states explored": verdict.states,
                    "longest prefix placed": verdict.longest_prefix,
                    "operations": verdict.operations,
                    "failed at": str(verdict.failed_at) if verdict.failed_at else "none",
                }
            )
        )
        print()

    print(rule("the third answer"))
    print(f"a verdict is one of {LINEARIZABLE}, not linearizable, or {UNKNOWN}")
    print("the last one means the search ran out of budget, and it is falsy on purpose, so")
    print("that a caller writing if verdict does not read a budget exhaustion as a pass")


if __name__ == "__main__":
    main()
