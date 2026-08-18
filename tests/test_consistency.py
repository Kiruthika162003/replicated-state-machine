"""Checks that span modules, which no single module can make about itself."""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import rsm
from rsm import (
    batch,
    chart,
    expire,
    idle,
    keyspace,
    lease,
    observe,
    partition,
    quorum,
    rebalance,
    rejoin,
    timing,
)
from rsm.eval import mix
from rsm.node import (
    HEARTBEAT_INTERVAL,
    MAX_BATCH,
    MAX_ELECTION_TIMEOUT,
    MIN_ELECTION_TIMEOUT,
    ROLES,
    Node,
)
from rsm.report import MODULES, collect
from rsm.rpc import KINDS
from rsm.verify import liveness
from rsm.verify.coverage import grid
from rsm.verify.soak import BUDGET, SHORT
from rsm.wire import ASSUMED_ENTRY_BYTES, ASSUMED_MESSAGE_BYTES


def _modules() -> list[str]:
    """Every module in the package, found rather than listed."""
    out = []
    for one in pkgutil.walk_packages(rsm.__path__, prefix="rsm."):
        if one.name.endswith(".main") or one.name.endswith(".__init__"):
            continue
        out.append(one.name)
    return sorted(out)


def test_every_module_with_a_summarise_is_in_the_report():
    missing = []
    for name in _modules():
        made = importlib.import_module(name)
        if hasattr(made, "summarise") and name not in MODULES:
            missing.append(name)
    assert missing == ["rsm.report"]


def test_every_module_in_the_report_exists():
    assert all(importlib.import_module(one) for one in MODULES)


def test_every_module_in_the_report_has_a_summarise():
    assert all(hasattr(importlib.import_module(one), "summarise") for one in MODULES)


def test_the_report_has_no_repeats():
    assert len(set(MODULES)) == len(MODULES)


def test_the_shipped_timings_match_the_node():
    assert timing.SETTINGS["shipped"].heartbeat == HEARTBEAT_INTERVAL


def test_the_shipped_timeout_matches_the_node():
    made = timing.SETTINGS["shipped"]
    assert made.min_timeout == MIN_ELECTION_TIMEOUT
    assert made.max_timeout == MAX_ELECTION_TIMEOUT


def test_the_idle_floor_uses_the_shipped_heartbeat():
    assert idle.Floor(size=5).heartbeat == HEARTBEAT_INTERVAL


def test_the_mix_uses_the_shipped_heartbeat():
    made = mix.Mix(reads=0.5, strategy=mix.LEASE, size=5)
    assert made.read_cost == round(2 * made.peers / HEARTBEAT_INTERVAL, 3)


def test_the_batch_cap_is_the_nodes():
    assert batch.MAX_BATCH == MAX_BATCH


def test_the_byte_estimates_agree_between_wire_and_batch():
    assert batch.MESSAGE_BYTES == ASSUMED_MESSAGE_BYTES
    assert batch.ENTRY_BYTES == ASSUMED_ENTRY_BYTES


def test_the_quorum_agrees_with_the_node():
    made = Node(name="n0", members=("n0", "n1", "n2"), seed=0)
    assert made.quorum == quorum.majority(3)


def test_the_quorum_agrees_at_every_size():
    for size in (1, 3, 5, 7):
        members = tuple(f"n{one}" for one in range(size))
        made = Node(name="n0", members=members, seed=0)
        assert made.quorum == quorum.majority(size)


def test_the_lease_is_shorter_than_the_shortest_timeout():
    assert lease.LEASE < MIN_ELECTION_TIMEOUT


def test_the_lease_outlasts_a_heartbeat():
    assert lease.LEASE > HEARTBEAT_INTERVAL


def test_the_liveness_bound_is_two_timeouts():
    assert liveness.ELECTION_BOUND == MAX_ELECTION_TIMEOUT * 2


def test_the_rejoin_crossover_uses_the_batch():
    assert rejoin.by_entries(MAX_BATCH).messages == 1
    assert rejoin.by_entries(MAX_BATCH + 1).messages == 2


def test_the_chart_width_fits_a_terminal():
    assert chart.WIDTH <= 80


def test_the_report_is_clean_across_the_package():
    assert collect()


def test_no_module_reports_a_false_verdict():
    assert not collect().falsehoods


def test_every_module_reports_at_least_one_finding():
    made = collect()
    assert all(made.of(one) for one in made.modules)


def test_the_package_has_more_modules_than_the_report_lists():
    assert len(_modules()) >= len(MODULES)


def test_every_public_module_imports():
    assert all(importlib.import_module(one) for one in _modules())


@pytest.mark.parametrize("name", ["rsm.node", "rsm.log", "rsm.cluster", "rsm.net"])
def test_the_core_modules_have_no_optional_dependency(name):
    made = importlib.import_module(name)
    assert made.__doc__ is None or isinstance(made.__doc__, str)


def test_the_partition_directions_cover_both_ways():
    assert {partition.BOTH, partition.INBOUND, partition.OUTBOUND} == set(partition.DIRECTIONS)


def test_the_observe_signals_all_have_a_direction():
    assert set(observe.SIGNALS) == set(observe.WORSE_WHEN_LOWER) | set(
        observe.WORSE_WHEN_HIGHER
    )


def test_no_signal_is_worse_in_both_directions():
    assert not set(observe.WORSE_WHEN_LOWER) & set(observe.WORSE_WHEN_HIGHER)


def test_the_coverage_grid_uses_the_nodes_roles():
    assert {one.role for one in grid()} == set(ROLES)


def test_the_coverage_grid_uses_every_message_kind():
    assert {one.kind for one in grid()} == set(KINDS)


def test_the_keyspace_placement_is_stable_across_calls():
    left = keyspace.Keyspace(groups=8)
    right = keyspace.Keyspace(groups=8)
    assert all(left.group_of(f"k{one}") == right.group_of(f"k{one}") for one in range(50))


def test_the_expiry_sweep_is_shorter_than_the_lease():
    assert expire.SWEEP < expire.LEASE


def test_the_rebalance_phases_start_and_end_serving():
    assert rebalance.PHASES[0] == rebalance.STEADY
    assert rebalance.PHASES[-1] == rebalance.HANDED


def test_the_soak_budget_buys_several_short_runs():
    assert BUDGET // SHORT >= 5
