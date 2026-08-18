"""Watch a key, disconnect, come back the wrong way, and count what went missing.

Run with: python examples/follow_the_log.py

A watch is the feature that turns a replicated log into something people build on, and the whole
of it is a question about the log. The events are the committed entries in the order the log put
them in, and resuming means naming an index, because the alternative loses events silently.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.verify.trace import LEVELS, capture, replay
from rsm.watch import Event, Feed, Watcher


def resumption_rows() -> list[dict]:
    """The three ways a watcher comes back, over the same events."""
    events = [Event(index=one, key="k", value=one) for one in range(1, 31)]
    out = []
    for style in ("never disconnected", "from an index", "from now"):
        feed = Feed()
        made = feed.add(Watcher(name=style))
        mark = 0
        for index, one in enumerate(events):
            if index == 10 and style != "never disconnected":
                made.connected = False
                mark = made.at
            if index == 20 and style != "never disconnected":
                made.connected = True
                if style == "from now":
                    made.at = one.index - 1
                else:
                    for missed in feed.since(mark):
                        made.deliver(missed)
            feed.publish(one)
        out.append(
            {
                "resumption": style,
                "saw": len(made.seen),
                "missed": len(events) - len(made.seen),
                "in order": "yes" if made.ordered else "no",
                "complete": "yes" if len(made.seen) == len(events) else "no",
            }
        )
    return out


def fan_out_rows() -> list[dict]:
    """What the delivery costs as the watchers multiply."""
    events = [Event(index=one, key=f"k{one % 4}", value=one) for one in range(1, 41)]
    out = []
    for count, key in ((1, ""), (5, ""), (20, ""), (20, "filtered")):
        feed = Feed()
        for one in range(count):
            feed.add(Watcher(name=f"w{one}", key=f"k{one % 4}" if key else ""))
        for event in events:
            feed.publish(event)
        out.append(
            {
                "watchers": count,
                "filtered": "yes" if key else "no",
                "events": len(events),
                "deliveries": feed.delivered,
                "fan out": feed.as_dict()["fan_out"],
            }
        )
    return out


def trace_rows() -> list[dict]:
    """The levels of a recorded run, and what each one can still do."""
    made = capture(kill_at=60)
    out = []
    for level in LEVELS:
        one = made.at_level(level)
        out.append(
            {
                "level": level,
                "events": len(one),
                "share": round(len(one) / len(made), 3),
                "replayable": "yes" if one.of_kind("deliver") else "no",
                "readable": "yes" if len(one) < 40 else "no",
            }
        )
    return out


def main() -> None:
    print(rule("coming back from a disconnection"))
    print(table(resumption_rows()))
    print()
    print("every row is in order, including the one missing a third of the events, so a")
    print("client checking that the indices increase would pass all three")
    print()

    print(rule("what the delivery costs"))
    print(table(fan_out_rows()))
    print()
    print("the fan out is the watchers times the events, and filtering divides it by the")
    print("spread of the keys; none of it is a consensus cost")
    print()

    print(rule("recording a run"))
    print(table(trace_rows()))
    print()
    made = capture(kill_at=60)
    back = replay(made)
    print(
        pairs(
            {
                "events recorded": len(made),
                "events replayed": back.applied,
                "leaders reconstructed": len(back.leaders),
                "mismatches": len(back.mismatches),
                "the outline": len(made.at_level("outline")),
                "compression": bar(1 - len(made.at_level("outline")) / len(made), 20),
            }
        )
    )
    print()
    print("nothing is both readable and complete, and the answer is not a better level: a")
    print("trace is two artefacts sharing a list")


if __name__ == "__main__":
    main()
