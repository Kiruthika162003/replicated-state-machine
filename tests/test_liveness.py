from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.node import MAX_ELECTION_TIMEOUT
from rsm.verify import liveness as live
from rsm.verify.liveness import (
    COMMIT_BOUND,
    ELECTION_BOUND,
    LEADER_ELECTED,
    PATIENCE,
    PROPERTIES,
    Observation,
    Property,
    a_follower_catches_up,
    a_leader_is_elected,
    a_write_commits,
    under_a_partition,
)


def test_every_property_holds_on_a_healthy_cluster():
    made = live.every_bounded_property_holds_on_a_healthy_cluster()
    assert made["all_held"]


def test_every_margin_is_positive():
    made = live.every_bounded_property_holds_on_a_healthy_cluster()
    assert made["every_margin_is_positive"]


def test_the_tightest_property_still_had_room():
    made = live.every_bounded_property_holds_on_a_healthy_cluster()
    assert made["and_it_still_had_room"]


def test_no_run_length_elected_a_leader():
    made = live.a_liveness_property_cannot_be_falsified_by_a_finite_run()
    assert made["none_of_them_elected"]


def test_the_answer_never_changed():
    assert live.a_liveness_property_cannot_be_falsified_by_a_finite_run()[
        "and_the_answer_never_changed"
    ]


def test_watching_longer_told_us_nothing():
    assert live.a_liveness_property_cannot_be_falsified_by_a_finite_run()[
        "watching_longer_told_us_nothing"
    ]


def test_the_longest_run_passed_the_bound():
    assert live.a_liveness_property_cannot_be_falsified_by_a_finite_run()[
        "which_the_longest_run_passed_long_ago"
    ]


def test_a_partitioned_cluster_never_elects():
    assert live.the_correct_implementation_violates_liveness_under_a_partition()[
        "it_never_elected"
    ]


def test_the_condition_failed_under_a_partition():
    assert live.the_correct_implementation_violates_liveness_under_a_partition()[
        "the_condition_failed"
    ]


def test_a_failed_condition_is_still_truthy():
    assert live.the_correct_implementation_violates_liveness_under_a_partition()[
        "and_it_is_still_truthy"
    ]


def test_a_healthy_run_did_elect():
    made = live.the_correct_implementation_violates_liveness_under_a_partition()
    assert made["which_did_elect"]


def test_most_elections_fit_one_timeout():
    assert live.the_election_bound_comes_from_the_timers_and_not_from_a_guess()[
        "most_are_inside_one_timeout"
    ]


def test_not_every_election_does():
    assert live.the_election_bound_comes_from_the_timers_and_not_from_a_guess()[
        "but_not_all_of_them"
    ]


def test_every_election_fits_the_bound():
    assert live.the_election_bound_comes_from_the_timers_and_not_from_a_guess()[
        "every_one_inside"
    ]


def test_the_bound_has_room_for_a_retry():
    assert live.the_election_bound_comes_from_the_timers_and_not_from_a_guess()[
        "so_the_bound_has_room_for_a_retry"
    ]


def test_loss_costs_more_ticks():
    made = live.loss_makes_the_wait_longer_and_keeps_it_inside_the_bound()
    assert made["loss_costs_more"]


def test_loss_stays_inside_the_bound():
    assert live.loss_makes_the_wait_longer_and_keeps_it_inside_the_bound()[
        "and_it_is_still_inside"
    ]


def test_the_lossy_margin_is_thin():
    assert live.loss_makes_the_wait_longer_and_keeps_it_inside_the_bound()[
        "which_is_almost_nothing"
    ]


def test_a_property_without_a_bound_is_refused():
    assert live.a_property_without_a_bound_is_refused()


def test_a_property_without_a_name_is_refused():
    assert live.a_property_without_a_name_is_refused()


def test_the_verdict_flips_at_the_bound():
    assert live.an_observation_past_its_bound_is_falsy()["it_flips_at_the_boundary"]


def test_both_sides_of_the_bound_happened():
    assert live.an_observation_past_its_bound_is_falsy()["and_both_of_them_happened"]


def test_only_the_condition_separates_the_last_two():
    assert live.an_observation_past_its_bound_is_falsy()[
        "and_they_differ_only_in_the_condition"
    ]


def test_the_property_table_covers_four_rows():
    assert len(live.compare_the_properties()) == 4


def test_without_a_bound_the_partition_passes():
    assert live.liveness_needs_a_bound_and_a_condition_and_neither_alone_is_enough()[
        "without_a_bound_the_partition_passes"
    ]


def test_without_a_condition_it_fails():
    assert live.liveness_needs_a_bound_and_a_condition_and_neither_alone_is_enough()[
        "without_a_condition_it_fails"
    ]


def test_with_both_it_is_excused():
    assert live.liveness_needs_a_bound_and_a_condition_and_neither_alone_is_enough()[
        "and_with_both_it_is_excused"
    ]


def test_the_summary_lists_the_properties():
    assert live.summarise()["properties"] == [one.name for one in PROPERTIES]


def test_the_summary_says_a_partition_excuses_them():
    assert live.summarise()["a_partition_excuses_them"]


def test_a_property_reports_itself():
    assert Property(name="x", bound=5).as_dict()["bound"] == 5


def test_a_property_prints_its_condition():
    assert "while" in str(Property(name="x", bound=5))


def test_a_property_carries_a_condition_by_default():
    assert Property(name="x", bound=5).condition


def test_a_zero_bound_raises():
    with pytest.raises(ConfigError):
        Property(name="x", bound=0)


def test_an_unnamed_property_raises():
    with pytest.raises(ConfigError):
        Property(name="", bound=5)


def test_an_observation_inside_the_bound_is_truthy():
    assert Observation(claim=LEADER_ELECTED, waited=5, happened=True)


def test_an_observation_outside_it_is_falsy():
    assert not Observation(claim=LEADER_ELECTED, waited=ELECTION_BOUND + 1, happened=True)


def test_an_observation_that_never_happened_is_falsy():
    assert not Observation(claim=LEADER_ELECTED, waited=5, happened=False)


def test_an_excused_observation_is_truthy():
    made = Observation(claim=LEADER_ELECTED, waited=999, happened=False, conditional=False)
    assert made


def test_an_observation_reports_its_margin():
    made = Observation(claim=LEADER_ELECTED, waited=10, happened=True)
    assert made.margin == ELECTION_BOUND - 10


def test_a_late_observation_has_a_negative_margin():
    made = Observation(claim=LEADER_ELECTED, waited=ELECTION_BOUND + 3, happened=True)
    assert made.margin == -3


def test_an_observation_summarises():
    made = Observation(claim=LEADER_ELECTED, waited=1, happened=True)
    assert made.as_dict()["property"] == LEADER_ELECTED.name


def test_an_observation_prints_when_it_happened():
    made = Observation(claim=LEADER_ELECTED, waited=7, happened=True)
    assert "7" in str(made)


def test_an_observation_that_never_happened_says_so():
    made = Observation(claim=LEADER_ELECTED, waited=7, happened=False)
    assert "never" in str(made)


def test_an_excused_observation_says_nothing_is_claimed():
    made = Observation(claim=LEADER_ELECTED, waited=7, happened=False, conditional=False)
    assert "nothing is claimed" in str(made)


def test_a_leader_is_elected_after_a_crash():
    assert a_leader_is_elected(size=3, seed=2).happened


def test_a_leader_is_present_without_a_crash():
    assert a_leader_is_elected(size=3, seed=2, kill=False).waited <= 1


def test_a_write_commits_quickly():
    assert a_write_commits(size=3, seed=2).waited <= COMMIT_BOUND


def test_a_follower_catches_up_after_missing_everything():
    assert a_follower_catches_up(size=3, seed=2, writes=10).happened


def test_a_partitioned_cluster_is_excused():
    assert under_a_partition(size=3, seed=2, patience=60)


def test_a_partitioned_cluster_elects_nobody():
    assert not under_a_partition(size=3, seed=2, patience=60).happened


def test_the_election_bound_is_two_timeouts():
    assert ELECTION_BOUND == MAX_ELECTION_TIMEOUT * 2


def test_the_commit_bound_is_small():
    assert COMMIT_BOUND < ELECTION_BOUND


def test_the_patience_outlasts_every_bound():
    assert max(one.bound for one in PROPERTIES) < PATIENCE


def test_there_are_three_properties():
    assert len(PROPERTIES) == 3
