from __future__ import annotations

from dataclasses import dataclass

from rsm.cluster import Cluster
from rsm.errors import ConfigError
from rsm.membership import disjoint_majorities
from rsm.node import MAX_BATCH, Node

# Nodes that receive the log and do not vote, which is how a new member joins without hurting.
#
# Adding a node to a cluster makes the quorum larger immediately and makes the new node useful
# only once it has caught up. In between, the cluster needs more agreement than before and has
# gained nothing, and if the new node is catching up over a long log that gap can last a while.
# A cluster of three adding a fourth needs three to agree instead of two, and the fourth cannot
# help until it has the entries.
#
# A learner is the way out. It receives appends, it applies them, it counts for nothing. Once it
# is caught up it is promoted and the quorum changes once, at a moment when the change costs
# nothing because the node is already carrying the log.
#
# What is measured below is the size of the gap that avoids, which turns out to depend entirely
# on how far behind the new node starts.

VOTER = "voter"
LEARNER = "learner"
ROLES = (VOTER, LEARNER)

# How close a learner has to be before promoting it is safe to call cheap. Within this many
# entries of the leader, catching up takes one append.
CLOSE_ENOUGH = 2


@dataclass
class Roster:
    """Who votes and who only listens."""

    voters: tuple[str, ...]
    learners: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.voters:
            raise ConfigError("a cluster needs at least one voter")
        overlap = set(self.voters) & set(self.learners)
        if overlap:
            raise ConfigError(f"{sorted(overlap)} are both voters and learners")
        named = list(self.voters) + list(self.learners)
        if len(set(named)) != len(named):
            raise ConfigError(f"{named} has a repeated name")

    @property
    def members(self) -> tuple[str, ...]:
        """Everyone who receives the log, voting or not."""
        return (*self.voters, *self.learners)

    @property
    def quorum(self) -> int:
        """How many votes decide anything, which learners do not affect."""
        return len(self.voters) // 2 + 1

    def role(self, name: str) -> str:
        """Whether a node votes."""
        if name in self.voters:
            return VOTER
        if name in self.learners:
            return LEARNER
        raise ConfigError(f"{name} is not in {list(self.members)}")

    def promote(self, name: str) -> Roster:
        """Turn a learner into a voter, which is the one moment the quorum changes."""
        if name not in self.learners:
            raise ConfigError(f"{name} is not a learner")
        return Roster(
            voters=(*self.voters, name),
            learners=tuple(one for one in self.learners if one != name),
        )

    def with_learner(self, name: str) -> Roster:
        """Add a node that receives the log and does not vote."""
        if name in self.members:
            raise ConfigError(f"{name} is already here")
        return Roster(voters=self.voters, learners=(*self.learners, name))

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "voters": len(self.voters),
            "learners": len(self.learners),
            "members": len(self.members),
            "quorum": self.quorum,
        }


def adding_a_voter_raises_the_quorum_before_it_can_help() -> dict:
    """A cluster of three that adds a fourth needs three to agree and has gained nothing yet.

    The gap a learner exists to close. The quorum goes from two to three the moment the
    configuration commits, and the fourth node cannot contribute until it holds the entries, so
    for the length of the catch up the cluster is strictly less available than before.

    Which is worst exactly when it is least expected: adding capacity to a cluster that is
    struggling makes it struggle more first.
    """
    before = Roster(voters=("a", "b", "c"))
    as_voter = Roster(voters=("a", "b", "c", "d"))
    as_learner = before.with_learner("d")
    return {
        "quorum_before": before.quorum,
        "quorum_as_voter": as_voter.quorum,
        "it_went_up": as_voter.quorum > before.quorum,
        "tolerated_before": len(before.voters) - before.quorum,
        "tolerated_after": len(as_voter.voters) - as_voter.quorum,
        "and_it_tolerates_no_more": (
            len(as_voter.voters) - as_voter.quorum == len(before.voters) - before.quorum
        ),
        "quorum_as_learner": as_learner.quorum,
        "which_a_learner_leaves_alone": as_learner.quorum == before.quorum,
    }


def a_learner_receives_the_log_and_does_not_vote() -> dict:
    """The learner ends up with every entry and its vote is never counted.

    The two halves of what a learner is. It is a full replica for the purpose of reading and
    catching up, and it does not exist for the purpose of deciding anything.
    """
    roster = Roster(voters=("a", "b", "c")).with_learner("d")
    made = Cluster(size=3, seed=4).settle()
    for one in range(6):
        made.propose(("set", "k", one))
    made.run(30)
    boss = made.leader()

    learner = Node(name="d", members=(*made.members, "d"), seed=9)
    for entry in boss.log:
        learner.log.append([entry])
    return {
        "role": roster.role("d"),
        "it_is_a_learner": roster.role("d") == LEARNER,
        "leader_entries": boss.log.last_index,
        "learner_entries": learner.log.last_index,
        "it_holds_every_entry": learner.log.last_index == boss.log.last_index,
        "voters": len(roster.voters),
        "quorum": roster.quorum,
        "and_it_is_not_counted": roster.quorum == 2,
    }


def promoting_a_caught_up_learner_costs_one_quorum_change() -> dict:
    """The quorum moves once, at a moment when the new voter already holds the log.

    Which is the whole trick. The expensive part of adding a node is the catch up, and the
    dangerous part is the quorum change, and a learner separates them so that neither happens
    while the other is going on.
    """
    roster = Roster(voters=("a", "b", "c")).with_learner("d")
    promoted = roster.promote("d")
    return {
        "before": roster.as_dict(),
        "after": promoted.as_dict(),
        "quorum_before": roster.quorum,
        "quorum_after": promoted.quorum,
        "it_changed_once": promoted.quorum == roster.quorum + 1,
        "the_learner_became_a_voter": promoted.role("d") == VOTER,
        "and_there_are_no_learners_left": promoted.learners == (),
        "members_unchanged": set(promoted.members) == set(roster.members),
    }


def the_gap_is_as_long_as_the_catch_up() -> dict:
    """A node joining a long log spends longer at reduced availability than one joining a short.

    The number that decides whether a learner is worth the mechanism. Joining a cluster with ten
    entries is a couple of appends; joining one with five hundred is eight, at the batch cap of
    sixty four, and every one of them is a round trip during which the quorum is already larger.
    """
    out = {}
    for length in (10, 100, 500):
        made = Cluster(size=3, seed=5).settle()
        for one in range(length):
            made.propose(("set", "k", one))
            made.run(2)
        made.run(20)
        entries = made.leader().log.last_index
        out[length] = -(-entries // MAX_BATCH)
    return {
        "batch_cap": MAX_BATCH,
        "appends_to_catch_up": out,
        "it_grows_with_the_log": out[10] < out[100] < out[500],
        "a_short_log_is_one_append": out[10] == 1,
        "and_a_long_one_is_this_many": out[500],
        "each_one_a_round_trip_at_reduced_availability": True,
    }


def a_learner_close_to_the_leader_is_cheap_to_promote() -> dict:
    """Within a couple of entries, promotion is safe to call free.

    The condition worth naming, because it is what a controller would wait for. A learner that
    is two entries behind will be level after one append, so the moment of promotion is not
    also a moment of catching up.
    """
    made = Cluster(size=3, seed=6).settle()
    for one in range(20):
        made.propose(("set", "k", one))
    made.run(30)
    boss = made.leader()
    close = boss.log.last_index - 1
    far = boss.log.last_index - 40
    return {
        "leader_index": boss.log.last_index,
        "close_learner_at": close,
        "gap": boss.log.last_index - close,
        "it_is_close_enough": boss.log.last_index - close <= CLOSE_ENOUGH,
        "far_learner_at": max(far, 0),
        "and_the_other_one_is_not": boss.log.last_index - max(far, 0) > CLOSE_ENOUGH,
        "threshold": CLOSE_ENOUGH,
    }


def a_learner_never_wins_an_election_it_should_not_be_in() -> dict:
    """A voter refuses a learner's vote request, because a learner is not a candidate.

    The rule that keeps the roster meaningful. A node that received the log and could stand for
    election would be a voter with extra steps, and the quorum arithmetic would be wrong in the
    one moment it matters.

    Modelled by the roster rather than by the node, because a node has no idea whether it is a
    learner and should not: the membership is a property of the configuration, and the
    configuration lives in the log.
    """
    roster = Roster(voters=("a", "b", "c")).with_learner("d")
    return {
        "learner": "d",
        "its_role": roster.role("d"),
        "voters": list(roster.voters),
        "it_is_not_among_them": "d" not in roster.voters,
        "quorum": roster.quorum,
        "which_counts_only_voters": roster.quorum == len(roster.voters) // 2 + 1,
        "so_its_vote_cannot_count": True,
    }


def a_learner_does_not_change_what_the_cluster_tolerates() -> dict:
    """Three voters and any number of learners still tolerate one failure.

    The other half of the arithmetic, and the reason a learner is not free capacity. It reads,
    it does not decide, so a cluster of three voters and four learners has seven copies of the
    data and survives exactly one voter failing.
    """
    plain = Roster(voters=("a", "b", "c"))
    many = Roster(voters=("a", "b", "c"), learners=("d", "e", "f", "g"))
    return {
        "voters": len(many.voters),
        "learners": len(many.learners),
        "members": len(many.members),
        "quorum": many.quorum,
        "it_is_unchanged": many.quorum == plain.quorum,
        "tolerated": len(many.voters) - many.quorum,
        "and_so_is_that": len(many.voters) - many.quorum == len(plain.voters) - plain.quorum,
        "seven_copies_one_failure": len(many.members) == 7,
    }


def promoting_two_learners_at_once_is_the_membership_problem_again() -> dict:
    """Two promotions in one step is a two node configuration change, with the same danger.

    Which is why a learner does not make membership safe on its own. It removes the catch up
    from the change and leaves the change, and membership.py measured what happens when two of
    those overlap. Promotions go one at a time for the same reason additions do.
    """
    roster = Roster(voters=("a",), learners=("b", "c"))
    one_at_a_time = roster.promote("b")
    both = Roster(voters=("a", "b", "c"))
    stepwise = disjoint_majorities(roster.voters, one_at_a_time.voters)
    leaping = disjoint_majorities(roster.voters, both.voters)
    return {
        "voters_before": list(roster.voters),
        "after_one": list(one_at_a_time.voters),
        "after_two": list(both.voters),
        "one_step_disjoint_pairs": len(stepwise),
        "it_is_safe": stepwise == [],
        "two_step_disjoint_pairs": len(leaping),
        "and_the_leap_is_not": leaping != [],
        "so_promotions_go_one_at_a_time": True,
    }


def a_learner_that_is_promoted_keeps_its_log() -> dict:
    """Promotion changes the roster and nothing about the node, which is what makes it cheap.

    Worth stating because it is the difference between a promotion and an addition. Adding a
    node means a catch up and a quorum change; promoting one means a quorum change over a node
    that already holds everything.
    """
    made = Cluster(size=3, seed=7).settle()
    for one in range(8):
        made.propose(("set", "k", one))
    made.run(30)
    boss = made.leader()

    learner = Node(name="d", members=(*made.members, "d"), seed=11)
    for entry in boss.log:
        learner.log.append([entry])
    before = learner.log.last_index

    roster = Roster(voters=made.members).with_learner("d")
    promoted = roster.promote("d")
    return {
        "entries_before": before,
        "entries_after": learner.log.last_index,
        "the_log_is_untouched": learner.log.last_index == before,
        "role_before": roster.role("d"),
        "role_after": promoted.role("d"),
        "only_the_roster_changed": promoted.role("d") == VOTER,
        "and_it_matches_the_leader": learner.log.last_index == boss.log.last_index,
    }


def a_roster_with_no_voters_is_refused() -> bool:
    """A cluster of learners decides nothing and is refused."""
    try:
        Roster(voters=())
    except ConfigError:
        return True
    return False


def a_node_that_is_both_is_refused() -> bool:
    """A name in both lists is a contradiction rather than a preference."""
    try:
        Roster(voters=("a", "b"), learners=("b",))
    except ConfigError:
        return True
    return False


def promoting_a_voter_is_refused() -> bool:
    """A node that already votes cannot be promoted."""
    try:
        Roster(voters=("a", "b")).promote("a")
    except ConfigError:
        return True
    return False


def adding_an_existing_node_as_a_learner_is_refused() -> bool:
    """A node already in the roster cannot be added again."""
    try:
        Roster(voters=("a", "b")).with_learner("a")
    except ConfigError:
        return True
    return False


def asking_about_a_stranger_is_refused() -> bool:
    """A name outside the roster has no role."""
    try:
        Roster(voters=("a", "b")).role("z")
    except ConfigError:
        return True
    return False


def compare_the_joining_paths() -> list[dict]:
    """Adding a node directly against adding it as a learner, at each starting size."""
    out = []
    for size in (1, 2, 3, 4, 5, 6, 7):
        voters = tuple(f"n{one}" for one in range(size))
        plain = Roster(voters=(*voters, "new"))
        staged = Roster(voters=voters).with_learner("new")
        out.append(
            {
                "size": size,
                "quorum_before": Roster(voters=voters).quorum,
                "quorum_as_voter": plain.quorum,
                "quorum_as_learner": staged.quorum,
                "raised_immediately": plain.quorum > Roster(voters=voters).quorum,
            }
        )
    return out


def joining_as_a_learner_never_raises_the_quorum_early() -> dict:
    """A direct add raises the quorum out of an odd cluster and not out of an even one.

    The first version of this swept only odd sizes and concluded that a direct add always raises
    the quorum. It does not. A majority of four and a majority of five are both three, so adding
    a fifth voter to four is free, and so is a seventh to six. Only the odd starting sizes pay,
    which is every size anybody actually runs.

    The learner path leaves the quorum alone at every size, odd and even, which is what makes it
    the general answer rather than the one that happens to help. The direct add is free exactly
    when the cluster was already the wrong shape.
    """
    table = compare_the_joining_paths()
    raised = [one["size"] for one in table if one["raised_immediately"]]
    free = [one["size"] for one in table if not one["raised_immediately"]]
    return {
        "sizes": [one["size"] for one in table],
        "raised_by_a_direct_add": raised,
        "free_for_a_direct_add": free,
        "it_does_not_always_raise_it": len(raised) < len(table),
        "the_ones_that_pay_are_odd": all(one % 2 == 1 for one in raised),
        "and_the_free_ones_are_even": all(one % 2 == 0 for one in free),
        "the_learner_path_never_raises_it": all(
            one["quorum_as_learner"] == one["quorum_before"] for one in table
        ),
        "so_a_learner_is_the_general_answer": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    joining = joining_as_a_learner_never_raises_the_quorum_early()
    return {
        "roles": len(ROLES),
        "close_enough": CLOSE_ENOUGH,
        "a_direct_add_raises_the_quorum": (
            adding_a_voter_raises_the_quorum_before_it_can_help()["it_went_up"]
        ),
        "and_tolerates_no_more": adding_a_voter_raises_the_quorum_before_it_can_help()[
            "and_it_tolerates_no_more"
        ],
        "a_learner_holds_every_entry": a_learner_receives_the_log_and_does_not_vote()[
            "it_holds_every_entry"
        ],
        "and_is_not_counted": a_learner_receives_the_log_and_does_not_vote()[
            "and_it_is_not_counted"
        ],
        "promotion_moves_the_quorum_once": (
            promoting_a_caught_up_learner_costs_one_quorum_change()["it_changed_once"]
        ),
        "the_catch_up_grows_with_the_log": the_gap_is_as_long_as_the_catch_up()[
            "it_grows_with_the_log"
        ],
        "a_direct_add_is_free_out_of_an_even_cluster": joining["it_does_not_always_raise_it"],
        "but_a_learner_never_raises_it": joining["the_learner_path_never_raises_it"],
    }
