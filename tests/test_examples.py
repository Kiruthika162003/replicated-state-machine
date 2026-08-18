from __future__ import annotations

import importlib
import io
import pkgutil
from contextlib import redirect_stdout

import pytest

import examples
import rsm
from examples.common import bar, pairs, rule, table

SCRIPTS = sorted(
    one.name
    for one in pkgutil.iter_modules(examples.__path__)
    if one.name != "common"
)


def test_there_are_examples():
    assert len(SCRIPTS) >= 8


@pytest.mark.parametrize("name", SCRIPTS)
def test_every_example_imports(name):
    assert importlib.import_module(f"examples.{name}")


@pytest.mark.parametrize("name", SCRIPTS)
def test_every_example_has_a_main(name):
    assert callable(importlib.import_module(f"examples.{name}").main)


@pytest.mark.parametrize("name", SCRIPTS)
def test_every_example_explains_itself(name):
    made = importlib.import_module(f"examples.{name}")
    assert made.__doc__ and "Run with:" in made.__doc__


def test_a_rule_is_a_full_line():
    assert len(rule()) == 78


def test_a_titled_rule_carries_its_title():
    assert "demo" in rule("demo")


def test_a_titled_rule_is_still_a_full_line():
    assert len(rule("demo")) == 78


def test_a_table_has_a_header_and_a_divider():
    made = table([{"a": 1}]).splitlines()
    assert made[0].strip() == "a" and set(made[1].strip()) == {"-"}


def test_a_table_has_a_row_per_mapping():
    assert len(table([{"a": 1}, {"a": 2}]).splitlines()) == 4


def test_a_table_aligns_its_columns():
    made = table([{"a": 1, "b": 2}, {"a": 100, "b": 200}]).splitlines()
    assert len({len(one) for one in made}) == 1


def test_an_empty_table_says_so():
    assert table([]) == "nothing to show"


def test_a_table_takes_an_explicit_column_order():
    assert table([{"a": 1, "b": 2}], columns=["b", "a"]).startswith("b")


def test_a_missing_column_is_blank():
    assert "  " in table([{"a": 1}, {"a": 2, "b": 3}], columns=["a", "b"])


def test_pairs_aligns_its_keys():
    made = pairs({"a": 1, "bbb": 2}).splitlines()
    assert len({len(one) - len(one.lstrip()) for one in made}) == 1


def test_pairs_spells_out_booleans():
    assert pairs({"ok": True}).endswith("yes")


def test_pairs_spells_out_false_too():
    assert pairs({"ok": False}).endswith("no")


def test_pairs_trims_floats():
    assert pairs({"x": 0.500}).endswith("0.5")


def test_an_empty_mapping_says_so():
    assert pairs({}) == "nothing to show"


def test_pairs_can_be_indented():
    assert pairs({"a": 1}, indent="  ").startswith("  ")


def test_a_full_bar_is_all_marks():
    assert bar(1.0, 10) == "#" * 10


def test_an_empty_bar_is_all_dots():
    assert bar(0.0, 10) == "." * 10


def test_a_half_bar_is_half():
    assert bar(0.5, 10).count("#") == 5


def test_a_bar_clamps_above_one():
    assert bar(2.0, 10) == "#" * 10


def test_a_bar_clamps_below_zero():
    assert bar(-1.0, 10) == "." * 10


CHEAP = (
    "check_a_history",
    "grow_the_cluster",
    "elect_a_leader",
    "survive_a_partition",
    "tour",
)


@pytest.mark.parametrize("name", CHEAP)
def test_a_cheap_example_runs_end_to_end(name):
    made = importlib.import_module(f"examples.{name}")
    caught = io.StringIO()
    with redirect_stdout(caught):
        made.main()
    assert caught.getvalue()


@pytest.mark.parametrize("name", CHEAP)
def test_a_cheap_example_prints_a_rule(name):
    made = importlib.import_module(f"examples.{name}")
    caught = io.StringIO()
    with redirect_stdout(caught):
        made.main()
    assert "--" in caught.getvalue()


@pytest.mark.parametrize("name", CHEAP)
def test_a_cheap_example_prints_several_lines(name):
    made = importlib.import_module(f"examples.{name}")
    caught = io.StringIO()
    with redirect_stdout(caught):
        made.main()
    assert len(caught.getvalue().splitlines()) > 10


def test_the_cheap_examples_are_a_subset():
    assert set(CHEAP) <= set(SCRIPTS)


def test_every_example_is_named_as_a_phrase():
    assert sum(1 for one in SCRIPTS if "_" in one) >= len(SCRIPTS) - 1


def test_no_example_shares_a_name_with_a_module():
    assert not (set(SCRIPTS) & set(dir(rsm)))
