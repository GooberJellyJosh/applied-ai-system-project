"""
Request planner for the VibeFinder assistant.

The planner turns a plain-language request into a RequestPlan: the
preferences to score songs with, the scoring mode to use, and the evidence
(knowledge base documents) behind each decision.

It combines two ways of looking things up in the knowledge base:

    1. Named mentions   the request contains a guide's name or alias, such
                        as "lofi", "mellow", "gym", or "no lyrics"
    2. Retrieval        the request only describes what it wants ("music to
                        fall asleep to"), so the retriever finds the closest
                        guide by TF-IDF similarity

A named mention always wins over a retrieved guess. Every preference in the
plan records which document it came from, so the final answer can cite it.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from src.app_logging import get_logger
from src.guardrails import clamp_preferences
from src.knowledge_base import (
    ACTIVITY_TYPE,
    GENRE_TYPE,
    MOOD_TYPE,
    SONG_TYPE,
    TRAIT_TYPE,
    KnowledgeBase,
    KnowledgeDocument,
)
from src.retriever import RetrievedDocument, TfidfRetriever, stem_word, tokenize

logger = get_logger("planner")

# A retrieved (not named) guide is only trusted above these similarities
INFERRED_GENRE_MIN_SIMILARITY = 0.25
INFERRED_MOOD_MIN_SIMILARITY = 0.20
INFERRED_ACTIVITY_MIN_SIMILARITY = 0.20

# Relevance gate for requests that name no guide: below these values the request
# is treated as "not about music". Coverage is strict on purpose, because a
# request whose main word is unknown ("write my essay about the day") can still
# share a few everyday words with the guides.
MIN_RELEVANT_SIMILARITY = 0.12
MIN_REQUEST_COVERAGE = 0.75

# How many retrieved documents are kept for the trace and the log
RETRIEVED_DOCUMENTS_TO_KEEP = 8

# Words that flip the meaning of the genre or mood that follows them
NEGATION_WORDS = {
    "not", "no", "non", "without", "except", "excluding", "avoid", "skip",
    "hate", "dislike", "never", "nothing", "dont", "don't", "isn't", "isnt",
}
# How many words before a mention are checked for a negation word
NEGATION_WINDOW_WORDS = 3
# Words that carry a negation on to the next mention ("no country or metal")
NEGATION_CONNECTORS = {"or", "nor"}

# Guide types that can be found by name inside the request
MENTIONABLE_TYPES = (GENRE_TYPE, MOOD_TYPE, ACTIVITY_TYPE, TRAIT_TYPE)

# Matches "80s", "1980s", "90's", and "2010s"
DECADE_PATTERN = re.compile(r"(?<![a-z0-9])((?:19|20)?\d0)'?s(?![a-z0-9])")
# Two-digit decades from the 30s up belong to the 1900s; "00s"-"20s" to the 2000s
FIRST_TWO_DIGIT_DECADE_OF_1900S = 30

# Characters that end a clause when looking backwards for a negation word
CLAUSE_BOUNDARY_PATTERN = re.compile(r"[|,.;:!?]")


@dataclass
class GuideMention:
    """A guide whose name or alias was found word-for-word in the request."""
    document: KnowledgeDocument
    matched_phrase: str        # the exact words found, e.g. "lo-fi"
    start_position: int        # character position in the request
    end_position: int
    is_negated: bool = False   # True for "not sad", "no country", ...


@dataclass
class PlanEvidence:
    """Records where one preference came from."""
    preference_name: str   # e.g. "energy"
    value: Any             # e.g. 0.35
    source_doc_id: str     # e.g. "activity:studying"
    how_found: str         # e.g. 'you said "studying"' or "retrieved (similarity 0.33)"


@dataclass
class RequestPlan:
    """Everything the assistant decided about a request before ranking songs."""
    request_text: str
    preferences: Dict = field(default_factory=dict)
    scoring_mode_name: str = "balanced"
    use_diversity: bool = True
    genre_was_named: bool = False                  # the user typed the genre themselves
    excluded_genres: List[str] = field(default_factory=list)
    excluded_moods: List[str] = field(default_factory=list)
    evidence: List[PlanEvidence] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)           # readable planning steps
    warnings: List[str] = field(default_factory=list)
    retrieved_documents: List[RetrievedDocument] = field(default_factory=list)
    song_matches: Dict[int, RetrievedDocument] = field(default_factory=dict)  # song id -> match
    top_similarity: float = 0.0       # best similarity of any retrieved document
    request_coverage: float = 0.0     # share of request words the knowledge base recognized
    has_named_mentions: bool = False
    # Set by the self-check when the requested genre is not in the catalog and
    # the closest available genre is used instead (holds the original request).
    originally_requested_genre: Optional[str] = None

    @property
    def is_understood(self) -> bool:
        """True when the knowledge base recognized enough of the request to act on it."""
        if self.has_named_mentions:
            return True
        return (
            self.top_similarity >= MIN_RELEVANT_SIMILARITY
            and self.request_coverage >= MIN_REQUEST_COVERAGE
        )

    def evidence_for(self, preference_name: str) -> Optional[PlanEvidence]:
        """Return the evidence that set a preference, or None if it was never set."""
        for evidence_item in self.evidence:
            if evidence_item.preference_name == preference_name:
                return evidence_item
        return None


# ---------------------------------------------------------------------------
# Step 1: find guides that are named in the request
# ---------------------------------------------------------------------------
def find_guide_mentions(request_text: str, knowledge_base: KnowledgeBase) -> List[GuideMention]:
    """Find every guide name or alias that appears as whole words in the request."""
    lowered_request = request_text.lower()

    # Collect (phrase, document) pairs and try the longest phrases first so
    # "indie pop" is matched before "pop" and "k-pop" before "pop".
    phrase_candidates = []
    for doc_type in MENTIONABLE_TYPES:
        for document in knowledge_base.documents_of_type(doc_type):
            for phrase in [document.name, *document.metadata.get("aliases", [])]:
                phrase_candidates.append((phrase.lower(), document))
    phrase_candidates.sort(key=lambda candidate: (-len(candidate[0]), candidate[0]))

    is_character_claimed = [False] * len(lowered_request)
    mentions: List[GuideMention] = []
    mentioned_doc_ids: Set[str] = set()

    for phrase, document in phrase_candidates:
        # The phrase must not be glued to other letters ("pop" inside "popular")
        phrase_pattern = re.compile(r"(?<![a-z0-9&])" + re.escape(phrase) + r"(?![a-z0-9&])")
        for match in phrase_pattern.finditer(lowered_request):
            if any(is_character_claimed[match.start():match.end()]):
                continue  # these words already belong to a longer phrase
            for position in range(match.start(), match.end()):
                is_character_claimed[position] = True
            if document.doc_id in mentioned_doc_ids:
                continue  # the same guide was already mentioned earlier
            mentioned_doc_ids.add(document.doc_id)
            mentions.append(GuideMention(document, phrase, match.start(), match.end()))

    mentions.sort(key=lambda mention: mention.start_position)
    _mark_negated_mentions(lowered_request, mentions, is_character_claimed)
    return mentions


def _mark_negated_mentions(
    lowered_request: str, mentions: List[GuideMention], is_character_claimed: List[bool]
) -> None:
    """Set is_negated on mentions that follow a word like "not" or "no"."""
    # Hide every matched phrase behind "|" so a phrase such as "no lyrics"
    # cannot be mistaken for a negation of the mention that follows it.
    masked_request = "".join(
        "|" if is_character_claimed[position] else character
        for position, character in enumerate(lowered_request)
    )

    previous_mention: Optional[GuideMention] = None
    for mention in mentions:
        # Only look at the words in the same clause, right before the mention
        text_before_mention = masked_request[: mention.start_position]
        current_clause = CLAUSE_BOUNDARY_PATTERN.split(text_before_mention)[-1]
        words_before_mention = current_clause.split()[-NEGATION_WINDOW_WORDS:]

        if any(word in NEGATION_WORDS for word in words_before_mention):
            mention.is_negated = True
        elif "but" in words_before_mention and "anything" in lowered_request[: mention.start_position]:
            mention.is_negated = True  # "anything but country"
        elif previous_mention is not None and previous_mention.is_negated:
            # "no country or metal": the negation carries across "or"
            text_between = lowered_request[previous_mention.end_position: mention.start_position]
            if text_between.strip(" ,") in NEGATION_CONNECTORS:
                mention.is_negated = True
        previous_mention = mention


# ---------------------------------------------------------------------------
# Step 2: small helpers that read facts out of the request
# ---------------------------------------------------------------------------
def find_requested_decade(request_text: str) -> Optional[int]:
    """Return the decade named in the request (e.g. "80s" -> 1980), or None."""
    decade_match = DECADE_PATTERN.search(request_text.lower())
    if decade_match is None:
        return None

    decade_digits = decade_match.group(1)
    if len(decade_digits) == 4:
        return int(decade_digits)
    two_digit_decade = int(decade_digits)
    century = 1900 if two_digit_decade >= FIRST_TWO_DIGIT_DECADE_OF_1900S else 2000
    return century + two_digit_decade


def find_requested_mood_tags(request_text: str, songs: List[Dict]) -> List[str]:
    """Return the catalog's detailed mood tags (e.g. "nostalgic") that the request uses."""
    request_stems = set(tokenize(request_text))
    catalog_tags = sorted({tag for song in songs for tag in song.get("mood_tags", [])})
    return [tag for tag in catalog_tags if stem_word(tag.lower()) in request_stems]


def calculate_request_coverage(
    request_text: str, mentions: List[GuideMention], retrieved: List[RetrievedDocument]
) -> float:
    """Return the share (0-1) of meaningful request words the knowledge base recognized."""
    request_stems = set(tokenize(request_text))
    if not request_stems:
        return 0.0

    recognized_stems: Set[str] = set()
    for mention in mentions:
        recognized_stems.update(tokenize(mention.matched_phrase))
    for retrieved_document in retrieved:
        recognized_stems.update(retrieved_document.matched_terms)

    return round(len(request_stems & recognized_stems) / len(request_stems), 2)


def _best_retrieved_of_type(
    retrieved: List[RetrievedDocument], doc_type: str, min_similarity: float
) -> Optional[RetrievedDocument]:
    """Return the best retrieved document of one type if it clears the similarity bar."""
    for retrieved_document in retrieved:  # already sorted best first
        if retrieved_document.document.doc_type == doc_type:
            return retrieved_document if retrieved_document.similarity >= min_similarity else None
    return None


# ---------------------------------------------------------------------------
# Step 3: build the plan
# ---------------------------------------------------------------------------
def build_request_plan(
    request_text: str,
    knowledge_base: KnowledgeBase,
    retriever: TfidfRetriever,
    songs: List[Dict],
) -> RequestPlan:
    """Look the request up in the knowledge base and decide how to rank songs for it."""
    plan = RequestPlan(request_text=request_text)

    # --- Named mentions ------------------------------------------------------
    mentions = find_guide_mentions(request_text, knowledge_base)
    wanted_mentions = [mention for mention in mentions if not mention.is_negated]
    # A request that only says what to leave out ("not pop") is still understood
    plan.has_named_mentions = bool(mentions)

    # --- Retrieve: search every document for the request --------------------
    # Words the listener ruled out are blanked first, so "not pop" does not
    # pull pop songs towards the top of the search results.
    search_characters = list(request_text)
    for mention in mentions:
        if mention.is_negated:
            for position in range(mention.start_position, mention.end_position):
                search_characters[position] = " "
    all_retrieved = retriever.search("".join(search_characters), top_k=None)

    plan.retrieved_documents = all_retrieved[:RETRIEVED_DOCUMENTS_TO_KEEP]
    plan.top_similarity = all_retrieved[0].similarity if all_retrieved else 0.0
    plan.song_matches = {
        retrieved_document.document.metadata["song_id"]: retrieved_document
        for retrieved_document in all_retrieved
        if retrieved_document.document.doc_type == SONG_TYPE
    }
    plan.request_coverage = calculate_request_coverage(request_text, mentions, all_retrieved)

    # Negated genres and moods become exclusions
    for mention in mentions:
        if not mention.is_negated:
            continue
        if mention.document.doc_type == GENRE_TYPE:
            plan.excluded_genres.append(mention.document.name)
            plan.notes.append(f"Excluding genre \"{mention.document.name}\" (the request rules it out).")
        elif mention.document.doc_type == MOOD_TYPE:
            plan.excluded_moods.append(mention.document.name)
            plan.notes.append(f"Excluding mood \"{mention.document.name}\" (the request rules it out).")
        else:
            # "not too loud" or "not for the gym": the guide is not applied, and
            # the assistant does not try to guess the opposite
            plan.notes.append(f"Ignoring the \"{mention.document.name}\" guide (the request rules it out).")

    def set_preference(preference_name: str, value: Any, document: KnowledgeDocument, how_found: str) -> None:
        """Store a preference and remember which document it came from (later calls override)."""
        plan.preferences[preference_name] = value
        plan.evidence = [item for item in plan.evidence if item.preference_name != preference_name]
        plan.evidence.append(PlanEvidence(preference_name, value, document.doc_id, how_found))

    def first_named(doc_type: str) -> Optional[GuideMention]:
        """Return the first wanted mention of one guide type."""
        for mention in wanted_mentions:
            if mention.document.doc_type == doc_type:
                return mention
        return None

    # --- Genre: named first, otherwise the best retrieved genre guide --------
    genre_mention = first_named(GENRE_TYPE)
    if genre_mention is not None:
        genre_document = genre_mention.document
        plan.genre_was_named = True
        set_preference("genre", genre_document.name, genre_document, f'you said "{genre_mention.matched_phrase}"')
    else:
        retrieved_genre = _best_retrieved_of_type(all_retrieved, GENRE_TYPE, INFERRED_GENRE_MIN_SIMILARITY)
        genre_document = retrieved_genre.document if retrieved_genre else None
        if retrieved_genre is not None and genre_document.name not in plan.excluded_genres:
            set_preference("genre", genre_document.name, genre_document,
                           f"retrieved genre guide (similarity {retrieved_genre.similarity:.2f})")
        else:
            genre_document = None

    # The genre's typical energy is the weakest energy hint; later sources override it
    if genre_document is not None and "typical_energy" in genre_document.metadata:
        set_preference("energy", genre_document.metadata["typical_energy"], genre_document,
                       f"typical energy of {genre_document.name}")

    # --- Activity: named first, otherwise the best retrieved activity guide --
    activity_mention = first_named(ACTIVITY_TYPE)
    activity_document = None
    activity_how_found = ""
    if activity_mention is not None:
        activity_document = activity_mention.document
        activity_how_found = f'you said "{activity_mention.matched_phrase}"'
    else:
        retrieved_activity = _best_retrieved_of_type(all_retrieved, ACTIVITY_TYPE, INFERRED_ACTIVITY_MIN_SIMILARITY)
        if retrieved_activity is not None:
            activity_document = retrieved_activity.document
            activity_how_found = f"retrieved activity guide (similarity {retrieved_activity.similarity:.2f})"

    # --- Mood: named first, then the activity's mood, then a retrieved mood --
    mood_mention = first_named(MOOD_TYPE)
    mood_document = None
    if mood_mention is not None:
        mood_document = mood_mention.document
        set_preference("mood", mood_document.name, mood_document, f'you said "{mood_mention.matched_phrase}"')
    elif activity_document is None or "mood" not in activity_document.metadata.get("suggested_preferences", {}):
        # No named mood and no activity that implies one: fall back to retrieval
        retrieved_mood = _best_retrieved_of_type(all_retrieved, MOOD_TYPE, INFERRED_MOOD_MIN_SIMILARITY)
        if retrieved_mood is not None and retrieved_mood.document.name not in plan.excluded_moods:
            mood_document = retrieved_mood.document
            set_preference("mood", mood_document.name, mood_document,
                           f"retrieved mood guide (similarity {retrieved_mood.similarity:.2f})")

    if mood_document is not None and "typical_energy" in mood_document.metadata:
        set_preference("energy", mood_document.metadata["typical_energy"], mood_document,
                       f"typical energy of {mood_document.name} music")

    # --- Apply the activity's suggested preferences ---------------------------
    if activity_document is not None:
        suggested_preferences = activity_document.metadata.get("suggested_preferences", {})
        for preference_name, value in suggested_preferences.items():
            if preference_name == "mood":
                # A mood the user named, or one they ruled out, beats the activity's default
                if mood_document is not None or value in plan.excluded_moods:
                    continue
            set_preference(preference_name, value, activity_document, activity_how_found)
        plan.notes.append(f"Used the \"{activity_document.name}\" activity guide ({activity_how_found}).")

    # --- Sound traits ("no lyrics", "upbeat") are the most specific hints ----
    for mention in wanted_mentions:
        if mention.document.doc_type != TRAIT_TYPE:
            continue
        for preference_name, value in mention.document.metadata.get("suggested_preferences", {}).items():
            set_preference(preference_name, value, mention.document, f'you said "{mention.matched_phrase}"')

    # --- Facts read straight from the request text ----------------------------
    requested_decade = find_requested_decade(request_text)
    if requested_decade is not None:
        plan.preferences["decade"] = requested_decade
        plan.notes.append(f"Found a decade in the request: {requested_decade}s.")

    requested_mood_tags = find_requested_mood_tags(request_text, songs)
    existing_mood_tags = plan.preferences.get("mood_tags", [])
    combined_mood_tags = sorted(set(existing_mood_tags) | set(requested_mood_tags))
    if combined_mood_tags:
        plan.preferences["mood_tags"] = combined_mood_tags

    # --- Guardrail: keep every numeric target inside its valid range ---------
    plan.preferences, clamp_warnings = clamp_preferences(plan.preferences)
    plan.warnings.extend(clamp_warnings)

    # --- Choose how to rank ---------------------------------------------------
    plan.scoring_mode_name, mode_reason = choose_scoring_mode(plan)
    plan.notes.append(mode_reason)
    # Variety helps when the listener did not ask for one specific genre
    plan.use_diversity = not plan.genre_was_named

    logger.info(
        "Plan for %r: preferences=%s mode=%s diversity=%s coverage=%.2f top_similarity=%.2f",
        request_text, plan.preferences, plan.scoring_mode_name, plan.use_diversity,
        plan.request_coverage, plan.top_similarity,
    )
    return plan


def choose_scoring_mode(plan: RequestPlan) -> tuple:
    """Pick the scoring strategy that fits what the request did and did not specify."""
    has_genre = "genre" in plan.preferences
    has_mood = "mood" in plan.preferences
    has_energy = "energy" in plan.preferences

    if plan.genre_was_named and not has_mood:
        return "genre_first", "Scoring mode genre_first: a genre was named and no mood was given."
    if has_mood and not has_genre:
        return "mood_first", "Scoring mode mood_first: a mood is known but no genre was requested."
    if has_energy and not has_genre and not has_mood:
        return "energy_focused", "Scoring mode energy_focused: only the intensity of the music is known."
    return "balanced", "Scoring mode balanced: weighing genre, mood, and energy together."
