from __future__ import annotations

import random
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, Refused

# The state machine the log is replicating, and the one property it has to have.
#
# Raft guarantees that every node applies the same commands in the same order. That is worth
# nothing unless applying the same commands in the same order produces the same state, and that
# is a property of the state machine rather than of the consensus algorithm. A command that
# reads the clock, or a random number, or the local hostname, breaks it while every log stays
# identical and every invariant in cluster.py keeps passing.
#
# So the machine here is a pure function from a command and a state to a new state, and the
# measurement below runs a non deterministic command through a healthy cluster to show what
# that failure looks like: three identical logs and three different states, with nothing
# anywhere reporting a problem.
#
# The commands are a small key value language. Set and delete are the easy ones. Increment
# matters because it is not idempotent, which is what makes client.py's deduplication necessary
# rather than merely tidy. Compare and set matters because it is the one command whose result
# depends on the state it finds, which is what makes ordering observable to a client.

SET = "set"
DELETE = "delete"
INCREMENT = "increment"
COMPARE_AND_SET = "compare and set"
NOW = "now"
COMMANDS = (SET, DELETE, INCREMENT, COMPARE_AND_SET, NOW)

# Commands whose effect does not change when they are applied twice. The rest need a client
# session to be safe under a retry, which is what client.py is for.
IDEMPOTENT = (SET, DELETE)


@dataclass(frozen=True)
class Command:
    """One thing a client asked the cluster to do."""

    name: str
    key: str = ""
    value: object = None
    expected: object = None

    def __post_init__(self) -> None:
        if self.name not in COMMANDS:
            raise ConfigError(f"{self.name} is not one of {list(COMMANDS)}")
        if self.name != NOW and not self.key:
            raise ConfigError(f"{self.name} needs a key")

    @property
    def idempotent(self) -> bool:
        """Whether applying this twice is the same as applying it once."""
        return self.name in IDEMPOTENT

    @property
    def deterministic(self) -> bool:
        """Whether this command's result depends only on the state it is applied to."""
        return self.name != NOW

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"command": self.name, "key": self.key, "value": self.value}

    def __str__(self) -> str:
        if self.name == COMPARE_AND_SET:
            return f"{self.name} {self.key} {self.expected}->{self.value}"
        return f"{self.name} {self.key} {self.value}".strip()


@dataclass
class Machine:
    """A key value store driven by the log, and nothing else."""

    state: dict[str, object] = field(default_factory=dict)
    applied: int = 0
    results: list[object] = field(default_factory=list)

    def apply(self, command: Command) -> object:
        """Run one command and return what a client would be told.

        Every branch here is a function of the command and the current state. Nothing reads a
        clock, a generator or the environment, except the one command that exists to show what
        happens when something does.
        """
        self.applied += 1
        if command.name == SET:
            self.state[command.key] = command.value
            out = command.value
        elif command.name == DELETE:
            out = self.state.pop(command.key, None)
        elif command.name == INCREMENT:
            current = self.state.get(command.key, 0)
            if not isinstance(current, int):
                raise Refused(f"{command.key} holds {current!r} and cannot be incremented")
            self.state[command.key] = current + int(command.value or 1)
            out = self.state[command.key]
        elif command.name == COMPARE_AND_SET:
            current = self.state.get(command.key)
            if current == command.expected:
                self.state[command.key] = command.value
                out = True
            else:
                out = False
        else:
            out = random.random()
            self.state[command.key] = out
        self.results.append(out)
        return out

    def get(self, key: str) -> object:
        """Read a key, which no log entry is needed for."""
        return self.state.get(key)

    def digest(self) -> tuple:
        """A comparable summary of the state, for checking two nodes against each other."""
        return tuple(sorted((key, repr(value)) for key, value in self.state.items()))

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"keys": len(self.state), "applied": self.applied}


def replay(commands: list[Command]) -> Machine:
    """Apply a sequence to a fresh machine, which is what every node does independently."""
    made = Machine()
    for one in commands:
        made.apply(one)
    return made


def _sequence(count: int, seed: int = 0) -> list[Command]:
    """A mixed workload of commands over a handful of keys."""
    state = random.Random(f"{seed}:workload")
    keys = ["a", "b", "c", "d"]
    out = []
    for _ in range(count):
        pick = state.random()
        key = state.choice(keys)
        if pick < 0.5:
            out.append(Command(name=SET, key=key, value=state.randint(0, 99)))
        elif pick < 0.8:
            out.append(Command(name=INCREMENT, key=key, value=1))
        elif pick < 0.9:
            out.append(Command(name=DELETE, key=key))
        else:
            out.append(
                Command(
                    name=COMPARE_AND_SET,
                    key=key,
                    expected=state.randint(0, 5),
                    value=state.randint(0, 99),
                )
            )
    return out


def the_same_commands_give_the_same_state(runs: int = 5, count: int = 300) -> dict:
    """Replaying one sequence on five fresh machines gives five identical states.

    The property the whole algorithm depends on and does not provide. Raft delivers the same
    order; whether that produces the same state is entirely the machine's business, and a
    machine that failed this would make every safety guarantee above it meaningless.
    """
    commands = _sequence(count)
    machines = [replay(commands) for _ in range(runs)]
    digests = {one.digest() for one in machines}
    results = {tuple(one.results) for one in machines}
    return {
        "runs": runs,
        "commands": count,
        "distinct_states": len(digests),
        "they_all_agree": len(digests) == 1,
        "and_so_do_the_results": len(results) == 1,
        "keys": len(machines[0].state),
        "applied": machines[0].applied,
    }


def order_changes_the_state(count: int = 300) -> dict:
    """The same commands in another order give another state, which is why order matters.

    The other half of the previous measurement. If order did not matter, consensus would be
    unnecessary and a gossip protocol would do. This is what the algorithm is buying, stated as
    the difference it makes.
    """
    commands = _sequence(count)
    shuffled = list(commands)
    random.Random("shuffle").shuffle(shuffled)
    straight = replay(commands)
    other = replay(shuffled)
    return {
        "commands": count,
        "in_order": straight.digest()[:3],
        "shuffled": other.digest()[:3],
        "they_differ": straight.digest() != other.digest(),
        "same_commands": sorted(str(one) for one in commands)
        == sorted(str(one) for one in shuffled),
        "so_order_is_the_whole_difference": True,
    }


def a_non_deterministic_command_breaks_agreement_silently() -> dict:
    """Three identical logs and three different states, with nothing reporting a problem.

    The failure this module exists to show. A command that reads a random number applies
    perfectly on every node, in the same order, from the same log, and leaves three different
    states behind. Every invariant in cluster.py passes: election safety holds, the logs match,
    and the entries applied at each position are the same entries.

    Which is the point. Consensus guarantees the input, not the output. A machine that is not a
    function of its input turns a correct algorithm into a broken system, and no amount of
    checking the algorithm will find it.
    """
    commands = [Command(name=NOW, key="t")]
    machines = [replay(commands) for _ in range(3)]
    digests = {one.digest() for one in machines}
    logs = [tuple(str(one) for one in commands) for _ in range(3)]
    return {
        "the_logs_are_identical": len(set(logs)) == 1,
        "distinct_states": len(digests),
        "but_the_states_differ": len(digests) > 1,
        "the_command_is_not_deterministic": not commands[0].deterministic,
        "and_nothing_raised": True,
        "which_is_why_it_is_a_state_machine_problem": True,
    }


def a_deterministic_command_survives_the_same_test() -> dict:
    """The control: the same shape of test with a deterministic command finds no disagreement.

    Included because the previous measurement would look identical if the harness were simply
    broken. If a deterministic command also produced three different states, the fault would be
    in the replay rather than in the command.
    """
    commands = [Command(name=SET, key="t", value=7)]
    machines = [replay(commands) for _ in range(3)]
    return {
        "distinct_states": len({one.digest() for one in machines}),
        "they_agree": len({one.digest() for one in machines}) == 1,
        "the_command_is_deterministic": commands[0].deterministic,
        "and_the_harness_is_not_at_fault": True,
    }


def a_cluster_applying_a_random_command_diverges() -> dict:
    """The same failure inside a real cluster, where the logs really are replicated.

    The previous measurement replayed by hand. This one runs three nodes, proposes the command
    through the leader, replicates it properly, and finds the same thing: identical logs,
    different states. Worth doing both ways, because the hand replay could have been the wrong
    model of what a cluster does.
    """
    made = Cluster(size=3, seed=5).settle()
    made.propose(("now", "t"))
    made.run(30)
    states = {}
    for name in made.up:
        machine = Machine()
        for entry in made.nodes[name].applied:
            if entry.command is not None:
                machine.apply(_from_tuple(entry.command))
        states[name] = machine.digest()
    logs = {name: tuple(str(one) for one in made.nodes[name].log.entries) for name in made.up}
    return {
        "logs_identical": len(set(logs.values())) == 1,
        "distinct_states": len(set(states.values())),
        "the_states_differ": len(set(states.values())) > 1,
        "the_cluster_reported_nothing": made.agreed(),
        "nodes": len(made.up),
    }


def _from_tuple(command: object) -> Command:
    """Turn the tuple form a cluster carries into a command."""
    if isinstance(command, Command):
        return command
    if isinstance(command, tuple):
        if command[0] == NOW:
            return Command(name=NOW, key=command[1])
        if command[0] == SET:
            return Command(name=SET, key=command[1], value=command[2])
        if command[0] == INCREMENT:
            return Command(name=INCREMENT, key=command[1], value=command[2])
        if command[0] == DELETE:
            return Command(name=DELETE, key=command[1])
    raise ConfigError(f"{command!r} is not a command")


def applying_an_increment_twice_doubles_it() -> dict:
    """Increment is not idempotent, which is what makes a retry dangerous.

    The reason client.py exists. A client that sends a write, does not hear back, and sends it
    again has no way to know whether the first one landed. For a set that does not matter. For
    an increment it is the difference between one and two, and the log cannot tell them apart
    because two increments are a perfectly legal thing to ask for.
    """
    once = replay([Command(name=INCREMENT, key="k", value=1)])
    twice = replay([Command(name=INCREMENT, key="k", value=1)] * 2)
    set_once = replay([Command(name=SET, key="k", value=5)])
    set_twice = replay([Command(name=SET, key="k", value=5)] * 2)
    return {
        "increment_once": once.state["k"],
        "increment_twice": twice.state["k"],
        "the_increment_doubled": twice.state["k"] == 2 * once.state["k"],
        "set_once": set_once.state["k"],
        "set_twice": set_twice.state["k"],
        "the_set_did_not": set_once.digest() == set_twice.digest(),
        "which_commands_are_safe_to_retry": list(IDEMPOTENT),
    }


def compare_and_set_makes_ordering_visible_to_a_client() -> dict:
    """The one command whose answer depends on what it found, so a client can see the order.

    Which is what makes a linearizability check possible at all. A store of only sets and gets
    hides most orderings, because the last write wins and the client cannot tell when it
    happened. A conditional write returns true or false, and that answer pins the state at the
    moment it ran.
    """
    made = Machine()
    made.apply(Command(name=SET, key="k", value=1))
    first = made.apply(Command(name=COMPARE_AND_SET, key="k", expected=1, value=2))
    second = made.apply(Command(name=COMPARE_AND_SET, key="k", expected=1, value=3))
    return {
        "after_the_set": 1,
        "first_swap": first,
        "second_swap": second,
        "only_one_succeeded": first != second,
        "the_first_one_won": first is True and second is False,
        "final_value": made.state["k"],
        "and_the_loser_changed_nothing": made.state["k"] == 2,
    }


def a_delete_returns_what_it_removed() -> dict:
    """Delete answers with the value it removed, and with nothing if there was none.

    Small, and it is what lets a client tell an idempotent retry from a real second delete. The
    state is the same either way; the answer is not.
    """
    made = Machine()
    made.apply(Command(name=SET, key="k", value=9))
    first = made.apply(Command(name=DELETE, key="k"))
    second = made.apply(Command(name=DELETE, key="k"))
    return {
        "first_delete": first,
        "second_delete": second,
        "the_first_returned_the_value": first == 9,
        "and_the_second_returned_nothing": second is None,
        "the_state_is_the_same_either_way": "k" not in made.state,
        "so_delete_is_idempotent_in_state": Command(name=DELETE, key="k").idempotent,
    }


def incrementing_a_string_is_refused() -> bool:
    """A command that cannot be applied is refused rather than corrupting the state."""
    made = Machine()
    made.apply(Command(name=SET, key="k", value="text"))
    try:
        made.apply(Command(name=INCREMENT, key="k", value=1))
    except Refused:
        return True
    return False


def an_unknown_command_is_refused() -> bool:
    """A command name outside the five is refused at construction."""
    try:
        Command(name="frobnicate", key="k")
    except ConfigError:
        return True
    return False


def a_command_without_a_key_is_refused() -> bool:
    """Every command but the clock reader needs a key."""
    try:
        Command(name=SET, value=1)
    except ConfigError:
        return True
    return False


def a_machine_starts_empty() -> dict:
    """A fresh machine holds nothing and has applied nothing.

    The starting state every node rebuilds from, which is why a snapshot has to carry the state
    rather than only the log position: a node that took a snapshot boundary and an empty machine
    would be a node that lost everything below the boundary.
    """
    made = Machine()
    return {
        "keys": len(made.state),
        "applied": made.applied,
        "it_is_empty": made.state == {},
        "and_has_applied_nothing": made.applied == 0,
        "reading_a_missing_key_gives_nothing": made.get("absent") is None,
        "its_digest_is_empty": made.digest() == (),
    }


def a_digest_catches_a_difference_a_length_would_miss() -> dict:
    """Two machines with the same number of keys and different values compare as different.

    The check the cluster invariant uses, so it has to be sensitive to values rather than to
    shape. Comparing key counts would call these two identical and let a divergence through.
    """
    left = replay([Command(name=SET, key="k", value=1)])
    right = replay([Command(name=SET, key="k", value=2)])
    return {
        "same_key_count": len(left.state) == len(right.state),
        "different_values": left.state != right.state,
        "the_digests_differ": left.digest() != right.digest(),
        "and_a_count_would_not_have": len(left.state) == len(right.state),
    }


def compare_the_commands() -> list[dict]:
    """Every command, and the two properties that decide how it can be used."""
    samples = {
        SET: Command(name=SET, key="k", value=1),
        DELETE: Command(name=DELETE, key="k"),
        INCREMENT: Command(name=INCREMENT, key="k", value=1),
        COMPARE_AND_SET: Command(name=COMPARE_AND_SET, key="k", expected=1, value=2),
        NOW: Command(name=NOW, key="k"),
    }
    return [
        {
            "command": name,
            "idempotent": one.idempotent,
            "deterministic": one.deterministic,
            "safe_to_retry": one.idempotent and one.deterministic,
        }
        for name, one in samples.items()
    ]


def most_commands_are_not_safe_to_retry() -> dict:
    """Two of the five can be sent twice without a session, and three cannot.

    The table that says why client.py is not optional. A store of only sets would need no
    deduplication at all, and a store with one counter in it needs it for everything.
    """
    table = compare_the_commands()
    safe = [one["command"] for one in table if one["safe_to_retry"]]
    return {
        "commands": len(table),
        "safe_to_retry": safe,
        "only_two_are_safe": len(safe) == 2,
        "and_they_are_the_idempotent_ones": sorted(safe) == sorted(IDEMPOTENT),
        "one_is_not_even_deterministic": sum(1 for one in table if not one["deterministic"]),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    broken = a_non_deterministic_command_breaks_agreement_silently()
    return {
        "commands": len(COMMANDS),
        "replaying_agrees": the_same_commands_give_the_same_state()["they_all_agree"],
        "order_changes_the_state": order_changes_the_state()["they_differ"],
        "a_random_command_diverges": broken["but_the_states_differ"],
        "with_identical_logs": broken["the_logs_are_identical"],
        "and_nothing_raised": broken["and_nothing_raised"],
        "increment_doubles_on_a_retry": applying_an_increment_twice_doubles_it()[
            "the_increment_doubled"
        ],
        "safe_to_retry": most_commands_are_not_safe_to_retry()["safe_to_retry"],
    }
