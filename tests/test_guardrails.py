"""Tests for the input guardrails and the logging setup."""

import logging

from src.app_logging import LOG_FILE_NAME, configure_logging, get_logger
from src.guardrails import (
    MAX_REQUEST_LENGTH,
    REASON_EMPTY,
    REASON_NO_WORDS,
    REASON_OK,
    REASON_TOO_LONG,
    check_request,
    clamp_preferences,
    clamp_result_count,
)


def test_normal_request_is_allowed_and_cleaned():
    result = check_request("  calm   music\tfor studying \n")

    assert result.is_allowed
    assert result.reason_code == REASON_OK
    assert result.cleaned_text == "calm music for studying"


def test_empty_and_missing_requests_are_rejected():
    for bad_request in ("", "    ", "\n\t", None):
        result = check_request(bad_request)
        assert not result.is_allowed
        assert result.reason_code == REASON_EMPTY
        assert result.message  # the user is told what to do instead


def test_overlong_request_is_rejected():
    result = check_request("la " * MAX_REQUEST_LENGTH)

    assert not result.is_allowed
    assert result.reason_code == REASON_TOO_LONG


def test_request_without_letters_is_rejected():
    result = check_request("12345 !!! ???")

    assert not result.is_allowed
    assert result.reason_code == REASON_NO_WORDS


def test_result_count_is_clamped_with_a_warning():
    assert clamp_result_count(5, catalog_size=20) == (5, None)

    too_many, warning_for_too_many = clamp_result_count(500, catalog_size=20)
    assert too_many == 10
    assert warning_for_too_many is not None

    too_few, warning_for_too_few = clamp_result_count(0, catalog_size=20)
    assert too_few == 1
    assert warning_for_too_few is not None


def test_result_count_never_exceeds_a_tiny_catalog():
    safe_count, warning = clamp_result_count(5, catalog_size=3)

    assert safe_count == 3
    assert warning is not None


def test_out_of_range_preferences_are_clamped():
    safe_preferences, warnings = clamp_preferences({"genre": "classical", "energy": 1.5, "tempo_bpm": 10})

    assert safe_preferences["energy"] == 1.0
    assert safe_preferences["tempo_bpm"] == 40.0
    assert safe_preferences["genre"] == "classical"  # non-numeric fields are untouched
    assert len(warnings) == 2


def test_non_numeric_targets_are_dropped():
    safe_preferences, warnings = clamp_preferences({"energy": "loud", "valence": 0.5})

    assert "energy" not in safe_preferences
    assert safe_preferences["valence"] == 0.5
    assert len(warnings) == 1


def test_valid_preferences_pass_through_unchanged():
    original_preferences = {"genre": "pop", "energy": 0.8, "likes_acoustic": True}
    safe_preferences, warnings = clamp_preferences(original_preferences)

    assert safe_preferences == original_preferences
    assert warnings == []


def test_logging_writes_to_a_file(tmp_path):
    configure_logging(log_dir=str(tmp_path))
    get_logger("test").info("hello from the test")

    # Flush handlers so the line is on disk before reading it back
    for handler in logging.getLogger("vibefinder").handlers:
        handler.flush()

    log_text = (tmp_path / LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "hello from the test" in log_text
    assert "vibefinder.test" in log_text


def test_configuring_logging_twice_does_not_duplicate_handlers(tmp_path):
    first_logger = configure_logging(log_dir=str(tmp_path))
    handler_count_after_first_call = len(first_logger.handlers)
    second_logger = configure_logging(log_dir=str(tmp_path))

    assert len(second_logger.handlers) == handler_count_after_first_call
