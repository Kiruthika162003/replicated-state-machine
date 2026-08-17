from __future__ import annotations

import pytest

from rsm import node as member
from rsm.errors import ConfigError, NotLeader
from rsm.log import NO_INDEX, NO_TERM, Entry
from rsm.node import (
    CANDIDATE,
    FOLLOWER,
    HEARTBEAT_INTERVAL,
    LEADER,
    MAX_BATCH,
    MAX_ELECTION_TIMEOUT,
    MIN_ELECTION_TIMEOUT,
    ROLES,
    Node,
)
from rsm.rpc import Append, Appended, Installed, InstallSnapshot, RequestVote, Vote


def elected(name: str = "a", members: tuple[str, ...] = ("a", "b", "c")) -> Node:
    """A node that has won an election, which is where most of these start."""
    node = Node(name=name, members=members)
    node.become_candidate()
    for one in node.peers:
        if node.role == LEADER:
            break
        node.step(Vote(sender=one, recipient=name, term=node.term, granted=True))
    return node


def test_a_fresh_node_is_a_follower():
    assert member.a_fresh_node_is_a_follower()["it_is_a_follower"]


def test_a_fresh_node_has_spent_no_vote():
    assert member.a_fresh_node_is_a_follower()["with_no_vote_spent"]


def test_a_fresh_node_has_an_empty_log():
    assert member.a_fresh_node_is_a_follower()["and_an_empty_log"]


def test_a_fresh_node_knows_no_leader():
    assert member.a_fresh_node_is_a_follower()["and_no_leader"]


def test_three_nodes_need_two():
    assert member.a_majority_of_three_is_two()["three_needs_two"]


def test_four_nodes_need_three():
    assert member.a_majority_of_three_is_two()["four_also_needs_three"]


def test_four_tolerates_what_three_does():
    assert member.a_majority_of_three_is_two()["and_tolerates_the_same_as_three"]


def test_an_even_cluster_buys_nothing():
    assert member.a_majority_of_three_is_two()["so_an_even_cluster_buys_nothing"]


def test_a_node_votes_once_per_term():
    assert member.a_node_votes_once_per_term()["the_second_is_refused"]


def test_the_first_candidate_gets_the_vote():
    assert member.a_node_votes_once_per_term()["the_first_wins"]


def test_a_later_term_gets_a_fresh_vote():
    assert member.a_node_votes_once_per_term()["but_a_later_term_gets_a_fresh_vote"]


def test_a_repeated_request_is_granted_again():
    assert member.a_repeated_request_from_the_same_candidate_is_granted_again()[
        "a_retry_gets_the_same_answer"
    ]


def test_a_different_candidate_is_still_refused():
    assert member.a_repeated_request_from_the_same_candidate_is_granted_again()[
        "and_a_different_candidate_does_not"
    ]


def test_a_shorter_log_is_refused_a_vote():
    assert member.a_vote_is_refused_to_a_log_behind_this_one()["a_shorter_log_is_refused"]


def test_an_equal_log_is_granted_a_vote():
    assert member.a_vote_is_refused_to_a_log_behind_this_one()["and_an_equal_one_is_granted"]


def test_the_log_decided_the_vote():
    assert member.a_vote_is_refused_to_a_log_behind_this_one()["so_the_log_decided_it"]


def test_a_majority_takes_office():
    assert member.a_candidate_that_collects_a_majority_takes_office()[
        "it_took_office_on_the_second"
    ]


def test_a_candidate_asks_every_peer():
    assert member.a_candidate_that_collects_a_majority_takes_office()["it_asked_every_peer"]


def test_the_third_vote_changes_nothing():
    assert member.a_candidate_that_collects_a_majority_takes_office()[
        "the_third_vote_changed_nothing"
    ]


def test_a_leader_writes_a_noop():
    assert member.a_leader_writes_an_empty_entry_on_election()["it_appended_one"]


def test_the_noop_is_empty():
    assert member.a_leader_writes_an_empty_entry_on_election()["and_it_is_empty"]


def test_the_noop_carries_the_new_term():
    assert member.a_leader_writes_an_empty_entry_on_election()["at_the_new_term"]


def test_a_leader_steps_down_on_a_later_term():
    assert member.a_leader_steps_down_on_a_later_term()["and_it_stepped_down"]


def test_a_deposed_leader_adopts_the_term():
    assert member.a_leader_steps_down_on_a_later_term()["adopting_the_later_term"]


def test_a_deposed_leader_forgets_its_vote():
    assert member.a_leader_steps_down_on_a_later_term()["and_forgetting_its_vote"]


def test_a_candidate_steps_down_for_a_leader():
    assert member.a_candidate_steps_down_for_a_leader_of_its_own_term()[
        "and_it_became_a_follower"
    ]


def test_that_step_down_changes_no_term():
    assert member.a_candidate_steps_down_for_a_leader_of_its_own_term()["term_unchanged"]


def test_the_new_follower_knows_the_leader():
    assert member.a_candidate_steps_down_for_a_leader_of_its_own_term()[
        "and_it_knows_the_leader"
    ]


def test_a_stale_append_is_refused():
    assert member.a_stale_append_is_refused_without_changing_anything()["it_refused"]


def test_a_stale_append_leaves_the_log_alone():
    assert member.a_stale_append_is_refused_without_changing_anything()["the_log_is_untouched"]


def test_the_refusal_carries_the_current_term():
    assert member.a_stale_append_is_refused_without_changing_anything()[
        "the_reply_carries_the_current_term"
    ]


def test_a_follower_takes_a_matching_append():
    assert member.a_follower_takes_entries_that_continue_its_log()["it_took_both"]


def test_a_follower_commits_what_the_leader_had():
    assert member.a_follower_takes_entries_that_continue_its_log()[
        "it_committed_what_the_leader_had"
    ]


def test_a_follower_does_not_apply_uncommitted_entries():
    assert member.a_follower_takes_entries_that_continue_its_log()[
        "but_not_the_uncommitted_one"
    ]


def test_a_follower_refuses_an_append_it_cannot_place():
    assert member.a_follower_refuses_an_append_it_cannot_place()["it_refused"]


def test_the_refusal_names_the_end_of_the_log():
    assert member.a_follower_refuses_an_append_it_cannot_place()["it_named_the_end_of_its_log"]


def test_a_refused_append_creates_no_gap():
    assert member.a_follower_refuses_an_append_it_cannot_place()["and_no_gap_was_created"]


def test_truncation_starts_at_the_real_conflict():
    assert member.a_follower_truncates_what_conflicts_and_keeps_what_does_not()[
        "index_three_was_replaced"
    ]


def test_truncation_leaves_the_prefix():
    assert member.a_follower_truncates_what_conflicts_and_keeps_what_does_not()[
        "nothing_below_the_conflict_moved"
    ]


def test_the_new_entry_lands():
    assert member.a_follower_truncates_what_conflicts_and_keeps_what_does_not()[
        "index_four_is_the_new_one"
    ]


def test_a_majority_commits_a_current_term_entry():
    assert member.a_leader_commits_when_a_majority_holds_an_entry_from_its_term()[
        "one_acknowledgement_committed_it"
    ]


def test_committing_applies_it():
    assert member.a_leader_commits_when_a_majority_holds_an_entry_from_its_term()[
        "and_it_was_applied"
    ]


def test_committing_changes_the_state():
    assert member.a_leader_commits_when_a_majority_holds_an_entry_from_its_term()[
        "the_state_changed"
    ]


def test_an_old_term_entry_is_not_committed_by_counting():
    assert member.a_leader_will_not_commit_an_entry_from_an_earlier_term()[
        "it_was_not_committed"
    ]


def test_the_noop_makes_the_old_entry_commitable():
    assert member.a_leader_will_not_commit_an_entry_from_an_earlier_term()[
        "so_the_old_entry_is_committed_too"
    ]


def test_the_noop_commits_both():
    assert member.a_leader_will_not_commit_an_entry_from_an_earlier_term()[
        "and_the_noop_committed_both"
    ]


def test_committing_the_top_commits_the_bottom():
    assert member.committing_an_entry_commits_everything_below_it()["and_everything_below"]


def test_entries_are_applied_in_order():
    assert member.committing_an_entry_commits_everything_below_it()["applied_in_order"]


def test_applying_twice_applies_nothing_new():
    assert member.committing_an_entry_commits_everything_below_it()[
        "the_last_call_applied_nothing_new"
    ]


def test_applying_stops_at_the_commit_index():
    assert member.applying_never_runs_ahead_of_committing()["never_past_the_commit_index"]


def test_a_second_apply_call_does_nothing():
    assert member.applying_never_runs_ahead_of_committing()["a_second_call_applies_nothing"]


def test_raising_the_commit_index_applies_the_rest():
    assert member.applying_never_runs_ahead_of_committing()[
        "and_raising_the_commit_index_applies_the_rest"
    ]


def test_the_state_holds_the_last_write():
    assert member.applying_never_runs_ahead_of_committing()["the_state_holds_the_last_write"]


def test_a_single_node_elects_itself():
    assert member.a_single_node_cluster_commits_without_asking_anyone()["it_elected_itself"]


def test_a_single_node_commits_at_once():
    assert member.a_single_node_cluster_commits_without_asking_anyone()["it_committed_at_once"]


def test_a_single_node_applies_its_write():
    assert member.a_single_node_cluster_commits_without_asking_anyone()["and_applied_it"]


def test_a_follower_refuses_a_client_write():
    assert member.a_follower_refuses_a_client_write()


def test_a_node_outside_its_cluster_is_refused():
    assert member.a_node_outside_its_own_cluster_is_refused()


def test_a_repeated_member_name_is_refused():
    assert member.a_membership_with_a_repeated_name_is_refused()


def test_the_role_table_covers_three():
    assert len(member.compare_the_roles()) == len(ROLES)


def test_only_the_leader_accepts_writes():
    assert member.only_a_leader_accepts_writes()["only_the_leader_accepts"]


def test_a_late_follower_stands_for_election():
    assert member.only_a_leader_accepts_writes()["a_late_follower_stands_for_election"]


def test_the_summary_says_one_vote_per_term():
    assert member.summarise()["one_vote_per_term"]


def test_the_summary_says_the_noop_commits_the_old_entry():
    assert member.summarise()["the_noop_commits_it"]


def test_a_node_lists_its_peers():
    assert Node(name="a", members=("a", "b", "c")).peers == ("b", "c")


def test_a_node_reports_its_quorum():
    assert Node(name="a", members=("a", "b", "c", "d", "e")).quorum == 3


def test_a_follower_is_not_a_leader():
    assert not Node(name="a", members=("a", "b")).is_leader


def test_an_elected_node_is_a_leader():
    assert elected().is_leader


def test_a_candidate_bumps_its_term():
    node = Node(name="a", members=("a", "b", "c"))
    before = node.term
    node.become_candidate()
    assert node.term == before + 1


def test_a_candidate_votes_for_itself():
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    assert node.voted_for == "a"


def test_a_candidate_counts_its_own_vote():
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    assert node.votes == {"a"}


def test_a_candidate_sends_one_request_per_peer():
    node = Node(name="a", members=("a", "b", "c", "d", "e"))
    assert len(node.become_candidate()) == 4


def test_a_refused_vote_does_not_count():
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=False))
    assert node.role == CANDIDATE


def test_a_vote_for_an_old_candidacy_is_ignored():
    node = Node(name="a", members=("a", "b", "c"))
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
    assert node.role == FOLLOWER


def test_a_leader_sets_up_its_indices():
    node = elected()
    assert set(node.next_index) == {"b", "c"}


def test_a_leader_starts_every_follower_at_the_noop():
    node = elected()
    assert set(node.next_index.values()) == {node.log.last_index}


def test_a_leader_starts_every_match_at_nothing():
    node = elected()
    assert node.match_index["b"] == NO_INDEX


def test_a_leader_accepts_a_proposal():
    node = elected()
    assert node.propose(("set", "k", 1)) == node.log.last_index


def test_a_proposal_carries_the_leaders_term():
    node = elected()
    index = node.propose(("set", "k", 1))
    assert node.log.at(index).term == node.term


def test_a_candidate_refuses_a_proposal():
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    with pytest.raises(NotLeader):
        node.propose("x")


def test_replicating_sends_one_message_per_peer():
    assert len(elected().replicate()) == 2


def test_replicating_to_one_peer_sends_one():
    assert len(elected().replicate("b")) == 1


def test_a_replicated_append_carries_the_consistency_check():
    node = elected()
    made = node.replicate("b")[0]
    assert made.previous_index == node.log.last_index - 1


def test_a_caught_up_follower_gets_a_heartbeat():
    node = elected()
    node.next_index["b"] = node.log.last_index + 1
    assert node.replicate("b")[0].is_heartbeat


def test_a_behind_follower_gets_entries():
    node = elected()
    node.propose("x")
    node.next_index["b"] = 1
    assert not node.replicate("b")[0].is_heartbeat


def test_a_leader_beats_on_the_interval():
    node = elected()
    node.heartbeat_due = 0
    assert len(node.tick(HEARTBEAT_INTERVAL)) == 2


def test_a_leader_is_quiet_between_beats():
    node = elected()
    node.heartbeat_due = 100
    assert node.tick(1) == []


def test_a_follower_stands_when_its_deadline_passes():
    node = Node(name="a", members=("a", "b", "c"))
    node.tick(node.election_deadline)
    assert node.role == CANDIDATE


def test_a_follower_waits_until_then():
    node = Node(name="a", members=("a", "b", "c"))
    node.tick(node.election_deadline - 1)
    assert node.role == FOLLOWER


def test_an_append_resets_the_election_timer():
    node = Node(name="a", members=("a", "b", "c"))
    before = node.election_deadline
    node.now = 100
    node.step(Append(sender="b", recipient="a", term=1, previous_index=NO_INDEX))
    assert node.election_deadline > before


def test_a_granted_vote_resets_the_election_timer():
    node = Node(name="a", members=("a", "b", "c"))
    before = node.election_deadline
    node.now = 100
    node.step(RequestVote(sender="b", recipient="a", term=2))
    assert node.election_deadline > before


def test_the_election_timeout_is_randomised_in_range():
    node = Node(name="a", members=("a", "b", "c"))
    span = node.election_deadline - node.now
    assert MIN_ELECTION_TIMEOUT <= span <= MAX_ELECTION_TIMEOUT


def test_two_nodes_get_different_timeouts():
    made = [Node(name=one, members=("a", "b", "c", "d", "e")) for one in "abcde"]
    assert len({one.election_deadline for one in made}) > 1


def test_a_leader_takes_a_snapshot_reply():
    node = elected()
    node.step(Installed(sender="b", recipient="a", term=node.term, last_index=7))
    assert node.match_index["b"] == 7


def test_a_follower_ahead_of_the_leader_gets_a_heartbeat():
    assert member.a_follower_can_report_an_index_the_leader_does_not_have()[
        "and_it_is_a_heartbeat"
    ]


def test_the_leader_clamps_to_its_own_end():
    assert member.a_follower_can_report_an_index_the_leader_does_not_have()[
        "which_is_the_leaders_own_end"
    ]


def test_the_follower_really_was_ahead():
    assert member.a_follower_can_report_an_index_the_leader_does_not_have()[
        "the_follower_is_ahead"
    ]


def test_a_follower_installs_a_snapshot():
    node = Node(name="c", members=("a", "b", "c"))
    node.step(
        InstallSnapshot(
            sender="a",
            recipient="c",
            term=1,
            last_index=40,
            last_term=1,
            state={"k": 9},
        )
    )
    assert node.log.snapshot_index == 40


def test_installing_a_snapshot_sets_the_state():
    node = Node(name="c", members=("a", "b", "c"))
    node.step(
        InstallSnapshot(
            sender="a", recipient="c", term=1, last_index=40, last_term=1, state={"k": 9}
        )
    )
    assert node.state == {"k": 9}


def test_installing_a_snapshot_moves_the_commit_index():
    node = Node(name="c", members=("a", "b", "c"))
    node.step(InstallSnapshot(sender="a", recipient="c", term=1, last_index=40, last_term=1))
    assert node.commit_index == 40


def test_an_older_snapshot_is_ignored():
    node = Node(name="c", members=("a", "b", "c"))
    node.log.append([Entry(term=1, index=one) for one in range(1, 60)])
    node.step(InstallSnapshot(sender="a", recipient="c", term=1, last_index=40, last_term=1))
    assert node.log.last_index == 59


def test_a_leader_sends_a_snapshot_to_a_compacted_follower():
    node = elected()
    node.log = node.log.__class__(entries=[], snapshot_index=50, snapshot_term=1)
    node.next_index["b"] = 10
    assert isinstance(node.replicate("b")[0], InstallSnapshot)


def test_a_node_summarises():
    assert Node(name="a", members=("a", "b")).as_dict()["node"] == "a"


def test_a_node_prints_its_role_and_term():
    assert str(Node(name="a", members=("a", "b"))).startswith("a follower@1")


def test_a_node_outside_the_membership_raises():
    with pytest.raises(ConfigError):
        Node(name="z", members=("a", "b"))


def test_the_batch_cap_is_sixty_four():
    assert MAX_BATCH == 64


def test_the_heartbeat_is_well_below_the_election_timeout():
    assert HEARTBEAT_INTERVAL * 2 < MIN_ELECTION_TIMEOUT


def test_a_leader_backs_up_on_a_refusal():
    node = elected()
    node.propose("x")
    node.step(
        Appended(
            sender="b",
            recipient="a",
            term=node.term,
            success=False,
            conflict_index=1,
        )
    )
    assert node.next_index["b"] == 1


def test_a_leader_moves_on_after_a_success():
    node = elected()
    index = node.propose("x")
    node.step(
        Appended(sender="b", recipient="a", term=node.term, success=True, match_index=index)
    )
    assert node.next_index["b"] == index + 1


def test_a_late_reply_does_not_move_a_match_backwards():
    node = elected()
    node.step(Appended(sender="b", recipient="a", term=node.term, success=True, match_index=5))
    node.step(Appended(sender="b", recipient="a", term=node.term, success=True, match_index=2))
    assert node.match_index["b"] == 5


def test_a_reply_to_a_deposed_leader_is_ignored():
    node = Node(name="a", members=("a", "b", "c"))
    node.step(Appended(sender="b", recipient="a", term=1, success=True, match_index=5))
    assert node.match_index.get("b", NO_TERM) == NO_TERM
