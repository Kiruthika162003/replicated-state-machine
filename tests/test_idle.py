from __future__ import annotations

import pytest

from rsm import idle as floor_module
from rsm.errors import ConfigError
from rsm.idle import RATES, WINDOW, Floor, measure
from rsm.node import HEARTBEAT_INTERVAL


def test_the_model_matches_the_cluster():
    assert floor_module.the_model_of_the_floor_matches_the_cluster_exactly()[
        "they_agree_everywhere"
    ]


def test_an_idle_run_commits_nothing():
    assert floor_module.the_model_of_the_floor_matches_the_cluster_exactly()[
        "and_nothing_was_committed"
    ]


def test_the_floor_at_five_is_positive():
    assert (
        floor_module.the_model_of_the_floor_matches_the_cluster_exactly()["the_floor_at_five"]
        > 0
    )


def test_the_crossover_is_size_independent():
    assert floor_module.the_crossover_is_the_heartbeat_and_not_the_cluster_size()[
        "they_are_the_same"
    ]


def test_the_heartbeat_moves_the_crossover():
    assert floor_module.the_crossover_is_the_heartbeat_and_not_the_cluster_size()[
        "and_the_heartbeat_moves_it"
    ]


def test_the_crossover_is_a_hundred_over_the_heartbeat():
    assert floor_module.the_crossover_is_the_heartbeat_and_not_the_cluster_size()[
        "it_is_a_hundred_over_the_heartbeat"
    ]


def test_a_lazier_heartbeat_lowers_the_floor():
    assert floor_module.a_lazier_heartbeat_lowers_the_floor_in_proportion()[
        "it_falls_with_the_interval"
    ]


def test_it_falls_exactly_in_proportion():
    assert floor_module.a_lazier_heartbeat_lowers_the_floor_in_proportion()[
        "exactly_in_proportion"
    ]


def test_the_safe_limit_saves_something():
    assert (
        floor_module.a_lazier_heartbeat_lowers_the_floor_in_proportion()[
            "and_the_saving_against_shipped"
        ]
        > 0
    )


def test_at_no_writes_the_floor_is_everything():
    assert floor_module.the_floor_is_most_of_the_bill_at_realistic_write_rates()[
        "at_no_writes_it_is_everything"
    ]


def test_at_one_write_it_is_most():
    assert floor_module.the_floor_is_most_of_the_bill_at_realistic_write_rates()[
        "at_one_write_it_is_most"
    ]


def test_at_a_hundred_it_is_a_quarter():
    assert floor_module.the_floor_is_most_of_the_bill_at_realistic_write_rates()[
        "at_a_hundred_it_is_a_quarter"
    ]


def test_the_crossover_sits_between_them():
    assert floor_module.the_floor_is_most_of_the_bill_at_realistic_write_rates()[
        "and_it_sits_between_the_two"
    ]


def test_one_node_costs_nothing():
    assert floor_module.a_cluster_of_one_has_no_floor_at_all()["it_costs_nothing"]


def test_two_nodes_cost_something():
    assert floor_module.a_cluster_of_one_has_no_floor_at_all()["and_two_costs_something"]


def test_the_floor_is_the_price_of_a_copy():
    assert floor_module.a_cluster_of_one_has_no_floor_at_all()[
        "so_the_floor_is_the_price_of_a_copy"
    ]


def test_a_cluster_of_none_is_refused():
    assert floor_module.a_cluster_of_no_nodes_is_refused()


def test_a_zero_heartbeat_is_refused():
    assert floor_module.a_zero_heartbeat_is_refused()


def test_a_zero_write_cost_is_refused():
    assert floor_module.a_zero_write_cost_is_refused()


def test_a_window_of_no_ticks_is_refused():
    assert floor_module.a_window_of_no_ticks_is_refused()


def test_the_shape_table_covers_nine():
    assert len(floor_module.compare_the_shapes()) == 9


def test_no_shape_has_a_zero_floor():
    assert floor_module.the_floor_is_the_only_cost_that_never_goes_away()[
        "none_of_them_is_zero"
    ]


def test_the_floor_range_is_wide():
    assert floor_module.the_floor_is_the_only_cost_that_never_goes_away()["the_range"] > 5


def test_the_crossover_moves_only_with_the_heartbeat():
    assert floor_module.the_floor_is_the_only_cost_that_never_goes_away()[
        "and_the_crossover_only_moves_with_the_heartbeat"
    ]


def test_the_summary_says_the_model_matches():
    assert floor_module.summarise()["the_model_matches_the_cluster"]


def test_the_summary_says_the_floor_dominates():
    assert floor_module.summarise()["the_floor_dominates_at_low_rates"]


def test_a_floor_reports_its_peers():
    assert Floor(size=5).peers == 4


def test_a_single_node_has_no_peers():
    assert Floor(size=1).peers == 0


def test_a_floor_is_two_messages_per_peer_per_interval():
    assert Floor(size=5, heartbeat=2).per_tick == 4.0


def test_a_single_node_floor_is_zero():
    assert Floor(size=1).per_tick == 0.0


def test_a_floor_scales_with_the_window():
    made = Floor(size=5)
    assert made.per_window == round(made.per_tick * WINDOW, 1)


def test_a_floor_reports_its_bytes():
    assert Floor(size=5).bytes_per_tick > Floor(size=3).bytes_per_tick


def test_a_floor_reports_its_crossover():
    assert Floor(size=5).crossover() > 0


def test_a_cheaper_write_raises_the_crossover():
    made = Floor(size=5)
    assert made.crossover(write_cost=1) > made.crossover(write_cost=8)


def test_a_zero_write_cost_raises():
    with pytest.raises(ConfigError):
        Floor(size=5).crossover(write_cost=0)


def test_a_floor_summarises():
    assert Floor(size=7).as_dict()["size"] == 7


def test_a_zero_size_raises():
    with pytest.raises(ConfigError):
        Floor(size=0)


def test_a_zero_heartbeat_raises():
    with pytest.raises(ConfigError):
        Floor(size=3, heartbeat=0)


def test_measuring_an_idle_cluster_sends_messages():
    assert measure(size=3, window=60)["messages"] > 0


def test_measuring_an_idle_cluster_commits_nothing():
    assert measure(size=3, window=60)["committed"] == 0


def test_measuring_reports_the_kinds_it_saw():
    assert "append" in measure(size=3, window=60)["kinds"]


def test_measuring_a_larger_cluster_costs_more():
    assert measure(size=7, window=60)["messages"] > measure(size=3, window=60)["messages"]


def test_a_zero_window_raises():
    with pytest.raises(ConfigError):
        measure(window=0)


def test_the_rates_include_an_idle_one():
    assert 0 in RATES


def test_the_shipped_heartbeat_is_the_default():
    assert Floor(size=3).heartbeat == HEARTBEAT_INTERVAL
