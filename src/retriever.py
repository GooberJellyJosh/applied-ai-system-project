"""
Retriever for the VibeFinder assistant.

Given a plain-language request, the retriever finds the knowledge base
documents that are most relevant to it. It uses TF-IDF vectors and cosine
similarity, written with only the Python standard library:

    TF  (term frequency)          a word counts more the more a document uses it
    IDF (inverse document freq.)  a word counts more the fewer documents use it
    cosine similarity             compares the direction of two vectors, so a
                                  long document is not favored over a short one

A similarity of 0 means "no shared meaningful words" and 1 means "same words".
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.knowledge_base import KnowledgeDocument

# Words that carry no musical meaning. They are removed before matching so a
# request like "I want some music for studying" is matched on "studying" only.
STOP_WORDS = {
    "a", "about", "an", "and", "any", "anything", "are", "as", "at", "be", "but",
    "by", "can", "could", "do", "don", "except", "for", "from", "get", "give",
    "got", "have", "how", "i", "if", "im", "in", "is", "it", "its", "just",
    "kind", "like", "listen", "looking", "love", "me", "music", "my", "need",
    "no", "not", "nothing", "of", "on", "or", "play", "playlist", "please",
    "really", "recommend", "recommendation", "recommendations", "should", "so",
    "some", "something", "song", "songs", "sort", "stuff", "suggest", "that",
    "the", "then", "these", "thing", "things", "this", "to", "track", "tracks",
    "tune", "tunes", "up", "very", "want", "wanna", "was", "what", "when",
    "which", "while", "will", "with", "without", "would", "you", "your",
}

# A token is letters/digits, optionally joined by "&" so "r&b" stays one word.
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:&[a-z0-9]+)*")

# Words this short are never stemmed ("pop", "sad", "80s")
MIN_LENGTH_TO_STEM = 4
# A stem must keep at least this many letters
MIN_STEM_LENGTH = 3


def stem_word(word: str) -> str:
    """
    Reduce a word to a rough root so related forms match each other.

    Examples: studying -> study, relaxed -> relax, running -> run, dances -> danc.
    The root does not have to be a real word. It only has to be the same for
    the request and for the documents.
    """
    if len(word) < MIN_LENGTH_TO_STEM:
        return word

    # "studies" -> "study"
    if word.endswith("ies") and len(word) - 3 >= MIN_STEM_LENGTH - 1:
        word = word[:-3] + "y"
    else:
        for suffix in ("ing", "ed", "es", "s"):
            if not word.endswith(suffix) or len(word) - len(suffix) < MIN_STEM_LENGTH:
                continue
            # Leave words such as "focus", "bass", and "this" alone
            if suffix == "s" and word.endswith(("ss", "us", "is")):
                break
            root = word[: -len(suffix)]
            # "running" -> "runn" -> "run" (but keep "chill", "bass", "jazz")
            ends_with_doubled_letter = len(root) > MIN_STEM_LENGTH and root[-1] == root[-2]
            if suffix in ("ing", "ed") and ends_with_doubled_letter and root[-1] not in "lsz":
                root = root[:-1]
            word = root
            break

    # "dance" and "dancing" should both end up as "danc"
    if len(word) > MIN_STEM_LENGTH and word.endswith("e"):
        word = word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    """Split text into lowercase stemmed words, dropping stop words and single letters."""
    # Hyphens become spaces so "late-night" matches "late night"
    lowered_text = text.lower().replace("-", " ")
    tokens = []
    for raw_token in TOKEN_PATTERN.findall(lowered_text):
        if len(raw_token) < 2 or raw_token in STOP_WORDS:
            continue
        tokens.append(stem_word(raw_token))
    return tokens


@dataclass
class RetrievedDocument:
    """A knowledge base document together with how well it matched the request."""
    document: KnowledgeDocument
    similarity: float                                        # cosine similarity, 0 to 1
    matched_terms: List[str] = field(default_factory=list)   # request words found in the document


class TfidfRetriever:
    """Ranks knowledge base documents against a request using TF-IDF cosine similarity."""

    def __init__(self, documents: List[KnowledgeDocument]):
        self.documents = documents
        tokenized_documents = [tokenize(document.text) for document in documents]

        # Document frequency: in how many documents does each word appear?
        document_frequency: Counter = Counter()
        for document_tokens in tokenized_documents:
            document_frequency.update(set(document_tokens))

        # Smoothed IDF so a word that appears everywhere still gets a small weight
        document_count = len(documents)
        self.inverse_document_frequency: Dict[str, float] = {
            term: math.log((1 + document_count) / (1 + frequency)) + 1.0
            for term, frequency in document_frequency.items()
        }

        # Pre-compute one unit-length TF-IDF vector per document
        self.document_vectors: List[Dict[str, float]] = [
            self._build_vector(document_tokens) for document_tokens in tokenized_documents
        ]

    def _build_vector(self, tokens: List[str]) -> Dict[str, float]:
        """Turn a list of tokens into a unit-length TF-IDF vector (stored as a dict)."""
        term_counts = Counter(token for token in tokens if token in self.inverse_document_frequency)
        vector = {
            # 1 + log(count) keeps a repeated word from dominating the vector
            term: (1.0 + math.log(count)) * self.inverse_document_frequency[term]
            for term, count in term_counts.items()
        }
        vector_length = math.sqrt(sum(weight * weight for weight in vector.values()))
        if vector_length == 0:
            return {}
        return {term: weight / vector_length for term, weight in vector.items()}

    def search(
        self,
        query: str,
        top_k: Optional[int] = 5,
        doc_type: Optional[str] = None,
        min_similarity: float = 0.0,
    ) -> List[RetrievedDocument]:
        """
        Return the documents most similar to the query, best first.

        top_k=None returns every match. doc_type limits the search to one kind
        of document. Documents at or below min_similarity are left out.
        """
        query_vector = self._build_vector(tokenize(query))
        if not query_vector:
            return []  # nothing in the request is known to the knowledge base

        matches = []
        for document, document_vector in zip(self.documents, self.document_vectors):
            if doc_type is not None and document.doc_type != doc_type:
                continue
            shared_terms = [term for term in query_vector if term in document_vector]
            if not shared_terms:
                continue
            # Both vectors are unit length, so the dot product is the cosine similarity
            similarity = sum(query_vector[term] * document_vector[term] for term in shared_terms)
            if similarity > min_similarity:
                matches.append(RetrievedDocument(document, round(similarity, 4), sorted(shared_terms)))

        # Highest similarity first; ties are broken by id so results are repeatable
        matches.sort(key=lambda match: (-match.similarity, match.document.doc_id))
        return matches if top_k is None else matches[:top_k]
