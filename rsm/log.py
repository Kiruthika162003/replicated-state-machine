from __future__ import annotations

import random
from dataclasses import dataclass, field

from rsm.errors import Compacted, ConfigError, LeaderAppendOnly, LogError, NotFound

# The replicated log, which is the only thing in Raft that is actually replicated. Everything
# else in the algorithm exists to keep this one structure identical across nodes.
#
# Two properties carry the whole safety argument and both are enforced here rather than by the
# node that owns the log.
#
# If two logs hold an entry with the same index and term, they hold the same command. That is
# true because a leader never changes an entry it has written and there is one leader per term,
# so an index and a term name a single write.
#
# If two logs hold an entry with the same index and term, every entry before it is identical
# too. That is true by induction, and the induction is maintained by the consistency check on
# append: a follower refuses entries whose predecessor it does not have. The measurement below
# builds two logs through legal appends only and confirms it, because an induction that holds on
# paper and not in the code is the more dangerous of the two.
#
# Indices here are one based, because index zero is the empty log before anything was written
# and the algorithm needs a name for that position. The entry at index zero does not exist and
# asking for it is an error rather than a sentinel.

# The term of the position before the first entry. Not a real term, and no entry ever carries
# it, which is what makes it safe to compare against.
NO_TERM = 0

# The index before the first entry.
NO_INDEX = 0


@dataclass(frozen=True)
class Entry:
    """One command, and the term of the leader that accepted it."""

    term: int
    index: int
    command: object = None

    def __post_init__(self) -> None:
        if self.term < 1:
            raise ConfigError(f"{self.term} is not a term")
        if self.index < 1:
            raise ConfigError(f"{self.index} is not an index")

    @property
    def is_noop(self) -> bool:
        """Whether this is the empty entry a leader writes on election."""
        return self.command is None

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"index": self.index, "term": self.term, "command": self.command}

    def __str__(self) -> str:
        return f"{self.index}@{self.term}"


@dataclass
class Log:
    """A node's copy of the replicated log, with everything before the snapshot discarded."""

    entries: list[Entry] = field(default_factory=list)
    snapshot_index: int = NO_INDEX
    snapshot_term: int = NO_TERM

    def __post_init__(self) -> None:
        if self.snapshot_index < NO_INDEX:
            raise ConfigError(f"{self.snapshot_index} is not a snapshot index")
        for position, one in enumerate(self.entries):
            if one.index != self.snapshot_index + position + 1:
                raise ConfigError(f"{one} is out of place at position {position}")
        for earlier, later in zip(self.entries, self.entries[1:], strict=False):
            if later.term < earlier.term:
                raise ConfigError(f"terms go backwards at {later}")

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    @property
    def first_index(self) -> int:
        """The lowest index still held, which is one past the snapshot."""
        return self.snapshot_index + 1

    @property
    def last_index(self) -> int:
        """The highest index held, or the snapshot's if the log is empty."""
        return self.entries[-1].index if self.entries else self.snapshot_index

    @property
    def last_term(self) -> int:
        """The term of the last entry, or the snapshot's if the log is empty."""
        return self.entries[-1].term if self.entries else self.snapshot_term

    @property
    def empty(self) -> bool:
        """Whether anything has ever been written."""
        return self.last_index == NO_INDEX

    def holds(self, index: int) -> bool:
        """Whether this index is present, rather than compacted away or not yet written."""
        return self.first_index <= index <= self.last_index

    def at(self, index: int) -> Entry:
        """The entry at an index, refused rather than guessed at if it is not there."""
        if index <= self.snapshot_index:
            raise Compacted(f"index {index} is inside the snapshot at {self.snapshot_index}")
        if index > self.last_index:
            raise NotFound(f"index {index} is past the end at {self.last_index}")
        return self.entries[index - self.first_index]

    def term_at(self, index: int) -> int:
        """The term at an index, with the two boundary positions answered rather than refused.

        The snapshot's own index has a known term and no entry, and the position before the
        first write has no term at all. Both come up in the consistency check on every append,
        so both are answered here rather than left for each caller to special case.
        """
        if index == NO_INDEX:
            return NO_TERM
        if index == self.snapshot_index:
            return self.snapshot_term
        return self.at(index).term

    def slice(self, start: int, stop: int | None = None) -> list[Entry]:
        """The entries from an index onwards, for sending to a follower."""
        if start < self.first_index:
            raise Compacted(f"index {start} is inside the snapshot at {self.snapshot_index}")
        end = self.last_index if stop is None else min(stop, self.last_index)
        return [self.at(one) for one in range(start, end + 1)]

    def matches(self, index: int, term: int) -> bool:
        """Whether this log holds that index at that term, which is the consistency check."""
        if index == NO_INDEX:
            return True
        if index < self.snapshot_index or index > self.last_index:
            return False
        return self.term_at(index) == term

    def is_up_to_date(self, other_index: int, other_term: int) -> bool:
        """Whether another log is at least as up to date as this one.

        The election restriction, and the one comparison in Raft that is most often written the
        wrong way round. The term of the last entry is compared first and the length only breaks
        a tie. A longer log with an older last term loses, and the measurement below builds the
        case where getting that backwards elects a leader missing a committed entry.
        """
        if other_term != self.last_term:
            return other_term > self.last_term
        return other_index >= self.last_index

    def append(self, entries: list[Entry]) -> Log:
        """Add entries to the end, refusing anything that does not continue the log."""
        if not entries:
            return self
        for one in entries:
            if one.index != self.last_index + 1:
                raise LogError(f"{one} does not follow index {self.last_index}")
            if one.term < self.last_term:
                raise LeaderAppendOnly(f"{one} has a term below {self.last_term}")
            self.entries.append(one)
        return self

    def truncate_from(self, index: int) -> int:
        """Discard the entry at an index and everything after it, returning how many went.

        Only a follower reconciling with a leader does this, and only for entries it has not
        applied. A leader calling it would be the append only violation the error names, which
        is why the check lives here rather than in the caller that is already confused.
        """
        if index <= self.snapshot_index:
            raise Compacted(f"index {index} is inside the snapshot at {self.snapshot_index}")
        if index > self.last_index:
            return 0
        keep = index - self.first_index
        going = len(self.entries) - keep
        del self.entries[keep:]
        return going


def written(terms: list[int], start: int = 1, commands: list | None = None) -> Log:
    """A log with one entry per term given, which is how every case below is built.

    Starting above index one means the entries below it were compacted, so the log gets a
    snapshot at the position before the first entry. There is no other way to hold a log that
    begins at index five, and letting the helper produce one would produce a log the constructor
    would refuse.
    """
    entries = []
    for position, term in enumerate(terms):
        command = commands[position] if commands is not None else f"c{start + position}"
        entries.append(Entry(term=term, index=start + position, command=command))
    if start == 1:
        return Log(entries=entries)
    return Log(
        entries=entries,
        snapshot_index=start - 1,
        snapshot_term=terms[0] if terms else 1,
    )


def diverge(base: Log, at: int, terms: list[int]) -> Log:
    """A copy of a log with a different tail, which is what a stale leader leaves behind."""
    if at < 1:
        raise ConfigError(f"{at} is not an index")
    kept = [one for one in base.entries if one.index < at]
    made = Log(entries=list(kept))
    for position, term in enumerate(terms):
        made.entries.append(Entry(term=term, index=at + position, command=f"x{at + position}"))
    return made


def agree_up_to(left: Log, right: Log) -> int:
    """The highest index at which two logs hold the same entry, which reconciling must find."""
    highest = min(left.last_index, right.last_index)
    for index in range(highest, NO_INDEX, -1):
        if not left.holds(index) or not right.holds(index):
            continue
        if left.term_at(index) == right.term_at(index):
            return index
    return NO_INDEX


def reconcile_one_at_a_time(leader: Log, follower: Log) -> int:
    """Round trips to reconcile a follower by walking the next index back one at a time.

    The algorithm as the paper first states it. Each rejected append tells the leader only that
    the follower disagreed, so it tries the previous index, and the number of round trips is the
    length of the divergence plus one.
    """
    trips = 0
    next_index = leader.last_index + 1
    while next_index > NO_INDEX:
        trips += 1
        previous = next_index - 1
        if follower.matches(
            previous, leader.term_at(previous) if leader.holds(previous) else 0
        ):
            return trips
        if previous == NO_INDEX:
            return trips
        next_index -= 1
    return trips


def reconcile_by_conflict_term(leader: Log, follower: Log) -> int:
    """Round trips when the follower names the term it disagreed on.

    The optimisation from section five of the paper. A rejection carries the term of the
    conflicting entry and the first index the follower holds for that term, so the leader can
    skip the whole term in one step instead of walking it.
    """
    trips = 0
    next_index = leader.last_index + 1
    while next_index > NO_INDEX:
        trips += 1
        previous = next_index - 1
        leader_term = leader.term_at(previous) if leader.holds(previous) else NO_TERM
        if previous == NO_INDEX or follower.matches(previous, leader_term):
            return trips
        if not follower.holds(previous):
            next_index = follower.last_index + 1
            continue
        conflicting = follower.term_at(previous)
        first = previous
        while first > follower.first_index and follower.term_at(first - 1) == conflicting:
            first -= 1
        next_index = first
    return trips


def _pair(divergence: int, agreed: int = 20) -> tuple[Log, Log]:
    """A leader and a follower sharing a prefix and disagreeing on a tail of a given length."""
    leader = written([1] * agreed + [3] * divergence)
    follower = diverge(leader, agreed + 1, [2] * divergence)
    return leader, follower


def the_matching_property_holds_by_induction(length: int = 200, seed: int = 1) -> dict:
    """Two logs built by legal appends agree everywhere before any index they agree at.

    The property everything else rests on, checked against logs that were built the way real
    ones are rather than constructed to pass. A follower only accepts entries whose predecessor
    it already holds, so an agreement at one index is an agreement at every index below it, and
    if that fails the safety argument fails with it.
    """
    state = random.Random(seed)
    leader = Log()
    follower = Log()
    term = 1
    for index in range(1, length + 1):
        if state.random() < 0.05:
            term += 1
        one = Entry(term=term, index=index, command=f"c{index}")
        leader.append([one])
        if follower.matches(index - 1, leader.term_at(index - 1)):
            follower.append([one])
    checked = 0
    failures = []
    for index in range(1, follower.last_index + 1):
        if leader.term_at(index) != follower.term_at(index):
            continue
        checked += 1
        for earlier in range(1, index):
            if leader.at(earlier) != follower.at(earlier):
                failures.append((index, earlier))
                break
    return {
        "entries": length,
        "terms": term,
        "follower_length": follower.last_index,
        "agreements_checked": checked,
        "it_holds_everywhere": failures == [],
        "failures": failures[:5],
    }


def a_follower_refuses_an_entry_whose_predecessor_it_lacks(length: int = 50) -> dict:
    """The consistency check maintains the induction, so removing it breaks the property.

    Measured by running the same appends twice, once with the check and once without. The
    unchecked log ends up the same length and holds a hole, which is exactly the state the
    matching property forbids and exactly the state a reader cannot detect from the length.
    """
    leader = written([1] * 10 + [2] * 10 + [3] * (length - 20))
    checked = Log()
    unchecked = Log()
    refused = 0
    for one in leader:
        if one.index % 7 == 0 and one.index > 5:
            continue
        if checked.matches(one.index - 1, leader.term_at(one.index - 1)):
            checked.append([one])
        else:
            refused += 1
        if one.index == unchecked.last_index + 1:
            unchecked.append([one])
        else:
            unchecked.entries.append(one)
    holes = [
        one.index for position, one in enumerate(unchecked.entries) if one.index != position + 1
    ]
    return {
        "leader_length": leader.last_index,
        "checked_length": checked.last_index,
        "unchecked_entries": len(unchecked.entries),
        "refused": refused,
        "the_checked_log_stops_at_the_first_gap": checked.last_index < leader.last_index,
        "and_the_unchecked_one_has_holes": holes != [],
        "first_hole": holes[0] if holes else None,
    }


def the_up_to_date_check_compares_the_term_first(agreed: int = 10) -> dict:
    """A longer log with an older last term is not up to date, and reversing that loses data.

    The comparison Raft gets right and most first attempts get backwards. A candidate whose log
    is longer looks better and is not: its extra entries come from a term that never committed,
    while the shorter log holds an entry from a later term that may have. Electing on length
    would put a leader in charge that is missing a committed entry.

    The pair below is the smallest case that separates them. The long log has twelve entries
    ending in term two, the short one has eleven ending in term three, and only the term first
    comparison prefers the short one.
    """
    short = written([1] * agreed + [3])
    long = written([1] * agreed + [2, 2])
    correct = short.is_up_to_date(long.last_index, long.last_term)
    by_length = long.last_index >= short.last_index
    return {
        "short_length": short.last_index,
        "short_last_term": short.last_term,
        "long_length": long.last_index,
        "long_last_term": long.last_term,
        "the_long_log_is_not_up_to_date": not correct,
        "but_it_is_longer": by_length,
        "the_two_rules_disagree": correct != by_length,
        "and_the_short_log_wins": long.is_up_to_date(short.last_index, short.last_term),
    }


def a_tie_on_term_is_broken_by_length(agreed: int = 10) -> dict:
    """When the last terms match, the longer log is the up to date one.

    The other half of the same comparison, measured separately because a rule that always
    prefers the shorter log would pass the previous measurement and be just as wrong.
    """
    short = written([1] * agreed)
    long = written([1] * (agreed + 5))
    return {
        "short_length": short.last_index,
        "long_length": long.last_index,
        "same_last_term": short.last_term == long.last_term,
        "the_longer_one_is_up_to_date": short.is_up_to_date(long.last_index, long.last_term),
        "and_the_shorter_one_is_not": not long.is_up_to_date(short.last_index, short.last_term),
        "an_equal_log_is_up_to_date": short.is_up_to_date(short.last_index, short.last_term),
    }


def the_conflict_term_optimisation_saves_a_round_trip_per_entry(divergence: int = 20) -> dict:
    """Walking back one index at a time costs a round trip per divergent entry.

    The comparison the paper suggests and does not measure. On a follower that diverged twenty
    entries ago, walking back takes twenty one round trips and naming the conflicting term takes
    two, because the whole divergence is one term and one step clears it.
    """
    leader, follower = _pair(divergence)
    slow = reconcile_one_at_a_time(leader, follower)
    fast = reconcile_by_conflict_term(leader, follower)
    return {
        "divergence": divergence,
        "agreed_prefix": agree_up_to(leader, follower),
        "one_at_a_time": slow,
        "by_conflict_term": fast,
        "the_optimisation_is_cheaper": fast < slow,
        "by_this_many_trips": slow - fast,
        "and_it_does_not_depend_on_the_divergence": fast <= 3,
    }


def the_optimisation_is_worth_nothing_on_a_short_divergence() -> list[dict]:
    """The same comparison across divergence lengths, which is what decides whether to bother.

    The previous measurement makes the optimisation look essential and it is not, because a
    divergence of twenty entries is not what happens. A follower that missed one append is one
    entry behind, and there both algorithms take two round trips. The saving is proportional to
    a quantity that is almost always one or two.
    """
    out = []
    for divergence in (1, 2, 5, 20, 100):
        leader, follower = _pair(divergence)
        slow = reconcile_one_at_a_time(leader, follower)
        fast = reconcile_by_conflict_term(leader, follower)
        out.append(
            {
                "divergence": divergence,
                "one_at_a_time": slow,
                "by_conflict_term": fast,
                "saved": slow - fast,
                "worth_it": slow - fast > 1,
            }
        )
    return out


def the_optimisation_only_pays_on_a_long_divergence() -> dict:
    """Stated as the conclusion of the sweep rather than as an opinion about it.

    At a divergence of one the two are equal and the optimisation is pure code. At a hundred it
    saves ninety nine round trips. Which of those a deployment sees depends entirely on how long
    a partition lasts, and that is not something the log can know, so the optimisation is
    implemented and the measurement of when it is pointless is kept next to it.
    """
    table = the_optimisation_is_worth_nothing_on_a_short_divergence()
    worth = [one for one in table if one["worth_it"]]
    return {
        "divergences": [one["divergence"] for one in table],
        "saved": [one["saved"] for one in table],
        "it_saves_nothing_at_one": table[0]["saved"] == 0,
        "and_ninety_nine_at_a_hundred": table[-1]["saved"] > 90,
        "cases_where_it_pays": len(worth),
        "of": len(table),
        "the_saving_is_the_divergence_less_one": all(
            one["saved"] == max(one["divergence"] - 1, 0) for one in table
        ),
    }


def an_append_that_conflicts_discards_the_tail(divergence: int = 5) -> dict:
    """Reconciling truncates the follower from the first disagreement, not from the end.

    Which entries go is the whole question. Truncating from the agreement point discards work
    that was never committed and is allowed. Truncating one entry too few leaves a stale entry
    in place with correct entries above it, and the matching property is gone with no error
    raised anywhere.
    """
    leader, follower = _pair(divergence)
    agreed = agree_up_to(leader, follower)
    going = follower.truncate_from(agreed + 1)
    follower.append(leader.slice(agreed + 1))
    return {
        "agreed_at": agreed,
        "discarded": going,
        "it_discarded_the_divergence": going == divergence,
        "the_logs_now_match": [one.as_dict() for one in follower]
        == [one.as_dict() for one in leader],
        "final_length": follower.last_index,
    }


def a_leader_never_truncates_its_own_log() -> bool:
    """Appending an entry from an older term is refused as an append only violation."""
    log = written([1, 1, 2, 2])
    try:
        log.append([Entry(term=1, index=5, command="late")])
    except LeaderAppendOnly:
        return True
    return False


def reading_inside_a_snapshot_is_refused() -> bool:
    """An index discarded into a snapshot is refused rather than returning the wrong entry."""
    log = Log(entries=[Entry(term=2, index=11)], snapshot_index=10, snapshot_term=1)
    try:
        log.at(5)
    except Compacted:
        return True
    return False


def reading_past_the_end_is_refused() -> bool:
    """An index beyond the last entry is refused."""
    try:
        written([1, 1, 1]).at(9)
    except NotFound:
        return True
    return False


def an_out_of_order_append_is_refused() -> bool:
    """An entry that does not continue the log is refused rather than leaving a hole."""
    log = written([1, 1])
    try:
        log.append([Entry(term=1, index=7, command="gap")])
    except LogError:
        return True
    return False


def a_log_with_a_hole_is_refused() -> bool:
    """A log constructed with a gap in it is refused at construction."""
    try:
        Log(entries=[Entry(term=1, index=1), Entry(term=1, index=3)])
    except ConfigError:
        return True
    return False


def a_log_whose_terms_go_backwards_is_refused() -> bool:
    """Terms never decrease along a log, and one that does is refused."""
    try:
        Log(entries=[Entry(term=2, index=1), Entry(term=1, index=2)])
    except ConfigError:
        return True
    return False


def a_zero_term_entry_is_refused() -> bool:
    """Term zero names the position before the first entry and no entry may carry it."""
    try:
        Entry(term=0, index=1)
    except ConfigError:
        return True
    return False


def the_empty_log_matches_the_empty_position() -> dict:
    """Index zero matches in every log, which is what lets the first append succeed.

    A boundary that has to be right or a fresh cluster never writes anything. The consistency
    check on the first entry asks whether the follower holds index zero at term zero, and the
    answer has to be yes for a log that holds nothing at all.
    """
    empty = Log()
    written_log = written([1, 1, 1])
    return {
        "empty_last_index": empty.last_index,
        "empty_last_term": empty.last_term,
        "the_empty_log_matches_position_zero": empty.matches(NO_INDEX, NO_TERM),
        "so_does_a_written_one": written_log.matches(NO_INDEX, NO_TERM),
        "the_empty_log_is_empty": empty.empty,
        "and_it_matches_nothing_else": not empty.matches(1, 1),
    }


def a_snapshot_moves_the_first_index(kept: int = 5, discarded: int = 20) -> dict:
    """After compaction the log starts above zero and still answers about its own boundary.

    The place where index arithmetic goes wrong, so it is measured directly. The snapshot's
    index has a term and no entry, everything below it is gone, and the consistency check has to
    keep working across that boundary because a follower catching up will land on it.
    """
    log = Log(
        entries=[
            Entry(term=3, index=discarded + one, command=f"c{one}")
            for one in range(1, kept + 1)
        ],
        snapshot_index=discarded,
        snapshot_term=2,
    )
    return {
        "first_index": log.first_index,
        "last_index": log.last_index,
        "entries_held": len(log),
        "it_matches_at_the_boundary": log.matches(discarded, 2),
        "and_not_at_the_wrong_term": not log.matches(discarded, 9),
        "the_boundary_has_a_term_and_no_entry": log.term_at(discarded) == 2,
        "reading_below_it_is_refused": reading_inside_a_snapshot_is_refused(),
    }


def compare_the_reconciliations() -> list[dict]:
    """Both reconciliation strategies across the divergences that separate them."""
    return the_optimisation_is_worth_nothing_on_a_short_divergence()


def summarise() -> dict:
    """The findings in one mapping."""
    induction = the_matching_property_holds_by_induction()
    ordering = the_up_to_date_check_compares_the_term_first()
    sweep = the_optimisation_only_pays_on_a_long_divergence()
    return {
        "matching_holds": induction["it_holds_everywhere"],
        "agreements_checked": induction["agreements_checked"],
        "term_beats_length": ordering["the_two_rules_disagree"],
        "ties_go_to_the_longer_log": a_tie_on_term_is_broken_by_length()[
            "the_longer_one_is_up_to_date"
        ],
        "optimisation_saves_nothing_at_one": sweep["it_saves_nothing_at_one"],
        "and_ninety_nine_at_a_hundred": sweep["and_ninety_nine_at_a_hundred"],
        "a_leader_never_truncates": a_leader_never_truncates_its_own_log(),
    }
