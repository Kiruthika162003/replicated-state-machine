"""Compare a cluster with one copy of the state machine after every single command.

Run with: python examples/refine_step_by_step.py

An end to end comparison says the two agreed at the finish. A refinement check says they agreed
at every step, which is a stronger claim, and when it fails it says which command did it rather
than that something did.
"""

from __future__ import annotations

import contextlib

from examples.common import pairs, rule, table
from rsm.cluster import Cluster
from rsm.errors import NoLeader
from rsm.machine import SET, Command
from rsm.verify.reference import Reference
from rsm.verify.refine import Refinement, Step, check, mapping

COMMANDS = 12


def diverging(slip_at: int, undo_at: int = 0) -> Refinement:
    """A run where the model is given a command the cluster never gets."""
    commands = [Command(name=SET, key=f"k{one % 3}", value=one) for one in range(COMMANDS)]
    cluster = Cluster(size=3, seed=1).settle()
    model = Reference()
    out = Refinement(commands=len(commands))
    for index, one in enumerate(commands, start=1):
        model.apply(one)
        if index == slip_at:
            model.apply(Command(name=SET, key="ghost", value=1))
        if undo_at and index == undo_at:
            model.apply(Command(name="delete", key="ghost"))
        with contextlib.suppress(NoLeader):
            cluster.propose((one.name, one.key, one.value))
        cluster.run(4)
        found = cluster.leader()
        out.steps.append(
            Step(
                at=index,
                command=str(one),
                model=mapping(model.state),
                cluster=mapping(found.state if found else {}),
            )
        )
    return out


def step_rows(made: Refinement, keep: int = 12) -> list[dict]:
    """The steps, as a table."""
    return [
        {
            "at": one.at,
            "command": one.command,
            "model keys": len(one.model),
            "cluster keys": len(one.cluster),
            "agrees": "yes" if one.agrees else "no",
        }
        for one in made.steps[:keep]
    ]


def main() -> None:
    clean = check(
        commands=[Command(name=SET, key=f"k{one % 3}", value=one) for one in range(8)]
    )
    print(rule("a run that refines the model"))
    print(table(step_rows(clean)))
    print()
    print(pairs(clean.as_dict()))
    print()

    broken = diverging(slip_at=5)
    print(rule("a run that stops refining it at step five"))
    print(table(step_rows(broken)))
    print()
    print(pairs(broken.as_dict()))
    print()
    print("an end to end check would say the final states differ, which is true and says")
    print("nothing about which of twelve commands did it")
    print()

    returning = diverging(slip_at=4, undo_at=6)
    print(rule("a run that diverges and comes back"))
    print(table(step_rows(returning)))
    print()
    print(
        pairs(
            {
                "the ends agree": returning.steps[-1].agrees,
                "so an end to end check passes": returning.steps[-1].agrees,
                "the step check holds": bool(returning),
                "steps that broke": len(returning.breaks),
                "first break": str(returning.first_break) if returning.first_break else "none",
            }
        )
    )
    print()
    print("this is the run that separates the two checks: the answer at the end was right and")
    print("the run was not")


if __name__ == "__main__":
    main()
