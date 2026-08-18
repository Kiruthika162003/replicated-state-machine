from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.eval import tuning as tune
from rsm.eval.tuning import (
    BASE_TIMEOUT,
    HEARTBEATS,
    SIZES,
    SPREADS,
    WEIGHTINGS,
    Grid,
    Setting,
    Weights,
    sweep,
)


def test_the_objective_decides_the_winner():
    assert tune.the_weighting_picks_the_setting_and_not_the_measurement()[
        "they_are_not_all_the_same"
    ]


def test_two_objectives_disagree():
    assert tune.the_weighting_picks_the_setting_and_not_the_measurement()[
        "and_those_two_disagree"
    ]


def test_there_are_several_distinct_winners():
    made = tune.the_weighting_picks_the_setting_and_not_the_measurement()
    assert made["distinct_winners"] > 1


def test_every_winner_is_the_smallest_cluster():
    assert tune.every_weighting_picks_the_smallest_cluster()["they_are_all_the_smallest"]


def test_the_bigger_clusters_cost_more():
    assert tune.every_weighting_picks_the_smallest_cluster()["and_cost_more"]


def test_no_run_in_the_sweep_failed():
    assert tune.every_weighting_picks_the_smallest_cluster()["no_run_had_a_failure"]


def test_the_sweep_cannot_see_why_seven_exists():
    assert tune.every_weighting_picks_the_smallest_cluster()[
        "so_the_sweep_cannot_see_why_seven_exists"
    ]


def test_a_flat_spread_commits_nothing():
    assert tune.a_spread_of_nothing_loses_every_row_it_appears_in()["none_of_them_committed"]


def test_every_other_row_commits_something():
    assert tune.a_spread_of_nothing_loses_every_row_it_appears_in()["and_the_rest_did"]


def test_no_size_rescues_a_flat_spread():
    assert tune.a_spread_of_nothing_loses_every_row_it_appears_in()["no_size_rescued_it"]


def test_no_heartbeat_rescues_it_either():
    assert tune.a_spread_of_nothing_loses_every_row_it_appears_in()["and_no_heartbeat_did"]


def test_an_empty_weighting_is_refused():
    assert tune.a_weighting_that_weighs_nothing_is_refused()


def test_an_unnamed_weighting_is_refused():
    assert tune.an_unnamed_weighting_is_refused()


def test_a_setting_with_no_nodes_is_refused():
    assert tune.a_setting_with_no_nodes_is_refused()


def test_a_negative_spread_is_refused():
    assert tune.a_negative_spread_is_refused()


def test_an_empty_grid_has_no_best_row():
    assert tune.an_empty_grid_has_no_best_row()


def test_two_objectives_with_one_winner_agree_widely():
    assert tune.two_objectives_that_share_a_winner_agree_most_of_the_way_down()[
        "and_most_of_them_do"
    ]


def test_they_agree_on_second_place():
    assert tune.two_objectives_that_share_a_winner_agree_most_of_the_way_down()[
        "second_place_agrees"
    ]


def test_they_agree_on_the_worst_row():
    assert tune.two_objectives_that_share_a_winner_agree_most_of_the_way_down()[
        "and_both_agree_on_the_worst"
    ]


def test_a_disagreeing_objective_ranks_differently():
    assert tune.two_objectives_that_share_a_winner_agree_most_of_the_way_down()[
        "and_that_one_agrees_on_far_fewer"
    ]


def test_the_weighting_table_covers_them_all():
    assert len(tune.compare_the_weightings()) == len(WEIGHTINGS)


def test_no_setting_is_best_at_everything():
    assert tune.no_setting_is_best_at_everything()["they_are_not_one_row"]


def test_a_score_is_required():
    assert tune.no_setting_is_best_at_everything()["so_a_score_is_required"]


def test_the_summary_says_the_objective_decides():
    assert tune.summarise()["the_objective_decides"]


def test_the_summary_says_every_winner_is_smallest():
    assert tune.summarise()["every_winner_is_the_smallest_cluster"]


def test_a_weighting_scores_a_row():
    made = Weights(name="x", committed=2.0)
    row = {"committed": 3, "messages": 0, "terms": 0, "uptime": 0}
    assert made.score(row) == 6.0


def test_a_weighting_charges_for_messages():
    made = Weights(name="x", committed=1.0, messages=0.5)
    row = {"committed": 4, "messages": 4, "terms": 0, "uptime": 0}
    assert made.score(row) == 2.0


def test_a_weighting_charges_for_elections():
    made = Weights(name="x", committed=1.0, elections=2.0)
    row = {"committed": 4, "messages": 0, "terms": 1, "uptime": 0}
    assert made.score(row) == 2.0


def test_a_weighting_rewards_uptime():
    made = Weights(name="x", committed=0.0, uptime=10.0)
    row = {"committed": 0, "messages": 0, "terms": 0, "uptime": 0.5}
    assert made.score(row) == 5.0


def test_a_weighting_summarises():
    assert Weights(name="named").as_dict()["weighting"] == "named"


def test_an_empty_weighting_raises():
    with pytest.raises(ConfigError):
        Weights(name="x", committed=0.0)


def test_an_unnamed_weighting_raises():
    with pytest.raises(ConfigError):
        Weights(name="")


def test_a_setting_builds_its_timings():
    made = Setting(size=3, heartbeat=4, spread=6)
    assert made.timings.heartbeat == 4


def test_a_setting_spreads_its_timeout():
    made = Setting(size=3, heartbeat=4, spread=6)
    assert made.timings.max_timeout - made.timings.min_timeout == 6


def test_a_setting_starts_at_the_base_timeout():
    assert Setting(size=3, heartbeat=4, spread=0).timings.min_timeout == BASE_TIMEOUT


def test_a_setting_summarises():
    assert Setting(size=5, heartbeat=3, spread=2).as_dict()["size"] == 5


def test_a_setting_prints_itself():
    assert "5 nodes" in str(Setting(size=5, heartbeat=3, spread=2))


def test_a_setting_with_no_nodes_raises():
    with pytest.raises(ConfigError):
        Setting(size=0, heartbeat=3, spread=2)


def test_a_setting_with_no_heartbeat_raises():
    with pytest.raises(ConfigError):
        Setting(size=3, heartbeat=0, spread=2)


def test_a_negative_spread_raises():
    with pytest.raises(ConfigError):
        Setting(size=3, heartbeat=3, spread=-1)


def test_a_grid_ranks_its_rows():
    made = sweep()
    ranked = made.ranked(WEIGHTINGS["correctness only"])
    assert len(ranked) == len(made.rows)


def test_the_best_row_is_first_in_the_ranking():
    made = sweep()
    weights = WEIGHTINGS["correctness only"]
    assert made.ranked(weights)[0] == made.best(weights)


def test_an_empty_grid_raises():
    with pytest.raises(ConfigError):
        Grid().best(WEIGHTINGS["correctness only"])


def test_a_grid_summarises():
    assert Grid().as_dict()["rows"] == 0


def test_the_sweep_covers_the_product():
    assert len(sweep().rows) == len(SIZES) * len(HEARTBEATS) * len(SPREADS)


def test_the_sweep_needs_a_seed():
    with pytest.raises(ConfigError):
        sweep(seeds=0)


def test_every_row_names_its_setting():
    assert all(one["setting"] for one in sweep().rows)


def test_the_spreads_include_a_flat_one():
    assert 0 in SPREADS


def test_the_sizes_are_odd():
    assert all(one % 2 == 1 for one in SIZES)
