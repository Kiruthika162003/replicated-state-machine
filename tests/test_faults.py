from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.net import Conditions
from rsm.verify import faults as injection
from rsm.verify.faults import (
    CRASH,
    HEAL,
    KINDS,
    PARTITION,
    RESTART,
    Fault,
    Schedule,
    random_schedule,
    run,
)


def test_a_schedule_replays_exactly():
    assert injection.a_schedule_replays_exactly()["they_are_identical"]


def test_the_replay_found_one_outcome():
    assert injection.a_schedule_replays_exactly()["distinct_outcomes"] == 1


def test_an_inert_crash_is_counted_separately():
    assert injection.a_fault_that_fires_into_a_dead_node_does_nothing()["only_two_did_anything"]


def test_the_inert_schedule_looked_bigger():
    assert injection.a_fault_that_fires_into_a_dead_node_does_nothing()[
        "and_the_schedule_looked_like_five"
    ]


def test_the_inert_exposure_is_two_fifths():
    assert injection.a_fault_that_fires_into_a_dead_node_does_nothing()["exposure"] == 0.4


def test_an_inert_heal_is_counted_separately():
    assert injection.a_heal_with_no_partition_does_nothing()["two_did_something"]


def test_the_inert_heal_exposure_is_a_half():
    assert injection.a_heal_with_no_partition_does_nothing()["exposure"] == 0.5


def test_generated_schedules_mostly_land():
    assert injection.a_well_formed_schedule_has_high_exposure()["most_faults_land"]


def test_in_fact_every_generated_fault_lands():
    assert injection.a_well_formed_schedule_has_high_exposure()["in_fact_all_of_them_do"]


def test_the_exposure_improved_on_the_first_version():
    made = injection.a_well_formed_schedule_has_high_exposure()
    assert made["mean_exposure"] > made["against_this_before_the_fix"]


def test_every_generated_schedule_is_safe():
    assert injection.every_generated_schedule_stays_safe()["they_are_all_safe"]


def test_no_generated_schedule_breached_anything():
    assert injection.every_generated_schedule_stays_safe()["breaches"] == 0


def test_the_generated_faults_were_real():
    assert injection.every_generated_schedule_stays_safe()["and_the_faults_were_real"]


def test_the_generated_schedules_committed_something():
    assert injection.every_generated_schedule_stays_safe()["committed_total"] > 100


def test_faults_cost_commits():
    assert injection.faults_cost_availability_and_not_safety()["faults_cost_commits"]


def test_faults_cost_no_safety():
    assert injection.faults_cost_availability_and_not_safety()["and_safety_is_unaffected"]


def test_both_fault_conditions_are_safe():
    assert injection.faults_cost_availability_and_not_safety()["both_are_safe"]


def test_loss_costs_commits_too():
    assert injection.a_lossy_link_is_a_fault_the_schedule_does_not_have_to_name()[
        "loss_costs_commits"
    ]


def test_loss_is_not_in_the_fault_list():
    assert injection.a_lossy_link_is_a_fault_the_schedule_does_not_have_to_name()[
        "and_it_is_not_in_the_fault_list"
    ]


def test_a_lossy_run_is_still_safe():
    assert injection.a_lossy_link_is_a_fault_the_schedule_does_not_have_to_name()[
        "both_are_safe"
    ]


def test_a_schedule_names_its_seed():
    assert injection.a_schedule_is_a_bug_report()["it_names_the_seed"]


def test_a_schedule_names_its_size():
    assert injection.a_schedule_is_a_bug_report()["and_the_size"]


def test_a_schedule_names_every_fault():
    assert injection.a_schedule_is_a_bug_report()["and_every_fault"]


def test_a_schedule_prints_on_one_line():
    assert injection.a_schedule_is_a_bug_report()["in_one_line"]


def test_a_clean_outcome_is_truthy():
    assert injection.an_outcome_of_a_broken_run_is_falsy()["a_clean_outcome_is_truthy"]


def test_a_broken_outcome_is_falsy():
    assert injection.an_outcome_of_a_broken_run_is_falsy()["and_a_broken_one_is_falsy"]


def test_a_fault_after_the_end_is_refused():
    assert injection.a_fault_after_the_end_is_refused()


def test_an_unknown_fault_kind_is_refused():
    assert injection.a_fault_of_an_unknown_kind_is_refused()


def test_a_crash_without_a_target_is_refused():
    assert injection.a_crash_without_a_target_is_refused()


def test_a_partition_without_sides_is_refused():
    assert injection.a_partition_without_sides_is_refused()


def test_a_fault_at_tick_zero_is_refused():
    assert injection.a_fault_at_tick_zero_is_refused()


def test_a_run_of_no_ticks_is_refused():
    assert injection.a_run_of_no_ticks_is_refused()


def test_the_schedule_table_covers_ten():
    assert len(injection.compare_the_schedules()) == 10


def test_the_schedules_all_differ():
    assert injection.the_schedules_differ_from_each_other()["they_all_differ"]


def test_the_schedules_use_different_fault_kinds():
    assert injection.the_schedules_differ_from_each_other()["and_they_use_different_faults"]


def test_the_summary_says_schedules_replay():
    assert injection.summarise()["a_schedule_replays"]


def test_the_summary_says_every_schedule_is_safe():
    assert injection.summarise()["every_schedule_stays_safe"]


def test_the_summary_says_faults_cost_availability():
    assert injection.summarise()["faults_cost_availability"]


def test_a_fault_summarises():
    made = Fault(kind=CRASH, at=4, target="n0")
    assert made.as_dict()["kind"] == CRASH


def test_a_crash_prints_its_target():
    assert str(Fault(kind=CRASH, at=4, target="n0")) == "4: crash n0"


def test_a_heal_prints_without_a_target():
    assert str(Fault(kind=HEAL, at=9)) == "9: heal"


def test_a_partition_prints_its_sides():
    made = Fault(kind=PARTITION, at=3, sides=(("a",), ("b", "c")))
    assert "partition" in str(made)


def test_an_unknown_kind_raises():
    with pytest.raises(ConfigError):
        Fault(kind="nonsense", at=1, target="n0")


def test_a_restart_needs_a_target():
    with pytest.raises(ConfigError):
        Fault(kind=RESTART, at=1)


def test_a_schedule_groups_its_faults_by_tick():
    made = Schedule(
        seed=1,
        ticks=50,
        faults=[Fault(kind=CRASH, at=5, target="n0"), Fault(kind=HEAL, at=5)],
    )
    assert len(made.due[5]) == 2


def test_a_schedule_summarises():
    made = Schedule(seed=3, ticks=50)
    assert made.as_dict()["seed"] == 3


def test_a_schedule_with_no_faults_is_valid():
    assert Schedule(seed=1, ticks=10).faults == []


def test_a_schedule_of_zero_size_is_refused():
    with pytest.raises(ConfigError):
        Schedule(seed=1, ticks=10, size=0)


def test_a_late_fault_raises():
    with pytest.raises(ConfigError):
        Schedule(seed=1, ticks=10, faults=[Fault(kind=HEAL, at=99)])


def test_running_an_empty_schedule_still_elects():
    made = run(Schedule(seed=2, ticks=60))
    assert made.leaders >= 1


def test_running_an_empty_schedule_commits():
    made = run(Schedule(seed=2, ticks=120))
    assert made.committed > 0


def test_running_an_empty_schedule_is_safe():
    assert bool(run(Schedule(seed=2, ticks=60)))


def test_an_empty_schedule_applies_nothing():
    made = run(Schedule(seed=2, ticks=60))
    assert made.applied == 0 and made.skipped == 0


def test_an_empty_schedule_has_no_exposure():
    assert run(Schedule(seed=2, ticks=60)).exposure == 0.0


def test_an_outcome_summarises():
    made = run(Schedule(seed=2, ticks=60))
    assert made.as_dict()["seed"] == 2


def test_a_generated_schedule_has_the_asked_for_faults():
    assert len(random_schedule(1, faults=4).faults) == 4


def test_a_generated_schedule_is_sorted_by_tick():
    made = random_schedule(5)
    assert [one.at for one in made.faults] == sorted(one.at for one in made.faults)


def test_a_generated_schedule_fits_its_run():
    made = random_schedule(5, ticks=200)
    assert all(one.at < 200 for one in made.faults)


def test_a_generated_schedule_names_its_seed():
    assert random_schedule(9).seed == 9


def test_a_lossy_schedule_carries_its_conditions():
    made = Schedule(seed=1, ticks=50, conditions=Conditions(loss=0.2))
    assert made.conditions.loss == 0.2


def test_there_are_four_fault_kinds():
    assert len(KINDS) == 4
