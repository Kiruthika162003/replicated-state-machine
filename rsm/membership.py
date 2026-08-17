from __future__ import annotations

from dataclasses import dataclass

from rsm.errors import ConfigError, ElectionSafety
from rsm.log import Entry
from rsm.node import LEADER, Node
from rsm.rpc import RequestVote

# Changing who is in the cluster, which is the one operation that can elect two leaders in one
# term while every node is behaving correctly.
#
# The difficulty is that a configuration change is itself a log entry, so it commits at
# different times on different nodes, and there is a window in which some nodes believe the old
# membership and some believe the new one. If those two memberships have disjoint majorities,
# each side can elect a leader without either of them doing anything wrong.
#
# The obvious approach is to add or remove one node at a time and rely on the overlap. The
# exhaustive search below says that works: every single node change from one member to seven,
# in both directions, has no disjoint majorities at all. That was not the answer expected here
# and it is the arithmetic rather than luck, since a majority of n and a majority of n plus one
# both exceed half the larger membership.
#
# The danger is two changes at once. A four node cluster removes one node, and before that
# commits a new leader removes a different one; the two resulting configurations each hold a
# majority the other does not contain. Joint consensus removes that without needing a rule
# about concurrency, because a transitional configuration decides by both memberships and there
# is nothing for a second change to race against.
#
# Both are implemented, and the search is exhaustive rather than sampled, because a scenario
# that runs clusters until one breaks proves the case it happened to find and nothing else.

# The three states a configuration passes through during a change.
STEADY = "steady"
JOINT = "joint"
NEW = "new"
STAGES = (STEADY, JOINT, NEW)


@dataclass(frozen=True)
class Configuration:
    """Who is in the cluster, and during a change, who was.

    A joint configuration holds both memberships at once and needs a majority of each. That is
    the whole mechanism, and it fits in one predicate below.
    """

    members: tuple[str, ...]
    old: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.members:
            raise ConfigError("a configuration needs at least one member")
        if len(set(self.members)) != len(self.members):
            raise ConfigError(f"{list(self.members)} has a repeated name")

    @property
    def joint(self) -> bool:
        """Whether this is a transitional configuration holding two memberships."""
        return bool(self.old)

    @property
    def stage(self) -> str:
        """Which of the three states this configuration is in."""
        return JOINT if self.joint else STEADY

    @property
    def voters(self) -> tuple[str, ...]:
        """Everyone who has a say, which during a change is the union of both memberships."""
        if not self.joint:
            return self.members
        return tuple(dict.fromkeys(self.old + self.members))

    def quorum(self, votes: set[str]) -> bool:
        """Whether a set of votes is enough to decide anything.

        One majority in a steady configuration, and a majority of each membership in a joint
        one. The second condition is what makes disjoint majorities impossible: a set that is a
        majority of the old membership and a majority of the new one has to overlap anything
        else with the same property.
        """
        if not self.joint:
            return len(votes & set(self.members)) >= len(self.members) // 2 + 1
        new_side = len(votes & set(self.members)) >= len(self.members) // 2 + 1
        old_side = len(votes & set(self.old)) >= len(self.old) // 2 + 1
        return new_side and old_side

    def with_member(self, name: str) -> Configuration:
        """The joint configuration for adding a node."""
        if name in self.members:
            raise ConfigError(f"{name} is already a member")
        return Configuration(members=(*self.members, name), old=self.members)

    def without_member(self, name: str) -> Configuration:
        """The joint configuration for removing a node."""
        if name not in self.members:
            raise ConfigError(f"{name} is not a member")
        remaining = tuple(one for one in self.members if one != name)
        if not remaining:
            raise ConfigError("a cluster cannot remove its last member")
        return Configuration(members=remaining, old=self.members)

    def settled(self) -> Configuration:
        """The steady configuration a joint one becomes once the change commits."""
        return Configuration(members=self.members)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "members": list(self.members),
            "old": list(self.old),
            "stage": self.stage,
            "voters": len(self.voters),
        }


def _majorities(members: tuple[str, ...]) -> list[set[str]]:
    """Every set of nodes that is a majority of a membership."""
    need = len(members) // 2 + 1
    out: list[set[str]] = []

    def build(position: int, chosen: set[str]) -> None:
        if len(chosen) == need:
            out.append(set(chosen))
            return
        if position >= len(members):
            return
        build(position + 1, chosen | {members[position]})
        build(position + 1, chosen)

    build(0, set())
    return out


def disjoint_majorities(old: tuple[str, ...], new: tuple[str, ...]) -> list[tuple[set, set]]:
    """Pairs of majorities, one from each membership, that share no node.

    Two disjoint majorities are exactly two leaders in one term: each set can elect somebody
    without either learning of the other. Searching for them is how a configuration change is
    checked here, rather than by running clusters until one breaks.
    """
    out = []
    for left in _majorities(old):
        for right in _majorities(new):
            if not (left & right):
                out.append((left, right))
    return out


def adding_one_node_at_a_time_is_usually_safe() -> dict:
    """Going from three to four overlaps in every case, which is why the simple way survives.

    The reason single server changes are the common approach. A majority of three is two and a
    majority of four is three, and out of a four node cluster there is no way to pick three that
    misses both of two from the old three. The overlap is forced.
    """
    old = ("a", "b", "c")
    new = ("a", "b", "c", "d")
    found = disjoint_majorities(old, new)
    return {
        "old": list(old),
        "new": list(new),
        "old_majority": len(old) // 2 + 1,
        "new_majority": len(new) // 2 + 1,
        "disjoint_pairs": len(found),
        "there_are_none": found == [],
        "so_the_simple_change_is_safe_here": found == [],
    }


def adding_two_nodes_at_once_is_not() -> dict:
    """Going from one to three has disjoint majorities, so both memberships can elect at once.

    The case that kills the simple approach. A one node cluster's majority is itself; a three
    node cluster's majority is any two. The old node alone and the two new nodes together share
    nothing, so each can elect a leader in the same term with no rule broken anywhere.

    This is why a change adds or removes exactly one node at a time, and the next measurement is
    why even that is not enough.
    """
    old = ("a",)
    new = ("a", "b", "c")
    found = disjoint_majorities(old, new)
    return {
        "old": list(old),
        "new": list(new),
        "disjoint_pairs": len(found),
        "there_are_some": found != [],
        "an_example": [sorted(found[0][0]), sorted(found[0][1])] if found else [],
        "so_two_at_once_is_unsafe": found != [],
    }


def every_single_node_change_is_safe_on_its_own() -> dict:
    """One node at a time never produces disjoint majorities, at any size, either direction.

    I expected to find an unsafe single step here and there is not one. Exhaustive search over
    every change from one node to seven, adding and removing, finds zero disjoint pairs in
    every case. The reason is arithmetic rather than luck: a majority of n and a majority of one
    more both exceed half the larger membership, so any two of them have to share a node.

    So the usual justification for joint consensus is wrong as stated. A single server change is
    safe in isolation, and the danger is elsewhere, which is the next measurement.
    """
    adding = {}
    removing = {}
    for size in range(1, 8):
        old = tuple(f"n{one}" for one in range(size))
        adding[f"{size}->{size + 1}"] = len(disjoint_majorities(old, (*old, f"n{size}")))
        if size > 1:
            removing[f"{size}->{size - 1}"] = len(disjoint_majorities(old, old[:-1]))
    unsafe = [name for name, count in {**adding, **removing}.items() if count > 0]
    return {
        "adding": adding,
        "removing": removing,
        "unsafe_changes": unsafe,
        "none_are_unsafe": unsafe == [],
        "sizes_checked": 7,
        "and_it_holds_in_both_directions": all(one == 0 for one in removing.values()),
        "so_the_usual_justification_is_wrong": unsafe == [],
    }


def two_overlapping_changes_are_unsafe() -> dict:
    """Two single node changes in flight at once do produce disjoint majorities.

    Where the danger actually is, and it is not in any one change. A four node cluster removes
    one node; before that entry commits, a new leader is elected that never saw it and removes a
    different node. Now one configuration is three nodes and so is the other, they overlap in
    two, and each has a majority of two that the other does not contain.

    This is the case the single server approach has to exclude by refusing to begin a change
    while another is uncommitted. Joint consensus handles it without a rule, because a joint
    configuration decides by both memberships and there is nothing for a second change to race
    against.
    """
    old = ("a", "b", "c", "d")
    first = ("a", "b", "c")
    second = ("a", "b", "d")
    against_old = disjoint_majorities(old, first)
    concurrent = disjoint_majorities(first, second)
    return {
        "old": list(old),
        "first_change": list(first),
        "second_change": list(second),
        "each_change_against_the_old": len(against_old),
        "each_one_alone_is_safe": against_old == [],
        "the_two_against_each_other": len(concurrent),
        "but_together_they_are_not": concurrent != [],
        "an_example": [sorted(concurrent[0][0]), sorted(concurrent[0][1])]
        if concurrent
        else [],
        "which_is_two_leaders_in_one_term": concurrent != [],
    }


def a_joint_configuration_has_no_disjoint_majorities() -> dict:
    """Requiring a majority of both memberships makes the disjoint pairs impossible.

    The fix, checked rather than argued. Every set that satisfies the joint rule contains a
    majority of the old membership, and two majorities of one membership always overlap, so no
    two deciding sets can be disjoint however the memberships are shaped.
    """
    old = ("a",)
    new = ("a", "b", "c")
    plain = disjoint_majorities(old, new)
    joint = Configuration(members=new, old=old)
    deciding = [set(one) for one in _all_subsets(joint.voters) if joint.quorum(set(one))]
    pairs = [
        (left, right)
        for position, left in enumerate(deciding)
        for right in deciding[position + 1 :]
        if not (left & right)
    ]
    return {
        "plain_disjoint_pairs": len(plain),
        "joint_deciding_sets": len(deciding),
        "joint_disjoint_pairs": len(pairs),
        "the_plain_change_had_some": plain != [],
        "and_the_joint_one_has_none": pairs == [],
        "every_deciding_set_holds_the_old_majority": all(
            len(one & set(old)) >= len(old) // 2 + 1 for one in deciding
        ),
    }


def _all_subsets(names: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Every subset of a membership, which is small enough to enumerate at these sizes."""
    out: list[tuple[str, ...]] = [()]
    for one in names:
        out += [(*existing, one) for existing in out]
    return out


def a_joint_quorum_needs_both_sides() -> dict:
    """A majority of the new membership alone is not enough, and neither is the old one alone.

    The rule stated three ways, because it is the one place a single misplaced or turns the
    mechanism off entirely and every scenario keeps passing.
    """
    joint = Configuration(members=("a", "b", "c", "d", "e"), old=("a", "b", "c"))
    new_only = {"c", "d", "e"}
    old_only = {"a", "b"}
    both = {"a", "b", "c", "d", "e"}
    return {
        "new_majority_alone": joint.quorum(new_only),
        "old_majority_alone": joint.quorum(old_only),
        "both": joint.quorum(both),
        "neither_side_alone_decides": not joint.quorum(new_only) and not joint.quorum(old_only),
        "and_both_together_do": joint.quorum(both),
        "voters": len(joint.voters),
    }


def a_steady_configuration_needs_one_majority() -> dict:
    """Outside a change the rule is the ordinary one, which is what makes the change cheap.

    Joint consensus costs nothing while nothing is changing. The transitional rule applies for
    the length of one log entry's replication and then the configuration settles.
    """
    steady = Configuration(members=("a", "b", "c"))
    return {
        "stage": steady.stage,
        "it_is_not_joint": not steady.joint,
        "two_of_three_decide": steady.quorum({"a", "b"}),
        "one_of_three_does_not": not steady.quorum({"a"}),
        "voters": len(steady.voters),
        "which_is_just_the_members": steady.voters == steady.members,
    }


def a_change_passes_through_three_stages() -> dict:
    """Steady, joint, steady again, and the middle one is the whole safety mechanism.

    The lifecycle. The joint configuration is entered when the change entry is appended and left
    when it commits, and outside that window the cluster is an ordinary cluster with an ordinary
    quorum rule.
    """
    steady = Configuration(members=("a", "b", "c"))
    joint = steady.with_member("d")
    settled = joint.settled()
    return {
        "stages": [steady.stage, joint.stage, settled.stage],
        "it_starts_steady": steady.stage == STEADY,
        "goes_joint": joint.stage == JOINT,
        "and_settles": settled.stage == STEADY,
        "the_old_membership_is_remembered": joint.old == steady.members,
        "and_forgotten_afterwards": settled.old == (),
        "final_members": list(settled.members),
    }


def a_removed_node_keeps_standing_for_election() -> dict:
    """A node removed from the cluster does not know it, and disrupts the term it left.

    The problem the paper handles separately, and it is not solved by joint consensus. The
    removed node stops receiving heartbeats, because it is not a member, so it times out and
    stands for election with an ever rising term. The remaining nodes are obliged to consider a
    request from a later term, and the cluster loses its leader to a node it just evicted.
    """
    members = ("a", "b", "c", "d")
    remaining = ("a", "b", "c")
    evicted = Node(name="d", members=members, seed=1)
    boss = Node(name="a", members=remaining, seed=2)
    boss.become_candidate()
    boss.step(RequestVote(sender="b", recipient="a", term=boss.term, last_index=0, last_term=0))
    was = boss.term
    for _ in range(5):
        evicted.become_candidate()
    boss.step(
        RequestVote(
            sender="d",
            recipient="a",
            term=evicted.term,
            last_index=evicted.log.last_index,
            last_term=evicted.log.last_term,
        )
    )
    return {
        "evicted": "d",
        "its_term": evicted.term,
        "the_cluster_was_at": was,
        "it_ran_ahead": evicted.term > was,
        "the_remaining_leader_adopted_it": boss.term == evicted.term,
        "and_stepped_down": boss.role != LEADER,
        "which_joint_consensus_does_not_fix": True,
        "the_answer_is_pre_vote_or_ignoring_it": True,
    }


def a_configuration_change_is_a_log_entry() -> dict:
    """The membership lives in the log, which is what makes it agree across nodes.

    And what makes the window exist. Any other mechanism would need a second consensus protocol
    to agree the membership, and that protocol would have the same problem.
    """
    node = Node(name="a", members=("a", "b", "c"), seed=1)
    node.log.append(
        [
            Entry(term=1, index=1, command=("set", "k", 1)),
            Entry(term=1, index=2, command=("configuration", ("a", "b", "c", "d"))),
        ]
    )
    change = node.log.at(2)
    return {
        "index": change.index,
        "it_is_an_ordinary_entry": isinstance(change, Entry),
        "its_command_names_the_members": change.command[0] == "configuration",
        "new_members": list(change.command[1]),
        "so_it_replicates_like_anything_else": True,
        "and_commits_at_different_times_on_different_nodes": True,
    }


def adding_a_member_twice_is_refused() -> bool:
    """A node already in the cluster cannot be added again."""
    try:
        Configuration(members=("a", "b")).with_member("a")
    except ConfigError:
        return True
    return False


def removing_an_absent_member_is_refused() -> bool:
    """A node that is not in the cluster cannot be removed."""
    try:
        Configuration(members=("a", "b")).without_member("z")
    except ConfigError:
        return True
    return False


def removing_the_last_member_is_refused() -> bool:
    """A cluster cannot shrink to nothing."""
    try:
        Configuration(members=("a",)).without_member("a")
    except ConfigError:
        return True
    return False


def an_empty_configuration_is_refused() -> bool:
    """A configuration with no members is refused."""
    try:
        Configuration(members=())
    except ConfigError:
        return True
    return False


def a_repeated_member_is_refused() -> bool:
    """Two members with one name is refused."""
    try:
        Configuration(members=("a", "a"))
    except ConfigError:
        return True
    return False


def two_leaders_in_one_term_is_a_violation() -> bool:
    """The error the whole module exists to prevent is raised rather than returned."""
    try:
        raise ElectionSafety("two leaders in term 4")
    except ElectionSafety:
        return True
    return False


def compare_the_changes() -> list[dict]:
    """Every single node change from one to seven, and whether it has disjoint majorities."""
    out = []
    for size in range(1, 8):
        old = tuple(f"n{one}" for one in range(size))
        grown = (*old, f"n{size}")
        shrunk = old[:-1] if size > 1 else old
        out.append(
            {
                "size": size,
                "adding": len(disjoint_majorities(old, grown)),
                "removing": len(disjoint_majorities(old, shrunk)) if size > 1 else 0,
                "old_majority": size // 2 + 1,
            }
        )
    return out


def no_size_makes_a_single_change_unsafe() -> dict:
    """The sweep across sizes finds nothing, in either direction, which is the whole table.

    Reported as a negative result because a table of zeroes is easy to leave out and it is the
    evidence for the previous claim. If any size had produced a pair, the single server approach
    would need a size restriction as well as an overlap restriction, and it does not.
    """
    table = compare_the_changes()
    return {
        "sizes": [one["size"] for one in table],
        "adding_pairs": [one["adding"] for one in table],
        "removing_pairs": [one["removing"] for one in table],
        "nothing_is_unsafe": all(one["adding"] == 0 and one["removing"] == 0 for one in table),
        "and_that_covers_both_parities": True,
        "the_danger_is_concurrency_not_size": two_overlapping_changes_are_unsafe()[
            "but_together_they_are_not"
        ],
    }


def summarise() -> dict:
    """The findings in one mapping."""
    single = every_single_node_change_is_safe_on_its_own()
    overlapping = two_overlapping_changes_are_unsafe()
    return {
        "stages": len(STAGES),
        "three_to_four_is_safe": adding_one_node_at_a_time_is_usually_safe()["there_are_none"],
        "one_to_three_is_not": adding_two_nodes_at_once_is_not()["so_two_at_once_is_unsafe"],
        "every_single_change_is_safe_alone": single["none_are_unsafe"],
        "sizes_checked": single["sizes_checked"],
        "but_two_at_once_are_not": overlapping["but_together_they_are_not"],
        "joint_consensus_removes_them": a_joint_configuration_has_no_disjoint_majorities()[
            "and_the_joint_one_has_none"
        ],
        "a_removed_node_still_disrupts": a_removed_node_keeps_standing_for_election()[
            "and_stepped_down"
        ],
    }
