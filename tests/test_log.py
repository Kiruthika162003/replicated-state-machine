from __future__ import annotations

import pytest

from rsm import log as replicated
from rsm.errors import Compacted, ConfigError, LeaderAppendOnly, LogError, NotFound
from rsm.log import (
    NO_INDEX,
    NO_TERM,
    Entry,
    Log,
    agree_up_to,
    diverge,
    reconcile_by_conflict_term,
    reconcile_one_at_a_time,
    written,
)


def test_the_matching_property_holds():
    assert replicated.the_matching_property_holds_by_induction()["it_holds_everywhere"]


def test_the_induction_was_actually_checked():
    assert replicated.the_matching_property_holds_by_induction()["agreements_checked"] > 100


def test_the_induction_found_no_failures():
    assert replicated.the_matching_property_holds_by_induction()["failures"] == []


def test_a_checked_log_stops_at_the_first_gap():
    assert replicated.a_follower_refuses_an_entry_whose_predecessor_it_lacks()[
        "the_checked_log_stops_at_the_first_gap"
    ]


def test_an_unchecked_log_grows_holes():
    assert replicated.a_follower_refuses_an_entry_whose_predecessor_it_lacks()[
        "and_the_unchecked_one_has_holes"
    ]


def test_the_check_refused_something():
    assert replicated.a_follower_refuses_an_entry_whose_predecessor_it_lacks()["refused"] > 0


def test_a_longer_log_with_an_older_term_is_not_up_to_date():
    assert replicated.the_up_to_date_check_compares_the_term_first()[
        "the_long_log_is_not_up_to_date"
    ]


def test_the_long_log_really_is_longer():
    assert replicated.the_up_to_date_check_compares_the_term_first()["but_it_is_longer"]


def test_the_two_rules_disagree():
    assert replicated.the_up_to_date_check_compares_the_term_first()["the_two_rules_disagree"]


def test_the_shorter_log_with_the_later_term_wins():
    assert replicated.the_up_to_date_check_compares_the_term_first()["and_the_short_log_wins"]


def test_a_tie_goes_to_the_longer_log():
    assert replicated.a_tie_on_term_is_broken_by_length()["the_longer_one_is_up_to_date"]


def test_a_tie_does_not_go_to_the_shorter_one():
    assert replicated.a_tie_on_term_is_broken_by_length()["and_the_shorter_one_is_not"]


def test_an_equal_log_is_up_to_date():
    assert replicated.a_tie_on_term_is_broken_by_length()["an_equal_log_is_up_to_date"]


def test_the_conflict_term_optimisation_is_cheaper():
    assert replicated.the_conflict_term_optimisation_saves_a_round_trip_per_entry()[
        "the_optimisation_is_cheaper"
    ]


def test_the_optimisation_is_constant_in_the_divergence():
    assert replicated.the_conflict_term_optimisation_saves_a_round_trip_per_entry()[
        "and_it_does_not_depend_on_the_divergence"
    ]


def test_the_optimisation_saves_nothing_on_one_entry():
    assert replicated.the_optimisation_only_pays_on_a_long_divergence()[
        "it_saves_nothing_at_one"
    ]


def test_the_optimisation_saves_a_lot_on_a_hundred():
    assert replicated.the_optimisation_only_pays_on_a_long_divergence()[
        "and_ninety_nine_at_a_hundred"
    ]


def test_the_saving_is_the_divergence_less_one():
    assert replicated.the_optimisation_only_pays_on_a_long_divergence()[
        "the_saving_is_the_divergence_less_one"
    ]


def test_the_optimisation_pays_on_a_minority_of_cases():
    made = replicated.the_optimisation_only_pays_on_a_long_divergence()
    assert made["cases_where_it_pays"] < made["of"]


def test_reconciling_discards_exactly_the_divergence():
    assert replicated.an_append_that_conflicts_discards_the_tail()[
        "it_discarded_the_divergence"
    ]


def test_reconciling_makes_the_logs_match():
    assert replicated.an_append_that_conflicts_discards_the_tail()["the_logs_now_match"]


def test_a_leader_never_truncates_its_own_log():
    assert replicated.a_leader_never_truncates_its_own_log()


def test_reading_inside_a_snapshot_is_refused():
    assert replicated.reading_inside_a_snapshot_is_refused()


def test_reading_past_the_end_is_refused():
    assert replicated.reading_past_the_end_is_refused()


def test_an_out_of_order_append_is_refused():
    assert replicated.an_out_of_order_append_is_refused()


def test_a_log_with_a_hole_is_refused():
    assert replicated.a_log_with_a_hole_is_refused()


def test_a_log_whose_terms_go_backwards_is_refused():
    assert replicated.a_log_whose_terms_go_backwards_is_refused()


def test_a_zero_term_entry_is_refused():
    assert replicated.a_zero_term_entry_is_refused()


def test_the_empty_log_matches_position_zero():
    assert replicated.the_empty_log_matches_the_empty_position()[
        "the_empty_log_matches_position_zero"
    ]


def test_a_written_log_also_matches_position_zero():
    assert replicated.the_empty_log_matches_the_empty_position()["so_does_a_written_one"]


def test_the_empty_log_matches_nothing_else():
    assert replicated.the_empty_log_matches_the_empty_position()["and_it_matches_nothing_else"]


def test_a_snapshot_moves_the_first_index():
    assert replicated.a_snapshot_moves_the_first_index()["first_index"] == 21


def test_a_snapshot_boundary_still_matches():
    assert replicated.a_snapshot_moves_the_first_index()["it_matches_at_the_boundary"]


def test_a_snapshot_boundary_rejects_the_wrong_term():
    assert replicated.a_snapshot_moves_the_first_index()["and_not_at_the_wrong_term"]


def test_the_reconciliation_table_covers_five_divergences():
    assert len(replicated.compare_the_reconciliations()) == 5


def test_the_summary_says_matching_holds():
    assert replicated.summarise()["matching_holds"]


def test_the_summary_says_term_beats_length():
    assert replicated.summarise()["term_beats_length"]


def test_an_entry_knows_its_index_and_term():
    one = Entry(term=3, index=7, command="x")
    assert one.index == 7 and one.term == 3


def test_an_entry_without_a_command_is_a_noop():
    assert Entry(term=1, index=1).is_noop


def test_an_entry_with_a_command_is_not():
    assert not Entry(term=1, index=1, command="set a 1").is_noop


def test_an_entry_summarises():
    assert Entry(term=2, index=5, command="x").as_dict()["index"] == 5


def test_an_entry_prints_as_index_at_term():
    assert str(Entry(term=2, index=5)) == "5@2"


def test_an_entry_at_index_zero_is_refused():
    with pytest.raises(ConfigError):
        Entry(term=1, index=0)


def test_an_empty_log_has_no_last_index():
    assert Log().last_index == NO_INDEX


def test_an_empty_log_has_no_last_term():
    assert Log().last_term == NO_TERM


def test_a_written_log_reports_its_last_index():
    assert written([1, 1, 2]).last_index == 3


def test_a_written_log_reports_its_last_term():
    assert written([1, 1, 2]).last_term == 2


def test_a_log_counts_its_entries():
    assert len(written([1, 1, 2])) == 3


def test_a_log_iterates_its_entries():
    assert [one.index for one in written([1, 1, 2])] == [1, 2, 3]


def test_a_log_reads_an_entry():
    assert written([1, 2, 3]).at(2).term == 2


def test_a_log_reads_a_term():
    assert written([1, 2, 3]).term_at(3) == 3


def test_a_log_reads_term_zero_at_index_zero():
    assert written([1, 2]).term_at(NO_INDEX) == NO_TERM


def test_a_log_holds_what_it_wrote():
    assert written([1, 1]).holds(2)


def test_a_log_does_not_hold_what_it_did_not():
    assert not written([1, 1]).holds(9)


def test_a_log_slices_from_an_index():
    assert [one.index for one in written([1, 1, 1, 1]).slice(2)] == [2, 3, 4]


def test_a_log_slices_a_range():
    assert [one.index for one in written([1] * 6).slice(2, 4)] == [2, 3, 4]


def test_a_slice_past_the_end_stops_at_the_end():
    assert len(written([1, 1]).slice(1, 99)) == 2


def test_a_slice_inside_a_snapshot_is_refused():
    made = Log(entries=[Entry(term=2, index=6)], snapshot_index=5, snapshot_term=1)
    with pytest.raises(Compacted):
        made.slice(2)


def test_a_log_matches_its_own_entries():
    made = written([1, 2, 3])
    assert made.matches(2, 2)


def test_a_log_does_not_match_a_wrong_term():
    assert not written([1, 2, 3]).matches(2, 9)


def test_a_log_does_not_match_past_its_end():
    assert not written([1, 2]).matches(9, 1)


def test_appending_extends_the_log():
    made = written([1, 1])
    made.append([Entry(term=1, index=3, command="c3")])
    assert made.last_index == 3


def test_appending_nothing_changes_nothing():
    made = written([1, 1])
    assert made.append([]).last_index == 2


def test_appending_out_of_order_raises():
    with pytest.raises(LogError):
        written([1, 1]).append([Entry(term=1, index=5)])


def test_appending_an_older_term_raises():
    with pytest.raises(LeaderAppendOnly):
        written([1, 2]).append([Entry(term=1, index=3)])


def test_truncating_removes_the_tail():
    made = written([1, 1, 1, 1])
    assert made.truncate_from(3) == 2


def test_truncating_leaves_the_prefix():
    made = written([1, 1, 1, 1])
    made.truncate_from(3)
    assert made.last_index == 2


def test_truncating_past_the_end_removes_nothing():
    assert written([1, 1]).truncate_from(9) == 0


def test_truncating_into_a_snapshot_is_refused():
    made = Log(entries=[Entry(term=2, index=6)], snapshot_index=5, snapshot_term=1)
    with pytest.raises(Compacted):
        made.truncate_from(2)


def test_reading_past_the_end_raises():
    with pytest.raises(NotFound):
        written([1]).at(4)


def test_a_negative_snapshot_index_is_refused():
    with pytest.raises(ConfigError):
        Log(snapshot_index=-1)


def test_diverging_keeps_the_prefix():
    base = written([1] * 10)
    made = diverge(base, 6, [2, 2])
    assert [one.index for one in made][:5] == [1, 2, 3, 4, 5]


def test_diverging_replaces_the_tail():
    base = written([1] * 10)
    made = diverge(base, 6, [2, 2])
    assert made.last_index == 7 and made.last_term == 2


def test_diverging_at_index_zero_is_refused():
    with pytest.raises(ConfigError):
        diverge(written([1]), 0, [2])


def test_agreement_finds_the_shared_prefix():
    base = written([1] * 10)
    assert agree_up_to(base, diverge(base, 6, [2, 2])) == 5


def test_two_identical_logs_agree_everywhere():
    assert agree_up_to(written([1, 2, 3]), written([1, 2, 3])) == 3


def test_two_logs_that_share_nothing_agree_at_zero():
    assert agree_up_to(written([1, 1]), written([2, 2])) == NO_INDEX


def test_an_empty_log_agrees_at_zero():
    assert agree_up_to(Log(), written([1, 1])) == NO_INDEX


def test_walking_back_costs_a_trip_per_entry():
    base = written([1] * 10 + [3] * 4)
    assert reconcile_one_at_a_time(base, diverge(base, 11, [2] * 4)) == 5


def test_naming_the_term_costs_two_trips():
    base = written([1] * 10 + [3] * 4)
    assert reconcile_by_conflict_term(base, diverge(base, 11, [2] * 4)) == 2


def test_an_up_to_date_follower_costs_one_trip():
    base = written([1, 1, 1])
    assert reconcile_one_at_a_time(base, written([1, 1, 1])) == 1


def test_both_strategies_agree_on_an_up_to_date_follower():
    base = written([1, 1, 1])
    same = written([1, 1, 1])
    assert reconcile_one_at_a_time(base, same) == reconcile_by_conflict_term(base, same)


def test_writing_a_log_from_terms():
    assert [one.term for one in written([1, 2, 2])] == [1, 2, 2]


def test_writing_a_log_from_a_start_index():
    assert written([1, 1], start=5).first_index == 5


def test_writing_a_log_from_a_start_index_makes_a_snapshot():
    assert written([1, 1], start=5).snapshot_index == 4


def test_writing_a_log_with_commands():
    assert written([1, 1], commands=["a", "b"]).at(1).command == "a"
