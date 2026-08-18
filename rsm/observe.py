from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.net import Conditions
from rsm.partition import INBOUND, OUTBOUND, Cut, Cuts

# Which signals would have caught which fault, as a matrix rather than as an opinion.
#
# Three modules in this package have found a fault that leaves the obvious health check
# unchanged. rsm.timing found a cluster with a heartbeat longer than its election timeout that
# holds a leader nine ticks in ten and commits one write in ten. rsm.partition found a leader
# that cannot hear, which holds the office at full uptime and commits nothing. rsm.eval
# availability found that a majority being up says almost nothing about whether writes land.
#
# Each of those was a note at the end of a module. This is the same question asked directly: run
# a set of faults, record a set of signals, and see which signals move. What comes out is a
# matrix with one row per fault and one column per signal, and the interesting cells are the
# blanks, because a blank is a fault that a system watching that signal would not see.
#
# Nothing here is novel about consensus. It is about the gap between what is easy to export and
# what is worth exporting, and it belongs in this package because the gap is unusually wide for
# a replicated log: the cheapest signal to publish, whether there is a leader, is nearly
# independent of whether the cluster is doing its job.

# How long each scenario runs for.
WINDOW = 400

# How often a write is attempted.
EVERY = 12

# How much a signal has to move before it counts as having noticed.
NOTICE = 0.2


@dataclass
class Reading:
    """Every signal a run produced, in the units they are naturally exported in."""

    name: str
    ticks: int = 0
    leader_ticks: int = 0
    terms: int = 0
    changes: int = 0
    attempted: int = 0
    committed: int = 0
    messages: int = 0
    applied_lag: list[int] = field(default_factory=list)

    @property
    def leader_uptime(self) -> float:
        """The share of ticks somebody held the office."""
        if self.ticks == 0:
            return 0.0
        return round(self.leader_ticks / self.ticks, 3)

    @property
    def commit_rate(self) -> float:
        """Committed writes per attempt, which is what a client experiences."""
        if self.attempted == 0:
            return 0.0
        return round(self.committed / self.attempted, 3)

    @property
    def message_rate(self) -> float:
        """Messages per tick, which is what a traffic graph shows."""
        if self.ticks == 0:
            return 0.0
        return round(self.messages / self.ticks, 2)

    @property
    def term_rate(self) -> float:
        """Terms burned per hundred ticks, which is what leadership churn looks like."""
        if self.ticks == 0:
            return 0.0
        return round(self.terms * 100 / self.ticks, 2)

    @property
    def worst_lag(self) -> int:
        """The furthest any running node fell behind the leader's commit index."""
        return max(self.applied_lag, default=0)

    def signals(self) -> dict:
        """The five signals, named the way they would be on a dashboard."""
        return {
            "leader present": self.leader_uptime,
            "term rate": self.term_rate,
            "commit rate": self.commit_rate,
            "message rate": self.message_rate,
            "replica lag": float(self.worst_lag),
        }

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"run": self.name, **self.signals()}


def _run(
    name: str,
    size: int = 5,
    seed: int = 1,
    window: int = WINDOW,
    cuts: list[Cut] | None = None,
    cut_leader: str = "",
    kill: str = "",
    loss: float = 0.0,
    pre_vote: bool = False,
) -> Reading:
    """One scenario, watched tick by tick, with every signal recorded as it would be exported.

    The commit count is taken at the end from what survived rather than counted at proposal
    time. A proposal that a leader accepted and then lost its office before replicating is not a
    committed write, and counting it as one would make the very fault this module is about
    invisible in the signal that is supposed to catch it.
    """
    if window < 1:
        raise ConfigError(f"{window} is not a window")
    conditions = Conditions(loss=loss) if loss else None
    made = Cluster(size=size, seed=seed, conditions=conditions, pre_vote=pre_vote).settle()
    rules = Cuts(made)
    for one in cuts or []:
        rules.add(one)
    if cut_leader:
        found = made.leader()
        if found is not None:
            rules.add(Cut(node=found.name, direction=cut_leader))
    if kill == "leader":
        found = made.leader()
        if found is not None:
            made.crash(found.name)
    elif kill:
        made.crash(kill)
    seen = Reading(name=name)
    start = made.net.counts.sent
    last = None
    for tick in range(1, window + 1):
        if tick % EVERY == 0:
            seen.attempted += 1
            with contextlib.suppress(NoLeader):
                made.propose(("set", "k", tick))
        made.tick()
        seen.ticks += 1
        found = made.leader()
        if found is not None:
            seen.leader_ticks += 1
            if last is not None and found.name != last:
                seen.changes += 1
            last = found.name
            behind = [
                found.commit_index - made.nodes[one].commit_index
                for one in made.up
                if one != found.name
            ]
            seen.applied_lag.append(max(behind, default=0))
    seen.terms = max(one.term for one in made.nodes.values())
    seen.committed = min(seen.attempted, len(made.committed()))
    seen.messages = made.net.counts.sent - start
    rules.restore()
    return seen


# The direction each signal moves in when things go wrong.
WORSE_WHEN_LOWER = ("leader present", "commit rate", "message rate")
WORSE_WHEN_HIGHER = ("term rate", "replica lag")
SIGNALS = WORSE_WHEN_LOWER + WORSE_WHEN_HIGHER


def noticed(healthy: float, faulty: float, signal: str, threshold: float = NOTICE) -> bool:
    """Whether a signal moved far enough, and in the bad direction, to raise an alarm.

    Relative rather than absolute, because the signals are in different units and a rule that
    compared them by absolute change would be comparing a share against a message count. The
    direction matters as much as the size: a message rate that falls is a cluster doing less
    work, and one that rises is usually a cluster doing more, so only the fall counts.
    """
    if signal not in WORSE_WHEN_LOWER + WORSE_WHEN_HIGHER:
        raise ConfigError(f"{signal} is not a signal")
    if healthy == 0:
        return abs(faulty) > threshold
    change = (faulty - healthy) / abs(healthy)
    if signal in WORSE_WHEN_LOWER:
        return change < -threshold
    return change > threshold


SCENARIOS = {
    "healthy": {},
    "deaf follower": {"cuts": [Cut(node="n4", direction=INBOUND)]},
    "deaf leader": {"cut_leader": INBOUND},
    "mute leader": {"cut_leader": OUTBOUND},
    "crashed leader": {"kill": "leader"},
    "lossy link": {"loss": 0.3},
}


def readings() -> dict[str, Reading]:
    """Every scenario, run once."""
    return {name: _run(name, **rest) for name, rest in SCENARIOS.items()}


def matrix() -> dict[str, dict[str, bool]]:
    """One row per fault, one column per signal, true where the signal would have noticed."""
    runs = readings()
    healthy = runs["healthy"].signals()
    out = {}
    for name, run in runs.items():
        if name == "healthy":
            continue
        found = run.signals()
        out[name] = {
            signal: noticed(healthy[signal], found[signal], signal) for signal in healthy
        }
    return out


def only_the_commit_rate_catches_every_fault_that_matters() -> dict:
    """Of five signals, one notices every run that lost writes and four miss at least one.

    The matrix. Two of the five faults are handled correctly by the cluster, the mute leader and
    the crashed leader, so a signal that stays quiet through those is not missing anything. The
    two that lose writes are the deaf follower and the deaf leader.

    The deaf follower is loud: uptime halves, the term rate goes up fourteen times, the lag goes
    to twenty eight. Anything would catch it.

    The deaf leader is silent on four signals out of five. Uptime is one, the term is flat, the
    message rate is down by a sixth, and the commit rate is zero. It is the only fault here that
    needs the commit rate to be seen at all.
    """
    made = matrix()
    lost_writes = ["deaf follower", "deaf leader"]
    per_signal = {}
    for signal in SIGNALS:
        per_signal[signal] = sum(1 for fault in lost_writes if made[fault][signal])
    return {
        "faults": sorted(made),
        "faults_that_lost_writes": lost_writes,
        "caught_by": per_signal,
        "the_commit_rate_caught_both": per_signal["commit rate"] == len(lost_writes),
        "and_it_is_the_only_one": [
            signal for signal, count in per_signal.items() if count == len(lost_writes)
        ]
        == ["commit rate"],
        "the_deaf_leader_row": made["deaf leader"],
        "how_many_saw_it": sum(made["deaf leader"].values()),
        "out_of": len(made["deaf leader"]),
    }


def the_replica_lag_moves_the_wrong_way_under_the_worst_fault() -> dict:
    """A leader that commits nothing has no followers behind it, so the lag improves.

    The cell worth staring at. Replica lag is a good signal for a follower that has fallen
    behind and it is measured against the leader's commit index, which under a deaf leader never
    moves. So every follower is exactly caught up with a leader that is doing nothing, and the
    lag is lower than in a healthy cluster.

    A rule that alerts on rising lag would not merely miss this fault. It would show the cluster
    getting healthier as it stopped working.
    """
    runs = readings()
    healthy = runs["healthy"].worst_lag
    deaf = runs["deaf leader"].worst_lag
    follower = runs["deaf follower"].worst_lag
    return {
        "healthy_lag": healthy,
        "deaf_leader_lag": deaf,
        "it_is_lower_than_healthy": deaf < healthy,
        "deaf_follower_lag": follower,
        "and_the_follower_fault_raises_it": follower > healthy,
        "so_the_signal_is_inverted_by_one_and_not_the_other": deaf < healthy < follower,
        "deaf_leader_commits": runs["deaf leader"].commit_rate,
        "which_is_nothing": runs["deaf leader"].commit_rate == 0.0,
    }


def the_noisy_signals_fire_on_the_faults_the_cluster_handled() -> dict:
    """The term rate and the replica lag alert on both faults that lost nothing.

    The other half of the matrix, and the more common failure of a dashboard. A crashed leader
    and a mute leader are both handled: the cluster elects, catches up and commits everything it
    was given. The term rate and the replica lag move on both of them.

    So those two signals fire for faults that needed no attention and stay quiet for the one
    that did. That is not a threshold that needs tuning. A signal that is loud about recovery
    and silent about failure is measuring recovery.

    Three signals are quiet here, not one, since leader presence and the message rate also miss
    the handled faults. What separates the commit rate from those two is that it is the only one
    of the three that is also loud about the faults that mattered.
    """
    made = matrix()
    runs = readings()
    handled = [
        name for name in made if runs[name].commit_rate >= runs["healthy"].commit_rate - 0.05
    ]
    false_alarms = {}
    for signal in SIGNALS:
        false_alarms[signal] = sum(1 for name in handled if made[name][signal])
    return {
        "handled_faults": sorted(handled),
        "false_alarms": false_alarms,
        "the_term_rate_fires_on_all_of_them": false_alarms["term rate"] == len(handled),
        "and_so_does_the_lag": false_alarms["replica lag"] == len(handled),
        "the_commit_rate_fires_on_none": false_alarms["commit rate"] == 0,
        "quiet_signals": sorted(signal for signal, count in false_alarms.items() if count == 0),
        "there_are_three_quiet_ones": sum(1 for count in false_alarms.values() if count == 0)
        == 3,
        "but_only_one_of_them_catches_the_real_faults": (
            only_the_commit_rate_catches_every_fault_that_matters()["and_it_is_the_only_one"]
        ),
    }


def an_unknown_signal_is_refused() -> bool:
    """A signal the comparison does not know the direction of is refused."""
    try:
        noticed(1.0, 0.5, "vibes")
    except ConfigError:
        return True
    return False


def a_zero_window_is_refused() -> bool:
    """A run of no ticks observes nothing."""
    try:
        _run("x", window=0)
    except ConfigError:
        return True
    return False


def a_signal_from_a_zero_baseline_is_compared_absolutely() -> dict:
    """A healthy value of zero has no relative change, so the rule falls back to the size.

    The boundary the relative rule has to handle. A signal that is zero when things are working,
    which the term rate nearly is, cannot be compared by ratio, and dividing by it would either
    raise or produce an infinity that alerts on every run.
    """
    return {
        "from_zero_to_nothing": noticed(0.0, 0.0, "term rate"),
        "from_zero_to_something": noticed(0.0, 5.0, "term rate"),
        "it_notices_the_second": noticed(0.0, 5.0, "term rate")
        and not noticed(0.0, 0.0, "term rate"),
        "and_a_tiny_move_is_ignored": not noticed(0.0, 0.01, "term rate"),
    }


def compare_the_scenarios() -> list[dict]:
    """Every scenario with every signal, as it would appear on a dashboard."""
    return [one.as_dict() for one in readings().values()]


def the_cheapest_signal_to_export_is_the_least_useful_one() -> dict:
    """Leader presence catches one fault in five and is the one everybody publishes.

    The summary of the whole module. Whether there is a leader is a boolean a node already
    knows, costs nothing to export and needs no history to interpret. It caught the loud fault
    and missed the quiet one, missed both handled faults, and reported a hundred percent through
    a cluster that committed nothing for four hundred ticks.

    The commit rate needs a counter, a window and a client's point of view to interpret, and it
    is the only signal here that is right about every row.
    """
    made = matrix()
    runs = readings()
    caught = {signal: sum(1 for name in made if made[name][signal]) for signal in SIGNALS}
    real = {name for name in made if runs[name].commit_rate < 0.95}
    return {
        "faults": len(made),
        "caught_by_each": caught,
        "leader_presence_caught": caught["leader present"],
        "it_is_the_least_of_them": caught["leader present"] == min(caught.values()),
        "real_faults": sorted(real),
        "leader_presence_on_the_deaf_leader": runs["deaf leader"].leader_uptime,
        "which_is_perfect": runs["deaf leader"].leader_uptime == 1.0,
        "while_it_committed": runs["deaf leader"].commit_rate,
        "and_that_is_nothing": runs["deaf leader"].commit_rate == 0.0,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    catching = only_the_commit_rate_catches_every_fault_that_matters()
    noisy = the_noisy_signals_fire_on_the_faults_the_cluster_handled()
    return {
        "scenarios": len(SCENARIOS),
        "signals": len(readings()["healthy"].signals()),
        "the_commit_rate_catches_everything": catching["the_commit_rate_caught_both"],
        "and_it_is_the_only_one": catching["and_it_is_the_only_one"],
        "the_deaf_leader_was_seen_by": catching["how_many_saw_it"],
        "out_of": catching["out_of"],
        "the_noisy_signals_fire_on_handled_faults": noisy["the_term_rate_fires_on_all_of_them"],
        "the_commit_rate_never_does": noisy["the_commit_rate_fires_on_none"],
        "the_lag_is_inverted": the_replica_lag_moves_the_wrong_way_under_the_worst_fault()[
            "it_is_lower_than_healthy"
        ],
    }
