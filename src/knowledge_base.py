"""
Knowledge base for the VibeFinder assistant.

The assistant never answers from the raw request alone. It first looks things
up in this knowledge base, which is built from five sources:

    1. data/songs.csv                  -> one "song" document per catalog song
    2. data/knowledge/genres.json      -> genre guides (including genres the
                                          catalog does not have, with their
                                          closest in-catalog relatives)
    3. data/knowledge/moods.json       -> mood guides and similar moods
    4. data/knowledge/activities.json  -> what listeners want for an activity
    5. data/knowledge/sound_traits.json-> phrases like "no lyrics" or "upbeat"

Every source is turned into KnowledgeDocument objects so the retriever can
search all of them the same way.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Document types stored in the knowledge base
SONG_TYPE = "song"
GENRE_TYPE = "genre"
MOOD_TYPE = "mood"
ACTIVITY_TYPE = "activity"
TRAIT_TYPE = "trait"

# Guide file name for each non-song document type
GUIDE_FILES = {
    GENRE_TYPE: "genres.json",
    MOOD_TYPE: "moods.json",
    ACTIVITY_TYPE: "activities.json",
    TRAIT_TYPE: "sound_traits.json",
}

DEFAULT_KNOWLEDGE_DIR = "data/knowledge"

# Cut-off values used to describe a song's numbers in plain words, so a
# request such as "quiet acoustic song" can match a song whose row only
# contains energy=0.30 and acousticness=0.90.
LOW_ENERGY_MAX = 0.40
HIGH_ENERGY_MIN = 0.70
SLOW_TEMPO_MAX_BPM = 85
FAST_TEMPO_MIN_BPM = 120
ACOUSTIC_MIN = 0.60
ELECTRONIC_MAX = 0.20
INSTRUMENTAL_MIN = 0.60
VOCAL_MAX = 0.20
POSITIVE_VALENCE_MIN = 0.70
DARK_VALENCE_MAX = 0.40
DANCEABLE_MIN = 0.75
SPOKEN_WORD_MIN = 0.30
POPULAR_MIN = 75
UNDERGROUND_MAX = 45


@dataclass
class KnowledgeDocument:
    """One searchable entry in the knowledge base."""
    doc_id: str      # unique id such as "song:2" or "genre:lofi"
    doc_type: str    # one of the *_TYPE constants above
    name: str        # short label, e.g. "lofi" or "Midnight Coding"
    text: str        # the full text the retriever searches
    summary: str     # one readable sentence the assistant can quote as evidence
    metadata: Dict = field(default_factory=dict)  # structured facts for the planner


class KnowledgeBase:
    """Holds every document and offers simple lookups by id and by type."""

    def __init__(self, documents: List[KnowledgeDocument]):
        self.documents = documents
        self._documents_by_id = {document.doc_id: document for document in documents}

    def get(self, doc_id: str) -> Optional[KnowledgeDocument]:
        """Return the document with this id, or None when it does not exist."""
        return self._documents_by_id.get(doc_id)

    def documents_of_type(self, doc_type: str) -> List[KnowledgeDocument]:
        """Return every document of one type, in load order."""
        return [document for document in self.documents if document.doc_type == doc_type]

    def __len__(self) -> int:
        return len(self.documents)


def describe_song_in_words(song: Dict) -> List[str]:
    """Translate a song's numeric attributes into descriptive phrases."""
    phrases = []

    # Energy
    if song["energy"] < LOW_ENERGY_MAX:
        phrases.append("low energy, quiet, soft and gentle")
    elif song["energy"] >= HIGH_ENERGY_MIN:
        phrases.append("high energy, loud, energetic and powerful")
    else:
        phrases.append("medium energy")

    # Tempo
    if song["tempo_bpm"] < SLOW_TEMPO_MAX_BPM:
        phrases.append("slow tempo")
    elif song["tempo_bpm"] > FAST_TEMPO_MIN_BPM:
        phrases.append("fast tempo")
    else:
        phrases.append("mid tempo")

    # Acoustic versus electronic production
    if song["acousticness"] >= ACOUSTIC_MIN:
        phrases.append("acoustic, unplugged sound")
    elif song["acousticness"] <= ELECTRONIC_MAX:
        phrases.append("electronic, produced sound")

    # Vocals (only described when the catalog has the attribute)
    instrumentalness = song.get("instrumentalness")
    if instrumentalness is not None:
        if instrumentalness >= INSTRUMENTAL_MIN:
            phrases.append("instrumental, wordless")
        elif instrumentalness <= VOCAL_MAX:
            phrases.append("sung vocals")

    # Musical positivity
    if song["valence"] >= POSITIVE_VALENCE_MIN:
        phrases.append("bright and positive")
    elif song["valence"] <= DARK_VALENCE_MAX:
        phrases.append("dark and emotional")

    if song["danceability"] >= DANCEABLE_MIN:
        phrases.append("danceable and groovy")

    speechiness = song.get("speechiness")
    if speechiness is not None and speechiness >= SPOKEN_WORD_MIN:
        phrases.append("rapped verses, lyrical")

    popularity = song.get("popularity")
    if popularity is not None:
        if popularity >= POPULAR_MIN:
            phrases.append("popular mainstream hit")
        elif popularity <= UNDERGROUND_MAX:
            phrases.append("underground hidden gem")

    return phrases


def build_song_document(song: Dict) -> KnowledgeDocument:
    """Create the searchable document for one catalog song."""
    mood_tags = song.get("mood_tags") or []
    descriptive_phrases = describe_song_in_words(song)

    summary = f"\"{song['title']}\" by {song['artist']} is a {song['mood']} {song['genre']} song"
    if mood_tags:
        summary += f" tagged {', '.join(mood_tags)}"
    summary += f" ({'; '.join(descriptive_phrases)})."

    # The searchable text repeats the genre and mood so they weigh more than
    # a single descriptive word.
    text_parts = [
        song["title"],
        song["artist"],
        song["genre"], song["genre"],
        song["mood"], song["mood"],
        " ".join(mood_tags),
        ". ".join(descriptive_phrases),
    ]
    release_decade = song.get("release_decade")
    if release_decade is not None:
        # Both spellings so "80s" and "1980s" can match
        text_parts.append(f"{release_decade}s {str(release_decade)[2:]}s")

    return KnowledgeDocument(
        doc_id=f"{SONG_TYPE}:{song['id']}",
        doc_type=SONG_TYPE,
        name=song["title"],
        text=" ".join(text_parts),
        summary=summary,
        metadata={"song_id": song["id"]},
    )


def build_guide_document(doc_type: str, entry: Dict) -> KnowledgeDocument:
    """Create the searchable document for one guide entry (genre, mood, activity, or trait)."""
    name = entry["name"]
    aliases = entry.get("aliases", [])
    description = entry["description"]

    # Everything except the display fields is kept as structured metadata
    # (typical_energy, similar_genres, suggested_preferences, ...).
    metadata = {key: value for key, value in entry.items() if key not in ("name", "description")}

    return KnowledgeDocument(
        doc_id=f"{doc_type}:{name}",
        doc_type=doc_type,
        name=name,
        text=f"{name} {name} {' '.join(aliases)} {description}",
        summary=f"{doc_type.capitalize()} guide \"{name}\": {description}",
        metadata=metadata,
    )


def load_guide_entries(guide_path: Path) -> List[Dict]:
    """Read one guide JSON file and check that every entry has the required fields."""
    with open(guide_path, encoding="utf-8") as guide_file:
        entries = json.load(guide_file)

    if not isinstance(entries, list):
        raise ValueError(f"{guide_path} must contain a JSON list of guide entries")
    for entry in entries:
        if "name" not in entry or "description" not in entry:
            raise ValueError(f"Every entry in {guide_path} needs a 'name' and a 'description'")
    return entries


def load_knowledge_base(
    songs: List[Dict],
    knowledge_dir: str = DEFAULT_KNOWLEDGE_DIR,
    include_guides: bool = True,
) -> KnowledgeBase:
    """
    Build the knowledge base from the song catalog and the guide files.

    include_guides=False builds a songs-only knowledge base. The evaluation
    script uses it as a baseline to measure how much the guides help.
    """
    documents = [build_song_document(song) for song in songs]

    if include_guides:
        for doc_type, file_name in GUIDE_FILES.items():
            guide_path = Path(knowledge_dir) / file_name
            for entry in load_guide_entries(guide_path):
                documents.append(build_guide_document(doc_type, entry))

    return KnowledgeBase(documents)
