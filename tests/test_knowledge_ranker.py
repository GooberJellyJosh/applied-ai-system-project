"""Tests for the knowledge-aware ranking step."""

from src.knowledge_ranker import RELATED_MATCH_SHARES, rank_songs_with_knowledge, related_match_share
from src.request_planner import RequestPlan, build_request_plan


def rank_request(request_text, knowledge_base, retriever, songs, result_count=5):
    """Plan and rank a request with the shared fixtures."""
    plan = build_request_plan(request_text, knowledge_base, retriever, songs)
    return rank_songs_with_knowledge(plan, songs, knowledge_base, result_count)


def reasons_for(ranked_songs, title):
    """Return the joined reasons for one recommended song."""
    for result in ranked_songs:
        if result.song["title"] == title:
            return " | ".join(result.reasons)
    raise AssertionError(f"{title} was not recommended")


def test_related_genre_earns_partial_credit(knowledge_base, retriever, songs):
    ranked_songs = rank_request("pop", knowledge_base, retriever, songs, result_count=10)

    # "Rooftop Lights" is indie pop, which the pop guide lists as a related genre
    assert "related genre: indie pop is close to pop" in reasons_for(ranked_songs, "Rooftop Lights")


def test_similar_mood_earns_partial_credit(knowledge_base, retriever, songs):
    ranked_songs = rank_request("sad", knowledge_base, retriever, songs)

    # "Harbor Lullaby" is melancholy; VibeFinder 1.0 gave it no credit for "sad"
    assert "similar mood: melancholy is close to sad" in reasons_for(ranked_songs, "Harbor Lullaby")


def test_excluded_genre_is_never_recommended(knowledge_base, retriever, songs):
    ranked_songs = rank_request("anything but pop", knowledge_base, retriever, songs, result_count=20)

    assert ranked_songs, "expected the rest of the catalog to be recommended"
    assert all(result.song["genre"] != "pop" for result in ranked_songs)


def test_excluded_mood_is_never_recommended(knowledge_base, retriever, songs):
    ranked_songs = rank_request("pop but not sad", knowledge_base, retriever, songs, result_count=20)

    assert all(result.song["mood"] != "sad" for result in ranked_songs)


def test_wording_bonus_rewards_songs_that_match_the_request_text(knowledge_base, retriever, songs):
    ranked_songs = rank_request("80s night drive", knowledge_base, retriever, songs)

    assert ranked_songs[0].song["title"] == "Night Drive Loop"
    assert "matches your wording" in reasons_for(ranked_songs, "Night Drive Loop")


def test_results_are_sorted_and_limited(knowledge_base, retriever, songs):
    ranked_songs = rank_request("chill lofi", knowledge_base, retriever, songs, result_count=3)

    scores = [result.score for result in ranked_songs]
    assert len(ranked_songs) == 3
    assert scores == sorted(scores, reverse=True)


def test_every_result_cites_documents_that_exist(knowledge_base, retriever, songs):
    ranked_songs = rank_request("happy pop for a party", knowledge_base, retriever, songs)

    for result in ranked_songs:
        assert f"song:{result.song['id']}" in result.source_doc_ids
        assert all(knowledge_base.get(doc_id) is not None for doc_id in result.source_doc_ids)


def test_a_song_with_no_matching_preference_still_gets_an_honest_reason(knowledge_base, songs):
    empty_plan = RequestPlan(request_text="", use_diversity=False)

    ranked_songs = rank_songs_with_knowledge(empty_plan, songs, knowledge_base, result_count=3)

    assert all(result.reasons for result in ranked_songs)
    assert "no stated preference matched" in ranked_songs[0].reasons[0]


def test_named_genre_keeps_its_own_songs_on_top(knowledge_base, retriever, songs):
    ranked_songs = rank_request("lofi", knowledge_base, retriever, songs, result_count=3)

    assert [result.song["genre"] for result in ranked_songs] == ["lofi", "lofi", "lofi"]


def test_closer_related_moods_earn_more_credit(knowledge_base, retriever, songs):
    ranked_songs = rank_request("sad songs", knowledge_base, retriever, songs)

    # The sad guide lists melancholy before nostalgic, so the melancholy song
    # should rank above the nostalgic one once the two sad songs are placed.
    assert [result.song["mood"] for result in ranked_songs[:3]] == ["sad", "sad", "melancholy"]


def test_related_match_share_shrinks_and_then_levels_off():
    assert related_match_share(0) > related_match_share(1) > related_match_share(2)
    assert related_match_share(10) == RELATED_MATCH_SHARES[-1]
