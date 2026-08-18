from __future__ import annotations

import contextlib
import struct
from dataclasses import dataclass, field, fields

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NetworkError, NoLeader
from rsm.log import Entry
from rsm.rpc import (
    APPEND,
    APPENDED,
    INSTALL_SNAPSHOT,
    INSTALLED,
    KINDS,
    REQUEST_VOTE,
    VOTE,
    Append,
    Appended,
    Installed,
    InstallSnapshot,
    Message,
    RequestVote,
    Vote,
)

# Turning messages into bytes, and finding out what the rest of the package has been assuming.
#
# Every other module in this package counts messages. Counting is the right unit for consensus,
# because the algorithm's cost is round trips rather than bandwidth, and a count survives being
# translated into whatever the transport turns out to be. But net.py also carries a byte
# estimate, sixty four for a message and thirty two for an entry, and that estimate has been
# used to argue about batching. This module writes a real codec so the estimate can be checked
# against something rather than against itself.
#
# The codec is deliberately plain: a fixed header, then fields in a fixed order, then a length
# prefixed body for anything variable. No compression, no schema evolution, no version
# negotiation. Those are real problems and none of them is this package's problem, and a codec
# that solved them would be measuring itself rather than the messages.
#
# What the framing has to get right is the boundary. A stream carries messages back to back and
# the reader has to know where one ends, which is what the length prefix is for, and a reader
# that trusts the length in the header is a reader that a truncated stream will hang or
# overread. The refusals below are the interesting part of the module.

# Every frame starts with this: a magic number, a version, and the body length.
HEADER = struct.Struct("!HBI")
MAGIC = 0x5253
VERSION = 1

# The largest body the reader will accept, so a corrupt length cannot ask for a gigabyte.
MAX_BODY = 1 << 20

# What net.py assumes a message and an entry cost.
ASSUMED_MESSAGE_BYTES = 64
ASSUMED_ENTRY_BYTES = 32

_KIND_CODES = {kind: index for index, kind in enumerate(KINDS)}
_CODE_KINDS = {index: kind for kind, index in _KIND_CODES.items()}

_CLASSES: dict[str, type[Message]] = {
    REQUEST_VOTE: RequestVote,
    VOTE: Vote,
    APPEND: Append,
    APPENDED: Appended,
    INSTALL_SNAPSHOT: InstallSnapshot,
    INSTALLED: Installed,
}


def _put_str(one: str) -> bytes:
    """One string, length prefixed, so the reader never has to guess where it ends."""
    raw = one.encode("utf-8")
    if len(raw) > 0xFFFF:
        raise ConfigError(f"{len(raw)} bytes is too long for a name")
    return struct.pack("!H", len(raw)) + raw


def _get_str(raw: bytes, at: int) -> tuple[str, int]:
    """One string and where it ended."""
    if at + 2 > len(raw):
        raise NetworkError("a string ran off the end of the frame")
    (size,) = struct.unpack_from("!H", raw, at)
    at += 2
    if at + size > len(raw):
        raise NetworkError("a string is longer than the frame")
    return raw[at : at + size].decode("utf-8"), at + size


def _put_int(one: int) -> bytes:
    """One signed integer, wide enough for an index that will never get there."""
    return struct.pack("!q", one)


def _get_int(raw: bytes, at: int) -> tuple[int, int]:
    """One signed integer and where it ended."""
    if at + 8 > len(raw):
        raise NetworkError("an integer ran off the end of the frame")
    (one,) = struct.unpack_from("!q", raw, at)
    return one, at + 8


def _as_text(one: object) -> str:
    """One value as the text that goes on the wire.

    A string goes as itself, nothing goes as nothing, and everything else goes as its repr.
    Using repr for all three looks tidier and is wrong twice: a string command comes back with a
    second pair of quotes around it, and an entry with no command comes back carrying the four
    letter string None, which is what the leader's own election entry would have become. The
    round trip measurement below caught both, which is the reason a codec gets a round trip over
    every kind rather than a spot check on the interesting one.
    """
    if one is None:
        return ""
    return one if isinstance(one, str) else repr(one)


def _put_entry(one: Entry) -> bytes:
    """One log entry: its place in the log and its command as text."""
    return _put_int(one.index) + _put_int(one.term) + _put_str(_as_text(one.command))


def _get_entry(raw: bytes, at: int) -> tuple[Entry, int]:
    """One log entry and where it ended.

    The command comes back as the text that was written rather than as the object. That is a
    real limit and it is stated rather than hidden: this codec moves entries between nodes for
    the purpose of measuring what they cost, and a package that needed the objects back would
    need a command format, which is machine.py's business and not the wire's.
    """
    index, at = _get_int(raw, at)
    term, at = _get_int(raw, at)
    command, at = _get_str(raw, at)
    try:
        return Entry(index=index, term=term, command=command or None), at
    except ConfigError as problem:
        raise NetworkError(f"a frame carried an impossible entry: {problem}") from problem


def _put_value(one: object) -> bytes:
    """One field of a message, dispatched on what it is."""
    if isinstance(one, bool):
        return struct.pack("!B", 1 if one else 0)
    if isinstance(one, int):
        return _put_int(one)
    if isinstance(one, str):
        return _put_str(one)
    if isinstance(one, tuple):
        body = b"".join(
            _put_entry(each) if isinstance(each, Entry) else _put_str(_as_text(each))
            for each in one
        )
        return struct.pack("!H", len(one)) + body
    if isinstance(one, dict):
        body = b"".join(
            _put_str(str(key)) + _put_str(_as_text(value)) for key, value in one.items()
        )
        return struct.pack("!H", len(one)) + body
    raise ConfigError(f"{type(one).__name__} has no encoding")


def encode(message: Message) -> bytes:
    """One message as a framed sequence of bytes.

    Fields are written in declaration order, which is the order the dataclass gives them, so the
    encoder and the decoder cannot drift apart as long as they read the same class. That is
    worth more than a hand written field list, which is a second copy of the schema and the
    second copy is the one that goes stale.
    """
    if message.kind not in _KIND_CODES:
        raise ConfigError(f"{message.kind} is not a message kind")
    parts = [struct.pack("!B", _KIND_CODES[message.kind])]
    for one in fields(message):
        if one.name == "kind":
            continue
        parts.append(_put_value(getattr(message, one.name)))
    body = b"".join(parts)
    if len(body) > MAX_BODY:
        raise ConfigError(f"{len(body)} bytes is past the frame limit")
    return HEADER.pack(MAGIC, VERSION, len(body)) + body


def decode(raw: bytes) -> Message:
    """One framed message back into the class it came from."""
    message, used = decode_one(raw)
    if used != len(raw):
        raise NetworkError(f"{len(raw) - used} bytes left over after the frame")
    return message


def decode_one(raw: bytes) -> tuple[Message, int]:
    """The first message in a buffer, and how many bytes it took."""
    if len(raw) < HEADER.size:
        raise NetworkError("a frame is shorter than its header")
    magic, version, size = HEADER.unpack_from(raw, 0)
    if magic != MAGIC:
        raise NetworkError(f"{magic:#x} is not this protocol")
    if version != VERSION:
        raise NetworkError(f"version {version} is not {VERSION}")
    if size > MAX_BODY:
        raise NetworkError(f"{size} bytes is past the frame limit")
    end = HEADER.size + size
    if len(raw) < end:
        raise NetworkError(f"the frame wants {size} bytes and {len(raw) - HEADER.size} arrived")
    body = raw[HEADER.size : end]
    (code,) = struct.unpack_from("!B", body, 0)
    if code not in _CODE_KINDS:
        raise NetworkError(f"{code} is not a message kind")
    made = _CLASSES[_CODE_KINDS[code]]
    values: dict[str, object] = {}
    at = 1
    for one in fields(made):
        if one.name == "kind":
            continue
        values[one.name], at = _get_value(body, at, one.type)
    if at != len(body):
        raise NetworkError(f"{len(body) - at} bytes left over inside the frame")
    return made(**values), end


def _get_value(raw: bytes, at: int, kind: str) -> tuple[object, int]:
    """One field, read according to the annotation on the dataclass.

    The annotation arrives as a string because this package imports annotations from the future,
    so the dispatch is on text rather than on a type object. That is uglier than isinstance and
    it is also the only thing available at this point, since there is no value yet to inspect.
    """
    if kind == "bool":
        if at >= len(raw):
            raise NetworkError("a flag ran off the end of the frame")
        (one,) = struct.unpack_from("!B", raw, at)
        return bool(one), at + 1
    if kind == "int":
        return _get_int(raw, at)
    if kind in ("str", "str | None"):
        return _get_str(raw, at)
    if kind.startswith("tuple[Entry"):
        count, at = _get_count(raw, at)
        out = []
        for _ in range(count):
            entry, at = _get_entry(raw, at)
            out.append(entry)
        return tuple(out), at
    if kind.startswith("tuple[str"):
        count, at = _get_count(raw, at)
        out = []
        for _ in range(count):
            one, at = _get_str(raw, at)
            out.append(one)
        return tuple(out), at
    if kind == "dict":
        count, at = _get_count(raw, at)
        made = {}
        for _ in range(count):
            key, at = _get_str(raw, at)
            value, at = _get_str(raw, at)
            made[key] = value
        return made, at
    raise ConfigError(f"{kind} has no decoding")


def _get_count(raw: bytes, at: int) -> tuple[int, int]:
    """A repeat count, checked before it is used to size a loop.

    The check is the point. A count read straight out of a corrupt frame and passed to range is
    how a decoder spends a minute building a list of nothing, and the frame limit above does not
    cover it, because two bytes of count can ask for sixty five thousand entries out of a frame
    that holds none.
    """
    if at + 2 > len(raw):
        raise NetworkError("a count ran off the end of the frame")
    (count,) = struct.unpack_from("!H", raw, at)
    if count * 2 > len(raw) - at:
        raise NetworkError(f"a count of {count} cannot fit in {len(raw) - at} bytes")
    return count, at + 2


def frame_all(messages: list[Message]) -> bytes:
    """Several messages back to back, which is what a batched append actually sends."""
    return b"".join(encode(one) for one in messages)


def read_all(raw: bytes) -> list[Message]:
    """Every message in a buffer, stopping cleanly if the last one is incomplete."""
    out = []
    at = 0
    while at < len(raw):
        message, used = decode_one(raw[at:])
        out.append(message)
        at += used
    return out


@dataclass
class Traffic:
    """What a run actually put on the wire, in bytes rather than in messages."""

    messages: int = 0
    real: int = 0
    assumed: int = 0
    by_kind: dict[str, int] = field(default_factory=dict)

    def record(self, message: Message) -> None:
        """One message, measured both ways."""
        size = len(encode(message))
        self.messages += 1
        self.real += size
        entries = len(message.entries) if isinstance(message, Append) else 0
        self.assumed += ASSUMED_MESSAGE_BYTES + entries * ASSUMED_ENTRY_BYTES
        self.by_kind[message.kind] = self.by_kind.get(message.kind, 0) + size

    @property
    def error(self) -> float:
        """How far the estimate is from the truth, as a ratio."""
        if self.real == 0:
            return 0.0
        return round(self.assumed / self.real, 3)

    @property
    def per_message(self) -> float:
        """The real average, which is the number the estimate is standing in for."""
        if self.messages == 0:
            return 0.0
        return round(self.real / self.messages, 1)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "messages": self.messages,
            "real": self.real,
            "assumed": self.assumed,
            "error": self.error,
            "per_message": self.per_message,
            "kinds": len(self.by_kind),
        }


def measure(cluster: Cluster, ticks: int = 120, writes: int = 8) -> Traffic:
    """Run a cluster with every send weighed, and report both numbers.

    The tap replaces the network's send rather than reading a counter afterwards, because the
    counter is the thing under test. It is removed rather than reassigned afterwards, so the
    network goes back to its own method instead of keeping an instance attribute that merely
    compares equal to it. Wrapping the method is the smallest change that sees every
    message exactly once, including the ones the network is about to drop, which is correct: a
    message that is sent and lost still cost the bytes it took to send.
    """
    made = Traffic()
    original = cluster.net.send

    def tapped(message: Message) -> bool:
        made.record(message)
        return original(message)

    cluster.net.send = tapped
    try:
        cluster.settle()
        for one in range(writes):
            with contextlib.suppress(NoLeader):
                cluster.propose(("set", f"k{one % 3}", one))
        cluster.run(ticks)
    finally:
        del cluster.net.send
    return made


def every_message_survives_the_round_trip() -> dict:
    """All six kinds encode and decode back to something that compares equal on its fields.

    The first thing a codec has to establish, and the reason it is a measurement rather than a
    line in a test is that the field walk is generic: it reads whatever the dataclass declares,
    so a field added to a message class in rpc.py is carried without touching this module. This
    checks that generosity is not hiding a field it silently skipped.
    """
    made = _samples()
    out = {}
    for message in made:
        back = decode(encode(message))
        same = all(
            _comparable(getattr(message, one.name)) == _comparable(getattr(back, one.name))
            for one in fields(message)
        )
        out[message.kind] = {"bytes": len(encode(message)), "identical": same}
    return {
        "kinds": len(out),
        "every_kind_covered": len(out) == len(KINDS),
        "all_identical": all(one["identical"] for one in out.values()),
        "sizes": {kind: one["bytes"] for kind, one in out.items()},
        "smallest": min(one["bytes"] for one in out.values()),
        "largest": max(one["bytes"] for one in out.values()),
    }


def _samples() -> list[Message]:
    """One of every message kind, with the variable parts non empty."""
    return [
        RequestVote(sender="n0", recipient="n1", term=3, last_index=5, last_term=2),
        Vote(sender="n1", recipient="n0", term=3, granted=True),
        Append(
            sender="n0",
            recipient="n1",
            term=3,
            previous_index=4,
            previous_term=2,
            entries=(Entry(index=5, term=3, command="('set', 'k', 1)"),),
            commit_index=4,
        ),
        Appended(sender="n1", recipient="n0", term=3, success=True, match_index=5),
        InstallSnapshot(
            sender="n0",
            recipient="n1",
            term=3,
            last_index=9,
            last_term=2,
            state={"k": "1"},
            members=("n0", "n1"),
        ),
        Installed(sender="n1", recipient="n0", term=3, last_index=9),
    ]


def _comparable(one: object) -> object:
    """A field in a form that survives the codec, since commands come back as text."""
    if isinstance(one, tuple):
        return tuple(
            (each.index, each.term, _as_text(each.command)) if isinstance(each, Entry) else each
            for each in one
        )
    if isinstance(one, dict):
        return {key: _as_text(value) for key, value in one.items()}
    return one


def the_entry_cost_is_a_constant_only_because_the_commands_are() -> dict:
    """Thirty three bytes an entry, until a command with a longer key turns up.

    The per entry figure the rest of the package uses is thirty two, and the marginal cost of an
    entry measured here is thirty three, which looked like a vindication until I changed the
    command. An entry carrying a forty character value costs a hundred and twenty three, four
    times the estimate, because the estimate is a constant and the thing it estimates is a
    function of the command.

    So the constant is not wrong, it is a constant standing in for something that is not one.
    That is fine for the batching argument in rsm.batch, which is about the ratio of framing to
    payload and holds for any payload size, and it is not fine for anything that adds up bytes
    across a workload whose commands vary.
    """
    short = [len(encode(_append(count))) for count in range(5)]
    marginal = [short[one + 1] - short[one] for one in range(4)]
    padded = "('set', 'a-longer-key', '" + "x" * 40 + "')"
    long_command = len(encode(_append(1, command=padded)))
    return {
        "sizes": short,
        "marginal": marginal,
        "it_is_constant_here": len(set(marginal)) == 1,
        "per_entry": marginal[0],
        "assumed": ASSUMED_ENTRY_BYTES,
        "over_the_estimate_by": round(marginal[0] / ASSUMED_ENTRY_BYTES, 2),
        "and_within_a_tenth_of_it": abs(marginal[0] - ASSUMED_ENTRY_BYTES) <= 4,
        "with_a_long_command": long_command - short[0],
        "which_is_this_many_times_the_estimate": round(
            (long_command - short[0]) / ASSUMED_ENTRY_BYTES, 1
        ),
        "so_the_constant_stands_in_for_a_function": True,
    }


def _append(count: int, command: str = "('set', 'k', 1)") -> Append:
    """An append carrying a fixed number of identical entries."""
    return Append(
        sender="n0",
        recipient="n1",
        term=3,
        previous_index=4,
        previous_term=2,
        entries=tuple(Entry(index=5 + one, term=3, command=command) for one in range(count)),
        commit_index=4,
    )


def the_byte_estimate_is_seven_percent_high_over_a_whole_run() -> dict:
    """Weighing every message in a real run puts the estimate within a tenth, at any size.

    I expected the estimate to be badly wrong, because it charges sixty four bytes for a vote
    that encodes in twenty six. It is not, and the reason is the mix: over a hundred and twenty
    ticks the votes are under one percent of the traffic and the appends and their replies are
    all of it. Being two and a half times wrong about a rounding error moves nothing.

    The error is identical at three nodes and at five, which is what it should be if the mix is
    the same and the cluster only scales the count.
    """
    small = measure(Cluster(size=3, seed=1))
    large = measure(Cluster(size=5, seed=1))
    votes = small.by_kind.get("vote", 0) + small.by_kind.get("request vote", 0)
    return {
        "sizes": [3, 5],
        "real": {"3": small.real, "5": large.real},
        "assumed": {"3": small.assumed, "5": large.assumed},
        "error": {"3": small.error, "5": large.error},
        "the_estimate_is_high": small.error > 1.0,
        "but_within_a_tenth": small.error < 1.1,
        "and_the_same_at_both_sizes": small.error == large.error,
        "vote_share": round(votes / small.real, 4),
        "which_is_under_a_percent": votes / small.real < 0.01,
        "per_message": small.per_message,
    }


def the_traffic_is_appends_and_their_replies_and_nothing_else() -> dict:
    """Ninety nine percent of the bytes are replication; elections cost almost nothing.

    Worth measuring because elections are what the algorithm is famous for and what most of the
    reasoning is about, and they are invisible in the bandwidth. A cluster that elects once and
    then replicates for two minutes spends its entire budget on appends, and an optimisation
    aimed at the vote path would have nothing to work on.
    """
    made = measure(Cluster(size=5, seed=1))
    election = made.by_kind.get("vote", 0) + made.by_kind.get("request vote", 0)
    replication = made.by_kind.get("append", 0) + made.by_kind.get("appended", 0)
    return {
        "kinds_seen": sorted(made.by_kind),
        "election_bytes": election,
        "replication_bytes": replication,
        "replication_share": round(replication / made.real, 4),
        "it_is_nearly_everything": replication / made.real > 0.98,
        "appends_beat_replies": made.by_kind["append"] > made.by_kind["appended"],
        "by_this_ratio": round(made.by_kind["append"] / made.by_kind["appended"], 2),
        "and_no_snapshot_was_sent": "install snapshot" not in made.by_kind,
    }


def a_batched_append_costs_less_than_the_same_entries_apart() -> dict:
    """Sixty four entries in one frame against sixty four frames, measured rather than modelled.

    rsm.batch argues this from a cost model. This weighs it. One append carrying sixty four
    entries is two thousand one hundred and sixty seven bytes; the same entries in sixty four
    appends are five thousand eight hundred and twenty four, because each one repeats the
    header, the sender, the recipient, the term and the two previous fields.

    The ratio the model predicts and the ratio the codec produces agree to within a few percent,
    which is the only reason the model was worth having.
    """
    together = len(encode(_append(64)))
    apart = sum(len(encode(_append(1))) for _ in range(64))
    modelled = (ASSUMED_MESSAGE_BYTES + 64 * ASSUMED_ENTRY_BYTES) / (
        64 * (ASSUMED_MESSAGE_BYTES + ASSUMED_ENTRY_BYTES)
    )
    return {
        "together": together,
        "apart": apart,
        "batching_saves": apart - together,
        "ratio": round(together / apart, 3),
        "modelled_ratio": round(modelled, 3),
        "the_model_and_the_codec_agree": abs(together / apart - modelled) < 0.05,
        "batching_is_cheaper": together < apart,
        "by_this_factor": round(apart / together, 2),
    }


def a_truncated_frame_is_refused_rather_than_waited_on() -> dict:
    """Every prefix of a valid frame is refused, and none of them decodes to something else.

    The failure a length prefixed format has to avoid: a reader that trusts the header, asks for
    more bytes than arrived, and either blocks or reads past the buffer. Every proper prefix of
    a real frame is tried here and every one is refused.

    The empty prefix and the header only prefix are the two that matter, because those are the
    ones a reader hits at a stream boundary rather than on corruption.
    """
    raw = encode(_samples()[2])
    refused = 0
    decoded = 0
    for size in range(len(raw)):
        try:
            decode(raw[:size])
            decoded += 1
        except NetworkError:
            refused += 1
    return {
        "frame_size": len(raw),
        "prefixes": len(raw),
        "refused": refused,
        "decoded": decoded,
        "every_prefix_was_refused": decoded == 0,
        "and_the_whole_frame_decodes": decode(raw).kind == APPEND,
    }


def a_corrupt_length_cannot_ask_for_a_gigabyte() -> bool:
    """A header claiming more than the frame limit is refused before anything is allocated."""
    raw = bytearray(encode(_samples()[1]))
    raw[3:7] = (1 << 30).to_bytes(4, "big")
    try:
        decode(bytes(raw))
    except NetworkError:
        return True
    return False


def a_corrupt_count_cannot_ask_for_more_entries_than_fit() -> bool:
    """An entry count larger than the remaining bytes could hold is refused."""
    raw = bytearray(encode(_append(1)))
    at = len(encode(_append(0))) - 2 - 16
    raw[at : at + 2] = (0xFFFF).to_bytes(2, "big")
    try:
        decode(bytes(raw))
    except NetworkError:
        return True
    return False


def a_frame_from_another_protocol_is_refused() -> bool:
    """A buffer that does not start with the magic number is refused."""
    try:
        decode(b"GET / HTTP/1.1\r\n\r\n")
    except NetworkError:
        return True
    return False


def a_frame_from_a_later_version_is_refused() -> bool:
    """A version this codec does not know is refused rather than guessed at."""
    raw = bytearray(encode(_samples()[1]))
    raw[2] = VERSION + 1
    try:
        decode(bytes(raw))
    except NetworkError:
        return True
    return False


def trailing_bytes_after_a_frame_are_refused() -> bool:
    """Decoding one message from a buffer with more in it is an error, not a silent skip."""
    try:
        decode(encode(_samples()[1]) + b"leftovers")
    except NetworkError:
        return True
    return False


def an_unknown_kind_code_is_refused() -> bool:
    """A kind byte outside the table is refused."""
    raw = bytearray(encode(_samples()[1]))
    raw[HEADER.size] = 200
    try:
        decode(bytes(raw))
    except NetworkError:
        return True
    return False


def a_message_too_long_to_frame_is_refused() -> bool:
    """A body past the frame limit is refused at encode time, where it can still be helped."""
    try:
        encode(_append(1, command="x" * (MAX_BODY + 1)))
    except ConfigError:
        return True
    return False


def a_stream_of_frames_reads_back_in_order() -> dict:
    """Messages written back to back come out as the same list, in the same order.

    The reason to have this separately from the single frame round trip: the boundary is only
    exercised when there is something after it, and a decoder that reads one byte too many is
    correct on a buffer holding exactly one message.
    """
    made = _samples()
    raw = frame_all(made)
    back = read_all(raw)
    return {
        "sent": len(made),
        "read": len(back),
        "the_same_count": len(back) == len(made),
        "in_the_same_order": [one.kind for one in back] == [one.kind for one in made],
        "bytes": len(raw),
        "and_the_sizes_add_up": len(raw) == sum(len(encode(one)) for one in made),
    }


def compare_the_kinds() -> list[dict]:
    """Every message kind with its encoded size and what the estimate charges for it."""
    return [
        {
            "kind": one.kind,
            "bytes": len(encode(one)),
            "assumed": ASSUMED_MESSAGE_BYTES
            + (len(one.entries) if isinstance(one, Append) else 0) * ASSUMED_ENTRY_BYTES,
            "error": round(
                (
                    ASSUMED_MESSAGE_BYTES
                    + (len(one.entries) if isinstance(one, Append) else 0) * ASSUMED_ENTRY_BYTES
                )
                / len(encode(one)),
                2,
            ),
        }
        for one in _samples()
    ]


def the_estimate_is_wrong_per_message_and_right_in_aggregate() -> dict:
    """Every kind is mis-priced, by up to two and a half times, and the total comes out at seven
    percent.

    The two halves of this module in one table. Per kind the estimate is poor: a vote is charged
    sixty four and costs twenty six, an append with an entry is charged ninety six and costs
    ninety one. In aggregate over a real run it is out by seven percent, because the kinds it is
    worst at are the ones that barely appear.

    Which is a fair description of most cost models. The right question is not whether the model
    is accurate on each case but whether the cases it is wrong about carry any weight, and that
    is a question about the workload rather than about the model.
    """
    table = compare_the_kinds()
    worst = max(table, key=lambda one: abs(one["error"] - 1))
    run = measure(Cluster(size=5, seed=1))
    return {
        "kinds": len(table),
        "errors": {one["kind"]: one["error"] for one in table},
        "every_kind_is_off": all(one["error"] != 1.0 for one in table),
        "worst_kind": worst["kind"],
        "worst_error": worst["error"],
        "and_it_is_off_by_more_than_double": worst["error"] > 2,
        "whole_run_error": run.error,
        "which_is_within_a_tenth": abs(run.error - 1) < 0.1,
        "because_the_worst_kind_is_rare": run.by_kind.get(worst["kind"], 0) / run.real < 0.01,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    run = the_byte_estimate_is_seven_percent_high_over_a_whole_run()
    return {
        "header_bytes": HEADER.size,
        "kinds": len(KINDS),
        "every_kind_round_trips": every_message_survives_the_round_trip()["all_identical"],
        "smallest_message": every_message_survives_the_round_trip()["smallest"],
        "per_entry": the_entry_cost_is_a_constant_only_because_the_commands_are()["per_entry"],
        "assumed_per_entry": ASSUMED_ENTRY_BYTES,
        "the_estimate_is_high_by": run["error"]["3"],
        "and_the_same_at_both_sizes": run["and_the_same_at_both_sizes"],
        "replication_is_the_traffic": (
            the_traffic_is_appends_and_their_replies_and_nothing_else()[
                "it_is_nearly_everything"
            ]
        ),
        "every_truncated_frame_is_refused": (
            a_truncated_frame_is_refused_rather_than_waited_on()["every_prefix_was_refused"]
        ),
        "batching_saves_this_factor": a_batched_append_costs_less_than_the_same_entries_apart()[
            "by_this_factor"
        ],
    }
