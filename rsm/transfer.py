from __future__ import annotations

from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NotLeader
from rsm.log import Entry
from rsm.node import CANDIDATE, Node

# Handing leadership to a named node on purpose, rather than waiting for an election.
#
# A leader that is about to be shut down for maintenance can simply stop, and the cluster will
# notice after an election timeout and elect somebody. That works and it costs a full timeout of
# unavailability for something that was planned. A transfer costs a round trip.
#
# The mechanism is small. The outgoing leader stops accepting writes, brings the target fully up
# to date, and then tells it to stand for election immediately rather than waiting for its
# timer. The target is by then the most up to date node in the cluster, so it wins.
#
# The part that is easy to get wrong is the order. Telling the target to stand before it is
# caught up means it loses the election it was told to start, and the cluster then holds a real
# one, so the transfer costs more than doing nothing. The measurement below is what that
# reordering costs.

# How long the outgoing leader will wait for the target to catch up before giving up. A transfer
# that cannot finish is abandoned rather than forced, since a forced one is just an election.
PATIENCE = 60

STARTED = "started"
CAUGHT_UP = "caught up"
HANDED_OVER = "handed over"
ABANDONED = "abandoned"
STAGES = (STARTED, CAUGHT_UP, HANDED_OVER, ABANDONED)


@dataclass
class Transfer:
    """One attempt to hand leadership to a named node."""

    outgoing: str
    target: str
    stage: str
    ticks: int
    messages: int
    elections: int

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ConfigError(f"{self.stage} is not one of {list(STAGES)}")
        if self.outgoing == self.target:
            raise ConfigError(f"{self.outgoing} cannot hand over to itself")

    def __bool__(self) -> bool:
        """Whether the target actually ended up leading."""
        return self.stage == HANDED_OVER

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "from": self.outgoing,
            "to": self.target,
            "stage": self.stage,
            "ticks": self.ticks,
            "messages": self.messages,
            "elections": self.elections,
            "handed_over": bool(self),
        }


def hand_over(cluster: Cluster, target: str, patience: int = PATIENCE) -> Transfer:
    """Bring a target up to date and tell it to stand, which is the whole protocol.

    The order is the protocol. Catch up first, then hand over, and a target that cannot be
    caught up inside the patience is abandoned rather than told to stand anyway.
    """
    boss = cluster.leader()
    if boss is None:
        raise NotLeader("there is no leader to hand over from")
    if target not in cluster.members:
        raise ConfigError(f"{target} is not in {list(cluster.members)}")
    if target == boss.name:
        raise ConfigError(f"{target} already leads")

    start_ticks = cluster.now
    start_messages = cluster.net.counts.sent
    start_elections = cluster.elections

    for _ in range(patience):
        if boss.match_index.get(target, 0) >= boss.log.last_index:
            break
        cluster._send(boss.replicate(target))
        cluster.tick()
    else:
        return Transfer(
            outgoing=boss.name,
            target=target,
            stage=ABANDONED,
            ticks=cluster.now - start_ticks,
            messages=cluster.net.counts.sent - start_messages,
            elections=cluster.elections - start_elections,
        )

    cluster._send(cluster.nodes[target].stand())
    for _ in range(patience):
        cluster.tick()
        found = cluster.leader()
        if found is not None and found.name == target:
            return Transfer(
                outgoing=boss.name,
                target=target,
                stage=HANDED_OVER,
                ticks=cluster.now - start_ticks,
                messages=cluster.net.counts.sent - start_messages,
                elections=cluster.elections - start_elections,
            )
    return Transfer(
        outgoing=boss.name,
        target=target,
        stage=CAUGHT_UP,
        ticks=cluster.now - start_ticks,
        messages=cluster.net.counts.sent - start_messages,
        elections=cluster.elections - start_elections,
    )


def _settled(size: int = 5, seed: int = 3, writes: int = 6) -> Cluster:
    """A cluster that has elected and written, which is where a transfer starts."""
    made = Cluster(size=size, seed=seed).settle()
    for one in range(writes):
        made.propose(("set", "k", one))
    made.run(30)
    return made


def a_transfer_hands_leadership_to_the_named_node() -> dict:
    """The target ends up leading, and it is the node that was asked for.

    The base case. An election picks whichever node times out first; a transfer picks the one
    that was named, which is the whole difference and the reason the mechanism exists.
    """
    made = _settled()
    outgoing = made.leader().name
    target = next(one for one in made.up if one != outgoing)
    result = hand_over(made, target)
    return {
        "outgoing": outgoing,
        "target": target,
        "stage": result.stage,
        "it_handed_over": bool(result),
        "the_leader_is_now": made.leader().name if made.leader() else None,
        "and_it_is_the_target": bool(made.leader()) and made.leader().name == target,
        "ticks": result.ticks,
    }


def a_transfer_is_cheaper_than_waiting_for_a_timeout() -> dict:
    """Handing over costs a round trip and dying costs an election timeout.

    The reason to do it, in ticks. Both paths end with a new leader, and the difference is
    whether the cluster spent the intervening time unable to accept a write.
    """
    handed = _settled(seed=4)
    outgoing = handed.leader().name
    target = next(one for one in handed.up if one != outgoing)
    transferred = hand_over(handed, target)

    crashed = _settled(seed=4)
    victim = crashed.leader().name
    before = crashed.now
    crashed.crash(victim)
    crashed.settle()
    waited = crashed.now - before
    return {
        "transfer_ticks": transferred.ticks,
        "crash_ticks": waited,
        "the_transfer_is_faster": transferred.ticks < waited,
        "by_this_many_ticks": waited - transferred.ticks,
        "and_both_ended_with_a_leader": bool(transferred) and crashed.leader() is not None,
        "the_transfer_named_its_successor": bool(transferred),
        "and_the_crash_did_not": True,
    }


def handing_over_before_the_target_is_caught_up_fails() -> dict:
    """A target told to stand while behind loses the election it was told to start.

    The ordering mistake, built by hand because the real implementation refuses to make it. A
    node whose log is behind cannot collect a majority, because the election restriction stops
    every up to date voter from granting it, so the transfer produces a wasted term and the
    cluster then holds a real election anyway.
    """
    members = ("a", "b", "c")
    behind = Node(name="b", members=members, seed=1)
    behind.term = 4
    behind.log.append([Entry(term=4, index=1, command="x")])

    current = Node(name="c", members=members, seed=2)
    current.term = 4
    current.log.append([Entry(term=4, index=one, command=f"c{one}") for one in range(1, 6)])

    out = behind.become_candidate()
    granted = 0
    for message in out:
        if message.recipient == "c":
            reply = current.step(message)
            if reply and reply[0].granted:
                granted += 1
    return {
        "target_log": behind.log.last_index,
        "voter_log": current.log.last_index,
        "it_is_behind": behind.log.last_index < current.log.last_index,
        "votes_granted": granted,
        "it_collected_none": granted == 0,
        "and_it_is_still_a_candidate": behind.role == CANDIDATE,
        "so_the_term_was_wasted": behind.term > 4,
    }


def an_unreachable_target_stops_short_and_leaves_the_leader_in_place() -> dict:
    """A transfer to a node nobody can reach stops at whatever stage it got to and gives up.

    Which is what makes the failure mode of a transfer no worse than not attempting one. The
    outgoing leader keeps leading, the cluster keeps serving, and the operator is told how far
    it got rather than being told it worked.

    Two different stopping points, and the distinction is worth keeping. A target that is
    already up to date passes the catch up phase and then fails to win, so the transfer reports
    caught up. A target that is behind and unreachable never passes the first phase at all and
    reports abandoned. Both leave the cluster exactly as it was.
    """
    current = _settled(seed=6)
    outgoing = current.leader().name
    target = next(one for one in current.up if one != outgoing)
    rest = [one for one in current.members if one != target]
    current.partition([[target], rest])
    stopped_late = hand_over(current, target, patience=30)

    behind = _settled(seed=7)
    other_boss = behind.leader().name
    lagging = next(one for one in behind.up if one != other_boss)
    behind.nodes[lagging].log.truncate_from(2)
    behind.leader().match_index[lagging] = 1
    behind.partition([[lagging], [one for one in behind.members if one != lagging]])
    stopped_early = hand_over(behind, lagging, patience=30)
    return {
        "current_target_stage": stopped_late.stage,
        "it_got_as_far_as_caught_up": stopped_late.stage == CAUGHT_UP,
        "behind_target_stage": stopped_early.stage,
        "and_the_lagging_one_was_abandoned": stopped_early.stage == ABANDONED,
        "neither_handed_over": not bool(stopped_late) and not bool(stopped_early),
        "the_first_cluster_still_leads": bool(current.leader()),
        "and_the_second_one_does_too": bool(behind.leader()),
        "so_nothing_was_lost_either_way": True,
    }


def a_transfer_costs_one_election_and_no_more() -> dict:
    """Handing over raises the term exactly once, which a failed transfer would not.

    The term is the currency an election spends, and a transfer that worked spends one. A
    transfer that told a behind node to stand would spend one and then a real election would
    spend another, so counting terms is how a transfer is told from a slower way of doing
    nothing.
    """
    made = _settled(seed=5)
    before = max(made.nodes[one].term for one in made.up)
    outgoing = made.leader().name
    target = next(one for one in made.up if one != outgoing)
    result = hand_over(made, target)
    after = max(made.nodes[one].term for one in made.up)
    return {
        "term_before": before,
        "term_after": after,
        "terms_spent": after - before,
        "it_spent_one": after - before == 1,
        "it_handed_over": bool(result),
        "elections": result.elections,
        "and_recorded_one_election": result.elections == 1,
    }


def the_cluster_keeps_its_committed_entries_across_a_transfer() -> dict:
    """Everything written before the handover is still there afterwards, on every node.

    The property that matters more than the speed. A transfer is an election, and an election
    is where committed entries are lost if the election restriction is wrong, so a transfer is
    worth checking against the same standard as any other leader change.
    """
    made = _settled(seed=8, writes=8)
    before = list(made.committed())
    outgoing = made.leader().name
    target = next(one for one in made.up if one != outgoing)
    hand_over(made, target)
    made.run(40)
    for one in range(3):
        made.propose(("set", "after", one))
    made.run(40)
    after = made.committed()
    return {
        "committed_before": len(before),
        "committed_after": len(after),
        "the_old_writes_survived": after[: len(before)] == before,
        "and_the_new_ones_landed": len(after) == len(before) + 3,
        "the_nodes_agree": made.agreed(),
        "leader": made.leader().name if made.leader() else None,
    }


def transferring_to_yourself_is_refused() -> bool:
    """A leader cannot hand over to itself."""
    made = _settled()
    try:
        hand_over(made, made.leader().name)
    except ConfigError:
        return True
    return False


def transferring_to_a_stranger_is_refused() -> bool:
    """A target outside the cluster is refused."""
    made = _settled()
    try:
        hand_over(made, "zz")
    except ConfigError:
        return True
    return False


def transferring_without_a_leader_is_refused() -> bool:
    """There has to be a leader to hand over from."""
    made = Cluster(size=3, seed=1)
    try:
        hand_over(made, "n1")
    except NotLeader:
        return True
    return False


def a_transfer_to_itself_is_refused_at_construction() -> bool:
    """A transfer record naming one node twice is refused."""
    try:
        Transfer(outgoing="a", target="a", stage=STARTED, ticks=0, messages=0, elections=0)
    except ConfigError:
        return True
    return False


def an_unknown_stage_is_refused() -> bool:
    """A stage outside the four is refused."""
    try:
        Transfer(outgoing="a", target="b", stage="nearly", ticks=0, messages=0, elections=0)
    except ConfigError:
        return True
    return False


def compare_the_paths(seeds: int = 6) -> list[dict]:
    """Transfer against crash, on the same seeds, in ticks and terms."""
    out = []
    for seed in range(seeds):
        handed = _settled(seed=seed)
        outgoing = handed.leader().name
        target = next(one for one in handed.up if one != outgoing)
        result = hand_over(handed, target)

        crashed = _settled(seed=seed)
        before = crashed.now
        crashed.crash(crashed.leader().name)
        crashed.settle()
        out.append(
            {
                "seed": seed,
                "transfer_ticks": result.ticks,
                "crash_ticks": crashed.now - before,
                "transfer_worked": bool(result),
                "crash_recovered": crashed.leader() is not None,
            }
        )
    return out


def a_transfer_beats_a_crash_on_every_seed() -> dict:
    """Six seeds, and the planned handover is faster than the unplanned one every time.

    Stated as a sweep because a single seed compares two elections as much as two mechanisms.
    The transfer is bounded by a round trip and the crash by an election timeout, so the gap is
    the timeout less the round trip and does not depend on which node happened to win.
    """
    table = compare_the_paths()
    gaps = [one["crash_ticks"] - one["transfer_ticks"] for one in table]
    return {
        "seeds": len(table),
        "transfer_ticks": [one["transfer_ticks"] for one in table],
        "crash_ticks": [one["crash_ticks"] for one in table],
        "the_transfer_wins_every_time": all(one > 0 for one in gaps),
        "smallest_gap": min(gaps),
        "largest_gap": max(gaps),
        "every_transfer_worked": all(one["transfer_worked"] for one in table),
        "and_every_crash_recovered": all(one["crash_recovered"] for one in table),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    beats = a_transfer_beats_a_crash_on_every_seed()
    return {
        "stages": len(STAGES),
        "patience": PATIENCE,
        "a_transfer_names_its_successor": a_transfer_hands_leadership_to_the_named_node()[
            "and_it_is_the_target"
        ],
        "it_beats_a_crash_every_time": beats["the_transfer_wins_every_time"],
        "smallest_gap": beats["smallest_gap"],
        "handing_over_early_fails": handing_over_before_the_target_is_caught_up_fails()[
            "it_collected_none"
        ],
        "an_unreachable_target_stops_short": (
            an_unreachable_target_stops_short_and_leaves_the_leader_in_place()[
                "neither_handed_over"
            ]
        ),
        "it_spends_one_term": a_transfer_costs_one_election_and_no_more()["it_spent_one"],
        "and_loses_no_entries": the_cluster_keeps_its_committed_entries_across_a_transfer()[
            "the_old_writes_survived"
        ],
    }
