from __future__ import annotations

import pytest

from rsm import snapshot as trim
from rsm.errors import ConfigError, LogError
from rsm.log import NO_INDEX, NO_TERM, Entry, Log
from rsm.node import Node
from rsm.snapshot import (
    COMPACT_AFTER,
    ENTRY_BYTES,
    KEY_BYTES,
    Snapshot,
    compact,
    restore,
    take,
)


def test_the_term_survives_the_entry():
    assert trim.compacting_keeps_the_term_at_the_boundary()["but_the_term_survived"]


def test_the_entry_itself_is_gone():
    assert trim.compacting_keeps_the_term_at_the_boundary()["the_entry_is_gone"]


def test_the_consistency_check_still_passes():
    assert trim.compacting_keeps_the_term_at_the_boundary()["so_the_check_still_passes"]


def test_a_wrong_term_still_fails_at_the_boundary():
    assert trim.compacting_keeps_the_term_at_the_boundary()["and_a_wrong_term_still_fails"]


def test_reading_below_the_boundary_is_refused():
    assert trim.a_compacted_log_cannot_answer_below_the_boundary()["reading_below_is_refused"]


def test_reading_above_the_boundary_works():
    assert trim.a_compacted_log_cannot_answer_below_the_boundary()["and_reading_above_works"]


def test_matching_below_the_boundary_fails():
    assert trim.a_compacted_log_cannot_answer_below_the_boundary()[
        "matching_below_the_boundary_fails"
    ]


def test_compaction_frees_the_entries():
    assert trim.compacting_frees_the_entries_and_keeps_the_state()["it_freed_everything"]


def test_compaction_leaves_the_state_alone():
    assert trim.compacting_frees_the_entries_and_keeps_the_state()["the_state_is_unchanged"]


def test_the_snapshot_holds_the_state():
    assert trim.compacting_frees_the_entries_and_keeps_the_state()["and_the_snapshot_holds_it"]


def test_a_repeating_workload_compacts_well():
    assert trim.a_snapshot_is_smaller_than_the_log_it_replaces()["the_snapshot_is_smaller"]


def test_the_repeating_ratio_is_large():
    assert trim.a_snapshot_is_smaller_than_the_log_it_replaces()["by_this_ratio"] > 10


def test_a_workload_with_no_repeats_compacts_poorly():
    assert trim.a_workload_with_no_repeats_compacts_to_nothing()["they_are_comparable"]


def test_the_saving_belongs_to_the_workload():
    assert trim.a_workload_with_no_repeats_compacts_to_nothing()[
        "so_the_saving_is_the_workloads"
    ]


def test_a_restart_applies_nothing():
    assert trim.a_restart_from_a_snapshot_skips_the_replay()["it_applied_nothing"]


def test_a_restart_reaches_the_same_state():
    assert trim.a_restart_from_a_snapshot_skips_the_replay()["the_states_match"]


def test_the_replay_would_have_applied_everything():
    assert trim.a_restart_from_a_snapshot_skips_the_replay()["entries_replayed"] > 100


def test_a_far_behind_follower_gets_a_snapshot():
    assert trim.a_leader_sends_a_snapshot_when_the_entries_are_gone()["it_sent_a_snapshot"]


def test_a_current_follower_gets_an_append():
    assert trim.a_leader_sends_a_snapshot_when_the_entries_are_gone()[
        "and_a_current_follower_gets_an_append"
    ]


def test_the_snapshot_names_its_boundary():
    assert trim.a_leader_sends_a_snapshot_when_the_entries_are_gone()[
        "the_snapshot_names_its_boundary"
    ]


def test_installing_discards_the_old_log():
    assert trim.installing_a_snapshot_replaces_the_whole_log()["it_discarded_them"]


def test_installing_takes_the_state():
    assert trim.installing_a_snapshot_replaces_the_whole_log()["it_took_the_state"]


def test_installing_moves_the_commit_index():
    assert trim.installing_a_snapshot_replaces_the_whole_log()["and_moved_its_commit_index"]


def test_installing_moves_the_applied_index():
    assert trim.installing_a_snapshot_replaces_the_whole_log()["and_its_applied_index"]


def test_an_older_snapshot_is_ignored():
    assert trim.an_older_snapshot_is_ignored()["it_was_ignored"]


def test_an_older_snapshot_leaves_the_state_alone():
    assert trim.an_older_snapshot_is_ignored()["and_the_state_is_untouched"]


def test_the_follower_confirms_an_install():
    assert trim.a_follower_confirms_what_it_installed()["it_is_an_installed"]


def test_the_confirmation_names_the_boundary():
    assert trim.a_follower_confirms_what_it_installed()["which_is_the_boundary"]


def test_a_snapshot_carries_the_membership():
    assert trim.a_snapshot_carries_the_membership()["it_carries_them"]


def test_a_snapshot_message_carries_it_too():
    assert trim.a_snapshot_carries_the_membership()["and_a_message_carries_them_too"]


def test_a_snapshot_uses_the_applied_index():
    assert trim.a_snapshot_is_taken_at_the_applied_index_not_the_commit_index()[
        "it_used_the_applied_index"
    ]


def test_a_snapshot_does_not_use_the_commit_index():
    assert trim.a_snapshot_is_taken_at_the_applied_index_not_the_commit_index()[
        "and_not_the_commit_index"
    ]


def test_compacting_past_the_end_is_refused():
    assert trim.compacting_past_the_end_is_refused()


def test_compacting_backwards_is_refused():
    assert trim.compacting_backwards_is_refused()


def test_a_snapshot_without_a_term_is_refused():
    assert trim.a_snapshot_without_a_term_is_refused()


def test_a_negative_snapshot_index_is_refused():
    assert trim.a_negative_snapshot_index_is_refused()


def test_the_empty_snapshot_is_empty():
    assert trim.an_empty_snapshot_stands_for_nothing()["it_is_empty"]


def test_a_fresh_log_matches_the_empty_snapshot():
    assert trim.an_empty_snapshot_stands_for_nothing()["and_a_fresh_log_matches_it"]


def test_a_cluster_trims_every_node():
    assert trim.a_cluster_compacts_and_keeps_serving()["it_trimmed_every_node"]


def test_a_cluster_keeps_committing_after_compaction():
    assert trim.a_cluster_compacts_and_keeps_serving()["it_kept_committing"]


def test_a_compacted_cluster_agrees():
    assert trim.a_cluster_compacts_and_keeps_serving()["and_the_nodes_agree"]


def test_a_compacted_cluster_levels_its_logs():
    assert trim.a_cluster_compacts_and_keeps_serving()["logs_level"]


def test_the_threshold_table_covers_four():
    assert len(trim.compare_the_thresholds()) == 4


def test_a_lower_threshold_keeps_less():
    assert trim.the_threshold_trades_log_size_against_how_far_a_follower_may_lag()[
        "the_lower_threshold_keeps_less"
    ]


def test_a_lower_threshold_reaches_less_far():
    assert trim.the_threshold_trades_log_size_against_how_far_a_follower_may_lag()[
        "and_reaches_less_far"
    ]


def test_the_snapshot_size_does_not_depend_on_the_threshold():
    assert trim.the_threshold_trades_log_size_against_how_far_a_follower_may_lag()[
        "the_snapshot_is_the_same_size"
    ]


def test_the_summary_says_the_term_survives():
    assert trim.summarise()["the_term_survives_the_entry"]


def test_the_summary_says_a_cluster_survives_compaction():
    assert trim.summarise()["a_cluster_survives_compaction"]


def test_a_snapshot_reports_its_size():
    made = Snapshot(last_index=5, last_term=1, state={"a": 1, "b": 2})
    assert made.nbytes == 2 * KEY_BYTES


def test_a_snapshot_summarises():
    made = Snapshot(last_index=5, last_term=1, state={"a": 1})
    assert made.as_dict()["last_index"] == 5


def test_an_empty_snapshot_is_flagged():
    assert Snapshot(last_index=NO_INDEX, last_term=NO_TERM).empty


def test_a_real_snapshot_is_not_empty():
    assert not Snapshot(last_index=1, last_term=1).empty


def test_a_snapshot_at_a_real_index_needs_a_term():
    with pytest.raises(ConfigError):
        Snapshot(last_index=5, last_term=0)


def test_taking_a_snapshot_uses_the_applied_index():
    node = Node(name="a", members=("a", "b"), seed=1)
    node.log.append([Entry(term=1, index=1, command=("set", "k", 1))])
    node.commit_index = 1
    node.apply_committed()
    assert take(node).last_index == 1


def test_taking_a_snapshot_from_a_fresh_node_is_empty():
    assert take(Node(name="a", members=("a", "b"), seed=1)).empty


def test_compacting_returns_how_many_went():
    made = Log()
    made.append([Entry(term=1, index=one) for one in range(1, 11)])
    assert compact(made, 4, 1) == 4


def test_compacting_moves_the_first_index():
    made = Log()
    made.append([Entry(term=1, index=one) for one in range(1, 11)])
    compact(made, 4, 1)
    assert made.first_index == 5


def test_compacting_keeps_the_rest():
    made = Log()
    made.append([Entry(term=1, index=one) for one in range(1, 11)])
    compact(made, 4, 1)
    assert made.last_index == 10


def test_compacting_past_the_end_raises():
    made = Log()
    made.append([Entry(term=1, index=1)])
    with pytest.raises(LogError):
        compact(made, 9, 1)


def test_restoring_replaces_the_log():
    node = Node(name="a", members=("a", "b"), seed=1)
    node.log.append([Entry(term=1, index=one) for one in range(1, 5)])
    restore(node, Snapshot(last_index=40, last_term=2, state={"k": 1}))
    assert node.log.snapshot_index == 40


def test_restoring_sets_the_state():
    node = Node(name="a", members=("a", "b"), seed=1)
    restore(node, Snapshot(last_index=40, last_term=2, state={"k": 1}))
    assert node.state == {"k": 1}


def test_restoring_sets_the_applied_index():
    node = Node(name="a", members=("a", "b"), seed=1)
    restore(node, Snapshot(last_index=40, last_term=2))
    assert node.last_applied == 40


def test_the_entry_and_key_sizes_are_constants():
    assert ENTRY_BYTES > 0 and KEY_BYTES > 0


def test_the_compaction_threshold_is_set():
    assert COMPACT_AFTER > 0
