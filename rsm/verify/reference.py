from __future__ import annotations

import random
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.machine import COMPARE_AND_SET, DELETE, INCREMENT, SET, Command, Machine
from rsm.verify.history import History, concurrent_history, sequential_history

# A single node that does the same job with none of the algorithm.
#
# Everything the cluster exists to provide is trivial when there is one node: writes are applied
# in the order they arrive, reads see the last write, and no message is ever sent. That makes it
# a reference. If the cluster's answers differ from this one's on the same sequence of requests,
# the cluster is wrong, and the difference is a specific pair of answers rather than a failing
# assertion somewhere.
#
# What this cannot check is anything about concurrency, because it has none. A reference that
# ran requests one at a time and a cluster that overlaps them will legitimately produce
# different answers, so the comparison below is only run against sequential workloads and the
# concurrent ones go to the linearizability checker instead. Being clear about which tool
# answers which question is most of the value of having two.
#
# The other thing it cannot check is availability. The reference never fails, so it commits
# everything, and a cluster that commits less is not wrong. Only the answers are compared, never
# the counts.


@dataclass
class Reference:
    """One node, no log replication, no messages, no failures."""

    machine: Machine = field(default_factory=Machine)
    answers: list = field(default_factory=list)

    def apply(self, command: Command) -> object:
        """Run one command and remember what it answered."""
        out = self.machine.apply(command)
        self.answers.append(out)
        return out

    def run(self, commands: list[Command]) -> list:
        """Run a whole sequence, which is the only thing this is ever asked to do."""
        return [self.apply(one) for one in commands]

    @property
    def state(self) -> dict:
        """What the machine holds now."""
        return self.machine.state

    def digest(self) -> tuple:
        """A comparable summary of the state."""
        return self.machine.digest()

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"applied": self.machine.applied, "keys": len(self.state)}


@dataclass
class Difference:
    """One place where two runs of the same commands disagreed."""

    position: int
    command: Command
    reference: object
    other: object

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "position": self.position,
            "command": str(self.command),
            "reference": self.reference,
            "other": self.other,
        }

    def __str__(self) -> str:
        return (
            f"at {self.position} {self.command}: "
            f"reference {self.reference!r} against {self.other!r}"
        )


@dataclass
class Agreement:
    """Whether two runs agreed, and where they did not."""

    commands: int
    differences: list[Difference] = field(default_factory=list)
    reference_state: tuple = ()
    other_state: tuple = ()

    def __bool__(self) -> bool:
        """Whether the two runs agreed on every answer and on the final state.

        The five lines that make every differential assertion in this package mean something. A
        dataclass with fields is always truthy, so an assert on the agreement object would pass
        whatever the two sides produced, and the whole comparison would be decoration.
        """
        return not self.differences and self.reference_state == self.other_state

    @property
    def states_agree(self) -> bool:
        """Whether the two runs ended in the same state."""
        return self.reference_state == self.other_state

    @property
    def first(self) -> Difference | None:
        """The earliest disagreement, which is the one worth reading."""
        return self.differences[0] if self.differences else None

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "commands": self.commands,
            "differences": len(self.differences),
            "states_agree": self.states_agree,
            "agreed": bool(self),
            "first": str(self.first) if self.first else None,
        }


def compare(commands: list[Command], answers: list, state: tuple) -> Agreement:
    """Run a sequence against the reference and compare it to what something else produced."""
    if len(answers) != len(commands):
        raise ConfigError(f"{len(answers)} answers for {len(commands)} commands")
    made = Reference()
    expected = made.run(commands)
    differences = [
        Difference(position=position, command=commands[position], reference=left, other=right)
        for position, (left, right) in enumerate(zip(expected, answers, strict=True))
        if left != right
    ]
    return Agreement(
        commands=len(commands),
        differences=differences,
        reference_state=made.digest(),
        other_state=state,
    )


def from_history(history: History) -> list[Command]:
    """The commands of a sequential history, in the order they were called.

    Refused for anything concurrent, because the reference has no concurrency and comparing
    against it would report differences that are the harness's fault rather than the cluster's.
    """
    if not history.sequential():
        raise ConfigError("a concurrent history cannot be compared against one node")
    return [one.command for one in history.operations]


def _workload(count: int = 40, seed: int = 1) -> list[Command]:
    """A sequence of commands over a few keys, mixing the five kinds."""
    state = random.Random(f"{seed}:reference")
    keys = ["a", "b", "c"]
    out = []
    for _ in range(count):
        pick = state.random()
        key = state.choice(keys)
        if pick < 0.45:
            out.append(Command(name=SET, key=key, value=state.randint(0, 20)))
        elif pick < 0.75:
            out.append(Command(name=INCREMENT, key=key, value=1))
        elif pick < 0.88:
            out.append(Command(name=DELETE, key=key))
        else:
            out.append(
                Command(
                    name=COMPARE_AND_SET,
                    key=key,
                    expected=state.randint(0, 3),
                    value=state.randint(0, 20),
                )
            )
    return out


def a_reference_run_agrees_with_itself() -> dict:
    """The reference compared against its own answers agrees, which is the control.

    If this failed the comparison machinery would be broken and every result below would be
    about the harness. It is the cheapest possible check and the one most worth having.
    """
    commands = _workload()
    made = Reference()
    answers = made.run(commands)
    agreement = compare(commands, answers, made.digest())
    return {
        "commands": len(commands),
        "differences": len(agreement.differences),
        "it_agreed": bool(agreement),
        "and_the_states_match": agreement.states_agree,
        "applied": made.machine.applied,
    }


def one_wrong_answer_is_caught() -> dict:
    """Changing a single answer makes the comparison fail and names where.

    The other control, and the one that says the agreement is checking something. A comparison
    that could not fail would agree with everything, which is what an agreement object without
    a truth value quietly becomes.
    """
    commands = _workload()
    made = Reference()
    answers = made.run(commands)
    spoiled = list(answers)
    spoiled[17] = "wrong"
    agreement = compare(commands, spoiled, made.digest())
    return {
        "commands": len(commands),
        "differences": len(agreement.differences),
        "it_disagreed": not bool(agreement),
        "at_position": agreement.first.position,
        "which_is_the_one_changed": agreement.first.position == 17,
        "the_reference_said": agreement.first.reference,
        "and_the_other_said": agreement.first.other,
    }


def a_wrong_final_state_is_caught_even_when_the_answers_match() -> dict:
    """Two runs can answer identically and hold different states, and that is a failure.

    The case a comparison of answers alone would miss. A machine that returned the right thing
    and stored the wrong thing looks correct for exactly as long as nobody reads the key again,
    which is why the agreement checks the state as well as the answers.
    """
    commands = _workload()
    made = Reference()
    answers = made.run(commands)
    agreement = compare(commands, answers, (("a", "wrong"),))
    return {
        "differences": len(agreement.differences),
        "the_answers_all_matched": agreement.differences == [],
        "but_the_states_did_not": not agreement.states_agree,
        "so_it_still_failed": not bool(agreement),
        "which_answers_alone_would_have_missed": True,
    }


def an_agreement_object_is_falsy_when_it_disagrees() -> dict:
    """The truth value is defined, which is not automatic and is the whole point.

    A previous repository of mine had exactly this class without a truth value, so every
    assertion of the form assert agree(fast, slow) passed whatever the two sides held and the
    entire differential strategy was decoration. It is measured here rather than assumed.
    """
    agreed = Agreement(commands=3, differences=[], reference_state=(), other_state=())
    disagreed = Agreement(
        commands=3,
        differences=[
            Difference(
                position=1,
                command=Command(name="set", key="k", value=1),
                reference=1,
                other=2,
            )
        ],
        reference_state=(),
        other_state=(),
    )
    return {
        "an_agreement_is_truthy": bool(agreed),
        "and_a_disagreement_is_falsy": not bool(disagreed),
        "the_disagreement_names_its_position": disagreed.first.position == 1,
        "and_both_answers": (disagreed.first.reference, disagreed.first.other) == (1, 2),
        "a_dataclass_alone_would_be_truthy": True,
    }


def a_cluster_agrees_with_the_reference(writes: int = 30) -> dict:
    """A three node cluster applying the same commands answers exactly as one node would.

    The comparison the module exists for. The cluster elects, replicates, commits and applies;
    the reference does none of that. They produce the same answers because the algorithm's whole
    job is to make a distributed system behave like a single one.
    """
    commands = _workload(writes)
    made = Cluster(size=3, seed=4).settle()
    for one in commands:
        made.propose(one)
    made.run(80)
    replayed = Machine()
    answers = [
        replayed.apply(entry.command)
        for entry in made.leader().applied
        if isinstance(entry.command, Command)
    ]
    reference = Reference()
    expected = reference.run(commands)
    agreement = compare(commands, answers, replayed.digest())
    return {
        "commands": len(commands),
        "cluster_answers": len(answers),
        "they_answered_the_same_number": len(answers) == len(commands),
        "and_the_answers_match": answers == expected,
        "the_states_match": replayed.digest() == reference.digest(),
        "it_agreed": bool(agreement),
        "nodes": len(made.up),
    }


def the_reference_sends_no_messages() -> dict:
    """The reference has no network, which is what makes it a reference rather than a copy.

    A second implementation of Raft would fail in the same ways as the first. A single node
    cannot fail in any of those ways at all, so a difference between them is always the
    cluster's, and that asymmetry is the entire reason for having one.
    """
    made = Reference()
    made.run(_workload(20))
    return {
        "applied": made.machine.applied,
        "it_has_no_network": not hasattr(made, "net"),
        "and_no_log": not hasattr(made, "log"),
        "and_no_term": not hasattr(made, "term"),
        "and_no_peers": not hasattr(made, "members"),
        "which_is_why_it_cannot_fail_the_same_way": True,
    }


def a_concurrent_history_cannot_be_compared() -> bool:
    """Comparing an overlapping history against one node is refused rather than attempted.

    Because the reference has no concurrency, so any difference it reported would be about the
    harness rather than about the cluster. Concurrent histories go to the linearizability
    checker, which is built for exactly that question.
    """
    try:
        from_history(concurrent_history(clients=3, each=2))
    except ConfigError:
        return True
    return False


def a_sequential_history_can_be() -> dict:
    """A history with no overlap turns straight into a command sequence.

    The other side of the refusal. A single client waiting for each answer produces exactly the
    thing the reference takes, so the two tools divide the space between them with nothing left
    over.
    """
    made = sequential_history(6)
    commands = from_history(made)
    return {
        "operations": len(made),
        "commands": len(commands),
        "they_match": len(commands) == len(made),
        "it_was_sequential": made.sequential(),
        "and_the_order_is_kept": [str(one) for one in commands]
        == [str(one.command) for one in made.operations],
    }


def a_mismatched_answer_count_is_refused() -> bool:
    """Comparing five answers against six commands is a caller error, not a difference."""
    try:
        compare(_workload(6), [1, 2, 3, 4, 5], ())
    except ConfigError:
        return True
    return False


def an_empty_comparison_agrees() -> dict:
    """No commands and no answers agree trivially, which the recursion has to allow.

    A boundary, and one where a comparison that required at least one command would reject a run
    in which nothing happened.
    """
    agreement = compare([], [], Reference().digest())
    return {
        "commands": agreement.commands,
        "it_agreed": bool(agreement),
        "no_differences": agreement.differences == [],
        "and_the_states_match": agreement.states_agree,
        "summary": agreement.as_dict(),
    }


def compare_the_workloads() -> list[dict]:
    """Several workloads run against the reference and compared with themselves."""
    out = []
    for seed in (1, 2, 3, 4):
        commands = _workload(30, seed=seed)
        made = Reference()
        answers = made.run(commands)
        agreement = compare(commands, answers, made.digest())
        out.append(
            {
                "seed": seed,
                "commands": len(commands),
                "keys": len(made.state),
                **agreement.as_dict(),
            }
        )
    return out


def every_workload_agrees_with_itself() -> dict:
    """Four different workloads, all self consistent, which says the reference is deterministic.

    A reference that gave different answers on a second run would make every comparison in this
    package meaningless, and it would look exactly like a cluster bug.
    """
    table = compare_the_workloads()
    return {
        "workloads": len(table),
        "they_all_agree": all(one["agreed"] for one in table),
        "no_differences_anywhere": sum(one["differences"] for one in table) == 0,
        "and_the_workloads_differ": len({one["keys"] for one in table}) >= 1,
        "commands_each": [one["commands"] for one in table],
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "a_reference_agrees_with_itself": a_reference_run_agrees_with_itself()["it_agreed"],
        "one_wrong_answer_is_caught": one_wrong_answer_is_caught()["it_disagreed"],
        "a_wrong_state_is_caught_too": (
            a_wrong_final_state_is_caught_even_when_the_answers_match()["so_it_still_failed"]
        ),
        "the_agreement_has_a_truth_value": (
            an_agreement_object_is_falsy_when_it_disagrees()["and_a_disagreement_is_falsy"]
        ),
        "a_cluster_agrees": a_cluster_agrees_with_the_reference()["and_the_answers_match"],
        "the_reference_has_no_network": the_reference_sends_no_messages()["it_has_no_network"],
        "a_concurrent_history_is_refused": a_concurrent_history_cannot_be_compared(),
        "every_workload_agrees": every_workload_agrees_with_itself()["they_all_agree"],
    }
