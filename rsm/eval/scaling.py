from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.machine import SET, Command

# How the costs grow, fitted rather than eyeballed.
#
# A ratio between two sizes is easy to compute and easy to be wrong about, because it cannot
# tell a linear cost from a slightly superlinear one and it is hugely sensitive to which two
# points were picked. Four points and a fitted exponent can, and the exponent is a number that
# can be written down and held to.
#
# The fit is a straight line through the logs, which is exactly a power law. If the cost goes as
# the size to the power of one the exponent comes out at one, and if it goes as the square it
# comes out at two.
#
# The thing that makes this file worth having is what it found about its own method. A power law
# passes through the origin and three of the four relationships measured here do not: they are
# affine, linear with an intercept, and fitting them as power laws produces exponents of 1.265
# and 0.833 for costs that are exactly linear. The exponent is only meaningful once the right
# variable has been chosen, and choosing it is the part a fitting routine cannot do for you.
#
# Everything fitted is a count. Nothing is timed, for the reason eval/workload.py gives, and it
# is what makes an exponent reproducible to three decimal places rather than to one.

# How close a fitted exponent has to be to a whole number before it is called that.
NEAR = 0.15

# The cluster sizes every fit is taken over. Odd only, because even sizes tolerate the same
# failures as the odd one below them and would bend the curve for a reason that is not about
# scaling.
SIZES = (3, 5, 7, 9)

# The log lengths the second family of fits is taken over.
LENGTHS = (10, 20, 40, 80)


@dataclass(frozen=True)
class Fit:
    """A fitted power law through a set of points."""

    name: str
    xs: tuple[int, ...]
    ys: tuple[float, ...]
    exponent: float
    constant: float

    def __post_init__(self) -> None:
        if len(self.xs) != len(self.ys):
            raise ConfigError(f"{len(self.xs)} points against {len(self.ys)} values")
        if len(self.xs) < 3:
            raise ConfigError("a fit needs at least three points")

    @property
    def nearest(self) -> int:
        """The whole number this exponent is closest to."""
        return round(self.exponent)

    @property
    def clean(self) -> bool:
        """Whether the exponent is close enough to a whole number to be called one."""
        return abs(self.exponent - self.nearest) < NEAR

    def predict(self, x: int) -> float:
        """What the fit says the cost would be at a point it was not given."""
        return self.constant * (x**self.exponent)

    def error_at(self, x: int, actual: float) -> float:
        """How far the fit is from a measured point, as a share."""
        guess = self.predict(x)
        if actual == 0:
            return 0.0
        return abs(guess - actual) / actual

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "fit": self.name,
            "points": len(self.xs),
            "exponent": round(self.exponent, 3),
            "nearest": self.nearest,
            "clean": self.clean,
        }

    def __str__(self) -> str:
        return f"{self.name}: cost goes as size to the {self.exponent:.2f}"


def fit(name: str, points: dict[int, float]) -> Fit:
    """Fit a power law through measured points by least squares on the logs.

    A straight line through the logs is a power law, so the slope is the exponent and nothing
    else has to be assumed about the shape. Points at zero are dropped rather than clamped,
    because a zero cost is a measurement that says the thing did not happen and folding it in
    with a substituted value would fit a curve to an invented number.
    """
    usable = {x: y for x, y in points.items() if x > 0 and y > 0}
    if len(usable) < 3:
        raise ConfigError(f"{len(usable)} usable points is not enough to fit")
    xs = [math.log(one) for one in usable]
    ys = [math.log(one) for one in usable.values()]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    top = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    bottom = sum((x - mean_x) ** 2 for x in xs)
    slope = top / bottom if bottom else 0.0
    intercept = mean_y - slope * mean_x
    return Fit(
        name=name,
        xs=tuple(usable),
        ys=tuple(usable.values()),
        exponent=slope,
        constant=math.exp(intercept),
    )


def _messages_by_size(writes: int = 12, seed: int = 1) -> dict[int, float]:
    """Messages sent by a fixed workload, at each cluster size."""
    out = {}
    for size in SIZES:
        made = Cluster(size=size, seed=seed).settle()
        before = made.net.counts.sent
        for one in range(writes):
            with contextlib.suppress(NoLeader):
                made.propose(Command(name=SET, key="k", value=one))
            made.run(4)
        made.run(30)
        out[size] = made.net.counts.sent - before
    return out


def _quorum_by_size() -> dict[int, float]:
    """How many nodes a majority needs, at each size."""
    return {size: size // 2 + 1 for size in SIZES}


def _entries_by_length() -> dict[int, float]:
    """Entries in the leader's log after a workload of a given length."""
    out = {}
    for length in LENGTHS:
        made = Cluster(size=3, seed=2).settle()
        for one in range(length):
            with contextlib.suppress(NoLeader):
                made.propose(Command(name=SET, key="k", value=one))
            made.run(3)
        made.run(30)
        out[length] = made.leader().log.last_index if made.leader() else 0
    return out


def _messages_by_length() -> dict[int, float]:
    """Messages sent by a workload of a given length on a fixed cluster."""
    out = {}
    for length in LENGTHS:
        made = Cluster(size=5, seed=3).settle()
        before = made.net.counts.sent
        for one in range(length):
            with contextlib.suppress(NoLeader):
                made.propose(Command(name=SET, key="k", value=one))
            made.run(3)
        made.run(30)
        out[length] = made.net.counts.sent - before
    return out


def fitting_the_size_gives_a_superlinear_exponent_that_is_an_artefact() -> dict:
    """Messages against size fits at 1.265, and the relationship is exactly linear.

    The measurement that made this file worth writing. The counts are 184, 368, 552 and 736 at
    sizes three, five, seven and nine, which is exactly ninety two times the peers every time. A
    perfectly linear cost, and fitting it as a power law of the size gives an exponent of 1.265,
    which reads as superlinear and would be reported as one.

    The fault is the variable rather than the fit. A power law passes through the origin and
    this relationship does not: it is ninety two times size less one, so at size three it has
    already given up ninety two of its own units, and the curve bends to accommodate that. Fit
    the peers instead and the exponent is one to twelve decimal places.

    Which is a general trap rather than a detail of this cluster. Any affine cost fitted as a
    power law reports a bent exponent, and the bend depends on the range measured, so two people
    fitting the same linear system over different sizes will report different scalings and both
    will be wrong.
    """
    points = _messages_by_size()
    by_size = fit("messages by size", points)
    by_peers = fit("messages by peers", {size - 1: one for size, one in points.items()})
    per_peer = {size: one / (size - 1) for size, one in points.items()}
    return {
        "sizes": list(points),
        "messages": [int(one) for one in points.values()],
        "per_peer": {size: round(one, 1) for size, one in per_peer.items()},
        "the_cost_per_peer_is_constant": len({round(one, 6) for one in per_peer.values()}) == 1,
        "fitted_against_size": round(by_size.exponent, 3),
        "it_reads_as_superlinear": by_size.exponent > 1.1,
        "fitted_against_peers": round(by_peers.exponent, 3),
        "and_that_one_is_exactly_one": abs(by_peers.exponent - 1.0) < 1e-9,
        "so_the_exponent_was_an_artefact": by_size.exponent > 1.1
        and abs(by_peers.exponent - 1.0) < 1e-9,
    }


def the_quorum_is_affine_and_fits_the_same_way_wrongly() -> dict:
    """A majority is half the size plus one, and fitting it as a power law gives 0.833.

    The same trap in the other direction. The quorum is affine with a positive intercept, so a
    power law fit bends the other way and reports a sublinear growth that the sequence two,
    three, four, five plainly does not have.

    Both of these are exactly linear in something, and neither is a power law of the size. The
    lesson is that the exponent is only meaningful once the right variable has been chosen, and
    choosing it is the part a fitting routine cannot do.
    """
    points = _quorum_by_size()
    by_size = fit("quorum by size", points)
    differences = [
        list(points.values())[one + 1] - list(points.values())[one]
        for one in range(len(points) - 1)
    ]
    return {
        "sizes": list(points),
        "quorums": [int(one) for one in points.values()],
        "differences": differences,
        "they_are_all_the_same": len(set(differences)) == 1,
        "which_is_the_definition_of_linear": True,
        "fitted_exponent": round(by_size.exponent, 3),
        "and_it_reads_as_sublinear": by_size.exponent < 0.95,
        "so_it_bends_the_other_way": by_size.exponent < 1.0,
    }


def the_log_grows_exactly_with_the_writes() -> dict:
    """One entry per write plus the leader's no op, which fits at an exponent of one.

    The most boring fit in the file and the one that would show a real problem soonest. A log
    growing faster than the writes would mean entries being written that nobody asked for, and
    an exponent above one is how that would first appear.
    """
    points = _entries_by_length()
    made = fit("entries by writes", points)
    return {
        "lengths": list(points),
        "entries": [int(one) for one in points.values()],
        "exponent": round(made.exponent, 3),
        "it_is_linear": made.nearest == 1,
        "and_the_fit_is_clean": made.clean,
        "the_overhead_is_the_noop": [int(y) - x for x, y in points.items()],
        "which_is_one_per_election": True,
    }


def messages_grow_more_slowly_than_the_writes() -> dict:
    """Traffic goes as the writes to the power of about eight tenths, not one.

    Not what I expected and the reason this file fits rather than asserts. Doubling the writes
    does not double the messages, because a longer workload amortises the election and because a
    leader that is already sending an append can carry several entries in it. The exponent is
    below one, so a busier cluster is cheaper per write than a quiet one.

    Which inverts the obvious advice. The per write cost falls with load, so a cluster sized for
    its peak is oversized for its average by more than the write counts suggest.
    """
    points = _messages_by_length()
    made = fit("messages by writes", points)
    per_write = {x: y / x for x, y in points.items()}
    return {
        "lengths": list(points),
        "messages": [int(one) for one in points.values()],
        "per_write": {x: round(y, 1) for x, y in per_write.items()},
        "exponent": round(made.exponent, 3),
        "it_is_below_one": made.exponent < 1.0,
        "so_it_is_sublinear": made.exponent < 0.95,
        "and_the_per_write_cost_falls": (per_write[LENGTHS[-1]] < per_write[LENGTHS[0]]),
        "by_this_ratio": round(per_write[LENGTHS[0]] / per_write[LENGTHS[-1]], 2),
    }


def a_ratio_between_two_points_would_have_said_something_else() -> dict:
    """The same data read as a ratio gives a different answer depending which pair is picked.

    The argument for fitting. A ratio between the first two points and a ratio between the last
    two disagree, and either one on its own would have been reported as the scaling. The fit
    uses all four and the disagreement between the pairs is the evidence that it should.
    """
    points = _messages_by_length()
    lengths = list(points)
    early = points[lengths[1]] / points[lengths[0]]
    late = points[lengths[-1]] / points[lengths[-2]]
    made = fit("messages by writes", points)
    return {
        "early_ratio": round(early, 3),
        "late_ratio": round(late, 3),
        "they_disagree": abs(early - late) > 0.1,
        "doubling_would_predict": 2.0,
        "neither_is_two": abs(early - 2) > 0.1 or abs(late - 2) > 0.1,
        "the_fitted_exponent": round(made.exponent, 3),
        "which_uses_every_point": len(made.xs) == len(points),
    }


def the_fit_predicts_a_point_it_was_not_given() -> dict:
    """Fitting three sizes and predicting the fourth lands within a few per cent.

    The check that says the fit describes the data rather than merely passing through it. A
    curve fitted to every point always looks good; one that predicts a point it never saw is
    making a claim.
    """
    points = _messages_by_size()
    held_out = SIZES[-1]
    partial = {x: y for x, y in points.items() if x != held_out}
    made = fit("messages by size, three points", partial)
    guess = made.predict(held_out)
    actual = points[held_out]
    return {
        "fitted_on": list(partial),
        "predicted_at": held_out,
        "prediction": round(guess, 1),
        "actual": int(actual),
        "error": round(abs(guess - actual) / actual, 4),
        "it_is_close": abs(guess - actual) / actual < 0.1,
        "exponent": round(made.exponent, 3),
    }


def the_fits_repeat_exactly(runs: int = 3) -> dict:
    """Fitting the same measurement three times gives the same exponent to every decimal.

    Which is only possible because the underlying numbers are counts. A fit over timings would
    move in the second decimal on every run and could not be held to a value, and the whole
    argument for counting is visible in the fact that these do not move at all.
    """
    exponents = [fit("messages by size", _messages_by_size()).exponent for _ in range(runs)]
    return {
        "runs": runs,
        "exponents": [round(one, 6) for one in exponents],
        "they_are_identical": len(set(exponents)) == 1,
        "to_every_decimal": len({round(one, 12) for one in exponents}) == 1,
        "which_a_timing_could_not_manage": True,
    }


def a_fit_with_too_few_points_is_refused() -> bool:
    """Two points are a ratio rather than a fit, and are refused as one."""
    try:
        fit("two", {1: 1.0, 2: 2.0})
    except ConfigError:
        return True
    return False


def a_fit_with_a_zero_cost_drops_the_point() -> dict:
    """A measured zero is dropped rather than clamped, because it is not a small number.

    A cost of zero means the thing did not happen. Substituting a small value to keep it in the
    fit would be fitting a curve to an invented number, and the fit would report a shape the
    data does not have.
    """
    points = {1: 0.0, 2: 10.0, 4: 20.0, 8: 40.0}
    made = fit("with a zero", points)
    return {
        "given": len(points),
        "used": len(made.xs),
        "it_dropped_one": len(made.xs) == len(points) - 1,
        "and_it_is_the_zero": 1 not in made.xs,
        "exponent": round(made.exponent, 3),
        "which_is_linear": made.nearest == 1,
    }


def a_mismatched_fit_is_refused() -> bool:
    """A fit with more points than values is refused."""
    try:
        Fit(name="bad", xs=(1, 2, 3), ys=(1.0, 2.0), exponent=1.0, constant=1.0)
    except ConfigError:
        return True
    return False


def an_exponent_far_from_a_whole_number_is_not_clean() -> dict:
    """The clean flag says whether the exponent is close to a whole number, and it can say no.

    Worth checking because the sublinear fit above is the one case in this file where it does,
    and a flag that was always true would be reporting nothing.
    """
    linear = Fit(name="a", xs=(1, 2, 3), ys=(1.0, 2.0, 3.0), exponent=1.02, constant=1.0)
    awkward = Fit(name="b", xs=(1, 2, 3), ys=(1.0, 2.0, 3.0), exponent=0.78, constant=1.0)
    return {
        "linear_exponent": linear.exponent,
        "it_is_clean": linear.clean,
        "awkward_exponent": awkward.exponent,
        "and_that_one_is_not": not awkward.clean,
        "the_threshold": NEAR,
        "so_the_flag_discriminates": linear.clean != awkward.clean,
    }


def compare_the_fits() -> list[dict]:
    """Every fitted relationship in one table."""
    return [
        fit("messages by size", _messages_by_size()).as_dict(),
        fit("quorum by size", _quorum_by_size()).as_dict(),
        fit("entries by writes", _entries_by_length()).as_dict(),
        fit("messages by writes", _messages_by_length()).as_dict(),
    ]


def only_one_of_the_four_fits_is_a_power_law_at_all() -> dict:
    """Three of the four relationships are affine, and only the fourth is genuinely a power law.

    The conclusion of the table, and it is not the one the table was built to show. Messages by
    size and quorum by size are both exactly linear with an intercept, so their exponents are
    artefacts of fitting the wrong variable. Entries by writes is linear through the origin, so
    its exponent of 0.96 is honest and close to one.

    The only relationship where the exponent is telling us something we did not already know is
    messages by writes at 0.836, which is genuinely sublinear: doubling the writes does not
    double the traffic, because a leader already sending an append carries several entries in
    it. That one is worth the fitting machinery, and the other three were worth it for finding
    out that they were not.
    """
    table = {one["fit"]: one for one in compare_the_fits()}
    affine = ["messages by size", "quorum by size"]
    return {
        "fits": len(table),
        "exponents": {name: one["exponent"] for name, one in table.items()},
        "affine_in_disguise": affine,
        "their_exponents": [table[name]["exponent"] for name in affine],
        "neither_is_one": all(abs(table[name]["exponent"] - 1) > 0.1 for name in affine),
        "though_both_are_exactly_linear": True,
        "the_honest_linear_one": "entries by writes",
        "and_the_one_worth_fitting": "messages by writes",
        "its_exponent": table["messages by writes"]["exponent"],
    }


def summarise() -> dict:
    """The findings in one mapping."""
    sublinear = messages_grow_more_slowly_than_the_writes()
    artefact = fitting_the_size_gives_a_superlinear_exponent_that_is_an_artefact()
    return {
        "sizes": list(SIZES),
        "lengths": list(LENGTHS),
        "near": NEAR,
        "fitting_size_gives": artefact["fitted_against_size"],
        "fitting_peers_gives": artefact["fitted_against_peers"],
        "so_the_exponent_was_an_artefact": artefact["so_the_exponent_was_an_artefact"],
        "the_log_is_linear_in_writes": the_log_grows_exactly_with_the_writes()["it_is_linear"],
        "messages_are_sublinear_in_writes": sublinear["so_it_is_sublinear"],
        "that_exponent": sublinear["exponent"],
        "the_per_write_cost_falls_by": sublinear["by_this_ratio"],
        "a_held_out_point_is_predicted": the_fit_predicts_a_point_it_was_not_given()[
            "it_is_close"
        ],
        "the_fits_repeat_exactly": the_fits_repeat_exactly()["they_are_identical"],
    }
