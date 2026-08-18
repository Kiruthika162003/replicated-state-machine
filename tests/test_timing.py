from __future__ import annotations

import pytest

from rsm import timing as clocks
from rsm.errors import ConfigError
from rsm.node import HEARTBEAT_INTERVAL, MIN_ELECTION_TIMEOUT
from rsm.timing import (
    RECOMMENDED_RATIO,
    SETTINGS,
    WINDOW,
    Timings,
    Trial,
    trial,
)


def test_a_fixed_timeout_elects_nobody_at_any_seed():
    assert clocks.a_fixed_timeout_never_elects_anyone_at_all()["no_seed_elected_anyone"]


def test_a_fixed_timeout_burns_the_same_terms_at_every_seed():
    assert clocks.a_fixed_timeout_never_elects_anyone_at_all()[
        "and_every_seed_burned_the_same_terms"
    ]


def test_one_node_elects_itself_on_a_fixed_timeout():
    assert clocks.a_fixed_timeout_never_elects_anyone_at_all()["one_node_elects_itself"]


def test_nothing_larger_than_one_elects_on_a_fixed_timeout():
    assert clocks.a_fixed_timeout_never_elects_anyone_at_all()["and_nothing_larger_does"]


def test_a_fixed_timeout_has_no_uptime():
    assert clocks.a_fixed_timeout_never_elects_anyone_at_all()["uptime_at_five"] == 0.0


def test_a_narrow_range_is_stable_everywhere():
    assert clocks.one_tick_of_spread_is_enough_to_break_the_tie()["narrow_is_stable_everywhere"]


def test_a_fixed_range_is_stable_nowhere():
    assert clocks.one_tick_of_spread_is_enough_to_break_the_tie()["and_fixed_is_stable_nowhere"]


def test_the_narrow_spread_is_one_tick():
    assert clocks.one_tick_of_spread_is_enough_to_break_the_tie()["narrow_spread"] == 1


def test_a_wide_range_is_no_more_stable():
    assert clocks.one_tick_of_spread_is_enough_to_break_the_tie()[
        "the_wide_range_is_no_more_stable"
    ]


def test_the_inverted_setting_reads_as_healthy():
    assert clocks.a_heartbeat_longer_than_the_timeout_keeps_a_leader_and_commits_nothing()[
        "which_reads_as_healthy"
    ]


def test_the_inverted_setting_commits_almost_nothing():
    assert clocks.a_heartbeat_longer_than_the_timeout_keeps_a_leader_and_commits_nothing()[
        "but_it_committed_almost_nothing"
    ]


def test_the_inverted_setting_is_the_cheaper_one():
    assert clocks.a_heartbeat_longer_than_the_timeout_keeps_a_leader_and_commits_nothing()[
        "and_it_is_the_cheaper_of_the_two"
    ]


def test_the_inverted_heartbeat_cannot_arrive_in_time():
    assert clocks.a_heartbeat_longer_than_the_timeout_keeps_a_leader_and_commits_nothing()[
        "the_heartbeat_cannot_arrive_in_time"
    ]


def test_a_slow_link_commits_nothing():
    assert clocks.an_election_timeout_below_the_round_trip_is_fatal()["it_committed_nothing"]


def test_a_fast_link_commits_everything():
    assert clocks.an_election_timeout_below_the_round_trip_is_fatal()[
        "which_committed_everything"
    ]


def test_the_slow_link_differs_only_in_delay():
    assert clocks.an_election_timeout_below_the_round_trip_is_fatal()[
        "and_the_only_difference_is_the_delay"
    ]


def test_the_slow_round_trip_eats_the_timeout():
    assert clocks.an_election_timeout_below_the_round_trip_is_fatal()[
        "the_round_trip_is_most_of_the_timeout"
    ]


def test_the_tight_setting_works_at_three():
    assert clocks.a_timeout_that_works_at_three_nodes_fails_at_seven()["it_works_at_three"]


def test_the_tight_setting_fails_at_seven():
    assert clocks.a_timeout_that_works_at_three_nodes_fails_at_seven()["and_fails_at_seven"]


def test_the_tight_churn_grows_with_the_size():
    assert clocks.a_timeout_that_works_at_three_nodes_fails_at_seven()[
        "the_churn_grows_with_the_size"
    ]


def test_the_shipped_setting_works_at_every_size():
    assert clocks.a_timeout_that_works_at_three_nodes_fails_at_seven()[
        "shipped_works_at_every_size"
    ]


def test_the_per_node_cost_is_not_flat():
    assert clocks.a_timeout_that_works_at_three_nodes_fails_at_seven()["which_is_not_flat"]


def test_the_per_peer_cost_is_flat():
    assert clocks.a_timeout_that_works_at_three_nodes_fails_at_seven()[
        "but_the_per_peer_cost_is"
    ]


def test_the_shipped_heartbeat_lands_in_time():
    assert clocks.the_shipped_settings_satisfy_the_inequality_they_are_meant_to()[
        "a_heartbeat_lands_in_time"
    ]


def test_an_election_fits_inside_the_shipped_timeout():
    assert clocks.the_shipped_settings_satisfy_the_inequality_they_are_meant_to()[
        "an_election_fits"
    ]


def test_the_shipped_ratio_is_below_the_usual_advice():
    assert clocks.the_shipped_settings_satisfy_the_inequality_they_are_meant_to()[
        "which_is_below_the_usual_advice"
    ]


def test_a_deadline_collision_is_ordinary():
    assert clocks.the_shipped_settings_satisfy_the_inequality_they_are_meant_to()[
        "so_a_collision_is_ordinary"
    ]


def test_the_same_timings_replay_identically():
    assert clocks.the_same_timings_and_seed_replay_the_same_run()["they_are_identical"]


def test_the_replay_found_one_shape():
    assert clocks.the_same_timings_and_seed_replay_the_same_run()["distinct"] == 1


def test_the_replay_was_a_real_run():
    assert clocks.the_same_timings_and_seed_replay_the_same_run()["and_it_is_a_real_run"]


def test_every_seed_commits_everything():
    assert clocks.a_different_seed_moves_the_counts_but_not_the_verdict()[
        "all_committed_everything"
    ]


def test_every_seed_is_stable():
    assert clocks.a_different_seed_moves_the_counts_but_not_the_verdict()["all_stable"]


def test_the_seed_moves_the_cost():
    assert clocks.a_different_seed_moves_the_counts_but_not_the_verdict()["the_cost_moves"]


def test_the_seed_spread_is_small():
    assert clocks.a_different_seed_moves_the_counts_but_not_the_verdict()["spread"] < 1.1


def test_the_worst_seed_is_still_good():
    assert clocks.a_different_seed_moves_the_counts_but_not_the_verdict()[
        "and_the_worst_is_still_good"
    ]


def test_a_fast_heartbeat_costs_more():
    assert clocks.a_heartbeat_of_one_costs_three_times_the_traffic_for_nothing()[
        "the_fast_one_costs_more"
    ]


def test_a_fast_heartbeat_costs_about_three_times():
    made = clocks.a_heartbeat_of_one_costs_three_times_the_traffic_for_nothing()
    assert made["by_this_factor"] > 2.5


def test_a_fast_heartbeat_buys_no_commits():
    assert clocks.a_heartbeat_of_one_costs_three_times_the_traffic_for_nothing()[
        "and_buys_no_commits"
    ]


def test_a_lazy_heartbeat_loses_the_leadership():
    assert clocks.a_heartbeat_of_one_costs_three_times_the_traffic_for_nothing()[
        "but_it_loses_the_leadership"
    ]


def test_the_single_beat_rule_allowed_the_lazy_heartbeat():
    assert clocks.a_heartbeat_of_one_costs_three_times_the_traffic_for_nothing()[
        "which_the_single_beat_rule_allows"
    ]


def test_the_two_beat_rule_refused_it():
    assert clocks.a_heartbeat_of_one_costs_three_times_the_traffic_for_nothing()[
        "and_the_two_beat_rule_does_not"
    ]


def test_the_single_beat_rule_is_optimistic():
    assert clocks.the_heartbeat_has_to_fit_twice_not_once()[
        "the_single_beat_rule_is_optimistic"
    ]


def test_the_two_beat_rule_is_close():
    assert clocks.the_heartbeat_has_to_fit_twice_not_once()["the_two_beat_rule_is_close"]


def test_the_two_beat_rule_errs_low():
    assert clocks.the_heartbeat_has_to_fit_twice_not_once()["and_it_errs_low"]


def test_commits_survive_past_the_stability_boundary():
    assert clocks.the_heartbeat_has_to_fit_twice_not_once()["commits_survive_past_the_boundary"]


def test_commits_fail_well_past_it():
    assert clocks.the_heartbeat_has_to_fit_twice_not_once()["and_only_fail_well_past_it"]


def test_the_stability_boundary_is_around_half():
    made = clocks.the_heartbeat_has_to_fit_twice_not_once()
    assert 3 <= made["stable_up_to"] <= 6


def test_the_fastest_beat_recovers_slowest():
    assert clocks.a_faster_heartbeat_makes_failover_slower_not_quicker()[
        "the_fastest_beat_is_the_slowest_to_recover"
    ]


def test_the_lazier_beats_all_recover_quicker():
    assert clocks.a_faster_heartbeat_makes_failover_slower_not_quicker()[
        "and_the_lazier_three_are_all_quicker"
    ]


def test_the_recovery_gap_is_about_two_ticks():
    assert (
        clocks.a_faster_heartbeat_makes_failover_slower_not_quicker()["by_this_many_ticks"] > 1
    )


def test_the_best_recovery_beats_the_shortest_timeout():
    assert clocks.a_faster_heartbeat_makes_failover_slower_not_quicker()[
        "the_best_case_is_inside_the_shortest_timeout"
    ]


def test_every_recovery_fits_a_timeout():
    assert clocks.a_faster_heartbeat_makes_failover_slower_not_quicker()[
        "all_inside_a_timeout_and_an_election"
    ]


def test_a_zero_heartbeat_is_refused():
    assert clocks.a_zero_heartbeat_is_refused()


def test_a_backwards_range_is_refused():
    assert clocks.a_backwards_timeout_range_is_refused()


def test_a_zero_delay_is_refused():
    assert clocks.a_zero_delay_is_refused()


def test_a_trial_of_no_nodes_is_refused():
    assert clocks.a_trial_of_no_nodes_is_refused()


def test_the_setting_table_covers_them_all():
    assert len(clocks.compare_the_settings()) == len(SETTINGS)


def test_everything_that_worked_passed_the_rules():
    assert clocks.the_two_textbook_rules_are_not_enough_on_their_own()[
        "everything_that_worked_passed_the_rules"
    ]


def test_the_rules_alone_are_not_enough():
    assert clocks.the_two_textbook_rules_are_not_enough_on_their_own()[
        "but_not_the_other_way_round"
    ]


def test_the_odd_one_out_is_the_fixed_range():
    assert clocks.the_two_textbook_rules_are_not_enough_on_their_own()["the_odd_one_out"] == [
        "fixed"
    ]


def test_the_fixed_range_proposed_nothing():
    assert clocks.the_two_textbook_rules_are_not_enough_on_their_own()["it_proposed_nothing"]


def test_the_fixed_range_has_no_spread():
    assert clocks.the_two_textbook_rules_are_not_enough_on_their_own()[
        "because_it_has_no_spread"
    ]


def test_the_summary_says_a_fixed_timeout_elects_nobody():
    assert clocks.summarise()["a_fixed_timeout_elects_nobody"]


def test_the_summary_says_one_tick_is_enough():
    assert clocks.summarise()["one_tick_of_spread_is_enough"]


def test_the_summary_says_a_fast_heartbeat_slows_failover():
    assert clocks.summarise()["a_fast_heartbeat_slows_failover"]


def test_the_summary_says_the_rules_miss_the_fixed_range():
    assert clocks.summarise()["the_two_rules_miss_the_fixed_range"]


def test_the_summary_reports_the_shipped_settings():
    assert clocks.summarise()["shipped"]["heartbeat"] == HEARTBEAT_INTERVAL


def test_timings_report_their_spread():
    assert Timings(name="x", heartbeat=1, min_timeout=10, max_timeout=20).spread == 10


def test_timings_report_their_beats_per_timeout():
    made = Timings(name="x", heartbeat=5, min_timeout=10, max_timeout=20)
    assert made.beats_per_timeout == 2.0


def test_timings_report_their_round_trips():
    made = Timings(name="x", heartbeat=1, min_timeout=10, max_timeout=20, delay=1)
    assert made.deliveries_per_timeout == 5.0


def test_a_sane_setting_says_so():
    assert Timings(name="x", heartbeat=3, min_timeout=10, max_timeout=20).sane


def test_an_inverted_setting_is_not_sane():
    assert not Timings(name="x", heartbeat=20, min_timeout=10, max_timeout=20).sane


def test_a_comfortable_setting_says_so():
    assert Timings(name="x", heartbeat=3, min_timeout=10, max_timeout=20).comfortable


def test_a_marginal_setting_is_sane_but_not_comfortable():
    made = Timings(name="x", heartbeat=8, min_timeout=10, max_timeout=20)
    assert made.sane and not made.comfortable


def test_timings_summarise():
    assert (
        Timings(name="x", heartbeat=3, min_timeout=10, max_timeout=20).as_dict()["timings"]
        == "x"
    )


def test_a_zero_heartbeat_raises():
    with pytest.raises(ConfigError):
        Timings(name="x", heartbeat=0, min_timeout=10, max_timeout=20)


def test_a_zero_timeout_raises():
    with pytest.raises(ConfigError):
        Timings(name="x", heartbeat=3, min_timeout=0, max_timeout=20)


def test_a_backwards_range_raises():
    with pytest.raises(ConfigError):
        Timings(name="x", heartbeat=3, min_timeout=20, max_timeout=10)


def test_a_zero_delay_raises():
    with pytest.raises(ConfigError):
        Timings(name="x", heartbeat=3, min_timeout=10, max_timeout=20, delay=0)


def test_a_trial_elects_a_leader():
    made = Trial(SETTINGS["shipped"], size=3, seed=1).settle()
    assert made.cluster.leader() is not None


def test_a_trial_writes_what_it_is_given():
    made = Trial(SETTINGS["shipped"], size=3, seed=1)
    made.settle()
    assert made.propose(4) == 4


def test_a_trial_commits_what_it_writes():
    made = Trial(SETTINGS["shipped"], size=3, seed=1)
    made.settle()
    made.propose(4)
    made.run(30)
    assert made.committed() == 4


def test_a_trial_with_no_leader_commits_nothing():
    made = Trial(SETTINGS["fixed"], size=3, seed=1).run(60)
    assert made.committed() == 0


def test_a_trial_of_no_nodes_raises():
    with pytest.raises(ConfigError):
        Trial(SETTINGS["shipped"], size=0)


def test_a_bounded_propose_gives_up():
    made = Trial(SETTINGS["fixed"], size=3, seed=1)
    assert made.propose(5, budget=40) == 0


def test_a_run_reports_its_uptime():
    made = trial(SETTINGS["shipped"], size=3)
    assert 0.0 < made.uptime <= 1.0


def test_a_run_of_no_ticks_has_no_uptime():
    made = clocks.Run(
        timings=SETTINGS["shipped"],
        leaders=0,
        terms=1,
        committed=0,
        proposed=0,
        messages=0,
        leaderless_ticks=0,
        ticks=0,
    )
    assert made.uptime == 0.0 and made.churn == 0.0


def test_a_good_run_is_truthy():
    assert trial(SETTINGS["shipped"], size=3)


def test_a_bad_run_is_falsy():
    assert not trial(SETTINGS["fixed"], size=3)


def test_a_run_reports_its_churn():
    assert trial(SETTINGS["tight"], size=5).churn > trial(SETTINGS["shipped"], size=5).churn


def test_a_run_summarises():
    assert trial(SETTINGS["shipped"], size=3).as_dict()["timings"] == "shipped"


def test_the_window_is_long_enough_to_settle():
    assert WINDOW > MIN_ELECTION_TIMEOUT * 10


def test_the_recommended_ratio_is_the_usual_one():
    assert RECOMMENDED_RATIO == 10


def test_every_named_setting_is_named_after_itself():
    assert all(name == one.name for name, one in SETTINGS.items())
