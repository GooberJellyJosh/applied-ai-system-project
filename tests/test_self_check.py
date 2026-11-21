"""Tests for the self-check, plan revision, summary check, and confidence score."""

from src.knowledge_ranker import RankedSong, rank_songs_with_knowledge
from src.recommender import BALANCED_MODE
from src.request_planner import RequestPlan, build_request_plan
from src.self_check import (
    CHECK_EXCLUSIONS_RESPECTED,
    CHECK_GENRE_AVAILABLE,
    CHECK_MOOD_REPRESENTED,
    CHECK_NO_DUPLICATES,
    CHECK_SONGS_IN_CATALOG,
    FAILED_CHECK_CONFIDENCE_CAP,
    MAX_SUMMARY_LENGTH,
    CheckResult,
    best_possible_score,
    check_written_summary,
    compute_confidence,
    failed_check_names,
    propose_revision,
    run_result_checks,
)

RESULT_COUNT = 5


def plan_and_rank(request_text, knowledge_base, retriever, songs):
    """Return (plan, ranked songs) for a request using the shared fixtures."""
    plan = build_request_plan(request_text, knowledge_base, retriever, songs)
    ranked_songs = rank_songs_with_knowledge(plan, songs, knowledge_base, RESULT_COUNT)
    return plan, ranked_songs


def as_ranked(song):
    """Wrap a catalog song as a recommendation with a reason and a valid source."""
    return RankedSong(song, 1.0, ["test reason"], [f"song:{song['id']}"])


def test_a_normal_request_passes_every_check(knowledge_base, retriever, songs):
    plan, ranked_songs = plan_and_rank("chill lofi for studying", knowledge_base, retriever, songs)

    checks = run_result_checks(plan, ranked_songs, songs, knowledge_base, RESULT_COUNT)

    assert failed_check_names(checks) == []


def test_missing_genre_fails_a_check_and_is_revised(knowledge_base, retriever, songs):
    plan, ranked_songs = plan_and_rank("k-pop", knowledge_base, retriever, songs)
    checks = run_result_checks(plan, ranked_songs, songs, knowledge_base, RESULT_COUNT)

    assert CHECK_GENRE_AVAILABLE in failed_check_names(checks)

    revised_plan, description = propose_revision(plan, checks, songs, knowledge_base)

    assert revised_plan.preferences["genre"] == "pop"  # first related genre in the k-pop guide
    assert revised_plan.originally_requested_genre == "k-pop"
    assert "k-pop" in description
    assert plan.preferences["genre"] == "k-pop"  # the original plan is left untouched


def test_revised_plan_passes_the_checks(knowledge_base, retriever, songs):
    plan, ranked_songs = plan_and_rank("k-pop", knowledge_base, retriever, songs)
    checks = run_result_checks(plan, ranked_songs, songs, knowledge_base, RESULT_COUNT)
    revised_plan, _ = propose_revision(plan, checks, songs, knowledge_base)

    revised_ranking = rank_songs_with_knowledge(revised_plan, songs, knowledge_base, RESULT_COUNT)
    revised_checks = run_result_checks(revised_plan, revised_ranking, songs, knowledge_base, RESULT_COUNT)

    assert failed_check_names(revised_checks) == []


def test_no_revision_is_proposed_when_everything_passes(knowledge_base, retriever, songs):
    plan, ranked_songs = plan_and_rank("happy pop", knowledge_base, retriever, songs)
    checks = run_result_checks(plan, ranked_songs, songs, knowledge_base, RESULT_COUNT)

    assert propose_revision(plan, checks, songs, knowledge_base) is None


def test_an_invented_song_is_caught(knowledge_base, songs):
    invented_song = dict(songs[0], id=999, title="Song That Does Not Exist")
    plan = RequestPlan(request_text="test")

    checks = run_result_checks(plan, [as_ranked(invented_song)], songs, knowledge_base, 1)

    assert CHECK_SONGS_IN_CATALOG in failed_check_names(checks)


def test_a_repeated_song_is_caught(knowledge_base, songs):
    plan = RequestPlan(request_text="test")

    checks = run_result_checks(plan, [as_ranked(songs[0]), as_ranked(songs[0])], songs, knowledge_base, 2)

    assert CHECK_NO_DUPLICATES in failed_check_names(checks)


def test_an_excluded_genre_in_the_results_is_caught(knowledge_base, songs):
    pop_song = next(song for song in songs if song["genre"] == "pop")
    plan = RequestPlan(request_text="test", excluded_genres=["pop"])

    checks = run_result_checks(plan, [as_ranked(pop_song)], songs, knowledge_base, 1)

    assert CHECK_EXCLUSIONS_RESPECTED in failed_check_names(checks)


def test_missing_mood_switches_the_plan_to_mood_first(knowledge_base, songs):
    # Ask for romantic but hand back only loud songs, as a careless ranking might
    loud_songs = [song for song in songs if song["mood"] in ("intense", "aggressive")]
    plan = RequestPlan(request_text="test", preferences={"mood": "romantic"}, scoring_mode_name="balanced")

    checks = run_result_checks(plan, [as_ranked(song) for song in loud_songs], songs, knowledge_base, 3)
    assert CHECK_MOOD_REPRESENTED in failed_check_names(checks)

    revised_plan, _ = propose_revision(plan, checks, songs, knowledge_base)
    assert revised_plan.scoring_mode_name == "mood_first"


def test_summary_check_accepts_a_summary_about_the_recommended_songs(songs):
    ranked_songs = [as_ranked(songs[0]), as_ranked(songs[1])]
    summary = f"The best match is \"{songs[0]['title']}\", and \"{songs[1]['title']}\" is close behind."

    checks = check_written_summary(summary, ranked_songs, songs)

    assert failed_check_names(checks) == []


def test_summary_check_rejects_a_song_that_was_not_recommended(songs):
    ranked_songs = [as_ranked(songs[0])]
    summary = f"\"{songs[0]['title']}\" is great, and you should also try \"{songs[5]['title']}\"."

    checks = check_written_summary(summary, ranked_songs, songs)

    assert "summary_only_mentions_recommended_songs" in failed_check_names(checks)


def test_summary_check_rejects_a_summary_that_skips_the_top_pick(songs):
    ranked_songs = [as_ranked(songs[0]), as_ranked(songs[1])]

    checks = check_written_summary(f"Try \"{songs[1]['title']}\".", ranked_songs, songs)

    assert "summary_mentions_top_pick" in failed_check_names(checks)


def test_summary_check_rejects_empty_and_overlong_text(songs):
    ranked_songs = [as_ranked(songs[0])]
    overlong_summary = songs[0]["title"] + " " + "x" * MAX_SUMMARY_LENGTH

    assert "summary_length" in failed_check_names(check_written_summary("", ranked_songs, songs))
    assert "summary_length" in failed_check_names(check_written_summary(overlong_summary, ranked_songs, songs))


def test_best_possible_score_adds_up_the_mode_weights():
    preferences = {"genre": "pop", "mood": "happy", "energy": 0.8}

    assert best_possible_score(preferences, BALANCED_MODE) == 4.5  # 2.0 + 1.0 + 1.5
    assert best_possible_score({}, BALANCED_MODE) == 0.0


def test_confidence_is_high_for_a_clear_request(knowledge_base, retriever, songs):
    plan, ranked_songs = plan_and_rank("chill lofi for studying", knowledge_base, retriever, songs)
    checks = run_result_checks(plan, ranked_songs, songs, knowledge_base, RESULT_COUNT)

    report = compute_confidence(plan, ranked_songs, checks, was_revised=False)

    assert report.label == "high"
    assert 0.7 <= report.score <= 1.0


def test_confidence_drops_when_only_part_of_the_request_is_understood(knowledge_base, retriever, songs):
    clear_plan, clear_ranking = plan_and_rank("pop", knowledge_base, retriever, songs)
    vague_plan, vague_ranking = plan_and_rank("pop quiz answers for chemistry", knowledge_base, retriever, songs)

    clear_report = compute_confidence(clear_plan, clear_ranking, [], was_revised=False)
    vague_report = compute_confidence(vague_plan, vague_ranking, [], was_revised=False)

    assert vague_report.score < clear_report.score
    assert vague_report.label == "low"


def test_confidence_is_lower_after_a_revision(knowledge_base, retriever, songs):
    plan, ranked_songs = plan_and_rank("happy pop", knowledge_base, retriever, songs)

    without_revision = compute_confidence(plan, ranked_songs, [], was_revised=False)
    with_revision = compute_confidence(plan, ranked_songs, [], was_revised=True)

    assert with_revision.score < without_revision.score


def test_a_failed_check_caps_confidence(knowledge_base, retriever, songs):
    plan, ranked_songs = plan_and_rank("happy pop", knowledge_base, retriever, songs)
    failed_check = CheckResult("example_check", False, "forced failure")

    report = compute_confidence(plan, ranked_songs, [failed_check], was_revised=False)

    assert report.score <= FAILED_CHECK_CONFIDENCE_CAP
    assert report.label == "low"
