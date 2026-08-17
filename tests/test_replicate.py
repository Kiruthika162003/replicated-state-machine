from __future__ import annotations

from rsm import replicate as spread
from rsm.node import MAX_BATCH
from rsm.replicate import SPREAD_TICKS, Spread


def test_the_obvious_rule_commits_the_old_entry():
    assert spread.the_obvious_commit_rule_loses_a_committed_entry()[
        "and_the_loose_one_committed_it"
    ]


def test_the_real_rule_refuses_to_commit_it():
    assert spread.the_obvious_commit_rule_loses_a_committed_entry()[
        "the_rule_refused_to_commit"
    ]


def test_the_rival_wins_the_next_term():
    assert spread.the_obvious_commit_rule_loses_a_committed_entry()[
        "the_rival_won_the_next_term"
    ]


def test_the_committed_entry_is_overwritten():
    assert spread.the_obvious_commit_rule_loses_a_committed_entry()["and_it_was_overwritten"]


def test_the_rival_collected_a_majority():
    assert spread.the_obvious_commit_rule_loses_a_committed_entry()["votes_for_the_rival"] >= 2


def test_a_current_term_entry_commits():
    assert spread.the_rule_makes_the_entry_safe_once_the_term_catches_up()[
        "the_fresh_entry_committed"
    ]


def test_it_carries_the_old_entry_with_it():
    assert spread.the_rule_makes_the_entry_safe_once_the_term_catches_up()[
        "and_it_carried_the_old_one_with_it"
    ]


def test_the_rival_can_no_longer_win():
    assert spread.the_rule_makes_the_entry_safe_once_the_term_catches_up()[
        "the_rival_cannot_win"
    ]


def test_a_quorum_commits():
    assert spread.a_write_reaches_every_node_not_just_a_quorum()[
        "a_quorum_was_enough_to_commit"
    ]


def test_replication_continues_past_the_quorum():
    assert spread.a_write_reaches_every_node_not_just_a_quorum()[
        "but_everyone_ended_up_with_it"
    ]


def test_commit_needs_the_quorum_less_the_leader():
    assert spread.commit_costs_one_round_trip()["it_is_the_quorum_less_the_leader"]


def test_three_nodes_need_one_reply():
    assert spread.commit_costs_one_round_trip()["three_needs_one_reply"]


def test_seven_nodes_need_three_replies():
    assert spread.commit_costs_one_round_trip()["seven_needs_three"]


def test_no_size_needs_every_reply():
    assert spread.commit_costs_one_round_trip()["and_never_all_of_them"]


def test_two_down_still_commits():
    assert spread.a_slow_follower_does_not_slow_a_write()["it_committed_with_two_down"]


def test_the_dead_nodes_hold_nothing_new():
    assert spread.a_slow_follower_does_not_slow_a_write()["and_the_dead_nodes_hold_nothing_new"]


def test_a_behind_follower_catches_up():
    assert spread.a_follower_that_falls_behind_is_caught_up_by_the_ordinary_path()["caught_up"]


def test_the_gap_was_real():
    assert (
        spread.a_follower_that_falls_behind_is_caught_up_by_the_ordinary_path()[
            "gap_when_it_returned"
        ]
        > 5
    )


def test_it_applied_the_same_commands():
    assert spread.a_follower_that_falls_behind_is_caught_up_by_the_ordinary_path()[
        "and_it_applied_the_same_commands"
    ]


def test_batching_sends_one_message():
    assert spread.batching_turns_many_messages_into_one()["it_sent_one_message"]


def test_batching_carries_everything():
    assert spread.batching_turns_many_messages_into_one()["carrying_everything"]


def test_the_cap_bounds_a_message():
    assert spread.the_batch_cap_bounds_one_message()["it_stopped_at_the_cap"]


def test_a_long_catch_up_needs_several_messages():
    assert spread.the_batch_cap_bounds_one_message()["and_that_is_more_than_one"]


def test_the_cap_is_the_batch_constant():
    assert spread.the_batch_cap_bounds_one_message()["cap"] == MAX_BATCH


def test_a_real_divergence_reconciles():
    assert spread.the_conflict_reply_beats_walking_back_in_a_real_cluster()[
        "the_logs_agree_now"
    ]


def test_the_orphans_are_removed():
    assert spread.the_conflict_reply_beats_walking_back_in_a_real_cluster()[
        "and_the_orphans_are_gone"
    ]


def test_the_reconciled_nodes_agree():
    assert spread.the_conflict_reply_beats_walking_back_in_a_real_cluster()["the_nodes_agree"]


def test_loss_still_commits_everything():
    assert spread.loss_costs_correctness_nothing_and_messages_less_than_nothing()[
        "both_committed_everything"
    ]


def test_loss_still_agrees():
    assert spread.loss_costs_correctness_nothing_and_messages_less_than_nothing()["both_agree"]


def test_loss_levels_the_logs():
    assert spread.loss_costs_correctness_nothing_and_messages_less_than_nothing()[
        "both_levelled_their_logs"
    ]


def test_loss_sends_fewer_messages():
    assert spread.loss_costs_correctness_nothing_and_messages_less_than_nothing()[
        "loss_sent_fewer_messages"
    ]


def test_the_message_saving_is_modest():
    made = spread.loss_costs_correctness_nothing_and_messages_less_than_nothing()
    assert 0.7 < made["by_this_ratio"] < 1.0


def test_an_old_reply_does_not_move_the_match_back():
    assert spread.a_reordered_reply_never_moves_a_match_index_backwards()[
        "it_did_not_move_backwards"
    ]


def test_the_next_index_follows_the_match():
    assert spread.a_reordered_reply_never_moves_a_match_index_backwards()[
        "and_the_next_index_agrees"
    ]


def test_the_leader_counts_itself():
    assert spread.a_leader_replicates_to_itself_by_definition()["it_counts_itself"]


def test_the_leader_does_not_commit_alone():
    assert spread.a_leader_replicates_to_itself_by_definition()["it_did_not_commit_alone"]


def test_one_reply_commits_in_a_cluster_of_three():
    assert spread.a_leader_replicates_to_itself_by_definition()["and_one_reply_was_enough"]


def test_a_follower_caps_the_commit_index():
    assert spread.a_follower_never_commits_ahead_of_the_leader()["it_capped_at_its_own_log"]


def test_a_follower_did_not_take_the_leaders_number():
    assert spread.a_follower_never_commits_ahead_of_the_leader()["and_did_not_take_nine"]


def test_the_node_does_not_police_membership():
    assert spread.the_node_does_not_police_the_membership()["and_did_not_refuse"]


def test_the_network_does():
    assert spread.the_node_does_not_police_the_membership()["the_network_refused_it"]


def test_an_append_below_the_snapshot_is_refused():
    assert spread.an_append_below_the_snapshot_is_refused()


def test_the_write_path_table_covers_four():
    assert len(spread.compare_the_write_paths()) == 4


def test_size_costs_more_than_loss():
    assert spread.the_link_costs_less_than_the_cluster_size()["size_costs_more_than_loss"]


def test_loss_can_cost_less_than_nothing():
    assert spread.the_link_costs_less_than_the_cluster_size()["and_loss_can_even_cost_less"]


def test_the_size_step_is_a_real_cost():
    assert spread.the_link_costs_less_than_the_cluster_size()["the_size_step_costs"] > 0


def test_the_summary_says_the_obvious_rule_fails():
    assert spread.summarise()["and_it_gets_overwritten"]


def test_the_summary_says_the_real_rule_refuses():
    assert spread.summarise()["the_real_rule_refuses"]


def test_a_spread_reports_its_holders():
    made = Spread(index=3, holders=5, committed=True, messages=40)
    assert made.holders == 5


def test_a_spread_summarises():
    made = Spread(index=3, holders=5, committed=True, messages=40)
    assert made.as_dict()["index"] == 3


def test_a_spread_reports_its_replication():
    made = Spread(index=3, holders=4, committed=True, messages=40)
    assert made.replicated == 4


def test_the_spread_budget_is_generous():
    assert SPREAD_TICKS >= 30
