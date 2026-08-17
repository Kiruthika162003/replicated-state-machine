from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.eval import workload as load
from rsm.eval.workload import LOADS, WRITES, Cost, Load, measure, measure_all
from rsm.net import Conditions


def test_every_workload_commits_what_it_attempts():
    assert load.every_workload_commits_what_it_attempts()["all_committed"]


def test_no_workload_lost_a_write():
    assert load.every_workload_commits_what_it_attempts()["and_none_lost_a_write"]


def test_the_workloads_committed_something():
    assert load.every_workload_commits_what_it_attempts()["total_committed"] > 100


def test_the_cost_grows_with_the_size():
    assert load.the_cost_per_write_is_set_by_the_size()["it_grows_with_the_size"]


def test_seven_costs_three_times_three():
    assert load.the_cost_per_write_is_set_by_the_size()["seven_over_three"] == 3.0


def test_five_costs_twice_three():
    assert load.the_cost_per_write_is_set_by_the_size()["five_over_three"] == 2.0


def test_the_size_ratios_match_the_peer_ratios():
    assert load.the_cost_per_write_is_set_by_the_size()["and_they_are_close"]


def test_a_long_workload_is_cheaper_per_write():
    assert load.the_number_of_writes_barely_changes_the_cost_per_write()[
        "the_long_one_is_cheaper_per_write"
    ]


def test_but_not_by_much():
    assert load.the_number_of_writes_barely_changes_the_cost_per_write()["but_not_by_much"]


def test_the_client_count_changes_nothing():
    assert load.the_client_count_changes_nothing()["they_are_the_same"]


def test_the_client_difference_is_zero():
    assert load.the_client_count_changes_nothing()["difference"] == 0


def test_loss_sends_fewer_messages():
    assert load.a_lossy_link_costs_fewer_messages_and_more_ticks()["loss_sends_fewer"]


def test_loss_still_commits_everything():
    assert load.a_lossy_link_costs_fewer_messages_and_more_ticks()["both_committed_everything"]


def test_jitter_costs_more_messages():
    assert load.a_jittery_link_is_the_most_expensive_setting_of_all()["jitter_costs_more"]


def test_jitter_costs_three_times_as_much():
    assert load.a_jittery_link_is_the_most_expensive_setting_of_all()["by_this_factor"] > 2


def test_the_two_link_faults_go_opposite_ways():
    assert load.a_jittery_link_is_the_most_expensive_setting_of_all()[
        "so_the_two_link_faults_go_opposite_ways"
    ]


def test_both_link_faults_still_commit():
    assert load.a_jittery_link_is_the_most_expensive_setting_of_all()[
        "and_both_still_commit_everything"
    ]


def test_the_same_workload_costs_the_same():
    assert load.the_same_workload_costs_the_same_every_time()["they_are_identical"]


def test_the_repeat_found_one_shape():
    assert load.the_same_workload_costs_the_same_every_time()["distinct"] == 1


def test_the_repeat_was_a_real_workload():
    assert load.the_same_workload_costs_the_same_every_time()["and_it_is_a_real_workload"]


def test_the_seed_changes_nothing():
    assert load.the_seed_does_not_change_the_cost_at_all()["they_are_all_the_same"]


def test_the_seed_spread_is_zero():
    assert load.the_seed_does_not_change_the_cost_at_all()["spread"] == 0


def test_one_seed_is_a_fair_measurement():
    assert load.the_seed_does_not_change_the_cost_at_all()["so_one_seed_is_a_fair_measurement"]


def test_an_idle_cluster_still_sends():
    assert load.a_workload_of_no_writes_still_costs_messages()["it_sent_messages_anyway"]


def test_a_busy_cluster_sends_more():
    assert load.a_workload_of_no_writes_still_costs_messages()["the_busy_one_sent_more"]


def test_an_idle_cluster_commits_nothing():
    assert load.a_workload_of_no_writes_still_costs_messages()["idle_committed"] == 0


def test_a_dead_node_loses_no_writes():
    assert load.a_workload_with_a_dead_node_loses_no_writes()["it_lost_nothing"]


def test_a_dead_node_costs_an_election():
    assert load.a_workload_with_a_dead_node_loses_no_writes()["and_it_took_an_election"]


def test_four_nodes_remain():
    assert load.a_workload_with_a_dead_node_loses_no_writes()["up"] == 4


def test_a_negative_write_count_is_refused():
    assert load.a_negative_write_count_is_refused()


def test_a_zero_client_workload_is_refused():
    assert load.a_zero_client_workload_is_refused()


def test_a_zero_size_workload_is_refused():
    assert load.a_zero_size_workload_is_refused()


def test_the_workload_table_covers_eight():
    assert len(load.compare_the_workloads()) == 8


def test_the_link_moves_the_cost_more_than_the_size():
    assert load.the_link_moves_the_cost_more_than_the_size_does()["the_link_moves_it_more"]


def test_size_is_still_linear():
    assert load.the_link_moves_the_cost_more_than_the_size_does()["and_size_is_still_linear"]


def test_every_workload_in_the_table_committed():
    assert load.the_link_moves_the_cost_more_than_the_size_does()["every_workload_committed"]


def test_the_summary_says_the_counts_repeat():
    assert load.summarise()["the_counts_repeat"]


def test_the_summary_says_the_link_beats_the_size():
    assert load.summarise()["the_link_beats_the_size"]


def test_a_load_summarises():
    assert Load(name="x").as_dict()["workload"] == "x"


def test_a_load_defaults_to_five_nodes():
    assert Load(name="x").size == 5


def test_a_load_defaults_to_one_client():
    assert Load(name="x").clients == 1


def test_a_lossy_load_says_so():
    assert Load(name="x", conditions=Conditions(loss=0.2)).as_dict()["lossy"]


def test_a_clean_load_does_not():
    assert not Load(name="x").as_dict()["lossy"]


def test_a_negative_write_count_raises():
    with pytest.raises(ConfigError):
        Load(name="x", writes=-5)


def test_a_zero_size_raises():
    with pytest.raises(ConfigError):
        Load(name="x", size=0)


def test_a_cost_reports_its_per_write():
    made = Cost(
        load=Load(name="x"), messages=100, ticks=10, committed=10, elections=1, attempted=10
    )
    assert made.per_write == 10.0


def test_a_cost_with_nothing_committed_has_no_per_write():
    made = Cost(
        load=Load(name="x"), messages=100, ticks=10, committed=0, elections=1, attempted=10
    )
    assert made.per_write == 0.0


def test_a_cost_reports_its_availability():
    made = Cost(
        load=Load(name="x"), messages=100, ticks=10, committed=5, elections=1, attempted=10
    )
    assert made.availability == 0.5


def test_a_cost_with_nothing_attempted_has_no_availability():
    made = Cost(
        load=Load(name="x"), messages=0, ticks=10, committed=0, elections=1, attempted=0
    )
    assert made.availability == 0.0


def test_a_cost_summarises():
    made = measure(Load(name="x", size=3, writes=4))
    assert made.as_dict()["workload"] == "x"


def test_measuring_a_workload_commits_it():
    assert measure(Load(name="x", size=3, writes=6)).committed == 6


def test_measuring_a_workload_sends_messages():
    assert measure(Load(name="x", size=3, writes=6)).messages > 0


def test_measuring_all_covers_every_load():
    assert len(measure_all()) == len(LOADS)


def test_the_write_count_is_twenty():
    assert WRITES == 20


def test_every_named_load_is_named_after_itself():
    assert all(name == one.name for name, one in LOADS.items())
