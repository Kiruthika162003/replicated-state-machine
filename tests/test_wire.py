from __future__ import annotations

import pytest

from rsm import wire as codec
from rsm.cluster import Cluster
from rsm.errors import ConfigError, NetworkError
from rsm.log import Entry
from rsm.rpc import Append, Appended, Message, RequestVote, Vote
from rsm.wire import (
    ASSUMED_ENTRY_BYTES,
    ASSUMED_MESSAGE_BYTES,
    HEADER,
    MAGIC,
    MAX_BODY,
    VERSION,
    Traffic,
    decode,
    decode_one,
    encode,
    frame_all,
    measure,
    read_all,
)


def test_every_kind_round_trips():
    assert codec.every_message_survives_the_round_trip()["all_identical"]


def test_every_kind_is_covered():
    assert codec.every_message_survives_the_round_trip()["every_kind_covered"]


def test_the_smallest_message_is_small():
    assert codec.every_message_survives_the_round_trip()["smallest"] < 40


def test_the_entry_cost_is_constant_for_one_command():
    assert codec.the_entry_cost_is_a_constant_only_because_the_commands_are()[
        "it_is_constant_here"
    ]


def test_the_entry_cost_is_near_the_estimate():
    assert codec.the_entry_cost_is_a_constant_only_because_the_commands_are()[
        "and_within_a_tenth_of_it"
    ]


def test_a_long_command_costs_much_more():
    made = codec.the_entry_cost_is_a_constant_only_because_the_commands_are()
    assert made["which_is_this_many_times_the_estimate"] > 2


def test_the_constant_stands_in_for_a_function():
    assert codec.the_entry_cost_is_a_constant_only_because_the_commands_are()[
        "so_the_constant_stands_in_for_a_function"
    ]


def test_the_estimate_is_high():
    assert codec.the_byte_estimate_is_seven_percent_high_over_a_whole_run()[
        "the_estimate_is_high"
    ]


def test_the_estimate_is_within_a_tenth():
    assert codec.the_byte_estimate_is_seven_percent_high_over_a_whole_run()[
        "but_within_a_tenth"
    ]


def test_the_estimate_error_does_not_move_with_size():
    assert codec.the_byte_estimate_is_seven_percent_high_over_a_whole_run()[
        "and_the_same_at_both_sizes"
    ]


def test_votes_are_a_rounding_error():
    assert codec.the_byte_estimate_is_seven_percent_high_over_a_whole_run()[
        "which_is_under_a_percent"
    ]


def test_replication_is_nearly_all_the_traffic():
    assert codec.the_traffic_is_appends_and_their_replies_and_nothing_else()[
        "it_is_nearly_everything"
    ]


def test_appends_outweigh_their_replies():
    assert codec.the_traffic_is_appends_and_their_replies_and_nothing_else()[
        "appends_beat_replies"
    ]


def test_no_snapshot_is_sent_in_a_short_run():
    assert codec.the_traffic_is_appends_and_their_replies_and_nothing_else()[
        "and_no_snapshot_was_sent"
    ]


def test_batching_is_cheaper_on_the_wire():
    assert codec.a_batched_append_costs_less_than_the_same_entries_apart()[
        "batching_is_cheaper"
    ]


def test_the_model_and_the_codec_agree():
    assert codec.a_batched_append_costs_less_than_the_same_entries_apart()[
        "the_model_and_the_codec_agree"
    ]


def test_batching_saves_about_two_and_a_half_times():
    made = codec.a_batched_append_costs_less_than_the_same_entries_apart()
    assert made["by_this_factor"] > 2


def test_every_truncated_frame_is_refused():
    assert codec.a_truncated_frame_is_refused_rather_than_waited_on()[
        "every_prefix_was_refused"
    ]


def test_the_whole_frame_still_decodes():
    assert codec.a_truncated_frame_is_refused_rather_than_waited_on()[
        "and_the_whole_frame_decodes"
    ]


def test_a_corrupt_length_is_refused():
    assert codec.a_corrupt_length_cannot_ask_for_a_gigabyte()


def test_a_corrupt_count_is_refused():
    assert codec.a_corrupt_count_cannot_ask_for_more_entries_than_fit()


def test_another_protocol_is_refused():
    assert codec.a_frame_from_another_protocol_is_refused()


def test_a_later_version_is_refused():
    assert codec.a_frame_from_a_later_version_is_refused()


def test_trailing_bytes_are_refused():
    assert codec.trailing_bytes_after_a_frame_are_refused()


def test_an_unknown_kind_code_is_refused():
    assert codec.an_unknown_kind_code_is_refused()


def test_an_oversized_message_is_refused():
    assert codec.a_message_too_long_to_frame_is_refused()


def test_a_stream_reads_back_the_same_count():
    assert codec.a_stream_of_frames_reads_back_in_order()["the_same_count"]


def test_a_stream_reads_back_in_order():
    assert codec.a_stream_of_frames_reads_back_in_order()["in_the_same_order"]


def test_the_stream_sizes_add_up():
    assert codec.a_stream_of_frames_reads_back_in_order()["and_the_sizes_add_up"]


def test_the_kind_table_covers_six():
    assert len(codec.compare_the_kinds()) == 6


def test_every_kind_is_mispriced():
    assert codec.the_estimate_is_wrong_per_message_and_right_in_aggregate()["every_kind_is_off"]


def test_the_worst_kind_is_off_by_double():
    assert codec.the_estimate_is_wrong_per_message_and_right_in_aggregate()[
        "and_it_is_off_by_more_than_double"
    ]


def test_the_whole_run_is_within_a_tenth():
    assert codec.the_estimate_is_wrong_per_message_and_right_in_aggregate()[
        "which_is_within_a_tenth"
    ]


def test_the_worst_kind_is_rare():
    assert codec.the_estimate_is_wrong_per_message_and_right_in_aggregate()[
        "because_the_worst_kind_is_rare"
    ]


def test_the_summary_says_every_kind_round_trips():
    assert codec.summarise()["every_kind_round_trips"]


def test_the_summary_reports_the_header_size():
    assert codec.summarise()["header_bytes"] == HEADER.size


def test_the_summary_reports_the_estimate_error():
    assert codec.summarise()["the_estimate_is_high_by"] > 1.0


def test_a_vote_round_trips():
    made = Vote(sender="n0", recipient="n1", term=4, granted=True)
    assert decode(encode(made)) == made


def test_a_request_vote_round_trips():
    made = RequestVote(sender="n0", recipient="n1", term=4, last_index=3, last_term=2)
    assert decode(encode(made)) == made


def test_an_appended_round_trips():
    made = Appended(sender="n1", recipient="n0", term=4, success=True, match_index=7)
    assert decode(encode(made)) == made


def test_an_empty_append_round_trips():
    made = Append(sender="n0", recipient="n1", term=4, previous_index=3, previous_term=2)
    assert decode(encode(made)).entries == ()


def test_an_append_keeps_its_entries():
    made = Append(
        sender="n0",
        recipient="n1",
        term=4,
        entries=(Entry(index=1, term=1, command="a"), Entry(index=2, term=1, command="b")),
    )
    assert [one.command for one in decode(encode(made)).entries] == ["a", "b"]


def test_an_entry_keeps_its_index_and_term():
    made = Append(sender="n0", recipient="n1", term=4, entries=(Entry(index=9, term=3),))
    back = decode(encode(made)).entries[0]
    assert back.index == 9 and back.term == 3


def test_an_empty_command_comes_back_as_none():
    made = Append(sender="n0", recipient="n1", term=4, entries=(Entry(index=9, term=3),))
    assert decode(encode(made)).entries[0].command is None


def test_a_frame_starts_with_the_magic():
    assert HEADER.unpack_from(encode(Vote(sender="a", recipient="b", term=1)), 0)[0] == MAGIC


def test_a_frame_carries_the_version():
    assert HEADER.unpack_from(encode(Vote(sender="a", recipient="b", term=1)), 0)[1] == VERSION


def test_a_frame_length_matches_the_body():
    raw = encode(Vote(sender="a", recipient="b", term=1))
    assert HEADER.unpack_from(raw, 0)[2] == len(raw) - HEADER.size


def test_decode_one_reports_what_it_used():
    raw = encode(Vote(sender="a", recipient="b", term=1))
    assert decode_one(raw + b"more")[1] == len(raw)


def test_an_empty_buffer_is_refused():
    with pytest.raises(NetworkError):
        decode(b"")


def test_a_header_without_a_body_is_refused():
    with pytest.raises(NetworkError):
        decode(HEADER.pack(MAGIC, VERSION, 20))


def test_an_unknown_message_kind_is_refused():
    with pytest.raises(ConfigError):
        encode(Message(kind="gossip", sender="a", recipient="b", term=1))


def test_a_body_past_the_limit_is_refused():
    with pytest.raises(NetworkError):
        decode(HEADER.pack(MAGIC, VERSION, MAX_BODY + 1) + b"x")


def test_framing_nothing_gives_nothing():
    assert frame_all([]) == b""


def test_reading_nothing_gives_nothing():
    assert read_all(b"") == []


def test_traffic_starts_empty():
    assert Traffic().as_dict()["messages"] == 0


def test_empty_traffic_has_no_error():
    assert Traffic().error == 0.0


def test_empty_traffic_has_no_average():
    assert Traffic().per_message == 0.0


def test_traffic_counts_a_message():
    made = Traffic()
    made.record(Vote(sender="a", recipient="b", term=1))
    assert made.messages == 1 and made.real > 0


def test_traffic_charges_the_estimate():
    made = Traffic()
    made.record(Vote(sender="a", recipient="b", term=1))
    assert made.assumed == ASSUMED_MESSAGE_BYTES


def test_traffic_charges_for_entries():
    made = Traffic()
    made.record(
        Append(
            sender="a", recipient="b", term=1, entries=(Entry(index=1, term=1, command="x"),)
        )
    )
    assert made.assumed == ASSUMED_MESSAGE_BYTES + ASSUMED_ENTRY_BYTES


def test_measuring_a_cluster_sees_messages():
    assert measure(Cluster(size=3, seed=2), ticks=40, writes=2).messages > 0


def test_measuring_a_cluster_reports_kinds():
    assert measure(Cluster(size=3, seed=2), ticks=40, writes=2).by_kind


def test_measuring_restores_the_network():
    made = Cluster(size=3, seed=2)
    measure(made, ticks=20, writes=1)
    assert "send" not in made.net.__dict__
