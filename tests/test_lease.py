from __future__ import annotations

import pytest

from rsm import lease as leases
from rsm.errors import ConfigError
from rsm.lease import (
    LEASE,
    LEASE_SHARE,
    Lease,
    Read,
    Serving,
)
from rsm.node import MIN_ELECTION_TIMEOUT


def test_the_local_read_answers_everything():
    assert leases.the_local_read_is_free_and_wrong()["it_answered_everything"]


def test_the_local_read_is_mostly_wrong():
    assert leases.the_local_read_is_free_and_wrong()["and_most_of_it_was_wrong"]


def test_the_local_read_is_not_correct():
    assert leases.the_local_read_is_free_and_wrong()["it_is_not_correct"]


def test_the_local_read_refuses_nothing():
    assert leases.the_local_read_is_free_and_wrong()["and_nothing_was_refused"]


def test_a_lease_serves_nothing_stale():
    assert leases.a_lease_refuses_rather_than_lying()["nothing_was_stale"]


def test_a_lease_is_correct():
    assert leases.a_lease_refuses_rather_than_lying()["it_is_correct"]


def test_a_lease_gives_up_availability():
    assert leases.a_lease_refuses_rather_than_lying()["it_gave_up_availability"]


def test_the_lease_gives_up_a_lot():
    assert leases.a_lease_refuses_rather_than_lying()["by_this_share"] > 0.5


def test_short_leases_are_clean():
    assert leases.a_lease_longer_than_an_election_timeout_serves_stale_reads()[
        "the_short_leases_are_clean"
    ]


def test_long_leases_are_not():
    assert leases.a_lease_longer_than_an_election_timeout_serves_stale_reads()[
        "the_long_ones_are_not"
    ]


def test_the_boundary_is_the_election_timeout():
    assert leases.a_lease_longer_than_an_election_timeout_serves_stale_reads()[
        "and_it_is_the_election_timeout"
    ]


def test_the_shipped_lease_leaves_a_margin():
    assert (
        leases.a_lease_longer_than_an_election_timeout_serves_stale_reads()[
            "which_leaves_this_much_margin"
        ]
        > 0
    )


def test_no_drift_is_clean():
    assert leases.a_clock_error_below_the_margin_is_invisible_and_above_it_is_not()[
        "no_drift_is_clean"
    ]


def test_the_unsound_count_is_the_drift():
    assert leases.a_clock_error_below_the_margin_is_invisible_and_above_it_is_not()[
        "the_unsound_count_is_the_drift"
    ]


def test_a_small_drift_shows_nothing():
    assert leases.a_clock_error_below_the_margin_is_invisible_and_above_it_is_not()[
        "a_small_drift_is_unsound_and_not_wrong"
    ]


def test_a_large_drift_shows_everything():
    assert leases.a_clock_error_below_the_margin_is_invisible_and_above_it_is_not()[
        "a_large_drift_is_both"
    ]


def test_the_exposure_starts_before_the_damage():
    assert leases.a_clock_error_below_the_margin_is_invisible_and_above_it_is_not()[
        "and_the_exposure_starts_earlier"
    ]


def test_the_read_through_the_log_is_correct():
    assert leases.the_read_through_the_log_is_correct_and_only_available_with_a_leader()[
        "it_is_correct"
    ]


def test_it_serves_more_than_the_lease():
    assert leases.the_read_through_the_log_is_correct_and_only_available_with_a_leader()[
        "and_it_serves_more_than_the_lease"
    ]


def test_it_serves_fewer_than_the_local_read():
    assert leases.the_read_through_the_log_is_correct_and_only_available_with_a_leader()[
        "but_fewer_than_the_local_read"
    ]


def test_only_the_local_read_is_wrong():
    assert leases.the_read_through_the_log_is_correct_and_only_available_with_a_leader()[
        "and_the_local_read_is_the_only_wrong_one"
    ]


def test_it_needs_no_clock_assumption():
    assert leases.the_read_through_the_log_is_correct_and_only_available_with_a_leader()[
        "it_needs_no_clock_assumption"
    ]


def test_a_lease_without_a_holder_is_refused():
    assert leases.a_lease_without_a_holder_is_refused()


def test_a_lease_of_no_length_is_refused():
    assert leases.a_lease_of_no_length_is_refused()


def test_the_strategy_table_covers_four():
    assert len(leases.compare_the_strategies()) == 4


def test_the_local_read_is_the_wrong_one_in_the_table():
    assert leases.only_the_lease_is_free_and_it_is_the_only_one_that_needs_a_clock()[
        "the_local_read_is_wrong"
    ]


def test_the_lease_is_right_in_the_table():
    assert leases.only_the_lease_is_free_and_it_is_the_only_one_that_needs_a_clock()[
        "the_lease_is_right"
    ]


def test_a_wrong_clock_makes_the_lease_wrong():
    assert leases.only_the_lease_is_free_and_it_is_the_only_one_that_needs_a_clock()[
        "and_a_wrong_clock_makes_it_wrong"
    ]


def test_the_lease_is_shorter_than_the_timeout():
    assert leases.only_the_lease_is_free_and_it_is_the_only_one_that_needs_a_clock()[
        "the_lease_is_shorter_than_the_timeout"
    ]


def test_the_lease_outlasts_a_heartbeat():
    assert leases.only_the_lease_is_free_and_it_is_the_only_one_that_needs_a_clock()[
        "and_longer_than_a_heartbeat"
    ]


def test_the_summary_says_the_local_read_is_wrong():
    assert leases.summarise()["the_local_read_is_wrong"]


def test_the_summary_says_the_boundary_is_the_timeout():
    assert leases.summarise()["the_boundary_is_the_election_timeout"]


def test_the_summary_reports_the_lease():
    assert leases.summarise()["lease"] == LEASE


def test_a_lease_reports_when_it_expires():
    assert Lease(holder="n0", granted_at=10, length=5).expires_at == 15


def test_a_drifted_lease_expires_later():
    assert Lease(holder="n0", granted_at=10, length=5, drift=3).expires_at == 18


def test_a_lease_really_expires_on_time():
    assert Lease(holder="n0", granted_at=10, length=5, drift=3).really_expires_at == 15


def test_a_lease_reports_its_overrun():
    assert Lease(holder="n0", granted_at=0, length=5, drift=4).overrun == 4


def test_an_undrifted_lease_has_no_overrun():
    assert Lease(holder="n0", granted_at=0, length=5).overrun == 0


def test_a_lease_is_held_before_it_expires():
    assert Lease(holder="n0", granted_at=0, length=5).held_at(4)


def test_a_lease_is_not_held_after():
    assert not Lease(holder="n0", granted_at=0, length=5).held_at(5)


def test_a_drifted_lease_is_held_past_soundness():
    made = Lease(holder="n0", granted_at=0, length=5, drift=4)
    assert made.held_at(6) and not made.sound_at(6)


def test_an_undrifted_lease_is_sound_while_held():
    made = Lease(holder="n0", granted_at=0, length=5)
    assert all(made.held_at(one) == made.sound_at(one) for one in range(10))


def test_a_lease_summarises():
    assert Lease(holder="n0", granted_at=1, length=5).as_dict()["holder"] == "n0"


def test_an_unowned_lease_raises():
    with pytest.raises(ConfigError):
        Lease(holder="", granted_at=0)


def test_a_zero_length_lease_raises():
    with pytest.raises(ConfigError):
        Lease(holder="n0", granted_at=0, length=0)


def test_a_stale_read_says_so():
    assert Read(at=1, served_by="n0", value=1, truth=2, strategy="local").stale


def test_a_current_read_does_not():
    assert not Read(at=1, served_by="n0", value=2, truth=2, strategy="local").stale


def test_a_read_summarises():
    made = Read(at=3, served_by="n0", value=1, truth=1, strategy="lease")
    assert made.as_dict()["strategy"] == "lease"


def test_a_serving_reports_its_stale_count():
    made = Serving(
        strategy="x",
        reads=[Read(at=1, served_by="n0", value=1, truth=2, strategy="x")],
    )
    assert made.stale == 1


def test_a_serving_reports_its_cost():
    made = Serving(
        strategy="x",
        reads=[Read(at=1, served_by="n0", value=1, truth=1, strategy="x")],
        messages=10,
    )
    assert made.cost == 10.0


def test_an_empty_serving_has_no_cost():
    assert Serving(strategy="x").cost == 0.0


def test_an_empty_serving_is_falsy():
    assert not Serving(strategy="x")


def test_a_clean_serving_is_truthy():
    assert Serving(
        strategy="x",
        reads=[Read(at=1, served_by="n0", value=1, truth=1, strategy="x")],
    )


def test_a_serving_summarises():
    assert Serving(strategy="named").as_dict()["strategy"] == "named"


def test_the_lease_share_is_under_one():
    assert 0 < LEASE_SHARE < 1


def test_the_lease_is_under_the_timeout():
    assert LEASE < MIN_ELECTION_TIMEOUT
