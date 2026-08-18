from __future__ import annotations

import pytest

from rsm import quorum as rules
from rsm.errors import ConfigError
from rsm.quorum import (
    EXHAUSTIVE,
    SIZES,
    Rule,
    disjoint,
    every_pair_overlaps,
    majority,
    raft,
    tolerates,
)


def test_the_sum_test_matches_the_search():
    assert rules.the_intersection_rule_is_exactly_the_arithmetic()["they_always_agree"]


def test_the_sum_test_covered_every_rule():
    assert rules.the_intersection_rule_is_exactly_the_arithmetic()["rules_checked"] > 100


def test_the_smallest_symmetric_rule_is_the_majority():
    assert rules.a_majority_for_both_is_the_smallest_symmetric_rule_that_works()[
        "it_is_the_majority"
    ]


def test_one_less_than_a_majority_fails():
    assert rules.a_majority_for_both_is_the_smallest_symmetric_rule_that_works()[
        "one_less_fails"
    ]


def test_an_even_size_never_tolerates_more():
    assert rules.an_even_cluster_tolerates_no_more_than_the_odd_one_below_it()[
        "the_even_one_never_tolerates_more"
    ]


def test_an_even_size_always_costs_more():
    assert rules.an_even_cluster_tolerates_no_more_than_the_odd_one_below_it()[
        "and_always_costs_more"
    ]


def test_five_and_six_tolerate_the_same():
    made = rules.an_even_cluster_tolerates_no_more_than_the_odd_one_below_it()
    assert made["five_and_six"] == [2, 2]


def test_the_flexible_rules_all_intersect():
    assert rules.a_cheaper_commit_quorum_is_safe_and_costs_availability()["all_three_intersect"]


def test_the_search_agrees_with_the_flexible_rules():
    assert rules.a_cheaper_commit_quorum_is_safe_and_costs_availability()[
        "and_the_search_agrees"
    ]


def test_a_cheap_write_rule_costs_less_per_write():
    assert rules.a_cheaper_commit_quorum_is_safe_and_costs_availability()[
        "cheap_writes_costs_less_per_write"
    ]


def test_a_cheap_write_rule_elects_less_reliably():
    assert rules.a_cheaper_commit_quorum_is_safe_and_costs_availability()[
        "but_survives_fewer_failures_at_election"
    ]


def test_a_cheap_write_rule_tolerates_less():
    assert rules.a_cheaper_commit_quorum_is_safe_and_costs_availability()[
        "the_cheap_rule_tolerates_less"
    ]


def test_every_unsafe_rule_has_a_counterexample():
    assert rules.the_rules_that_fail_are_exactly_the_ones_that_do_not_add_up()[
        "every_one_has_a_counterexample"
    ]


def test_no_counterexample_overlaps():
    assert rules.the_rules_that_fail_are_exactly_the_ones_that_do_not_add_up()[
        "and_none_of_them_overlap"
    ]


def test_there_are_ten_unsafe_rules_at_five():
    assert (
        rules.the_rules_that_fail_are_exactly_the_ones_that_do_not_add_up()["unsafe_rules"]
        == 10
    )


def test_a_cluster_of_one_asks_nobody():
    assert rules.a_cluster_of_one_is_its_own_quorum()["it_asks_nobody"]


def test_a_cluster_of_one_survives_nothing():
    assert rules.a_cluster_of_one_is_its_own_quorum()["and_survives_nothing"]


def test_a_cluster_of_one_intersects_trivially():
    assert rules.a_cluster_of_one_is_its_own_quorum()["trivially"]


def test_one_and_two_both_tolerate_nothing():
    assert rules.a_cluster_of_two_is_worse_than_a_cluster_of_one()["both_tolerate_nothing"]


def test_two_costs_an_acknowledgement():
    assert rules.a_cluster_of_two_is_worse_than_a_cluster_of_one()[
        "and_costs_an_acknowledgement"
    ]


def test_the_second_node_is_a_copy_not_a_spare():
    assert rules.a_cluster_of_two_is_worse_than_a_cluster_of_one()[
        "so_the_second_node_is_a_copy_not_a_spare"
    ]


def test_a_witness_helps_elections():
    assert rules.a_witness_that_votes_and_never_holds_data_still_counts()[
        "the_witness_helps_elections"
    ]


def test_a_witness_that_holds_nothing_does_not_help_writes():
    assert rules.a_witness_that_votes_and_never_holds_data_still_counts()[
        "and_if_it_holds_nothing_writes_do_not_improve"
    ]


def test_every_witness_rule_intersects():
    assert rules.a_witness_that_votes_and_never_holds_data_still_counts()[
        "all_of_them_intersect"
    ]


def test_a_witness_is_a_quorum_rule():
    assert rules.a_witness_that_votes_and_never_holds_data_still_counts()[
        "so_a_witness_is_a_quorum_rule"
    ]


def test_every_growth_step_gains_nothing_or_one():
    assert rules.growing_a_cluster_by_one_never_helps_twice()["it_is_zero_or_one"]


def test_stepping_off_an_even_size_gains():
    assert rules.growing_a_cluster_by_one_never_helps_twice()["stepping_off_an_even_size_gains"]


def test_stepping_off_an_odd_size_does_not():
    assert rules.growing_a_cluster_by_one_never_helps_twice()[
        "stepping_off_an_odd_one_does_not"
    ]


def test_half_the_nodes_buy_nothing():
    assert rules.growing_a_cluster_by_one_never_helps_twice()["so_half_the_nodes_buy_nothing"]


def test_a_zero_size_is_refused():
    assert rules.a_zero_size_is_refused()


def test_an_oversized_quorum_is_refused():
    assert rules.a_quorum_larger_than_the_cluster_is_refused()


def test_an_empty_quorum_is_refused():
    assert rules.a_quorum_of_none_is_refused()


def test_a_rule_of_no_size_is_refused():
    assert rules.a_rule_of_no_size_is_refused()


def test_the_rule_table_covers_twenty_five():
    assert len(rules.compare_the_rules()) == 25


def test_most_rules_at_five_are_safe():
    assert rules.most_rules_at_size_five_are_unsafe_and_the_safe_ones_all_cost_the_same()[
        "most_are_safe"
    ]


def test_the_boundary_sums_to_one_more_than_the_size():
    assert rules.most_rules_at_size_five_are_unsafe_and_the_safe_ones_all_cost_the_same()[
        "the_boundary_sums_to_six"
    ]


def test_the_boundary_rules_all_cost_the_same():
    assert rules.most_rules_at_size_five_are_unsafe_and_the_safe_ones_all_cost_the_same()[
        "and_they_all_cost_the_same"
    ]


def test_the_boundary_has_five_rules():
    assert (
        rules.most_rules_at_size_five_are_unsafe_and_the_safe_ones_all_cost_the_same()[
            "on_the_boundary"
        ]
        == 5
    )


def test_the_summary_says_the_sum_test_is_exact():
    assert rules.summarise()["the_sum_test_is_exact"]


def test_the_summary_says_the_majority_is_forced():
    assert rules.summarise()["the_majority_is_forced"]


def test_the_summary_covers_every_size():
    assert rules.summarise()["sizes"] == list(SIZES)


def test_a_majority_of_three_is_two():
    assert majority(3) == 2


def test_a_majority_of_four_is_three():
    assert majority(4) == 3


def test_a_majority_of_one_is_one():
    assert majority(1) == 1


def test_a_majority_of_zero_raises():
    with pytest.raises(ConfigError):
        majority(0)


def test_three_tolerates_one():
    assert tolerates(3) == 1


def test_four_also_tolerates_one():
    assert tolerates(4) == 1


def test_the_raft_rule_is_symmetric():
    made = raft(5)
    assert made.election == made.commit == 3


def test_the_raft_rule_intersects():
    assert raft(7).intersects


def test_a_rule_reports_its_write_cost():
    assert Rule(size=5, election=3, commit=3).write_cost == 2


def test_a_rule_reports_its_election_cost():
    assert Rule(size=5, election=4, commit=2).election_cost == 3


def test_a_rule_of_one_costs_nothing_to_write():
    assert Rule(size=1, election=1, commit=1).write_cost == 0


def test_a_rule_reports_what_writes_survive():
    assert Rule(size=5, election=4, commit=2).survives_writes == 3


def test_a_rule_reports_what_elections_survive():
    assert Rule(size=5, election=4, commit=2).survives_elections == 1


def test_a_rule_survives_the_worst_of_the_two():
    assert Rule(size=5, election=4, commit=2).survives == 1


def test_a_rule_summarises():
    assert Rule(size=5, election=3, commit=3).as_dict()["size"] == 5


def test_a_named_rule_keeps_its_name():
    assert Rule(size=5, election=3, commit=3, name="x").as_dict()["rule"] == "x"


def test_an_unnamed_rule_describes_itself():
    assert Rule(size=5, election=3, commit=2).as_dict()["rule"] == "3/2 of 5"


def test_a_rule_prints_itself():
    assert "out of 5" in str(Rule(size=5, election=3, commit=3))


def test_an_unsafe_rule_has_a_disjoint_pair():
    assert disjoint(Rule(size=5, election=2, commit=2)) is not None


def test_a_safe_rule_has_none():
    assert disjoint(Rule(size=5, election=3, commit=3)) is None


def test_the_disjoint_pair_really_is_disjoint():
    left, right = disjoint(Rule(size=5, election=2, commit=2))
    assert not left & right


def test_every_pair_overlaps_agrees_with_the_sum():
    made = Rule(size=6, election=4, commit=3)
    assert every_pair_overlaps(made) == made.intersects


def test_a_quorum_of_everyone_always_overlaps():
    assert every_pair_overlaps(Rule(size=4, election=4, commit=1))


def test_the_exhaustive_sizes_are_small():
    assert max(EXHAUSTIVE) <= 7
