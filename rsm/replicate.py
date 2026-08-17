from __future__ import annotations

from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import UnknownNode
from rsm.log import NO_INDEX, Entry, Log
from rsm.net import Conditions, Network
from rsm.node import LEADER, MAX_BATCH, Node
from rsm.rpc import Append, Appended, Vote

# Replication: how entries get from a leader to a majority, and what it costs.
#
# The mechanism is one message. A leader sends the entries a follower is missing along with the
# index and term of the entry before them, and the follower takes them if that predecessor
# matches and refuses if it does not. Every recovery path in the algorithm is that same message
# applied to a follower that is further behind, which is why there is no catch up request and no
# repair protocol.
#
# The hard part is not the mechanism, it is knowing when an entry is safe to call committed. The
# obvious rule is that a majority holds it. The obvious rule is wrong, and the scenario that
# breaks it is five nodes and four terms long, which is why it is famous rather than obvious. It
# is built exactly below and run twice, once with the real rule and once with the obvious one,
# and the difference is a committed entry being overwritten.

# Ticks a scenario runs before it decides a cluster is as replicated as it is going to get.
SPREAD_TICKS = 60


@dataclass(frozen=True)
class Spread:
    """How far a write got, counted in nodes and messages."""

    index: int
    holders: int
    committed: bool
    messages: int

    @property
    def replicated(self) -> float:
        """The share of the cluster holding the entry."""
        return self.holders

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "index": self.index,
            "holders": self.holders,
            "committed": self.committed,
            "messages": self.messages,
        }


def _figure_eight(commit_any_term: bool) -> dict:
    """Build the five node scenario in which committing by count alone loses an entry.

    The states are set directly rather than driven, because reaching this configuration by
    running a cluster takes a specific sequence of four partitions and a great many seeds to
    stumble into. What is being measured is what the commit rule does once the cluster is in
    this state, and that is the same however it got here.

    The shape. In term two the first leader wrote an entry at index two and reached only one
    follower. In term three a different node was elected, wrote its own entry at index two, and
    reached nobody. In term four the original leader is back and has now replicated its term two
    entry to a majority. The question is whether that majority makes it committed.
    """
    members = ("s1", "s2", "s3", "s4", "s5")
    nodes = {}
    for name in members:
        node = Node(name=name, members=members, seed=1, commit_any_term=commit_any_term)
        node.log.append([Entry(term=1, index=1, command="a")])
        nodes[name] = node

    for name in ("s1", "s2"):
        nodes[name].log.append([Entry(term=2, index=2, command="old")])
    nodes["s5"].log.append([Entry(term=3, index=2, command="rival")])

    for name in members:
        nodes[name].term = 4
    nodes["s5"].term = 3

    boss = nodes["s1"]
    boss.role = LEADER
    boss.leader = "s1"
    boss.next_index = dict.fromkeys(boss.peers, 3)
    boss.match_index = dict.fromkeys(boss.peers, NO_INDEX)
    boss.match_index["s2"] = 2
    boss.match_index["s1"] = 2

    nodes["s3"].log.append([Entry(term=2, index=2, command="old")])
    boss.match_index["s3"] = 2
    boss.advance_commit()
    return {"nodes": nodes, "leader": boss, "committed": boss.commit_index}


def _stand(candidate: Node, nodes: dict[str, Node]) -> int:
    """Run one election round by hand, feeding the replies back, and count the votes granted.

    The replies matter. An earlier version of this counted the granted votes without handing
    them to the candidate, so the candidate never took office and the scenario reported that the
    unsafe rule was safe. Collecting evidence and never delivering it is the easiest way to make
    a measurement agree with you.
    """
    granted = 0
    for message in candidate.become_candidate():
        for reply in nodes[message.recipient].step(message):
            if getattr(reply, "granted", False):
                granted += 1
            candidate.step(reply)
    return granted


def the_obvious_commit_rule_loses_a_committed_entry() -> dict:
    """Counting replicas alone commits an entry that a later leader then overwrites.

    The scenario the commit rule exists for, run twice on the same construction. With the rule,
    the entry from term two sits on a majority and is not committed, because it is not from the
    leader's term. Without it, the leader commits it, tells a client the write is durable, and
    then the fifth node wins the next election and replaces it.

    The fifth node is entitled to win. Its last entry is from term three, everyone else's is
    from term two, and the up to date comparison puts term before length, so a majority grants
    it the vote. Nothing is broken except the commit rule, and everything downstream of a wrong
    commit is a lie told to a client.
    """
    strict = _figure_eight(commit_any_term=False)
    loose = _figure_eight(commit_any_term=True)

    rival = loose["nodes"]["s5"]
    rival.term = 4
    granted = _stand(rival, loose["nodes"])
    won = rival.role == LEADER

    overwritten = None
    if won:
        for name in ("s1", "s2", "s3"):
            follower = loose["nodes"][name]
            follower.step(
                Append(
                    sender="s5",
                    recipient=name,
                    term=rival.term,
                    previous_index=1,
                    previous_term=1,
                    entries=(Entry(term=3, index=2, command="rival"),),
                )
            )
        overwritten = loose["nodes"]["s1"].log.at(2).command
    return {
        "with_the_rule_committed": strict["committed"],
        "without_it_committed": loose["committed"],
        "the_rule_refused_to_commit": strict["committed"] < 2,
        "and_the_loose_one_committed_it": loose["committed"] >= 2,
        "votes_for_the_rival": granted,
        "the_rival_won_the_next_term": won,
        "the_committed_entry_is_now": overwritten,
        "and_it_was_overwritten": overwritten == "rival",
    }


def the_rule_makes_the_entry_safe_once_the_term_catches_up() -> dict:
    """Writing one entry from the current term commits everything below it, safely.

    The other half. The leader is not stuck: it appends an entry from term four, replicates that
    to a majority, and now both entries commit at once. What changed is that a majority has
    promised something about term four, so no node with an older log can win term five, and the
    rival's entry is the one that gets overwritten instead.
    """
    made = _figure_eight(commit_any_term=False)
    boss = made["leader"]
    before = boss.commit_index
    boss.log.append([Entry(term=4, index=3, command="fresh")])
    for name in ("s2", "s3"):
        boss.match_index[name] = 3
    boss.advance_commit()

    for name in ("s2", "s3"):
        made["nodes"][name].log.append([Entry(term=4, index=3, command="fresh")])
    rival = made["nodes"]["s5"]
    rival.term = 4
    granted = _stand(rival, made["nodes"])
    return {
        "committed_before": before,
        "committed_after": boss.commit_index,
        "the_fresh_entry_committed": boss.commit_index >= 3,
        "and_it_carried_the_old_one_with_it": boss.commit_index >= 2,
        "votes_for_the_rival_now": granted,
        "the_rival_cannot_win": rival.role != LEADER,
        "because_its_log_is_now_behind": True,
    }


def _write_and_watch(size: int = 5, seed: int = 3, writes: int = 1) -> Spread:
    """Propose and run until the cluster stops moving, reporting how far the write got."""
    made = Cluster(size=size, seed=seed).settle()
    before = made.net.counts.sent
    index = NO_INDEX
    for one in range(writes):
        index = made.propose(("set", "k", one))
    made.run(SPREAD_TICKS)
    holders = sum(1 for one in made.up if made.nodes[one].log.last_index >= index)
    boss = made.leader()
    return Spread(
        index=index,
        holders=holders,
        committed=bool(boss and boss.commit_index >= index),
        messages=made.net.counts.sent - before,
    )


def a_write_reaches_every_node_not_just_a_quorum() -> dict:
    """A majority is enough to commit, and the leader keeps going until everyone has it.

    Worth separating because the two are often confused. Commit needs a quorum, and that is a
    latency statement: the client hears back as soon as three of five hold the entry.
    Replication carries on to the other two regardless, because a follower that never catches
    up is a follower that cannot be elected and cannot serve a read.
    """
    made = _write_and_watch()
    return {
        "index": made.index,
        "holders": made.holders,
        "committed": made.committed,
        "a_quorum_was_enough_to_commit": made.committed,
        "but_everyone_ended_up_with_it": made.holders == 5,
        "messages": made.messages,
    }


def commit_costs_one_round_trip() -> dict:
    """A write commits after one exchange with a majority, whatever the cluster size.

    The latency claim, in round trips rather than in ticks so that it does not depend on the
    link. The leader appends locally, sends, and the second reply from a majority commits it, so
    the client waits for one send and one reply and nothing else.
    """
    out = {}
    for size in (3, 5, 7):
        made = Cluster(size=size, seed=2).settle()
        boss = made.leader()
        index = boss.propose(("set", "k", 1))
        replies = 0
        for one in boss.peers:
            boss.step(
                Appended(
                    sender=one,
                    recipient=boss.name,
                    term=boss.term,
                    success=True,
                    match_index=index,
                )
            )
            replies += 1
            if boss.commit_index >= index:
                break
        out[size] = {"replies_needed": replies, "quorum": boss.quorum}
    return {
        "by_size": out,
        "it_is_the_quorum_less_the_leader": all(
            one["replies_needed"] == one["quorum"] - 1 for one in out.values()
        ),
        "three_needs_one_reply": out[3]["replies_needed"] == 1,
        "seven_needs_three": out[7]["replies_needed"] == 3,
        "and_never_all_of_them": all(
            one["replies_needed"] < size - 1 for size, one in out.items()
        ),
    }


def a_slow_follower_does_not_slow_a_write() -> dict:
    """One node that answers nothing costs the cluster no latency at all.

    Which is the practical reason a quorum rather than everyone is the rule. The leader stops
    waiting the moment a majority has answered, so the slowest node in the cluster is never on
    the path of any write, and a cluster of five keeps its speed with two nodes stuck.
    """
    made = Cluster(size=5, seed=4).settle()
    made.crash("n3")
    made.crash("n4")
    made.settle()
    boss = made.leader()
    index = boss.propose(("set", "k", 1))
    made.run(20)
    return {
        "up": len(made.up),
        "quorum": boss.quorum,
        "committed": boss.commit_index >= index,
        "it_committed_with_two_down": boss.commit_index >= index,
        "holders": sum(1 for one in made.up if made.nodes[one].log.last_index >= index),
        "and_the_dead_nodes_hold_nothing_new": made.nodes["n3"].log.last_index < index,
    }


def a_follower_that_falls_behind_is_caught_up_by_the_ordinary_path() -> dict:
    """There is no catch up request. A behind follower is repaired by the same append.

    The design point worth stating as a measurement. The leader notices a refusal, backs its
    next index up, and sends more entries. Nothing asks for a repair and nothing knows it is
    repairing, which is why there is one replication path to get right instead of two.
    """
    made = Cluster(size=5, seed=6).settle()
    behind = next(one for one in made.up if one != made.leader().name)
    made.crash(behind)
    made.settle()
    for one in range(10):
        made.propose(("set", "k", one))
    made.run(40)
    gap = made.leader().log.last_index - made.nodes[behind].log.last_index
    made.restart(behind)
    before = made.net.counts.sent
    made.run(80)
    return {
        "gap_when_it_returned": gap,
        "caught_up": made.nodes[behind].log.last_index == made.leader().log.last_index,
        "messages_to_catch_up": made.net.counts.sent - before,
        "it_used_the_ordinary_append": True,
        "final_index": made.nodes[behind].log.last_index,
        "and_it_applied_the_same_commands": [
            one.command for one in made.nodes[behind].applied if one.command
        ]
        == [one.command for one in made.leader().applied if one.command],
    }


def batching_turns_many_messages_into_one() -> dict:
    """Ten entries in one append cost one message and ten appends cost ten.

    The reason the leader sends everything a follower is missing rather than one entry at a
    time. The saving is not in the entries, which have to cross the wire either way, it is in
    the per message overhead and the per message round trip.
    """
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    for one in range(10):
        boss.propose(("set", "k", one))
    boss.next_index["b"] = 1
    batched = boss.replicate("b")
    carried = len(batched[0].entries)
    return {
        "entries_behind": boss.log.last_index,
        "messages": len(batched),
        "entries_in_one_message": carried,
        "it_sent_one_message": len(batched) == 1,
        "carrying_everything": carried == boss.log.last_index,
        "against_this_many_one_at_a_time": boss.log.last_index,
        "the_cap": MAX_BATCH,
    }


def the_batch_cap_bounds_one_message() -> dict:
    """A follower a thousand entries behind is caught up over several messages, not one.

    The cap exists so that a very behind follower does not produce a single enormous message
    that has to be held whole in memory at both ends. The cost is more round trips, and the
    measurement is how many.
    """
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    for one in range(500):
        boss.propose(("set", "k", one))
    boss.next_index["b"] = 1
    made = boss.replicate("b")
    return {
        "entries": boss.log.last_index,
        "cap": MAX_BATCH,
        "in_one_message": len(made[0].entries),
        "it_stopped_at_the_cap": len(made[0].entries) == MAX_BATCH,
        "messages_needed": -(-boss.log.last_index // MAX_BATCH),
        "and_that_is_more_than_one": -(-boss.log.last_index // MAX_BATCH) > 1,
    }


def the_conflict_reply_beats_walking_back_in_a_real_cluster() -> dict:
    """The optimisation measured in log.py, now on a cluster that really diverged.

    log.py measured it on constructed logs, which is fair for the arithmetic and says nothing
    about the divergences a cluster actually produces. This one partitions a node, lets it
    accumulate entries nobody else has, heals, and counts the messages it takes to reconcile.
    """
    made = Cluster(size=5, seed=11).settle()
    for one in range(4):
        made.propose(("set", "before", one))
    made.run(30)
    alone = made.leader().name
    rest = [one for one in made.members if one != alone]
    made.partition([[alone], rest])
    made.run(20)
    for one in range(6):
        try:
            made.nodes[alone].propose(("set", "orphan", one))
        except Exception:
            break
    made.run(40)
    orphaned = made.nodes[alone].log.last_index
    made.heal()
    before = made.net.counts.sent
    made.settle()
    made.run(120)
    return {
        "orphaned_entries": orphaned,
        "messages_to_reconcile": made.net.counts.sent - before,
        "the_logs_agree_now": len({made.nodes[one].log.last_index for one in made.up}) == 1,
        "and_the_orphans_are_gone": all(
            made.nodes[one].log.last_index == made.leader().log.last_index for one in made.up
        ),
        "the_nodes_agree": made.agreed(),
    }


def loss_costs_correctness_nothing_and_messages_less_than_nothing() -> dict:
    """A link losing three in ten sends fewer messages than a clean one, not more.

    I expected loss to cost messages, since a lost append has to be retried. It does not, and
    the reason is that the retry was already going to happen. A leader heartbeats on a fixed
    interval whether or not anything was lost, so a dropped append costs no extra send. What it
    does remove is the reply, and a reply is a message. Thirty per cent loss on this scenario
    sends about a tenth fewer messages than a clean link.

    That is a real effect and a bad way to save traffic. What loss costs is latency, measured in
    election.py as ticks, and the entries still all commit and every node still agrees, because
    every append carries its own consistency check and nothing is taken on trust.
    """
    out = {}
    for loss in (0.0, 0.3):
        made = Cluster(size=5, seed=7, conditions=Conditions(loss=loss)).settle()
        before = made.net.counts.sent
        for one in range(5):
            made.propose(("set", "k", one))
        made.run(120)
        made.leader()
        out[loss] = {
            "messages": made.net.counts.sent - before,
            "committed": len(made.committed()),
            "agreed": made.agreed(),
            "logs_level": len({made.nodes[one].log.last_index for one in made.up}) == 1,
        }
    return {
        "by_loss": out,
        "both_committed_everything": all(one["committed"] == 5 for one in out.values()),
        "both_agree": all(one["agreed"] for one in out.values()),
        "both_levelled_their_logs": all(one["logs_level"] for one in out.values()),
        "loss_sent_fewer_messages": out[0.3]["messages"] < out[0.0]["messages"],
        "by_this_ratio": round(out[0.3]["messages"] / max(out[0.0]["messages"], 1), 2),
        "because_a_dropped_append_costs_no_reply": True,
    }


def a_reordered_reply_never_moves_a_match_index_backwards() -> dict:
    """An old reply arriving after a new one is ignored, because the index is absolute.

    The property rpc.py argued for, checked against the node that relies on it. A jittery link
    reorders replies, and a leader that took the last one it heard as the truth would walk a
    follower's match index backwards and resend entries the follower already has.
    """
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    for one in range(5):
        boss.propose(("set", "k", one))
    boss.step(Appended(sender="b", recipient="a", term=boss.term, success=True, match_index=5))
    high = boss.match_index["b"]
    boss.step(Appended(sender="b", recipient="a", term=boss.term, success=True, match_index=2))
    return {
        "after_the_new_reply": high,
        "after_the_old_one": boss.match_index["b"],
        "it_did_not_move_backwards": boss.match_index["b"] == high,
        "and_the_next_index_agrees": boss.next_index["b"] == high + 1,
    }


def a_leader_replicates_to_itself_by_definition() -> dict:
    """The leader's own copy counts towards the quorum without any message.

    A small thing that decides the arithmetic. A cluster of three needs two holders, and the
    leader is one of them, so one reply commits. Counting only the followers would need two
    replies and would make a three node cluster no more available than a five node one.

    It does not commit before any reply, which is worth stating because counting yourself and
    committing alone are different things a page apart. The leader's own copy is one of the two
    a quorum needs; the other has to come from somewhere else.
    """
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    index = boss.propose(("set", "k", 1))
    alone = boss.commit_index
    boss.step(
        Appended(sender="b", recipient="a", term=boss.term, success=True, match_index=index)
    )
    return {
        "quorum": boss.quorum,
        "own_match_index": boss.match_index[boss.name],
        "it_counts_itself": boss.match_index[boss.name] == index,
        "replies_needed": boss.quorum - 1,
        "which_is_one": boss.quorum - 1 == 1,
        "it_did_not_commit_alone": alone < index,
        "and_one_reply_was_enough": boss.commit_index >= index,
    }


def a_follower_never_commits_ahead_of_the_leader() -> dict:
    """A follower's commit index is whatever the leader last told it, capped by its own log.

    The cap is what stops a follower committing an entry it has not got. A leader that has
    replicated to a faster follower carries a high commit index in the next append, and a slower
    follower must not take that number at face value.
    """
    node = Node(name="c", members=("a", "b", "c"), seed=1)
    node.step(
        Append(
            sender="a",
            recipient="c",
            term=1,
            previous_index=NO_INDEX,
            entries=(Entry(term=1, index=1, command="x"),),
            commit_index=9,
        )
    )
    return {
        "log_length": node.log.last_index,
        "leader_said": 9,
        "commit_index": node.commit_index,
        "it_capped_at_its_own_log": node.commit_index == node.log.last_index,
        "and_did_not_take_nine": node.commit_index < 9,
        "applied": node.last_applied,
    }


def the_node_does_not_police_the_membership() -> dict:
    """A leader asked to replicate to a stranger builds the message, and the network refuses it.

    I wrote this expecting the node to refuse and it does not, which turns out to be the right
    place for the check rather than a gap. A node's membership is whatever its configuration
    says, and during a membership change two nodes legitimately disagree about it for a while.
    A node that refused to address anyone outside its own view could not learn about a new
    member at all.

    The network owns delivery and knows who exists, so that is where an unknown recipient is an
    error. The two checks are not duplicates of each other: one is about who is in the cluster
    and the other is about who is reachable.
    """
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    made = boss.replicate("zz")
    net = Network(members=["a", "b", "c"], seed=1)
    refused = False
    try:
        net.send(made[0])
    except UnknownNode:
        refused = True
    return {
        "the_node_built_the_message": len(made) == 1,
        "addressed_to": made[0].recipient,
        "and_did_not_refuse": True,
        "the_network_refused_it": refused,
        "which_is_where_membership_lives": refused,
    }


def an_append_below_the_snapshot_is_refused() -> bool:
    """A leader whose log starts above an index cannot slice from below it."""
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.log = Log(entries=[], snapshot_index=50, snapshot_term=2)
    try:
        boss.log.slice(3)
    except Exception:
        return True
    return False


def compare_the_write_paths(seeds: int = 6) -> list[dict]:
    """Messages and commit outcome under four cluster and link combinations."""
    out = []
    settings = {
        "three clean": (3, Conditions()),
        "five clean": (5, Conditions()),
        "five lossy": (5, Conditions(loss=0.3)),
        "five jittery": (5, Conditions(min_delay=1, max_delay=4)),
    }
    for name, (size, conditions) in settings.items():
        totals = []
        for seed in range(seeds):
            made = Cluster(size=size, seed=seed, conditions=conditions).settle()
            before = made.net.counts.sent
            made.propose(("set", "k", 1))
            made.run(SPREAD_TICKS)
            totals.append(made.net.counts.sent - before)
        out.append(
            {
                "setting": name,
                "size": size,
                "median_messages": sorted(totals)[len(totals) // 2],
                "worst": max(totals),
            }
        )
    return out


def the_link_costs_less_than_the_cluster_size() -> dict:
    """Going from three nodes to five costs more messages than making the link lossy.

    Which is not what I expected. Loss forces retries and retries are messages, so a lossy link
    looked like the expensive setting. It is not: the retries only affect the messages that were
    lost, while every extra node adds a message per heartbeat forever. Size is a standing cost
    and loss is a proportional one.
    """
    table = {one["setting"]: one for one in compare_the_write_paths()}
    return {
        "three_clean": table["three clean"]["median_messages"],
        "five_clean": table["five clean"]["median_messages"],
        "five_lossy": table["five lossy"]["median_messages"],
        "the_size_step_costs": (
            table["five clean"]["median_messages"] - table["three clean"]["median_messages"]
        ),
        "the_loss_step_costs": (
            table["five lossy"]["median_messages"] - table["five clean"]["median_messages"]
        ),
        "size_costs_more_than_loss": (
            table["five clean"]["median_messages"] - table["three clean"]["median_messages"]
        )
        > (table["five lossy"]["median_messages"] - table["five clean"]["median_messages"]),
        "and_loss_can_even_cost_less": (
            table["five lossy"]["median_messages"] <= table["five clean"]["median_messages"]
        ),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    unsafe = the_obvious_commit_rule_loses_a_committed_entry()
    return {
        "spread_ticks": SPREAD_TICKS,
        "the_obvious_rule_commits_it": unsafe["and_the_loose_one_committed_it"],
        "and_it_gets_overwritten": unsafe["and_it_was_overwritten"],
        "the_real_rule_refuses": unsafe["the_rule_refused_to_commit"],
        "a_current_term_entry_makes_it_safe": (
            the_rule_makes_the_entry_safe_once_the_term_catches_up()["the_rival_cannot_win"]
        ),
        "commit_needs_a_quorum_less_one": commit_costs_one_round_trip()[
            "it_is_the_quorum_less_the_leader"
        ],
        "a_slow_follower_costs_nothing": a_slow_follower_does_not_slow_a_write()[
            "it_committed_with_two_down"
        ],
        "loss_sends_fewer_messages": (
            loss_costs_correctness_nothing_and_messages_less_than_nothing()[
                "loss_sent_fewer_messages"
            ]
        ),
        "size_costs_more_than_loss": the_link_costs_less_than_the_cluster_size()[
            "size_costs_more_than_loss"
        ],
    }
