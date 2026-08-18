from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.machine import SET, Command
from rsm.verify.reference import Reference

# Checking the cluster against the model at every step, not only at the end.
#
# rsm.verify.reference compares a cluster with one copy of the state machine by running the
# same commands through both and comparing the answers and the final state. That catches a
# great deal and it is end to end: the two are compared once, after everything has happened.
#
# A refinement check is the same comparison made continuously. After every applied entry, the
# cluster's state has to equal the model's after the same number of commands, and if it ever
# does not the check says which command it was. Worth having for the reason a stack trace beats
# an exit code: both say something failed and one of them says where.
#
# The mapping is what makes it a refinement rather than an equality. The cluster's state is a
# dictionary on the leader plus a log plus a commit index plus a term; the model's is a
# dictionary. The mapping throws away everything the model does not have and compares what is
# left, and choosing what to throw away is the whole content of a refinement proof. Here it is
# small enough to write in one function and is written in one function on purpose.

# How many commands a refinement run uses.
COMMANDS = 40

# How often a run checks, in applied entries.
EVERY = 1


@dataclass(frozen=True)
class Step:
    """One point of comparison: the model's state and the cluster's, after the same commands."""

    at: int
    command: str
    model: tuple
    cluster: tuple

    @property
    def agrees(self) -> bool:
        """Whether the mapping made the two equal."""
        return self.model == self.cluster

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "at": self.at,
            "command": self.command,
            "agrees": self.agrees,
            "model": len(self.model),
            "cluster": len(self.cluster),
        }

    def __str__(self) -> str:
        if self.agrees:
            return f"{self.at}: {self.command} agreed"
        return f"{self.at}: {self.command} left {self.cluster} against {self.model}"


@dataclass
class Refinement:
    """Every step of one comparison, and where it first went wrong."""

    steps: list[Step] = field(default_factory=list)
    commands: int = 0

    @property
    def first_break(self) -> Step | None:
        """The earliest step where the mapping failed, which is the useful part."""
        return next((one for one in self.steps if not one.agrees), None)

    @property
    def breaks(self) -> list[Step]:
        """Every step that failed."""
        return [one for one in self.steps if not one.agrees]

    def __bool__(self) -> bool:
        """A refinement holds if every step agreed."""
        return bool(self.steps) and not self.breaks

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "commands": self.commands,
            "steps": len(self.steps),
            "breaks": len(self.breaks),
            "first_break": str(self.first_break) if self.first_break else "",
            "holds": bool(self),
        }


def mapping(state: dict) -> tuple:
    """The part of a state the model also has, in a form two states can be compared on.

    Sorted rather than a dictionary, because two dictionaries with the same pairs in a different
    insertion order are equal in Python and not equal when printed, and a check whose failures
    are unreadable is a check nobody uses.
    """
    return tuple(sorted((str(key), repr(value)) for key, value in state.items()))


def _commands(count: int = COMMANDS, keys: int = 5) -> list[Command]:
    """A sequence of writes that touch a few keys repeatedly."""
    return [Command(name=SET, key=f"k{one % keys}", value=one) for one in range(count)]


def check(commands: list[Command] | None = None, size: int = 3, seed: int = 1) -> Refinement:
    """Run the same commands through a cluster and a model, comparing after each one.

    The cluster's state is read from whichever node is leading, because that is the node a
    client would ask, and the mapping is applied to both sides before they are compared. A check
    that compared the raw states would fail on the log, the term and the commit index, none of
    which the model has or should have.

    An empty list of commands is refused rather than replaced with the default. Writing it as
    commands or the default treats an empty list as an absent one, so a caller asking to check
    nothing silently got forty commands instead.
    """
    made = _commands() if commands is None else commands
    if not made:
        raise ConfigError("a refinement check needs commands")
    cluster = Cluster(size=size, seed=seed).settle()
    model = Reference()
    out = Refinement(commands=len(made))
    for index, one in enumerate(made, start=1):
        model.apply(one)
        with contextlib.suppress(NoLeader):
            cluster.propose((one.name, one.key, one.value))
        cluster.run(4)
        if index % EVERY:
            continue
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


def the_cluster_refines_the_model_at_every_step() -> dict:
    """Forty commands, forty comparisons, and the two states agree at every one.

    The base case, and it is a stronger statement than the end to end check it extends. Agreeing
    at the end is compatible with disagreeing in the middle and coming back; agreeing at every
    step is not.
    """
    made = check()
    return {
        "commands": made.commands,
        "steps": len(made.steps),
        "it_holds": bool(made),
        "breaks": len(made.breaks),
        "first_break": str(made.first_break) if made.first_break else "none",
        "and_the_states_are_not_empty": bool(made.steps[-1].model),
        "keys_at_the_end": len(made.steps[-1].model),
    }


def a_step_check_says_which_command_broke_it() -> dict:
    """Feeding the model a command the cluster never got breaks at exactly that step.

    What the continuous check buys. The two runs are made to diverge at a known point by
    slipping an extra command into the model, and the first break is that command rather than
    the end of the run.

    An end to end comparison would have reported that the final states differ, which is true and
    says nothing about which of forty commands did it.
    """
    commands = _commands(count=12)
    cluster = Cluster(size=3, seed=1).settle()
    model = Reference()
    out = Refinement(commands=len(commands))
    slipped = 5
    for index, one in enumerate(commands, start=1):
        model.apply(one)
        if index == slipped:
            model.apply(Command(name=SET, key="ghost", value=1))
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
    return {
        "commands": len(commands),
        "slipped_at": slipped,
        "it_broke": not bool(out),
        "first_break_at": out.first_break.at if out.first_break else 0,
        "and_it_is_the_slipped_command": (
            out.first_break.at == slipped if out.first_break else False
        ),
        "breaks": len(out.breaks),
        "and_everything_after_it_broke_too": len(out.breaks) == len(commands) - slipped + 1,
        "an_end_to_end_check_would_say": "the final states differ",
    }


def the_mapping_is_what_makes_the_comparison_possible() -> dict:
    """The raw states differ at every step; the mapped ones agree at every step.

    What a refinement mapping is for, shown by removing it. The cluster's node holds a log, a
    term, a commit index, an applied index and two index maps per peer. The model holds a
    dictionary. Comparing them directly fails immediately and says nothing, because they were
    never meant to be equal.

    Choosing what to throw away is the whole content of a refinement argument, and getting it
    wrong in the generous direction is the danger: a mapping that discarded the state itself
    would agree with everything.
    """
    cluster = Cluster(size=3, seed=1).settle()
    model = Reference()
    for one in _commands(count=8):
        model.apply(one)
        with contextlib.suppress(NoLeader):
            cluster.propose((one.name, one.key, one.value))
        cluster.run(4)
    found = cluster.leader()
    raw_cluster = {
        "state": found.state,
        "term": found.term,
        "commit_index": found.commit_index,
        "log": len(found.log),
    }
    return {
        "model_fields": sorted(vars(model.machine)),
        "cluster_fields": sorted(raw_cluster),
        "they_are_different_shapes": set(raw_cluster) != set(vars(model.machine)),
        "raw_states_are_equal": raw_cluster == vars(model.machine),
        "mapped_states_are_equal": mapping(found.state) == mapping(model.state),
        "the_mapping_keeps": len(mapping(found.state)),
        "and_discards": len(raw_cluster) - 1,
        "a_generous_mapping_would_agree_with_anything": mapping({}) == mapping({}),
    }


def refinement_is_stronger_than_agreeing_at_the_end() -> dict:
    """A run that diverges and comes back passes the end to end check and fails this one.

    The case that separates the two. The model is given an extra command and then given a
    command that undoes it, so the final states match exactly and the middle does not.

    An end to end comparison passes that run without comment. The step check reports the two
    steps where the states differed and the exact command each time, which is the difference
    between knowing the answer was right and knowing the run was.
    """
    commands = _commands(count=10)
    cluster = Cluster(size=3, seed=1).settle()
    model = Reference()
    out = Refinement(commands=len(commands))
    for index, one in enumerate(commands, start=1):
        model.apply(one)
        if index == 4:
            model.apply(Command(name=SET, key="ghost", value=1))
        if index == 6:
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
    return {
        "commands": len(commands),
        "the_ends_agree": out.steps[-1].agrees,
        "so_an_end_to_end_check_passes": out.steps[-1].agrees,
        "the_step_check_fails": not bool(out),
        "breaks": len(out.breaks),
        "and_it_is_the_middle": [one.at for one in out.breaks] == [4, 5],
        "first_break_at": out.first_break.at if out.first_break else 0,
        "so_refinement_is_the_stronger_claim": True,
    }


def a_check_with_no_commands_is_refused() -> bool:
    """A refinement over nothing holds trivially and is refused rather than reported."""
    try:
        check(commands=[])
    except ConfigError:
        return True
    return False


def an_empty_refinement_is_falsy() -> dict:
    """A refinement with no steps is not a refinement that held.

    The distinction the truthiness has to get right. Nothing checked is not the same as
    everything passed, and a check that reported an empty run as a success would pass every run
    it failed to perform.
    """
    empty = Refinement()
    one_step = Refinement(steps=[Step(at=1, command="x", model=(), cluster=())], commands=1)
    return {
        "empty_is_falsy": not bool(empty),
        "and_a_single_agreeing_step_is_truthy": bool(one_step),
        "empty_breaks": len(empty.breaks),
        "which_is_none": not empty.breaks,
        "and_it_is_still_falsy": not bool(empty),
        "first_break_of_an_empty_one": empty.first_break,
    }


def compare_the_sizes() -> list[dict]:
    """The refinement over several cluster sizes."""
    return [{"size": size, **check(size=size).as_dict()} for size in (1, 3, 5)]


def every_size_refines_the_same_model() -> dict:
    """One node, three and five all track the same single copy of the state machine.

    The point of the exercise. The model has no notion of a cluster, a leader or a log, and the
    cluster's size changes everything about how it reaches a state and nothing about which state
    it reaches. That is the claim consensus makes, checked at every step rather than at the end.
    """
    table = compare_the_sizes()
    return {
        "sizes": [one["size"] for one in table],
        "every_size_holds": all(one["holds"] for one in table),
        "steps": {one["size"]: one["steps"] for one in table},
        "and_they_all_took_the_same_steps": len({one["steps"] for one in table}) == 1,
        "breaks": {one["size"]: one["breaks"] for one in table},
        "none_of_them_broke": all(one["breaks"] == 0 for one in table),
        "the_model_has_no_size": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "commands": COMMANDS,
        "the_cluster_refines_the_model": the_cluster_refines_the_model_at_every_step()[
            "it_holds"
        ],
        "a_break_names_its_command": a_step_check_says_which_command_broke_it()[
            "and_it_is_the_slipped_command"
        ],
        "the_mapping_is_needed": the_mapping_is_what_makes_the_comparison_possible()[
            "they_are_different_shapes"
        ],
        "refinement_is_stronger": refinement_is_stronger_than_agreeing_at_the_end()[
            "the_step_check_fails"
        ],
        "and_the_end_to_end_check_passes_that_run": (
            refinement_is_stronger_than_agreeing_at_the_end()["so_an_end_to_end_check_passes"]
        ),
        "every_size_refines_it": every_size_refines_the_same_model()["every_size_holds"],
    }
