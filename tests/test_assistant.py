"""End-to-end tests for the assistant pipeline."""

import src.assistant as assistant_module
from src.assistant import (
    STATUS_ANSWERED,
    STATUS_ERROR,
    STATUS_NO_MATCH,
    STATUS_NO_RESULTS,
    STATUS_REJECTED,
    MusicAssistant,
    format_response,
)
from src.knowledge_base import load_knowledge_base
from src.response_writer import LanguageModelSummaryWriter


class ScriptedWriter(LanguageModelSummaryWriter):
    """A language model writer that returns prepared drafts instead of calling an API."""

    def __init__(self, drafts):
        super().__init__(client=object(), model_name="scripted")
        self.drafts = list(drafts)
        self.feedback_received = []

    def write_summary(self, plan, ranked_songs, knowledge_base, feedback=None):
        self.feedback_received.append(feedback)
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        # "{top}" lets a test refer to whichever song ranked first
        return draft.replace("{top}", ranked_songs[0].song["title"])


def test_clear_request_is_answered_with_grounded_recommendations(assistant):
    response = assistant.answer("something mellow for late-night studying")

    assert response.status == STATUS_ANSWERED
    assert len(response.recommendations) == 5
    assert response.recommendations[0].song["genre"] == "lofi"
    assert response.passed_all_checks
    assert response.confidence_label == "high"
    assert response.summary_writer_name == "template"
    assert response.recommendations[0].song["title"] in response.message


def test_retrieved_knowledge_changes_the_ranking(assistant):
    """The same catalog gives different answers depending on what was retrieved."""
    study_titles = [result.song["title"] for result in assistant.answer("music for studying").recommendations]
    gym_titles = [result.song["title"] for result in assistant.answer("music for the gym").recommendations]

    assert set(study_titles).isdisjoint(gym_titles)


def test_empty_request_is_rejected_by_the_guardrail(assistant):
    response = assistant.answer("   ")

    assert response.status == STATUS_REJECTED
    assert response.recommendations == []
    assert response.message


def test_unrelated_request_gets_no_guess(assistant):
    response = assistant.answer("what is the capital of France")

    assert response.status == STATUS_NO_MATCH
    assert response.recommendations == []
    assert response.confidence == 0.0


def test_missing_genre_triggers_one_revision(assistant):
    response = assistant.answer("k-pop dance party")

    assert response.status == STATUS_ANSWERED
    assert response.was_revised
    assert response.plan.originally_requested_genre == "k-pop"
    assert response.plan.preferences["genre"] == "pop"
    assert response.passed_all_checks
    assert any(step.startswith("REVISE") for step in response.trace)
    assert "The catalog has no k-pop songs" in response.message


def test_exclusions_are_respected_end_to_end(assistant):
    response = assistant.answer("sad songs for a rainy day but not country", result_count=10)

    assert response.status == STATUS_ANSWERED
    assert all(result.song["genre"] != "country" for result in response.recommendations)


def test_exclusion_only_request_is_answered_with_low_confidence(assistant):
    response = assistant.answer("not pop, not lofi, not rock")

    assert response.status == STATUS_ANSWERED
    assert response.confidence_label == "low"
    assert all(result.song["genre"] not in ("pop", "lofi", "rock") for result in response.recommendations)
    assert any("Low confidence" in warning for warning in response.warnings)


def test_oversized_result_count_is_clamped_with_a_warning(assistant):
    response = assistant.answer("happy pop", result_count=500)

    assert len(response.recommendations) == 10
    assert any("Requested 500 songs" in warning for warning in response.warnings)


def test_same_request_gives_the_same_answer_every_time(assistant):
    first_response = assistant.answer("upbeat pop for a workout")
    second_response = assistant.answer("upbeat pop for a workout")

    first_titles = [result.song["title"] for result in first_response.recommendations]
    second_titles = [result.song["title"] for result in second_response.recommendations]
    assert first_titles == second_titles
    assert first_response.confidence == second_response.confidence
    assert first_response.message == second_response.message


def test_everything_excluded_reports_no_results(songs):
    only_pop_songs = [song for song in songs if song["genre"] == "pop"]
    tiny_assistant = MusicAssistant(only_pop_songs, load_knowledge_base(only_pop_songs))

    response = tiny_assistant.answer("anything but pop")

    assert response.status == STATUS_NO_RESULTS
    assert response.recommendations == []


def test_unexpected_failure_is_caught_and_reported(assistant, monkeypatch):
    def broken_ranker(*arguments, **keyword_arguments):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(assistant_module, "rank_songs_with_knowledge", broken_ranker)

    response = assistant.answer("happy pop")  # must not raise

    assert response.status == STATUS_ERROR
    assert response.recommendations == []


def test_verified_language_model_summary_is_used(songs, knowledge_base):
    writer = ScriptedWriter(["\"{top}\" is the closest match to what you asked for."])
    assistant_with_model = MusicAssistant(songs, knowledge_base, language_model_writer=writer)

    response = assistant_with_model.answer("happy pop")

    assert response.summary_writer_name == "language_model"
    assert "is the closest match" in response.message


def test_bad_language_model_draft_is_retried_with_feedback(songs, knowledge_base):
    writer = ScriptedWriter([
        "You should really hear Iron Cathedral.",          # names a song that was not recommended
        "\"{top}\" is the best fit for an upbeat pop mood.",  # corrected draft
    ])
    assistant_with_model = MusicAssistant(songs, knowledge_base, language_model_writer=writer)

    response = assistant_with_model.answer("happy pop")

    assert response.summary_writer_name == "language_model"
    assert writer.feedback_received[0] is None
    assert "Iron Cathedral" in writer.feedback_received[1]


def test_language_model_that_keeps_failing_falls_back_to_the_template(songs, knowledge_base):
    writer = ScriptedWriter(["Try Iron Cathedral.", "Seriously, Iron Cathedral."])
    assistant_with_model = MusicAssistant(songs, knowledge_base, language_model_writer=writer)

    response = assistant_with_model.answer("happy pop")

    assert response.status == STATUS_ANSWERED
    assert response.summary_writer_name == "template"
    assert "Iron Cathedral" not in response.message


def test_language_model_error_falls_back_to_the_template(songs, knowledge_base):
    writer = ScriptedWriter([ConnectionError("network is down")])
    assistant_with_model = MusicAssistant(songs, knowledge_base, language_model_writer=writer)

    response = assistant_with_model.answer("happy pop")

    assert response.status == STATUS_ANSWERED
    assert response.summary_writer_name == "template"


def test_formatted_response_shows_sources_confidence_and_trace(assistant):
    response = assistant.answer("something mellow for late-night studying")

    output_text = format_response(response, show_trace=True)

    assert "Confidence:" in output_text
    assert "How I read your request:" in output_text
    assert "sources: song:" in output_text
    assert "Self-check:" in output_text
    assert "Trace:" in output_text
    assert "GUARDRAIL" in output_text


def test_formatted_rejection_explains_what_to_do(assistant):
    output_text = format_response(assistant.answer(""))

    assert "Status: rejected" in output_text
    assert "describe the music you want" in output_text


def test_assistant_can_be_built_from_files():
    assistant_from_files = MusicAssistant.from_files()

    assert assistant_from_files.answer("jazz").recommendations[0].song["genre"] == "jazz"


def test_songs_only_baseline_understands_less_than_the_full_knowledge_base():
    full_assistant = MusicAssistant.from_files()
    baseline_assistant = MusicAssistant.from_files(include_guides=False)

    # "fall asleep" is only explained by the sleep activity guide, not by any song row
    full_response = full_assistant.answer("music to fall asleep to")
    baseline_response = baseline_assistant.answer("music to fall asleep to")

    assert full_response.status == STATUS_ANSWERED
    assert baseline_response.status == STATUS_NO_MATCH
