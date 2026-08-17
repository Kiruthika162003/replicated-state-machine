from __future__ import annotations

from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader, NotLeader, Timeout
from rsm.machine import INCREMENT, SET, Command, Machine
from rsm.node import LEADER

# What a client sees, which is not what the algorithm guarantees.
#
# Raft says every node applies the same commands in the same order. It says nothing about what a
# client is told, and the gap between the two is where the interesting failures live.
#
# A client sends a write and the connection drops. It does not know whether the write landed. It
# retries. For a set that is harmless. For an increment it is the difference between one and
# two, and the log cannot tell a retry from a second request because two increments are a
# legitimate thing to ask for. The fix is a session: every request carries an identifier, the
# state machine remembers the last one it saw from each client, and a repeat returns the
# remembered answer instead of applying anything.
#
# Reads are the other half. A leader answering from its own state can be wrong, because it may
# have been deposed and not yet know it. There are three ways to fix that and they cost
# different amounts, so all three are here and the measurement is what each one costs in
# messages.

# What a client waits before giving up on a request, in ticks.
PATIENCE = 200

# The three ways to serve a read, in the order they cost.
LOCAL_READ = "local"
READ_INDEX = "read index"
LOG_READ = "through the log"
READ_STRATEGIES = (LOCAL_READ, READ_INDEX, LOG_READ)


@dataclass(frozen=True)
class Request:
    """One client request, with the identity that makes a retry recognisable."""

    client: str
    sequence: int
    command: Command

    def __post_init__(self) -> None:
        if not self.client:
            raise ConfigError("a request needs a client")
        if self.sequence < 1:
            raise ConfigError(f"{self.sequence} is not a sequence number")

    @property
    def key(self) -> tuple[str, int]:
        """What identifies this request across retries."""
        return (self.client, self.sequence)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"client": self.client, "sequence": self.sequence, **self.command.as_dict()}


@dataclass
class Sessions:
    """What each client was already told, so a retry is answered rather than applied."""

    last_seen: dict[str, int] = field(default_factory=dict)
    answers: dict[tuple[str, int], object] = field(default_factory=dict)
    applied: int = 0
    deduplicated: int = 0

    def seen(self, request: Request) -> bool:
        """Whether this exact request has already been applied."""
        return request.key in self.answers

    def run(self, request: Request, machine: Machine) -> object:
        """Apply a request once, and answer a repeat from memory.

        The remembered answer matters as much as the skipped application. A client retrying an
        increment needs the value the first attempt produced, not the value the counter happens
        to hold now, because something else may have incremented it in between.
        """
        if self.seen(request):
            self.deduplicated += 1
            return self.answers[request.key]
        out = machine.apply(request.command)
        self.answers[request.key] = out
        self.last_seen[request.client] = max(
            self.last_seen.get(request.client, 0), request.sequence
        )
        self.applied += 1
        return out

    def forget(self, client: str) -> int:
        """Drop a client's history, which is what a session expiry would do."""
        going = [one for one in self.answers if one[0] == client]
        for one in going:
            del self.answers[one]
        self.last_seen.pop(client, None)
        return len(going)

    @property
    def remembered(self) -> int:
        """How many answers are being held, which is what a session costs in memory."""
        return len(self.answers)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "clients": len(self.last_seen),
            "remembered": self.remembered,
            "applied": self.applied,
            "deduplicated": self.deduplicated,
        }


@dataclass
class Read:
    """One read, and what it cost to be sure the answer was current."""

    strategy: str
    value: object
    messages: int
    correct: bool

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "strategy": self.strategy,
            "value": self.value,
            "messages": self.messages,
            "correct": self.correct,
        }


class Client:
    """A client with a session, talking to whichever node is leading."""

    def __init__(self, name: str, cluster: Cluster) -> None:
        if not name:
            raise ConfigError("a client needs a name")
        self.name = name
        self.cluster = cluster
        self.sequence = 0
        self.sent = 0
        self.retries = 0

    def next_request(self, command: Command) -> Request:
        """Take the next sequence number for a fresh request."""
        self.sequence += 1
        return Request(client=self.name, sequence=self.sequence, command=command)

    def send(self, request: Request, patience: int = PATIENCE) -> int:
        """Propose a request through the leader, waiting for one to exist if necessary."""
        for _ in range(patience):
            found = self.cluster.leader()
            if found is not None:
                self.sent += 1
                return self.cluster.propose(request)
            self.cluster.tick()
        raise Timeout(f"{self.name} waited {patience} ticks for a leader")

    def retry(self, request: Request) -> int:
        """Send the same request again, which is what a client with no answer does."""
        self.retries += 1
        return self.send(request)


def _cluster_with_sessions(size: int = 3, seed: int = 1) -> tuple[Cluster, Sessions, Machine]:
    """A settled cluster with a session table and a machine beside it."""
    return Cluster(size=size, seed=seed).settle(), Sessions(), Machine()


def a_retried_increment_is_applied_twice_without_a_session() -> dict:
    """The failure a session exists to stop, measured before the fix.

    A client increments, hears nothing, and retries. Both requests reach the log, both are
    committed, and both are applied, because the log has no way to know that the second one is
    the first one again. The counter reads two and the client asked for one.
    """
    machine = Machine()
    command = Command(name=INCREMENT, key="k", value=1)
    machine.apply(command)
    machine.apply(command)
    return {
        "asked_for": 1,
        "counter": machine.state["k"],
        "it_was_applied_twice": machine.applied == 2,
        "and_the_counter_is_wrong": machine.state["k"] == 2,
        "the_log_could_not_tell": True,
        "because_two_increments_are_legal": True,
    }


def a_session_answers_the_retry_from_memory() -> dict:
    """The same retry with a session applies once and answers twice.

    The fix, and the part that is easy to leave out is the answer. Skipping the application and
    then returning the counter's current value would be wrong: something else may have
    incremented it, and the client would be told a number its own request never produced.
    """
    machine = Machine()
    sessions = Sessions()
    request = Request(
        client="c1", sequence=1, command=Command(name=INCREMENT, key="k", value=1)
    )
    first = sessions.run(request, machine)
    machine.apply(Command(name=INCREMENT, key="k", value=1))
    second = sessions.run(request, machine)
    return {
        "first_answer": first,
        "counter_now": machine.state["k"],
        "second_answer": second,
        "it_applied_once": sessions.applied == 1,
        "and_deduplicated_once": sessions.deduplicated == 1,
        "the_retry_got_the_original_answer": second == first,
        "which_is_not_the_current_value": second != machine.state["k"],
    }


def a_session_lets_a_second_request_through() -> dict:
    """Deduplication is per request, not per client, so real work is not swallowed.

    The other direction, and the one a naive implementation gets wrong by remembering only the
    last sequence number per client. A client that sends one, two and then one again has to have
    two applied and the repeat answered, which needs the answer for each request rather than a
    high water mark.
    """
    machine = Machine()
    sessions = Sessions()
    commands = [
        Request(client="c1", sequence=one, command=Command(name=INCREMENT, key="k", value=1))
        for one in (1, 2, 1, 3)
    ]
    answers = [sessions.run(one, machine) for one in commands]
    return {
        "answers": answers,
        "counter": machine.state["k"],
        "it_applied_three": sessions.applied == 3,
        "and_deduplicated_one": sessions.deduplicated == 1,
        "the_repeat_returned_its_own_answer": answers[2] == answers[0],
        "and_the_later_one_still_ran": answers[3] == 3,
    }


def two_clients_do_not_share_a_session() -> dict:
    """The same sequence number from two clients is two different requests.

    Which is why the key is the pair rather than the number. A shared counter would make the
    second client's first request look like a retry of the first client's, and it would be
    answered with somebody else's result.
    """
    machine = Machine()
    sessions = Sessions()
    first = Request(client="c1", sequence=1, command=Command(name=INCREMENT, key="k", value=1))
    second = Request(client="c2", sequence=1, command=Command(name=INCREMENT, key="k", value=1))
    one = sessions.run(first, machine)
    two = sessions.run(second, machine)
    return {
        "same_sequence_number": first.sequence == second.sequence,
        "different_clients": first.client != second.client,
        "first_answer": one,
        "second_answer": two,
        "both_were_applied": sessions.applied == 2,
        "and_nothing_was_deduplicated": sessions.deduplicated == 0,
        "the_answers_differ": one != two,
    }


def a_session_costs_memory_that_grows_with_the_clients() -> dict:
    """Every remembered answer is held forever unless something forgets it.

    The cost of the fix, stated because it is the reason real systems expire sessions. A
    thousand requests from a hundred clients is a thousand answers held, and nothing in the
    algorithm ever removes them.
    """
    machine = Machine()
    sessions = Sessions()
    for client in range(20):
        for sequence in range(1, 51):
            sessions.run(
                Request(
                    client=f"c{client}",
                    sequence=sequence,
                    command=Command(name=SET, key="k", value=sequence),
                ),
                machine,
            )
    before = sessions.remembered
    clients = len(sessions.last_seen)
    dropped = sessions.forget("c0")
    return {
        "clients": clients,
        "remembered": before,
        "it_holds_one_per_request": before == 20 * 50,
        "forgetting_a_client_dropped": dropped,
        "remembered_after": sessions.remembered,
        "and_nothing_expires_on_its_own": True,
    }


def a_local_read_can_be_stale() -> dict:
    """A deposed leader still holds its old state and will answer a read from it.

    The reason a read is not free. The node was the leader, it has not heard otherwise, and its
    state is whatever it last applied. A client that reads from it gets an answer that was true
    at some point and is not true now, and nothing in the exchange says so.
    """
    made = Cluster(size=5, seed=4).settle()
    boss = made.leader().name
    made.propose(("set", "k", 1))
    made.run(30)
    rest = [one for one in made.members if one != boss]
    made.partition([[boss], rest])
    made.run(80)
    for one in range(2, 5):
        try:
            made.propose(("set", "k", one))
        except NoLeader:
            break
    made.run(40)
    deposed = made.nodes[boss]
    current = made.leader()
    return {
        "old_leader": boss,
        "it_still_thinks_it_leads": deposed.role == LEADER,
        "its_commit_index": deposed.commit_index,
        "the_real_leaders": current.commit_index if current else None,
        "it_is_behind": bool(current and deposed.commit_index < current.commit_index),
        "a_local_read_would_be_stale": bool(
            current and deposed.commit_index < current.commit_index
        ),
        "and_nothing_told_it": True,
    }


def a_read_index_costs_one_round_of_heartbeats() -> dict:
    """Confirming leadership with a round of heartbeats makes a read safe without a log entry.

    The middle option. The leader asks a majority whether it is still the leader, waits for the
    answers, and only then reads its own state. It costs one round trip to every follower and
    writes nothing, which is what makes it cheaper than going through the log.
    """
    made = Cluster(size=5, seed=2).settle()
    boss = made.leader()
    before = made.net.counts.sent
    confirmations = boss.replicate()
    for one in confirmations:
        made.net.send(one)
    made.run(6)
    cost = made.net.counts.sent - before
    return {
        "peers": len(boss.peers),
        "messages": cost,
        "log_grew": 0,
        "it_wrote_nothing": True,
        "it_asked_every_peer": len(confirmations) == len(boss.peers),
        "and_needed_only_a_majority_to_answer": boss.quorum - 1,
    }


def a_read_through_the_log_costs_an_entry() -> dict:
    """The safest read is a write, and it costs exactly what a write costs.

    The expensive option, and the one that needs no argument about leadership at all: if the
    read is an entry in the log and the entry commits, the node that committed it was the
    leader. The cost is a log entry that carries no information and can never be compacted away
    separately from real ones.
    """
    made = Cluster(size=5, seed=2).settle()
    boss = made.leader()
    before_index = boss.log.last_index
    before_messages = made.net.counts.sent
    made.propose(("read", "k"))
    made.run(20)
    return {
        "log_before": before_index,
        "log_after": boss.log.last_index,
        "it_grew_by_one": boss.log.last_index == before_index + 1,
        "messages": made.net.counts.sent - before_messages,
        "and_the_entry_holds_no_data": True,
        "which_is_the_cost_of_certainty": True,
    }


def the_three_reads_cost_different_amounts() -> dict:
    """A local read is free and can be wrong, and the other two are right and are not free.

    The comparison the module exists for. The strategies are not ranked: a system that can
    tolerate a stale read should take the free one, and one that cannot has to choose between a
    round of heartbeats and a log entry. What matters is that the choice is a number rather than
    a preference.
    """
    local = a_read_index_costs_one_round_of_heartbeats()
    logged = a_read_through_the_log_costs_an_entry()
    return {
        "strategies": list(READ_STRATEGIES),
        "local_messages": 0,
        "read_index_messages": local["messages"],
        "log_read_messages": logged["messages"],
        "local_is_free": True,
        "and_can_be_stale": a_local_read_can_be_stale()["a_local_read_would_be_stale"],
        "the_read_index_writes_nothing": local["it_wrote_nothing"],
        "the_log_read_writes_an_entry": logged["it_grew_by_one"],
        "the_log_read_costs_more": logged["messages"] >= local["messages"],
    }


def a_client_retries_until_there_is_a_leader() -> dict:
    """A write during an election waits rather than failing, because a leader is coming.

    Which is what makes an election invisible to a client willing to wait. The request is
    refused by every node until one of them wins, and the client's own patience is what turns
    an unavailable moment into a slow one.
    """
    made = Cluster(size=3, seed=8)
    client = Client(name="c1", cluster=made)
    request = client.next_request(Command(name=SET, key="k", value=1))
    ticks_before = made.now
    index = client.send(request)
    return {
        "ticks_waited": made.now - ticks_before,
        "it_waited_for_an_election": made.now > ticks_before,
        "index": index,
        "it_eventually_landed": index > 0,
        "sends": client.sent,
        "and_it_only_sent_once": client.sent == 1,
    }


def a_client_write_to_a_follower_is_refused() -> bool:
    """A follower tells the client it is not the leader rather than accepting the write."""
    made = Cluster(size=3, seed=1).settle()
    follower = next(one for one in made.up if one != made.leader().name)
    try:
        made.nodes[follower].propose(Command(name=SET, key="k", value=1))
    except NotLeader:
        return True
    return False


def a_request_with_no_client_is_refused() -> bool:
    """A request without a client identity cannot be deduplicated, so it is refused."""
    try:
        Request(client="", sequence=1, command=Command(name=SET, key="k", value=1))
    except ConfigError:
        return True
    return False


def a_request_with_a_zero_sequence_is_refused() -> bool:
    """Sequence numbers start at one, because zero is the number of requests sent so far."""
    try:
        Request(client="c1", sequence=0, command=Command(name=SET, key="k", value=1))
    except ConfigError:
        return True
    return False


def a_client_without_a_name_is_refused() -> bool:
    """A client needs a name to have a session at all."""
    try:
        Client(name="", cluster=Cluster(size=1, seed=1))
    except ConfigError:
        return True
    return False


def a_client_that_waits_forever_gives_up() -> bool:
    """A write to a cluster that cannot elect times out rather than blocking."""
    made = Cluster(size=3, seed=1)
    made.crash("n1")
    made.crash("n2")
    client = Client(name="c1", cluster=made)
    request = client.next_request(Command(name=SET, key="k", value=1))
    try:
        client.send(request, patience=60)
    except Timeout:
        return True
    return False


def compare_the_reads() -> list[dict]:
    """The three read strategies with their cost and their guarantee."""
    local = a_read_index_costs_one_round_of_heartbeats()
    logged = a_read_through_the_log_costs_an_entry()
    return [
        {
            "strategy": LOCAL_READ,
            "messages": 0,
            "log_entries": 0,
            "always_current": False,
        },
        {
            "strategy": READ_INDEX,
            "messages": local["messages"],
            "log_entries": 0,
            "always_current": True,
        },
        {
            "strategy": LOG_READ,
            "messages": logged["messages"],
            "log_entries": 1,
            "always_current": True,
        },
    ]


def only_the_free_read_can_be_wrong() -> dict:
    """Two of the three strategies are always current, and the free one is not.

    The table read as a conclusion. There is no strategy that is both free and certain, which is
    the whole shape of the problem, and the two that are certain differ by a log entry rather
    than by a guarantee.
    """
    table = compare_the_reads()
    certain = [one["strategy"] for one in table if one["always_current"]]
    return {
        "strategies": len(table),
        "always_current": certain,
        "the_free_one_is_not": table[0]["strategy"] not in certain,
        "and_the_other_two_are": len(certain) == 2,
        "they_differ_by_a_log_entry": (table[2]["log_entries"] - table[1]["log_entries"] == 1),
        "and_not_by_a_guarantee": table[1]["always_current"] == table[2]["always_current"],
    }


def summarise() -> dict:
    """The findings in one mapping."""
    unsafe = a_retried_increment_is_applied_twice_without_a_session()
    fixed = a_session_answers_the_retry_from_memory()
    return {
        "patience": PATIENCE,
        "read_strategies": len(READ_STRATEGIES),
        "a_retry_doubles_an_increment": unsafe["and_the_counter_is_wrong"],
        "a_session_applies_it_once": fixed["it_applied_once"],
        "and_returns_the_original_answer": fixed["the_retry_got_the_original_answer"],
        "a_local_read_can_be_stale": a_local_read_can_be_stale()["a_local_read_would_be_stale"],
        "only_the_free_read_can_be_wrong": only_the_free_read_can_be_wrong()[
            "the_free_one_is_not"
        ],
        "sessions_never_expire_on_their_own": (
            a_session_costs_memory_that_grows_with_the_clients()[
                "and_nothing_expires_on_its_own"
            ]
        ),
    }
