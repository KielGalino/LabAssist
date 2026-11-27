"""Tests for core/rag.py - chunking, Taglish expansion, hybrid search, BM25 fallback."""
import pytest

from core import rag


@pytest.fixture(scope="module")
def retriever():
    return rag.get_retriever()


def test_all_16_sops_loaded_and_chunked(retriever):
    sop_ids = {c["sop_id"] for c in retriever.chunks}
    assert len(sop_ids) == 16
    # every chunk keeps the SOP header for context
    assert all(c["text"].startswith("# SOP-") for c in retriever.chunks)


def test_taglish_expansion():
    tokens = rag.tokenize("sira ang mouse, walang tunog")
    assert {"broken", "damaged", "sound"} <= set(tokens)


@pytest.mark.parametrize("query, expected_sop", [
    ("My monitor has no signal, black screen", "SOP-03"),
    ("itim ang screen ng PC ko", "SOP-03"),
    ("nakalimutan ko password ko", "SOP-02"),
    ("walang internet sa PC-07", "SOP-06"),
    ("which server is PC-20 connected to", "SOP-05"),
    ("how do I connect to the faculty wifi", "SOP-07"),
    ("where do I save my files", "SOP-08"),
    ("paano mag-print", "SOP-09"),
    ("ayaw gumana ng mouse", "SOP-10"),
    ("can students install software", "SOP-11"),
    ("walang tunog ang headset", "SOP-12"),
    ("bawal ba kumain sa lab", "SOP-13"),
    ("may usok sa PC-12", "SOP-14"),
    ("what time does the lab open", "SOP-15"),
    ("projector no display", "SOP-16"),
])
def test_query_returns_right_sop(retriever, query, expected_sop):
    results, relevant = retriever.search(query, 4)
    assert relevant
    assert expected_sop in [r["sop_id"] for r in results[:2]]


@pytest.mark.parametrize("query", ["recipe for chicken adobo", "who won the NBA finals"])
def test_off_topic_is_not_relevant(retriever, query):
    _, relevant = retriever.search(query, 4)
    assert not relevant


def test_bm25_only_fallback_when_chroma_fails(retriever, monkeypatch):
    """If the vector DB breaks, search still works using BM25 only."""
    monkeypatch.setattr(retriever, "vector_ok", False)
    results, relevant = retriever.search("paano mag-print", 4)
    assert relevant and results[0]["sop_id"] == "SOP-09"
    assert all(r["vector"] == 0 for r in results)
