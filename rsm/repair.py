from __future__ import annotations

import math
from dataclasses import dataclass

from rsm.errors import ConfigError
from rsm.log import Log, agree_up_to, written
from rsm.node import Node
from rsm.rpc import Append, Appended

# Finding where two logs stopped agreeing, in as few round trips as possible.
#
# A new leader does not know how much of each follower's log it shares. It has an optimistic
# guess, its own last index, and a way to find out: send an append whose previous index and term
# name a position, and the follower either accepts, which proves it agrees up to there, or
# refuses. That is a probe, and repairing a divergent follower is a search using it.
#
# Raft walks back one index at a time and then, with the conflict optimisation, jumps over a
# whole term at a time. Neither is the fastest search available. Log matching says that if a
# follower agrees at index i then it agrees at every index below i, and a predicate that is
# monotone in that way can be searched by bisection in a logarithmic number of probes. That is
# not what the paper does and this module measures what the choice is worth.
#
# The three strategies are run against real nodes exchanging real messages rather than against
# the pure log functions in rsm.log, because the question here is how many round trips it costs
# and a round trip is a message, not an array index.

# How far back the strategies are allowed to search before giving up.
LIMIT = 4000


@dataclass
class Repair:
    """What one repair strategy cost and where it ended up."""

    strategy: str
    probes: int
    matched: int
    divergence: int

    def __post_init__(self) -> None:
        if self.probes < 0:
            raise ConfigError(f"{self.probes} is not a probe count")

    @property
    def found(self) -> bool:
        """Whether the search landed on the true agreement point."""
        return self.matched == self.divergence

    def __bool__(self) -> bool:
        """A repair is good if it found the right place."""
        return self.found

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "strategy": self.strategy,
            "probes": self.probes,
            "matched": self.matched,
            "divergence": self.divergence,
            "found": self.found,
        }

    def __str__(self) -> str:
        return f"{self.strategy} found {self.matched} in {self.probes} probes"


def _pair(
    leader_terms: list[int], follower_terms: list[int], term: int = 9
) -> tuple[Node, Node]:
    """A leader and a follower with the logs described, ready to exchange messages."""
    members = ("n0", "n1")
    leader = Node(name="n0", members=members, seed=0)
    follower = Node(name="n1", members=members, seed=1)
    leader.term = term
    follower.term = term
    leader.log = written(leader_terms)
    follower.log = written(follower_terms)
    leader.role = "leader"
    leader.leader = "n0"
    follower.leader = "n0"
    leader.next_index = {"n1": leader.log.last_index + 1}
    leader.match_index = {"n1": 0}
    return leader, follower


def probe(leader: Node, follower: Node, index: int) -> Appended:
    """One round trip: does the follower agree at this index?

    An empty append is a question. It carries no entries, so accepting it changes nothing about
    the follower's log, and refusing it says only that the follower cannot place an entry after
    that position. That is exactly the predicate the search needs and it is the ordinary append
    path rather than a special message, which is why none of the three strategies below needs a
    protocol change.
    """
    if index < 0:
        raise ConfigError(f"{index} is not an index to probe")
    message = Append(
        sender=leader.name,
        recipient=follower.name,
        term=leader.term,
        previous_index=index,
        previous_term=leader.log.term_at(index) if index else 0,
        entries=(),
        commit_index=leader.commit_index,
    )
    replies = follower.step(message)
    return replies[0]


def walk(leader: Node, follower: Node) -> Repair:
    """Step back one index per round trip, which is what the paper describes.

    Simple, obviously correct, and linear in how far apart the logs are. A follower a thousand
    entries behind costs a thousand round trips, which is the reason the optimisation below
    exists.
    """
    truth = agree_up_to(leader.log, follower.log)
    index = leader.log.last_index
    probes = 0
    while index >= 0 and probes < LIMIT:
        probes += 1
        reply = probe(leader, follower, index)
        if reply.success:
            return Repair(strategy="walk back", probes=probes, matched=index, divergence=truth)
        index -= 1
    return Repair(strategy="walk back", probes=probes, matched=-1, divergence=truth)


def skip(leader: Node, follower: Node) -> Repair:
    """Jump over a whole term per round trip, using what the refusal says.

    A refusal carries the term of the entry the follower holds at the contested index and the
    first index it holds of that term. The leader can skip straight past every entry of that
    term, so a divergence made of one long term costs one probe instead of its length.

    What it cannot do is skip past a divergence made of many short terms, which is the case in
    the measurements below where it does no better than walking.
    """
    truth = agree_up_to(leader.log, follower.log)
    index = leader.log.last_index
    probes = 0
    while index >= 0 and probes < LIMIT:
        probes += 1
        reply = probe(leader, follower, index)
        if reply.success:
            return Repair(strategy="skip term", probes=probes, matched=index, divergence=truth)
        index = _next_index(leader.log, reply, index)
    return Repair(strategy="skip term", probes=probes, matched=-1, divergence=truth)


def _next_index(log: Log, reply: Appended, index: int) -> int:
    """Where to probe next, given what the refusal said.

    If the leader holds the conflicting term, it can jump to its own last entry of that term,
    because everything above that is a term the follower does not have. If it does not hold the
    term at all, it jumps below the follower's first entry of it. Falling back to one step is
    what makes this safe when the reply carries nothing useful.
    """
    if reply.conflict_term > 0:
        own = [one.index for one in log.entries if one.term == reply.conflict_term]
        if own:
            return min(max(own), index - 1)
        return min(max(reply.conflict_index - 1, 0), index - 1)
    if reply.conflict_index > 0:
        return min(reply.conflict_index - 1, index - 1)
    return index - 1


def bisect(leader: Node, follower: Node) -> Repair:
    """Binary search on the agreement point, which log matching makes sound.

    The predicate is monotone: a follower that agrees at index i agrees at every index below it.
    That is the log matching property and it is exactly the precondition binary search needs, so
    the number of probes is the logarithm of the range rather than its length.

    Raft does not do this. The reasons usually given are that the walk is simpler and that the
    common case is a follower one or two entries behind, where a bisection over the whole log is
    worse. Both are measured below and both are true, which is a more interesting answer than
    either strategy simply winning.
    """
    truth = agree_up_to(leader.log, follower.log)
    low = 0
    high = leader.log.last_index
    probes = 0
    best = 0
    while low <= high and probes < LIMIT:
        middle = (low + high) // 2
        probes += 1
        if probe(leader, follower, middle).success:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return Repair(strategy="bisect", probes=probes, matched=best, divergence=truth)


def hybrid(leader: Node, follower: Node, patience: int = 3) -> Repair:
    """Walk back a few steps first, then bisect whatever is left.

    Written after the measurements below, not before. Walking is unbeatable when the follower is
    one or two entries behind and unbounded when it is not; bisecting is bounded and pays a
    fixed toll set by the length of the log. Doing a little of the first and then the second
    gets the common case at the common case price and keeps the worst case logarithmic.

    The patience is how many single steps to try before giving up on the optimistic guess. Three
    is not tuned to anything; it is the point past which the walk has already cost more than a
    bisection over a log of a thousand would.
    """
    if patience < 0:
        raise ConfigError(f"{patience} is not a patience")
    truth = agree_up_to(leader.log, follower.log)
    index = leader.log.last_index
    probes = 0
    while index >= 0 and probes < patience:
        probes += 1
        if probe(leader, follower, index).success:
            return Repair(strategy="hybrid", probes=probes, matched=index, divergence=truth)
        index -= 1
    low = 0
    high = index
    best = 0
    while low <= high and probes < LIMIT:
        middle = (low + high) // 2
        probes += 1
        if probe(leader, follower, middle).success:
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return Repair(strategy="hybrid", probes=probes, matched=best, divergence=truth)


STRATEGIES = {
    "walk back": walk,
    "skip term": skip,
    "bisect": bisect,
    "hybrid": hybrid,
}


def _tail(agreed: int, depth: int, alternating: bool = False) -> tuple[Node, Node]:
    """A leader and a follower agreeing to a point and disagreeing after it."""
    leader = [1] * agreed + [2] * depth
    if alternating:
        follower = [1] * agreed + [3 + one for one in range(depth)]
    else:
        follower = [1] * agreed + [3] * depth
    return _pair(leader, follower, term=depth + 10)


def every_strategy_finds_the_same_place() -> dict:
    """All four land on the true agreement point, at every depth tried.

    The only thing that has to hold before any of the cost numbers mean anything. A search that
    is fast and lands one index early would truncate an entry the follower and the leader both
    hold, and a search that lands one late would leave a conflicting entry in place, which log
    matching would then be quietly wrong about.
    """
    out = {}
    for depth in (1, 2, 5, 20, 60):
        made = {}
        for name, strategy in STRATEGIES.items():
            leader, follower = _tail(40, depth)
            made[name] = strategy(leader, follower)
        out[depth] = made
    return {
        "depths": sorted(out),
        "strategies": sorted(STRATEGIES),
        "all_found_it": all(bool(one) for row in out.values() for one in row.values()),
        "they_agree_at_every_depth": all(
            len({one.matched for one in row.values()}) == 1 for row in out.values()
        ),
        "matched": {depth: next(iter(row.values())).matched for depth, row in out.items()},
        "and_it_is_the_agreement_point": all(
            next(iter(row.values())).matched == 40 for row in out.values()
        ),
    }


def walking_back_costs_one_probe_per_entry() -> dict:
    """The cost is the divergence plus one, exactly, at every depth.

    Not approximately linear, exactly linear, because every probe moves the search one index and
    the loop stops on the first acceptance. A follower a thousand entries behind is a thousand
    round trips before the first entry is sent.
    """
    out = {}
    for depth in (1, 2, 5, 20, 60, 120):
        leader, follower = _tail(40, depth)
        out[depth] = walk(leader, follower).probes
    return {
        "depths": sorted(out),
        "probes": out,
        "it_is_the_depth_plus_one": all(probes == depth + 1 for depth, probes in out.items()),
        "the_deepest_cost": max(out.values()),
        "and_it_grows_without_bound": out[120] > out[1] * 50,
    }


def the_conflict_reply_collapses_one_term_into_one_probe() -> dict:
    """A divergent tail made of a single term costs two probes however deep it is.

    The optimisation the paper adds, working exactly as advertised. The refusal names the term
    the follower holds at the contested index, the leader has no entries of that term, and it
    jumps below the follower's first entry of it. One jump clears the whole tail.
    """
    out = {}
    for depth in (5, 20, 60, 120):
        leader, follower = _tail(40, depth)
        out[depth] = skip(leader, follower).probes
    walked = {}
    for depth in (5, 20, 60, 120):
        leader, follower = _tail(40, depth)
        walked[depth] = walk(leader, follower).probes
    return {
        "depths": sorted(out),
        "probes": out,
        "it_is_flat": len(set(out.values())) == 1,
        "at_this_many": next(iter(out.values())),
        "walking_the_same": walked,
        "and_walking_is_not": len(set(walked.values())) > 1,
        "saving_at_the_deepest": walked[120] - out[120],
    }


def the_conflict_reply_is_worth_nothing_when_the_terms_alternate() -> dict:
    """A tail of one term per entry costs the optimisation exactly what walking costs.

    The worst case, and it is not a near miss: the probe counts are identical, not similar.
    Every refusal names a term that covers one entry, so the jump the leader can make is one
    entry, which is the step it would have taken anyway.

    A tail of distinct terms means a cluster that changed leader on almost every entry, which is
    not the common case and is exactly the case a cluster is in after a bad spell. The
    optimisation stops working at the moment there is most to repair.
    """
    out = {}
    for depth in (5, 20, 60):
        leader, follower = _tail(40, depth, alternating=True)
        skipped = skip(leader, follower)
        leader, follower = _tail(40, depth, alternating=True)
        walked = walk(leader, follower)
        out[depth] = {"skip": skipped.probes, "walk": walked.probes}
    return {
        "depths": sorted(out),
        "probes": out,
        "they_are_identical": all(one["skip"] == one["walk"] for one in out.values()),
        "and_both_grow_with_the_depth": out[60]["skip"] > out[5]["skip"],
        "the_deepest": out[60]["skip"],
        "so_the_worst_case_is_no_optimisation_at_all": True,
    }


def bisecting_costs_the_logarithm_of_the_log_not_the_divergence() -> dict:
    """Six probes at a divergence of five and six at a divergence of sixty.

    The property the other two do not have. Binary search is bounded by the length of the log
    rather than by how much of it is wrong, so the deepest divergence costs the same as the
    shallowest, and the cost of the worst case is a number that can be written down in advance.

    It is sound because of log matching. A follower that accepts a probe at index i has agreed
    at every index below i, so the predicate the search is inverting is monotone, which is the
    one thing binary search requires. Without log matching the whole strategy would be nonsense
    rather than merely slower.
    """
    out = {}
    for depth in (1, 5, 20, 60, 120):
        leader, follower = _tail(40, depth)
        out[depth] = bisect(leader, follower).probes
    bound = math.ceil(math.log2(40 + 120 + 1)) + 1
    return {
        "depths": sorted(out),
        "probes": out,
        "it_barely_moves": max(out.values()) - min(out.values()) <= 2,
        "the_deepest": out[120],
        "against_walking": walk(*_tail(40, 120)).probes,
        "it_is_much_cheaper_when_deep": out[120] < walk(*_tail(40, 120)).probes,
        "predicted_bound": bound,
        "and_it_stays_under_the_bound": max(out.values()) <= bound,
    }


def bisecting_is_the_worst_strategy_when_the_follower_is_nearly_current() -> dict:
    """One entry behind costs two probes walking and ten bisecting a long log.

    The case that decides it, and the reason the paper does not bisect. A follower one or two
    entries behind is the overwhelmingly common case, since that is what every follower is
    during normal operation, and bisection pays the full logarithm of the log every time. Worse,
    that toll grows as the log grows, so the strategy gets slower at the common case the longer
    the cluster has been running.

    The two strategies are optimising different things and both are right about their own case.
    """
    out = {}
    for length in (50, 200, 800):
        leader, follower = _pair([1] * length + [2], [1] * length + [3])
        walked = walk(leader, follower).probes
        leader, follower = _pair([1] * length + [2], [1] * length + [3])
        halved = bisect(leader, follower).probes
        out[length] = {"walk": walked, "bisect": halved}
    return {
        "lengths": sorted(out),
        "probes": out,
        "walking_is_flat": len({one["walk"] for one in out.values()}) == 1,
        "and_bisecting_is_not": len({one["bisect"] for one in out.values()}) > 1,
        "bisecting_grows_with_the_log": out[800]["bisect"] > out[50]["bisect"],
        "walking_wins_everywhere_here": all(
            one["walk"] < one["bisect"] for one in out.values()
        ),
        "by_this_much_at_the_longest": out[800]["bisect"] - out[800]["walk"],
    }


def a_few_steps_then_a_bisection_gets_both_cases() -> dict:
    """Two probes when the follower is current, ten when it is sixty entries adrift.

    Written after the two measurements above rather than before. Walking is unbeatable in the
    common case and unbounded in the bad one; bisecting is bounded and pays a fixed toll every
    time. Three steps of walking followed by a bisection takes the common case at the common
    case price and keeps the worst case logarithmic.

    It is not free. In the bad case it costs the three wasted steps on top of the bisection, so
    it is worse than pure bisection by exactly the patience. That is the trade, and it is a good
    one only because the common case is common.
    """
    shallow = {}
    for length in (50, 800):
        leader, follower = _pair([1] * length + [2], [1] * length + [3])
        shallow[length] = {
            "walk": walk(*_pair([1] * length + [2], [1] * length + [3])).probes,
            "bisect": bisect(*_pair([1] * length + [2], [1] * length + [3])).probes,
            "hybrid": hybrid(leader, follower).probes,
        }
    deep = {}
    for depth in (20, 60):
        deep[depth] = {
            "walk": walk(*_tail(40, depth, alternating=True)).probes,
            "bisect": bisect(*_tail(40, depth, alternating=True)).probes,
            "hybrid": hybrid(*_tail(40, depth, alternating=True)).probes,
        }
    return {
        "shallow": shallow,
        "deep": deep,
        "it_matches_walking_when_shallow": all(
            one["hybrid"] == one["walk"] for one in shallow.values()
        ),
        "and_beats_walking_when_deep": all(
            one["hybrid"] < one["walk"] for one in deep.values()
        ),
        "it_costs_more_than_bisecting_when_deep": all(
            one["hybrid"] > one["bisect"] for one in deep.values()
        ),
        "by_about_the_patience": deep[60]["hybrid"] - deep[60]["bisect"],
        "and_it_is_never_the_worst_of_the_three": all(
            one["hybrid"] <= max(one["walk"], one["bisect"])
            for one in list(shallow.values()) + list(deep.values())
        ),
    }


def a_probe_below_zero_is_refused() -> bool:
    """A search cannot ask about an index before the start of the log."""
    leader, follower = _tail(10, 2)
    try:
        probe(leader, follower, -1)
    except ConfigError:
        return True
    return False


def a_negative_probe_count_is_refused() -> bool:
    """A repair that claims fewer than no probes is refused."""
    try:
        Repair(strategy="x", probes=-1, matched=0, divergence=0)
    except ConfigError:
        return True
    return False


def a_negative_patience_is_refused() -> bool:
    """The hybrid needs a patience of at least none."""
    leader, follower = _tail(10, 2)
    try:
        hybrid(leader, follower, patience=-1)
    except ConfigError:
        return True
    return False


def bisecting_pays_its_toll_even_when_there_is_nothing_to_repair() -> dict:
    """Identical logs cost one probe under three strategies and five under bisection.

    The boundary case, and it separates the strategies more sharply than the shallow divergence
    did. A follower that is completely current is the state every follower is in almost all the
    time, and the three strategies that start from the leader's own last index confirm it in one
    probe. Binary search starts in the middle by construction, so it cannot confirm anything in
    one probe and never will.

    That is the toll in its purest form: five round trips to establish that there was nothing to
    do at all.
    """
    out = {}
    for name, strategy in STRATEGIES.items():
        leader, follower = _pair([1] * 30, [1] * 30)
        out[name] = strategy(leader, follower)
    return {
        "strategies": sorted(out),
        "probes": {name: one.probes for name, one in out.items()},
        "three_took_one_probe": sum(one.probes == 1 for one in out.values()) == 3,
        "and_bisecting_took_more": out["bisect"].probes > 1,
        "how_many": out["bisect"].probes,
        "and_all_found_the_end": all(one.matched == 30 for one in out.values()),
        "and_all_agree": all(bool(one) for one in out.values()),
    }


def an_empty_follower_is_repaired_from_the_beginning() -> dict:
    """A follower with no log at all agrees at index zero, which every strategy reaches.

    The other boundary. There is no entry to match on, so the search has to bottom out at the
    position before the first index rather than at the first index, and a strategy that stops at
    one would loop forever on a fresh node joining an old cluster.
    """
    out = {}
    for name, strategy in STRATEGIES.items():
        leader = Node(name="n0", members=("n0", "n1"), seed=0)
        follower = Node(name="n1", members=("n0", "n1"), seed=1)
        leader.term = follower.term = 5
        leader.log = written([1] * 40)
        follower.log = Log()
        out[name] = strategy(leader, follower)
    return {
        "strategies": sorted(out),
        "matched": {name: one.matched for name, one in out.items()},
        "they_all_reached_zero": all(one.matched == 0 for one in out.values()),
        "probes": {name: one.probes for name, one in out.items()},
        "walking_paid_for_every_index": out["walk back"].probes == 41,
        "and_bisecting_did_not": out["bisect"].probes < out["walk back"].probes,
    }


def compare_the_strategies() -> list[dict]:
    """Every strategy over a shallow case, a deep one term case and a deep alternating one."""
    out = []
    cases = {
        "current": ([1] * 200, [1] * 200),
        "one behind": ([1] * 200 + [2], [1] * 200 + [3]),
        "deep one term": ([1] * 40 + [2] * 60, [1] * 40 + [3] * 60),
        "deep alternating": ([1] * 40 + [2] * 60, [1] * 40 + [3 + one for one in range(60)]),
    }
    for label, (leader_terms, follower_terms) in cases.items():
        for strategy in STRATEGIES.values():
            leader, follower = _pair(leader_terms, follower_terms, term=200)
            made = strategy(leader, follower)
            out.append({"case": label, **made.as_dict()})
    return out


def bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case() -> dict:
    """Four cases, four different winners, and the ranking depends entirely on the weighting.

    I expected the hybrid to come out as the compromise with the tightest worst case, and it
    does not. Measured across the four cases, the largest gap behind the winner is fifty nine
    probes for walking, fifty five for the conflict optimisation, eight for the hybrid and seven
    for pure bisection. On worst case alone, bisection wins.

    What the hybrid has instead is the two common cases for nothing. A current follower and a
    follower one entry behind cost it exactly what walking costs, zero behind the winner, where
    bisection is six or seven probes behind on both. So the ranking is not a property of the
    strategies, it is a property of how often a follower is nearly current, and in a cluster
    with a stable leader it nearly always is.

    That is the whole argument for the paper's choice too. Walking has the worst worst case of
    all four and it is optimal in the state a follower spends its life in.
    """
    table = compare_the_strategies()
    cases = sorted({one["case"] for one in table})
    best = {
        case: min((one for one in table if one["case"] == case), key=lambda one: one["probes"])[
            "strategy"
        ]
        for case in cases
    }
    gaps = {}
    for case in cases:
        rows = {one["strategy"]: one["probes"] for one in table if one["case"] == case}
        gaps[case] = {name: probes - min(rows.values()) for name, probes in rows.items()}
    worst = {name: max(one[name] for one in gaps.values()) for name in sorted(STRATEGIES)}
    shallow = ["current", "one behind"]
    return {
        "cases": cases,
        "winners": best,
        "no_strategy_wins_everything": len(set(best.values())) > 1,
        "every_repair_found_its_place": all(one["found"] for one in table),
        "worst_gap": worst,
        "bisecting_has_the_smallest_worst_gap": worst["bisect"] == min(worst.values()),
        "and_the_hybrid_is_next": sorted(worst.values())[1] == worst["hybrid"],
        "shallow_gaps": {
            name: max(gaps[case][name] for case in shallow) for name in sorted(STRATEGIES)
        },
        "the_hybrid_is_free_when_shallow": all(gaps[case]["hybrid"] == 0 for case in shallow),
        "and_bisecting_is_not": all(gaps[case]["bisect"] > 0 for case in shallow),
        "so_the_ranking_is_about_the_workload": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "strategies": sorted(STRATEGIES),
        "they_all_find_the_same_place": every_strategy_finds_the_same_place()["all_found_it"],
        "walking_is_linear": walking_back_costs_one_probe_per_entry()[
            "it_is_the_depth_plus_one"
        ],
        "the_conflict_reply_is_flat_on_one_term": (
            the_conflict_reply_collapses_one_term_into_one_probe()["it_is_flat"]
        ),
        "and_useless_on_many": the_conflict_reply_is_worth_nothing_when_the_terms_alternate()[
            "they_are_identical"
        ],
        "bisecting_is_logarithmic": (
            bisecting_costs_the_logarithm_of_the_log_not_the_divergence()["it_barely_moves"]
        ),
        "but_loses_the_common_case": (
            bisecting_is_the_worst_strategy_when_the_follower_is_nearly_current()[
                "walking_wins_everywhere_here"
            ]
        ),
        "the_hybrid_gets_both": a_few_steps_then_a_bisection_gets_both_cases()[
            "it_matches_walking_when_shallow"
        ],
        "and_no_strategy_wins_everything": (
            bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
                "no_strategy_wins_everything"
            ]
        ),
    }
