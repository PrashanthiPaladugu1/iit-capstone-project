import hashlib
import re

import pymupdf
import pytest

import rag_store as rs


class FakeGateway:
    """Stands in for gateway.Gateway: a bag-of-words vector, so similar words give similar vectors."""
    def __init__(self):
        self.calls = 0

    def embed(self, texts, **kw):
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in re.findall(r"[a-z]+", t.lower()):
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0
            out.append(v)

        class R:
            vectors = out
        return R()


def make_pdf(path, pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=10)
    doc.save(str(path))
    doc.close()


@pytest.fixture
def store(tmp_path):
    return rs.RagStore(chroma_dir=tmp_path / "chroma", db=tmp_path / "rag.sqlite", gateway=FakeGateway(),
                       collection="test-collection")


@pytest.fixture
def docs(tmp_path):
    folder = tmp_path / "data" / "ACME"
    folder.mkdir(parents=True)
    make_pdf(folder / "Transcript_Oct_2024.pdf",
             ["Management said cement demand is strong and margins will improve next quarter. " * 6, ""])
    make_pdf(folder / "Annual_Report_2024.pdf",
             ["The board warns about currency risk and rising steel prices. " * 6])
    return folder


def test_ingest_stores_chunks_with_metadata(store, docs):
    res = store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1, 2))
    assert res["files_done"] == 2 and res["chunks"] > 0
    got = store.collection.get(limit=1, include=["metadatas"])["metadatas"][0]
    assert {"symbol", "doc_type", "year", "file", "page", "chunk"} <= set(got)
    assert got["symbol"] == "ACME"


def test_empty_pages_are_counted(store, docs):
    store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1,))
    row = [r for r in store.file_rows() if r["file"] == "Transcript_Oct_2024.pdf"][0]
    assert row["pages"] == 2 and row["empty_pages"] == 1 and row["status"] == "done"


def test_second_run_skips_done_files_and_does_not_embed_again(store, docs):
    store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1, 2))
    calls = store.gateway.calls
    again = store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1, 2))
    assert again["files_done"] == 0 and again["files_skipped"] == 2
    assert store.gateway.calls == calls


def test_bad_pdf_is_recorded_and_the_run_goes_on(store, docs):
    (docs / "Transcript_Jan_2023.pdf").write_bytes(b"not a pdf")
    res = store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1, 2))
    assert res["files_failed"] == 1 and res["files_done"] == 2
    bad = [r for r in store.file_rows() if r["status"] == "error"]
    assert bad and bad[0]["file"] == "Transcript_Jan_2023.pdf"


def test_failed_file_is_tried_again_next_run(store, docs):
    bad = docs / "Transcript_Jan_2023.pdf"
    bad.write_bytes(b"not a pdf")
    store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1,))
    make_pdf(bad, ["Now it is a real transcript about dividends. " * 5])
    res = store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1,))
    assert res["files_done"] == 1 and res["files_failed"] == 0


def test_search_returns_citations_and_filters(store, docs):
    store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1, 2))
    store.mark_complete()
    hits = store.search("currency risk steel prices", symbol="ACME", top_k=3)
    assert hits and hits[0]["file"] == "Annual_Report_2024.pdf" and hits[0]["page"] == 1
    assert {"text", "symbol", "doc_type", "year", "file", "page", "score"} <= set(hits[0])
    only_calls = store.search("cement demand", doc_type="transcript", top_k=5)
    assert only_calls and all(h["doc_type"] == "transcript" for h in only_calls)
    assert store.search("cement", symbol="OTHER") == []


def test_unfinished_collection_is_not_searched(store, docs):
    store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1,))
    with pytest.raises(rs.RagError, match="not finished"):
        store.search("cement")
    assert store.search("cement", allow_partial=True)


def test_status_counts(store, docs):
    store.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1, 2))
    s = store.status()
    assert s["collection"] == "test-collection" and s["files_done"] == 2 and s["complete"] is False
    assert s["chunks"] == store.collection.count()


def test_collections_are_separate(tmp_path, docs):
    a = rs.RagStore(chroma_dir=tmp_path / "chroma", db=tmp_path / "rag.sqlite", gateway=FakeGateway(), collection="coll-a")
    b = rs.RagStore(chroma_dir=tmp_path / "chroma", db=tmp_path / "rag.sqlite", gateway=FakeGateway(), collection="coll-b")
    a.ingest_stock("ACME", docs, size=300, overlap=30, tiers=(1,))
    assert a.collection.count() > 0 and b.collection.count() == 0
    assert b.status()["files_done"] == 0


def test_run_records(store):
    rid = store.start_run("--trial")
    assert store.run_rows()[0]["status"] == "running"
    store.finish_run(rid, "partial", {"files_done": 2, "files_skipped": 1, "files_failed": 0, "chunks": 40}, "ok")
    row = store.run_rows()[0]
    assert (row["status"], row["files_done"], row["chunks"], row["command"]) == ("partial", 2, 40, "--trial")
    assert row["finished"] >= row["started"]
