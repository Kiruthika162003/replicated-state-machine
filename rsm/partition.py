from __future__ import annotations

import contextlib
from dataclasses import dataclass, field

from rsm.cluster import Cluster
from rsm.errors import ConfigError, NoLeader, UnknownNode

# Partitions that are not clean splits, which is most of them.
#
# The partition every simulation models is a clean one: the cluster falls into two groups, each
# group can talk to itself and to nobody else, and the split is the same in both directions.
# That is the easy case, and the algorithm handles it by design: the minority side cannot elect,
# the majority side carries on, and healing reconciles the logs.
#
# The awkward ones are the partitions that are not symmetric. A node that can send but not
# receive. A link that works one way. A node that can reach the leader while the leader cannot
# reach it. These are not exotic; they are what a misconfigured firewall rule, a full receive
# queue or an asymmetric route produces, and they break the assumption that reachability is a
# relation on pairs rather than on ordered pairs.
#
# The one that matters is the isolated node that keeps standing for election. It cannot win,
# because it cannot hear a vote, but its requests carry a term that grows every time it tries,
# and every request it manages to send deposes a working leader. A cluster can be brought down
# by a node that is doing nothing but failing.

# Which direction a cut applies in.
BOTH = "both"
OUTBOUND = "outbound"
INBOUND = "inbound"
DIRECTIONS = (BOTH, OUTBOUND, INBOUND)


@dataclass
class Cut:
    """One directed break in the network, expressed as a rule rather than as a set of sides."""

    node: str
    direction: str = BOTH
    peer: str = ""

    def __post_init__(self) -> None:
        if not self.node:
            raise ConfigError("a cut needs a node")
        if self.direction not in DIRECTIONS:
            raise ConfigError(f"{self.direction} is not one of {list(DIRECTIONS)}")
        if self.peer == self.node:
            raise ConfigError(f"{self.node} cannot be cut from itself")

    def blocks(self, sender: str, recipient: str) -> bool:
        """Whether this cut stops a message going this way.

        With a peer named it is one link and with no peer it is every link the node has. Both
        are worth having and they behave completely differently, which is the measurement two
        functions below.
        """
        if self.peer and self.peer not in (sender, recipient):
            return False
        if self.direction in (BOTH, OUTBOUND) and sender == self.node:
            return True
        return self.direction in (BOTH, INBOUND) and recipient == self.node

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"node": self.node, "direction": self.direction, "peer": self.peer}

    def __str__(self) -> str:
        if self.peer:
            return f"{self.node} cut {self.direction} from {self.peer}"
        return f"{self.node} cut {self.direction}"


class Cuts:
    """A set of directed cuts, replacing the network's own symmetric partition rule.

    This installs itself over the network's reachable method rather than reusing sides, because
    sides cannot express a one way break at all: a side is a set, a set has no direction, and
    the whole point of this module is the direction.
    """

    def __init__(self, cluster: Cluster) -> None:
        self.cluster = cluster
        self.cuts: list[Cut] = []
        self.original = cluster.net.reachable
        cluster.net.reachable = self.reachable

    def add(self, cut: Cut) -> Cuts:
        """Install one cut, checking it names a node the network has heard of."""
        if cut.node not in self.cluster.members:
            raise UnknownNode(f"{cut.node} is not in {list(self.cluster.members)}")
        self.cuts.append(cut)
        return self

    def reachable(self, sender: str, recipient: str) -> bool:
        """Whether a message can go this way, under the cuts and the network's own rule."""
        if any(one.blocks(sender, recipient) for one in self.cuts):
            return False
        return self.original(sender, recipient)

    def heal(self) -> Cuts:
        """Remove every cut."""
        self.cuts = []
        return self

    def restore(self) -> None:
        """Give the network its own rule back."""
        with contextlib.suppress(AttributeError):
            del self.cluster.net.reachable

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {"cuts": [one.as_dict() for one in self.cuts]}


@dataclass
class Run:
    """What a cluster did while a cut was in place."""

    name: str
    terms: int
    leaders: int
    committed: int
    proposed: int
    messages: int
    leaderless: int
    ticks: int
    changes: int = 0
    seen: list[str] = field(default_factory=list)

    @property
    def uptime(self) -> float:
        """The share of the run that had a leader."""
        if self.ticks == 0:
            return 0.0
        return round((self.ticks - self.leaderless) / self.ticks, 3)

    def __bool__(self) -> bool:
        """A run is good if the cluster kept committing what it was given."""
        return self.proposed > 0 and self.committed == self.proposed

    def as_dict(self) -> dict:
        """Flat mapping for logging."""
        return {
            "run": self.name,
            "terms": self.terms,
            "leaders": self.leaders,
            "changes": self.changes,
            "committed": self.committed,
            "proposed": self.proposed,
            "messages": self.messages,
            "uptime": self.uptime,
            "healthy": bool(self),
        }


def run(
    name: str,
    cuts: list[Cut],
    size: int = 5,
    seed: int = 1,
    settle: int = 60,
    ticks: int = 240,
    writes: int = 8,
    pre_vote: bool = False,
) -> Run:
    """Settle a cluster, apply the cuts, then write to it and watch what happens.

    The cuts go on after the cluster has settled on purpose. A cut applied at tick zero measures
    whether a cluster can form under it, which is a different question from whether an
    established cluster survives it, and the second one is the interesting one here.
    """
    made = Cluster(size=size, seed=seed, pre_vote=pre_vote)
    made.run(settle)
    rules = Cuts(made)
    for one in cuts:
        rules.add(one)
    start = made.now
    leaderless = 0
    seen: list[str] = []
    changes = 0
    written = 0
    for tick in range(ticks):
        if tick % 20 == 0 and written < writes:
            written += 1
            with contextlib.suppress(NoLeader):
                made.propose(("set", "k", tick))
        made.tick()
        found = made.leader()
        if found is None:
            leaderless += 1
        elif not seen or seen[-1] != found.name:
            changes += 1
            seen.append(found.name)
    rules.restore()
    return Run(
        name=name,
        terms=max(one.term for one in made.nodes.values()),
        leaders=len(set(seen)),
        committed=len(made.committed()),
        proposed=written,
        messages=made.net.counts.sent,
        leaderless=leaderless,
        ticks=made.now - start,
        changes=changes,
        seen=seen,
    )


def _leader_of(size: int = 5, seed: int = 1, settle: int = 60) -> str:
    """Who leads a settled cluster, so a cut can be aimed at the office rather than a name."""
    made = Cluster(size=size, seed=seed)
    made.run(settle)
    found = made.leader()
    if found is None:
        raise NoLeader("nothing settled")
    return found.name


def a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak() -> dict:
    """The direction of the cut decides everything, and the harmless direction is the surprise.

    Three cuts on the same follower. Cut it in both directions and the cluster does not notice:
    one leader, full uptime, every write committed, while the isolated node burns eighteen terms
    standing for elections nobody can hear. Cut only its outbound traffic, so it can hear but
    not answer, and the cluster does not notice either, because a node that can hear the leader
    never times out and never stands at all.

    Cut only its inbound traffic, so it can speak but not hear, and the cluster falls apart.
    Eighteen terms, four different leaders, eight leadership changes, half the writes lost and
    uptime down to fifty five percent. The node cannot win an election, because it cannot hear
    a vote. It does not need to. Every request it sends carries a term one higher than the last,
    and every leader that receives one steps down.

    The intuition that a node which cannot speak is more broken than one which cannot hear is
    exactly backwards here. Speaking is what does the damage.
    """
    clean = run("clean", [])
    both = run("both", [Cut(node="n4")])
    outbound = run("outbound", [Cut(node="n4", direction=OUTBOUND)])
    inbound = run("inbound", [Cut(node="n4", direction=INBOUND)])
    return {
        "clean_is_healthy": bool(clean),
        "isolating_it_is_harmless": bool(both),
        "and_it_still_burns_terms": both.terms > clean.terms,
        "terms_isolated": both.terms,
        "silencing_it_is_harmless": bool(outbound),
        "and_it_burns_no_terms": outbound.terms == clean.terms,
        "deafening_it_is_not": not inbound,
        "committed": inbound.committed,
        "proposed": inbound.proposed,
        "leadership_changes": inbound.changes,
        "uptime": inbound.uptime,
        "terms_deafened": inbound.terms,
        "and_the_two_directions_disagree": bool(outbound) and not inbound,
    }


def a_pre_vote_round_removes_the_disruption_entirely() -> dict:
    """The deafened node goes from eight leadership changes to none.

    The pre vote round asks whether an election would succeed before starting one, and it asks
    at the current term rather than at a higher one. A node that cannot hear gets no answers, so
    it never reaches the real election and never raises its term, so there is nothing for a
    leader to step down to.

    It is not free. The same run costs about a fifth more messages, because every election that
    does happen now runs two rounds instead of one. That is the trade: a fifth more traffic
    against a cluster that survives a broken network card.
    """
    plain = run("plain", [Cut(node="n4", direction=INBOUND)], pre_vote=False)
    guarded = run("pre vote", [Cut(node="n4", direction=INBOUND)], pre_vote=True)
    return {
        "plain_changes": plain.changes,
        "guarded_changes": guarded.changes,
        "it_stopped_the_churn": guarded.changes < plain.changes,
        "plain_terms": plain.terms,
        "guarded_terms": guarded.terms,
        "and_the_term_stopped_climbing": guarded.terms < plain.terms,
        "plain_committed": plain.committed,
        "guarded_committed": guarded.committed,
        "it_committed_everything": bool(guarded),
        "plain_messages": plain.messages,
        "guarded_messages": guarded.messages,
        "and_it_costs_more_messages": guarded.messages > plain.messages,
        "by_this_ratio": round(guarded.messages / plain.messages, 2),
    }


def a_leader_that_cannot_hear_holds_the_office_and_commits_nothing() -> dict:
    """Full uptime, one leader, no churn, and not one write committed.

    The other half of the same asymmetry, aimed at the leader. Cut the leader's inbound traffic
    and it keeps sending heartbeats, so no follower ever times out and no election ever starts,
    and it never hears an acknowledgement, so it can never move the commit index. The cluster
    looks perfect: a leader the whole time, no churn, terms flat. It has committed nothing since
    the cut.

    Cut the leader's outbound traffic instead and the cluster recovers in one election, because
    the followers stop hearing from it and replace it, which is exactly what the timeout is for.

    Every liveness check this package has would pass the first case. Uptime is one, the term is
    stable, the leader is present. rsm.timing found the same thing from the other end: uptime
    measures whether somebody holds the office, not whether anybody is doing the job.
    """
    leader = _leader_of()
    deaf = run("deaf leader", [Cut(node=leader, direction=INBOUND)])
    mute = run("mute leader", [Cut(node=leader, direction=OUTBOUND)])
    return {
        "leader": leader,
        "deaf_uptime": deaf.uptime,
        "deaf_changes": deaf.changes,
        "deaf_terms": deaf.terms,
        "it_looks_perfectly_healthy": deaf.uptime == 1.0 and deaf.changes <= 1,
        "deaf_committed": deaf.committed,
        "and_committed_nothing": deaf.committed == 0,
        "mute_committed": mute.committed,
        "mute_changes": mute.changes,
        "the_mute_one_recovers": mute.committed > 0,
        "by_electing_someone_else": mute.changes > deaf.changes,
        "so_the_dangerous_cut_is_the_quiet_one": deaf.committed < mute.committed,
    }


def one_broken_link_is_survivable_and_one_broken_node_is_not() -> dict:
    """The same direction of cut, applied to one link or to every link, is two different faults.

    Cut the inbound traffic on one link, so a single follower cannot hear one particular peer,
    and nothing happens: it hears the leader through the other links, never times out, never
    stands. Cut the inbound traffic on every link the same node has and the cluster loses half
    its writes.

    So the fault is not that a node cannot hear something. It is that a node cannot hear
    anything, which is what makes its timer fire, and it can still be heard, which is what makes
    the term it raises everybody else's problem.
    """
    clean = run("clean", [])
    link = run("one link", [Cut(node="n4", direction=INBOUND, peer="n0")])
    whole = run("every link", [Cut(node="n4", direction=INBOUND)])
    return {
        "clean_committed": clean.committed,
        "link_committed": link.committed,
        "whole_committed": whole.committed,
        "one_link_is_harmless": bool(link),
        "and_the_whole_node_is_not": not whole,
        "link_changes": link.changes,
        "whole_changes": whole.changes,
        "the_churn_is_all_in_the_whole_node_case": whole.changes > link.changes,
        "link_terms": link.terms,
        "whole_terms": whole.terms,
    }


def the_damage_needs_a_majority_to_hear_the_higher_term() -> dict:
    """A deafened node in a three node cluster does the same damage; in a larger one, more.

    The disruption is not about the ratio of broken nodes, it is about whether the one broken
    node can reach the others at all, and outbound is the direction that reaches. So the cluster
    size barely helps: five nodes and seven nodes churn just as badly as three, because the
    deafened node is talking to all of them.

    That is the part that makes it worth guarding against rather than sizing around. Adding
    nodes is the usual answer to a fault that takes out a fraction of the cluster, and this is
    not one of those.
    """
    out = {}
    for size in (3, 5, 7):
        out[size] = run(f"{size}", [Cut(node="n2", direction=INBOUND)], size=size)
    return {
        "sizes": sorted(out),
        "changes": {size: one.changes for size, one in out.items()},
        "committed": {size: one.committed for size, one in out.items()},
        "terms": {size: one.terms for size, one in out.items()},
        "every_size_is_disrupted": all(one.changes > 1 for one in out.values()),
        "and_none_of_them_committed_everything": not any(bool(one) for one in out.values()),
        "the_largest_is_no_better": out[7].changes >= out[3].changes - 2,
        "so_size_is_not_the_answer": True,
    }


def healing_a_cut_recovers_without_help() -> dict:
    """The cluster comes back on its own once the cut is removed, and keeps what it committed.

    The other half of any fault measurement, and the easy half here. What matters is that the
    entries committed before the cut are still committed after it, which is leader completeness
    holding through a fault that had nothing to do with logs.
    """
    made = Cluster(size=5, seed=1)
    made.run(60)
    for one in range(4):
        made.propose(("set", "before", one))
    made.run(30)
    before = len(made.committed())
    rules = Cuts(made).add(Cut(node="n4", direction=INBOUND))
    made.run(150)
    during = len(made.committed())
    rules.heal()
    made.run(150)
    for one in range(4):
        with contextlib.suppress(NoLeader):
            made.propose(("set", "after", one))
    made.run(60)
    rules.restore()
    return {
        "committed_before": before,
        "committed_during": during,
        "committed_after": len(made.committed()),
        "nothing_was_lost": len(made.committed()) >= before,
        "it_made_progress_again": len(made.committed()) > during,
        "there_is_a_leader": made.leader() is not None,
        "and_everyone_agrees": made.agreed(),
    }


def a_cut_without_a_node_is_refused() -> bool:
    """A cut has to say what it cuts."""
    try:
        Cut(node="")
    except ConfigError:
        return True
    return False


def an_unknown_direction_is_refused() -> bool:
    """There are three directions and anything else is a typo."""
    try:
        Cut(node="n0", direction="sideways")
    except ConfigError:
        return True
    return False


def cutting_a_node_from_itself_is_refused() -> bool:
    """A node cannot be separated from itself, since it never sends to itself."""
    try:
        Cut(node="n0", peer="n0")
    except ConfigError:
        return True
    return False


def cutting_a_stranger_is_refused() -> bool:
    """A cut naming a node the cluster does not have is refused."""
    made = Cluster(size=3, seed=0)
    rules = Cuts(made)
    try:
        rules.add(Cut(node="nowhere"))
    except UnknownNode:
        return True
    finally:
        rules.restore()
    return False


def compare_the_cuts() -> list[dict]:
    """Every shape of cut over the same cluster."""
    leader = _leader_of()
    return [
        run("none", []).as_dict(),
        run("follower both", [Cut(node="n4")]).as_dict(),
        run("follower mute", [Cut(node="n4", direction=OUTBOUND)]).as_dict(),
        run("follower deaf", [Cut(node="n4", direction=INBOUND)]).as_dict(),
        run("one link", [Cut(node="n4", direction=INBOUND, peer="n0")]).as_dict(),
        run("leader mute", [Cut(node=leader, direction=OUTBOUND)]).as_dict(),
        run("leader deaf", [Cut(node=leader, direction=INBOUND)]).as_dict(),
    ]


def only_one_cut_in_the_table_is_genuinely_misleading() -> dict:
    """Three runs fail and only one of them looks healthy while doing it.

    I expected the table to divide into working and misleading. It does not. Of the three runs
    that fail to commit everything, the mute leader loses exactly one write, during the failover
    it correctly triggers, and its uptime dips; that is a fault handled properly, not a
    disguise. The deafened follower has uptime of fifty five percent, which any check would
    catch.

    That leaves one: the deafened leader, at a hundred percent uptime, no leadership changes, a
    flat term, and nothing committed at all. One run out of seven where the health signal is not
    merely optimistic but exactly inverted.

    The transferable part is what to export. Whether there is a leader is easy to measure, cheap
    to publish and, in the one case that matters most, completely wrong. The commit index moving
    is the thing that says the cluster is working.
    """
    table = compare_the_cuts()
    broken = [one for one in table if not one["healthy"]]
    inverted = [one for one in broken if one["uptime"] >= 0.99 and one["committed"] == 0]
    nearly = [one for one in broken if 0 < one["committed"] < one["proposed"]]
    return {
        "runs": len(table),
        "healthy": [one["run"] for one in table if one["healthy"]],
        "broken": [one["run"] for one in broken],
        "inverted": [one["run"] for one in inverted],
        "there_is_exactly_one": len(inverted) == 1,
        "and_it_is_the_deaf_leader": [one["run"] for one in inverted] == ["leader deaf"],
        "its_uptime": inverted[0]["uptime"],
        "its_commits": inverted[0]["committed"],
        "the_others_lose_only_some": [one["run"] for one in nearly],
        "and_they_dip_in_uptime_or_churn": all(
            one["uptime"] < 1.0 or one["changes"] > 1 for one in nearly
        ),
        "so_the_commit_index_is_the_signal": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    directions = a_node_that_cannot_hear_is_worse_than_one_that_cannot_speak()
    return {
        "directions": len(DIRECTIONS),
        "silencing_a_node_is_harmless": directions["silencing_it_is_harmless"],
        "deafening_one_is_not": directions["deafening_it_is_not"],
        "leadership_changes_when_deafened": directions["leadership_changes"],
        "pre_vote_stops_it": a_pre_vote_round_removes_the_disruption_entirely()[
            "it_stopped_the_churn"
        ],
        "and_costs_this_much_traffic": a_pre_vote_round_removes_the_disruption_entirely()[
            "by_this_ratio"
        ],
        "a_deaf_leader_commits_nothing": (
            a_leader_that_cannot_hear_holds_the_office_and_commits_nothing()[
                "and_committed_nothing"
            ]
        ),
        "while_looking_healthy": (
            a_leader_that_cannot_hear_holds_the_office_and_commits_nothing()[
                "it_looks_perfectly_healthy"
            ]
        ),
        "one_link_is_survivable": one_broken_link_is_survivable_and_one_broken_node_is_not()[
            "one_link_is_harmless"
        ],
        "size_does_not_help": the_damage_needs_a_majority_to_hear_the_higher_term()[
            "so_size_is_not_the_answer"
        ],
        "healing_recovers": healing_a_cut_recovers_without_help()["it_made_progress_again"],
        "one_run_in_seven_is_inverted": only_one_cut_in_the_table_is_genuinely_misleading()[
            "there_is_exactly_one"
        ],
    }
