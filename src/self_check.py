"""
Self-check for the VibeFinder assistant.

After the assistant ranks songs it does not simply trust the result. This
module lets it check its own work, revise the plan when a check fails, and
report how confident it is:

    run_result_checks()      verifies the recommendations against the catalog,
                             the request, and the knowledge base
    propose_revision()       turns a failed check into a revised plan, so the
                             assistant can try once more
    check_written_summary()  verifies the written explanation only talks
                             about songs that were actually recommended
    compute_confidence()     scores the answer from 0 to 1
"""

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.app_logging import get_logger
from src.knowledge_base import KnowledgeBase
from src.knowledge_ranker import RankedSong
from src.recommender import ScoringMode, get_scoring_mode
from src.request_planner import PlanEvidence, RequestPlan, choose_scoring_mode

logger = get_logger("self_check")

# Names of the checks (also used to decide which revision to try)
CHECK_HAS_RESULTS = "has_results"
CHECK_SONGS_IN_CATALOG = "songs_in_catalog"
CHECK_NO_DUPLICATES = "no_duplicates"
CHECK_SORTED_BY_SCORE = "sorted_by_score"
CHECK_EXCLUSIONS_RESPECTED = "exclusions_respected"
CHECK_REASONS_AND_SOURCES = "reasons_and_sources"
CHECK_GENRE_AVAILABLE = "requested_genre_available"
CHECK_GENRE_REPRESENTED = "requested_genre_represented"
CHECK_MOOD_REPRESENTED = "requested_mood_represented"
CHECK_ENERGY_FITS = "top_pick_energy_fits"

# The top pick's energy may differ from the target by at most this much
MAX_TOP_PICK_ENERGY_GAP = 0.35

# Confidence = request coverage x (weighted retrieval strength and match quality).
# Coverage multiplies the rest so a half-understood request can never score high,
# no matter how well the songs fit the half that was understood.
RETRIEVAL_WEIGHT = 0.40         # how strongly the best document matched
MATCH_QUALITY_WEIGHT = 0.60     # how close the top pick is to a perfect score

# A retrieval similarity at or above this counts as a full-strength match
STRONG_SIMILARITY = 0.45
# Confidence is multiplied by this when the plan had to be revised
REVISION_PENALTY = 0.85
# Confidence can never be higher than this when a check still fails
FAILED_CHECK_CONFIDENCE_CAP = 0.35

HIGH_CONFIDENCE_MIN = 0.70
MEDIUM_CONFIDENCE_MIN = 0.45

# A written summary longer than this is rejected
MAX_SUMMARY_LENGTH = 900


@dataclass
class CheckResult:
    """The outcome of one self-check."""
    name: str
    passed: bool
    detail: str


@dataclass
class ConfidenceReport:
    """How sure the assistant is about an answer, and why."""
    score: float                                       # 0.0 to 1.0
    label: str                                         # "high", "medium", or "low"
    components: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Checking the recommendations
# ---------------------------------------------------------------------------
def run_result_checks(
    plan: RequestPlan,
    ranked_songs: List[RankedSong],
    songs: List[Dict],
    knowledge_base: KnowledgeBase,
    result_count: int,
) -> List[CheckResult]:
    """Run every self-check on a set of recommendations and return the outcomes."""
    checks: List[CheckResult] = []
    catalog_by_id = {song["id"]: song for song in songs}
    catalog_genres = {song["genre"].lower() for song in songs}
    excluded_genres = {genre.lower() for genre in plan.excluded_genres}
    excluded_moods = {mood.lower() for mood in plan.excluded_moods}

    # 1. There is something to recommend
    checks.append(CheckResult(
        CHECK_HAS_RESULTS, bool(ranked_songs),
        f"{len(ranked_songs)} of {result_count} requested songs returned",
    ))

    # 2. Every recommended song really exists in the catalog (no invented songs)
    unknown_titles = [
        result.song.get("title", "?") for result in ranked_songs
        if catalog_by_id.get(result.song.get("id")) != result.song
    ]
    checks.append(CheckResult(
        CHECK_SONGS_IN_CATALOG, not unknown_titles,
        "every song is in the catalog" if not unknown_titles
        else f"not in the catalog: {', '.join(unknown_titles)}",
    ))

    # 3. No song appears twice
    recommended_ids = [result.song.get("id") for result in ranked_songs]
    has_duplicates = len(recommended_ids) != len(set(recommended_ids))
    checks.append(CheckResult(
        CHECK_NO_DUPLICATES, not has_duplicates,
        "no repeated songs" if not has_duplicates else "a song is listed more than once",
    ))

    # 4. The list is ordered from the highest score to the lowest
    scores = [result.score for result in ranked_songs]
    is_sorted = all(earlier >= later for earlier, later in zip(scores, scores[1:]))
    checks.append(CheckResult(
        CHECK_SORTED_BY_SCORE, is_sorted,
        "scores are in descending order" if is_sorted else f"scores are out of order: {scores}",
    ))

    # 5. Nothing the listener ruled out slipped through
    excluded_titles = [
        result.song["title"] for result in ranked_songs
        if result.song["genre"].lower() in excluded_genres or result.song["mood"].lower() in excluded_moods
    ]
    checks.append(CheckResult(
        CHECK_EXCLUSIONS_RESPECTED, not excluded_titles,
        "no excluded genre or mood was recommended" if not excluded_titles
        else f"excluded songs were recommended: {', '.join(excluded_titles)}",
    ))

    # 6. Every recommendation is explained and cites documents that exist
    unsupported_titles = [
        result.song["title"] for result in ranked_songs
        if not result.reasons
        or not result.source_doc_ids
        or any(knowledge_base.get(doc_id) is None for doc_id in result.source_doc_ids)
    ]
    checks.append(CheckResult(
        CHECK_REASONS_AND_SOURCES, not unsupported_titles,
        "every song has reasons and valid sources" if not unsupported_titles
        else f"missing reasons or sources: {', '.join(unsupported_titles)}",
    ))

    # 7 and 8. Genre: is it in the catalog, and did it make the list?
    requested_genre = plan.preferences.get("genre")
    if requested_genre:
        genre_is_available = requested_genre.lower() in catalog_genres
        checks.append(CheckResult(
            CHECK_GENRE_AVAILABLE, genre_is_available,
            f"the catalog has {requested_genre} songs" if genre_is_available
            else f"the catalog has no {requested_genre} songs",
        ))
        if genre_is_available and plan.genre_was_named:
            genre_is_represented = any(
                result.song["genre"].lower() == requested_genre.lower() for result in ranked_songs
            )
            checks.append(CheckResult(
                CHECK_GENRE_REPRESENTED, genre_is_represented,
                f"at least one {requested_genre} song is recommended" if genre_is_represented
                else f"no {requested_genre} song made the list",
            ))

    # 9. Mood: at least one song has the requested mood or a similar one
    requested_mood = plan.preferences.get("mood")
    if requested_mood:
        mood_guide = knowledge_base.get(f"mood:{requested_mood}")
        acceptable_moods = {requested_mood.lower()}
        if mood_guide is not None:
            acceptable_moods.update(mood.lower() for mood in mood_guide.metadata.get("similar_moods", []))
        mood_is_represented = any(result.song["mood"].lower() in acceptable_moods for result in ranked_songs)
        checks.append(CheckResult(
            CHECK_MOOD_REPRESENTED, mood_is_represented,
            f"at least one song is {requested_mood} or close to it" if mood_is_represented
            else f"no song is {requested_mood} or close to it",
        ))

    # 10. Energy: the top pick is reasonably close to the target energy
    target_energy = plan.preferences.get("energy")
    if target_energy is not None and ranked_songs:
        energy_gap = abs(ranked_songs[0].song["energy"] - target_energy)
        checks.append(CheckResult(
            CHECK_ENERGY_FITS, energy_gap <= MAX_TOP_PICK_ENERGY_GAP,
            f"top pick energy {ranked_songs[0].song['energy']:.2f} vs target {target_energy:.2f}",
        ))

    for check in checks:
        if not check.passed:
            logger.warning("Self-check failed: %s (%s)", check.name, check.detail)
    return checks


def failed_check_names(checks: List[CheckResult]) -> List[str]:
    """Return the names of the checks that did not pass."""
    return [check.name for check in checks if not check.passed]


# ---------------------------------------------------------------------------
# Revising the plan after a failed check
# ---------------------------------------------------------------------------
def propose_revision(
    plan: RequestPlan,
    checks: List[CheckResult],
    songs: List[Dict],
    knowledge_base: KnowledgeBase,
) -> Optional[Tuple[RequestPlan, str]]:
    """
    Return (revised plan, description of the change) for the first fixable
    failed check, or None when there is nothing useful to change.
    """
    failed_names = failed_check_names(checks)
    if not failed_names:
        return None

    revised_plan = copy.deepcopy(plan)
    catalog_genres = {song["genre"].lower() for song in songs}
    excluded_genres = {genre.lower() for genre in plan.excluded_genres}

    # Fix 1: the requested genre is not in the catalog. Use the closest genre
    # the genre guide lists, and tell the listener about the swap.
    if CHECK_GENRE_AVAILABLE in failed_names:
        requested_genre = plan.preferences["genre"]
        genre_guide = knowledge_base.get(f"genre:{requested_genre}")
        similar_genres = genre_guide.metadata.get("similar_genres", []) if genre_guide else []
        available_substitutes = [
            genre for genre in similar_genres
            if genre.lower() in catalog_genres and genre.lower() not in excluded_genres
        ]
        revised_plan.originally_requested_genre = requested_genre
        revised_plan.evidence = [item for item in revised_plan.evidence if item.preference_name != "genre"]

        if available_substitutes:
            substitute_genre = available_substitutes[0]
            revised_plan.preferences["genre"] = substitute_genre
            revised_plan.evidence.append(PlanEvidence(
                "genre", substitute_genre, f"genre:{requested_genre}",
                f"closest available genre to {requested_genre}",
            ))
            description = (
                f"The catalog has no {requested_genre} songs, so the plan now uses "
                f"{substitute_genre}, the closest genre listed in the {requested_genre} guide."
            )
        else:
            del revised_plan.preferences["genre"]
            revised_plan.genre_was_named = False
            revised_plan.scoring_mode_name, _ = choose_scoring_mode(revised_plan)
            description = (
                f"The catalog has no {requested_genre} songs and no close relative, "
                f"so the plan now ranks on mood and energy only."
            )
        revised_plan.notes.append(description)
        return revised_plan, description

    # Fix 2: the named genre exists but did not make the list. Weigh genre more.
    if CHECK_GENRE_REPRESENTED in failed_names and plan.scoring_mode_name != "genre_first":
        revised_plan.scoring_mode_name = "genre_first"
        description = "No song from the requested genre made the list, so the plan now uses genre_first scoring."
        revised_plan.notes.append(description)
        return revised_plan, description

    # Fix 3: the mood is missing from the list. Weigh mood more.
    if CHECK_MOOD_REPRESENTED in failed_names and plan.scoring_mode_name != "mood_first":
        revised_plan.scoring_mode_name = "mood_first"
        description = "No song matched the requested mood, so the plan now uses mood_first scoring."
        revised_plan.notes.append(description)
        return revised_plan, description

    # Fix 4: the top pick is far from the target energy. Weigh energy more.
    if CHECK_ENERGY_FITS in failed_names and plan.scoring_mode_name != "energy_focused":
        revised_plan.scoring_mode_name = "energy_focused"
        description = "The top pick was far from the target energy, so the plan now uses energy_focused scoring."
        revised_plan.notes.append(description)
        return revised_plan, description

    return None  # the remaining failures cannot be fixed by changing the plan


# ---------------------------------------------------------------------------
# Checking the written summary
# ---------------------------------------------------------------------------
def check_written_summary(
    summary_text: str, ranked_songs: List[RankedSong], songs: List[Dict]
) -> List[CheckResult]:
    """Verify a written summary only talks about songs that were actually recommended."""
    checks: List[CheckResult] = []
    lowered_summary = summary_text.lower()
    recommended_titles = {result.song["title"].lower() for result in ranked_songs}
    recommended_artists = {result.song["artist"].lower() for result in ranked_songs}

    is_reasonable_length = 0 < len(summary_text.strip()) <= MAX_SUMMARY_LENGTH
    checks.append(CheckResult(
        "summary_length", is_reasonable_length,
        f"summary is {len(summary_text.strip())} characters (limit {MAX_SUMMARY_LENGTH})",
    ))

    top_title = ranked_songs[0].song["title"] if ranked_songs else ""
    mentions_top_pick = bool(top_title) and top_title.lower() in lowered_summary
    checks.append(CheckResult(
        "summary_mentions_top_pick", mentions_top_pick,
        f"the summary names the top pick \"{top_title}\"" if mentions_top_pick
        else f"the summary never names the top pick \"{top_title}\"",
    ))

    # Catalog songs or artists that were NOT recommended must not be mentioned
    stray_mentions = sorted(
        {song["title"] for song in songs
         if song["title"].lower() not in recommended_titles and song["title"].lower() in lowered_summary}
        | {song["artist"] for song in songs
           if song["artist"].lower() not in recommended_artists and song["artist"].lower() in lowered_summary}
    )
    checks.append(CheckResult(
        "summary_only_mentions_recommended_songs", not stray_mentions,
        "the summary only names recommended songs" if not stray_mentions
        else f"the summary names songs or artists that were not recommended: {', '.join(stray_mentions)}",
    ))
    return checks


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------
def best_possible_score(preferences: Dict, scoring_mode: ScoringMode) -> float:
    """Return the score a song would get if it matched every preference perfectly."""
    best_score = 0.0
    if preferences.get("genre"):
        best_score += scoring_mode.genre_points
    if preferences.get("mood"):
        best_score += scoring_mode.mood_points
    if preferences.get("energy") is not None:
        best_score += scoring_mode.energy_points
    if preferences.get("likes_acoustic") is not None:
        best_score += scoring_mode.acoustic_points
    for feature_name in ("valence", "danceability", "tempo_bpm", "popularity", "instrumentalness", "speechiness"):
        if preferences.get(feature_name) is not None:
            best_score += scoring_mode.points_for_feature(feature_name)
    if preferences.get("mood_tags"):
        best_score += scoring_mode.mood_tag_max_points
    if preferences.get("decade") is not None:
        best_score += scoring_mode.decade_points
    return best_score


def compute_confidence(
    plan: RequestPlan,
    ranked_songs: List[RankedSong],
    checks: List[CheckResult],
    was_revised: bool,
) -> ConfidenceReport:
    """Scale retrieval strength and match quality by request coverage to get a 0-1 confidence score."""
    coverage = plan.request_coverage
    retrieval_strength = min(1.0, plan.top_similarity / STRONG_SIMILARITY)

    # Match quality: how close the top pick came to a perfect score for this plan
    perfect_score = best_possible_score(plan.preferences, get_scoring_mode(plan.scoring_mode_name))
    if ranked_songs and perfect_score > 0:
        match_quality = min(1.0, ranked_songs[0].score / perfect_score)
    else:
        match_quality = 0.0

    confidence = coverage * (
        RETRIEVAL_WEIGHT * retrieval_strength + MATCH_QUALITY_WEIGHT * match_quality
    )
    if was_revised:
        confidence *= REVISION_PENALTY
    if failed_check_names(checks):
        confidence = min(confidence, FAILED_CHECK_CONFIDENCE_CAP)
    confidence = round(confidence, 2)

    if confidence >= HIGH_CONFIDENCE_MIN:
        label = "high"
    elif confidence >= MEDIUM_CONFIDENCE_MIN:
        label = "medium"
    else:
        label = "low"

    return ConfidenceReport(
        score=confidence,
        label=label,
        components={
            "request_coverage": round(coverage, 2),
            "retrieval_strength": round(retrieval_strength, 2),
            "match_quality": round(match_quality, 2),
        },
    )
