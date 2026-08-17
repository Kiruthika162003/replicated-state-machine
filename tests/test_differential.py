from __future__ import annotations

from rsm.machine import SET, Command
from rsm.verify import differential as harness
from rsm.verify import reference as single
from rsm.verify.differential import (
    CHECKERS,
    CONCURRENT,
    INVARIANTS,
    LINEARIZABILITY,
    REFERENCE,
    SEQUENTIAL,
    SHAPES,
    Result,
    concurrent_run,
    sequential_run,
)
from rsm.verify.history import sequential_history
from rsm.verify.reference import Agreement, Difference, Reference, compare, from_history


def test_a_reference_agrees_with_itself():
    assert single.a_reference_run_agrees_with_itself()["it_agreed"]


def test_the_reference_states_match():
    assert single.a_reference_run_agrees_with_itself()["and_the_states_match"]


def test_one_wrong_answer_is_caught():
    assert single.one_wrong_answer_is_caught()["it_disagreed"]


def test_the_wrong_answer_is_located():
    assert single.one_wrong_answer_is_caught()["which_is_the_one_changed"]


def test_a_wrong_state_is_caught_even_when_answers_match():
    assert single.a_wrong_final_state_is_caught_even_when_the_answers_match()[
        "so_it_still_failed"
    ]


def test_the_answers_matched_in_that_case():
    assert single.a_wrong_final_state_is_caught_even_when_the_answers_match()[
        "the_answers_all_matched"
    ]


def test_an_agreement_is_truthy():
    assert single.an_agreement_object_is_falsy_when_it_disagrees()["an_agreement_is_truthy"]


def test_a_disagreement_is_falsy():
    assert single.an_agreement_object_is_falsy_when_it_disagrees()[
        "and_a_disagreement_is_falsy"
    ]


def test_a_cluster_agrees_with_the_reference():
    assert single.a_cluster_agrees_with_the_reference()["and_the_answers_match"]


def test_a_cluster_reaches_the_same_state():
    assert single.a_cluster_agrees_with_the_reference()["the_states_match"]


def test_a_cluster_answers_every_command():
    assert single.a_cluster_agrees_with_the_reference()["they_answered_the_same_number"]


def test_the_reference_has_no_network():
    assert single.the_reference_sends_no_messages()["it_has_no_network"]


def test_the_reference_has_no_log():
    assert single.the_reference_sends_no_messages()["and_no_log"]


def test_a_concurrent_history_is_refused():
    assert single.a_concurrent_history_cannot_be_compared()


def test_a_sequential_history_converts():
    assert single.a_sequential_history_can_be()["they_match"]


def test_the_converted_order_is_kept():
    assert single.a_sequential_history_can_be()["and_the_order_is_kept"]


def test_a_mismatched_answer_count_is_refused():
    assert single.a_mismatched_answer_count_is_refused()


def test_an_empty_comparison_agrees():
    assert single.an_empty_comparison_agrees()["it_agreed"]


def test_every_workload_agrees_with_itself():
    assert single.every_workload_agrees_with_itself()["they_all_agree"]


def test_no_workload_had_a_difference():
    assert single.every_workload_agrees_with_itself()["no_differences_anywhere"]


def test_the_reference_summary_says_a_cluster_agrees():
    assert single.summarise()["a_cluster_agrees"]


def test_a_sequential_run_passes():
    assert harness.a_sequential_run_passes_both_checks()["it_passed"]


def test_a_sequential_run_skips_the_checker():
    assert harness.a_sequential_run_passes_both_checks()["skipped"] == [LINEARIZABILITY]


def test_a_sequential_run_commits():
    assert harness.a_sequential_run_passes_both_checks()["and_it_committed"]


def test_a_concurrent_run_passes():
    assert harness.a_concurrent_run_passes_both_of_its_checks()["it_passed"]


def test_a_concurrent_run_skips_the_reference():
    assert harness.a_concurrent_run_passes_both_of_its_checks()["skipped"] == [REFERENCE]


def test_a_concurrent_run_is_decided():
    assert harness.a_concurrent_run_passes_both_of_its_checks()["and_it_was_decided"]


def test_a_concurrent_run_really_overlapped():
    assert harness.a_concurrent_run_passes_both_of_its_checks()["and_there_was_real_overlap"]


def test_neither_shape_runs_all_three():
    assert harness.neither_shape_runs_all_three_checks()["neither_runs_all_three"]


def test_together_they_cover_everything():
    assert harness.neither_shape_runs_all_three_checks()["together_they_cover_everything"]


def test_they_share_the_invariants():
    assert harness.neither_shape_runs_all_three_checks()["and_they_share_one"]


def test_the_reference_catches_a_wrong_answer():
    assert harness.the_reference_catches_a_wrong_answer()["broken_disagreed"]


def test_the_clean_comparison_still_agrees():
    assert harness.the_reference_catches_a_wrong_answer()["clean_agreed"]


def test_the_checker_catches_an_impossible_history():
    assert harness.the_checker_catches_an_impossible_history()["it_was_rejected"]


def test_that_rejection_was_decided():
    assert harness.the_checker_catches_an_impossible_history()["and_it_was_decided"]


def test_the_invariants_look_at_a_clientless_run():
    assert harness.the_invariants_catch_what_the_others_cannot()["the_invariants_still_looked"]


def test_the_other_two_say_nothing_there():
    made = harness.the_invariants_catch_what_the_others_cannot()
    assert made["the_checker_says_nothing_useful"] and made["and_so_does_the_reference"]


def test_a_failing_result_is_falsy():
    assert harness.a_result_of_a_failing_run_is_falsy()["and_a_failing_one_is_falsy"]


def test_a_passing_result_is_truthy():
    assert harness.a_result_of_a_failing_run_is_falsy()["a_passing_result_is_truthy"]


def test_faults_do_not_break_the_checks():
    assert harness.a_run_under_faults_still_passes_every_applicable_check()["they_are_all_safe"]


def test_those_faults_were_real():
    assert harness.a_run_under_faults_still_passes_every_applicable_check()[
        "and_the_faults_were_real"
    ]


def test_every_seed_passes_both_shapes():
    assert harness.every_seed_passes_both_shapes()["they_all_passed"]


def test_both_shapes_were_run():
    assert harness.every_seed_passes_both_shapes()["and_both_shapes_were_run"]


def test_no_seed_reported_a_failure():
    assert harness.every_seed_passes_both_shapes()["failures"] == []


def test_an_unknown_shape_is_refused():
    assert harness.an_unknown_shape_is_refused()


def test_an_empty_schedule_is_still_a_schedule():
    assert harness.a_schedule_with_no_faults_is_still_a_schedule()


def test_the_shape_table_covers_two():
    assert len(harness.compare_the_shapes()) == 2


def test_neither_shape_covers_everything():
    assert harness.the_two_shapes_together_cover_the_three_checkers()[
        "neither_covers_everything"
    ]


def test_the_two_shapes_together_do():
    assert harness.the_two_shapes_together_cover_the_three_checkers()["together_they_do"]


def test_both_shapes_passed():
    assert harness.the_two_shapes_together_cover_the_three_checkers()["and_both_passed"]


def test_the_summary_says_every_seed_passes():
    assert harness.summarise()["every_seed_passes"]


def test_the_summary_says_the_reference_can_fail():
    assert harness.summarise()["the_reference_catches_a_wrong_answer"]


def test_a_result_reports_its_coverage():
    made = Result(shape=SEQUENTIAL, commands=5, ran=[INVARIANTS, REFERENCE])
    assert round(made.coverage, 3) == 0.667


def test_a_result_with_every_checker_has_full_coverage():
    made = Result(shape=SEQUENTIAL, commands=5, ran=list(CHECKERS))
    assert made.coverage == 1.0


def test_a_result_summarises():
    made = Result(shape=CONCURRENT, commands=5)
    assert made.as_dict()["shape"] == CONCURRENT


def test_a_sequential_run_returns_a_result():
    assert sequential_run(seed=3, count=6).shape == SEQUENTIAL


def test_a_concurrent_run_returns_a_result():
    assert concurrent_run(seed=3, each=1).shape == CONCURRENT


def test_a_reference_applies_a_command():
    made = Reference()
    assert made.apply(Command(name=SET, key="k", value=3)) == 3


def test_a_reference_runs_a_sequence():
    made = Reference()
    assert made.run([Command(name=SET, key="k", value=one) for one in range(3)]) == [0, 1, 2]


def test_a_reference_reports_its_state():
    made = Reference()
    made.apply(Command(name=SET, key="k", value=3))
    assert made.state == {"k": 3}


def test_a_reference_summarises():
    made = Reference()
    made.apply(Command(name=SET, key="k", value=3))
    assert made.as_dict()["applied"] == 1


def test_a_difference_summarises():
    made = Difference(
        position=2, command=Command(name=SET, key="k", value=1), reference=1, other=2
    )
    assert made.as_dict()["position"] == 2


def test_a_difference_prints_both_sides():
    made = Difference(
        position=2, command=Command(name=SET, key="k", value=1), reference=1, other=2
    )
    assert "reference 1" in str(made)


def test_an_agreement_summarises():
    assert Agreement(commands=3).as_dict()["commands"] == 3


def test_an_agreement_with_no_differences_is_truthy():
    assert bool(Agreement(commands=3))


def test_comparing_a_matching_run_agrees():
    commands = [Command(name=SET, key="k", value=one) for one in range(4)]
    made = Reference()
    answers = made.run(commands)
    assert bool(compare(commands, answers, made.digest()))


def test_converting_a_sequential_history_gives_commands():
    assert len(from_history(sequential_history(4))) == 4


def test_there_are_three_checkers():
    assert len(CHECKERS) == 3


def test_there_are_two_shapes():
    assert len(SHAPES) == 2
