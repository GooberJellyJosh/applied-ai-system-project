"""Shared pytest fixtures: the real catalog, knowledge base, and retriever."""

import pytest

from src.knowledge_base import load_knowledge_base
from src.recommender import load_songs
from src.retriever import TfidfRetriever

SONGS_CSV_PATH = "data/songs.csv"


@pytest.fixture(scope="session")
def songs():
    """The full song catalog from data/songs.csv."""
    return load_songs(SONGS_CSV_PATH)


@pytest.fixture(scope="session")
def knowledge_base(songs):
    """The knowledge base built from the catalog and every guide file."""
    return load_knowledge_base(songs)


@pytest.fixture(scope="session")
def retriever(knowledge_base):
    """A retriever over the full knowledge base."""
    return TfidfRetriever(knowledge_base.documents)

