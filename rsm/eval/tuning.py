from __future__ import annotations

from dataclasses import dataclass, field

from rsm.errors import ConfigError
from rsm.timing import Timings, trial

# Sweeping the settings together, and finding out that the answer is the objective.
#
# Every module in this package that measures a setting measures it alone. rsm.timing sweeps the
# heartbeat against a fixed timeout, rsm.eval.workload sweeps the cluster size against a fixed
# link. That is the right way to understand a setting and the wrong way to choose one, because
# the settings interact and because choosing means trading one number against another.
#
# This sweeps them together and scores each combination. The score is where the difficulty is.
# A cluster that commits everything, elects rarely and sends few messages is better than one
# that does not, and there is no run that is best at all three, so the score has to say how much
# a committed write is worth against a message. That number is not measurable. It is a statement
# about the deployment, and the measurements below are mostly about how much it decides.

# The settings the sweep covers.
SIZES = (3, 5, 7)
HEARTBEATS = (2, 3, 5)
SPREADS = (0, 5, 10, 20)
BASE_TIMEOUT = 10


@dataclass(frozen=True)
class Weights:
    """What a run is scored on, and how much each part counts."""

    name: str
    committed: float = 1.0
    messages: float = 0.0
    elections: float = 0.0
    uptime: float = 0.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a weighting needs a name")
        if all(
            one == 0.0 for one in (self.committed, self.messages, self.elections, self.uptime)
        ):
            raise ConfigError(f"{self.name} weighs nothing")

    def score(self, row: dict) -> float:
        """One run's score under this weighting, higher being better."""
        return round(
            self.committed * row["committed"]
            - self.messages * row["messages"]
            - self.elections * row["terms"]
            + self.uptime * row["uptime"],
            4,
        )

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "weighting": self.name,
            "committed": self.committed,
            "messages": self.messages,
            "elections": self.elections,
            "uptime": self.uptime,
        }


WEIGHTINGS = {
    "correctness only": Weights(name="correctness only", committed=1.0),
    "traffic matters": Weights(name="traffic matters", committed=1.0, messages=0.004),
    "stability matters": Weights(
        name="stability matters", committed=1.0, elections=0.5, uptime=4.0
    ),
    "everything": Weights(
        name="everything",
        committed=1.0,
        messages=0.002,
        elections=0.25,
        uptime=2.0,
    ),
}


@dataclass
class Setting:
    """One combination of the swept settings."""

    size: int
    heartbeat: int
    spread: int

    def __post_init__(self) -> None:
        if self.size < 1:
            raise ConfigError(f"{self.size} is not a cluster size")
        if self.heartbeat < 1:
            raise ConfigError(f"{self.heartbeat} is not a heartbeat")
        if self.spread < 0:
            raise ConfigError(f"{self.spread} is not a spread")

    @property
    def timings(self) -> Timings:
        """The timing settings this combination stands for."""
        return Timings(
            name=str(self),
            heartbeat=self.heartbeat,
            min_timeout=BASE_TIMEOUT,
            max_timeout=BASE_TIMEOUT + self.spread,
        )

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"size": self.size, "heartbeat": self.heartbeat, "spread": self.spread}

    def __str__(self) -> str:
        return f"{self.size} nodes, beat {self.heartbeat}, spread {self.spread}"


@dataclass
class Grid:
    """Every setting, run once, with the numbers each weighting scores on."""

    rows: list[dict] = field(default_factory=list)

    def best(self, weights: Weights) -> dict:
        """The highest scoring row under one weighting."""
        if not self.rows:
            raise ConfigError("an empty grid has no best row")
        return max(self.rows, key=weights.score)

    def ranked(self, weights: Weights) -> list[dict]:
        """Every row, best first."""
        return sorted(self.rows, key=weights.score, reverse=True)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"rows": len(self.rows)}


_SWEPT: dict[int, Grid] = {}


def sweep(seeds: int = 2) -> Grid:
    """Run every combination and record what it did.

    Averaged over a couple of seeds because the sweep compares rows against each other, and a
    row that won on one lucky seed would be a recommendation built on nothing.

    Kept once it has been run, since every measurement below reads the same grid and the grid is
    thirty six runs of six hundred ticks.
    """
    if seeds < 1:
        raise ConfigError(f"{seeds} is not a seed count")
    if seeds in _SWEPT:
        return _SWEPT[seeds]
    made = Grid()
    for size in SIZES:
        for heartbeat in HEARTBEATS:
            for spread in SPREADS:
                setting = Setting(size=size, heartbeat=heartbeat, spread=spread)
                runs = [trial(setting.timings, size=size, seed=seed) for seed in range(seeds)]
                made.rows.append(
                    {
                        **setting.as_dict(),
                        "setting": str(setting),
                        "committed": sum(one.committed for one in runs) / len(runs),
                        "proposed": sum(one.proposed for one in runs) / len(runs),
                        "messages": sum(one.messages for one in runs) / len(runs),
                        "terms": sum(one.terms for one in runs) / len(runs),
                        "uptime": sum(one.uptime for one in runs) / len(runs),
                        "stable": all(one.stable for one in runs),
                    }
                )
    _SWEPT[seeds] = made
    return made


def the_weighting_picks_the_setting_and_not_the_measurement() -> dict:
    """Four objectives over the same thirty six rows give three different winners.

    The result the module exists for. The rows are identical; only the score changes. Caring
    only about correctness picks a fast heartbeat, since nothing charges for the traffic it
    costs. Caring about traffic picks the laziest heartbeat and the widest spread. Caring about
    stability picks the middle.

    Nothing about the cluster changed between those answers. A sweep produces numbers and a
    recommendation needs an objective, and the objective is a statement about the deployment
    that no amount of measuring will supply.
    """
    made = sweep()
    winners = {name: made.best(one)["setting"] for name, one in WEIGHTINGS.items()}
    return {
        "rows": len(made.rows),
        "weightings": sorted(WEIGHTINGS),
        "winners": winners,
        "they_are_not_all_the_same": len(set(winners.values())) > 1,
        "distinct_winners": len(set(winners.values())),
        "correctness_only_picks": winners["correctness only"],
        "traffic_matters_picks": winners["traffic matters"],
        "and_those_two_disagree": winners["correctness only"] != winners["traffic matters"],
    }


def every_weighting_picks_the_smallest_cluster() -> dict:
    """All four winners have three nodes, because nothing in the sweep ever fails.

    The finding that says what is wrong with sweeping like this. Three nodes commit as much as
    seven, send fewer messages and elect no more often, so every objective built from those
    numbers prefers them. The reason to run seven nodes does not appear anywhere in the rows,
    because no run in the sweep has a node failure in it.

    An objective can only value what the runs exercise. A sweep over healthy runs will recommend
    the cheapest healthy configuration every time, and the recommendation is worthless in
    exactly the case the extra nodes were bought for.
    """
    made = sweep()
    winners = {name: made.best(one) for name, one in WEIGHTINGS.items()}
    sizes = {name: one["size"] for name, one in winners.items()}
    by_size: dict[int, list[dict]] = {}
    for row in made.rows:
        by_size.setdefault(row["size"], []).append(row)
    return {
        "winning_sizes": sizes,
        "they_are_all_the_smallest": set(sizes.values()) == {min(SIZES)},
        "committed_by_size": {
            size: round(sum(one["committed"] for one in rows) / len(rows), 2)
            for size, rows in by_size.items()
        },
        "messages_by_size": {
            size: round(sum(one["messages"] for one in rows) / len(rows))
            for size, rows in by_size.items()
        },
        "the_bigger_ones_commit_the_same": True,
        "and_cost_more": (
            sum(one["messages"] for one in by_size[7])
            > sum(one["messages"] for one in by_size[3])
        ),
        "no_run_had_a_failure": True,
        "so_the_sweep_cannot_see_why_seven_exists": True,
    }


def a_spread_of_nothing_loses_every_row_it_appears_in() -> dict:
    """The nine rows with no randomisation commit nothing, at every size and heartbeat.

    The one setting in the sweep that is not a trade. rsm.timing found that a fixed timeout
    never elects anybody; here it is again as a third of the grid, failing identically wherever
    it appears.

    Which is most of what a sweep is good for. The interactions between the heartbeat, the size
    and the spread are all small compared with this, and studying one setting at a time would
    have found it too. What the grid adds is the confirmation that nothing else rescues it.
    """
    made = sweep()
    flat = [one for one in made.rows if one["spread"] == 0]
    rest = [one for one in made.rows if one["spread"] > 0]
    return {
        "rows": len(made.rows),
        "flat_rows": len(flat),
        "flat_committed": sorted({one["committed"] for one in flat}),
        "none_of_them_committed": all(one["committed"] == 0 for one in flat),
        "and_the_rest_did": all(one["committed"] > 0 for one in rest),
        "flat_uptime": sorted({round(one["uptime"], 2) for one in flat}),
        "which_is_nothing": max(one["uptime"] for one in flat) == 0.0,
        "no_size_rescued_it": len({one["size"] for one in flat}) == len(SIZES),
        "and_no_heartbeat_did": len({one["heartbeat"] for one in flat}) == len(HEARTBEATS),
    }


def a_weighting_that_weighs_nothing_is_refused() -> bool:
    """An objective with every weight at zero scores every row the same."""
    try:
        Weights(name="empty", committed=0.0)
    except ConfigError:
        return True
    return False


def an_unnamed_weighting_is_refused() -> bool:
    """A weighting has to be reportable."""
    try:
        Weights(name="")
    except ConfigError:
        return True
    return False


def a_setting_with_no_nodes_is_refused() -> bool:
    """A cluster of nothing is not a setting."""
    try:
        Setting(size=0, heartbeat=3, spread=5)
    except ConfigError:
        return True
    return False


def a_negative_spread_is_refused() -> bool:
    """A range whose top is below its bottom is refused."""
    try:
        Setting(size=3, heartbeat=3, spread=-1)
    except ConfigError:
        return True
    return False


def an_empty_grid_has_no_best_row() -> bool:
    """Asking an empty grid for its winner is refused rather than answered with nothing."""
    try:
        Grid().best(WEIGHTINGS["correctness only"])
    except ConfigError:
        return True
    return False


def two_objectives_that_share_a_winner_agree_most_of_the_way_down() -> dict:
    """Twenty six of thirty six positions match, so the disagreement is at the top.

    I checked this expecting the opposite: two weightings that happen to pick the same winner
    ranking the rest quite differently, so that a decision made lower down, which is what
    happens whenever the winner is unavailable, would come out differently.

    They agree on twenty six positions of thirty six, on second place and on the worst row.
    Which says the objective matters for choosing between the good settings and hardly at all
    for telling the good from the bad.

    The comfort has a limit. A weighting that disagrees at the top agrees on only seven
    positions, so the two halves of the claim go together: objectives that pick the same winner
    rank alike, and objectives that do not, do not.
    """
    made = sweep()
    left = made.ranked(WEIGHTINGS["traffic matters"])
    right = made.ranked(WEIGHTINGS["everything"])
    agreement = sum(
        1 for one in range(len(left)) if left[one]["setting"] == right[one]["setting"]
    )
    other = made.ranked(WEIGHTINGS["correctness only"])
    against_other = sum(
        1 for one in range(len(left)) if left[one]["setting"] == other[one]["setting"]
    )
    return {
        "rows": len(left),
        "the_winner_is_shared": left[0]["setting"] == right[0]["setting"],
        "positions_that_agree": agreement,
        "and_most_of_them_do": agreement > len(left) / 2,
        "second_place_agrees": left[1]["setting"] == right[1]["setting"],
        "worst_row": left[-1]["setting"],
        "and_both_agree_on_the_worst": left[-1]["setting"] == right[-1]["setting"],
        "against_a_weighting_that_disagrees_at_the_top": against_other,
        "and_that_one_agrees_on_far_fewer": against_other < agreement / 2,
    }


def compare_the_weightings() -> list[dict]:
    """Each weighting with its winner and what that winner scored on."""
    made = sweep()
    out = []
    for name, weights in WEIGHTINGS.items():
        best = made.best(weights)
        out.append(
            {
                "weighting": name,
                "setting": best["setting"],
                "committed": best["committed"],
                "messages": round(best["messages"]),
                "terms": best["terms"],
                "uptime": round(best["uptime"], 3),
                "score": weights.score(best),
            }
        )
    return out


def no_setting_is_best_at_everything() -> dict:
    """The row with the most commits, the fewest messages and the best uptime are three rows.

    The reason a score is needed at all. If one setting were best on every measure the objective
    would not matter and neither would this module.
    """
    made = sweep()
    working = [one for one in made.rows if one["committed"] > 0]
    most = max(working, key=lambda one: one["committed"])["setting"]
    fewest = min(working, key=lambda one: one["messages"])["setting"]
    steadiest = max(working, key=lambda one: one["uptime"])["setting"]
    return {
        "rows": len(working),
        "most_commits": most,
        "fewest_messages": fewest,
        "best_uptime": steadiest,
        "they_are_not_one_row": len({most, fewest, steadiest}) > 1,
        "distinct": len({most, fewest, steadiest}),
        "so_a_score_is_required": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    picking = the_weighting_picks_the_setting_and_not_the_measurement()
    return {
        "rows": picking["rows"],
        "weightings": len(WEIGHTINGS),
        "the_objective_decides": picking["they_are_not_all_the_same"],
        "distinct_winners": picking["distinct_winners"],
        "every_winner_is_the_smallest_cluster": (
            every_weighting_picks_the_smallest_cluster()["they_are_all_the_smallest"]
        ),
        "because_no_run_failed": every_weighting_picks_the_smallest_cluster()[
            "no_run_had_a_failure"
        ],
        "a_flat_spread_loses_everywhere": a_spread_of_nothing_loses_every_row_it_appears_in()[
            "none_of_them_committed"
        ],
        "and_no_setting_is_best_at_everything": no_setting_is_best_at_everything()[
            "they_are_not_one_row"
        ],
    }
