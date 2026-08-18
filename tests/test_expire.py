from __future__ import annotations

import pytest

from rsm import expire as ttl
from rsm.errors import ConfigError
from rsm.expire import LEASE, SWEEP, Lease, Store, Sweep, run


def test_the_clock_version_diverges():
    assert ttl.expiring_on_each_replicas_clock_makes_them_disagree()["they_disagreed"]


def test_the_clock_version_diverges_often():
    made = ttl.expiring_on_each_replicas_clock_makes_them_disagree()
    assert made["share_of_the_run"] > 0.1


def test_the_clock_version_costs_one_entry_per_lease():
    assert ttl.expiring_on_each_replicas_clock_makes_them_disagree()[
        "and_it_is_one_entry_per_lease"
    ]


def test_the_log_version_agrees():
    assert ttl.expiring_through_the_log_never_diverges_and_costs_double()[
        "the_log_version_agreed"
    ]


def test_the_clock_version_does_not():
    assert ttl.expiring_through_the_log_never_diverges_and_costs_double()[
        "and_the_clock_version_did_not"
    ]


def test_the_log_version_costs_double():
    assert ttl.expiring_through_the_log_never_diverges_and_costs_double()["it_costs_double"]


def test_everything_granted_was_revoked():
    assert ttl.expiring_through_the_log_never_diverges_and_costs_double()[
        "and_everything_granted_was_revoked"
    ]


def test_the_delay_is_under_a_sweep():
    assert ttl.the_log_version_keeps_a_key_past_its_lease()["it_is_under_a_sweep"]


def test_the_replicas_agree_through_the_delay():
    assert ttl.the_log_version_keeps_a_key_past_its_lease()[
        "and_every_replica_agreed_throughout"
    ]


def test_the_delay_is_shared():
    assert ttl.the_log_version_keeps_a_key_past_its_lease()["so_the_delay_is_shared"]


def test_a_shorter_sweep_is_quicker():
    assert ttl.a_shorter_sweep_costs_nothing_extra_and_shortens_the_delay()[
        "a_shorter_sweep_is_quicker"
    ]


def test_a_shorter_sweep_costs_the_same():
    assert ttl.a_shorter_sweep_costs_nothing_extra_and_shortens_the_delay()[
        "and_costs_the_same_entries"
    ]


def test_every_sweep_agreed():
    assert ttl.a_shorter_sweep_costs_nothing_extra_and_shortens_the_delay()["every_one_agreed"]


def test_the_model_does_not_charge_for_sweeping():
    assert ttl.a_shorter_sweep_costs_nothing_extra_and_shortens_the_delay()[
        "and_the_model_does_not_charge_for_the_sweep"
    ]


def test_a_lease_without_a_key_is_refused():
    assert ttl.a_lease_without_a_key_is_refused()


def test_a_lease_of_no_length_is_refused():
    assert ttl.a_lease_of_no_length_is_refused()


def test_a_run_with_one_replica_is_refused():
    assert ttl.a_run_with_one_replica_is_refused()


def test_a_run_with_no_leases_is_refused():
    assert ttl.a_run_with_no_leases_is_refused()


def test_aligned_clocks_look_perfect():
    assert ttl.clocks_that_agree_hide_the_problem_entirely()["it_looks_perfect"]


def test_a_small_skew_breaks_it():
    assert ttl.clocks_that_agree_hide_the_problem_entirely()["and_a_small_skew_breaks_it"]


def test_the_correctness_was_about_the_clocks():
    assert ttl.clocks_that_agree_hide_the_problem_entirely()[
        "so_the_correctness_was_a_claim_about_the_clocks"
    ]


def test_the_arrangement_table_covers_four():
    assert len(ttl.compare_the_arrangements()) == 4


def test_only_one_row_fails():
    assert ttl.only_the_log_version_is_correct_under_both_clocks()["only_one_row_fails"]


def test_the_failing_row_is_the_skewed_clock():
    assert ttl.only_the_log_version_is_correct_under_both_clocks()["and_it_is_the_skewed_clock"]


def test_the_log_rows_cost_double():
    assert ttl.only_the_log_version_is_correct_under_both_clocks()["the_log_rows_cost_double"]


def test_the_clock_rows_do_not():
    assert ttl.only_the_log_version_is_correct_under_both_clocks()["and_the_clock_rows_do_not"]


def test_the_summary_says_the_clock_version_diverges():
    assert ttl.summarise()["the_clock_version_diverges"]


def test_the_summary_says_the_log_version_does_not():
    assert ttl.summarise()["the_log_version_does_not"]


def test_a_lease_reports_when_it_expires():
    assert Lease(key="k", value=1, granted_at=10, length=5).expires_at == 15


def test_a_lease_is_not_expired_early():
    assert not Lease(key="k", value=1, granted_at=10, length=5).expired(14)


def test_a_lease_is_expired_at_its_end():
    assert Lease(key="k", value=1, granted_at=10, length=5).expired(15)


def test_a_lease_summarises():
    assert Lease(key="k", value=1, granted_at=0).as_dict()["key"] == "k"


def test_a_lease_without_a_key_raises():
    with pytest.raises(ConfigError):
        Lease(key="", value=1, granted_at=0)


def test_a_lease_of_no_length_raises():
    with pytest.raises(ConfigError):
        Lease(key="k", value=1, granted_at=0, length=0)


def test_a_lease_before_time_raises():
    with pytest.raises(ConfigError):
        Lease(key="k", value=1, granted_at=-1)


def test_a_store_takes_a_lease():
    made = Store(name="r0")
    made.grant(Lease(key="k", value=1, granted_at=0))
    assert made.keys() == ("k",)


def test_a_store_revokes_a_lease():
    made = Store(name="r0")
    made.grant(Lease(key="k", value=1, granted_at=0))
    assert made.revoke("k") and made.keys() == ()


def test_revoking_an_absent_key_says_so():
    assert not Store(name="r0").revoke("k")


def test_a_log_driven_store_keeps_expired_leases():
    made = Store(name="r0", by_clock=False)
    made.grant(Lease(key="k", value=1, granted_at=0, length=2))
    made.tick(50)
    assert made.keys() == ("k",)


def test_a_clock_driven_store_drops_them():
    made = Store(name="r0", by_clock=True)
    made.grant(Lease(key="k", value=1, granted_at=0, length=2))
    made.tick(50)
    assert made.keys() == ()


def test_a_clock_driven_store_counts_what_it_swept():
    made = Store(name="r0", by_clock=True)
    made.grant(Lease(key="k", value=1, granted_at=0, length=2))
    made.tick(50)
    assert made.swept == 1


def test_a_store_keeps_its_clock():
    made = Store(name="r0")
    made.tick(7)
    assert made.now == 7


def test_a_store_summarises():
    assert Store(name="named").as_dict()["replica"] == "named"


def test_a_sweep_reports_its_cost():
    assert Sweep(name="x", granted=4, entries=8).cost == 2.0


def test_a_sweep_with_no_grants_has_no_cost():
    assert Sweep(name="x").cost == 0.0


def test_a_sweep_reports_its_worst_delay():
    assert Sweep(name="x", delays=[1, 9, 3]).worst_delay == 9


def test_a_sweep_with_no_delays_reports_zero():
    assert Sweep(name="x").worst_delay == 0


def test_an_agreeing_sweep_is_truthy():
    assert Sweep(name="x")


def test_a_diverging_sweep_is_falsy():
    assert not Sweep(name="x", divergences=3)


def test_a_sweep_summarises():
    assert Sweep(name="named").as_dict()["run"] == "named"


def test_a_clock_run_diverges():
    assert not run("x", by_clock=True, window=120)


def test_a_log_run_does_not():
    assert run("x", by_clock=False, window=120)


def test_a_run_grants_what_it_is_asked_for():
    assert run("x", by_clock=False, leases=5, window=200).granted == 5


def test_a_run_with_one_replica_raises():
    with pytest.raises(ConfigError):
        run("x", by_clock=True, replicas=1)


def test_a_run_with_no_leases_raises():
    with pytest.raises(ConfigError):
        run("x", by_clock=True, leases=0)


def test_the_lease_outlasts_a_sweep():
    assert LEASE > SWEEP
