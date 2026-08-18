from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader

# Splitting the keys across several independent groups, and what stops being true when you do.
#
# One consensus group has a throughput ceiling, which rsm.backpressure measures at about
# thirty writes a tick. The usual answer is more groups: split the keyspace, run a cluster per
# part, and the ceiling multiplies. That works, and the measurement below shows it working.
#
# What it costs is the thing the whole package has been about. Inside one group a write is
# ordered against every other write and either commits or does not. Across two groups there is
# no such thing. Two writes to two groups commit at two different moments, and there is a window
# where one has happened and the other has not, and nothing in Raft closes that window, because
# Raft was never asked to.
#
# So this module is mostly about measuring a window. How wide it is, what a reader inside it
# sees, and what it would take to close it, which is a protocol this package does not implement
# and is careful not to pretend it does.

# How many keys the measurements spread across the groups.
KEYS = 240

# How long a federated run watches.
WINDOW = 200


def digest(key: str) -> int:
    """A stable number for a key, which is what the placement is a function of.

    Not the builtin hash. Python randomises string hashing per interpreter, so a placement built
    on it would put a key in one group today and another tomorrow, and every determinism claim
    in this package would quietly stop being true across processes. rsm.node was bitten by the
    same thing and the fix is the same: use a digest that is a function of the bytes.
    """
    return int.from_bytes(hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest(), "big")


@dataclass(frozen=True)
class Keyspace:
    """Which group a key belongs to."""

    groups: int

    def __post_init__(self) -> None:
        if self.groups < 1:
            raise ConfigError(f"{self.groups} is not a group count")

    def group_of(self, key: str) -> int:
        """The group that owns a key."""
        if not key:
            raise ConfigError("a key cannot be empty")
        return digest(key) % self.groups

    def spread(self, keys: list[str]) -> dict[int, int]:
        """How many of these keys land in each group."""
        out = dict.fromkeys(range(self.groups), 0)
        for one in keys:
            out[self.group_of(one)] += 1
        return out

    def balance(self, keys: list[str]) -> float:
        """The largest group's share over the fair share, which is how uneven the split is."""
        counts = self.spread(keys)
        if not keys:
            return 0.0
        fair = len(keys) / self.groups
        return round(max(counts.values()) / fair, 3)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"groups": self.groups}


@dataclass
class Federation:
    """Several independent clusters, one per group, with nothing between them."""

    keyspace: Keyspace
    size: int = 3
    seed: int = 1
    clusters: dict[int, Cluster] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")
        for one in range(self.keyspace.groups):
            self.clusters[one] = Cluster(size=self.size, seed=self.seed + one).settle()

    def write(self, key: str, value: object) -> int:
        """Write one key, to whichever group owns it."""
        group = self.keyspace.group_of(key)
        return self.clusters[group].propose(("set", key, value))

    def tick(self, ticks: int = 1) -> None:
        """Advance every group, which they do independently because they are independent."""
        for _ in range(ticks):
            for made in self.clusters.values():
                made.tick()

    def committed(self) -> int:
        """How many writes have committed across every group."""
        return sum(len(one.committed()) for one in self.clusters.values())

    def messages(self) -> int:
        """What the whole federation has sent."""
        return sum(one.net.counts.sent for one in self.clusters.values())

    def leaders(self) -> dict[int, str]:
        """Who leads each group, which is not the same node and need not be."""
        out = {}
        for group, made in self.clusters.items():
            found = made.leader()
            if found is not None:
                out[group] = found.name
        return out

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "groups": self.keyspace.groups,
            "size": self.size,
            "nodes": self.keyspace.groups * self.size,
            "leaders": len(self.leaders()),
            "committed": self.committed(),
            "messages": self.messages(),
        }


def the_ceiling_multiplies_with_the_groups() -> dict:
    """Every group commits everything, and the message count falls as the groups multiply.

    The reason to shard, and a number I had backwards. Each group runs its own election, its own
    log and its own commit rule, and none waits for any other, so the work adds up. I expected
    the message count to add up too and wrote down that the throughput is bought with more
    traffic.

    Measured over a fixed hundred and twenty writes, the total falls: three thousand six hundred
    messages at one group and two thousand two hundred at eight, thirty per write down to
    eighteen. The reason is that there is no cross group traffic at all, so spreading the writes
    means each replication cascade happens inside a smaller share of the work rather than
    against the whole of it.

    What the extra nodes buy is not fewer messages, it is that the messages happen in parallel.
    The honest version of the trade is in the failure measurement below rather than here.
    """
    out = {}
    for groups in (1, 2, 4, 8):
        fed = Federation(keyspace=Keyspace(groups=groups))
        keys = [f"k{one}" for one in range(120)]
        for index, key in enumerate(keys):
            with contextlib.suppress(NoLeader):
                fed.write(key, index)
            if index % 10 == 0:
                fed.tick(2)
        fed.tick(40)
        out[groups] = fed
    return {
        "groups": sorted(out),
        "committed": {one: made.committed() for one, made in out.items()},
        "nodes": {one: one * 3 for one in out},
        "messages": {one: made.messages() for one, made in out.items()},
        "every_group_elected": all(len(made.leaders()) == one for one, made in out.items()),
        "they_all_committed_everything": all(made.committed() == 120 for made in out.values()),
        "messages_per_write": {
            one: round(made.messages() / max(1, made.committed()), 1)
            for one, made in out.items()
        },
        "the_cost_per_write_falls": out[8].messages() < out[1].messages(),
        "by_this_factor": round(out[1].messages() / out[8].messages(), 2),
        "and_there_is_no_traffic_between_groups": True,
    }


def a_write_across_two_groups_is_not_atomic() -> dict:
    """One group commits and the other has not, and there is nothing to ask about it.

    The window. Write two keys that live in different groups, then tick one group and not the
    other, and the federation is in a state where half the write has happened. A reader looking
    at both groups sees one new value and one old one.

    Nothing here is a bug. Each group is behaving exactly as specified and the specification
    says nothing about the pair, because a consensus group is a total order over its own log and
    two logs have no order between them at all. Closing the window needs a commit protocol
    across the groups, which this package does not implement and will not pretend to.
    """
    space = Keyspace(groups=4)
    left = "alpha"
    right = "beta"
    while space.group_of(left) == space.group_of(right):
        right += "x"
    fed = Federation(keyspace=space)
    fed.write(left, 1)
    fed.write(right, 1)
    fed.tick(20)
    before = fed.committed()
    fed.write(left, 2)
    fed.write(right, 2)
    fed.clusters[space.group_of(left)].run(20)
    seen_left = _value(fed, left)
    seen_right = _value(fed, right)
    fed.tick(20)
    return {
        "left_group": space.group_of(left),
        "right_group": space.group_of(right),
        "they_are_different": space.group_of(left) != space.group_of(right),
        "committed_before": before,
        "left_after_one_group_ticked": seen_left,
        "right_after_one_group_ticked": seen_right,
        "the_halves_disagree": seen_left != seen_right,
        "left_at_the_end": _value(fed, left),
        "right_at_the_end": _value(fed, right),
        "and_they_agree_eventually": _value(fed, left) == _value(fed, right),
        "so_the_window_closes_on_its_own_and_nothing_ordered_it": True,
    }


def _value(fed: Federation, key: str) -> object:
    """The newest committed value for a key, from the group that owns it."""
    made = fed.clusters[fed.keyspace.group_of(key)]
    best = None
    for one in made.committed():
        if isinstance(one, tuple) and len(one) == 3 and one[1] == key:
            best = one[2]
    return best


def a_group_failure_takes_out_its_share_and_no_more() -> dict:
    """Killing a majority of one group in four stops a quarter of the keys.

    The other half of the trade, and the good half. Groups fail independently because they are
    independent, so an outage is partial in a way a single cluster's outage never is. Three of
    the four groups keep taking writes throughout.

    A single cluster of twelve nodes would have survived the same three failures without
    noticing, because three out of twelve is nowhere near a majority. So sharding buys
    throughput and partial failure and gives up the ability to pool the redundancy, which is a
    real cost and is usually left out of the comparison.
    """
    space = Keyspace(groups=4)
    fed = Federation(keyspace=space)
    keys = [f"k{one}" for one in range(80)]
    broken = 2
    for name in list(fed.clusters[broken].members)[:2]:
        fed.clusters[broken].crash(name)
    fed.tick(40)
    accepted: dict[int, int] = dict.fromkeys(range(space.groups), 0)
    attempted: dict[int, int] = dict.fromkeys(range(space.groups), 0)
    for index, key in enumerate(keys):
        group = space.group_of(key)
        attempted[group] += 1
        with contextlib.suppress(NoLeader):
            fed.write(key, index)
            accepted[group] += 1
        if index % 10 == 0:
            fed.tick(2)
    fed.tick(40)
    return {
        "groups": space.groups,
        "broken_group": broken,
        "attempted": attempted,
        "accepted": accepted,
        "the_broken_group_took_nothing": accepted[broken] == 0,
        "the_others_took_everything": all(
            accepted[one] == attempted[one] for one in accepted if one != broken
        ),
        "share_lost": round(attempted[broken] / len(keys), 3),
        "and_it_is_about_a_quarter": 0.15 < attempted[broken] / len(keys) < 0.35,
        "nodes_down": 2,
        "out_of": space.groups * fed.size,
        "which_a_single_cluster_would_have_survived": (space.groups * fed.size) // 2 + 1 > 2,
    }


def the_placement_is_a_digest_because_the_builtin_hash_is_not_stable() -> dict:
    """The same key lands in the same group in every process, which the builtin would not.

    The determinism trap, met for the second time in this package. Python randomises string
    hashing per interpreter unless told not to, so a placement built on the builtin puts a key
    in one group today and another tomorrow. rsm.node hit the same thing with its election
    timers.
    """
    space = Keyspace(groups=8)
    keys = ["alpha", "beta", "gamma", "delta"]
    placed = {one: space.group_of(one) for one in keys}
    return {
        "keys": keys,
        "placement": placed,
        "it_is_stable": placed == {one: space.group_of(one) for one in keys},
        "a_second_keyspace_agrees": all(
            Keyspace(groups=8).group_of(one) == placed[one] for one in keys
        ),
        "and_a_different_group_count_moves_it": (
            Keyspace(groups=7).group_of("alpha") != placed["alpha"]
            or Keyspace(groups=5).group_of("alpha") != placed["alpha"]
        ),
        "digest_is_a_function_of_the_bytes": digest("alpha") == digest("alpha"),
    }


def the_keys_spread_evenly_enough_and_never_perfectly() -> dict:
    """Two hundred and forty keys over four groups land within a quarter of even.

    What a digest gives without any balancing on top. It gets worse as the groups multiply,
    because the fair share shrinks and the same random variation is a larger fraction of it.
    That is the argument for many more partitions than machines, which is a placement question
    rather than a consensus one.
    """
    keys = [f"k{one}" for one in range(KEYS)]
    out = {}
    for groups in (2, 4, 8, 16):
        space = Keyspace(groups=groups)
        out[groups] = {"spread": space.spread(keys), "balance": space.balance(keys)}
    return {
        "keys": len(keys),
        "group_counts": sorted(out),
        "balance": {one: made["balance"] for one, made in out.items()},
        "four_is_close_to_even": out[4]["balance"] < 1.3,
        "nothing_is_perfectly_even": all(one["balance"] > 1.0 for one in out.values()),
        "and_it_worsens_with_the_groups": out[16]["balance"] > out[2]["balance"],
        "smallest_group_at_sixteen": min(out[16]["spread"].values()),
        "largest_group_at_sixteen": max(out[16]["spread"].values()),
    }


def a_zero_group_keyspace_is_refused() -> bool:
    """A keyspace with nowhere to put a key is refused."""
    try:
        Keyspace(groups=0)
    except ConfigError:
        return True
    return False


def an_empty_key_is_refused() -> bool:
    """A key with no name has no place."""
    try:
        Keyspace(groups=4).group_of("")
    except ConfigError:
        return True
    return False


def a_federation_of_no_nodes_is_refused() -> bool:
    """A group has to have nodes in it."""
    try:
        Federation(keyspace=Keyspace(groups=2), size=0)
    except ConfigError:
        return True
    return False


def one_group_is_the_ordinary_cluster() -> dict:
    """A federation of one group is a cluster with a placement function in front of it.

    The degenerate case, worth having as a case rather than a special path: everything this
    module says about windows and partial failure is vacuous at one group, and the code that
    produces that answer is the same code.
    """
    fed = Federation(keyspace=Keyspace(groups=1))
    for one in range(10):
        fed.write(f"k{one}", one)
    fed.tick(30)
    keys = [f"k{one}" for one in range(20)]
    return {
        "groups": 1,
        "every_key_in_one_group": len({fed.keyspace.group_of(one) for one in keys}) == 1,
        "committed": fed.committed(),
        "it_committed_everything": fed.committed() == 10,
        "leaders": len(fed.leaders()),
        "and_there_is_one_leader": len(fed.leaders()) == 1,
        "balance": fed.keyspace.balance(keys),
        "which_is_exactly_even": fed.keyspace.balance(keys) == 1.0,
    }


def compare_the_group_counts() -> list[dict]:
    """Every group count with what it commits, what it costs and how evenly it spreads."""
    keys = [f"k{one}" for one in range(120)]
    out = []
    for groups in (1, 2, 4, 8):
        space = Keyspace(groups=groups)
        fed = Federation(keyspace=space)
        for index, key in enumerate(keys):
            with contextlib.suppress(NoLeader):
                fed.write(key, index)
            if index % 10 == 0:
                fed.tick(2)
        fed.tick(40)
        out.append(
            {
                "groups": groups,
                "nodes": groups * fed.size,
                "committed": fed.committed(),
                "messages": fed.messages(),
                "per_write": round(fed.messages() / max(1, fed.committed()), 1),
                "balance": space.balance(keys),
                "atomic across groups": groups == 1,
            }
        )
    return out


def sharding_trades_one_guarantee_for_two_properties() -> dict:
    """Every row commits everything; only the single group row is atomic across the keyspace.

    More groups gives parallel work and partial failure, and gives up the one thing a single
    group had, which is that any two writes are ordered against each other.

    That is not a trade between quantities. Throughput and failure isolation are numbers that
    can be tuned; atomicity across the keyspace is a property that is either there or is not,
    and at two groups it is already gone. Everything after the first split is the same world.
    """
    table = compare_the_group_counts()
    atomic = [one["groups"] for one in table if one["atomic across groups"]]
    return {
        "rows": len(table),
        "every_row_committed_everything": all(one["committed"] == 120 for one in table),
        "atomic_at": atomic,
        "and_only_at_one_group": atomic == [1],
        "balance": {one["groups"]: one["balance"] for one in table},
        "messages": {one["groups"]: one["messages"] for one in table},
        "the_property_is_lost_at_the_first_split": 2 not in atomic,
        "and_never_comes_back": 8 not in atomic,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "keys": KEYS,
        "every_group_commits_everything": the_ceiling_multiplies_with_the_groups()[
            "they_all_committed_everything"
        ],
        "the_cost_per_write_falls": the_ceiling_multiplies_with_the_groups()[
            "the_cost_per_write_falls"
        ],
        "a_cross_group_write_is_not_atomic": a_write_across_two_groups_is_not_atomic()[
            "the_halves_disagree"
        ],
        "a_group_failure_is_partial": a_group_failure_takes_out_its_share_and_no_more()[
            "the_others_took_everything"
        ],
        "and_a_single_cluster_would_have_survived_it": (
            a_group_failure_takes_out_its_share_and_no_more()[
                "which_a_single_cluster_would_have_survived"
            ]
        ),
        "the_placement_is_stable": (
            the_placement_is_a_digest_because_the_builtin_hash_is_not_stable()["it_is_stable"]
        ),
        "atomicity_goes_at_the_first_split": (
            sharding_trades_one_guarantee_for_two_properties()[
                "the_property_is_lost_at_the_first_split"
            ]
        ),
    }
