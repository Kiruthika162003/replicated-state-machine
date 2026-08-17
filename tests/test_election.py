from __future__ import annotations

from rsm import election as vote
from rsm.cluster import Cluster
from rsm.election import MAX_ROUNDS, Election
from rsm.log import Entry
from rsm.node import FOLLOWER, LEADER, Node
from rsm.rpc import RequestVote, Vote


def test_every_cold_start_elects():
    assert vote.a_cold_cluster_elects_in_one_round()["they_all_elected"]


def test_cold_starts_take_one_round():
    assert vote.a_cold_cluster_elects_in_one_round()["one_round_share"] == 1.0


def test_no_cold_start_needed_many_rounds():
    assert vote.a_cold_cluster_elects_in_one_round()["most_rounds"] <= 2


def test_a_fixed_timeout_always_collides():
    assert vote.a_fixed_timeout_makes_every_node_stand_together()["they_always_collide"]


def test_the_fixed_timeout_rate_is_one():
    assert vote.a_fixed_timeout_makes_every_node_stand_together()["collision_rate"] == 1.0


def test_the_collision_rate_starts_at_one():
    assert vote.a_little_randomisation_does_almost_all_the_work()["at_zero_it_always_collides"]


def test_ten_ticks_of_spread_is_uncommon():
    assert vote.a_little_randomisation_does_almost_all_the_work()["at_ten_it_is_uncommon"]


def test_fifty_ticks_of_spread_is_rare():
    assert vote.a_little_randomisation_does_almost_all_the_work()["at_fifty_it_is_rare"]


def test_the_fall_is_steepest_early():
    assert vote.a_little_randomisation_does_almost_all_the_work()["the_fall_is_steepest_early"]


def test_the_collision_rates_fall_throughout():
    rates = vote.a_little_randomisation_does_almost_all_the_work()["collision_rates"]
    assert all(rates[one] > rates[one + 1] for one in range(len(rates) - 1))


def test_detection_grows_with_the_spread():
    assert vote.the_extra_spread_costs_detection_time()["detection_grows_with_the_spread"]


def test_the_collision_rate_flattens():
    assert vote.the_extra_spread_costs_detection_time()["while_the_collision_rate_flattens"]


def test_the_last_stretch_of_spread_buys_nothing():
    assert vote.the_extra_spread_costs_detection_time()["so_the_last_stretch_buys_nothing"]


def test_nobody_wins_a_tie():
    assert vote.a_split_vote_resolves_itself()["nobody_won_the_tie"]


def test_a_tied_cluster_still_settles():
    assert vote.a_split_vote_resolves_itself()["a_real_cluster_still_settles"]


def test_a_tie_leaves_two_candidates():
    assert vote.a_split_vote_resolves_itself()["candidates_after_the_tie"] == 2


def test_every_size_elects():
    assert vote.an_even_cluster_does_not_actually_tie_in_practice()["every_size_elects"]


def test_no_size_needed_a_second_term():
    assert vote.an_even_cluster_does_not_actually_tie_in_practice()[
        "nobody_needed_a_second_term"
    ]


def test_the_even_sizes_were_no_worse():
    assert vote.an_even_cluster_does_not_actually_tie_in_practice()[
        "so_the_even_sizes_were_no_worse"
    ]


def test_a_stale_candidate_never_wins():
    assert vote.a_candidate_with_a_stale_log_cannot_win()["it_never_won"]


def test_a_stale_candidate_raises_the_term_anyway():
    assert vote.a_candidate_with_a_stale_log_cannot_win()["but_it_raised_the_term_every_time"]


def test_a_stale_candidate_stood_repeatedly():
    assert vote.a_candidate_with_a_stale_log_cannot_win()["times_it_stood"] > 5


def test_an_isolated_follower_runs_away_with_the_term():
    assert vote.a_partitioned_node_inflates_the_term_without_pre_vote()["it_ran_away_alone"]


def test_the_runaway_is_large():
    assert (
        vote.a_partitioned_node_inflates_the_term_without_pre_vote()["by_this_many_terms"] > 10
    )


def test_healing_costs_the_cluster_a_term():
    assert vote.a_partitioned_node_inflates_the_term_without_pre_vote()[
        "and_healing_cost_the_cluster_a_term"
    ]


def test_an_isolated_leader_never_bumps_its_term():
    assert vote.an_isolated_leader_does_not_bump_its_term_at_all()["it_never_bumped_its_term"]


def test_the_majority_moves_on_without_the_isolated_leader():
    assert vote.an_isolated_leader_does_not_bump_its_term_at_all()["which_moved_on_without_it"]


def test_the_isolated_leader_steps_down_on_healing():
    assert vote.an_isolated_leader_does_not_bump_its_term_at_all()[
        "and_it_stepped_down_on_the_first_message"
    ]


def test_pre_vote_stops_the_runaway():
    assert vote.pre_vote_stops_the_term_running_away()["it_stayed_put"]


def test_without_pre_vote_it_runs_away():
    assert vote.pre_vote_stops_the_term_running_away()["while_the_plain_one_did_not"]


def test_pre_vote_saves_many_terms():
    assert vote.pre_vote_stops_the_term_running_away()["the_saving_in_terms"] > 10


def test_pre_vote_avoids_the_healing_cost():
    assert vote.pre_vote_stops_the_term_running_away()["but_not_with_it"]


def test_a_pre_vote_spends_no_vote():
    assert vote.a_pre_vote_spends_nobodys_vote()["it_spent_no_vote"]


def test_the_real_request_after_a_pre_vote_is_granted():
    assert vote.a_pre_vote_spends_nobodys_vote()["the_real_request_was_granted"]


def test_the_real_request_spends_the_vote():
    assert vote.a_pre_vote_spends_nobodys_vote()["and_that_one_did_spend_it"]


def test_a_pre_vote_reply_is_marked():
    assert vote.a_pre_vote_spends_nobodys_vote()["the_reply_is_marked_as_a_pre_vote"]


def test_a_current_log_gets_a_pre_vote():
    assert vote.pre_vote_buys_nothing_when_the_returning_log_is_current()[
        "a_current_log_is_granted"
    ]


def test_a_stale_log_does_not():
    assert vote.pre_vote_buys_nothing_when_the_returning_log_is_current()[
        "and_a_stale_one_is_not"
    ]


def test_pre_vote_only_helps_the_stale_case():
    assert vote.pre_vote_buys_nothing_when_the_returning_log_is_current()[
        "so_it_only_helps_the_stale_case"
    ]


def test_a_pre_vote_never_moves_the_term():
    assert vote.pre_vote_buys_nothing_when_the_returning_log_is_current()[
        "the_term_did_not_move_either_way"
    ]


def test_every_loss_rate_still_elects():
    assert vote.a_lossy_link_costs_extra_rounds()["they_all_elect_at_every_rate"]


def test_loss_costs_terms():
    assert vote.a_lossy_link_costs_extra_rounds()["terms_grow_with_loss"]


def test_loss_costs_ticks():
    assert vote.a_lossy_link_costs_extra_rounds()["ticks_grow_with_loss"]


def test_half_loss_costs_real_time():
    assert vote.a_lossy_link_costs_extra_rounds()["half_loss_costs_this_many_ticks"] > 5


def test_two_of_five_elect_nobody():
    assert vote.a_cluster_that_cannot_reach_a_quorum_never_elects()["it_elected_nobody"]


def test_a_stuck_cluster_keeps_trying():
    assert vote.a_cluster_that_cannot_reach_a_quorum_never_elects()["and_it_kept_trying"]


def test_a_stuck_cluster_has_no_leader_anywhere():
    assert vote.a_cluster_that_cannot_reach_a_quorum_never_elects()[
        "every_survivor_is_a_candidate_or_follower"
    ]


def test_restoring_a_quorum_elects():
    assert vote.restoring_a_quorum_elects_immediately()["it_elected"]


def test_the_restored_cluster_keeps_the_high_term():
    assert vote.restoring_a_quorum_elects_immediately()["which_is_at_least_the_stuck_term"]


def test_a_dead_node_is_never_waited_for():
    assert vote.a_vote_request_to_a_stopped_node_is_simply_lost()[
        "the_dead_node_was_never_needed"
    ]


def test_two_of_three_is_a_quorum():
    assert vote.a_vote_request_to_a_stopped_node_is_simply_lost()["and_the_quorum_was_two"]


def test_an_impossible_spread_is_refused():
    assert vote.an_impossible_spread_is_refused()


def test_the_spread_table_covers_eight():
    assert len(vote.compare_the_spreads()) == 8


def test_the_shipped_spread_is_past_the_steep_part():
    assert vote.the_shipped_spread_sits_where_the_curve_bends()["most_of_the_fall_is_below_it"]


def test_ten_times_the_spread_saves_little():
    assert (
        vote.the_shipped_spread_sits_where_the_curve_bends()[
            "and_ten_times_the_spread_saves_this"
        ]
        < 0.25
    )


def test_ten_times_the_spread_costs_many_ticks():
    assert (
        vote.the_shipped_spread_sits_where_the_curve_bends()["for_this_many_extra_ticks"] > 50
    )


def test_the_summary_says_cold_starts_elect():
    assert vote.summarise()["cold_starts_elect"]


def test_the_summary_reports_the_runaway():
    assert vote.summarise()["the_runaway_without_it"] > 10


def test_an_election_reports_whether_it_was_clean():
    made = Election(seed=1, rounds=1, ticks=20, winner="a", terms_burned=2)
    assert made.clean


def test_an_election_without_a_winner_is_not_clean():
    made = Election(seed=1, rounds=1, ticks=20, winner=None, terms_burned=2)
    assert not made.clean


def test_a_long_election_is_not_clean():
    made = Election(seed=1, rounds=5, ticks=90, winner="a", terms_burned=6)
    assert not made.clean


def test_an_election_summarises():
    made = Election(seed=3, rounds=1, ticks=20, winner="a", terms_burned=2)
    assert made.as_dict()["seed"] == 3


def test_a_pre_vote_cluster_still_elects():
    assert Cluster(size=5, seed=2, pre_vote=True).settle().leader() is not None


def test_a_pre_vote_cluster_still_commits():
    made = Cluster(size=5, seed=2, pre_vote=True).settle()
    made.propose(("set", "k", 1))
    made.run(30)
    assert made.committed() == [("set", "k", 1)]


def test_a_pre_candidate_stays_a_follower():
    node = Node(name="a", members=("a", "b", "c"), seed=1, pre_vote=True)
    node.stand()
    assert node.role == FOLLOWER


def test_a_pre_candidate_does_not_bump_its_term():
    node = Node(name="a", members=("a", "b", "c"), seed=1, pre_vote=True)
    before = node.term
    node.stand()
    assert node.term == before


def test_a_pre_candidate_asks_every_peer():
    node = Node(name="a", members=("a", "b", "c"), seed=1, pre_vote=True)
    assert len(node.stand()) == 2


def test_a_pre_candidate_marks_its_requests():
    node = Node(name="a", members=("a", "b", "c"), seed=1, pre_vote=True)
    assert all(one.pre_vote for one in node.stand())


def test_a_pre_candidate_asks_about_the_next_term():
    node = Node(name="a", members=("a", "b", "c"), seed=1, pre_vote=True)
    assert node.stand()[0].term == node.term + 1


def test_a_granted_pre_vote_majority_starts_a_real_election():
    node = Node(name="a", members=("a", "b", "c"), seed=1, pre_vote=True)
    node.stand()
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True, pre_vote=True))
    assert node.role != FOLLOWER


def test_a_node_without_pre_vote_stands_directly():
    node = Node(name="a", members=("a", "b", "c"), seed=1)
    node.stand()
    assert node.role != FOLLOWER


def test_a_pre_vote_from_a_stale_log_is_refused():
    voter = Node(name="a", members=("a", "b", "c"), seed=1)
    voter.log.append([Entry(term=1, index=1, command="x")])
    made = voter.step(
        RequestVote(
            sender="b",
            recipient="a",
            term=voter.term + 1,
            last_index=0,
            last_term=0,
            pre_vote=True,
        )
    )
    assert not made[0].granted


def test_a_pre_vote_at_the_same_term_is_refused():
    voter = Node(name="a", members=("a", "b", "c"), seed=1)
    made = voter.step(
        RequestVote(
            sender="b", recipient="a", term=voter.term, last_index=0, last_term=0, pre_vote=True
        )
    )
    assert not made[0].granted


def test_a_pre_vote_never_deposes_a_leader():
    node = Node(name="a", members=("a", "b", "c"), seed=1)
    node.become_candidate()
    node.step(RequestVote(sender="b", recipient="a", term=node.term, last_index=0, last_term=0))
    was = node.term
    node.step(
        RequestVote(
            sender="b",
            recipient="a",
            term=node.term + 9,
            last_index=0,
            last_term=0,
            pre_vote=True,
        )
    )
    assert node.term == was


def test_the_round_cap_is_generous():
    assert MAX_ROUNDS >= 10


def test_a_pre_vote_cluster_survives_a_partition():
    made = Cluster(size=5, seed=3, pre_vote=True).settle()
    made.partition([["n0"], ["n1", "n2", "n3", "n4"]])
    made.run(80)
    majority = [made.nodes[one] for one in ("n1", "n2", "n3", "n4")]
    assert any(one.role == LEADER for one in majority)
