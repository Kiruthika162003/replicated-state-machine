from __future__ import annotations

import pytest

from rsm import observe as watch
from rsm.errors import ConfigError
from rsm.observe import (
    EVERY,
    NOTICE,
    SCENARIOS,
    SIGNALS,
    WINDOW,
    Reading,
    matrix,
    noticed,
    readings,
)


def test_the_commit_rate_catches_both_real_faults():
    assert watch.only_the_commit_rate_catches_every_fault_that_matters()[
        "the_commit_rate_caught_both"
    ]


def test_the_commit_rate_is_the_only_one_that_does():
    assert watch.only_the_commit_rate_catches_every_fault_that_matters()[
        "and_it_is_the_only_one"
    ]


def test_the_deaf_leader_is_seen_by_one_signal():
    made = watch.only_the_commit_rate_catches_every_fault_that_matters()
    assert made["how_many_saw_it"] == 1


def test_the_deaf_leader_row_is_mostly_blank():
    made = watch.only_the_commit_rate_catches_every_fault_that_matters()
    assert sum(made["the_deaf_leader_row"].values()) < made["out_of"] / 2


def test_the_lag_is_lower_under_a_deaf_leader():
    assert watch.the_replica_lag_moves_the_wrong_way_under_the_worst_fault()[
        "it_is_lower_than_healthy"
    ]


def test_the_lag_rises_under_a_deaf_follower():
    assert watch.the_replica_lag_moves_the_wrong_way_under_the_worst_fault()[
        "and_the_follower_fault_raises_it"
    ]


def test_the_lag_is_inverted_by_one_fault_and_not_the_other():
    assert watch.the_replica_lag_moves_the_wrong_way_under_the_worst_fault()[
        "so_the_signal_is_inverted_by_one_and_not_the_other"
    ]


def test_the_deaf_leader_commits_nothing():
    assert watch.the_replica_lag_moves_the_wrong_way_under_the_worst_fault()["which_is_nothing"]


def test_the_term_rate_fires_on_handled_faults():
    assert watch.the_noisy_signals_fire_on_the_faults_the_cluster_handled()[
        "the_term_rate_fires_on_all_of_them"
    ]


def test_the_lag_fires_on_handled_faults():
    assert watch.the_noisy_signals_fire_on_the_faults_the_cluster_handled()[
        "and_so_does_the_lag"
    ]


def test_the_commit_rate_fires_on_none_of_them():
    assert watch.the_noisy_signals_fire_on_the_faults_the_cluster_handled()[
        "the_commit_rate_fires_on_none"
    ]


def test_three_signals_are_quiet():
    assert watch.the_noisy_signals_fire_on_the_faults_the_cluster_handled()[
        "there_are_three_quiet_ones"
    ]


def test_only_one_quiet_signal_catches_the_real_faults():
    assert watch.the_noisy_signals_fire_on_the_faults_the_cluster_handled()[
        "but_only_one_of_them_catches_the_real_faults"
    ]


def test_an_unknown_signal_is_refused():
    assert watch.an_unknown_signal_is_refused()


def test_a_zero_window_is_refused():
    assert watch.a_zero_window_is_refused()


def test_a_zero_baseline_notices_a_real_move():
    assert watch.a_signal_from_a_zero_baseline_is_compared_absolutely()["it_notices_the_second"]


def test_a_zero_baseline_ignores_a_tiny_move():
    assert watch.a_signal_from_a_zero_baseline_is_compared_absolutely()[
        "and_a_tiny_move_is_ignored"
    ]


def test_the_scenario_table_covers_them_all():
    assert len(watch.compare_the_scenarios()) == len(SCENARIOS)


def test_leader_presence_catches_the_least():
    assert watch.the_cheapest_signal_to_export_is_the_least_useful_one()[
        "it_is_the_least_of_them"
    ]


def test_leader_presence_is_perfect_under_a_deaf_leader():
    made = watch.the_cheapest_signal_to_export_is_the_least_useful_one()
    assert made["which_is_perfect"]


def test_the_deaf_leader_committed_nothing_meanwhile():
    made = watch.the_cheapest_signal_to_export_is_the_least_useful_one()
    assert made["and_that_is_nothing"]


def test_the_summary_says_the_commit_rate_catches_everything():
    assert watch.summarise()["the_commit_rate_catches_everything"]


def test_the_summary_says_the_lag_is_inverted():
    assert watch.summarise()["the_lag_is_inverted"]


def test_the_summary_counts_the_signals():
    assert watch.summarise()["signals"] == len(SIGNALS)


def test_a_reading_reports_leader_uptime():
    assert Reading(name="x", ticks=100, leader_ticks=80).leader_uptime == 0.8


def test_a_reading_with_no_ticks_has_no_uptime():
    assert Reading(name="x").leader_uptime == 0.0


def test_a_reading_reports_its_commit_rate():
    assert Reading(name="x", attempted=10, committed=7).commit_rate == 0.7


def test_a_reading_with_no_attempts_has_no_rate():
    assert Reading(name="x").commit_rate == 0.0


def test_a_reading_reports_its_message_rate():
    assert Reading(name="x", ticks=100, messages=250).message_rate == 2.5


def test_a_reading_reports_its_term_rate():
    assert Reading(name="x", ticks=100, terms=4).term_rate == 4.0


def test_a_reading_reports_its_worst_lag():
    assert Reading(name="x", applied_lag=[1, 8, 3]).worst_lag == 8


def test_a_reading_with_no_lag_reports_zero():
    assert Reading(name="x").worst_lag == 0


def test_a_reading_names_five_signals():
    assert set(Reading(name="x").signals()) == set(SIGNALS)


def test_a_reading_summarises():
    assert Reading(name="named").as_dict()["run"] == "named"


def test_a_falling_uptime_is_noticed():
    assert noticed(1.0, 0.5, "leader present")


def test_a_rising_uptime_is_not():
    assert not noticed(0.5, 1.0, "leader present")


def test_a_rising_term_rate_is_noticed():
    assert noticed(1.0, 5.0, "term rate")


def test_a_falling_term_rate_is_not():
    assert not noticed(5.0, 1.0, "term rate")


def test_a_small_move_is_ignored():
    assert not noticed(1.0, 0.95, "commit rate")


def test_a_large_move_is_not():
    assert noticed(1.0, 0.5, "commit rate")


def test_the_threshold_is_relative():
    assert noticed(100.0, 50.0, "message rate") and not noticed(100.0, 95.0, "message rate")


def test_an_unknown_signal_raises():
    with pytest.raises(ConfigError):
        noticed(1.0, 2.0, "nonsense")


def test_the_matrix_has_a_row_per_fault():
    assert len(matrix()) == len(SCENARIOS) - 1


def test_the_matrix_has_a_column_per_signal():
    assert all(set(row) == set(SIGNALS) for row in matrix().values())


def test_the_readings_cover_every_scenario():
    assert set(readings()) == set(SCENARIOS)


def test_the_healthy_run_commits_everything():
    assert readings()["healthy"].commit_rate == 1.0


def test_the_healthy_run_keeps_a_leader():
    assert readings()["healthy"].leader_uptime > 0.95


def test_the_deaf_leader_keeps_a_leader_too():
    assert readings()["deaf leader"].leader_uptime > 0.95


def test_the_deaf_leader_commits_nothing_at_all():
    assert readings()["deaf leader"].commit_rate == 0.0


def test_the_window_is_long_enough_for_several_elections():
    assert WINDOW > 100


def test_writes_are_attempted_regularly():
    assert 0 < EVERY < 50


def test_the_threshold_is_a_share():
    assert 0 < NOTICE < 1
