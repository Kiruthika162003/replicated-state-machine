from __future__ import annotations

import pytest

from rsm import learner as staging
from rsm.errors import ConfigError
from rsm.learner import CLOSE_ENOUGH, LEARNER, ROLES, VOTER, Roster


def test_a_direct_add_raises_the_quorum():
    assert staging.adding_a_voter_raises_the_quorum_before_it_can_help()["it_went_up"]


def test_a_direct_add_tolerates_no_more():
    assert staging.adding_a_voter_raises_the_quorum_before_it_can_help()[
        "and_it_tolerates_no_more"
    ]


def test_a_learner_leaves_the_quorum_alone():
    assert staging.adding_a_voter_raises_the_quorum_before_it_can_help()[
        "which_a_learner_leaves_alone"
    ]


def test_a_learner_holds_every_entry():
    assert staging.a_learner_receives_the_log_and_does_not_vote()["it_holds_every_entry"]


def test_a_learner_is_flagged_as_one():
    assert staging.a_learner_receives_the_log_and_does_not_vote()["it_is_a_learner"]


def test_a_learner_is_not_counted():
    assert staging.a_learner_receives_the_log_and_does_not_vote()["and_it_is_not_counted"]


def test_promotion_moves_the_quorum_once():
    assert staging.promoting_a_caught_up_learner_costs_one_quorum_change()["it_changed_once"]


def test_promotion_makes_a_voter():
    assert staging.promoting_a_caught_up_learner_costs_one_quorum_change()[
        "the_learner_became_a_voter"
    ]


def test_promotion_leaves_no_learners():
    assert staging.promoting_a_caught_up_learner_costs_one_quorum_change()[
        "and_there_are_no_learners_left"
    ]


def test_promotion_keeps_the_membership():
    assert staging.promoting_a_caught_up_learner_costs_one_quorum_change()["members_unchanged"]


def test_the_catch_up_grows_with_the_log():
    assert staging.the_gap_is_as_long_as_the_catch_up()["it_grows_with_the_log"]


def test_a_short_log_is_one_append():
    assert staging.the_gap_is_as_long_as_the_catch_up()["a_short_log_is_one_append"]


def test_a_long_log_takes_several():
    assert staging.the_gap_is_as_long_as_the_catch_up()["and_a_long_one_is_this_many"] > 4


def test_a_close_learner_is_cheap_to_promote():
    assert staging.a_learner_close_to_the_leader_is_cheap_to_promote()["it_is_close_enough"]


def test_a_far_learner_is_not():
    assert staging.a_learner_close_to_the_leader_is_cheap_to_promote()[
        "and_the_other_one_is_not"
    ]


def test_a_learner_is_not_among_the_voters():
    assert staging.a_learner_never_wins_an_election_it_should_not_be_in()[
        "it_is_not_among_them"
    ]


def test_the_quorum_counts_only_voters():
    assert staging.a_learner_never_wins_an_election_it_should_not_be_in()[
        "which_counts_only_voters"
    ]


def test_learners_do_not_change_the_quorum():
    assert staging.a_learner_does_not_change_what_the_cluster_tolerates()["it_is_unchanged"]


def test_learners_do_not_change_what_is_tolerated():
    assert staging.a_learner_does_not_change_what_the_cluster_tolerates()["and_so_is_that"]


def test_seven_copies_still_tolerate_one_failure():
    assert staging.a_learner_does_not_change_what_the_cluster_tolerates()[
        "seven_copies_one_failure"
    ]


def test_one_promotion_at_a_time_is_safe():
    assert staging.promoting_two_learners_at_once_is_the_membership_problem_again()[
        "it_is_safe"
    ]


def test_two_promotions_at_once_are_not():
    assert staging.promoting_two_learners_at_once_is_the_membership_problem_again()[
        "and_the_leap_is_not"
    ]


def test_promotion_keeps_the_log():
    assert staging.a_learner_that_is_promoted_keeps_its_log()["the_log_is_untouched"]


def test_promotion_only_changes_the_roster():
    assert staging.a_learner_that_is_promoted_keeps_its_log()["only_the_roster_changed"]


def test_the_promoted_node_matches_the_leader():
    assert staging.a_learner_that_is_promoted_keeps_its_log()["and_it_matches_the_leader"]


def test_a_roster_with_no_voters_is_refused():
    assert staging.a_roster_with_no_voters_is_refused()


def test_a_node_that_is_both_is_refused():
    assert staging.a_node_that_is_both_is_refused()


def test_promoting_a_voter_is_refused():
    assert staging.promoting_a_voter_is_refused()


def test_adding_an_existing_node_is_refused():
    assert staging.adding_an_existing_node_as_a_learner_is_refused()


def test_asking_about_a_stranger_is_refused():
    assert staging.asking_about_a_stranger_is_refused()


def test_the_joining_table_covers_seven_sizes():
    assert len(staging.compare_the_joining_paths()) == 7


def test_a_direct_add_does_not_always_raise_the_quorum():
    assert staging.joining_as_a_learner_never_raises_the_quorum_early()[
        "it_does_not_always_raise_it"
    ]


def test_the_sizes_that_pay_are_odd():
    assert staging.joining_as_a_learner_never_raises_the_quorum_early()[
        "the_ones_that_pay_are_odd"
    ]


def test_the_free_sizes_are_even():
    assert staging.joining_as_a_learner_never_raises_the_quorum_early()[
        "and_the_free_ones_are_even"
    ]


def test_the_learner_path_never_raises_it():
    assert staging.joining_as_a_learner_never_raises_the_quorum_early()[
        "the_learner_path_never_raises_it"
    ]


def test_the_summary_says_a_learner_is_not_counted():
    assert staging.summarise()["and_is_not_counted"]


def test_the_summary_says_a_learner_never_raises_it():
    assert staging.summarise()["but_a_learner_never_raises_it"]


def test_a_roster_lists_its_members():
    made = Roster(voters=("a", "b"), learners=("c",))
    assert made.members == ("a", "b", "c")


def test_a_roster_reports_its_quorum():
    assert Roster(voters=("a", "b", "c", "d", "e")).quorum == 3


def test_learners_do_not_count_towards_the_quorum():
    assert Roster(voters=("a", "b", "c"), learners=("d", "e")).quorum == 2


def test_a_voter_reports_its_role():
    assert Roster(voters=("a",)).role("a") == VOTER


def test_a_learner_reports_its_role():
    assert Roster(voters=("a",), learners=("b",)).role("b") == LEARNER


def test_promoting_moves_a_name_across():
    made = Roster(voters=("a",), learners=("b",)).promote("b")
    assert made.voters == ("a", "b") and made.learners == ()


def test_adding_a_learner_leaves_the_voters():
    made = Roster(voters=("a", "b")).with_learner("c")
    assert made.voters == ("a", "b")


def test_adding_a_learner_extends_the_learners():
    made = Roster(voters=("a", "b")).with_learner("c")
    assert made.learners == ("c",)


def test_a_roster_summarises():
    assert Roster(voters=("a", "b"), learners=("c",)).as_dict()["members"] == 3


def test_an_empty_voter_list_raises():
    with pytest.raises(ConfigError):
        Roster(voters=())


def test_an_overlapping_roster_raises():
    with pytest.raises(ConfigError):
        Roster(voters=("a",), learners=("a",))


def test_a_repeated_voter_raises():
    with pytest.raises(ConfigError):
        Roster(voters=("a", "a"))


def test_promoting_a_stranger_raises():
    with pytest.raises(ConfigError):
        Roster(voters=("a",)).promote("z")


def test_a_stranger_has_no_role():
    with pytest.raises(ConfigError):
        Roster(voters=("a",)).role("z")


def test_there_are_two_roles():
    assert len(ROLES) == 2


def test_the_closeness_threshold_is_small():
    assert CLOSE_ENOUGH <= 5
