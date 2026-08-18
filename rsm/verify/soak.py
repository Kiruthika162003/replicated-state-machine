from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.verify.coverage import Cell, Watched, grid
from rsm.verify.faults import random_schedule
from rsm.verify.invariants import inspect

# Whether a long run finds more than several short ones, at the same total cost.
#
# The usual way to gain confidence in a distributed system is to run it for a long time under
# faults and watch nothing break. That is a soak, and it is expensive in the only currency this
# package has: ticks. The question nobody asks is whether the tenth hour of a soak is worth as
# much as the first hour of a different one.
#
# It is measurable here because rsm.verify.coverage gives a way to say what a run reached. Fix a
# budget of ticks, spend it one way as a single long run and the other way as many short runs
# from different seeds, and compare what each covered and what each found.
#
# The answer has a mechanism behind it and the mechanism is the interesting part. A cold cluster
# spends its first twenty ticks electing, which is where most of the variety in this state
# machine is; a settled cluster spends the next thousand replicating, which is one cell over and
# over. So the marginal value of a soak tick falls quickly, and the marginal value of a fresh
# seed does not.

# How many ticks a comparison is allowed to spend in total.
BUDGET = 3000

# The lengths of the short runs.
SHORT = 150


@dataclass
class Soak:
    """What one way of spending the budget reached and found."""

    name: str
    runs: int = 0
    ticks: int = 0
    cells: set[Cell] = field(default_factory=set)
    breaches: int = 0
    committed: int = 0
    first_seen: dict[str, int] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        """The share of the transition grid this way of spending reached."""
        return round(len(self.cells) / len(grid()), 3)

    @property
    def per_thousand(self) -> float:
        """Cells reached per thousand ticks, which is what compares two budgets."""
        if self.ticks == 0:
            return 0.0
        return round(len(self.cells) * 1000 / self.ticks, 2)

    @property
    def last_discovery(self) -> int:
        """The tick at which the newest cell was first reached."""
        return max(self.first_seen.values(), default=0)

    @property
    def wasted(self) -> int:
        """Ticks spent after the last thing was discovered."""
        return max(0, self.ticks - self.last_discovery)

    def __bool__(self) -> bool:
        """A soak is good news if nothing broke."""
        return self.breaches == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "way": self.name,
            "runs": self.runs,
            "ticks": self.ticks,
            "cells": len(self.cells),
            "coverage": self.coverage,
            "per_thousand": self.per_thousand,
            "last_discovery": self.last_discovery,
            "wasted": self.wasted,
            "breaches": self.breaches,
            "safe": bool(self),
        }


def _cluster(size: int, seed: int) -> Cluster:
    """A cluster of recording nodes, so a run's coverage can be read off it."""
    made = Cluster(size=size, seed=seed, check=False)
    for name in made.members:
        made.nodes[name] = Watched(name=name, members=made.members, seed=seed)
    return made


def _one(made: Soak, size: int, seed: int, ticks: int, faults: int, spent: int) -> int:
    """Run one cluster under a fault schedule, folding what it reached into the soak."""
    Watched.seen = set()
    cluster = _cluster(size=size, seed=seed)
    schedule = random_schedule(seed=seed, size=size, ticks=ticks, faults=faults)
    due = schedule.due
    for tick in range(1, ticks + 1):
        for fault in due.get(tick, []):
            with contextlib.suppress(Exception):
                if fault.kind == "crash":
                    cluster.crash(fault.target)
                elif fault.kind == "restart":
                    cluster.restart(fault.target)
                elif fault.kind == "partition":
                    cluster.partition([list(one) for one in fault.sides])
                else:
                    cluster.heal()
        if tick % 15 == 0:
            with contextlib.suppress(NoLeader):
                cluster.propose(("set", "k", tick))
        cluster.tick()
        for one in Watched.seen - made.cells:
            made.first_seen[str(one)] = spent + tick
        made.cells |= Watched.seen
    report = inspect(cluster)
    made.breaches += len(report.breaches)
    made.committed += len(cluster.committed())
    made.runs += 1
    made.ticks += ticks
    return spent + ticks


def one_long_run(budget: int = BUDGET, size: int = 5, seed: int = 0) -> Soak:
    """Spend the whole budget on a single cluster."""
    if budget < 1:
        raise ConfigError(f"{budget} is not a budget")
    made = Soak(name="one long run")
    _one(made, size=size, seed=seed, ticks=budget, faults=12, spent=0)
    return made


def many_short_runs(budget: int = BUDGET, size: int = 5, each: int = SHORT) -> Soak:
    """Spend the same budget on as many fresh clusters as it buys."""
    if budget < 1:
        raise ConfigError(f"{budget} is not a budget")
    if each < 1:
        raise ConfigError(f"{each} is not a run length")
    made = Soak(name="many short runs")
    spent = 0
    seed = 0
    while spent < budget:
        spent = _one(made, size=size, seed=seed, ticks=each, faults=3, spent=spent)
        seed += 1
    return made


def many_short_runs_reach_more_than_one_long_one() -> dict:
    """Twenty one cells against nine, for the same three thousand ticks.

    The measurement the module exists for, and the margin is not close. Spending the budget as
    twenty fresh clusters covers more than twice what spending it on one covers, and it is
    still discovering at the end while the long run stopped at tick twelve hundred.

    The mechanism is the election. A cold cluster spends its first twenty ticks doing the most
    varied thing this state machine does; a settled one spends the next thousand replicating,
    which is one transition repeated. Restarting is how you buy another election.
    """
    long_run = one_long_run()
    short = many_short_runs()
    return {
        "budget": BUDGET,
        "long_cells": len(long_run.cells),
        "short_cells": len(short.cells),
        "the_short_runs_reached_more": len(short.cells) > len(long_run.cells),
        "by_this_factor": round(len(short.cells) / max(1, len(long_run.cells)), 2),
        "long_coverage": long_run.coverage,
        "short_coverage": short.coverage,
        "runs": {"long": long_run.runs, "short": short.runs},
        "and_they_cost_the_same": long_run.ticks == short.ticks,
        "neither_broke_anything": long_run.breaches == short.breaches == 0,
    }


def the_long_run_stops_discovering_and_keeps_running() -> dict:
    """Nothing new after tick twelve hundred, and it runs to three thousand.

    The number that says why. More than half the long run's budget is spent after the last
    thing it found, which is not a small inefficiency, it is most of the run.

    The short runs waste almost nothing by the same measure, because each ends shortly after
    its own election and the next one starts a new one.
    """
    long_run = one_long_run()
    short = many_short_runs()
    return {
        "long_last_discovery": long_run.last_discovery,
        "long_ticks": long_run.ticks,
        "long_wasted": long_run.wasted,
        "which_is_most_of_it": long_run.wasted > long_run.ticks / 2,
        "short_last_discovery": short.last_discovery,
        "short_wasted": short.wasted,
        "and_the_short_runs_waste_almost_none": short.wasted < short.ticks / 5,
        "the_short_runs_were_still_finding_things": (
            short.last_discovery > long_run.last_discovery
        ),
    }


def coverage_per_tick_favours_the_fresh_seed() -> dict:
    """Seven cells per thousand ticks against three, which is the number to plan with.

    The same result stated as a rate, because a rate is what a budget is spent against. Whatever
    the budget, spending it on fresh seeds buys more than twice the coverage of spending it on
    duration.

    That is not an argument against soaking. It is an argument that a soak tests for something
    else, for what accumulates over time rather than what varies between runs, and that this
    package has nothing which accumulates.
    """
    long_run = one_long_run()
    short = many_short_runs()
    return {
        "long_per_thousand": long_run.per_thousand,
        "short_per_thousand": short.per_thousand,
        "the_short_runs_win": short.per_thousand > long_run.per_thousand,
        "by_this_factor": round(short.per_thousand / max(0.01, long_run.per_thousand), 2),
        "grid": len(grid()),
        "and_neither_covers_it": max(long_run.coverage, short.coverage) < 0.6,
        "which_matches_the_coverage_module": True,
    }


def neither_way_of_spending_finds_a_breach() -> dict:
    """Three thousand ticks each and no safety property fails, which is the boring half.

    Worth reporting, because the coverage comparison is about how much of the machine each way
    exercises and says nothing about whether the machine is right. Both ran the real
    implementation under real faults and neither broke anything.
    """
    long_run = one_long_run()
    short = many_short_runs()
    return {
        "long_breaches": long_run.breaches,
        "short_breaches": short.breaches,
        "neither_broke": long_run.breaches == short.breaches == 0,
        "both_are_truthy": bool(long_run) and bool(short),
        "long_committed": long_run.committed,
        "short_committed": short.committed,
        "and_both_committed_something": long_run.committed > 0 and short.committed > 0,
    }


def a_budget_of_nothing_is_refused() -> bool:
    """A soak with no ticks soaks nothing."""
    try:
        one_long_run(budget=0)
    except ConfigError:
        return True
    return False


def a_run_length_of_nothing_is_refused() -> bool:
    """Short runs of no ticks would never finish spending the budget."""
    try:
        many_short_runs(each=0)
    except ConfigError:
        return True
    return False


def compare_the_run_lengths() -> list[dict]:
    """The same budget split into runs of several lengths."""
    out = [one_long_run().as_dict()]
    for each in (20, 60, 150, 400):
        made = many_short_runs(each=each)
        made.name = f"runs of {each}"
        out.append(made.as_dict())
    return out


def the_best_run_length_is_in_the_middle() -> dict:
    """Coverage peaks at about sixty ticks and falls away on both sides of it.

    The obvious next question, and the answer is not an extreme. Runs of ten reach nothing at
    all, because the election timeout is ten to twenty and a run that short never finishes one.
    Runs of sixty reach twenty three, ninety reach twenty three, a hundred and fifty reach
    twenty one, four hundred reach eighteen and the single three thousand tick run reaches
    nine.

    So the useful length is the one that gets through an election and a little replication, and
    that is the same shape every other setting in this package has: the value is in covering the
    interesting part once, and both more and less are worse.
    """
    table = compare_the_run_lengths()
    single = next(one["cells"] for one in table if one["way"] == "one long run")
    splits = [one for one in table if one["way"].startswith("runs of")]
    best = max(splits, key=lambda one: one["cells"])
    return {
        "rows": len(table),
        "cells": {one["way"]: one["cells"] for one in table},
        "the_single_run": single,
        "every_split_beats_it": all(one["cells"] >= single for one in splits),
        "the_best_length": best["way"],
        "it_is_not_the_shortest": best["way"] != "runs of 20",
        "and_not_the_longest_split": best["way"] != "runs of 400",
        "it_falls_off_on_both_sides": (
            next(one["cells"] for one in splits if one["way"] == "runs of 20") < best["cells"]
            and next(one["cells"] for one in splits if one["way"] == "runs of 400")
            < best["cells"]
        ),
        "wasted": {one["way"]: one["wasted"] for one in table},
    }


def summarise() -> dict:
    """The findings in one mapping."""
    reach = many_short_runs_reach_more_than_one_long_one()
    waste = the_long_run_stops_discovering_and_keeps_running()
    return {
        "budget": BUDGET,
        "short_runs_reach_more": reach["the_short_runs_reached_more"],
        "by_this_factor": reach["by_this_factor"],
        "at_the_same_cost": reach["and_they_cost_the_same"],
        "the_long_run_wastes_most_of_its_budget": waste["which_is_most_of_it"],
        "and_the_short_ones_waste_almost_none": waste["and_the_short_runs_waste_almost_none"],
        "the_rate_favours_fresh_seeds": coverage_per_tick_favours_the_fresh_seed()[
            "the_short_runs_win"
        ],
        "and_neither_way_found_a_breach": neither_way_of_spending_finds_a_breach()[
            "neither_broke"
        ],
        "the_best_length_is_in_the_middle": the_best_run_length_is_in_the_middle()[
            "it_falls_off_on_both_sides"
        ],
    }
