from __future__ import annotations

from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.node import HEARTBEAT_INTERVAL
from rsm.wire import ASSUMED_MESSAGE_BYTES

# What a cluster costs when nothing is happening.
#
# Every other cost in this package is per write, which is the right unit for the work a cluster
# does and hides the work it does anyway. A leader with nothing to replicate still sends a
# heartbeat to every follower on a fixed interval, forever, and that is the floor: the cost of a
# cluster that exists.
#
# The floor matters more than it sounds, because most clusters are not busy. A configuration
# store might take a hundred writes a day, and at that rate the heartbeats are not a rounding
# error on the bill, they are the bill. The measurements below find the write rate at which that
# stops being true, and it is much higher than it looks.
#
# The floor is also the one cost that a lazier heartbeat lowers directly, which is the setting
# rsm.timing found the tightest constraints on. So the idle cost and the failover time are the
# same knob read from two ends, and this module is the end nobody looks at.

# How long an idle run watches.
WINDOW = 300

# The write rates worth pricing, in writes per hundred ticks.
RATES = (0, 1, 5, 20, 100)


@dataclass(frozen=True)
class Floor:
    """What a cluster of this shape costs while doing nothing."""

    size: int
    heartbeat: int = HEARTBEAT_INTERVAL

    def __post_init__(self) -> None:
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")
        if self.heartbeat < 1:
            raise ConfigError(f"{self.heartbeat} is not a heartbeat interval")

    @property
    def peers(self) -> int:
        """How many nodes the leader beats at."""
        return self.size - 1

    @property
    def per_tick(self) -> float:
        """Messages a tick: one beat and one reply per peer, per interval."""
        return round(2 * self.peers / self.heartbeat, 3)

    @property
    def per_window(self) -> float:
        """Messages over a standard window."""
        return round(self.per_tick * WINDOW, 1)

    @property
    def bytes_per_tick(self) -> float:
        """What the floor costs on the wire."""
        return round(self.per_tick * ASSUMED_MESSAGE_BYTES, 1)

    def crossover(self, write_cost: float | None = None) -> float:
        """The write rate, per hundred ticks, at which writes cost as much as the heartbeats.

        Below it the cluster is mostly paying to exist and above it mostly paying to work, and
        the number is the one worth knowing before tuning anything.
        """
        cost = write_cost if write_cost is not None else 2 * self.peers
        if cost <= 0:
            raise ConfigError(f"{cost} is not a write cost")
        return round(self.per_tick * 100 / cost, 2)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "size": self.size,
            "heartbeat": self.heartbeat,
            "per_tick": self.per_tick,
            "per_window": self.per_window,
            "bytes_per_tick": self.bytes_per_tick,
            "crossover": self.crossover(),
        }


def measure(size: int = 5, seed: int = 1, window: int = WINDOW) -> dict:
    """Run a cluster with no writes at all and count what it sent."""
    if window < 1:
        raise ConfigError(f"{window} is not a window")
    made = Cluster(size=size, seed=seed).settle()
    before = made.net.counts.sent
    made.run(window)
    sent = made.net.counts.sent - before
    return {
        "size": size,
        "window": window,
        "messages": sent,
        "per_tick": round(sent / window, 3),
        "committed": len(made.committed()),
        "kinds": sorted(made.net.counts.by_kind),
    }


def the_model_of_the_floor_matches_the_cluster_exactly() -> dict:
    """Predicted and measured messages per tick agree to three decimals at every size.

    Worth doing first because everything below is arithmetic on the model, and a model that
    disagreed with the cluster would be arithmetic about nothing. Four hundred messages over
    three hundred idle ticks at three nodes and sixteen hundred at nine, and the formula gives
    both.
    """
    out = {}
    for size in (3, 5, 7, 9):
        made = Floor(size=size)
        found = measure(size=size)
        out[size] = {"predicted": made.per_tick, "measured": found["per_tick"]}
    return {
        "sizes": sorted(out),
        "results": out,
        "they_agree_everywhere": all(
            abs(one["predicted"] - one["measured"]) < 0.01 for one in out.values()
        ),
        "and_nothing_was_committed": measure(size=5)["committed"] == 0,
        "the_floor_at_five": Floor(size=5).per_tick,
        "over_a_window": Floor(size=5).per_window,
    }


def the_crossover_is_the_heartbeat_and_not_the_cluster_size() -> dict:
    """Thirty three writes per hundred ticks at three nodes and at nine, identically.

    The number worth knowing before tuning anything, and it is independent of the size. Both the
    floor and the cost of a write are proportional to the peer count, so the peer count cancels,
    and what is left is a hundred over the heartbeat interval.

    Below that rate the cluster is mostly paying to exist. A store taking a hundred writes a day
    is nowhere near it, so its bill is heartbeats and its cluster size changes the bill and not
    the ratio.
    """
    out = {size: Floor(size=size).crossover() for size in (3, 5, 7, 9)}
    beats = {beat: Floor(size=5, heartbeat=beat).crossover() for beat in (1, 3, 8)}
    return {
        "sizes": sorted(out),
        "crossovers": out,
        "they_are_the_same": len({round(one, 1) for one in out.values()}) == 1,
        "at_this_rate": round(next(iter(out.values())), 1),
        "heartbeats": sorted(beats),
        "by_heartbeat": beats,
        "and_the_heartbeat_moves_it": beats[1] > beats[8],
        "it_is_a_hundred_over_the_heartbeat": abs(beats[1] - 100.0) < 1.0,
    }


def a_lazier_heartbeat_lowers_the_floor_in_proportion() -> dict:
    """Beating every eighth tick costs an eighth of beating every tick, exactly.

    The one setting that moves the floor, and it moves it linearly. Which makes the trade with
    rsm.timing precise rather than vague: that module found leadership breaks above a heartbeat
    of five against a timeout of ten, so the floor can be cut to two fifths of the shipped
    setting and no further without churning.
    """
    out = {beat: Floor(size=5, heartbeat=beat) for beat in (1, 2, 3, 5, 8)}
    return {
        "heartbeats": sorted(out),
        "per_tick": {beat: one.per_tick for beat, one in out.items()},
        "it_falls_with_the_interval": out[8].per_tick < out[1].per_tick,
        "exactly_in_proportion": abs(out[1].per_tick / 8 - out[8].per_tick) < 0.01,
        "shipped": HEARTBEAT_INTERVAL,
        "the_safe_limit_from_timing": 5,
        "the_floor_at_the_safe_limit": out[5].per_tick,
        "and_the_saving_against_shipped": round(
            1 - out[5].per_tick / out[HEARTBEAT_INTERVAL].per_tick, 3
        ),
    }


def the_floor_is_most_of_the_bill_at_realistic_write_rates() -> dict:
    """At one write per hundred ticks the heartbeats are ninety seven percent of the traffic.

    The measurement the module exists for. Prices a run at several write rates and reports how
    much of the total the floor is. At a hundred writes per hundred ticks the writes dominate
    and the floor is a quarter; at one, the floor is nearly everything.

    Most clusters live at the left of that table and are sized and tuned as though they lived at
    the right.
    """
    floor = Floor(size=5)
    write_cost = 2 * floor.peers
    out = {}
    for rate in RATES:
        writes = rate / 100
        total = floor.per_tick + writes * write_cost
        out[rate] = {
            "total_per_tick": round(total, 3),
            "floor_share": round(floor.per_tick / total, 3),
        }
    return {
        "rates": list(RATES),
        "results": out,
        "at_no_writes_it_is_everything": out[0]["floor_share"] == 1.0,
        "at_one_write_it_is_most": out[1]["floor_share"] > 0.9,
        "at_a_hundred_it_is_a_quarter": out[100]["floor_share"] < 0.3,
        "the_crossover_rate": floor.crossover(),
        "and_it_sits_between_the_two": 20 < floor.crossover() < 100,
    }


def a_cluster_of_one_has_no_floor_at_all() -> dict:
    """One node beats at nobody, so it costs nothing to exist and everything to lose.

    The boundary, and the one place the whole trade disappears. A single node has no peers, so
    the heartbeat has nobody to reach and the floor is exactly zero, which is the only
    configuration in this package where doing nothing is free.

    It is also the configuration that tolerates nothing, which rsm.quorum measured. The floor is
    the price of having somebody else hold a copy.
    """
    alone = Floor(size=1)
    pair = Floor(size=2)
    return {
        "one_peers": alone.peers,
        "one_per_tick": alone.per_tick,
        "it_costs_nothing": alone.per_tick == 0.0,
        "two_per_tick": pair.per_tick,
        "and_two_costs_something": pair.per_tick > 0,
        "one_bytes": alone.bytes_per_tick,
        "and_no_bytes_either": alone.bytes_per_tick == 0.0,
        "so_the_floor_is_the_price_of_a_copy": True,
    }


def a_cluster_of_no_nodes_is_refused() -> bool:
    """A cluster of nothing has no floor to compute."""
    try:
        Floor(size=0)
    except ConfigError:
        return True
    return False


def a_zero_heartbeat_is_refused() -> bool:
    """A heartbeat of no ticks is refused."""
    try:
        Floor(size=3, heartbeat=0)
    except ConfigError:
        return True
    return False


def a_zero_write_cost_is_refused() -> bool:
    """A crossover against a free write is refused rather than reported as infinite."""
    try:
        Floor(size=3).crossover(write_cost=0)
    except ConfigError:
        return True
    return False


def a_window_of_no_ticks_is_refused() -> bool:
    """A measurement of no ticks measures nothing."""
    try:
        measure(window=0)
    except ConfigError:
        return True
    return False


def compare_the_shapes() -> list[dict]:
    """Every size at every heartbeat worth considering."""
    return [
        Floor(size=size, heartbeat=beat).as_dict() for size in (3, 5, 7) for beat in (1, 3, 5)
    ]


def the_floor_is_the_only_cost_that_never_goes_away() -> dict:
    """Nine shapes, nine floors, and not one of them is zero.

    The table. Every other cost in this package can be driven to nothing by not doing the thing
    that causes it: no writes, no write cost; no elections, no election cost. The floor is what
    is left when everything else is switched off, and the only settings that touch it are the
    cluster size and the heartbeat, both of which rsm.timing and rsm.quorum have already
    constrained from the other side.
    """
    table = compare_the_shapes()
    return {
        "shapes": len(table),
        "floors": sorted({one["per_tick"] for one in table}),
        "none_of_them_is_zero": all(one["per_tick"] > 0 for one in table),
        "cheapest": min(one["per_tick"] for one in table),
        "dearest": max(one["per_tick"] for one in table),
        "the_range": round(
            max(one["per_tick"] for one in table) / min(one["per_tick"] for one in table), 2
        ),
        "and_the_crossover_only_moves_with_the_heartbeat": len(
            {round(one["crossover"], 1) for one in table if one["heartbeat"] == 3}
        )
        == 1,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    crossing = the_crossover_is_the_heartbeat_and_not_the_cluster_size()
    return {
        "window": WINDOW,
        "the_model_matches_the_cluster": (
            the_model_of_the_floor_matches_the_cluster_exactly()["they_agree_everywhere"]
        ),
        "the_crossover_is_size_independent": crossing["they_are_the_same"],
        "at_this_rate": crossing["at_this_rate"],
        "and_it_is_a_hundred_over_the_heartbeat": crossing[
            "it_is_a_hundred_over_the_heartbeat"
        ],
        "a_lazier_heartbeat_lowers_it_in_proportion": (
            a_lazier_heartbeat_lowers_the_floor_in_proportion()["exactly_in_proportion"]
        ),
        "the_floor_dominates_at_low_rates": (
            the_floor_is_most_of_the_bill_at_realistic_write_rates()["at_one_write_it_is_most"]
        ),
        "and_only_one_node_escapes_it": a_cluster_of_one_has_no_floor_at_all()[
            "it_costs_nothing"
        ],
    }
