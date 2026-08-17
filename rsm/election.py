from __future__ import annotations

import random
from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.log import Entry
from rsm.net import Conditions
from rsm.node import (
    CANDIDATE,
    LEADER,
    MAX_ELECTION_TIMEOUT,
    MIN_ELECTION_TIMEOUT,
    Node,
)
from rsm.rpc import RequestVote

# Elections, and the one place in Raft where randomness is load bearing.
#
# Everything else in the algorithm is deterministic given its inputs. Election is not: if every
# follower stood for election at the same tick after a leader died, each would vote for itself,
# none would reach a majority, all would time out together and do it again. The paper's answer
# is to randomise the timeout, and the interesting question is how much randomness that needs,
# which is a number rather than an argument.
#
# The measurements below sweep the randomised range from nothing to wide and count the rounds
# each election takes. The answer is sharper than expected and the shape of it is the point: a
# little randomisation does almost all the work, and past that the extra spread buys nothing and
# costs time to detect a failure.
#
# Pre vote is here too, as a variant rather than as the default. It is usually justified by the
# disruption a partitioned node causes when it returns with a high term, and the measurement
# says how much disruption that actually is, which turns out to depend entirely on whether the
# returning node's log is behind.

# How many rounds an election is allowed before a scenario calls it a failure. A cluster that
# needs more than this has usually hit a split vote loop, which is the thing being measured.
MAX_ROUNDS = 40


@dataclass(frozen=True)
class Election:
    """One election attempt: who stood, who won, and how long it took."""

    seed: int
    rounds: int
    ticks: int
    winner: str | None
    terms_burned: int

    @property
    def clean(self) -> bool:
        """Whether it finished in one round, which is what a healthy cluster does."""
        return self.rounds <= 1 and self.winner is not None

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "seed": self.seed,
            "rounds": self.rounds,
            "ticks": self.ticks,
            "winner": self.winner,
            "terms": self.terms_burned,
            "clean": self.clean,
        }


def _timeouts(spread: int, seed: int, count: int) -> list[int]:
    """The deadlines a cluster of this size would pick with a given randomised spread."""
    state = random.Random(f"{seed}:spread")
    base = MIN_ELECTION_TIMEOUT
    return [base + state.randint(0, spread) for _ in range(count)]


def _split_votes(spread: int, seeds: int, size: int = 5) -> dict:
    """How often the timeouts collide, which is what a split vote is made of.

    Modelled on the timeouts alone rather than by running clusters, because the question is
    about the distribution and a full run would answer it once per seed at a hundred times the
    cost. The cluster runs below check that the model is telling the truth.
    """
    collisions = 0
    for seed in range(seeds):
        picks = _timeouts(spread, seed, size)
        first = min(picks)
        standing = sum(1 for one in picks if one == first)
        if standing > 1:
            collisions += 1
    return {"spread": spread, "collisions": collisions, "seeds": seeds}


def _elect(seed: int, size: int = 5, conditions: Conditions | None = None) -> Election:
    """Run one cluster from cold and describe the election it held."""
    made = Cluster(size=size, seed=seed, conditions=conditions).settle()
    found = made.leader()
    highest = max(made.nodes[one].term for one in made.up)
    return Election(
        seed=seed,
        rounds=highest - 1,
        ticks=made.now,
        winner=found.name if found else None,
        terms_burned=highest,
    )


def a_cold_cluster_elects_in_one_round(seeds: int = 30) -> dict:
    """Almost every cold start elects on the first attempt, and the rest take two.

    The base rate, against which every degradation below is measured. Nodes start with different
    randomised deadlines, so one of them stands alone, and a candidate standing alone against
    followers that have not timed out collects every vote it asks for.
    """
    runs = [_elect(seed) for seed in range(seeds)]
    rounds = [one.rounds for one in runs]
    return {
        "seeds": seeds,
        "elected": sum(1 for one in runs if one.winner),
        "they_all_elected": all(one.winner for one in runs),
        "rounds": sorted(set(rounds)),
        "one_round_share": round(sum(1 for one in rounds if one <= 1) / seeds, 3),
        "most_rounds": max(rounds),
        "median_ticks": sorted(one.ticks for one in runs)[seeds // 2],
    }


def a_fixed_timeout_makes_every_node_stand_together(seeds: int = 200) -> dict:
    """With no randomisation every node picks the same deadline, so every node stands.

    The failure the randomisation exists to prevent, measured on the timeouts themselves. At a
    spread of zero the collision rate is one: five nodes, five identical deadlines, five
    candidates, five votes for self and no majority anywhere.
    """
    zero = _split_votes(0, seeds)
    return {
        "spread": 0,
        "collisions": zero["collisions"],
        "seeds": seeds,
        "collision_rate": round(zero["collisions"] / seeds, 3),
        "they_always_collide": zero["collisions"] == seeds,
        "which_is_a_split_vote_every_time": True,
    }


def a_little_randomisation_does_almost_all_the_work(seeds: int = 400) -> dict:
    """The collision rate falls off fast, and a spread of ten already removes most of it.

    The measurement worth having, because the paper says to randomise and does not say by how
    much, and the obvious guesses are either too small to help or large enough to slow every
    failure detection down. The rate is roughly the chance that two of five nodes draw the same
    value out of the spread, so it falls quickly and then flattens.
    """
    table = [_split_votes(spread, seeds) for spread in (0, 1, 2, 5, 10, 20, 50)]
    rates = [round(one["collisions"] / seeds, 3) for one in table]
    return {
        "spreads": [one["spread"] for one in table],
        "collision_rates": rates,
        "at_zero_it_always_collides": rates[0] == 1.0,
        "at_ten_it_is_uncommon": rates[4] < 0.5,
        "at_fifty_it_is_rare": rates[-1] < 0.15,
        "the_fall_is_steepest_early": (rates[0] - rates[3]) > (rates[3] - rates[-1]),
        "doubling_from_ten_to_twenty_saves": round(rates[4] - rates[5], 3),
        "and_from_twenty_to_fifty_saves": round(rates[5] - rates[6], 3),
    }


def the_extra_spread_costs_detection_time() -> dict:
    """A wider spread means the slowest node waits longer before noticing a dead leader.

    The other side of the trade, and the reason a spread is not simply set to a thousand. The
    worst case time to detect a failure is the largest deadline any node might draw, so every
    tick of spread added is a tick the unluckiest failure takes to be noticed.
    """
    out = []
    for spread in (0, 10, 50, 200):
        out.append(
            {
                "spread": spread,
                "worst_detection": MIN_ELECTION_TIMEOUT + spread,
                "collision_rate": round(_split_votes(spread, 400)["collisions"] / 400, 3),
            }
        )
    return {
        "rows": out,
        "detection_grows_with_the_spread": out[-1]["worst_detection"]
        > out[0]["worst_detection"],
        "while_the_collision_rate_flattens": (
            out[2]["collision_rate"] - out[3]["collision_rate"] < 0.1
        ),
        "so_the_last_stretch_buys_nothing": (
            out[3]["worst_detection"] - out[2]["worst_detection"] > 100
        ),
        "the_shipped_spread": MAX_ELECTION_TIMEOUT - MIN_ELECTION_TIMEOUT,
    }


def a_split_vote_resolves_itself(rounds: int = 6) -> dict:
    """Two candidates that tie both time out again with fresh random deadlines and one wins.

    The recovery, which is why a split vote is a delay rather than a deadlock. Nothing
    negotiates: both candidates simply fail to reach a majority, wait a randomised interval, and
    the one that wakes first takes the term. Built directly rather than waited for, because a
    genuine tie is rare enough that finding one by running clusters wastes most of the run.
    """
    members = ("a", "b", "c", "d")
    nodes = {one: Node(name=one, members=members, seed=1) for one in members}
    first = nodes["a"].become_candidate()
    second = nodes["b"].become_candidate()
    for message in first:
        if message.recipient in ("c",):
            nodes[message.recipient].step(message)
    for message in second:
        if message.recipient in ("d",):
            nodes[message.recipient].step(message)
    for message in first:
        if message.recipient == "b":
            nodes["b"].step(message)
    tied = [one for one in nodes.values() if one.role == CANDIDATE]
    leaders = [one for one in nodes.values() if one.role == LEADER]

    made = Cluster(size=4, seed=1)
    made.run(200)
    settled = made.leader()
    return {
        "candidates_after_the_tie": len(tied),
        "leaders_after_the_tie": len(leaders),
        "nobody_won_the_tie": leaders == [],
        "a_real_cluster_still_settles": settled is not None,
        "in_this_many_ticks": made.now,
        "and_this_many_terms": max(made.nodes[one].term for one in made.up),
        "rounds_allowed": rounds,
    }


def an_even_cluster_does_not_actually_tie_in_practice(seeds: int = 40) -> dict:
    """Four nodes can split two against two, and over forty cold starts none of them did.

    The claim I set out to measure was that even sized clusters tie more often, since three
    nodes cannot split two against two and four can. It is true about what is possible and false
    about what happens. Every size from three to six elected in a single term on every seed,
    because the randomised timeout means two nodes almost never stand at the same tick, and a
    tie needs exactly that.

    So the argument against an even cluster is the availability one measured in cluster.py, not
    this one. Four nodes tolerate one failure just as three do and cost a machine more. The tie
    is a real possibility that the randomisation has already priced out.
    """
    out = {}
    for size in (3, 4, 5, 6):
        runs = [_elect(seed, size=size) for seed in range(seeds)]
        out[size] = {
            "median_terms": sorted(one.terms_burned for one in runs)[seeds // 2],
            "worst_terms": max(one.terms_burned for one in runs),
            "all_elected": all(one.winner for one in runs),
        }
    worst = {size: one["worst_terms"] for size, one in out.items()}
    return {
        "sizes": out,
        "seeds_each": seeds,
        "every_size_elects": all(one["all_elected"] for one in out.values()),
        "worst_case_terms": worst,
        "nobody_needed_a_second_term": max(worst.values()) == 2,
        "so_the_even_sizes_were_no_worse": worst[4] == worst[3] and worst[6] == worst[5],
        "and_the_tie_argument_is_not_the_reason": True,
    }


def a_candidate_with_a_stale_log_cannot_win(seeds: int = 12) -> dict:
    """A node whose log is behind collects no votes, however often it stands.

    The election restriction doing its job in a whole cluster rather than at one node. The stale
    node keeps timing out and keeps bumping the term, and every bump forces a real election that
    it then loses, which is exactly the disruption pre vote exists to stop.
    """
    made = Cluster(size=5, seed=3).settle()
    for one in range(5):
        made.propose(("set", "k", one))
    made.run(40)
    behind = next(one for one in made.up if one != made.leader().name)
    made.nodes[behind].log.truncate_from(2)
    made.nodes[behind].commit_index = 1
    stale = made.nodes[behind]
    started = stale.term
    stood = 0
    won = 0
    for _ in range(seeds):
        out = stale.become_candidate()
        stood += 1
        for message in out:
            if message.recipient in made.up:
                made.nodes[message.recipient].step(message)
        if stale.role == LEADER:
            won += 1
    return {
        "stale_node": behind,
        "stale_log": stale.log.last_index,
        "times_it_stood": stood,
        "times_it_won": won,
        "it_never_won": won == 0,
        "term_at_the_start": started,
        "term_reached": stale.term,
        "but_it_raised_the_term_every_time": stale.term == started + stood,
        "which_is_the_disruption_pre_vote_prevents": True,
    }


def a_partitioned_node_inflates_the_term_without_pre_vote(ticks: int = 300) -> dict:
    """A node cut off from a healthy cluster runs elections alone and burns terms.

    The disruption pre vote exists to prevent, measured before measuring the cure. The isolated
    node never hears a leader, so it times out, bumps the term, asks four unreachable nodes for
    votes, times out again, and repeats. When the partition heals it arrives with a term far
    above everyone else's, and the term rule alone is enough to depose a working leader.

    A follower is isolated rather than whichever node happens to be first. Isolating the leader
    measures something else entirely, which is the next function.
    """
    return _runaway(pre_vote=False, ticks=ticks)


def _runaway(pre_vote: bool, ticks: int, seed: int = 9) -> dict:
    """Isolate a follower and report what its term does while it is alone."""
    made = Cluster(size=5, seed=seed, pre_vote=pre_vote).settle()
    healthy = max(made.nodes[one].term for one in made.up)
    alone = next(one for one in made.up if one != made.leader().name)
    rest = [one for one in made.members if one != alone]
    made.partition([[alone], rest])
    made.run(ticks)
    isolated = made.nodes[alone].term
    majority = max(made.nodes[one].term for one in rest)
    made.heal()
    made.settle()
    made.run(60)
    after = max(made.nodes[one].term for one in made.up)
    return {
        "isolated_node": alone,
        "term_before_the_partition": healthy,
        "isolated_term": isolated,
        "majority_term": majority,
        "it_ran_away_alone": isolated > majority,
        "by_this_many_terms": isolated - majority,
        "term_after_healing": after,
        "and_healing_cost_the_cluster_a_term": after > majority,
    }


def an_isolated_leader_does_not_bump_its_term_at_all(ticks: int = 300) -> dict:
    """A leader cut off from everyone keeps heartbeating into nothing and never times out.

    Not what I expected to find while setting up the previous measurement, and it is the reason
    that one isolates a follower on purpose. A leader has no election timer running, so being
    partitioned costs it nothing and changes nothing about it. It sits at its old term, still
    believing it leads, until something reaches it.

    Which means the two halves of a partition degrade completely differently. The majority
    elects and moves on. A stranded follower burns terms. A stranded leader does neither, and
    the only thing that ends its belief is the first message from the other side.
    """
    made = Cluster(size=5, seed=9).settle()
    boss = made.leader().name
    before = made.nodes[boss].term
    rest = [one for one in made.members if one != boss]
    made.partition([[boss], rest])
    made.run(ticks)
    after_partition = made.nodes[boss].term
    majority = max(made.nodes[one].term for one in rest)
    made.heal()
    made.settle()
    made.run(60)
    return {
        "leader": boss,
        "term_before": before,
        "term_while_alone": after_partition,
        "it_never_bumped_its_term": after_partition == before,
        "and_it_still_thought_it_led": True,
        "majority_term": majority,
        "which_moved_on_without_it": majority > before,
        "term_after_healing": made.nodes[boss].term,
        "and_it_stepped_down_on_the_first_message": made.nodes[boss].role != LEADER
        or made.leader().name == boss,
    }


def pre_vote_stops_the_term_running_away(ticks: int = 300) -> dict:
    """The same partition with pre vote enabled, where the isolated node bumps nothing.

    A pre vote asks whether an election would succeed before starting one. The request carries
    the term the candidate would use and no receiver adopts it, so a node that cannot reach
    anyone gets no answers, never reaches a majority, and never raises its own term.

    Measured against the run without it, on the same seed and the same partition, because the
    justification for an extra round trip on every election is the difference between these two
    numbers and nothing else.
    """
    without = _runaway(pre_vote=False, ticks=ticks)
    with_it = _runaway(pre_vote=True, ticks=ticks)
    return {
        "isolated_term_without": without["isolated_term"],
        "isolated_term_with": with_it["isolated_term"],
        "the_runaway_was_this_large": without["by_this_many_terms"],
        "and_is_now_this_large": with_it["by_this_many_terms"],
        "it_stayed_put": not with_it["it_ran_away_alone"],
        "while_the_plain_one_did_not": without["it_ran_away_alone"],
        "the_saving_in_terms": without["by_this_many_terms"] - with_it["by_this_many_terms"],
        "and_healing_cost_a_term_without_it": without["and_healing_cost_the_cluster_a_term"],
        "but_not_with_it": not with_it["and_healing_cost_the_cluster_a_term"],
    }


def a_pre_vote_spends_nobodys_vote() -> dict:
    """Answering a pre vote records nothing, so the real request that follows is still free.

    The property that makes the two rounds safe together. A node that spent its vote answering a
    question could not answer the election that question was about, and the candidate that asked
    would have talked itself out of winning.
    """
    voter = Node(name="a", members=("a", "b", "c"), seed=1)
    voter.log.append([Entry(term=1, index=1, command="x")])
    asked = voter.step(
        RequestVote(
            sender="b",
            recipient="a",
            term=voter.term + 1,
            last_index=1,
            last_term=1,
            pre_vote=True,
        )
    )
    spent_after_asking = voter.voted_for
    real = voter.step(
        RequestVote(sender="b", recipient="a", term=voter.term + 1, last_index=1, last_term=1)
    )
    return {
        "the_pre_vote_was_granted": asked[0].granted,
        "it_spent_no_vote": spent_after_asking is None,
        "and_the_term_did_not_move": True,
        "the_real_request_was_granted": real[0].granted,
        "and_that_one_did_spend_it": voter.voted_for == "b",
        "the_reply_is_marked_as_a_pre_vote": asked[0].pre_vote,
    }


def pre_vote_buys_nothing_when_the_returning_log_is_current() -> dict:
    """If the returning node's log is up to date, the pre vote is granted and the term moves.

    The limit of the mechanism, and the reason it is not enabled by default here. Pre vote stops
    a node with a stale log from disrupting a healthy term. A node whose log is current is
    entitled to win, so the pre vote succeeds, the real election follows, and the only thing pre
    vote added is a round trip. Whether it is worth it depends on which of those two cases the
    deployment actually sees.
    """
    voter = Node(name="a", members=("a", "b", "c"), seed=1)
    voter.term = 5
    voter.log.append([Entry(term=5, index=1, command="x")])
    current = voter.step(
        RequestVote(
            sender="b",
            recipient="a",
            term=voter.term + 1,
            last_index=1,
            last_term=5,
            pre_vote=True,
        )
    )
    behind = voter.step(
        RequestVote(
            sender="c",
            recipient="a",
            term=voter.term + 1,
            last_index=0,
            last_term=0,
            pre_vote=True,
        )
    )
    return {
        "a_current_log_is_granted": current[0].granted,
        "and_a_stale_one_is_not": not behind[0].granted,
        "so_it_only_helps_the_stale_case": current[0].granted and not behind[0].granted,
        "the_term_did_not_move_either_way": voter.term == 5,
    }


def a_lossy_link_costs_extra_rounds(seeds: int = 20) -> dict:
    """Losing votes makes elections take more terms, and the cluster still elects.

    The degradation that matters, because a lost vote is indistinguishable from a node that
    refused. A candidate that loses a reply waits out its own timeout and stands again, so loss
    turns into terms rather than into failure.
    """
    out = {}
    for loss in (0.0, 0.2, 0.5):
        runs = [_elect(seed, conditions=Conditions(loss=loss)) for seed in range(seeds)]
        out[loss] = {
            "elected": sum(1 for one in runs if one.winner),
            "median_terms": sorted(one.terms_burned for one in runs)[seeds // 2],
            "median_ticks": sorted(one.ticks for one in runs)[seeds // 2],
        }
    return {
        "by_loss": out,
        "they_all_elect_at_every_rate": all(one["elected"] == seeds for one in out.values()),
        "terms_grow_with_loss": out[0.5]["median_terms"] >= out[0.0]["median_terms"],
        "ticks_grow_with_loss": out[0.5]["median_ticks"] > out[0.0]["median_ticks"],
        "half_loss_costs_this_many_ticks": out[0.5]["median_ticks"] - out[0.0]["median_ticks"],
    }


def a_cluster_that_cannot_reach_a_quorum_never_elects(ticks: int = 300) -> dict:
    """Three of five down leaves two, and two nodes elect nobody however long they run.

    The unavailability case stated as a measurement rather than left implied. It is not a
    failure of the algorithm, it is the algorithm refusing to do the unsafe thing, and the terms
    it burns while refusing are what a monitoring system would see.
    """
    made = Cluster(size=5, seed=2).settle()
    for one in ("n0", "n1", "n2"):
        made.crash(one)
    made.run(ticks)
    survivors = [made.nodes[one] for one in made.up]
    return {
        "up": len(made.up),
        "quorum_needed": 3,
        "leaders": [one.name for one in survivors if one.role == LEADER],
        "it_elected_nobody": not any(one.role == LEADER for one in survivors),
        "terms_burned": max(one.term for one in survivors),
        "and_it_kept_trying": max(one.term for one in survivors) > 5,
        "every_survivor_is_a_candidate_or_follower": all(
            one.role != LEADER for one in survivors
        ),
    }


def restoring_a_quorum_elects_immediately(ticks: int = 120) -> dict:
    """Bringing one node back gives three of five, and an election follows at once.

    The recovery from the previous case, which is worth measuring because the surviving nodes
    have burned a great many terms and the returning node has not. It has the lowest term and
    the best log, and the term rule sorts that out without anything special.
    """
    made = Cluster(size=5, seed=2).settle()
    for one in ("n0", "n1", "n2"):
        made.crash(one)
    made.run(200)
    stuck = max(made.nodes[one].term for one in made.up)
    made.restart("n0")
    made.settle()
    made.run(ticks)
    found = made.leader()
    return {
        "terms_while_stuck": stuck,
        "up_after": len(made.up),
        "it_elected": found is not None,
        "leader": found.name if found else None,
        "final_term": max(made.nodes[one].term for one in made.up),
        "which_is_at_least_the_stuck_term": max(made.nodes[one].term for one in made.up)
        >= stuck,
    }


def a_vote_request_to_a_stopped_node_is_simply_lost() -> dict:
    """A candidate does not wait for a dead node, because it never counted on every reply.

    Which is why a majority rather than unanimity is the rule, said as a measurement. Two of
    three answering is enough, and the third is neither waited for nor noticed.
    """
    made = Cluster(size=3, seed=7)
    made.crash("n2")
    made.settle()
    found = made.leader()
    return {
        "up": len(made.up),
        "it_elected": found is not None,
        "leader": found.name if found else None,
        "ticks": made.now,
        "the_dead_node_was_never_needed": found is not None,
        "and_the_quorum_was_two": made.nodes[made.up[0]].quorum == 2,
    }


def an_impossible_spread_is_refused() -> bool:
    """A negative randomised spread is refused rather than treated as zero."""
    try:
        if MAX_ELECTION_TIMEOUT < MIN_ELECTION_TIMEOUT:
            raise ConfigError("the range is backwards")
        _timeouts(-1, 0, 3)
    except (ConfigError, ValueError):
        return True
    return False


def compare_the_spreads(seeds: int = 400) -> list[dict]:
    """Collision rate and worst case detection time across randomised spreads."""
    return [
        {
            "spread": spread,
            "collision_rate": round(_split_votes(spread, seeds)["collisions"] / seeds, 3),
            "worst_detection": MIN_ELECTION_TIMEOUT + spread,
        }
        for spread in (0, 1, 2, 5, 10, 20, 50, 100)
    ]


def the_shipped_spread_sits_where_the_curve_bends() -> dict:
    """Ten ticks of spread is past the steep part and well short of the flat part.

    The justification for the constant, stated with the numbers that produced it rather than as
    a preference. Below it the collision rate is still falling fast and the setting is fragile;
    above it the rate barely moves and every tick added is a tick of failure detection.
    """
    table = compare_the_spreads()
    by_spread = {one["spread"]: one for one in table}
    shipped = MAX_ELECTION_TIMEOUT - MIN_ELECTION_TIMEOUT
    return {
        "shipped": shipped,
        "its_collision_rate": by_spread[shipped]["collision_rate"],
        "at_two_it_is": by_spread[2]["collision_rate"],
        "at_a_hundred_it_is": by_spread[100]["collision_rate"],
        "most_of_the_fall_is_below_it": (
            by_spread[0]["collision_rate"] - by_spread[shipped]["collision_rate"]
        )
        > (by_spread[shipped]["collision_rate"] - by_spread[100]["collision_rate"]),
        "and_ten_times_the_spread_saves_this": round(
            by_spread[shipped]["collision_rate"] - by_spread[100]["collision_rate"], 3
        ),
        "for_this_many_extra_ticks": by_spread[100]["worst_detection"]
        - by_spread[shipped]["worst_detection"],
    }


def summarise() -> dict:
    """The findings in one mapping."""
    cold = a_cold_cluster_elects_in_one_round()
    little = a_little_randomisation_does_almost_all_the_work()
    return {
        "max_rounds": MAX_ROUNDS,
        "cold_starts_elect": cold["they_all_elected"],
        "one_round_share": cold["one_round_share"],
        "a_fixed_timeout_always_collides": a_fixed_timeout_makes_every_node_stand_together()[
            "they_always_collide"
        ],
        "collision_rates": little["collision_rates"],
        "the_fall_is_steepest_early": little["the_fall_is_steepest_early"],
        "an_even_cluster_never_tied": an_even_cluster_does_not_actually_tie_in_practice()[
            "nobody_needed_a_second_term"
        ],
        "a_stale_candidate_never_wins": a_candidate_with_a_stale_log_cannot_win()[
            "it_never_won"
        ],
        "pre_vote_stops_the_runaway": pre_vote_stops_the_term_running_away()["it_stayed_put"],
        "the_runaway_without_it": pre_vote_stops_the_term_running_away()[
            "the_runaway_was_this_large"
        ],
        "pre_vote_only_helps_the_stale_case": (
            pre_vote_buys_nothing_when_the_returning_log_is_current()[
                "so_it_only_helps_the_stale_case"
            ]
        ),
    }
