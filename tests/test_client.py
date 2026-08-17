from __future__ import annotations

import pytest

from rsm import client as caller
from rsm.client import (
    LOCAL_READ,
    LOG_READ,
    PATIENCE,
    READ_INDEX,
    READ_STRATEGIES,
    Client,
    Read,
    Request,
    Sessions,
)
from rsm.cluster import Cluster
from rsm.errors import ConfigError, Timeout
from rsm.machine import INCREMENT, SET, Command, Machine


def test_a_retry_doubles_an_increment():
    assert caller.a_retried_increment_is_applied_twice_without_a_session()[
        "and_the_counter_is_wrong"
    ]


def test_the_retry_was_applied_twice():
    assert caller.a_retried_increment_is_applied_twice_without_a_session()[
        "it_was_applied_twice"
    ]


def test_a_session_applies_it_once():
    assert caller.a_session_answers_the_retry_from_memory()["it_applied_once"]


def test_a_session_deduplicates_the_retry():
    assert caller.a_session_answers_the_retry_from_memory()["and_deduplicated_once"]


def test_the_retry_gets_the_original_answer():
    assert caller.a_session_answers_the_retry_from_memory()["the_retry_got_the_original_answer"]


def test_the_original_answer_is_not_the_current_value():
    assert caller.a_session_answers_the_retry_from_memory()["which_is_not_the_current_value"]


def test_a_session_lets_new_requests_through():
    assert caller.a_session_lets_a_second_request_through()["it_applied_three"]


def test_a_session_still_catches_the_repeat():
    assert caller.a_session_lets_a_second_request_through()["and_deduplicated_one"]


def test_the_repeat_returns_its_own_answer():
    assert caller.a_session_lets_a_second_request_through()[
        "the_repeat_returned_its_own_answer"
    ]


def test_a_later_request_still_runs():
    assert caller.a_session_lets_a_second_request_through()["and_the_later_one_still_ran"]


def test_two_clients_do_not_share_a_session():
    assert caller.two_clients_do_not_share_a_session()["both_were_applied"]


def test_nothing_was_deduplicated_across_clients():
    assert caller.two_clients_do_not_share_a_session()["and_nothing_was_deduplicated"]


def test_the_two_clients_got_different_answers():
    assert caller.two_clients_do_not_share_a_session()["the_answers_differ"]


def test_a_session_holds_one_answer_per_request():
    assert caller.a_session_costs_memory_that_grows_with_the_clients()[
        "it_holds_one_per_request"
    ]


def test_forgetting_a_client_frees_its_answers():
    made = caller.a_session_costs_memory_that_grows_with_the_clients()
    assert made["remembered_after"] < made["remembered"]


def test_nothing_expires_on_its_own():
    assert caller.a_session_costs_memory_that_grows_with_the_clients()[
        "and_nothing_expires_on_its_own"
    ]


def test_a_deposed_leader_still_thinks_it_leads():
    assert caller.a_local_read_can_be_stale()["it_still_thinks_it_leads"]


def test_a_deposed_leader_is_behind():
    assert caller.a_local_read_can_be_stale()["it_is_behind"]


def test_a_local_read_would_be_stale():
    assert caller.a_local_read_can_be_stale()["a_local_read_would_be_stale"]


def test_nothing_told_the_deposed_leader():
    assert caller.a_local_read_can_be_stale()["and_nothing_told_it"]


def test_a_read_index_writes_nothing():
    assert caller.a_read_index_costs_one_round_of_heartbeats()["it_wrote_nothing"]


def test_a_read_index_asks_every_peer():
    assert caller.a_read_index_costs_one_round_of_heartbeats()["it_asked_every_peer"]


def test_a_read_index_needs_only_a_majority():
    assert (
        caller.a_read_index_costs_one_round_of_heartbeats()[
            "and_needed_only_a_majority_to_answer"
        ]
        == 2
    )


def test_a_log_read_grows_the_log():
    assert caller.a_read_through_the_log_costs_an_entry()["it_grew_by_one"]


def test_a_log_read_costs_messages():
    assert caller.a_read_through_the_log_costs_an_entry()["messages"] > 0


def test_the_local_read_is_free():
    assert caller.the_three_reads_cost_different_amounts()["local_is_free"]


def test_the_local_read_can_be_stale():
    assert caller.the_three_reads_cost_different_amounts()["and_can_be_stale"]


def test_the_log_read_costs_more_than_the_read_index():
    assert caller.the_three_reads_cost_different_amounts()["the_log_read_costs_more"]


def test_a_client_waits_for_an_election():
    assert caller.a_client_retries_until_there_is_a_leader()["it_waited_for_an_election"]


def test_a_client_write_eventually_lands():
    assert caller.a_client_retries_until_there_is_a_leader()["it_eventually_landed"]


def test_a_patient_client_sends_once():
    assert caller.a_client_retries_until_there_is_a_leader()["and_it_only_sent_once"]


def test_a_write_to_a_follower_is_refused():
    assert caller.a_client_write_to_a_follower_is_refused()


def test_a_request_with_no_client_is_refused():
    assert caller.a_request_with_no_client_is_refused()


def test_a_zero_sequence_is_refused():
    assert caller.a_request_with_a_zero_sequence_is_refused()


def test_a_nameless_client_is_refused():
    assert caller.a_client_without_a_name_is_refused()


def test_an_impatient_client_gives_up():
    assert caller.a_client_that_waits_forever_gives_up()


def test_the_read_table_covers_three():
    assert len(caller.compare_the_reads()) == len(READ_STRATEGIES)


def test_two_reads_are_always_current():
    assert caller.only_the_free_read_can_be_wrong()["and_the_other_two_are"]


def test_the_free_read_is_not():
    assert caller.only_the_free_read_can_be_wrong()["the_free_one_is_not"]


def test_the_certain_reads_differ_by_a_log_entry():
    assert caller.only_the_free_read_can_be_wrong()["they_differ_by_a_log_entry"]


def test_the_certain_reads_give_the_same_guarantee():
    assert caller.only_the_free_read_can_be_wrong()["and_not_by_a_guarantee"]


def test_the_summary_says_a_retry_doubles():
    assert caller.summarise()["a_retry_doubles_an_increment"]


def test_the_summary_says_a_session_fixes_it():
    assert caller.summarise()["a_session_applies_it_once"]


def test_a_request_knows_its_key():
    made = Request(client="c1", sequence=3, command=Command(name=SET, key="k", value=1))
    assert made.key == ("c1", 3)


def test_a_request_summarises():
    made = Request(client="c1", sequence=3, command=Command(name=SET, key="k", value=1))
    assert made.as_dict()["client"] == "c1"


def test_a_request_with_no_client_raises():
    with pytest.raises(ConfigError):
        Request(client="", sequence=1, command=Command(name=SET, key="k", value=1))


def test_a_request_with_a_negative_sequence_raises():
    with pytest.raises(ConfigError):
        Request(client="c1", sequence=-1, command=Command(name=SET, key="k", value=1))


def test_a_fresh_session_table_remembers_nothing():
    assert Sessions().remembered == 0


def test_a_session_remembers_after_running():
    made = Sessions()
    made.run(
        Request(client="c1", sequence=1, command=Command(name=SET, key="k", value=1)),
        Machine(),
    )
    assert made.remembered == 1


def test_a_session_recognises_a_repeat():
    made = Sessions()
    request = Request(client="c1", sequence=1, command=Command(name=SET, key="k", value=1))
    made.run(request, Machine())
    assert made.seen(request)


def test_a_session_does_not_recognise_a_new_request():
    made = Sessions()
    first = Request(client="c1", sequence=1, command=Command(name=SET, key="k", value=1))
    second = Request(client="c1", sequence=2, command=Command(name=SET, key="k", value=1))
    made.run(first, Machine())
    assert not made.seen(second)


def test_forgetting_an_unknown_client_drops_nothing():
    assert Sessions().forget("nobody") == 0


def test_a_session_table_summarises():
    made = Sessions()
    made.run(
        Request(client="c1", sequence=1, command=Command(name=INCREMENT, key="k")),
        Machine(),
    )
    assert made.as_dict()["clients"] == 1


def test_a_client_numbers_its_requests():
    made = Client(name="c1", cluster=Cluster(size=1, seed=1))
    first = made.next_request(Command(name=SET, key="k", value=1))
    second = made.next_request(Command(name=SET, key="k", value=2))
    assert (first.sequence, second.sequence) == (1, 2)


def test_a_client_sends_through_the_leader():
    made = Cluster(size=3, seed=1).settle()
    client = Client(name="c1", cluster=made)
    request = client.next_request(Command(name=SET, key="k", value=1))
    assert client.send(request) > 0


def test_a_client_counts_its_sends():
    made = Cluster(size=3, seed=1).settle()
    client = Client(name="c1", cluster=made)
    client.send(client.next_request(Command(name=SET, key="k", value=1)))
    assert client.sent == 1


def test_a_client_counts_its_retries():
    made = Cluster(size=3, seed=1).settle()
    client = Client(name="c1", cluster=made)
    request = client.next_request(Command(name=SET, key="k", value=1))
    client.send(request)
    client.retry(request)
    assert client.retries == 1


def test_a_client_giving_up_raises():
    made = Cluster(size=3, seed=1)
    made.crash("n1")
    made.crash("n2")
    client = Client(name="c1", cluster=made)
    with pytest.raises(Timeout):
        client.send(client.next_request(Command(name=SET, key="k", value=1)), patience=40)


def test_a_read_summarises():
    made = Read(strategy=LOCAL_READ, value=1, messages=0, correct=False)
    assert made.as_dict()["strategy"] == LOCAL_READ


def test_a_read_reports_its_cost():
    made = Read(strategy=READ_INDEX, value=1, messages=8, correct=True)
    assert made.messages == 8


def test_the_read_strategies_are_named():
    assert set(READ_STRATEGIES) == {LOCAL_READ, READ_INDEX, LOG_READ}


def test_the_patience_is_generous():
    assert PATIENCE >= 100
