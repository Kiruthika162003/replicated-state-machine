from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.errors import ConfigError, NoLeader
from rsm.keyspace import Federation, Keyspace
from rsm.snapshot import KEY_BYTES

# Moving keys from one group to another, which needs something Raft does not provide.
#
# rsm.keyspace splits the keyspace across independent groups and shows that a write touching two
# of them is not atomic, because two logs have no order between them. Moving a key range is
# exactly such a write: the source group has to stop owning it at the same moment the
# destination starts, and there is no same moment.
#
# So a move is done in phases, chosen so that no moment has two owners. Freeze the range at the
# source, which makes it unavailable; copy the state; hand ownership over; unfreeze at the
# destination. Every phase is a write inside one group, and the sequence supplies the ordering
# the groups do not have between them.
#
# The cost is the freeze. Between the first phase and the last the range answers nothing, and
# the measurements are mostly about how long that is and what it depends on. The alternative,
# serving from both sides during the copy, is what the phases exist to prevent, and it is
# measured too, by doing it wrong on purpose.

# The phases a move passes through.
STEADY = "steady"
FROZEN = "frozen"
COPYING = "copying"
HANDED = "handed"
PHASES = (STEADY, FROZEN, COPYING, HANDED)

# How many keys a range holds in the measurements.
RANGE = 40

# How many bytes a key costs to copy.
COPY_BYTES = KEY_BYTES


@dataclass
class Move:
    """One range moving from one group to another, and where it has got to."""

    keys: tuple[str, ...]
    source: int
    destination: int
    phase: str = STEADY
    frozen_at: int = 0
    handed_at: int = 0

    def __post_init__(self) -> None:
        if not self.keys:
            raise ConfigError("a move needs keys")
        if self.source == self.destination:
            raise ConfigError(f"group {self.source} cannot move a range to itself")
        if self.phase not in PHASES:
            raise ConfigError(f"{self.phase} is not one of {list(PHASES)}")

    @property
    def owner(self) -> int:
        """Which group owns the range right now, which is never both."""
        return self.destination if self.phase == HANDED else self.source

    @property
    def serving(self) -> bool:
        """Whether the range answers anything in this phase."""
        return self.phase in (STEADY, HANDED)

    @property
    def nbytes(self) -> int:
        """What the copy costs."""
        return len(self.keys) * COPY_BYTES

    def advance(self, now: int) -> str:
        """Move to the next phase, recording when the interesting ones happened."""
        order = list(PHASES)
        at = order.index(self.phase)
        if at + 1 >= len(order):
            raise ConfigError("the move has finished")
        self.phase = order[at + 1]
        if self.phase == FROZEN:
            self.frozen_at = now
        if self.phase == HANDED:
            self.handed_at = now
        return self.phase

    @property
    def unavailable_for(self) -> int:
        """How long the range answered nothing."""
        if not self.handed_at:
            return 0
        return self.handed_at - self.frozen_at

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "keys": len(self.keys),
            "source": self.source,
            "destination": self.destination,
            "phase": self.phase,
            "owner": self.owner,
            "serving": self.serving,
            "bytes": self.nbytes,
            "unavailable_for": self.unavailable_for,
        }


@dataclass
class Attempt:
    """What a run of writes saw while a range was moving."""

    name: str
    attempted: int = 0
    served: int = 0
    refused: int = 0
    owners: list[int] = field(default_factory=list)
    two_owners: int = 0

    @property
    def availability(self) -> float:
        """The share of writes to the moving range that were answered."""
        if self.attempted == 0:
            return 0.0
        return round(self.served / self.attempted, 3)

    def __bool__(self) -> bool:
        """A run is correct if the range never had two owners at once."""
        return self.two_owners == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "run": self.name,
            "attempted": self.attempted,
            "served": self.served,
            "refused": self.refused,
            "availability": self.availability,
            "two_owners": self.two_owners,
            "safe": bool(self),
        }


def _range(space: Keyspace, source: int, count: int = RANGE) -> tuple[str, ...]:
    """A set of keys that all live in one group, which is what a range is."""
    out = []
    one = 0
    while len(out) < count and one < count * 100:
        key = f"k{one}"
        if space.group_of(key) == source:
            out.append(key)
        one += 1
    if not out:
        raise ConfigError(f"group {source} owns none of the keys tried")
    return tuple(out)


def run_move(
    name: str,
    copy_ticks: int = 20,
    writes: int = 30,
    every: int = 4,
    unsafe: bool = False,
) -> tuple[Attempt, Move]:
    """Move a range while clients write to it, either in phases or by serving from both sides.

    The unsafe version is not a strawman. Serving the old owner during the copy is the obvious
    optimisation and it is what anybody writes first, because the freeze is the only part of the
    move that a client can see.
    """
    if writes < 1:
        raise ConfigError(f"{writes} is not a write count")
    space = Keyspace(groups=4)
    fed = Federation(keyspace=space)
    keys = _range(space, source=0)
    move = Move(keys=keys, source=0, destination=1)
    out = Attempt(name=name)
    for tick in range(1, writes * every + 1):
        if tick == every * 2:
            move.advance(tick)
        if tick == every * 3:
            move.advance(tick)
        if tick == every * 3 + copy_ticks:
            move.advance(tick)
        if tick % every == 0:
            out.attempted += 1
            owners = _owners(move, unsafe=unsafe)
            out.owners.append(len(owners))
            if len(owners) > 1:
                out.two_owners += 1
            if not owners:
                out.refused += 1
            else:
                with contextlib.suppress(NoLeader):
                    fed.clusters[owners[0]].propose(("set", keys[0], tick))
                    out.served += 1
        fed.tick()
    return out, move


def _owners(move: Move, unsafe: bool) -> list[int]:
    """Which groups would answer for the range in this phase.

    The safe rule is the move's own: one owner, and nobody during the freeze. The unsafe rule
    keeps the source serving while the copy runs, so during the copy phase the destination is
    building state that the source is still changing.
    """
    if unsafe and move.phase in (FROZEN, COPYING):
        return [move.source, move.destination] if move.phase == COPYING else [move.source]
    return [move.owner] if move.serving else []


def the_phases_cost_availability_and_buy_a_single_owner() -> dict:
    """Eighty percent availability with one owner throughout, against a hundred with two.

    The trade the phases make. Freezing the range refuses six writes out of thirty and
    guarantees that at no moment do two groups both answer for the same key. Serving from both
    sides during the copy answers everything and has five moments where the source is still
    taking writes the destination's copy will not contain.

    The unsafe version is not a strawman, it is the obvious optimisation: the freeze is the only
    part of the move a client can see, so it is the part somebody removes. What it removes is
    the only thing supplying an order between the two groups.
    """
    safe, _ = run_move("phased")
    unsafe, _ = run_move("both sides", unsafe=True)
    return {
        "safe_availability": safe.availability,
        "unsafe_availability": unsafe.availability,
        "the_unsafe_one_answers_more": unsafe.availability > safe.availability,
        "by_this_share": round(unsafe.availability - safe.availability, 3),
        "safe_two_owners": safe.two_owners,
        "unsafe_two_owners": unsafe.two_owners,
        "and_it_has_two_owners_sometimes": unsafe.two_owners > 0,
        "the_phased_one_never_does": safe.two_owners == 0,
        "safe_is_correct": bool(safe),
        "and_the_other_is_not": not bool(unsafe),
    }


def the_freeze_lasts_as_long_as_the_copy() -> dict:
    """Doubling the copy time doubles the window where the range answers nothing.

    Where the cost comes from and what to do about it. The range is unavailable from the freeze
    until the hand over and everything in between is copying, so the downtime is the copy.

    Which says the way to shorten a move is to move less. That is the argument for many small
    ranges over few large ones, and the same argument rsm.keyspace made about balance from the
    other direction.
    """
    out = {}
    for copying in (4, 12, 24, 48):
        made, move = run_move(f"copy {copying}", copy_ticks=copying)
        out[copying] = {"unavailable": move.unavailable_for, "availability": made.availability}
    return {
        "copy_times": sorted(out),
        "unavailable_for": {one: made["unavailable"] for one, made in out.items()},
        "it_tracks_the_copy": out[48]["unavailable"] > out[4]["unavailable"],
        "availability": {one: made["availability"] for one, made in out.items()},
        "and_availability_falls_with_it": out[48]["availability"] < out[4]["availability"],
        "the_quickest": out[4]["availability"],
        "the_slowest": out[48]["availability"],
        "so_the_way_to_shorten_a_move_is_to_move_less": True,
    }


def the_range_has_exactly_one_owner_in_every_phase() -> dict:
    """Steady and handed have one owner, frozen and copying have none, and never two.

    The property the phases exist for, checked against every phase rather than against a run. A
    run only visits the phases it happens to reach; the table visits all four.

    Nobody owning it is a fine answer and two owning it is not. An unavailable range is a
    refusal a client can handle, and two owners is two clients told different things about the
    same key, which is what the whole package has been about.
    """
    made = Move(keys=("a", "b"), source=0, destination=1)
    out = {}
    for phase in PHASES:
        made.phase = phase
        out[phase] = {"owner": made.owner, "serving": made.serving}
    return {
        "phases": list(PHASES),
        "owners": {phase: one["owner"] for phase, one in out.items()},
        "serving": {phase: one["serving"] for phase, one in out.items()},
        "the_steady_phase_serves": out[STEADY]["serving"],
        "the_handed_phase_serves": out[HANDED]["serving"],
        "and_the_middle_two_do_not": not out[FROZEN]["serving"] and not out[COPYING]["serving"],
        "ownership_moves_at_the_hand_over": out[COPYING]["owner"] != out[HANDED]["owner"],
        "and_never_before": out[FROZEN]["owner"] == out[STEADY]["owner"],
    }


def a_move_to_the_same_group_is_refused() -> bool:
    """A range cannot be moved to where it already is."""
    try:
        Move(keys=("a",), source=1, destination=1)
    except ConfigError:
        return True
    return False


def a_move_of_no_keys_is_refused() -> bool:
    """A move of nothing is refused."""
    try:
        Move(keys=(), source=0, destination=1)
    except ConfigError:
        return True
    return False


def an_unknown_phase_is_refused() -> bool:
    """There are four phases and anything else is a typo."""
    try:
        Move(keys=("a",), source=0, destination=1, phase="halfway")
    except ConfigError:
        return True
    return False


def advancing_past_the_last_phase_is_refused() -> bool:
    """A finished move has nowhere to go."""
    made = Move(keys=("a",), source=0, destination=1, phase=HANDED)
    try:
        made.advance(1)
    except ConfigError:
        return True
    return False


def a_run_with_no_writes_is_refused() -> bool:
    """A move nobody writes to measures nothing about availability."""
    try:
        run_move("x", writes=0)
    except ConfigError:
        return True
    return False


def compare_the_strategies() -> list[dict]:
    """The phased move and the both sides move, at two copy lengths."""
    out = []
    for copying in (8, 32):
        for unsafe in (False, True):
            made, move = run_move(
                f"{'both sides' if unsafe else 'phased'}, copy {copying}",
                copy_ticks=copying,
                unsafe=unsafe,
            )
            out.append({**made.as_dict(), "copy": copying, "bytes": move.nbytes})
    return out


def only_the_phased_move_is_safe_at_any_copy_length() -> dict:
    """Both phased rows are safe and both of the others are not, however long the copy is.

    The table has no crossover in it. The copy length changes how much availability the phased
    move gives up and changes nothing about whether either is correct. There is no copy quick
    enough to make serving from both sides safe, because the problem is not how long the window
    lasts but that it exists.
    """
    table = compare_the_strategies()
    phased = [one for one in table if one["run"].startswith("phased")]
    both = [one for one in table if one["run"].startswith("both")]
    return {
        "rows": len(table),
        "phased_safe": [one["safe"] for one in phased],
        "both_sides_safe": [one["safe"] for one in both],
        "every_phased_row_is_safe": all(one["safe"] for one in phased),
        "and_no_unsafe_row_is": not any(one["safe"] for one in both),
        "phased_availability": [one["availability"] for one in phased],
        "a_longer_copy_costs_availability": phased[0]["availability"]
        >= phased[1]["availability"],
        "and_never_changes_the_safety": len({one["safe"] for one in phased}) == 1,
        "bytes": {one["run"]: one["bytes"] for one in table},
    }


def summarise() -> dict:
    """The findings in one mapping."""
    trade = the_phases_cost_availability_and_buy_a_single_owner()
    return {
        "phases": list(PHASES),
        "range": RANGE,
        "the_phased_move_is_safe": trade["safe_is_correct"],
        "the_both_sides_move_is_not": trade["and_the_other_is_not"],
        "the_phases_cost_availability": trade["by_this_share"],
        "the_freeze_tracks_the_copy": the_freeze_lasts_as_long_as_the_copy()[
            "it_tracks_the_copy"
        ],
        "so_move_less": the_freeze_lasts_as_long_as_the_copy()[
            "so_the_way_to_shorten_a_move_is_to_move_less"
        ],
        "one_owner_in_every_phase": the_range_has_exactly_one_owner_in_every_phase()[
            "and_the_middle_two_do_not"
        ],
        "and_no_copy_length_makes_the_unsafe_one_safe": (
            only_the_phased_move_is_safe_at_any_copy_length()["and_no_unsafe_row_is"]
        ),
    }
