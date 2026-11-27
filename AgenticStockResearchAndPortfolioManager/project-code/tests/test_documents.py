"""documents.py: passage search over the RAG index, with citations and a 'not found' cutoff. Uses a fake store."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from documents import Documents, DocumentsError  # noqa: E402
from rag_store import RagError  # noqa: E402


class FakeStore:
    name = "fake-collection"

    def __init__(self, hits=None, error=None):
        self.hits, self.error, self.calls = hits or [], error, []

    def search(self, query, **kw):
        self.calls.append({"query": query, **kw})
        if self.error:
            raise self.error
        return self.hits


def hit(score, text="Margins will improve.", **kw):
    base = {"text": text, "symbol": "TCS", "doc_type": "transcript", "year": 2025, "month": "Oct",
            "file": "Transcript_Oct_2025.pdf", "page": 7, "chunk": 0, "score": score}
    return {**base, **kw}


def test_passages_carry_file_page_and_score():
    docs = Documents(FakeStore([hit(0.74)]), min_score=0.6)
    out = docs.search("margin outlook", symbol="tcs")
    assert out["found"] is True
    p = out["passages"][0]
    assert (p["file"], p["page"], p["doc_type"], p["year"], p["score"]) == ("Transcript_Oct_2025.pdf", 7, "transcript", 2025, 0.74)
    assert "Margins will improve." in p["text"]


def test_symbol_is_upper_cased_and_filters_are_passed_on():
    store = FakeStore([hit(0.9)])
    Documents(store, min_score=0.6).search("risk", symbol="tcs", doc_type="annual_report", year=2024, top_k=3)
    assert store.calls == [{"query": "risk", "symbol": "TCS", "doc_type": "annual_report", "year": 2024, "top_k": 3}]


def test_weak_matches_are_dropped_and_say_not_found():
    out = Documents(FakeStore([hit(0.52), hit(0.41)]), min_score=0.6).search("weather in Mumbai")
    assert out["found"] is False and out["passages"] == []
    assert "No passage" in out["message"]


def test_only_strong_matches_are_kept():
    out = Documents(FakeStore([hit(0.8), hit(0.5)]), min_score=0.6).search("margins")
    assert [p["score"] for p in out["passages"]] == [0.8]


def test_long_passage_text_is_shortened():
    out = Documents(FakeStore([hit(0.9, text="word " * 2000)]), min_score=0.6, max_chars=300).search("x")
    assert len(out["passages"][0]["text"]) <= 305


def test_unknown_doc_type_is_rejected():
    with pytest.raises(DocumentsError, match="doc_type"):
        Documents(FakeStore(), min_score=0.6).search("x", doc_type="tweet")


def test_empty_question_is_rejected():
    with pytest.raises(DocumentsError, match="query"):
        Documents(FakeStore(), min_score=0.6).search("  ")


def test_unfinished_index_is_reported_as_an_error():
    with pytest.raises(DocumentsError, match="not finished"):
        Documents(FakeStore(error=RagError("collection 'x' is not finished, so it is not searched yet")),
                  min_score=0.6).search("x")


def test_top_k_is_limited():
    store = FakeStore([hit(0.9)])
    Documents(store, min_score=0.6).search("x", top_k=99)
    assert store.calls[0]["top_k"] <= 10


def test_embedding_or_store_failure_becomes_a_plain_error():
    with pytest.raises(DocumentsError, match="unavailable.*OLLAMA_HOST"):
        Documents(FakeStore(error=ValueError("OLLAMA_HOST is not set")), min_score=0.6).search("x")
