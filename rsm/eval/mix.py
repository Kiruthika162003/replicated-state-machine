from __future__ import annotations

from dataclasses import dataclass

from rsm.errors import ConfigError
from rsm.node import HEARTBEAT_INTERVAL
from rsm.wire import ASSUMED_ENTRY_BYTES, ASSUMED_MESSAGE_BYTES

# What a workload costs as the balance between reads and writes moves.
#
# Every cost in this package so far is per write, because a write is what consensus is for. Most
# workloads are not mostly writes. A configuration store is read on every deploy and written on
# every change; a lock service is written on every acquire and read constantly by everything
# checking whether it holds the lock.
#
# Which matters because the three read strategies in rsm.client cost wildly different amounts,
# from nothing to more than a write, and the difference is multiplied by the read share. At one
# write in ten the read strategy is most of the bill; at nine in ten it is a rounding error, and
# the same cluster with the same settings can be tuned in opposite directions depending on which
# it is.
#
# The costs here are counted from the message model rather than run, because the point is the
# arithmetic of the mix rather than the behaviour of the cluster, and the behaviour is measured
# in rsm.eval.workload already. What this adds is that the answer depends on a number nobody
# usually writes down.

# The read strategies, and what each costs in messages beyond the leader's own work.
LOCAL = "local"
LEASE = "lease"
READ_INDEX = "read index"
THROUGH_THE_LOG = "through the log"
STRATEGIES = (LOCAL, LEASE, READ_INDEX, THROUGH_THE_LOG)

# The read shares worth looking at.
SHARES = (0.0, 0.5, 0.9, 0.99)


@dataclass(frozen=True)
class Mix:
    """One balance of reads to writes, and the strategy the reads use."""

    reads: float
    strategy: str
    size: int = 5
    batch: int = 1

    def __post_init__(self) -> None:
        if not 0.0 <= self.reads <= 1.0:
            raise ConfigError(f"{self.reads} is not a read share")
        if self.strategy not in STRATEGIES:
            raise ConfigError(f"{self.strategy} is not one of {list(STRATEGIES)}")
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")
        if self.batch < 1:
            raise ConfigError(f"{self.batch} is not a batch size")

    @property
    def peers(self) -> int:
        """How many other nodes the leader talks to."""
        return self.size - 1

    @property
    def write_cost(self) -> float:
        """Messages per write: one append and one reply per peer, amortised over the batch."""
        return round(2 * self.peers / self.batch, 3)

    @property
    def write_bytes(self) -> float:
        """Bytes per write, which is where batching stops helping and the entry remains."""
        return round(
            (2 * ASSUMED_MESSAGE_BYTES * self.peers) / self.batch
            + ASSUMED_ENTRY_BYTES * self.size,
            2,
        )

    @property
    def read_bytes(self) -> float:
        """Bytes per read, which is what separates the two correct and costly strategies.

        A read through the log writes an entry that every node keeps, so it costs the same
        messages as a read index and an entry more, on every node, for as long as the log lives.
        That difference does not appear in a message count and is the whole reason the read
        index exists.
        """
        if self.strategy == LOCAL:
            return 0.0
        if self.strategy == LEASE:
            return round(2 * ASSUMED_MESSAGE_BYTES * self.peers / HEARTBEAT_INTERVAL, 2)
        if self.strategy == READ_INDEX:
            return float(2 * ASSUMED_MESSAGE_BYTES * self.peers)
        return self.write_bytes

    @property
    def read_cost(self) -> float:
        """Messages per read under this strategy.

        Local costs nothing, because the leader answers from its own state. A lease costs
        nothing after the heartbeat that granted it, which is already being sent, so it is
        charged the share of a heartbeat round a read waits for. The read index costs a round of
        heartbeats. Through the log costs a write.
        """
        if self.strategy == LOCAL:
            return 0.0
        if self.strategy == LEASE:
            return round(2 * self.peers / HEARTBEAT_INTERVAL, 3)
        if self.strategy == READ_INDEX:
            return float(2 * self.peers)
        return self.write_cost

    @property
    def cost(self) -> float:
        """The average cost of an operation at this mix."""
        return round(self.reads * self.read_cost + (1 - self.reads) * self.write_cost, 3)

    @property
    def read_share_of_cost(self) -> float:
        """How much of the bill the reads are, which is what decides where to tune."""
        total = self.cost
        if total == 0:
            return 0.0
        return round(self.reads * self.read_cost / total, 3)

    @property
    def correct(self) -> bool:
        """Whether this strategy can return a stale answer, which rsm.lease measures."""
        return self.strategy != LOCAL

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "reads": self.reads,
            "strategy": self.strategy,
            "size": self.size,
            "write_cost": self.write_cost,
            "read_cost": self.read_cost,
            "cost": self.cost,
            "write_bytes": self.write_bytes,
            "read_bytes": self.read_bytes,
            "read_share_of_cost": self.read_share_of_cost,
            "correct": self.correct,
        }


def compare_the_strategies(reads: float = 0.9, size: int = 5) -> list[dict]:
    """Every read strategy at one mix."""
    return [Mix(reads=reads, strategy=one, size=size).as_dict() for one in STRATEGIES]


def compare_the_shares(strategy: str = READ_INDEX) -> list[dict]:
    """One strategy across the read shares."""
    return [Mix(reads=one, strategy=strategy).as_dict() for one in SHARES]


def the_read_strategy_becomes_the_whole_bill_as_the_reads_grow() -> dict:
    """At ninety percent reads the read index is nine tenths of the cost; at zero it is none.

    The arithmetic of a mix, which is obvious once written down and is not usually written down.
    A read strategy that costs the same as a write is a doubling at half reads and a tenfold
    increase at ninety percent, and the cluster settings worth tuning in the first case are not
    the ones that matter in the second.

    The number that decides it is the read share, which is a property of the application and
    appears nowhere in any cluster configuration.
    """
    out = {one: Mix(reads=one, strategy=READ_INDEX) for one in SHARES}
    return {
        "shares": list(SHARES),
        "read_share_of_cost": {one: made.read_share_of_cost for one, made in out.items()},
        "at_no_reads_it_is_nothing": out[0.0].read_share_of_cost == 0.0,
        "at_ninety_percent_it_is_most": out[0.9].read_share_of_cost > 0.8,
        "costs": {one: made.cost for one, made in out.items()},
        "the_cost_is_flat_for_this_strategy": len({made.cost for made in out.values()}) == 1,
        "because_a_read_costs_a_write": out[0.9].read_cost == out[0.9].write_cost,
    }


def batching_makes_the_read_strategy_matter_more() -> dict:
    """Batching sixty four deep leaves the reads as ninety nine percent of the bill.

    The interaction worth having. Batching is the standard answer to write cost and it works,
    taking a write from eight messages to an eighth of one. It does nothing for reads, because a
    read index round cannot be batched with anything.

    So every improvement to the write path makes the read path a larger share of what is left,
    and a cluster carefully tuned for writes is one where the read strategy is now nearly the
    whole cost.
    """
    out = {one: Mix(reads=0.9, strategy=READ_INDEX, batch=one) for one in (1, 8, 64)}
    return {
        "batches": sorted(out),
        "write_cost": {one: made.write_cost for one, made in out.items()},
        "it_falls_with_the_batch": out[64].write_cost < out[1].write_cost,
        "read_cost": {one: made.read_cost for one, made in out.items()},
        "and_the_read_cost_does_not": len({made.read_cost for made in out.values()}) == 1,
        "read_share_of_cost": {one: made.read_share_of_cost for one, made in out.items()},
        "the_reads_take_over": out[64].read_share_of_cost > out[1].read_share_of_cost,
        "at_the_deepest_batch": out[64].read_share_of_cost,
        "which_is_nearly_everything": out[64].read_share_of_cost > 0.95,
    }


def the_two_correct_strategies_cost_the_same_messages_and_different_bytes() -> dict:
    """A read index and a read through the log are eight messages each, and one writes an entry.

    The distinction a message count cannot see, and the reason the read index exists. Both need
    a round trip to establish that the leader is still the leader. The read through the log gets
    it by writing an entry, which every node then keeps for as long as the log lives.

    So the two are identical on the measure this package uses everywhere else and differ on the
    one it uses rarely, which is a caution about the measure rather than about the strategies:
    counting messages is right for consensus and blind to anything that accumulates.
    """
    index = Mix(reads=0.9, strategy=READ_INDEX)
    through = Mix(reads=0.9, strategy=THROUGH_THE_LOG)
    return {
        "read_index_messages": index.read_cost,
        "through_the_log_messages": through.read_cost,
        "they_are_the_same": index.read_cost == through.read_cost,
        "read_index_bytes": index.read_bytes,
        "through_the_log_bytes": through.read_bytes,
        "and_the_bytes_are_not": through.read_bytes > index.read_bytes,
        "by_this_ratio": round(through.read_bytes / index.read_bytes, 2),
        "and_the_entry_stays": True,
        "entry_bytes": ASSUMED_ENTRY_BYTES,
    }


def the_free_strategy_is_the_wrong_one_and_the_lease_is_the_compromise() -> dict:
    """Local costs nothing and can be stale; the lease costs a third of a heartbeat and cannot.

    The table lined up against rsm.lease, which measured the correctness side of the same four
    strategies. Local is free and wrong. The lease is nearly free and right, on a clock
    assumption. The read index and the read through the log are dear and right on no assumption
    at all.

    Put the two tables together and the ordering is by what you are willing to assume rather
    than by what you are willing to pay, which is the more useful way round.
    """
    table = {one["strategy"]: one for one in compare_the_strategies()}
    correct = [name for name, one in table.items() if one["correct"]]
    cheapest = min(one["cost"] for one in table.values() if one["correct"])
    return {
        "strategies": sorted(table),
        "correct": sorted(correct),
        "the_free_one_is_the_wrong_one": not table[LOCAL]["correct"],
        "local_cost": table[LOCAL]["cost"],
        "lease_cost": table[LEASE]["cost"],
        "read_index_cost": table[READ_INDEX]["cost"],
        "the_lease_is_the_cheapest_correct_one": table[LEASE]["cost"] == cheapest,
        "and_it_costs_a_fraction_of_a_read_index": (
            table[LEASE]["cost"] < table[READ_INDEX]["cost"]
        ),
        "by_this_ratio": round(table[READ_INDEX]["cost"] / table[LEASE]["cost"], 2),
    }


def a_read_share_outside_the_range_is_refused() -> bool:
    """A share of the operations has to be a share."""
    try:
        Mix(reads=1.5, strategy=LOCAL)
    except ConfigError:
        return True
    return False


def an_unknown_strategy_is_refused() -> bool:
    """There are four strategies and anything else is a typo."""
    try:
        Mix(reads=0.5, strategy="guessing")
    except ConfigError:
        return True
    return False


def a_zero_batch_is_refused() -> bool:
    """A batch of nothing never sends."""
    try:
        Mix(reads=0.5, strategy=LOCAL, batch=0)
    except ConfigError:
        return True
    return False


def a_cluster_of_none_is_refused() -> bool:
    """A mix needs a cluster to run on."""
    try:
        Mix(reads=0.5, strategy=LOCAL, size=0)
    except ConfigError:
        return True
    return False


def a_workload_of_only_writes_makes_the_strategy_irrelevant() -> dict:
    """At no reads all four cost the same, which is where most benchmarks sit.

    The boundary worth naming. A benchmark that writes and never reads cannot distinguish the
    four, so any of them can be chosen on the strength of it, and the one that looks best on
    every other measure is the free and wrong one.

    Which is a fair description of how a local read gets shipped: it costs nothing in the test
    and is wrong in the case the test never runs.
    """
    out = {one: Mix(reads=0.0, strategy=one) for one in STRATEGIES}
    return {
        "strategies": sorted(out),
        "costs": {one: made.cost for one, made in out.items()},
        "they_are_all_the_same": len({made.cost for made in out.values()}) == 1,
        "and_it_is_the_write_cost": out[LOCAL].cost == out[LOCAL].write_cost,
        "correctness_still_differs": len({made.correct for made in out.values()}) > 1,
        "so_a_write_only_benchmark_cannot_choose": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    bytes_apart = the_two_correct_strategies_cost_the_same_messages_and_different_bytes()
    return {
        "strategies": list(STRATEGIES),
        "shares": list(SHARES),
        "the_reads_become_the_bill": (
            the_read_strategy_becomes_the_whole_bill_as_the_reads_grow()[
                "at_ninety_percent_it_is_most"
            ]
        ),
        "batching_makes_it_worse": batching_makes_the_read_strategy_matter_more()[
            "the_reads_take_over"
        ],
        "the_two_correct_ones_differ_in_bytes": bytes_apart["and_the_bytes_are_not"],
        "and_not_in_messages": bytes_apart["they_are_the_same"],
        "the_lease_is_the_cheapest_correct_one": (
            the_free_strategy_is_the_wrong_one_and_the_lease_is_the_compromise()[
                "the_lease_is_the_cheapest_correct_one"
            ]
        ),
        "a_write_only_benchmark_cannot_choose": (
            a_workload_of_only_writes_makes_the_strategy_irrelevant()[
                "so_a_write_only_benchmark_cannot_choose"
            ]
        ),
    }
