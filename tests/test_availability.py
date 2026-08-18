from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.eval import availability as uptime
from rsm.eval.availability import (
    EVERY,
    REPAIR,
    SEEDS,
    SIZES,
    WINDOW,
    Watch,
    binomial,
    watch,
)


def test_the_formula_always_overstates():
    assert uptime.the_binomial_gets_better_with_size_and_the_cluster_does_not()[
        "the_formula_always_overstates"
    ]


def test_the_error_grows_with_size():
    assert uptime.the_binomial_gets_better_with_size_and_the_cluster_does_not()[
        "the_error_grows_with_size"
    ]


def test_the_error_at_nine_is_enormous():
    made = uptime.the_binomial_gets_better_with_size_and_the_cluster_does_not()
    assert made["at_nine"] > 1000


def test_the_error_at_three_is_modest():
    made = uptime.the_binomial_gets_better_with_size_and_the_cluster_does_not()
    assert made["at_three"] < 10


def test_the_measured_value_plateaus():
    assert uptime.the_binomial_gets_better_with_size_and_the_cluster_does_not()[
        "the_measured_value_plateaus"
    ]


def test_the_predicted_value_does_not():
    assert uptime.the_binomial_gets_better_with_size_and_the_cluster_does_not()[
        "while_the_predicted_one_does_not"
    ]


def test_most_runs_keep_a_majority_throughout():
    assert uptime.a_majority_is_up_almost_always_and_writes_still_fail()[
        "and_most_runs_had_one"
    ]


def test_some_runs_lose_writes_with_a_full_majority():
    assert uptime.a_majority_is_up_almost_always_and_writes_still_fail()[
        "some_of_them_still_lost_writes"
    ]


def test_the_quorum_availability_is_exactly_one():
    made = uptime.a_majority_is_up_almost_always_and_writes_still_fail()
    assert made["which_is_exactly_one"]


def test_the_missing_part_is_agreement():
    assert uptime.a_majority_is_up_almost_always_and_writes_still_fail()[
        "so_the_missing_part_is_agreement"
    ]


def test_the_outage_is_shorter_than_a_repair():
    assert uptime.the_outage_after_a_failure_is_an_election_and_not_a_repair()[
        "it_is_shorter_than_a_repair"
    ]


def test_the_outage_is_about_an_election():
    assert uptime.the_outage_after_a_failure_is_an_election_and_not_a_repair()[
        "and_it_is_about_an_election_timeout"
    ]


def test_the_repair_is_several_times_the_outage():
    made = uptime.the_outage_after_a_failure_is_an_election_and_not_a_repair()
    assert made["by_this_factor"] > 1.5


def test_some_runs_had_an_outage():
    made = uptime.the_outage_after_a_failure_is_an_election_and_not_a_repair()
    assert made["runs_with_an_outage"] > 0


def test_a_zero_window_is_refused():
    assert uptime.a_zero_window_is_refused()


def test_a_negative_failure_count_is_refused():
    assert uptime.a_negative_failure_count_is_refused()


def test_an_impossible_probability_is_refused():
    assert uptime.a_probability_outside_the_range_is_refused()


def test_a_cluster_of_none_is_refused():
    assert uptime.a_cluster_of_no_nodes_has_no_majority()


def test_perfect_nodes_give_perfect_availability():
    assert uptime.the_formula_agrees_with_itself_at_the_boundaries()["all_perfect_are_one"]


def test_dead_nodes_give_none():
    assert uptime.the_formula_agrees_with_itself_at_the_boundaries()["all_dead_are_zero"]


def test_a_coin_flip_gives_a_half():
    assert uptime.the_formula_agrees_with_itself_at_the_boundaries()[
        "and_an_odd_size_gives_exactly_a_half"
    ]


def test_a_larger_cluster_needs_less_from_each_node():
    assert uptime.a_bigger_cluster_needs_more_of_it_up_to_reach_the_same_number()[
        "a_larger_cluster_needs_less"
    ]


def test_the_percentage_barely_moves():
    assert uptime.a_bigger_cluster_needs_more_of_it_up_to_reach_the_same_number()[
        "the_percentage_barely_moves"
    ]


def test_the_allowed_downtime_grows_a_lot():
    assert uptime.a_bigger_cluster_needs_more_of_it_up_to_reach_the_same_number()[
        "and_that_is_a_large_factor"
    ]


def test_the_size_table_covers_them_all():
    assert len(uptime.compare_the_sizes()) == len(SIZES)


def test_the_summary_says_the_formula_overstates():
    assert uptime.summarise()["the_formula_always_overstates"]


def test_the_summary_says_the_outage_is_an_election():
    assert uptime.summarise()["the_outage_is_an_election"]


def test_the_summary_counts_the_seeds():
    assert uptime.summarise()["seeds"] == SEEDS


def test_a_majority_of_perfect_nodes_is_certain():
    assert binomial(5, 1.0) == 1.0


def test_a_majority_of_dead_nodes_is_impossible():
    assert binomial(5, 0.0) == 0.0


def test_a_larger_cluster_beats_a_smaller_one():
    assert binomial(7, 0.9) > binomial(3, 0.9)


def test_an_even_size_is_no_better_than_the_odd_below_it():
    assert binomial(6, 0.9) <= binomial(5, 0.9)


def test_a_single_node_is_its_own_availability():
    assert binomial(1, 0.9) == 0.9


def test_a_bad_probability_raises():
    with pytest.raises(ConfigError):
        binomial(3, -0.1)


def test_a_zero_size_raises():
    with pytest.raises(ConfigError):
        binomial(0, 0.9)


def test_a_watch_reports_write_availability():
    made = Watch(name="x", size=3, attempts=10, committed=9)
    assert made.write_availability == 0.9


def test_a_watch_with_no_attempts_has_none():
    assert Watch(name="x", size=3).write_availability == 0.0


def test_a_watch_reports_quorum_availability():
    made = Watch(name="x", size=3, majority_ticks=90, ticks=100)
    assert made.quorum_availability == 0.9


def test_a_watch_reports_leader_availability():
    made = Watch(name="x", size=3, leader_ticks=80, ticks=100)
    assert made.leader_availability == 0.8


def test_a_watch_with_no_ticks_reports_zero():
    made = Watch(name="x", size=3)
    assert made.quorum_availability == 0.0 and made.leader_availability == 0.0


def test_a_watch_reports_node_availability():
    made = Watch(name="x", size=4, node_ticks=380, ticks=100)
    assert made.node_availability == 0.95


def test_a_watch_predicts_from_its_nodes():
    made = Watch(name="x", size=3, node_ticks=300, ticks=100)
    assert made.predicted == 1.0


def test_a_watch_reports_its_gap():
    made = Watch(name="x", size=3, attempts=10, committed=8, majority_ticks=100, ticks=100)
    assert made.gap == 0.2


def test_a_watch_reports_its_worst_outage():
    assert Watch(name="x", size=3, downtime=[2, 9, 4]).worst_outage == 9


def test_a_watch_with_no_outage_reports_zero():
    assert Watch(name="x", size=3).worst_outage == 0


def test_a_complete_watch_is_truthy():
    assert Watch(name="x", size=3, attempts=5, committed=5)


def test_a_watch_that_lost_a_write_is_falsy():
    assert not Watch(name="x", size=3, attempts=5, committed=4)


def test_a_watch_summarises():
    assert Watch(name="named", size=3).as_dict()["run"] == "named"


def test_watching_attempts_writes():
    assert watch("x", size=3, window=200, failures=1).attempts > 0


def test_watching_commits_most_writes():
    made = watch("x", size=3, window=200, failures=1)
    assert made.write_availability > 0.5


def test_watching_counts_every_tick():
    assert watch("x", size=3, window=200, failures=1).ticks == 200


def test_watching_with_no_failures_loses_nothing():
    assert watch("x", size=3, window=200, failures=0)


def test_a_zero_window_raises():
    with pytest.raises(ConfigError):
        watch("x", window=0)


def test_a_negative_failure_count_raises():
    with pytest.raises(ConfigError):
        watch("x", failures=-2)


def test_the_window_is_long_enough_for_several_failures():
    assert WINDOW > REPAIR * 10


def test_writes_are_attempted_regularly():
    assert 0 < EVERY < 50


def test_the_sizes_are_odd():
    assert all(one % 2 == 1 for one in SIZES)
