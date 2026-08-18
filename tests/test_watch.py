from __future__ import annotations

import pytest

from rsm import watch as feeds
from rsm.errors import ConfigError
from rsm.watch import AWAY, EVENTS, Event, Feed, Watcher


def test_delivery_is_ordered():
    assert feeds.a_watch_delivers_in_log_order_because_there_is_no_other()[
        "every_delivery_was_ordered"
    ]


def test_two_watchers_agree_on_the_order():
    assert feeds.a_watch_delivers_in_log_order_because_there_is_no_other()["they_saw_the_same"]


def test_a_filtered_watcher_sees_only_its_key():
    assert feeds.a_watch_delivers_in_log_order_because_there_is_no_other()[
        "and_only_its_own_key"
    ]


def test_resuming_from_now_misses_events():
    assert feeds.resuming_from_now_loses_everything_that_happened_while_away()[
        "and_the_naive_one_did_not"
    ]


def test_resuming_from_an_index_misses_nothing():
    assert feeds.resuming_from_now_loses_everything_that_happened_while_away()[
        "the_careful_one_saw_everything"
    ]


def test_the_gap_is_invisible_in_the_sequence():
    assert feeds.resuming_from_now_loses_everything_that_happened_while_away()[
        "so_the_gap_is_invisible_in_the_sequence"
    ]


def test_both_resumptions_stay_ordered():
    assert feeds.resuming_from_now_loses_everything_that_happened_while_away()[
        "both_were_ordered"
    ]


def test_a_late_index_survives_compaction():
    assert feeds.a_watcher_that_resumes_from_a_compacted_index_cannot_be_served()[
        "the_watcher_can_resume_from_the_late_one"
    ]


def test_an_early_index_does_not():
    assert feeds.a_watcher_that_resumes_from_a_compacted_index_cannot_be_served()[
        "and_not_from_the_early_one"
    ]


def test_the_state_does_not_say_what_happened():
    assert feeds.a_watcher_that_resumes_from_a_compacted_index_cannot_be_served()[
        "which_does_not_say_what_happened"
    ]


def test_the_fan_out_is_a_product():
    assert feeds.the_fan_out_is_the_watchers_times_the_events()["it_is_the_product"]


def test_filtering_reduces_the_fan_out():
    assert feeds.the_fan_out_is_the_watchers_times_the_events()["filtering_helped"]


def test_filtering_helps_by_the_key_count():
    made = feeds.the_fan_out_is_the_watchers_times_the_events()
    assert made["by_this_factor"] > 1


def test_the_cluster_committed_the_same_either_way():
    assert feeds.the_fan_out_is_the_watchers_times_the_events()[
        "and_the_cluster_committed_the_same"
    ]


def test_an_event_without_a_key_is_refused():
    assert feeds.an_event_without_a_key_is_refused()


def test_an_event_at_index_zero_is_refused():
    assert feeds.an_event_before_the_first_index_is_refused()


def test_a_repeated_watcher_name_is_refused():
    assert feeds.a_repeated_watcher_name_is_refused()


def test_a_negative_resume_index_is_refused():
    assert feeds.a_negative_resume_index_is_refused()


def test_an_event_is_delivered_once():
    assert feeds.a_watcher_never_sees_an_event_twice()["and_only_once"]


def test_an_older_event_is_refused():
    assert feeds.a_watcher_never_sees_an_event_twice()["an_older_event_is_refused"]


def test_a_newer_event_is_taken():
    assert feeds.a_watcher_never_sees_an_event_twice()["and_a_newer_one_is_taken"]


def test_the_resumption_table_covers_three():
    assert len(feeds.compare_the_resumptions()) == 3


def test_every_resumption_is_ordered():
    assert feeds.only_an_index_resume_is_complete_and_all_three_look_the_same()[
        "every_row_is_ordered"
    ]


def test_resuming_from_now_is_incomplete():
    assert feeds.only_an_index_resume_is_complete_and_all_three_look_the_same()[
        "and_from_now_is_not"
    ]


def test_the_client_keeps_the_index_anyway():
    assert feeds.only_an_index_resume_is_complete_and_all_three_look_the_same()[
        "so_the_client_keeps_the_index_anyway"
    ]


def test_the_summary_says_delivery_is_ordered():
    assert feeds.summarise()["delivery_is_ordered"]


def test_the_summary_says_the_gap_is_invisible():
    assert feeds.summarise()["and_the_gap_is_invisible"]


def test_an_event_summarises():
    assert Event(index=3, key="k", value=1).as_dict()["index"] == 3


def test_an_event_prints_itself():
    assert "k = 1" in str(Event(index=3, key="k", value=1))


def test_an_event_needs_a_key():
    with pytest.raises(ConfigError):
        Event(index=1, key="", value=1)


def test_an_event_needs_a_real_index():
    with pytest.raises(ConfigError):
        Event(index=0, key="k", value=1)


def test_a_watcher_with_no_key_wants_everything():
    assert Watcher(name="w").wants(Event(index=1, key="anything", value=1))


def test_a_filtered_watcher_wants_its_key():
    assert Watcher(name="w", key="k").wants(Event(index=1, key="k", value=1))


def test_a_filtered_watcher_refuses_another():
    assert not Watcher(name="w", key="k").wants(Event(index=1, key="j", value=1))


def test_a_disconnected_watcher_takes_nothing():
    made = Watcher(name="w", connected=False)
    assert not made.deliver(Event(index=1, key="k", value=1))


def test_a_watcher_advances_its_index():
    made = Watcher(name="w")
    made.deliver(Event(index=7, key="k", value=1))
    assert made.at == 7


def test_a_watcher_refuses_an_index_it_passed():
    made = Watcher(name="w", at=9)
    assert not made.deliver(Event(index=5, key="k", value=1))


def test_an_empty_watcher_is_ordered():
    assert Watcher(name="w").ordered


def test_a_watcher_summarises():
    assert Watcher(name="named").as_dict()["watcher"] == "named"


def test_an_unfiltered_watcher_says_everything():
    assert Watcher(name="w").as_dict()["key"] == "everything"


def test_a_feed_registers_watchers():
    made = Feed()
    made.add(Watcher(name="w"))
    assert len(made.watchers) == 1


def test_a_feed_refuses_a_repeated_name():
    made = Feed()
    made.add(Watcher(name="w"))
    with pytest.raises(ConfigError):
        made.add(Watcher(name="w"))


def test_a_feed_publishes_to_everyone():
    made = Feed()
    made.add(Watcher(name="a"))
    made.add(Watcher(name="b"))
    assert made.publish(Event(index=1, key="k", value=1)) == 2


def test_a_feed_skips_uninterested_watchers():
    made = Feed()
    made.add(Watcher(name="a", key="j"))
    assert made.publish(Event(index=1, key="k", value=1)) == 0


def test_a_feed_keeps_its_events():
    made = Feed()
    made.publish(Event(index=1, key="k", value=1))
    assert len(made.events) == 1


def test_a_feed_serves_events_since_an_index():
    made = Feed()
    for one in range(1, 6):
        made.publish(Event(index=one, key="k", value=one))
    assert [one.index for one in made.since(3)] == [4, 5]


def test_a_feed_since_the_end_is_empty():
    made = Feed()
    made.publish(Event(index=1, key="k", value=1))
    assert made.since(9) == []


def test_a_feed_since_a_negative_index_raises():
    with pytest.raises(ConfigError):
        Feed().since(-2)


def test_a_feed_reports_its_fan_out():
    made = Feed()
    made.add(Watcher(name="a"))
    made.add(Watcher(name="b"))
    made.publish(Event(index=1, key="k", value=1))
    assert made.as_dict()["fan_out"] == 2.0


def test_an_empty_feed_has_no_fan_out_error():
    assert Feed().as_dict()["fan_out"] == 0.0


def test_the_event_count_is_worth_watching():
    assert EVENTS >= 20


def test_the_away_time_covers_several_events():
    assert AWAY > 10
