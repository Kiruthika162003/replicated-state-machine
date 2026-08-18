from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.eval import latency as timing
from rsm.eval.latency import PATIENCE, SPACING, WRITES, Sample, measure
from rsm.net import Conditions


def test_a_healthy_run_has_no_variance():
    assert timing.a_stable_leader_commits_with_no_variance_at_all()["they_are_all_the_same"]


def test_a_healthy_commit_is_a_round_trip():
    assert timing.a_stable_leader_commits_with_no_variance_at_all()["and_it_is_a_round_trip"]


def test_a_healthy_spread_is_one():
    assert timing.a_stable_leader_commits_with_no_variance_at_all()["which_is_one"]


def test_a_healthy_run_loses_nothing():
    assert timing.a_stable_leader_commits_with_no_variance_at_all()["nothing_was_lost"]


def test_a_failure_leaves_the_median_alone():
    assert timing.one_leader_failure_multiplies_the_worst_case_and_leaves_the_median_alone()[
        "the_median_did_not_move"
    ]


def test_a_failure_leaves_the_ninetieth_alone():
    assert timing.one_leader_failure_multiplies_the_worst_case_and_leaves_the_median_alone()[
        "nor_did_the_ninetieth"
    ]


def test_a_failure_moves_the_maximum():
    assert timing.one_leader_failure_multiplies_the_worst_case_and_leaves_the_median_alone()[
        "but_the_worst_did"
    ]


def test_the_failure_factor_is_large():
    made = timing.one_leader_failure_multiplies_the_worst_case_and_leaves_the_median_alone()
    assert made["by_this_factor"] > 4


def test_the_tail_is_inside_the_timeout_range():
    assert timing.the_tail_is_an_election_timeout_and_the_median_is_a_round_trip()[
        "the_worst_is_inside_the_timeout_range"
    ]


def test_the_median_is_a_round_trip():
    assert timing.the_tail_is_an_election_timeout_and_the_median_is_a_round_trip()[
        "and_the_median_is_a_round_trip"
    ]


def test_the_ratio_follows_the_constants():
    assert timing.the_tail_is_an_election_timeout_and_the_median_is_a_round_trip()[
        "which_is_about_the_ratio_of_the_constants"
    ]


def test_jitter_moves_the_median():
    assert timing.jitter_moves_the_whole_distribution_and_adds_no_tail()["the_median_moved"]


def test_jitter_barely_moves_the_spread():
    assert timing.jitter_moves_the_whole_distribution_and_adds_no_tail()[
        "and_the_spread_barely_did"
    ]


def test_the_jitter_factor_is_real():
    made = timing.jitter_moves_the_whole_distribution_and_adds_no_tail()
    assert made["by_this_factor"] > 1.5


def test_loss_leaves_the_median_unchanged():
    assert timing.loss_adds_a_small_tail_and_a_failure_adds_a_large_one()[
        "the_median_is_unchanged"
    ]


def test_loss_adds_a_tail():
    assert timing.loss_adds_a_small_tail_and_a_failure_adds_a_large_one()["and_there_is_a_tail"]


def test_the_failure_tail_beats_the_loss_tail():
    assert timing.loss_adds_a_small_tail_and_a_failure_adds_a_large_one()[
        "the_failure_tail_is_larger"
    ]


def test_the_two_tails_come_from_the_two_constants():
    assert timing.loss_adds_a_small_tail_and_a_failure_adds_a_large_one()[
        "and_the_two_tails_are_the_two_constants"
    ]


def test_every_size_commits_in_the_same_time():
    assert timing.the_cluster_size_does_not_change_the_latency()["they_are_all_the_same"]


def test_a_single_node_is_quicker():
    assert timing.the_cluster_size_does_not_change_the_latency()["one_node_is_quicker"]


def test_every_size_committed_everything():
    assert timing.the_cluster_size_does_not_change_the_latency()[
        "every_size_committed_everything"
    ]


def test_a_bad_share_is_refused():
    assert timing.a_share_outside_the_range_is_refused()


def test_a_run_of_no_writes_is_refused():
    assert timing.a_run_of_no_writes_is_refused()


def test_a_spacing_of_none_is_refused():
    assert timing.a_spacing_of_none_is_refused()


def test_an_empty_sample_reports_zeroes():
    assert timing.an_empty_sample_reports_zeroes_rather_than_raising()["they_are_all_zero"]


def test_an_empty_sample_is_falsy():
    assert timing.an_empty_sample_reports_zeroes_rather_than_raising()["and_it_is_falsy"]


def test_the_condition_table_covers_four():
    assert len(timing.compare_the_conditions()) == 4


def test_the_two_rankings_disagree():
    assert timing.no_single_statistic_ranks_the_four_conditions_the_same_way()["they_disagree"]


def test_the_failure_has_the_worst_maximum():
    assert timing.no_single_statistic_ranks_the_four_conditions_the_same_way()[
        "the_failure_has_the_worst_maximum"
    ]


def test_the_jitter_has_the_worst_median():
    assert timing.no_single_statistic_ranks_the_four_conditions_the_same_way()[
        "and_the_jitter_the_worst_median"
    ]


def test_the_ranking_is_a_choice():
    assert timing.no_single_statistic_ranks_the_four_conditions_the_same_way()[
        "so_the_ranking_is_a_choice"
    ]


def test_the_summary_says_the_healthy_run_is_flat():
    assert timing.summarise()["a_healthy_run_has_no_variance"]


def test_the_summary_says_size_changes_nothing():
    assert timing.summarise()["size_changes_nothing"]


def test_the_summary_reports_the_round_trip():
    assert timing.summarise()["the_round_trip"] == 2


def test_a_sample_reports_its_count():
    assert Sample(name="x", latencies=[1, 2, 3]).count == 3


def test_a_sample_reports_its_median():
    assert Sample(name="x", latencies=[1, 3, 5]).median == 3.0


def test_a_sample_reports_its_mean():
    assert Sample(name="x", latencies=[1, 2, 3]).mean == 2.0


def test_a_sample_reports_its_worst():
    assert Sample(name="x", latencies=[1, 9, 3]).worst == 9


def test_a_sample_reports_its_best():
    assert Sample(name="x", latencies=[4, 9, 3]).best == 3


def test_a_sample_reports_a_quantile():
    assert Sample(name="x", latencies=list(range(1, 11))).quantile(0.9) == 10


def test_a_quantile_of_one_is_the_worst():
    made = Sample(name="x", latencies=[1, 5, 9])
    assert made.quantile(1.0) == made.worst


def test_a_quantile_is_a_real_sample():
    made = Sample(name="x", latencies=[2, 4, 6, 8])
    assert made.quantile(0.5) in made.latencies


def test_a_bad_quantile_raises():
    with pytest.raises(ConfigError):
        Sample(name="x", latencies=[1]).quantile(0.0)


def test_a_sample_reports_its_spread():
    assert Sample(name="x", latencies=[2, 2, 8]).spread == 4.0


def test_a_flat_sample_has_a_spread_of_one():
    assert Sample(name="x", latencies=[3, 3, 3]).spread == 1.0


def test_a_sample_with_losses_is_falsy():
    assert not Sample(name="x", latencies=[1, 2], lost=1)


def test_a_clean_sample_is_truthy():
    assert Sample(name="x", latencies=[1, 2])


def test_a_sample_summarises():
    assert Sample(name="named", latencies=[1]).as_dict()["run"] == "named"


def test_measuring_returns_a_latency_per_write():
    assert measure("x", writes=5, size=3).count == 5


def test_measuring_a_lossy_link_still_commits():
    assert measure("x", writes=5, size=3, conditions=Conditions(loss=0.2)).count == 5


def test_measuring_with_no_writes_raises():
    with pytest.raises(ConfigError):
        measure("x", writes=0)


def test_measuring_with_no_spacing_raises():
    with pytest.raises(ConfigError):
        measure("x", spacing=0)


def test_the_write_count_is_worth_measuring():
    assert WRITES >= 20


def test_the_spacing_is_more_than_a_round_trip():
    assert SPACING > 2


def test_the_patience_outlasts_an_election():
    assert PATIENCE > 100
