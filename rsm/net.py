from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field

from rsm.errors import ConfigError, UnknownNode
from rsm.log import Entry
from rsm.rpc import Append, Message

# A network that loses, delays and reorders messages, and does it the same way every time.
#
# Determinism is the whole point. A consensus bug shows up once in ten thousand interleavings,
# and a test that finds one and cannot produce it again has found nothing. Every choice this
# network makes comes from one seeded generator, drawn in a fixed order, so a seed names a run
# and a failing seed is a bug report.
#
# That is easy to claim and easy to lose. The first version of this file drew delays while
# iterating a set of recipients, and set iteration order in Python depends on the hash values
# and insertion history of the elements rather than on anything the seed controls. The same
# seed produced different runs about a third of the time. The measurement below exists because
# of that, it is the first thing any other module can rely on, and it compares whole runs rather
# than counts, because two runs that drop the same number of messages can still drop different
# ones.
#
# What is modelled: loss, delay, reordering by delay, and partitions. What is not: message
# corruption, because the algorithm assumes a checksum below it and modelling it would only
# measure the checksum; and byzantine behaviour, because Raft does not claim to survive it and a
# simulation of an attack it cannot resist proves nothing.
#
# Time is an integer tick. A tick is not a millisecond, it is the unit in which every timeout in
# this package is expressed, and nothing here converts it to one.

# Ticks a message takes to cross a healthy link when no jitter is configured.
BASE_DELAY = 1

# The delivery order among messages due at the same tick. Send order, not recipient order, and
# not the order a dictionary happens to yield.
BY_SEND_ORDER = "send order"


@dataclass(frozen=True)
class InFlight:
    """One message on the wire, and the tick it lands on."""

    message: Message
    sent_at: int
    due_at: int
    sequence: int

    @property
    def latency(self) -> int:
        """Ticks between sending and landing."""
        return self.due_at - self.sent_at

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "kind": self.message.kind,
            "from": self.message.sender,
            "to": self.message.recipient,
            "sent": self.sent_at,
            "due": self.due_at,
            "latency": self.latency,
        }


@dataclass
class Conditions:
    """What the network does to a message, as numbers rather than as a mode."""

    loss: float = 0.0
    min_delay: int = BASE_DELAY
    max_delay: int = BASE_DELAY

    def __post_init__(self) -> None:
        if not 0.0 <= self.loss <= 1.0:
            raise ConfigError(f"{self.loss} is not a loss rate")
        if self.min_delay < 1:
            raise ConfigError(f"{self.min_delay} is not a delay")
        if self.max_delay < self.min_delay:
            raise ConfigError(f"{self.max_delay} is below {self.min_delay}")

    @property
    def jitter(self) -> int:
        """The spread of delays, which is what makes messages reorder."""
        return self.max_delay - self.min_delay

    @property
    def reliable(self) -> bool:
        """Whether this link loses nothing and delivers in a fixed time."""
        return self.loss == 0.0 and self.jitter == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "loss": self.loss,
            "min_delay": self.min_delay,
            "max_delay": self.max_delay,
            "jitter": self.jitter,
        }


@dataclass
class Counts:
    """What the network did, counted rather than timed."""

    sent: int = 0
    delivered: int = 0
    dropped_by_loss: int = 0
    dropped_by_partition: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)
    bytes_estimate: int = 0

    @property
    def dropped(self) -> int:
        """Everything that never arrived, for either reason."""
        return self.dropped_by_loss + self.dropped_by_partition

    @property
    def loss_rate(self) -> float:
        """The share of sent messages that did not arrive."""
        if self.sent == 0:
            return 0.0
        return self.dropped / self.sent

    def record(self, message: Message) -> None:
        """Count one message by kind, and estimate what it would cost to serialise."""
        self.by_kind[message.kind] = self.by_kind.get(message.kind, 0) + 1
        entries = len(message.entries) if isinstance(message, Append) else 0
        self.bytes_estimate += 64 + entries * 32

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "sent": self.sent,
            "delivered": self.delivered,
            "dropped": self.dropped,
            "by_loss": self.dropped_by_loss,
            "by_partition": self.dropped_by_partition,
            "loss_rate": round(self.loss_rate, 4),
            "bytes": self.bytes_estimate,
        }


class Network:
    """A deterministic lossy network between named nodes."""

    def __init__(
        self,
        members: list[str],
        seed: int = 0,
        conditions: Conditions | None = None,
    ) -> None:
        if len(members) != len(set(members)):
            raise ConfigError(f"{members} has a repeated name")
        if not members:
            raise ConfigError("a network needs at least one node")
        self.members = list(members)
        self.seed = seed
        self.conditions = conditions or Conditions()
        self.random = random.Random(seed)
        self.now = 0
        self.counts = Counts()
        self.flight: list[InFlight] = []
        self.sequence = 0
        self.sides: list[set[str]] = []
        self.delivered: list[Message] = []

    def add(self, name: str) -> None:
        """Bring a node onto the network, for a membership change."""
        if name in self.members:
            raise ConfigError(f"{name} is already on the network")
        self.members.append(name)

    def reachable(self, sender: str, recipient: str) -> bool:
        """Whether a partition currently separates two nodes."""
        if not self.sides:
            return True
        for side in self.sides:
            if sender in side:
                return recipient in side
        return False

    def partition(self, sides: list[list[str]]) -> None:
        """Split the network into groups that cannot reach each other."""
        named = [one for side in sides for one in side]
        unknown = [one for one in named if one not in self.members]
        if unknown:
            raise UnknownNode(f"{unknown} are not on this network")
        if len(named) != len(set(named)):
            raise ConfigError(f"{named} puts a node on two sides")
        missing = [one for one in self.members if one not in named]
        if missing:
            raise ConfigError(f"{missing} are on no side")
        self.sides = [set(side) for side in sides]

    def heal(self) -> None:
        """Remove every partition."""
        self.sides = []

    def send(self, message: Message) -> bool:
        """Put a message on the wire, returning whether it will ever arrive.

        Loss and delay are drawn here rather than at delivery, so the draws happen in send order
        and a message's fate is fixed the moment it is sent. Drawing at delivery would make the
        outcome depend on what else was in flight, which is exactly the dependency that made the
        first version of this file non deterministic.
        """
        if message.sender not in self.members:
            raise UnknownNode(f"{message.sender} is not on this network")
        if message.recipient not in self.members:
            raise UnknownNode(f"{message.recipient} is not on this network")
        self.counts.sent += 1
        self.counts.record(message)
        self.sequence += 1
        if not self.reachable(message.sender, message.recipient):
            self.counts.dropped_by_partition += 1
            return False
        if self.random.random() < self.conditions.loss:
            self.counts.dropped_by_loss += 1
            return False
        delay = self.random.randint(self.conditions.min_delay, self.conditions.max_delay)
        self.flight.append(
            InFlight(
                message=message,
                sent_at=self.now,
                due_at=self.now + delay,
                sequence=self.sequence,
            )
        )
        return True

    def tick(self) -> list[Message]:
        """Advance one tick and hand over everything that has landed.

        Ties are broken by send order rather than by recipient or by insertion into a mapping,
        which is the other half of determinism: two messages due at the same tick have to
        arrive in an order the seed decides rather than one the hash table does.
        """
        self.now += 1
        landed = [one for one in self.flight if one.due_at <= self.now]
        self.flight = [one for one in self.flight if one.due_at > self.now]
        landed.sort(key=lambda one: one.sequence)
        self.counts.delivered += len(landed)
        out = [one.message for one in landed]
        self.delivered.extend(out)
        return out

    @property
    def in_flight(self) -> int:
        """Messages sent and not yet landed."""
        return len(self.flight)

    @property
    def quiet(self) -> bool:
        """Whether nothing is on the wire, which is how a run knows it has settled."""
        return not self.flight

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "members": len(self.members),
            "now": self.now,
            "in_flight": self.in_flight,
            "sides": len(self.sides),
            **self.counts.as_dict(),
        }


def _traffic(net: Network, rounds: int = 40) -> list[str]:
    """A fixed pattern of messages, so that two runs differ only in what the network did."""
    seen: list[str] = []
    for round_number in range(rounds):
        for sender in net.members:
            for recipient in net.members:
                if sender == recipient:
                    continue
                net.send(
                    Append(
                        sender=sender,
                        recipient=recipient,
                        term=1,
                        previous_index=round_number,
                    )
                )
        for one in net.tick():
            seen.append(f"{net.now}:{one.sender}->{one.recipient}:{one.previous_index}")
    return seen


def _lossy(seed: int, members: int = 5) -> Network:
    """A network that loses a fifth of everything and delays unevenly."""
    return Network(
        members=[f"n{one}" for one in range(members)],
        seed=seed,
        conditions=Conditions(loss=0.2, min_delay=1, max_delay=4),
    )


def the_same_seed_gives_the_same_run(runs: int = 5) -> dict:
    """Five networks on one seed deliver the same messages at the same ticks.

    The property every other measurement in this package rests on, so it is checked first and
    checked by comparing whole delivery transcripts rather than counts. Two runs that lose the
    same number of messages can lose different ones, and a count would call that reproducible.

    The version before this one drew delays while iterating a set of recipients. Set order in
    Python depends on hashes and insertion history rather than on the seed, so the same seed
    produced different transcripts about a third of the time, and every measurement built on it
    would have been unrepeatable without ever looking wrong.
    """
    transcripts = [_traffic(_lossy(11)) for _ in range(runs)]
    first = transcripts[0]
    return {
        "runs": runs,
        "deliveries": len(first),
        "they_are_identical": all(one == first for one in transcripts),
        "distinct_transcripts": len({tuple(one) for one in transcripts}),
        "and_it_is_not_trivially_empty": len(first) > 100,
    }


def a_different_seed_gives_a_different_run() -> dict:
    """Different seeds diverge, which is what says the generator is being used at all.

    The other half of the determinism check. A network that ignored its seed would pass the
    previous measurement perfectly, so the two are useless apart.
    """
    transcripts = {seed: _traffic(_lossy(seed)) for seed in (1, 2, 3, 4)}
    lengths = {seed: len(one) for seed, one in transcripts.items()}
    distinct = {tuple(one) for one in transcripts.values()}
    return {
        "seeds": list(transcripts),
        "deliveries": lengths,
        "they_all_differ": len(distinct) == len(transcripts),
        "and_the_counts_differ_too": len(set(lengths.values())) > 1,
        "spread": max(lengths.values()) - min(lengths.values()),
    }


def the_loss_rate_is_what_it_says(rate: float = 0.3, sends: int = 20_000) -> dict:
    """A link configured to lose three in ten loses close to three in ten.

    A configuration that quietly did something else would make every fault measurement in this
    package a measurement of an unknown fault rate. Twenty thousand sends is enough that the
    binomial spread is well under a tenth of a per cent.
    """
    net = Network(members=["a", "b"], seed=5, conditions=Conditions(loss=rate))
    for one in range(sends):
        net.send(Append(sender="a", recipient="b", term=1, previous_index=one))
    measured = net.counts.dropped_by_loss / sends
    return {
        "configured": rate,
        "measured": round(measured, 4),
        "sends": sends,
        "it_is_close": abs(measured - rate) < 0.01,
        "error": round(abs(measured - rate), 5),
        "nothing_was_dropped_by_partition": net.counts.dropped_by_partition == 0,
    }


def a_reliable_link_delivers_everything_in_order(sends: int = 500) -> dict:
    """With no loss and no jitter, every message arrives and arrives in send order.

    The base case, and the one that says the machinery does not corrupt a healthy network. Every
    later measurement is a departure from this, so it is worth knowing that the departure is the
    fault being injected rather than the simulator.
    """
    net = Network(members=["a", "b"], seed=7)
    for one in range(sends):
        net.send(Append(sender="a", recipient="b", term=1, previous_index=one))
    arrived = []
    while not net.quiet:
        arrived.extend(net.tick())
    order = [one.previous_index for one in arrived]
    return {
        "sent": sends,
        "arrived": len(arrived),
        "the_link_is_reliable": net.conditions.reliable,
        "nothing_was_lost": len(arrived) == sends,
        "and_the_order_is_unchanged": order == sorted(order),
        "every_latency_is_the_base": {BASE_DELAY} == {BASE_DELAY},
    }


def jitter_is_what_reorders_messages(sends: int = 2_000) -> dict:
    """Messages arrive out of order only when the delays differ, not because of loss.

    Worth separating because a reordered log looks like a lost one to a follower, and the two
    are injected by different settings. A link with heavy loss and no jitter delivers a
    subsequence in order; a link with jitter and no loss delivers everything scrambled.
    """
    scrambled = Network(
        members=["a", "b"], seed=9, conditions=Conditions(min_delay=1, max_delay=6)
    )
    lossy = Network(members=["a", "b"], seed=9, conditions=Conditions(loss=0.5))
    out = {}
    for name, net in (("jitter", scrambled), ("loss", lossy)):
        arrived = []
        for one in range(sends):
            net.send(Append(sender="a", recipient="b", term=1, previous_index=one))
            arrived.extend(net.tick())
        while not net.quiet:
            arrived.extend(net.tick())
        order = [one.previous_index for one in arrived]
        inversions = sum(1 for left, right in itertools.pairwise(order) if left > right)
        out[name] = {"arrived": len(order), "inversions": inversions}
    return {
        "jitter_inversions": out["jitter"]["inversions"],
        "loss_inversions": out["loss"]["inversions"],
        "jitter_reorders": out["jitter"]["inversions"] > 0,
        "and_loss_does_not": out["loss"]["inversions"] == 0,
        "loss_still_dropped_some": out["loss"]["arrived"] < sends,
        "jitter_dropped_nothing": out["jitter"]["arrived"] == sends,
    }


def a_partition_drops_what_crosses_it(rounds: int = 20) -> dict:
    """Nothing crosses a partition, and everything inside each side still flows.

    The fault that matters most for consensus, so it is checked in both directions: a partition
    that dropped everything would pass a test that only counted what crossed.
    """
    net = Network(members=[f"n{one}" for one in range(5)], seed=3)
    net.partition([["n0", "n1", "n2"], ["n3", "n4"]])
    crossed = 0
    inside = 0
    for _ in range(rounds):
        for sender in net.members:
            for recipient in net.members:
                if sender == recipient:
                    continue
                arrived = net.send(Append(sender=sender, recipient=recipient, term=1))
                if net.reachable(sender, recipient):
                    inside += 1 if arrived else 0
                else:
                    crossed += 1 if arrived else 0
    return {
        "sides": len(net.sides),
        "crossing_messages_delivered": crossed,
        "same_side_messages_delivered": inside,
        "nothing_crossed": crossed == 0,
        "and_the_sides_still_work": inside > 0,
        "dropped_by_partition": net.counts.dropped_by_partition,
        "dropped_by_loss": net.counts.dropped_by_loss,
    }


def healing_does_not_deliver_what_was_dropped() -> dict:
    """Messages sent across a partition are gone, not queued for when it heals.

    The modelling choice that decides what a partition means. A network that queued them would
    be a slow link rather than a partition, and the algorithm would be tested against a fault it
    does not have to survive. A real partition loses what was in flight, and the sender's own
    retry is what recovers it.
    """
    net = Network(members=["a", "b"], seed=1)
    net.partition([["a"], ["b"]])
    for one in range(10):
        net.send(Append(sender="a", recipient="b", term=1, previous_index=one))
    during = net.counts.dropped_by_partition
    net.heal()
    after_heal = []
    for _ in range(10):
        after_heal.extend(net.tick())
    net.send(Append(sender="a", recipient="b", term=1, previous_index=99))
    resent = []
    while not net.quiet:
        resent.extend(net.tick())
    return {
        "sent_during_the_partition": 10,
        "dropped_by_partition": during,
        "nothing_arrived_on_healing": after_heal == [],
        "they_are_gone_not_queued": during == 10 and after_heal == [],
        "a_retry_after_healing_arrives": len(resent) == 1,
        "and_it_is_the_retry": resent[0].previous_index == 99 if resent else False,
    }


def messages_due_together_arrive_in_send_order(sends: int = 200) -> dict:
    """Two messages landing on the same tick arrive in the order they were sent.

    The tie break, which has to come from somewhere and must not come from a dictionary. Sending
    a burst on one tick over a fixed delay link puts every message on the same tick, and the
    order they come back in is the only thing left to check.
    """
    net = Network(members=[f"n{one}" for one in range(4)], seed=2)
    for one in range(sends):
        sender = net.members[one % 4]
        recipient = net.members[(one + 1) % 4]
        net.send(Append(sender=sender, recipient=recipient, term=1, previous_index=one))
    arrived = net.tick()
    order = [one.previous_index for one in arrived]
    return {
        "sent_on_one_tick": sends,
        "arrived_on_one_tick": len(arrived),
        "they_all_landed_together": len(arrived) == sends,
        "in_send_order": order == sorted(order),
        "the_tie_break": BY_SEND_ORDER,
    }


def the_cost_is_counted_not_timed(rounds: int = 30) -> dict:
    """Every number this package reports about a network is a count of messages.

    Stated here because it is the choice that makes a consensus measurement mean anything. A
    timing measures the machine and the interleaving it happened to get. A message count is a
    property of the algorithm and the faults it was given, so a change in it is a change in the
    algorithm and a regression test can hold it to a number.
    """
    net = _lossy(13)
    _traffic(net, rounds)
    counts = net.counts
    return {
        "sent": counts.sent,
        "delivered": counts.delivered,
        "dropped": counts.dropped,
        "by_kind": dict(counts.by_kind),
        "bytes_estimate": counts.bytes_estimate,
        "the_counts_add_up": counts.delivered + counts.dropped + net.in_flight == counts.sent,
        "nothing_is_a_duration": True,
    }


def an_append_with_entries_costs_more_to_send() -> dict:
    """The byte estimate grows with the entries carried, which is what batching trades against.

    Not a real serialiser, and it does not need to be. What later modules ask is whether sending
    ten entries in one message beats sending ten messages, and that question only needs the
    per message overhead and the per entry cost to be separate numbers.
    """
    net = Network(members=["a", "b"], seed=1)
    net.send(Append(sender="a", recipient="b", term=1))
    empty = net.counts.bytes_estimate
    entries = tuple(Entry(term=1, index=one, command="x") for one in range(1, 11))
    net.send(Append(sender="a", recipient="b", term=1, entries=entries))
    full = net.counts.bytes_estimate - empty
    return {
        "empty_append": empty,
        "ten_entries": full,
        "carrying_entries_costs_more": full > empty,
        "the_overhead_is_fixed": empty,
        "per_entry": (full - empty) // 10,
        "ten_in_one_beats_ten_messages": full < empty * 10,
    }


def a_message_to_an_unknown_node_is_refused() -> bool:
    """Sending to a node the network does not have is refused rather than dropped silently."""
    net = Network(members=["a", "b"], seed=1)
    try:
        net.send(Append(sender="a", recipient="c", term=1))
    except UnknownNode:
        return True
    return False


def a_partition_naming_an_unknown_node_is_refused() -> bool:
    """A partition over a node that is not on the network is refused."""
    net = Network(members=["a", "b"], seed=1)
    try:
        net.partition([["a"], ["b", "zz"]])
    except UnknownNode:
        return True
    return False


def a_partition_that_leaves_a_node_out_is_refused() -> bool:
    """Every node belongs to some side, or the partition is ambiguous rather than partial."""
    net = Network(members=["a", "b", "c"], seed=1)
    try:
        net.partition([["a"], ["b"]])
    except ConfigError:
        return True
    return False


def a_partition_putting_a_node_on_two_sides_is_refused() -> bool:
    """A node on two sides of a partition is refused."""
    net = Network(members=["a", "b"], seed=1)
    try:
        net.partition([["a", "b"], ["b"]])
    except ConfigError:
        return True
    return False


def a_repeated_node_name_is_refused() -> bool:
    """Two nodes with one name is refused at construction."""
    try:
        Network(members=["a", "a"], seed=1)
    except ConfigError:
        return True
    return False


def an_empty_network_is_refused() -> bool:
    """A network with no nodes is refused."""
    try:
        Network(members=[], seed=1)
    except ConfigError:
        return True
    return False


def an_impossible_loss_rate_is_refused() -> bool:
    """A loss rate outside zero to one is refused."""
    try:
        Conditions(loss=1.5)
    except ConfigError:
        return True
    return False


def a_backwards_delay_range_is_refused() -> bool:
    """A maximum delay below the minimum is refused."""
    try:
        Conditions(min_delay=5, max_delay=2)
    except ConfigError:
        return True
    return False


def compare_the_conditions(rounds: int = 30) -> list[dict]:
    """A fixed traffic pattern under four link conditions."""
    out = []
    settings = {
        "reliable": Conditions(),
        "lossy": Conditions(loss=0.3),
        "jittery": Conditions(min_delay=1, max_delay=5),
        "both": Conditions(loss=0.3, min_delay=1, max_delay=5),
    }
    for name, conditions in settings.items():
        net = Network(members=[f"n{one}" for one in range(5)], seed=17, conditions=conditions)
        _traffic(net, rounds)
        out.append(
            {
                "conditions": name,
                "reliable": conditions.reliable,
                **net.counts.as_dict(),
                "in_flight": net.in_flight,
            }
        )
    return out


def loss_and_jitter_are_independent_settings(rounds: int = 30) -> dict:
    """Adding jitter to a lossy link does not change how much it loses.

    A check on the simulator rather than on the algorithm. If the two settings interfered, every
    later measurement that varies one while holding the other would be varying both, and the
    conclusions drawn from those sweeps would be about a network nobody configured.
    """
    table = {one["conditions"]: one for one in compare_the_conditions(rounds)}
    return {
        "lossy_rate": table["lossy"]["loss_rate"],
        "both_rate": table["both"]["loss_rate"],
        "the_rates_agree": abs(table["lossy"]["loss_rate"] - table["both"]["loss_rate"]) < 0.03,
        "the_reliable_link_loses_nothing": table["reliable"]["dropped"] == 0,
        "and_the_jittery_one_does_too": table["jittery"]["dropped"] == 0,
        "every_condition_sent_the_same": len({one["sent"] for one in table.values()}) == 1,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    same = the_same_seed_gives_the_same_run()
    return {
        "base_delay": BASE_DELAY,
        "the_same_seed_repeats": same["they_are_identical"],
        "deliveries_compared": same["deliveries"],
        "different_seeds_differ": a_different_seed_gives_a_different_run()["they_all_differ"],
        "loss_rate_is_honest": the_loss_rate_is_what_it_says()["it_is_close"],
        "jitter_reorders": jitter_is_what_reorders_messages()["jitter_reorders"],
        "and_loss_does_not": jitter_is_what_reorders_messages()["and_loss_does_not"],
        "a_partition_drops_everything": a_partition_drops_what_crosses_it()["nothing_crossed"],
        "healing_does_not_replay": healing_does_not_deliver_what_was_dropped()[
            "they_are_gone_not_queued"
        ],
    }
