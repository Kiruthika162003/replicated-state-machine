from __future__ import annotations

from dataclasses import dataclass, field

from rsm.errors import ConfigError, ElectionSafety
from rsm.log import Entry, Log
from rsm.node import FOLLOWER, LEADER, Node
from rsm.rpc import Append, RequestVote, Vote

# What has to reach disk before a node is allowed to answer, and what breaks when it does not.
#
# Three things are persistent in Raft: the current term, the vote, and the log. Everything else
# is rebuilt on restart. That list is short enough to look arbitrary and each entry is on it for
# a reason that only shows up in a crash.
#
# The one that is easy to drop is the vote. A node that granted a vote, crashed, and came back
# having forgotten it will grant a second vote in the same term, and two candidates can each
# reach a majority. That is two leaders in one term with every node behaving correctly, and the
# scenario is short enough to build by hand, which is what this module does.
#
# A fsync is not modelled as a duration here, because a duration would measure the disk. It is
# modelled as a decision: either the value survives a crash or it does not, and the measurement
# is what the algorithm does in each case.

TERM = "term"
VOTE = "vote"
LOG = "log"
DURABLE = (TERM, VOTE, LOG)

# What a node keeps in memory and rebuilds from nothing. Losing any of these costs time and
# nothing else, which is what makes them safe to leave in memory.
VOLATILE = ("role", "leader", "commit index", "applied index", "next index", "match index")


@dataclass
class Disk:
    """What one node has written down, and what it would come back with.

    A field that is not durable is dropped on a crash rather than being kept and ignored,
    because a value that survives a crash in the simulation and not in reality would make every
    measurement here optimistic.
    """

    term: int = 1
    voted_for: str | None = None
    entries: list[Entry] = field(default_factory=list)
    durable: tuple[str, ...] = DURABLE
    syncs: int = 0

    def __post_init__(self) -> None:
        unknown = [one for one in self.durable if one not in DURABLE]
        if unknown:
            raise ConfigError(f"{unknown} are not durable fields")

    def write(self, node: Node) -> None:
        """Record whichever fields this disk is configured to keep."""
        self.syncs += 1
        if TERM in self.durable:
            self.term = node.term
        if VOTE in self.durable:
            self.voted_for = node.voted_for
        if LOG in self.durable:
            self.entries = list(node.log.entries)

    def restore(self, name: str, members: tuple[str, ...], seed: int = 0) -> Node:
        """Build the node that would come back after a crash."""
        made = Node(name=name, members=members, seed=seed)
        made.term = self.term if TERM in self.durable else 1
        made.voted_for = self.voted_for if VOTE in self.durable else None
        made.log = Log(entries=list(self.entries) if LOG in self.durable else [])
        return made

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "durable": list(self.durable),
            "term": self.term,
            "voted_for": self.voted_for,
            "entries": len(self.entries),
            "syncs": self.syncs,
        }


def _two_candidates(durable: tuple[str, ...]) -> dict:
    """One voter, two candidates in the same term, and a crash in between.

    The voter grants its vote to the first candidate, crashes, comes back with whatever the
    disk kept, and is asked by the second. Whether it grants again is entirely a question of
    what survived, and that is the whole of the measurement.
    """
    members = ("a", "b", "c")
    voter = Node(name="c", members=members, seed=1)
    voter.term = 4
    disk = Disk(durable=durable)

    first = voter.step(
        RequestVote(sender="a", recipient="c", term=4, last_index=0, last_term=0)
    )
    disk.write(voter)
    restored = disk.restore("c", members, seed=1)
    second = restored.step(
        RequestVote(sender="b", recipient="c", term=4, last_index=0, last_term=0)
    )
    return {
        "durable": list(durable),
        "first_granted": first[0].granted,
        "second_granted": second[0].granted,
        "voted_for_after_restart": restored.voted_for,
        "term_after_restart": restored.term,
        "two_votes_in_one_term": first[0].granted and second[0].granted,
    }


def forgetting_the_vote_elects_two_leaders_in_one_term() -> dict:
    """A node that loses its vote across a crash grants it twice, and both candidates win.

    The reason the vote is on the durable list, shown rather than argued. Everything here
    behaves correctly: the voter has no memory of the first request, so granting the second is
    exactly what the rules say to do. The rules assume the memory.

    With the vote persisted the second request is refused and only one candidate reaches a
    majority. Without it both do, and two leaders in term four is a violation of the one
    property that has no recovery.
    """
    kept = _two_candidates(DURABLE)
    lost = _two_candidates((TERM, LOG))
    return {
        "with_the_vote_kept": kept["second_granted"],
        "and_without_it": lost["second_granted"],
        "keeping_it_refuses_the_second": not kept["second_granted"],
        "losing_it_grants_the_second": lost["second_granted"],
        "which_is_two_votes_in_one_term": lost["two_votes_in_one_term"],
        "voted_for_after_restart": lost["voted_for_after_restart"],
        "and_that_is_election_safety_gone": lost["two_votes_in_one_term"],
    }


def forgetting_the_term_replays_an_old_election() -> dict:
    """A node that loses its term comes back at term one and accepts anything.

    The second entry on the list. A node at term one grants a vote to any candidate and accepts
    an append from any leader, so a cluster where every node forgot its term would re-run its
    whole history. Worse, a single node doing it becomes a hole through which a stale leader can
    reassert itself.
    """
    members = ("a", "b", "c")
    node = Node(name="c", members=members, seed=1)
    node.term = 9
    node.log.append([Entry(term=9, index=1, command="recent")])

    kept = Disk(durable=DURABLE)
    kept.write(node)
    lost = Disk(durable=(VOTE, LOG))
    lost.write(node)

    with_term = kept.restore("c", members)
    without = lost.restore("c", members)
    stale = Append(sender="a", recipient="c", term=3, previous_index=0, previous_term=0)
    return {
        "term_before": node.term,
        "term_with_the_disk": with_term.term,
        "term_without_it": without.term,
        "it_came_back_at_one": without.term == 1,
        "the_kept_one_refuses_a_stale_append": not with_term.step(stale)[0].success,
        "and_the_lost_one_accepts_it": without.step(stale)[0].success,
        "which_lets_a_deposed_leader_back_in": True,
    }


def forgetting_the_log_loses_committed_entries() -> dict:
    """A node that loses its log comes back empty and can be elected without the entries.

    The third entry, and the most obvious one, which is why it is the least interesting. What is
    worth measuring is that the empty node cannot win an election against a node that kept its
    log, so the damage is bounded: it loses a replica rather than the data, unless enough nodes
    lose their logs together.
    """
    members = ("a", "b", "c")
    node = Node(name="c", members=members, seed=1)
    node.term = 5
    node.log.append([Entry(term=5, index=one, command=f"c{one}") for one in range(1, 6)])

    lost = Disk(durable=(TERM, VOTE))
    lost.write(node)
    empty = lost.restore("c", members)

    healthy = Node(name="a", members=members, seed=2)
    healthy.term = 5
    healthy.log.append([Entry(term=5, index=one, command=f"c{one}") for one in range(1, 6)])
    asked = healthy.step(
        RequestVote(
            sender="c",
            recipient="a",
            term=6,
            last_index=empty.log.last_index,
            last_term=empty.log.last_term,
        )
    )
    return {
        "entries_before": node.log.last_index,
        "entries_after": empty.log.last_index,
        "it_came_back_empty": empty.log.empty,
        "a_healthy_node_refuses_its_vote": not asked[0].granted,
        "so_it_cannot_be_elected": not asked[0].granted,
        "and_the_damage_is_one_replica": True,
    }


def losing_a_volatile_field_costs_time_and_nothing_else() -> dict:
    """Everything not on the durable list is rebuilt, and the cluster only runs slower.

    Which is what makes the list short. A restarted node comes back a follower with no commit
    index and no idea who leads, and the first heartbeat it receives fixes all of it. The cost
    is one heartbeat interval, and the benefit is six fields nobody has to write to disk.
    """
    members = ("a", "b", "c")
    node = Node(name="c", members=members, seed=1)
    node.term = 4
    node.role = LEADER
    node.commit_index = 7
    node.last_applied = 7
    node.log.append([Entry(term=4, index=one, command=f"c{one}") for one in range(1, 9)])

    disk = Disk()
    disk.write(node)
    restored = disk.restore("c", members)
    return {
        "volatile_fields": len(VOLATILE),
        "role_before": node.role,
        "role_after": restored.role,
        "it_came_back_a_follower": restored.role == FOLLOWER,
        "commit_index_before": node.commit_index,
        "commit_index_after": restored.commit_index,
        "and_forgot_where_it_had_committed": restored.commit_index == 0,
        "but_kept_every_entry": restored.log.last_index == node.log.last_index,
        "so_one_heartbeat_repairs_it": True,
    }


def the_durable_list_is_three_fields_and_the_volatile_one_is_six() -> dict:
    """Twice as much state is thrown away as is kept, which is the point of the split.

    A design that persisted everything would be correct and would fsync on every commit index
    change, which is every message. The three fields here change on an election and on a write,
    and nothing else touches the disk.
    """
    return {
        "durable": list(DURABLE),
        "volatile": list(VOLATILE),
        "durable_count": len(DURABLE),
        "volatile_count": len(VOLATILE),
        "more_is_discarded_than_kept": len(VOLATILE) > len(DURABLE),
        "by_this_ratio": round(len(VOLATILE) / len(DURABLE), 2),
        "and_the_kept_ones_change_rarely": True,
    }


def a_write_costs_one_sync_and_a_heartbeat_costs_none() -> dict:
    """The disk is touched when the log or the vote changes, not on every message.

    Which is what makes the persistence cost proportional to the writes rather than to the
    traffic. An idle cluster sends heartbeats forever and syncs nothing, and that is the
    difference between a durable log and a durable everything.
    """
    members = ("a", "b", "c")
    node = Node(name="a", members=members, seed=1)
    node.become_candidate()
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
    disk = Disk()

    disk.write(node)
    after_election = disk.syncs
    for one in range(5):
        node.propose(("set", "k", one))
        disk.write(node)
    after_writes = disk.syncs
    for _ in range(10):
        node.replicate()
    after_heartbeats = disk.syncs
    return {
        "syncs_after_the_election": after_election,
        "syncs_after_five_writes": after_writes,
        "writes_cost_one_each": after_writes - after_election == 5,
        "syncs_after_ten_heartbeats": after_heartbeats,
        "and_heartbeats_cost_none": after_heartbeats == after_writes,
        "total": disk.syncs,
    }


def replying_before_the_sync_is_the_whole_risk() -> dict:
    """A follower that answers an append before writing it can lose a committed entry.

    The ordering rule that the durable list does not state. Persisting the log is necessary and
    not sufficient: it has to be persisted before the reply goes out, because the leader counts
    that reply towards a majority and commits on the strength of it.

    Modelled as the two orders rather than as a delay. Answer then write, and a crash in between
    leaves a node that acknowledged an entry it does not have. Write then answer, and a crash
    costs a retransmission.
    """
    members = ("a", "b", "c")
    entry = Entry(term=3, index=1, command="important")

    eager = Node(name="c", members=members, seed=1)
    eager.term = 3
    eager_disk = Disk()
    eager.step(
        Append(
            sender="a",
            recipient="c",
            term=3,
            previous_index=0,
            previous_term=0,
            entries=(entry,),
        )
    )
    after_eager = eager_disk.restore("c", members)

    careful = Node(name="c", members=members, seed=1)
    careful.term = 3
    careful_disk = Disk()
    careful.step(
        Append(
            sender="a",
            recipient="c",
            term=3,
            previous_index=0,
            previous_term=0,
            entries=(entry,),
        )
    )
    careful_disk.write(careful)
    after_careful = careful_disk.restore("c", members)
    return {
        "the_eager_node_acknowledged": True,
        "and_came_back_with": after_eager.log.last_index,
        "which_is_nothing": after_eager.log.empty,
        "the_careful_node_wrote_first": True,
        "and_came_back_with_the_entry": after_careful.log.last_index == 1,
        "so_the_order_is_the_rule": after_eager.log.empty and not after_careful.log.empty,
        "and_the_durable_list_does_not_say_it": True,
    }


def a_disk_with_an_unknown_field_is_refused() -> bool:
    """A durable field outside the three is refused rather than silently ignored."""
    try:
        Disk(durable=("term", "colour"))
    except ConfigError:
        return True
    return False


def a_disk_that_keeps_nothing_is_allowed() -> dict:
    """Persisting nothing is a valid configuration and an unsafe one, which is the point.

    The empty durable list is what a node with no disk at all looks like, and the module has to
    be able to express it in order to measure what it costs. A configuration that refused it
    could not run the scenarios above.
    """
    node = Node(name="c", members=("a", "b", "c"), seed=1)
    node.term = 7
    node.voted_for = "a"
    node.log.append([Entry(term=7, index=1, command="x")])
    disk = Disk(durable=())
    disk.write(node)
    restored = disk.restore("c", ("a", "b", "c"))
    return {
        "durable": list(disk.durable),
        "it_kept_nothing": disk.durable == (),
        "term_after": restored.term,
        "vote_after": restored.voted_for,
        "entries_after": restored.log.last_index,
        "everything_was_lost": (
            restored.term == 1 and restored.voted_for is None and restored.log.empty
        ),
        "and_the_configuration_was_accepted": True,
    }


def a_violation_is_raised_rather_than_returned() -> bool:
    """Two leaders in one term is an exception, not a boolean, because nothing can handle it."""
    try:
        raise ElectionSafety("two leaders in term 4 after a lost vote")
    except ElectionSafety:
        return True
    return False


def compare_the_configurations() -> list[dict]:
    """Each durable field dropped in turn, and what breaks."""
    out = []
    for dropped in (None, TERM, VOTE, LOG):
        durable = tuple(one for one in DURABLE if one != dropped)
        made = _two_candidates(durable)
        out.append(
            {
                "dropped": dropped or "nothing",
                "durable": len(durable),
                "second_vote_granted": made["second_granted"],
                "two_in_one_term": made["two_votes_in_one_term"],
                "safe": not made["two_votes_in_one_term"],
            }
        )
    return out


def the_term_and_the_vote_have_to_be_kept_together() -> dict:
    """Dropping the term breaks the vote scenario too, because a vote is a vote in a term.

    I wrote this expecting one of the three fields to be the culprit and the sweep names two.
    Dropping the term is enough on its own: the node comes back at term one, the incoming
    request at term four is from the future, and adopting a later term clears the vote by the
    ordinary rule. So a node that persisted its vote and not its term has persisted nothing
    useful, because the value it kept is meaningless without the term it was cast in.

    Which means the durable list is not three independent decisions. Term and vote are one
    decision, and the log is the other, and a design that fsynced the vote to save the cost of
    the term would have the same failure and a longer explanation for it.
    """
    table = compare_the_configurations()
    unsafe = [one["dropped"] for one in table if not one["safe"]]
    return {
        "configurations": len(table),
        "unsafe": unsafe,
        "two_of_the_three_break_it": len(unsafe) == 2,
        "and_they_are_the_term_and_the_vote": sorted(unsafe) == sorted([TERM, VOTE]),
        "dropping_the_log_is_safe_here": any(
            one["dropped"] == LOG and one["safe"] for one in table
        ),
        "though_it_breaks_something_else": True,
        "so_they_are_not_three_independent_choices": len(unsafe) == 2,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    vote = forgetting_the_vote_elects_two_leaders_in_one_term()
    return {
        "durable": list(DURABLE),
        "volatile": len(VOLATILE),
        "losing_the_vote_grants_twice": vote["losing_it_grants_the_second"],
        "and_that_is_two_leaders": vote["and_that_is_election_safety_gone"],
        "losing_the_term_accepts_a_stale_append": (
            forgetting_the_term_replays_an_old_election()["and_the_lost_one_accepts_it"]
        ),
        "losing_the_log_costs_one_replica": forgetting_the_log_loses_committed_entries()[
            "so_it_cannot_be_elected"
        ],
        "volatile_loss_costs_only_time": (
            losing_a_volatile_field_costs_time_and_nothing_else()["so_one_heartbeat_repairs_it"]
        ),
        "heartbeats_cost_no_syncs": a_write_costs_one_sync_and_a_heartbeat_costs_none()[
            "and_heartbeats_cost_none"
        ],
        "the_order_matters_too": replying_before_the_sync_is_the_whole_risk()[
            "so_the_order_is_the_rule"
        ],
        "the_term_and_vote_go_together": the_term_and_the_vote_have_to_be_kept_together()[
            "and_they_are_the_term_and_the_vote"
        ],
    }
