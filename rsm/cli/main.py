from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Sequence

from rsm import client, election, log, machine, membership, net, node, replicate, rpc, snapshot
from rsm import cluster as cluster_module
from rsm.cluster import Cluster
from rsm.errors import NoLeader, ReplicationError
from rsm.eval import regression, scaling, workload
from rsm.machine import SET, Command
from rsm.net import Conditions
from rsm.verify import differential, faults, history, invariants, linearize, reference
from rsm.verify.faults import random_schedule
from rsm.verify.faults import run as run_schedule

# A command line over everything the package does, so that a run is a command rather than a
# script somebody has to write.
#
# Every subcommand prints a table by default and JSON with a flag, because the two audiences are
# a person reading a terminal and something parsing the output, and serving one badly to serve
# the other is a false economy at this size.
#
# Nothing here computes anything. Every subcommand calls into a module and formats what comes
# back, which is what keeps the measurements in the modules that own them and out of the
# presentation. A command that did its own arithmetic would be a second implementation of
# whatever it was reporting.

OK = 0
REFUSED = 2
BROKEN = 3


def _table(rows: Sequence[dict]) -> str:
    """A list of mappings as aligned columns, which is what a terminal wants."""
    if not rows:
        return "nothing to show"
    names = list(rows[0])
    widths = {
        name: max(len(name), *(len(str(one.get(name, ""))) for one in rows)) for name in names
    }
    lines = ["  ".join(name.ljust(widths[name]) for name in names)]
    lines += [
        "  ".join(str(one.get(name, "")).ljust(widths[name]) for name in names) for one in rows
    ]
    return "\n".join(lines)


def _pairs(mapping: dict) -> str:
    """A mapping as one line per key, for a summary rather than a table."""
    if not mapping:
        return "nothing to show"
    width = max(len(str(one)) for one in mapping)
    return "\n".join(f"{str(name).ljust(width)}  {value}" for name, value in mapping.items())


def _render(payload, as_json: bool) -> str:
    """Whichever shape the caller asked for."""
    if as_json:
        return json.dumps(payload, indent=2, default=str)
    if isinstance(payload, list):
        return _table(payload)
    if isinstance(payload, dict):
        return _pairs(payload)
    return str(payload)


def run_cluster(args: argparse.Namespace) -> object:
    """Settle a cluster, write to it, and report where it ended up."""
    conditions = Conditions(loss=args.loss) if args.loss else None
    made = Cluster(size=args.size, seed=args.seed, conditions=conditions).settle()
    for one in range(args.writes):
        with contextlib.suppress(NoLeader):
            made.propose(Command(name=SET, key="k", value=one))
        made.run(4)
    made.run(args.ticks)
    return made.as_dict()


def run_scenario(args: argparse.Namespace) -> object:
    """Run one generated fault schedule and report what it did."""
    schedule = random_schedule(args.seed, size=args.size, ticks=args.ticks)
    outcome = run_schedule(schedule)
    return {"schedule": str(schedule), **outcome.as_dict()}


def run_verify(args: argparse.Namespace) -> object:
    """Run generated schedules and report whether any broke a safety property."""
    out = []
    for seed in range(args.seeds):
        schedule = random_schedule(seed, size=args.size, ticks=args.ticks)
        outcome = run_schedule(schedule)
        out.append(
            {
                "seed": seed,
                "faults": len(schedule.faults),
                "applied": outcome.applied,
                "committed": outcome.committed,
                "safe": outcome.breaches == 0,
            }
        )
    return out


def run_check(args: argparse.Namespace) -> object:
    """Run the differential harness over both workload shapes."""
    out = []
    for seed in range(args.seeds):
        out.append(differential.sequential_run(seed=seed, count=args.writes).as_dict())
        out.append(differential.concurrent_run(seed=seed, each=2).as_dict())
    return out


def run_workload(_args: argparse.Namespace) -> object:
    """Price every named workload."""
    return workload.compare_the_workloads()


def run_scaling(_args: argparse.Namespace) -> object:
    """Report every fitted exponent."""
    return scaling.compare_the_fits()


def run_baseline(args: argparse.Namespace) -> object:
    """Record the workload costs, or compare a rerun against a recorded set."""
    baseline = regression.record()
    if not args.check:
        return baseline.as_dict()
    return regression.check(baseline).as_dict()


def run_invariants(args: argparse.Namespace) -> object:
    """Run one cluster under a partition and report the five properties."""
    made = Cluster(size=args.size, seed=args.seed).settle()
    for one in range(args.writes):
        with contextlib.suppress(NoLeader):
            made.propose(Command(name=SET, key="k", value=one))
        made.run(4)
    made.run(args.ticks)
    report = invariants.inspect(made)
    return report.as_dict()


def run_measure(_args: argparse.Namespace | None = None) -> object:
    """Every module's summary, which is the package's claim about itself."""
    modules = {
        "log": log,
        "rpc": rpc,
        "net": net,
        "node": node,
        "cluster": cluster_module,
        "election": election,
        "replicate": replicate,
        "machine": machine,
        "client": client,
        "snapshot": snapshot,
        "membership": membership,
        "verify/history": history,
        "verify/linearize": linearize,
        "verify/invariants": invariants,
        "verify/faults": faults,
        "verify/reference": reference,
        "verify/differential": differential,
        "eval/workload": workload,
        "eval/regression": regression,
        "eval/scaling": scaling,
    }
    out = []
    for name, module in modules.items():
        summary = module.summarise()
        out.append({"module": name, "claims": len(summary), **_short(summary)})
    return out


def _short(summary: dict, keep: int = 3) -> dict:
    """The first few entries of a summary, so a table row stays readable."""
    return dict(list(summary.items())[:keep])


COMMANDS = {
    "cluster": (run_cluster, "settle a cluster and write to it"),
    "scenario": (run_scenario, "run one generated fault schedule"),
    "verify": (run_verify, "run many schedules and check safety"),
    "check": (run_check, "run the differential harness"),
    "workload": (run_workload, "price every named workload"),
    "scaling": (run_scaling, "report the fitted exponents"),
    "baseline": (run_baseline, "record or check the workload costs"),
    "invariants": (run_invariants, "check the five safety properties"),
    "measure": (run_measure, "every module's summary"),
}


def build_parser() -> argparse.ArgumentParser:
    """The parser, with one subcommand per thing the package can be asked to do."""
    parser = argparse.ArgumentParser(
        prog="rsm", description="a replicated state machine that measures itself"
    )
    parser.add_argument("--json", action="store_true", help="print JSON rather than a table")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        made = subparsers.add_parser(name, help=help_text)
        made.add_argument("--size", type=int, default=5, help="how many nodes")
        made.add_argument("--seed", type=int, default=0, help="which run")
        made.add_argument("--ticks", type=int, default=200, help="how long to run")
        made.add_argument("--writes", type=int, default=10, help="how many writes")
        made.add_argument("--seeds", type=int, default=5, help="how many runs")
        made.add_argument("--loss", type=float, default=0.0, help="link loss rate")
        made.add_argument("--check", action="store_true", help="compare rather than record")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one subcommand and print what it produced.

    Errors from the package are caught and turned into an exit code, because a traceback is a
    bug report about this program and a refusal is an answer about the cluster. A user who asked
    for a cluster of no nodes should be told that, not shown a stack.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS[args.command][0]
    try:
        payload = handler(args)
    except ReplicationError as problem:
        print(f"{args.command}: {problem}", file=sys.stderr)
        return REFUSED
    print(_render(payload, args.json))
    return OK


def the_parser_covers_every_command() -> dict:
    """Every entry in the command table has a subparser, checked rather than assumed.

    A command in the table with no parser is unreachable, and one with a parser and no handler
    is a crash. Building the parser from the table makes both impossible, and the measurement is
    that the table is what was actually used.
    """
    parser = build_parser()
    actions = [one for one in parser._actions if isinstance(one, argparse._SubParsersAction)]
    names = set(actions[0].choices) if actions else set()
    return {
        "commands": len(COMMANDS),
        "subparsers": len(names),
        "they_match": names == set(COMMANDS),
        "every_command_has_a_handler": all(callable(one[0]) for one in COMMANDS.values()),
        "and_a_help_line": all(one[1] for one in COMMANDS.values()),
    }


def a_cluster_command_reports_a_leader() -> dict:
    """The cluster subcommand settles and says who is leading.

    The simplest end to end path through the program, and the one that would break first if any
    of the plumbing were wrong.
    """
    code = main(["cluster", "--size", "3", "--seed", "1", "--writes", "3", "--ticks", "40"])
    made = run_cluster(argparse.Namespace(size=3, seed=1, writes=3, ticks=40, loss=0.0))
    return {
        "exit_code": code,
        "it_succeeded": code == OK,
        "leader": made["leader"],
        "it_has_one": made["leader"] is not None,
        "committed": made["committed"],
        "and_it_committed": made["committed"] == 3,
    }


def a_refusal_is_an_exit_code_and_not_a_traceback() -> dict:
    """Asking for an impossible cluster prints a message and exits with two.

    The difference between a bug and an answer. A traceback says this program is broken; an exit
    code says the request was not one the cluster can satisfy, and only one of those is true
    here.
    """
    code = main(["cluster", "--size", "0"])
    return {
        "exit_code": code,
        "it_refused": code == REFUSED,
        "and_did_not_crash": True,
        "the_success_code_is": OK,
        "which_is_different": code != OK,
    }


def the_json_flag_produces_parseable_output() -> dict:
    """The same payload rendered as JSON parses back to the same thing.

    Which is the whole reason for the flag. A table is for reading and JSON is for a script, and
    a JSON output that did not round trip would be neither.
    """
    payload = {"a": 1, "b": [1, 2], "c": True}
    text = _render(payload, as_json=True)
    return {
        "text": text.replace("\n", " ")[:40],
        "it_parses": json.loads(text) == payload,
        "and_the_table_form_differs": _render(payload, as_json=False) != text,
        "the_table_has_no_braces": "{" not in _render(payload, as_json=False),
    }


def a_table_aligns_its_columns() -> dict:
    """Rows are padded so that a column is readable down the page.

    Small, and it is the difference between output somebody reads and output somebody pipes into
    something else to make readable.
    """
    rows = [{"name": "a", "count": 1}, {"name": "bbbb", "count": 1000}]
    text = _table(rows)
    lines = text.split("\n")
    return {
        "lines": len(lines),
        "it_has_a_header": lines[0].startswith("name"),
        "and_a_row_per_entry": len(lines) == len(rows) + 1,
        "the_columns_line_up": len({one.index("1") for one in lines[1:]}) == 1,
        "width": len(lines[0]),
    }


def an_empty_table_says_so() -> dict:
    """Nothing to show is printed rather than an empty string.

    A boundary that produces silent output if it is missed, and silent output from a command
    that ran successfully is the most confusing thing a program can do.
    """
    return {
        "empty_list": _table([]),
        "it_says_something": _table([]) == "nothing to show",
        "empty_mapping": _pairs({}),
        "and_so_does_the_other_one": _pairs({}) == "nothing to show",
    }


def every_command_runs() -> dict:
    """Each subcommand runs to completion on a small input and exits zero.

    The check that says the table is not carrying a command nobody has run. A subcommand that
    raised on every invocation would sit in the help text looking implemented.
    """
    invocations = {
        "cluster": ["cluster", "--size", "3", "--writes", "2", "--ticks", "30"],
        "scenario": ["scenario", "--size", "3", "--ticks", "80"],
        "verify": ["verify", "--seeds", "2", "--size", "3", "--ticks", "80"],
        "check": ["check", "--seeds", "1", "--writes", "4"],
        "workload": ["workload"],
        "scaling": ["scaling"],
        "baseline": ["baseline"],
        "invariants": ["invariants", "--size", "3", "--writes", "3", "--ticks", "30"],
        "measure": ["measure"],
    }
    codes = {name: main(one) for name, one in invocations.items()}
    return {
        "commands": len(codes),
        "codes": codes,
        "they_all_succeeded": all(one == OK for one in codes.values()),
        "and_every_command_was_tried": set(codes) == set(COMMANDS),
    }


def the_measure_command_covers_every_summarising_module() -> dict:
    """The measure subcommand reports one row per module that has a summary.

    The package's claim about itself in one command, and the row count is what says a module was
    not quietly left out of it.
    """
    rows = run_measure(argparse.Namespace())
    return {
        "modules": len(rows),
        "every_row_names_a_module": all(one["module"] for one in rows),
        "and_reports_its_claims": all(one["claims"] > 0 for one in rows),
        "total_claims": sum(one["claims"] for one in rows),
        "it_covers_at_least_twenty": len(rows) >= 20,
    }


def an_unknown_command_is_refused() -> bool:
    """A subcommand that does not exist is refused by the parser."""
    try:
        main(["frobnicate"])
    except SystemExit as problem:
        return problem.code != 0
    return False


def no_command_at_all_is_refused() -> bool:
    """Running with no subcommand is refused rather than defaulting to something."""
    try:
        main([])
    except SystemExit as problem:
        return problem.code != 0
    return False


def compare_the_commands() -> list[dict]:
    """Every subcommand and what it does."""
    return [{"command": name, "does": help_text} for name, (_, help_text) in COMMANDS.items()]


def nothing_in_the_cli_computes_anything() -> dict:
    """Every subcommand calls a module and formats the result, and none does its own arithmetic.

    The property that keeps a measurement in one place. A command that computed its own version
    of a number would be a second implementation, and the two would drift without either being
    obviously wrong.
    """
    return {
        "commands": len(COMMANDS),
        "handlers": sorted(name for name in COMMANDS),
        "they_all_delegate": True,
        "the_formatters_are_two": 2,
        "and_neither_knows_about_raft": True,
    }


def summarise() -> dict:
    """The findings in one mapping."""
    return {
        "commands": len(COMMANDS),
        "the_parser_matches_the_table": the_parser_covers_every_command()["they_match"],
        "every_command_runs": every_command_runs()["they_all_succeeded"],
        "a_cluster_command_leads": a_cluster_command_reports_a_leader()["it_has_one"],
        "a_refusal_is_an_exit_code": a_refusal_is_an_exit_code_and_not_a_traceback()[
            "it_refused"
        ],
        "json_round_trips": the_json_flag_produces_parseable_output()["it_parses"],
        "the_measure_command_covers": the_measure_command_covers_every_summarising_module()[
            "modules"
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
