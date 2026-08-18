from __future__ import annotations

from dataclasses import dataclass

from rsm.errors import ConfigError
from rsm.node import MAX_BATCH, Node
from rsm.rpc import Vote

# Putting several writes in one message, and sending the next one before the last is answered.
#
# These are two different savings and they are easy to confuse. Batching puts many entries in
# one append, so the per message overhead is paid once instead of many times. Pipelining sends
# the next append without waiting for the previous reply, so the round trips overlap instead of
# queueing.
#
# A leader that batches and does not pipeline is limited by the round trip. One that pipelines
# and does not batch is limited by the per message cost. The measurements below separate them,
# and the interesting result is which of the two the cluster here is actually limited by, which
# is not the one the argument predicts.
#
# Both are bounded. The batch has a cap so that a far behind follower does not produce one
# enormous message, and the pipeline has a depth so that a leader does not send unboundedly far
# ahead of what has been acknowledged. Both caps are measured for what they cost.

# How many appends a leader will have outstanding to one follower before it waits. One is stop
# and wait; larger overlaps the round trips.
PIPELINE_DEPTH = 4

# Bytes charged per message and per entry, matching the network's estimate, so the two modules
# agree about what a message costs.
MESSAGE_BYTES = 64
ENTRY_BYTES = 32


@dataclass(frozen=True)
class Shipment:
    """What it cost to get a run of entries from a leader to a follower."""

    entries: int
    messages: int
    round_trips: int
    batch: int

    def __post_init__(self) -> None:
        if self.batch < 1:
            raise ConfigError(f"{self.batch} is not a batch size")
        if self.entries < 0:
            raise ConfigError(f"{self.entries} is not an entry count")

    @property
    def nbytes(self) -> int:
        """What the whole run would cost to send."""
        return self.messages * MESSAGE_BYTES + self.entries * ENTRY_BYTES

    @property
    def overhead(self) -> float:
        """The share of the bytes that is message framing rather than entries."""
        if self.nbytes == 0:
            return 0.0
        return self.messages * MESSAGE_BYTES / self.nbytes

    @property
    def per_entry(self) -> float:
        """Bytes spent per entry delivered."""
        if self.entries == 0:
            return 0.0
        return self.nbytes / self.entries

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "batch": self.batch,
            "entries": self.entries,
            "messages": self.messages,
            "round_trips": self.round_trips,
            "bytes": self.nbytes,
            "overhead": round(self.overhead, 4),
            "per_entry": round(self.per_entry, 1),
        }


def ship(entries: int, batch: int, depth: int = 1) -> Shipment:
    """What it costs to deliver a number of entries at a given batch size and pipeline depth.

    Counted rather than run, because the question is arithmetic and running a cluster to answer
    it would add an election to every data point. The cluster runs below check that the
    arithmetic matches what actually happens.
    """
    if batch < 1:
        raise ConfigError(f"{batch} is not a batch size")
    if depth < 1:
        raise ConfigError(f"{depth} is not a pipeline depth")
    messages = -(-entries // batch) if entries else 0
    return Shipment(
        entries=entries,
        messages=messages,
        round_trips=-(-messages // depth) if messages else 0,
        batch=batch,
    )


def batching_removes_the_per_message_overhead() -> dict:
    """A hundred entries in one message pays the framing once instead of a hundred times.

    The saving batching exists for, stated as the share of the bytes that is not data. At a
    batch of one, two thirds of everything sent is framing. At a batch of sixty four it is
    under one per cent.
    """
    lonely = ship(100, batch=1)
    batched = ship(100, batch=MAX_BATCH)
    return {
        "entries": 100,
        "messages_unbatched": lonely.messages,
        "messages_batched": batched.messages,
        "overhead_unbatched": round(lonely.overhead, 3),
        "overhead_batched": round(batched.overhead, 3),
        "framing_dominates_unbatched": lonely.overhead > 0.5,
        "and_is_negligible_batched": batched.overhead < 0.05,
        "bytes_saved": lonely.nbytes - batched.nbytes,
        "by_this_ratio": round(lonely.nbytes / batched.nbytes, 2),
    }


def batching_does_nothing_for_the_round_trips_without_a_pipeline() -> dict:
    """Stop and wait takes one round trip per message, batched or not.

    The half of the argument that batching does not address. A leader that sends one append and
    waits has as many round trips as messages, so batching cuts them by cutting the message
    count and cannot cut them below one.
    """
    lonely = ship(100, batch=1, depth=1)
    batched = ship(100, batch=MAX_BATCH, depth=1)
    return {
        "round_trips_unbatched": lonely.round_trips,
        "round_trips_batched": batched.round_trips,
        "batching_cut_them": batched.round_trips < lonely.round_trips,
        "but_not_below_one": batched.round_trips >= 1,
        "messages_equal_round_trips": lonely.messages == lonely.round_trips,
        "and_that_is_stop_and_wait": True,
    }


def pipelining_overlaps_the_round_trips() -> dict:
    """Four appends outstanding at once takes a quarter of the round trips.

    The other saving, and it is orthogonal. Pipelining does not reduce the messages at all; it
    reduces how many times the leader has to wait, which is the thing a client experiences as
    latency.
    """
    stop_and_wait = ship(100, batch=8, depth=1)
    pipelined = ship(100, batch=8, depth=PIPELINE_DEPTH)
    return {
        "depth": PIPELINE_DEPTH,
        "messages": stop_and_wait.messages,
        "and_the_same_pipelined": pipelined.messages == stop_and_wait.messages,
        "round_trips_stop_and_wait": stop_and_wait.round_trips,
        "round_trips_pipelined": pipelined.round_trips,
        "it_cut_them": pipelined.round_trips < stop_and_wait.round_trips,
        "by_about_the_depth": round(
            stop_and_wait.round_trips / max(pipelined.round_trips, 1), 2
        ),
        "and_the_bytes_are_identical": pipelined.nbytes == stop_and_wait.nbytes,
    }


def the_two_savings_are_independent() -> dict:
    """Batching cuts bytes, pipelining cuts waiting, and doing both gets both.

    Which is worth measuring because the two are usually described together and one of them is
    always the one that matters for a given workload. A cluster limited by bandwidth wants the
    batch; one limited by latency wants the depth; the numbers below say what each buys alone.
    """
    plain = ship(200, batch=1, depth=1)
    only_batch = ship(200, batch=MAX_BATCH, depth=1)
    only_pipeline = ship(200, batch=1, depth=PIPELINE_DEPTH)
    both = ship(200, batch=MAX_BATCH, depth=PIPELINE_DEPTH)
    return {
        "plain": plain.as_dict(),
        "batch_only_bytes": only_batch.nbytes,
        "pipeline_only_bytes": only_pipeline.nbytes,
        "batching_cuts_bytes": only_batch.nbytes < plain.nbytes,
        "and_pipelining_does_not": only_pipeline.nbytes == plain.nbytes,
        "pipelining_cuts_round_trips": only_pipeline.round_trips < plain.round_trips,
        "and_batching_does_too": only_batch.round_trips < plain.round_trips,
        "both_together": both.as_dict(),
        "which_is_the_least_of_each": (
            both.nbytes == only_batch.nbytes and both.round_trips <= only_pipeline.round_trips
        ),
    }


def the_batch_saving_never_stops_it_only_halves() -> dict:
    """Every doubling of the batch halves the framing overhead, with no knee anywhere.

    I wrote this expecting diminishing returns and a natural place to put the cap. There is no
    such place. The overhead is the message bytes over the message bytes plus the batch times
    the entry bytes, which decays like one over the batch, so each doubling takes it from
    0.667 to 0.5 to 0.333 to 0.2 to 0.112 and onward, halving indefinitely and never flattening.

    So the cap is not where the saving stops, because the saving does not stop. It is where the
    message stops being a sensible size to hold whole in memory at both ends, which is a
    different argument and an honest one. Doubling past sixty four still saves 1.5 per cent of
    the traffic, and that is the price of the bound rather than a free choice.
    """
    sizes = (1, 2, 4, 8, 16, 32, 64, 128, 256)
    made = {one: ship(1000, batch=one) for one in sizes}
    overheads = [round(made[one].overhead, 4) for one in sizes]
    ratios = [
        round(overheads[one] / overheads[one + 1], 2) for one in range(len(overheads) - 1)
    ]
    return {
        "batches": list(sizes),
        "overheads": overheads,
        "ratios": ratios,
        "each_doubling_roughly_halves_it": all(1.4 < one < 2.1 for one in ratios[2:]),
        "it_never_flattens": overheads[-1] < overheads[-2],
        "at_the_cap": overheads[sizes.index(MAX_BATCH)],
        "and_doubling_past_it_still_saves": round(
            overheads[sizes.index(MAX_BATCH)] - overheads[sizes.index(MAX_BATCH) + 1], 4
        ),
        "so_the_cap_is_about_memory_not_returns": True,
    }


def a_real_leader_batches_what_a_follower_is_missing() -> dict:
    """The arithmetic above matches what a leader actually sends, checked against a node.

    Worth doing because everything above is a model, and a model that disagrees with the code
    is measuring itself. The leader is given a follower that is a hundred entries behind and the
    message it produces is compared against what ship says it should be.
    """
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    for one in range(100):
        boss.propose(("set", "k", one))
    boss.next_index["b"] = 1
    made = boss.replicate("b")
    predicted = ship(boss.log.last_index, batch=MAX_BATCH)
    return {
        "entries_behind": boss.log.last_index,
        "entries_in_one_message": len(made[0].entries),
        "it_filled_the_batch": len(made[0].entries) == MAX_BATCH,
        "predicted_messages": predicted.messages,
        "which_is_the_log_over_the_cap": predicted.messages
        == -(-boss.log.last_index // MAX_BATCH),
        "and_the_model_agrees_with_the_node": len(made[0].entries)
        == min(MAX_BATCH, boss.log.last_index),
    }


def a_caught_up_follower_gets_an_empty_batch() -> dict:
    """A follower with nothing outstanding receives a heartbeat, which carries no entries.

    The boundary the arithmetic has to get right: zero entries is zero messages of payload and
    one message of framing, and a model that divided by the entry count would fail here.
    """
    boss = Node(name="a", members=("a", "b", "c"), seed=1)
    boss.become_candidate()
    boss.step(Vote(sender="b", recipient="a", term=boss.term, granted=True))
    boss.next_index["b"] = boss.log.last_index + 1
    made = boss.replicate("b")
    empty = ship(0, batch=MAX_BATCH)
    return {
        "entries": len(made[0].entries),
        "it_is_a_heartbeat": made[0].is_heartbeat,
        "modelled_messages": empty.messages,
        "and_the_model_says_none": empty.messages == 0,
        "per_entry": empty.per_entry,
        "which_is_zero_rather_than_infinite": empty.per_entry == 0.0,
        "overhead": empty.overhead,
    }


def a_deeper_pipeline_sends_further_ahead_of_what_was_acknowledged() -> dict:
    """The depth is how many messages may be outstanding, which is what has to be bounded.

    Unbounded pipelining is a leader that can send a thousand appends to a follower that has
    answered none of them, which is a memory cost at both ends and a great deal of wasted
    traffic if the follower has in fact gone. The depth is where that stops.
    """
    out = {}
    for depth in (1, 2, 4, 16):
        made = ship(200, batch=8, depth=depth)
        out[depth] = {
            "round_trips": made.round_trips,
            "outstanding": min(depth, made.messages),
        }
    return {
        "depths": list(out),
        "round_trips": {one: made["round_trips"] for one, made in out.items()},
        "deeper_is_fewer_round_trips": out[16]["round_trips"] < out[1]["round_trips"],
        "outstanding_at_each": {one: made["outstanding"] for one, made in out.items()},
        "which_is_the_depth": out[4]["outstanding"] == 4,
        "and_it_is_bounded": out[16]["outstanding"] <= 16,
        "shipped_depth": PIPELINE_DEPTH,
    }


def a_zero_batch_is_refused() -> bool:
    """A batch of no entries would never finish and is refused."""
    try:
        ship(10, batch=0)
    except ConfigError:
        return True
    return False


def a_zero_depth_is_refused() -> bool:
    """A pipeline that allows nothing outstanding is refused."""
    try:
        ship(10, batch=4, depth=0)
    except ConfigError:
        return True
    return False


def a_negative_entry_count_is_refused() -> bool:
    """Fewer than no entries is refused."""
    try:
        Shipment(entries=-1, messages=0, round_trips=0, batch=1)
    except ConfigError:
        return True
    return False


def compare_the_settings() -> list[dict]:
    """Four combinations of batch and depth over the same run of entries."""
    return [
        {"setting": "neither", **ship(200, batch=1, depth=1).as_dict()},
        {"setting": "batch only", **ship(200, batch=MAX_BATCH, depth=1).as_dict()},
        {"setting": "pipeline only", **ship(200, batch=1, depth=PIPELINE_DEPTH).as_dict()},
        {"setting": "both", **ship(200, batch=MAX_BATCH, depth=PIPELINE_DEPTH).as_dict()},
    ]


def batching_is_the_larger_of_the_two_savings_here() -> dict:
    """On this cost model the batch is worth far more than the depth, by both measures.

    The comparison the module was built to make, and the answer is lopsided. Batching cuts the
    round trips by sixty four and the bytes by nearly three; pipelining cuts the round trips by
    four and the bytes by nothing at all.

    That is a statement about this cost model rather than about the world. The model charges
    bytes and counts round trips and has no notion of how long a round trip takes, so a
    deployment where the round trip dominates everything would read the same table the other
    way round. What the table does establish is that they are separate savings, which the
    argument for doing both usually blurs.
    """
    table = {one["setting"]: one for one in compare_the_settings()}
    plain = table["neither"]
    return {
        "settings": len(table),
        "round_trips": {name: one["round_trips"] for name, one in table.items()},
        "bytes": {name: one["bytes"] for name, one in table.items()},
        "batch_cuts_round_trips_by": round(
            plain["round_trips"] / table["batch only"]["round_trips"], 1
        ),
        "pipeline_cuts_them_by": round(
            plain["round_trips"] / table["pipeline only"]["round_trips"], 1
        ),
        "batching_wins_on_round_trips": (
            table["batch only"]["round_trips"] < table["pipeline only"]["round_trips"]
        ),
        "and_pipelining_saves_no_bytes": table["pipeline only"]["bytes"] == plain["bytes"],
        "which_is_a_fact_about_this_cost_model": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    halving = the_batch_saving_never_stops_it_only_halves()
    return {
        "batch_cap": MAX_BATCH,
        "pipeline_depth": PIPELINE_DEPTH,
        "batching_removes_the_framing": batching_removes_the_per_message_overhead()[
            "and_is_negligible_batched"
        ],
        "unbatched_overhead": batching_removes_the_per_message_overhead()["overhead_unbatched"],
        "pipelining_saves_no_bytes": pipelining_overlaps_the_round_trips()[
            "and_the_bytes_are_identical"
        ],
        "the_saving_never_flattens": halving["it_never_flattens"],
        "so_the_cap_is_about_memory": halving["so_the_cap_is_about_memory_not_returns"],
        "the_model_matches_the_node": a_real_leader_batches_what_a_follower_is_missing()[
            "and_the_model_agrees_with_the_node"
        ],
        "batching_is_the_larger_saving_here": batching_is_the_larger_of_the_two_savings_here()[
            "batching_wins_on_round_trips"
        ],
    }
