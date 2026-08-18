from __future__ import annotations

import pytest

from rsm import backpressure as load
from rsm.backpressure import BOUND, WINDOW, Load, Result, offer
from rsm.errors import ConfigError
from rsm.net import Conditions


def test_the_ceiling_is_flat():
    assert load.the_cluster_has_a_flat_ceiling_and_accepts_past_it_anyway()[
        "the_ceiling_is_flat"
    ]


def test_the_depth_is_not_flat():
    assert load.the_cluster_has_a_flat_ceiling_and_accepts_past_it_anyway()[
        "the_depth_is_not_flat"
    ]


def test_it_accepts_everything():
    assert load.the_cluster_has_a_flat_ceiling_and_accepts_past_it_anyway()[
        "it_accepted_everything"
    ]


def test_the_tail_runs_away_above_the_ceiling():
    assert load.the_cluster_has_a_flat_ceiling_and_accepts_past_it_anyway()[
        "and_the_tail_runs_away_above_the_ceiling"
    ]


def test_the_wait_grows_above_the_ceiling():
    assert load.the_queue_is_what_turns_a_rate_problem_into_a_latency_problem()[
        "the_wait_grows"
    ]


def test_the_wait_grows_a_lot():
    made = load.the_queue_is_what_turns_a_rate_problem_into_a_latency_problem()
    assert made["by_this_factor"] > 5


def test_the_throughput_does_not_grow():
    assert load.the_queue_is_what_turns_a_rate_problem_into_a_latency_problem()[
        "and_the_throughput_does_not"
    ]


def test_nothing_is_refused_without_a_bound():
    assert load.the_queue_is_what_turns_a_rate_problem_into_a_latency_problem()[
        "nothing_was_refused"
    ]


def test_a_bound_gives_the_bound_over_the_heartbeat():
    assert load.a_bound_below_the_ceiling_costs_exactly_the_throughput_it_removes()[
        "it_is_the_bound_over_the_heartbeat"
    ]


def test_the_prediction_stops_at_the_ceiling():
    assert load.a_bound_below_the_ceiling_costs_exactly_the_throughput_it_removes()[
        "until_it_hits_the_ceiling"
    ]


def test_a_tight_bound_refuses_almost_everything():
    assert load.a_bound_below_the_ceiling_costs_exactly_the_throughput_it_removes()[
        "a_tight_bound_refuses_almost_everything"
    ]


def test_the_right_bound_keeps_the_throughput():
    assert load.the_right_bound_is_a_heartbeat_of_work_and_costs_nothing()[
        "the_right_bound_keeps_the_throughput"
    ]


def test_the_right_bound_cuts_the_wait():
    assert load.the_right_bound_is_a_heartbeat_of_work_and_costs_nothing()["and_cuts_the_wait"]


def test_the_right_bound_cuts_it_a_lot():
    made = load.the_right_bound_is_a_heartbeat_of_work_and_costs_nothing()
    assert made["by_this_factor"] > 5


def test_a_tight_bound_loses_throughput():
    assert load.the_right_bound_is_a_heartbeat_of_work_and_costs_nothing()[
        "the_tight_bound_loses_throughput"
    ]


def test_a_tight_bound_barely_helps_the_wait():
    assert load.the_right_bound_is_a_heartbeat_of_work_and_costs_nothing()[
        "and_barely_improves_the_wait"
    ]


def test_the_bound_range_is_not_a_smooth_trade():
    assert load.the_right_bound_is_a_heartbeat_of_work_and_costs_nothing()[
        "so_the_range_is_not_a_smooth_trade"
    ]


def test_only_the_bounded_run_says_anything():
    assert load.a_refusal_is_information_and_a_slow_success_is_not()[
        "only_one_of_them_says_anything"
    ]


def test_both_runs_commit_about_the_same():
    assert load.a_refusal_is_information_and_a_slow_success_is_not()[
        "they_commit_about_the_same"
    ]


def test_only_the_unbounded_run_leaves_a_backlog():
    assert load.a_refusal_is_information_and_a_slow_success_is_not()[
        "and_one_of_them_leaves_a_backlog"
    ]


def test_a_slow_link_lowers_the_ceiling():
    assert load.a_slower_link_lowers_the_ceiling_and_the_bound_follows_it()["the_ceiling_fell"]


def test_the_bound_still_helps_on_a_slow_link():
    assert load.a_slower_link_lowers_the_ceiling_and_the_bound_follows_it()[
        "the_bound_still_helps"
    ]


def test_the_bound_is_no_longer_free_on_a_slow_link():
    assert load.a_slower_link_lowers_the_ceiling_and_the_bound_follows_it()[
        "but_it_is_no_longer_free"
    ]


def test_the_bound_is_really_a_rate():
    assert load.a_slower_link_lowers_the_ceiling_and_the_bound_follows_it()[
        "so_the_bound_is_really_a_rate"
    ]


def test_a_zero_rate_is_refused():
    assert load.a_zero_rate_is_refused()


def test_a_negative_bound_is_refused():
    assert load.a_negative_bound_is_refused()


def test_a_zero_window_is_refused():
    assert load.a_zero_window_is_refused()


def test_the_bound_table_covers_four():
    assert len(load.compare_the_bounds()) == 4


def test_the_summary_reports_the_ceiling():
    assert load.summarise()["ceiling"] > 10


def test_the_summary_says_a_refusal_is_information():
    assert load.summarise()["a_refusal_is_information"]


def test_the_summary_says_the_right_bound_is_free():
    assert load.summarise()["the_right_bound_is_free"]


def test_a_load_reports_whether_it_is_bounded():
    assert Load(name="x", per_tick=1, bound=10).bounded


def test_an_unbounded_load_says_so():
    assert not Load(name="x", per_tick=1).bounded


def test_a_load_summarises():
    assert Load(name="named", per_tick=1).as_dict()["load"] == "named"


def test_a_zero_rate_raises():
    with pytest.raises(ConfigError):
        Load(name="x", per_tick=0)


def test_a_negative_rate_raises():
    with pytest.raises(ConfigError):
        Load(name="x", per_tick=-1)


def test_a_negative_bound_raises():
    with pytest.raises(ConfigError):
        Load(name="x", per_tick=1, bound=-1)


def test_a_zero_size_raises():
    with pytest.raises(ConfigError):
        Load(name="x", per_tick=1, size=0)


def test_a_result_reports_its_worst_depth():
    assert Result(load=Load(name="x", per_tick=1), depths=[1, 7, 3]).worst_depth == 7


def test_a_result_reports_its_final_depth():
    assert Result(load=Load(name="x", per_tick=1), depths=[1, 7, 3]).final_depth == 3


def test_an_empty_result_has_no_depth():
    assert Result(load=Load(name="x", per_tick=1)).worst_depth == 0


def test_a_result_reports_its_throughput():
    made = Result(load=Load(name="x", per_tick=1), committed=50, ticks=100)
    assert made.throughput == 0.5


def test_a_result_with_no_ticks_has_no_throughput():
    assert Result(load=Load(name="x", per_tick=1)).throughput == 0.0


def test_a_result_reports_its_acceptance():
    made = Result(load=Load(name="x", per_tick=1), offered=10, accepted=4)
    assert made.acceptance == 0.4


def test_a_result_with_nothing_offered_has_no_acceptance():
    assert Result(load=Load(name="x", per_tick=1)).acceptance == 0.0


def test_a_result_reports_its_worst_wait():
    assert Result(load=Load(name="x", per_tick=1), waits=[2, 9]).worst_wait == 9


def test_a_short_result_is_not_growing():
    assert not Result(load=Load(name="x", per_tick=1), depths=[1, 2, 3]).growing


def test_a_rising_result_is_growing():
    made = Result(load=Load(name="x", per_tick=1), depths=list(range(40)))
    assert made.growing


def test_a_flat_result_is_not():
    made = Result(load=Load(name="x", per_tick=1), depths=[5] * 40)
    assert not made.growing


def test_a_stable_result_is_truthy():
    assert Result(load=Load(name="x", per_tick=1), depths=[5] * 40)


def test_a_growing_result_is_falsy():
    assert not Result(load=Load(name="x", per_tick=1), depths=list(range(40)))


def test_a_result_summarises():
    assert Result(load=Load(name="named", per_tick=1)).as_dict()["load"] == "named"


def test_offering_a_small_load_commits_it():
    made = offer(Load(name="x", per_tick=0.5, size=3), window=80)
    assert made.committed > 0


def test_offering_keeps_the_depth_small_below_the_ceiling():
    assert offer(Load(name="x", per_tick=1, size=3), window=80).worst_depth < 20


def test_a_bounded_offer_never_exceeds_its_bound():
    made = offer(Load(name="x", per_tick=40, size=3, bound=16), window=80)
    assert made.worst_depth <= 16


def test_a_bounded_offer_refuses():
    assert offer(Load(name="x", per_tick=40, size=3, bound=16), window=80).refused > 0


def test_a_lossy_link_still_commits():
    made = offer(Load(name="x", per_tick=1, size=3, conditions=Conditions(loss=0.2)), window=80)
    assert made.committed > 0


def test_a_zero_window_raises():
    with pytest.raises(ConfigError):
        offer(Load(name="x", per_tick=1), window=0)


def test_the_window_is_long_enough_to_saturate():
    assert WINDOW >= 200


def test_the_default_bound_is_positive():
    assert BOUND > 0
