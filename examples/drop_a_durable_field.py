"""The term and the vote turn out to be one decision to persist, not two independent ones.

Run with: python examples/drop_a_durable_field.py

The obvious guess is that the durable term, the durable vote and the durable log are three
separate safety decisions, each protecting against its own failure. Dropping each one in turn
and re-running the double-vote scenario says otherwise: dropping the term breaks the vote
protection too, because a node that comes back not knowing its term treats an old vote as
belonging to a term that no longer means anything, and clears it by the ordinary rule for
adopting a later term. Persisting the vote without the term keeps a value that cannot be used.
"""

from __future__ import annotations

from examples.common import rule, table
from rsm.persist import (
    compare_the_configurations,
    the_term_and_the_vote_have_to_be_kept_together,
)


def main() -> None:
    print(rule("each durable field dropped in turn"))
    print(table(compare_the_configurations()))
    print()

    verdict = the_term_and_the_vote_have_to_be_kept_together()
    print(rule("what the sweep says about the three fields"))
    print(f"configurations tried            {verdict['configurations']}")
    print(f"unsafe configurations           {verdict['unsafe']}")
    print(f"exactly two of three break it   {verdict['two_of_the_three_break_it']}")
    print(f"and they are term and vote      {verdict['and_they_are_the_term_and_the_vote']}")
    print(f"dropping the log alone is safe  {verdict['dropping_the_log_is_safe_here']}")

    if not verdict["two_of_the_three_break_it"]:
        raise SystemExit("expected exactly two of the three fields to be unsafe to drop")
    if not verdict["and_they_are_the_term_and_the_vote"]:
        raise SystemExit("expected the term and the vote to be the two unsafe fields")


if __name__ == "__main__":
    main()
