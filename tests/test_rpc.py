from __future__ import annotations

import pytest

from rsm import rpc as calls
from rsm.errors import ConfigError
from rsm.log import NO_INDEX, NO_TERM, Entry
from rsm.rpc import (
    AHEAD,
    APPEND,
    APPENDED,
    CURRENT,
    INSTALL_SNAPSHOT,
    INSTALLED,
    KINDS,
    REPLIES,
    REQUEST_VOTE,
    STALE,
    VOTE,
    Append,
    Appended,
    Installed,
    InstallSnapshot,
    Message,
    RequestVote,
    Vote,
    term_check,
)


def test_a_later_term_is_always_ahead():
    assert calls.a_higher_term_always_wins()["a_later_term_is_always_ahead"]


def test_an_equal_term_is_current():
    assert calls.a_higher_term_always_wins()["an_equal_term_is_current"]


def test_an_earlier_term_is_stale():
    assert calls.a_higher_term_always_wins()["an_earlier_term_is_stale"]


def test_the_kind_never_changes_the_answer():
    assert calls.a_higher_term_always_wins()["and_the_kind_never_matters"]


def test_an_equal_term_is_not_a_step_down():
    assert calls.an_equal_term_is_not_a_reason_to_step_down()["an_equal_term_is_current"]


def test_only_a_later_term_is_ahead():
    assert calls.an_equal_term_is_not_a_reason_to_step_down()["and_only_a_later_one_is_ahead"]


def test_the_two_cases_are_different_answers():
    assert calls.an_equal_term_is_not_a_reason_to_step_down()["they_are_different_answers"]


def test_a_stale_message_is_recognised():
    assert calls.a_stale_message_is_refused_with_the_current_term()["it_is_stale"]


def test_a_refusal_carries_the_current_term():
    assert calls.a_stale_message_is_refused_with_the_current_term()[
        "the_refusal_carries_the_current_term"
    ]


def test_one_round_trip_catches_a_stale_node_up():
    assert calls.a_stale_message_is_refused_with_the_current_term()["so_one_trip_catches_it_up"]


def test_a_heartbeat_carries_no_entries():
    assert calls.a_heartbeat_is_an_append_with_no_entries()["a_beat_has_no_entries"]


def test_an_append_with_entries_is_not_a_heartbeat():
    assert calls.a_heartbeat_is_an_append_with_no_entries()["and_one_with_entries_is_not"]


def test_both_carry_the_consistency_check():
    assert calls.a_heartbeat_is_an_append_with_no_entries()["both_carry_the_consistency_check"]


def test_a_heartbeat_does_not_move_the_follower():
    assert calls.a_heartbeat_is_an_append_with_no_entries()[
        "a_beat_leaves_the_follower_where_it_was"
    ]


def test_a_bare_refusal_names_no_term():
    assert calls.a_refusal_carries_what_the_leader_needs_to_back_up()[
        "a_bare_refusal_names_no_term"
    ]


def test_a_detailed_refusal_names_its_term():
    assert calls.a_refusal_carries_what_the_leader_needs_to_back_up()["the_detailed_one_does"]


def test_a_detailed_refusal_names_where_the_term_starts():
    assert calls.a_refusal_carries_what_the_leader_needs_to_back_up()[
        "and_names_where_that_term_starts"
    ]


def test_a_match_index_is_idempotent():
    assert calls.a_successful_append_reports_a_match_rather_than_a_count()[
        "applying_it_twice_changes_nothing"
    ]


def test_an_old_reply_does_not_move_the_leader_back():
    assert calls.a_successful_append_reports_a_match_rather_than_a_count()[
        "and_an_old_reply_after_a_new_one_does_not_go_backwards"
    ]


def test_a_message_to_itself_is_refused():
    assert calls.a_message_to_itself_is_refused()


def test_an_unknown_kind_is_refused():
    assert calls.a_message_of_an_unknown_kind_is_refused()


def test_a_message_without_a_term_is_refused():
    assert calls.a_message_without_a_term_is_refused()


def test_a_message_cannot_be_altered():
    assert calls.a_message_cannot_be_altered_after_it_is_sent()


def test_the_kind_table_covers_every_kind():
    assert len(calls.compare_the_kinds()) == len(KINDS)


def test_every_kind_carries_a_term():
    assert calls.every_kind_carries_a_term()["they_all_carry_a_term"]


def test_the_requests_and_replies_pair_up():
    assert calls.every_kind_carries_a_term()["and_they_pair_up"]


def test_there_are_three_replies():
    assert calls.every_kind_carries_a_term()["replies"] == 3


def test_the_summary_says_a_later_term_wins():
    assert calls.summarise()["a_later_term_always_wins"]


def test_the_summary_says_messages_are_frozen():
    assert calls.summarise()["messages_are_frozen"]


def test_there_are_six_kinds():
    assert len(KINDS) == 6


def test_three_kinds_are_replies():
    assert len(REPLIES) == 3


def test_every_reply_is_a_kind():
    assert all(one in KINDS for one in REPLIES)


def test_a_message_knows_its_route():
    made = Message(kind=APPEND, sender="a", recipient="b", term=2)
    assert made.sender == "a" and made.recipient == "b"


def test_a_message_summarises():
    made = Message(kind=APPEND, sender="a", recipient="b", term=2)
    assert made.as_dict()["kind"] == APPEND


def test_a_message_prints_its_route_and_term():
    made = Message(kind=APPEND, sender="a", recipient="b", term=2)
    assert str(made) == "a->b append@2"


def test_a_reply_knows_it_is_one():
    assert Vote(sender="b", recipient="a", term=2).is_reply


def test_a_request_knows_it_is_not():
    assert not RequestVote(sender="a", recipient="b", term=2).is_reply


def test_a_vote_request_carries_its_log():
    made = RequestVote(sender="a", recipient="b", term=3, last_index=9, last_term=2)
    assert made.last_index == 9 and made.last_term == 2


def test_a_vote_request_defaults_to_the_empty_log():
    made = RequestVote(sender="a", recipient="b", term=3)
    assert made.last_index == NO_INDEX and made.last_term == NO_TERM


def test_a_vote_request_can_be_a_pre_vote():
    assert RequestVote(sender="a", recipient="b", term=3, pre_vote=True).pre_vote


def test_a_vote_carries_its_answer():
    assert Vote(sender="b", recipient="a", term=3, granted=True).granted


def test_a_vote_defaults_to_refusing():
    assert not Vote(sender="b", recipient="a", term=3).granted


def test_an_append_carries_its_entries():
    one = Entry(term=3, index=8, command="x")
    made = Append(sender="a", recipient="b", term=3, entries=(one,))
    assert made.entries == (one,)


def test_an_append_carries_a_commit_index():
    made = Append(sender="a", recipient="b", term=3, commit_index=6)
    assert made.commit_index == 6


def test_an_empty_append_is_a_heartbeat():
    assert Append(sender="a", recipient="b", term=3).is_heartbeat


def test_an_appends_last_index_is_its_last_entry():
    one = Entry(term=3, index=8)
    made = Append(sender="a", recipient="b", term=3, previous_index=7, entries=(one,))
    assert made.last_index == 8


def test_a_heartbeats_last_index_is_its_previous():
    made = Append(sender="a", recipient="b", term=3, previous_index=7)
    assert made.last_index == 7


def test_an_appended_reports_success():
    assert Appended(sender="b", recipient="a", term=3, success=True).success


def test_an_appended_defaults_to_refusing():
    assert not Appended(sender="b", recipient="a", term=3).success


def test_an_appended_carries_a_match_index():
    assert Appended(sender="b", recipient="a", term=3, match_index=11).match_index == 11


def test_an_appended_carries_a_conflict():
    made = Appended(sender="b", recipient="a", term=3, conflict_term=2, conflict_index=5)
    assert made.conflict_term == 2 and made.conflict_index == 5


def test_a_snapshot_carries_its_boundary():
    made = InstallSnapshot(sender="a", recipient="b", term=4, last_index=40, last_term=3)
    assert made.last_index == 40 and made.last_term == 3


def test_a_snapshot_carries_state():
    made = InstallSnapshot(sender="a", recipient="b", term=4, state={"a": 1})
    assert made.state == {"a": 1}


def test_a_snapshot_carries_its_membership():
    made = InstallSnapshot(sender="a", recipient="b", term=4, members=("a", "b"))
    assert made.members == ("a", "b")


def test_an_installed_confirms_the_index():
    assert Installed(sender="b", recipient="a", term=4, last_index=40).last_index == 40


def test_an_installed_is_a_reply():
    assert Installed(sender="b", recipient="a", term=4).is_reply


def test_a_snapshot_is_not_a_reply():
    assert not InstallSnapshot(sender="a", recipient="b", term=4).is_reply


def test_the_snapshot_kinds_are_named():
    assert INSTALL_SNAPSHOT in KINDS and INSTALLED in REPLIES


def test_the_vote_kinds_are_named():
    assert REQUEST_VOTE in KINDS and VOTE in REPLIES


def test_the_append_kinds_are_named():
    assert APPEND in KINDS and APPENDED in REPLIES


def test_a_lower_term_checks_as_stale():
    made = Message(kind=APPEND, sender="a", recipient="b", term=2)
    assert term_check(5, made) == STALE


def test_an_equal_term_checks_as_current():
    made = Message(kind=APPEND, sender="a", recipient="b", term=5)
    assert term_check(5, made) == CURRENT


def test_a_higher_term_checks_as_ahead():
    made = Message(kind=APPEND, sender="a", recipient="b", term=9)
    assert term_check(5, made) == AHEAD


def test_a_message_needs_keywords():
    with pytest.raises(TypeError):
        Message(APPEND, "a", "b", 1)


def test_a_reply_to_itself_is_refused():
    with pytest.raises(ConfigError):
        Vote(sender="a", recipient="a", term=1)
