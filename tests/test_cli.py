from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout

import pytest

from rsm.cli import main as terminal
from rsm.cli.main import (
    COMMANDS,
    OK,
    REFUSED,
    _pairs,
    _render,
    _short,
    _table,
    build_parser,
    main,
    run_measure,
)


def run(argv: list[str]) -> tuple[int, str]:
    """Run one command and capture what it printed."""
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


def test_the_parser_matches_the_command_table():
    assert terminal.the_parser_covers_every_command()["they_match"]


def test_every_command_has_a_handler():
    assert terminal.the_parser_covers_every_command()["every_command_has_a_handler"]


def test_every_command_has_a_help_line():
    assert terminal.the_parser_covers_every_command()["and_a_help_line"]


def test_the_cluster_command_finds_a_leader():
    assert terminal.a_cluster_command_reports_a_leader()["it_has_one"]


def test_the_cluster_command_succeeds():
    assert terminal.a_cluster_command_reports_a_leader()["it_succeeded"]


def test_the_cluster_command_commits():
    assert terminal.a_cluster_command_reports_a_leader()["and_it_committed"]


def test_a_refusal_is_an_exit_code():
    assert terminal.a_refusal_is_an_exit_code_and_not_a_traceback()["it_refused"]


def test_a_refusal_differs_from_success():
    assert terminal.a_refusal_is_an_exit_code_and_not_a_traceback()["which_is_different"]


def test_the_json_flag_round_trips():
    assert terminal.the_json_flag_produces_parseable_output()["it_parses"]


def test_the_table_form_is_different():
    assert terminal.the_json_flag_produces_parseable_output()["and_the_table_form_differs"]


def test_the_table_has_no_braces():
    assert terminal.the_json_flag_produces_parseable_output()["the_table_has_no_braces"]


def test_a_table_has_a_header():
    assert terminal.a_table_aligns_its_columns()["it_has_a_header"]


def test_a_table_has_a_row_per_entry():
    assert terminal.a_table_aligns_its_columns()["and_a_row_per_entry"]


def test_a_table_lines_up_its_columns():
    assert terminal.a_table_aligns_its_columns()["the_columns_line_up"]


def test_an_empty_table_says_something():
    assert terminal.an_empty_table_says_so()["it_says_something"]


def test_an_empty_mapping_says_something():
    assert terminal.an_empty_table_says_so()["and_so_does_the_other_one"]


def test_every_command_runs():
    assert terminal.every_command_runs()["they_all_succeeded"]


def test_every_command_was_tried():
    assert terminal.every_command_runs()["and_every_command_was_tried"]


def test_the_measure_command_covers_the_modules():
    assert terminal.the_measure_command_covers_every_summarising_module()[
        "it_covers_at_least_twenty"
    ]


def test_every_measured_row_names_a_module():
    assert terminal.the_measure_command_covers_every_summarising_module()[
        "every_row_names_a_module"
    ]


def test_every_measured_row_has_claims():
    assert terminal.the_measure_command_covers_every_summarising_module()[
        "and_reports_its_claims"
    ]


def test_the_total_claims_are_many():
    assert terminal.the_measure_command_covers_every_summarising_module()["total_claims"] > 100


def test_an_unknown_command_is_refused():
    assert terminal.an_unknown_command_is_refused()


def test_no_command_is_refused():
    assert terminal.no_command_at_all_is_refused()


def test_the_command_table_lists_every_command():
    assert len(terminal.compare_the_commands()) == len(COMMANDS)


def test_nothing_in_the_cli_computes():
    assert terminal.nothing_in_the_cli_computes_anything()["they_all_delegate"]


def test_the_summary_says_every_command_runs():
    assert terminal.summarise()["every_command_runs"]


def test_the_summary_says_json_round_trips():
    assert terminal.summarise()["json_round_trips"]


def test_the_cluster_command_prints_something():
    code, text = run(["cluster", "--size", "3", "--writes", "2", "--ticks", "20"])
    assert code == OK and text.strip()


def test_the_cluster_command_names_a_leader():
    _, text = run(["cluster", "--size", "3", "--writes", "2", "--ticks", "20"])
    assert "leader" in text


def test_the_json_flag_gives_json():
    _, text = run(["--json", "cluster", "--size", "3", "--writes", "1", "--ticks", "20"])
    assert json.loads(text)["size"] == 3


def test_the_scenario_command_prints_its_schedule():
    _, text = run(["scenario", "--size", "3", "--ticks", "80"])
    assert "seed" in text


def test_the_verify_command_reports_a_row_per_seed():
    _, text = run(["verify", "--seeds", "2", "--size", "3", "--ticks", "60"])
    assert len(text.strip().split("\n")) == 3


def test_the_workload_command_prints_a_table():
    _, text = run(["workload"])
    assert "workload" in text


def test_the_scaling_command_prints_exponents():
    _, text = run(["scaling"])
    assert "exponent" in text


def test_the_baseline_command_records():
    code, text = run(["baseline"])
    assert code == OK and "workloads" in text


def test_the_baseline_command_checks():
    code, text = run(["baseline", "--check"])
    assert code == OK and "clean" in text


def test_the_invariants_command_reports_the_properties():
    _, text = run(["invariants", "--size", "3", "--writes", "2", "--ticks", "20"])
    assert "properties" in text


def test_the_measure_command_prints_a_row_per_module():
    _, text = run(["measure"])
    assert len(text.strip().split("\n")) >= 20


def test_a_bad_size_exits_two():
    code, _ = run(["cluster", "--size", "-1"])
    assert code == REFUSED


def test_a_bad_size_prints_nothing_to_stdout():
    _, text = run(["cluster", "--size", "0"])
    assert text == ""


def test_a_table_of_one_row():
    made = _table([{"a": 1}])
    assert made.split("\n") == ["a", "1"]


def test_a_table_pads_the_header():
    made = _table([{"name": "abcdef"}])
    assert made.split("\n")[0] == "name  "


def test_a_table_handles_a_missing_key():
    made = _table([{"a": 1, "b": 2}, {"a": 3}])
    assert made.split("\n")[2].strip() == "3"


def test_pairs_lists_one_per_line():
    made = _pairs({"a": 1, "b": 2})
    assert len(made.split("\n")) == 2


def test_pairs_aligns_its_names():
    made = _pairs({"a": 1, "bbbb": 2})
    assert made.split("\n")[0].startswith("a   ")


def test_rendering_a_list_gives_a_table():
    assert "a" in _render([{"a": 1}], as_json=False)


def test_rendering_a_mapping_gives_pairs():
    assert "a" in _render({"a": 1}, as_json=False)


def test_rendering_a_string_gives_the_string():
    assert _render("hello", as_json=False) == "hello"


def test_rendering_as_json_gives_json():
    assert json.loads(_render({"a": 1}, as_json=True)) == {"a": 1}


def test_shortening_keeps_three():
    assert len(_short({"a": 1, "b": 2, "c": 3, "d": 4})) == 3


def test_shortening_keeps_the_first_three():
    assert list(_short({"a": 1, "b": 2, "c": 3, "d": 4})) == ["a", "b", "c"]


def test_shortening_a_small_mapping_keeps_it_all():
    assert len(_short({"a": 1})) == 1


def test_the_parser_has_a_json_flag():
    made = build_parser().parse_args(["--json", "workload"])
    assert made.json


def test_the_parser_defaults_to_a_table():
    made = build_parser().parse_args(["workload"])
    assert not made.json


def test_the_parser_takes_a_size():
    assert build_parser().parse_args(["cluster", "--size", "7"]).size == 7


def test_the_parser_takes_a_seed():
    assert build_parser().parse_args(["cluster", "--seed", "9"]).seed == 9


def test_the_parser_takes_a_loss_rate():
    assert build_parser().parse_args(["cluster", "--loss", "0.2"]).loss == 0.2


def test_the_parser_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_measuring_returns_rows():
    assert isinstance(run_measure(argparse.Namespace()), list)


def test_measuring_needs_no_arguments():
    assert len(run_measure()) >= 20


def test_the_success_code_is_zero():
    assert OK == 0


def test_the_refusal_code_is_two():
    assert REFUSED == 2


def test_every_new_command_has_a_handler():
    assert all(callable(one[0]) for one in terminal.COMMANDS.values())


def test_the_command_table_has_grown():
    assert len(terminal.COMMANDS) >= 20


def test_the_parser_still_covers_every_command():
    assert terminal.the_parser_covers_every_command()["they_match"]


def test_the_quorum_command_returns_a_table():
    assert len(terminal.run_quorum(None)) == 25


def test_the_timing_command_returns_a_table():
    assert terminal.run_timing(None)


def test_the_partition_command_returns_a_table():
    assert len(terminal.run_partition(None)) == 7


def test_the_repair_command_returns_a_table():
    assert len(terminal.run_repair(None)) == 16


def test_the_lease_command_returns_a_table():
    assert len(terminal.run_lease(None)) == 4


def test_the_observe_command_returns_a_table():
    assert terminal.run_observe(None)


def test_the_load_command_returns_a_table():
    assert len(terminal.run_load(None)) == 4


def test_the_recovery_command_returns_a_table():
    assert len(terminal.run_recovery(None)) == 5


def test_the_shard_command_returns_a_table():
    assert len(terminal.run_shard(None)) == 4


def test_the_tune_command_returns_a_table():
    assert terminal.run_tune(None)


def test_the_mix_command_takes_a_read_share():
    made = terminal.run_mix(argparse.Namespace(reads=0.5))
    assert all(one["reads"] == 0.5 for one in made)


def test_the_coverage_command_returns_a_table():
    assert terminal.run_coverage(None)


def test_the_report_command_counts_the_findings():
    assert terminal.run_report(None)["findings"] > 100


def test_the_measure_command_covers_every_module():
    assert len(terminal.run_measure(None)) > 40


def test_the_measure_command_names_its_modules():
    assert all(one["module"] for one in terminal.run_measure(None))


def test_a_new_command_runs_end_to_end():
    assert terminal.main(["quorum"]) == terminal.OK


def test_a_new_command_renders_as_json():
    assert terminal.main(["--json", "quorum"]) == terminal.OK
