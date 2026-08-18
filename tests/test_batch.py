from __future__ import annotations

import pytest

from rsm import batch as shipping
from rsm.batch import (
    ENTRY_BYTES,
    MESSAGE_BYTES,
    PIPELINE_DEPTH,
    Shipment,
    ship,
)
from rsm.errors import ConfigError
from rsm.node import MAX_BATCH


def test_batching_removes_the_framing():
    assert shipping.batching_removes_the_per_message_overhead()["and_is_negligible_batched"]


def test_framing_dominates_unbatched():
    assert shipping.batching_removes_the_per_message_overhead()["framing_dominates_unbatched"]


def test_batching_saves_bytes():
    assert shipping.batching_removes_the_per_message_overhead()["bytes_saved"] > 0


def test_batching_cuts_round_trips():
    assert shipping.batching_does_nothing_for_the_round_trips_without_a_pipeline()[
        "batching_cut_them"
    ]


def test_batching_cannot_cut_below_one():
    assert shipping.batching_does_nothing_for_the_round_trips_without_a_pipeline()[
        "but_not_below_one"
    ]


def test_stop_and_wait_has_one_trip_per_message():
    assert shipping.batching_does_nothing_for_the_round_trips_without_a_pipeline()[
        "messages_equal_round_trips"
    ]


def test_pipelining_cuts_round_trips():
    assert shipping.pipelining_overlaps_the_round_trips()["it_cut_them"]


def test_pipelining_sends_the_same_messages():
    assert shipping.pipelining_overlaps_the_round_trips()["and_the_same_pipelined"]


def test_pipelining_sends_the_same_bytes():
    assert shipping.pipelining_overlaps_the_round_trips()["and_the_bytes_are_identical"]


def test_pipelining_cuts_by_about_the_depth():
    assert shipping.pipelining_overlaps_the_round_trips()["by_about_the_depth"] > 2


def test_batching_cuts_bytes():
    assert shipping.the_two_savings_are_independent()["batching_cuts_bytes"]


def test_pipelining_does_not_cut_bytes():
    assert shipping.the_two_savings_are_independent()["and_pipelining_does_not"]


def test_both_cut_round_trips():
    made = shipping.the_two_savings_are_independent()
    assert made["pipelining_cuts_round_trips"] and made["and_batching_does_too"]


def test_doing_both_gets_the_least_of_each():
    assert shipping.the_two_savings_are_independent()["which_is_the_least_of_each"]


def test_each_doubling_halves_the_overhead():
    assert shipping.the_batch_saving_never_stops_it_only_halves()[
        "each_doubling_roughly_halves_it"
    ]


def test_the_overhead_never_flattens():
    assert shipping.the_batch_saving_never_stops_it_only_halves()["it_never_flattens"]


def test_doubling_past_the_cap_still_saves():
    assert (
        shipping.the_batch_saving_never_stops_it_only_halves()[
            "and_doubling_past_it_still_saves"
        ]
        > 0
    )


def test_the_cap_is_about_memory():
    assert shipping.the_batch_saving_never_stops_it_only_halves()[
        "so_the_cap_is_about_memory_not_returns"
    ]


def test_a_real_leader_fills_the_batch():
    assert shipping.a_real_leader_batches_what_a_follower_is_missing()["it_filled_the_batch"]


def test_the_model_agrees_with_the_node():
    assert shipping.a_real_leader_batches_what_a_follower_is_missing()[
        "and_the_model_agrees_with_the_node"
    ]


def test_the_predicted_message_count_is_the_log_over_the_cap():
    assert shipping.a_real_leader_batches_what_a_follower_is_missing()[
        "which_is_the_log_over_the_cap"
    ]


def test_a_caught_up_follower_gets_a_heartbeat():
    assert shipping.a_caught_up_follower_gets_an_empty_batch()["it_is_a_heartbeat"]


def test_an_empty_shipment_has_no_messages():
    assert shipping.a_caught_up_follower_gets_an_empty_batch()["and_the_model_says_none"]


def test_an_empty_shipment_has_no_per_entry_cost():
    assert shipping.a_caught_up_follower_gets_an_empty_batch()[
        "which_is_zero_rather_than_infinite"
    ]


def test_a_deeper_pipeline_is_fewer_round_trips():
    assert shipping.a_deeper_pipeline_sends_further_ahead_of_what_was_acknowledged()[
        "deeper_is_fewer_round_trips"
    ]


def test_the_outstanding_count_is_the_depth():
    assert shipping.a_deeper_pipeline_sends_further_ahead_of_what_was_acknowledged()[
        "which_is_the_depth"
    ]


def test_the_outstanding_count_is_bounded():
    assert shipping.a_deeper_pipeline_sends_further_ahead_of_what_was_acknowledged()[
        "and_it_is_bounded"
    ]


def test_a_zero_batch_is_refused():
    assert shipping.a_zero_batch_is_refused()


def test_a_zero_depth_is_refused():
    assert shipping.a_zero_depth_is_refused()


def test_a_negative_entry_count_is_refused():
    assert shipping.a_negative_entry_count_is_refused()


def test_the_setting_table_covers_four():
    assert len(shipping.compare_the_settings()) == 4


def test_batching_wins_on_round_trips_here():
    assert shipping.batching_is_the_larger_of_the_two_savings_here()[
        "batching_wins_on_round_trips"
    ]


def test_pipelining_saves_no_bytes_here():
    assert shipping.batching_is_the_larger_of_the_two_savings_here()[
        "and_pipelining_saves_no_bytes"
    ]


def test_the_comparison_is_about_this_cost_model():
    assert shipping.batching_is_the_larger_of_the_two_savings_here()[
        "which_is_a_fact_about_this_cost_model"
    ]


def test_the_summary_says_the_model_matches_the_node():
    assert shipping.summarise()["the_model_matches_the_node"]


def test_the_summary_says_the_saving_never_flattens():
    assert shipping.summarise()["the_saving_never_flattens"]


def test_shipping_nothing_costs_nothing():
    assert ship(0, batch=8).messages == 0


def test_shipping_one_entry_costs_one_message():
    assert ship(1, batch=8).messages == 1


def test_shipping_rounds_up():
    assert ship(9, batch=8).messages == 2


def test_shipping_exactly_fills():
    assert ship(16, batch=8).messages == 2


def test_a_shipment_reports_its_bytes():
    made = ship(10, batch=10)
    assert made.nbytes == MESSAGE_BYTES + 10 * ENTRY_BYTES


def test_a_shipment_reports_its_overhead():
    made = ship(1, batch=1)
    assert made.overhead == MESSAGE_BYTES / (MESSAGE_BYTES + ENTRY_BYTES)


def test_an_empty_shipment_has_no_overhead():
    assert ship(0, batch=8).overhead == 0.0


def test_a_shipment_reports_its_per_entry_cost():
    made = ship(10, batch=10)
    assert made.per_entry == made.nbytes / 10


def test_a_shipment_summarises():
    assert ship(10, batch=5).as_dict()["messages"] == 2


def test_a_deeper_pipeline_needs_fewer_trips():
    assert ship(100, batch=1, depth=4).round_trips < ship(100, batch=1, depth=1).round_trips


def test_a_depth_beyond_the_messages_gives_one_trip():
    assert ship(3, batch=1, depth=99).round_trips == 1


def test_a_zero_batch_raises():
    with pytest.raises(ConfigError):
        ship(10, batch=0)


def test_a_zero_depth_raises():
    with pytest.raises(ConfigError):
        ship(10, batch=1, depth=0)


def test_a_negative_batch_on_a_shipment_raises():
    with pytest.raises(ConfigError):
        Shipment(entries=1, messages=1, round_trips=1, batch=0)


def test_a_negative_entry_count_raises():
    with pytest.raises(ConfigError):
        Shipment(entries=-1, messages=0, round_trips=0, batch=1)


def test_the_pipeline_depth_is_more_than_one():
    assert PIPELINE_DEPTH > 1


def test_the_message_and_entry_sizes_are_set():
    assert MESSAGE_BYTES > 0 and ENTRY_BYTES > 0


def test_the_batch_cap_matches_the_node():
    assert ship(MAX_BATCH, batch=MAX_BATCH).messages == 1
