from __future__ import annotations

import pytest

from rsm import cluster as group
from rsm.cluster import SETTLE_TICKS, Cluster, Snapshot
from rsm.errors import ConfigError, NoLeader, UnknownNode
from rsm.net import Conditions
from rsm.node import FOLLOWER, LEADER


def test_every_seed_elects_a_leader():
    assert group.a_fresh_cluster_elects_exactly_one_leader()["they_all_elected"]


def test_election_is_not_always_the_same_node():
    assert group.a_fresh_cluster_elects_exactly_one_leader()["and_not_always_the_same_node"]


def test_the_slowest_election_is_bounded():
    assert group.a_fresh_cluster_elects_exactly_one_leader()["slowest"] < 100


def test_a_write_reaches_every_node():
    assert group.a_write_reaches_every_node()["they_all_applied_everything"]


def test_a_write_arrives_in_the_same_order_everywhere():
    assert group.a_write_reaches_every_node()["and_in_the_same_order"]


def test_the_order_is_the_write_order():
    assert group.a_write_reaches_every_node()["the_order_is_the_write_order"]


def test_killing_the_leader_recovers():
    assert group.killing_the_leader_elects_another()["they_all_recovered"]


def test_the_dead_node_never_comes_back_as_leader():
    assert group.killing_the_leader_elects_another()["and_never_the_dead_node"]


def test_recovery_is_bounded():
    assert group.killing_the_leader_elects_another()["slowest_recovery"] < 200


def test_old_writes_survive_a_failure():
    assert group.a_cluster_keeps_serving_after_one_failure()["the_old_writes_survived"]


def test_new_writes_land_after_a_failure():
    assert group.a_cluster_keeps_serving_after_one_failure()["and_the_new_ones_landed"]


def test_the_failure_cost_an_election():
    assert group.a_cluster_keeps_serving_after_one_failure()["it_took_an_election"]


def test_a_minority_elects_nobody():
    assert group.a_minority_cannot_elect_a_leader()["the_minority_elected_nobody"]


def test_the_majority_still_has_a_leader():
    assert group.a_minority_cannot_elect_a_leader()["and_the_majority_has_one"]


def test_the_minority_burns_terms():
    assert group.a_minority_cannot_elect_a_leader()["which_is_above_the_majority"]


def test_a_healed_partition_keeps_the_early_writes():
    assert group.a_healed_partition_reconciles()["the_early_writes_survived"]


def test_a_healed_partition_levels_the_logs():
    assert group.a_healed_partition_reconciles()["every_log_is_the_same_length"]


def test_a_healed_partition_agrees():
    assert group.a_healed_partition_reconciles()["and_the_nodes_agree"]


def test_the_same_seed_replays():
    assert group.the_same_seed_replays_the_same_cluster()["they_are_identical"]


def test_the_replay_is_a_real_run():
    assert group.the_same_seed_replays_the_same_cluster()["and_it_is_a_real_run"]


def test_the_replay_found_one_transcript():
    assert group.the_same_seed_replays_the_same_cluster()["distinct"] == 1


def test_the_invariants_run_every_tick():
    assert group.the_invariants_are_checked_every_tick()["it_checked_every_tick"]


def test_no_term_ever_had_two_leaders():
    assert group.the_invariants_are_checked_every_tick()["never_two_in_one_term"]


def test_two_leaders_at_once_happens():
    assert group.two_leaders_at_once_is_not_a_violation()["it_happens"]


def test_two_leaders_at_once_does_not_always_happen():
    assert group.two_leaders_at_once_is_not_a_violation()["but_not_every_time"]


def test_two_leaders_always_claim_different_terms():
    assert group.two_leaders_at_once_is_not_a_violation()["the_terms_always_differ"]


def test_a_restart_keeps_the_term():
    assert group.a_restarted_node_keeps_its_log_and_forgets_the_rest()["term_kept"]


def test_a_restart_keeps_the_vote():
    assert group.a_restarted_node_keeps_its_log_and_forgets_the_rest()["vote_kept"]


def test_a_restart_keeps_the_log():
    assert group.a_restarted_node_keeps_its_log_and_forgets_the_rest()["log_kept"]


def test_a_restart_comes_back_a_follower():
    assert group.a_restarted_node_keeps_its_log_and_forgets_the_rest()[
        "it_came_back_a_follower"
    ]


def test_a_restart_forgets_what_it_applied():
    assert group.a_restarted_node_keeps_its_log_and_forgets_the_rest()[
        "and_forgot_what_it_had_applied"
    ]


def test_a_restarted_node_was_behind():
    assert group.a_restarted_node_catches_up()["it_was_behind"]


def test_a_restarted_node_catches_up():
    assert group.a_restarted_node_catches_up()["and_it_caught_up"]


def test_a_restarted_node_applies_the_same_commands():
    assert group.a_restarted_node_catches_up()["and_applied_the_same_commands"]


def test_a_cluster_of_one_sends_nothing():
    assert group.a_cluster_of_one_needs_no_messages()["it_sent_nothing"]


def test_a_cluster_of_one_still_commits():
    assert group.a_cluster_of_one_needs_no_messages()["and_still_committed"]


def test_proposing_without_a_leader_is_refused():
    assert group.proposing_without_a_leader_is_refused()


def test_crashing_an_unknown_node_is_refused():
    assert group.crashing_an_unknown_node_is_refused()


def test_restarting_a_running_node_is_refused():
    assert group.restarting_a_running_node_is_refused()


def test_a_cluster_of_no_nodes_is_refused():
    assert group.a_cluster_of_no_nodes_is_refused()


def test_the_size_table_covers_four():
    assert len(group.compare_the_cluster_sizes()) == 4


def test_messages_grow_with_the_size():
    assert group.a_larger_cluster_costs_more_messages_per_write()["it_grows_with_the_size"]


def test_messages_are_linear_in_the_peers():
    assert group.a_larger_cluster_costs_more_messages_per_write()[
        "and_it_is_linear_in_the_peers"
    ]


def test_seven_costs_three_times_three():
    assert group.a_larger_cluster_costs_more_messages_per_write()["seven_over_three"] == 3.0


def test_seven_tolerates_two_more_failures():
    assert (
        group.a_larger_cluster_costs_more_messages_per_write()["for_this_many_more_failures"]
        == 2
    )


def test_the_election_time_barely_moves_with_size():
    assert group.a_larger_cluster_costs_more_messages_per_write()[
        "but_the_election_time_barely_moves"
    ]


def test_the_summary_says_every_seed_elects():
    assert group.summarise()["every_seed_elects"]


def test_the_summary_says_the_seed_replays():
    assert group.summarise()["the_seed_replays"]


def test_a_cluster_names_its_members():
    assert Cluster(size=3).members == ("n0", "n1", "n2")


def test_a_cluster_starts_with_everyone_up():
    assert len(Cluster(size=5).up) == 5


def test_a_cluster_starts_at_tick_zero():
    assert Cluster(size=3).now == 0


def test_a_cluster_starts_with_no_leader():
    assert Cluster(size=3).leader() is None


def test_settling_elects():
    assert Cluster(size=3, seed=1).settle().leader() is not None


def test_settling_leaves_the_wire_quiet():
    assert Cluster(size=3, seed=1).settle().net.quiet


def test_running_advances_the_clock():
    made = Cluster(size=3, seed=1).run(10)
    assert made.now == 10


def test_running_records_a_snapshot_per_tick():
    made = Cluster(size=3, seed=1).run(10)
    assert len(made.history) == 10


def test_a_crashed_node_leaves_the_up_list():
    made = Cluster(size=3, seed=1)
    made.crash("n1")
    assert made.up == ["n0", "n2"]


def test_a_restarted_node_rejoins_the_up_list():
    made = Cluster(size=3, seed=1)
    made.crash("n1")
    made.restart("n1")
    assert "n1" in made.up


def test_a_crashed_node_receives_nothing():
    made = Cluster(size=3, seed=1).settle()
    made.crash("n1")
    before = made.nodes["n1"].log.last_index
    made.run(30)
    assert made.nodes["n1"].log.last_index == before


def test_a_cluster_reports_its_committed_commands():
    made = Cluster(size=3, seed=2).settle()
    made.propose(("set", "k", 1))
    made.run(20)
    assert made.committed() == [("set", "k", 1)]


def test_a_cluster_with_no_leader_has_committed_nothing():
    assert Cluster(size=3).committed() == []


def test_a_settled_cluster_agrees():
    made = Cluster(size=3, seed=2).settle()
    made.propose(("set", "k", 1))
    made.run(20)
    assert made.agreed()


def test_a_cluster_summarises():
    made = Cluster(size=3, seed=2).settle()
    assert made.as_dict()["size"] == 3


def test_a_cluster_counts_its_elections():
    made = Cluster(size=3, seed=2).settle()
    assert made.elections >= 1


def test_a_cluster_counts_its_messages():
    made = Cluster(size=3, seed=2).settle()
    assert made.net.counts.sent > 0


def test_a_partition_reaches_the_network():
    made = Cluster(size=3, seed=1)
    made.partition([["n0"], ["n1", "n2"]])
    assert not made.net.reachable("n0", "n1")


def test_healing_reaches_the_network():
    made = Cluster(size=3, seed=1)
    made.partition([["n0"], ["n1", "n2"]])
    made.heal()
    assert made.net.reachable("n0", "n1")


def test_a_cluster_survives_a_lossy_link():
    made = Cluster(size=3, seed=4, conditions=Conditions(loss=0.2)).settle()
    assert made.leader() is not None


def test_a_cluster_survives_a_jittery_link():
    made = Cluster(size=3, seed=4, conditions=Conditions(min_delay=1, max_delay=4)).settle()
    assert made.leader() is not None


def test_a_snapshot_lists_its_leaders():
    made = Snapshot(
        tick=1,
        roles={"a": LEADER, "b": FOLLOWER},
        terms={"a": 2, "b": 2},
        commits={"a": 0, "b": 0},
        applied={"a": [], "b": []},
    )
    assert made.leaders == ["a"]


def test_a_snapshot_groups_leaders_by_term():
    made = Snapshot(
        tick=1,
        roles={"a": LEADER, "b": LEADER},
        terms={"a": 2, "b": 3},
        commits={"a": 0, "b": 0},
        applied={"a": [], "b": []},
    )
    assert made.leaders_by_term == {2: ["a"], 3: ["b"]}


def test_a_snapshot_summarises():
    made = Snapshot(
        tick=7,
        roles={"a": LEADER},
        terms={"a": 2},
        commits={"a": 3},
        applied={"a": []},
    )
    assert made.as_dict()["tick"] == 7


def test_a_negative_cluster_size_is_refused():
    with pytest.raises(ConfigError):
        Cluster(size=-1)


def test_proposing_with_no_leader_raises():
    with pytest.raises(NoLeader):
        Cluster(size=3).propose("x")


def test_crashing_a_stranger_raises():
    with pytest.raises(UnknownNode):
        Cluster(size=3).crash("zz")


def test_the_settle_budget_is_generous():
    assert SETTLE_TICKS >= 200
