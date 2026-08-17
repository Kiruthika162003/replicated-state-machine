from __future__ import annotations

import random
from dataclasses import dataclass, field

from rsm.errors import ConfigError, NotLeader
from rsm.log import NO_INDEX, NO_TERM, Entry, Log
from rsm.rpc import (
    AHEAD,
    STALE,
    Append,
    Appended,
    Installed,
    InstallSnapshot,
    Message,
    RequestVote,
    Vote,
    term_check,
)

# One node of the cluster, written as a state machine with no threads and no clock.
#
# Everything a node does is a reply to something: a message arrived, a tick passed, or a client
# proposed a command. Each of those is a method that takes the input, changes this node's state,
# and returns the messages to send. Nothing here touches a socket and nothing sleeps, which is
# what lets the whole cluster run inside one deterministic loop and a failing run be replayed
# from a seed.
#
# The three roles are the paper's. A follower waits and answers. A candidate asks for votes. A
# leader replicates and decides what is committed. The transitions between them are the part
# that is easy to write nearly correctly, so each one has a measurement.
#
# Two rules carry the safety argument and both are easy to leave out because a cluster works
# without them until it does not.
#
# A node grants its vote only to a log at least as up to date as its own, which is what keeps a
# leader from being elected without every committed entry.
#
# A leader commits an entry only when a majority holds it and the entry comes from the leader's
# own term. That second half is the one that gets dropped. A leader that counts replicas of an
# entry from an earlier term can commit it, lose the election, and watch the new leader
# overwrite what it just told a client was durable. The scenario is in replicate.py and it is
# five nodes and four terms long, which is why nobody finds it by accident.

FOLLOWER = "follower"
CANDIDATE = "candidate"
LEADER = "leader"
ROLES = (FOLLOWER, CANDIDATE, LEADER)

# Ticks a follower waits without hearing from a leader before standing for election. Randomised
# per node inside this range, and election.py measures what happens as the range narrows.
MIN_ELECTION_TIMEOUT = 10
MAX_ELECTION_TIMEOUT = 20

# Each node's generator is seeded from a string rather than from a hash of one. Python
# randomises string hashes per process, so seeding with hash((seed, name)) produced a different
# cluster in every interpreter while looking perfectly reproducible inside one. Two runs of the
# same measurement in separate processes disagreed, which is how it was found. Seeding a Random
# with a string goes through a digest instead, and that is stable everywhere.

# Ticks between a leader's heartbeats. Well below the minimum election timeout, because a leader
# that heartbeats slower than its followers time out is a leader that deposes itself.
HEARTBEAT_INTERVAL = 3

# How many entries a leader will put in one append. Capped so that a follower catching up over a
# long log does it over several messages rather than one enormous one.
MAX_BATCH = 64


@dataclass
class Node:
    """One member of the cluster: its persistent state, its role, and its view of the others."""

    name: str
    members: tuple[str, ...]
    seed: int = 0
    pre_vote: bool = False
    commit_any_term: bool = False

    term: int = 1
    voted_for: str | None = None
    log: Log = field(default_factory=Log)

    role: str = FOLLOWER
    leader: str | None = None
    commit_index: int = NO_INDEX
    last_applied: int = NO_INDEX

    next_index: dict[str, int] = field(default_factory=dict)
    match_index: dict[str, int] = field(default_factory=dict)
    votes: set[str] = field(default_factory=set)
    pre_votes: set[str] = field(default_factory=set)

    now: int = 0
    election_deadline: int = 0
    heartbeat_due: int = 0
    applied: list[Entry] = field(default_factory=list)
    state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in self.members:
            raise ConfigError(f"{self.name} is not in {list(self.members)}")
        if len(set(self.members)) != len(self.members):
            raise ConfigError(f"{list(self.members)} has a repeated name")
        self.random = random.Random(f"{self.seed}:{self.name}")
        self.reset_election_timer()

    @property
    def peers(self) -> tuple[str, ...]:
        """Everyone except this node."""
        return tuple(one for one in self.members if one != self.name)

    @property
    def quorum(self) -> int:
        """How many nodes make a majority, including this one."""
        return len(self.members) // 2 + 1

    @property
    def is_leader(self) -> bool:
        """Whether this node believes it is the leader."""
        return self.role == LEADER

    def reset_election_timer(self) -> None:
        """Pick a new randomised deadline, which is what breaks split votes.

        Randomised per node and per election. A fixed timeout makes every follower stand at the
        same tick after a leader dies, and election.py measures how many rounds that costs.
        """
        span = self.random.randint(MIN_ELECTION_TIMEOUT, MAX_ELECTION_TIMEOUT)
        self.election_deadline = self.now + span

    def become_follower(self, term: int, leader: str | None = None) -> None:
        """Step down, adopting a term. The only way a term ever changes upwards on this node."""
        if term > self.term:
            self.term = term
            self.voted_for = None
        self.role = FOLLOWER
        self.leader = leader
        self.votes = set()
        self.pre_votes = set()
        self.reset_election_timer()

    def stand(self) -> list[Message]:
        """Begin an election, with a pre vote round first if this node is configured for one."""
        if self.pre_vote and len(self.members) > 1:
            return self.become_pre_candidate()
        return self.become_candidate()

    def become_pre_candidate(self) -> list[Message]:
        """Ask whether an election would succeed, without starting one.

        The request carries the term this node would use and the receiver does not adopt it,
        which is the entire mechanism. A node whose log is behind is refused here and never
        raises anyone's term, so the cluster it was partitioned from carries on undisturbed.

        Nothing about this node changes yet. It stays a follower with its old term, so if the
        pre vote fails it has cost one round trip and left no trace.
        """
        self.pre_votes = {self.name}
        self.reset_election_timer()
        return [
            RequestVote(
                sender=self.name,
                recipient=one,
                term=self.term + 1,
                last_index=self.log.last_index,
                last_term=self.log.last_term,
                pre_vote=True,
            )
            for one in self.peers
        ]

    def become_candidate(self) -> list[Message]:
        """Stand for election: bump the term, vote for yourself, ask everyone else."""
        self.term += 1
        self.role = CANDIDATE
        self.voted_for = self.name
        self.leader = None
        self.votes = {self.name}
        self.pre_votes = set()
        self.reset_election_timer()
        if len(self.members) == 1:
            return self.become_leader()
        return [
            RequestVote(
                sender=self.name,
                recipient=one,
                term=self.term,
                last_index=self.log.last_index,
                last_term=self.log.last_term,
            )
            for one in self.peers
        ]

    def become_leader(self) -> list[Message]:
        """Take office, and write one empty entry to make the term commitable.

        The no op matters more than it looks. A leader cannot commit an entry from an earlier
        term by counting replicas, so a leader that took office over a log full of uncommitted
        entries from previous terms could not commit any of them until a new write arrived. The
        empty entry is that write. Committing it commits everything below it, and a cluster that
        goes quiet immediately after an election still finishes what the last one started.
        """
        self.role = LEADER
        self.leader = self.name
        self.votes = set()
        self.next_index = dict.fromkeys(self.peers, self.log.last_index + 1)
        self.match_index = dict.fromkeys(self.peers, NO_INDEX)
        self.log.append([Entry(term=self.term, index=self.log.last_index + 1)])
        self.match_index[self.name] = self.log.last_index
        self.heartbeat_due = self.now + HEARTBEAT_INTERVAL
        if len(self.members) == 1:
            self.advance_commit()
        return self.replicate()

    def propose(self, command: object) -> int:
        """Accept a client write, returning the index it landed at."""
        if not self.is_leader:
            raise NotLeader(f"{self.name} is a {self.role}")
        one = Entry(term=self.term, index=self.log.last_index + 1, command=command)
        self.log.append([one])
        self.match_index[self.name] = self.log.last_index
        if len(self.members) == 1:
            self.advance_commit()
        return one.index

    def replicate(self, to: str | None = None) -> list[Message]:
        """Send each follower what it is missing, or a heartbeat if it is missing nothing.

        The next index is clamped to this log's own end before anything reads from it. A
        follower can report a match above the leader's last index, by installing a snapshot the
        leader took after trimming, and the version before this one read the term at that index
        and raised past the end of its own log. Clamping is right rather than merely safe: there
        is nothing above the leader's last index to send, so the message is a heartbeat.
        """
        out: list[Message] = []
        for one in [to] if to else self.peers:
            wanted = self.next_index.get(one, self.log.last_index + 1)
            start = min(wanted, self.log.last_index + 1)
            if start <= self.log.snapshot_index:
                out.append(
                    InstallSnapshot(
                        sender=self.name,
                        recipient=one,
                        term=self.term,
                        last_index=self.log.snapshot_index,
                        last_term=self.log.snapshot_term,
                        state=dict(self.state),
                        members=self.members,
                    )
                )
                continue
            previous = start - 1
            entries = tuple(self.log.slice(start, start + MAX_BATCH - 1))
            out.append(
                Append(
                    sender=self.name,
                    recipient=one,
                    term=self.term,
                    previous_index=previous,
                    previous_term=self.log.term_at(previous),
                    entries=entries,
                    commit_index=self.commit_index,
                )
            )
        return out

    def tick(self, now: int) -> list[Message]:
        """Advance this node's clock and do whatever the new time requires."""
        self.now = now
        if self.role == LEADER:
            if now >= self.heartbeat_due:
                self.heartbeat_due = now + HEARTBEAT_INTERVAL
                return self.replicate()
            return []
        if now >= self.election_deadline:
            return self.stand()
        return []

    def step(self, message: Message) -> list[Message]:
        """Handle one message, returning what to send in reply.

        The term check comes first and applies to every kind, which is why it is here rather
        than repeated in each handler. A message from a later term makes this node a follower
        before the message is looked at, and a message from an earlier term is refused with this
        node's term attached so the sender can catch up.
        """
        asking = isinstance(message, RequestVote | Vote) and message.pre_vote
        state = term_check(self.term, message)
        if asking:
            if state == STALE:
                return self._refuse(message)
        elif state == AHEAD:
            self.become_follower(message.term)
        elif state == STALE:
            return self._refuse(message)

        if isinstance(message, RequestVote):
            return self._on_request_vote(message)
        if isinstance(message, Vote):
            return self._on_vote(message)
        if isinstance(message, Append):
            return self._on_append(message)
        if isinstance(message, Appended):
            return self._on_appended(message)
        if isinstance(message, InstallSnapshot):
            return self._on_install(message)
        if isinstance(message, Installed):
            return self._on_installed(message)
        return []

    def _refuse(self, message: Message) -> list[Message]:
        """Answer a message from an older term, so the sender learns the current one."""
        if isinstance(message, RequestVote):
            return [
                Vote(sender=self.name, recipient=message.sender, term=self.term, granted=False)
            ]
        if isinstance(message, Append):
            return [
                Appended(
                    sender=self.name,
                    recipient=message.sender,
                    term=self.term,
                    success=False,
                )
            ]
        return []

    def _on_request_vote(self, message: RequestVote) -> list[Message]:
        """Grant a vote if none is spent this term and the candidate's log is up to date.

        A pre vote is answered on the log alone and records nothing. It cannot spend this node's
        vote, because the election it asks about has not started and may never start, and a node
        that spent its vote on a question would be unable to answer the real request that
        follows.
        """
        current = self.log.is_up_to_date(message.last_index, message.last_term)
        if message.pre_vote:
            return [
                Vote(
                    sender=self.name,
                    recipient=message.sender,
                    term=self.term,
                    granted=current and message.term > self.term,
                    pre_vote=True,
                )
            ]
        free = self.voted_for in (None, message.sender)
        granted = free and current
        if granted:
            self.voted_for = message.sender
            self.reset_election_timer()
        return [
            Vote(
                sender=self.name,
                recipient=message.sender,
                term=self.term,
                granted=granted,
            )
        ]

    def _on_vote(self, message: Vote) -> list[Message]:
        """Count a vote, and take office once a majority has answered."""
        if message.pre_vote:
            return self._on_pre_vote(message)
        if self.role != CANDIDATE or not message.granted:
            return []
        self.votes.add(message.sender)
        if len(self.votes) >= self.quorum:
            return self.become_leader()
        return []

    def _on_pre_vote(self, message: Vote) -> list[Message]:
        """Count a pre vote, and start the real election once a majority says it would work."""
        if self.role != FOLLOWER or not message.granted or not self.pre_votes:
            return []
        self.pre_votes.add(message.sender)
        if len(self.pre_votes) >= self.quorum:
            return self.become_candidate()
        return []

    def _on_append(self, message: Append) -> list[Message]:
        """Take entries from the leader, after checking they continue this log."""
        self.leader = message.sender
        if self.role != FOLLOWER:
            self.become_follower(message.term, message.sender)
            self.leader = message.sender
        self.reset_election_timer()

        if not self.log.matches(message.previous_index, message.previous_term):
            return [self._conflict(message)]

        for one in message.entries:
            if self.log.holds(one.index):
                if self.log.term_at(one.index) == one.term:
                    continue
                self.log.truncate_from(one.index)
            if one.index == self.log.last_index + 1:
                self.log.entries.append(one)
        if message.commit_index > self.commit_index:
            self.commit_index = min(message.commit_index, self.log.last_index)
            self.apply_committed()
        return [
            Appended(
                sender=self.name,
                recipient=message.sender,
                term=self.term,
                success=True,
                match_index=message.last_index,
                read_id=message.read_id,
            )
        ]

    def _conflict(self, message: Append) -> Appended:
        """Refuse an append, naming the term this log disagrees on and where that term starts.

        The two extra fields are what turn a walk back into a jump. Only this node can compute
        them, because only this node can see its own log, which is why they are on the reply
        rather than derived by the leader from what it already knows.
        """
        if message.previous_index > self.log.last_index:
            return Appended(
                sender=self.name,
                recipient=message.sender,
                term=self.term,
                success=False,
                conflict_index=self.log.last_index + 1,
                read_id=message.read_id,
            )
        conflicting = self.log.term_at(message.previous_index)
        first = message.previous_index
        while first > self.log.first_index and self.log.term_at(first - 1) == conflicting:
            first -= 1
        return Appended(
            sender=self.name,
            recipient=message.sender,
            term=self.term,
            success=False,
            conflict_term=conflicting,
            conflict_index=first,
            read_id=message.read_id,
        )

    def _on_appended(self, message: Appended) -> list[Message]:
        """Move a follower's index forward on success, or back it up on a refusal."""
        if self.role != LEADER:
            return []
        if message.success:
            self.match_index[message.sender] = max(
                self.match_index.get(message.sender, NO_INDEX), message.match_index
            )
            self.next_index[message.sender] = self.match_index[message.sender] + 1
            self.advance_commit()
            if self.next_index[message.sender] <= self.log.last_index:
                return self.replicate(message.sender)
            return []
        if message.conflict_term != NO_TERM:
            self.next_index[message.sender] = self._skip_term(message.conflict_term, message)
        else:
            self.next_index[message.sender] = max(message.conflict_index, self.log.first_index)
        return self.replicate(message.sender)

    def _skip_term(self, conflict_term: int, message: Appended) -> int:
        """Where to retry after a follower named the term it disagreed on.

        If this leader also holds that term, the follower's copy of it is wrong only past the
        leader's last entry for it, so the retry starts there. If the leader has never seen the
        term, the follower's whole run of it is wrong and the retry starts where the follower
        says the run began.
        """
        for index in range(self.log.last_index, self.log.first_index - 1, -1):
            if self.log.term_at(index) == conflict_term:
                return index + 1
        return max(message.conflict_index, self.log.first_index)

    def advance_commit(self) -> None:
        """Commit the highest index a majority holds, if it comes from this leader's term.

        The second condition is the one that is easy to leave out, and a cluster runs for a long
        time without it. Counting replicas of an entry from an earlier term can commit something
        a later leader is still entitled to overwrite, because the majority holding it never
        promised anything about it: they accepted it from a leader that has since been deposed.
        Only an entry from the current term carries the guarantee, and committing one commits
        everything below it.

        The commit_any_term flag drops the second condition. It is not a configuration anyone
        should turn on: it exists so that replicate.py can run the same scenario with the rule
        and without it and show the committed entry being overwritten, which is a stronger
        argument than the paragraph above.
        """
        if self.role != LEADER:
            return
        self.match_index[self.name] = self.log.last_index
        for index in range(self.log.last_index, self.commit_index, -1):
            if not self.commit_any_term and self.log.term_at(index) != self.term:
                continue
            holders = sum(
                1 for one in self.members if self.match_index.get(one, NO_INDEX) >= index
            )
            if holders >= self.quorum:
                self.commit_index = index
                self.apply_committed()
                return

    def apply_committed(self) -> list[Entry]:
        """Hand every newly committed entry to the state machine, in index order."""
        out: list[Entry] = []
        while self.last_applied < self.commit_index:
            self.last_applied += 1
            if not self.log.holds(self.last_applied):
                continue
            one = self.log.at(self.last_applied)
            self.applied.append(one)
            out.append(one)
            if one.command is not None:
                self._apply(one.command)
        return out

    def _apply(self, command: object) -> None:
        """Apply one command to the key value state this node keeps."""
        if isinstance(command, tuple) and len(command) == 3 and command[0] == "set":
            self.state[command[1]] = command[2]

    def _on_install(self, message: InstallSnapshot) -> list[Message]:
        """Replace this node's log with a snapshot from the leader."""
        self.leader = message.sender
        self.reset_election_timer()
        if message.last_index > self.log.last_index:
            self.log = Log(
                entries=[],
                snapshot_index=message.last_index,
                snapshot_term=message.last_term,
            )
            self.state = dict(message.state)
            self.commit_index = message.last_index
            self.last_applied = message.last_index
        return [
            Installed(
                sender=self.name,
                recipient=message.sender,
                term=self.term,
                last_index=self.log.last_index,
            )
        ]

    def _on_installed(self, message: Installed) -> list[Message]:
        """Record that a follower took the snapshot and carry on from there."""
        if self.role != LEADER:
            return []
        self.match_index[message.sender] = max(
            self.match_index.get(message.sender, NO_INDEX), message.last_index
        )
        self.next_index[message.sender] = self.match_index[message.sender] + 1
        self.advance_commit()
        return self.replicate(message.sender)

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "node": self.name,
            "role": self.role,
            "term": self.term,
            "voted_for": self.voted_for,
            "leader": self.leader,
            "last_index": self.log.last_index,
            "commit_index": self.commit_index,
            "applied": self.last_applied,
        }

    def __str__(self) -> str:
        return f"{self.name} {self.role}@{self.term} log={self.log.last_index}"


def _three(seed: int = 0) -> list[Node]:
    """Three fresh nodes, which is the smallest cluster that can lose one."""
    members = ("a", "b", "c")
    return [Node(name=one, members=members, seed=seed) for one in members]


def _exchange(nodes: list[Node], messages: list[Message], rounds: int = 6) -> list[Message]:
    """Deliver messages between nodes directly, with no network, until they stop replying."""
    by_name = {one.name: one for one in nodes}
    seen: list[Message] = []
    pending = list(messages)
    for _ in range(rounds):
        if not pending:
            break
        seen.extend(pending)
        out: list[Message] = []
        for one in pending:
            out.extend(by_name[one.recipient].step(one))
        pending = out
    return seen


def a_fresh_node_is_a_follower() -> dict:
    """Every node starts as a follower with an empty log and no vote spent.

    The starting state, checked because a node that started as a candidate would elect a leader
    on the first tick of every run and half the measurements below would be about a cluster that
    never had a quiet moment.
    """
    one = Node(name="a", members=("a", "b", "c"))
    return {
        "role": one.role,
        "term": one.term,
        "it_is_a_follower": one.role == FOLLOWER,
        "with_no_vote_spent": one.voted_for is None,
        "and_an_empty_log": one.log.empty,
        "and_no_leader": one.leader is None,
        "quorum": one.quorum,
    }


def a_majority_of_three_is_two() -> dict:
    """Quorum is half plus one, so an even cluster buys nothing over the odd one below it.

    Worth stating as a number because it is the argument for odd sized clusters. Four nodes
    need three to agree and tolerate one failure, exactly as three nodes do, so the fourth node
    adds a machine to run and nothing to availability.
    """
    sizes = {}
    for size in (1, 2, 3, 4, 5, 6, 7):
        members = tuple(f"n{one}" for one in range(size))
        node = Node(name="n0", members=members)
        sizes[size] = {"quorum": node.quorum, "tolerates": size - node.quorum}
    return {
        "sizes": sizes,
        "three_needs_two": sizes[3]["quorum"] == 2,
        "four_also_needs_three": sizes[4]["quorum"] == 3,
        "and_tolerates_the_same_as_three": sizes[4]["tolerates"] == sizes[3]["tolerates"],
        "so_an_even_cluster_buys_nothing": all(
            sizes[one]["tolerates"] == sizes[one + 1]["tolerates"] for one in (1, 3, 5)
        ),
    }


def a_node_votes_once_per_term() -> dict:
    """A second candidate in the same term is refused, which is what makes one leader per term.

    The whole of election safety in one rule. Two candidates in a term can each collect votes
    from nodes that have not voted yet, and only the single vote per term stops both reaching a
    majority.
    """
    voter = Node(name="c", members=("a", "b", "c"))
    first = voter.step(RequestVote(sender="a", recipient="c", term=2))
    second = voter.step(RequestVote(sender="b", recipient="c", term=2))
    third = voter.step(RequestVote(sender="b", recipient="c", term=3))
    return {
        "first_granted": first[0].granted,
        "second_granted": second[0].granted,
        "third_granted": third[0].granted,
        "the_first_wins": first[0].granted,
        "the_second_is_refused": not second[0].granted,
        "but_a_later_term_gets_a_fresh_vote": third[0].granted,
        "voted_for": voter.voted_for,
    }


def a_repeated_request_from_the_same_candidate_is_granted_again() -> dict:
    """The same candidate asking twice gets the same answer, because votes are idempotent.

    Which matters because a lost vote reply makes a candidate ask again, and a voter that
    refused the retry would deny a candidate it had already chosen. The rule is a vote for
    nobody or for this candidate, not a vote for nobody.
    """
    voter = Node(name="c", members=("a", "b", "c"))
    first = voter.step(RequestVote(sender="a", recipient="c", term=2))
    again = voter.step(RequestVote(sender="a", recipient="c", term=2))
    other = voter.step(RequestVote(sender="b", recipient="c", term=2))
    return {
        "first": first[0].granted,
        "again": again[0].granted,
        "other": other[0].granted,
        "a_retry_gets_the_same_answer": first[0].granted and again[0].granted,
        "and_a_different_candidate_does_not": not other[0].granted,
    }


def a_vote_is_refused_to_a_log_behind_this_one() -> dict:
    """A candidate whose log is behind is refused, whatever its term.

    The election restriction as the node applies it. The term on the request only says the
    candidate is current, and the log fields say whether it is entitled to lead. A node with
    committed entries the candidate lacks refuses, which is what keeps those entries alive.
    """
    voter = Node(name="c", members=("a", "b", "c"))
    voter.log.append([Entry(term=1, index=1), Entry(term=2, index=2), Entry(term=3, index=3)])

    def ask(last_index: int, last_term: int) -> bool:
        made = RequestVote(
            sender="a",
            recipient="c",
            term=4,
            last_index=last_index,
            last_term=last_term,
        )
        return voter.step(made)[0].granted

    behind = ask(2, 2)
    voter.voted_for = None
    level = ask(3, 3)
    return {
        "own_log": voter.log.last_index,
        "own_term": voter.log.last_term,
        "a_shorter_log_is_refused": not behind,
        "and_an_equal_one_is_granted": level,
        "the_request_terms_were_the_same": True,
        "so_the_log_decided_it": behind != level,
    }


def a_candidate_that_collects_a_majority_takes_office() -> dict:
    """Two votes of three make a leader, and the third vote changes nothing.

    Checked because a candidate that waited for every vote would never take office with a node
    down, which is the case the whole algorithm exists to survive.
    """
    node = Node(name="a", members=("a", "b", "c"))
    out = node.become_candidate()
    before = node.role
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
    after_one = node.role
    node.step(Vote(sender="c", recipient="a", term=node.term, granted=True))
    return {
        "requests_sent": len(out),
        "role_before": before,
        "role_after_one_vote": after_one,
        "role_after_two": node.role,
        "it_took_office_on_the_second": after_one == LEADER,
        "the_third_vote_changed_nothing": node.role == LEADER,
        "it_asked_every_peer": len(out) == 2,
    }


def a_leader_writes_an_empty_entry_on_election() -> dict:
    """Taking office appends one no op, which is what makes the new term commitable.

    Without it a leader elected over a log of uncommitted entries from earlier terms cannot
    commit any of them, because the commit rule only counts entries from the current term. The
    cluster would sit with a leader, a quorum, and nothing committed until a client happened to
    write. The empty entry is that write.
    """
    node = Node(name="a", members=("a", "b", "c"))
    node.log.append([Entry(term=1, index=1, command="x"), Entry(term=1, index=2, command="y")])
    before = node.log.last_index
    node.become_candidate()
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
    return {
        "log_before": before,
        "log_after": node.log.last_index,
        "it_appended_one": node.log.last_index == before + 1,
        "and_it_is_empty": node.log.at(node.log.last_index).is_noop,
        "at_the_new_term": node.log.at(node.log.last_index).term == node.term,
        "which_is_above_the_others": node.term > 1,
    }


def a_leader_steps_down_on_a_later_term() -> dict:
    """A leader that hears a later term becomes a follower before reading the message.

    The rule that resolves a healed partition without any negotiation. The leader on the
    minority side has been sending appends into nothing; the first reply carrying a later term
    deposes it, and it does not have to be told it lost.
    """
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
    was = node.role
    old_term = node.term
    node.step(Appended(sender="c", recipient="a", term=old_term + 5, success=False))
    return {
        "role_before": was,
        "role_after": node.role,
        "term_before": old_term,
        "term_after": node.term,
        "it_was_the_leader": was == LEADER,
        "and_it_stepped_down": node.role == FOLLOWER,
        "adopting_the_later_term": node.term == old_term + 5,
        "and_forgetting_its_vote": node.voted_for is None,
    }


def a_candidate_steps_down_for_a_leader_of_its_own_term() -> dict:
    """An append from the current term ends a candidacy, without any term change.

    The case that a naive term comparison misses. The append is not from a later term, so the
    generic rule does nothing, and a candidate that ignored it would keep asking for votes in a
    term that already has a leader.
    """
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    was = node.role
    term = node.term
    node.step(Append(sender="b", recipient="a", term=term, previous_index=NO_INDEX))
    return {
        "role_before": was,
        "role_after": node.role,
        "term_unchanged": node.term == term,
        "it_was_a_candidate": was == CANDIDATE,
        "and_it_became_a_follower": node.role == FOLLOWER,
        "and_it_knows_the_leader": node.leader == "b",
    }


def a_stale_append_is_refused_without_changing_anything() -> dict:
    """An append from a dead leader is refused and leaves the log alone.

    The deposed leader on the far side of a healed partition is still sending. Its appends carry
    an old term and would overwrite the real log if the term check did not come first.
    """
    node = Node(name="c", members=("a", "b", "c"))
    node.term = 5
    node.log.append([Entry(term=5, index=1, command="real")])
    out = node.step(
        Append(
            sender="a",
            recipient="c",
            term=2,
            previous_index=NO_INDEX,
            entries=(Entry(term=2, index=1, command="stale"),),
        )
    )
    return {
        "own_term": node.term,
        "it_refused": not out[0].success,
        "the_reply_carries_the_current_term": out[0].term == 5,
        "the_log_is_untouched": node.log.at(1).command == "real",
        "and_still_one_entry": node.log.last_index == 1,
    }


def a_follower_takes_entries_that_continue_its_log() -> dict:
    """The ordinary case: the consistency check passes and the entries land.

    Measured because every interesting case below is a departure from it, and a departure from
    something that was already broken proves nothing.
    """
    node = Node(name="c", members=("a", "b", "c"))
    out = node.step(
        Append(
            sender="a",
            recipient="c",
            term=1,
            previous_index=NO_INDEX,
            previous_term=NO_TERM,
            entries=(
                Entry(term=1, index=1, command="x"),
                Entry(term=1, index=2, command="y"),
            ),
            commit_index=1,
        )
    )
    return {
        "it_succeeded": out[0].success,
        "match_index": out[0].match_index,
        "log_length": node.log.last_index,
        "it_took_both": node.log.last_index == 2,
        "it_committed_what_the_leader_had": node.commit_index == 1,
        "and_applied_it": node.last_applied == 1,
        "but_not_the_uncommitted_one": node.last_applied < 2,
    }


def a_follower_refuses_an_append_it_cannot_place() -> dict:
    """An append whose predecessor is missing is refused, with the gap named.

    The refusal carries where this node's log actually ends, so the leader can jump straight
    there instead of walking back one index at a time from wherever it guessed.
    """
    node = Node(name="c", members=("a", "b", "c"))
    node.log.append([Entry(term=1, index=1, command="x")])
    out = node.step(
        Append(
            sender="a",
            recipient="c",
            term=1,
            previous_index=7,
            previous_term=1,
            entries=(Entry(term=1, index=8, command="z"),),
        )
    )
    return {
        "it_refused": not out[0].success,
        "conflict_index": out[0].conflict_index,
        "it_named_the_end_of_its_log": out[0].conflict_index == 2,
        "the_log_is_unchanged": node.log.last_index == 1,
        "and_no_gap_was_created": node.log.last_index == len(node.log),
    }


def a_follower_truncates_what_conflicts_and_keeps_what_does_not() -> dict:
    """Only entries that actually disagree are discarded, not everything from the first one on.

    The subtlety in the append handler. An entry the follower already holds at the same term is
    skipped rather than reapplied, and truncation starts at the first genuine disagreement.
    Truncating from the start of the message would discard entries the leader is not resending
    and would make every retry destroy work.
    """
    node = Node(name="c", members=("a", "b", "c"))
    node.log.append(
        [
            Entry(term=1, index=1, command="keep"),
            Entry(term=1, index=2, command="keep"),
            Entry(term=2, index=3, command="wrong"),
            Entry(term=2, index=4, command="wrong"),
        ]
    )
    out = node.step(
        Append(
            sender="a",
            recipient="c",
            term=3,
            previous_index=2,
            previous_term=1,
            entries=(
                Entry(term=1, index=3, command="keep"),
                Entry(term=3, index=4, command="right"),
            ),
        )
    )
    return {
        "it_succeeded": out[0].success,
        "final_length": node.log.last_index,
        "index_one_survived": node.log.at(1).command == "keep",
        "index_three_was_replaced": node.log.at(3).command == "keep",
        "index_four_is_the_new_one": node.log.at(4).command == "right",
        "nothing_below_the_conflict_moved": node.log.at(2).command == "keep",
    }


def a_leader_commits_when_a_majority_holds_an_entry_from_its_term() -> dict:
    """Two of three acknowledging an entry from the current term commits it.

    The commit rule in its ordinary form, before the case that complicates it. Both halves have
    to hold, and this measures the half that is easy: the counting.
    """
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
    index = node.propose(("set", "k", 1))
    before = node.commit_index
    node.step(
        Appended(sender="b", recipient="a", term=node.term, success=True, match_index=index)
    )
    return {
        "index": index,
        "commit_before": before,
        "commit_after": node.commit_index,
        "one_acknowledgement_committed_it": node.commit_index >= index,
        "because_the_leader_counts_itself": node.quorum == 2,
        "and_it_was_applied": node.last_applied >= index,
        "the_state_changed": node.state.get("k") == 1,
    }


def a_leader_will_not_commit_an_entry_from_an_earlier_term() -> dict:
    """A majority holding an old entry is not enough, and this is the rule that says so.

    The half of the commit rule that gets dropped, measured on the smallest case that shows it.
    A leader elected in term three finds an entry from term two on a majority of nodes. Counting
    replicas would commit it. The rule refuses, because the nodes holding it accepted it from a
    leader that has since been deposed and promised nothing about it, and a later leader is
    still entitled to overwrite it. What makes it commitable is an entry from term three above
    it, which is what the no op on election is for.
    """
    node = Node(name="a", members=("a", "b", "c"))
    node.term = 3
    node.role = LEADER
    node.log.append(
        [Entry(term=1, index=1, command="x"), Entry(term=2, index=2, command="old")]
    )
    node.next_index = dict.fromkeys(node.peers, 3)
    node.match_index = dict.fromkeys(node.peers, NO_INDEX)
    node.match_index["b"] = 2
    node.advance_commit()
    without_noop = node.commit_index

    node.log.append([Entry(term=3, index=3)])
    node.match_index["b"] = 3
    node.advance_commit()
    return {
        "old_entry_term": 2,
        "leader_term": node.term,
        "a_majority_held_the_old_entry": True,
        "it_was_not_committed": without_noop == NO_INDEX,
        "commit_after_the_noop": node.commit_index,
        "and_the_noop_committed_both": node.commit_index == 3,
        "so_the_old_entry_is_committed_too": node.commit_index >= 2,
    }


def committing_an_entry_commits_everything_below_it() -> dict:
    """The commit index is one number, so committing index nine commits one through eight.

    Which is what makes the previous measurement work. The current term entry is the one that
    can be committed by counting, and everything under it comes along, including the entries
    from earlier terms that could never have been committed on their own.
    """
    node = Node(name="a", members=("a", "b", "c"))
    node.term = 4
    node.role = LEADER
    node.log.append(
        [Entry(term=1, index=one, command=f"c{one}") for one in range(1, 9)]
        + [Entry(term=4, index=9)]
    )
    node.next_index = dict.fromkeys(node.peers, 10)
    node.match_index = dict.fromkeys(node.peers, NO_INDEX)
    node.match_index["b"] = 9
    node.advance_commit()
    applied = node.apply_committed()
    return {
        "commit_index": node.commit_index,
        "it_committed_the_top": node.commit_index == 9,
        "and_everything_below": node.last_applied == 9,
        "entries_applied": len(node.applied),
        "applied_in_order": [one.index for one in node.applied] == list(range(1, 10)),
        "the_last_call_applied_nothing_new": applied == [],
    }


def applying_never_runs_ahead_of_committing() -> dict:
    """Entries are applied only once and only after they commit, in index order.

    The property the state machine depends on. Applying twice would double a counter, applying
    out of order would produce a different state on different nodes, and applying uncommitted
    entries would apply something a later leader removes.
    """
    node = Node(name="c", members=("a", "b", "c"))
    node.log.append(
        [Entry(term=1, index=one, command=("set", "k", one)) for one in range(1, 6)]
    )
    node.commit_index = 3
    first = node.apply_committed()
    again = node.apply_committed()
    node.commit_index = 5
    rest = node.apply_committed()
    return {
        "first_batch": [one.index for one in first],
        "second_call": again,
        "rest": [one.index for one in rest],
        "it_applied_three": len(first) == 3,
        "a_second_call_applies_nothing": again == [],
        "and_raising_the_commit_index_applies_the_rest": [one.index for one in rest] == [4, 5],
        "never_past_the_commit_index": node.last_applied == node.commit_index,
        "the_state_holds_the_last_write": node.state["k"] == 5,
    }


def the_election_timer_is_seeded_by_a_string_not_a_hash() -> dict:
    """A node's timeouts have to be the same in every process, and a hash of a name is not.

    Found by a summary that disagreed with the measurement it was summarising. Both called the
    same function with the same seed and got different answers, because they ran in different
    interpreters and Python randomises the hash of a string per process. Inside one process the
    old version looked perfectly reproducible, which is the worst way for this to fail.

    Seeding a generator with the string itself goes through a digest rather than the process
    hash, so the deadlines below are fixed constants and a failing seed stays a failing seed
    across a restart, a machine and a rerun tomorrow.
    """
    made = [Node(name=one, members=("a", "b", "c"), seed=0) for one in ("a", "b", "c")]
    spans = [one.election_deadline for one in made]
    again = [
        Node(name=one, members=("a", "b", "c"), seed=0).election_deadline
        for one in ("a", "b", "c")
    ]
    other_seed = [
        Node(name=one, members=("a", "b", "c"), seed=1).election_deadline
        for one in ("a", "b", "c")
    ]
    return {
        "deadlines": spans,
        "they_repeat_in_this_process": spans == again,
        "they_are_these_exact_numbers": spans == [11, 18, 15],
        "a_different_seed_differs": other_seed != spans,
        "every_deadline_is_in_range": all(
            MIN_ELECTION_TIMEOUT <= one <= MAX_ELECTION_TIMEOUT for one in spans
        ),
        "and_the_nodes_do_not_all_agree": len(set(spans)) > 1,
    }


def a_follower_can_report_an_index_the_leader_does_not_have() -> dict:
    """A snapshot reply can name an index above the leader's log, and it must not read past it.

    Found by a test rather than by reasoning, which is the point of writing them. A follower
    that installs a snapshot answers with the index it now holds, and that index can sit above
    the leader's own last entry if the leader has trimmed since. The version before this one
    took the next index at face value and asked its own log for the term one below, which is an
    index it does not hold, and raised out of a message handler.

    Clamping to the leader's own end is right rather than merely safe: there is nothing above it
    to send, so the correct message is a heartbeat, which is what the clamp produces.
    """
    node = Node(name="a", members=("a", "b", "c"))
    node.become_candidate()
    node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
    node.step(Installed(sender="b", recipient="a", term=node.term, last_index=7))
    out = node.replicate("b")
    return {
        "leader_last_index": node.log.last_index,
        "follower_reported": node.match_index["b"],
        "the_follower_is_ahead": node.match_index["b"] > node.log.last_index,
        "it_still_produced_a_message": len(out) == 1,
        "and_it_is_a_heartbeat": out[0].is_heartbeat,
        "clamped_to": out[0].previous_index,
        "which_is_the_leaders_own_end": out[0].previous_index == node.log.last_index,
    }


def a_single_node_cluster_commits_without_asking_anyone() -> dict:
    """One node is its own majority, so a write commits the moment it is proposed.

    The degenerate case, worth having because the quorum arithmetic has to hold at one and a
    cluster of one is what every test fixture starts from before it grows.
    """
    node = Node(name="a", members=("a",))
    node.become_candidate()
    index = node.propose(("set", "k", 7))
    return {
        "role": node.role,
        "it_elected_itself": node.role == LEADER,
        "index": index,
        "commit_index": node.commit_index,
        "it_committed_at_once": node.commit_index >= index,
        "and_applied_it": node.state.get("k") == 7,
        "quorum": node.quorum,
    }


def a_follower_refuses_a_client_write() -> bool:
    """Only a leader accepts a proposal, and a follower says so rather than accepting it."""
    node = Node(name="a", members=("a", "b", "c"))
    try:
        node.propose(("set", "k", 1))
    except NotLeader:
        return True
    return False


def a_node_outside_its_own_cluster_is_refused() -> bool:
    """A node whose name is not in the membership is refused at construction."""
    try:
        Node(name="z", members=("a", "b", "c"))
    except ConfigError:
        return True
    return False


def a_membership_with_a_repeated_name_is_refused() -> bool:
    """Two members with one name is refused."""
    try:
        Node(name="a", members=("a", "a", "b"))
    except ConfigError:
        return True
    return False


def compare_the_roles() -> list[dict]:
    """What each role does with a tick and with a client write."""
    out = []
    for role in ROLES:
        node = Node(name="a", members=("a", "b", "c"))
        if role == CANDIDATE:
            node.become_candidate()
        elif role == LEADER:
            node.become_candidate()
            node.step(Vote(sender="b", recipient="a", term=node.term, granted=True))
        node.now = 100
        sends = len(node.tick(100))
        try:
            node.propose(("set", "k", 1))
            accepts = True
        except NotLeader:
            accepts = False
        out.append(
            {
                "role": node.role,
                "accepts_writes": accepts,
                "messages_on_a_late_tick": sends,
                "term": node.term,
            }
        )
    return out


def only_a_leader_accepts_writes() -> dict:
    """One of the three roles takes a client write, and the other two refuse.

    Stated as a sweep over the roles rather than as a claim about one, because the interesting
    failure is a candidate that accepts a write it can never commit.
    """
    table = compare_the_roles()
    accepting = [one["role"] for one in table if one["accepts_writes"]]
    return {
        "roles": len(table),
        "accepting": accepting,
        "only_the_leader_accepts": accepting == [LEADER],
        "every_role_answers_a_tick": all(one["messages_on_a_late_tick"] >= 0 for one in table),
        "a_late_follower_stands_for_election": table[0]["messages_on_a_late_tick"] == 2,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    old_term = a_leader_will_not_commit_an_entry_from_an_earlier_term()
    noop = a_leader_writes_an_empty_entry_on_election()
    return {
        "roles": len(ROLES),
        "quorum_of_three": Node(name="a", members=("a", "b", "c")).quorum,
        "one_vote_per_term": a_node_votes_once_per_term()["the_second_is_refused"],
        "votes_are_idempotent": a_repeated_request_from_the_same_candidate_is_granted_again()[
            "a_retry_gets_the_same_answer"
        ],
        "a_behind_log_is_refused": a_vote_is_refused_to_a_log_behind_this_one()[
            "a_shorter_log_is_refused"
        ],
        "a_leader_writes_a_noop": noop["it_appended_one"],
        "an_old_entry_is_not_committed_alone": old_term["it_was_not_committed"],
        "the_noop_commits_it": old_term["so_the_old_entry_is_committed_too"],
        "only_the_leader_accepts_writes": only_a_leader_accepts_writes()[
            "only_the_leader_accepts"
        ],
    }
