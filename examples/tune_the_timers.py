"""Sweep the heartbeat and the election timeout, and find where each one stops working.

Run with: python examples/tune_the_timers.py

The usual advice is that the broadcast time should be much less than the election timeout, which
should be much less than the mean time between failures. Neither half says what much less means.
This runs the cluster at a range of settings and prints what each one committed.
"""

from __future__ import annotations

from examples.common import bar, pairs, rule, table
from rsm.timing import SETTINGS, Timings, trial

BEATS = (1, 2, 3, 4, 5, 6, 8, 10, 12)
SEEDS = 3


def sweep_row(beat: int) -> dict:
    """One heartbeat interval, run at several seeds, reported as the worst of them."""
    timings = Timings(name=f"beat {beat}", heartbeat=beat, min_timeout=10, max_timeout=20)
    runs = [trial(timings, seed=seed) for seed in range(SEEDS)]
    worst = min(runs, key=lambda one: one.committed)
    return {
        "heartbeat": beat,
        "one beat rule": "ok" if timings.sane else "no",
        "two beat rule": "ok" if timings.comfortable else "no",
        "stable": "yes" if all(one.stable for one in runs) else "no",
        "committed": f"{worst.committed}/{worst.proposed}",
        "terms": max(one.terms for one in runs),
        "uptime": bar(min(one.uptime for one in runs), 20),
    }


def named_row(name: str) -> dict:
    """One of the shipped named settings."""
    made = trial(SETTINGS[name])
    return {
        "setting": name,
        "heartbeat": SETTINGS[name].heartbeat,
        "timeout": f"{SETTINGS[name].min_timeout}-{SETTINGS[name].max_timeout}",
        "delay": SETTINGS[name].delay,
        "committed": f"{made.committed}/{made.proposed}",
        "leaders": made.leaders,
        "terms": made.terms,
        "messages": made.messages,
    }


def main() -> None:
    print(rule("sweeping the heartbeat against a timeout of ten to twenty"))
    print(table([sweep_row(one) for one in BEATS]))
    print()
    print("the one beat rule allows an interval of eight and leadership breaks at six")
    print("the two beat rule predicts the boundary a tick low, which is the right side")
    print()

    print(rule("the named settings"))
    print(table([named_row(one) for one in SETTINGS]))
    print()
    print("the fixed range never elects anybody at all, at any seed, because a timeout with")
    print("no spread makes every node stand in the same tick forever")
    print()

    inverted = trial(SETTINGS["inverted"])
    shipped = trial(SETTINGS["shipped"])
    print(rule("the setting that looks healthy"))
    print(
        pairs(
            {
                "inverted uptime": inverted.uptime,
                "inverted committed": f"{inverted.committed}/{inverted.proposed}",
                "inverted messages": inverted.messages,
                "shipped messages": shipped.messages,
                "the cheaper of the two": "inverted"
                if inverted.messages < shipped.messages
                else "shipped",
            }
        )
    )
    print()
    print("nine ticks in ten with a leader, fewer messages than any other setting here,")
    print("and one write committed out of ten: neither uptime nor traffic would catch it")


if __name__ == "__main__":
    main()
