from __future__ import annotations

# The errors this package raises, arranged so that a caller can catch the class of problem it
# knows how to handle rather than the specific one.
#
# The distinction that matters is between a protocol violation and a refusal. A refusal is an
# ordinary outcome: a node that is not the leader refuses a write, a client retries elsewhere,
# and nothing is wrong. A violation means the algorithm did something it is not allowed to do,
# and there is no recovery from it because the safety argument has already failed. They are
# different exception trees for that reason, and nothing in the package catches ConsensusError.


class ReplicationError(Exception):
    """Anything this package raises."""


class ConsensusError(ReplicationError):
    """A Raft safety property was violated.

    Never caught anywhere in this package. If one of these escapes, the invariant checker found
    the algorithm doing something the paper forbids, and continuing would produce measurements
    of a system that is already broken.
    """


class ElectionSafety(ConsensusError):
    """Two leaders in one term."""


class LogMatching(ConsensusError):
    """Two logs agree at an index and term but not on the entry."""


class LeaderCompleteness(ConsensusError):
    """A committed entry is missing from a later leader's log."""


class StateMachineSafety(ConsensusError):
    """Two nodes applied different entries at the same index."""


class LeaderAppendOnly(ConsensusError):
    """A leader overwrote or removed an entry from its own log."""


class Refused(ReplicationError):
    """An ordinary refusal, expected in normal operation."""


class NotLeader(Refused):
    """A write was sent to a node that is not the leader."""


class NoLeader(Refused):
    """There is no leader to send to, usually mid election."""


class Unavailable(Refused):
    """The cluster cannot make progress, usually for want of a quorum."""


class Timeout(Refused):
    """A client request did not complete in the ticks allowed."""


class LogError(ReplicationError):
    """The log was asked for something it does not hold."""


class Compacted(LogError):
    """An index has been discarded into a snapshot and cannot be read."""


class NotFound(LogError):
    """An index is beyond the end of the log."""


class ConfigError(ReplicationError):
    """A cluster, node or scenario was configured impossibly."""


class NetworkError(ReplicationError):
    """The simulated network was asked to do something it cannot."""


class UnknownNode(NetworkError):
    """A message was addressed to a node the network does not have."""
