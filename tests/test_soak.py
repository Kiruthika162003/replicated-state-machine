from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.verify import soak as long_run
from rsm.verify.coverage import grid
from rsm.verify.soak import BUDGET, SHORT, Soak, many_short_runs, one_long_run


def test_the_short_runs_reach_more():
    assert long_run.many_short_runs_reach_more_than_one_long_one()[
        "the_short_runs_reached_more"
    ]


def test_they_cost_the_same():
    assert long_run.many_short_runs_reach_more_than_one_long_one()["and_they_cost_the_same"]


def test_the_margin_is_large():
    made = long_run.many_short_runs_reach_more_than_one_long_one()
    assert made["by_this_factor"] > 1.5


def test_neither_broke_anything():
    assert long_run.many_short_runs_reach_more_than_one_long_one()["neither_broke_anything"]


def test_the_long_run_wastes_most_of_its_budget():
    assert long_run.the_long_run_stops_discovering_and_keeps_running()["which_is_most_of_it"]


def test_the_short_runs_waste_almost_nothing():
    assert long_run.the_long_run_stops_discovering_and_keeps_running()[
        "and_the_short_runs_waste_almost_none"
    ]


def test_the_short_runs_were_still_finding_things():
    assert long_run.the_long_run_stops_discovering_and_keeps_running()[
        "the_short_runs_were_still_finding_things"
    ]


def test_the_rate_favours_fresh_seeds():
    assert long_run.coverage_per_tick_favours_the_fresh_seed()["the_short_runs_win"]


def test_neither_way_covers_the_grid():
    assert long_run.coverage_per_tick_favours_the_fresh_seed()["and_neither_covers_it"]


def test_the_rate_margin_is_large():
    made = long_run.coverage_per_tick_favours_the_fresh_seed()
    assert made["by_this_factor"] > 1.5


def test_neither_way_finds_a_breach():
    assert long_run.neither_way_of_spending_finds_a_breach()["neither_broke"]


def test_both_ways_are_truthy():
    assert long_run.neither_way_of_spending_finds_a_breach()["both_are_truthy"]


def test_both_ways_committed_something():
    assert long_run.neither_way_of_spending_finds_a_breach()["and_both_committed_something"]


def test_a_budget_of_nothing_is_refused():
    assert long_run.a_budget_of_nothing_is_refused()


def test_a_run_length_of_nothing_is_refused():
    assert long_run.a_run_length_of_nothing_is_refused()


def test_the_length_table_covers_five():
    assert len(long_run.compare_the_run_lengths()) == 5


def test_every_split_beats_the_single_run():
    assert long_run.the_best_run_length_is_in_the_middle()["every_split_beats_it"]


def test_the_best_length_is_not_the_shortest():
    assert long_run.the_best_run_length_is_in_the_middle()["it_is_not_the_shortest"]


def test_the_best_length_is_not_the_longest():
    assert long_run.the_best_run_length_is_in_the_middle()["and_not_the_longest_split"]


def test_coverage_falls_off_on_both_sides():
    assert long_run.the_best_run_length_is_in_the_middle()["it_falls_off_on_both_sides"]


def test_the_summary_says_short_runs_reach_more():
    assert long_run.summarise()["short_runs_reach_more"]


def test_the_summary_says_the_best_length_is_in_the_middle():
    assert long_run.summarise()["the_best_length_is_in_the_middle"]


def test_a_soak_reports_its_coverage():
    made = one_long_run(budget=200)
    assert 0 < made.coverage <= 1


def test_an_empty_soak_has_no_coverage():
    assert Soak(name="x").coverage == 0.0


def test_a_soak_reports_its_rate():
    assert one_long_run(budget=200).per_thousand > 0


def test_a_soak_with_no_ticks_has_no_rate():
    assert Soak(name="x").per_thousand == 0.0


def test_a_soak_reports_its_last_discovery():
    assert one_long_run(budget=200).last_discovery > 0


def test_an_empty_soak_discovered_nothing():
    assert Soak(name="x").last_discovery == 0


def test_a_soak_reports_what_it_wasted():
    made = one_long_run(budget=200)
    assert made.wasted == made.ticks - made.last_discovery


def test_a_soak_with_no_breach_is_truthy():
    assert Soak(name="x")


def test_a_soak_with_a_breach_is_falsy():
    assert not Soak(name="x", breaches=1)


def test_a_soak_summarises():
    assert Soak(name="named").as_dict()["way"] == "named"


def test_a_long_run_is_one_run():
    assert one_long_run(budget=200).runs == 1


def test_a_long_run_spends_its_budget():
    assert one_long_run(budget=200).ticks == 200


def test_short_runs_spend_the_same_budget():
    assert many_short_runs(budget=300, each=100).ticks == 300


def test_short_runs_are_several():
    assert many_short_runs(budget=300, each=100).runs == 3


def test_short_runs_reach_something():
    assert many_short_runs(budget=300, each=100).cells


def test_a_soak_covers_part_of_the_grid():
    made = many_short_runs(budget=300, each=100)
    assert len(made.cells) < len(grid())


def test_a_zero_budget_raises():
    with pytest.raises(ConfigError):
        one_long_run(budget=0)


def test_a_zero_run_length_raises():
    with pytest.raises(ConfigError):
        many_short_runs(each=0)


def test_the_budget_is_worth_spending():
    assert BUDGET >= 1000


def test_the_short_length_gets_through_an_election():
    assert SHORT > 20
