# Running replicated-state-machine

Leader election, log replication and consensus, written in Python. This file covers how to build
the project, run its tests, and execute it. Every command below was run from a
clean checkout of this repository before being written down.

## Requirements

Python 3.11 or newer. There are no third party runtime dependencies.

## Setup

Nothing to install. The package has no dependencies, so every command below
runs from the repository root against the source tree as it stands.

## Run the tests

```bash
python -m pytest -q
```

The suite is the primary check. It runs from the repository root with no
arguments and no configuration, and it prints the number of tests it ran. A
non-zero exit status means something is wrong. Read the printed summary rather
than a shell pipeline, because piping the output through another command
replaces the real exit code with that of the last command in the pipe.

## Lint

```bash
python -m ruff check .
```

The lint configuration lives in `pyproject.toml`. It passes with no findings.

## Run the command line tool

```bash
python -m rsm.cli.main --help
```

The subcommands are `cluster`, `scenario`, `verify`, `check`, `workload`, `scaling`, `invariants`, `measure`, `report`, `partition`, `quorum`.

For example:

```bash
python -m rsm.cli.main cluster
```

## Run a worked example

There are 35 runnable examples in `examples/`. Each exposes `main()`, which prints a
measured comparison and raises if the number it just measured stopped matching what
the example claims:

```bash
python -c "from examples.break_it_on_purpose import main; main()"
```

The full list is `break_it_on_purpose`, `chart_the_sweeps`, `check_a_history`,
`choose_a_size`, `elect_a_leader`, `expire_a_lock`, `find_a_bug`,
`hand_off_leadership`, `pick_the_spread`, `join_as_a_learner`, `stress_the_network`,
`a_healthy_looking_lie`, `drop_a_durable_field`, `restart_in_order`,
`count_the_messages`, `cover_two_shapes`, `check_every_scenario`, and others.

## Layout

- `rsm/` the package itself
- `rsm/verify/` the verification organ, a set of measured claims about the
  package as a whole rather than unit tests of one function
- `tests/` the test suite
- `examples/` runnable end to end scenarios

## Notes

Every example is checked to import cleanly, expose `main()`, and explain itself in a
docstring; a handful of the cheaper ones are also run end to end and checked for
output. The rest check their own measurement with a `raise SystemExit` at the bottom,
so running the example is itself the check. Where a guess about behaviour was refuted
by measurement, the wrong guess is kept in the source beside the measured value rather
than deleted.
