from __future__ import annotations

import pytest

from rsm import priority as prefer
from rsm.errors import ConfigError
from rsm.priority import (
    EVERY,
    FLAT,
    MEMBERS,
    RANKED,
    STEP,
    WINDOW,
    Outcome,
    Priorities,
    Run,
)


def test_the_preference_puts_it_in_charge():
    assert prefer.a_priority_delay_puts_the_preferred_node_in_charge()["the_preference_worked"]


def test_the_flat_run_does_not_prefer_it():
    assert prefer.a_priority_delay_puts_the_preferred_node_in_charge()[
        "and_the_flat_run_did_not_prefer_it"
    ]


def test_both_schemes_settle_on_one_leader():
    assert prefer.a_priority_delay_puts_the_preferred_node_in_charge()["both_settled_on_one"]


def test_the_preference_loses_the_office_after_a_flap():
    assert prefer.a_priority_decides_an_election_and_never_reclaims_one()["it_lost_the_office"]


def test_the_preference_never_takes_it_back():
    assert prefer.a_priority_decides_an_election_and_never_reclaims_one()[
        "and_never_took_it_back"
    ]


def test_the_plain_scheme_tries_no_transfer():
    assert prefer.a_priority_decides_an_election_and_never_reclaims_one()[
        "which_it_did_not_try"
    ]


def test_reclaiming_recovers_the_office():
    assert prefer.reclaiming_costs_an_election_every_time_the_node_returns()[
        "it_recovered_the_office"
    ]


def test_reclaiming_costs_an_election():
    assert prefer.reclaiming_costs_an_election_every_time_the_node_returns()[
        "and_it_cost_an_election"
    ]


def test_reclaiming_leaves_availability_alone_once():
    assert prefer.reclaiming_costs_an_election_every_time_the_node_returns()[
        "and_availability_was_unchanged"
    ]


def test_the_flat_scheme_elects_nobody_when_the_preferred_flaps():
    assert prefer.preferring_an_unreliable_node_costs_a_quarter_of_the_availability()[
        "it_elected_nobody"
    ]


def test_the_preference_costs_availability():
    assert prefer.preferring_an_unreliable_node_costs_a_quarter_of_the_availability()[
        "the_preference_cost_availability"
    ]


def test_the_cost_is_large():
    made = prefer.preferring_an_unreliable_node_costs_a_quarter_of_the_availability()
    assert made["by_this_share"] > 0.1


def test_the_elections_bought_the_share():
    assert prefer.preferring_an_unreliable_node_costs_a_quarter_of_the_availability()[
        "elections_bought_the_share"
    ]


def test_the_top_rank_waits_nothing():
    assert prefer.an_unranked_node_waits_as_long_as_the_last_one()["the_top_waits_nothing"]


def test_an_unranked_node_waits_most():
    assert prefer.an_unranked_node_waits_as_long_as_the_last_one()[
        "and_an_unranked_node_waits_most"
    ]


def test_a_flat_scheme_has_no_delays():
    assert prefer.a_flat_priority_is_the_shipped_behaviour()["they_are_all_zero"]


def test_a_ranked_scheme_has_them():
    assert prefer.a_flat_priority_is_the_shipped_behaviour()["and_the_ranked_one_is_not"]


def test_the_ranked_delays_are_a_step_apart():
    assert prefer.a_flat_priority_is_the_shipped_behaviour()["which_are_a_step_apart"]


def test_an_empty_order_is_refused():
    assert prefer.an_empty_priority_order_is_refused()


def test_a_repeated_node_is_refused():
    assert prefer.a_repeated_node_in_the_order_is_refused()


def test_a_negative_step_is_refused():
    assert prefer.a_negative_step_is_refused()


def test_a_cluster_of_none_is_refused():
    assert prefer.a_run_of_no_nodes_is_refused()


def test_the_scheme_table_covers_five():
    assert len(prefer.compare_the_schemes()) == 5


def test_the_flapping_case_costs_more():
    assert prefer.the_preference_is_free_on_a_steady_cluster_and_dear_on_a_flapping_one()[
        "the_flapping_case_costs_more"
    ]


def test_the_flapping_case_gets_less_for_it():
    assert prefer.the_preference_is_free_on_a_steady_cluster_and_dear_on_a_flapping_one()[
        "and_it_gets_less_for_it"
    ]


def test_it_is_the_same_configuration():
    assert prefer.the_preference_is_free_on_a_steady_cluster_and_dear_on_a_flapping_one()[
        "same_configuration"
    ]


def test_the_summary_says_the_delay_works():
    assert prefer.summarise()["the_delay_puts_it_in_charge"]


def test_the_summary_says_it_never_reclaims():
    assert prefer.summarise()["but_it_never_reclaims"]


def test_the_preferred_node_is_first():
    assert Priorities(order=("n2", "n0")).preferred == "n2"


def test_a_rank_costs_a_step():
    made = Priorities(order=("n0", "n1", "n2"), step=5)
    assert made.delay("n2") == 10


def test_the_top_rank_costs_nothing():
    assert Priorities(order=("n0", "n1")).delay("n0") == 0


def test_a_stranger_waits_past_the_last_rank():
    made = Priorities(order=("n0", "n1"), step=5)
    assert made.delay("n9") == 10


def test_a_flat_scheme_says_it_is_flat():
    assert Priorities(order=("n0", "n1"), step=0).flat


def test_a_ranked_scheme_says_it_is_not():
    assert not Priorities(order=("n0", "n1")).flat


def test_priorities_summarise():
    assert Priorities(order=("n0",)).as_dict()["preferred"] == "n0"


def test_an_empty_order_raises():
    with pytest.raises(ConfigError):
        Priorities(order=())


def test_a_repeated_rank_raises():
    with pytest.raises(ConfigError):
        Priorities(order=("n0", "n1", "n0"))


def test_a_negative_step_raises():
    with pytest.raises(ConfigError):
        Priorities(order=("n0",), step=-1)


def test_an_outcome_reports_its_share():
    made = Outcome(name="x", preferred="n0", preferred_ticks=30, ticks=100)
    assert made.share == 0.3


def test_an_outcome_with_no_ticks_has_no_share():
    assert Outcome(name="x").share == 0.0


def test_an_outcome_reports_its_availability():
    made = Outcome(name="x", attempted=10, committed=8)
    assert made.availability == 0.8


def test_an_outcome_with_nothing_attempted_has_none():
    assert Outcome(name="x").availability == 0.0


def test_an_outcome_counts_distinct_leaders():
    assert Outcome(name="x", leaders=["n0", "n1", "n0"]).distinct == 2


def test_an_outcome_that_kept_the_office_is_truthy():
    assert Outcome(name="x", preferred_ticks=80, ticks=100)


def test_an_outcome_that_lost_it_is_falsy():
    assert not Outcome(name="x", preferred_ticks=10, ticks=100)


def test_an_outcome_summarises():
    assert Outcome(name="named").as_dict()["run"] == "named"


def test_a_run_elects_the_preferred_node():
    made = Run(Priorities(order=("n1", "n0", "n2")), size=3).go("x", window=200)
    assert made.share > 0.5


def test_a_flat_run_still_elects_somebody():
    made = Run(Priorities(order=("n0", "n1", "n2"), step=0), size=3).go("x", window=200)
    assert made.distinct >= 1


def test_a_run_of_no_nodes_raises():
    with pytest.raises(ConfigError):
        Run(RANKED, size=0)


def test_a_run_commits_what_it_attempts():
    made = Run(Priorities(order=("n1", "n0", "n2")), size=3).go("x", window=200)
    assert made.availability > 0.8


def test_the_shipped_members_are_five():
    assert len(MEMBERS) == 5


def test_the_flat_scheme_covers_every_member():
    assert set(FLAT.order) == set(MEMBERS)


def test_the_ranked_scheme_covers_every_member():
    assert set(RANKED.order) == set(MEMBERS)


def test_the_step_is_smaller_than_a_timeout():
    assert STEP < 10


def test_the_window_holds_several_elections():
    assert WINDOW > 100


def test_writes_are_attempted_regularly():
    assert 0 < EVERY < WINDOW
