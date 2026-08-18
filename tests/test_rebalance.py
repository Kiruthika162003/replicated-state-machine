from __future__ import annotations

import pytest

from rsm import rebalance as move_module
from rsm.errors import ConfigError
from rsm.rebalance import (
    COPY_BYTES,
    COPYING,
    FROZEN,
    HANDED,
    PHASES,
    RANGE,
    STEADY,
    Attempt,
    Move,
    run_move,
)


def test_the_phased_move_is_correct():
    assert move_module.the_phases_cost_availability_and_buy_a_single_owner()["safe_is_correct"]


def test_the_both_sides_move_is_not():
    assert move_module.the_phases_cost_availability_and_buy_a_single_owner()[
        "and_the_other_is_not"
    ]


def test_the_unsafe_move_answers_more():
    assert move_module.the_phases_cost_availability_and_buy_a_single_owner()[
        "the_unsafe_one_answers_more"
    ]


def test_the_phased_move_never_has_two_owners():
    assert move_module.the_phases_cost_availability_and_buy_a_single_owner()[
        "the_phased_one_never_does"
    ]


def test_the_unsafe_move_sometimes_does():
    assert move_module.the_phases_cost_availability_and_buy_a_single_owner()[
        "and_it_has_two_owners_sometimes"
    ]


def test_the_freeze_tracks_the_copy():
    assert move_module.the_freeze_lasts_as_long_as_the_copy()["it_tracks_the_copy"]


def test_availability_falls_with_the_copy():
    assert move_module.the_freeze_lasts_as_long_as_the_copy()["and_availability_falls_with_it"]


def test_the_quickest_copy_is_the_most_available():
    made = move_module.the_freeze_lasts_as_long_as_the_copy()
    assert made["the_quickest"] > made["the_slowest"]


def test_the_way_to_shorten_a_move_is_to_move_less():
    assert move_module.the_freeze_lasts_as_long_as_the_copy()[
        "so_the_way_to_shorten_a_move_is_to_move_less"
    ]


def test_the_steady_phase_serves():
    assert move_module.the_range_has_exactly_one_owner_in_every_phase()[
        "the_steady_phase_serves"
    ]


def test_the_middle_phases_do_not():
    assert move_module.the_range_has_exactly_one_owner_in_every_phase()[
        "and_the_middle_two_do_not"
    ]


def test_ownership_moves_at_the_hand_over():
    assert move_module.the_range_has_exactly_one_owner_in_every_phase()[
        "ownership_moves_at_the_hand_over"
    ]


def test_ownership_never_moves_before():
    assert move_module.the_range_has_exactly_one_owner_in_every_phase()["and_never_before"]


def test_a_move_to_the_same_group_is_refused():
    assert move_module.a_move_to_the_same_group_is_refused()


def test_a_move_of_no_keys_is_refused():
    assert move_module.a_move_of_no_keys_is_refused()


def test_an_unknown_phase_is_refused():
    assert move_module.an_unknown_phase_is_refused()


def test_advancing_past_the_end_is_refused():
    assert move_module.advancing_past_the_last_phase_is_refused()


def test_a_run_with_no_writes_is_refused():
    assert move_module.a_run_with_no_writes_is_refused()


def test_the_strategy_table_covers_four():
    assert len(move_module.compare_the_strategies()) == 4


def test_every_phased_row_is_safe():
    assert move_module.only_the_phased_move_is_safe_at_any_copy_length()[
        "every_phased_row_is_safe"
    ]


def test_no_unsafe_row_is():
    assert move_module.only_the_phased_move_is_safe_at_any_copy_length()["and_no_unsafe_row_is"]


def test_a_longer_copy_costs_availability():
    assert move_module.only_the_phased_move_is_safe_at_any_copy_length()[
        "a_longer_copy_costs_availability"
    ]


def test_the_copy_length_never_changes_the_safety():
    assert move_module.only_the_phased_move_is_safe_at_any_copy_length()[
        "and_never_changes_the_safety"
    ]


def test_the_summary_says_the_phased_move_is_safe():
    assert move_module.summarise()["the_phased_move_is_safe"]


def test_the_summary_says_the_other_is_not():
    assert move_module.summarise()["the_both_sides_move_is_not"]


def test_a_move_starts_at_the_source():
    assert Move(keys=("a",), source=2, destination=3).owner == 2


def test_a_move_ends_at_the_destination():
    made = Move(keys=("a",), source=2, destination=3, phase=HANDED)
    assert made.owner == 3


def test_a_steady_move_serves():
    assert Move(keys=("a",), source=0, destination=1).serving


def test_a_frozen_move_does_not():
    assert not Move(keys=("a",), source=0, destination=1, phase=FROZEN).serving


def test_a_copying_move_does_not():
    assert not Move(keys=("a",), source=0, destination=1, phase=COPYING).serving


def test_a_handed_move_serves():
    assert Move(keys=("a",), source=0, destination=1, phase=HANDED).serving


def test_a_move_reports_its_size():
    assert Move(keys=("a", "b"), source=0, destination=1).nbytes == 2 * COPY_BYTES


def test_a_move_advances_through_the_phases():
    made = Move(keys=("a",), source=0, destination=1)
    assert made.advance(1) == FROZEN


def test_a_move_records_when_it_froze():
    made = Move(keys=("a",), source=0, destination=1)
    made.advance(7)
    assert made.frozen_at == 7


def test_a_move_records_when_it_handed_over():
    made = Move(keys=("a",), source=0, destination=1)
    made.advance(1)
    made.advance(2)
    made.advance(9)
    assert made.handed_at == 9


def test_a_move_reports_how_long_it_was_unavailable():
    made = Move(keys=("a",), source=0, destination=1)
    made.advance(2)
    made.advance(3)
    made.advance(12)
    assert made.unavailable_for == 10


def test_an_unfinished_move_reports_no_downtime():
    made = Move(keys=("a",), source=0, destination=1)
    made.advance(2)
    assert made.unavailable_for == 0


def test_a_move_summarises():
    assert Move(keys=("a",), source=0, destination=1).as_dict()["source"] == 0


def test_a_move_to_itself_raises():
    with pytest.raises(ConfigError):
        Move(keys=("a",), source=1, destination=1)


def test_a_move_of_nothing_raises():
    with pytest.raises(ConfigError):
        Move(keys=(), source=0, destination=1)


def test_an_unknown_phase_raises():
    with pytest.raises(ConfigError):
        Move(keys=("a",), source=0, destination=1, phase="halfway")


def test_advancing_a_finished_move_raises():
    made = Move(keys=("a",), source=0, destination=1, phase=HANDED)
    with pytest.raises(ConfigError):
        made.advance(1)


def test_an_attempt_reports_its_availability():
    assert Attempt(name="x", attempted=10, served=7).availability == 0.7


def test_an_attempt_with_nothing_attempted_has_none():
    assert Attempt(name="x").availability == 0.0


def test_an_attempt_without_two_owners_is_truthy():
    assert Attempt(name="x")


def test_an_attempt_with_two_owners_is_falsy():
    assert not Attempt(name="x", two_owners=2)


def test_an_attempt_summarises():
    assert Attempt(name="named").as_dict()["run"] == "named"


def test_a_phased_run_is_safe():
    made, _ = run_move("x", writes=10)
    assert made


def test_an_unsafe_run_is_not():
    made, _ = run_move("x", writes=10, unsafe=True)
    assert not made


def test_a_run_returns_its_move():
    _, made = run_move("x", writes=10)
    assert made.phase == HANDED


def test_a_run_with_no_writes_raises():
    with pytest.raises(ConfigError):
        run_move("x", writes=0)


def test_the_phases_are_four():
    assert len(PHASES) == 4


def test_the_phases_start_steady():
    assert PHASES[0] == STEADY


def test_the_phases_end_handed():
    assert PHASES[-1] == HANDED


def test_the_range_is_worth_moving():
    assert RANGE >= 10
