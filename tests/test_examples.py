from __future__ import annotations

import importlib
import pkgutil

import pytest

import examples
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
