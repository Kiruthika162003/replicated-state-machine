from __future__ import annotations

import pytest

from rsm import chart as draw
from rsm.chart import EMPTY, FULL, WIDTH, Series, bars, logarithmic, sparkline
from rsm.errors import ConfigError


def test_a_baseline_changes_the_story():
    assert draw.a_chart_from_zero_shows_the_ratio_and_one_from_the_minimum_does_not()[
        "and_those_are_not"
    ]


def test_the_bars_from_zero_stay_close():
    assert draw.a_chart_from_zero_shows_the_ratio_and_one_from_the_minimum_does_not()[
        "and_they_are_close"
    ]


def test_the_underlying_data_is_the_same():
    assert draw.a_chart_from_zero_shows_the_ratio_and_one_from_the_minimum_does_not()[
        "the_data_is_identical"
    ]


def test_a_linear_axis_empties_the_small_values():
    assert draw.a_linear_axis_hides_a_series_that_spans_orders_of_magnitude()[
        "the_first_two_are_empty"
    ]


def test_a_log_axis_shows_them_all():
    assert draw.a_linear_axis_hides_a_series_that_spans_orders_of_magnitude()[
        "and_the_log_ones_are_not"
    ]


def test_the_log_gaps_follow_the_ratios():
    assert draw.a_linear_axis_hides_a_series_that_spans_orders_of_magnitude()[
        "and_the_gaps_are_the_ratios"
    ]


def test_a_flat_series_draws_the_same_bars():
    assert draw.a_flat_series_draws_flat()["they_are_all_the_same"]


def test_a_flat_series_from_the_minimum_does_not_divide_by_nothing():
    assert draw.a_flat_series_draws_flat()["which_did_not_divide_by_nothing"]


def test_a_flat_sparkline_is_flat():
    assert draw.a_flat_series_draws_flat()["and_the_sparkline_is_flat"]


def test_a_rising_sparkline_rises():
    assert draw.a_sparkline_shows_a_shape_and_not_a_value()["it_rises"]


def test_a_falling_sparkline_falls():
    assert draw.a_sparkline_shows_a_shape_and_not_a_value()["it_falls"]


def test_a_bump_peaks_in_the_middle():
    assert draw.a_sparkline_shows_a_shape_and_not_a_value()["and_the_bump_peaks_in_the_middle"]


def test_a_sparkline_is_one_line():
    assert draw.a_sparkline_shows_a_shape_and_not_a_value()["and_it_is_one_line"]


def test_an_empty_series_draws_nothing():
    assert draw.an_empty_series_draws_nothing()["it_drew_nothing"]


def test_an_empty_series_has_no_sparkline():
    assert draw.an_empty_series_draws_nothing()["and_the_sparkline_is_empty"]


def test_an_empty_series_reports_zeroes():
    assert draw.an_empty_series_draws_nothing()["which_are_zero_rather_than_an_error"]


def test_mismatched_labels_are_refused():
    assert draw.a_series_with_the_wrong_number_of_labels_is_refused()


def test_an_unnamed_series_is_refused():
    assert draw.an_unnamed_series_is_refused()


def test_a_chart_of_no_width_is_refused():
    assert draw.a_chart_of_no_width_is_refused()


def test_a_logarithm_of_nothing_positive_is_refused():
    assert draw.a_logarithmic_chart_of_nothing_positive_is_refused()


def test_the_axis_table_covers_four():
    assert len(draw.compare_the_axes()) == 4


def test_the_wide_series_needs_a_log_axis():
    assert draw.the_axis_is_a_claim_and_not_a_setting()["the_wide_one_needs_a_log_axis"]


def test_the_narrow_series_do_not():
    assert draw.the_axis_is_a_claim_and_not_a_setting()["and_the_narrow_ones_do_not"]


def test_the_flat_series_needs_neither():
    assert draw.the_axis_is_a_claim_and_not_a_setting()["and_the_flat_one_needs_neither"]


def test_the_summary_says_the_baseline_matters():
    assert draw.summarise()["a_baseline_changes_the_story"]


def test_the_summary_says_the_axis_is_a_claim():
    assert draw.summarise()["and_the_axis_is_a_claim"]


def test_a_series_reports_its_range():
    made = Series(name="x", values=[1.0, 5.0, 3.0])
    assert made.low == 1.0 and made.high == 5.0


def test_a_series_reports_its_span():
    assert Series(name="x", values=[1.0, 5.0]).span == 4.0


def test_an_empty_series_has_no_span():
    assert Series(name="x").span == 0.0


def test_a_flat_series_says_it_is_flat():
    assert Series(name="x", values=[2.0, 2.0]).flat


def test_a_varying_series_does_not():
    assert not Series(name="x", values=[2.0, 3.0]).flat


def test_a_series_reports_its_orders_of_magnitude():
    assert Series(name="x", values=[1.0, 1000.0]).orders == 3.0


def test_a_series_with_no_positive_value_has_no_orders():
    assert Series(name="x", values=[0.0, -1.0]).orders == 0.0


def test_a_series_labels_its_points():
    made = Series(name="x", values=[1.0, 2.0], labels=["a", "b"])
    assert made.at(1) == "b"


def test_an_unlabelled_series_uses_positions():
    assert Series(name="x", values=[1.0, 2.0]).at(1) == "1"


def test_a_series_reports_its_length():
    assert len(Series(name="x", values=[1.0, 2.0, 3.0])) == 3


def test_a_series_summarises():
    assert Series(name="named", values=[1.0]).as_dict()["series"] == "named"


def test_mismatched_labels_raise():
    with pytest.raises(ConfigError):
        Series(name="x", values=[1.0, 2.0], labels=["only one"])


def test_an_unnamed_series_raises():
    with pytest.raises(ConfigError):
        Series(name="", values=[1.0])


def test_bars_draw_a_row_per_value():
    assert len(bars(Series(name="x", values=[1.0, 2.0, 3.0]))) == 3


def test_the_largest_value_fills_the_width():
    made = bars(Series(name="x", values=[1.0, 2.0]), width=10)
    assert made[-1].count(FULL) == 10


def test_a_zero_value_draws_empty():
    made = bars(Series(name="x", values=[0.0, 10.0]), width=10)
    assert made[0].count(FULL) == 0


def test_bars_pad_to_the_width():
    made = bars(Series(name="x", values=[1.0, 2.0]), width=10)
    assert made[0].count(FULL) + made[0].count(EMPTY) == 10


def test_bars_of_nothing_are_nothing():
    assert bars(Series(name="x")) == []


def test_a_zero_width_raises():
    with pytest.raises(ConfigError):
        bars(Series(name="x", values=[1.0]), width=0)


def test_a_logarithmic_chart_draws_every_positive_value():
    made = logarithmic(Series(name="x", values=[1.0, 100.0]), width=10)
    assert all(one.count(FULL) > 0 for one in made)


def test_a_logarithmic_chart_draws_a_zero_as_empty():
    made = logarithmic(Series(name="x", values=[0.0, 100.0]), width=10)
    assert made[0].count(FULL) == 0


def test_a_logarithmic_chart_of_one_value_is_full():
    made = logarithmic(Series(name="x", values=[5.0]), width=10)
    assert made[0].count(FULL) == 10


def test_a_logarithmic_chart_needs_a_positive_value():
    with pytest.raises(ConfigError):
        logarithmic(Series(name="x", values=[0.0]))


def test_a_logarithmic_chart_of_no_width_raises():
    with pytest.raises(ConfigError):
        logarithmic(Series(name="x", values=[1.0]), width=0)


def test_a_sparkline_has_a_character_per_point():
    assert len(sparkline(Series(name="x", values=[1.0, 2.0, 3.0]))) == 3


def test_a_sparkline_of_nothing_is_empty():
    assert sparkline(Series(name="x")) == ""


def test_a_sparkline_uses_digits():
    assert sparkline(Series(name="x", values=[1.0, 9.0])).isdigit()


def test_the_default_width_is_a_terminal_width():
    assert 20 <= WIDTH <= 80
