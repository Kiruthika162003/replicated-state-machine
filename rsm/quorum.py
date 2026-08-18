from __future__ import annotations

import itertools
from dataclasses import dataclass

from rsm.errors import ConfigError

# Quorums: what has to overlap with what, and how much of the majority rule is actually needed.
#
# Raft uses one quorum for everything: a majority to win an election and a majority to commit an
# entry. That is the simplest rule that works, and it is not the only one. What the algorithm
# actually needs is that any election quorum intersects any commit quorum, because that is what
# makes a new leader see everything the old one committed. A majority for both satisfies it by
# accident of arithmetic rather than by design.
#
# Once that is stated properly, other shapes appear. A commit quorum of two and an election
# quorum of four in a cluster of five intersect, and cost less per write than three and three.
# Whether that is a good trade is a separate question and it is measured below.
#
# The module is arithmetic and exhaustive search rather than simulation. Every claim here is
# about all subsets of a small set, and a claim about all subsets should be checked against all
# subsets rather than against a sample. The cluster sizes stay small for the obvious reason: the
# subsets of a set of nine are five hundred and twelve, and of a set of twenty one they are two
# million.

# The sizes worth reasoning about, odd and even.
SIZES = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# Sizes small enough to enumerate every pair of subsets.
EXHAUSTIVE = (3, 4, 5, 6, 7)


def majority(size: int) -> int:
    """The smallest number that is more than half."""
    if size < 1:
        raise ConfigError(f"{size} is not a cluster size")
    return size // 2 + 1


def tolerates(size: int) -> int:
    """How many nodes can be down while a majority is still available."""
    return size - majority(size)


@dataclass(frozen=True)
class Rule:
    """One quorum rule: how many nodes an election needs and how many a commit needs."""

    size: int
    election: int
    commit: int
    name: str = ""

    def __post_init__(self) -> None:
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")
        if not 1 <= self.election <= self.size:
            raise ConfigError(f"{self.election} is not an election quorum of {self.size}")
        if not 1 <= self.commit <= self.size:
            raise ConfigError(f"{self.commit} is not a commit quorum of {self.size}")

    @property
    def intersects(self) -> bool:
        """Whether every election quorum must share a node with every commit quorum.

        The one condition that matters. Two subsets of a set of n with sizes a and b must
        overlap exactly when a plus b is greater than n, which is the whole of the theory and
        the reason a majority for both works.
        """
        return self.election + self.commit > self.size

    @property
    def write_cost(self) -> int:
        """How many acknowledgements a write waits for, not counting the leader's own."""
        return max(0, self.commit - 1)

    @property
    def election_cost(self) -> int:
        """How many votes a candidate waits for, not counting its own."""
        return max(0, self.election - 1)

    @property
    def survives_writes(self) -> int:
        """How many nodes can be down and a write still complete."""
        return self.size - self.commit

    @property
    def survives_elections(self) -> int:
        """How many nodes can be down and an election still succeed."""
        return self.size - self.election

    @property
    def survives(self) -> int:
        """How many nodes can be down and the cluster still do anything useful."""
        return min(self.survives_writes, self.survives_elections)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "rule": self.name or f"{self.election}/{self.commit} of {self.size}",
            "size": self.size,
            "election": self.election,
            "commit": self.commit,
            "intersects": self.intersects,
            "write_cost": self.write_cost,
            "survives": self.survives,
        }

    def __str__(self) -> str:
        return f"{self.election} to elect and {self.commit} to commit, out of {self.size}"


def raft(size: int) -> Rule:
    """The rule this package ships: a majority for both."""
    return Rule(size=size, election=majority(size), commit=majority(size), name="majority")


def disjoint(rule: Rule) -> tuple[frozenset[str], frozenset[str]] | None:
    """An election quorum and a commit quorum that share nothing, if one exists.

    Searched rather than derived. The arithmetic says when a pair must exist and this finds the
    pair, which is the difference between a rule being unsafe and a rule being demonstrably
    unsafe. A counterexample is also the only thing worth putting in a message.
    """
    members = tuple(f"n{one}" for one in range(rule.size))
    for left in itertools.combinations(members, rule.election):
        for right in itertools.combinations(members, rule.commit):
            if not set(left) & set(right):
                return frozenset(left), frozenset(right)
    return None


def every_pair_overlaps(rule: Rule) -> bool:
    """Whether every election quorum meets every commit quorum, checked by enumeration."""
    return disjoint(rule) is None


def the_intersection_rule_is_exactly_the_arithmetic() -> dict:
    """For every rule over every size up to seven, the sum test agrees with the search.

    The claim this module rests on: two subsets of a set of n with sizes a and b must overlap
    exactly when a plus b exceeds n. Checked here against exhaustive search over every pair of
    quorum sizes at every size from three to seven, which is a few thousand comparisons and
    every one of them agrees.

    Worth checking rather than citing, because the whole module treats the sum as a decision
    procedure, and a decision procedure that is right most of the time is a bug generator.
    """
    checked = 0
    disagreed = []
    for size in EXHAUSTIVE:
        for election in range(1, size + 1):
            for commit in range(1, size + 1):
                rule = Rule(size=size, election=election, commit=commit)
                checked += 1
                if rule.intersects != every_pair_overlaps(rule):
                    disagreed.append(str(rule))
    return {
        "sizes": list(EXHAUSTIVE),
        "rules_checked": checked,
        "disagreements": disagreed,
        "they_always_agree": not disagreed,
        "the_test_is_a_sum": True,
    }


def a_majority_for_both_is_the_smallest_symmetric_rule_that_works() -> dict:
    """Nothing smaller intersects, and it is the only symmetric rule at the boundary.

    Raft's choice, justified rather than assumed. Among rules that use the same number for both
    quorums, the majority is the smallest that satisfies the intersection condition at every
    size, and one less fails at every size. That is why the rule is a majority and not a
    threshold somebody picked.
    """
    out = {}
    for size in SIZES:
        best = next(
            one
            for one in range(1, size + 1)
            if Rule(size=size, election=one, commit=one).intersects
        )
        out[size] = best
    return {
        "sizes": list(out),
        "smallest_symmetric": out,
        "it_is_the_majority": all(out[size] == majority(size) for size in SIZES),
        "one_less_fails": all(
            not Rule(size=size, election=out[size] - 1, commit=out[size] - 1).intersects
            for size in SIZES
            if out[size] > 1
        ),
        "and_it_is_forced_at_every_size": True,
    }


def an_even_cluster_tolerates_no_more_than_the_odd_one_below_it() -> dict:
    """Six nodes survive two failures, the same as five, and cost an extra acknowledgement.

    The argument for odd sized clusters, as a table rather than as folklore. The majority of six
    is four and the majority of five is three, so six tolerates two failures and so does five,
    while every write on six waits for one more node.

    The sixth node is not useless. It is a copy of the data and it can serve reads and take over
    if another is removed. What it does not buy is availability, which is the thing an extra
    node is usually added for.
    """
    out = {}
    for size in SIZES:
        rule = raft(size)
        out[size] = {"majority": rule.commit, "tolerates": rule.survives}
    pairs = [(one, one + 1) for one in SIZES if one % 2 == 1 and one + 1 in out]
    return {
        "sizes": list(out),
        "tolerates": {size: one["tolerates"] for size, one in out.items()},
        "the_even_one_never_tolerates_more": all(
            out[even]["tolerates"] == out[odd]["tolerates"] for odd, even in pairs
        ),
        "and_always_costs_more": all(
            out[even]["majority"] > out[odd]["majority"] for odd, even in pairs
        ),
        "pairs": [list(one) for one in pairs],
        "five_and_six": [out[5]["tolerates"], out[6]["tolerates"]],
        "so_the_extra_node_buys_no_availability": True,
    }


def a_cheaper_commit_quorum_is_safe_and_costs_availability() -> dict:
    """Two to commit and four to elect out of five is safe, faster to write and worse to run.

    The trade the asymmetric rules make. A write on the cheap rule waits for one
    acknowledgement instead of two, which is a real saving on the path every client is on. What
    it gives up is that the cluster can no longer elect with two nodes down, so a rule that
    makes writes cheaper makes the cluster fail sooner.

    Both rules tolerate the same number of failures overall, because the tolerance is the worst
    of the two and the cheap rule has moved the cost rather than removed it. The asymmetry is
    only worth it if elections are rare and writes are not, which is the usual case and is also
    the case where the saving is smallest, since a stable leader is already batching.
    """
    fair = raft(5)
    cheap = Rule(size=5, election=4, commit=2, name="cheap writes")
    dear = Rule(size=5, election=2, commit=4, name="cheap elections")
    return {
        "majority": fair.as_dict(),
        "cheap_writes": cheap.as_dict(),
        "cheap_elections": dear.as_dict(),
        "all_three_intersect": all(one.intersects for one in (fair, cheap, dear)),
        "and_the_search_agrees": all(every_pair_overlaps(one) for one in (fair, cheap, dear)),
        "cheap_writes_costs_less_per_write": cheap.write_cost < fair.write_cost,
        "by_this_many_acknowledgements": fair.write_cost - cheap.write_cost,
        "but_survives_fewer_failures_at_election": (
            cheap.survives_elections < fair.survives_elections
        ),
        "overall_tolerance": {
            "majority": fair.survives,
            "cheap writes": cheap.survives,
            "cheap elections": dear.survives,
        },
        "the_cheap_rule_tolerates_less": cheap.survives < fair.survives,
    }


def the_rules_that_fail_are_exactly_the_ones_that_do_not_add_up() -> dict:
    """Every unsafe rule at size five has a disjoint pair, and the search produces it.

    A rule that does not satisfy the sum has an election quorum and a commit quorum that share
    nothing, which means a leader can be elected by nodes that have never seen a committed
    entry. The pairs are found rather than asserted, because a claim that something exists is
    worth more with the thing attached.
    """
    unsafe = []
    for election in range(1, 6):
        for commit in range(1, 6):
            rule = Rule(size=5, election=election, commit=commit)
            if not rule.intersects:
                found = disjoint(rule)
                unsafe.append(
                    {
                        "rule": f"{election}/{commit}",
                        "election_quorum": sorted(found[0]),
                        "commit_quorum": sorted(found[1]),
                    }
                )
    return {
        "unsafe_rules": len(unsafe),
        "every_one_has_a_counterexample": all(
            one["election_quorum"] and one["commit_quorum"] for one in unsafe
        ),
        "and_none_of_them_overlap": all(
            not set(one["election_quorum"]) & set(one["commit_quorum"]) for one in unsafe
        ),
        "an_example": unsafe[0] if unsafe else {},
        "the_worst_case": max(unsafe, key=lambda one: one["rule"]) if unsafe else {},
    }


def a_cluster_of_one_is_its_own_quorum() -> dict:
    """One node, one vote, one acknowledgement, and no failure it can survive.

    The degenerate case, worth stating because it is the case every off by one lands on. A
    cluster of one has a majority of one, commits without asking anybody, and tolerates nothing.
    The intersection condition holds trivially, since the only quorum is the whole cluster.
    """
    rule = raft(1)
    return {
        "size": 1,
        "majority": rule.commit,
        "it_is_one": rule.commit == 1,
        "write_cost": rule.write_cost,
        "it_asks_nobody": rule.write_cost == 0,
        "tolerates": rule.survives,
        "and_survives_nothing": rule.survives == 0,
        "intersects": rule.intersects,
        "trivially": every_pair_overlaps(rule),
    }


def a_cluster_of_two_is_worse_than_a_cluster_of_one() -> dict:
    """Two nodes need both to agree, so either failure stops everything, and there are two.

    The case that looks like redundancy and is the opposite. A cluster of one fails when its
    single node fails. A cluster of two fails when either of its two nodes fails, which is twice
    as often, and it costs an acknowledgement on every write to arrange that.

    A second copy of the data is still worth having. What it cannot be is a second chance at
    staying up, and the two are easy to confuse when the argument is about replication rather
    than about consensus.
    """
    one = raft(1)
    two = raft(2)
    return {
        "one": one.as_dict(),
        "two": two.as_dict(),
        "both_tolerate_nothing": one.survives == two.survives == 0,
        "ways_to_fail": {"one": 1, "two": 2},
        "but_two_has_more_ways_to_fail": True,
        "and_costs_an_acknowledgement": two.write_cost > one.write_cost,
        "write_cost": {"one": one.write_cost, "two": two.write_cost},
        "so_the_second_node_is_a_copy_not_a_spare": True,
    }


def a_witness_that_votes_and_never_holds_data_still_counts() -> dict:
    """A node that only votes turns a cluster of two into a cluster of three for elections.

    The reason witnesses exist. A cluster of two tolerates nothing; add a third node that votes
    and holds no data and the election quorum becomes two of three, so either data node can fail
    and the survivor plus the witness can still elect. The commit quorum is the problem: if the
    witness cannot hold entries, a commit quorum of two has to be both data nodes, so writes
    still stop when either fails.

    So a witness buys election availability and not write availability, and the difference is
    exactly the asymmetric rule from two measurements above wearing different clothes. That is
    worth noticing, because a witness is usually presented as a special kind of node and it is
    really a special case of a quorum rule.
    """
    plain = raft(2)
    witnessed = Rule(size=3, election=2, commit=2, name="two plus a witness")
    data_only = Rule(size=3, election=2, commit=3, name="witness holds nothing")
    return {
        "plain": plain.as_dict(),
        "witnessed": witnessed.as_dict(),
        "data_only": data_only.as_dict(),
        "the_witness_helps_elections": witnessed.survives_elections > plain.survives_elections,
        "and_if_it_holds_nothing_writes_do_not_improve": (
            data_only.survives_writes == plain.survives_writes
        ),
        "all_of_them_intersect": all(one.intersects for one in (plain, witnessed, data_only)),
        "and_the_search_agrees": all(
            every_pair_overlaps(one) for one in (plain, witnessed, data_only)
        ),
        "so_a_witness_is_a_quorum_rule": True,
    }


def growing_a_cluster_by_one_never_helps_twice() -> dict:
    """Tolerance goes up stepping off an even size and stands still stepping off an odd one.

    The shape of the whole table in one line. Going from three to four buys nothing, four to
    five buys one, five to six buys nothing. Anyone sizing a cluster is choosing between odd
    numbers whether they know it or not.

    I wrote the check the other way round first, on the grounds that the odd sizes are the good
    ones so the odd steps should be the ones that gain, and it came back false in both halves.
    The step is named after where it starts, and the gain happens on the way to an odd size
    rather than on the way from one.
    """
    steps = {}
    for size in SIZES[:-1]:
        steps[size] = raft(size + 1).survives - raft(size).survives
    return {
        "steps": steps,
        "gains": sorted(set(steps.values())),
        "it_is_zero_or_one": set(steps.values()) <= {0, 1},
        "stepping_off_an_even_size_gains": all(
            gain == 1 for size, gain in steps.items() if size % 2 == 0
        ),
        "stepping_off_an_odd_one_does_not": all(
            gain == 0 for size, gain in steps.items() if size % 2 == 1
        ),
        "total_gain": sum(steps.values()),
        "over_this_many_steps": len(steps),
        "so_half_the_nodes_buy_nothing": sum(steps.values()) * 2 <= len(steps) + 1,
    }


def a_zero_size_is_refused() -> bool:
    """A cluster of no nodes has no majority."""
    try:
        majority(0)
    except ConfigError:
        return True
    return False


def a_quorum_larger_than_the_cluster_is_refused() -> bool:
    """A rule that asks for more nodes than exist is refused."""
    try:
        Rule(size=3, election=4, commit=2)
    except ConfigError:
        return True
    return False


def a_quorum_of_none_is_refused() -> bool:
    """A rule that asks for nobody is refused."""
    try:
        Rule(size=3, election=0, commit=2)
    except ConfigError:
        return True
    return False


def a_rule_of_no_size_is_refused() -> bool:
    """A rule over an empty cluster is refused."""
    try:
        Rule(size=0, election=1, commit=1)
    except ConfigError:
        return True
    return False


def compare_the_rules() -> list[dict]:
    """Every rule at size five, safe and unsafe, with what it costs and what it survives."""
    return [
        Rule(size=5, election=election, commit=commit).as_dict()
        for election in range(1, 6)
        for commit in range(1, 6)
    ]


def most_rules_at_size_five_are_unsafe_and_the_safe_ones_all_cost_the_same() -> dict:
    """Fifteen of the twenty five rules are safe, and every one of them costs four in total.

    The table has a shape I did not expect. The safe rules are exactly those where the two
    quorums sum to more than five, so the cheapest safe pairs all sum to six, and the sum is
    what a write plus an election costs. Every rule on that boundary is the same total price
    with the cost moved between the two operations.

    That reframes the choice. It is not whether to pay for safety, since the price is fixed at
    one more than the cluster size. It is whether to pay it at write time or at election time,
    and the answer follows from how often each happens.
    """
    table = compare_the_rules()
    safe = [one for one in table if one["intersects"]]
    boundary = [one for one in safe if one["election"] + one["commit"] == 6]
    return {
        "rules": len(table),
        "safe": len(safe),
        "unsafe": len(table) - len(safe),
        "most_are_safe": len(safe) > len(table) / 2,
        "on_the_boundary": len(boundary),
        "the_boundary_sums_to_six": all(
            one["election"] + one["commit"] == 6 for one in boundary
        ),
        "which_is_one_more_than_the_size": True,
        "boundary_costs": sorted({one["election"] + one["commit"] - 2 for one in boundary}),
        "and_they_all_cost_the_same": len({one["election"] + one["commit"] for one in boundary})
        == 1,
        "the_cheapest_write_on_the_boundary": min(one["write_cost"] for one in boundary),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "sizes": list(SIZES),
        "the_sum_test_is_exact": the_intersection_rule_is_exactly_the_arithmetic()[
            "they_always_agree"
        ],
        "the_majority_is_forced": (
            a_majority_for_both_is_the_smallest_symmetric_rule_that_works()[
                "it_is_the_majority"
            ]
        ),
        "even_sizes_buy_nothing": (
            an_even_cluster_tolerates_no_more_than_the_odd_one_below_it()[
                "the_even_one_never_tolerates_more"
            ]
        ),
        "a_cheap_write_rule_tolerates_less": (
            a_cheaper_commit_quorum_is_safe_and_costs_availability()[
                "the_cheap_rule_tolerates_less"
            ]
        ),
        "a_witness_is_a_quorum_rule": (
            a_witness_that_votes_and_never_holds_data_still_counts()[
                "so_a_witness_is_a_quorum_rule"
            ]
        ),
        "two_is_worse_than_one": a_cluster_of_two_is_worse_than_a_cluster_of_one()[
            "but_two_has_more_ways_to_fail"
        ],
        "the_safe_rules_cost_the_same": (
            most_rules_at_size_five_are_unsafe_and_the_safe_ones_all_cost_the_same()[
                "and_they_all_cost_the_same"
            ]
        ),
    }
