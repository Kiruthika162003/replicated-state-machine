from __future__ import annotations

import pytest

from rsm import recovery as restart
from rsm.errors import ConfigError, UnknownNode
from rsm.recovery import (
    PATIENCE,
    SETTLE,
    WRITES,
    Recovery,
    Run,
    cold_start,
    rolling,
    too_fast,
)


def test_every_pattern_keeps_its_data():
    assert restart.every_pattern_keeps_every_committed_entry()["every_one_kept_everything"]


def test_no_pattern_goes_backwards():
    assert restart.every_pattern_keeps_every_committed_entry()[
        "and_none_of_them_went_backwards"
    ]


def test_the_worst_availability_is_zero():
    made = restart.every_pattern_keeps_every_committed_entry()
    assert made["the_worst_availability"] == 0.0


def test_the_leader_last_order_costs_one_election():
    assert restart.restarting_the_leader_last_costs_exactly_one_election()["last_is_always_one"]


def test_the_leader_first_order_costs_more():
    assert restart.restarting_the_leader_last_costs_exactly_one_election()["and_first_is_not"]


def test_the_leader_last_order_is_more_available():
    assert restart.restarting_the_leader_last_costs_exactly_one_election()[
        "and_it_is_better_too"
    ]


def test_the_worst_leader_first_run_is_worse():
    made = restart.restarting_the_leader_last_costs_exactly_one_election()
    assert made["the_worst_first_run"] < made["leader_last_availability"]


def test_availability_rises_with_the_spacing():
    assert restart.the_spacing_buys_availability_and_never_buys_a_quorum()[
        "it_rises_with_the_spacing"
    ]


def test_no_spacing_loses_a_quorum():
    assert restart.the_spacing_buys_availability_and_never_buys_a_quorum()[
        "never_at_any_spacing"
    ]


def test_three_at_once_does():
    assert restart.the_spacing_buys_availability_and_never_buys_a_quorum()[
        "and_that_is_the_real_risk"
    ]


def test_a_cold_start_keeps_everything():
    assert restart.a_cold_start_accepts_nothing_and_forgets_nothing()["it_kept_everything"]


def test_a_cold_start_accepts_nothing():
    assert restart.a_cold_start_accepts_nothing_and_forgets_nothing()["it_accepted_nothing"]


def test_a_cold_start_loses_its_quorum():
    made = restart.a_cold_start_accepts_nothing_and_forgets_nothing()
    assert made["ticks_without_a_quorum"] > 0


def test_a_rolling_restart_beats_a_cold_start():
    assert restart.a_cold_start_accepts_nothing_and_forgets_nothing()["which_is_much_better"]


def test_a_cluster_of_none_is_refused():
    assert restart.a_restart_of_no_nodes_is_refused()


def test_restarting_a_running_node_is_refused():
    assert restart.restarting_a_running_node_is_refused()


def test_crashing_a_stranger_is_refused():
    assert restart.crashing_a_stranger_is_refused()


def test_three_nodes_lose_quorum_to_two_restarts():
    assert restart.a_smaller_cluster_tolerates_fewer_restarts_at_once()["three_loses_quorum"]


def test_five_nodes_do_not():
    assert restart.a_smaller_cluster_tolerates_fewer_restarts_at_once()["and_five_does_not"]


def test_seven_nodes_do_not_either():
    assert restart.a_smaller_cluster_tolerates_fewer_restarts_at_once()["and_nor_does_seven"]


def test_every_size_kept_its_data():
    assert restart.a_smaller_cluster_tolerates_fewer_restarts_at_once()[
        "everything_was_kept_anyway"
    ]


def test_the_pattern_table_covers_five():
    assert len(restart.compare_the_patterns()) == 5


def test_the_table_keeps_its_data_everywhere():
    assert restart.the_patterns_differ_only_in_availability_and_by_a_lot()[
        "every_one_kept_its_data"
    ]


def test_the_availability_spans_the_range():
    assert restart.the_patterns_differ_only_in_availability_and_by_a_lot()[
        "the_range_is_the_whole_range"
    ]


def test_safety_is_constant_across_the_table():
    assert restart.the_patterns_differ_only_in_availability_and_by_a_lot()[
        "and_safety_is_constant"
    ]


def test_the_summary_says_every_pattern_keeps_its_data():
    assert restart.summarise()["every_pattern_keeps_its_data"]


def test_the_summary_says_two_at_once_is_the_risk():
    assert restart.summarise()["two_at_once_is_the_real_risk"]


def test_a_recovery_reports_whether_it_kept_its_data():
    assert Recovery(name="x", committed_before=3, committed_after=3).kept


def test_a_recovery_that_lost_data_says_so():
    assert not Recovery(name="x", committed_before=3, committed_after=2).kept


def test_a_recovery_reports_its_uptime():
    assert Recovery(name="x", ticks=100, leaderless=20).uptime == 0.8


def test_a_recovery_with_no_ticks_has_no_uptime():
    assert Recovery(name="x").uptime == 0.0


def test_a_recovery_reports_its_worst_gap():
    assert Recovery(name="x", gaps=[3, 11, 2]).worst_gap == 11


def test_a_recovery_with_no_gap_reports_zero():
    assert Recovery(name="x").worst_gap == 0


def test_a_recovery_reports_its_availability():
    made = Recovery(name="x", attempted_during=10, accepted_during=7)
    assert made.availability == 0.7


def test_a_recovery_with_nothing_attempted_has_none():
    assert Recovery(name="x").availability == 0.0


def test_a_clean_recovery_is_truthy():
    assert Recovery(name="x", committed_before=1, committed_after=1)


def test_a_recovery_that_lost_quorum_is_falsy():
    assert not Recovery(name="x", committed_before=1, committed_after=1, lost_quorum=5)


def test_a_recovery_summarises():
    assert Recovery(name="named").as_dict()["pattern"] == "named"


def test_a_run_starts_with_writes_committed():
    assert Run(name="x", size=3).made.committed_before == WRITES


def test_a_run_of_no_nodes_raises():
    with pytest.raises(ConfigError):
        Run(name="x", size=0)


def test_a_run_advances_its_tick_count():
    made = Run(name="x", size=3)
    made.advance(10)
    assert made.made.ticks == 10


def test_a_run_bounces_a_node():
    made = Run(name="x", size=3)
    made.bounce("n0", down_for=5)
    assert "n0" not in made.cluster.down


def test_a_run_finishes_with_a_recovery():
    made = Run(name="x", size=3)
    assert made.finish().committed_after >= WRITES


def test_restarting_a_running_node_raises():
    made = Run(name="x", size=3)
    with pytest.raises(ConfigError):
        made.cluster.restart("n0")


def test_crashing_a_stranger_raises():
    made = Run(name="x", size=3)
    with pytest.raises(UnknownNode):
        made.cluster.crash("nowhere")


def test_a_cold_start_returns_a_recovery():
    assert cold_start(size=3).as_dict()["pattern"] == "cold start"


def test_a_rolling_restart_names_its_order():
    assert "leader last" in rolling(size=3).as_dict()["pattern"]


def test_a_leader_first_restart_says_so():
    assert "leader first" in rolling(size=3, leader_last=False).as_dict()["pattern"]


def test_too_fast_names_how_many():
    assert "3 at once" in too_fast(size=5).as_dict()["pattern"]


def test_the_settle_time_outlasts_an_election():
    assert SETTLE > 20


def test_the_patience_is_generous():
    assert PATIENCE > SETTLE


def test_the_run_writes_something_first():
    assert WRITES > 0
