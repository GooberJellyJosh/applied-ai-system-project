"""Tests for tokenizing, stemming, and TF-IDF retrieval."""

from src.knowledge_base import (
    ACTIVITY_TYPE,
    GENRE_TYPE,
    SONG_TYPE,
    KnowledgeDocument,
    load_knowledge_base,
)
from src.recommender import load_songs
from src.retriever import TfidfRetriever, stem_word, tokenize

SONGS_CSV_PATH = "data/songs.csv"


def make_catalog_retriever() -> TfidfRetriever:
    """Build a retriever over the real catalog and guide files."""
    knowledge_base = load_knowledge_base(load_songs(SONGS_CSV_PATH))
    return TfidfRetriever(knowledge_base.documents)


def test_stemming_matches_related_word_forms():
    assert stem_word("studying") == stem_word("study")
    assert stem_word("studies") == stem_word("study")
    assert stem_word("relaxing") == stem_word("relaxed") == stem_word("relax")
    assert stem_word("running") == stem_word("run")
    assert stem_word("dancing") == stem_word("dance")
    assert stem_word("focused") == stem_word("focus")


def test_stemming_leaves_short_words_alone():
    assert stem_word("pop") == "pop"
    assert stem_word("sad") == "sad"
    assert stem_word("80s") == "80s"


def test_tokenize_removes_stop_words_and_splits_hyphens():
    tokens = tokenize("I want some late-night music for STUDYING")

    # "late" is stemmed to "lat"; the stem only has to be consistent
    assert tokens == ["lat", "night", "study"]


def test_tokenize_keeps_r_and_b_as_one_word():
    assert "r&b" in tokenize("smooth R&B please")


def test_search_ranks_the_most_relevant_document_first():
    documents = [
        KnowledgeDocument("genre:rock", GENRE_TYPE, "rock", "rock loud electric guitars", "rock"),
        KnowledgeDocument("genre:lofi", GENRE_TYPE, "lofi", "lofi mellow beats for studying", "lofi"),
    ]
    retriever = TfidfRetriever(documents)

    results = retriever.search("mellow study beats")

    assert results[0].document.doc_id == "genre:lofi"
    assert 0.0 < results[0].similarity <= 1.0
    assert "study" in results[0].matched_terms


def test_search_returns_nothing_for_unrelated_text():
    retriever = make_catalog_retriever()

    assert retriever.search("xylophone quantum spreadsheet") == []


def test_search_can_be_limited_to_one_document_type():
    retriever = make_catalog_retriever()

    results = retriever.search("music for the gym", doc_type=ACTIVITY_TYPE)

    assert results, "expected at least one activity guide to match"
    assert all(result.document.doc_type == ACTIVITY_TYPE for result in results)
    assert results[0].document.name == "workout"


def test_search_finds_songs_from_descriptive_words():
    retriever = make_catalog_retriever()

    results = retriever.search("quiet acoustic instrumental", doc_type=SONG_TYPE, top_k=3)

    # Every top match should be a soft, acoustic, mostly instrumental song
    songs_by_id = {song["id"]: song for song in load_songs(SONGS_CSV_PATH)}
    for result in results:
        song = songs_by_id[result.document.metadata["song_id"]]
        assert song["acousticness"] >= 0.6
        assert song["energy"] < 0.5


def test_search_results_are_repeatable():
    retriever = make_catalog_retriever()

    first_run = [(match.document.doc_id, match.similarity) for match in retriever.search("chill night")]
    second_run = [(match.document.doc_id, match.similarity) for match in retriever.search("chill night")]

    assert first_run == second_run
