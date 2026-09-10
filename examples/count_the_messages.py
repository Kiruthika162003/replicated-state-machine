"""Growing the cluster costs more messages than making its links lossy, which is backwards.

Run with: python examples/count_the_messages.py

Loss forces retries, and retries are messages, so a lossy link looks like the expensive
setting to add. It is the cheaper one. A retry only resends whatever was actually lost, but an
extra node adds a heartbeat's worth of messages forever, on every tick, whether anything failed
or not. Size is a standing cost paid regardless of what happens; loss is a proportional cost
paid only for what goes wrong.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.replicate import compare_the_write_paths, the_link_costs_less_than_the_cluster_size


def main() -> None:
    print(rule("messages to commit one write, four settings, six seeds each"))
    print(table(compare_the_write_paths()))
    print()

    verdict = the_link_costs_less_than_the_cluster_size()
    print(rule("which step actually costs more"))
    print(f"three nodes, clean link        {verdict['three_clean']} messages")
    print(f"five nodes, clean link         {verdict['five_clean']} messages")
    print(f"five nodes, lossy link         {verdict['five_lossy']} messages")
    print(f"cost of the size step          {verdict['the_size_step_costs']}")
    print(f"cost of the loss step          {verdict['the_loss_step_costs']}")
    print(f"size costs more than loss      {verdict['size_costs_more_than_loss']}")
    print(f"loss can even cost less        {verdict['and_loss_can_even_cost_less']}")

    if not verdict["size_costs_more_than_loss"]:
        raise SystemExit("expected growing the cluster to cost more than adding loss")


if __name__ == "__main__":
    main()
