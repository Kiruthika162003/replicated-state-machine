from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.machine import INCREMENT, SET, Command
from rsm.verify import linearize as checker
from rsm.verify.history import History
from rsm.verify.linearize import (
    BUDGET,
    LINEARIZABLE,
    NOT_LINEARIZABLE,
    UNKNOWN,
    VERDICTS,
    Verdict,
    check,
    sequential_example,
)


def test_a_correct_history_passes():
    assert checker.a_correct_sequential_history_passes()["it_passed"]


def test_a_correct_history_is_decided():
    assert checker.a_correct_sequential_history_passes()["and_it_decided"]


def test_a_correct_history_is_cheap():
    assert checker.a_correct_sequential_history_passes()["a_sequential_history_costs_little"]


def test_an_impossible_answer_fails():
    assert checker.an_impossible_answer_fails()["it_failed"]


def test_the_impossible_history_is_decided():
    assert checker.an_impossible_answer_fails()["and_it_decided"]


def test_it_explained_the_first_operation():
    assert checker.an_impossible_answer_fails()["it_got_through_the_first_one"]


def test_a_stale_read_is_rejected():
    assert checker.a_stale_read_is_caught()["it_was_rejected"]


def test_the_stale_write_returned_first():
    assert checker.a_stale_read_is_caught()["the_write_returned_first"]


def test_overlapping_the_same_operations_passes():
    assert checker.concurrency_makes_an_otherwise_wrong_history_right()["it_passed"]


def test_the_separated_version_still_fails():
    assert checker.concurrency_makes_an_otherwise_wrong_history_right()[
        "the_separated_version_failed"
    ]


def test_only_the_windows_differ():
    assert checker.the_same_operations_pass_or_fail_on_their_windows_alone()[
        "so_only_the_windows_differ"
    ]


def test_the_two_histories_have_the_same_commands():
    assert checker.the_same_operations_pass_or_fail_on_their_windows_alone()["same_commands"]


def test_the_two_histories_have_the_same_results():
    assert checker.the_same_operations_pass_or_fail_on_their_windows_alone()["same_results"]


def test_a_pending_operation_can_be_placed():
    assert checker.a_pending_operation_may_be_placed_or_dropped()[
        "so_the_pending_one_was_placed"
    ]


def test_a_pending_operation_can_be_left_out():
    assert checker.a_pending_operation_that_must_not_have_happened()[
        "so_the_pending_one_was_left_out"
    ]


def test_the_constraint_prunes_the_search():
    assert checker.the_real_time_constraint_prunes_the_search()["it_visited_far_fewer"]


def test_a_sequential_check_is_about_linear():
    assert checker.the_real_time_constraint_prunes_the_search()["about_one_per_operation"]


def test_width_alone_costs_nothing():
    assert checker.width_alone_costs_nothing_and_ambiguity_costs_everything()[
        "width_alone_costs_nothing"
    ]


def test_ambiguity_costs_a_great_deal():
    assert checker.width_alone_costs_nothing_and_ambiguity_costs_everything()[
        "and_ambiguity_costs_a_great_deal"
    ]


def test_the_ambiguity_factor_is_large():
    assert (
        checker.width_alone_costs_nothing_and_ambiguity_costs_everything()["by_this_factor"]
        > 10
    )


def test_the_ambiguous_history_fails():
    assert checker.width_alone_costs_nothing_and_ambiguity_costs_everything()[
        "and_the_ambiguous_one_failed"
    ]


def test_a_starved_search_says_unknown():
    assert checker.running_out_of_budget_is_not_a_pass()["it_is_unknown"]


def test_unknown_is_falsy():
    assert checker.running_out_of_budget_is_not_a_pass()["and_it_is_falsy"]


def test_unknown_says_it_did_not_decide():
    assert checker.running_out_of_budget_is_not_a_pass()["and_it_says_it_did_not_decide"]


def test_with_budget_it_is_a_real_rejection():
    assert checker.running_out_of_budget_is_not_a_pass()["with_budget_it_is_a_real_rejection"]


def test_unknown_and_rejected_are_different_answers():
    assert checker.running_out_of_budget_is_not_a_pass()["and_unknown_is_not_that"]


def test_a_cheap_history_survives_a_small_budget():
    assert checker.running_out_of_budget_is_not_a_pass()[
        "a_passing_history_survives_the_same_budget"
    ]


def test_a_rejection_reports_its_prefix():
    assert checker.a_rejection_names_where_it_got_stuck()["it_explained_the_first_three"]


def test_a_rejection_stops_at_the_bad_one():
    assert checker.a_rejection_names_where_it_got_stuck()["and_not_the_fourth"]


def test_a_rejection_names_the_operation():
    assert checker.a_rejection_names_where_it_got_stuck()["it_names_where"]


def test_an_empty_history_passes():
    assert checker.an_empty_history_is_linearizable()["it_passed"]


def test_an_empty_history_costs_one_state():
    assert checker.an_empty_history_is_linearizable()["and_it_cost_one_state"]


def test_a_zero_budget_is_refused():
    assert checker.a_zero_budget_is_refused()


def test_an_unknown_verdict_is_refused():
    assert checker.an_unknown_verdict_is_refused()


def test_the_case_table_covers_four():
    assert len(checker.compare_the_histories()) == 4


def test_no_small_case_is_unknown():
    assert checker.every_case_is_decided()["none_are_unknown"]


def test_some_cases_pass_and_some_fail():
    made = checker.every_case_is_decided()
    assert made["some_pass"] and made["and_some_fail"]


def test_the_summary_says_unknown_is_falsy():
    assert checker.summarise()["unknown_is_falsy"]


def test_the_summary_says_width_is_cheap():
    assert checker.summarise()["width_alone_is_cheap"]


def test_a_verdict_is_truthy_when_linearizable():
    made = Verdict(answer=LINEARIZABLE, states=1, longest_prefix=1, operations=1)
    assert bool(made)


def test_a_verdict_is_falsy_when_not():
    made = Verdict(answer=NOT_LINEARIZABLE, states=1, longest_prefix=0, operations=1)
    assert not bool(made)


def test_a_verdict_is_falsy_when_unknown():
    made = Verdict(answer=UNKNOWN, states=1, longest_prefix=0, operations=1)
    assert not bool(made)


def test_a_decided_verdict_says_so():
    made = Verdict(answer=LINEARIZABLE, states=1, longest_prefix=1, operations=1)
    assert made.decided


def test_an_unknown_verdict_is_not_decided():
    made = Verdict(answer=UNKNOWN, states=1, longest_prefix=0, operations=1)
    assert not made.decided


def test_a_verdict_summarises():
    made = Verdict(answer=LINEARIZABLE, states=7, longest_prefix=3, operations=3)
    assert made.as_dict()["states"] == 7


def test_a_bad_verdict_name_raises():
    with pytest.raises(ConfigError):
        Verdict(answer="maybe", states=1, longest_prefix=0, operations=0)


def test_checking_the_example_passes():
    assert bool(check(sequential_example()))


def test_checking_with_a_zero_budget_raises():
    with pytest.raises(ConfigError):
        check(sequential_example(), budget=0)


def test_checking_an_empty_history_passes():
    assert bool(check(History()))


def test_a_verdict_counts_the_operations():
    assert check(sequential_example()).operations == 2


def test_a_single_write_is_linearizable():
    made = History()
    one = made.call("c1", Command(name=SET, key="k", value=1))
    made.complete(one, 1)
    assert bool(check(made))


def test_a_single_write_with_a_wrong_answer_is_not():
    made = History()
    one = made.call("c1", Command(name=SET, key="k", value=1))
    made.complete(one, 99)
    assert not check(made)


def test_a_lone_pending_operation_is_linearizable():
    made = History()
    made.call("c1", Command(name=INCREMENT, key="k", value=1))
    assert bool(check(made))


def test_there_are_three_verdicts():
    assert len(VERDICTS) == 3


def test_the_budget_is_generous():
    assert BUDGET >= 10_000
