"""
Input guardrails for the VibeFinder assistant.

These checks run before any retrieval or scoring happens. They make sure the
system fails safely with a clear message instead of crashing or returning a
confident-looking answer for input it cannot handle.

    check_request()       rejects empty, oversized, or wordless requests
    clamp_result_count()  keeps "how many songs" inside a sensible range
    clamp_preferences()   pulls out-of-range numeric targets back into range
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Longest request the assistant accepts, in characters
MAX_REQUEST_LENGTH = 300

# Fewest and most songs the assistant will return
MIN_RESULT_COUNT = 1
MAX_RESULT_COUNT = 10

# Reason codes reported with a rejected request (also written to the log)
REASON_OK = "ok"
REASON_EMPTY = "empty_request"
REASON_TOO_LONG = "request_too_long"
REASON_NO_WORDS = "no_words"

# Valid range for each numeric preference: (lowest, highest)
PREFERENCE_RANGES: Dict[str, Tuple[float, float]] = {
    "energy": (0.0, 1.0),
    "valence": (0.0, 1.0),
    "danceability": (0.0, 1.0),
    "instrumentalness": (0.0, 1.0),
    "speechiness": (0.0, 1.0),
    "popularity": (0.0, 100.0),
    "tempo_bpm": (40.0, 220.0),
}

# Characters such as tabs, newlines, and other non-printing control codes
CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
REPEATED_SPACE_PATTERN = re.compile(r"\s+")
LETTER_PATTERN = re.compile(r"[A-Za-z]")


@dataclass
class GuardrailResult:
    """The outcome of checking one request."""
    is_allowed: bool    # True when the request may continue through the pipeline
    cleaned_text: str   # the request with control characters and extra spaces removed
    reason_code: str    # one of the REASON_* constants
    message: str        # what to tell the user when the request is rejected


def check_request(raw_request: Optional[str]) -> GuardrailResult:
    """Clean a raw request and decide whether the assistant should handle it."""
    if not isinstance(raw_request, str):
        return GuardrailResult(
            False, "", REASON_EMPTY,
            "Please describe the music you want, for example \"calm music for studying\".",
        )

    # Replace control characters with spaces, then collapse repeated whitespace
    text_without_control_characters = CONTROL_CHARACTER_PATTERN.sub(" ", raw_request)
    cleaned_text = REPEATED_SPACE_PATTERN.sub(" ", text_without_control_characters).strip()

    if not cleaned_text:
        return GuardrailResult(
            False, "", REASON_EMPTY,
            "Please describe the music you want, for example \"calm music for studying\".",
        )

    if len(cleaned_text) > MAX_REQUEST_LENGTH:
        return GuardrailResult(
            False, cleaned_text[:MAX_REQUEST_LENGTH], REASON_TOO_LONG,
            f"That request is too long ({len(cleaned_text)} characters). "
            f"Please keep it under {MAX_REQUEST_LENGTH} characters.",
        )

    if not LETTER_PATTERN.search(cleaned_text):
        return GuardrailResult(
            False, cleaned_text, REASON_NO_WORDS,
            "I could not find any words in that request. "
            "Try describing a genre, a mood, or what you are doing.",
        )

    return GuardrailResult(True, cleaned_text, REASON_OK, "")


def clamp_result_count(requested_count: int, catalog_size: int) -> Tuple[int, Optional[str]]:
    """Return a safe number of songs to recommend, plus a warning when it was changed."""
    highest_allowed = max(MIN_RESULT_COUNT, min(MAX_RESULT_COUNT, catalog_size))
    safe_count = max(MIN_RESULT_COUNT, min(requested_count, highest_allowed))

    if safe_count != requested_count:
        warning = (
            f"Requested {requested_count} songs; showing {safe_count} "
            f"(allowed range is {MIN_RESULT_COUNT} to {highest_allowed})."
        )
        return safe_count, warning
    return safe_count, None


def clamp_preferences(preferences: Dict) -> Tuple[Dict, List[str]]:
    """
    Return a copy of the preferences with numeric targets pulled into range.

    Non-numeric values for a numeric target are dropped. Every change is
    reported as a warning so the user knows their input was adjusted.
    """
    safe_preferences = dict(preferences)
    warnings = []

    for preference_name, (lowest, highest) in PREFERENCE_RANGES.items():
        if preference_name not in safe_preferences:
            continue
        value = safe_preferences[preference_name]

        # bool is a subclass of int in Python, so rule it out explicitly
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            del safe_preferences[preference_name]
            warnings.append(f"Ignored {preference_name}={value!r} because it is not a number.")
            continue

        clamped_value = max(lowest, min(float(value), highest))
        if clamped_value != value:
            safe_preferences[preference_name] = clamped_value
            warnings.append(
                f"{preference_name}={value} is outside {lowest:g}-{highest:g}; "
                f"using {clamped_value:g} instead."
            )

    return safe_preferences, warnings
