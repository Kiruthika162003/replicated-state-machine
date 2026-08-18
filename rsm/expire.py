from __future__ import annotations

from dataclasses import dataclass, field

from rsm.errors import ConfigError

# Keys that go away on their own, and the only safe way to arrange it.
#
# A key with a lifetime is a thing every coordination service offers: a lock that releases if
# the holder dies, a registration that lapses, a cache entry. The obvious implementation stores
# an expiry time with the value and has each node drop the key once its own clock passes it.
#
# That is a state machine that reads a clock, which rsm.machine already measured as the way to
# make replicas disagree while every safety property still holds. Every node applies the same
# entries in the same order and reaches a different state, because the state is a function of
# the entries and of the moment each node happened to look.
#
# The safe arrangement is to make the expiry an entry. The leader notices that a lease is up and
# proposes a delete, which every node applies at the same position in the log, so the key
# disappears at the same place in the order everywhere. The cost is an entry per expiry, and for
# short lived keys that can be more entries than the writes that created them.
#
# What is measured: how far the replicas drift under the clock version, that the log version
# does not drift at all, and what the log version costs in entries and in the delay between a
# lease ending and the key going.

# How long a lease lasts, in ticks.
LEASE = 30

# How often the leader looks for expired leases.
SWEEP = 10


@dataclass
class Lease:
    """One key with a lifetime, and the tick it was granted at."""

    key: str
    value: object
    granted_at: int
    length: int = LEASE

    def __post_init__(self) -> None:
        if not self.key:
            raise ConfigError("a lease needs a key")
        if self.length < 1:
            raise ConfigError(f"{self.length} is not a lease length")
        if self.granted_at < 0:
            raise ConfigError(f"{self.granted_at} is not a tick")

    @property
    def expires_at(self) -> int:
        """When the lease runs out, on whatever clock granted it."""
        return self.granted_at + self.length

    def expired(self, now: int) -> bool:
        """Whether this lease has run out by the given tick."""
        return now >= self.expires_at

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "key": self.key,
            "value": self.value,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
        }


@dataclass
class Store:
    """A replica's view of the leased keys, expired either by a clock or by the log."""

    name: str
    by_clock: bool = False
    leases: dict[str, Lease] = field(default_factory=dict)
    now: int = 0
    swept: int = 0

    def grant(self, lease: Lease) -> None:
        """Take a lease, which every replica does when it applies the entry."""
        self.leases[lease.key] = lease

    def revoke(self, key: str) -> bool:
        """Drop a lease because the log said so."""
        return self.leases.pop(key, None) is not None

    def tick(self, now: int) -> None:
        """Advance this replica's clock, dropping expired leases if it is the clock version."""
        self.now = now
        if not self.by_clock:
            return
        going = [key for key, one in self.leases.items() if one.expired(now)]
        for key in going:
            del self.leases[key]
            self.swept += 1

    def keys(self) -> tuple[str, ...]:
        """What this replica currently holds, which is what two replicas are compared on."""
        return tuple(sorted(self.leases))

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "replica": self.name,
            "by_clock": self.by_clock,
            "keys": len(self.leases),
            "swept": self.swept,
            "now": self.now,
        }


@dataclass
class Sweep:
    """What a run of leases did across the replicas."""

    name: str
    granted: int = 0
    revoked: int = 0
    entries: int = 0
    ticks: int = 0
    divergences: int = 0
    worst_difference: int = 0
    delays: list[int] = field(default_factory=list)

    @property
    def agreed(self) -> bool:
        """Whether the replicas held the same keys at every tick."""
        return self.divergences == 0

    @property
    def cost(self) -> float:
        """Log entries per lease, which is what the safe version charges."""
        if self.granted == 0:
            return 0.0
        return round(self.entries / self.granted, 2)

    @property
    def worst_delay(self) -> int:
        """The longest a key outlived its lease before the log caught up."""
        return max(self.delays, default=0)

    def __bool__(self) -> bool:
        """A run is correct if the replicas never disagreed."""
        return self.agreed

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "run": self.name,
            "granted": self.granted,
            "revoked": self.revoked,
            "entries": self.entries,
            "cost": self.cost,
            "divergences": self.divergences,
            "worst_difference": self.worst_difference,
            "worst_delay": self.worst_delay,
            "agreed": self.agreed,
        }


def run(
    name: str,
    by_clock: bool,
    replicas: int = 3,
    leases: int = 12,
    every: int = 12,
    skew: int = 4,
    window: int = 300,
    sweep: int = SWEEP,
) -> Sweep:
    """Grant leases and let them lapse, either by each replica's clock or by the log.

    The replicas' clocks are deliberately skewed, one tick further off per replica, because a
    clock version that is only wrong when the clocks are wrong is a version whose correctness is
    a claim about the operator's infrastructure rather than about the algorithm.
    """
    if replicas < 2:
        raise ConfigError(f"{replicas} is not enough replicas to compare")
    if leases < 1:
        raise ConfigError(f"{leases} is not a lease count")
    stores = [Store(name=f"r{one}", by_clock=by_clock) for one in range(replicas)]
    made = Sweep(name=name)
    pending: dict[str, Lease] = {}
    for tick in range(1, window + 1):
        if tick % every == 0 and made.granted < leases:
            made.granted += 1
            made.entries += 1
            lease = Lease(key=f"k{made.granted}", value=made.granted, granted_at=tick)
            pending[lease.key] = lease
            for store in stores:
                store.grant(lease)
        if not by_clock and tick % sweep == 0:
            for key, lease in list(pending.items()):
                if lease.expired(tick):
                    made.entries += 1
                    made.revoked += 1
                    made.delays.append(tick - lease.expires_at)
                    del pending[key]
                    for store in stores:
                        store.revoke(key)
        for index, store in enumerate(stores):
            store.tick(tick + index * skew if by_clock else tick)
        if by_clock:
            for key in list(pending):
                if all(key not in store.leases for store in stores):
                    made.revoked += 1
                    del pending[key]
        seen = {store.keys() for store in stores}
        if len(seen) > 1:
            made.divergences += 1
            sizes = [len(store.leases) for store in stores]
            made.worst_difference = max(made.worst_difference, max(sizes) - min(sizes))
        made.ticks += 1
    return made


def expiring_on_each_replicas_clock_makes_them_disagree() -> dict:
    """Ninety six ticks out of three hundred with the replicas holding different keys.

    The obvious implementation, failing in the way rsm.machine predicted. Every replica applied
    exactly the same entries in exactly the same order, and their states differ, because the
    state also depends on when each of them looked at its own clock.

    Nothing here is a consensus failure. The log is identical on every replica throughout, every
    safety property holds, and the cluster would pass every check in rsm.verify.invariants. What
    is broken is the assumption underneath all of them, which is that applying the same log
    gives the same state.
    """
    made = run("clock", by_clock=True)
    return {
        "ticks": made.ticks,
        "divergences": made.divergences,
        "they_disagreed": not made.agreed,
        "share_of_the_run": round(made.divergences / made.ticks, 3),
        "worst_difference": made.worst_difference,
        "entries": made.entries,
        "cost_per_lease": made.cost,
        "and_it_is_one_entry_per_lease": made.cost == 1.0,
        "granted": made.granted,
        "revoked": made.revoked,
    }


def expiring_through_the_log_never_diverges_and_costs_double() -> dict:
    """Zero divergences, two entries per lease instead of one.

    The safe arrangement. The leader notices a lease is up and proposes a delete, which every
    replica applies at the same position, so the key goes at the same place in the order
    everywhere. The states are identical at every tick of the run.

    The price is exact and easy to state: the grant is one entry and the revoke is another, so a
    workload of short lived keys writes twice the log it looks like it is writing. For a lock
    service where every lock is taken and released that is the whole story of the log.
    """
    clock = run("clock", by_clock=True)
    log = run("log", by_clock=False)
    return {
        "clock_divergences": clock.divergences,
        "log_divergences": log.divergences,
        "the_log_version_agreed": log.agreed,
        "and_the_clock_version_did_not": not clock.agreed,
        "clock_entries": clock.entries,
        "log_entries": log.entries,
        "it_costs_double": log.entries == clock.entries * 2,
        "cost_per_lease": log.cost,
        "granted": log.granted,
        "revoked": log.revoked,
        "and_everything_granted_was_revoked": log.granted == log.revoked,
    }


def the_log_version_keeps_a_key_past_its_lease() -> dict:
    """A key can outlive its lease by most of a sweep interval, and every replica agrees on it.

    What the safe version gives up. The leader looks for expired leases every ten ticks, so a
    lease that lapses one tick after a sweep waits nine ticks for the next one. The measured
    worst is eight.

    That is a delay rather than an error, and the distinction is the whole point: every replica
    holds the key for exactly the same stretch, so a client that asks any of them gets the same
    answer. The clock version has no delay and no agreement, which is the wrong trade for
    anything that a lock is protecting.
    """
    made = run("log", by_clock=False)
    return {
        "sweep": SWEEP,
        "worst_delay": made.worst_delay,
        "it_is_under_a_sweep": made.worst_delay < SWEEP,
        "delays": sorted(set(made.delays)),
        "and_every_replica_agreed_throughout": made.agreed,
        "divergences": made.divergences,
        "so_the_delay_is_shared": True,
    }


def a_shorter_sweep_costs_nothing_extra_and_shortens_the_delay() -> dict:
    """Sweeping every two ticks instead of ten cuts the worst delay and writes the same entries.

    The sweep interval turns out to be nearly free, because the entries are one per expiry
    however often the leader looks. Looking more often finds each expiry sooner and finds the
    same number of them.

    What it costs is the sweep itself, which is work on the leader rather than traffic, and this
    model does not charge for that. Worth saying, because a measurement that shows a knob as
    free usually means the cost is somewhere the model is not looking.
    """
    out = {}
    for sweep in (2, 5, 10, 20):
        made = _with_sweep(sweep)
        out[sweep] = made
    return {
        "sweeps": sorted(out),
        "worst_delay": {one: made.worst_delay for one, made in out.items()},
        "a_shorter_sweep_is_quicker": out[2].worst_delay < out[20].worst_delay,
        "entries": {one: made.entries for one, made in out.items()},
        "and_costs_the_same_entries": len({one.entries for one in out.values()}) == 1,
        "every_one_agreed": all(one.agreed for one in out.values()),
        "and_the_model_does_not_charge_for_the_sweep": True,
    }


def _with_sweep(sweep: int) -> Sweep:
    """One log driven run at a given sweep interval."""
    return run(f"sweep {sweep}", by_clock=False, sweep=sweep)


def a_lease_without_a_key_is_refused() -> bool:
    """A lease has to be on something."""
    try:
        Lease(key="", value=1, granted_at=0)
    except ConfigError:
        return True
    return False


def a_lease_of_no_length_is_refused() -> bool:
    """A lease that ends when it starts is refused."""
    try:
        Lease(key="k", value=1, granted_at=0, length=0)
    except ConfigError:
        return True
    return False


def a_run_with_one_replica_is_refused() -> bool:
    """Divergence needs two replicas to be a comparison at all."""
    try:
        run("x", by_clock=True, replicas=1)
    except ConfigError:
        return True
    return False


def a_run_with_no_leases_is_refused() -> bool:
    """A run that grants nothing measures nothing."""
    try:
        run("x", by_clock=True, leases=0)
    except ConfigError:
        return True
    return False


def clocks_that_agree_hide_the_problem_entirely() -> dict:
    """With no skew the clock version looks perfect, which is why it ships.

    The reason this mistake is common. Set every replica's clock to the same value and the clock
    version diverges not at all: the keys go at the same tick everywhere because the ticks are
    the same everywhere. Every test passes.

    The skew is not exotic. One tick per replica is a few milliseconds in anything real, and it
    is enough to put a third of the run into disagreement.
    """
    aligned = run("aligned", by_clock=True, skew=0)
    skewed = run("skewed", by_clock=True, skew=4)
    return {
        "aligned_divergences": aligned.divergences,
        "it_looks_perfect": aligned.agreed,
        "skewed_divergences": skewed.divergences,
        "and_a_small_skew_breaks_it": not skewed.agreed,
        "skew": 4,
        "share_of_the_run": round(skewed.divergences / skewed.ticks, 3),
        "so_the_correctness_was_a_claim_about_the_clocks": True,
    }


def compare_the_arrangements() -> list[dict]:
    """Both arrangements, with and without clock skew."""
    return [
        run("clock, aligned", by_clock=True, skew=0).as_dict(),
        run("clock, skewed", by_clock=True, skew=4).as_dict(),
        run("log, aligned", by_clock=False, skew=0).as_dict(),
        run("log, skewed", by_clock=False, skew=4).as_dict(),
    ]


def only_the_log_version_is_correct_under_both_clocks() -> dict:
    """Three of four rows agree and the one that does not is the one that will ship.

    The table. The log version agrees whatever the clocks do, because it never asks them. The
    clock version agrees exactly when the clocks do, which is the condition nobody can hold.

    That the aligned clock row passes is the whole difficulty. A correctness that depends on an
    assumption nobody wrote down looks like correctness in every test that happens to satisfy
    the assumption.
    """
    table = compare_the_arrangements()
    agreed = [one["run"] for one in table if one["agreed"]]
    return {
        "rows": len(table),
        "agreed": agreed,
        "the_broken_one": [one["run"] for one in table if not one["agreed"]],
        "only_one_row_fails": len(agreed) == len(table) - 1,
        "and_it_is_the_skewed_clock": [one["run"] for one in table if not one["agreed"]]
        == ["clock, skewed"],
        "entries": {one["run"]: one["entries"] for one in table},
        "the_log_rows_cost_double": all(
            one["cost"] == 2.0 for one in table if one["run"].startswith("log")
        ),
        "and_the_clock_rows_do_not": all(
            one["cost"] == 1.0 for one in table if one["run"].startswith("clock")
        ),
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "lease": LEASE,
        "sweep": SWEEP,
        "the_clock_version_diverges": (
            expiring_on_each_replicas_clock_makes_them_disagree()["they_disagreed"]
        ),
        "the_log_version_does_not": (
            expiring_through_the_log_never_diverges_and_costs_double()["the_log_version_agreed"]
        ),
        "and_it_costs_double": expiring_through_the_log_never_diverges_and_costs_double()[
            "it_costs_double"
        ],
        "the_delay_is_under_a_sweep": the_log_version_keeps_a_key_past_its_lease()[
            "it_is_under_a_sweep"
        ],
        "a_shorter_sweep_is_free_here": (
            a_shorter_sweep_costs_nothing_extra_and_shortens_the_delay()[
                "and_costs_the_same_entries"
            ]
        ),
        "aligned_clocks_hide_it": clocks_that_agree_hide_the_problem_entirely()[
            "it_looks_perfect"
        ],
    }
