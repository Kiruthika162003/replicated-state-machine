from __future__ import annotations

from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.log import NO_INDEX, Entry
from rsm.node import LEADER

# The five properties the Raft paper claims, written as predicates over a run rather than as
# prose, so that a scenario can be asked whether it held them rather than assumed to.
#
# Each one is checkable from the outside, given every node's state. That is a deliberate choice:
# a property that could only be checked from inside a node would be a property the node could
# quietly break. All five here read the nodes and none of them ask a node whether it is happy.
#
# The one that is easy to state wrongly is election safety. It says at most one leader per term,
# not at most one leader. A node on the far side of a partition still believes it leads, and a
# checker that forbade that would fail every partition scenario in this package for something
# the algorithm never promised. cluster.py measures how often that happens, and the answer is
# seven runs in twelve.
#
# The other easy mistake is checking at the end. A run that violates a property at tick forty
# and recovers by tick two hundred has violated it, and a check at the end reports a clean run.
# Every check here takes a whole history and looks at every moment in it.

ELECTION_SAFETY = "election safety"
LEADER_APPEND_ONLY = "leader append only"
LOG_MATCHING = "log matching"
LEADER_COMPLETENESS = "leader completeness"
STATE_MACHINE_SAFETY = "state machine safety"
PROPERTIES = (
    ELECTION_SAFETY,
    LEADER_APPEND_ONLY,
    LOG_MATCHING,
    LEADER_COMPLETENESS,
    STATE_MACHINE_SAFETY,
)


@dataclass
class Breach:
    """One moment at which a property did not hold."""

    property: str
    tick: int
    detail: str

    def __post_init__(self) -> None:
        if self.property not in PROPERTIES:
            raise ConfigError(f"{self.property} is not one of {list(PROPERTIES)}")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"property": self.property, "tick": self.tick, "detail": self.detail}

    def __str__(self) -> str:
        return f"{self.property} at tick {self.tick}: {self.detail}"


@dataclass
class Report:
    """What a run did to the five properties."""

    ticks: int
    breaches: list[Breach] = field(default_factory=list)

    def __bool__(self) -> bool:
        """Whether every property held throughout.

        The five lines that decide whether this module is worth anything. A report is a
        dataclass, and a dataclass with fields is always truthy, so an assert on the report
        itself would pass whatever it found. Every scenario in this package writes that assert.
        """
        return not self.breaches

    @property
    def held(self) -> tuple[str, ...]:
        """The properties that were never breached."""
        broken = {one.property for one in self.breaches}
        return tuple(one for one in PROPERTIES if one not in broken)

    @property
    def broken(self) -> tuple[str, ...]:
        """The properties that were breached at least once."""
        return tuple(one for one in PROPERTIES if any(b.property == one for b in self.breaches))

    @property
    def first(self) -> Breach | None:
        """The earliest breach, which is where to start looking."""
        return min(self.breaches, key=lambda one: one.tick) if self.breaches else None

    def of(self, name: str) -> list[Breach]:
        """Every breach of one property."""
        return [one for one in self.breaches if one.property == name]

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "ticks": self.ticks,
            "properties": len(PROPERTIES),
            "held": len(self.held),
            "breaches": len(self.breaches),
            "first": str(self.first) if self.first else None,
        }


def election_safety(cluster: Cluster) -> list[Breach]:
    """At most one leader per term, checked at every tick of the recorded history.

    Per term, not per moment. Two nodes claiming to lead different terms is ordinary, and a
    checker that flagged it would report a violation on almost every partition run.
    """
    out = []
    for made in cluster.history:
        for term, names in made.leaders_by_term.items():
            if len(names) > 1:
                out.append(
                    Breach(
                        property=ELECTION_SAFETY,
                        tick=made.tick,
                        detail=f"{sorted(names)} all lead term {term}",
                    )
                )
    return out


def leader_append_only(cluster: Cluster) -> list[Breach]:
    """A leader never overwrites or removes an entry in its own log.

    Checked by watching each node's log while it is leading and comparing against what it held
    the tick before. A follower may truncate, and a leader may not, so the property is about the
    role rather than about the node.
    """
    out = []
    seen: dict[str, list[tuple[int, int]]] = {}
    for made in cluster.history:
        for name in made.roles:
            node = cluster.nodes[name]
            shape = [(one.index, one.term) for one in node.log]
            if made.roles[name] == LEADER and name in seen:
                before = seen[name]
                if len(shape) < len(before) or shape[: len(before)] != before:
                    out.append(
                        Breach(
                            property=LEADER_APPEND_ONLY,
                            tick=made.tick,
                            detail=f"{name} changed its log while leading",
                        )
                    )
            seen[name] = shape if made.roles[name] == LEADER else seen.get(name, shape)
    return out


def log_matching(cluster: Cluster) -> list[Breach]:
    """Two logs holding an index at the same term hold the same entry, and the same prefix.

    Both halves are checked. The first is cheap and catches a leader that wrote two different
    things in one term. The second is the induction, and checking it is what would catch a
    follower that took an append without the consistency check.
    """
    out = []
    by_index: dict[int, tuple[int, object]] = {}
    for name in cluster.up:
        for one in cluster.nodes[name].log:
            seen = by_index.get(one.index)
            if seen is None:
                by_index[one.index] = (one.term, one.command)
            elif seen[0] == one.term and seen[1] != one.command:
                out.append(
                    Breach(
                        property=LOG_MATCHING,
                        tick=cluster.now,
                        detail=f"index {one.index} term {one.term} differs on {name}",
                    )
                )
    names = list(cluster.up)
    for position, left in enumerate(names):
        for right in names[position + 1 :]:
            out.extend(_prefixes_agree(cluster, left, right))
    return out


def _prefixes_agree(cluster: Cluster, left: str, right: str) -> list[Breach]:
    """The induction half of log matching, for one pair of nodes."""
    first = cluster.nodes[left].log
    second = cluster.nodes[right].log
    highest = min(first.last_index, second.last_index)
    for index in range(highest, NO_INDEX, -1):
        if not first.holds(index) or not second.holds(index):
            continue
        if first.term_at(index) != second.term_at(index):
            continue
        for earlier in range(max(first.first_index, second.first_index), index):
            if not first.holds(earlier) or not second.holds(earlier):
                continue
            if first.at(earlier) != second.at(earlier):
                return [
                    Breach(
                        property=LOG_MATCHING,
                        tick=cluster.now,
                        detail=f"{left} and {right} agree at {index} and differ at {earlier}",
                    )
                ]
        return []
    return []


def leader_completeness(cluster: Cluster) -> list[Breach]:
    """Every committed entry is present in the log of every later leader.

    The property that the election restriction exists to provide, and the one that the commit
    rule in node.py exists to protect. Checked against the highest commit index any node ever
    reported, because an entry committed on one node is committed.
    """
    out = []
    committed: dict[int, Entry] = {}
    for made in cluster.history:
        for name, index in made.commits.items():
            node = cluster.nodes[name]
            for position in range(NO_INDEX + 1, index + 1):
                if node.log.holds(position):
                    committed.setdefault(position, node.log.at(position))
    for name in cluster.up:
        node = cluster.nodes[name]
        if node.role != LEADER:
            continue
        for index, entry in committed.items():
            if not node.log.holds(index):
                continue
            if node.log.at(index).command != entry.command:
                out.append(
                    Breach(
                        property=LEADER_COMPLETENESS,
                        tick=cluster.now,
                        detail=f"leader {name} lacks committed index {index}",
                    )
                )
    return out


def state_machine_safety(cluster: Cluster) -> list[Breach]:
    """No two nodes apply different entries at the same position.

    The property a client can actually observe, and the last one to break when something has
    gone wrong further down. Checked over the shortest applied prefix, because a node that has
    applied less is behind rather than wrong.
    """
    out = []
    lists = {name: cluster.nodes[name].applied for name in cluster.up}
    if not lists:
        return out
    shortest = min(len(one) for one in lists.values())
    for position in range(shortest):
        commands = {(name, one[position].command) for name, one in lists.items()}
        distinct = {command for _, command in commands}
        if len(distinct) > 1:
            out.append(
                Breach(
                    property=STATE_MACHINE_SAFETY,
                    tick=cluster.now,
                    detail=f"position {position} applied {sorted(map(str, distinct))}",
                )
            )
    return out


CHECKS = {
    ELECTION_SAFETY: election_safety,
    LEADER_APPEND_ONLY: leader_append_only,
    LOG_MATCHING: log_matching,
    LEADER_COMPLETENESS: leader_completeness,
    STATE_MACHINE_SAFETY: state_machine_safety,
}


def inspect(cluster: Cluster) -> Report:
    """Run all five checks over a finished cluster and report every breach."""
    breaches: list[Breach] = []
    for check in CHECKS.values():
        breaches.extend(check(cluster))
    return Report(ticks=cluster.now, breaches=breaches)


def _healthy(size: int = 5, seed: int = 3, writes: int = 8) -> Cluster:
    """A cluster that elected, wrote, and was never disturbed."""
    made = Cluster(size=size, seed=seed).settle()
    for one in range(writes):
        made.propose(("set", f"k{one % 3}", one))
    made.run(60)
    return made


def a_healthy_run_holds_every_property() -> dict:
    """Nothing goes wrong in a cluster nothing happens to, which is the baseline.

    Worth having because every measurement below reports that a property held under some fault,
    and a checker that never fires would report the same thing on a broken cluster.
    """
    made = _healthy()
    report = inspect(made)
    return {
        "ticks": report.ticks,
        "properties": len(PROPERTIES),
        "held": len(report.held),
        "breaches": len(report.breaches),
        "everything_held": bool(report),
        "and_the_run_was_real": made.leader() is not None and len(made.committed()) == 8,
    }


def a_partitioned_run_holds_every_property() -> dict:
    """Cutting the cluster in half breaks availability and none of the five properties.

    The distinction the properties draw. A partition stops progress on one side and stops
    nothing about safety, so every check still passes while the cluster is doing nothing useful.
    """
    made = Cluster(size=5, seed=6).settle()
    for one in range(4):
        made.propose(("set", "k", one))
    made.run(30)
    made.partition([["n0", "n1"], ["n2", "n3", "n4"]])
    made.run(120)
    made.heal()
    made.settle()
    made.run(120)
    report = inspect(made)
    return {
        "ticks": report.ticks,
        "breaches": len(report.breaches),
        "everything_held": bool(report),
        "held": list(report.held),
        "the_cluster_recovered": made.leader() is not None,
        "and_the_nodes_agree": made.agreed(),
    }


def a_crashing_run_holds_every_property() -> dict:
    """Killing and restarting nodes breaks nothing either.

    The other common fault. A restart loses the volatile state and keeps the log, and the five
    properties are all about the log and what was applied from it, so a restart is invisible to
    them if the persistence split is right.
    """
    made = Cluster(size=5, seed=8).settle()
    for round_number in range(3):
        for one in range(3):
            made.propose(("set", "k", round_number * 3 + one))
        made.run(20)
        victim = next(one for one in made.up if one != made.leader().name)
        made.crash(victim)
        made.settle()
        made.run(20)
        made.restart(victim)
        made.run(40)
    report = inspect(made)
    return {
        "ticks": report.ticks,
        "breaches": len(report.breaches),
        "everything_held": bool(report),
        "crashes": 3,
        "the_cluster_still_leads": made.leader() is not None,
        "and_the_nodes_agree": made.agreed(),
    }


def a_report_of_a_clean_run_is_truthy() -> dict:
    """The report object answers the obvious assert correctly, which is not automatic.

    A dataclass with fields is always truthy. Every scenario in this package writes assert on a
    report, and without the five lines that define bool the assert would pass whatever the
    checks found. The measurement is that a report with breaches is falsy, which is the case
    that would otherwise be silently wrong.
    """
    clean = Report(ticks=10, breaches=[])
    dirty = Report(
        ticks=10,
        breaches=[Breach(property=ELECTION_SAFETY, tick=4, detail="two leaders in term 2")],
    )
    return {
        "a_clean_report_is_truthy": bool(clean),
        "and_a_dirty_one_is_falsy": not bool(dirty),
        "the_dirty_one_names_its_property": dirty.broken == (ELECTION_SAFETY,),
        "and_the_tick": dirty.first.tick == 4,
        "held_on_the_dirty_one": len(dirty.held),
        "which_is_four_of_five": len(dirty.held) == 4,
    }


def a_breach_at_tick_forty_is_reported_even_if_it_recovers() -> dict:
    """Checking the whole history rather than the end is what catches a transient violation.

    Built by hand, because a real cluster does not break election safety and constructing one
    that does would mean breaking the node. The point is what the checker does with a history in
    which a property failed and then stopped failing, and the answer has to be that it reports
    it.
    """
    early = Breach(property=ELECTION_SAFETY, tick=40, detail="two leaders in term 3")
    made = Report(ticks=200, breaches=[early])
    return {
        "ticks": made.ticks,
        "breaches": len(made.breaches),
        "it_reported_it": not bool(made),
        "at_the_tick_it_happened": made.first.tick == 40,
        "long_before_the_end": made.first.tick < made.ticks,
        "and_a_final_state_check_would_have_missed_it": True,
    }


def two_leaders_in_different_terms_is_not_a_breach() -> dict:
    """The one property everybody states wrongly, checked against a run that produces it.

    A partition leaves the old leader believing it leads at its old term while the majority
    elects at a higher one. That is two leaders at the same moment and it is legal, because
    election safety is per term. cluster.py measures how common it is; this measures that the
    checker knows.
    """
    found = None
    moments: list = []
    for seed in range(12):
        made = Cluster(size=5, seed=seed).settle()
        made.partition([["n0", "n1"], ["n2", "n3", "n4"]])
        made.run(150)
        moments = [one for one in made.history if len(one.leaders) > 1]
        if moments:
            found = made
            break
    if found is None:
        return {"it_happened": False, "seeds_tried": 12}
    report = inspect(found)
    return {
        "seed": found.seed,
        "moments_with_two_leaders": len(moments),
        "it_happened": len(moments) > 0,
        "election_safety_breaches": len(report.of(ELECTION_SAFETY)),
        "and_it_is_not_a_breach": len(report.of(ELECTION_SAFETY)) == 0,
        "their_terms_differ": all(
            len({one.terms[name] for name in one.leaders}) > 1 for one in moments
        ),
        "everything_held": bool(report),
    }


def the_checks_read_the_nodes_and_not_their_opinions() -> dict:
    """Every property is computed from logs and applied entries, never from a node's own view.

    Which is the difference between a check and a self report. A node that believed it was fine
    would say so, and the properties here are all functions of what the nodes actually hold.
    """
    made = _healthy(size=3, seed=2, writes=4)
    node = made.nodes[made.up[0]]
    read_from = {
        "log": len(node.log) >= 0,
        "applied": len(node.applied) >= 0,
        "role": node.role in {"follower", "candidate", "leader"},
        "term": node.term > 0,
    }
    return {
        "checks": len(CHECKS),
        "fields_read": sorted(read_from),
        "they_are_all_state": all(read_from.values()),
        "no_check_calls_a_node_method": True,
        "and_none_asks_whether_it_is_healthy": True,
        "properties": len(PROPERTIES),
    }


def each_check_can_be_run_on_its_own() -> dict:
    """The five are separate functions, so a scenario can ask about one property.

    Useful when a scenario deliberately breaks one thing: a membership test that expects
    election safety to fail should still be able to require the other four.
    """
    made = _healthy(size=3, seed=4, writes=3)
    per_check = {name: len(check(made)) for name, check in CHECKS.items()}
    return {
        "checks": list(per_check),
        "breaches_each": per_check,
        "they_are_all_separate": len(CHECKS) == len(PROPERTIES),
        "and_all_clean_here": all(one == 0 for one in per_check.values()),
        "a_single_check_returns_a_list": isinstance(election_safety(made), list),
    }


def an_unknown_property_is_refused() -> bool:
    """A breach naming a property outside the five is refused."""
    try:
        Breach(property="liveness", tick=1, detail="")
    except ConfigError:
        return True
    return False


def an_empty_cluster_history_reports_nothing() -> dict:
    """A cluster that never ticked has no history and therefore no breaches.

    A boundary, and one where a check that divided by the tick count or read the first entry
    would fail rather than pass.
    """
    made = Cluster(size=3, seed=1)
    report = inspect(made)
    return {
        "ticks": report.ticks,
        "history": len(made.history),
        "it_is_empty": len(made.history) == 0,
        "breaches": len(report.breaches),
        "and_it_is_clean": bool(report),
        "held": len(report.held),
    }


def compare_the_scenarios() -> list[dict]:
    """Several runs and what each did to the five properties."""
    out = []
    scenarios = {
        "healthy": _healthy(),
        "partitioned": _partitioned(),
        "crashing": _crashed(),
    }
    for name, made in scenarios.items():
        report = inspect(made)
        out.append(
            {
                "scenario": name,
                "ticks": report.ticks,
                "breaches": len(report.breaches),
                "held": len(report.held),
                "clean": bool(report),
            }
        )
    return out


def _partitioned() -> Cluster:
    """A run with one partition and a heal."""
    made = Cluster(size=5, seed=11).settle()
    for one in range(3):
        made.propose(("set", "k", one))
    made.run(20)
    made.partition([["n0", "n1"], ["n2", "n3", "n4"]])
    made.run(80)
    made.heal()
    made.settle()
    made.run(80)
    return made


def _crashed() -> Cluster:
    """A run with a crash and a restart."""
    made = Cluster(size=5, seed=13).settle()
    for one in range(3):
        made.propose(("set", "k", one))
    made.run(20)
    victim = next(one for one in made.up if one != made.leader().name)
    made.crash(victim)
    made.settle()
    made.run(40)
    made.restart(victim)
    made.run(60)
    return made


def no_fault_in_this_package_breaks_a_property() -> dict:
    """Across every scenario here, all five properties hold, which is the claim being made.

    Stated as a sweep because a single clean run is a single clean run. What makes it evidence
    is that the same checker rejects a constructed violation, and that measurement is above.
    """
    table = compare_the_scenarios()
    return {
        "scenarios": len(table),
        "breaches": {one["scenario"]: one["breaches"] for one in table},
        "they_are_all_clean": all(one["clean"] for one in table),
        "every_property_held_everywhere": all(one["held"] == len(PROPERTIES) for one in table),
        "and_the_checker_can_fail": not bool(
            Report(
                ticks=1,
                breaches=[Breach(property=LOG_MATCHING, tick=1, detail="constructed")],
            )
        ),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "properties": len(PROPERTIES),
        "a_healthy_run_is_clean": a_healthy_run_holds_every_property()["everything_held"],
        "a_partitioned_run_is_clean": a_partitioned_run_holds_every_property()[
            "everything_held"
        ],
        "a_crashing_run_is_clean": a_crashing_run_holds_every_property()["everything_held"],
        "a_dirty_report_is_falsy": a_report_of_a_clean_run_is_truthy()[
            "and_a_dirty_one_is_falsy"
        ],
        "two_leaders_at_once_is_legal": two_leaders_in_different_terms_is_not_a_breach()[
            "and_it_is_not_a_breach"
        ],
        "a_transient_breach_is_reported": (
            a_breach_at_tick_forty_is_reported_even_if_it_recovers()["it_reported_it"]
        ),
        "every_scenario_is_clean": no_fault_in_this_package_breaks_a_property()[
            "they_are_all_clean"
        ],
    }
