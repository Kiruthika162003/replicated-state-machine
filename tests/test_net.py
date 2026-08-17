from __future__ import annotations

import pytest

from rsm import net as wire
from rsm.errors import ConfigError, UnknownNode
from rsm.log import Entry
from rsm.net import (
    BASE_DELAY,
    BY_SEND_ORDER,
    Conditions,
    Counts,
    InFlight,
    Network,
)
from rsm.rpc import Append


def test_the_same_seed_repeats():
    assert wire.the_same_seed_gives_the_same_run()["they_are_identical"]


def test_the_repeat_check_compared_a_real_run():
    assert wire.the_same_seed_gives_the_same_run()["and_it_is_not_trivially_empty"]


def test_the_repeat_check_found_one_transcript():
    assert wire.the_same_seed_gives_the_same_run()["distinct_transcripts"] == 1


def test_different_seeds_give_different_runs():
    assert wire.a_different_seed_gives_a_different_run()["they_all_differ"]


def test_different_seeds_lose_different_amounts():
    assert wire.a_different_seed_gives_a_different_run()["and_the_counts_differ_too"]


def test_the_loss_rate_is_close_to_configured():
    assert wire.the_loss_rate_is_what_it_says()["it_is_close"]


def test_the_loss_rate_error_is_small():
    assert wire.the_loss_rate_is_what_it_says()["error"] < 0.01


def test_loss_does_not_come_from_a_partition():
    assert wire.the_loss_rate_is_what_it_says()["nothing_was_dropped_by_partition"]


def test_a_reliable_link_loses_nothing():
    assert wire.a_reliable_link_delivers_everything_in_order()["nothing_was_lost"]


def test_a_reliable_link_keeps_the_order():
    assert wire.a_reliable_link_delivers_everything_in_order()["and_the_order_is_unchanged"]


def test_a_reliable_link_says_it_is_reliable():
    assert wire.a_reliable_link_delivers_everything_in_order()["the_link_is_reliable"]


def test_jitter_reorders():
    assert wire.jitter_is_what_reorders_messages()["jitter_reorders"]


def test_loss_does_not_reorder():
    assert wire.jitter_is_what_reorders_messages()["and_loss_does_not"]


def test_loss_still_drops():
    assert wire.jitter_is_what_reorders_messages()["loss_still_dropped_some"]


def test_jitter_drops_nothing():
    assert wire.jitter_is_what_reorders_messages()["jitter_dropped_nothing"]


def test_nothing_crosses_a_partition():
    assert wire.a_partition_drops_what_crosses_it()["nothing_crossed"]


def test_the_sides_of_a_partition_still_work():
    assert wire.a_partition_drops_what_crosses_it()["and_the_sides_still_work"]


def test_a_partition_counts_its_drops():
    assert wire.a_partition_drops_what_crosses_it()["dropped_by_partition"] > 0


def test_a_partition_drop_is_not_a_loss_drop():
    assert wire.a_partition_drops_what_crosses_it()["dropped_by_loss"] == 0


def test_healing_delivers_nothing_that_was_dropped():
    assert wire.healing_does_not_deliver_what_was_dropped()["nothing_arrived_on_healing"]


def test_partitioned_messages_are_gone_not_queued():
    assert wire.healing_does_not_deliver_what_was_dropped()["they_are_gone_not_queued"]


def test_a_retry_after_healing_arrives():
    assert wire.healing_does_not_deliver_what_was_dropped()["a_retry_after_healing_arrives"]


def test_the_retry_is_the_message_that_arrives():
    assert wire.healing_does_not_deliver_what_was_dropped()["and_it_is_the_retry"]


def test_messages_due_together_land_together():
    assert wire.messages_due_together_arrive_in_send_order()["they_all_landed_together"]


def test_messages_due_together_arrive_in_send_order():
    assert wire.messages_due_together_arrive_in_send_order()["in_send_order"]


def test_the_tie_break_is_named():
    assert wire.messages_due_together_arrive_in_send_order()["the_tie_break"] == BY_SEND_ORDER


def test_the_counts_add_up():
    assert wire.the_cost_is_counted_not_timed()["the_counts_add_up"]


def test_the_counts_are_by_kind():
    assert wire.the_cost_is_counted_not_timed()["by_kind"]


def test_carrying_entries_costs_more():
    assert wire.an_append_with_entries_costs_more_to_send()["carrying_entries_costs_more"]


def test_batching_beats_separate_messages():
    assert wire.an_append_with_entries_costs_more_to_send()["ten_in_one_beats_ten_messages"]


def test_the_per_entry_cost_is_separate():
    assert wire.an_append_with_entries_costs_more_to_send()["per_entry"] == 32


def test_an_unknown_recipient_is_refused():
    assert wire.a_message_to_an_unknown_node_is_refused()


def test_a_partition_over_an_unknown_node_is_refused():
    assert wire.a_partition_naming_an_unknown_node_is_refused()


def test_a_partition_leaving_a_node_out_is_refused():
    assert wire.a_partition_that_leaves_a_node_out_is_refused()


def test_a_partition_with_a_node_on_two_sides_is_refused():
    assert wire.a_partition_putting_a_node_on_two_sides_is_refused()


def test_a_repeated_name_is_refused():
    assert wire.a_repeated_node_name_is_refused()


def test_an_empty_network_is_refused():
    assert wire.an_empty_network_is_refused()


def test_an_impossible_loss_rate_is_refused():
    assert wire.an_impossible_loss_rate_is_refused()


def test_a_backwards_delay_range_is_refused():
    assert wire.a_backwards_delay_range_is_refused()


def test_the_conditions_table_covers_four():
    assert len(wire.compare_the_conditions()) == 4


def test_loss_and_jitter_do_not_interfere():
    assert wire.loss_and_jitter_are_independent_settings()["the_rates_agree"]


def test_a_reliable_condition_loses_nothing():
    assert wire.loss_and_jitter_are_independent_settings()["the_reliable_link_loses_nothing"]


def test_every_condition_sent_the_same_traffic():
    assert wire.loss_and_jitter_are_independent_settings()["every_condition_sent_the_same"]


def test_the_summary_says_the_seed_repeats():
    assert wire.summarise()["the_same_seed_repeats"]


def test_the_summary_says_healing_does_not_replay():
    assert wire.summarise()["healing_does_not_replay"]


def test_a_network_starts_at_tick_zero():
    assert Network(members=["a", "b"]).now == 0


def test_a_network_starts_quiet():
    assert Network(members=["a", "b"]).quiet


def test_sending_puts_a_message_in_flight():
    net = Network(members=["a", "b"])
    net.send(Append(sender="a", recipient="b", term=1))
    assert net.in_flight == 1


def test_ticking_delivers_it():
    net = Network(members=["a", "b"])
    net.send(Append(sender="a", recipient="b", term=1))
    assert len(net.tick()) == 1


def test_ticking_empties_the_wire():
    net = Network(members=["a", "b"])
    net.send(Append(sender="a", recipient="b", term=1))
    net.tick()
    assert net.quiet


def test_ticking_advances_the_clock():
    net = Network(members=["a", "b"])
    net.tick()
    assert net.now == 1


def test_a_delayed_message_waits():
    net = Network(members=["a", "b"], conditions=Conditions(min_delay=3, max_delay=3))
    net.send(Append(sender="a", recipient="b", term=1))
    assert net.tick() == [] and net.tick() == []


def test_a_delayed_message_arrives_on_time():
    net = Network(members=["a", "b"], conditions=Conditions(min_delay=3, max_delay=3))
    net.send(Append(sender="a", recipient="b", term=1))
    net.tick()
    net.tick()
    assert len(net.tick()) == 1


def test_a_network_records_what_it_delivered():
    net = Network(members=["a", "b"])
    net.send(Append(sender="a", recipient="b", term=1))
    net.tick()
    assert len(net.delivered) == 1


def test_a_network_summarises():
    net = Network(members=["a", "b", "c"])
    assert net.as_dict()["members"] == 3


def test_a_network_can_gain_a_node():
    net = Network(members=["a", "b"])
    net.add("c")
    assert "c" in net.members


def test_adding_a_node_twice_is_refused():
    net = Network(members=["a", "b"])
    with pytest.raises(ConfigError):
        net.add("a")


def test_everything_is_reachable_without_a_partition():
    net = Network(members=["a", "b", "c"])
    assert net.reachable("a", "c")


def test_a_partition_makes_the_far_side_unreachable():
    net = Network(members=["a", "b", "c"])
    net.partition([["a"], ["b", "c"]])
    assert not net.reachable("a", "b")


def test_a_partition_leaves_the_near_side_reachable():
    net = Network(members=["a", "b", "c"])
    net.partition([["a"], ["b", "c"]])
    assert net.reachable("b", "c")


def test_healing_restores_reachability():
    net = Network(members=["a", "b", "c"])
    net.partition([["a"], ["b", "c"]])
    net.heal()
    assert net.reachable("a", "b")


def test_a_send_across_a_partition_returns_false():
    net = Network(members=["a", "b"])
    net.partition([["a"], ["b"]])
    assert not net.send(Append(sender="a", recipient="b", term=1))


def test_a_send_on_a_healthy_link_returns_true():
    net = Network(members=["a", "b"])
    assert net.send(Append(sender="a", recipient="b", term=1))


def test_sending_from_an_unknown_node_is_refused():
    net = Network(members=["a", "b"])
    with pytest.raises(UnknownNode):
        net.send(Append(sender="zz", recipient="b", term=1))


def test_conditions_report_their_jitter():
    assert Conditions(min_delay=2, max_delay=7).jitter == 5


def test_default_conditions_are_reliable():
    assert Conditions().reliable


def test_lossy_conditions_are_not_reliable():
    assert not Conditions(loss=0.1).reliable


def test_jittery_conditions_are_not_reliable():
    assert not Conditions(min_delay=1, max_delay=2).reliable


def test_conditions_summarise():
    assert Conditions(loss=0.25).as_dict()["loss"] == 0.25


def test_a_zero_delay_is_refused():
    with pytest.raises(ConfigError):
        Conditions(min_delay=0)


def test_counts_start_at_nothing():
    assert Counts().sent == 0


def test_counts_add_their_drops():
    made = Counts(dropped_by_loss=3, dropped_by_partition=4)
    assert made.dropped == 7


def test_counts_report_a_loss_rate():
    made = Counts(sent=10, dropped_by_loss=2)
    assert made.loss_rate == 0.2


def test_an_empty_count_has_no_loss_rate():
    assert Counts().loss_rate == 0.0


def test_counts_record_by_kind():
    made = Counts()
    made.record(Append(sender="a", recipient="b", term=1))
    assert made.by_kind["append"] == 1


def test_counts_estimate_bytes():
    made = Counts()
    made.record(Append(sender="a", recipient="b", term=1, entries=(Entry(term=1, index=1),)))
    assert made.bytes_estimate == 96


def test_counts_summarise():
    assert Counts(sent=5).as_dict()["sent"] == 5


def test_a_flight_reports_its_latency():
    made = InFlight(
        message=Append(sender="a", recipient="b", term=1),
        sent_at=2,
        due_at=6,
        sequence=1,
    )
    assert made.latency == 4


def test_a_flight_summarises():
    made = InFlight(
        message=Append(sender="a", recipient="b", term=1),
        sent_at=2,
        due_at=6,
        sequence=1,
    )
    assert made.as_dict()["latency"] == 4


def test_the_base_delay_is_one_tick():
    assert BASE_DELAY == 1
