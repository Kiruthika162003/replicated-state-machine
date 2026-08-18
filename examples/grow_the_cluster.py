"""Add and remove members, and show why two changes at once are not two safe changes.

Run with: python examples/grow_the_cluster.py

A membership change is a log entry like any other, which means there is a window where some
nodes have applied it and others have not. The single server rule says that window is safe as
long as the old majority and the new majority must overlap. Two changes at once break it, and
the break is easy to see once the majorities are written out.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.membership import Configuration, disjoint_majorities
from rsm.quorum import majority

STEPS = (
    ("n0", "n1", "n2"),
    ("n0", "n1", "n2", "n3"),
    ("n0", "n1", "n2", "n3", "n4"),
)


def step_row(old: tuple[str, ...], new: tuple[str, ...]) -> dict:
    """One proposed change and whether the two majorities have to overlap."""
    found = disjoint_majorities(old, new)
    return {
        "from": " ".join(old),
        "to": " ".join(new),
        "old majority": majority(len(old)),
        "new majority": majority(len(new)),
        "added": len(set(new) - set(old)),
        "removed": len(set(old) - set(new)),
        "safe": "yes" if not found else "no",
        "counterexample": ""
        if not found
        else f"{sorted(found[0][0])} and {sorted(found[0][1])}",
    }


def main() -> None:
    print(rule("growing one node at a time"))
    print(table([step_row(STEPS[one], STEPS[one + 1]) for one in range(len(STEPS) - 1)]))
    print()

    print(rule("growing two at once"))
    print(table([step_row(("n0", "n1", "n2"), ("n0", "n1", "n2", "n3", "n4"))]))
    print()
    print("three nodes need two to agree and five need three, and there are two nodes in")
    print("the new set that the old set never heard of, so a majority of each can be found")
    print("that share nothing at all")
    print()

    print(rule("the configurations"))
    rows = []
    for members in STEPS:
        rows.append(
            {
                "members": " ".join(members),
                "size": len(members),
                "quorum": majority(len(members)),
                "tolerates": len(members) - majority(len(members)),
                "stage": Configuration(members=members).stage,
            }
        )
    print(table(rows))
    print()

    print(rule("what a joint configuration is for"))
    old = ("n0", "n1", "n2")
    new = ("n0", "n1", "n2", "n3", "n4")
    joint = Configuration(members=new, old=old)
    left = set(old[: majority(len(old))])
    right = set(new[len(new) - majority(len(new)) :])
    print(
        pairs(
            {
                "old": " ".join(old),
                "new": " ".join(new),
                "stage": joint.stage,
                "voters": len(joint.voters),
                "from the old set": majority(len(old)),
                "from the new set": majority(len(new)),
                "an old majority alone": f"{sorted(left)} decides: {joint.quorum(left)}",
                "a new majority alone": f"{sorted(right)} decides: {joint.quorum(right)}",
                "both together": joint.quorum(left | right),
            }
        )
    )
    print()
    print("requiring a majority of both sets at once removes the overlap problem by")
    print("construction, at the cost of a change that takes two rounds instead of one")


if __name__ == "__main__":
    main()
