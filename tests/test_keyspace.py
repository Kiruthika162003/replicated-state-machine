from __future__ import annotations

import pytest

from rsm import keyspace as shard
from rsm.errors import ConfigError
from rsm.keyspace import KEYS, WINDOW, Federation, Keyspace, digest


def test_every_group_commits_everything():
    assert shard.the_ceiling_multiplies_with_the_groups()["they_all_committed_everything"]


def test_every_group_elects_a_leader():
    assert shard.the_ceiling_multiplies_with_the_groups()["every_group_elected"]


def test_the_cost_per_write_falls():
    assert shard.the_ceiling_multiplies_with_the_groups()["the_cost_per_write_falls"]


def test_there_is_no_traffic_between_groups():
    assert shard.the_ceiling_multiplies_with_the_groups()[
        "and_there_is_no_traffic_between_groups"
    ]


def test_a_cross_group_write_lands_in_two_groups():
    assert shard.a_write_across_two_groups_is_not_atomic()["they_are_different"]


def test_the_halves_disagree_mid_write():
    assert shard.a_write_across_two_groups_is_not_atomic()["the_halves_disagree"]


def test_the_halves_agree_eventually():
    assert shard.a_write_across_two_groups_is_not_atomic()["and_they_agree_eventually"]


def test_nothing_ordered_the_two_halves():
    assert shard.a_write_across_two_groups_is_not_atomic()[
        "so_the_window_closes_on_its_own_and_nothing_ordered_it"
    ]


def test_a_broken_group_takes_nothing():
    assert shard.a_group_failure_takes_out_its_share_and_no_more()[
        "the_broken_group_took_nothing"
    ]


def test_the_other_groups_take_everything():
    assert shard.a_group_failure_takes_out_its_share_and_no_more()["the_others_took_everything"]


def test_the_share_lost_is_about_a_quarter():
    assert shard.a_group_failure_takes_out_its_share_and_no_more()["and_it_is_about_a_quarter"]


def test_a_single_cluster_would_have_survived_it():
    assert shard.a_group_failure_takes_out_its_share_and_no_more()[
        "which_a_single_cluster_would_have_survived"
    ]


def test_the_placement_is_stable():
    assert shard.the_placement_is_a_digest_because_the_builtin_hash_is_not_stable()[
        "it_is_stable"
    ]


def test_a_second_keyspace_agrees():
    assert shard.the_placement_is_a_digest_because_the_builtin_hash_is_not_stable()[
        "a_second_keyspace_agrees"
    ]


def test_a_different_group_count_moves_a_key():
    assert shard.the_placement_is_a_digest_because_the_builtin_hash_is_not_stable()[
        "and_a_different_group_count_moves_it"
    ]


def test_four_groups_are_close_to_even():
    assert shard.the_keys_spread_evenly_enough_and_never_perfectly()["four_is_close_to_even"]


def test_nothing_is_perfectly_even():
    made = shard.the_keys_spread_evenly_enough_and_never_perfectly()
    assert made["nothing_is_perfectly_even"]


def test_the_balance_worsens_with_the_groups():
    assert shard.the_keys_spread_evenly_enough_and_never_perfectly()[
        "and_it_worsens_with_the_groups"
    ]


def test_a_zero_group_keyspace_is_refused():
    assert shard.a_zero_group_keyspace_is_refused()


def test_an_empty_key_is_refused():
    assert shard.an_empty_key_is_refused()


def test_a_federation_of_no_nodes_is_refused():
    assert shard.a_federation_of_no_nodes_is_refused()


def test_one_group_holds_every_key():
    assert shard.one_group_is_the_ordinary_cluster()["every_key_in_one_group"]


def test_one_group_commits_everything():
    assert shard.one_group_is_the_ordinary_cluster()["it_committed_everything"]


def test_one_group_is_exactly_even():
    assert shard.one_group_is_the_ordinary_cluster()["which_is_exactly_even"]


def test_the_group_table_covers_four():
    assert len(shard.compare_the_group_counts()) == 4


def test_every_row_commits_everything():
    assert shard.sharding_trades_one_guarantee_for_two_properties()[
        "every_row_committed_everything"
    ]


def test_only_one_group_is_atomic():
    assert shard.sharding_trades_one_guarantee_for_two_properties()["and_only_at_one_group"]


def test_atomicity_goes_at_the_first_split():
    assert shard.sharding_trades_one_guarantee_for_two_properties()[
        "the_property_is_lost_at_the_first_split"
    ]


def test_atomicity_never_comes_back():
    assert shard.sharding_trades_one_guarantee_for_two_properties()["and_never_comes_back"]


def test_the_summary_says_a_cross_group_write_is_not_atomic():
    assert shard.summarise()["a_cross_group_write_is_not_atomic"]


def test_the_summary_says_a_group_failure_is_partial():
    assert shard.summarise()["a_group_failure_is_partial"]


def test_a_digest_is_stable():
    assert digest("alpha") == digest("alpha")


def test_two_keys_give_two_digests():
    assert digest("alpha") != digest("beta")


def test_a_digest_is_a_number():
    assert isinstance(digest("alpha"), int)


def test_a_digest_is_positive():
    assert digest("alpha") > 0


def test_a_key_lands_in_a_group():
    assert 0 <= Keyspace(groups=4).group_of("alpha") < 4


def test_the_same_key_lands_in_the_same_group():
    space = Keyspace(groups=4)
    assert space.group_of("alpha") == space.group_of("alpha")


def test_one_group_takes_every_key():
    space = Keyspace(groups=1)
    assert all(space.group_of(f"k{one}") == 0 for one in range(20))


def test_an_empty_key_raises():
    with pytest.raises(ConfigError):
        Keyspace(groups=4).group_of("")


def test_a_zero_group_keyspace_raises():
    with pytest.raises(ConfigError):
        Keyspace(groups=0)


def test_a_negative_group_count_raises():
    with pytest.raises(ConfigError):
        Keyspace(groups=-2)


def test_a_spread_covers_every_group():
    space = Keyspace(groups=4)
    assert set(space.spread([f"k{one}" for one in range(40)])) == {0, 1, 2, 3}


def test_a_spread_adds_up():
    space = Keyspace(groups=4)
    keys = [f"k{one}" for one in range(40)]
    assert sum(space.spread(keys).values()) == len(keys)


def test_an_empty_spread_is_all_zeroes():
    assert set(Keyspace(groups=3).spread([]).values()) == {0}


def test_a_balance_of_one_group_is_one():
    assert Keyspace(groups=1).balance([f"k{one}" for one in range(10)]) == 1.0


def test_a_balance_is_at_least_one():
    assert Keyspace(groups=4).balance([f"k{one}" for one in range(80)]) >= 1.0


def test_an_empty_balance_is_zero():
    assert Keyspace(groups=4).balance([]) == 0.0


def test_a_keyspace_summarises():
    assert Keyspace(groups=6).as_dict()["groups"] == 6


def test_a_federation_makes_a_cluster_per_group():
    made = Federation(keyspace=Keyspace(groups=3))
    assert len(made.clusters) == 3


def test_a_federation_elects_in_every_group():
    made = Federation(keyspace=Keyspace(groups=3))
    assert len(made.leaders()) == 3


def test_a_federation_writes_to_the_owning_group():
    made = Federation(keyspace=Keyspace(groups=3))
    made.write("alpha", 1)
    made.tick(20)
    owner = made.keyspace.group_of("alpha")
    assert len(made.clusters[owner].committed()) == 1


def test_a_federation_leaves_the_other_groups_alone():
    made = Federation(keyspace=Keyspace(groups=3))
    made.write("alpha", 1)
    made.tick(20)
    owner = made.keyspace.group_of("alpha")
    assert all(not made.clusters[one].committed() for one in made.clusters if one != owner)


def test_a_federation_counts_every_commit():
    made = Federation(keyspace=Keyspace(groups=2))
    for one in range(6):
        made.write(f"k{one}", one)
    made.tick(30)
    assert made.committed() == 6


def test_a_federation_counts_every_message():
    made = Federation(keyspace=Keyspace(groups=2))
    assert made.messages() > 0


def test_a_federation_summarises():
    made = Federation(keyspace=Keyspace(groups=2))
    assert made.as_dict()["groups"] == 2


def test_a_federation_reports_its_node_count():
    made = Federation(keyspace=Keyspace(groups=3), size=5)
    assert made.as_dict()["nodes"] == 15


def test_a_federation_of_no_nodes_raises():
    with pytest.raises(ConfigError):
        Federation(keyspace=Keyspace(groups=2), size=0)


def test_every_group_has_a_leader_name():
    made = Federation(keyspace=Keyspace(groups=4))
    assert all(isinstance(one, str) for one in made.leaders().values())


def test_the_key_count_is_worth_spreading():
    assert KEYS >= 100


def test_the_window_is_long_enough():
    assert WINDOW >= 100
