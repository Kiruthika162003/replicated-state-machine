from __future__ import annotations

import pytest

from rsm import machine as store
from rsm.errors import ConfigError, Refused
from rsm.machine import (
    COMMANDS,
    COMPARE_AND_SET,
    DELETE,
    IDEMPOTENT,
    INCREMENT,
    NOW,
    SET,
    Command,
    Machine,
    replay,
)


def test_replaying_agrees():
    assert store.the_same_commands_give_the_same_state()["they_all_agree"]


def test_replaying_agrees_on_results_too():
    assert store.the_same_commands_give_the_same_state()["and_so_do_the_results"]


def test_replaying_found_one_state():
    assert store.the_same_commands_give_the_same_state()["distinct_states"] == 1


def test_order_changes_the_state():
    assert store.order_changes_the_state()["they_differ"]


def test_the_shuffle_used_the_same_commands():
    assert store.order_changes_the_state()["same_commands"]


def test_a_random_command_breaks_agreement():
    assert store.a_non_deterministic_command_breaks_agreement_silently()[
        "but_the_states_differ"
    ]


def test_the_logs_were_identical_anyway():
    assert store.a_non_deterministic_command_breaks_agreement_silently()[
        "the_logs_are_identical"
    ]


def test_nothing_raised_about_it():
    assert store.a_non_deterministic_command_breaks_agreement_silently()["and_nothing_raised"]


def test_the_command_is_flagged_as_non_deterministic():
    assert store.a_non_deterministic_command_breaks_agreement_silently()[
        "the_command_is_not_deterministic"
    ]


def test_the_control_agrees():
    assert store.a_deterministic_command_survives_the_same_test()["they_agree"]


def test_the_control_command_is_deterministic():
    assert store.a_deterministic_command_survives_the_same_test()[
        "the_command_is_deterministic"
    ]


def test_a_cluster_diverges_on_a_random_command():
    assert store.a_cluster_applying_a_random_command_diverges()["the_states_differ"]


def test_the_cluster_logs_were_identical():
    assert store.a_cluster_applying_a_random_command_diverges()["logs_identical"]


def test_the_cluster_reported_nothing_wrong():
    assert store.a_cluster_applying_a_random_command_diverges()["the_cluster_reported_nothing"]


def test_an_increment_doubles_on_a_retry():
    assert store.applying_an_increment_twice_doubles_it()["the_increment_doubled"]


def test_a_set_does_not():
    assert store.applying_an_increment_twice_doubles_it()["the_set_did_not"]


def test_only_one_swap_succeeds():
    assert store.compare_and_set_makes_ordering_visible_to_a_client()["only_one_succeeded"]


def test_the_first_swap_wins():
    assert store.compare_and_set_makes_ordering_visible_to_a_client()["the_first_one_won"]


def test_the_losing_swap_changes_nothing():
    assert store.compare_and_set_makes_ordering_visible_to_a_client()[
        "and_the_loser_changed_nothing"
    ]


def test_a_delete_returns_what_it_removed():
    assert store.a_delete_returns_what_it_removed()["the_first_returned_the_value"]


def test_a_second_delete_returns_nothing():
    assert store.a_delete_returns_what_it_removed()["and_the_second_returned_nothing"]


def test_delete_leaves_the_same_state_either_way():
    assert store.a_delete_returns_what_it_removed()["the_state_is_the_same_either_way"]


def test_incrementing_a_string_is_refused():
    assert store.incrementing_a_string_is_refused()


def test_an_unknown_command_is_refused():
    assert store.an_unknown_command_is_refused()


def test_a_command_without_a_key_is_refused():
    assert store.a_command_without_a_key_is_refused()


def test_a_machine_starts_empty():
    assert store.a_machine_starts_empty()["it_is_empty"]


def test_a_fresh_machine_has_applied_nothing():
    assert store.a_machine_starts_empty()["and_has_applied_nothing"]


def test_a_missing_key_reads_as_nothing():
    assert store.a_machine_starts_empty()["reading_a_missing_key_gives_nothing"]


def test_a_digest_catches_a_value_difference():
    assert store.a_digest_catches_a_difference_a_length_would_miss()["the_digests_differ"]


def test_a_count_would_have_missed_it():
    assert store.a_digest_catches_a_difference_a_length_would_miss()["same_key_count"]


def test_the_command_table_covers_five():
    assert len(store.compare_the_commands()) == len(COMMANDS)


def test_only_two_commands_are_safe_to_retry():
    assert store.most_commands_are_not_safe_to_retry()["only_two_are_safe"]


def test_the_safe_ones_are_the_idempotent_ones():
    assert store.most_commands_are_not_safe_to_retry()["and_they_are_the_idempotent_ones"]


def test_one_command_is_not_deterministic():
    assert store.most_commands_are_not_safe_to_retry()["one_is_not_even_deterministic"] == 1


def test_the_summary_says_a_random_command_diverges():
    assert store.summarise()["a_random_command_diverges"]


def test_the_summary_says_the_logs_were_identical():
    assert store.summarise()["with_identical_logs"]


def test_a_set_stores_a_value():
    made = Machine()
    made.apply(Command(name=SET, key="k", value=7))
    assert made.get("k") == 7


def test_a_set_returns_the_value():
    made = Machine()
    assert made.apply(Command(name=SET, key="k", value=7)) == 7


def test_a_delete_removes_the_key():
    made = Machine()
    made.apply(Command(name=SET, key="k", value=7))
    made.apply(Command(name=DELETE, key="k"))
    assert made.get("k") is None


def test_an_increment_starts_from_zero():
    made = Machine()
    assert made.apply(Command(name=INCREMENT, key="k", value=3)) == 3


def test_an_increment_defaults_to_one():
    made = Machine()
    assert made.apply(Command(name=INCREMENT, key="k")) == 1


def test_a_swap_that_matches_succeeds():
    made = Machine()
    made.apply(Command(name=SET, key="k", value=1))
    assert made.apply(Command(name=COMPARE_AND_SET, key="k", expected=1, value=2)) is True


def test_a_swap_that_misses_fails():
    made = Machine()
    made.apply(Command(name=SET, key="k", value=1))
    assert made.apply(Command(name=COMPARE_AND_SET, key="k", expected=9, value=2)) is False


def test_a_swap_on_a_missing_key_can_match_nothing():
    made = Machine()
    assert made.apply(Command(name=COMPARE_AND_SET, key="k", expected=None, value=2)) is True


def test_a_machine_counts_what_it_applied():
    made = Machine()
    made.apply(Command(name=SET, key="k", value=1))
    made.apply(Command(name=SET, key="j", value=2))
    assert made.applied == 2


def test_a_machine_records_its_results():
    made = Machine()
    made.apply(Command(name=SET, key="k", value=1))
    assert made.results == [1]


def test_a_machine_summarises():
    made = Machine()
    made.apply(Command(name=SET, key="k", value=1))
    assert made.as_dict()["keys"] == 1


def test_incrementing_a_string_raises():
    made = Machine()
    made.apply(Command(name=SET, key="k", value="text"))
    with pytest.raises(Refused):
        made.apply(Command(name=INCREMENT, key="k"))


def test_replaying_gives_a_machine():
    made = replay([Command(name=SET, key="k", value=4)])
    assert made.get("k") == 4


def test_replaying_nothing_gives_an_empty_machine():
    assert replay([]).state == {}


def test_a_set_is_idempotent():
    assert Command(name=SET, key="k", value=1).idempotent


def test_an_increment_is_not():
    assert not Command(name=INCREMENT, key="k").idempotent


def test_a_swap_is_not_idempotent():
    assert not Command(name=COMPARE_AND_SET, key="k", expected=1, value=2).idempotent


def test_the_clock_command_is_not_deterministic():
    assert not Command(name=NOW, key="k").deterministic


def test_every_other_command_is_deterministic():
    for one in COMMANDS:
        if one == NOW:
            continue
        assert Command(name=one, key="k").deterministic


def test_a_command_summarises():
    assert Command(name=SET, key="k", value=1).as_dict()["command"] == SET


def test_a_command_prints_itself():
    assert str(Command(name=SET, key="k", value=1)) == "set k 1"


def test_a_swap_prints_both_values():
    made = Command(name=COMPARE_AND_SET, key="k", expected=1, value=2)
    assert "1->2" in str(made)


def test_an_unknown_command_name_raises():
    with pytest.raises(ConfigError):
        Command(name="explode", key="k")


def test_a_keyless_command_raises():
    with pytest.raises(ConfigError):
        Command(name=INCREMENT)


def test_the_clock_command_needs_no_key():
    assert Command(name=NOW).name == NOW


def test_two_commands_are_idempotent():
    assert len(IDEMPOTENT) == 2


def test_there_are_five_commands():
    assert len(COMMANDS) == 5
