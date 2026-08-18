from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.rpc import Vote
from rsm.verify import trace as record
from rsm.verify.trace import (
    COMMIT,
    DELIVER,
    KINDS,
    LEVELS,
    ROLE,
    SEND,
    Event,
    Replay,
    Trace,
    capture,
    replay,
)


def test_a_trace_replays_to_the_same_leaders():
    assert record.a_trace_replays_to_the_same_leaders()["both_matched"]


def test_a_quiet_run_replays_to_one_leader():
    assert record.a_trace_replays_to_the_same_leaders()["the_quiet_run_had_one_leader"]


def test_a_killed_run_replays_to_two():
    assert record.a_trace_replays_to_the_same_leaders()["and_the_killed_one_had_two"]


def test_the_network_alone_reconstructs_no_leader():
    assert record.a_recording_of_the_network_alone_cannot_reproduce_the_run()[
        "the_network_alone_finds_none"
    ]


def test_the_full_trace_does():
    assert record.a_recording_of_the_network_alone_cannot_reproduce_the_run()[
        "and_the_full_trace_finds_one"
    ]


def test_the_network_level_applied_plenty():
    assert record.a_recording_of_the_network_alone_cannot_reproduce_the_run()[
        "which_is_not_a_small_number"
    ]


def test_the_gap_is_not_about_volume():
    assert record.a_recording_of_the_network_alone_cannot_reproduce_the_run()[
        "so_the_gap_is_not_about_volume"
    ]


def test_the_outline_is_the_smallest_level():
    assert record.an_outline_is_a_thirtieth_of_the_size_and_keeps_the_story()[
        "the_outline_is_smallest"
    ]


def test_the_outline_is_much_smaller():
    assert record.an_outline_is_a_thirtieth_of_the_size_and_keeps_the_story()[
        "it_is_at_least_ten_times"
    ]


def test_the_outline_keeps_the_role_changes():
    assert record.an_outline_is_a_thirtieth_of_the_size_and_keeps_the_story()[
        "the_outline_has_the_role_changes"
    ]


def test_the_outline_keeps_no_messages():
    assert record.an_outline_is_a_thirtieth_of_the_size_and_keeps_the_story()["and_no_messages"]


def test_recording_does_not_change_the_commits():
    assert record.recording_changes_nothing_about_the_run()["and_the_same_ticks"]


def test_recording_does_not_change_the_count():
    assert record.recording_changes_nothing_about_the_run()["the_same_count"]


def test_the_per_node_filters_add_up():
    assert record.a_trace_can_be_read_by_node_or_by_window()["they_add_up"]


def test_a_window_is_smaller_than_the_trace():
    assert record.a_trace_can_be_read_by_node_or_by_window()["the_window_is_smaller"]


def test_a_window_holds_only_its_range():
    assert record.a_trace_can_be_read_by_node_or_by_window()[
        "and_every_event_in_it_is_in_range"
    ]


def test_the_window_covers_the_failure():
    assert record.a_trace_can_be_read_by_node_or_by_window()["the_window_covers_the_failure"]


def test_an_unknown_kind_is_refused():
    assert record.an_unknown_event_kind_is_refused()


def test_an_event_without_a_node_is_refused():
    assert record.an_event_without_a_node_is_refused()


def test_an_unknown_level_is_refused():
    assert record.an_unknown_level_is_refused()


def test_replaying_an_outline_is_refused():
    assert record.replaying_a_trace_with_no_messages_is_refused()


def test_a_run_of_no_ticks_is_refused():
    assert record.a_run_of_no_ticks_is_refused()


def test_the_level_table_covers_them_all():
    assert len(record.compare_the_levels()) == len(LEVELS)


def test_nothing_is_both_readable_and_complete():
    assert record.only_the_full_trace_is_both_readable_and_replayable_and_it_is_neither()[
        "nothing_is_both_readable_and_complete"
    ]


def test_the_outline_is_the_readable_one():
    assert record.only_the_full_trace_is_both_readable_and_replayable_and_it_is_neither()[
        "the_outline_is_the_readable_one"
    ]


def test_the_full_trace_is_the_complete_one():
    assert record.only_the_full_trace_is_both_readable_and_replayable_and_it_is_neither()[
        "the_full_trace_is_complete"
    ]


def test_the_summary_says_a_trace_replays():
    assert record.summarise()["a_trace_replays"]


def test_the_summary_says_recording_changes_nothing():
    assert record.summarise()["recording_changes_nothing"]


def test_an_event_summarises():
    assert Event(at=3, kind=ROLE, node="n0", detail="x").as_dict()["at"] == 3


def test_an_event_prints_its_node():
    assert "n0" in str(Event(at=3, kind=ROLE, node="n0", detail="x"))


def test_an_unknown_kind_raises():
    with pytest.raises(ConfigError):
        Event(at=1, kind="rumour", node="n0")


def test_a_negative_tick_raises():
    with pytest.raises(ConfigError):
        Event(at=-1, kind=ROLE, node="n0")


def test_an_event_without_a_node_raises():
    with pytest.raises(ConfigError):
        Event(at=1, kind=ROLE, node="")


def test_a_trace_records_events():
    made = Trace(seed=0, size=3)
    made.record(Event(at=1, kind=ROLE, node="n0"))
    assert len(made) == 1


def test_a_trace_filters_by_kind():
    made = Trace(seed=0, size=3)
    made.record(Event(at=1, kind=ROLE, node="n0"))
    made.record(Event(at=2, kind=COMMIT, node="n0"))
    assert len(made.of_kind(ROLE)) == 1


def test_a_trace_filters_by_node():
    made = Trace(seed=0, size=3)
    made.record(Event(at=1, kind=ROLE, node="n0"))
    made.record(Event(at=2, kind=ROLE, node="n1"))
    assert len(made.of_node("n1")) == 1


def test_a_trace_filters_by_window():
    made = Trace(seed=0, size=3)
    for tick in range(10):
        made.record(Event(at=tick, kind=ROLE, node="n0"))
    assert len(made.between(3, 6)) == 3


def test_a_trace_lists_its_nodes():
    made = Trace(seed=0, size=3)
    made.record(Event(at=1, kind=ROLE, node="n1"))
    made.record(Event(at=2, kind=ROLE, node="n0"))
    assert made.nodes == ("n1", "n0")


def test_a_trace_is_iterable():
    made = Trace(seed=0, size=3)
    made.record(Event(at=1, kind=ROLE, node="n0"))
    assert [one.node for one in made] == ["n0"]


def test_a_trace_summarises():
    made = Trace(seed=7, size=3)
    assert made.as_dict()["seed"] == 7


def test_a_level_keeps_only_its_kinds():
    made = capture(ticks=40, writes=1)
    assert {one.kind for one in made.at_level("outline")} <= set(LEVELS["outline"])


def test_an_unknown_level_raises():
    with pytest.raises(ConfigError):
        capture(ticks=20, writes=1).at_level("chatty")


def test_a_short_trace_renders_whole():
    made = Trace(seed=0, size=3)
    for tick in range(5):
        made.record(Event(at=tick, kind=ROLE, node="n0"))
    assert len(made.render(40).splitlines()) == 5


def test_a_long_trace_is_truncated_in_the_middle():
    made = Trace(seed=0, size=3)
    for tick in range(100):
        made.record(Event(at=tick, kind=ROLE, node="n0"))
    assert "more" in made.render(20)


def test_a_truncated_render_keeps_both_ends():
    made = Trace(seed=0, size=3)
    for tick in range(100):
        made.record(Event(at=tick, kind=ROLE, node="n0"))
    lines = made.render(20).splitlines()
    assert lines[0].strip().startswith("0") and lines[-1].strip().startswith("99")


def test_capturing_records_every_kind():
    assert {one.kind for one in capture(ticks=60)} == set(KINDS)


def test_capturing_records_the_tick_count():
    assert capture(ticks=60).ticks == 60


def test_capturing_a_zero_run_raises():
    with pytest.raises(ConfigError):
        capture(ticks=0)


def test_a_replay_reports_what_it_applied():
    assert replay(capture(ticks=60)).applied > 0


def test_a_matching_replay_is_truthy():
    assert replay(capture(ticks=60))


def test_a_mismatched_replay_is_falsy():
    assert not Replay(events=1, applied=1, mismatches=["something"])


def test_a_replay_summarises():
    assert replay(capture(ticks=60)).as_dict()["matched"]


def test_replaying_without_deliveries_raises():
    with pytest.raises(ConfigError):
        replay(capture(ticks=40).at_level("outline"))


def test_a_send_event_carries_its_message():
    made = capture(ticks=40)
    assert any(one.message is not None for one in made.of_kind(SEND))


def test_a_delivery_event_carries_its_message():
    made = capture(ticks=40)
    assert all(one.message is not None for one in made.of_kind(DELIVER))


def test_an_event_can_hold_a_message():
    made = Event(
        at=1,
        kind=DELIVER,
        node="n0",
        message=Vote(sender="n1", recipient="n0", term=2),
    )
    assert made.message.kind == "vote"


def test_there_are_four_kinds():
    assert len(KINDS) == 4


def test_every_level_is_a_subset_of_the_kinds():
    assert all(set(one) <= set(KINDS) for one in LEVELS.values())
