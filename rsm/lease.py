from __future__ import annotations

from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.node import HEARTBEAT_INTERVAL, MIN_ELECTION_TIMEOUT

# Leader leases: serving reads without asking anybody, and the assumption that costs.
#
# A read that has to be correct cannot simply be answered by whoever thinks it is the leader,
# because a deposed leader does not know it has been deposed. rsm.client measures the three
# usual answers: read locally and risk being stale, confirm leadership with a round of
# heartbeats first, or put the read through the log as an entry. The first is free and wrong,
# the second costs a round trip, the third costs a round trip and a log entry.
#
# The lease is a fourth answer. A leader that heard from a majority at tick t may serve reads
# locally until t plus a lease, on the argument that no other leader can have been elected in
# that window, because an election needs a timeout to expire first. It is free after the
# heartbeat that established it, and it is the only one of the four that is free and correct.
#
# The catch is what it assumes. The argument compares a duration measured on the leader's clock
# with a duration measured on the followers' clocks, so it holds only if the clocks agree to
# within some bound. Raft is otherwise entirely free of clock assumptions: it uses timers to
# decide when to give up, never to decide what is true. A lease is the one place that changes,
# and this module measures what happens when the assumption is wrong rather than arguing about
# whether it usually is.

# How long a lease lasts, as a share of the shortest election timeout.
#
# It has to be shorter, and the margin is what pays for the clock error. At exactly the timeout
# there is no margin at all and any drift in the wrong direction is a stale read.
LEASE_SHARE = 0.5
LEASE = int(MIN_ELECTION_TIMEOUT * LEASE_SHARE)


@dataclass
class Read:
    """One read, what it returned, and what the truth was at the time."""

    at: int
    served_by: str
    value: object
    truth: object
    strategy: str

    @property
    def stale(self) -> bool:
        """Whether the answer was already out of date when it was given."""
        return self.value != self.truth

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "at": self.at,
            "by": self.served_by,
            "value": self.value,
            "truth": self.truth,
            "stale": self.stale,
            "strategy": self.strategy,
        }


@dataclass
class Lease:
    """A leader's claim to serve reads alone, and when it expires.

    Held on the leader's own clock, which is the whole point and the whole risk. The expiry is
    a tick on this node's clock, and the safety argument is about a tick on somebody else's.
    """

    holder: str
    granted_at: int
    length: int = LEASE
    drift: int = 0

    def __post_init__(self) -> None:
        if not self.holder:
            raise ConfigError("a lease needs a holder")
        if self.length < 1:
            raise ConfigError(f"{self.length} is not a lease length")

    @property
    def expires_at(self) -> int:
        """When the holder stops serving, in real ticks.

        The drift is what its clock is wrong by. A leader whose clock runs slow counts fewer
        ticks than have passed, so it goes on serving after the lease it granted itself has
        really ended, and the amount it overruns by is the error. That is the dangerous
        direction and the only one modelled here; a fast clock ends the lease early, which
        costs availability and nothing else.
        """
        return self.granted_at + self.length + self.drift

    @property
    def really_expires_at(self) -> int:
        """When the lease actually ran out, measured on a clock that is right."""
        return self.granted_at + self.length

    def held_at(self, now: int) -> bool:
        """Whether the holder would serve a read at this tick."""
        return now < self.expires_at

    def sound_at(self, now: int) -> bool:
        """Whether serving at this tick was within the lease that was actually granted."""
        return now < self.really_expires_at

    @property
    def overrun(self) -> int:
        """How many ticks the holder serves past the lease it was given."""
        return max(0, self.expires_at - self.really_expires_at)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "holder": self.holder,
            "granted_at": self.granted_at,
            "length": self.length,
            "expires_at": self.expires_at,
            "really_expires_at": self.really_expires_at,
            "drift": self.drift,
        }


@dataclass
class Serving:
    """What a run of reads did under one strategy."""

    strategy: str
    reads: list[Read] = field(default_factory=list)
    messages: int = 0
    refused: int = 0
    unsound: int = 0

    @property
    def stale(self) -> int:
        """How many answers were out of date."""
        return sum(1 for one in self.reads if one.stale)

    @property
    def served(self) -> int:
        """How many reads were answered at all."""
        return len(self.reads)

    @property
    def cost(self) -> float:
        """Messages per read, which is what the strategy is trading against correctness."""
        if not self.reads:
            return 0.0
        return round(self.messages / len(self.reads), 2)

    def __bool__(self) -> bool:
        """A run is good if every answer it gave was current."""
        return self.served > 0 and self.stale == 0

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "strategy": self.strategy,
            "served": self.served,
            "stale": self.stale,
            "refused": self.refused,
            "unsound": self.unsound,
            "messages": self.messages,
            "cost": self.cost,
            "correct": bool(self),
        }


def _write_then_read(
    strategy: str,
    drift: int = 0,
    length: int = LEASE,
    reads: int = 40,
    seed: int = 2,
) -> Serving:
    """Write, strand the old leader, keep writing on the majority, and read from the old one.

    The scenario every read strategy has to survive. A leader cut off from the majority is
    deposed by an election it cannot see, and the majority carries on writing, so anything the
    old leader says about the state afterwards is out of date. The strategies differ only in
    whether they let it say anything.

    The majority has to keep writing. The first version of this stranded the leader and then
    left the cluster idle, so the old leader's answer stayed correct by accident and every
    strategy looked safe.
    """
    made = Cluster(size=5, seed=seed).settle()
    old = made.leader()
    if old is None:
        raise NoLeader("nothing settled")
    for one in range(3):
        made.propose(("set", "k", one))
    made.run(20)
    out = Serving(strategy=strategy)
    stranded = [one for one in made.members if one != old.name]
    made.partition([[old.name], stranded])
    lease = Lease(holder=old.name, granted_at=made.now, length=length, drift=drift)
    before = made.net.counts.sent
    written = 3
    for step in range(reads):
        made.tick()
        if step % 6 == 0:
            fresh = _leader_among(made, stranded)
            if fresh is not None:
                fresh.propose(("set", "k", written))
                written += 1
        current = _truth_on(made, stranded)
        if strategy == "local":
            out.reads.append(_answer(made, old, current, strategy))
        elif strategy == "lease":
            if lease.held_at(made.now):
                answer = _answer(made, old, current, strategy)
                out.reads.append(answer)
                if not lease.sound_at(made.now):
                    out.unsound += 1
            else:
                out.refused += 1
        else:
            fresh = _leader_among(made, stranded)
            if fresh is None:
                out.refused += 1
            else:
                out.reads.append(_answer(made, fresh, current, strategy))
    out.messages = made.net.counts.sent - before
    return out


def _answer(cluster: Cluster, node, truth: object, strategy: str) -> Read:
    """One read served by one node, recorded against what was actually committed."""
    return Read(
        at=cluster.now,
        served_by=node.name,
        value=_value_on(node),
        truth=truth,
        strategy=strategy,
    )


def _leader_among(cluster: Cluster, side: list[str]):
    """Whoever leads on this side, which is not the same as who the cluster thinks leads."""
    for name in side:
        node = cluster.nodes[name]
        if node.is_leader:
            return node
    return None


def _truth_on(cluster: Cluster, side: list[str]) -> object:
    """The newest committed value on the side that still has a majority."""
    best = None
    for name in side:
        node = cluster.nodes[name]
        for entry in node.log.entries:
            if entry.index <= node.commit_index and entry.command is not None:
                best = entry.command
    return best


def _value_on(node) -> object:
    """The newest committed value this node believes in."""
    best = None
    for entry in node.log.entries:
        if entry.index <= node.commit_index and entry.command is not None:
            best = entry.command
    return best


def the_local_read_is_free_and_wrong() -> dict:
    """A stranded leader answers forty reads and twenty five of them are out of date.

    The baseline. Reading from whoever believes it is the leader costs nothing and is correct
    exactly while that belief is, which after a partition is not long. The first fifteen answers
    are right because the other side has not committed anything new yet, and everything after
    that is stale.

    Worth noticing that it never notices. There is no error, no refusal and no signal of any
    kind; the reads keep succeeding and the answers keep being wrong.
    """
    made = _write_then_read("local")
    return {
        "served": made.served,
        "stale": made.stale,
        "it_answered_everything": made.refused == 0,
        "and_most_of_it_was_wrong": made.stale > made.served // 3,
        "cost": made.cost,
        "it_is_not_correct": not made,
        "and_nothing_was_refused": made.refused == 0,
    }


def a_lease_refuses_rather_than_lying() -> dict:
    """The stranded leader answers four reads and then stops, and every answer is current.

    What a lease buys. The leader serves for as long as its lease is good and then refuses,
    because it cannot renew a lease it cannot get a majority to acknowledge. The refusals are
    the point: an unavailable read is a client's problem to handle, and a stale one is not,
    because the client cannot tell.
    """
    leased = _write_then_read("lease")
    local = _write_then_read("local")
    return {
        "served": leased.served,
        "refused": leased.refused,
        "stale": leased.stale,
        "nothing_was_stale": leased.stale == 0,
        "it_is_correct": bool(leased),
        "local_served": local.served,
        "local_stale": local.stale,
        "and_the_local_read_was_not": not local,
        "it_gave_up_availability": leased.served < local.served,
        "by_this_share": round(1 - leased.served / local.served, 2),
    }


def a_lease_longer_than_an_election_timeout_serves_stale_reads() -> dict:
    """The boundary is exactly the election timeout, and one tick past it the reads go wrong.

    Sweeping the lease length puts the failure at twenty, which is the maximum election timeout
    this package ships. That is not a coincidence and it is the whole safety argument: the lease
    is sound only while no other leader can have been elected, and the earliest that can happen
    is one election timeout after the last contact.

    Below the boundary every read is current. At it, four are stale. Well past it, most of them
    are. There is no gentle degradation, because the thing that changes at the boundary is
    whether somebody else is allowed to have been elected.
    """
    out = {}
    for length in (5, 10, 15, 20, 25, 40):
        made = _write_then_read("lease", length=length)
        out[length] = {"served": made.served, "stale": made.stale}
    boundary = min((length for length, one in out.items() if one["stale"]), default=0)
    return {
        "lengths": sorted(out),
        "results": out,
        "the_short_leases_are_clean": all(out[length]["stale"] == 0 for length in (5, 10, 15)),
        "the_long_ones_are_not": all(out[length]["stale"] > 0 for length in (25, 40)),
        "boundary": boundary,
        "max_election_timeout": MIN_ELECTION_TIMEOUT * 2,
        "and_it_is_the_election_timeout": boundary == MIN_ELECTION_TIMEOUT * 2,
        "shipped_lease": LEASE,
        "which_leaves_this_much_margin": MIN_ELECTION_TIMEOUT * 2 - LEASE,
    }


def a_clock_error_below_the_margin_is_invisible_and_above_it_is_not() -> dict:
    """Four ticks of drift serves four reads it should not have and none of them is wrong.

    The measurement the module was built for. A leader whose clock runs slow keeps serving after
    its lease has really ended, and the number of reads it serves outside the lease is exactly
    the drift. Whether any of them is wrong is a different question, and the answer is no until
    the overrun reaches the point where somebody else could have been elected and committed.

    So a clock error smaller than the margin produces no incorrect answers at all, which is the
    uncomfortable part. The system is already unsafe by its own argument and there is nothing to
    measure, no error and no stale value, until the drift grows past the margin and the wrong
    answers begin.
    """
    out = {}
    for drift in (0, 4, 8, 12):
        made = _write_then_read("lease", length=10, drift=drift)
        out[drift] = {"served": made.served, "unsound": made.unsound, "stale": made.stale}
    return {
        "drifts": sorted(out),
        "results": out,
        "the_unsound_count_is_the_drift": all(
            one["unsound"] == drift for drift, one in out.items()
        ),
        "no_drift_is_clean": out[0]["unsound"] == 0 and out[0]["stale"] == 0,
        "a_small_drift_is_unsound_and_not_wrong": (
            out[4]["unsound"] > 0 and out[4]["stale"] == 0
        ),
        "a_large_drift_is_both": out[12]["unsound"] > 0 and out[12]["stale"] > 0,
        "the_damage_starts_at": min(
            (drift for drift, one in out.items() if one["stale"]), default=0
        ),
        "and_the_exposure_starts_earlier": True,
    }


def the_read_through_the_log_is_correct_and_only_available_with_a_leader() -> dict:
    """Twenty nine current answers and eleven refusals, and the refusals are the election.

    The strategy that needs no clock assumption at all. The read is answered by whoever the
    majority has elected, so it is current by the same argument that makes a write current, and
    it is unavailable exactly while there is no leader.

    Against the lease it serves far more reads, because the lease cannot be renewed on the
    stranded side and there is nothing to renew it against. Against the local read it serves
    fewer and none of them is wrong. The three strategies are not three points on a line; they
    are three different answers to what should happen when the truth is unavailable.
    """
    through = _write_then_read("through")
    leased = _write_then_read("lease")
    local = _write_then_read("local")
    return {
        "served": through.served,
        "refused": through.refused,
        "stale": through.stale,
        "it_is_correct": bool(through),
        "and_it_serves_more_than_the_lease": through.served > leased.served,
        "but_fewer_than_the_local_read": through.served < local.served,
        "local_stale": local.stale,
        "and_the_local_read_is_the_only_wrong_one": (
            local.stale > 0 and through.stale == 0 and leased.stale == 0
        ),
        "it_needs_no_clock_assumption": True,
    }


def a_lease_without_a_holder_is_refused() -> bool:
    """A lease belongs to somebody."""
    try:
        Lease(holder="", granted_at=0)
    except ConfigError:
        return True
    return False


def a_lease_of_no_length_is_refused() -> bool:
    """A lease that expires when it is granted is refused."""
    try:
        Lease(holder="n0", granted_at=0, length=0)
    except ConfigError:
        return True
    return False


def compare_the_strategies() -> list[dict]:
    """The four read strategies over the same partition.

    The drifted row uses eighteen ticks of clock error rather than a smaller one, because the
    shipped lease of five leaves a margin of fifteen and anything inside that is absorbed. That
    is the margin doing its job, and it is why the row has to be pushed past it to show
    anything.
    """
    drifted = _write_then_read("lease", length=LEASE, drift=18).as_dict()
    drifted["strategy"] = "lease with a wrong clock"
    return [
        _write_then_read("local").as_dict(),
        _write_then_read("lease").as_dict(),
        _write_then_read("through").as_dict(),
        drifted,
    ]


def only_the_lease_is_free_and_it_is_the_only_one_that_needs_a_clock() -> dict:
    """The correct and cheap option is the one that assumes something the rest of Raft does not.

    The table, and the trade it describes. Reading locally costs nothing and is wrong. Reading
    through the log costs a round trip and is right. The lease costs nothing after the heartbeat
    that granted it and is right, on one condition that appears nowhere else in the algorithm:
    that the leader's clock and the followers' clocks agree to within the margin.

    Everywhere else Raft uses time only to decide when to give up. A node that times out early
    causes an unnecessary election and nothing worse; a node that times out late is slow and
    nothing worse. The lease is the single place where a clock decides what is true, and the
    drift measurement above is what that costs when the assumption does not hold.
    """
    table = {one["strategy"]: one for one in compare_the_strategies()}
    correct = [one for one in table.values() if one["correct"]]
    return {
        "strategies": sorted({one["strategy"] for one in table.values()}),
        "rows": len(compare_the_strategies()),
        "correct_strategies": len(correct),
        "the_local_read_is_wrong": not table["local"]["correct"],
        "the_lease_is_right": table["lease"]["correct"],
        "and_a_wrong_clock_makes_it_wrong": not table["lease with a wrong clock"]["correct"],
        "the_drift_it_took": 18,
        "against_a_margin_of": MIN_ELECTION_TIMEOUT * 2 - LEASE,
        "lease_length": LEASE,
        "min_timeout": MIN_ELECTION_TIMEOUT,
        "heartbeat": HEARTBEAT_INTERVAL,
        "the_lease_is_shorter_than_the_timeout": LEASE < MIN_ELECTION_TIMEOUT,
        "and_longer_than_a_heartbeat": LEASE > HEARTBEAT_INTERVAL,
        "so_it_can_be_renewed_before_it_lapses": LEASE > HEARTBEAT_INTERVAL,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    boundary = a_lease_longer_than_an_election_timeout_serves_stale_reads()
    drifted = a_clock_error_below_the_margin_is_invisible_and_above_it_is_not()
    return {
        "lease": LEASE,
        "min_timeout": MIN_ELECTION_TIMEOUT,
        "the_local_read_is_wrong": the_local_read_is_free_and_wrong()["it_is_not_correct"],
        "the_lease_refuses_instead": a_lease_refuses_rather_than_lying()["nothing_was_stale"],
        "the_boundary_is_the_election_timeout": boundary["and_it_is_the_election_timeout"],
        "the_margin": boundary["which_leaves_this_much_margin"],
        "the_unsound_count_is_the_drift": drifted["the_unsound_count_is_the_drift"],
        "and_a_small_drift_shows_nothing": drifted["a_small_drift_is_unsound_and_not_wrong"],
        "the_damage_starts_at": drifted["the_damage_starts_at"],
        "reading_through_the_log_needs_no_clock": (
            the_read_through_the_log_is_correct_and_only_available_with_a_leader()[
                "it_needs_no_clock_assumption"
            ]
        ),
    }
