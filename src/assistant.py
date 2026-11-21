"""
The VibeFinder assistant pipeline.

MusicAssistant.answer() takes a plain-language request and runs it through
every stage of the system:

    1. GUARDRAIL  reject empty, oversized, or wordless input
    2. RETRIEVE   search the knowledge base for relevant documents
    3. PLAN       turn the retrieved knowledge into preferences and a scoring mode
    4. ACT        rank the catalog with the knowledge-aware ranker
    5. CHECK      verify the result; if a check fails, REVISE the plan and try again
    6. SCORE      compute a confidence score
    7. WRITE      explain the result using only retrieved facts

Each stage is recorded in a trace so the reasoning can be inspected, and in
logs/vibefinder.log so a run can be reviewed later.
"""

import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.app_logging import get_logger
from src.guardrails import check_request, clamp_result_count
from src.knowledge_base import DEFAULT_KNOWLEDGE_DIR, KnowledgeBase, load_knowledge_base
from src.knowledge_ranker import RankedSong, rank_songs_with_knowledge
from src.recommender import load_songs
from src.request_planner import RequestPlan, build_request_plan
from src.response_writer import (
    LanguageModelSummaryWriter,
    TemplateSummaryWriter,
    describe_interpretation,
)
from src.retriever import TfidfRetriever
from src.self_check import (
    CHECK_HAS_RESULTS,
    CheckResult,
    check_written_summary,
    compute_confidence,
    failed_check_names,
    propose_revision,
    run_result_checks,
)
from src.table_format import format_table

logger = get_logger("assistant")

DEFAULT_SONGS_CSV_PATH = "data/songs.csv"
DEFAULT_RESULT_COUNT = 5

# The assistant may revise its plan this many times after a failed self-check
MAX_PLAN_REVISIONS = 1
# The language model gets this many tries to write a summary that passes the checks
MAX_SUMMARY_ATTEMPTS = 2

# Response statuses
STATUS_ANSWERED = "answered"      # recommendations were produced
STATUS_REJECTED = "rejected"      # the input guardrail refused the request
STATUS_NO_MATCH = "no_match"      # nothing in the knowledge base relates to the request
STATUS_NO_RESULTS = "no_results"  # every song was ruled out by the request's exclusions
STATUS_ERROR = "error"            # an unexpected failure was caught

NO_MATCH_MESSAGE = (
    "I could not connect that request to anything in my music knowledge base, so I am "
    "not going to guess. Try naming a genre, a mood, or what you are doing, for example "
    "\"upbeat pop for a workout\" or \"quiet music for studying\"."
)
NO_RESULTS_MESSAGE = (
    "Every song in the catalog was ruled out by what you asked me to leave out. "
    "Try excluding fewer genres or moods."
)
ERROR_MESSAGE = (
    "Something went wrong while working on that request. "
    "The details were written to logs/vibefinder.log."
)

SUMMARY_WRAP_WIDTH = 88


@dataclass
class AssistantResponse:
    """Everything the assistant produced for one request."""
    request_text: str
    status: str
    message: str                                          # the summary, or why there is no answer
    recommendations: List[RankedSong] = field(default_factory=list)
    plan: Optional[RequestPlan] = None
    checks: List[CheckResult] = field(default_factory=list)
    confidence: float = 0.0
    confidence_label: str = "none"
    confidence_components: Dict[str, float] = field(default_factory=dict)
    was_revised: bool = False
    summary_writer_name: str = ""                         # "template" or "language_model"
    warnings: List[str] = field(default_factory=list)
    trace: List[str] = field(default_factory=list)        # one line per pipeline step

    @property
    def passed_all_checks(self) -> bool:
        """True when no self-check failed."""
        return not failed_check_names(self.checks)


class MusicAssistant:
    """Answers plain-language music requests using retrieval, planning, and self-checking."""

    def __init__(
        self,
        songs: List[Dict],
        knowledge_base: KnowledgeBase,
        language_model_writer: Optional[LanguageModelSummaryWriter] = None,
    ):
        self.songs = songs
        self.knowledge_base = knowledge_base
        self.retriever = TfidfRetriever(knowledge_base.documents)
        self.template_writer = TemplateSummaryWriter()
        self.language_model_writer = language_model_writer  # None means "template only"

    @classmethod
    def from_files(
        cls,
        songs_csv_path: str = DEFAULT_SONGS_CSV_PATH,
        knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
        include_guides: bool = True,
        use_language_model: bool = False,
    ) -> "MusicAssistant":
        """Build an assistant from the song catalog and the knowledge guide files."""
        songs = load_songs(songs_csv_path)
        knowledge_base = load_knowledge_base(songs, knowledge_dir, include_guides=include_guides)
        language_model_writer = LanguageModelSummaryWriter() if use_language_model else None
        logger.info(
            "Assistant ready: %d songs, %d knowledge documents, language model %s",
            len(songs), len(knowledge_base), "on" if use_language_model else "off",
        )
        return cls(songs, knowledge_base, language_model_writer)

    # -----------------------------------------------------------------------
    # The pipeline
    # -----------------------------------------------------------------------
    def answer(self, raw_request: Optional[str], result_count: int = DEFAULT_RESULT_COUNT) -> AssistantResponse:
        """Run the full pipeline for one request. This method never raises."""
        try:
            return self._answer(raw_request, result_count)
        except Exception:  # the last line of defense: log it and fail with a safe message
            logger.exception("Unexpected error while answering %r", raw_request)
            return AssistantResponse(
                request_text=str(raw_request), status=STATUS_ERROR, message=ERROR_MESSAGE,
                trace=["ERROR: an unexpected failure was caught and logged"],
            )

    def _answer(self, raw_request: Optional[str], result_count: int) -> AssistantResponse:
        """The pipeline itself; answer() wraps it with error handling."""
        trace: List[str] = []
        warnings: List[str] = []

        # --- 1. GUARDRAIL -----------------------------------------------------
        guardrail_result = check_request(raw_request)
        if not guardrail_result.is_allowed:
            logger.warning("Request rejected (%s): %r", guardrail_result.reason_code, raw_request)
            trace.append(f"GUARDRAIL: rejected ({guardrail_result.reason_code})")
            return AssistantResponse(
                request_text=guardrail_result.cleaned_text, status=STATUS_REJECTED,
                message=guardrail_result.message, trace=trace,
            )
        request_text = guardrail_result.cleaned_text
        trace.append("GUARDRAIL: request accepted")
        logger.info("Request accepted: %r", request_text)

        safe_result_count, count_warning = clamp_result_count(result_count, len(self.songs))
        if count_warning:
            warnings.append(count_warning)

        # --- 2. RETRIEVE and 3. PLAN -----------------------------------------
        plan = build_request_plan(request_text, self.knowledge_base, self.retriever, self.songs)
        warnings.extend(plan.warnings)
        retrieved_summary = ", ".join(
            f"{match.document.doc_id} ({match.similarity:.2f})" for match in plan.retrieved_documents[:5]
        )
        trace.append(f"RETRIEVE: {retrieved_summary or 'no documents matched'}")
        trace.append(
            f"PLAN: preferences={plan.preferences}, mode={plan.scoring_mode_name}, "
            f"diversity={'on' if plan.use_diversity else 'off'}"
        )

        # Relevance gate: refuse to guess when the knowledge base found nothing related
        if not plan.is_understood:
            logger.warning(
                "No relevant knowledge for %r (top similarity %.2f, coverage %.2f)",
                request_text, plan.top_similarity, plan.request_coverage,
            )
            trace.append("PLAN: request is not related to the knowledge base, declining to guess")
            return AssistantResponse(
                request_text=request_text, status=STATUS_NO_MATCH, message=NO_MATCH_MESSAGE,
                plan=plan, warnings=warnings, trace=trace,
            )

        # --- 4. ACT and 5. CHECK (with one possible revision) ----------------
        ranked_songs = rank_songs_with_knowledge(plan, self.songs, self.knowledge_base, safe_result_count)
        trace.append("ACT: ranked " + ", ".join(
            f"{result.song['title']} ({result.score:.2f})" for result in ranked_songs
        ))
        checks = run_result_checks(plan, ranked_songs, self.songs, self.knowledge_base, safe_result_count)
        trace.append(self._describe_checks(checks))

        was_revised = False
        for _ in range(MAX_PLAN_REVISIONS):
            if not failed_check_names(checks):
                break
            revision = propose_revision(plan, checks, self.songs, self.knowledge_base)
            if revision is None:
                break  # nothing about the plan can fix the remaining failures
            plan, revision_description = revision
            was_revised = True
            logger.info("Plan revised: %s", revision_description)
            trace.append(f"REVISE: {revision_description}")

            ranked_songs = rank_songs_with_knowledge(plan, self.songs, self.knowledge_base, safe_result_count)
            trace.append("ACT: ranked " + ", ".join(
                f"{result.song['title']} ({result.score:.2f})" for result in ranked_songs
            ))
            checks = run_result_checks(plan, ranked_songs, self.songs, self.knowledge_base, safe_result_count)
            trace.append(self._describe_checks(checks))

        if CHECK_HAS_RESULTS in failed_check_names(checks):
            return AssistantResponse(
                request_text=request_text, status=STATUS_NO_RESULTS, message=NO_RESULTS_MESSAGE,
                plan=plan, checks=checks, was_revised=was_revised, warnings=warnings, trace=trace,
            )

        # --- 6. SCORE ---------------------------------------------------------
        confidence_report = compute_confidence(plan, ranked_songs, checks, was_revised)
        trace.append(
            f"SCORE: confidence {confidence_report.score:.2f} ({confidence_report.label}) "
            f"from {confidence_report.components}"
        )
        if confidence_report.label == "low":
            warnings.append("Low confidence: treat these picks as rough guesses.")
        for check in checks:
            if not check.passed:
                warnings.append(f"Self-check \"{check.name}\" did not pass: {check.detail}.")

        # --- 7. WRITE ---------------------------------------------------------
        summary_text, writer_name = self._write_summary(plan, ranked_songs, trace)

        logger.info(
            "Answered %r: status=%s confidence=%.2f revised=%s writer=%s top=%s",
            request_text, STATUS_ANSWERED, confidence_report.score, was_revised, writer_name,
            ranked_songs[0].song["title"],
        )
        return AssistantResponse(
            request_text=request_text,
            status=STATUS_ANSWERED,
            message=summary_text,
            recommendations=ranked_songs,
            plan=plan,
            checks=checks,
            confidence=confidence_report.score,
            confidence_label=confidence_report.label,
            confidence_components=confidence_report.components,
            was_revised=was_revised,
            summary_writer_name=writer_name,
            warnings=warnings,
            trace=trace,
        )

    @staticmethod
    def _describe_checks(checks: List[CheckResult]) -> str:
        """Summarize a list of check results as one trace line."""
        failed_names = failed_check_names(checks)
        passed_count = len(checks) - len(failed_names)
        line = f"CHECK: {passed_count}/{len(checks)} checks passed"
        if failed_names:
            line += f" (failed: {', '.join(failed_names)})"
        return line

    # -----------------------------------------------------------------------
    # Writing the summary
    # -----------------------------------------------------------------------
    def _write_summary(self, plan: RequestPlan, ranked_songs: List[RankedSong], trace: List[str]):
        """Return (summary text, writer name), preferring the language model when it is enabled."""
        if self.language_model_writer is not None:
            model_summary = self._write_summary_with_language_model(plan, ranked_songs, trace)
            if model_summary is not None:
                trace.append("WRITE: summary written by the language model and verified")
                return model_summary, self.language_model_writer.name
            trace.append("WRITE: language model unavailable or rejected, using the template writer")

        template_summary = self.template_writer.write_summary(plan, ranked_songs, self.knowledge_base)
        if self.language_model_writer is None:
            trace.append("WRITE: summary written by the template writer")
        return template_summary, self.template_writer.name

    def _write_summary_with_language_model(
        self, plan: RequestPlan, ranked_songs: List[RankedSong], trace: List[str]
    ) -> Optional[str]:
        """
        Ask the language model for a summary and verify it. Returns None when
        the model cannot be used, so the caller falls back to the template.
        """
        # The Anthropic SDK is optional. Its error classes are only needed to
        # report a precise reason when a call fails.
        try:
            import anthropic
        except ImportError:
            anthropic = None

        feedback = None
        for attempt_number in range(1, MAX_SUMMARY_ATTEMPTS + 1):
            try:
                draft_summary = self.language_model_writer.write_summary(
                    plan, ranked_songs, self.knowledge_base, feedback=feedback
                )
            except ImportError:
                logger.warning("Language model skipped: install it with 'pip install -r requirements-llm.txt'.")
                return None
            except Exception as error:
                logger.warning("Language model call failed: %s", _describe_model_error(error, anthropic))
                return None

            # CHECK the model's own output before showing it to anyone
            summary_checks = check_written_summary(draft_summary, ranked_songs, self.songs)
            failed_details = [check.detail for check in summary_checks if not check.passed]
            if not failed_details:
                return draft_summary

            feedback = "; ".join(failed_details)
            logger.warning("Language model draft %d rejected: %s", attempt_number, feedback)
            trace.append(f"CHECK: language model draft {attempt_number} rejected ({feedback})")

        return None


def _describe_model_error(error: Exception, anthropic_module) -> str:
    """Return a short, specific description of why a language model call failed."""
    if anthropic_module is not None:
        if isinstance(error, anthropic_module.AuthenticationError):
            return "no valid API credentials were found"
        if isinstance(error, anthropic_module.RateLimitError):
            return "the API rate limit was reached"
        if isinstance(error, anthropic_module.APIStatusError):
            return f"the API returned status {error.status_code}"
        if isinstance(error, anthropic_module.APIConnectionError):
            return "the API could not be reached"
    return f"{type(error).__name__}: {error}"


# ---------------------------------------------------------------------------
# Turning a response into terminal text
# ---------------------------------------------------------------------------
def format_response(response: AssistantResponse, show_trace: bool = False) -> str:
    """Format an AssistantResponse as readable terminal output."""
    lines = [f"Request: {response.request_text}"]

    if response.status != STATUS_ANSWERED:
        lines.append(f"Status: {response.status}")
        lines.append("")
        lines.extend(textwrap.wrap(response.message, SUMMARY_WRAP_WIDTH))
    else:
        lines.append(
            f"Status: {response.status}   |   Confidence: {response.confidence:.2f} "
            f"({response.confidence_label})   |   Summary by: {response.summary_writer_name}"
        )
        lines.append("")
        lines.append("How I read your request:")
        interpretation_lines = describe_interpretation(response.plan)
        lines.extend(f"  - {line}" for line in interpretation_lines or ["no specific preferences found"])
        lines.append("")
        lines.append("Summary:")
        lines.extend(f"  {line}" for line in textwrap.wrap(response.message, SUMMARY_WRAP_WIDTH))
        lines.append("")

        # Reuse the VibeFinder 1.0 table for the ranked songs
        table_rows = []
        for rank, result in enumerate(response.recommendations, start=1):
            song_cell = (
                f"{result.song['title']}\n{result.song['artist']}\n"
                f"{result.song['genre']} / {result.song['mood']}"
            )
            reasons_cell = "\n".join(f"- {reason}" for reason in result.reasons)
            reasons_cell += f"\nsources: {', '.join(result.source_doc_ids)}"
            table_rows.append([str(rank), song_cell, f"{result.score:.2f}", reasons_cell])
        lines.append(format_table(["#", "Song", "Score", "Why (with sources)"], table_rows,
                                  max_widths=[2, 24, 5, 56]))

        failed_names = failed_check_names(response.checks)
        check_line = f"Self-check: {len(response.checks) - len(failed_names)}/{len(response.checks)} checks passed"
        if response.was_revised:
            check_line += " (after revising the plan once)"
        lines.append(check_line)

    for warning in response.warnings:
        lines.append(f"Warning: {warning}")

    if show_trace:
        lines.append("")
        lines.append("Trace:")
        lines.extend(f"  {step_number}. {step}" for step_number, step in enumerate(response.trace, start=1))

    return "\n".join(lines)
