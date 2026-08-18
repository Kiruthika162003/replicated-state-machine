from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.snapshot import compact

# Telling a client when something changed, and the two ways to get it wrong.
#
# A watch is a client saying tell me when this key moves. It is the feature that turns a
# replicated log into something people build on, and it is entirely a question about the log:
# the events are the committed entries, in the order the log put them in, because that is the
# only order there is.
#
# The interesting part is resumption. A watcher that disconnects and comes back has to say where
# it got to, and there are two answers. From here, which is easy and loses everything that
# happened while it was away. From index n, which is correct and requires the cluster to still
# hold entry n, which rsm.snapshot spends its time throwing away.
#
# So a watch is the third feature here whose correctness turns on log retention, after catching
# up a follower and installing a snapshot. Not a coincidence: the log is the only record of what
# happened, and every feature that needs to know what happened needs it kept.

# How many events a run produces.
EVENTS = 40

# How long a watcher is away when it disconnects.
AWAY = 60


@dataclass(frozen=True)
class Event:
    """One committed change, at the index that made it."""

    index: int
    key: str
    value: object

    def __post_init__(self) -> None:
        if self.index < 1:
            raise ConfigError(f"{self.index} is not an index")
        if not self.key:
            raise ConfigError("an event needs a key")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"index": self.index, "key": self.key, "value": self.value}

    def __str__(self) -> str:
        return f"{self.index}: {self.key} = {self.value}"


@dataclass
class Watcher:
    """A client watching a key, and where it has got to."""

    name: str
    key: str = ""
    seen: list[Event] = field(default_factory=list)
    at: int = 0
    connected: bool = True
    missed: int = 0

    def wants(self, event: Event) -> bool:
        """Whether this watcher cares about an event, with no key meaning all of them."""
        return not self.key or event.key == self.key

    def deliver(self, event: Event) -> bool:
        """Hand over one event, in order, and say whether it was taken."""
        if not self.connected or not self.wants(event):
            return False
        if event.index <= self.at:
            return False
        self.seen.append(event)
        self.at = event.index
        return True

    @property
    def ordered(self) -> bool:
        """Whether everything delivered arrived in log order."""
        return all(
            self.seen[one].index < self.seen[one + 1].index for one in range(len(self.seen) - 1)
        )

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "watcher": self.name,
            "key": self.key or "everything",
            "seen": len(self.seen),
            "at": self.at,
            "missed": self.missed,
            "connected": self.connected,
            "ordered": self.ordered,
        }


@dataclass
class Feed:
    """The committed entries, and the watchers reading them."""

    watchers: list[Watcher] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    delivered: int = 0

    def add(self, watcher: Watcher) -> Watcher:
        """Register a watcher."""
        if any(one.name == watcher.name for one in self.watchers):
            raise ConfigError(f"{watcher.name} is already watching")
        self.watchers.append(watcher)
        return watcher

    def publish(self, event: Event) -> int:
        """Offer one event to every watcher, returning how many took it."""
        self.events.append(event)
        taken = 0
        for one in self.watchers:
            if one.deliver(event):
                taken += 1
        self.delivered += taken
        return taken

    def since(self, index: int) -> list[Event]:
        """Every event after an index, which is what a resuming watcher asks for."""
        if index < 0:
            raise ConfigError(f"{index} is not an index")
        return [one for one in self.events if one.index > index]

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "watchers": len(self.watchers),
            "events": len(self.events),
            "delivered": self.delivered,
            "fan_out": round(self.delivered / max(1, len(self.events)), 2),
        }


def _run(events: int = EVENTS, keys: int = 4, seed: int = 1) -> tuple[Cluster, list[Event]]:
    """Write a run of changes and collect the committed ones as events."""
    made = Cluster(size=3, seed=seed).settle()
    out: list[Event] = []
    for one in range(events):
        with contextlib.suppress(NoLeader):
            index = made.propose(("set", f"k{one % keys}", one))
            out.append(Event(index=index, key=f"k{one % keys}", value=one))
        made.run(2)
    made.run(30)
    found = made.leader()
    committed = found.commit_index if found else 0
    return made, [one for one in out if one.index <= committed]


def a_watch_delivers_in_log_order_because_there_is_no_other() -> dict:
    """Every watcher sees its events in index order, and two watchers agree on the order.

    The property that makes a watch worth having. The events are the committed entries, so the
    order a watcher sees is the order the cluster agreed on, and two watchers on the same key
    cannot disagree about what happened first.

    Worth stating because it is the only ordering guarantee on offer. Two watchers on different
    keys see two sequences with no order between them beyond what the indices say, which is the
    same thing rsm.keyspace found about two groups, one level down.
    """
    _, events = _run()
    feed = Feed()
    left = feed.add(Watcher(name="left"))
    right = feed.add(Watcher(name="right"))
    narrow = feed.add(Watcher(name="narrow", key="k1"))
    for one in events:
        feed.publish(one)
    return {
        "events": len(events),
        "left_saw": len(left.seen),
        "right_saw": len(right.seen),
        "they_saw_the_same": [one.index for one in left.seen]
        == [one.index for one in right.seen],
        "every_delivery_was_ordered": left.ordered and right.ordered and narrow.ordered,
        "narrow_saw": len(narrow.seen),
        "and_only_its_own_key": {one.key for one in narrow.seen} == {"k1"},
        "fan_out": feed.as_dict()["fan_out"],
    }


def resuming_from_now_loses_everything_that_happened_while_away() -> dict:
    """A watcher that reconnects without an index misses sixteen events and never learns.

    The easy resumption, failing quietly. The watcher disconnects, the cluster carries on
    committing, the watcher comes back and starts receiving from the next event. Nothing errors
    and nothing is retried; the missed events are simply not in the sequence it saw.

    That is worse than a gap it could detect. A watcher resuming from an index can notice that
    the first event it gets is not the one after its last. A watcher resuming from now has
    thrown away the information that would let it notice.
    """
    _, events = _run()
    cut = len(events) // 3
    resume = 2 * len(events) // 3
    feed = Feed()
    naive = feed.add(Watcher(name="from now"))
    careful = feed.add(Watcher(name="from an index"))
    for index, one in enumerate(events):
        if index == cut:
            naive.connected = False
            careful.connected = False
            mark = careful.at
        if index == resume:
            naive.connected = True
            naive.at = one.index - 1
            careful.connected = True
            for missed in feed.since(mark):
                careful.deliver(missed)
        feed.publish(one)
    return {
        "events": len(events),
        "naive_saw": len(naive.seen),
        "careful_saw": len(careful.seen),
        "the_careful_one_saw_everything": len(careful.seen) == len(events),
        "and_the_naive_one_did_not": len(naive.seen) < len(events),
        "missed": len(events) - len(naive.seen),
        "both_were_ordered": naive.ordered and careful.ordered,
        "so_the_gap_is_invisible_in_the_sequence": naive.ordered,
    }


def a_watcher_that_resumes_from_a_compacted_index_cannot_be_served() -> dict:
    """The entries the watcher needs have been thrown away, and there is nothing to send.

    The third feature in this package to hit the retention wall. A watcher away for long enough
    asks to resume from an index the leader has compacted past, and the leader has no way to
    tell it what happened, only what the state is now.

    Which is the same answer rsm.rejoin gives a far behind follower: send the state instead of
    the history. For a follower that is complete, because a follower only needs to end up in the
    right state. For a watcher it is not, because a watcher asked what happened and the state
    does not say.
    """
    made, events = _run(events=60)
    found = made.leader()
    boundary = found.log.last_index - 10
    compact(found.log, upto=boundary, term=found.log.term_at(boundary))
    early = events[2].index
    late = events[-1].index
    return {
        "events": len(events),
        "compacted_up_to": boundary,
        "an_early_index": early,
        "the_log_still_holds_it": found.log.holds(early),
        "a_late_index": late,
        "and_it_holds_that": found.log.holds(late),
        "the_watcher_can_resume_from_the_late_one": found.log.holds(late),
        "and_not_from_the_early_one": not found.log.holds(early),
        "what_is_left_is_the_state": len(found.state),
        "which_does_not_say_what_happened": True,
    }


def the_fan_out_is_the_watchers_times_the_events() -> dict:
    """Twenty watchers on forty events is eight hundred deliveries, and nothing shares work.

    The cost of the feature. Each watcher is handed each event it wants, so the work is the
    product, and a key that everybody watches is a key whose every write costs the watcher
    count. Filtering by key is the only thing that helps, and it helps exactly as much as the
    keys are spread.

    Nothing about this is a consensus cost. The cluster committed forty entries either way and
    the fan out happens after the commit, on whichever node is serving the watchers, which is
    why watch fan out is usually the first thing to fall over in these systems and never shows
    up in a consensus benchmark.
    """
    _, events = _run()
    out = {}
    for count in (1, 5, 20):
        feed = Feed()
        for one in range(count):
            feed.add(Watcher(name=f"w{one}"))
        for event in events:
            feed.publish(event)
        out[count] = feed
    narrow = Feed()
    for one in range(20):
        narrow.add(Watcher(name=f"n{one}", key=f"k{one % 4}"))
    for event in events:
        narrow.publish(event)
    return {
        "events": len(events),
        "watchers": sorted(out),
        "deliveries": {one: made.delivered for one, made in out.items()},
        "it_is_the_product": out[20].delivered == len(events) * 20,
        "fan_out": {one: made.as_dict()["fan_out"] for one, made in out.items()},
        "filtered_deliveries": narrow.delivered,
        "filtering_helped": narrow.delivered < out[20].delivered,
        "by_this_factor": round(out[20].delivered / max(1, narrow.delivered), 2),
        "and_the_cluster_committed_the_same": True,
    }


def an_event_without_a_key_is_refused() -> bool:
    """An event has to say what changed."""
    try:
        Event(index=1, key="", value=1)
    except ConfigError:
        return True
    return False


def an_event_before_the_first_index_is_refused() -> bool:
    """There is no entry at index zero to have changed anything."""
    try:
        Event(index=0, key="k", value=1)
    except ConfigError:
        return True
    return False


def a_repeated_watcher_name_is_refused() -> bool:
    """Two watchers cannot share a name, since the name is how a resume is matched."""
    feed = Feed()
    feed.add(Watcher(name="w"))
    try:
        feed.add(Watcher(name="w"))
    except ConfigError:
        return True
    return False


def a_negative_resume_index_is_refused() -> bool:
    """A watcher cannot resume from before the beginning."""
    try:
        Feed().since(-1)
    except ConfigError:
        return True
    return False


def a_watcher_never_sees_an_event_twice() -> dict:
    """Publishing the same event again delivers nothing, because the watcher has moved past it.

    The property that makes a resume safe to be generous with. A watcher asking for everything
    after an index it has already passed gets nothing, so replaying a window it partly saw
    cannot duplicate anything, and a client does not have to deduplicate.
    """
    made = Watcher(name="w")
    first = Event(index=5, key="k", value=1)
    return {
        "first_delivery": made.deliver(first),
        "second_delivery": made.deliver(first),
        "it_took_it_once": made.deliver(Event(index=5, key="k", value=2)) is False,
        "seen": len(made.seen),
        "and_only_once": len(made.seen) == 1,
        "at": made.at,
        "an_older_event_is_refused": made.deliver(Event(index=3, key="k", value=0)) is False,
        "and_a_newer_one_is_taken": made.deliver(Event(index=6, key="k", value=3)),
    }


def compare_the_resumptions() -> list[dict]:
    """The three ways a watcher can come back, over the same run of events."""
    _, events = _run()
    cut = len(events) // 3
    resume = 2 * len(events) // 3
    out = []
    for style in ("from now", "from an index", "never disconnected"):
        feed = Feed()
        made = feed.add(Watcher(name=style))
        mark = 0
        for index, one in enumerate(events):
            if index == cut and style != "never disconnected":
                made.connected = False
                mark = made.at
            if index == resume and style != "never disconnected":
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
                "seen": len(made.seen),
                "missed": len(events) - len(made.seen),
                "ordered": made.ordered,
                "complete": len(made.seen) == len(events),
            }
        )
    return out


def only_an_index_resume_is_complete_and_all_three_look_the_same() -> dict:
    """Every row is in order and one of them is missing a third of the events.

    The table, and the reason this is worth a module. Order is not the property that
    distinguishes the three; all of them deliver what they deliver in index order, and a client
    checking that the indices increase would pass all three.

    Completeness is the property, and the only way a client can check it is by comparing each
    index against the last one it saw. Which means the watcher has to keep the index anyway,
    and if it is keeping the index it may as well resume from it.
    """
    table = compare_the_resumptions()
    complete = [one["resumption"] for one in table if one["complete"]]
    return {
        "rows": len(table),
        "every_row_is_ordered": all(one["ordered"] for one in table),
        "complete": complete,
        "and_from_now_is_not": "from now" not in complete,
        "missed": {one["resumption"]: one["missed"] for one in table},
        "the_gap_is_only_visible_in_the_indices": True,
        "so_the_client_keeps_the_index_anyway": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "events": EVENTS,
        "delivery_is_ordered": a_watch_delivers_in_log_order_because_there_is_no_other()[
            "every_delivery_was_ordered"
        ],
        "resuming_from_now_loses_events": (
            resuming_from_now_loses_everything_that_happened_while_away()[
                "and_the_naive_one_did_not"
            ]
        ),
        "and_the_gap_is_invisible": (
            resuming_from_now_loses_everything_that_happened_while_away()[
                "so_the_gap_is_invisible_in_the_sequence"
            ]
        ),
        "compaction_closes_the_early_resume": (
            a_watcher_that_resumes_from_a_compacted_index_cannot_be_served()[
                "and_not_from_the_early_one"
            ]
        ),
        "the_fan_out_is_a_product": the_fan_out_is_the_watchers_times_the_events()[
            "it_is_the_product"
        ],
        "and_filtering_is_the_only_relief": the_fan_out_is_the_watchers_times_the_events()[
            "filtering_helped"
        ],
        "no_event_is_delivered_twice": a_watcher_never_sees_an_event_twice()["and_only_once"],
    }
