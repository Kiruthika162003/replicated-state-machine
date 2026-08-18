from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.quorum import majority

# What share of the time the cluster can take a write, against what the arithmetic says.
#
# The usual way to size a cluster is a binomial: if each node is up with probability p, and is
# independent of the others, the chance a majority is up is the sum of the binomial terms from
# the majority upwards. It is a clean formula, it is in every capacity planning document, and
# this module exists to find out how far it is from what a cluster does.
#
# It is wrong in a specific direction and for a specific reason. The formula asks whether a
# majority is up. A cluster needs a majority to be up and to have agreed on a leader, and after
# every failure of the leader there is a stretch where a majority is up and nothing can be
# committed because the election has not finished yet. That stretch is the election timeout, and
# it is missing from the formula entirely.
#
# So the measurement here is availability of writes rather than availability of nodes: the share
# of attempts that actually commit. The difference between that and the binomial is the price of
# consensus, and it is a number nobody writes down.

# How long a run watches, in ticks.
WINDOW = 1200

# How often a write is attempted.
EVERY = 10

# How long a crashed node stays down before it is restarted.
REPAIR = 40


def binomial(size: int, up: float) -> float:
    """The chance a majority is up, given each node is up independently with this chance.

    The textbook formula, written out rather than imported, because the point of the module is
    to disagree with it and a disagreement with something imported is harder to read.
    """
    if size < 1:
        raise ConfigError(f"{size} is not a cluster size")
    if not 0.0 <= up <= 1.0:
        raise ConfigError(f"{up} is not a probability")
    need = majority(size)
    total = 0.0
    for alive in range(need, size + 1):
        total += math.comb(size, alive) * (up**alive) * ((1 - up) ** (size - alive))
    return round(total, 6)


@dataclass
class Watch:
    """What a run saw: how often a write could be taken and how often a majority was up."""

    name: str
    size: int
    attempts: int = 0
    committed: int = 0
    refused: int = 0
    majority_ticks: int = 0
    leader_ticks: int = 0
    node_ticks: int = 0
    ticks: int = 0
    downtime: list[int] = field(default_factory=list)

    @property
    def write_availability(self) -> float:
        """The share of attempted writes that committed, which is what a client sees."""
        if self.attempts == 0:
            return 0.0
        return round(self.committed / self.attempts, 4)

    @property
    def quorum_availability(self) -> float:
        """The share of ticks a majority was running, which is what the formula counts."""
        if self.ticks == 0:
            return 0.0
        return round(self.majority_ticks / self.ticks, 4)

    @property
    def leader_availability(self) -> float:
        """The share of ticks somebody was leading."""
        if self.ticks == 0:
            return 0.0
        return round(self.leader_ticks / self.ticks, 4)

    @property
    def node_availability(self) -> float:
        """The share of the run an average node was up, which is the formula's input."""
        if self.ticks == 0 or self.size == 0:
            return 0.0
        return round(self.node_ticks / (self.ticks * self.size), 4)

    @property
    def predicted(self) -> float:
        """What the binomial says, given the node availability this run actually had."""
        return binomial(self.size, self.node_availability)

    @property
    def gap(self) -> float:
        """How much less available writes are than nodes, which is the cost of the election."""
        return round(self.quorum_availability - self.write_availability, 4)

    @property
    def worst_outage(self) -> int:
        """The longest stretch with no leader."""
        return max(self.downtime, default=0)

    def __bool__(self) -> bool:
        """A watch is good news if every attempted write committed."""
        return self.attempts > 0 and self.committed == self.attempts

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "run": self.name,
            "size": self.size,
            "attempts": self.attempts,
            "committed": self.committed,
            "writes": self.write_availability,
            "quorum": self.quorum_availability,
            "leader": self.leader_availability,
            "nodes": self.node_availability,
            "predicted": self.predicted,
            "gap": self.gap,
            "worst_outage": self.worst_outage,
        }


def watch(
    name: str,
    size: int = 5,
    seed: int = 1,
    window: int = WINDOW,
    failures: int = 6,
    repair: int = REPAIR,
    pre_vote: bool = False,
) -> Watch:
    """Run a cluster while nodes fail and come back, and count what a client would have seen.

    Failures are drawn at fixed ticks from a seeded generator, one node at a time, each down for
    the repair interval. Drawn rather than modelled as a rate because a rate produces a run
    nobody can reproduce, and the whole package is built so that a seed names a run.

    The draw is keyed on the seed alone and not on the run's name. It was keyed on both at
    first, which meant every row of every comparison below was fed a different set of failures,
    so the pre vote run looked perfect and had simply been dealt an easier hand.
    """
    if window < 1:
        raise ConfigError(f"{window} is not a window")
    if failures < 0:
        raise ConfigError(f"{failures} is not a failure count")
    made = Cluster(size=size, seed=seed, pre_vote=pre_vote).settle()
    state = random.Random(f"{seed}:availability")
    schedule = sorted(state.sample(range(50, window - repair), failures))
    victims = [state.choice(made.members) for _ in schedule]
    seen = Watch(name=name, size=size)
    due: dict[int, str] = {}
    outage = 0
    for tick in range(1, window + 1):
        if schedule and tick == schedule[0]:
            schedule.pop(0)
            target = victims.pop(0)
            if target not in made.down:
                made.crash(target)
                due[tick + repair] = target
        back = due.pop(tick, None)
        if back is not None and back in made.down:
            made.restart(back)
        if tick % EVERY == 0:
            seen.attempts += 1
            try:
                made.propose(("set", "k", tick))
                seen.committed += 1
            except NoLeader:
                seen.refused += 1
        made.tick()
        seen.ticks += 1
        seen.node_ticks += len(made.up)
        if len(made.up) >= majority(size):
            seen.majority_ticks += 1
        if made.leader() is not None:
            seen.leader_ticks += 1
            if outage:
                seen.downtime.append(outage)
                outage = 0
        else:
            outage += 1
    if outage:
        seen.downtime.append(outage)
    return seen


SIZES = (3, 5, 7, 9)
SEEDS = 6


def _across(size: int, seeds: int = SEEDS, **rest) -> list[Watch]:
    """The same failure schedule over several seeds, so one lucky run cannot carry a claim."""
    return [watch(f"{size}", size=size, seed=seed, **rest) for seed in range(seeds)]


def the_binomial_gets_better_with_size_and_the_cluster_does_not() -> dict:
    """At nine nodes the formula understates unavailability by four orders of magnitude.

    The table this module exists for. Feed the binomial the node availability each run actually
    had and compare what it predicts with what the writes did.

    At three nodes the formula says ninety eight point eight percent and the cluster manages
    ninety six point four, which is a factor of three in the part that matters. At five it is
    twenty. At seven, four hundred and eighty. At nine, nearly ten thousand.

    The measured availability does improve with size, from ninety six to ninety nine percent,
    and then it stops. The formula does not stop, because every node added multiplies the chance
    that a majority is down and nothing else. What is left over when a majority is up is the
    stretch after a leader dies, and rsm.timing shows that stretch is set by the election timer
    rather than by the cluster size, so adding nodes cannot shrink it.

    Sizing a cluster on the binomial is therefore sizing it against the wrong failure. Past five
    nodes the term the formula computes is not the term that decides the outcome.
    """
    out = {}
    for size in SIZES:
        runs = _across(size)
        measured = sum(one.write_availability for one in runs) / len(runs)
        predicted = sum(one.predicted for one in runs) / len(runs)
        nodes = sum(one.node_availability for one in runs) / len(runs)
        out[size] = {
            "nodes": round(nodes, 4),
            "predicted": round(predicted, 6),
            "measured": round(measured, 4),
            "understated_by": round((1 - measured) / max(1e-9, 1 - predicted), 1),
        }
    return {
        "sizes": sorted(out),
        "table": out,
        "the_formula_always_overstates": all(
            one["predicted"] > one["measured"] for one in out.values()
        ),
        "the_error_grows_with_size": (
            out[9]["understated_by"] > out[7]["understated_by"] > out[3]["understated_by"]
        ),
        "at_three": out[3]["understated_by"],
        "at_nine": out[9]["understated_by"],
        "the_measured_value_plateaus": abs(out[9]["measured"] - out[7]["measured"]) < 0.01,
        "while_the_predicted_one_does_not": out[9]["predicted"] > out[7]["predicted"],
    }


def a_majority_is_up_almost_always_and_writes_still_fail() -> dict:
    """Quorum availability is one and write availability is not, in the same run.

    The gap in its simplest form. With one node down at a time a majority of five is never
    absent, so the quantity the formula computes is exactly one, and writes still fail. Every
    failed write happened while a majority of the cluster was running and willing.

    This is the difference between a replicated store and a consensus one. The data was
    available on a majority throughout; what was missing was agreement about who was allowed to
    write it.
    """
    runs = _across(5)
    perfect = [one for one in runs if one.quorum_availability == 1.0]
    return {
        "runs": len(runs),
        "runs_with_a_permanent_majority": len(perfect),
        "and_most_runs_had_one": len(perfect) >= len(runs) // 2,
        "write_availability_in_those": [one.write_availability for one in perfect],
        "some_of_them_still_lost_writes": any(one.write_availability < 1.0 for one in perfect),
        "quorum_availability_in_those": sorted({one.quorum_availability for one in perfect}),
        "which_is_exactly_one": all(one.quorum_availability == 1.0 for one in perfect),
        "so_the_missing_part_is_agreement": True,
    }


def the_outage_after_a_failure_is_an_election_and_not_a_repair() -> dict:
    """The longest stretch without a leader is a dozen ticks, not the forty a repair takes.

    Worth separating because the two are easy to conflate. A node is down for forty ticks and
    the cluster is leaderless for about a dozen, so the outage is not the failure, it is the
    detection and the election that follow it. Repairing faster would not help; the cluster is
    already serving long before the node comes back.

    That also says which knob matters. Reducing the repair time is an operations question and
    changes nothing here. Reducing the election timeout is the only thing that shortens this
    outage, and rsm.timing measures what it costs to go too far.
    """
    runs = _across(5)
    outages = [one.worst_outage for one in runs if one.worst_outage]
    return {
        "repair_time": REPAIR,
        "worst_outages": sorted(outages),
        "longest": max(outages, default=0),
        "it_is_shorter_than_a_repair": max(outages, default=0) < REPAIR,
        "by_this_factor": round(REPAIR / max(1, max(outages, default=1)), 2),
        "and_it_is_about_an_election_timeout": 5 <= max(outages, default=0) <= 30,
        "runs_with_an_outage": len(outages),
        "out_of": len(runs),
    }


def a_zero_window_is_refused() -> bool:
    """A run of no ticks watches nothing."""
    try:
        watch("x", window=0)
    except ConfigError:
        return True
    return False


def a_negative_failure_count_is_refused() -> bool:
    """Fewer than no failures is refused."""
    try:
        watch("x", failures=-1)
    except ConfigError:
        return True
    return False


def a_probability_outside_the_range_is_refused() -> bool:
    """An availability above one is refused rather than clamped."""
    try:
        binomial(5, 1.5)
    except ConfigError:
        return True
    return False


def a_cluster_of_no_nodes_has_no_majority() -> bool:
    """The formula needs a cluster."""
    try:
        binomial(0, 0.9)
    except ConfigError:
        return True
    return False


def the_formula_agrees_with_itself_at_the_boundaries() -> dict:
    """Perfect nodes give perfect availability, dead nodes give none, at every size.

    The two cases the formula has to get exactly right, since everything between them is
    interpolation over terms that are hard to check by eye. Both come out at the boundary rather
    than near it, which rules out an off by one in the range of the sum.
    """
    perfect = {size: binomial(size, 1.0) for size in SIZES}
    dead = {size: binomial(size, 0.0) for size in SIZES}
    half = {size: binomial(size, 0.5) for size in SIZES}
    return {
        "sizes": list(SIZES),
        "perfect": perfect,
        "all_perfect_are_one": all(one == 1.0 for one in perfect.values()),
        "dead": dead,
        "all_dead_are_zero": all(one == 0.0 for one in dead.values()),
        "half": half,
        "a_coin_flip_gives_about_a_half": all(0.3 < one < 0.7 for one in half.values()),
        "and_an_odd_size_gives_exactly_a_half": half[3] == 0.5,
    }


def a_bigger_cluster_needs_more_of_it_up_to_reach_the_same_number() -> dict:
    """Five nines needs each node up ninety nine point nine percent at three and ninety six at
    nine.

    The direction the formula is right about, stated so the criticism above is not mistaken for
    a claim that the arithmetic is useless. Given independent failures and instant recovery, a
    larger cluster genuinely does tolerate worse nodes.

    Read as a percentage the improvement looks small, under four points across the whole table,
    which is why the allowed downtime is the number to look at instead: it goes from one part in
    a thousand to thirty nine, a factor of thirty nine, and that is the shape of the claim
    people make for larger clusters.

    The point of the earlier measurement is not that this is wrong, it is that it stops being
    the binding constraint long before the numbers get interesting.
    """
    target = 0.99999
    out = {}
    for size in SIZES:
        need = 1.0
        for step in range(1000):
            candidate = 1.0 - step / 1000
            if binomial(size, candidate) >= target:
                need = candidate
            else:
                break
        out[size] = round(need, 3)
    return {
        "target": target,
        "needed_per_node": out,
        "a_larger_cluster_needs_less": out[9] < out[3],
        "at_three": out[3],
        "at_nine": out[9],
        "the_percentage_barely_moves": out[3] - out[9] < 0.05,
        "allowed_downtime": {size: round(1 - one, 4) for size, one in out.items()},
        "but_the_allowed_downtime_grows": round((1 - out[9]) / (1 - out[3]), 1),
        "and_that_is_a_large_factor": (1 - out[9]) / (1 - out[3]) > 10,
        "and_the_formula_is_right_about_that": True,
    }


def compare_the_sizes() -> list[dict]:
    """Every size over the same failure schedule, averaged across seeds."""
    out = []
    for size in SIZES:
        runs = _across(size)
        out.append(
            {
                "size": size,
                "writes": round(sum(one.write_availability for one in runs) / len(runs), 4),
                "quorum": round(sum(one.quorum_availability for one in runs) / len(runs), 4),
                "leader": round(sum(one.leader_availability for one in runs) / len(runs), 4),
                "predicted": round(sum(one.predicted for one in runs) / len(runs), 6),
                "worst_outage": max(one.worst_outage for one in runs),
            }
        )
    return out


def summarise() -> dict:
    """The findings in one mapping."""
    table = the_binomial_gets_better_with_size_and_the_cluster_does_not()
    return {
        "sizes": list(SIZES),
        "seeds": SEEDS,
        "the_formula_always_overstates": table["the_formula_always_overstates"],
        "understated_at_three": table["at_three"],
        "understated_at_nine": table["at_nine"],
        "the_measured_value_plateaus": table["the_measured_value_plateaus"],
        "a_majority_is_up_and_writes_fail": (
            a_majority_is_up_almost_always_and_writes_still_fail()[
                "some_of_them_still_lost_writes"
            ]
        ),
        "the_outage_is_an_election": (
            the_outage_after_a_failure_is_an_election_and_not_a_repair()[
                "and_it_is_about_an_election_timeout"
            ]
        ),
        "and_shorter_than_a_repair": (
            the_outage_after_a_failure_is_an_election_and_not_a_repair()[
                "it_is_shorter_than_a_repair"
            ]
        ),
    }
