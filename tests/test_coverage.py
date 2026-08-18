from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.node import CANDIDATE, FOLLOWER, LEADER, ROLES
from rsm.rpc import APPEND, CURRENT, KINDS, STALE, VOTE
from rsm.verify import coverage as reach
from rsm.verify.coverage import (
    SCENARIOS,
    TERMS,
    Cell,
    Coverage,
    by_hand,
    grid,
    measure_all,
)


def test_the_quiet_run_reaches_a_few_cells():
    assert reach.five_scenarios_reach_a_fifth_of_the_grid()["quiet_reached"] > 0


def test_the_faults_add_cells():
    assert reach.five_scenarios_reach_a_fifth_of_the_grid()["the_faults_added"] > 0


def test_the_union_is_about_a_fifth():
    assert reach.five_scenarios_reach_a_fifth_of_the_grid()["which_is_about_a_fifth"]


def test_no_single_scenario_reaches_the_union():
    assert reach.five_scenarios_reach_a_fifth_of_the_grid()[
        "and_no_single_scenario_reaches_half_of_the_union"
    ]


def test_nothing_in_the_grid_is_unreachable():
    assert reach.every_cell_is_reachable_and_the_scenarios_reach_a_fifth()[
        "nothing_is_unreachable"
    ]


def test_there_is_no_dead_branch():
    assert reach.every_cell_is_reachable_and_the_scenarios_reach_a_fifth()[
        "so_there_is_no_dead_branch"
    ]


def test_the_hole_is_most_of_the_grid():
    assert reach.every_cell_is_reachable_and_the_scenarios_reach_a_fifth()[
        "and_it_is_most_of_the_grid"
    ]


def test_the_hole_has_examples():
    made = reach.every_cell_is_reachable_and_the_scenarios_reach_a_fifth()
    assert made["examples_of_the_hole"]


def test_the_pairs_are_a_minority():
    assert reach.the_cells_the_scenarios_reach_are_the_ones_the_node_sends()[
        "and_the_pairs_are_a_minority_of_the_grid"
    ]


def test_no_role_saw_a_stale_message():
    assert reach.the_cells_the_scenarios_reach_are_the_ones_the_node_sends()[
        "no_role_saw_a_stale_message"
    ]


def test_the_faults_add_terms():
    assert reach.the_cells_the_scenarios_reach_are_the_ones_the_node_sends()[
        "the_faults_add_terms_not_kinds"
    ]


def test_an_unknown_role_is_refused():
    assert reach.a_cell_with_an_unknown_role_is_refused()


def test_an_unknown_kind_is_refused():
    assert reach.a_cell_with_an_unknown_kind_is_refused()


def test_an_unknown_term_relation_is_refused():
    assert reach.a_cell_with_an_unknown_term_relation_is_refused()


def test_the_scenario_table_covers_them_all():
    assert len(reach.compare_the_scenarios()) == len(SCENARIOS)


def test_the_scenarios_differ_in_value():
    assert reach.the_cheapest_scenario_reaches_as_much_as_the_dearest()["they_differ"]


def test_the_partition_is_the_dearest():
    assert reach.the_cheapest_scenario_reaches_as_much_as_the_dearest()[
        "the_partition_is_the_dearest"
    ]


def test_the_partition_is_not_the_most_productive():
    assert reach.the_cheapest_scenario_reaches_as_much_as_the_dearest()[
        "and_not_the_most_productive"
    ]


def test_the_value_gap_is_large():
    made = reach.the_cheapest_scenario_reaches_as_much_as_the_dearest()
    assert made["by_this_factor"] > 1.5


def test_the_summary_counts_the_grid():
    assert reach.summarise()["grid"] == len(grid())


def test_the_summary_says_nothing_is_unreachable():
    assert reach.summarise()["nothing_is_unreachable"]


def test_the_grid_is_the_product():
    assert len(grid()) == len(ROLES) * len(KINDS) * len(TERMS)


def test_every_cell_in_the_grid_is_distinct():
    assert len(set(grid())) == len(grid())


def test_a_cell_summarises():
    assert Cell(role=FOLLOWER, kind=APPEND, term=CURRENT).as_dict()["role"] == FOLLOWER


def test_a_cell_prints_itself():
    made = Cell(role=LEADER, kind=VOTE, term=STALE)
    assert "leader" in str(made) and "stale" in str(made)


def test_an_unknown_role_raises():
    with pytest.raises(ConfigError):
        Cell(role="regent", kind=APPEND, term=CURRENT)


def test_an_unknown_kind_raises():
    with pytest.raises(ConfigError):
        Cell(role=FOLLOWER, kind="gossip", term=CURRENT)


def test_an_unknown_term_raises():
    with pytest.raises(ConfigError):
        Cell(role=FOLLOWER, kind=APPEND, term="sideways")


def test_a_coverage_reports_its_share():
    made = Coverage(name="x", cells={Cell(role=FOLLOWER, kind=APPEND, term=CURRENT)})
    assert 0 < made.share < 1


def test_an_empty_coverage_has_no_share():
    assert Coverage(name="x").share == 0.0


def test_a_coverage_summarises():
    assert Coverage(name="named").as_dict()["scenario"] == "named"


def test_a_coverage_reports_the_grid_size():
    assert Coverage(name="x").as_dict()["of"] == len(grid())


def test_measuring_covers_every_scenario():
    assert set(measure_all()) == set(SCENARIOS)


def test_every_scenario_reaches_something():
    assert all(one.cells for one in measure_all().values())


def test_every_scenario_sends_messages():
    assert all(one.messages > 0 for one in measure_all().values())


def test_the_quiet_scenario_reaches_the_fewest_or_close():
    made = measure_all()
    assert len(made["quiet"].cells) <= max(len(one.cells) for one in made.values())


def test_hand_building_reaches_the_whole_grid():
    assert len(by_hand()) == len(grid())


def test_hand_building_reaches_the_candidate_role():
    assert any(one.role == CANDIDATE for one in by_hand())


def test_hand_building_reaches_the_leader_role():
    assert any(one.role == LEADER for one in by_hand())


def test_hand_building_reaches_stale_terms():
    assert any(one.term == STALE for one in by_hand())


def test_the_scenarios_are_five():
    assert len(SCENARIOS) == 5


def test_there_are_three_term_relations():
    assert len(TERMS) == 3
