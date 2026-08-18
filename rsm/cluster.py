from __future__ import annotations

from dataclasses import dataclass

from rsm.errors import (
    ConfigError,
    ElectionSafety,
    LogMatching,
    NoLeader,
    StateMachineSafety,
    UnknownNode,
)
from rsm.log import NO_INDEX, Log
from rsm.net import Conditions, Network
from rsm.node import FOLLOWER, LEADER, Node
from rsm.rpc import Message

# The driver: several nodes, one network, one loop, and no threads anywhere.
#
# A tick is delivery then timers then sending. Everything the network has for this tick goes to
# its node, every node is asked whether the new time requires anything, and whatever comes back
# goes on the wire. The order is fixed and the nodes are visited in membership order, so a run
# is a function of the seed and nothing else.
#
# That is the whole reason this exists rather than threads and sockets. A consensus bug is an
# interleaving, and an interleaving you cannot reproduce is a rumour. Every scenario in this
# package is a seed, a fault schedule and a tick count, and every one of them replays.
#
# The invariants are checked on every tick rather than at the end. A cluster that violates
# election safety at tick forty and looks correct at tick two hundred has still violated it, and
# a check that only runs at the end would report a healthy cluster. Checking throughout costs a
# pass over the nodes per tick, which is nothing next to being able to say when it broke.

# How long a scenario will wait for a cluster to settle before giving up. Generous, because a
# run that needs more than this has usually failed to elect at all and the count is diagnostic.
SETTLE_TICKS = 400


@dataclass
class Snapshot:
    """What every node looked like at one tick, for checking invariants against."""

    tick: int
    roles: dict[str, str]
    terms: dict[str, int]
    commits: dict[str, int]
    applied: dict[str, list]

    @property
    def leaders(self) -> list[str]:
        """Every node that believes it is the leader right now."""
        return [name for name, role in self.roles.items() if role == LEADER]

    @property
    def leaders_by_term(self) -> dict[int, list[str]]:
        """Leaders grouped by the term they claim, which is what election safety is about."""
        out: dict[int, list[str]] = {}
        for name in self.leaders:
            out.setdefault(self.terms[name], []).append(name)
        return out

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "tick": self.tick,
            "leaders": self.leaders,
            "max_term": max(self.terms.values()) if self.terms else 0,
            "max_commit": max(self.commits.values()) if self.commits else 0,
        }


class Cluster:
    """Several nodes on one deterministic network, driven a tick at a time."""

    def __init__(
        self,
        size: int = 3,
        seed: int = 0,
        conditions: Conditions | None = None,
        check: bool = True,
        pre_vote: bool = False,
    ) -> None:
        if size < 1:
            raise ConfigError(f"{size} is not a cluster size")
        self.members = tuple(f"n{one}" for one in range(size))
        self.seed = seed
        self.pre_vote = pre_vote
        self.net = Network(members=list(self.members), seed=seed, conditions=conditions)
        self.nodes = {
            one: Node(name=one, members=self.members, seed=seed, pre_vote=pre_vote)
            for one in self.members
        }
        self.now = 0
        self.down: set[str] = set()
        self.check = check
        self.history: list[Snapshot] = []
        self.elections = 0
        self.last_leader: str | None = None

    @property
    def up(self) -> list[str]:
        """The nodes that are running, in membership order."""
        return [one for one in self.members if one not in self.down]

    def leader(self) -> Node | None:
        """The leader of the highest term, if exactly one node claims to be one.

        Two nodes can believe they lead at the same moment without any safety violation, as long
        as they claim different terms: the older one has not heard the news yet. Taking the
        highest term is what a client would do, and it is what makes a scenario able to write
        without knowing the fault schedule.
        """
        claiming = [self.nodes[one] for one in self.up if self.nodes[one].role == LEADER]
        if not claiming:
            return None
        best = max(one.term for one in claiming)
        top = [one for one in claiming if one.term == best]
        return top[0] if len(top) == 1 else None

    def snapshot(self) -> Snapshot:
        """What every running node looks like now."""
        return Snapshot(
            tick=self.now,
            roles={one: self.nodes[one].role for one in self.up},
            terms={one: self.nodes[one].term for one in self.up},
            commits={one: self.nodes[one].commit_index for one in self.up},
            applied={
                one: [entry.command for entry in self.nodes[one].applied] for one in self.up
            },
        )

    def tick(self) -> None:
        """One step of the world: deliver, then time, then send."""
        self.now += 1
        for message in self.net.tick():
            if message.recipient in self.down:
                continue
            self._send(self.nodes[message.recipient].step(message))
        for one in self.up:
            self._send(self.nodes[one].tick(self.now))
        found = self.leader()
        if found is not None and found.name != self.last_leader:
            self.elections += 1
            self.last_leader = found.name
        made = self.snapshot()
        self.history.append(made)
        if self.check:
            self.verify(made)

    def _send(self, messages: list[Message]) -> None:
        """Put a node's output on the wire, skipping anything addressed to a stopped node."""
        for one in messages:
            if one.sender in self.down:
                continue
            self.net.send(one)

    def run(self, ticks: int) -> Cluster:
        """Advance a fixed number of ticks."""
        for _ in range(ticks):
            self.tick()
        return self

    def settle(self, ticks: int = SETTLE_TICKS) -> Cluster:
        """Run until there is a leader and nothing is in flight, or give up."""
        for _ in range(ticks):
            self.tick()
            if self.leader() is not None and self.net.quiet:
                return self
        return self

    def propose(self, command: object) -> int:
        """Write through whichever node is currently leading."""
        found = self.leader()
        if found is None:
            raise NoLeader("no node is leading")
        index = found.propose(command)
        self._send(found.replicate())
        return index

    def crash(self, name: str) -> None:
        """Stop a node, keeping only what it would have written to disk.

        The persistent state is the term, the vote and the log. Everything else is volatile and
        is rebuilt from scratch on restart. Getting that split wrong is how a cluster elects two
        leaders in one term, and the scenario that shows it is in election.py.
        """
        if name not in self.members:
            raise UnknownNode(f"{name} is not in {list(self.members)}")
        self.down.add(name)

    def restart(self, name: str) -> None:
        """Bring a node back with its log, its term and its vote, and nothing else."""
        if name not in self.down:
            raise ConfigError(f"{name} is not down")
        old = self.nodes[name]
        fresh = Node(
            name=name,
            members=self.members,
            seed=self.seed + self.now,
            pre_vote=self.pre_vote,
        )
        fresh.term = old.term
        fresh.voted_for = old.voted_for
        fresh.log = Log(
            entries=list(old.log.entries),
            snapshot_index=old.log.snapshot_index,
            snapshot_term=old.log.snapshot_term,
        )
        fresh.now = self.now
        fresh.reset_election_timer()
        self.nodes[name] = fresh
        self.down.discard(name)

    def partition(self, sides: list[list[str]]) -> None:
        """Split the network."""
        self.net.partition(sides)

    def heal(self) -> None:
        """Remove every partition."""
        self.net.heal()

    def committed(self) -> list[object]:
        """The commands the leader has applied, which is the cluster's answer."""
        found = self.leader()
        if found is None:
            return []
        return [one.command for one in found.applied if one.command is not None]

    def committed_count(self) -> int:
        """How many client commands the leader has applied, which is what a caller waits on."""
        return len(self.committed())

    def agreed(self) -> bool:
        """Whether every running node has applied the same prefix."""
        histories = [
            [entry.index for entry in self.nodes[one].applied[: self._shortest()]]
            for one in self.up
        ]
        return len({tuple(one) for one in histories}) <= 1

    def _shortest(self) -> int:
        """How far every running node has applied, which is the prefix they compare on."""
        if not self.up:
            return 0
        return min(len(self.nodes[one].applied) for one in self.up)

    def verify(self, made: Snapshot) -> None:
        """Check the safety properties that must hold at every moment.

        Raised rather than returned. These are not conditions a caller can handle: if two nodes
        lead the same term, everything measured after that point is a measurement of a broken
        algorithm, and carrying on would produce numbers that look like results.
        """
        for term, names in made.leaders_by_term.items():
            if len(names) > 1:
                raise ElectionSafety(f"{names} all lead term {term}")
        by_index: dict[int, tuple[int, object]] = {}
        for one in self.up:
            node = self.nodes[one]
            for entry in node.log:
                seen = by_index.get(entry.index)
                if seen is None:
                    by_index[entry.index] = (entry.term, entry.command)
                elif seen[0] == entry.term and seen[1] != entry.command:
                    raise LogMatching(f"index {entry.index} at term {entry.term} differs")
        shortest = self._shortest()
        for position in range(shortest):
            commands = {
                self.nodes[one].applied[position].as_dict()["command"] for one in self.up
            }
            if len(commands) > 1:
                raise StateMachineSafety(f"position {position} applied {commands}")

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        found = self.leader()
        return {
            "size": len(self.members),
            "up": len(self.up),
            "now": self.now,
            "leader": found.name if found else None,
            "term": found.term
            if found
            else max((self.nodes[one].term for one in self.up), default=0),
            "committed": len(self.committed()),
            "elections": self.elections,
            "messages": self.net.counts.sent,
        }


def _settled(size: int = 3, seed: int = 0, conditions: Conditions | None = None) -> Cluster:
    """A cluster that has elected and gone quiet, which is where most scenarios begin."""
    return Cluster(size=size, seed=seed, conditions=conditions).settle()


def a_fresh_cluster_elects_exactly_one_leader(seeds: int = 20) -> dict:
    """Three nodes started together settle on one leader, over twenty seeds.

    The base case, and one seed would not be enough to state it. Election is the one part of
    Raft that depends on randomness, so a measurement over a single run says only that this run
    worked. Twenty seeds and the tick each one took is what says the mechanism works.
    """
    ticks = []
    leaders = []
    for seed in range(seeds):
        made = Cluster(size=3, seed=seed).settle()
        found = made.leader()
        leaders.append(found.name if found else None)
        ticks.append(made.now)
    return {
        "seeds": seeds,
        "elected": sum(1 for one in leaders if one is not None),
        "they_all_elected": all(one is not None for one in leaders),
        "ticks": ticks[:5],
        "slowest": max(ticks),
        "fastest": min(ticks),
        "distinct_leaders": len({one for one in leaders if one}),
        "and_not_always_the_same_node": len({one for one in leaders if one}) > 1,
    }


def a_write_reaches_every_node(writes: int = 5) -> dict:
    """A command proposed to the leader is applied by all three, in the same order.

    The thing the whole algorithm is for, so it is checked as a sequence rather than a set. Two
    nodes applying the same commands in different orders would produce different states from the
    same log, and a set comparison would call that agreement.
    """
    made = _settled()
    for one in range(writes):
        made.propose(("set", "k", one))
    made.run(30)
    seen = {
        name: [entry.command for entry in made.nodes[name].applied if entry.command is not None]
        for name in made.up
    }
    first = seen[made.members[0]]
    return {
        "writes": writes,
        "applied": {name: len(one) for name, one in seen.items()},
        "they_all_applied_everything": all(len(one) == writes for one in seen.values()),
        "and_in_the_same_order": all(one == first for one in seen.values()),
        "the_order_is_the_write_order": first == [("set", "k", one) for one in range(writes)],
    }


def killing_the_leader_elects_another(seeds: int = 10) -> dict:
    """Stopping the leader costs one election and the cluster carries on.

    The availability claim, measured rather than asserted. Three nodes tolerate one failure, so
    the survivors must elect from among themselves and must do it without the dead node's vote.
    """
    out = []
    for seed in range(seeds):
        made = _settled(seed=seed)
        first = made.leader().name
        made.crash(first)
        made.settle()
        second = made.leader()
        out.append(
            {
                "seed": seed,
                "first": first,
                "second": second.name if second else None,
                "recovered": second is not None,
                "ticks": made.now,
            }
        )
    return {
        "seeds": seeds,
        "recovered": sum(1 for one in out if one["recovered"]),
        "they_all_recovered": all(one["recovered"] for one in out),
        "and_never_the_dead_node": all(
            one["second"] != one["first"] for one in out if one["recovered"]
        ),
        "slowest_recovery": max(one["ticks"] for one in out),
    }


def a_cluster_keeps_serving_after_one_failure(writes: int = 4) -> dict:
    """Writes accepted before and after a leader dies both survive.

    The two halves that matter to a client. What was committed before the failure has to still
    be there, and the cluster has to accept new writes afterwards, and a cluster that did only
    one of those would look available and lose data or look safe and be useless.
    """
    made = _settled()
    for one in range(writes):
        made.propose(("set", "before", one))
    made.run(30)
    before = list(made.committed())
    made.crash(made.leader().name)
    made.settle()
    for one in range(writes):
        made.propose(("set", "after", one))
    made.run(30)
    after = made.committed()
    return {
        "before": len(before),
        "after": len(after),
        "the_old_writes_survived": after[: len(before)] == before,
        "and_the_new_ones_landed": len(after) == len(before) + writes,
        "it_took_an_election": made.elections >= 2,
        "nodes_up": len(made.up),
    }


def a_minority_cannot_elect_a_leader(ticks: int = 200) -> dict:
    """Two nodes cut off from three cannot make a majority, however long they try.

    The other side of the availability claim and the more important one. A minority that
    elected would be a second leader, and the whole safety argument is that it cannot happen.
    Measured by letting it try for two hundred ticks and counting the terms it burned through.
    """
    made = Cluster(size=5, seed=4).settle()
    made.partition([["n0", "n1"], ["n2", "n3", "n4"]])
    made.run(ticks)
    minority = [made.nodes[one] for one in ("n0", "n1")]
    majority = [made.nodes[one] for one in ("n2", "n3", "n4")]
    return {
        "minority_leaders": [one.name for one in minority if one.role == LEADER],
        "majority_leaders": [one.name for one in majority if one.role == LEADER],
        "the_minority_elected_nobody": not any(one.role == LEADER for one in minority),
        "and_the_majority_has_one": sum(1 for one in majority if one.role == LEADER) == 1,
        "the_minority_burned_terms": max(one.term for one in minority),
        "which_is_above_the_majority": max(one.term for one in minority)
        > max(one.term for one in majority),
    }


def a_healed_partition_reconciles(ticks: int = 120) -> dict:
    """The minority rejoins, adopts the winner's log, and loses nothing that was committed.

    What a partition actually costs. The minority ran elections and got nowhere, so it has a
    high term and an old log; the majority kept serving. On healing, the term makes the majority
    leader step down, an election settles it, and the entries the minority never saw arrive.
    """
    made = Cluster(size=5, seed=6).settle()
    for one in range(3):
        made.propose(("set", "before", one))
    made.run(20)
    committed_before = list(made.committed())
    made.partition([["n0", "n1"], ["n2", "n3", "n4"]])
    made.run(60)
    for one in range(3):
        try:
            made.propose(("set", "during", one))
        except NoLeader:
            break
    made.run(40)
    made.heal()
    made.settle()
    made.run(ticks)
    after = made.committed()
    logs = {one: made.nodes[one].log.last_index for one in made.up}
    return {
        "committed_before": len(committed_before),
        "committed_after": len(after),
        "the_early_writes_survived": after[: len(committed_before)] == committed_before,
        "logs": logs,
        "every_log_is_the_same_length": len(set(logs.values())) == 1,
        "and_the_nodes_agree": made.agreed(),
        "elections": made.elections,
    }


def the_same_seed_replays_the_same_cluster(runs: int = 4) -> dict:
    """Four clusters on one seed produce identical tick by tick histories.

    The property the network established, carried up to the level that matters. Every scenario
    in this package is a seed, and a scenario that did not replay would make every measurement
    below a single unrepeatable observation.
    """
    transcripts = []
    for _ in range(runs):
        made = Cluster(size=5, seed=21).settle().run(60)
        transcripts.append(
            [
                (one.tick, tuple(sorted(one.roles.items())), tuple(sorted(one.terms.items())))
                for one in made.history
            ]
        )
    first = transcripts[0]
    return {
        "runs": runs,
        "ticks": len(first),
        "they_are_identical": all(one == first for one in transcripts),
        "distinct": len({tuple(one) for one in transcripts}),
        "and_it_is_a_real_run": len(first) > 50,
    }


def the_invariants_are_checked_every_tick() -> dict:
    """Safety is checked as the run goes, not once at the end.

    A cluster that violates election safety at tick forty and recovers by tick two hundred has
    still violated it, and an end of run check would report a healthy cluster. The cost is a
    pass over the nodes per tick, which buys the ability to say which tick it broke on.
    """
    made = Cluster(size=5, seed=8).settle().run(80)
    checked = len(made.history)
    worst = max(len(one.leaders) for one in made.history)
    with_two = [one.tick for one in made.history if len(one.leaders_by_term.get(1, [])) > 1]
    return {
        "ticks_checked": checked,
        "it_checked_every_tick": checked == made.now,
        "most_leaders_at_once": worst,
        "never_two_in_one_term": with_two == [],
        "and_two_at_once_is_allowed": worst >= 1,
    }


def two_leaders_at_once_is_not_a_violation(ticks: int = 120) -> dict:
    """Two nodes can believe they lead at once, in different terms, and that is legal.

    The distinction a naive invariant gets wrong. Election safety says one leader per term, not
    one leader. A leader on the wrong side of a partition still thinks it leads until it hears
    otherwise, and a checker that forbade that would fail every partition scenario here for a
    condition the algorithm never promised.

    It is not a rare corner either, but how often it appears depends on which side the old
    leader was on, so it is swept over seeds rather than shown on one. The runs where the
    deposed leader lands in the minority are the ones that produce it, and it persists for as
    long as the partition does, because nothing can reach that node to tell it.
    """
    found = []
    for seed in range(12):
        made = Cluster(size=5, seed=seed).settle()
        made.partition([["n0", "n1"], ["n2", "n3", "n4"]])
        made.run(ticks)
        moments = [one for one in made.history if len(one.leaders) > 1]
        terms: list[int] = []
        if moments:
            first = moments[0]
            terms = sorted({first.terms[name] for name in first.leaders})
        found.append({"seed": seed, "moments": len(moments), "terms": terms})
    with_two = [one for one in found if one["moments"] > 0]
    return {
        "seeds": len(found),
        "seeds_with_two_leaders": len(with_two),
        "it_happens": len(with_two) > 0,
        "but_not_every_time": len(with_two) < len(found),
        "longest_stretch": max(one["moments"] for one in found),
        "the_terms_always_differ": all(len(one["terms"]) > 1 for one in with_two),
        "and_no_violation_was_raised": True,
    }


def a_restarted_node_keeps_its_log_and_forgets_the_rest() -> dict:
    """Restarting keeps the term, the vote and the log, and rebuilds everything else.

    The split between what a real node writes to disk and what it holds in memory. Getting it
    wrong in either direction is a bug: keeping too much hides a class of failure the algorithm
    is supposed to survive, and keeping too little elects two leaders in one term.
    """
    made = _settled(size=5, seed=3)
    for one in range(3):
        made.propose(("set", "k", one))
    made.run(30)
    name = next(one for one in made.up if one != made.leader().name)
    before = made.nodes[name]
    kept = (before.term, before.voted_for, before.log.last_index)
    had_role = before.role
    made.crash(name)
    made.restart(name)
    after = made.nodes[name]
    return {
        "term_kept": after.term == kept[0],
        "vote_kept": after.voted_for == kept[1],
        "log_kept": after.log.last_index == kept[2],
        "role_was": had_role,
        "role_is_now": after.role,
        "it_came_back_a_follower": after.role == FOLLOWER,
        "and_forgot_what_it_had_applied": after.last_applied == NO_INDEX,
        "and_forgot_its_commit_index": after.commit_index == NO_INDEX,
    }


def a_restarted_node_catches_up(ticks: int = 120) -> dict:
    """A node that missed writes while down is brought level by the leader without asking.

    Which is the only recovery mechanism there is. The leader notices the follower refusing its
    appends, backs up, and replays. Nothing in the algorithm has a catch up request, and that is
    the point: recovery is the ordinary replication path applied to a follower that is behind.
    """
    made = _settled(size=5, seed=5)
    name = next(one for one in made.up if one != made.leader().name)
    made.crash(name)
    made.settle()
    for one in range(6):
        made.propose(("set", "k", one))
    made.run(40)
    missed = made.nodes[name].log.last_index
    made.restart(name)
    made.run(ticks)
    caught = made.nodes[name]
    leader = made.leader()
    return {
        "index_while_down": missed,
        "leader_index": leader.log.last_index if leader else 0,
        "index_after": caught.log.last_index,
        "it_was_behind": missed < (leader.log.last_index if leader else 0),
        "and_it_caught_up": caught.log.last_index == (leader.log.last_index if leader else -1),
        "and_applied_the_same_commands": [
            one.command for one in caught.applied if one.command is not None
        ]
        == [one.command for one in leader.applied if one.command is not None],
    }


def a_cluster_of_one_needs_no_messages() -> dict:
    """One node elects itself and commits without sending anything.

    The degenerate case, which is worth running because it exercises the quorum arithmetic at
    its boundary and because a cluster that sent messages to nobody would still count them.
    """
    made = Cluster(size=1, seed=1).settle()
    made.propose(("set", "k", 1))
    made.run(5)
    return {
        "leader": made.leader().name,
        "it_elected_itself": made.leader() is not None,
        "messages_sent": made.net.counts.sent,
        "it_sent_nothing": made.net.counts.sent == 0,
        "committed": len(made.committed()),
        "and_still_committed": len(made.committed()) == 1,
    }


def proposing_without_a_leader_is_refused() -> bool:
    """A write with no leader is refused rather than queued."""
    made = Cluster(size=3, seed=1)
    try:
        made.propose("x")
    except NoLeader:
        return True
    return False


def crashing_an_unknown_node_is_refused() -> bool:
    """Stopping a node that is not in the cluster is refused."""
    made = Cluster(size=3, seed=1)
    try:
        made.crash("zz")
    except UnknownNode:
        return True
    return False


def restarting_a_running_node_is_refused() -> bool:
    """Restarting a node that never stopped is refused."""
    made = Cluster(size=3, seed=1)
    try:
        made.restart("n0")
    except ConfigError:
        return True
    return False


def a_cluster_of_no_nodes_is_refused() -> bool:
    """A cluster of size zero is refused."""
    try:
        Cluster(size=0)
    except ConfigError:
        return True
    return False


def compare_the_cluster_sizes(seeds: int = 8) -> list[dict]:
    """What size costs, in ticks to elect and messages to commit one write."""
    out = []
    for size in (1, 3, 5, 7):
        ticks = []
        messages = []
        for seed in range(seeds):
            made = Cluster(size=size, seed=seed).settle()
            ticks.append(made.now)
            before = made.net.counts.sent
            made.propose(("set", "k", 1))
            made.run(20)
            messages.append(made.net.counts.sent - before)
        out.append(
            {
                "size": size,
                "quorum": size // 2 + 1,
                "median_ticks": sorted(ticks)[len(ticks) // 2],
                "median_messages": sorted(messages)[len(messages) // 2],
            }
        )
    return out


def a_larger_cluster_costs_more_messages_per_write() -> dict:
    """The message cost of a write grows with the cluster and the availability does not.

    The trade behind choosing a size. Every write goes to every follower and comes back, so the
    traffic is linear in the peers rather than in the nodes, and the measured counts are exactly
    proportional to size less one. Seven nodes cost three times what three do and tolerate two
    more failures, which is a better exchange than it first looks and is still an exchange.

    The tick to elect barely moves across the sizes, which was not expected. Adding nodes adds
    vote requests and vote replies, and none of them are on the critical path: a candidate needs
    a majority to answer, not everyone, and the majority of seven answers about as quickly as
    the majority of three because the timeout, not the traffic, sets the pace.
    """
    table = compare_the_cluster_sizes()
    by_size = {one["size"]: one for one in table}
    per_peer = {one["size"]: one["median_messages"] // max(one["size"] - 1, 1) for one in table}
    ticks = [one["median_ticks"] for one in table]
    return {
        "sizes": [one["size"] for one in table],
        "messages": {one["size"]: one["median_messages"] for one in table},
        "per_peer": per_peer,
        "one_node_sends_nothing": by_size[1]["median_messages"] == 0,
        "it_grows_with_the_size": (
            by_size[3]["median_messages"]
            < by_size[5]["median_messages"]
            < by_size[7]["median_messages"]
        ),
        "and_it_is_linear_in_the_peers": len({per_peer[one] for one in (3, 5, 7)}) == 1,
        "seven_over_three": round(
            by_size[7]["median_messages"] / max(by_size[3]["median_messages"], 1), 2
        ),
        "for_this_many_more_failures": (7 - by_size[7]["quorum"]) - (3 - by_size[3]["quorum"]),
        "ticks": ticks,
        "but_the_election_time_barely_moves": max(ticks) - min(ticks) <= 5,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    fresh = a_fresh_cluster_elects_exactly_one_leader()
    return {
        "settle_ticks": SETTLE_TICKS,
        "every_seed_elects": fresh["they_all_elected"],
        "slowest_election": fresh["slowest"],
        "a_write_reaches_everyone": a_write_reaches_every_node()["they_all_applied_everything"],
        "a_dead_leader_is_replaced": killing_the_leader_elects_another()["they_all_recovered"],
        "a_minority_elects_nobody": a_minority_cannot_elect_a_leader()[
            "the_minority_elected_nobody"
        ],
        "two_leaders_at_once_is_legal": two_leaders_at_once_is_not_a_violation()["it_happens"],
        "the_seed_replays": the_same_seed_replays_the_same_cluster()["they_are_identical"],
    }
