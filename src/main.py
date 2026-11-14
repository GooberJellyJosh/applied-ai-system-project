"""
Command line runner for the VibeFinder music recommender.

Run from the project root with:
    python -m src.main                              # every profile, balanced mode
    python -m src.main --profile chill_lofi         # one profile
    python -m src.main --mode mood_first --diverse  # another strategy + variety
    python -m src.main --list                       # show profile and mode names
"""

import argparse

from src.recommender import SCORING_MODES, get_scoring_mode, load_songs, recommend_songs
from src.table_format import format_table

SONGS_CSV_PATH = "data/songs.csv"
TOP_K = 5

# ---------------------------------------------------------------------------
# User taste profiles
# Each entry maps a short key to (display name, preference dictionary).
# ---------------------------------------------------------------------------
CORE_PROFILES = {
    "pop_happy": ("Default Pop / Happy", {"genre": "pop", "mood": "happy", "energy": 0.8}),
    "high_energy_pop": (
        "High-Energy Pop",
        {"genre": "pop", "mood": "intense", "energy": 0.9,
         "likes_acoustic": False, "danceability": 0.85},
    ),
    "chill_lofi": (
        "Chill Lofi",
        {"genre": "lofi", "mood": "chill", "energy": 0.35,
         "likes_acoustic": True, "instrumentalness": 0.85},
    ),
    "deep_intense_rock": (
        "Deep Intense Rock",
        {"genre": "rock", "mood": "intense", "energy": 0.92,
         "likes_acoustic": False, "tempo_bpm": 150, "valence": 0.4},
    ),
    "nostalgic_night_owl": (
        "Nostalgic Night Owl (advanced features)",
        {"genre": "synthwave", "mood": "moody", "energy": 0.65,
         "mood_tags": ["nostalgic", "nocturnal", "dreamy"], "decade": 1980},
    ),
}

# Adversarial / edge-case profiles meant to "trick" the scoring logic
EDGE_CASE_PROFILES = {
    "sad_but_hyped": (
        "Edge: Sad but Hyped (conflicting mood and energy)",
        {"genre": "edm", "mood": "sad", "energy": 0.9},
    ),
    "genre_ghost": (
        "Edge: Genre Ghost (genre not in catalog)",
        {"genre": "k-pop", "mood": "happy", "energy": 0.7},
    ),
    "acoustic_headbanger": (
        "Edge: Acoustic Headbanger (metal + likes acoustic)",
        {"genre": "metal", "mood": "aggressive", "energy": 0.95, "likes_acoustic": True},
    ),
    "out_of_range_energy": (
        "Edge: Out-of-Range Energy (energy 1.5)",
        {"genre": "classical", "mood": "peaceful", "energy": 1.5},
    ),
    "no_preferences": ("Edge: No Preferences (empty profile)", {}),
}

ALL_PROFILES = {**CORE_PROFILES, **EDGE_CASE_PROFILES}


def parse_arguments() -> argparse.Namespace:
    """Read command line options for the profile, scoring mode, and number of results."""
    parser = argparse.ArgumentParser(description="VibeFinder music recommender")
    parser.add_argument(
        "--profile",
        default="all",
        choices=["all", "core", "edge", *ALL_PROFILES],
        help="which taste profile(s) to run (default: all)",
    )
    parser.add_argument(
        "--mode",
        default="balanced",
        choices=list(SCORING_MODES),
        help="scoring strategy to rank songs with (default: balanced)",
    )
    parser.add_argument("--k", type=int, default=TOP_K, help="number of songs to recommend")
    parser.add_argument(
        "--diverse",
        action="store_true",
        help="penalize repeat artists/genres so the top list has more variety",
    )
    parser.add_argument("--list", action="store_true", help="list profiles and modes, then exit")
    return parser.parse_args()


def select_profiles(profile_choice: str) -> dict:
    """Return the profiles matching the --profile option."""
    if profile_choice == "all":
        return ALL_PROFILES
    if profile_choice == "core":
        return CORE_PROFILES
    if profile_choice == "edge":
        return EDGE_CASE_PROFILES
    return {profile_choice: ALL_PROFILES[profile_choice]}


def print_available_options() -> None:
    """Print every profile key and scoring mode so users know what they can pick."""
    print("Profiles:")
    for profile_key, (display_name, _) in ALL_PROFILES.items():
        print(f"  {profile_key:<22} {display_name}")
    print("\nScoring modes:")
    for mode_name, mode in SCORING_MODES.items():
        print(f"  {mode_name:<22} {mode.description}")


def print_recommendations(
    profile_name: str, user_prefs: dict, mode_name: str, recommendations: list
) -> None:
    """Print a summary table showing each recommended song, its score, and its reasons."""
    print(f"Profile: {profile_name}   |   Mode: {mode_name}")
    print(f"Preferences: {user_prefs}")

    table_rows = []
    for rank, (song, score, explanation) in enumerate(recommendations, start=1):
        song_cell = f"{song['title']}\n{song['artist']}\n{song['genre']} / {song['mood']}"
        # Each reason goes on its own line inside the "Why" column
        reasons_cell = "\n".join(f"- {reason}" for reason in explanation.split("; ") if reason)
        table_rows.append([str(rank), song_cell, f"{score:.2f}", reasons_cell or "- no matches"])

    print(format_table(["#", "Song", "Score", "Why"], table_rows, max_widths=[2, 24, 5, 52]))
    print()


def main() -> None:
    """Load the catalog, run the chosen profiles, and print the top recommendations."""
    arguments = parse_arguments()
    if arguments.list:
        print_available_options()
        return

    scoring_mode = get_scoring_mode(arguments.mode)
    songs = load_songs(SONGS_CSV_PATH)
    print(f"Loaded songs: {len(songs)}")
    print(f"Scoring mode: {scoring_mode.name} - {scoring_mode.description}")
    print(f"Diversity penalty: {'on' if arguments.diverse else 'off'}\n")

    for display_name, user_prefs in select_profiles(arguments.profile).values():
        recommendations = recommend_songs(
            user_prefs, songs, k=arguments.k, mode=scoring_mode, diversity=arguments.diverse
        )
        print_recommendations(display_name, user_prefs, scoring_mode.name, recommendations)


if __name__ == "__main__":
    main()
