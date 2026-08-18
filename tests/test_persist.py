from __future__ import annotations

import pytest

from rsm import persist as durability
from rsm.errors import ConfigError
from rsm.log import Entry
from rsm.node import FOLLOWER, Node
from rsm.persist import DURABLE, LOG, TERM, VOLATILE, VOTE, Disk


def test_losing_the_vote_grants_it_twice():
    assert durability.forgetting_the_vote_elects_two_leaders_in_one_term()[
        "losing_it_grants_the_second"
    ]


def test_keeping_the_vote_refuses_the_second():
    assert durability.forgetting_the_vote_elects_two_leaders_in_one_term()[
        "keeping_it_refuses_the_second"
    ]


def test_losing_the_vote_is_two_leaders():
    assert durability.forgetting_the_vote_elects_two_leaders_in_one_term()[
        "and_that_is_election_safety_gone"
    ]


def test_losing_the_term_comes_back_at_one():
    assert durability.forgetting_the_term_replays_an_old_election()["it_came_back_at_one"]


def test_a_kept_term_refuses_a_stale_append():
    assert durability.forgetting_the_term_replays_an_old_election()[
        "the_kept_one_refuses_a_stale_append"
    ]


def test_a_lost_term_accepts_a_stale_append():
    assert durability.forgetting_the_term_replays_an_old_election()[
        "and_the_lost_one_accepts_it"
    ]


def test_losing_the_log_comes_back_empty():
    assert durability.forgetting_the_log_loses_committed_entries()["it_came_back_empty"]


def test_an_empty_node_cannot_be_elected():
    assert durability.forgetting_the_log_loses_committed_entries()["so_it_cannot_be_elected"]


def test_a_healthy_node_refuses_its_vote():
    assert durability.forgetting_the_log_loses_committed_entries()[
        "a_healthy_node_refuses_its_vote"
    ]


def test_a_restart_comes_back_a_follower():
    assert durability.losing_a_volatile_field_costs_time_and_nothing_else()[
        "it_came_back_a_follower"
    ]


def test_a_restart_forgets_its_commit_index():
    assert durability.losing_a_volatile_field_costs_time_and_nothing_else()[
        "and_forgot_where_it_had_committed"
    ]


def test_a_restart_keeps_every_entry():
    assert durability.losing_a_volatile_field_costs_time_and_nothing_else()[
        "but_kept_every_entry"
    ]


def test_more_state_is_discarded_than_kept():
    assert durability.the_durable_list_is_three_fields_and_the_volatile_one_is_six()[
        "more_is_discarded_than_kept"
    ]


def test_the_discard_ratio_is_two():
    assert (
        durability.the_durable_list_is_three_fields_and_the_volatile_one_is_six()[
            "by_this_ratio"
        ]
        == 2.0
    )


def test_a_write_costs_one_sync():
    assert durability.a_write_costs_one_sync_and_a_heartbeat_costs_none()[
        "writes_cost_one_each"
    ]


def test_a_heartbeat_costs_none():
    assert durability.a_write_costs_one_sync_and_a_heartbeat_costs_none()[
        "and_heartbeats_cost_none"
    ]


def test_the_eager_node_loses_the_entry():
    assert durability.replying_before_the_sync_is_the_whole_risk()["which_is_nothing"]


def test_the_careful_node_keeps_it():
    assert durability.replying_before_the_sync_is_the_whole_risk()[
        "and_came_back_with_the_entry"
    ]


def test_the_order_is_the_rule():
    assert durability.replying_before_the_sync_is_the_whole_risk()["so_the_order_is_the_rule"]


def test_an_unknown_durable_field_is_refused():
    assert durability.a_disk_with_an_unknown_field_is_refused()


def test_a_disk_that_keeps_nothing_is_allowed():
    assert durability.a_disk_that_keeps_nothing_is_allowed()[
        "and_the_configuration_was_accepted"
    ]


def test_a_disk_that_keeps_nothing_loses_everything():
    assert durability.a_disk_that_keeps_nothing_is_allowed()["everything_was_lost"]


def test_a_violation_is_raised():
    assert durability.a_violation_is_raised_rather_than_returned()


def test_the_configuration_table_covers_four():
    assert len(durability.compare_the_configurations()) == 4


def test_two_of_three_fields_break_the_scenario():
    assert durability.the_term_and_the_vote_have_to_be_kept_together()[
        "two_of_the_three_break_it"
    ]


def test_they_are_the_term_and_the_vote():
    assert durability.the_term_and_the_vote_have_to_be_kept_together()[
        "and_they_are_the_term_and_the_vote"
    ]


def test_dropping_the_log_is_safe_in_that_scenario():
    assert durability.the_term_and_the_vote_have_to_be_kept_together()[
        "dropping_the_log_is_safe_here"
    ]


def test_they_are_not_three_independent_choices():
    assert durability.the_term_and_the_vote_have_to_be_kept_together()[
        "so_they_are_not_three_independent_choices"
    ]


def test_the_summary_says_the_vote_matters():
    assert durability.summarise()["losing_the_vote_grants_twice"]


def test_the_summary_says_the_order_matters():
    assert durability.summarise()["the_order_matters_too"]


def test_a_disk_starts_at_term_one():
    assert Disk().term == 1


def test_a_disk_starts_with_no_vote():
    assert Disk().voted_for is None


def test_a_disk_starts_empty():
    assert Disk().entries == []


def test_a_disk_counts_its_syncs():
    made = Disk()
    made.write(Node(name="a", members=("a", "b"), seed=1))
    assert made.syncs == 1


def test_a_disk_records_the_term():
    node = Node(name="a", members=("a", "b"), seed=1)
    node.term = 9
    made = Disk()
    made.write(node)
    assert made.term == 9


def test_a_disk_records_the_vote():
    node = Node(name="a", members=("a", "b"), seed=1)
    node.voted_for = "b"
    made = Disk()
    made.write(node)
    assert made.voted_for == "b"


def test_a_disk_records_the_log():
    node = Node(name="a", members=("a", "b"), seed=1)
    node.log.append([Entry(term=1, index=1, command="x")])
    made = Disk()
    made.write(node)
    assert len(made.entries) == 1


def test_a_disk_without_the_term_does_not_record_it():
    node = Node(name="a", members=("a", "b"), seed=1)
    node.term = 9
    made = Disk(durable=(VOTE, LOG))
    made.write(node)
    assert made.term == 1


def test_restoring_gives_a_follower():
    made = Disk()
    assert made.restore("a", ("a", "b")).role == FOLLOWER


def test_restoring_returns_the_term():
    made = Disk(term=6)
    assert made.restore("a", ("a", "b")).term == 6


def test_restoring_without_the_term_gives_one():
    made = Disk(term=6, durable=(VOTE, LOG))
    assert made.restore("a", ("a", "b")).term == 1


def test_restoring_returns_the_log():
    made = Disk(entries=[Entry(term=1, index=1, command="x")])
    assert made.restore("a", ("a", "b")).log.last_index == 1


def test_restoring_without_the_log_gives_nothing():
    made = Disk(entries=[Entry(term=1, index=1)], durable=(TERM, VOTE))
    assert made.restore("a", ("a", "b")).log.empty


def test_a_disk_summarises():
    assert Disk().as_dict()["term"] == 1


def test_a_disk_reports_what_it_keeps():
    assert Disk(durable=(TERM,)).as_dict()["durable"] == [TERM]


def test_an_unknown_field_raises():
    with pytest.raises(ConfigError):
        Disk(durable=("term", "weather"))


def test_there_are_three_durable_fields():
    assert len(DURABLE) == 3


def test_there_are_six_volatile_fields():
    assert len(VOLATILE) == 6


def test_the_durable_fields_are_named():
    assert set(DURABLE) == {TERM, VOTE, LOG}
