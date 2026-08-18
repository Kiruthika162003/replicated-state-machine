from __future__ import annotations

import pytest

from rsm import report as summary
from rsm.errors import ConfigError
from rsm.report import MODULES, TURNS, Finding, Report, collect


def test_every_module_answers():
    assert summary.every_module_reports_its_findings()["every_one_answered"]


def test_there_are_many_findings():
    assert summary.every_module_reports_its_findings()["and_there_are_many"]


def test_every_module_reports_several():
    assert summary.every_module_reports_its_findings()["per_module"] > 3


def test_no_verdict_is_false():
    assert summary.no_verdict_in_the_package_comes_back_false()["none_of_them_are_false"]


def test_the_report_is_clean():
    assert summary.no_verdict_in_the_package_comes_back_false()["the_report_is_clean"]


def test_nothing_failed_to_answer():
    assert summary.no_verdict_in_the_package_comes_back_false()["and_nothing_failed_to_answer"]


def test_the_corrections_are_about_a_tenth():
    assert summary.one_finding_in_nine_is_a_correction_and_most_modules_have_one()[
        "it_is_about_a_tenth"
    ]


def test_most_modules_have_a_correction():
    assert summary.one_finding_in_nine_is_a_correction_and_most_modules_have_one()[
        "and_most_modules_have_one"
    ]


def test_the_most_corrected_module_is_named():
    made = summary.one_finding_in_nine_is_a_correction_and_most_modules_have_one()
    assert made["the_most_corrected"]


def test_a_report_over_no_modules_is_refused():
    assert summary.a_report_over_no_modules_is_refused()


def test_a_module_without_a_summarise_is_recorded():
    assert summary.a_module_without_a_summarise_is_recorded_rather_than_raised()["one_of_each"]


def test_the_failure_says_why():
    assert summary.a_module_without_a_summarise_is_recorded_rather_than_raised()[
        "the_failure_says_why"
    ]


def test_the_other_module_still_reported():
    assert summary.a_module_without_a_summarise_is_recorded_rather_than_raised()[
        "and_the_other_still_reported"
    ]


def test_an_unimportable_module_is_recorded():
    assert summary.a_module_that_cannot_be_imported_is_recorded_too()["it_recorded_the_import"]


def test_the_import_reason_is_attached():
    assert summary.a_module_that_cannot_be_imported_is_recorded_too()["the_reason_is_attached"]


def test_the_real_module_still_answered():
    assert summary.a_module_that_cannot_be_imported_is_recorded_too()[
        "and_the_real_module_answered"
    ]


def test_verdicts_are_the_majority():
    assert summary.the_findings_are_mostly_verdicts_rather_than_numbers()[
        "verdicts_are_the_majority"
    ]


def test_there_are_numbers_too():
    assert summary.the_findings_are_mostly_verdicts_rather_than_numbers()[
        "and_there_are_numbers_too"
    ]


def test_the_module_table_covers_them_all():
    assert len(summary.compare_the_modules()) == len(MODULES)


def test_the_package_agrees_with_itself():
    assert summary.the_package_agrees_with_itself()["the_report_is_clean"]


def test_nothing_in_the_package_is_false():
    assert summary.the_package_agrees_with_itself()["nothing_is_false"]


def test_every_module_said_something():
    assert summary.the_package_agrees_with_itself()["and_every_module_said_something"]


def test_the_summary_counts_the_modules():
    assert summary.summarise()["modules"] == len(MODULES)


def test_the_summary_says_no_verdict_is_false():
    assert summary.summarise()["no_verdict_is_false"]


def test_a_finding_knows_it_is_a_turn():
    assert Finding(module="m", key="and_it_did_not", value=True).is_turn


def test_a_plain_finding_is_not():
    assert not Finding(module="m", key="it_worked", value=True).is_turn


def test_a_boolean_finding_is_a_verdict():
    assert Finding(module="m", key="k", value=True).is_verdict


def test_a_number_is_not_a_verdict():
    assert not Finding(module="m", key="k", value=3).is_verdict


def test_a_finding_summarises():
    assert Finding(module="m", key="k", value=1).as_dict()["module"] == "m"


def test_a_finding_prints_itself():
    assert "k = 1" in str(Finding(module="m", key="k", value=1))


def test_an_empty_report_is_clean():
    assert Report()


def test_a_report_with_a_false_verdict_is_not():
    made = Report(findings=[Finding(module="m", key="k", value=False)])
    assert not made


def test_a_report_with_a_failure_is_not():
    assert not Report(failed={"m": "no summarise"})


def test_a_report_lists_its_modules():
    made = Report(
        findings=[
            Finding(module="a", key="k", value=1),
            Finding(module="b", key="k", value=1),
            Finding(module="a", key="j", value=1),
        ]
    )
    assert made.modules == ("a", "b")


def test_a_report_filters_by_module():
    made = Report(
        findings=[
            Finding(module="a", key="k", value=1),
            Finding(module="b", key="k", value=1),
        ]
    )
    assert len(made.of("a")) == 1


def test_a_report_collects_its_verdicts():
    made = Report(
        findings=[
            Finding(module="a", key="k", value=True),
            Finding(module="a", key="j", value=4),
        ]
    )
    assert len(made.verdicts) == 1


def test_a_report_collects_its_falsehoods():
    made = Report(
        findings=[
            Finding(module="a", key="k", value=False),
            Finding(module="a", key="j", value=True),
        ]
    )
    assert len(made.falsehoods) == 1


def test_a_report_collects_its_turns():
    made = Report(
        findings=[
            Finding(module="a", key="and_so", value=True),
            Finding(module="a", key="plain", value=True),
        ]
    )
    assert len(made.turns) == 1


def test_a_report_summarises():
    assert Report().as_dict()["clean"]


def test_collecting_one_module_works():
    made = collect(modules=("rsm.quorum",))
    assert made.modules == ("rsm.quorum",)


def test_collecting_records_a_bad_name():
    assert "rsm.nowhere" in collect(modules=("rsm.nowhere",)).failed


def test_collecting_records_a_missing_summarise():
    assert "rsm.errors" in collect(modules=("rsm.errors",)).failed


def test_collecting_nothing_raises():
    with pytest.raises(ConfigError):
        collect(modules=())


def test_the_module_list_has_no_repeats():
    assert len(set(MODULES)) == len(MODULES)


def test_the_module_list_is_long():
    assert len(MODULES) > 30


def test_every_turn_word_ends_with_an_underscore():
    assert all(one.endswith("_") for one in TURNS)
