from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.machine import SET, Command
from rsm.verify import refine as step_check
from rsm.verify.refine import COMMANDS, EVERY, Refinement, Step, check, mapping


def test_the_cluster_refines_the_model():
    assert step_check.the_cluster_refines_the_model_at_every_step()["it_holds"]


def test_the_refinement_took_every_step():
    made = step_check.the_cluster_refines_the_model_at_every_step()
    assert made["steps"] == made["commands"]


def test_the_refinement_broke_nowhere():
    assert step_check.the_cluster_refines_the_model_at_every_step()["breaks"] == 0


def test_the_final_state_is_not_empty():
    assert step_check.the_cluster_refines_the_model_at_every_step()[
        "and_the_states_are_not_empty"
    ]


def test_a_slipped_command_breaks_the_check():
    assert step_check.a_step_check_says_which_command_broke_it()["it_broke"]


def test_the_break_names_the_slipped_command():
    assert step_check.a_step_check_says_which_command_broke_it()[
        "and_it_is_the_slipped_command"
    ]


def test_everything_after_the_break_broke_too():
    assert step_check.a_step_check_says_which_command_broke_it()[
        "and_everything_after_it_broke_too"
    ]


def test_the_two_shapes_differ():
    assert step_check.the_mapping_is_what_makes_the_comparison_possible()[
        "they_are_different_shapes"
    ]


def test_the_raw_states_are_not_equal():
    assert not step_check.the_mapping_is_what_makes_the_comparison_possible()[
        "raw_states_are_equal"
    ]


def test_the_mapped_states_are():
    assert step_check.the_mapping_is_what_makes_the_comparison_possible()[
        "mapped_states_are_equal"
    ]


def test_a_generous_mapping_agrees_with_anything():
    assert step_check.the_mapping_is_what_makes_the_comparison_possible()[
        "a_generous_mapping_would_agree_with_anything"
    ]


def test_the_ends_agree_in_the_returning_run():
    assert step_check.refinement_is_stronger_than_agreeing_at_the_end()["the_ends_agree"]


def test_the_step_check_still_fails():
    assert step_check.refinement_is_stronger_than_agreeing_at_the_end()["the_step_check_fails"]


def test_the_break_is_in_the_middle():
    assert step_check.refinement_is_stronger_than_agreeing_at_the_end()["and_it_is_the_middle"]


def test_refinement_is_the_stronger_claim():
    assert step_check.refinement_is_stronger_than_agreeing_at_the_end()[
        "so_refinement_is_the_stronger_claim"
    ]


def test_a_check_with_no_commands_is_refused():
    assert step_check.a_check_with_no_commands_is_refused()


def test_an_empty_refinement_is_falsy():
    assert step_check.an_empty_refinement_is_falsy()["empty_is_falsy"]


def test_a_single_agreeing_step_is_truthy():
    assert step_check.an_empty_refinement_is_falsy()["and_a_single_agreeing_step_is_truthy"]


def test_an_empty_refinement_has_no_breaks():
    assert step_check.an_empty_refinement_is_falsy()["which_is_none"]


def test_the_size_table_covers_three():
    assert len(step_check.compare_the_sizes()) == 3


def test_every_size_refines_the_model():
    assert step_check.every_size_refines_the_same_model()["every_size_holds"]


def test_every_size_took_the_same_steps():
    assert step_check.every_size_refines_the_same_model()["and_they_all_took_the_same_steps"]


def test_no_size_broke():
    assert step_check.every_size_refines_the_same_model()["none_of_them_broke"]


def test_the_summary_says_the_cluster_refines_the_model():
    assert step_check.summarise()["the_cluster_refines_the_model"]


def test_the_summary_says_refinement_is_stronger():
    assert step_check.summarise()["refinement_is_stronger"]


def test_a_mapping_sorts_its_keys():
    assert mapping({"b": 1, "a": 2})[0][0] == "a"


def test_a_mapping_of_nothing_is_empty():
    assert mapping({}) == ()


def test_two_equal_states_map_alike():
    assert mapping({"a": 1, "b": 2}) == mapping({"b": 2, "a": 1})


def test_two_different_states_do_not():
    assert mapping({"a": 1}) != mapping({"a": 2})


def test_a_mapping_keeps_every_key():
    assert len(mapping({"a": 1, "b": 2, "c": 3})) == 3


def test_an_agreeing_step_says_so():
    assert Step(at=1, command="x", model=(("a", "1"),), cluster=(("a", "1"),)).agrees


def test_a_disagreeing_step_does_not():
    assert not Step(at=1, command="x", model=(("a", "1"),), cluster=()).agrees


def test_a_step_summarises():
    made = Step(at=3, command="x", model=(), cluster=())
    assert made.as_dict()["at"] == 3


def test_an_agreeing_step_prints_that():
    made = Step(at=3, command="x", model=(), cluster=())
    assert "agreed" in str(made)


def test_a_disagreeing_step_prints_both_sides():
    made = Step(at=3, command="x", model=(("a", "1"),), cluster=())
    assert "against" in str(made)


def test_a_refinement_finds_its_first_break():
    made = Refinement(
        steps=[
            Step(at=1, command="x", model=(), cluster=()),
            Step(at=2, command="y", model=(("a", "1"),), cluster=()),
            Step(at=3, command="z", model=(("b", "1"),), cluster=()),
        ]
    )
    assert made.first_break.at == 2


def test_a_clean_refinement_has_no_first_break():
    made = Refinement(steps=[Step(at=1, command="x", model=(), cluster=())])
    assert made.first_break is None


def test_a_refinement_counts_its_breaks():
    made = Refinement(
        steps=[
            Step(at=1, command="x", model=(("a", "1"),), cluster=()),
            Step(at=2, command="y", model=(), cluster=()),
        ]
    )
    assert len(made.breaks) == 1


def test_a_clean_refinement_is_truthy():
    assert Refinement(steps=[Step(at=1, command="x", model=(), cluster=())])


def test_a_broken_refinement_is_falsy():
    made = Refinement(steps=[Step(at=1, command="x", model=(("a", "1"),), cluster=())])
    assert not made


def test_an_empty_refinement_is_falsy_too():
    assert not Refinement()


def test_a_refinement_summarises():
    assert Refinement().as_dict()["steps"] == 0


def test_a_refinement_reports_its_first_break_in_the_summary():
    made = Refinement(steps=[Step(at=1, command="x", model=(("a", "1"),), cluster=())])
    assert made.as_dict()["first_break"]


def test_checking_a_short_run_holds():
    made = check(commands=[Command(name=SET, key="k", value=one) for one in range(5)])
    assert made


def test_checking_records_a_step_per_command():
    commands = [Command(name=SET, key="k", value=one) for one in range(6)]
    assert len(check(commands=commands).steps) == 6


def test_checking_a_single_node_cluster_holds():
    made = check(commands=[Command(name=SET, key="k", value=1)], size=1)
    assert made


def test_checking_nothing_raises():
    with pytest.raises(ConfigError):
        check(commands=[])


def test_the_command_count_is_worth_checking():
    assert COMMANDS >= 10


def test_the_check_runs_every_step():
    assert EVERY == 1
