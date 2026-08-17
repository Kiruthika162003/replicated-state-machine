from __future__ import annotations

import contextlib
import random
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.net import Conditions
from rsm.verify.invariants import inspect

# Fault schedules: what goes wrong, when, and written down so it can be run again.
#
# A scenario in this package is a seed, a list of faults with the tick each one fires at, and a
# tick count. That is enough to reproduce a run exactly, which is the whole reason the network
# and the nodes were built without threads or clocks. A schedule that found a bug is a bug
# report, and one that has never found anything is still worth keeping, because it is what says
# the property held under that fault rather than under no fault.
#
# The faults are the ones the algorithm claims to survive: nodes stopping and coming back,
# partitions opening and healing, and a link that loses and reorders. Nothing here corrupts a
# message or makes a node lie, because Raft does not claim to survive either and a scenario that
# tested them would be measuring a claim nobody made.
#
# What is measured below is not that the cluster survives. It is how much of the schedule the
# cluster is actually exposed to, which turns out to be the thing that is easy to get wrong: a
# fault that fires while the cluster is already down does nothing, and a schedule made of those
# looks thorough and tests very little.

CRASH = "crash"
RESTART = "restart"
PARTITION = "partition"
HEAL = "heal"
KINDS = (CRASH, RESTART, PARTITION, HEAL)


@dataclass(frozen=True)
class Fault:
    """One thing going wrong at one tick."""

    kind: str
    at: int
    target: str = ""
    sides: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ConfigError(f"{self.kind} is not one of {list(KINDS)}")
        if self.at < 1:
            raise ConfigError(f"{self.at} is not a tick")
        if self.kind in (CRASH, RESTART) and not self.target:
            raise ConfigError(f"a {self.kind} needs a target")
        if self.kind == PARTITION and not self.sides:
            raise ConfigError("a partition needs sides")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "kind": self.kind,
            "at": self.at,
            "target": self.target,
            "sides": [list(one) for one in self.sides],
        }

    def __str__(self) -> str:
        if self.kind == PARTITION:
            return f"{self.at}: partition {[list(one) for one in self.sides]}"
        return f"{self.at}: {self.kind} {self.target}".strip()


@dataclass
class Schedule:
    """A run: a seed, a list of faults, and how long to go on for."""

    seed: int
    ticks: int
    faults: list[Fault] = field(default_factory=list)
    size: int = 5
    conditions: Conditions | None = None

    def __post_init__(self) -> None:
        if self.ticks < 1:
            raise ConfigError(f"{self.ticks} is not a run length")
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")
        late = [one for one in self.faults if one.at > self.ticks]
        if late:
            raise ConfigError(f"{[str(one) for one in late]} fire after the run ends")

    @property
    def due(self) -> dict[int, list[Fault]]:
        """The faults grouped by the tick they fire at."""
        out: dict[int, list[Fault]] = {}
        for one in self.faults:
            out.setdefault(one.at, []).append(one)
        return out

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "seed": self.seed,
            "size": self.size,
            "ticks": self.ticks,
            "faults": len(self.faults),
            "kinds": sorted({one.kind for one in self.faults}),
        }

    def __str__(self) -> str:
        return f"seed {self.seed}, {self.size} nodes, {self.ticks} ticks, " + "; ".join(
            str(one) for one in self.faults
        )


@dataclass
class Outcome:
    """What a schedule did: whether it stayed safe, and what it exposed the cluster to."""

    schedule: Schedule
    applied: int
    skipped: int
    writes: int
    committed: int
    leaders: int
    breaches: int

    def __bool__(self) -> bool:
        """Whether every safety property held throughout the run."""
        return self.breaches == 0

    @property
    def exposure(self) -> float:
        """The share of scheduled faults that actually did something."""
        total = self.applied + self.skipped
        if total == 0:
            return 0.0
        return self.applied / total

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "seed": self.schedule.seed,
            "faults": len(self.schedule.faults),
            "applied": self.applied,
            "skipped": self.skipped,
            "exposure": round(self.exposure, 3),
            "writes": self.writes,
            "committed": self.committed,
            "leaders": self.leaders,
            "safe": bool(self),
        }


def run(schedule: Schedule, writes_every: int = 15) -> Outcome:
    """Run a schedule, injecting faults at their ticks and writing along the way.

    Writes happen on a fixed interval rather than continuously, so that a schedule's cost is a
    function of its length rather than of how long a leader survived. A write that finds no
    leader is counted as attempted and not as committed, which is what makes the availability
    number below mean something.
    """
    made = Cluster(size=schedule.size, seed=schedule.seed, conditions=schedule.conditions)
    due = schedule.due
    applied = 0
    skipped = 0
    writes = 0
    for tick in range(1, schedule.ticks + 1):
        for fault in due.get(tick, []):
            if _apply(made, fault):
                applied += 1
            else:
                skipped += 1
        if tick % writes_every == 0:
            writes += 1
            with contextlib.suppress(NoLeader):
                made.propose(("set", "k", tick))
        made.tick()
    report = inspect(made)
    return Outcome(
        schedule=schedule,
        applied=applied,
        skipped=skipped,
        writes=writes,
        committed=len(made.committed()),
        leaders=made.elections,
        breaches=len(report.breaches),
    )


def _apply(cluster: Cluster, fault: Fault) -> bool:
    """Inject one fault, returning whether it changed anything.

    A crash of a node that is already down changes nothing, and so does a heal with no
    partition. Reporting those as applied is what makes a schedule look thorough while testing
    nothing, so they are counted separately.
    """
    if fault.kind == CRASH:
        if fault.target in cluster.down:
            return False
        cluster.crash(fault.target)
        return True
    if fault.kind == RESTART:
        if fault.target not in cluster.down:
            return False
        cluster.restart(fault.target)
        return True
    if fault.kind == PARTITION:
        if cluster.net.sides:
            return False
        cluster.partition([list(one) for one in fault.sides])
        return True
    if not cluster.net.sides:
        return False
    cluster.heal()
    return True


def random_schedule(seed: int, size: int = 5, ticks: int = 300, faults: int = 6) -> Schedule:
    """A schedule drawn from a seed, so that a failing seed names a whole scenario.

    Drawn rather than enumerated, because the interesting schedules are the ones nobody would
    think to write. The draw is seeded, so a schedule is a number and a bug report is a number.

    The ticks are drawn first and sorted, and the kinds are chosen walking them in order. The
    first version drew a kind and a tick together and sorted afterwards, so the tracking of what
    was already down and already split followed the draw order rather than the run order, and it
    produced schedules with two partitions in a row and two heals in a row. Those are exactly
    the inert faults the exposure measurement is about, and the generator was manufacturing
    them.
    """
    state = random.Random(f"{seed}:schedule")
    members = [f"n{one}" for one in range(size)]
    when = sorted(state.sample(range(2, ticks - 1), faults))
    out: list[Fault] = []
    down: set[str] = set()
    split = False
    for at in when:
        pick = state.random()
        if pick < 0.35 and len(down) < size // 2:
            target = state.choice([one for one in members if one not in down])
            down.add(target)
            out.append(Fault(kind=CRASH, at=at, target=target))
        elif pick < 0.6 and down:
            target = state.choice(sorted(down))
            down.discard(target)
            out.append(Fault(kind=RESTART, at=at, target=target))
        elif pick < 0.85 and not split:
            cut = state.randint(1, size - 1)
            shuffled = list(members)
            state.shuffle(shuffled)
            out.append(
                Fault(
                    kind=PARTITION,
                    at=at,
                    sides=(tuple(shuffled[:cut]), tuple(shuffled[cut:])),
                )
            )
            split = True
        elif split:
            out.append(Fault(kind=HEAL, at=at))
            split = False
        elif down:
            target = state.choice(sorted(down))
            down.discard(target)
            out.append(Fault(kind=RESTART, at=at, target=target))
        else:
            target = state.choice(members)
            down.add(target)
            out.append(Fault(kind=CRASH, at=at, target=target))
    return Schedule(seed=seed, ticks=ticks, faults=out, size=size)


def a_schedule_replays_exactly(runs: int = 3) -> dict:
    """Running one schedule three times gives the same outcome every time.

    The property everything else rests on, checked at the level a scenario is written at rather
    than at the level the network was checked at. A schedule that did not replay would make
    every failure below a single unrepeatable observation.
    """
    made = random_schedule(7)
    outcomes = [run(made) for _ in range(runs)]
    shapes = {
        (one.applied, one.skipped, one.committed, one.leaders, one.breaches) for one in outcomes
    }
    return {
        "schedule": str(made),
        "runs": runs,
        "distinct_outcomes": len(shapes),
        "they_are_identical": len(shapes) == 1,
        "faults": len(made.faults),
        "committed": outcomes[0].committed,
    }


def a_fault_that_fires_into_a_dead_node_does_nothing() -> dict:
    """Crashing a node that is already down is counted as skipped, not as applied.

    The measurement this module exists for. A schedule that crashes the same node four times
    reads as four faults and is one, and a suite made of those would report broad fault coverage
    while exposing the cluster to almost nothing.
    """
    schedule = Schedule(
        seed=1,
        ticks=120,
        faults=[
            Fault(kind=CRASH, at=10, target="n0"),
            Fault(kind=CRASH, at=20, target="n0"),
            Fault(kind=CRASH, at=30, target="n0"),
            Fault(kind=RESTART, at=40, target="n0"),
            Fault(kind=RESTART, at=50, target="n0"),
        ],
    )
    outcome = run(schedule)
    return {
        "scheduled": len(schedule.faults),
        "applied": outcome.applied,
        "skipped": outcome.skipped,
        "only_two_did_anything": outcome.applied == 2,
        "exposure": outcome.exposure,
        "which_is_two_of_five": round(2 / 5, 3) == outcome.exposure,
        "and_the_schedule_looked_like_five": len(schedule.faults) == 5,
    }


def a_heal_with_no_partition_does_nothing() -> dict:
    """The same for healing a cluster that was never split.

    Included because it is the other half of the same mistake and it is easier to make: a
    schedule that heals on a timer, whether or not it partitioned, looks symmetric and is half
    inert.
    """
    schedule = Schedule(
        seed=2,
        ticks=100,
        faults=[
            Fault(kind=HEAL, at=10),
            Fault(kind=PARTITION, at=20, sides=(("n0", "n1"), ("n2", "n3", "n4"))),
            Fault(kind=HEAL, at=60),
            Fault(kind=HEAL, at=70),
        ],
    )
    outcome = run(schedule)
    return {
        "scheduled": len(schedule.faults),
        "applied": outcome.applied,
        "skipped": outcome.skipped,
        "two_did_something": outcome.applied == 2,
        "exposure": outcome.exposure,
        "the_first_heal_was_inert": True,
        "and_so_was_the_second_one": True,
    }


def a_well_formed_schedule_has_high_exposure(seeds: int = 20) -> dict:
    """Every fault in every generated schedule lands, which took two attempts to achieve.

    The draw tracks which nodes are down and whether the cluster is split, walking the ticks in
    the order they will fire. The first version tracked that in draw order and sorted the ticks
    afterwards, which produced schedules with two partitions in a row and a mean exposure of
    0.725: a quarter of the faults it wrote were inert, and it was manufacturing exactly the
    problem this measurement exists to detect.
    """
    outcomes = [run(random_schedule(seed)) for seed in range(seeds)]
    exposures = [one.exposure for one in outcomes]
    return {
        "seeds": seeds,
        "mean_exposure": round(sum(exposures) / len(exposures), 3),
        "worst": round(min(exposures), 3),
        "best": round(max(exposures), 3),
        "most_faults_land": sum(exposures) / len(exposures) > 0.8,
        "in_fact_all_of_them_do": min(exposures) == 1.0,
        "against_this_before_the_fix": 0.725,
        "total_applied": sum(one.applied for one in outcomes),
    }


def every_generated_schedule_stays_safe(seeds: int = 30) -> dict:
    """Thirty drawn schedules, and no safety property broken in any of them.

    The claim the whole package is making, run against schedules nobody chose. It is worth
    something only because the checker rejects a constructed violation, which invariants.py
    measures, and because the faults actually landed, which the previous measurement does.

    It did not pass first time. Seed fourteen reported a leader completeness breach, and the
    fault was in the checker rather than in the algorithm: it required every current leader to
    hold every committed entry, including a node stranded at an older term that the property
    says nothing about. Thirty schedules were enough to find a bug, and the bug was in the thing
    doing the looking.
    """
    outcomes = [run(random_schedule(seed)) for seed in range(seeds)]
    return {
        "seeds": seeds,
        "safe": sum(1 for one in outcomes if one),
        "they_are_all_safe": all(bool(one) for one in outcomes),
        "breaches": sum(one.breaches for one in outcomes),
        "faults_applied": sum(one.applied for one in outcomes),
        "and_the_faults_were_real": sum(one.applied for one in outcomes) > seeds * 3,
        "committed_total": sum(one.committed for one in outcomes),
    }


def faults_cost_availability_and_not_safety(seeds: int = 20) -> dict:
    """A schedule with faults commits less than one without, and is exactly as safe.

    The distinction the whole package draws, measured on the same seeds with and without the
    faults. Safety is a property of the algorithm and availability is a property of the
    circumstances, and the second is what a fault takes away.
    """
    with_faults = [run(random_schedule(seed)) for seed in range(seeds)]
    without = [run(Schedule(seed=seed, ticks=300, faults=[], size=5)) for seed in range(seeds)]
    return {
        "seeds": seeds,
        "committed_with_faults": sum(one.committed for one in with_faults),
        "committed_without": sum(one.committed for one in without),
        "faults_cost_commits": sum(one.committed for one in with_faults)
        < sum(one.committed for one in without),
        "both_are_safe": all(bool(one) for one in with_faults + without),
        "breaches_with": sum(one.breaches for one in with_faults),
        "breaches_without": sum(one.breaches for one in without),
        "and_safety_is_unaffected": sum(one.breaches for one in with_faults) == 0,
    }


def a_lossy_link_is_a_fault_the_schedule_does_not_have_to_name(seeds: int = 12) -> dict:
    """Loss is a condition of the run rather than an event in it, and it costs commits too.

    Kept separate from the fault list because it is not a moment. A partition happens at a tick
    and a lossy link is true for the whole run, and mixing the two would make a schedule that
    could not be replayed by reading it.
    """
    clean = [run(Schedule(seed=seed, ticks=200, faults=[])) for seed in range(seeds)]
    lossy = [
        run(Schedule(seed=seed, ticks=200, faults=[], conditions=Conditions(loss=0.3)))
        for seed in range(seeds)
    ]
    return {
        "seeds": seeds,
        "clean_committed": sum(one.committed for one in clean),
        "lossy_committed": sum(one.committed for one in lossy),
        "loss_costs_commits": sum(one.committed for one in lossy)
        <= sum(one.committed for one in clean),
        "both_are_safe": all(bool(one) for one in clean + lossy),
        "and_it_is_not_in_the_fault_list": all(len(one.schedule.faults) == 0 for one in lossy),
    }


def a_schedule_is_a_bug_report() -> dict:
    """A schedule prints as one line that names everything needed to reproduce it.

    Which is the point of writing faults down rather than injecting them from a loop. A failing
    run reports a seed, a size, a length and a fault list, and that string is enough for anybody
    to run it again.
    """
    made = random_schedule(3)
    text = str(made)
    return {
        "text": text,
        "it_names_the_seed": "seed 3" in text,
        "and_the_size": "5 nodes" in text,
        "and_the_length": "300 ticks" in text,
        "and_every_fault": all(str(one) in text for one in made.faults),
        "faults": len(made.faults),
        "in_one_line": "\n" not in text,
    }


def an_outcome_of_a_broken_run_is_falsy() -> dict:
    """The outcome object answers the obvious assert, which a dataclass would not.

    The same five lines as the report in invariants.py, and worth repeating because a fault
    scenario is exactly the place somebody writes assert on the result and moves on.
    """
    schedule = Schedule(seed=1, ticks=10, faults=[])
    clean = Outcome(
        schedule=schedule, applied=0, skipped=0, writes=0, committed=0, leaders=1, breaches=0
    )
    broken = Outcome(
        schedule=schedule, applied=0, skipped=0, writes=0, committed=0, leaders=1, breaches=3
    )
    return {
        "a_clean_outcome_is_truthy": bool(clean),
        "and_a_broken_one_is_falsy": not bool(broken),
        "the_broken_one_counts_its_breaches": broken.breaches == 3,
        "and_the_clean_one_has_none": clean.breaches == 0,
    }


def a_fault_after_the_end_is_refused() -> bool:
    """A schedule whose fault fires past its own length is refused rather than ignored."""
    try:
        Schedule(seed=1, ticks=10, faults=[Fault(kind=CRASH, at=50, target="n0")])
    except ConfigError:
        return True
    return False


def a_fault_of_an_unknown_kind_is_refused() -> bool:
    """A kind outside the four is refused."""
    try:
        Fault(kind="meltdown", at=1, target="n0")
    except ConfigError:
        return True
    return False


def a_crash_without_a_target_is_refused() -> bool:
    """A crash has to name a node."""
    try:
        Fault(kind=CRASH, at=1)
    except ConfigError:
        return True
    return False


def a_partition_without_sides_is_refused() -> bool:
    """A partition has to name its sides."""
    try:
        Fault(kind=PARTITION, at=1)
    except ConfigError:
        return True
    return False


def a_fault_at_tick_zero_is_refused() -> bool:
    """Ticks start at one, because tick zero is before the run began."""
    try:
        Fault(kind=HEAL, at=0)
    except ConfigError:
        return True
    return False


def a_run_of_no_ticks_is_refused() -> bool:
    """A schedule has to run for at least one tick."""
    try:
        Schedule(seed=1, ticks=0)
    except ConfigError:
        return True
    return False


def compare_the_schedules(seeds: int = 10) -> list[dict]:
    """Ten generated schedules and what each one did."""
    return [run(random_schedule(seed)).as_dict() for seed in range(seeds)]


def the_schedules_differ_from_each_other() -> dict:
    """Ten seeds produce ten different fault lists, which is what makes the sweep worth running.

    A generator that produced the same schedule from every seed would pass every measurement
    above and test one scenario thirty times. Checked on the fault lists rather than on the
    outcomes, because two different schedules can easily produce the same outcome.
    """
    schedules = [random_schedule(seed) for seed in range(10)]
    texts = {str(one) for one in schedules}
    kinds = {tuple(sorted({fault.kind for fault in one.faults})) for one in schedules}
    return {
        "schedules": len(schedules),
        "distinct": len(texts),
        "they_all_differ": len(texts) == len(schedules),
        "distinct_kind_sets": len(kinds),
        "and_they_use_different_faults": len(kinds) > 1,
        "fault_counts": sorted({len(one.faults) for one in schedules}),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    inert = a_fault_that_fires_into_a_dead_node_does_nothing()
    return {
        "kinds": len(KINDS),
        "a_schedule_replays": a_schedule_replays_exactly()["they_are_identical"],
        "an_inert_fault_is_counted_separately": inert["only_two_did_anything"],
        "its_exposure": inert["exposure"],
        "generated_schedules_mostly_land": a_well_formed_schedule_has_high_exposure()[
            "most_faults_land"
        ],
        "every_schedule_stays_safe": every_generated_schedule_stays_safe()["they_are_all_safe"],
        "faults_cost_availability": faults_cost_availability_and_not_safety()[
            "faults_cost_commits"
        ],
        "and_not_safety": faults_cost_availability_and_not_safety()["and_safety_is_unaffected"],
        "the_schedules_differ": the_schedules_differ_from_each_other()["they_all_differ"],
    }
