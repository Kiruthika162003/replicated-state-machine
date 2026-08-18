from __future__ import annotations

import contextlib
import random
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.node import MAX_ELECTION_TIMEOUT, MIN_ELECTION_TIMEOUT
from rsm.transfer import hand_over

# Preferring one node as leader, and what the preference costs.
#
# Raft does not care which node leads. Any node with an up to date log will do, and the
# election picks whichever timer fires first, which is deliberately random. Deployments care a
# great deal: they want the leader near the clients, or on the machine with the fast disk, or
# out of the region that is about to be patched.
#
# There are two ways to express a preference. Transfer the leadership when the wrong node has
# it, which rsm.transfer measures, or make the preferred node more likely to win an election in
# the first place by having the others wait longer before standing. This module is about the
# second, and about what happens when a preference meets a node that keeps coming and going.
#
# Nothing here touches safety. A priority scheme changes who stands and when, which is exactly
# the part of the algorithm that is already arbitrary, so the worst a bad priority can do is
# waste elections. That is worth saying plainly because it is the reason this is a reasonable
# thing to do at all: the algorithm has left the choice open on purpose.

# How much longer a node waits per step of priority below the top.
STEP = 6

# How long a run watches.
WINDOW = 600

# The tick a write is attempted on.
EVERY = 20


@dataclass
class Priorities:
    """Which node is preferred, and by how much."""

    order: tuple[str, ...]
    step: int = STEP

    def __post_init__(self) -> None:
        if not self.order:
            raise ConfigError("a priority order needs at least one node")
        if len(set(self.order)) != len(self.order):
            raise ConfigError(f"{list(self.order)} has a repeated name")
        if self.step < 0:
            raise ConfigError(f"{self.step} is not a step")

    def delay(self, name: str) -> int:
        """How many extra ticks this node waits before standing.

        A node not in the order waits as long as the last one, rather than not at all. The other
        way round is the trap: a node nobody thought to rank would become the most eager
        candidate in the cluster.
        """
        if name in self.order:
            return self.order.index(name) * self.step
        return len(self.order) * self.step

    @property
    def preferred(self) -> str:
        """The node this cluster would rather have leading."""
        return self.order[0]

    @property
    def flat(self) -> bool:
        """Whether this expresses no preference at all."""
        return self.step == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "order": list(self.order),
            "step": self.step,
            "preferred": self.preferred,
            "flat": self.flat,
        }


@dataclass
class Outcome:
    """What one run under one priority scheme did."""

    name: str
    leaders: list[str] = field(default_factory=list)
    preferred: str = ""
    preferred_ticks: int = 0
    ticks: int = 0
    elections: int = 0
    committed: int = 0
    attempted: int = 0
    messages: int = 0
    transfers: int = 0

    @property
    def share(self) -> float:
        """The share of the run the preferred node spent leading."""
        if self.ticks == 0:
            return 0.0
        return round(self.preferred_ticks / self.ticks, 3)

    @property
    def availability(self) -> float:
        """The share of attempted writes that committed."""
        if self.attempted == 0:
            return 0.0
        return round(self.committed / self.attempted, 3)

    @property
    def distinct(self) -> int:
        """How many different nodes led during the run."""
        return len(set(self.leaders))

    def __bool__(self) -> bool:
        """A run is good if the preferred node led for most of it."""
        return self.share > 0.5

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "run": self.name,
            "preferred": self.preferred,
            "share": self.share,
            "elections": self.elections,
            "leaders": self.distinct,
            "availability": self.availability,
            "transfers": self.transfers,
            "messages": self.messages,
        }


class Run:
    """A cluster whose election timers carry a priority delay.

    The delay goes on the outside, in the same way rsm.timing drives its sweep: the node decides
    when its timer resets and this decides how long the timer is. That keeps the node's own
    rules untouched, which matters here more than usual, because a priority scheme that changed
    anything about voting would be changing the part that is not arbitrary.
    """

    def __init__(
        self,
        priorities: Priorities,
        size: int = 5,
        seed: int = 1,
        crash: str = "",
        crash_at: int = -1,
        restart_at: int = -1,
        flap_every: int = 0,
        flap_for: int = 30,
        reclaim: bool = False,
    ) -> None:
        if size < 1:
            raise ConfigError(f"{size} is not a cluster size")
        self.priorities = priorities
        self.cluster = Cluster(size=size, seed=seed, check=False)
        self.random = random.Random(f"{seed}:priority")
        self.deadline: dict[str, int] = {}
        self.seen: dict[str, int] = {}
        self.crash = crash
        self.crash_at = crash_at
        self.restart_at = restart_at
        self.flap_every = flap_every
        self.flap_for = flap_for
        self.reclaim = reclaim
        self.transfers = 0
        for name in self.cluster.members:
            self._rearm(name)

    def _rearm(self, name: str) -> None:
        """Draw this node a deadline, plus whatever its priority costs it."""
        span = self.random.randint(MIN_ELECTION_TIMEOUT, MAX_ELECTION_TIMEOUT)
        self.deadline[name] = self.cluster.now + span + self.priorities.delay(name)
        self.seen[name] = self.cluster.nodes[name].election_deadline

    def _follow(self) -> None:
        """Rearm anybody whose node reset its own timer."""
        for name, node in self.cluster.nodes.items():
            if node.election_deadline != self.seen[name]:
                self._rearm(name)

    def tick(self) -> None:
        """One step of the world, with the priority delays applied."""
        cluster = self.cluster
        cluster.now += 1
        for message in cluster.net.tick():
            if message.recipient in cluster.down:
                continue
            cluster._send(cluster.nodes[message.recipient].step(message))
        self._follow()
        for name in cluster.up:
            node = cluster.nodes[name]
            node.now = cluster.now
            if node.is_leader:
                cluster._send(node.tick(cluster.now))
                self._rearm(name)
                continue
            if cluster.now >= self.deadline[name]:
                cluster._send(node.stand())
                self._rearm(name)
        self._follow()

    def _flap(self, tick: int) -> None:
        """Take the preferred node down and bring it back, over and over.

        The pattern a preference is worst at: a node that is preferred and unreliable. Every
        return is an opportunity to hand the leadership back, and every hand back is an election
        the cluster would not otherwise have had.
        """
        want = self.priorities.preferred
        phase = tick % self.flap_every
        if phase == 0 and want not in self.cluster.down:
            self.cluster.crash(want)
        elif phase == self.flap_for and want in self.cluster.down:
            self.cluster.restart(want)

    def _reclaim(self) -> None:
        """Hand the leadership back to the preferred node when somebody else has it.

        Only when the preferred node is running and caught up, which the transfer itself checks.
        A reclaim that fired at a node still catching up would cost an election and lose it.
        """
        found = self.cluster.leader()
        want = self.priorities.preferred
        if found is None or found.name == want or want in self.cluster.down:
            return
        with contextlib.suppress(Exception):
            if hand_over(self.cluster, want):
                self.transfers += 1

    def go(self, name: str, window: int = WINDOW) -> Outcome:
        """Run the window and report what the preferred node got."""
        out = Outcome(name=name, preferred=self.priorities.preferred)
        start = self.cluster.net.counts.sent
        last = None
        for tick in range(window):
            if tick == self.crash_at and self.crash:
                with contextlib.suppress(KeyError):
                    self.cluster.crash(self.crash)
            if tick == self.restart_at and self.crash in self.cluster.down:
                self.cluster.restart(self.crash)
            if self.flap_every and tick > 60:
                self._flap(tick)
            if tick % EVERY == 0:
                out.attempted += 1
                with contextlib.suppress(NoLeader):
                    self.cluster.propose(("set", "k", tick))
            self.tick()
            out.ticks += 1
            if self.reclaim and tick % 40 == 0:
                self._reclaim()
            found = self.cluster.leader()
            if found is None:
                continue
            if found.name == self.priorities.preferred:
                out.preferred_ticks += 1
            if last is None or found.name != last:
                out.leaders.append(found.name)
                if last is not None:
                    out.elections += 1
                last = found.name
        out.committed = len(self.cluster.committed())
        out.messages = self.cluster.net.counts.sent - start
        out.transfers = self.transfers
        return out


MEMBERS = ("n0", "n1", "n2", "n3", "n4")
FLAT = Priorities(order=MEMBERS, step=0)
RANKED = Priorities(order=("n3", "n0", "n1", "n2", "n4"))


def a_priority_delay_puts_the_preferred_node_in_charge() -> dict:
    """The ranked scheme gives the preferred node ninety six percent of the run.

    The mechanism working. Every other node waits an extra six ticks per step below the top
    before it stands, so in a cold cluster the preferred node's timer fires first and it wins
    unopposed. The flat scheme gives it whatever the seed happens to give it, which here is
    nothing at all.

    The cost is a slower first election, since the preferred node's timer is the shortest but
    everybody else's is now longer, and if the preferred node is absent the cluster waits out
    the extra delay before anybody else tries.
    """
    flat = Run(FLAT).go("flat")
    ranked = Run(RANKED).go("ranked")
    return {
        "flat_share": flat.share,
        "ranked_share": ranked.share,
        "the_preference_worked": ranked.share > 0.9,
        "and_the_flat_run_did_not_prefer_it": flat.share < 0.5,
        "flat_leaders": flat.distinct,
        "ranked_leaders": ranked.distinct,
        "both_settled_on_one": flat.distinct == ranked.distinct == 1,
        "flat_availability": flat.availability,
        "ranked_availability": ranked.availability,
        "step": RANKED.step,
    }


def a_priority_decides_an_election_and_never_reclaims_one() -> dict:
    """Once the preferred node loses the office, the delay does nothing to get it back.

    The limit of the mechanism, and it surprised me. Crash the preferred node, let somebody else
    win, bring it back, and it stays a follower for the rest of the run: its share falls to
    thirty percent and there is one election in the whole window.

    The reason is that a priority delay only matters when a node decides to stand, and a node
    that can hear a working leader never decides to stand. The preference is expressed at
    election time and there is no election to express it in.

    Getting it back needs a transfer, which is a different mechanism with a different cost, and
    the next measurement is about what that costs.
    """
    made = Run(RANKED, crash="n3", crash_at=200, restart_at=260).go("flap")
    steady = Run(RANKED).go("steady")
    return {
        "share_after_the_flap": made.share,
        "share_without_one": steady.share,
        "it_lost_the_office": made.share < steady.share / 2,
        "elections": made.elections,
        "and_never_took_it_back": made.elections <= 1,
        "transfers": made.transfers,
        "which_it_did_not_try": made.transfers == 0,
        "leaders": made.distinct,
    }


def reclaiming_costs_an_election_every_time_the_node_returns() -> dict:
    """A transfer back raises the share from thirty percent to eighty three, for one election.

    The other mechanism. Checking periodically whether the preferred node is running and not
    leading, and handing over when both are true, recovers most of what the delay could not.
    One return, one transfer, one extra election, and about twenty extra messages.

    That is a good trade for a node that comes back once. The measurement after this one is what
    happens when it comes back repeatedly.
    """
    without = Run(RANKED, crash="n3", crash_at=200, restart_at=260).go("no reclaim")
    with_it = Run(RANKED, crash="n3", crash_at=200, restart_at=260, reclaim=True).go("reclaim")
    return {
        "share_without": without.share,
        "share_with": with_it.share,
        "it_recovered_the_office": with_it.share > without.share * 2,
        "elections_without": without.elections,
        "elections_with": with_it.elections,
        "and_it_cost_an_election": with_it.elections > without.elections,
        "transfers": with_it.transfers,
        "messages_without": without.messages,
        "messages_with": with_it.messages,
        "availability_without": without.availability,
        "availability_with": with_it.availability,
        "and_availability_was_unchanged": with_it.availability == without.availability,
    }


def preferring_an_unreliable_node_costs_a_quarter_of_the_availability() -> dict:
    """No preference elects nothing and stays up; a preference and a reclaim churn instead.

    The result that decides when a preference is worth having. Give the preferred node a habit
    of failing every hundred and twenty ticks and compare three schemes over the same run.

    With no preference the cluster elects nobody at all, because the flapping node was never
    leading and its coming and going costs the cluster nothing. Availability is ninety seven
    percent. With a preference and a reclaim the preferred node leads seventy percent of the
    time, at eight elections and seventy three percent availability.

    So the preference is what makes the unreliable node matter. A scheme that never gets what it
    wants is the one that stays up, and preferring a node is only worth it when the node is more
    reliable than the alternatives rather than less.
    """
    flat = Run(FLAT, flap_every=120).go("no preference")
    plain = Run(RANKED, flap_every=120).go("preference")
    reclaimed = Run(RANKED, flap_every=120, reclaim=True).go("preference and reclaim")
    return {
        "flat_elections": flat.elections,
        "flat_availability": flat.availability,
        "it_elected_nobody": flat.elections == 0,
        "reclaimed_share": reclaimed.share,
        "reclaimed_elections": reclaimed.elections,
        "reclaimed_availability": reclaimed.availability,
        "the_preference_cost_availability": reclaimed.availability < flat.availability,
        "by_this_share": round(flat.availability - reclaimed.availability, 3),
        "and_bought_this_much_preference": reclaimed.share - flat.share,
        "plain_share": plain.share,
        "elections_bought_the_share": reclaimed.elections > plain.elections,
    }


def an_unranked_node_waits_as_long_as_the_last_one() -> dict:
    """A node nobody thought to rank is the least eager, not the most.

    The trap in the obvious implementation. If an unranked node has no delay, it becomes the
    first to stand in every election, so the one node the operator did not think about wins.
    Treating it as ranked last makes the default the safe direction.
    """
    made = Priorities(order=("n0", "n1"), step=STEP)
    return {
        "ranked": list(made.order),
        "delays": {name: made.delay(name) for name in ("n0", "n1", "n2", "n9")},
        "the_top_waits_nothing": made.delay("n0") == 0,
        "and_an_unranked_node_waits_most": made.delay("n9") > made.delay("n1"),
        "which_is_the_safe_direction": True,
        "step": made.step,
    }


def a_flat_priority_is_the_shipped_behaviour() -> dict:
    """A step of zero gives every node the same delay, which is what Raft does.

    Worth having as a case rather than as a special path. The scheme with no preference is the
    same code with one parameter set to nothing, so the comparison above is between two runs of
    one implementation rather than between an implementation and its absence.
    """
    flat = Priorities(order=MEMBERS, step=0)
    return {
        "flat": flat.flat,
        "delays": {name: flat.delay(name) for name in MEMBERS},
        "they_are_all_zero": {flat.delay(one) for one in MEMBERS} == {0},
        "and_the_ranked_one_is_not": not RANKED.flat,
        "ranked_delays": {name: RANKED.delay(name) for name in MEMBERS},
        "which_are_a_step_apart": RANKED.delay("n0") - RANKED.delay("n3") == RANKED.step,
    }


def an_empty_priority_order_is_refused() -> bool:
    """A preference over nobody is refused."""
    try:
        Priorities(order=())
    except ConfigError:
        return True
    return False


def a_repeated_node_in_the_order_is_refused() -> bool:
    """A node cannot hold two ranks."""
    try:
        Priorities(order=("n0", "n0"))
    except ConfigError:
        return True
    return False


def a_negative_step_is_refused() -> bool:
    """A step that makes lower ranked nodes more eager is refused."""
    try:
        Priorities(order=("n0", "n1"), step=-2)
    except ConfigError:
        return True
    return False


def a_run_of_no_nodes_is_refused() -> bool:
    """A cluster of nothing cannot have a preference."""
    try:
        Run(RANKED, size=0)
    except ConfigError:
        return True
    return False


def compare_the_schemes() -> list[dict]:
    """Every scheme over a steady cluster and over a flapping preferred node."""
    return [
        Run(FLAT).go("flat, steady").as_dict(),
        Run(RANKED).go("ranked, steady").as_dict(),
        Run(FLAT, flap_every=120).go("flat, flapping").as_dict(),
        Run(RANKED, flap_every=120).go("ranked, flapping").as_dict(),
        Run(RANKED, flap_every=120, reclaim=True).go("reclaimed, flapping").as_dict(),
    ]


def the_preference_is_free_on_a_steady_cluster_and_dear_on_a_flapping_one() -> dict:
    """The same scheme costs a few percent in one column and a quarter in the other.

    The table that says when to use this. On a steady cluster the ranked scheme gets almost all
    of what it wants for a few percent of availability, which is a good trade and the case
    everybody has in mind when they configure a preference.

    On a flapping cluster the same scheme with a reclaim gives up a quarter of the availability
    for seventy percent preference, which is the case nobody has in mind, and it is the same
    configuration.
    """
    table = {one["run"]: one for one in compare_the_schemes()}
    steady_cost = (
        table["flat, steady"]["availability"] - table["ranked, steady"]["availability"]
    )
    flapping_cost = (
        table["flat, flapping"]["availability"] - table["reclaimed, flapping"]["availability"]
    )
    return {
        "runs": sorted(table),
        "steady_cost": round(steady_cost, 3),
        "flapping_cost": round(flapping_cost, 3),
        "the_flapping_case_costs_more": flapping_cost > steady_cost,
        "by_this_factor": round(flapping_cost / max(0.001, steady_cost), 1),
        "steady_share": table["ranked, steady"]["share"],
        "flapping_share": table["reclaimed, flapping"]["share"],
        "and_it_gets_less_for_it": (
            table["reclaimed, flapping"]["share"] < table["ranked, steady"]["share"]
        ),
        "same_configuration": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "step": STEP,
        "the_delay_puts_it_in_charge": (
            a_priority_delay_puts_the_preferred_node_in_charge()["the_preference_worked"]
        ),
        "but_it_never_reclaims": a_priority_decides_an_election_and_never_reclaims_one()[
            "and_never_took_it_back"
        ],
        "a_transfer_does": reclaiming_costs_an_election_every_time_the_node_returns()[
            "it_recovered_the_office"
        ],
        "and_costs_an_election": reclaiming_costs_an_election_every_time_the_node_returns()[
            "and_it_cost_an_election"
        ],
        "preferring_an_unreliable_node_costs": (
            preferring_an_unreliable_node_costs_a_quarter_of_the_availability()["by_this_share"]
        ),
        "an_unranked_node_waits_most": an_unranked_node_waits_as_long_as_the_last_one()[
            "and_an_unranked_node_waits_most"
        ],
        "the_same_configuration_differs_by": (
            the_preference_is_free_on_a_steady_cluster_and_dear_on_a_flapping_one()[
                "by_this_factor"
            ]
        ),
    }
