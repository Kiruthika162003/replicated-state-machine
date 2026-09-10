"""Trim the log under a running cluster, and see the threshold trade log size for reach.

Run with: python examples/compact_and_keep_serving.py

A node that never trims its log can always catch up a lagging follower with ordinary appends,
at the cost of a log that grows forever. A node that trims aggressively keeps a small log and
loses that option early: a follower behind the compaction threshold cannot be repaired with
appends any more, because the entries it needs no longer exist, and has to be sent the whole
state instead. The threshold is not a size knob, it is a reach knob, and the sweep below is
what it actually trades against what people expect it to trade against.
"""

from __future__ import annotations

from examples.common import pairs, rule, table
from rsm.snapshot import (
    COMPACT_AFTER,
    a_cluster_compacts_and_keeps_serving,
    compare_the_thresholds,
    the_threshold_trades_log_size_against_how_far_a_follower_may_lag,
)


def main() -> None:
    live = a_cluster_compacts_and_keeps_serving()
    print(rule("a cluster compacting while it keeps serving"))
    print(
        pairs(
            {
                "log length before trimming": live["log_before"],
                "nodes trimmed": len(live["trimmed"]),
                "every node trimmed": live["it_trimmed_every_node"],
                "it kept committing across the boundary": live["it_kept_committing"],
                "the nodes still agree": live["and_the_nodes_agree"],
                "logs are level again": live["logs_level"],
            }
        )
    )
    print()

    print(rule("what four thresholds cost, on the same workload"))
    print(table(compare_the_thresholds()))
    print()
    print("the snapshot column does not move, because a snapshot is the state and the state")
    print("does not care how many entries produced it; the log and reach columns move together")
    print()

    trade = the_threshold_trades_log_size_against_how_far_a_follower_may_lag()
    print(rule("the trade, stated as a comparison rather than a table"))
    print(
        pairs(
            {
                "lower threshold keeps fewer entries": trade["the_lower_threshold_keeps_less"],
                "and reaches less far": trade["and_reaches_less_far"],
                "the snapshot stays one size": trade["the_snapshot_is_the_same_size"],
                "shipped threshold": trade["shipped_threshold"],
            }
        )
    )
    print()
    print(f"this package ships with a threshold of {COMPACT_AFTER} entries")

    if not (live["it_trimmed_every_node"] and live["it_kept_committing"]):
        raise SystemExit("expected compaction to trim every node without stalling commits")
    if not (trade["the_lower_threshold_keeps_less"] and trade["and_reaches_less_far"]):
        raise SystemExit("expected a lower threshold to keep less and reach less far")
    if not trade["the_snapshot_is_the_same_size"]:
        raise SystemExit("expected the snapshot size to be independent of the threshold")


if __name__ == "__main__":
    main()
