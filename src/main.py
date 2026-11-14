"""
Command line runner for the VibeFinder music recommender.

Run from the project root with:
    python -m src.main
"""

from src.recommender import load_songs, recommend_songs

SONGS_CSV_PATH = "data/songs.csv"
TOP_K = 5


def print_recommendations(profile_name: str, user_prefs: dict, recommendations: list) -> None:
    """Print a readable block showing each recommended song, its score, and its reasons."""
    print("=" * 60)
    print(f"Profile: {profile_name}")
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
    songs = load_songs(SONGS_CSV_PATH)
    print(f"Loaded songs: {len(songs)}\n")

    # Starter example profile: upbeat pop listener
    user_prefs = {"genre": "pop", "mood": "happy", "energy": 0.8}

    recommendations = recommend_songs(user_prefs, songs, k=TOP_K)
    print_recommendations("Default Pop / Happy", user_prefs, recommendations)


if __name__ == "__main__":
    main()
