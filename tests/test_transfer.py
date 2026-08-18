from __future__ import annotations

import pytest

from rsm import transfer as handover
from rsm.cluster import Cluster
from rsm.errors import ConfigError, NotLeader
from rsm.transfer import (
    ABANDONED,
    CAUGHT_UP,
    HANDED_OVER,
    PATIENCE,
    STAGES,
    STARTED,
    Transfer,
    hand_over,
)


def test_a_transfer_names_its_successor():
    assert handover.a_transfer_hands_leadership_to_the_named_node()["and_it_is_the_target"]


def test_a_transfer_hands_over():
    assert handover.a_transfer_hands_leadership_to_the_named_node()["it_handed_over"]


def test_a_transfer_is_quick():
    assert handover.a_transfer_hands_leadership_to_the_named_node()["ticks"] < 10


def test_a_transfer_beats_a_crash():
    assert handover.a_transfer_is_cheaper_than_waiting_for_a_timeout()["the_transfer_is_faster"]


def test_both_paths_end_with_a_leader():
    assert handover.a_transfer_is_cheaper_than_waiting_for_a_timeout()[
        "and_both_ended_with_a_leader"
    ]


def test_the_crash_did_not_name_a_successor():
    assert handover.a_transfer_is_cheaper_than_waiting_for_a_timeout()["and_the_crash_did_not"]


def test_an_early_handover_collects_no_votes():
    assert handover.handing_over_before_the_target_is_caught_up_fails()["it_collected_none"]


def test_an_early_handover_leaves_a_candidate():
    assert handover.handing_over_before_the_target_is_caught_up_fails()[
        "and_it_is_still_a_candidate"
    ]


def test_an_early_handover_wastes_a_term():
    assert handover.handing_over_before_the_target_is_caught_up_fails()[
        "so_the_term_was_wasted"
    ]


def test_an_unreachable_current_target_stops_at_caught_up():
    assert handover.an_unreachable_target_stops_short_and_leaves_the_leader_in_place()[
        "it_got_as_far_as_caught_up"
    ]


def test_an_unreachable_lagging_target_is_abandoned():
    assert handover.an_unreachable_target_stops_short_and_leaves_the_leader_in_place()[
        "and_the_lagging_one_was_abandoned"
    ]


def test_neither_unreachable_target_handed_over():
    assert handover.an_unreachable_target_stops_short_and_leaves_the_leader_in_place()[
        "neither_handed_over"
    ]


def test_both_clusters_still_lead():
    made = handover.an_unreachable_target_stops_short_and_leaves_the_leader_in_place()
    assert made["the_first_cluster_still_leads"] and made["and_the_second_one_does_too"]


def test_a_transfer_spends_one_term():
    assert handover.a_transfer_costs_one_election_and_no_more()["it_spent_one"]


def test_a_transfer_records_one_election():
    assert handover.a_transfer_costs_one_election_and_no_more()["and_recorded_one_election"]


def test_a_transfer_keeps_the_committed_entries():
    assert handover.the_cluster_keeps_its_committed_entries_across_a_transfer()[
        "the_old_writes_survived"
    ]


def test_a_transfer_accepts_new_writes_afterwards():
    assert handover.the_cluster_keeps_its_committed_entries_across_a_transfer()[
        "and_the_new_ones_landed"
    ]


def test_the_nodes_agree_after_a_transfer():
    assert handover.the_cluster_keeps_its_committed_entries_across_a_transfer()[
        "the_nodes_agree"
    ]


def test_transferring_to_yourself_is_refused():
    assert handover.transferring_to_yourself_is_refused()


def test_transferring_to_a_stranger_is_refused():
    assert handover.transferring_to_a_stranger_is_refused()


def test_transferring_without_a_leader_is_refused():
    assert handover.transferring_without_a_leader_is_refused()


def test_a_self_transfer_record_is_refused():
    assert handover.a_transfer_to_itself_is_refused_at_construction()


def test_an_unknown_stage_is_refused():
    assert handover.an_unknown_stage_is_refused()


def test_the_path_table_covers_six_seeds():
    assert len(handover.compare_the_paths()) == 6


def test_the_transfer_wins_on_every_seed():
    assert handover.a_transfer_beats_a_crash_on_every_seed()["the_transfer_wins_every_time"]


def test_the_smallest_gap_is_real():
    assert handover.a_transfer_beats_a_crash_on_every_seed()["smallest_gap"] > 5


def test_every_transfer_in_the_sweep_worked():
    assert handover.a_transfer_beats_a_crash_on_every_seed()["every_transfer_worked"]


def test_every_crash_in_the_sweep_recovered():
    assert handover.a_transfer_beats_a_crash_on_every_seed()["and_every_crash_recovered"]


def test_the_summary_says_it_beats_a_crash():
    assert handover.summarise()["it_beats_a_crash_every_time"]


def test_the_summary_says_it_loses_no_entries():
    assert handover.summarise()["and_loses_no_entries"]


def test_a_transfer_reports_its_route():
    made = Transfer(
        outgoing="a", target="b", stage=HANDED_OVER, ticks=3, messages=8, elections=1
    )
    assert made.outgoing == "a" and made.target == "b"


def test_a_handed_over_transfer_is_truthy():
    made = Transfer(
        outgoing="a", target="b", stage=HANDED_OVER, ticks=3, messages=8, elections=1
    )
    assert bool(made)


def test_an_abandoned_transfer_is_falsy():
    made = Transfer(outgoing="a", target="b", stage=ABANDONED, ticks=3, messages=8, elections=0)
    assert not bool(made)


def test_a_caught_up_transfer_is_falsy():
    made = Transfer(outgoing="a", target="b", stage=CAUGHT_UP, ticks=3, messages=8, elections=0)
    assert not bool(made)


def test_a_transfer_summarises():
    made = Transfer(outgoing="a", target="b", stage=STARTED, ticks=3, messages=8, elections=0)
    assert made.as_dict()["from"] == "a"


def test_a_transfer_reports_whether_it_handed_over():
    made = Transfer(
        outgoing="a", target="b", stage=HANDED_OVER, ticks=3, messages=8, elections=1
    )
    assert made.as_dict()["handed_over"]


def test_a_self_transfer_raises():
    with pytest.raises(ConfigError):
        Transfer(outgoing="a", target="a", stage=STARTED, ticks=0, messages=0, elections=0)


def test_a_bad_stage_raises():
    with pytest.raises(ConfigError):
        Transfer(outgoing="a", target="b", stage="soon", ticks=0, messages=0, elections=0)


def test_handing_over_without_a_leader_raises():
    with pytest.raises(NotLeader):
        hand_over(Cluster(size=3, seed=1), "n1")


def test_handing_over_to_a_stranger_raises():
    made = Cluster(size=3, seed=1).settle()
    with pytest.raises(ConfigError):
        hand_over(made, "zz")


def test_handing_over_to_the_leader_raises():
    made = Cluster(size=3, seed=1).settle()
    with pytest.raises(ConfigError):
        hand_over(made, made.leader().name)


def test_handing_over_returns_a_transfer():
    made = Cluster(size=3, seed=2).settle()
    target = next(one for one in made.up if one != made.leader().name)
    assert isinstance(hand_over(made, target), Transfer)


def test_handing_over_moves_the_leader():
    made = Cluster(size=3, seed=2).settle()
    target = next(one for one in made.up if one != made.leader().name)
    hand_over(made, target)
    assert made.leader().name == target


def test_there_are_four_stages():
    assert len(STAGES) == 4


def test_the_patience_is_generous():
    assert PATIENCE >= 30
