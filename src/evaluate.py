"""
Evaluation harness for the VibeFinder assistant.

Runs every case in data/evaluation_cases.json through the full assistant
and prints a pass/fail report. Each case holds a request and what a
reasonable listener would expect back (the status, the kind of song on top,
what must not appear, how confident the answer may be).

Run from the project root with:

    python -m src.evaluate                  # report for the full system
    python -m src.evaluate --baseline       # also compare against a songs-only knowledge base
    python -m src.evaluate --json out.json  # also save machine-readable results
    python -m src.evaluate --strict         # exit with code 1 if any case fails

The report measures three things:

    accuracy     how many cases meet their expectations
    consistency  whether running the same request twice gives the same answer
    calibration  whether confidence is higher on passed cases than on failed ones
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.app_logging import configure_logging, get_logger
from src.assistant import STATUS_ANSWERED, AssistantResponse, MusicAssistant
from src.table_format import format_table

logger = get_logger("evaluate")

DEFAULT_CASES_PATH = "data/evaluation_cases.json"
RESULT_COUNT = 5

# How many top results the "top_three_moods_in" expectation looks at
TOP_MOODS_TO_CHECK = 3

# Every expectation key a case may use. An unknown key is an error, so a typo
# in the cases file cannot silently turn into a check that always passes.
KNOWN_EXPECTATION_KEYS = {
    "status", "status_in",
    "top_genre_in", "top_mood_in", "top_title", "top_artist", "top_three_moods_in",
    "min_top_energy", "max_top_energy", "min_top_instrumentalness",
    "forbidden_genres", "forbidden_moods", "genres_in_results_include",
    "was_revised", "min_confidence", "max_confidence", "must_not_set_genre",
}


@dataclass
class CaseResult:
    """The outcome of running one evaluation case."""
    case_id: str
    category: str
    request: str
    status: str
    confidence: float
    top_title: str
    passed: bool
    failures: List[str] = field(default_factory=list)   # why the case failed, if it did
    is_consistent: bool = True                           # same answer on a second run


def load_cases(cases_path: str = DEFAULT_CASES_PATH) -> List[Dict]:
    """Read the evaluation cases and validate their structure."""
    with open(cases_path, encoding="utf-8") as cases_file:
        cases = json.load(cases_file)

    seen_ids = set()
    for case in cases:
        for required_field in ("id", "category", "request", "expect"):
            if required_field not in case:
                raise ValueError(f"Evaluation case {case} is missing '{required_field}'")
        if case["id"] in seen_ids:
            raise ValueError(f"Duplicate evaluation case id: {case['id']}")
        seen_ids.add(case["id"])

        unknown_keys = set(case["expect"]) - KNOWN_EXPECTATION_KEYS
        if unknown_keys:
            raise ValueError(f"Case '{case['id']}' uses unknown expectation(s): {sorted(unknown_keys)}")
    return cases


def find_expectation_failures(response: AssistantResponse, expectations: Dict) -> List[str]:
    """Compare a response with a case's expectations and return every mismatch."""
    failures = []
    recommendations = response.recommendations
    top_song = recommendations[0].song if recommendations else None

    # --- Status ---------------------------------------------------------------
    if "status" in expectations and response.status != expectations["status"]:
        failures.append(f"status was {response.status}, expected {expectations['status']}")
    if "status_in" in expectations and response.status not in expectations["status_in"]:
        failures.append(f"status was {response.status}, expected one of {expectations['status_in']}")

    # --- Expectations about the top pick --------------------------------------
    top_pick_keys = {
        "top_genre_in", "top_mood_in", "top_title", "top_artist",
        "min_top_energy", "max_top_energy", "min_top_instrumentalness",
    }
    if top_song is None:
        if top_pick_keys & set(expectations):
            failures.append("no songs were recommended")
    else:
        if "top_genre_in" in expectations and top_song["genre"] not in expectations["top_genre_in"]:
            failures.append(f"top genre was {top_song['genre']}, expected one of {expectations['top_genre_in']}")
        if "top_mood_in" in expectations and top_song["mood"] not in expectations["top_mood_in"]:
            failures.append(f"top mood was {top_song['mood']}, expected one of {expectations['top_mood_in']}")
        if "top_title" in expectations and top_song["title"] != expectations["top_title"]:
            failures.append(f"top song was \"{top_song['title']}\", expected \"{expectations['top_title']}\"")
        if "top_artist" in expectations and top_song["artist"] != expectations["top_artist"]:
            failures.append(f"top artist was {top_song['artist']}, expected {expectations['top_artist']}")
        if "min_top_energy" in expectations and top_song["energy"] < expectations["min_top_energy"]:
            failures.append(f"top energy {top_song['energy']} is below {expectations['min_top_energy']}")
        if "max_top_energy" in expectations and top_song["energy"] > expectations["max_top_energy"]:
            failures.append(f"top energy {top_song['energy']} is above {expectations['max_top_energy']}")
        if "min_top_instrumentalness" in expectations:
            instrumentalness = top_song.get("instrumentalness") or 0.0
            if instrumentalness < expectations["min_top_instrumentalness"]:
                failures.append(
                    f"top instrumentalness {instrumentalness} is below "
                    f"{expectations['min_top_instrumentalness']}"
                )

    # --- Expectations about the whole list ------------------------------------
    if "top_three_moods_in" in expectations:
        top_moods = [result.song["mood"] for result in recommendations[:TOP_MOODS_TO_CHECK]]
        unexpected_moods = [mood for mood in top_moods if mood not in expectations["top_three_moods_in"]]
        if unexpected_moods or len(top_moods) < TOP_MOODS_TO_CHECK:
            failures.append(f"top three moods were {top_moods}, expected only {expectations['top_three_moods_in']}")

    recommended_genres = {result.song["genre"] for result in recommendations}
    recommended_moods = {result.song["mood"] for result in recommendations}
    for forbidden_genre in expectations.get("forbidden_genres", []):
        if forbidden_genre in recommended_genres:
            failures.append(f"a {forbidden_genre} song was recommended")
    for forbidden_mood in expectations.get("forbidden_moods", []):
        if forbidden_mood in recommended_moods:
            failures.append(f"a {forbidden_mood} song was recommended")
    for wanted_genre in expectations.get("genres_in_results_include", []):
        if wanted_genre not in recommended_genres:
            failures.append(f"no {wanted_genre} song was recommended")

    # --- Expectations about the assistant's own behavior ----------------------
    if "was_revised" in expectations and response.was_revised != expectations["was_revised"]:
        failures.append(f"was_revised was {response.was_revised}, expected {expectations['was_revised']}")
    if "min_confidence" in expectations and response.confidence < expectations["min_confidence"]:
        failures.append(f"confidence {response.confidence:.2f} is below {expectations['min_confidence']}")
    if "max_confidence" in expectations and response.confidence > expectations["max_confidence"]:
        failures.append(f"confidence {response.confidence:.2f} is above {expectations['max_confidence']}")
    if expectations.get("must_not_set_genre") and response.plan is not None:
        chosen_genre = response.plan.originally_requested_genre or response.plan.preferences.get("genre")
        if chosen_genre:
            failures.append(f"the request was read as asking for the genre \"{chosen_genre}\"")

    return failures


def response_fingerprint(response: AssistantResponse) -> tuple:
    """Return the parts of a response that must be identical between two runs."""
    return (
        response.status,
        response.confidence,
        response.message,
        tuple((result.song["id"], result.score) for result in response.recommendations),
    )


def run_evaluation(assistant: MusicAssistant, cases: List[Dict]) -> List[CaseResult]:
    """Run every case twice (to check consistency) and score it against its expectations."""
    results = []
    for case in cases:
        first_response = assistant.answer(case["request"], result_count=RESULT_COUNT)
        second_response = assistant.answer(case["request"], result_count=RESULT_COUNT)

        failures = find_expectation_failures(first_response, case["expect"])
        top_title = first_response.recommendations[0].song["title"] if first_response.recommendations else "-"
        result = CaseResult(
            case_id=case["id"],
            category=case["category"],
            request=case["request"],
            status=first_response.status,
            confidence=first_response.confidence,
            top_title=top_title,
            passed=not failures,
            failures=failures,
            is_consistent=response_fingerprint(first_response) == response_fingerprint(second_response),
        )
        results.append(result)
        logger.info("Evaluation case %s: %s %s", case["id"], "PASS" if result.passed else "FAIL", failures)
    return results


def average(values: List[float]) -> Optional[float]:
    """Return the mean of a list, or None when the list is empty."""
    return round(sum(values) / len(values), 2) if values else None


def summarize(results: List[CaseResult]) -> Dict:
    """Compute the headline numbers for a list of case results."""
    passed_results = [result for result in results if result.passed]
    answered_results = [result for result in results if result.status == STATUS_ANSWERED]

    passed_by_category: Dict[str, List[int]] = {}
    for result in results:
        passed_count, total_count = passed_by_category.setdefault(result.category, [0, 0])
        passed_by_category[result.category] = [passed_count + int(result.passed), total_count + 1]

    return {
        "total_cases": len(results),
        "passed_cases": len(passed_results),
        "pass_rate": round(len(passed_results) / len(results), 2) if results else 0.0,
        "consistent_cases": sum(1 for result in results if result.is_consistent),
        "passed_by_category": passed_by_category,
        "average_confidence_answered": average([result.confidence for result in answered_results]),
        "average_confidence_passed": average([r.confidence for r in answered_results if r.passed]),
        "average_confidence_failed": average([r.confidence for r in answered_results if not r.passed]),
    }


def shorten(text: str, max_length: int) -> str:
    """Trim long text for a table cell."""
    return text if len(text) <= max_length else text[: max_length - 3] + "..."


def format_report(results: List[CaseResult], baseline_results: Optional[List[CaseResult]] = None) -> str:
    """Build the full text report."""
    summary = summarize(results)
    lines = ["VibeFinder evaluation report", "============================", ""]

    table_rows = [
        [
            result.case_id,
            result.category,
            shorten(result.request, 44) or "(empty)",
            result.status,
            f"{result.confidence:.2f}",
            shorten(result.top_title, 22),
            "PASS" if result.passed else "FAIL",
        ]
        for result in results
    ]
    lines.append(format_table(
        ["Case", "Category", "Request", "Status", "Conf.", "Top song", "Result"], table_rows,
        max_widths=[24, 12, 44, 10, 5, 22, 6],
    ))
    lines.append("")

    lines.append("Summary")
    lines.append("-------")
    lines.append(
        f"Passed: {summary['passed_cases']} of {summary['total_cases']} cases "
        f"({summary['pass_rate']:.0%})"
    )
    category_parts = [
        f"{category} {passed}/{total}" for category, (passed, total) in summary["passed_by_category"].items()
    ]
    lines.append("By category: " + ", ".join(category_parts))
    lines.append(
        f"Consistency: {summary['consistent_cases']} of {summary['total_cases']} cases "
        f"gave an identical answer when run twice"
    )
    lines.append(
        f"Confidence (answered cases): average {summary['average_confidence_answered']}, "
        f"passed cases {summary['average_confidence_passed']}, "
        f"failed cases {summary['average_confidence_failed']}"
    )

    failed_results = [result for result in results if not result.passed]
    if failed_results:
        lines.append("")
        lines.append("Failed cases")
        lines.append("------------")
        for result in failed_results:
            lines.append(f"- {result.case_id} (\"{result.request}\"): " + "; ".join(result.failures))

    if baseline_results is not None:
        baseline_summary = summarize(baseline_results)
        lines.append("")
        lines.append("Baseline comparison (songs-only knowledge base, no guides)")
        lines.append("----------------------------------------------------------")
        lines.append(
            f"Full knowledge base: {summary['passed_cases']} of {summary['total_cases']} passed. "
            f"Songs-only baseline: {baseline_summary['passed_cases']} of {baseline_summary['total_cases']} passed."
        )
        baseline_passed_by_id = {result.case_id: result.passed for result in baseline_results}
        fixed_by_guides = [
            result.case_id for result in results
            if result.passed and not baseline_passed_by_id.get(result.case_id, False)
        ]
        lost_with_guides = [
            result.case_id for result in results
            if not result.passed and baseline_passed_by_id.get(result.case_id, False)
        ]
        lines.append(f"Cases that only pass with the guides ({len(fixed_by_guides)}): "
                     + (", ".join(fixed_by_guides) or "none"))
        lines.append(f"Cases that only pass without the guides ({len(lost_with_guides)}): "
                     + (", ".join(lost_with_guides) or "none"))

    return "\n".join(lines)


def parse_arguments() -> argparse.Namespace:
    """Read the command line options for the evaluation run."""
    parser = argparse.ArgumentParser(description="Evaluate the VibeFinder assistant")
    parser.add_argument("--cases", default=DEFAULT_CASES_PATH, help="path to the evaluation cases JSON file")
    parser.add_argument("--baseline", action="store_true",
                        help="also run a songs-only knowledge base to measure what the guides add")
    parser.add_argument("--json", metavar="PATH", help="also write the results as JSON to this file")
    parser.add_argument("--strict", action="store_true", help="exit with code 1 when any case fails")
    return parser.parse_args()


def main() -> None:
    """Run the evaluation and print the report."""
    arguments = parse_arguments()
    configure_logging()

    cases = load_cases(arguments.cases)
    results = run_evaluation(MusicAssistant.from_files(), cases)

    baseline_results = None
    if arguments.baseline:
        baseline_results = run_evaluation(MusicAssistant.from_files(include_guides=False), cases)

    print(format_report(results, baseline_results))

    if arguments.json:
        json_payload = {
            "summary": summarize(results),
            "cases": [result.__dict__ for result in results],
        }
        if baseline_results is not None:
            json_payload["baseline_summary"] = summarize(baseline_results)
        with open(arguments.json, "w", encoding="utf-8") as json_file:
            json.dump(json_payload, json_file, indent=2)
        print(f"\nJSON results written to {arguments.json}")

    if arguments.strict and any(not result.passed for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
