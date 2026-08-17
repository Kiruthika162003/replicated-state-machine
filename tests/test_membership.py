from __future__ import annotations

import pytest

from rsm import membership as config
from rsm.errors import ConfigError
from rsm.membership import (
    JOINT,
    STAGES,
    STEADY,
    Configuration,
    disjoint_majorities,
)


def test_three_to_four_has_no_disjoint_majorities():
    assert config.adding_one_node_at_a_time_is_usually_safe()["there_are_none"]


def test_one_to_three_does():
    assert config.adding_two_nodes_at_once_is_not()["so_two_at_once_is_unsafe"]


def test_the_two_at_once_example_is_shown():
    assert config.adding_two_nodes_at_once_is_not()["an_example"]


def test_every_single_change_is_safe():
    assert config.every_single_node_change_is_safe_on_its_own()["none_are_unsafe"]


def test_it_holds_when_removing_too():
    assert config.every_single_node_change_is_safe_on_its_own()[
        "and_it_holds_in_both_directions"
    ]


def test_the_usual_justification_is_wrong():
    assert config.every_single_node_change_is_safe_on_its_own()[
        "so_the_usual_justification_is_wrong"
    ]


def test_the_search_covered_seven_sizes():
    assert config.every_single_node_change_is_safe_on_its_own()["sizes_checked"] == 7


def test_each_overlapping_change_is_safe_alone():
    assert config.two_overlapping_changes_are_unsafe()["each_one_alone_is_safe"]


def test_two_overlapping_changes_are_not():
    assert config.two_overlapping_changes_are_unsafe()["but_together_they_are_not"]


def test_the_overlapping_example_is_shown():
    assert config.two_overlapping_changes_are_unsafe()["an_example"]


def test_the_overlap_is_two_leaders():
    assert config.two_overlapping_changes_are_unsafe()["which_is_two_leaders_in_one_term"]


def test_a_plain_change_can_have_disjoint_pairs():
    assert config.a_joint_configuration_has_no_disjoint_majorities()[
        "the_plain_change_had_some"
    ]


def test_a_joint_configuration_has_none():
    assert config.a_joint_configuration_has_no_disjoint_majorities()[
        "and_the_joint_one_has_none"
    ]


def test_every_joint_deciding_set_holds_the_old_majority():
    assert config.a_joint_configuration_has_no_disjoint_majorities()[
        "every_deciding_set_holds_the_old_majority"
    ]


def test_neither_side_alone_decides():
    assert config.a_joint_quorum_needs_both_sides()["neither_side_alone_decides"]


def test_both_sides_together_decide():
    assert config.a_joint_quorum_needs_both_sides()["and_both_together_do"]


def test_a_steady_configuration_uses_one_majority():
    assert config.a_steady_configuration_needs_one_majority()["two_of_three_decide"]


def test_a_steady_minority_does_not_decide():
    assert config.a_steady_configuration_needs_one_majority()["one_of_three_does_not"]


def test_a_steady_configuration_is_not_joint():
    assert config.a_steady_configuration_needs_one_majority()["it_is_not_joint"]


def test_a_change_starts_steady():
    assert config.a_change_passes_through_three_stages()["it_starts_steady"]


def test_a_change_goes_joint():
    assert config.a_change_passes_through_three_stages()["goes_joint"]


def test_a_change_settles():
    assert config.a_change_passes_through_three_stages()["and_settles"]


def test_the_old_membership_is_remembered_during_the_change():
    assert config.a_change_passes_through_three_stages()["the_old_membership_is_remembered"]


def test_the_old_membership_is_forgotten_afterwards():
    assert config.a_change_passes_through_three_stages()["and_forgotten_afterwards"]


def test_a_removed_node_runs_ahead():
    assert config.a_removed_node_keeps_standing_for_election()["it_ran_ahead"]


def test_a_removed_node_deposes_the_leader():
    assert config.a_removed_node_keeps_standing_for_election()["and_stepped_down"]


def test_joint_consensus_does_not_fix_that():
    assert config.a_removed_node_keeps_standing_for_election()[
        "which_joint_consensus_does_not_fix"
    ]


def test_a_configuration_change_is_a_log_entry():
    assert config.a_configuration_change_is_a_log_entry()["it_is_an_ordinary_entry"]


def test_the_change_entry_names_its_members():
    assert config.a_configuration_change_is_a_log_entry()["its_command_names_the_members"]


def test_adding_a_member_twice_is_refused():
    assert config.adding_a_member_twice_is_refused()


def test_removing_an_absent_member_is_refused():
    assert config.removing_an_absent_member_is_refused()


def test_removing_the_last_member_is_refused():
    assert config.removing_the_last_member_is_refused()


def test_an_empty_configuration_is_refused():
    assert config.an_empty_configuration_is_refused()


def test_a_repeated_member_is_refused():
    assert config.a_repeated_member_is_refused()


def test_election_safety_is_raised_not_returned():
    assert config.two_leaders_in_one_term_is_a_violation()


def test_the_change_table_covers_seven_sizes():
    assert len(config.compare_the_changes()) == 7


def test_no_size_is_unsafe():
    assert config.no_size_makes_a_single_change_unsafe()["nothing_is_unsafe"]


def test_the_danger_is_concurrency():
    assert config.no_size_makes_a_single_change_unsafe()["the_danger_is_concurrency_not_size"]


def test_the_summary_says_single_changes_are_safe():
    assert config.summarise()["every_single_change_is_safe_alone"]


def test_the_summary_says_two_at_once_are_not():
    assert config.summarise()["but_two_at_once_are_not"]


def test_a_configuration_lists_its_members():
    assert Configuration(members=("a", "b")).members == ("a", "b")


def test_a_steady_configuration_has_no_old_membership():
    assert Configuration(members=("a", "b")).old == ()


def test_a_steady_configuration_reports_its_stage():
    assert Configuration(members=("a", "b")).stage == STEADY


def test_a_joint_configuration_reports_its_stage():
    assert Configuration(members=("a", "b"), old=("a",)).stage == JOINT


def test_a_steady_configuration_voters_are_its_members():
    made = Configuration(members=("a", "b", "c"))
    assert made.voters == made.members


def test_a_joint_configuration_voters_are_the_union():
    made = Configuration(members=("b", "c"), old=("a", "b"))
    assert set(made.voters) == {"a", "b", "c"}


def test_a_configuration_summarises():
    assert Configuration(members=("a", "b")).as_dict()["stage"] == STEADY


def test_adding_a_member_gives_a_joint_configuration():
    assert Configuration(members=("a", "b")).with_member("c").joint


def test_adding_a_member_keeps_the_old_membership():
    made = Configuration(members=("a", "b")).with_member("c")
    assert made.old == ("a", "b")


def test_adding_a_member_grows_the_new_one():
    made = Configuration(members=("a", "b")).with_member("c")
    assert made.members == ("a", "b", "c")


def test_removing_a_member_shrinks_the_new_one():
    made = Configuration(members=("a", "b", "c")).without_member("b")
    assert made.members == ("a", "c")


def test_settling_drops_the_old_membership():
    made = Configuration(members=("a", "b"), old=("a",)).settled()
    assert made.old == ()


def test_settling_keeps_the_new_membership():
    made = Configuration(members=("a", "b"), old=("a",)).settled()
    assert made.members == ("a", "b")


def test_a_majority_of_three_decides():
    assert Configuration(members=("a", "b", "c")).quorum({"a", "b"})


def test_a_minority_of_three_does_not():
    assert not Configuration(members=("a", "b", "c")).quorum({"a"})


def test_an_empty_vote_set_decides_nothing():
    assert not Configuration(members=("a", "b", "c")).quorum(set())


def test_an_outsider_does_not_count():
    assert not Configuration(members=("a", "b", "c")).quorum({"a", "z"})


def test_adding_an_existing_member_raises():
    with pytest.raises(ConfigError):
        Configuration(members=("a",)).with_member("a")


def test_removing_a_stranger_raises():
    with pytest.raises(ConfigError):
        Configuration(members=("a", "b")).without_member("z")


def test_an_empty_membership_raises():
    with pytest.raises(ConfigError):
        Configuration(members=())


def test_two_identical_memberships_have_no_disjoint_majorities():
    assert disjoint_majorities(("a", "b", "c"), ("a", "b", "c")) == []


def test_two_separate_memberships_do():
    assert disjoint_majorities(("a", "b", "c"), ("x", "y", "z")) != []


def test_there_are_three_stages():
    assert len(STAGES) == 3
