"""
Command line runner for the VibeFinder music recommender.

Run from the project root with:
    python -m src.main
    python -m src.main --mode mood_first
"""

import argparse

from src.recommender import SCORING_MODES, get_scoring_mode, load_songs, recommend_songs

SONGS_CSV_PATH = "data/songs.csv"
TOP_K = 5


def parse_arguments() -> argparse.Namespace:
    """Read command line options for the scoring mode and number of results."""
    parser = argparse.ArgumentParser(description="VibeFinder music recommender")
    parser.add_argument(
        "--mode",
        default="balanced",
        choices=list(SCORING_MODES),
        help="scoring strategy to rank songs with (default: balanced)",
    )
    parser.add_argument("--k", type=int, default=TOP_K, help="number of songs to recommend")
    return parser.parse_args()


def print_recommendations(
    profile_name: str, user_prefs: dict, mode_name: str, recommendations: list
) -> None:
    """Print a readable block showing each recommended song, its score, and its reasons."""
    print("=" * 60)
    print(f"Profile: {profile_name}   |   Mode: {mode_name}")
    print(f"Preferences: {user_prefs}")
    print("=" * 60)
    for rank, (song, score, explanation) in enumerate(recommendations, start=1):
        print(f"{rank}. {song['title']} by {song['artist']}  [{song['genre']} / {song['mood']}]")
        print(f"   Score: {score:.2f}")
        # Each reason goes on its own line so it's easy to read
        for reason in explanation.split("; "):
            print(f"     - {reason}")
        print()


def main() -> None:
    """Load the catalog, run the default profile, and print the top recommendations."""
    arguments = parse_arguments()
    scoring_mode = get_scoring_mode(arguments.mode)

    songs = load_songs(SONGS_CSV_PATH)
    print(f"Loaded songs: {len(songs)}")
    print(f"Scoring mode: {scoring_mode.name} - {scoring_mode.description}\n")

    # Starter example profile: upbeat pop listener
    user_prefs = {"genre": "pop", "mood": "happy", "energy": 0.8}

    recommendations = recommend_songs(user_prefs, songs, k=arguments.k, mode=scoring_mode)
    print_recommendations("Default Pop / Happy", user_prefs, scoring_mode.name, recommendations)


if __name__ == "__main__":
    main()
