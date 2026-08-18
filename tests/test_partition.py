from __future__ import annotations

import pytest

from rsm import partition as cuts
from rsm.cluster import Cluster
from rsm.errors import ConfigError, UnknownNode
from rsm.partition import (
    BOTH,
    DIRECTIONS,
    INBOUND,
    OUTBOUND,
    Cut,
    Cuts,
    Run,
    run,
)


def test_a_clean_run_is_healthy():
    assert cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()[
        "clean_is_healthy"
    ]


def test_isolating_a_follower_is_harmless():
    assert cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()[
        "isolating_it_is_harmless"
    ]


def test_an_isolated_follower_still_burns_terms():
    assert cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()[
        "and_it_still_burns_terms"
    ]


def test_silencing_a_follower_is_harmless():
    assert cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()[
        "silencing_it_is_harmless"
    ]


def test_a_silenced_follower_burns_no_terms():
    assert cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()[
        "and_it_burns_no_terms"
    ]


def test_deafening_a_follower_is_not_harmless():
    assert cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()[
        "deafening_it_is_not"
    ]


def test_the_two_directions_disagree():
    assert cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()[
        "and_the_two_directions_disagree"
    ]


def test_a_deafened_follower_loses_writes():
    made = cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()
    assert made["committed"] < made["proposed"]


def test_a_deafened_follower_causes_churn():
    made = cuts.a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()
    assert made["leadership_changes"] > 2


def test_pre_vote_stops_the_churn():
    assert cuts.a_pre_vote_round_removes_the_disruption_entirely()["it_stopped_the_churn"]


def test_pre_vote_stops_the_term_climbing():
    assert cuts.a_pre_vote_round_removes_the_disruption_entirely()[
        "and_the_term_stopped_climbing"
    ]


def test_pre_vote_commits_everything():
    assert cuts.a_pre_vote_round_removes_the_disruption_entirely()["it_committed_everything"]


def test_pre_vote_costs_more_messages():
    assert cuts.a_pre_vote_round_removes_the_disruption_entirely()["and_it_costs_more_messages"]


def test_the_pre_vote_overhead_is_modest():
    assert cuts.a_pre_vote_round_removes_the_disruption_entirely()["by_this_ratio"] < 2.0


def test_a_deaf_leader_looks_healthy():
    assert cuts.a_leader_that_cannot_hear_holds_the_office_and_commits_nothing()[
        "it_looks_perfectly_healthy"
    ]


def test_a_deaf_leader_commits_nothing():
    assert cuts.a_leader_that_cannot_hear_holds_the_office_and_commits_nothing()[
        "and_committed_nothing"
    ]


def test_a_mute_leader_is_replaced():
    assert cuts.a_leader_that_cannot_hear_holds_the_office_and_commits_nothing()[
        "the_mute_one_recovers"
    ]


def test_the_mute_leader_causes_an_election():
    assert cuts.a_leader_that_cannot_hear_holds_the_office_and_commits_nothing()[
        "by_electing_someone_else"
    ]


def test_the_quiet_cut_is_the_dangerous_one():
    assert cuts.a_leader_that_cannot_hear_holds_the_office_and_commits_nothing()[
        "so_the_dangerous_cut_is_the_quiet_one"
    ]


def test_one_broken_link_is_harmless():
    assert cuts.one_broken_link_is_survivable_and_one_broken_node_is_not()[
        "one_link_is_harmless"
    ]


def test_one_broken_node_is_not():
    assert cuts.one_broken_link_is_survivable_and_one_broken_node_is_not()[
        "and_the_whole_node_is_not"
    ]


def test_the_churn_is_in_the_whole_node_case():
    assert cuts.one_broken_link_is_survivable_and_one_broken_node_is_not()[
        "the_churn_is_all_in_the_whole_node_case"
    ]


def test_the_broken_link_leaves_the_term_alone():
    made = cuts.one_broken_link_is_survivable_and_one_broken_node_is_not()
    assert made["link_terms"] < made["whole_terms"]


def test_every_size_is_disrupted():
    assert cuts.the_damage_needs_a_majority_to_hear_the_higher_term()["every_size_is_disrupted"]


def test_no_size_commits_everything():
    assert cuts.the_damage_needs_a_majority_to_hear_the_higher_term()[
        "and_none_of_them_committed_everything"
    ]


def test_the_largest_cluster_is_no_better():
    assert cuts.the_damage_needs_a_majority_to_hear_the_higher_term()[
        "the_largest_is_no_better"
    ]


def test_size_is_not_the_answer():
    assert cuts.the_damage_needs_a_majority_to_hear_the_higher_term()[
        "so_size_is_not_the_answer"
    ]


def test_healing_loses_nothing():
    assert cuts.healing_a_cut_recovers_without_help()["nothing_was_lost"]


def test_healing_makes_progress_again():
    assert cuts.healing_a_cut_recovers_without_help()["it_made_progress_again"]


def test_healing_leaves_a_leader():
    assert cuts.healing_a_cut_recovers_without_help()["there_is_a_leader"]


def test_healing_leaves_everyone_agreeing():
    assert cuts.healing_a_cut_recovers_without_help()["and_everyone_agrees"]


def test_a_cut_without_a_node_is_refused():
    assert cuts.a_cut_without_a_node_is_refused()


def test_an_unknown_direction_is_refused():
    assert cuts.an_unknown_direction_is_refused()


def test_cutting_a_node_from_itself_is_refused():
    assert cuts.cutting_a_node_from_itself_is_refused()


def test_cutting_a_stranger_is_refused():
    assert cuts.cutting_a_stranger_is_refused()


def test_the_cut_table_covers_seven():
    assert len(cuts.compare_the_cuts()) == 7


def test_exactly_one_run_is_inverted():
    assert cuts.only_one_cut_in_the_table_is_genuinely_misleading()["there_is_exactly_one"]


def test_the_inverted_run_is_the_deaf_leader():
    assert cuts.only_one_cut_in_the_table_is_genuinely_misleading()["and_it_is_the_deaf_leader"]


def test_the_inverted_run_has_full_uptime():
    assert cuts.only_one_cut_in_the_table_is_genuinely_misleading()["its_uptime"] == 1.0


def test_the_other_broken_runs_show_a_symptom():
    assert cuts.only_one_cut_in_the_table_is_genuinely_misleading()[
        "and_they_dip_in_uptime_or_churn"
    ]


def test_the_commit_index_is_the_signal():
    assert cuts.only_one_cut_in_the_table_is_genuinely_misleading()[
        "so_the_commit_index_is_the_signal"
    ]


def test_the_summary_says_deafening_is_worse():
    assert cuts.summarise()["deafening_one_is_not"]


def test_the_summary_says_pre_vote_helps():
    assert cuts.summarise()["pre_vote_stops_it"]


def test_the_summary_counts_the_directions():
    assert cuts.summarise()["directions"] == len(DIRECTIONS)


def test_a_both_cut_blocks_outgoing():
    assert Cut(node="n0").blocks("n0", "n1")


def test_a_both_cut_blocks_incoming():
    assert Cut(node="n0").blocks("n1", "n0")


def test_a_both_cut_leaves_others_alone():
    assert not Cut(node="n0").blocks("n1", "n2")


def test_an_outbound_cut_blocks_only_sending():
    made = Cut(node="n0", direction=OUTBOUND)
    assert made.blocks("n0", "n1") and not made.blocks("n1", "n0")


def test_an_inbound_cut_blocks_only_receiving():
    made = Cut(node="n0", direction=INBOUND)
    assert made.blocks("n1", "n0") and not made.blocks("n0", "n1")


def test_a_peer_cut_blocks_one_link():
    made = Cut(node="n0", peer="n1")
    assert made.blocks("n0", "n1") and not made.blocks("n0", "n2")


def test_a_peer_cut_works_in_the_named_direction():
    made = Cut(node="n0", direction=INBOUND, peer="n1")
    assert made.blocks("n1", "n0") and not made.blocks("n0", "n1")


def test_a_cut_summarises():
    assert Cut(node="n0", direction=INBOUND).as_dict()["direction"] == INBOUND


def test_a_cut_prints_itself():
    assert str(Cut(node="n0", direction=BOTH)) == "n0 cut both"


def test_a_peer_cut_prints_its_peer():
    assert "from n1" in str(Cut(node="n0", peer="n1"))


def test_an_empty_cut_raises():
    with pytest.raises(ConfigError):
        Cut(node="")


def test_an_unknown_direction_raises():
    with pytest.raises(ConfigError):
        Cut(node="n0", direction="up")


def test_a_self_cut_raises():
    with pytest.raises(ConfigError):
        Cut(node="n0", peer="n0")


def test_cuts_block_what_they_are_given():
    made = Cluster(size=3, seed=0)
    rules = Cuts(made).add(Cut(node="n0", direction=OUTBOUND))
    try:
        assert not made.net.reachable("n0", "n1")
    finally:
        rules.restore()


def test_cuts_leave_the_rest_reachable():
    made = Cluster(size=3, seed=0)
    rules = Cuts(made).add(Cut(node="n0", direction=OUTBOUND))
    try:
        assert made.net.reachable("n1", "n2")
    finally:
        rules.restore()


def test_healing_removes_every_cut():
    made = Cluster(size=3, seed=0)
    rules = Cuts(made).add(Cut(node="n0"))
    rules.heal()
    try:
        assert made.net.reachable("n0", "n1")
    finally:
        rules.restore()


def test_restoring_gives_the_network_its_rule_back():
    made = Cluster(size=3, seed=0)
    Cuts(made).add(Cut(node="n0")).restore()
    assert "reachable" not in made.net.__dict__


def test_cuts_keep_the_networks_own_partitions():
    made = Cluster(size=3, seed=0)
    made.partition([["n0"], ["n1", "n2"]])
    rules = Cuts(made)
    try:
        assert not made.net.reachable("n0", "n1")
    finally:
        rules.restore()


def test_cuts_summarise():
    made = Cluster(size=3, seed=0)
    rules = Cuts(made).add(Cut(node="n0"))
    try:
        assert len(rules.as_dict()["cuts"]) == 1
    finally:
        rules.restore()


def test_adding_a_stranger_raises():
    made = Cluster(size=3, seed=0)
    rules = Cuts(made)
    try:
        with pytest.raises(UnknownNode):
            rules.add(Cut(node="n9"))
    finally:
        rules.restore()


def test_a_run_reports_its_uptime():
    assert 0.0 <= run("x", [], ticks=60, writes=2).uptime <= 1.0


def test_a_run_of_no_ticks_has_no_uptime():
    made = Run(
        name="x",
        terms=1,
        leaders=0,
        committed=0,
        proposed=0,
        messages=0,
        leaderless=0,
        ticks=0,
    )
    assert made.uptime == 0.0


def test_a_run_that_committed_everything_is_truthy():
    assert run("x", [], ticks=80, writes=2)


def test_a_run_that_proposed_nothing_is_falsy():
    made = Run(
        name="x",
        terms=1,
        leaders=1,
        committed=0,
        proposed=0,
        messages=1,
        leaderless=0,
        ticks=10,
    )
    assert not made


def test_a_run_summarises():
    assert run("named", [], ticks=60, writes=2).as_dict()["run"] == "named"


def test_the_directions_are_three():
    assert len(DIRECTIONS) == 3
