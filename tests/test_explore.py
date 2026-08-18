from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.node import Node
from rsm.verify import explore as search
from rsm.verify.explore import (
    BREADTH,
    DELIVER,
    DEPTH,
    MAX_TERM,
    PROPOSE,
    RESTART,
    TIMEOUT,
    Coverage,
    Move,
    Violation,
    explore,
    start,
)
from rsm.verify.fuzz import DEFECTS


def test_the_lost_vote_is_found_by_exploring():
    assert search.searching_every_ordering_finds_what_the_schedules_missed()[
        "found_with_restarts"
    ]


def test_the_lost_vote_breaks_election_safety():
    made = search.searching_every_ordering_finds_what_the_schedules_missed()
    assert made["property"] == "election safety"


def test_the_lost_vote_needs_a_restart():
    assert search.searching_every_ordering_finds_what_the_schedules_missed()[
        "and_without_them_it_is_invisible"
    ]


def test_the_lost_vote_path_is_short():
    made = search.searching_every_ordering_finds_what_the_schedules_missed()
    assert len(made["the_path"]) <= 10


def test_the_lost_vote_path_contains_a_restart():
    made = search.searching_every_ordering_finds_what_the_schedules_missed()
    assert any(one.startswith("restart") for one in made["the_path"])


def test_the_sound_implementation_survives_the_search():
    assert search.the_sound_implementation_survives_every_ordering_it_reaches()["nothing_broke"]


def test_a_clean_coverage_is_truthy():
    assert search.the_sound_implementation_survives_every_ordering_it_reaches()["it_is_truthy"]


def test_the_soundness_claim_is_bounded():
    assert search.the_sound_implementation_survives_every_ordering_it_reaches()[
        "and_the_claim_is_bounded"
    ]


def test_breadth_first_finds_both():
    assert search.breadth_first_finds_both_and_depth_first_finds_one()["breadth_found_both"]


def test_depth_first_finds_one():
    assert search.breadth_first_finds_both_and_depth_first_finds_one()["depth_found_one"]


def test_the_depth_first_path_is_longer():
    assert search.breadth_first_finds_both_and_depth_first_finds_one()[
        "depth_first_path_is_longer"
    ]


def test_the_depth_first_path_is_much_longer():
    made = search.breadth_first_finds_both_and_depth_first_finds_one()
    assert made["by_this_many_moves"] >= 4


def test_symmetry_cuts_the_state_count():
    assert search.symmetry_reduction_cuts_the_states_by_about_four()["cut_by"] > 2


def test_the_cut_is_about_the_permutations():
    assert search.symmetry_reduction_cuts_the_states_by_about_four()[
        "it_is_about_the_permutations"
    ]


def test_symmetry_finds_the_same_violation():
    assert search.symmetry_reduction_cuts_the_states_by_about_four()["both_found_it"]


def test_symmetry_finds_it_at_the_same_depth():
    assert search.symmetry_reduction_cuts_the_states_by_about_four()["and_at_the_same_depth"]


def test_symmetry_buys_depth():
    assert search.symmetry_reduction_cuts_the_states_by_about_four()[
        "the_same_budget_goes_deeper"
    ]


def test_the_deep_defects_are_not_reached():
    assert search.the_deep_defects_are_out_of_reach_of_both_searches()["neither_was_found"]


def test_the_budget_ran_out_on_breadth():
    assert search.the_deep_defects_are_out_of_reach_of_both_searches()[
        "the_budget_ran_out_on_breadth"
    ]


def test_the_deep_search_was_not_exhausted():
    assert search.the_deep_defects_are_out_of_reach_of_both_searches()["and_not_on_depth"]


def test_each_search_finds_one_the_other_misses():
    assert search.the_two_searches_find_different_defects()["each_finds_one_the_other_misses"]


def test_only_exploring_finds_the_lost_vote():
    assert search.the_two_searches_find_different_defects()["only_exploring"] == [
        "forgets the vote"
    ]


def test_only_fuzzing_finds_the_log_check():
    assert search.the_two_searches_find_different_defects()["only_fuzzing"] == [
        "ignores the log"
    ]


def test_both_find_the_double_vote():
    assert search.the_two_searches_find_different_defects()["both"] == ["votes twice"]


def test_together_they_cover_three_of_four():
    made = search.the_two_searches_find_different_defects()
    assert made["together_they_cover"] == 3 and made["out_of"] == 4


def test_the_last_defect_needs_a_written_scenario():
    assert search.the_two_searches_find_different_defects()[
        "and_the_last_one_needs_a_written_scenario"
    ]


def test_there_are_more_paths_than_states():
    assert search.a_state_reached_twice_is_explored_once()["there_are_more_paths_than_states"]


def test_the_path_to_state_ratio_is_large():
    assert search.a_state_reached_twice_is_explored_once()["by_this_factor"] > 10


def test_a_search_with_no_depth_is_refused():
    assert search.a_search_with_no_depth_is_refused()


def test_a_search_with_no_states_is_refused():
    assert search.a_search_with_no_state_budget_is_refused()


def test_an_unknown_order_is_refused():
    assert search.an_unknown_search_order_is_refused()


def test_an_unknown_move_is_refused():
    assert search.an_unknown_move_is_refused()


def test_a_delivery_without_a_message_is_refused():
    assert search.a_delivery_without_a_message_is_refused()


def test_a_timeout_without_a_node_is_refused():
    assert search.a_timeout_without_a_node_is_refused()


def test_a_world_of_no_nodes_is_refused():
    assert search.a_world_of_no_nodes_is_refused()


def test_the_defect_table_covers_them_all():
    assert len(search.compare_the_defects()) == len(DEFECTS)


def test_the_summary_says_the_lost_vote_is_found():
    assert search.summarise()["the_lost_vote_is_found"]


def test_the_summary_says_the_claim_is_bounded():
    assert search.summarise()["but_the_claim_is_bounded"]


def test_the_summary_counts_the_coverage():
    assert search.summarise()["the_two_searches_cover"] == 3


def test_a_fresh_world_has_nothing_in_flight():
    assert start(DEFECTS["sound"]).pending == []


def test_a_fresh_world_has_no_leaders():
    assert start(DEFECTS["sound"]).leaders == {}


def test_a_fresh_world_knows_its_members():
    assert start(DEFECTS["sound"], size=3).members == ("n0", "n1", "n2")


def test_a_world_of_no_nodes_raises():
    with pytest.raises(ConfigError):
        start(DEFECTS["sound"], size=0)


def test_a_timeout_puts_messages_in_flight():
    made = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n0"))
    assert len(made.pending) == 2


def test_a_delivery_takes_one_off_the_queue():
    made = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n0"))
    after = made.apply(Move(kind=DELIVER, index=0))
    assert len(after.pending) == len(made.pending)


def test_a_drop_loses_a_message():
    made = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n0"))
    after = made.apply(Move(kind="drop", index=0))
    assert after.lost == 1 and len(after.pending) == 1


def test_applying_a_move_leaves_the_original_alone():
    made = start(DEFECTS["sound"])
    made.apply(Move(kind=TIMEOUT, node="n0"))
    assert made.pending == []


def test_a_restart_forgets_the_role():
    made = start(DEFECTS["sound"])
    made.nodes["n0"].role = "leader"
    after = made.apply(Move(kind=RESTART, node="n0"))
    assert after.nodes["n0"].role == "follower"


def test_a_restart_keeps_the_term():
    made = start(DEFECTS["sound"])
    made.nodes["n0"].term = 5
    after = made.apply(Move(kind=RESTART, node="n0"))
    assert after.nodes["n0"].term == 5


def test_a_forgetful_restart_drops_the_vote():
    made = start(DEFECTS["forgets the vote"])
    made.nodes["n0"].voted_for = "n1"
    after = made.apply(Move(kind=RESTART, node="n0"))
    assert after.nodes["n0"].voted_for is None


def test_an_ordinary_restart_keeps_the_vote():
    made = start(DEFECTS["sound"])
    made.nodes["n0"].voted_for = "n1"
    after = made.apply(Move(kind=RESTART, node="n0"))
    assert after.nodes["n0"].voted_for == "n1"


def test_a_fresh_world_offers_a_timeout_per_node():
    assert len(start(DEFECTS["sound"]).moves()) == 3


def test_a_world_at_the_term_bound_offers_nothing():
    made = start(DEFECTS["sound"])
    for node in made.nodes.values():
        node.term = MAX_TERM
    assert made.moves() == []


def test_drops_double_the_delivery_moves():
    made = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n0"))
    assert len(made.moves(drops=True)) > len(made.moves())


def test_restarts_add_a_move_per_node():
    made = start(DEFECTS["sound"])
    assert len(made.moves(restarts=1)) == len(made.moves()) + 3


def test_a_key_is_stable():
    made = start(DEFECTS["sound"])
    assert made.key() == made.key()


def test_a_symmetric_key_folds_the_names():
    left = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n0"))
    right = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n1"))
    assert left.key(symmetry=True) == right.key(symmetry=True)


def test_a_plain_key_does_not():
    left = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n0"))
    right = start(DEFECTS["sound"]).apply(Move(kind=TIMEOUT, node="n1"))
    assert left.key() != right.key()


def test_a_move_prints_itself():
    assert str(Move(kind=DELIVER, index=2)) == "deliver 2"


def test_a_node_move_prints_its_node():
    assert str(Move(kind=TIMEOUT, node="n1")) == "timeout n1"


def test_a_propose_needs_a_node():
    with pytest.raises(ConfigError):
        Move(kind=PROPOSE)


def test_a_violation_with_a_property_is_truthy():
    assert Violation(property="election safety", detail="x", path=())


def test_a_violation_without_one_is_falsy():
    assert not Violation(property="", detail="", path=())


def test_a_violation_summarises():
    made = Violation(property="log matching", detail="x", path=("timeout n0",))
    assert made.as_dict()["depth"] == 1


def test_a_violation_prints_its_path():
    made = Violation(property="log matching", detail="x", path=("timeout n0",))
    assert "timeout n0" in str(made)


def test_a_coverage_with_a_violation_is_falsy():
    made = Coverage(
        states=1,
        depth=1,
        frontier=0,
        violation=Violation(property="x", detail="y", path=()),
    )
    assert not made


def test_a_coverage_summarises():
    assert Coverage(states=5, depth=2, frontier=1).as_dict()["states"] == 5


def test_an_exhausted_search_says_so():
    made = explore(DEFECTS["sound"], depth=2, states=100000, max_term=2, max_writes=0)
    assert made.exhausted


def test_an_exhausted_search_of_a_sound_node_finds_nothing():
    made = explore(DEFECTS["sound"], depth=2, states=100000, max_term=2, max_writes=0)
    assert made.violation is None


def test_a_search_stops_at_its_state_budget():
    assert explore(DEFECTS["sound"], depth=12, states=200).states <= 201


def test_a_search_reports_its_frontier():
    made = explore(DEFECTS["sound"], depth=3, states=100000, max_term=2, max_writes=0)
    assert made.frontier >= 0


def test_the_search_orders_are_two():
    assert {BREADTH, DEPTH} == {"breadth", "depth"}


def test_a_started_world_uses_the_defect_class():
    assert type(start(DEFECTS["sound"]).nodes["n0"]) is Node
