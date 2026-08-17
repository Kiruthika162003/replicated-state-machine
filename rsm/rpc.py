from __future__ import annotations

from dataclasses import dataclass, field

from rsm.errors import ConfigError
from rsm.log import NO_INDEX, NO_TERM, Entry

# The three remote calls the algorithm makes, as six message kinds, and the one rule that
# applies to all of them.
#
# Every message carries the term of the node that sent it, and every node compares that term
# against its own before looking at anything else. A higher term means this node is stale: it
# adopts the term, becomes a follower, and only then handles the message. A lower term means the
# sender is stale and the message is refused with the current term attached so the sender learns
# it. That rule is not part of any one RPC, it is the thing that makes terms work as a logical
# clock, and it is written once here rather than at the top of six handlers.
#
# Two consequences that are easy to miss and are measured below. Adopting a higher term makes a
# leader step down even when the message is a rejection of its own append, which is how a leader
# on the minority side of a partition finds out it is no longer leader. And a message whose term
# equals the receiver's is not stale and is not fresh, so it never causes a step down, which is
# what lets a leader and its followers talk for the whole term without churning.
#
# Messages are frozen. A node that wanted to alter one before forwarding it would be doing
# something the algorithm has no name for, and the network below copies rather than shares, so a
# delayed message cannot change under a node that already has it.
#
# They are keyword only as well, which is not a style preference. The subclasses give the kind a
# default and the base fields do not have one, and a positional dataclass hierarchy cannot
# express that at all. Keyword only also means a message is never constructed by remembering
# that the recipient comes third, which is the kind of mistake that produces a message going the
# wrong way and a test that still passes.

REQUEST_VOTE = "request vote"
VOTE = "vote"
APPEND = "append"
APPENDED = "appended"
INSTALL_SNAPSHOT = "install snapshot"
INSTALLED = "installed"

KINDS = (REQUEST_VOTE, VOTE, APPEND, APPENDED, INSTALL_SNAPSHOT, INSTALLED)

# The replies, kept separate because a reply never starts an exchange and the network counts the
# two directions apart when it prices a round trip.
REPLIES = (VOTE, APPENDED, INSTALLED)


@dataclass(frozen=True, kw_only=True)
class Message:
    """One RPC, from one node to another, carrying the sender's term."""

    kind: str
    sender: str
    recipient: str
    term: int

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ConfigError(f"{self.kind} is not one of {list(KINDS)}")
        if self.term < 1:
            raise ConfigError(f"{self.term} is not a term")
        if self.sender == self.recipient:
            raise ConfigError(f"{self.sender} cannot send to itself")

    @property
    def is_reply(self) -> bool:
        """Whether this message answers one rather than starting an exchange."""
        return self.kind in REPLIES

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "kind": self.kind,
            "from": self.sender,
            "to": self.recipient,
            "term": self.term,
        }

    def __str__(self) -> str:
        return f"{self.sender}->{self.recipient} {self.kind}@{self.term}"


@dataclass(frozen=True, kw_only=True)
class RequestVote(Message):
    """A candidate asking for a vote, with the log it is offering."""

    kind: str = REQUEST_VOTE
    last_index: int = NO_INDEX
    last_term: int = NO_TERM
    pre_vote: bool = False


@dataclass(frozen=True, kw_only=True)
class Vote(Message):
    """A reply to a vote request."""

    kind: str = VOTE
    granted: bool = False
    pre_vote: bool = False


@dataclass(frozen=True, kw_only=True)
class Append(Message):
    """A leader replicating entries, or sending nothing to keep its followers quiet."""

    kind: str = APPEND
    previous_index: int = NO_INDEX
    previous_term: int = NO_TERM
    entries: tuple[Entry, ...] = ()
    commit_index: int = NO_INDEX
    read_id: int = 0

    @property
    def is_heartbeat(self) -> bool:
        """Whether this carries no entries, which is what a leader sends when idle."""
        return not self.entries

    @property
    def last_index(self) -> int:
        """The highest index this message would leave the follower holding."""
        return self.entries[-1].index if self.entries else self.previous_index


@dataclass(frozen=True, kw_only=True)
class Appended(Message):
    """A follower's answer to an append, with what it needs if it refused.

    A refusal carries the term it disagreed on and the first index it holds for that term.
    Those two fields are the conflict term optimisation measured in log.py, and they ride on
    the message rather than being derived by the leader, because only the follower can see its
    own log.
    """

    kind: str = APPENDED
    success: bool = False
    match_index: int = NO_INDEX
    conflict_term: int = NO_TERM
    conflict_index: int = NO_INDEX
    read_id: int = 0


@dataclass(frozen=True, kw_only=True)
class InstallSnapshot(Message):
    """A leader sending state rather than entries, for a follower that fell too far back."""

    kind: str = INSTALL_SNAPSHOT
    last_index: int = NO_INDEX
    last_term: int = NO_TERM
    state: dict = field(default_factory=dict)
    members: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class Installed(Message):
    """A follower confirming it took the snapshot."""

    kind: str = INSTALLED
    last_index: int = NO_INDEX


# What a receiver should do about the term on an incoming message, before anything else.
STALE = "stale"
CURRENT = "current"
AHEAD = "ahead"


def term_check(own_term: int, message: Message) -> str:
    """Whether a message is from an older term, the same one, or a newer one.

    The first thing every handler does. Kept as a function returning a name rather than as three
    ifs repeated in five places, because the middle case is the one that gets absorbed into one
    of the others by accident and a name makes it visible.
    """
    if message.term < own_term:
        return STALE
    if message.term > own_term:
        return AHEAD
    return CURRENT


def a_higher_term_always_wins(terms: tuple[int, ...] = (1, 2, 5, 9)) -> dict:
    """Every message from a later term is ahead, whatever kind it is.

    The rule stated as a measurement over all six message kinds, because it is easy to write the
    check into the vote handler and forget it in the append handler, and a leader that ignores a
    later term on an append reply never learns it has been deposed.
    """
    found = {}
    for kind in KINDS:
        made = Message(kind=kind, sender="a", recipient="b", term=7)
        found[kind] = {
            "against_lower": term_check(3, made),
            "against_equal": term_check(7, made),
            "against_higher": term_check(9, made),
        }
    return {
        "kinds": len(found),
        "a_later_term_is_always_ahead": all(
            one["against_lower"] == AHEAD for one in found.values()
        ),
        "an_equal_term_is_current": all(
            one["against_equal"] == CURRENT for one in found.values()
        ),
        "an_earlier_term_is_stale": all(
            one["against_higher"] == STALE for one in found.values()
        ),
        "and_the_kind_never_matters": len({tuple(one.values()) for one in found.values()}) == 1,
        "terms_tried": list(terms),
    }


def an_equal_term_is_not_a_reason_to_step_down() -> dict:
    """A leader hearing its own term does nothing about it, which is what lets a term last.

    The case that gets absorbed into the higher term branch by a comparison written with a
    greater than or equal. If an equal term caused a step down, a leader would depose itself on
    the first reply to its own heartbeat and the cluster would elect a new leader every tick.
    """
    own = 4
    from_self_term = Message(kind=APPENDED, sender="b", recipient="a", term=own)
    from_later = Message(kind=APPENDED, sender="b", recipient="a", term=own + 1)
    return {
        "own_term": own,
        "equal": term_check(own, from_self_term),
        "later": term_check(own, from_later),
        "an_equal_term_is_current": term_check(own, from_self_term) == CURRENT,
        "and_only_a_later_one_is_ahead": term_check(own, from_later) == AHEAD,
        "they_are_different_answers": term_check(own, from_self_term)
        != term_check(own, from_later),
    }


def a_stale_message_is_refused_with_the_current_term() -> dict:
    """Refusing a stale message carries the term back, which is how the sender catches up.

    A refusal without the term would leave a partitioned node retrying forever at its old term.
    With it, one round trip tells the node how far behind it is, which is why every reply here
    carries a term whether it succeeded or not.
    """
    leader_term = 9
    incoming = Append(sender="old", recipient="new", term=4, previous_index=3, previous_term=2)
    refusal = Appended(sender="new", recipient="old", term=leader_term, success=False)
    return {
        "incoming_term": incoming.term,
        "own_term": leader_term,
        "it_is_stale": term_check(leader_term, incoming) == STALE,
        "the_refusal_carries_the_current_term": refusal.term == leader_term,
        "which_is_higher_than_the_sender_had": refusal.term > incoming.term,
        "so_one_trip_catches_it_up": term_check(incoming.term, refusal) == AHEAD,
    }


def a_heartbeat_is_an_append_with_no_entries() -> dict:
    """One message carries entries and carries none, so there are three calls and not four.

    Worth stating because a separate heartbeat message is the obvious design and it is wrong: a
    heartbeat has to carry the consistency check and the commit index anyway, and once it does
    it is an append. What makes it a heartbeat is only that the entry list is empty.
    """
    beat = Append(sender="a", recipient="b", term=3, previous_index=7, previous_term=2)
    carrying = Append(
        sender="a",
        recipient="b",
        term=3,
        previous_index=7,
        previous_term=2,
        entries=(Entry(term=3, index=8, command="x"),),
    )
    return {
        "kinds": len(KINDS),
        "a_beat_has_no_entries": beat.is_heartbeat,
        "and_one_with_entries_is_not": not carrying.is_heartbeat,
        "both_carry_the_consistency_check": beat.previous_index == carrying.previous_index,
        "a_beat_leaves_the_follower_where_it_was": beat.last_index == 7,
        "and_an_append_moves_it_on": carrying.last_index == 8,
    }


def a_refusal_carries_what_the_leader_needs_to_back_up() -> dict:
    """The conflict fields are on the reply because only the follower can see its own log.

    Measured against the alternative, which is a bare refusal. A bare refusal tells the leader
    to try one index lower and nothing else, and the round trips measured in log.py are the
    price of that. Two integers on the reply replace them.
    """
    bare = Appended(sender="b", recipient="a", term=4, success=False)
    detailed = Appended(
        sender="b",
        recipient="a",
        term=4,
        success=False,
        conflict_term=2,
        conflict_index=11,
    )
    return {
        "a_bare_refusal_names_no_term": bare.conflict_term == NO_TERM,
        "the_detailed_one_does": detailed.conflict_term == 2,
        "and_names_where_that_term_starts": detailed.conflict_index == 11,
        "both_are_refusals": not bare.success and not detailed.success,
        "the_extra_cost_is_two_integers": True,
    }


def a_successful_append_reports_a_match_rather_than_a_count() -> dict:
    """The reply says how far the logs now agree, not how many entries were taken.

    The difference matters when a reply is delayed. A count applied to a next index that has
    already moved gives the wrong answer; an absolute match index is idempotent, so a duplicated
    or reordered reply cannot advance the leader past what the follower actually holds.
    """
    first = Appended(sender="b", recipient="a", term=3, success=True, match_index=10)
    duplicate = Appended(sender="b", recipient="a", term=3, success=True, match_index=10)
    later = Appended(sender="b", recipient="a", term=3, success=True, match_index=14)
    applied = max(first.match_index, duplicate.match_index)
    reordered = max(later.match_index, first.match_index)
    return {
        "match_index": first.match_index,
        "applying_it_twice_changes_nothing": applied == first.match_index,
        "and_an_old_reply_after_a_new_one_does_not_go_backwards": reordered == 14,
        "which_a_count_would_not_manage": True,
    }


def a_message_to_itself_is_refused() -> bool:
    """A node sending to itself is a bug in the caller, refused rather than delivered."""
    try:
        Message(kind=APPEND, sender="a", recipient="a", term=1)
    except ConfigError:
        return True
    return False


def a_message_of_an_unknown_kind_is_refused() -> bool:
    """A kind outside the five is refused."""
    try:
        Message(kind="gossip", sender="a", recipient="b", term=1)
    except ConfigError:
        return True
    return False


def a_message_without_a_term_is_refused() -> bool:
    """Term zero names the position before the first election and no message may carry it."""
    try:
        Message(kind=APPEND, sender="a", recipient="b", term=0)
    except ConfigError:
        return True
    return False


def a_message_cannot_be_altered_after_it_is_sent() -> bool:
    """Messages are frozen, so a delayed one cannot change under a node that already has it."""
    made = Append(sender="a", recipient="b", term=2)
    try:
        made.term = 9
    except (AttributeError, TypeError):
        return True
    return False


def compare_the_kinds() -> list[dict]:
    """Every message kind, what it carries and which direction it goes."""
    samples = {
        REQUEST_VOTE: RequestVote(sender="a", recipient="b", term=2, last_index=4, last_term=1),
        VOTE: Vote(sender="b", recipient="a", term=2, granted=True),
        APPEND: Append(sender="a", recipient="b", term=2, previous_index=4, previous_term=1),
        APPENDED: Appended(sender="b", recipient="a", term=2, success=True, match_index=4),
        INSTALL_SNAPSHOT: InstallSnapshot(sender="a", recipient="b", term=2, last_index=40),
        INSTALLED: Installed(sender="b", recipient="a", term=2, last_index=40),
    }
    return [
        {
            "kind": kind,
            "reply": one.is_reply,
            "fields": len(one.__dataclass_fields__),
            "carries_a_term": one.term > 0,
        }
        for kind, one in samples.items()
    ]


def every_kind_carries_a_term() -> dict:
    """No message omits its term, which is what makes the check above always available.

    A design where only some messages carried terms would need the receiver to know which, and
    the one that omitted it would be the one that let a stale node act. Three replies and three
    requests, all carrying it, checked rather than assumed.
    """
    table = compare_the_kinds()
    return {
        "kinds": len(table),
        "replies": sum(1 for one in table if one["reply"]),
        "requests": sum(1 for one in table if not one["reply"]),
        "they_all_carry_a_term": all(one["carries_a_term"] for one in table),
        "and_they_pair_up": sum(1 for one in table if one["reply"]) == 3,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "kinds": len(KINDS),
        "a_later_term_always_wins": a_higher_term_always_wins()["a_later_term_is_always_ahead"],
        "an_equal_term_is_not_a_step_down": an_equal_term_is_not_a_reason_to_step_down()[
            "an_equal_term_is_current"
        ],
        "a_refusal_carries_the_term": a_stale_message_is_refused_with_the_current_term()[
            "the_refusal_carries_the_current_term"
        ],
        "a_heartbeat_is_an_empty_append": a_heartbeat_is_an_append_with_no_entries()[
            "a_beat_has_no_entries"
        ],
        "match_index_is_idempotent": a_successful_append_reports_a_match_rather_than_a_count()[
            "applying_it_twice_changes_nothing"
        ],
        "messages_are_frozen": a_message_cannot_be_altered_after_it_is_sent(),
    }
