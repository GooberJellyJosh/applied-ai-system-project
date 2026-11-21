"""
Response writer for the VibeFinder assistant.

Turns a plan and a ranked list of songs into the explanation the listener
reads. Every sentence is built from retrieved knowledge base documents and
from the scoring reasons, never from outside knowledge.

Two writers are available:

    TemplateSummaryWriter        always available, no network, fully repeatable
    LanguageModelSummaryWriter   optional; asks a Claude model to phrase the
                                 same facts more naturally

The language model never sees the listener's raw text. It only receives the
structured plan and the retrieved evidence, so instructions hidden in a
request cannot reach it. Its output is still verified by the self-check, and
the template writer is used whenever the model is unavailable or fails.
"""

import json
import os
import re
from typing import Dict, List, Optional

from src.app_logging import get_logger
from src.knowledge_base import ACTIVITY_TYPE, GENRE_TYPE, MOOD_TYPE, KnowledgeBase
from src.knowledge_ranker import RankedSong
from src.request_planner import RequestPlan

logger = get_logger("writer")

# Order in which preferences are shown, with a readable label for each
PREFERENCE_LABELS = [
    ("genre", "genre"),
    ("mood", "mood"),
    ("energy", "energy"),
    ("likes_acoustic", "acoustic sound"),
    ("instrumentalness", "instrumentalness"),
    ("tempo_bpm", "tempo (BPM)"),
    ("danceability", "danceability"),
    ("valence", "positivity"),
    ("popularity", "popularity"),
    ("speechiness", "speechiness"),
    ("mood_tags", "mood tags"),
    ("decade", "decade"),
]

# Guide types quoted as the "why" behind a plan, most specific first
GUIDE_TYPES_TO_QUOTE = (ACTIVITY_TYPE, MOOD_TYPE, GENRE_TYPE)

# Removes the "(+1.50)" point values from a scoring reason for the prose summary
POINTS_SUFFIX_PATTERN = re.compile(r"\s*\([+-]\d+\.\d+\)")

# How many reasons are quoted for the top pick in the summary sentence
TOP_PICK_REASONS_IN_SUMMARY = 3

# Settings for the optional language model writer
DEFAULT_LANGUAGE_MODEL = "claude-opus-5-5"
LANGUAGE_MODEL_ENVIRONMENT_VARIABLE = "VIBEFINDER_MODEL"
LANGUAGE_MODEL_MAX_TOKENS = 16000

LANGUAGE_MODEL_SYSTEM_PROMPT = (
    "You write the short explanation shown next to a music recommender's results. "
    "You are given a JSON object with the listener's interpreted preferences, notes "
    "retrieved from the app's knowledge base, and the ranked songs with the reasons "
    "each one scored well. Write two to four plain sentences that explain why the top "
    "song fits and mention one or two of the other ranked songs. Use only facts found "
    "in the JSON. Refer to songs by their exact titles, and never mention a song or "
    "artist that is not in the ranked list. Do not use lists, headings, or markdown."
)


def format_preference_value(preference_name: str, value) -> str:
    """Format one preference value for display."""
    if preference_name == "likes_acoustic":
        return "preferred" if value else "avoided"
    if preference_name == "mood_tags":
        return ", ".join(value)
    if preference_name == "decade":
        return f"{value}s"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def describe_interpretation(plan: RequestPlan) -> List[str]:
    """Return one line per preference, saying what was understood and where it came from."""
    lines = []
    for preference_name, label in PREFERENCE_LABELS:
        if preference_name not in plan.preferences:
            continue
        line = f"{label}: {format_preference_value(preference_name, plan.preferences[preference_name])}"
        evidence = plan.evidence_for(preference_name)
        if evidence is not None:
            line += f"  <- {evidence.how_found} [{evidence.source_doc_id}]"
        else:
            line += "  <- read directly from the request"
        lines.append(line)
    return lines


def find_guide_note(plan: RequestPlan, knowledge_base: KnowledgeBase) -> Optional[str]:
    """Return the most specific retrieved guide sentence that supports the plan, if any."""
    evidence_doc_ids = [evidence.source_doc_id for evidence in plan.evidence]
    for guide_type in GUIDE_TYPES_TO_QUOTE:
        for doc_id in evidence_doc_ids:
            document = knowledge_base.get(doc_id)
            if document is not None and document.doc_type == guide_type:
                return document.summary
    return None


def strip_points(reason: str) -> str:
    """Remove the point value from a scoring reason, e.g. "genre match: pop (+2.00)" -> "genre match: pop"."""
    return POINTS_SUFFIX_PATTERN.sub("", reason)


class TemplateSummaryWriter:
    """Builds the explanation from fixed sentence templates filled with retrieved facts."""

    name = "template"

    def write_summary(
        self, plan: RequestPlan, ranked_songs: List[RankedSong], knowledge_base: KnowledgeBase
    ) -> str:
        """Write a short grounded explanation of the recommendations."""
        sentences = []

        # Sentence 1: what the assistant understood
        described_preferences = []
        if "mood" in plan.preferences:
            described_preferences.append(plan.preferences["mood"])
        if "genre" in plan.preferences:
            described_preferences.append(plan.preferences["genre"])
        if not plan.preferences:
            # Nothing to aim for, e.g. a request that only lists what to avoid
            sentences.append("I did not find a genre, mood, or activity to aim for in that request.")
        else:
            style_description = " ".join(described_preferences) if described_preferences else "music"
            opening = f"I looked for {style_description}"
            if "energy" in plan.preferences:
                opening += f" around energy {plan.preferences['energy']:g}"
            sentences.append(opening + ".")

        # Sentence 2: the retrieved guide that shaped the plan
        guide_note = find_guide_note(plan, knowledge_base)
        if guide_note:
            sentences.append(f"The knowledge base says: {guide_note}")

        # Honest caveats about substitutions and exclusions
        if plan.originally_requested_genre:
            if "genre" in plan.preferences:
                sentences.append(
                    f"The catalog has no {plan.originally_requested_genre} songs, so I used "
                    f"{plan.preferences['genre']}, the closest genre the knowledge base lists."
                )
            else:
                sentences.append(
                    f"The catalog has no {plan.originally_requested_genre} songs or close relatives, "
                    f"so these picks are based on mood and energy only."
                )
        excluded_names = plan.excluded_genres + plan.excluded_moods
        if excluded_names:
            sentences.append(f"I left out anything {' or '.join(excluded_names)}, as you asked.")

        # The top pick and why, followed by the runners-up
        if ranked_songs:
            top_result = ranked_songs[0]
            top_reasons = "; ".join(
                strip_points(reason) for reason in top_result.reasons[:TOP_PICK_REASONS_IN_SUMMARY]
            )
            sentences.append(
                f"The best match is \"{top_result.song['title']}\" by {top_result.song['artist']} "
                f"({top_reasons})."
            )
            runner_up_titles = [f"\"{result.song['title']}\"" for result in ranked_songs[1:3]]
            if runner_up_titles:
                sentences.append(f"Also worth a listen: {' and '.join(runner_up_titles)}.")

        return " ".join(sentences)


class LanguageModelSummaryWriter:
    """Asks a Claude model to phrase the grounded facts as a natural explanation."""

    name = "language_model"

    def __init__(self, client=None, model_name: Optional[str] = None):
        # The client can be passed in (the tests use a fake one). Otherwise it is
        # created on first use so the app still starts when the SDK is not installed.
        self._client = client
        self.model_name = model_name or os.environ.get(
            LANGUAGE_MODEL_ENVIRONMENT_VARIABLE, DEFAULT_LANGUAGE_MODEL
        )

    def _get_client(self):
        """Create the Anthropic client the first time it is needed."""
        if self._client is None:
            import anthropic  # imported here so the SDK stays an optional dependency
            self._client = anthropic.Anthropic()  # reads credentials from the environment
        return self._client

    def build_context(
        self, plan: RequestPlan, ranked_songs: List[RankedSong], knowledge_base: KnowledgeBase
    ) -> Dict:
        """Collect the structured facts the model is allowed to use (no raw request text)."""
        guide_notes = []
        for evidence in plan.evidence:
            document = knowledge_base.get(evidence.source_doc_id)
            if document is not None and document.summary not in guide_notes:
                guide_notes.append(document.summary)

        return {
            "interpreted_preferences": plan.preferences,
            "excluded": plan.excluded_genres + plan.excluded_moods,
            "requested_genre_missing_from_catalog": plan.originally_requested_genre,
            "knowledge_base_notes": guide_notes,
            "ranked_songs": [
                {
                    "rank": rank,
                    "title": result.song["title"],
                    "artist": result.song["artist"],
                    "genre": result.song["genre"],
                    "mood": result.song["mood"],
                    "reasons": [strip_points(reason) for reason in result.reasons],
                }
                for rank, result in enumerate(ranked_songs, start=1)
            ],
        }

    def write_summary(
        self,
        plan: RequestPlan,
        ranked_songs: List[RankedSong],
        knowledge_base: KnowledgeBase,
        feedback: Optional[str] = None,
    ) -> str:
        """
        Return the model's explanation. Raises an exception when the model
        cannot be reached or declines, so the caller can fall back to the template.

        feedback carries the self-check failures from a previous draft so the
        model can correct them on a retry.
        """
        context = self.build_context(plan, ranked_songs, knowledge_base)
        user_message = "Write the explanation for this result:\n" + json.dumps(context, indent=2)
        if feedback:
            user_message += f"\n\nYour previous draft was rejected for these reasons: {feedback}"

        response = self._get_client().messages.create(
            model=self.model_name,
            max_tokens=LANGUAGE_MODEL_MAX_TOKENS,
            system=LANGUAGE_MODEL_SYSTEM_PROMPT,
            output_config={"effort": "low"},  # a short rewrite does not need deep reasoning
            messages=[{"role": "user", "content": user_message}],
        )

        # Anything other than a normal finish (a refusal, a cut-off) is treated as a failure
        if response.stop_reason != "end_turn":
            raise RuntimeError(f"language model stopped early: {response.stop_reason}")

        summary_text = " ".join(
            block.text.strip() for block in response.content if block.type == "text"
        ).strip()
        if not summary_text:
            raise RuntimeError("language model returned no text")

        logger.info("Language model %s wrote a %d-character summary", self.model_name, len(summary_text))
        return summary_text
