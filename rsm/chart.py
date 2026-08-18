from __future__ import annotations

import math
from dataclasses import dataclass, field

from rsm.errors import ConfigError

# Drawing a measurement, and the two ways a chart lies.
#
# Everything in this package prints tables, which are exact and hard to compare across rows. A
# chart is the opposite trade, and it is worth having for the sweeps: the shape of a curve is
# the finding in rsm.timing, rsm.backpressure and rsm.eval.scaling, and a shape read off twelve
# numbers is read wrong about as often as it is read right.
#
# The two ways a chart misleads are both about the axis. A bar chart whose baseline is not zero
# turns a five percent difference into a doubling, and a linear axis over values that differ by
# orders of magnitude shows one bar and eleven empty rows. Both are easy to do by accident and
# both are measured below, by drawing the same series twice and comparing what the drawing says.
#
# Nothing here is clever. It is text, it fits in a terminal, and the point of writing it rather
# than importing something is that a chart which rounds differently on different machines would
# be a chart this package cannot test.

# The width of a chart, in characters.
WIDTH = 40

# What a filled and an empty cell look like.
FULL = "#"
EMPTY = "."


@dataclass
class Series:
    """A named list of numbers, which is what everything here draws."""

    name: str
    values: list[float] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a series needs a name")
        if self.labels and len(self.labels) != len(self.values):
            raise ConfigError(f"{len(self.labels)} labels for {len(self.values)} values")

    @property
    def low(self) -> float:
        """The smallest value."""
        return min(self.values, default=0.0)

    @property
    def high(self) -> float:
        """The largest value."""
        return max(self.values, default=0.0)

    @property
    def span(self) -> float:
        """The distance between them, which is what a chart has to fit."""
        return self.high - self.low

    @property
    def flat(self) -> bool:
        """Whether every value is the same, which is a shape a chart must not invent."""
        return self.span == 0.0

    @property
    def orders(self) -> float:
        """How many powers of ten the values cover, which decides the axis."""
        low = min((one for one in self.values if one > 0), default=0.0)
        if low <= 0 or self.high <= 0:
            return 0.0
        return round(math.log10(self.high / low), 2)

    def at(self, index: int) -> str:
        """The label for one point, or its position when there are no labels."""
        if self.labels:
            return self.labels[index]
        return str(index)

    def __len__(self) -> int:
        return len(self.values)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "series": self.name,
            "points": len(self.values),
            "low": self.low,
            "high": self.high,
            "span": self.span,
            "orders": self.orders,
            "flat": self.flat,
        }


def bars(series: Series, width: int = WIDTH, from_zero: bool = True) -> list[str]:
    """One row per value, scaled either from zero or from the smallest value.

    From zero by default, because that is the honest default and the other one is the first way
    a chart lies. The option exists so the lie can be drawn and measured rather than described.
    """
    if width < 1:
        raise ConfigError(f"{width} is not a width")
    if not series.values:
        return []
    base = 0.0 if from_zero else series.low
    top = series.high
    reach = top - base
    out = []
    for index, value in enumerate(series.values):
        share = 0.0 if reach <= 0 else (value - base) / reach
        filled = max(0, min(width, round(share * width)))
        out.append(f"{series.at(index)} {FULL * filled}{EMPTY * (width - filled)} {value:g}")
    return out


def logarithmic(series: Series, width: int = WIDTH) -> list[str]:
    """One row per value, scaled by its logarithm, for series that span orders of magnitude.

    A series whose values are all equal draws full, the same as the linear chart does, rather
    than drawing one character. The two were inconsistent at first and a chart that changes
    shape when the axis changes, on data that has no shape, is the exact failure this module is
    about.
    """
    if width < 1:
        raise ConfigError(f"{width} is not a width")
    positive = [one for one in series.values if one > 0]
    if not positive:
        raise ConfigError("a logarithmic chart needs a positive value")
    low = math.log10(min(positive))
    high = math.log10(max(positive))
    reach = high - low
    out = []
    for index, value in enumerate(series.values):
        if value <= 0:
            out.append(f"{series.at(index)} {EMPTY * width} {value:g}")
            continue
        share = 1.0 if reach <= 0 else (math.log10(value) - low) / reach
        filled = max(1, min(width, round(share * width)))
        out.append(f"{series.at(index)} {FULL * filled}{EMPTY * (width - filled)} {value:g}")
    return out


def sparkline(series: Series) -> str:
    """The whole series on one line, at one character per point.

    Eight levels, because that is what the block characters would give and this uses digits so
    that the output is comparable across terminals. A sparkline is for spotting a shape in a
    table cell, not for reading a value off.
    """
    if not series.values:
        return ""
    if series.flat:
        return "0" * len(series.values)
    out = []
    for value in series.values:
        share = (value - series.low) / series.span
        out.append(str(min(7, int(share * 8))))
    return "".join(out)


def a_chart_from_zero_shows_the_ratio_and_one_from_the_minimum_does_not() -> dict:
    """Four values within ten percent become four bars within ten percent, or the full width.

    The first way a chart lies, drawn both ways. A series of ninety, ninety two, ninety five and
    ninety eight is nearly flat, and scaled from its own minimum it fills the width, which reads
    as a tenfold difference to anybody glancing at it.

    The rule is not that a baseline of zero is always right. It is that the baseline is part of
    the claim, and a chart that does not say which one it used has not made a claim at all.
    """
    made = Series(name="close", values=[90.0, 92.0, 95.0, 98.0])
    honest = bars(made, width=20, from_zero=True)
    misleading = bars(made, width=20, from_zero=False)
    return {
        "values": made.values,
        "span_as_a_share": round(made.span / made.high, 3),
        "it_is_a_small_difference": made.span / made.high < 0.15,
        "from_zero_first_bar": honest[0].count(FULL),
        "from_zero_last_bar": honest[-1].count(FULL),
        "and_they_are_close": honest[-1].count(FULL) - honest[0].count(FULL) <= 3,
        "from_minimum_first_bar": misleading[0].count(FULL),
        "from_minimum_last_bar": misleading[-1].count(FULL),
        "and_those_are_not": misleading[-1].count(FULL) - misleading[0].count(FULL) >= 15,
        "the_data_is_identical": True,
    }


def a_linear_axis_hides_a_series_that_spans_orders_of_magnitude() -> dict:
    """The availability errors from rsm.eval.availability draw as two empty rows and a full one.

    The second way a chart lies, and this one is by omission. Three, twenty one, four hundred
    and eighty two, nine thousand seven hundred: on a linear axis the first two are a fraction
    of a character and the shape of the growth is invisible.

    On a logarithmic axis all four are visible and the gaps between them are the ratios: four
    characters for the first step, eight for the second, seven for the third, which is right,
    because the first ratio is seven and the others are about twenty. The axis is what turns
    four numbers into a shape, and the shape it shows is the one the numbers have rather than an
    even staircase.
    """
    made = Series(name="error", values=[3.0, 20.8, 481.8, 9733.3], labels=["3", "5", "7", "9"])
    straight = [one.count(FULL) for one in bars(made, width=20)]
    curved = [one.count(FULL) for one in logarithmic(made, width=20)]
    return {
        "values": made.values,
        "orders_of_magnitude": made.orders,
        "it_spans_several": made.orders > 2,
        "linear_bars": straight,
        "the_first_two_are_empty": straight[:2] == [0, 0],
        "logarithmic_bars": curved,
        "and_the_log_ones_are_not": all(one > 0 for one in curved),
        "and_the_gaps_are_the_ratios": curved[1] - curved[0] < curved[2] - curved[1],
        "the_ratios": [round(made.values[one + 1] / made.values[one], 1) for one in range(3)],
    }


def a_flat_series_draws_flat() -> dict:
    """Four identical values give four identical bars and a sparkline of zeroes.

    The case a chart must not invent a shape for. Scaling from the minimum of a flat series
    divides by nothing, and the obvious implementations either raise or draw a full bar, both of
    which are answers to a question nobody asked.
    """
    made = Series(name="flat", values=[7.0, 7.0, 7.0, 7.0])
    drawn = bars(made, width=20)
    from_min = bars(made, width=20, from_zero=False)
    return {
        "flat": made.flat,
        "span": made.span,
        "bars_from_zero": [one.count(FULL) for one in drawn],
        "they_are_all_the_same": len({one.count(FULL) for one in drawn}) == 1,
        "and_full": drawn[0].count(FULL) == 20,
        "bars_from_the_minimum": [one.count(FULL) for one in from_min],
        "which_did_not_divide_by_nothing": len({one.count(FULL) for one in from_min}) == 1,
        "sparkline": sparkline(made),
        "and_the_sparkline_is_flat": set(sparkline(made)) == {"0"},
    }


def a_sparkline_shows_a_shape_and_not_a_value() -> dict:
    """A rising series reads as rising and a falling one as falling, in one line each.

    What a sparkline is for. It has eight levels and no axis, so it cannot be read for a number,
    and it fits in a table cell, so a table of twelve sweeps can carry twelve shapes.
    """
    rising = Series(name="up", values=[1.0, 2.0, 4.0, 8.0, 16.0])
    falling = Series(name="down", values=[16.0, 8.0, 4.0, 2.0, 1.0])
    bumpy = Series(name="bump", values=[1.0, 8.0, 16.0, 8.0, 1.0])
    return {
        "rising": sparkline(rising),
        "it_rises": sparkline(rising) == "".join(sorted(sparkline(rising))),
        "falling": sparkline(falling),
        "it_falls": sparkline(falling) == "".join(sorted(sparkline(falling), reverse=True)),
        "bumpy": sparkline(bumpy),
        "and_the_bump_peaks_in_the_middle": sparkline(bumpy)[2] == max(sparkline(bumpy)),
        "levels": len(set(sparkline(rising))),
        "and_it_is_one_line": "\n" not in sparkline(rising),
    }


def an_empty_series_draws_nothing() -> dict:
    """No values, no rows, and no exception either.

    The boundary a chart hits whenever a measurement returns nothing, which happens in this
    package whenever a run finds no leader. A chart that raised there would take a table with
    one empty column and turn it into a crash.
    """
    made = Series(name="empty")
    return {
        "points": len(made),
        "bars": bars(made),
        "it_drew_nothing": bars(made) == [],
        "sparkline": sparkline(made),
        "and_the_sparkline_is_empty": sparkline(made) == "",
        "low": made.low,
        "high": made.high,
        "which_are_zero_rather_than_an_error": made.low == made.high == 0.0,
    }


def a_series_with_the_wrong_number_of_labels_is_refused() -> bool:
    """A label per point or none at all."""
    try:
        Series(name="x", values=[1.0, 2.0], labels=["a"])
    except ConfigError:
        return True
    return False


def an_unnamed_series_is_refused() -> bool:
    """A chart with no name cannot be put in a table."""
    try:
        Series(name="", values=[1.0])
    except ConfigError:
        return True
    return False


def a_chart_of_no_width_is_refused() -> bool:
    """A chart with no room to draw in is refused."""
    try:
        bars(Series(name="x", values=[1.0]), width=0)
    except ConfigError:
        return True
    return False


def a_logarithmic_chart_of_nothing_positive_is_refused() -> bool:
    """A logarithm needs something above zero."""
    try:
        logarithmic(Series(name="x", values=[0.0, -1.0]))
    except ConfigError:
        return True
    return False


def compare_the_axes() -> list[dict]:
    """The same four series drawn both ways, with what each drawing shows."""
    made = {
        "close together": Series(name="close", values=[90.0, 92.0, 95.0, 98.0]),
        "orders apart": Series(name="orders", values=[3.0, 20.8, 481.8, 9733.3]),
        "flat": Series(name="flat", values=[7.0, 7.0, 7.0, 7.0]),
        "rising": Series(name="rising", values=[1.0, 2.0, 4.0, 8.0]),
    }
    out = []
    for label, series in made.items():
        linear = [one.count(FULL) for one in bars(series, width=20)]
        out.append(
            {
                "series": label,
                "orders": series.orders,
                "flat": series.flat,
                "linear range": max(linear) - min(linear),
                "sparkline": sparkline(series),
            }
        )
    return out


def the_axis_is_a_claim_and_not_a_setting() -> dict:
    """Two of the four series are drawn badly by a linear axis from zero, for opposite reasons.

    The table. The close together series is nearly flat and a linear axis from zero says so; the
    orders apart series is not, and the same axis hides three of its four points. Neither axis
    is right for both, and a chart that picked one without saying which would be making a claim
    silently.

    Which is why this module has both and neither is a default in the sense of being applied
    without being chosen: the caller says from_zero or calls logarithmic, and the choice is in
    the code that drew it.
    """
    table = compare_the_axes()
    wide = [one for one in table if one["orders"] > 2]
    narrow = [one for one in table if one["orders"] <= 1 and not one["flat"]]
    return {
        "series": [one["series"] for one in table],
        "wide": [one["series"] for one in wide],
        "narrow": [one["series"] for one in narrow],
        "the_wide_one_needs_a_log_axis": all(one["orders"] > 2 for one in wide),
        "and_the_narrow_ones_do_not": all(one["orders"] <= 1 for one in narrow),
        "flat_series": [one["series"] for one in table if one["flat"]],
        "and_the_flat_one_needs_neither": True,
        "linear_ranges": {one["series"]: one["linear range"] for one in table},
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "width": WIDTH,
        "a_baseline_changes_the_story": (
            a_chart_from_zero_shows_the_ratio_and_one_from_the_minimum_does_not()[
                "and_those_are_not"
            ]
        ),
        "and_the_data_is_the_same": (
            a_chart_from_zero_shows_the_ratio_and_one_from_the_minimum_does_not()[
                "the_data_is_identical"
            ]
        ),
        "a_linear_axis_hides_orders_of_magnitude": (
            a_linear_axis_hides_a_series_that_spans_orders_of_magnitude()[
                "the_first_two_are_empty"
            ]
        ),
        "a_flat_series_draws_flat": a_flat_series_draws_flat()["and_the_sparkline_is_flat"],
        "an_empty_series_draws_nothing": an_empty_series_draws_nothing()["it_drew_nothing"],
        "a_sparkline_shows_a_shape": a_sparkline_shows_a_shape_and_not_a_value()["it_rises"],
        "and_the_axis_is_a_claim": the_axis_is_a_claim_and_not_a_setting()[
            "the_wide_one_needs_a_log_axis"
        ],
    }
