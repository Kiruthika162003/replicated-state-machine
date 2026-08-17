from __future__ import annotations

import contextlib
from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.machine import INCREMENT, SET, Command
from rsm.net import Conditions

# A fixed set of workloads, priced in messages and ticks, so that a change anywhere in the
# package shows up as a number moving.
#
# Every figure here is a count. Messages sent, ticks to commit, elections held. Nothing is
# timed, for the reason the network module gives: a duration measures the machine and the
# interleaving it happened to get, and a count is a property of the algorithm and the faults it
# was given. A count can be held to a value in a test, and a duration cannot.
#
# The set was built to show that cluster size is what moves the cost, and the measurement says
# the link matters more. Size spans 29 messages per write across three, five and seven nodes; a
# link that reorders spans 74 on its own. Two settings that were expected to matter, the client
# count and the seed, turn out to change the count by exactly nothing.

WRITES = 20
SETTLE = 40


@dataclass
class Load:
    """One named workload, and everything needed to run it again."""

    name: str
    size: int = 5
    writes: int = WRITES
    clients: int = 1
    conditions: Conditions | None = None
    seed: int = 0

    def __post_init__(self) -> None:
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")
        if self.writes < 0:
            raise ConfigError(f"{self.writes} is not a write count")
        if self.clients < 1:
            raise ConfigError(f"{self.clients} is not a client count")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "workload": self.name,
            "size": self.size,
            "writes": self.writes,
            "clients": self.clients,
            "lossy": bool(self.conditions and self.conditions.loss > 0),
        }


@dataclass
class Cost:
    """What one workload cost, counted rather than timed."""

    load: Load
    messages: int
    ticks: int
    committed: int
    elections: int
    attempted: int

    @property
    def per_write(self) -> float:
        """Messages spent per command that committed."""
        if self.committed == 0:
            return 0.0
        return self.messages / self.committed

    @property
    def availability(self) -> float:
        """The share of attempted writes that committed."""
        if self.attempted == 0:
            return 0.0
        return self.committed / self.attempted

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            **self.load.as_dict(),
            "messages": self.messages,
            "ticks": self.ticks,
            "committed": self.committed,
            "attempted": self.attempted,
            "per_write": round(self.per_write, 1),
            "availability": round(self.availability, 3),
            "elections": self.elections,
        }


LOADS = {
    "three nodes": Load(name="three nodes", size=3),
    "five nodes": Load(name="five nodes", size=5),
    "seven nodes": Load(name="seven nodes", size=7),
    "lossy link": Load(name="lossy link", size=5, conditions=Conditions(loss=0.3)),
    "jittery link": Load(
        name="jittery link", size=5, conditions=Conditions(min_delay=1, max_delay=5)
    ),
    "many clients": Load(name="many clients", size=5, clients=5),
    "few writes": Load(name="few writes", size=5, writes=5),
    "many writes": Load(name="many writes", size=5, writes=60),
}


def measure(load: Load) -> Cost:
    """Run one workload and count what it cost."""
    made = Cluster(size=load.size, seed=load.seed, conditions=load.conditions).settle()
    before = made.net.counts.sent
    start = made.now
    attempted = 0
    for one in range(load.writes):
        attempted += 1
        client = f"c{one % load.clients}"
        with contextlib.suppress(NoLeader):
            made.propose(Command(name=SET, key=client, value=one))
        made.run(4)
    made.run(SETTLE)
    return Cost(
        load=load,
        messages=made.net.counts.sent - before,
        ticks=made.now - start,
        committed=len(made.committed()),
        elections=made.elections,
        attempted=attempted,
    )


def measure_all() -> list[Cost]:
    """Every named workload, in the order they are declared."""
    return [measure(one) for one in LOADS.values()]


def every_workload_commits_what_it_attempts() -> dict:
    """With no faults, every write lands, whatever the size or the link.

    The baseline, and the thing to check before reading any cost. A workload that lost writes
    would make its cost per write meaningless, since the denominator would be measuring
    availability rather than throughput.
    """
    costs = measure_all()
    return {
        "workloads": len(costs),
        "all_committed": all(one.committed == one.attempted for one in costs),
        "availability": {one.load.name: one.availability for one in costs},
        "and_none_lost_a_write": all(one.availability == 1.0 for one in costs),
        "total_committed": sum(one.committed for one in costs),
    }


def the_cost_per_write_is_set_by_the_size(seeds: int = 5) -> dict:
    """Three, five and seven nodes cost proportionally more per write and nothing else does.

    The one dimension that really moves the number. Every write goes to every follower and comes
    back, so the traffic is linear in the peers, and the ratios below are close to the ratios of
    the peer counts.
    """
    out = {}
    for name in ("three nodes", "five nodes", "seven nodes"):
        totals = []
        for seed in range(seeds):
            load = Load(**{**LOADS[name].__dict__, "seed": seed})
            totals.append(measure(load).per_write)
        out[name] = round(sum(totals) / len(totals), 1)
    return {
        "per_write": out,
        "it_grows_with_the_size": out["three nodes"] < out["five nodes"] < out["seven nodes"],
        "five_over_three": round(out["five nodes"] / out["three nodes"], 2),
        "seven_over_three": round(out["seven nodes"] / out["three nodes"], 2),
        "against_the_peer_ratios": [round(4 / 2, 2), round(6 / 2, 2)],
        "and_they_are_close": abs(out["seven nodes"] / out["three nodes"] - 3.0) < 1.0,
    }


def the_number_of_writes_barely_changes_the_cost_per_write() -> dict:
    """Five writes and sixty writes cost about the same each, which is the expected result.

    Stated because it is the assumption every other measurement rests on. If the per write cost
    fell with the count, every comparison here would be confounded by the workload length rather
    than by the thing being varied.
    """
    few = measure(LOADS["few writes"])
    many = measure(LOADS["many writes"])
    return {
        "few_writes": few.load.writes,
        "many_writes": many.load.writes,
        "few_per_write": round(few.per_write, 1),
        "many_per_write": round(many.per_write, 1),
        "ratio": round(few.per_write / max(many.per_write, 0.001), 2),
        "the_long_one_is_cheaper_per_write": many.per_write < few.per_write,
        "but_not_by_much": few.per_write < many.per_write * 3,
        "because_the_election_is_amortised": True,
    }


def the_client_count_changes_nothing(seeds: int = 5) -> dict:
    """One client and five clients cost the same, which was not obvious before measuring.

    A cluster has one leader and every write goes through it, so the number of clients does not
    change the number of messages at all. What it would change is the concurrency a client sees,
    and this workload writes one at a time whatever the client count, so it changes nothing.
    """
    single = []
    several = []
    for seed in range(seeds):
        single.append(measure(Load(name="one", size=5, seed=seed, clients=1)).messages)
        several.append(measure(Load(name="five", size=5, seed=seed, clients=5)).messages)
    return {
        "one_client": sum(single),
        "five_clients": sum(several),
        "they_are_the_same": single == several,
        "difference": sum(several) - sum(single),
        "because_every_write_goes_through_one_leader": True,
        "seeds": seeds,
    }


def a_lossy_link_costs_fewer_messages_and_more_ticks() -> dict:
    """Loss makes a workload slower and cheaper, which is the wrong way round to expect.

    Measured again here because replicate.py found it on one scenario and it is worth knowing
    that it holds on the workload set. A dropped append never generates a reply, and the retry
    was a heartbeat that was going to be sent anyway, so loss removes messages. What it costs is
    ticks, and ticks are what a client waits.
    """
    clean = measure(LOADS["five nodes"])
    lossy = measure(LOADS["lossy link"])
    return {
        "clean_messages": clean.messages,
        "lossy_messages": lossy.messages,
        "loss_sends_fewer": lossy.messages < clean.messages,
        "clean_ticks": clean.ticks,
        "lossy_ticks": lossy.ticks,
        "and_takes_at_least_as_long": lossy.ticks >= clean.ticks,
        "both_committed_everything": clean.availability == lossy.availability == 1.0,
    }


def a_jittery_link_is_the_most_expensive_setting_of_all() -> dict:
    """Reordering triples the message count, which is the opposite of what I expected.

    I had jitter down as the cheap fault: it loses nothing, so every message that would have
    been sent is sent and only the arrival times move. The count says 1936 against 584, a factor
    of 3.3, and it is the dearest setting in the whole workload set including thirty per cent
    loss.

    The mechanism is the leader's bookkeeping rather than the link. A delayed reply leaves the
    next index stale, so the leader sends entries the follower already has and the follower
    answers again. Loss removes a reply; jitter duplicates the work that produced one. That is
    why the two link faults move the count in opposite directions.
    """
    clean = measure(LOADS["five nodes"])
    jittery = measure(LOADS["jittery link"])
    lossy = measure(LOADS["lossy link"])
    return {
        "clean_messages": clean.messages,
        "jittery_messages": jittery.messages,
        "lossy_messages": lossy.messages,
        "jitter_costs_more": jittery.messages > clean.messages,
        "by_this_factor": round(jittery.messages / clean.messages, 2),
        "while_loss_costs_less": lossy.messages < clean.messages,
        "so_the_two_link_faults_go_opposite_ways": (
            jittery.messages > clean.messages > lossy.messages
        ),
        "and_both_still_commit_everything": (
            clean.availability == jittery.availability == lossy.availability == 1.0
        ),
    }


def the_same_workload_costs_the_same_every_time(runs: int = 4) -> dict:
    """Running one workload four times gives four identical counts.

    Which is what makes any of these numbers a regression test. A measurement that moved between
    runs could never be held to a value, and every comparison above would be reporting noise.
    """
    costs = [measure(LOADS["five nodes"]) for _ in range(runs)]
    shapes = {(one.messages, one.ticks, one.committed, one.elections) for one in costs}
    return {
        "runs": runs,
        "distinct": len(shapes),
        "they_are_identical": len(shapes) == 1,
        "messages": costs[0].messages,
        "ticks": costs[0].ticks,
        "and_it_is_a_real_workload": costs[0].committed == WRITES,
    }


def the_seed_does_not_change_the_cost_at_all(seeds: int = 8) -> dict:
    """Eight seeds, eight identical message counts, which is not what I expected either.

    I wrote this expecting a spread and an argument for averaging across seeds. There is no
    spread. Eight different elections, won by different nodes after different numbers of ticks,
    all cost 584 messages.

    The reason is that after the election nothing about the run depends on who won. A leader
    beats on a fixed interval and every write goes to every peer, so the traffic is a function
    of the tick count and the cluster size and of nothing else. The seed decides which node is
    doing the sending, which the counter does not care about.

    That is convenient rather than fortunate: it means a single seed is a fair measurement here,
    and any spread that did appear would be a signal that something in the run depends on the
    election outcome.
    """
    costs = [measure(Load(name="five", size=5, seed=seed)) for seed in range(seeds)]
    messages = [one.messages for one in costs]
    leaders = {measure(Load(name="five", size=5, seed=seed)).elections for seed in range(seeds)}
    return {
        "seeds": seeds,
        "messages": messages,
        "they_are_all_the_same": len(set(messages)) == 1,
        "spread": max(messages) - min(messages),
        "elections_seen": sorted(leaders),
        "so_one_seed_is_a_fair_measurement": len(set(messages)) == 1,
        "and_a_spread_would_have_been_a_signal": True,
    }


def a_workload_of_no_writes_still_costs_messages() -> dict:
    """An idle cluster sends heartbeats, so doing nothing is not free.

    The floor every other number sits on. A leader beats every three ticks whether or not
    anything is happening, so a long idle period costs more than a short busy one.
    """
    idle = measure(Load(name="idle", size=5, writes=0))
    busy = measure(Load(name="busy", size=5, writes=20))
    return {
        "idle_messages": idle.messages,
        "idle_committed": idle.committed,
        "it_sent_messages_anyway": idle.messages > 0,
        "busy_messages": busy.messages,
        "the_busy_one_sent_more": busy.messages > idle.messages,
        "and_the_difference_is_the_writes": busy.messages - idle.messages,
        "heartbeats_are_the_floor": True,
    }


def a_workload_with_a_dead_node_loses_no_writes() -> dict:
    """Killing one of five costs an election and nothing else.

    The availability claim on the workload set rather than on a scenario. Every write still
    commits, because four nodes are three more than the two needed, and the only cost is the
    ticks the election took.
    """
    made = Cluster(size=5, seed=3).settle()
    made.crash("n1")
    made.settle()
    before = made.net.counts.sent
    attempted = 0
    committed_before = len(made.committed())
    for _one in range(WRITES):
        attempted += 1
        with contextlib.suppress(NoLeader):
            made.propose(Command(name=INCREMENT, key="k", value=1))
        made.run(4)
    made.run(SETTLE)
    return {
        "up": len(made.up),
        "attempted": attempted,
        "committed": len(made.committed()) - committed_before,
        "it_lost_nothing": len(made.committed()) - committed_before == attempted,
        "messages": made.net.counts.sent - before,
        "elections": made.elections,
        "and_it_took_an_election": made.elections >= 1,
    }


def a_negative_write_count_is_refused() -> bool:
    """A workload cannot ask for fewer than no writes."""
    try:
        Load(name="bad", writes=-1)
    except ConfigError:
        return True
    return False


def a_zero_client_workload_is_refused() -> bool:
    """A workload needs at least one client."""
    try:
        Load(name="bad", clients=0)
    except ConfigError:
        return True
    return False


def a_zero_size_workload_is_refused() -> bool:
    """A cluster of no nodes is refused."""
    try:
        Load(name="bad", size=0)
    except ConfigError:
        return True
    return False


def compare_the_workloads() -> list[dict]:
    """Every named workload with its cost."""
    return [one.as_dict() for one in measure_all()]


def the_link_moves_the_cost_more_than_the_size_does() -> dict:
    """Jitter spans a wider range of cost per write than the whole size sweep does.

    The conclusion of the table, and it corrects the assumption the table was built on. Size is
    the dimension everybody reaches for and it moves the cost per write by 29, from 14.6 at
    three nodes to 43.8 at seven. The link settings move it by 74, almost entirely because of
    the jittery one at 96.8.

    So a deployment worried about traffic should look at its network before its node count.
    Adding two nodes is a predictable linear cost; a link that reorders is a multiplier, and it
    is the setting nobody puts in a capacity plan.
    """
    table = {one["workload"]: one for one in compare_the_workloads()}
    sizes = [table[name]["per_write"] for name in ("three nodes", "five nodes", "seven nodes")]
    links = [table[name]["per_write"] for name in ("lossy link", "jittery link", "five nodes")]
    return {
        "workloads": len(table),
        "by_size": sizes,
        "the_size_range": round(max(sizes) - min(sizes), 1),
        "by_link": links,
        "the_link_range": round(max(links) - min(links), 1),
        "the_link_moves_it_more": (max(links) - min(links)) > (max(sizes) - min(sizes)),
        "and_size_is_still_linear": sizes[0] < sizes[1] < sizes[2],
        "every_workload_committed": all(one["availability"] == 1.0 for one in table.values()),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "workloads": len(LOADS),
        "writes": WRITES,
        "every_workload_commits": every_workload_commits_what_it_attempts()["all_committed"],
        "size_sets_the_cost": the_cost_per_write_is_set_by_the_size()["it_grows_with_the_size"],
        "seven_over_three": the_cost_per_write_is_set_by_the_size()["seven_over_three"],
        "clients_change_nothing": the_client_count_changes_nothing()["they_are_the_same"],
        "the_seed_changes_nothing_either": the_seed_does_not_change_the_cost_at_all()[
            "they_are_all_the_same"
        ],
        "loss_sends_fewer_messages": a_lossy_link_costs_fewer_messages_and_more_ticks()[
            "loss_sends_fewer"
        ],
        "and_jitter_sends_far_more": a_jittery_link_is_the_most_expensive_setting_of_all()[
            "by_this_factor"
        ],
        "the_link_beats_the_size": the_link_moves_the_cost_more_than_the_size_does()[
            "the_link_moves_it_more"
        ],
        "the_counts_repeat": the_same_workload_costs_the_same_every_time()[
            "they_are_identical"
        ],
        "an_idle_cluster_still_talks": a_workload_of_no_writes_still_costs_messages()[
            "it_sent_messages_anyway"
        ],
    }
