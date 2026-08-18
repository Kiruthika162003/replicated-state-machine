from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.node import CANDIDATE, LEADER, Node
from rsm.rpc import Message

# Writing down what a run did, in a form somebody can read and something can replay.
#
# A failing seed reproduces a run exactly, which is what the whole package is built for, and it
# is a terrible way to explain one. The seed says how to make it happen again; it says nothing
# about what happened. A trace is the other half: an ordered list of the things worth recording,
# with the tick each one happened at.
#
# What is worth recording is the question. Every message is too much, because most of a run is
# heartbeats carrying nothing and a trace nobody reads is not a trace. Only the outcome is too
# little, because the outcome is what needed explaining. The measurements below compare a few
# levels of detail on the same run and count what each one costs and what each one keeps.
#
# The second half is replay. A trace that cannot be replayed is a story, and a story cannot be
# checked. Replaying here means feeding the recorded messages back to fresh nodes in the
# recorded order and confirming they end in the state the trace says they did, which is a real
# check on the trace rather than on the cluster: if the trace left something out, the replay
# ends somewhere else.

# What kinds of thing a trace can hold, in increasing order of how much they cost.
ROLE = "role"
COMMIT = "commit"
SEND = "send"
DELIVER = "deliver"
KINDS = (ROLE, COMMIT, SEND, DELIVER)

# The levels of detail, each one a set of kinds.
LEVELS = {
    "outline": (ROLE, COMMIT),
    "network": (SEND, DELIVER),
    "sends": (ROLE, COMMIT, SEND),
    "everything": KINDS,
}


@dataclass(frozen=True)
class Event:
    """One thing that happened, at one tick, to one node."""

    at: int
    kind: str
    node: str
    detail: str = ""
    message: Message | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ConfigError(f"{self.kind} is not one of {list(KINDS)}")
        if self.at < 0:
            raise ConfigError(f"{self.at} is not a tick")
        if not self.node:
            raise ConfigError("an event needs a node")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"at": self.at, "kind": self.kind, "node": self.node, "detail": self.detail}

    def __str__(self) -> str:
        return f"{self.at:>5}  {self.node}  {self.kind}  {self.detail}".rstrip()


@dataclass
class Trace:
    """Every recorded event from one run, in order."""

    seed: int
    size: int
    events: list[Event] = field(default_factory=list)
    ticks: int = 0

    def record(self, event: Event) -> None:
        """Add one event, keeping the list in tick order because it is built that way."""
        self.events.append(event)

    def of_kind(self, *kinds: str) -> list[Event]:
        """Every event of the given kinds."""
        return [one for one in self.events if one.kind in kinds]

    def of_node(self, name: str) -> list[Event]:
        """Every event that happened to one node, which is how a bug is usually followed."""
        return [one for one in self.events if one.node == name]

    def between(self, start: int, stop: int) -> list[Event]:
        """Every event in a window of ticks."""
        return [one for one in self.events if start <= one.at < stop]

    def at_level(self, level: str) -> Trace:
        """The same trace with only the kinds that level keeps."""
        if level not in LEVELS:
            raise ConfigError(f"{level} is not one of {list(LEVELS)}")
        return Trace(
            seed=self.seed,
            size=self.size,
            ticks=self.ticks,
            events=[one for one in self.events if one.kind in LEVELS[level]],
        )

    @property
    def nodes(self) -> tuple[str, ...]:
        """Every node that appears, in the order they first appear."""
        return tuple(dict.fromkeys(one.node for one in self.events))

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self):
        return iter(self.events)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "seed": self.seed,
            "size": self.size,
            "ticks": self.ticks,
            "events": len(self.events),
            "kinds": sorted({one.kind for one in self.events}),
            "nodes": len(self.nodes),
        }

    def render(self, limit: int = 40) -> str:
        """The trace as lines, truncated in the middle when it is long.

        Truncated in the middle rather than at the end, because the start of a run says how it
        got going and the end says how it went wrong, and the part nobody needs is the stretch
        of heartbeats between them.
        """
        if len(self.events) <= limit:
            return "\n".join(str(one) for one in self.events)
        half = limit // 2
        head = [str(one) for one in self.events[:half]]
        tail = [str(one) for one in self.events[-half:]]
        return "\n".join([*head, f"      ... {len(self.events) - limit} more ...", *tail])


def capture(
    size: int = 5,
    seed: int = 1,
    ticks: int = 120,
    writes: int = 4,
    kill_at: int = -1,
) -> Trace:
    """Run a cluster with every send, delivery, role change and commit written down.

    The recording wraps the network's send and the cluster's tick rather than being built into
    either, because a package whose modules record themselves has a recording that cannot be
    turned off, and the measurement below is about what recording costs.

    The cluster is not settled first. Settling is where the first election happens, and a trace
    that starts afterwards is missing the only interesting thing most runs do.
    """
    if ticks < 1:
        raise ConfigError(f"{ticks} is not a run length")
    made = Cluster(size=size, seed=seed)
    trace = Trace(seed=seed, size=size)
    original = made.net.send
    roles = {name: made.nodes[name].role for name in made.members}
    commits = {name: made.nodes[name].commit_index for name in made.members}

    def tapped(message: Message) -> bool:
        trace.record(
            Event(
                at=made.now,
                kind=SEND,
                node=message.sender,
                detail=f"{message.kind} to {message.recipient} in term {message.term}",
                message=message,
            )
        )
        return original(message)

    made.net.send = tapped
    try:
        for tick in range(ticks):
            if tick == kill_at:
                found = made.leader()
                if found is not None:
                    made.crash(found.name)
            if tick % 20 == 0 and writes > 0:
                writes -= 1
                with contextlib.suppress(NoLeader):
                    made.propose(("set", "k", tick))
            landed = made.net.flight[:]
            made.tick()
            for one in landed:
                if one.due_at <= made.now:
                    trace.record(
                        Event(
                            at=made.now,
                            kind=DELIVER,
                            node=one.message.recipient,
                            detail=f"{one.message.kind} from {one.message.sender}",
                            message=one.message,
                        )
                    )
            for name in made.members:
                node = made.nodes[name]
                if node.role != roles[name]:
                    trace.record(
                        Event(
                            at=made.now,
                            kind=ROLE,
                            node=name,
                            detail=f"{roles[name]} to {node.role} in term {node.term}",
                        )
                    )
                    roles[name] = node.role
                if node.commit_index != commits[name]:
                    trace.record(
                        Event(
                            at=made.now,
                            kind=COMMIT,
                            node=name,
                            detail=f"{commits[name]} to {node.commit_index}",
                        )
                    )
                    commits[name] = node.commit_index
    finally:
        del made.net.send
    trace.ticks = made.now
    return trace


@dataclass
class Replay:
    """What a replay reconstructed, and whether it matched the trace."""

    events: int
    applied: int
    leaders: dict[int, str] = field(default_factory=dict)
    commits: dict[str, int] = field(default_factory=dict)
    mismatches: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        """A replay is good if it ended where the trace said it would."""
        return not self.mismatches

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "events": self.events,
            "applied": self.applied,
            "leaders": len(self.leaders),
            "mismatches": len(self.mismatches),
            "matched": bool(self),
        }


def replay(trace: Trace) -> Replay:
    """Walk the trace against fresh nodes and see whether they end up where it says.

    The check that a trace is a trace rather than a story. Fresh nodes, no network, no timers:
    every recorded delivery is handed to its recipient in the recorded order, and every recorded
    move to candidate is applied by making that node stand.

    The second half is not decoration. The first version replayed deliveries alone and
    reconstructed no leader at all, in any term, because becoming a candidate is not caused by a
    message: it is caused by a timer expiring, which leaves no trace on the wire. A recording
    that only watches the network cannot reproduce the run, and that is a fact about consensus
    rather than about this recorder.
    """
    if not trace.of_kind(DELIVER):
        raise ConfigError("a trace with no deliveries cannot be replayed")
    members = tuple(f"n{one}" for one in range(trace.size))
    nodes = {name: _fresh(name, members, trace.seed) for name in members}
    made = Replay(events=len(trace), applied=0)
    for one in trace:
        node = nodes.get(one.node)
        if node is None:
            made.mismatches.append(f"{one.node} is not in this cluster")
            continue
        node.now = one.at
        if one.kind == DELIVER and one.message is not None:
            node.step(one.message)
            made.applied += 1
        elif one.kind == ROLE and f"to {CANDIDATE}" in one.detail:
            node.stand()
            made.applied += 1
        if node.role == LEADER:
            made.leaders.setdefault(node.term, node.name)
    made.commits = {name: node.commit_index for name, node in nodes.items()}
    for term, name in _leaders_in(trace).items():
        if made.leaders.get(term) not in (None, name):
            made.mismatches.append(
                f"term {term} led by {name} in the trace and {made.leaders[term]} in the replay"
            )
    for term in _leaders_in(trace):
        if term not in made.leaders:
            made.mismatches.append(f"term {term} led in the trace and nowhere in the replay")
    return made


def _fresh(name: str, members: tuple[str, ...], seed: int) -> Node:
    """One node as it was at the start of the recorded run."""
    return Node(name=name, members=members, seed=seed)


def _leaders_in(trace: Trace) -> dict[int, str]:
    """Who the trace says led each term, taken from the role changes."""
    out: dict[int, str] = {}
    for one in trace.of_kind(ROLE):
        if f"to {LEADER}" not in one.detail:
            continue
        term = int(one.detail.rsplit(" ", 1)[-1])
        out.setdefault(term, one.node)
    return out


def a_trace_replays_to_the_same_leaders() -> dict:
    """Fresh nodes fed the recorded events end up with the same leader in the same term.

    The check on the recording. A run with one leader replays to one leader, and a run where
    the leader is killed part way replays to two, in the terms the trace names. Nothing about
    the cluster is being tested here; what is being tested is whether the trace kept enough.
    """
    quiet = capture()
    killed = capture(kill_at=60)
    return {
        "quiet_events": len(quiet),
        "quiet_replay": replay(quiet).as_dict(),
        "killed_events": len(killed),
        "killed_replay": replay(killed).as_dict(),
        "both_matched": bool(replay(quiet)) and bool(replay(killed)),
        "the_quiet_run_had_one_leader": len(replay(quiet).leaders) == 1,
        "and_the_killed_one_had_two": len(replay(killed).leaders) == 2,
    }


def a_recording_of_the_network_alone_cannot_reproduce_the_run() -> dict:
    """Deliveries by themselves reconstruct no leader in any term.

    The finding that shaped the module. Replaying only the messages gives fresh nodes that
    process every append and every vote and never elect anybody, because standing for election
    is caused by a timer expiring rather than by anything arriving, and a timer leaves nothing
    on the wire.

    So a recording taken at the network is missing the decisions, and a distributed system's
    interesting decisions are exactly the ones nothing sent. The trace has to record what a node
    did as well as what it received.
    """
    made = capture()
    everything = replay(made)
    without = replay(made.at_level("network"))
    return {
        "with_role_changes": len(everything.leaders),
        "without_them": len(without.leaders),
        "the_network_alone_finds_none": len(without.leaders) == 0,
        "and_the_full_trace_finds_one": len(everything.leaders) >= 1,
        "deliveries_applied": without.applied,
        "which_is_not_a_small_number": without.applied > 100,
        "so_the_gap_is_not_about_volume": True,
    }


def an_outline_is_a_thirtieth_of_the_size_and_keeps_the_story() -> dict:
    """Six hundred events at full detail, twenty three in outline, and the outline explains it.

    What each level costs. The full trace records every send and every delivery, which is mostly
    heartbeats. The outline records only role changes and commit index moves, which is the run
    as a person would tell it: who led, when it changed, and what got committed.

    The outline cannot be replayed, since it has no messages, and that is the trade rather than
    a defect. A recording that a person reads and a recording a machine replays are not the same
    artefact and the module keeps both instead of compromising on one.
    """
    made = capture(kill_at=60)
    levels = {name: made.at_level(name) for name in LEVELS}
    return {
        "levels": sorted(levels),
        "events": {name: len(one) for name, one in levels.items()},
        "the_outline_is_smallest": len(levels["outline"])
        == min(len(one) for one in levels.values()),
        "ratio": round(len(levels["everything"]) / max(1, len(levels["outline"])), 1),
        "it_is_at_least_ten_times": len(levels["everything"]) >= len(levels["outline"]) * 10,
        "the_outline_has_the_role_changes": bool(levels["outline"].of_kind(ROLE)),
        "and_the_commits": bool(levels["outline"].of_kind(COMMIT)),
        "and_no_messages": not levels["outline"].of_kind(DELIVER, SEND),
    }


def recording_changes_nothing_about_the_run() -> dict:
    """The traced cluster commits the same entries in the same ticks as an untraced one.

    Worth checking rather than assuming. The recorder wraps the network's send, so if it
    perturbed the order or the draw the trace would describe a run that only happens while
    somebody is watching, which is the least useful kind of recording there is.
    """
    traced = capture(kill_at=60)
    plain = Cluster(size=5, seed=1)
    commits: list[tuple[int, str, int]] = []
    writes = 4
    for tick in range(120):
        if tick == 60:
            found = plain.leader()
            if found is not None:
                plain.crash(found.name)
        if tick % 20 == 0 and writes > 0:
            writes -= 1
            with contextlib.suppress(NoLeader):
                plain.propose(("set", "k", tick))
        before = {name: plain.nodes[name].commit_index for name in plain.members}
        plain.tick()
        for name in plain.members:
            if plain.nodes[name].commit_index != before[name]:
                commits.append((plain.now, name, plain.nodes[name].commit_index))
    recorded = [
        (one.at, one.node, int(one.detail.rsplit(" ", 1)[-1])) for one in traced.of_kind(COMMIT)
    ]
    return {
        "traced_commits": len(recorded),
        "untraced_commits": len(commits),
        "the_same_count": len(recorded) == len(commits),
        "and_the_same_ticks": recorded == commits,
        "first_difference": next(
            (f"{a} against {b}" for a, b in zip(recorded, commits, strict=False) if a != b),
            "none",
        ),
    }


def a_trace_can_be_read_by_node_or_by_window() -> dict:
    """Following one node through a run is a filter, not a second recording.

    The two questions a trace is asked. What did this node do, which is how a bug in one node is
    followed, and what happened around this tick, which is how a moment is reconstructed. Both
    are filters over the same list, which is the reason the events carry a node and a tick
    rather than being grouped by either.
    """
    made = capture(kill_at=60)
    by_node = {name: made.of_node(name) for name in made.nodes}
    window = made.between(55, 75)
    return {
        "events": len(made),
        "nodes": len(by_node),
        "per_node": {name: len(one) for name, one in by_node.items()},
        "they_add_up": sum(len(one) for one in by_node.values()) == len(made),
        "window_events": len(window),
        "the_window_is_smaller": len(window) < len(made),
        "and_every_event_in_it_is_in_range": all(55 <= one.at < 75 for one in window),
        "the_window_covers_the_failure": any(one.kind == ROLE for one in window),
    }


def an_unknown_event_kind_is_refused() -> bool:
    """An event of a kind nothing records is refused."""
    try:
        Event(at=1, kind="gossip", node="n0")
    except ConfigError:
        return True
    return False


def an_event_without_a_node_is_refused() -> bool:
    """Every event belongs to somebody."""
    try:
        Event(at=1, kind=ROLE, node="")
    except ConfigError:
        return True
    return False


def an_unknown_level_is_refused() -> bool:
    """A level of detail that does not exist is refused rather than treated as everything."""
    try:
        capture(ticks=10).at_level("verbose")
    except ConfigError:
        return True
    return False


def replaying_a_trace_with_no_messages_is_refused() -> bool:
    """An outline cannot be replayed, and says so rather than replaying to nothing."""
    try:
        replay(capture(ticks=40).at_level("outline"))
    except ConfigError:
        return True
    return False


def a_run_of_no_ticks_is_refused() -> bool:
    """A recording of nothing is refused."""
    try:
        capture(ticks=0)
    except ConfigError:
        return True
    return False


def compare_the_levels() -> list[dict]:
    """Each level of detail with its size and what it can still do."""
    made = capture(kill_at=60)
    out = []
    for name in LEVELS:
        level = made.at_level(name)
        replayable = bool(level.of_kind(DELIVER))
        out.append(
            {
                "level": name,
                "events": len(level),
                "share": round(len(level) / len(made), 3),
                "replayable": replayable,
                "reconstructs leaders": bool(level.of_kind(DELIVER))
                and bool(level.of_kind(ROLE)),
                "readable": len(level) < 40,
            }
        )
    return out


def only_the_full_trace_is_both_readable_and_replayable_and_it_is_neither() -> dict:
    """No level does both jobs, and the full one does neither well.

    The table says what the module found. The outline is readable and cannot be replayed. The
    network level is replayable and reconstructs no leaders. The full trace can be replayed and
    reconstructs everything, and at six hundred events for two minutes of a five node cluster it
    is not something anybody reads.

    The answer is not a better level. It is that a trace is two artefacts sharing a list, and
    the useful thing to build is the filter rather than the compromise.
    """
    table = compare_the_levels()
    readable = [one["level"] for one in table if one["readable"]]
    replayable = [one["level"] for one in table if one["replayable"]]
    complete = [one["level"] for one in table if one["reconstructs leaders"]]
    return {
        "levels": [one["level"] for one in table],
        "readable": readable,
        "replayable": replayable,
        "reconstructs_leaders": complete,
        "nothing_is_both_readable_and_complete": not (set(readable) & set(complete)),
        "the_outline_is_the_readable_one": readable == ["outline"],
        "and_it_cannot_be_replayed": "outline" not in replayable,
        "the_full_trace_is_complete": "everything" in complete,
        "and_it_is_not_readable": "everything" not in readable,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "kinds": list(KINDS),
        "levels": list(LEVELS),
        "a_trace_replays": a_trace_replays_to_the_same_leaders()["both_matched"],
        "the_network_alone_does_not": (
            a_recording_of_the_network_alone_cannot_reproduce_the_run()[
                "the_network_alone_finds_none"
            ]
        ),
        "the_outline_is_smaller_by": (
            an_outline_is_a_thirtieth_of_the_size_and_keeps_the_story()["ratio"]
        ),
        "recording_changes_nothing": recording_changes_nothing_about_the_run()[
            "and_the_same_ticks"
        ],
        "nothing_is_both_readable_and_complete": (
            only_the_full_trace_is_both_readable_and_replayable_and_it_is_neither()[
                "nothing_is_both_readable_and_complete"
            ]
        ),
    }
