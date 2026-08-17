from __future__ import annotations

import pytest

from rsm.errors import ConfigError
from rsm.machine import SET, Command
from rsm.verify import history as record
from rsm.verify.history import (
    PENDING,
    RETURNED,
    STATES,
    History,
    Operation,
    concurrent_history,
    sequential_history,
)


def test_a_sequential_history_has_no_overlap():
    assert record.a_sequential_history_has_no_overlap()["it_is_sequential"]


def test_a_sequential_history_has_one_client():
    assert record.a_sequential_history_has_no_overlap()["and_there_is_one_of_them"]


def test_every_sequential_operation_returned():
    assert record.a_sequential_history_has_no_overlap()["every_operation_returned"]


def test_a_concurrent_history_has_overlap():
    assert record.concurrency_is_what_makes_checking_expensive()["and_the_concurrent_one_does"]


def test_a_sequential_history_of_the_same_length_has_none():
    assert record.concurrency_is_what_makes_checking_expensive()["the_sequential_one_has_none"]


def test_length_is_not_the_cost():
    assert record.concurrency_is_what_makes_checking_expensive()["so_length_is_not_the_cost"]


def test_the_two_shapes_are_the_same_length():
    assert record.concurrency_is_what_makes_checking_expensive()["same_length"]


def test_non_overlapping_operations_have_a_forced_order():
    assert record.two_operations_that_do_not_overlap_have_a_real_order()[
        "so_the_order_is_forced"
    ]


def test_the_first_returned_before_the_second_was_called():
    assert record.two_operations_that_do_not_overlap_have_a_real_order()[
        "the_first_returned_before_the_second_was_called"
    ]


def test_overlapping_operations_may_go_either_way():
    assert record.two_overlapping_operations_may_go_either_way()["so_either_order_is_allowed"]


def test_overlap_is_symmetric():
    assert record.two_overlapping_operations_may_go_either_way()["and_overlap_is_symmetric"]


def test_a_pending_operation_is_recorded():
    assert record.an_operation_that_never_returned_is_not_an_error()["the_lost_one_is_pending"]


def test_a_pending_operation_has_no_result():
    assert record.an_operation_that_never_returned_is_not_an_error()["and_no_result"]


def test_a_pending_operation_is_not_an_error():
    assert record.an_operation_that_never_returned_is_not_an_error()["and_it_is_not_an_error"]


def test_a_client_never_overlaps_itself():
    assert record.a_client_is_sequential_with_itself()["a_client_never_overlaps_itself"]


def test_the_overlap_comes_from_other_clients():
    assert record.a_client_is_sequential_with_itself()["but_the_history_has_overlap"]


def test_the_history_holds_the_result():
    assert record.the_history_records_what_was_answered_not_what_happened()[
        "it_holds_the_result"
    ]


def test_the_history_holds_no_log_index():
    assert record.the_history_records_what_was_answered_not_what_happened()["it_holds_no_index"]


def test_the_history_holds_no_term():
    assert record.the_history_records_what_was_answered_not_what_happened()["and_no_term"]


def test_the_history_holds_no_node():
    assert record.the_history_records_what_was_answered_not_what_happened()["and_no_node"]


def test_a_history_finds_its_clients():
    assert record.a_history_counts_its_clients()["it_found_three"]


def test_clients_are_in_first_appearance_order():
    assert record.a_history_counts_its_clients()["in_first_appearance_order"]


def test_completing_an_unknown_operation_is_refused():
    assert record.completing_an_unknown_operation_is_refused()


def test_returning_before_calling_is_refused():
    assert record.returning_before_calling_is_refused()


def test_a_negative_call_time_is_refused():
    assert record.a_negative_call_time_is_refused()


def test_an_empty_history_is_sequential():
    assert record.an_empty_history_is_trivially_sequential()["it_is_sequential"]


def test_an_empty_history_has_no_clients():
    assert record.an_empty_history_is_trivially_sequential()["no_clients"]


def test_the_shape_table_covers_three():
    assert len(record.compare_the_shapes()) == 3


def test_nine_at_once_is_the_worst_case():
    assert record.overlap_grows_faster_than_length()["which_is_the_worst_case"]


def test_all_the_shapes_are_the_same_length():
    assert record.overlap_grows_faster_than_length()["and_they_are_all_nine_operations"]


def test_nine_at_once_beats_three_at_a_time():
    assert record.overlap_grows_faster_than_length()["nine_at_once_has_most"]


def test_the_summary_says_a_pending_operation_is_fine():
    assert record.summarise()["a_pending_operation_is_not_an_error"]


def test_the_summary_reports_the_worst_case():
    assert record.summarise()["worst_case_pairs"] == 36


def test_an_operation_knows_its_span():
    made = Operation(
        client="c1", command=Command(name=SET, key="k", value=1), called_at=2, returned_at=5
    )
    assert made.span == (2, 5)


def test_a_complete_operation_says_so():
    made = Operation(
        client="c1", command=Command(name=SET, key="k", value=1), called_at=2, returned_at=5
    )
    assert made.complete and made.state == RETURNED


def test_a_pending_operation_says_so():
    made = Operation(client="c1", command=Command(name=SET, key="k", value=1), called_at=2)
    assert not made.complete and made.state == PENDING


def test_an_operation_summarises():
    made = Operation(client="c1", command=Command(name=SET, key="k", value=1), called_at=2)
    assert made.as_dict()["client"] == "c1"


def test_an_operation_prints_itself():
    made = Operation(
        client="c1", command=Command(name=SET, key="k", value=1), called_at=2, returned_at=5
    )
    assert "[2,5]" in str(made)


def test_a_pending_operation_prints_a_question_mark():
    made = Operation(client="c1", command=Command(name=SET, key="k", value=1), called_at=2)
    assert "[2,?]" in str(made)


def test_a_pending_operation_overlaps_everything_after_it():
    early = Operation(client="c1", command=Command(name=SET, key="k", value=1), called_at=1)
    later = Operation(
        client="c2", command=Command(name=SET, key="k", value=2), called_at=9, returned_at=10
    )
    assert early.overlaps(later)


def test_returning_before_calling_raises():
    with pytest.raises(ConfigError):
        Operation(
            client="c1",
            command=Command(name=SET, key="k", value=1),
            called_at=5,
            returned_at=1,
        )


def test_a_history_records_a_call():
    made = History()
    made.call("c1", Command(name=SET, key="k", value=1))
    assert len(made) == 1


def test_a_history_records_a_completion():
    made = History()
    one = made.call("c1", Command(name=SET, key="k", value=1))
    made.complete(one, 1)
    assert one.result == 1


def test_a_history_advances_its_clock():
    made = History()
    one = made.call("c1", Command(name=SET, key="k", value=1))
    made.complete(one, 1)
    assert made.clock == 2


def test_a_history_iterates_its_operations():
    made = sequential_history(3)
    assert len(list(made)) == 3


def test_a_history_splits_by_client():
    made = concurrent_history(clients=2, each=2)
    assert len(made.of("c0")) == 2


def test_a_history_summarises():
    assert sequential_history(4).as_dict()["operations"] == 4


def test_a_history_counts_its_pending():
    made = History()
    made.call("c1", Command(name=SET, key="k", value=1))
    assert len(made.pending) == 1


def test_a_history_counts_its_completed():
    made = History()
    one = made.call("c1", Command(name=SET, key="k", value=1))
    made.complete(one, 1)
    assert len(made.completed) == 1


def test_completing_a_stranger_raises():
    made = History()
    stranger = Operation(client="c1", command=Command(name=SET, key="k", value=1), called_at=1)
    with pytest.raises(ConfigError):
        made.complete(stranger, 1)


def test_a_sequential_history_helper_is_sequential():
    assert sequential_history(5).sequential()


def test_a_concurrent_history_helper_is_not():
    assert not concurrent_history(clients=3, each=2).sequential()


def test_there_are_three_states():
    assert len(STATES) == 3
