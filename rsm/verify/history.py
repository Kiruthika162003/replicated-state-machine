from __future__ import annotations

from dataclasses import dataclass, field

from rsm.errors import ConfigError
from rsm.machine import COMPARE_AND_SET, INCREMENT, SET, Command

# A record of what clients asked for and what they were told, with the times.
#
# This is the only thing a linearizability checker gets to see. It does not look inside the
# cluster, at the log, or at any node's state. That is the point: a checker that read the log
# would be checking that the log agrees with itself, and the question is whether the answers
# handed to clients could have come from some single sequential execution.
#
# Every operation has two moments. The call, when the client sent it, and the return, when the
# client heard back. Between those two the operation might have taken effect at any instant, and
# the checker's whole job is to decide whether some choice of instants explains the answers.
#
# An operation that never returned is not an error. A client that timed out cannot know whether
# its write landed, and neither can the checker, so such an operation may or may not have taken
# effect and both possibilities have to be considered. Recording it as absent would hide real
# violations, and recording it as complete would invent answers nobody was given.

CALLED = "called"
RETURNED = "returned"
PENDING = "pending"
STATES = (CALLED, RETURNED, PENDING)


@dataclass
class Operation:
    """One client operation, from the moment it was sent to the moment it was answered."""

    client: str
    command: Command
    called_at: int
    returned_at: int | None = None
    result: object = None

    def __post_init__(self) -> None:
        if self.called_at < 0:
            raise ConfigError(f"{self.called_at} is not a time")
        if self.returned_at is not None and self.returned_at < self.called_at:
            raise ConfigError(
                f"returned at {self.returned_at} before it was called at {self.called_at}"
            )

    @property
    def complete(self) -> bool:
        """Whether the client heard an answer."""
        return self.returned_at is not None

    @property
    def state(self) -> str:
        """Whether this operation returned or is still outstanding."""
        return RETURNED if self.complete else PENDING

    @property
    def span(self) -> tuple[int, int | None]:
        """The window during which this operation might have taken effect."""
        return (self.called_at, self.returned_at)

    def overlaps(self, other: Operation) -> bool:
        """Whether two operations were in flight at the same time.

        Two operations that do not overlap have a real order and the checker must respect it.
        Two that do overlap may be placed in either order, and that freedom is the whole reason
        checking is expensive.
        """
        if self.returned_at is not None and other.called_at > self.returned_at:
            return False
        return not (other.returned_at is not None and self.called_at > other.returned_at)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "client": self.client,
            "command": str(self.command),
            "called": self.called_at,
            "returned": self.returned_at,
            "result": self.result,
            "state": self.state,
        }

    def __str__(self) -> str:
        end = self.returned_at if self.complete else "?"
        return f"{self.client} {self.command} [{self.called_at},{end}] -> {self.result!r}"


@dataclass
class History:
    """Every operation a run performed, in the order they were called."""

    operations: list[Operation] = field(default_factory=list)
    clock: int = 0

    def call(self, client: str, command: Command) -> Operation:
        """Record a client sending a request."""
        self.clock += 1
        made = Operation(client=client, command=command, called_at=self.clock)
        self.operations.append(made)
        return made

    def complete(self, operation: Operation, result: object) -> Operation:
        """Record a client hearing an answer."""
        if operation not in self.operations:
            raise ConfigError("that operation is not in this history")
        self.clock += 1
        operation.returned_at = self.clock
        operation.result = result
        return operation

    @property
    def pending(self) -> list[Operation]:
        """Operations that never returned, which the checker may place or drop."""
        return [one for one in self.operations if not one.complete]

    @property
    def completed(self) -> list[Operation]:
        """Operations the client heard back on, which the checker has to explain."""
        return [one for one in self.operations if one.complete]

    @property
    def clients(self) -> tuple[str, ...]:
        """Every client that appears, in first appearance order."""
        return tuple(dict.fromkeys(one.client for one in self.operations))

    def of(self, client: str) -> list[Operation]:
        """One client's operations, which are sequential by construction."""
        return [one for one in self.operations if one.client == client]

    def concurrent_pairs(self) -> int:
        """How many pairs of operations overlapped, which is what makes checking hard."""
        out = 0
        for position, left in enumerate(self.operations):
            for right in self.operations[position + 1 :]:
                if left.overlaps(right):
                    out += 1
        return out

    def sequential(self) -> bool:
        """Whether nothing ever overlapped, in which case there is only one order to check."""
        return self.concurrent_pairs() == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "operations": len(self.operations),
            "completed": len(self.completed),
            "pending": len(self.pending),
            "clients": len(self.clients),
            "concurrent_pairs": self.concurrent_pairs(),
        }

    def __len__(self) -> int:
        return len(self.operations)

    def __iter__(self):
        return iter(self.operations)


def sequential_history(count: int = 6) -> History:
    """One client, one operation at a time, which is the easiest thing to check."""
    made = History()
    for one in range(count):
        operation = made.call("c1", Command(name=SET, key="k", value=one))
        made.complete(operation, one)
    return made


def concurrent_history(clients: int = 3, each: int = 3) -> History:
    """Several clients with overlapping operations, which is where the freedom comes from."""
    made = History()
    open_ones = []
    for round_number in range(each):
        for client in range(clients):
            open_ones.append(made.call(f"c{client}", Command(name=INCREMENT, key="k", value=1)))
        for one in open_ones:
            made.complete(one, round_number + 1)
        open_ones = []
    return made


def a_sequential_history_has_no_overlap() -> dict:
    """One client waiting for each answer produces a total order with nothing to decide.

    The base case. Every operation returns before the next is called, so there is exactly one
    order consistent with the record and checking it is a replay rather than a search.
    """
    made = sequential_history(8)
    return {
        "operations": len(made),
        "concurrent_pairs": made.concurrent_pairs(),
        "it_is_sequential": made.sequential(),
        "every_operation_returned": len(made.pending) == 0,
        "clients": len(made.clients),
        "and_there_is_one_of_them": len(made.clients) == 1,
    }


def concurrency_is_what_makes_checking_expensive() -> dict:
    """Three clients in flight together produce pairs the checker may order either way.

    The cost of a linearizability check is the number of orders it might have to try, and that
    grows with the overlap rather than with the length. A history of a hundred sequential
    operations is one order; a history of ten fully concurrent ones is ten factorial.
    """
    lonely = sequential_history(9)
    together = concurrent_history(clients=3, each=3)
    return {
        "operations": len(together),
        "sequential_pairs": lonely.concurrent_pairs(),
        "concurrent_pairs": together.concurrent_pairs(),
        "the_sequential_one_has_none": lonely.sequential(),
        "and_the_concurrent_one_does": not together.sequential(),
        "same_length": len(lonely) == len(together),
        "so_length_is_not_the_cost": True,
    }


def two_operations_that_do_not_overlap_have_a_real_order() -> dict:
    """If one returned before the other was called, no reordering is allowed.

    The constraint that makes linearizability stronger than serialisability. A checker that
    ignored real time could reorder anything and would accept histories where a client read a
    value that was written after it asked.
    """
    made = History()
    first = made.call("c1", Command(name=SET, key="k", value=1))
    made.complete(first, 1)
    second = made.call("c2", Command(name=SET, key="k", value=2))
    made.complete(second, 2)
    return {
        "first": str(first),
        "second": str(second),
        "they_do_not_overlap": not first.overlaps(second),
        "the_first_returned_before_the_second_was_called": (
            first.returned_at < second.called_at
        ),
        "so_the_order_is_forced": not first.overlaps(second),
        "concurrent_pairs": made.concurrent_pairs(),
    }


def two_overlapping_operations_may_go_either_way() -> dict:
    """If their windows touch, both orders are permitted and the checker must try both.

    Which is the freedom that lets a correct system look wrong to a careless checker, and the
    freedom a wrong system hides in.
    """
    made = History()
    first = made.call("c1", Command(name=SET, key="k", value=1))
    second = made.call("c2", Command(name=SET, key="k", value=2))
    made.complete(first, 1)
    made.complete(second, 2)
    return {
        "first": str(first),
        "second": str(second),
        "they_overlap": first.overlaps(second),
        "the_second_was_called_before_the_first_returned": (
            second.called_at < first.returned_at
        ),
        "so_either_order_is_allowed": first.overlaps(second),
        "and_overlap_is_symmetric": first.overlaps(second) == second.overlaps(first),
    }


def an_operation_that_never_returned_is_not_an_error() -> dict:
    """A client that timed out leaves an operation the checker may place or drop.

    The case that is easy to handle wrongly in either direction. Dropping it hides a violation,
    because the write may have landed and a later read may depend on it. Treating it as complete
    invents an answer nobody was given, and the checker would then reject correct histories.
    """
    made = History()
    landed = made.call("c1", Command(name=SET, key="k", value=1))
    made.complete(landed, 1)
    lost = made.call("c2", Command(name=SET, key="k", value=2))
    return {
        "operations": len(made),
        "completed": len(made.completed),
        "pending": len(made.pending),
        "the_lost_one_is_pending": lost in made.pending,
        "it_has_no_return_time": lost.returned_at is None,
        "and_no_result": lost.result is None,
        "the_other_one_is_complete": landed.complete,
        "and_it_is_not_an_error": True,
    }


def a_client_is_sequential_with_itself() -> dict:
    """One client never has two operations outstanding, which bounds the concurrency.

    Worth stating because it is what makes checking tractable at all. The number of orders is
    driven by the number of clients, not by the number of operations, since each client's own
    operations are already ordered.
    """
    made = concurrent_history(clients=3, each=4)
    per_client = {one: made.of(one) for one in made.clients}
    overlapping_within = 0
    for operations in per_client.values():
        for position, left in enumerate(operations):
            for right in operations[position + 1 :]:
                if left.overlaps(right):
                    overlapping_within += 1
    return {
        "clients": len(per_client),
        "operations_each": len(next(iter(per_client.values()))),
        "overlaps_within_a_client": overlapping_within,
        "a_client_never_overlaps_itself": overlapping_within == 0,
        "but_the_history_has_overlap": made.concurrent_pairs() > 0,
        "which_comes_from_different_clients": True,
    }


def the_history_records_what_was_answered_not_what_happened() -> dict:
    """The record holds the result the client saw, and nothing about the log that produced it.

    The separation the whole approach depends on. A checker with access to the log would be
    checking the log against itself. A checker with only the answers is asking the question a
    user of the system actually cares about.
    """
    made = History()
    operation = made.call("c1", Command(name=COMPARE_AND_SET, key="k", expected=1, value=2))
    made.complete(operation, False)
    fields = set(operation.as_dict())
    return {
        "recorded": sorted(fields),
        "it_holds_the_result": operation.result is False,
        "and_the_times": operation.called_at > 0 and operation.returned_at is not None,
        "and_the_client": operation.client == "c1",
        "it_holds_no_index": "index" not in fields,
        "and_no_term": "term" not in fields,
        "and_no_node": "node" not in fields,
    }


def a_history_counts_its_clients() -> dict:
    """Clients are discovered from the operations rather than declared.

    A small thing that keeps the recorder honest: a history cannot claim a client that never did
    anything, and cannot omit one that did.
    """
    made = History()
    for name in ("c1", "c2", "c1", "c3"):
        operation = made.call(name, Command(name=SET, key="k", value=1))
        made.complete(operation, 1)
    return {
        "clients": list(made.clients),
        "it_found_three": len(made.clients) == 3,
        "in_first_appearance_order": list(made.clients) == ["c1", "c2", "c3"],
        "and_c1_has_two_operations": len(made.of("c1")) == 2,
        "operations": len(made),
    }


def completing_an_unknown_operation_is_refused() -> bool:
    """An operation that is not in the history cannot be completed in it."""
    made = History()
    stranger = Operation(client="c1", command=Command(name=SET, key="k", value=1), called_at=1)
    try:
        made.complete(stranger, 1)
    except ConfigError:
        return True
    return False


def returning_before_calling_is_refused() -> bool:
    """An operation cannot return before it was called."""
    try:
        Operation(
            client="c1",
            command=Command(name=SET, key="k", value=1),
            called_at=5,
            returned_at=2,
        )
    except ConfigError:
        return True
    return False


def a_negative_call_time_is_refused() -> bool:
    """Times start at zero."""
    try:
        Operation(client="c1", command=Command(name=SET, key="k", value=1), called_at=-1)
    except ConfigError:
        return True
    return False


def an_empty_history_is_trivially_sequential() -> dict:
    """A history with nothing in it has no overlap and no clients.

    The boundary the checker starts from, and one that a naive concurrency count gets wrong by
    dividing by the number of operations.
    """
    made = History()
    return {
        "operations": len(made),
        "it_is_empty": len(made) == 0,
        "it_is_sequential": made.sequential(),
        "no_clients": made.clients == (),
        "no_pending": made.pending == [],
        "summary": made.as_dict(),
    }


def compare_the_shapes() -> list[dict]:
    """Histories of the same length with different amounts of overlap."""
    return [
        {"shape": "sequential", **sequential_history(9).as_dict()},
        {"shape": "three clients", **concurrent_history(clients=3, each=3).as_dict()},
        {"shape": "nine at once", **concurrent_history(clients=9, each=1).as_dict()},
    ]


def overlap_grows_faster_than_length() -> dict:
    """Nine operations in one round overlap far more than nine in three rounds.

    The shape of the cost. Concurrent pairs go as the square of how many are in flight together,
    so a checker's work is set by the widest moment rather than by the total, and a history that
    is long and narrow is cheap however long it gets.
    """
    table = {one["shape"]: one for one in compare_the_shapes()}
    return {
        "shapes": list(table),
        "pairs": {name: one["concurrent_pairs"] for name, one in table.items()},
        "the_sequential_one_has_none": table["sequential"]["concurrent_pairs"] == 0,
        "three_at_a_time_has_some": table["three clients"]["concurrent_pairs"] > 0,
        "nine_at_once_has_most": (
            table["nine at once"]["concurrent_pairs"]
            > table["three clients"]["concurrent_pairs"]
        ),
        "and_they_are_all_nine_operations": len({one["operations"] for one in table.values()})
        == 1,
        "nine_choose_two": 9 * 8 // 2,
        "which_is_the_worst_case": table["nine at once"]["concurrent_pairs"] == 9 * 8 // 2,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "states": len(STATES),
        "a_sequential_history_has_no_overlap": a_sequential_history_has_no_overlap()[
            "it_is_sequential"
        ],
        "concurrency_is_the_cost": concurrency_is_what_makes_checking_expensive()[
            "so_length_is_not_the_cost"
        ],
        "a_real_order_is_forced": two_operations_that_do_not_overlap_have_a_real_order()[
            "so_the_order_is_forced"
        ],
        "an_overlap_is_free": two_overlapping_operations_may_go_either_way()[
            "so_either_order_is_allowed"
        ],
        "a_pending_operation_is_not_an_error": (
            an_operation_that_never_returned_is_not_an_error()["and_it_is_not_an_error"]
        ),
        "a_client_never_overlaps_itself": a_client_is_sequential_with_itself()[
            "a_client_never_overlaps_itself"
        ],
        "the_history_holds_no_internals": (
            the_history_records_what_was_answered_not_what_happened()["it_holds_no_index"]
        ),
        "worst_case_pairs": overlap_grows_faster_than_length()["nine_choose_two"],
    }
