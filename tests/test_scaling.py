from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.eval import scaling as growth
from rsm.eval.scaling import LENGTHS, NEAR, SIZES, Fit, fit


def test_the_cost_per_peer_is_constant():
    assert growth.fitting_the_size_gives_a_superlinear_exponent_that_is_an_artefact()[
        "the_cost_per_peer_is_constant"
    ]


def test_fitting_the_size_reads_as_superlinear():
    assert growth.fitting_the_size_gives_a_superlinear_exponent_that_is_an_artefact()[
        "it_reads_as_superlinear"
    ]


def test_fitting_the_peers_gives_exactly_one():
    assert growth.fitting_the_size_gives_a_superlinear_exponent_that_is_an_artefact()[
        "and_that_one_is_exactly_one"
    ]


def test_the_superlinear_exponent_was_an_artefact():
    assert growth.fitting_the_size_gives_a_superlinear_exponent_that_is_an_artefact()[
        "so_the_exponent_was_an_artefact"
    ]


def test_the_size_exponent_is_reported():
    made = growth.fitting_the_size_gives_a_superlinear_exponent_that_is_an_artefact()
    assert made["fitted_against_size"] > 1.2


def test_the_quorum_differences_are_constant():
    assert growth.the_quorum_is_affine_and_fits_the_same_way_wrongly()["they_are_all_the_same"]


def test_the_quorum_fit_reads_as_sublinear():
    assert growth.the_quorum_is_affine_and_fits_the_same_way_wrongly()[
        "and_it_reads_as_sublinear"
    ]


def test_the_quorum_bends_the_other_way():
    assert growth.the_quorum_is_affine_and_fits_the_same_way_wrongly()[
        "so_it_bends_the_other_way"
    ]


def test_the_log_is_linear_in_writes():
    assert growth.the_log_grows_exactly_with_the_writes()["it_is_linear"]


def test_the_log_fit_is_clean():
    assert growth.the_log_grows_exactly_with_the_writes()["and_the_fit_is_clean"]


def test_the_log_overhead_is_one_per_election():
    assert growth.the_log_grows_exactly_with_the_writes()["the_overhead_is_the_noop"] == [
        1,
        1,
        1,
        1,
    ]


def test_messages_are_sublinear_in_writes():
    assert growth.messages_grow_more_slowly_than_the_writes()["so_it_is_sublinear"]


def test_the_write_exponent_is_below_one():
    assert growth.messages_grow_more_slowly_than_the_writes()["it_is_below_one"]


def test_the_per_write_cost_falls():
    assert growth.messages_grow_more_slowly_than_the_writes()["and_the_per_write_cost_falls"]


def test_the_per_write_saving_is_real():
    assert growth.messages_grow_more_slowly_than_the_writes()["by_this_ratio"] > 1.2


def test_two_ratios_disagree():
    assert growth.a_ratio_between_two_points_would_have_said_something_else()["they_disagree"]


def test_neither_ratio_is_a_doubling():
    assert growth.a_ratio_between_two_points_would_have_said_something_else()["neither_is_two"]


def test_the_fit_uses_every_point():
    assert growth.a_ratio_between_two_points_would_have_said_something_else()[
        "which_uses_every_point"
    ]


def test_the_fit_predicts_a_held_out_point():
    assert growth.the_fit_predicts_a_point_it_was_not_given()["it_is_close"]


def test_the_held_out_error_is_small():
    assert growth.the_fit_predicts_a_point_it_was_not_given()["error"] < 0.1


def test_the_fits_repeat_exactly():
    assert growth.the_fits_repeat_exactly()["they_are_identical"]


def test_the_fits_repeat_to_every_decimal():
    assert growth.the_fits_repeat_exactly()["to_every_decimal"]


def test_a_fit_with_too_few_points_is_refused():
    assert growth.a_fit_with_too_few_points_is_refused()


def test_a_zero_cost_point_is_dropped():
    assert growth.a_fit_with_a_zero_cost_drops_the_point()["it_dropped_one"]


def test_the_dropped_point_is_the_zero():
    assert growth.a_fit_with_a_zero_cost_drops_the_point()["and_it_is_the_zero"]


def test_dropping_the_zero_leaves_a_linear_fit():
    assert growth.a_fit_with_a_zero_cost_drops_the_point()["which_is_linear"]


def test_a_mismatched_fit_is_refused():
    assert growth.a_mismatched_fit_is_refused()


def test_a_clean_exponent_is_flagged():
    assert growth.an_exponent_far_from_a_whole_number_is_not_clean()["it_is_clean"]


def test_an_awkward_exponent_is_not():
    assert growth.an_exponent_far_from_a_whole_number_is_not_clean()["and_that_one_is_not"]


def test_the_clean_flag_discriminates():
    assert growth.an_exponent_far_from_a_whole_number_is_not_clean()[
        "so_the_flag_discriminates"
    ]


def test_the_fit_table_covers_four():
    assert len(growth.compare_the_fits()) == 4


def test_two_fits_are_affine_in_disguise():
    assert (
        len(growth.only_one_of_the_four_fits_is_a_power_law_at_all()["affine_in_disguise"]) == 2
    )


def test_neither_affine_fit_reads_as_one():
    assert growth.only_one_of_the_four_fits_is_a_power_law_at_all()["neither_is_one"]


def test_the_worthwhile_fit_is_named():
    assert (
        growth.only_one_of_the_four_fits_is_a_power_law_at_all()["and_the_one_worth_fitting"]
        == "messages by writes"
    )


def test_the_summary_reports_both_exponents():
    made = growth.summarise()
    assert made["fitting_size_gives"] != made["fitting_peers_gives"]


def test_the_summary_says_the_fits_repeat():
    assert growth.summarise()["the_fits_repeat_exactly"]


def test_a_fit_reports_its_exponent():
    made = fit("x", {1: 1.0, 2: 2.0, 4: 4.0})
    assert abs(made.exponent - 1.0) < 1e-9


def test_a_quadratic_fits_at_two():
    made = fit("x", {1: 1.0, 2: 4.0, 4: 16.0})
    assert abs(made.exponent - 2.0) < 1e-9


def test_a_constant_fits_at_zero():
    made = fit("x", {1: 5.0, 2: 5.0, 4: 5.0})
    assert abs(made.exponent) < 1e-9


def test_a_fit_reports_its_nearest_whole_number():
    made = fit("x", {1: 1.0, 2: 2.1, 4: 3.9})
    assert made.nearest == 1


def test_a_clean_fit_says_so():
    assert fit("x", {1: 1.0, 2: 2.0, 4: 4.0}).clean


def test_a_fit_predicts():
    made = fit("x", {1: 1.0, 2: 2.0, 4: 4.0})
    assert abs(made.predict(8) - 8.0) < 1e-6


def test_a_fit_reports_its_error():
    made = fit("x", {1: 1.0, 2: 2.0, 4: 4.0})
    assert made.error_at(8, 8.0) < 1e-6


def test_a_fit_of_a_zero_actual_has_no_error():
    made = fit("x", {1: 1.0, 2: 2.0, 4: 4.0})
    assert made.error_at(8, 0.0) == 0.0


def test_a_fit_summarises():
    assert fit("x", {1: 1.0, 2: 2.0, 4: 4.0}).as_dict()["fit"] == "x"


def test_a_fit_prints_itself():
    assert "goes as size to the" in str(fit("x", {1: 1.0, 2: 2.0, 4: 4.0}))


def test_a_fit_with_two_points_raises():
    with pytest.raises(ConfigError):
        fit("x", {1: 1.0, 2: 2.0})


def test_a_fit_with_mismatched_lengths_raises():
    with pytest.raises(ConfigError):
        Fit(name="x", xs=(1, 2, 3), ys=(1.0,), exponent=1.0, constant=1.0)


def test_the_sizes_are_odd():
    assert all(one % 2 == 1 for one in SIZES)


def test_the_lengths_double():
    assert all(LENGTHS[one] * 2 == LENGTHS[one + 1] for one in range(len(LENGTHS) - 1))


def test_the_nearness_threshold_is_tight():
    assert NEAR <= 0.2
