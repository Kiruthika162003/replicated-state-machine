# replicated-state-machine

A Raft implementation in Python with no dependencies, built as a set of measurements. Every
module pairs the code with the runs that establish what it does, and a good many of those runs
came back disagreeing with what was expected of them.

The package is deterministic end to end. There are no threads and no wall clock: time is an
integer tick, the network draws its losses and delays from one seeded generator in a fixed
order, and every node seeds its election timer from a string rather than a hash. A seed names a
run exactly, so a failing seed is a bug report and a passing suite means the same thing on every
machine that runs it.

```bash
python -m rsm.cli.main cluster --size 5 --writes 10
python -m rsm.cli.main report
python examples/tour.py
```

## What is in it

Fifty five modules under `rsm/`, and the fifty two that measure something end in a `summarise()`
returning what they established. `rsm/report.py` collects all of it, four hundred and sixty two
findings gathered from the modules rather than restated, so the package's claim about itself
cannot drift from the code. Three hundred and thirty six of those findings are a yes or a no and
none of them comes back false.

The core is `log.py`, `rpc.py`, `net.py`, `node.py` and `cluster.py`: a log with the matching
property, six message types, a deterministic lossy network, one node's state machine, and a
cluster that ticks them. Everything else measures something about that.

`verify/` holds the checkers: five safety invariants, a linearizability checker with a third
verdict for undecided, a fault schedule generator, a reference model, a differential harness, a
fuzzer with a shrinker, an exhaustive ordering search, bounded liveness properties, an event
trace with replay, a transition coverage grid, a refinement check and a soak comparison.

`eval/` holds the costs: workloads, scaling fits, a regression baseline, latency distributions,
availability against the binomial, a joint parameter sweep and read write mixes.

The rest are one subject each: timing, batching, the wire codec, directed partitions, quorum
arithmetic, log repair, leases, observability, backpressure, restarts, rejoining, leader
priority, sharding, key expiry, watches, rebalancing, the idle floor and charting.

`examples/` holds twenty three runnable scripts, one per idea, which print intermediate state
rather than a verdict because the verdicts are already in the tests.

## Some of what the measurements found

The interesting half of this repository is the set of claims that did not survive being
measured. Each is recorded in the module that found it, in the docstring and in the commit
message, rather than quietly corrected.

**A fixed election timeout does not elect slowly, it never elects at all.** Every node starts
together, draws the same deadline, stands in the same tick and votes for itself, forever. Fifty
four terms in six hundred ticks and no leader, at every seed and every cluster size above one.
One tick of randomisation fixes it completely: a range of fifteen to sixteen is as stable at
seven nodes as a range of ten to forty.

**Beating faster makes failover slower.** Fourteen ticks to replace a dead leader at a heartbeat
of one against under thirteen at three, five and eight. The heartbeat is not the failure
detector, it is the thing that keeps resetting it, so a fast beat leaves every follower at the
start of its timer at the moment the leader dies.

**Cutting a node's inbound traffic is far worse than cutting its outbound.** A node that can hear
but not answer costs nothing. A node that can speak but not hear cannot win an election and does
not need to: every request it sends carries a higher term, and every leader that receives one
steps down. Eight leadership changes and half the writes lost. A leader that cannot hear is worse
still: full uptime, a flat term, and nothing committed at all.

**Fault injection and ordering search find different bugs.** Four deliberately broken nodes, each
one rule removed. Drawing fault schedules catches the node that ignores the election restriction
and misses the one that forgets its vote; enumerating message orderings catches the forgotten
vote and cannot reach the log check. Both catch the double vote. Neither catches the commit rule
for entries from earlier terms, which `replicate.py` catches by driving the nodes through the
sequence by hand.

**Shrinking a failing schedule changed the diagnosis, not just its length.** The double vote
arrives wrapped in six faults over three hundred ticks and needs none of them: two leaders in one
term inside the first thirty ticks of a completely healthy five node cluster.

**The binomial availability formula understates unavailability by four orders of magnitude at
nine nodes.** Measured availability improves from ninety six to ninety nine percent and then
stops, because what is left when a majority is up is the election after a leader dies, and that
does not shrink with the cluster.

**Bounding an uncommitted queue costs exactly the throughput it removes.** Throughput under a
bound is the bound divided by the heartbeat interval, precisely, because the leader drains the
queue once per heartbeat and refuses everything offered in between. The queue is not overhead, it
is the buffer that keeps the next batch full.

**Many short runs cover more than one long one.** Three thousand ticks spent on twenty fresh
clusters reaches twenty one transitions; spent on a single cluster it reaches nine. The long run
stops discovering at tick twelve hundred and keeps going to three thousand.

**No repair strategy wins every case.** Walking back is optimal when a follower is nearly current
and unbounded when it is not; bisecting is bounded and pays a fixed toll every time; the conflict
optimisation ties walking exactly when the terms alternate. The ranking is a property of how
often a follower is nearly current, not of the strategies.

**Sharding gives up a property rather than a quantity.** Throughput and failure isolation are
numbers that can be tuned. Atomicity across the keyspace is either there or is not, and at two
groups it is already gone.

**A state machine that reads a clock diverges while every safety property holds.** Expiring keys
on each replica's own clock puts a third of a run into disagreement, with an identical log on
every replica. With the clocks aligned it diverges not at all, which is why the mistake ships.

## Running it

```bash
pip install -e ".[dev]"
pytest
ruff check rsm tests examples
python -m rsm.cli.main --help
```

Three thousand three hundred and thirty one tests, all of them measurements of the same code the
package ships. Fifty four of the four hundred and sixty two findings are named after a
measurement that came back against what the docstring above it had claimed, spread across thirty
nine of the fifty two modules.

The command line has twenty four subcommands, one per module that produces a table worth reading
in a terminal, and `--json` on any of them. `python -m rsm.cli.main report` runs every
measurement in the package and prints what came back, which takes a couple of minutes and is the
shortest way to see the whole thing at once.

## What it is not

It is not a production consensus implementation. There is no persistence to disk, no real
transport, no security, and no attempt to survive a node that lies rather than one that stops.
Raft does not claim to survive a lying node, and a simulation of an attack it cannot resist would
prove nothing.

The measurements are of a model. The tick is not a millisecond, the byte estimates are checked
against a real codec and are still estimates, and every claim about a bound holds under the
conditions it was measured under. Where that matters, the module says so.

## Notes

Written by Kiruthika Subramani in collaboration with Claude, Anthropic's AI assistant.

Thirty thousand lines of implementation, tests and examples, not counting docstrings, comments or
blank lines. Every commit carries the finding that prompted it.
