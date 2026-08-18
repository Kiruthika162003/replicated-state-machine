from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.eval import mix as blend
from rsm.eval.mix import (
    LEASE,
    LOCAL,
    READ_INDEX,
    SHARES,
    STRATEGIES,
    THROUGH_THE_LOG,
    Mix,
)


def test_the_reads_become_the_bill():
    assert blend.the_read_strategy_becomes_the_whole_bill_as_the_reads_grow()[
        "at_ninety_percent_it_is_most"
    ]


def test_at_no_reads_they_cost_nothing():
    assert blend.the_read_strategy_becomes_the_whole_bill_as_the_reads_grow()[
        "at_no_reads_it_is_nothing"
    ]


def test_a_read_index_costs_a_write():
    assert blend.the_read_strategy_becomes_the_whole_bill_as_the_reads_grow()[
        "because_a_read_costs_a_write"
    ]


def test_batching_lowers_the_write_cost():
    assert blend.batching_makes_the_read_strategy_matter_more()["it_falls_with_the_batch"]


def test_batching_leaves_the_read_cost_alone():
    assert blend.batching_makes_the_read_strategy_matter_more()["and_the_read_cost_does_not"]


def test_batching_makes_the_reads_take_over():
    assert blend.batching_makes_the_read_strategy_matter_more()["the_reads_take_over"]


def test_the_reads_become_nearly_everything():
    assert blend.batching_makes_the_read_strategy_matter_more()["which_is_nearly_everything"]


def test_the_two_correct_strategies_cost_the_same_messages():
    assert blend.the_two_correct_strategies_cost_the_same_messages_and_different_bytes()[
        "they_are_the_same"
    ]


def test_they_differ_in_bytes():
    assert blend.the_two_correct_strategies_cost_the_same_messages_and_different_bytes()[
        "and_the_bytes_are_not"
    ]


def test_the_entry_stays():
    assert blend.the_two_correct_strategies_cost_the_same_messages_and_different_bytes()[
        "and_the_entry_stays"
    ]


def test_the_free_strategy_is_the_wrong_one():
    assert blend.the_free_strategy_is_the_wrong_one_and_the_lease_is_the_compromise()[
        "the_free_one_is_the_wrong_one"
    ]


def test_the_lease_is_the_cheapest_correct_one():
    assert blend.the_free_strategy_is_the_wrong_one_and_the_lease_is_the_compromise()[
        "the_lease_is_the_cheapest_correct_one"
    ]


def test_the_lease_beats_the_read_index():
    assert blend.the_free_strategy_is_the_wrong_one_and_the_lease_is_the_compromise()[
        "and_it_costs_a_fraction_of_a_read_index"
    ]


def test_a_read_share_outside_the_range_is_refused():
    assert blend.a_read_share_outside_the_range_is_refused()


def test_an_unknown_strategy_is_refused():
    assert blend.an_unknown_strategy_is_refused()


def test_a_zero_batch_is_refused():
    assert blend.a_zero_batch_is_refused()


def test_a_cluster_of_none_is_refused():
    assert blend.a_cluster_of_none_is_refused()


def test_a_write_only_workload_cannot_choose():
    assert blend.a_workload_of_only_writes_makes_the_strategy_irrelevant()[
        "so_a_write_only_benchmark_cannot_choose"
    ]


def test_a_write_only_workload_costs_the_same_everywhere():
    assert blend.a_workload_of_only_writes_makes_the_strategy_irrelevant()[
        "they_are_all_the_same"
    ]


def test_correctness_still_differs_at_no_reads():
    assert blend.a_workload_of_only_writes_makes_the_strategy_irrelevant()[
        "correctness_still_differs"
    ]


def test_the_strategy_table_covers_four():
    assert len(blend.compare_the_strategies()) == 4


def test_the_share_table_covers_them_all():
    assert len(blend.compare_the_shares()) == len(SHARES)


def test_the_summary_says_the_reads_become_the_bill():
    assert blend.summarise()["the_reads_become_the_bill"]


def test_the_summary_says_batching_makes_it_worse():
    assert blend.summarise()["batching_makes_it_worse"]


def test_a_mix_reports_its_peers():
    assert Mix(reads=0.5, strategy=LOCAL, size=5).peers == 4


def test_a_write_costs_two_messages_per_peer():
    assert Mix(reads=0.5, strategy=LOCAL, size=5).write_cost == 8.0


def test_batching_divides_the_write_cost():
    assert Mix(reads=0.5, strategy=LOCAL, size=5, batch=4).write_cost == 2.0


def test_a_local_read_is_free():
    assert Mix(reads=0.5, strategy=LOCAL).read_cost == 0.0


def test_a_lease_read_is_nearly_free():
    made = Mix(reads=0.5, strategy=LEASE)
    assert 0 < made.read_cost < made.write_cost


def test_a_read_index_costs_a_round():
    assert Mix(reads=0.5, strategy=READ_INDEX, size=5).read_cost == 8.0


def test_a_read_through_the_log_costs_a_write():
    made = Mix(reads=0.5, strategy=THROUGH_THE_LOG)
    assert made.read_cost == made.write_cost


def test_a_mix_of_no_reads_costs_a_write():
    made = Mix(reads=0.0, strategy=READ_INDEX)
    assert made.cost == made.write_cost


def test_a_mix_of_all_reads_costs_a_read():
    made = Mix(reads=1.0, strategy=READ_INDEX)
    assert made.cost == made.read_cost


def test_a_free_read_lowers_the_average():
    assert Mix(reads=0.9, strategy=LOCAL).cost < Mix(reads=0.0, strategy=LOCAL).cost


def test_the_read_share_of_cost_is_zero_without_reads():
    assert Mix(reads=0.0, strategy=READ_INDEX).read_share_of_cost == 0.0


def test_a_free_read_takes_no_share_of_the_cost():
    assert Mix(reads=0.9, strategy=LOCAL).read_share_of_cost == 0.0


def test_a_zero_cost_mix_has_no_share():
    made = Mix(reads=1.0, strategy=LOCAL)
    assert made.cost == 0.0 and made.read_share_of_cost == 0.0


def test_a_local_read_is_not_correct():
    assert not Mix(reads=0.5, strategy=LOCAL).correct


def test_the_other_strategies_are():
    assert all(Mix(reads=0.5, strategy=one).correct for one in STRATEGIES if one != LOCAL)


def test_a_mix_reports_its_write_bytes():
    assert Mix(reads=0.5, strategy=LOCAL).write_bytes > 0


def test_batching_lowers_the_write_bytes():
    assert (
        Mix(reads=0.5, strategy=LOCAL, batch=8).write_bytes
        < Mix(reads=0.5, strategy=LOCAL).write_bytes
    )


def test_a_local_read_costs_no_bytes():
    assert Mix(reads=0.5, strategy=LOCAL).read_bytes == 0.0


def test_a_read_through_the_log_costs_the_most_bytes():
    made = [Mix(reads=0.5, strategy=one) for one in STRATEGIES]
    assert max(made, key=lambda one: one.read_bytes).strategy == THROUGH_THE_LOG


def test_a_mix_summarises():
    assert Mix(reads=0.5, strategy=LEASE).as_dict()["strategy"] == LEASE


def test_a_bad_read_share_raises():
    with pytest.raises(ConfigError):
        Mix(reads=-0.1, strategy=LOCAL)


def test_an_unknown_strategy_raises():
    with pytest.raises(ConfigError):
        Mix(reads=0.5, strategy="hoping")


def test_a_zero_batch_raises():
    with pytest.raises(ConfigError):
        Mix(reads=0.5, strategy=LOCAL, batch=0)


def test_a_zero_size_raises():
    with pytest.raises(ConfigError):
        Mix(reads=0.5, strategy=LOCAL, size=0)


def test_there_are_four_strategies():
    assert len(STRATEGIES) == 4


def test_the_shares_span_the_range():
    assert min(SHARES) == 0.0 and max(SHARES) < 1.0
