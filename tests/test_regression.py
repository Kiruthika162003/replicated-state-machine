from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.eval import regression as guard
from rsm.eval.regression import (
    BETTER,
    GONE,
    NEW,
    SAME,
    TOLERANCE,
    VERDICTS,
    WORSE,
    Baseline,
    Change,
    Comparison,
    check,
    record,
)


def test_a_baseline_is_clean_against_itself():
    assert guard.a_baseline_compares_clean_against_itself()["it_is_clean"]


def test_every_workload_reads_the_same():
    assert guard.a_baseline_compares_clean_against_itself()["and_every_one_is_the_same"]


def test_the_worst_drift_is_nothing():
    assert guard.a_baseline_compares_clean_against_itself()["worst_drift"] == 0.0


def test_the_counts_are_exactly_equal():
    assert guard.the_counts_are_exact_rather_than_close()["they_are_all_exact"]


def test_the_tolerance_could_have_been_zero():
    assert guard.the_counts_are_exact_rather_than_close()["so_the_tolerance_could_be_zero"]


def test_the_tolerance_is_one_percent():
    assert guard.the_counts_are_exact_rather_than_close()["but_it_is_this"] == TOLERANCE


def test_a_regression_is_caught():
    assert guard.a_regression_is_caught()["it_failed"]


def test_a_regression_names_its_workload():
    assert guard.a_regression_is_caught()["and_it_is_named"]


def test_only_one_workload_regressed():
    assert guard.a_regression_is_caught()["one_workload_is_worse"]


def test_the_rest_stayed_the_same():
    assert guard.a_regression_is_caught()["the_rest_are_the_same"]


def test_the_regression_ratio_is_reported():
    assert guard.a_regression_is_caught()["by_this_ratio"] > 1.1


def test_an_improvement_is_not_a_failure():
    assert guard.an_improvement_is_not_a_failure()["and_it_is_still_clean"]


def test_an_improvement_is_reported():
    assert guard.an_improvement_is_not_a_failure()["the_improvement_is_reported"]


def test_an_improvement_produces_no_regressions():
    assert guard.an_improvement_is_not_a_failure()["which_is_none"]


def test_a_vanished_workload_is_noticed():
    assert guard.a_vanished_workload_is_a_failure()["it_noticed"]


def test_a_vanished_workload_fails():
    assert guard.a_vanished_workload_is_a_failure()["and_it_failed"]


def test_a_vanished_workload_is_named():
    assert guard.a_vanished_workload_is_a_failure()["the_missing_one_is_named"]


def test_a_new_workload_is_noticed():
    assert guard.a_new_workload_is_not_a_failure()["it_noticed"]


def test_a_new_workload_passes():
    assert guard.a_new_workload_is_not_a_failure()["and_it_passed"]


def test_a_new_workload_has_no_before():
    assert guard.a_new_workload_is_not_a_failure()["and_its_before_is_zero"]


def test_a_small_movement_is_the_same():
    assert guard.a_movement_inside_the_tolerance_is_the_same()["inside_is_the_same"]


def test_a_large_movement_is_worse():
    assert guard.a_movement_inside_the_tolerance_is_the_same()["outside_is_worse"]


def test_a_fall_is_better():
    assert guard.a_movement_inside_the_tolerance_is_the_same()["and_a_fall_is_better"]


def test_a_mismatched_baseline_is_refused():
    assert guard.a_mismatched_baseline_is_refused()


def test_a_negative_tolerance_is_refused():
    assert guard.a_negative_tolerance_is_refused()


def test_an_unknown_verdict_is_refused():
    assert guard.an_unknown_verdict_is_refused()


def test_an_empty_baseline_is_all_new():
    assert guard.an_empty_baseline_compares_everything_as_new()["they_are_all_new"]


def test_an_empty_baseline_passes():
    assert guard.an_empty_baseline_compares_everything_as_new()["and_it_passed"]


def test_the_verdict_table_covers_four_movements():
    assert len(guard.compare_the_verdicts()) == 4


def test_movements_reach_three_verdicts():
    assert guard.every_verdict_is_reachable()["movements_reach_three"]


def test_the_other_two_verdicts_are_structural():
    assert guard.every_verdict_is_reachable()["and_the_other_two_are_structural"]


def test_every_verdict_is_reachable():
    assert guard.every_verdict_is_reachable()["every_verdict_is_reachable"]


def test_the_summary_says_a_regression_is_caught():
    assert guard.summarise()["a_regression_is_caught"]


def test_the_summary_says_the_counts_are_exact():
    assert guard.summarise()["the_counts_are_exact"]


def test_a_baseline_lists_its_workloads():
    made = Baseline(messages={"a": 1, "b": 2}, committed={"a": 1, "b": 2})
    assert set(made.workloads) == {"a", "b"}


def test_a_baseline_summarises():
    made = Baseline(messages={"a": 5}, committed={"a": 1})
    assert made.as_dict()["total_messages"] == 5


def test_an_empty_baseline_is_valid():
    assert Baseline().workloads == ()


def test_a_mismatched_baseline_raises():
    with pytest.raises(ConfigError):
        Baseline(messages={"a": 1}, committed={})


def test_a_change_reports_its_ratio():
    made = Change(workload="a", before=100, after=150, verdict=WORSE)
    assert made.ratio == 1.5


def test_a_change_reports_its_drift():
    made = Change(workload="a", before=100, after=90, verdict=BETTER)
    assert round(made.drift, 3) == 0.1


def test_a_change_from_nothing_to_nothing_has_a_ratio_of_one():
    made = Change(workload="a", before=0, after=0, verdict=SAME)
    assert made.ratio == 1.0


def test_a_change_from_nothing_to_something_is_infinite():
    made = Change(workload="a", before=0, after=5, verdict=NEW)
    assert made.ratio == float("inf")


def test_a_change_summarises():
    made = Change(workload="a", before=1, after=1, verdict=SAME)
    assert made.as_dict()["workload"] == "a"


def test_a_change_prints_both_sides():
    made = Change(workload="a", before=1, after=2, verdict=WORSE)
    assert "1 -> 2" in str(made)


def test_an_unknown_verdict_raises():
    with pytest.raises(ConfigError):
        Change(workload="a", before=1, after=1, verdict="fine")


def test_an_empty_comparison_is_clean():
    assert bool(Comparison())


def test_a_comparison_with_a_regression_is_not():
    made = Comparison(changes=[Change(workload="a", before=1, after=2, verdict=WORSE)])
    assert not bool(made)


def test_a_comparison_with_a_gone_workload_is_not():
    made = Comparison(changes=[Change(workload="a", before=1, after=0, verdict=GONE)])
    assert not bool(made)


def test_a_comparison_with_an_improvement_is_clean():
    made = Comparison(changes=[Change(workload="a", before=2, after=1, verdict=BETTER)])
    assert bool(made)


def test_a_comparison_with_a_new_workload_is_clean():
    made = Comparison(changes=[Change(workload="a", before=0, after=1, verdict=NEW)])
    assert bool(made)


def test_a_comparison_filters_by_verdict():
    made = Comparison(
        changes=[
            Change(workload="a", before=1, after=2, verdict=WORSE),
            Change(workload="b", before=1, after=1, verdict=SAME),
        ]
    )
    assert len(made.of(WORSE)) == 1


def test_a_comparison_finds_its_worst():
    made = Comparison(
        changes=[
            Change(workload="a", before=100, after=110, verdict=WORSE),
            Change(workload="b", before=100, after=200, verdict=WORSE),
        ]
    )
    assert made.worst.workload == "b"


def test_an_empty_comparison_has_no_worst():
    assert Comparison().worst is None


def test_a_comparison_summarises():
    assert Comparison().as_dict()["workloads"] == 0


def test_recording_covers_every_workload():
    assert len(record().workloads) == 8


def test_checking_against_a_fresh_record_is_clean():
    assert bool(check(record()))


def test_there_are_five_verdicts():
    assert len(VERDICTS) == 5


def test_the_tolerance_is_tight():
    assert TOLERANCE <= 0.05
