"""Tests for building the knowledge base from the song catalog and the guide files."""

from src.knowledge_base import (
    ACTIVITY_TYPE,
    GENRE_TYPE,
    MOOD_TYPE,
    SONG_TYPE,
    TRAIT_TYPE,
    build_song_document,
    describe_song_in_words,
    load_knowledge_base,
)
from src.recommender import load_songs

SONGS_CSV_PATH = "data/songs.csv"


def test_knowledge_base_has_one_document_per_song():
    songs = load_songs(SONGS_CSV_PATH)
    knowledge_base = load_knowledge_base(songs)

    song_documents = knowledge_base.documents_of_type(SONG_TYPE)
    assert len(song_documents) == len(songs)
    assert knowledge_base.get("song:1").name == "Sunrise City"


def test_knowledge_base_loads_every_guide_type():
    knowledge_base = load_knowledge_base(load_songs(SONGS_CSV_PATH))

    for doc_type in (GENRE_TYPE, MOOD_TYPE, ACTIVITY_TYPE, TRAIT_TYPE):
        assert knowledge_base.documents_of_type(doc_type), f"no {doc_type} guides loaded"


def test_every_catalog_genre_and_mood_has_a_guide():
    songs = load_songs(SONGS_CSV_PATH)
    knowledge_base = load_knowledge_base(songs)

    for song in songs:
        assert knowledge_base.get(f"genre:{song['genre']}") is not None
        assert knowledge_base.get(f"mood:{song['mood']}") is not None


def test_guides_can_be_left_out_for_the_baseline():
    songs = load_songs(SONGS_CSV_PATH)
    songs_only = load_knowledge_base(songs, include_guides=False)

    assert len(songs_only) == len(songs)
    assert songs_only.documents_of_type(GENRE_TYPE) == []


def test_song_numbers_are_described_in_words():
    quiet_acoustic_song = {
        "id": 99, "title": "Test", "artist": "Tester", "genre": "folk", "mood": "chill",
        "energy": 0.2, "tempo_bpm": 60, "valence": 0.5, "danceability": 0.3,
        "acousticness": 0.9, "instrumentalness": 0.95,
    }
    phrases = " ".join(describe_song_in_words(quiet_acoustic_song))

    assert "low energy" in phrases
    assert "slow tempo" in phrases
    assert "acoustic" in phrases
    assert "instrumental" in phrases


def test_song_document_text_includes_genre_mood_and_decade():
    song = load_songs(SONGS_CSV_PATH)[7]  # Night Drive Loop, synthwave, 1980
    document = build_song_document(song)

    assert "synthwave" in document.text
    assert "moody" in document.text
    assert "80s" in document.text
    assert document.metadata["song_id"] == song["id"]
