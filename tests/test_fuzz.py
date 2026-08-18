from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.node import Node
from rsm.verify import fuzz
from rsm.verify.faults import Fault, Schedule, random_schedule
from rsm.verify.fuzz import (
    BUDGET,
    DEFECTS,
    Broken,
    Defect,
    Failure,
    IgnoresTheLog,
    VotesTwice,
    attempt,
    search,
    shrink,
)


def test_the_sound_implementation_survives():
    assert fuzz.the_sound_implementation_survives_the_whole_budget()["nothing_broke"]


def test_the_sound_search_used_its_budget():
    assert fuzz.the_sound_implementation_survives_the_whole_budget()["runs"] == BUDGET


def test_the_sound_schedules_carried_faults():
    assert fuzz.the_sound_implementation_survives_the_whole_budget()[
        "and_the_schedules_were_real"
    ]


def test_the_wide_defects_are_found_quickly():
    assert fuzz.the_two_wide_defects_are_caught_in_a_handful_of_seeds()["both_found_quickly"]


def test_the_wide_defects_are_real_failures():
    assert fuzz.the_two_wide_defects_are_caught_in_a_handful_of_seeds()["both_are_failures"]


def test_the_log_defect_breaks_state_machine_safety():
    made = fuzz.the_two_wide_defects_are_caught_in_a_handful_of_seeds()
    assert "state machine safety" in made["and_broke"]


def test_the_double_vote_breaks_election_safety():
    made = fuzz.the_two_wide_defects_are_caught_in_a_handful_of_seeds()
    assert "election safety" in made["and_broke_this"]


def test_the_narrow_defects_are_missed():
    assert fuzz.the_two_narrow_defects_are_invisible_to_fault_injection()["neither_was_found"]


def test_the_narrow_search_ran_every_schedule():
    assert (
        fuzz.the_two_narrow_defects_are_invisible_to_fault_injection()["schedules_run"] == 500
    )


def test_the_narrow_defects_are_message_ordering_bugs():
    made = fuzz.the_two_narrow_defects_are_invisible_to_fault_injection()
    assert made["what_decides_these_two"] == "which message arrives first"


def test_jitter_does_not_expose_the_narrow_defects():
    assert fuzz.neither_jitter_nor_loss_helps_find_them()[
        "the_narrow_ones_are_missed_everywhere"
    ]


def test_the_wide_defect_is_found_under_every_condition():
    assert fuzz.neither_jitter_nor_loss_helps_find_them()["the_wide_one_is_found_everywhere"]


def test_the_search_works_and_lacks_direction():
    assert fuzz.neither_jitter_nor_loss_helps_find_them()[
        "so_the_search_works_and_lacks_direction"
    ]


def test_shrinking_drops_faults():
    assert fuzz.shrinking_turns_six_faults_into_two()["it_dropped_faults"]


def test_shrinking_shortens_the_run():
    assert fuzz.shrinking_turns_six_faults_into_two()["and_shortened_the_run"]


def test_the_shrunk_schedule_still_fails():
    assert fuzz.shrinking_turns_six_faults_into_two()["it_still_fails"]


def test_the_shrunk_schedule_fails_the_same_way():
    assert fuzz.shrinking_turns_six_faults_into_two()["and_fails_the_same_way"]


def test_the_reproduction_is_readable():
    assert len(fuzz.shrinking_turns_six_faults_into_two()["reproduction"]) <= 3


def test_shrinking_can_remove_every_fault():
    assert fuzz.shrinking_can_remove_the_faults_entirely()["it_needs_no_faults"]


def test_the_faultless_reproduction_still_fails():
    assert fuzz.shrinking_can_remove_the_faults_entirely()["it_still_fails"]


def test_the_faultless_reproduction_is_election_safety():
    assert fuzz.shrinking_can_remove_the_faults_entirely()["and_it_is_election_safety"]


def test_a_healthy_cluster_is_enough_for_the_double_vote():
    assert fuzz.shrinking_can_remove_the_faults_entirely()["so_a_healthy_cluster_is_enough"]


def test_every_shrink_still_fails():
    assert fuzz.a_shrunk_schedule_always_still_fails()["every_shrink_still_fails"]


def test_every_shrink_matches_the_original():
    assert fuzz.a_shrunk_schedule_always_still_fails()["and_matches_the_original"]


def test_every_shrink_is_smaller():
    assert fuzz.a_shrunk_schedule_always_still_fails()["and_is_smaller"]


def test_shrinking_costs_less_than_the_budget():
    assert fuzz.shrinking_costs_less_than_the_search_that_found_it()[
        "shrinking_costs_less_than_the_budget"
    ]


def test_shrinking_costs_more_than_the_lucky_seed():
    assert fuzz.shrinking_costs_less_than_the_search_that_found_it()[
        "but_more_than_the_lucky_seed"
    ]


def test_shrinking_repeats_exactly():
    assert fuzz.shrinking_is_deterministic()["they_are_identical"]


def test_the_repeated_shrink_is_a_real_failure():
    assert fuzz.shrinking_is_deterministic()["and_it_is_a_real_failure"]


def test_the_live_check_caught_both():
    assert fuzz.the_live_check_and_the_history_check_agreed_on_everything()[
        "the_live_check_caught_both"
    ]


def test_the_history_caught_both():
    assert fuzz.the_live_check_and_the_history_check_agreed_on_everything()[
        "and_so_did_the_history"
    ]


def test_the_two_checkers_agreed():
    assert fuzz.the_live_check_and_the_history_check_agreed_on_everything()[
        "they_agreed_everywhere"
    ]


def test_the_defects_broke_different_properties():
    assert fuzz.the_live_check_and_the_history_check_agreed_on_everything()[
        "the_properties_differ"
    ]


def test_a_defect_that_removes_nothing_is_refused():
    assert fuzz.a_defect_that_removes_nothing_is_refused()


def test_a_defect_without_a_name_is_refused():
    assert fuzz.a_defect_without_a_name_is_refused()


def test_a_search_with_no_budget_is_refused():
    assert fuzz.a_search_with_no_budget_is_refused()


def test_shrinking_a_passing_run_is_refused():
    assert fuzz.shrinking_a_run_that_passed_is_refused()


def test_the_broken_cluster_keeps_the_refusals():
    assert fuzz.restarting_a_running_node_is_still_refused()


def test_the_defect_table_covers_them_all():
    assert len(fuzz.compare_the_defects()) == len(DEFECTS)


def test_half_the_defects_were_found():
    assert fuzz.half_the_defects_are_found_and_the_famous_ones_are_not()["half_were_found"]


def test_the_sound_defect_stayed_clean():
    assert fuzz.half_the_defects_are_found_and_the_famous_ones_are_not()[
        "the_sound_one_stayed_clean"
    ]


def test_the_missed_defects_are_the_ordering_ones():
    assert fuzz.half_the_defects_are_found_and_the_famous_ones_are_not()[
        "and_the_missed_ones_are_the_message_ordering_ones"
    ]


def test_the_summary_says_the_narrow_defects_are_missed():
    assert fuzz.summarise()["the_narrow_defects_are_missed"]


def test_the_summary_says_shrinking_is_deterministic():
    assert fuzz.summarise()["shrinking_is_deterministic"]


def test_the_summary_counts_the_defects():
    assert fuzz.summarise()["defects"] == len(DEFECTS) - 1


def test_a_defect_summarises():
    assert DEFECTS["ignores the log"].as_dict()["defect"] == "ignores the log"


def test_a_defect_reports_its_class():
    assert DEFECTS["ignores the log"].as_dict()["class"] == "IgnoresTheLog"


def test_a_defect_without_a_class_reports_the_plain_node():
    assert DEFECTS["commits any term"].as_dict()["class"] == "Node"


def test_a_defect_with_no_rule_removed_raises():
    with pytest.raises(ConfigError):
        Defect(name="x")


def test_an_unnamed_defect_raises():
    with pytest.raises(ConfigError):
        Defect(name="", commit_any_term=True)


def test_a_broken_cluster_uses_the_defect_class():
    made = Broken(defect=DEFECTS["ignores the log"], size=3, seed=0)
    assert isinstance(made.nodes["n0"], IgnoresTheLog)


def test_a_sound_cluster_uses_the_plain_node():
    made = Broken(defect=DEFECTS["sound"], size=3, seed=0)
    assert type(made.nodes["n0"]) is Node


def test_a_broken_cluster_carries_the_commit_flag():
    made = Broken(defect=DEFECTS["commits any term"], size=3, seed=0)
    assert made.nodes["n0"].commit_any_term


def test_a_restart_keeps_the_defect():
    made = Broken(defect=DEFECTS["votes twice"], size=3, seed=0).settle()
    made.crash("n1")
    made.restart("n1")
    assert isinstance(made.nodes["n1"], VotesTwice)


def test_a_forgetful_restart_drops_the_vote():
    made = Broken(defect=DEFECTS["forgets the vote"], size=3, seed=0).settle()
    made.nodes["n1"].voted_for = "n0"
    made.crash("n1")
    made.restart("n1")
    assert made.nodes["n1"].voted_for is None


def test_an_ordinary_restart_keeps_the_vote():
    made = Broken(defect=DEFECTS["sound"], size=3, seed=0).settle()
    made.nodes["n1"].voted_for = "n0"
    made.crash("n1")
    made.restart("n1")
    assert made.nodes["n1"].voted_for == "n0"


def test_restarting_a_running_node_raises():
    made = Broken(defect=DEFECTS["sound"], size=3, seed=0)
    with pytest.raises(ConfigError):
        made.restart("n0")


def test_a_failure_with_nothing_broken_is_falsy():
    made = Failure(schedule=random_schedule(seed=0), defect=DEFECTS["sound"], properties=())
    assert not made


def test_a_failure_with_a_property_is_truthy():
    made = Failure(
        schedule=random_schedule(seed=0),
        defect=DEFECTS["sound"],
        properties=("election safety",),
    )
    assert made


def test_a_failure_with_only_a_raise_is_truthy():
    made = Failure(
        schedule=random_schedule(seed=0),
        defect=DEFECTS["sound"],
        properties=(),
        raised="ElectionSafety",
    )
    assert made


def test_a_failure_reports_its_size():
    made = Failure(
        schedule=Schedule(seed=0, ticks=50, faults=[Fault(kind="crash", at=5, target="n0")]),
        defect=DEFECTS["sound"],
        properties=("election safety",),
    )
    assert made.size == 150


def test_a_failure_summarises():
    made = Failure(
        schedule=random_schedule(seed=7),
        defect=DEFECTS["sound"],
        properties=("election safety",),
    )
    assert made.as_dict()["seed"] == 7


def test_a_failure_prints_what_broke():
    made = Failure(
        schedule=random_schedule(seed=7),
        defect=DEFECTS["votes twice"],
        properties=("election safety",),
    )
    assert "election safety" in str(made)


def test_a_passing_failure_prints_that_nothing_broke():
    made = Failure(schedule=random_schedule(seed=7), defect=DEFECTS["sound"], properties=())
    assert "nothing broke" in str(made)


def test_attempting_a_sound_schedule_finds_nothing():
    assert not attempt(random_schedule(seed=0, ticks=120), DEFECTS["sound"])


def test_attempting_a_broken_schedule_finds_something():
    found = search(DEFECTS["ignores the log"], budget=20)
    assert found


def test_a_search_reports_how_many_seeds_it_used():
    assert search(DEFECTS["ignores the log"], budget=20).runs >= 1


def test_a_search_that_finds_nothing_returns_the_last_run():
    found = search(DEFECTS["sound"], budget=5)
    assert not found and found.runs == 5


def test_a_search_with_a_zero_budget_raises():
    with pytest.raises(ConfigError):
        search(DEFECTS["sound"], budget=0)


def test_shrinking_a_passing_failure_raises():
    with pytest.raises(ConfigError):
        shrink(
            Failure(schedule=random_schedule(seed=0), defect=DEFECTS["sound"], properties=())
        )


def test_shrinking_respects_the_floor():
    found = search(DEFECTS["votes twice"], budget=BUDGET)
    assert shrink(found, floor=100).schedule.ticks >= 100


def test_a_higher_floor_gives_a_longer_reproduction():
    found = search(DEFECTS["votes twice"], budget=BUDGET)
    assert shrink(found, floor=100).schedule.ticks > shrink(found, floor=30).schedule.ticks


def test_the_defect_names_match_their_keys():
    assert all(name == one.name for name, one in DEFECTS.items())


def test_the_budget_is_worth_running():
    assert BUDGET >= 100
