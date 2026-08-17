from __future__ import annotations

import pytest

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.verify import invariants as safety
from rsm.verify.invariants import (
    CHECKS,
    ELECTION_SAFETY,
    LEADER_APPEND_ONLY,
    LEADER_COMPLETENESS,
    LOG_MATCHING,
    PROPERTIES,
    STATE_MACHINE_SAFETY,
    Breach,
    Report,
    election_safety,
    inspect,
    log_matching,
    state_machine_safety,
)


def test_a_healthy_run_holds_everything():
    assert safety.a_healthy_run_holds_every_property()["everything_held"]


def test_a_healthy_run_was_a_real_run():
    assert safety.a_healthy_run_holds_every_property()["and_the_run_was_real"]


def test_a_healthy_run_held_all_five():
    assert safety.a_healthy_run_holds_every_property()["held"] == 5


def test_a_partitioned_run_holds_everything():
    assert safety.a_partitioned_run_holds_every_property()["everything_held"]


def test_a_partitioned_run_recovers():
    assert safety.a_partitioned_run_holds_every_property()["the_cluster_recovered"]


def test_a_partitioned_run_agrees_afterwards():
    assert safety.a_partitioned_run_holds_every_property()["and_the_nodes_agree"]


def test_a_crashing_run_holds_everything():
    assert safety.a_crashing_run_holds_every_property()["everything_held"]


def test_a_crashing_run_still_leads():
    assert safety.a_crashing_run_holds_every_property()["the_cluster_still_leads"]


def test_a_crashing_run_agrees():
    assert safety.a_crashing_run_holds_every_property()["and_the_nodes_agree"]


def test_a_clean_report_is_truthy():
    assert safety.a_report_of_a_clean_run_is_truthy()["a_clean_report_is_truthy"]


def test_a_dirty_report_is_falsy():
    assert safety.a_report_of_a_clean_run_is_truthy()["and_a_dirty_one_is_falsy"]


def test_a_dirty_report_names_its_property():
    assert safety.a_report_of_a_clean_run_is_truthy()["the_dirty_one_names_its_property"]


def test_a_dirty_report_still_holds_the_others():
    assert safety.a_report_of_a_clean_run_is_truthy()["which_is_four_of_five"]


def test_a_transient_breach_is_reported():
    assert safety.a_breach_at_tick_forty_is_reported_even_if_it_recovers()["it_reported_it"]


def test_a_transient_breach_names_its_tick():
    assert safety.a_breach_at_tick_forty_is_reported_even_if_it_recovers()[
        "at_the_tick_it_happened"
    ]


def test_a_transient_breach_is_before_the_end():
    assert safety.a_breach_at_tick_forty_is_reported_even_if_it_recovers()[
        "long_before_the_end"
    ]


def test_two_leaders_at_once_happens():
    assert safety.two_leaders_in_different_terms_is_not_a_breach()["it_happened"]


def test_two_leaders_at_once_is_not_a_breach():
    assert safety.two_leaders_in_different_terms_is_not_a_breach()["and_it_is_not_a_breach"]


def test_their_terms_always_differ():
    assert safety.two_leaders_in_different_terms_is_not_a_breach()["their_terms_differ"]


def test_that_run_held_everything():
    assert safety.two_leaders_in_different_terms_is_not_a_breach()["everything_held"]


def test_the_checks_read_state():
    assert safety.the_checks_read_the_nodes_and_not_their_opinions()["they_are_all_state"]


def test_no_check_asks_a_node_if_it_is_healthy():
    assert safety.the_checks_read_the_nodes_and_not_their_opinions()[
        "and_none_asks_whether_it_is_healthy"
    ]


def test_each_check_is_separate():
    assert safety.each_check_can_be_run_on_its_own()["they_are_all_separate"]


def test_each_check_is_clean_on_a_healthy_run():
    assert safety.each_check_can_be_run_on_its_own()["and_all_clean_here"]


def test_a_single_check_returns_a_list():
    assert safety.each_check_can_be_run_on_its_own()["a_single_check_returns_a_list"]


def test_an_unknown_property_is_refused():
    assert safety.an_unknown_property_is_refused()


def test_an_empty_history_is_clean():
    assert safety.an_empty_cluster_history_reports_nothing()["and_it_is_clean"]


def test_an_empty_history_has_no_ticks():
    assert safety.an_empty_cluster_history_reports_nothing()["it_is_empty"]


def test_the_scenario_table_covers_three():
    assert len(safety.compare_the_scenarios()) == 3


def test_every_scenario_is_clean():
    assert safety.no_fault_in_this_package_breaks_a_property()["they_are_all_clean"]


def test_every_property_held_in_every_scenario():
    assert safety.no_fault_in_this_package_breaks_a_property()["every_property_held_everywhere"]


def test_the_checker_can_still_fail():
    assert safety.no_fault_in_this_package_breaks_a_property()["and_the_checker_can_fail"]


def test_the_summary_says_a_dirty_report_is_falsy():
    assert safety.summarise()["a_dirty_report_is_falsy"]


def test_the_summary_says_every_scenario_is_clean():
    assert safety.summarise()["every_scenario_is_clean"]


def test_a_breach_summarises():
    made = Breach(property=LOG_MATCHING, tick=4, detail="x")
    assert made.as_dict()["tick"] == 4


def test_a_breach_prints_itself():
    made = Breach(property=LOG_MATCHING, tick=4, detail="x")
    assert "tick 4" in str(made)


def test_an_unknown_property_raises():
    with pytest.raises(ConfigError):
        Breach(property="availability", tick=1, detail="")


def test_an_empty_report_is_truthy():
    assert bool(Report(ticks=5))


def test_a_report_with_a_breach_is_falsy():
    made = Report(ticks=5, breaches=[Breach(property=LOG_MATCHING, tick=1, detail="x")])
    assert not bool(made)


def test_a_report_lists_what_held():
    made = Report(ticks=5, breaches=[Breach(property=LOG_MATCHING, tick=1, detail="x")])
    assert LOG_MATCHING not in made.held


def test_a_report_lists_what_broke():
    made = Report(ticks=5, breaches=[Breach(property=LOG_MATCHING, tick=1, detail="x")])
    assert made.broken == (LOG_MATCHING,)


def test_a_clean_report_has_no_first_breach():
    assert Report(ticks=5).first is None


def test_a_report_finds_its_earliest_breach():
    made = Report(
        ticks=9,
        breaches=[
            Breach(property=LOG_MATCHING, tick=7, detail="late"),
            Breach(property=ELECTION_SAFETY, tick=2, detail="early"),
        ],
    )
    assert made.first.tick == 2


def test_a_report_filters_by_property():
    made = Report(
        ticks=9,
        breaches=[
            Breach(property=LOG_MATCHING, tick=7, detail="a"),
            Breach(property=ELECTION_SAFETY, tick=2, detail="b"),
        ],
    )
    assert len(made.of(LOG_MATCHING)) == 1


def test_a_report_summarises():
    assert Report(ticks=5).as_dict()["ticks"] == 5


def test_inspecting_a_healthy_cluster_is_clean():
    made = Cluster(size=3, seed=2).settle()
    made.propose(("set", "k", 1))
    made.run(20)
    assert bool(inspect(made))


def test_inspecting_reports_the_tick_count():
    made = Cluster(size=3, seed=2).settle()
    assert inspect(made).ticks == made.now


def test_election_safety_is_clean_on_a_healthy_run():
    made = Cluster(size=3, seed=2).settle()
    assert election_safety(made) == []


def test_log_matching_is_clean_on_a_healthy_run():
    made = Cluster(size=3, seed=2).settle()
    made.propose(("set", "k", 1))
    made.run(20)
    assert log_matching(made) == []


def test_state_machine_safety_is_clean_on_a_healthy_run():
    made = Cluster(size=3, seed=2).settle()
    made.propose(("set", "k", 1))
    made.run(20)
    assert state_machine_safety(made) == []


def test_state_machine_safety_on_an_empty_cluster():
    assert state_machine_safety(Cluster(size=3, seed=1)) == []


def test_there_are_five_properties():
    assert len(PROPERTIES) == 5


def test_there_is_a_check_for_every_property():
    assert set(CHECKS) == set(PROPERTIES)


def test_the_properties_are_named():
    assert LEADER_APPEND_ONLY in PROPERTIES and LEADER_COMPLETENESS in PROPERTIES


def test_state_machine_safety_is_a_property():
    assert STATE_MACHINE_SAFETY in PROPERTIES
