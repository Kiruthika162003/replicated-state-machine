from __future__ import annotations

import contextlib
from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.node import MAX_BATCH
from rsm.snapshot import KEY_BYTES, compact, take
from rsm.wire import ASSUMED_ENTRY_BYTES, ASSUMED_MESSAGE_BYTES

# A node coming back after being away, and which of the two ways to catch it up.
#
# There are exactly two. Send it the entries it missed, one batch at a time, and let it apply
# them; or send it the state machine as it stands now and let it throw its log away. The first
# costs the entries, the second costs the state, and which is cheaper depends on how long the
# node was away and how much of the state the missed entries touched.
#
# It is not always a choice. A leader that has compacted its log past the point the returning
# node needs cannot send the entries, because it no longer has them, and the snapshot is the
# only path left. So the retention threshold is not only a disk decision, it decides which
# recovery paths exist, and a cluster that compacts aggressively has quietly chosen to send
# snapshots.
#
# What is measured here is the crossover: at what lag the snapshot becomes the cheaper of the
# two, how sharp the crossing is, and how much the workload moves it. A workload that writes the
# same few keys compacts to almost nothing and crosses early; one that writes a new key every
# time never compacts at all and never crosses.

# How many distinct keys the workloads below touch.
NARROW = 4
WIDE = 400


@dataclass(frozen=True)
class Path:
    """One way of catching a node up, and what it costs in messages and bytes."""

    name: str
    entries: int
    keys: int
    messages: int
    nbytes: int

    def __post_init__(self) -> None:
        if self.entries < 0:
            raise ConfigError(f"{self.entries} is not an entry count")
        if self.messages < 0:
            raise ConfigError(f"{self.messages} is not a message count")

    @property
    def per_message(self) -> float:
        """Bytes per message, which is what the transport sees."""
        if self.messages == 0:
            return 0.0
        return round(self.nbytes / self.messages, 1)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "path": self.name,
            "entries": self.entries,
            "keys": self.keys,
            "messages": self.messages,
            "bytes": self.nbytes,
            "per_message": self.per_message,
        }

    def __str__(self) -> str:
        return f"{self.name}: {self.messages} messages, {self.nbytes} bytes"


def by_entries(behind: int) -> Path:
    """Catching up by sending the missed entries, batched."""
    if behind < 0:
        raise ConfigError(f"{behind} is not a lag")
    messages = -(-behind // MAX_BATCH) if behind else 0
    return Path(
        name="entries",
        entries=behind,
        keys=0,
        messages=messages,
        nbytes=messages * ASSUMED_MESSAGE_BYTES + behind * ASSUMED_ENTRY_BYTES,
    )


def by_snapshot(keys: int) -> Path:
    """Catching up by sending the state, which is one message however big it is."""
    if keys < 0:
        raise ConfigError(f"{keys} is not a key count")
    return Path(
        name="snapshot",
        entries=0,
        keys=keys,
        messages=1,
        nbytes=ASSUMED_MESSAGE_BYTES + keys * KEY_BYTES,
    )


def cheaper(behind: int, keys: int) -> Path:
    """Whichever of the two costs fewer bytes, which is what a leader would pick."""
    entries = by_entries(behind)
    snapshot = by_snapshot(keys)
    return snapshot if snapshot.nbytes < entries.nbytes else entries


def crossover(keys: int) -> int:
    """The lag at which the snapshot becomes the cheaper path, for a state of this size.

    Solved by walking rather than by algebra. The entry path has a step in it every time the
    batch fills, so the crossing is not where the two straight lines meet, and an algebraic
    answer would be wrong by up to a batch.
    """
    if keys < 0:
        raise ConfigError(f"{keys} is not a key count")
    snapshot = by_snapshot(keys).nbytes
    for behind in range(100000):
        if by_entries(behind).nbytes >= snapshot:
            return behind
    raise ConfigError("no crossover inside the search")


def _run(keys: int, writes: int, size: int = 3, seed: int = 1) -> tuple[int, int]:
    """Write into a cluster and report how many entries and how many keys resulted."""
    made = Cluster(size=size, seed=seed).settle()
    for one in range(writes):
        with contextlib.suppress(NoLeader):
            made.propose(("set", f"k{one % keys}", one))
        if one % 8 == 0:
            made.run(2)
    made.run(30)
    found = made.leader()
    if found is None:
        raise NoLeader("nothing settled")
    return found.log.last_index, len(take(found).state)


def the_snapshot_wins_once_the_lag_passes_the_state_size() -> dict:
    """The crossing is at about three quarters of the key count, in entries.

    Where the two costs meet. A snapshot is one message carrying the whole state, so it costs
    the state and nothing else. The entries cost their own bytes plus a message header for every
    batch, so they cost slightly more per entry than the entry size suggests.

    That is why the crossing is below the key count rather than at it: an entry is thirty two
    bytes plus its share of the framing and a key is twenty four, so the entries lose the race
    before there are as many of them as there are keys.
    """
    out = {}
    for keys in (40, 400, 4000):
        out[keys] = crossover(keys)
    return {
        "key_counts": sorted(out),
        "crossovers": out,
        "it_is_below_the_key_count": all(out[keys] < keys for keys in out),
        "as_a_share": {keys: round(one / keys, 2) for keys, one in out.items()},
        "and_the_share_is_stable": (
            max(one / keys for keys, one in out.items())
            - min(one / keys for keys, one in out.items())
            < 0.05
        ),
        "entry_bytes": ASSUMED_ENTRY_BYTES,
        "key_bytes": KEY_BYTES,
        "and_an_entry_costs_more_than_a_key": ASSUMED_ENTRY_BYTES > KEY_BYTES,
    }


def a_narrow_workload_crosses_early_and_a_wide_one_never_does() -> dict:
    """Four keys of state against four hundred writes crosses at three entries.

    The workload decides the answer more than the lag does. A cluster whose clients write the
    same four keys over and over holds four keys of state however long it runs, so the snapshot
    is a hundred and sixty bytes forever and the entries lose almost immediately.

    A cluster whose clients write a new key every time holds as many keys as it has entries, so
    the snapshot grows exactly as fast as the log and the crossing never arrives. That is the
    case where compaction saves nothing, which rsm.snapshot measures from the other side.
    """
    narrow_entries, narrow_keys = _run(keys=NARROW, writes=200)
    wide_entries, wide_keys = _run(keys=WIDE, writes=200)
    return {
        "narrow_entries": narrow_entries,
        "narrow_keys": narrow_keys,
        "narrow_crossover": crossover(narrow_keys),
        "it_crosses_almost_at_once": crossover(narrow_keys) < 10,
        "wide_entries": wide_entries,
        "wide_keys": wide_keys,
        "wide_crossover": crossover(wide_keys),
        "and_the_wide_one_crosses_late": crossover(wide_keys) > crossover(narrow_keys) * 10,
        "the_wide_state_grows_with_the_log": wide_keys > narrow_keys * 10,
        "which_is_where_compaction_saves_nothing": True,
    }


def the_crossing_is_a_staircase_rather_than_a_point() -> dict:
    """The entry cost steps up every sixty four entries, so the crossing has a flat part.

    A detail that an algebraic answer gets wrong. The entry path pays a message header once per
    batch, so its cost is a staircase, and near the crossing there is a stretch of lags where
    adding entries does not change the message count and the decision does not move.

    Solving the two straight lines would put the crossing up to a batch away from where it is.
    The walk below finds the real one.
    """
    keys = 400
    snapshot = by_snapshot(keys).nbytes
    steps = []
    last = 0
    for behind in range(1, 800):
        messages = by_entries(behind).messages
        if messages != last:
            steps.append(behind)
            last = messages
    found = crossover(keys)
    straight = round((snapshot - ASSUMED_MESSAGE_BYTES) / ASSUMED_ENTRY_BYTES)
    return {
        "keys": keys,
        "measured_crossover": found,
        "straight_line_answer": straight,
        "they_differ": found != straight,
        "by_this_many_entries": abs(found - straight),
        "batch": MAX_BATCH,
        "steps_at": steps[:6],
        "the_steps_are_a_batch_apart": all(
            steps[one + 1] - steps[one] == MAX_BATCH for one in range(4)
        ),
        "and_the_error_is_under_a_batch": abs(found - straight) < MAX_BATCH,
    }


def compaction_decides_which_path_is_available_at_all() -> dict:
    """A leader that compacted past what the returning node needs has only one path left.

    The part that is not an optimisation. Catching a node up by entries requires the leader to
    still hold them, and compaction is exactly the act of not holding them. So a retention
    threshold is a decision about recovery paths as much as about disk: keep a long tail and
    both paths stay open, keep a short one and every returning node gets a snapshot whether or
    not that is cheaper.

    Measured against a real leader rather than by arithmetic, because the question is whether
    the entry is there and only the log can answer that.
    """
    made = Cluster(size=3, seed=1).settle()
    for one in range(120):
        with contextlib.suppress(NoLeader):
            made.propose(("set", f"k{one % NARROW}", one))
        if one % 8 == 0:
            made.run(2)
    made.run(30)
    found = made.leader()
    before = found.log.first_index
    kept = 20
    boundary = found.log.last_index - kept
    compact(found.log, upto=boundary, term=found.log.term_at(boundary))
    return {
        "last_index": found.log.last_index,
        "first_index_before": before,
        "first_index_after": found.log.first_index,
        "entries_kept": found.log.last_index - found.log.first_index + 1,
        "a_node_ten_behind_can_be_caught_up": found.log.holds(found.log.last_index - 10),
        "and_one_fifty_behind_cannot": not found.log.holds(found.log.last_index - 50),
        "so_the_snapshot_is_the_only_path": True,
        "keys_in_the_snapshot": len(take(found).state),
        "which_is_small_for_this_workload": len(take(found).state) <= NARROW,
    }


def a_negative_lag_is_refused() -> bool:
    """A node cannot be behind by less than nothing."""
    try:
        by_entries(-1)
    except ConfigError:
        return True
    return False


def a_negative_key_count_is_refused() -> bool:
    """A state cannot hold fewer than no keys."""
    try:
        by_snapshot(-1)
    except ConfigError:
        return True
    return False


def a_path_with_negative_messages_is_refused() -> bool:
    """A path that sends fewer than no messages is refused."""
    try:
        Path(name="x", entries=0, keys=0, messages=-1, nbytes=0)
    except ConfigError:
        return True
    return False


def a_node_that_is_current_needs_neither_path() -> dict:
    """Zero entries behind is zero messages, and the snapshot is still one.

    The boundary that decides what a leader does on every heartbeat to a caught up follower. The
    entry path costs nothing, the snapshot path costs a message and the whole state, and a
    leader that compared them the wrong way round would send a snapshot to a node that already
    had everything.
    """
    entries = by_entries(0)
    snapshot = by_snapshot(40)
    return {
        "entries_messages": entries.messages,
        "it_sends_nothing": entries.messages == 0,
        "entries_bytes": entries.nbytes,
        "snapshot_messages": snapshot.messages,
        "and_the_snapshot_still_costs_one": snapshot.messages == 1,
        "the_cheaper_one": cheaper(0, 40).name,
        "and_it_is_the_entries": cheaper(0, 40).name == "entries",
        "per_message_of_nothing": entries.per_message,
        "which_is_zero_rather_than_infinite": entries.per_message == 0.0,
    }


def compare_the_lags() -> list[dict]:
    """Both paths at a range of lags, for a state of four hundred keys."""
    out = []
    for behind in (0, 10, 100, 292, 500, 2000):
        entries = by_entries(behind)
        snapshot = by_snapshot(400)
        out.append(
            {
                "behind": behind,
                "entry messages": entries.messages,
                "entry bytes": entries.nbytes,
                "snapshot bytes": snapshot.nbytes,
                "cheaper": cheaper(behind, 400).name,
            }
        )
    return out


def the_leader_should_choose_and_usually_does_not() -> dict:
    """Only two of six lags favour the snapshot, and the usual rule sends it far more often.

    The rule most implementations use is a threshold on whether the entries still exist, which
    is not the same question as which is cheaper. On this table the snapshot is the better
    choice at two lags out of six and the entry path at four, and a leader deciding by
    availability alone would send a snapshot at every lag past its retention.

    The two rules agree when the retention is set near the crossover and disagree everywhere
    else, which is an argument for setting the retention from the state size rather than from a
    round number of entries.
    """
    table = compare_the_lags()
    favours = [one["behind"] for one in table if one["cheaper"] == "snapshot"]
    return {
        "lags": [one["behind"] for one in table],
        "snapshot_wins_at": favours,
        "entries_win_elsewhere": len(table) - len(favours),
        "the_snapshot_is_the_minority_choice": len(favours) < len(table) / 2,
        "crossover": crossover(400),
        "and_it_sits_inside_the_table": min(favours) >= crossover(400),
        "the_two_rules_agree_only_at_the_crossover": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "batch": MAX_BATCH,
        "entry_bytes": ASSUMED_ENTRY_BYTES,
        "key_bytes": KEY_BYTES,
        "crossover_at_four_hundred_keys": crossover(400),
        "the_crossing_is_below_the_key_count": (
            the_snapshot_wins_once_the_lag_passes_the_state_size()["it_is_below_the_key_count"]
        ),
        "a_narrow_workload_crosses_at_once": (
            a_narrow_workload_crosses_early_and_a_wide_one_never_does()[
                "it_crosses_almost_at_once"
            ]
        ),
        "the_crossing_is_a_staircase": the_crossing_is_a_staircase_rather_than_a_point()[
            "they_differ"
        ],
        "compaction_closes_the_entry_path": (
            compaction_decides_which_path_is_available_at_all()["and_one_fifty_behind_cannot"]
        ),
        "and_the_snapshot_is_the_minority_choice": (
            the_leader_should_choose_and_usually_does_not()[
                "the_snapshot_is_the_minority_choice"
            ]
        ),
    }
