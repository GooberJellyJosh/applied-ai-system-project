"""
Knowledge-aware ranking for the VibeFinder assistant.

The original VibeFinder 1.0 scoring rule (score_song) is still the core of
the ranking. This module adds three things that only the knowledge base can
provide, so retrieved information changes which songs are recommended:

    1. Related-genre credit   "indie pop" earns partial genre points when the
                              listener asked for "pop" (from the genre guide)
    2. Similar-mood credit    "melancholy" earns partial mood points when the
                              listener asked for "sad" (from the mood guide)
    3. Wording bonus          songs whose description matched the request's
                              own words earn points based on that similarity

Songs in an excluded genre or mood ("not sad", "no country") are removed.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from src.app_logging import get_logger
from src.knowledge_base import KnowledgeBase
from src.recommender import apply_diversity_penalty, get_scoring_mode, score_song
from src.request_planner import RequestPlan

logger = get_logger("ranker")

# Guides list related genres and similar moods closest first. The closest one
# earns the largest share of the full match points and later ones earn less,
# so "melancholy" counts for more than "nostalgic" when the request says "sad".
RELATED_MATCH_SHARES = (0.6, 0.45, 0.3)

# Wording bonus = similarity x scale, capped so it can never outweigh a genre match
WORDING_BONUS_SCALE = 3.0
WORDING_BONUS_MAX_POINTS = 1.5
# Ignore very weak word overlap
WORDING_BONUS_MIN_SIMILARITY = 0.05


@dataclass
class RankedSong:
    """One recommended song with its score, reasons, and supporting documents."""
    song: Dict
    score: float
    reasons: List[str] = field(default_factory=list)
    source_doc_ids: List[str] = field(default_factory=list)  # evidence behind the reasons


def _related_names(knowledge_base: KnowledgeBase, doc_id: str, metadata_key: str) -> List[str]:
    """Return the related genres or similar moods listed in a guide (empty if no guide)."""
    guide_document = knowledge_base.get(doc_id)
    if guide_document is None:
        return []
    return list(guide_document.metadata.get(metadata_key, []))


def related_match_share(position_in_guide: int) -> float:
    """Return the share of full points for the Nth related genre or similar mood (0 = closest)."""
    last_position = len(RELATED_MATCH_SHARES) - 1
    return RELATED_MATCH_SHARES[min(position_in_guide, last_position)]


def score_song_with_knowledge(
    plan: RequestPlan, song: Dict, knowledge_base: KnowledgeBase
) -> Tuple[float, List[str], List[str]]:
    """Score one song with the base recipe plus the knowledge-based adjustments."""
    scoring_mode = get_scoring_mode(plan.scoring_mode_name)
    total_score, reasons = score_song(plan.preferences, song, scoring_mode)

    # Every recommendation can cite the song's own knowledge base document
    source_doc_ids = [f"song:{song['id']}"]

    # 1. Related-genre credit (only when the exact genre did not already match)
    requested_genre = plan.preferences.get("genre")
    if requested_genre and song["genre"].lower() != requested_genre.lower():
        related_genres = _related_names(knowledge_base, f"genre:{requested_genre}", "similar_genres")
        if song["genre"] in related_genres:
            share = related_match_share(related_genres.index(song["genre"]))
            related_genre_points = round(scoring_mode.genre_points * share, 2)
            total_score += related_genre_points
            reasons.append(
                f"related genre: {song['genre']} is close to {requested_genre} (+{related_genre_points:.2f})"
            )
            source_doc_ids.append(f"genre:{requested_genre}")
    elif requested_genre:
        source_doc_ids.append(f"genre:{requested_genre}")

    # 2. Similar-mood credit (only when the exact mood did not already match)
    requested_mood = plan.preferences.get("mood")
    if requested_mood and song["mood"].lower() != requested_mood.lower():
        similar_moods = _related_names(knowledge_base, f"mood:{requested_mood}", "similar_moods")
        if song["mood"] in similar_moods:
            share = related_match_share(similar_moods.index(song["mood"]))
            similar_mood_points = round(scoring_mode.mood_points * share, 2)
            total_score += similar_mood_points
            reasons.append(
                f"similar mood: {song['mood']} is close to {requested_mood} (+{similar_mood_points:.2f})"
            )
            source_doc_ids.append(f"mood:{requested_mood}")
    elif requested_mood:
        source_doc_ids.append(f"mood:{requested_mood}")

    # 3. Wording bonus from the retriever's match on this song's description
    song_match = plan.song_matches.get(song["id"])
    if song_match is not None and song_match.similarity >= WORDING_BONUS_MIN_SIMILARITY:
        wording_points = round(
            min(song_match.similarity * WORDING_BONUS_SCALE, WORDING_BONUS_MAX_POINTS), 2
        )
        total_score += wording_points
        matched_words = ", ".join(song_match.matched_terms)
        reasons.append(f"matches your wording: {matched_words} (+{wording_points:.2f})")

    # Be honest when nothing in the request points at this song
    if not reasons:
        reasons.append("no stated preference matched; listed only because nothing ruled it out (+0.00)")

    return round(total_score, 2), reasons, source_doc_ids


def rank_songs_with_knowledge(
    plan: RequestPlan, songs: List[Dict], knowledge_base: KnowledgeBase, result_count: int
) -> List[RankedSong]:
    """Score every allowed song, sort, optionally diversify, and return the top results."""
    excluded_genres = {genre.lower() for genre in plan.excluded_genres}
    excluded_moods = {mood.lower() for mood in plan.excluded_moods}

    scored_songs = []
    sources_by_song_id: Dict[int, List[str]] = {}
    for song in songs:
        # Guardrail: never recommend something the listener ruled out
        if song["genre"].lower() in excluded_genres or song["mood"].lower() in excluded_moods:
            continue
        song_score, reasons, source_doc_ids = score_song_with_knowledge(plan, song, knowledge_base)
        scored_songs.append((song, song_score, reasons))
        sources_by_song_id[song["id"]] = source_doc_ids

    # Highest score first; ties are broken alphabetically so results are repeatable
    ranked = sorted(scored_songs, key=lambda item: (-item[1], item[0]["title"]))

    if plan.use_diversity:
        # Reuse the VibeFinder 1.0 diversity penalty to avoid repeat artists and genres
        ranked = apply_diversity_penalty(ranked, result_count)

    top_results = [
        RankedSong(song, song_score, reasons, sources_by_song_id[song["id"]])
        for song, song_score, reasons in ranked[:result_count]
    ]
    logger.info(
        "Ranked %d songs (mode=%s): %s",
        len(scored_songs), plan.scoring_mode_name,
        [(result.song["title"], result.score) for result in top_results],
    )
    return top_results
