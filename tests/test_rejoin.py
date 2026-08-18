from __future__ import annotations

import pytest

from rsm import rejoin as back
from rsm.errors import ConfigError
from rsm.node import MAX_BATCH
from rsm.rejoin import (
    NARROW,
    WIDE,
    Path,
    by_entries,
    by_snapshot,
    cheaper,
    crossover,
)
from rsm.snapshot import KEY_BYTES
from rsm.wire import ASSUMED_ENTRY_BYTES, ASSUMED_MESSAGE_BYTES


def test_the_crossing_is_below_the_key_count():
    assert back.the_snapshot_wins_once_the_lag_passes_the_state_size()[
        "it_is_below_the_key_count"
    ]


def test_the_crossing_share_is_stable():
    assert back.the_snapshot_wins_once_the_lag_passes_the_state_size()[
        "and_the_share_is_stable"
    ]


def test_an_entry_costs_more_than_a_key():
    assert back.the_snapshot_wins_once_the_lag_passes_the_state_size()[
        "and_an_entry_costs_more_than_a_key"
    ]


def test_a_narrow_workload_crosses_at_once():
    assert back.a_narrow_workload_crosses_early_and_a_wide_one_never_does()[
        "it_crosses_almost_at_once"
    ]


def test_a_wide_workload_crosses_late():
    assert back.a_narrow_workload_crosses_early_and_a_wide_one_never_does()[
        "and_the_wide_one_crosses_late"
    ]


def test_a_wide_state_grows_with_the_log():
    assert back.a_narrow_workload_crosses_early_and_a_wide_one_never_does()[
        "the_wide_state_grows_with_the_log"
    ]


def test_the_straight_line_answer_is_wrong():
    assert back.the_crossing_is_a_staircase_rather_than_a_point()["they_differ"]


def test_the_steps_are_a_batch_apart():
    assert back.the_crossing_is_a_staircase_rather_than_a_point()["the_steps_are_a_batch_apart"]


def test_the_straight_line_error_is_under_a_batch():
    assert back.the_crossing_is_a_staircase_rather_than_a_point()[
        "and_the_error_is_under_a_batch"
    ]


def test_a_near_node_can_be_caught_up_by_entries():
    assert back.compaction_decides_which_path_is_available_at_all()[
        "a_node_ten_behind_can_be_caught_up"
    ]


def test_a_far_node_cannot():
    assert back.compaction_decides_which_path_is_available_at_all()[
        "and_one_fifty_behind_cannot"
    ]


def test_compaction_leaves_the_snapshot_small():
    assert back.compaction_decides_which_path_is_available_at_all()[
        "which_is_small_for_this_workload"
    ]


def test_a_negative_lag_is_refused():
    assert back.a_negative_lag_is_refused()


def test_a_negative_key_count_is_refused():
    assert back.a_negative_key_count_is_refused()


def test_a_path_with_negative_messages_is_refused():
    assert back.a_path_with_negative_messages_is_refused()


def test_a_current_node_needs_no_messages():
    assert back.a_node_that_is_current_needs_neither_path()["it_sends_nothing"]


def test_the_snapshot_still_costs_a_message():
    assert back.a_node_that_is_current_needs_neither_path()["and_the_snapshot_still_costs_one"]


def test_the_entries_are_cheaper_for_a_current_node():
    assert back.a_node_that_is_current_needs_neither_path()["and_it_is_the_entries"]


def test_an_empty_path_has_no_per_message_cost():
    assert back.a_node_that_is_current_needs_neither_path()[
        "which_is_zero_rather_than_infinite"
    ]


def test_the_lag_table_covers_six():
    assert len(back.compare_the_lags()) == 6


def test_the_snapshot_is_the_minority_choice():
    assert back.the_leader_should_choose_and_usually_does_not()[
        "the_snapshot_is_the_minority_choice"
    ]


def test_the_crossover_sits_inside_the_table():
    assert back.the_leader_should_choose_and_usually_does_not()["and_it_sits_inside_the_table"]


def test_the_summary_reports_the_crossover():
    assert back.summarise()["crossover_at_four_hundred_keys"] > 0


def test_the_summary_says_compaction_closes_the_path():
    assert back.summarise()["compaction_closes_the_entry_path"]


def test_no_lag_costs_no_messages():
    assert by_entries(0).messages == 0


def test_one_entry_costs_one_message():
    assert by_entries(1).messages == 1


def test_a_batch_costs_one_message():
    assert by_entries(MAX_BATCH).messages == 1


def test_one_past_a_batch_costs_two():
    assert by_entries(MAX_BATCH + 1).messages == 2


def test_the_entry_path_charges_per_entry():
    made = by_entries(10)
    assert made.nbytes == ASSUMED_MESSAGE_BYTES + 10 * ASSUMED_ENTRY_BYTES


def test_a_negative_lag_raises():
    with pytest.raises(ConfigError):
        by_entries(-5)


def test_a_snapshot_is_always_one_message():
    assert by_snapshot(10000).messages == 1


def test_a_snapshot_charges_per_key():
    assert by_snapshot(10).nbytes == ASSUMED_MESSAGE_BYTES + 10 * KEY_BYTES


def test_an_empty_snapshot_is_just_a_header():
    assert by_snapshot(0).nbytes == ASSUMED_MESSAGE_BYTES


def test_a_negative_key_count_raises():
    with pytest.raises(ConfigError):
        by_snapshot(-1)


def test_a_path_reports_its_per_message_cost():
    assert by_entries(200).per_message > 0


def test_a_path_summarises():
    assert by_snapshot(4).as_dict()["path"] == "snapshot"


def test_a_path_prints_itself():
    assert "messages" in str(by_entries(10))


def test_a_negative_message_count_raises():
    with pytest.raises(ConfigError):
        Path(name="x", entries=0, keys=0, messages=-1, nbytes=0)


def test_a_negative_entry_count_raises():
    with pytest.raises(ConfigError):
        Path(name="x", entries=-1, keys=0, messages=1, nbytes=0)


def test_the_cheaper_path_at_no_lag_is_entries():
    assert cheaper(0, 100).name == "entries"


def test_the_cheaper_path_at_a_huge_lag_is_the_snapshot():
    assert cheaper(100000, 10).name == "snapshot"


def test_the_crossover_is_where_the_choice_changes():
    keys = 200
    found = crossover(keys)
    assert cheaper(found - 1, keys).name == "entries"


def test_past_the_crossover_the_snapshot_wins():
    keys = 200
    found = crossover(keys)
    assert cheaper(found + MAX_BATCH, keys).name == "snapshot"


def test_a_bigger_state_crosses_later():
    assert crossover(4000) > crossover(40)


def test_a_negative_state_raises():
    with pytest.raises(ConfigError):
        crossover(-1)


def test_the_narrow_workload_is_narrow():
    assert NARROW < WIDE


def test_the_wide_workload_is_wide():
    assert WIDE >= 100
