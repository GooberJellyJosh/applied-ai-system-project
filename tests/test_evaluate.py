"""Tests for the evaluation harness."""

import json

import pytest

from src.assistant import STATUS_ANSWERED, STATUS_REJECTED
from src.evaluate import (
    DEFAULT_CASES_PATH,
    CaseResult,
    find_expectation_failures,
    format_report,
    load_cases,
    run_evaluation,
    summarize,
)


def test_bundled_cases_file_is_valid():
    cases = load_cases(DEFAULT_CASES_PATH)

    assert len(cases) >= 20
    assert len({case["id"] for case in cases}) == len(cases)


def test_unknown_expectation_key_is_an_error(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([
        {"id": "typo", "category": "test", "request": "jazz", "expect": {"top_genre": "jazz"}},
    ]))

    with pytest.raises(ValueError, match="unknown expectation"):
        load_cases(str(cases_path))


def test_duplicate_case_ids_are_an_error(tmp_path):
    cases_path = tmp_path / "cases.json"
    case = {"id": "same", "category": "test", "request": "jazz", "expect": {"status": "answered"}}
    cases_path.write_text(json.dumps([case, case]))

    with pytest.raises(ValueError, match="Duplicate"):
        load_cases(str(cases_path))


def test_met_expectations_produce_no_failures(assistant):
    response = assistant.answer("some jazz please")

    failures = find_expectation_failures(response, {
        "status": STATUS_ANSWERED, "top_genre_in": ["jazz"], "max_top_energy": 0.5, "min_confidence": 0.5,
    })

    assert failures == []


def test_each_unmet_expectation_is_reported(assistant):
    response = assistant.answer("some jazz please")

    failures = find_expectation_failures(response, {
        "status": STATUS_REJECTED,
        "top_genre_in": ["metal"],
        "min_top_energy": 0.9,
        "forbidden_genres": ["jazz"],
        "was_revised": True,
        "max_confidence": 0.1,
    })

    assert len(failures) == 6


def test_expecting_a_top_song_fails_when_nothing_is_recommended(assistant):
    response = assistant.answer("")  # rejected by the guardrail

    failures = find_expectation_failures(response, {"top_genre_in": ["jazz"]})

    assert failures == ["no songs were recommended"]


def test_run_evaluation_scores_and_checks_consistency(assistant):
    cases = [
        {"id": "passes", "category": "test", "request": "jazz", "expect": {"top_genre_in": ["jazz"]}},
        {"id": "fails", "category": "test", "request": "jazz", "expect": {"top_genre_in": ["metal"]}},
    ]

    results = run_evaluation(assistant, cases)

    assert [result.passed for result in results] == [True, False]
    assert all(result.is_consistent for result in results)
    assert results[1].failures


def test_summary_counts_passes_by_category():
    results = [
        CaseResult("a", "genre", "jazz", STATUS_ANSWERED, 0.9, "Song A", passed=True),
        CaseResult("b", "genre", "rock", STATUS_ANSWERED, 0.5, "Song B", passed=False, failures=["wrong"]),
        CaseResult("c", "guardrail", "", STATUS_REJECTED, 0.0, "-", passed=True),
    ]

    summary = summarize(results)

    assert summary["total_cases"] == 3
    assert summary["passed_cases"] == 2
    assert summary["passed_by_category"] == {"genre": [1, 2], "guardrail": [1, 1]}
    assert summary["average_confidence_passed"] == 0.9   # only answered cases count
    assert summary["average_confidence_failed"] == 0.5


def test_report_lists_failures_and_the_baseline():
    results = [
        CaseResult("good", "genre", "jazz", STATUS_ANSWERED, 0.9, "Song A", passed=True),
        CaseResult("bad", "genre", "rock", STATUS_ANSWERED, 0.5, "Song B", passed=False, failures=["wrong genre"]),
    ]
    baseline_results = [
        CaseResult("good", "genre", "jazz", STATUS_ANSWERED, 0.2, "Song C", passed=False, failures=["x"]),
        CaseResult("bad", "genre", "rock", STATUS_ANSWERED, 0.2, "Song D", passed=False, failures=["x"]),
    ]

    report = format_report(results, baseline_results)

    assert "Passed: 1 of 2 cases (50%)" in report
    assert "- bad (\"rock\"): wrong genre" in report
    assert "Songs-only baseline: 0 of 2 passed" in report
    assert "Cases that only pass with the guides (1): good" in report
