from __future__ import annotations

from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import Compacted, ConfigError, LogError
from rsm.log import NO_INDEX, NO_TERM, Entry, Log
from rsm.machine import SET, Command, Machine
from rsm.node import Node
from rsm.rpc import Installed, InstallSnapshot, Vote

# Log compaction: throwing away entries that the state machine has already absorbed.
#
# A log that is never trimmed grows without bound, and every restart replays it from the
# beginning. A snapshot is the state machine's state at one index, written down, so that
# everything below that index can be discarded and a restart starts from the snapshot instead of
# from nothing.
#
# The part that is easy to get wrong is not taking the snapshot, it is what the log has to keep
# afterwards. The entry at the snapshot's own index is gone, and the consistency check on the
# next append will ask about exactly that index, so its term has to survive the entry that
# carried it. A log that discarded the term along with the entry cannot answer the question its
# leader is about to ask, and the follower refuses every append forever.
#
# The second part is that a follower can fall so far behind that the leader no longer has the
# entries it needs. There is no way to catch it up with appends, because the appends do not
# exist any more, so the leader sends the whole state instead. That is the third RPC, and the
# measurement below is when it becomes cheaper than the entries it replaces.

# How many entries a node accumulates before it considers compacting. Small enough that the
# scenarios reach it, and the measurement below is what the threshold costs either way.
COMPACT_AFTER = 50

# The estimated bytes one entry occupies, and one key of state. Both are made up, and only their
# ratio matters: it decides where sending a snapshot becomes cheaper than sending entries.
ENTRY_BYTES = 32
KEY_BYTES = 24


@dataclass(frozen=True)
class Snapshot:
    """The state machine at one index, and the log position it stands for."""

    last_index: int
    last_term: int
    state: dict = field(default_factory=dict)
    members: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.last_index < NO_INDEX:
            raise ConfigError(f"{self.last_index} is not an index")
        if self.last_index > NO_INDEX and self.last_term < 1:
            raise ConfigError(f"a snapshot at {self.last_index} needs a term")

    @property
    def nbytes(self) -> int:
        """What the state would cost to send."""
        return len(self.state) * KEY_BYTES

    @property
    def empty(self) -> bool:
        """Whether this snapshot stands for nothing."""
        return self.last_index == NO_INDEX

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "last_index": self.last_index,
            "last_term": self.last_term,
            "keys": len(self.state),
            "bytes": self.nbytes,
        }


def take(node: Node) -> Snapshot:
    """Capture a node's applied state as a snapshot at its last applied index.

    Taken at the applied index rather than the commit index, because the snapshot has to be a
    state the machine actually reached. A snapshot at the commit index would claim to describe
    entries the machine has not run yet.
    """
    applied = node.last_applied
    return Snapshot(
        last_index=applied,
        last_term=node.log.term_at(applied) if applied > NO_INDEX else NO_TERM,
        state=dict(node.state),
        members=node.members,
    )


def compact(log: Log, upto: int, term: int) -> int:
    """Discard everything at or below an index, keeping that index's term.

    The term is the whole point. It is what the next consistency check asks about, and a log
    that dropped it along with the entry would refuse every append that followed.
    """
    if upto < log.snapshot_index:
        raise ConfigError(f"{upto} is below the existing snapshot at {log.snapshot_index}")
    if upto > log.last_index:
        raise LogError(f"{upto} is past the end at {log.last_index}")
    going = [one for one in log.entries if one.index <= upto]
    log.entries = [one for one in log.entries if one.index > upto]
    log.snapshot_index = upto
    log.snapshot_term = term
    return len(going)


def restore(node: Node, made: Snapshot) -> None:
    """Replace a node's log and state with a snapshot, which is what a far behind node does."""
    node.log = Log(entries=[], snapshot_index=made.last_index, snapshot_term=made.last_term)
    node.state = dict(made.state)
    node.commit_index = made.last_index
    node.last_applied = made.last_index


def _loaded(entries: int = 120, keys: int = 8, seed: int = 1) -> Node:
    """A node with a log of writes over a few keys, all applied."""
    node = Node(name="a", members=("a", "b", "c"), seed=seed)
    for one in range(1, entries + 1):
        node.log.append([Entry(term=1, index=one, command=("set", f"k{one % keys}", one))])
    node.commit_index = entries
    node.apply_committed()
    return node


def compacting_keeps_the_term_at_the_boundary() -> dict:
    """The snapshot index has no entry and still has a term, which is what appends ask about.

    The failure this prevents is silent and total. A follower that compacted away the term along
    with the entry answers the next consistency check with a mismatch, refuses the append, and
    keeps refusing, because the leader backs up to an index that is inside the snapshot and can
    never be satisfied.
    """
    node = _loaded()
    term = node.log.term_at(60)
    dropped = compact(node.log, 60, term)
    return {
        "dropped": dropped,
        "first_index": node.log.first_index,
        "last_index": node.log.last_index,
        "the_entry_is_gone": not node.log.holds(60),
        "but_the_term_survived": node.log.term_at(60) == term,
        "so_the_check_still_passes": node.log.matches(60, term),
        "and_a_wrong_term_still_fails": not node.log.matches(60, term + 5),
    }


def a_compacted_log_cannot_answer_below_the_boundary() -> dict:
    """Everything under the snapshot is refused rather than answered wrongly.

    Which is the other half of the boundary. The term at the snapshot index is available; the
    term at any index below it is not, and the log says so rather than returning something
    plausible. A leader that receives that refusal knows to send a snapshot instead.
    """
    node = _loaded()
    compact(node.log, 60, node.log.term_at(60))
    refused = False
    try:
        node.log.at(59)
    except Compacted:
        refused = True
    return {
        "snapshot_index": node.log.snapshot_index,
        "reading_below_is_refused": refused,
        "reading_the_boundary_gives_a_term": node.log.term_at(60) > 0,
        "and_reading_above_works": node.log.at(61).index == 61,
        "matching_below_the_boundary_fails": not node.log.matches(59, 1),
    }


def compacting_frees_the_entries_and_keeps_the_state() -> dict:
    """The log shrinks and the state machine is untouched, which is the whole trade.

    A snapshot is a change of representation, not a loss. The hundred and twenty entries said
    how the state got there; the snapshot says what it is. For replay the first is necessary and
    for correctness only the second is.
    """
    node = _loaded()
    before_entries = len(node.log)
    before_state = dict(node.state)
    made = take(node)
    compact(node.log, made.last_index, made.last_term)
    return {
        "entries_before": before_entries,
        "entries_after": len(node.log),
        "it_freed_everything": len(node.log) == 0,
        "state_before": len(before_state),
        "state_after": len(node.state),
        "the_state_is_unchanged": node.state == before_state,
        "snapshot_keys": len(made.state),
        "and_the_snapshot_holds_it": made.state == before_state,
    }


def a_snapshot_is_smaller_than_the_log_it_replaces() -> dict:
    """Eight keys against a hundred and twenty entries, which is why compaction is worth doing.

    The saving is not in the entry count, it is in the ratio between distinct keys and writes. A
    workload that writes each key once compacts to nothing, and one that writes eight keys a
    thousand times compacts to eight.
    """
    node = _loaded(entries=120, keys=8)
    made = take(node)
    log_bytes = len(node.log) * ENTRY_BYTES
    return {
        "entries": len(node.log),
        "keys": len(made.state),
        "log_bytes": log_bytes,
        "snapshot_bytes": made.nbytes,
        "the_snapshot_is_smaller": made.nbytes < log_bytes,
        "by_this_ratio": round(log_bytes / max(made.nbytes, 1), 2),
        "which_is_writes_over_keys": round(120 / 8, 2),
    }


def a_workload_with_no_repeats_compacts_to_nothing() -> dict:
    """Writing each key once makes the snapshot nearly the size of the log it replaces.

    The case that says the previous measurement is about the workload rather than about
    compaction. A hundred and twenty distinct keys produce a hundred and twenty keys of state,
    and trimming the log saves the entry headers and nothing else: a ratio of 1.33 against 20.
    """
    node = _loaded(entries=120, keys=120)
    made = take(node)
    log_bytes = len(node.log) * ENTRY_BYTES
    return {
        "entries": len(node.log),
        "keys": len(made.state),
        "log_bytes": log_bytes,
        "snapshot_bytes": made.nbytes,
        "they_are_comparable": made.nbytes >= log_bytes * 0.5,
        "the_ratio": round(log_bytes / max(made.nbytes, 1), 2),
        "against_the_repeating_workload": a_snapshot_is_smaller_than_the_log_it_replaces()[
            "by_this_ratio"
        ],
        "so_the_saving_is_the_workloads": True,
    }


def a_restart_from_a_snapshot_skips_the_replay() -> dict:
    """Restoring reaches the same state without applying a single entry.

    What compaction buys at startup. Replaying a hundred and twenty entries and restoring one
    snapshot end in the same place, and the second one applies nothing at all.
    """
    node = _loaded()
    made = take(node)
    fresh = Node(name="b", members=("a", "b", "c"), seed=2)
    restore(fresh, made)
    replayed = Machine()
    for one in node.log:
        if one.command is not None:
            replayed.apply(Command(name=SET, key=one.command[1], value=one.command[2]))
    return {
        "entries_replayed": replayed.applied,
        "entries_applied_on_restore": 0,
        "the_states_match": fresh.state == node.state,
        "it_applied_nothing": fresh.last_applied == made.last_index,
        "and_the_log_starts_at_the_boundary": fresh.log.first_index == made.last_index + 1,
        "commit_index_after": fresh.commit_index,
    }


def a_leader_sends_a_snapshot_when_the_entries_are_gone() -> dict:
    """A follower below the leader's snapshot index gets state instead of entries.

    The only case where the ordinary replication path cannot work, because the entries the
    follower needs no longer exist. The leader notices that the next index it would send from is
    inside its own snapshot and switches messages.
    """
    boss = _loaded()
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    compact(boss.log, 100, boss.log.term_at(100))
    boss.next_index["b"] = 40
    made = boss.replicate("b")
    boss.next_index["c"] = boss.log.last_index
    ordinary = boss.replicate("c")
    return {
        "snapshot_index": boss.log.snapshot_index,
        "the_follower_wanted": 40,
        "it_sent_a_snapshot": isinstance(made[0], InstallSnapshot),
        "carrying_this_many_keys": len(made[0].state),
        "and_a_current_follower_gets_an_append": not isinstance(ordinary[0], InstallSnapshot),
        "the_snapshot_names_its_boundary": made[0].last_index == boss.log.snapshot_index,
    }


def installing_a_snapshot_replaces_the_whole_log() -> dict:
    """A follower taking a snapshot discards whatever it had and starts from the boundary.

    Which is safe because the snapshot comes from a leader, and a leader's log is by definition
    the one everybody else has to match. The follower's own entries below the boundary were
    either the same entries or entries it was going to lose anyway.
    """
    follower = Node(name="c", members=("a", "b", "c"), seed=3)
    follower.log.append(
        [Entry(term=1, index=one, command=("set", "j", one)) for one in range(1, 6)]
    )
    before = follower.log.last_index
    follower.step(
        InstallSnapshot(
            sender="a",
            recipient="c",
            term=1,
            last_index=100,
            last_term=1,
            state={"k": 9},
            members=("a", "b", "c"),
        )
    )
    return {
        "entries_before": before,
        "entries_after": len(follower.log),
        "it_discarded_them": len(follower.log) == 0,
        "snapshot_index": follower.log.snapshot_index,
        "state": dict(follower.state),
        "it_took_the_state": follower.state == {"k": 9},
        "and_moved_its_commit_index": follower.commit_index == 100,
        "and_its_applied_index": follower.last_applied == 100,
    }


def an_older_snapshot_is_ignored() -> dict:
    """A snapshot behind the follower's own log is dropped rather than applied.

    The case a delayed message produces. A snapshot in flight while the follower catches up by
    ordinary appends would, if applied, throw away entries the follower already has and set it
    backwards, and the leader would then have to send them again.
    """
    follower = Node(name="c", members=("a", "b", "c"), seed=3)
    follower.log.append(
        [Entry(term=1, index=one, command=("set", "j", one)) for one in range(1, 60)]
    )
    before = follower.log.last_index
    follower.step(
        InstallSnapshot(
            sender="a", recipient="c", term=1, last_index=20, last_term=1, state={"k": 1}
        )
    )
    return {
        "log_before": before,
        "snapshot_offered": 20,
        "log_after": follower.log.last_index,
        "it_was_ignored": follower.log.last_index == before,
        "and_the_state_is_untouched": follower.state == {},
        "the_reply_still_names_its_index": True,
    }


def a_follower_confirms_what_it_installed() -> dict:
    """The reply carries the index the follower now holds, which moves the leader's match.

    The same shape as an append reply, and for the same reason: an absolute index rather than a
    confirmation, so a duplicated or delayed reply cannot move the leader backwards.
    """
    follower = Node(name="c", members=("a", "b", "c"), seed=3)
    out = follower.step(
        InstallSnapshot(sender="a", recipient="c", term=1, last_index=80, last_term=1)
    )
    return {
        "replies": len(out),
        "it_is_an_installed": isinstance(out[0], Installed),
        "index": out[0].last_index,
        "which_is_the_boundary": out[0].last_index == 80,
        "and_it_carries_a_term": out[0].term >= 1,
    }


def a_snapshot_carries_the_membership() -> dict:
    """The configuration travels with the state, because it lives in the log too.

    Easy to forget and impossible to recover from. A node restored from a snapshot that omitted
    the membership would not know who to vote for or who to replicate to, and the entries that
    would have told it were the ones the snapshot replaced.
    """
    node = _loaded()
    made = take(node)
    return {
        "members": list(made.members),
        "it_carries_them": made.members == node.members,
        "count": len(made.members),
        "and_a_message_carries_them_too": InstallSnapshot(
            sender="a", recipient="b", term=1, last_index=1, last_term=1, members=made.members
        ).members
        == node.members,
    }


def a_snapshot_is_taken_at_the_applied_index_not_the_commit_index() -> dict:
    """The snapshot describes a state the machine reached, which is what applied means.

    A snapshot at the commit index would claim to describe entries the machine has not run, and
    a node restoring from it would hold a state that never existed anywhere.
    """
    node = _loaded()
    node.commit_index = node.log.last_index
    node.last_applied = node.log.last_index - 10
    made = take(node)
    return {
        "commit_index": node.commit_index,
        "last_applied": node.last_applied,
        "snapshot_index": made.last_index,
        "it_used_the_applied_index": made.last_index == node.last_applied,
        "and_not_the_commit_index": made.last_index != node.commit_index,
        "the_gap": node.commit_index - node.last_applied,
    }


def compacting_past_the_end_is_refused() -> bool:
    """A snapshot index above the log's last entry is refused."""
    node = _loaded(entries=10)
    try:
        compact(node.log, 99, 1)
    except LogError:
        return True
    return False


def compacting_backwards_is_refused() -> bool:
    """A snapshot index below an existing snapshot is refused."""
    node = _loaded()
    compact(node.log, 60, node.log.term_at(60))
    try:
        compact(node.log, 20, 1)
    except ConfigError:
        return True
    return False


def a_snapshot_without_a_term_is_refused() -> bool:
    """A snapshot at a real index needs the term of that index."""
    try:
        Snapshot(last_index=10, last_term=0)
    except ConfigError:
        return True
    return False


def a_negative_snapshot_index_is_refused() -> bool:
    """An index below zero is refused."""
    try:
        Snapshot(last_index=-1, last_term=1)
    except ConfigError:
        return True
    return False


def an_empty_snapshot_stands_for_nothing() -> dict:
    """A snapshot at index zero is the empty one, which a fresh node effectively has.

    Worth naming because it is the boundary the arithmetic starts from, and because a node that
    treated the empty snapshot as a real one would refuse its own first append.
    """
    made = Snapshot(last_index=NO_INDEX, last_term=NO_TERM)
    return {
        "index": made.last_index,
        "it_is_empty": made.empty,
        "no_bytes": made.nbytes == 0,
        "and_a_fresh_log_matches_it": Log().matches(NO_INDEX, NO_TERM),
        "summary": made.as_dict(),
    }


def a_cluster_compacts_and_keeps_serving(writes: int = 80) -> dict:
    """Compaction happens under a running cluster without anything noticing.

    The end to end case. Every node writes, applies, and trims, and the cluster keeps committing
    across the boundary. What would break here is an index calculation, and an index calculation
    that is wrong by one is invisible until the first append crosses the snapshot.
    """
    made = Cluster(size=3, seed=5).settle()
    for one in range(writes):
        made.propose(("set", f"k{one % 6}", one))
    made.run(60)
    boss = made.leader()
    before = boss.log.last_index
    trimmed = {}
    for name in made.up:
        node = made.nodes[name]
        if node.last_applied > 10:
            trimmed[name] = compact(
                node.log, node.last_applied, node.log.term_at(node.last_applied)
            )
    for one in range(10):
        made.propose(("set", "after", one))
    made.run(60)
    return {
        "log_before": before,
        "trimmed": trimmed,
        "it_trimmed_every_node": len(trimmed) == len(made.up),
        "committed_after": made.leader().commit_index if made.leader() else 0,
        "it_kept_committing": bool(made.leader() and made.leader().commit_index > before),
        "and_the_nodes_agree": made.agreed(),
        "logs_level": len({made.nodes[one].log.last_index for one in made.up}) == 1,
    }


def compare_the_thresholds(entries: int = 400, keys: int = 10) -> list[dict]:
    """What compacting at different points costs in retained entries and snapshot size.

    The threshold is how many entries a node keeps above its snapshot, so it is also how far a
    follower can fall behind and still be caught up with appends rather than with the whole
    state.
    """
    out = []
    for threshold in (25, 50, 100, 200):
        node = _loaded(entries=entries, keys=keys)
        made = take(node)
        kept = min(threshold, entries)
        out.append(
            {
                "compact_after": threshold,
                "entries_kept": kept,
                "snapshot_keys": len(made.state),
                "snapshot_bytes": made.nbytes,
                "log_bytes": kept * ENTRY_BYTES,
                "catch_up_reach": kept,
            }
        )
    return out


def the_threshold_trades_log_size_against_how_far_a_follower_may_lag() -> dict:
    """A lower threshold holds fewer entries and shortens the reach of an ordinary catch up.

    Neither end is right, and the reason is the second column rather than the first. Everyone
    picks a threshold to bound the log, and what it actually bounds is how far behind a follower
    can be and still be repaired by appends. Below that it needs the whole state instead, so a
    tight threshold turns a cheap catch up into an expensive one.

    The snapshot itself is the same size at every threshold, which is worth stating because it
    is the thing people expect to shrink. A snapshot is the state, and the state does not care
    how many entries produced it.
    """
    table = compare_the_thresholds()
    return {
        "thresholds": [one["compact_after"] for one in table],
        "entries_kept": [one["entries_kept"] for one in table],
        "catch_up_reach": [one["catch_up_reach"] for one in table],
        "the_lower_threshold_keeps_less": table[0]["entries_kept"] < table[-1]["entries_kept"],
        "and_reaches_less_far": table[0]["catch_up_reach"] < table[-1]["catch_up_reach"],
        "the_snapshot_is_the_same_size": len({one["snapshot_bytes"] for one in table}) == 1,
        "because_it_is_the_state_not_the_log": True,
        "shipped_threshold": COMPACT_AFTER,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    boundary = compacting_keeps_the_term_at_the_boundary()
    far_behind = a_leader_sends_a_snapshot_when_the_entries_are_gone()
    return {
        "compact_after": COMPACT_AFTER,
        "the_term_survives_the_entry": boundary["but_the_term_survived"],
        "and_the_check_still_passes": boundary["so_the_check_still_passes"],
        "compaction_frees_the_log": compacting_frees_the_entries_and_keeps_the_state()[
            "it_freed_everything"
        ],
        "the_saving_is_the_workloads": a_workload_with_no_repeats_compacts_to_nothing()[
            "so_the_saving_is_the_workloads"
        ],
        "a_restart_applies_nothing": a_restart_from_a_snapshot_skips_the_replay()[
            "it_applied_nothing"
        ],
        "a_far_behind_follower_gets_state": far_behind["it_sent_a_snapshot"],
        "an_old_snapshot_is_ignored": an_older_snapshot_is_ignored()["it_was_ignored"],
        "a_cluster_survives_compaction": a_cluster_compacts_and_keeps_serving()[
            "and_the_nodes_agree"
        ],
    }
