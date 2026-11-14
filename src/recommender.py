"""
Core logic for the VibeFinder music recommender.

The recommender is content-based: it compares each song's attributes
(genre, mood, energy, ...) against a user's taste profile, gives every
song a score, and returns the highest-scoring songs with reasons.
"""

import csv
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Scoring weights (the "Algorithm Recipe")
# ---------------------------------------------------------------------------
GENRE_MATCH_POINTS = 2.0      # flat bonus when genre matches exactly
MOOD_MATCH_POINTS = 1.0       # flat bonus when mood matches exactly
ENERGY_MAX_POINTS = 1.5       # max points for a perfect energy match
ACOUSTIC_MAX_POINTS = 0.5     # max points for matching the acoustic preference
OPTIONAL_TARGET_POINTS = 0.5  # max points for each optional numeric target

# Tempo is measured in BPM, not 0-1, so differences are divided by this
# range to put tempo closeness on the same 0-1 scale as the other features.
TEMPO_RANGE_BPM = 120.0

# Column types used when converting CSV text into numbers
INTEGER_COLUMNS = {"id"}
FLOAT_COLUMNS = {"energy", "tempo_bpm", "valence", "danceability", "acousticness"}


# ---------------------------------------------------------------------------
# Data classes (used by the OOP interface and the tests)
# ---------------------------------------------------------------------------
@dataclass
class Song:
    """Represents a song and its attributes."""
    id: int
    title: str
    artist: str
    genre: str
    mood: str
    energy: float
    tempo_bpm: float
    valence: float
    danceability: float
    acousticness: float


@dataclass
class UserProfile:
    """Represents a user's taste preferences."""
    favorite_genre: str
    favorite_mood: str
    target_energy: float
    likes_acoustic: bool
    target_valence: Optional[float] = None
    target_danceability: Optional[float] = None
    target_tempo_bpm: Optional[float] = None

    def to_prefs(self) -> Dict:
        """Convert this profile into the preference dictionary used by score_song."""
        prefs = {
            "genre": self.favorite_genre,
            "mood": self.favorite_mood,
            "energy": self.target_energy,
            "likes_acoustic": self.likes_acoustic,
        }
        # Only include optional targets the user actually set
        optional_targets = {
            "valence": self.target_valence,
            "danceability": self.target_danceability,
            "tempo_bpm": self.target_tempo_bpm,
        }
        for feature_name, target_value in optional_targets.items():
            if target_value is not None:
                prefs[feature_name] = target_value
        return prefs


class Recommender:
    """Object-oriented wrapper around the functional scoring and ranking logic."""

    def __init__(self, songs: List[Song]):
        self.songs = songs

    def recommend(self, user: UserProfile, k: int = 5) -> List[Song]:
        """Return the top k Song objects for the given user profile."""
        user_prefs = user.to_prefs()
        songs_by_id = {song.id: song for song in self.songs}
        song_dicts = [asdict(song) for song in self.songs]
        ranked = recommend_songs(user_prefs, song_dicts, k)
        return [songs_by_id[song_dict["id"]] for song_dict, _, _ in ranked]

    def explain_recommendation(self, user: UserProfile, song: Song) -> str:
        """Return a readable explanation of why a song fits the user."""
        _, reasons = score_song(user.to_prefs(), asdict(song))
        if not reasons:
            return "No strong match with this profile."
        return "; ".join(reasons)


# ---------------------------------------------------------------------------
# Functional interface (used by src/main.py)
# ---------------------------------------------------------------------------
def load_songs(csv_path: str) -> List[Dict]:
    """Read songs from a CSV file and return them as dictionaries with numeric fields converted."""
    songs = []
    with open(csv_path, newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            song = {}
            for column_name, raw_value in row.items():
                if column_name in INTEGER_COLUMNS:
                    song[column_name] = int(raw_value)
                elif column_name in FLOAT_COLUMNS:
                    song[column_name] = float(raw_value)
                else:
                    song[column_name] = raw_value.strip()
            songs.append(song)
    return songs


def closeness(song_value: float, target_value: float, value_range: float = 1.0) -> float:
    """Return a 0-1 similarity that is 1.0 for an exact match and shrinks as values drift apart."""
    distance = abs(song_value - target_value) / value_range
    return max(0.0, 1.0 - distance)  # clamp so far-off songs never go negative


def score_song(user_prefs: Dict, song: Dict) -> Tuple[float, List[str]]:
    """Score one song against the user's preferences and return (score, reasons)."""
    total_score = 0.0
    reasons = []

    # 1. Genre match: flat bonus for an exact (case-insensitive) match
    favorite_genre = user_prefs.get("genre")
    if favorite_genre and song["genre"].lower() == favorite_genre.lower():
        total_score += GENRE_MATCH_POINTS
        reasons.append(f"genre match: {song['genre']} (+{GENRE_MATCH_POINTS:.2f})")

    # 2. Mood match: flat bonus for an exact (case-insensitive) match
    favorite_mood = user_prefs.get("mood")
    if favorite_mood and song["mood"].lower() == favorite_mood.lower():
        total_score += MOOD_MATCH_POINTS
        reasons.append(f"mood match: {song['mood']} (+{MOOD_MATCH_POINTS:.2f})")

    # 3. Energy closeness: reward songs near the target, not just louder ones
    target_energy = user_prefs.get("energy")
    if target_energy is not None:
        energy_points = ENERGY_MAX_POINTS * closeness(song["energy"], target_energy)
        total_score += energy_points
        reasons.append(
            f"energy {song['energy']:.2f} vs target {target_energy:.2f} (+{energy_points:.2f})"
        )

    # 4. Acoustic preference: acoustic fans want high acousticness, others want low
    likes_acoustic = user_prefs.get("likes_acoustic")
    if likes_acoustic is not None:
        acoustic_fit = song["acousticness"] if likes_acoustic else 1.0 - song["acousticness"]
        acoustic_points = ACOUSTIC_MAX_POINTS * acoustic_fit
        total_score += acoustic_points
        label = "acoustic" if likes_acoustic else "non-acoustic"
        reasons.append(f"{label} preference (+{acoustic_points:.2f})")

    # 5. Optional numeric targets (only scored when the user provides them)
    optional_features = [
        ("valence", 1.0),
        ("danceability", 1.0),
        ("tempo_bpm", TEMPO_RANGE_BPM),
    ]
    for feature_name, value_range in optional_features:
        target_value = user_prefs.get(feature_name)
        if target_value is None:
            continue
        feature_points = OPTIONAL_TARGET_POINTS * closeness(
            song[feature_name], target_value, value_range
        )
        total_score += feature_points
        reasons.append(f"{feature_name} close to target (+{feature_points:.2f})")

    return round(total_score, 2), reasons


def recommend_songs(
    user_prefs: Dict, songs: List[Dict], k: int = 5
) -> List[Tuple[Dict, float, str]]:
    """Score every song, sort from highest to lowest, and return the top k as (song, score, explanation)."""
    scored_songs = []
    for song in songs:
        song_score, reasons = score_song(user_prefs, song)
        explanation = "; ".join(reasons)
        scored_songs.append((song, song_score, explanation))

    # sorted() returns a new list and leaves the caller's catalog untouched.
    # Ties are broken alphabetically by title so the output is stable.
    ranked = sorted(scored_songs, key=lambda item: (-item[1], item[0]["title"]))
    return ranked[:k]
