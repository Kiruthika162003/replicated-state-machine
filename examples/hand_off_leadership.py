"""Hand leadership to a named node on purpose, and see it cost a round trip, not a timeout.

Run with: python examples/hand_off_leadership.py

A leader that simply stops costs the cluster a full election timeout before anybody notices
and stands. A leader that transfers first brings the target fully up to date and then tells
it to stand immediately, which costs one round trip instead. The six seed sweep at the end is
the same comparison run enough times that the gap is a property of the two mechanisms rather
than of one lucky draw.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.cluster import Cluster
from rsm.transfer import a_transfer_beats_a_crash_on_every_seed, compare_the_paths, hand_over

SIZE = 5
SEED = 9
WRITES = 6


def _settled(seed: int) -> Cluster:
    """A cluster that has elected and written, which is where a transfer starts."""
    made = Cluster(size=SIZE, seed=seed).settle()
    for one in range(WRITES):
        made.propose(("set", "k", one))
    made.run(30)
    return made


def main() -> None:
    made = _settled(SEED)
    outgoing = made.leader().name
    target = next(one for one in made.up if one != outgoing)

    print(rule("before the transfer"))
    print(pairs({"leader": outgoing, "target": target, "committed": len(made.committed())}))
    print()

    result = hand_over(made, target)
    print(rule("the transfer"))
    print(pairs(result.as_dict()))
    print()

    found = made.leader()
    print(rule("after the transfer"))
    print(
        pairs(
            {
                "leader": found.name if found else "nobody",
                "it is the named target": bool(found) and found.name == target,
                "committed": len(made.committed()),
            }
        )
    )
    print()

    print(rule("six seeds, transfer against an unplanned crash"))
    print(table(compare_the_paths()))
    print()

    beats = a_transfer_beats_a_crash_on_every_seed()
    print(
        pairs(
            {
                "the transfer wins every seed": beats["the_transfer_wins_every_time"],
                "smallest gap in ticks": beats["smallest_gap"],
                "largest gap in ticks": beats["largest_gap"],
            }
        )
    )
    print()
    print("a crash pays for a full election timeout before anybody notices and stands; a")
    print("transfer pays for one round trip, because the outgoing leader chose the moment")
    print("and named its own successor instead of leaving that to whoever times out first")

    if found is None or found.name != target or not bool(result):
        raise SystemExit("expected the named target to end up leading")
    if not beats["the_transfer_wins_every_time"]:
        raise SystemExit("expected a transfer to beat a crash on every seed")


if __name__ == "__main__":
    main()
