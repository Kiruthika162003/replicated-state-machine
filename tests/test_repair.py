from __future__ import annotations

import pytest

from rsm import repair as fix
from rsm.errors import ConfigError
from rsm.log import Log, written
from rsm.node import Node
from rsm.repair import (
    LIMIT,
    STRATEGIES,
    Repair,
    bisect,
    hybrid,
    probe,
    skip,
    walk,
)


def _pair(leader_terms, follower_terms, term=200):
    return fix._pair(leader_terms, follower_terms, term=term)


def test_every_strategy_finds_the_same_place():
    assert fix.every_strategy_finds_the_same_place()["all_found_it"]


def test_the_strategies_agree_at_every_depth():
    assert fix.every_strategy_finds_the_same_place()["they_agree_at_every_depth"]


def test_they_land_on_the_agreement_point():
    assert fix.every_strategy_finds_the_same_place()["and_it_is_the_agreement_point"]


def test_walking_costs_the_depth_plus_one():
    assert fix.walking_back_costs_one_probe_per_entry()["it_is_the_depth_plus_one"]


def test_walking_grows_without_bound():
    assert fix.walking_back_costs_one_probe_per_entry()["and_it_grows_without_bound"]


def test_the_conflict_reply_is_flat_on_one_term():
    assert fix.the_conflict_reply_collapses_one_term_into_one_probe()["it_is_flat"]


def test_the_conflict_reply_costs_two_probes():
    assert fix.the_conflict_reply_collapses_one_term_into_one_probe()["at_this_many"] == 2


def test_walking_is_not_flat():
    assert fix.the_conflict_reply_collapses_one_term_into_one_probe()["and_walking_is_not"]


def test_the_conflict_saving_is_large_when_deep():
    made = fix.the_conflict_reply_collapses_one_term_into_one_probe()
    assert made["saving_at_the_deepest"] > 100


def test_alternating_terms_defeat_the_optimisation():
    assert fix.the_conflict_reply_is_worth_nothing_when_the_terms_alternate()[
        "they_are_identical"
    ]


def test_the_alternating_cost_grows():
    assert fix.the_conflict_reply_is_worth_nothing_when_the_terms_alternate()[
        "and_both_grow_with_the_depth"
    ]


def test_the_worst_case_is_no_optimisation():
    assert fix.the_conflict_reply_is_worth_nothing_when_the_terms_alternate()[
        "so_the_worst_case_is_no_optimisation_at_all"
    ]


def test_bisecting_barely_moves_with_depth():
    assert fix.bisecting_costs_the_logarithm_of_the_log_not_the_divergence()["it_barely_moves"]


def test_bisecting_beats_walking_when_deep():
    assert fix.bisecting_costs_the_logarithm_of_the_log_not_the_divergence()[
        "it_is_much_cheaper_when_deep"
    ]


def test_bisecting_stays_under_its_bound():
    assert fix.bisecting_costs_the_logarithm_of_the_log_not_the_divergence()[
        "and_it_stays_under_the_bound"
    ]


def test_walking_is_flat_in_the_log_length():
    assert fix.bisecting_is_the_worst_strategy_when_the_follower_is_nearly_current()[
        "walking_is_flat"
    ]


def test_bisecting_grows_with_the_log():
    assert fix.bisecting_is_the_worst_strategy_when_the_follower_is_nearly_current()[
        "bisecting_grows_with_the_log"
    ]


def test_walking_wins_the_shallow_cases():
    assert fix.bisecting_is_the_worst_strategy_when_the_follower_is_nearly_current()[
        "walking_wins_everywhere_here"
    ]


def test_the_hybrid_matches_walking_when_shallow():
    assert fix.a_few_steps_then_a_bisection_gets_both_cases()["it_matches_walking_when_shallow"]


def test_the_hybrid_beats_walking_when_deep():
    assert fix.a_few_steps_then_a_bisection_gets_both_cases()["and_beats_walking_when_deep"]


def test_the_hybrid_costs_more_than_bisecting_when_deep():
    assert fix.a_few_steps_then_a_bisection_gets_both_cases()[
        "it_costs_more_than_bisecting_when_deep"
    ]


def test_the_hybrid_is_never_the_worst():
    assert fix.a_few_steps_then_a_bisection_gets_both_cases()[
        "and_it_is_never_the_worst_of_the_three"
    ]


def test_a_probe_below_zero_is_refused():
    assert fix.a_probe_below_zero_is_refused()


def test_a_negative_probe_count_is_refused():
    assert fix.a_negative_probe_count_is_refused()


def test_a_negative_patience_is_refused():
    assert fix.a_negative_patience_is_refused()


def test_three_strategies_confirm_a_current_follower_at_once():
    assert fix.bisecting_pays_its_toll_even_when_there_is_nothing_to_repair()[
        "three_took_one_probe"
    ]


def test_bisecting_cannot_confirm_in_one_probe():
    assert fix.bisecting_pays_its_toll_even_when_there_is_nothing_to_repair()[
        "and_bisecting_took_more"
    ]


def test_every_strategy_finds_the_end_of_an_identical_log():
    assert fix.bisecting_pays_its_toll_even_when_there_is_nothing_to_repair()[
        "and_all_found_the_end"
    ]


def test_an_empty_follower_is_repaired_from_zero():
    assert fix.an_empty_follower_is_repaired_from_the_beginning()["they_all_reached_zero"]


def test_walking_pays_for_every_index_of_an_empty_follower():
    assert fix.an_empty_follower_is_repaired_from_the_beginning()[
        "walking_paid_for_every_index"
    ]


def test_bisecting_does_not():
    assert fix.an_empty_follower_is_repaired_from_the_beginning()["and_bisecting_did_not"]


def test_the_strategy_table_covers_every_case():
    assert len(fix.compare_the_strategies()) == 16


def test_no_strategy_wins_every_case():
    assert fix.bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
        "no_strategy_wins_everything"
    ]


def test_every_repair_in_the_table_found_its_place():
    assert fix.bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
        "every_repair_found_its_place"
    ]


def test_bisecting_has_the_smallest_worst_gap():
    assert fix.bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
        "bisecting_has_the_smallest_worst_gap"
    ]


def test_the_hybrid_is_second_on_the_worst_case():
    assert fix.bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
        "and_the_hybrid_is_next"
    ]


def test_the_hybrid_is_free_on_the_shallow_cases():
    assert fix.bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
        "the_hybrid_is_free_when_shallow"
    ]


def test_bisecting_pays_on_the_shallow_cases():
    assert fix.bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
        "and_bisecting_is_not"
    ]


def test_the_ranking_depends_on_the_workload():
    assert fix.bisecting_has_the_best_worst_case_and_the_hybrid_has_the_best_common_case()[
        "so_the_ranking_is_about_the_workload"
    ]


def test_the_summary_says_walking_is_linear():
    assert fix.summarise()["walking_is_linear"]


def test_the_summary_says_bisecting_is_logarithmic():
    assert fix.summarise()["bisecting_is_logarithmic"]


def test_the_summary_lists_every_strategy():
    assert fix.summarise()["strategies"] == sorted(STRATEGIES)


def test_a_probe_at_the_end_of_a_matching_log_succeeds():
    leader, follower = _pair([1] * 10, [1] * 10)
    assert probe(leader, follower, 10).success


def test_a_probe_past_a_divergence_fails():
    leader, follower = _pair([1] * 10 + [2], [1] * 10 + [3])
    assert not probe(leader, follower, 11).success


def test_a_probe_at_zero_always_succeeds():
    leader, follower = _pair([1] * 10, [2] * 10)
    assert probe(leader, follower, 0).success


def test_a_probe_carries_no_entries():
    leader, follower = _pair([1] * 10, [1] * 10)
    before = len(follower.log)
    probe(leader, follower, 10)
    assert len(follower.log) == before


def test_a_negative_probe_raises():
    leader, follower = _pair([1] * 4, [1] * 4)
    with pytest.raises(ConfigError):
        probe(leader, follower, -1)


def test_walking_finds_a_shallow_divergence():
    assert walk(*_pair([1] * 10 + [2], [1] * 10 + [3])).matched == 10


def test_skipping_finds_the_same_place():
    assert skip(*_pair([1] * 10 + [2] * 5, [1] * 10 + [3] * 5)).matched == 10


def test_bisecting_finds_the_same_place():
    assert bisect(*_pair([1] * 10 + [2] * 5, [1] * 10 + [3] * 5)).matched == 10


def test_the_hybrid_finds_the_same_place():
    assert hybrid(*_pair([1] * 10 + [2] * 5, [1] * 10 + [3] * 5)).matched == 10


def test_a_repair_reports_whether_it_found_the_point():
    assert walk(*_pair([1] * 6, [1] * 6)).found


def test_a_successful_repair_is_truthy():
    assert bisect(*_pair([1] * 6 + [2], [1] * 6 + [3]))


def test_a_repair_that_missed_is_falsy():
    assert not Repair(strategy="x", probes=1, matched=3, divergence=5)


def test_a_repair_summarises():
    assert walk(*_pair([1] * 6, [1] * 6)).as_dict()["strategy"] == "walk back"


def test_a_repair_prints_itself():
    assert "probes" in str(walk(*_pair([1] * 6, [1] * 6)))


def test_a_negative_probe_count_raises():
    with pytest.raises(ConfigError):
        Repair(strategy="x", probes=-2, matched=0, divergence=0)


def test_a_negative_patience_raises():
    leader, follower = _pair([1] * 6, [1] * 6)
    with pytest.raises(ConfigError):
        hybrid(leader, follower, patience=-1)


def test_a_patience_of_zero_is_a_bisection():
    leader, follower = _pair([1] * 40 + [2] * 20, [1] * 40 + [3] * 20)
    plain = bisect(*_pair([1] * 40 + [2] * 20, [1] * 40 + [3] * 20))
    assert hybrid(leader, follower, patience=0).probes == plain.probes


def test_a_large_patience_is_a_walk():
    leader, follower = _pair([1] * 20 + [2] * 4, [1] * 20 + [3] * 4)
    plain = walk(*_pair([1] * 20 + [2] * 4, [1] * 20 + [3] * 4))
    assert hybrid(leader, follower, patience=50).probes == plain.probes


def test_an_empty_follower_matches_at_zero():
    leader = Node(name="n0", members=("n0", "n1"), seed=0)
    follower = Node(name="n1", members=("n0", "n1"), seed=1)
    leader.term = follower.term = 3
    leader.log = written([1] * 5)
    follower.log = Log()
    assert bisect(leader, follower).matched == 0


def test_the_limit_is_generous():
    assert LIMIT > 1000


def test_every_strategy_is_named_in_the_table():
    assert set(STRATEGIES) == {"walk back", "skip term", "bisect", "hybrid"}
