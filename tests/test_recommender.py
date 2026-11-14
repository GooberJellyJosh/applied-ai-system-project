from src.recommender import Song, UserProfile, Recommender

def make_small_recommender() -> Recommender:
    songs = [
        Song(
            id=1,
            title="Test Pop Track",
            artist="Test Artist",
            genre="pop",
            mood="happy",
            energy=0.8,
            tempo_bpm=120,
            valence=0.9,
            danceability=0.8,
            acousticness=0.2,
        ),
        Song(
            id=2,
            title="Chill Lofi Loop",
            artist="Test Artist",
            genre="lofi",
            mood="chill",
            energy=0.4,
            tempo_bpm=80,
            valence=0.6,
            danceability=0.5,
            acousticness=0.9,
        ),
    ]
    return Recommender(songs)


def test_recommend_returns_songs_sorted_by_score():
    user = UserProfile(
        favorite_genre="pop",
        favorite_mood="happy",
        target_energy=0.8,
        likes_acoustic=False,
    )
    rec = make_small_recommender()
    results = rec.recommend(user, k=2)

    assert len(results) == 2
    # Starter expectation: the pop, happy, high energy song should score higher
    assert results[0].genre == "pop"
    assert results[0].mood == "happy"


def test_explain_recommendation_returns_non_empty_string():
    user = UserProfile(
        favorite_genre="pop",
        favorite_mood="happy",
        target_energy=0.8,
        likes_acoustic=False,
    )
    rec = make_small_recommender()
    song = rec.songs[0]

    explanation = rec.explain_recommendation(user, song)
    assert isinstance(explanation, str)
    assert explanation.strip() != ""


# ---------------------------------------------------------------------------
# Functional interface tests
# ---------------------------------------------------------------------------
from src.recommender import load_songs, score_song, recommend_songs, closeness


def test_load_songs_converts_numeric_columns():
    songs = load_songs("data/songs.csv")
    assert len(songs) >= 10
    first_song = songs[0]
    assert isinstance(first_song["id"], int)
    assert isinstance(first_song["energy"], float)
    assert isinstance(first_song["tempo_bpm"], float)


def test_closeness_is_one_for_exact_match_and_never_negative():
    assert closeness(0.5, 0.5) == 1.0
    assert closeness(0.0, 1.5) == 0.0  # far-off values clamp to zero


def test_score_song_returns_score_and_reasons():
    user_prefs = {"genre": "pop", "mood": "happy", "energy": 0.8}
    song = {"genre": "pop", "mood": "happy", "energy": 0.8, "acousticness": 0.2}
    score, reasons = score_song(user_prefs, song)
    assert score == 4.5  # 2.0 genre + 1.0 mood + 1.5 perfect energy
    assert any("genre match" in reason for reason in reasons)
    assert any("mood match" in reason for reason in reasons)


def test_recommend_songs_is_sorted_and_limited_to_k():
    songs = load_songs("data/songs.csv")
    user_prefs = {"genre": "lofi", "mood": "chill", "energy": 0.4}
    results = recommend_songs(user_prefs, songs, k=3)
    assert len(results) == 3
    scores = [score for _, score, _ in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0][0]["genre"] == "lofi"


# ---------------------------------------------------------------------------
# Advanced feature tests
# ---------------------------------------------------------------------------
def test_load_songs_parses_advanced_columns():
    songs = load_songs("data/songs.csv")
    first_song = songs[0]
    assert isinstance(first_song["popularity"], int)
    assert isinstance(first_song["release_decade"], int)
    assert isinstance(first_song["mood_tags"], list)
    assert len(first_song["mood_tags"]) > 0


def test_mood_tags_and_decade_add_points():
    base_prefs = {"energy": 0.5}
    detailed_prefs = {"energy": 0.5, "mood_tags": ["nostalgic", "dreamy"], "decade": 1980}
    song = {"genre": "synthwave", "mood": "moody", "energy": 0.5, "acousticness": 0.2,
            "mood_tags": ["nostalgic", "nocturnal", "dreamy"], "release_decade": 1980}
    base_score, _ = score_song(base_prefs, song)
    detailed_score, reasons = score_song(detailed_prefs, song)
    assert detailed_score == base_score + 1.0 + 0.5  # two tags (capped at 1.0) + decade
    assert any("shared mood tags" in reason for reason in reasons)


# ---------------------------------------------------------------------------
# Scoring mode (strategy) tests
# ---------------------------------------------------------------------------
import pytest
from src.recommender import SCORING_MODES, get_scoring_mode


def test_modes_change_the_weights_used():
    user_prefs = {"genre": "pop", "mood": "happy"}
    song = {"genre": "pop", "mood": "happy", "energy": 0.5, "acousticness": 0.5}
    balanced_score, _ = score_song(user_prefs, song, SCORING_MODES["balanced"])
    genre_first_score, _ = score_song(user_prefs, song, SCORING_MODES["genre_first"])
    mood_first_score, _ = score_song(user_prefs, song, SCORING_MODES["mood_first"])
    assert balanced_score == 3.0      # 2.0 + 1.0
    assert genre_first_score == 4.5   # 4.0 + 0.5
    assert mood_first_score == 3.75   # 0.75 + 3.0


def test_mood_first_mode_can_cross_genres():
    songs = load_songs("data/songs.csv")
    user_prefs = {"genre": "pop", "mood": "sad", "energy": 0.45}
    balanced_top = recommend_songs(user_prefs, songs, k=2)
    mood_first_top = recommend_songs(user_prefs, songs, k=2, mode=SCORING_MODES["mood_first"])
    balanced_titles = [song["title"] for song, _, _ in balanced_top]
    mood_first_titles = [song["title"] for song, _, _ in mood_first_top]
    assert "Crossroads Ache" not in balanced_titles  # blues song loses to pop songs
    assert "Crossroads Ache" in mood_first_titles    # mood_first lifts the sad blues song


def test_unknown_mode_raises_helpful_error():
    with pytest.raises(ValueError):
        get_scoring_mode("not_a_mode")


# ---------------------------------------------------------------------------
# Diversity penalty tests
# ---------------------------------------------------------------------------
def test_diversity_penalty_limits_repeat_artists():
    songs = load_songs("data/songs.csv")
    user_prefs = {"genre": "lofi", "mood": "chill", "energy": 0.4}
    plain = recommend_songs(user_prefs, songs, k=5)
    diverse = recommend_songs(user_prefs, songs, k=5, diversity=True)
    plain_titles = [song["title"] for song, _, _ in plain]
    diverse_titles = [song["title"] for song, _, _ in diverse]
    # "Focus Flow" is LoRoom's second lofi song, so it should drop in the diverse list
    assert diverse_titles.index("Focus Flow") > plain_titles.index("Focus Flow")
    # The penalized score is lower than the raw score
    plain_scores = {song["title"]: score for song, score, _ in plain}
    diverse_scores = {song["title"]: score for song, score, _ in diverse}
    assert diverse_scores["Focus Flow"] < plain_scores["Focus Flow"]


def test_diversity_penalty_is_explained():
    songs = load_songs("data/songs.csv")
    user_prefs = {"genre": "pop", "mood": "happy", "energy": 0.8}
    diverse = recommend_songs(user_prefs, songs, k=5, diversity=True)
    all_reasons = " ".join(explanation for _, _, explanation in diverse)
    assert "diversity:" in all_reasons


# ---------------------------------------------------------------------------
# Table formatting tests
# ---------------------------------------------------------------------------
from src.table_format import format_table


def test_format_table_handles_multiline_cells():
    table = format_table(["#", "Why"], [["1", "- genre match\n- mood match"]])
    lines = table.split("\n")
    assert "genre match" in table and "mood match" in table
    # Every line of the table has the same width
    assert len({len(line) for line in lines}) == 1
