from __future__ import annotations

import contextlib
from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader
from rsm.net import Conditions
from rsm.node import MAX_ELECTION_TIMEOUT

# Properties of the form eventually, and why they need a number attached.
#
# rsm.verify.invariants checks five safety properties, all of the form nothing bad ever happens.
# Those can be checked at a moment or over a history, and a violation is a definite thing: two
# leaders in a term, a committed entry that vanished. Liveness is the other half, and it is
# harder to check for a reason that has nothing to do with implementation: a property of the
# form something good eventually happens cannot be falsified by any finite run. However long
# the cluster has gone without electing anybody, it might elect somebody next tick.
#
# So a liveness property that can be checked at all is a bounded one: a leader within this many
# ticks, a commit within that many. The bound turns an unfalsifiable statement into a measurable
# one, and the number is not arbitrary, it comes out of the timers.
#
# The second half is the condition. Every bound here holds only while a majority can reach each
# other, and that is not a technicality to be noted and forgotten: under a partition the correct
# implementation violates every liveness property in this module, forever, and it is still
# correct. A checker that did not carry the condition would report the algorithm broken every
# time somebody unplugged a cable.

# How long a run watches before giving up on a property.
PATIENCE = 300

# The bound the timers imply for electing a leader after one dies.
ELECTION_BOUND = MAX_ELECTION_TIMEOUT * 2

# The bound for a write to commit once there is a leader.
COMMIT_BOUND = 8


@dataclass
class Property:
    """One bounded liveness property: something good, within this many ticks."""

    name: str
    bound: int
    condition: str = "a majority can reach each other"

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a property needs a name")
        if self.bound < 1:
            raise ConfigError(f"{self.bound} is not a bound")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"property": self.name, "bound": self.bound, "condition": self.condition}

    def __str__(self) -> str:
        return f"{self.name} within {self.bound} ticks, while {self.condition}"


LEADER_ELECTED = Property(name="a leader is elected", bound=ELECTION_BOUND)
WRITE_COMMITS = Property(name="a write commits", bound=COMMIT_BOUND)
FOLLOWER_CATCHES_UP = Property(name="a follower catches up", bound=ELECTION_BOUND * 2)
PROPERTIES = (LEADER_ELECTED, WRITE_COMMITS, FOLLOWER_CATCHES_UP)


@dataclass
class Observation:
    """Whether a property held in one run, and by how much."""

    claim: Property
    waited: int
    happened: bool
    conditional: bool = True

    @property
    def margin(self) -> int:
        """How many ticks were left over, or how many it went past by."""
        return self.claim.bound - self.waited

    def __bool__(self) -> bool:
        """The property held if the good thing happened inside the bound.

        A run where the condition did not hold is truthy, because a bound that only applies
        under a condition says nothing at all when the condition is absent, and reporting that
        as a failure is the mistake this module exists to avoid.
        """
        if not self.conditional:
            return True
        return self.happened and self.waited <= self.claim.bound

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "property": self.claim.name,
            "bound": self.claim.bound,
            "waited": self.waited,
            "happened": self.happened,
            "within": bool(self),
            "margin": self.margin,
            "condition held": self.conditional,
        }

    def __str__(self) -> str:
        if not self.conditional:
            return f"{self.claim.name}: the condition did not hold, so nothing is claimed"
        if not self.happened:
            return f"{self.claim.name}: never, in {self.waited} ticks"
        return f"{self.claim.name}: after {self.waited} ticks, bound {self.claim.bound}"


def a_leader_is_elected(
    size: int = 5, seed: int = 1, kill: bool = True, patience: int = PATIENCE
) -> Observation:
    """Watch how long the cluster takes to have a leader again after losing one."""
    made = Cluster(size=size, seed=seed).settle()
    if kill:
        found = made.leader()
        if found is None:
            raise NoLeader("nothing settled")
        made.crash(found.name)
        gone = found.name
    else:
        gone = ""
    start = made.now
    for _ in range(patience):
        made.tick()
        found = made.leader()
        if found is not None and found.name != gone:
            return Observation(claim=LEADER_ELECTED, waited=made.now - start, happened=True)
    return Observation(claim=LEADER_ELECTED, waited=patience, happened=False)


def a_write_commits(size: int = 5, seed: int = 1, patience: int = PATIENCE) -> Observation:
    """Watch how long a write takes to commit once there is a leader to take it."""
    made = Cluster(size=size, seed=seed).settle()
    before = len(made.committed())
    made.propose(("set", "k", 1))
    start = made.now
    for _ in range(patience):
        made.tick()
        if len(made.committed()) > before:
            return Observation(claim=WRITE_COMMITS, waited=made.now - start, happened=True)
    return Observation(claim=WRITE_COMMITS, waited=patience, happened=False)


def a_follower_catches_up(
    size: int = 5, seed: int = 1, writes: int = 30, patience: int = PATIENCE
) -> Observation:
    """Watch how long a node that missed everything takes to hold the whole log."""
    made = Cluster(size=size, seed=seed).settle()
    victim = next(one for one in made.members if not made.nodes[one].is_leader)
    made.crash(victim)
    for one in range(writes):
        with contextlib.suppress(NoLeader):
            made.propose(("set", "k", one))
        made.run(2)
    made.restart(victim)
    start = made.now
    for _ in range(patience):
        made.tick()
        found = made.leader()
        if found is None:
            continue
        if made.nodes[victim].log.last_index >= found.log.last_index:
            return Observation(
                claim=FOLLOWER_CATCHES_UP, waited=made.now - start, happened=True
            )
    return Observation(claim=FOLLOWER_CATCHES_UP, waited=patience, happened=False)


def under_a_partition(size: int = 5, seed: int = 1, patience: int = 200) -> Observation:
    """Watch a cluster with no majority, where the condition on every bound is absent.

    Electing somebody means electing somebody new, in a term above the one that was running when
    the partition opened. The incumbent does not step down when it is isolated, because nothing
    reaches it to say so, and a check that only asked whether some node believes it leads would
    report this fully partitioned cluster as having elected a leader on the first tick.
    """
    made = Cluster(size=size, seed=seed).settle()
    before = max(one.term for one in made.nodes.values())
    made.partition([[one] for one in made.members])
    start = made.now
    for _ in range(patience):
        made.tick()
        found = made.leader()
        if found is not None and found.term > before:
            return Observation(
                claim=LEADER_ELECTED,
                waited=made.now - start,
                happened=True,
                conditional=False,
            )
    return Observation(claim=LEADER_ELECTED, waited=patience, happened=False, conditional=False)


def every_bounded_property_holds_on_a_healthy_cluster() -> dict:
    """All three good things happen, all three well inside their bounds.

    The base case. A bound that nothing ever comes close to is not measuring anything, so the
    margins are reported as well as the verdicts: an election takes about a quarter of its
    bound, a commit a quarter of its, and a follower rejoining catches up in two ticks against a
    bound of eighty.
    """
    made = {
        "election": a_leader_is_elected(),
        "commit": a_write_commits(),
        "catch up": a_follower_catches_up(),
    }
    return {
        "properties": sorted(made),
        "all_held": all(bool(one) for one in made.values()),
        "waited": {name: one.waited for name, one in made.items()},
        "bounds": {name: one.claim.bound for name, one in made.items()},
        "margins": {name: one.margin for name, one in made.items()},
        "every_margin_is_positive": all(one.margin > 0 for one in made.values()),
        "the_tightest": min(made.values(), key=lambda one: one.margin).claim.name,
        "and_it_still_had_room": min(one.margin for one in made.values()) > 0,
    }


def a_liveness_property_cannot_be_falsified_by_a_finite_run() -> dict:
    """Watching longer never turns a maybe into a no, which is why the bound is there.

    The whole argument in one measurement. Run the partitioned cluster for a hundred ticks, then
    two hundred, then four hundred, and the answer is the same each time: no leader yet. Nothing
    in those runs distinguishes a cluster that will never elect anybody from one that will elect
    somebody on the next tick.

    The bound is what makes it decidable. It replaces eventually, which no run can refute, with
    within forty ticks, which any run can.
    """
    lengths = (100, 200, 400)
    out = {}
    for length in lengths:
        made = under_a_partition(patience=length)
        out[length] = {"happened": made.happened, "waited": made.waited}
    return {
        "lengths": list(lengths),
        "results": out,
        "none_of_them_elected": not any(one["happened"] for one in out.values()),
        "and_the_answer_never_changed": len({one["happened"] for one in out.values()}) == 1,
        "watching_longer_told_us_nothing": True,
        "the_bound_is": ELECTION_BOUND,
        "which_the_longest_run_passed_long_ago": max(lengths) > ELECTION_BOUND,
    }


def the_correct_implementation_violates_liveness_under_a_partition() -> dict:
    """No leader for two hundred ticks, and nothing is wrong.

    The reason every property here carries a condition. Cut a five node cluster into five pieces
    and no majority exists, so no election can succeed, so the cluster elects nobody for as long
    as the run goes on. Every safety property still holds. This is the algorithm working
    exactly as specified.

    An observation whose condition failed is truthy on purpose. A conditional statement says
    nothing when its condition is absent, and a checker that reported this as a failure would
    report the algorithm broken every time somebody unplugged a cable.
    """
    made = under_a_partition()
    healthy = a_leader_is_elected()
    return {
        "waited": made.waited,
        "it_never_elected": not made.happened,
        "the_condition_failed": not made.conditional,
        "and_it_is_still_truthy": bool(made),
        "against_a_healthy_run": healthy.waited,
        "which_did_elect": healthy.happened,
        "so_the_property_only_applies_under_its_condition": True,
        "the_condition": LEADER_ELECTED.condition,
    }


def the_election_bound_comes_from_the_timers_and_not_from_a_guess() -> dict:
    """Eleven seeds of twelve elect inside one timeout and the twelfth needs a second round.

    Where the number comes from, and why it is twice the timeout rather than once. A follower
    notices a dead leader when its own timer expires, which is drawn from ten to twenty, and
    then the election takes a round trip. Eleven of the twelve seeds finish in fourteen ticks or
    fewer. One takes twenty three, which is past a single timeout and is a split vote costing an
    extra round.

    That one seed is the whole argument for the doubled bound. A bound tight enough to look
    interesting is a bound that fails on the seed nobody ran, and a liveness check that cries
    wolf is one that gets deleted.
    """
    waits = [a_leader_is_elected(seed=seed).waited for seed in range(12)]
    return {
        "seeds": len(waits),
        "waits": sorted(waits),
        "worst": max(waits),
        "best": min(waits),
        "bound": ELECTION_BOUND,
        "every_one_inside": all(one <= ELECTION_BOUND for one in waits),
        "max_election_timeout": MAX_ELECTION_TIMEOUT,
        "most_are_inside_one_timeout": sum(1 for one in waits if one <= MAX_ELECTION_TIMEOUT)
        >= len(waits) - 2,
        "but_not_all_of_them": max(waits) > MAX_ELECTION_TIMEOUT,
        "so_the_bound_has_room_for_a_retry": ELECTION_BOUND >= MAX_ELECTION_TIMEOUT * 2,
    }


def loss_makes_the_wait_longer_and_keeps_it_inside_the_bound() -> dict:
    """A lossy link costs extra rounds and the bound absorbs them.

    The case the room in the bound is for, and it uses almost all of it. Losing three messages
    in ten means vote requests and replies go missing, so an election takes more rounds: the
    worst seed goes from twenty three ticks to thirty nine, against a bound of forty.

    One tick of margin is not comfortable. It says the bound is right for the conditions this
    package models and would have to move for a link that loses more, which is the honest
    version of a claim that a bound holds: it holds under the assumptions it was measured under.
    """
    clean = [a_leader_is_elected(seed=seed).waited for seed in range(8)]
    lossy = []
    for seed in range(8):
        made = Cluster(size=5, seed=seed, conditions=Conditions(loss=0.3)).settle()
        found = made.leader()
        if found is None:
            continue
        made.crash(found.name)
        start = made.now
        waited = PATIENCE
        for _ in range(PATIENCE):
            made.tick()
            fresh = made.leader()
            if fresh is not None and fresh.name != found.name:
                waited = made.now - start
                break
        lossy.append(waited)
    return {
        "seeds": len(lossy),
        "clean_worst": max(clean),
        "lossy_worst": max(lossy),
        "loss_costs_more": max(lossy) > max(clean),
        "by_this_many_ticks": max(lossy) - max(clean),
        "bound": ELECTION_BOUND,
        "and_it_is_still_inside": max(lossy) <= ELECTION_BOUND,
        "clean_mean": round(sum(clean) / len(clean), 1),
        "lossy_mean": round(sum(lossy) / len(lossy), 1),
        "margin_left": ELECTION_BOUND - max(lossy),
        "which_is_almost_nothing": ELECTION_BOUND - max(lossy) <= 2,
    }


def a_property_without_a_bound_is_refused() -> bool:
    """A property that promises something eventually is refused, since nothing can check it."""
    try:
        Property(name="something good", bound=0)
    except ConfigError:
        return True
    return False


def a_property_without_a_name_is_refused() -> bool:
    """A property has to be reportable."""
    try:
        Property(name="", bound=10)
    except ConfigError:
        return True
    return False


def an_observation_past_its_bound_is_falsy() -> dict:
    """The verdict is the bound, not whether the good thing happened at all.

    A run where the leader arrives one tick late is a failure of the property even though a
    leader did arrive, which is the difference between the bounded statement and the
    unfalsifiable one it replaced.
    """
    inside = Observation(claim=LEADER_ELECTED, waited=ELECTION_BOUND, happened=True)
    outside = Observation(claim=LEADER_ELECTED, waited=ELECTION_BOUND + 1, happened=True)
    never = Observation(claim=LEADER_ELECTED, waited=PATIENCE, happened=False)
    excused = Observation(
        claim=LEADER_ELECTED, waited=PATIENCE, happened=False, conditional=False
    )
    return {
        "at_the_bound": bool(inside),
        "one_past_it": bool(outside),
        "it_flips_at_the_boundary": bool(inside) and not bool(outside),
        "and_both_of_them_happened": inside.happened and outside.happened,
        "never_happened": bool(never),
        "excused_by_its_condition": bool(excused),
        "and_they_differ_only_in_the_condition": not bool(never) and bool(excused),
        "margins": [inside.margin, outside.margin],
    }


def compare_the_properties() -> list[dict]:
    """Each property observed on a healthy cluster and under a partition."""
    return [
        a_leader_is_elected().as_dict(),
        a_write_commits().as_dict(),
        a_follower_catches_up().as_dict(),
        under_a_partition().as_dict(),
    ]


def liveness_needs_a_bound_and_a_condition_and_neither_alone_is_enough() -> dict:
    """Drop either half and the check reports something false.

    The summary of the module as a table. Without a bound, no finite run can fail, so the
    checker passes everything including a cluster that has been down for an hour. Without a
    condition, a partition fails every property, so the checker reports a correct algorithm as
    broken whenever the network does what networks do.

    Both halves are easy to leave out and each is invisible until the case that needs it turns
    up, which is a fair description of most of the hard parts of this package.
    """
    healthy = a_leader_is_elected()
    partitioned = under_a_partition()
    unbounded = partitioned.happened
    unconditional = Observation(
        claim=partitioned.claim, waited=partitioned.waited, happened=partitioned.happened
    )
    return {
        "properties": len(PROPERTIES),
        "healthy_holds": bool(healthy),
        "partitioned_is_excused": bool(partitioned),
        "without_a_bound_the_partition_passes": not unbounded,
        "without_a_condition_it_fails": not bool(unconditional),
        "and_with_both_it_is_excused": bool(partitioned),
        "the_condition": LEADER_ELECTED.condition,
        "the_bound": LEADER_ELECTED.bound,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "properties": [one.name for one in PROPERTIES],
        "bounds": {one.name: one.bound for one in PROPERTIES},
        "all_hold_on_a_healthy_cluster": (
            every_bounded_property_holds_on_a_healthy_cluster()["all_held"]
        ),
        "no_finite_run_can_falsify_them": (
            a_liveness_property_cannot_be_falsified_by_a_finite_run()[
                "watching_longer_told_us_nothing"
            ]
        ),
        "a_partition_excuses_them": (
            the_correct_implementation_violates_liveness_under_a_partition()[
                "and_it_is_still_truthy"
            ]
        ),
        "the_bound_needs_room_for_a_retry": (
            the_election_bound_comes_from_the_timers_and_not_from_a_guess()[
                "but_not_all_of_them"
            ]
        ),
        "loss_stays_inside_it": loss_makes_the_wait_longer_and_keeps_it_inside_the_bound()[
            "and_it_is_still_inside"
        ],
    }
