"""Vector store for document search (RAG). One Chroma collection per embedding model and chunking setting.

- Embedding goes only through the gateway (role "embedding"), so changing provider needs no change here.
- Ingest is resumable: each file is recorded in SQLite when it is finished; a later run skips finished files.
  Chunk ids are fixed (symbol/file/page/chunk), so a file that was cut off half way is simply written again.
- A collection is searched only after mark_complete(), so a half-built collection never answers questions.
- Nothing is deleted. A new setting makes a new collection beside the old one.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

import config
import rag_chunker

EMBED_BATCH = 32

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  collection TEXT NOT NULL, symbol TEXT NOT NULL, file TEXT NOT NULL, doc_type TEXT, year INTEGER,
  pages INTEGER DEFAULT 0, empty_pages INTEGER DEFAULT 0, chunks INTEGER DEFAULT 0,
  size INTEGER, overlap INTEGER, status TEXT NOT NULL, error TEXT DEFAULT '', updated REAL,
  PRIMARY KEY(collection, symbol, file));
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT, started REAL, finished REAL, command TEXT,
  status TEXT, files_done INTEGER DEFAULT 0, files_skipped INTEGER DEFAULT 0, files_failed INTEGER DEFAULT 0,
  chunks INTEGER DEFAULT 0, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS collections(
  collection TEXT PRIMARY KEY, complete INTEGER DEFAULT 0, created REAL, completed REAL);
"""


class RagError(RuntimeError):
    pass


class RagStore:
    def __init__(self, chroma_dir: Path | str | None = None, db: Path | str | None = None, gateway=None,
                 collection: str | None = None):
        self.db = Path(db) if db else config.get("rag_db")
        self.chroma_dir = Path(chroma_dir) if chroma_dir else config.chroma_dir()
        self._gateway = gateway
        self.name = collection or self._current_collection_name()
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as con, con:
            con.executescript(_SCHEMA)
            con.execute("INSERT OR IGNORE INTO collections(collection, created) VALUES(?, ?)", (self.name, time.time()))
        import chromadb
        self._client = chromadb.PersistentClient(path=str(self.chroma_dir))
        self.collection = self._client.get_or_create_collection(self.name, metadata={"hnsw:space": "cosine"})

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _current_collection_name() -> str:
        from model_settings import SettingsStore
        return SettingsStore().embedding_collection()

    @property
    def gateway(self):
        if self._gateway is None:
            from gateway import Gateway
            self._gateway = Gateway()
        return self._gateway

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db)
        con.row_factory = sqlite3.Row
        return con

    # ------------------------------------------------------------------ ingest
    def ingest_stock(self, symbol: str, folder: Path, *, size: int, overlap: int, tiers=(1, 2, 3),
                     annual_reports: int = rag_chunker.LATEST_ANNUAL_REPORTS, log=lambda msg: None,
                     on_file=lambda file, pages, chunks: None) -> dict:
        """on_file(file, pages, chunks) is called after each finished file, for progress reporting."""
        res = {"files_done": 0, "files_skipped": 0, "files_failed": 0, "chunks": 0}
        for pdf in rag_chunker.select_documents(Path(folder), tiers, annual_reports=annual_reports):
            if self._status(symbol, pdf.name) == "done":
                res["files_skipped"] += 1
                continue
            info = rag_chunker.parse_document_name(pdf.name)
            try:
                pages = rag_chunker.read_pdf_pages(pdf)
                chunks, stats = rag_chunker.chunk_pages(pages, size, overlap)
            except Exception as exc:                     # a damaged PDF must not stop the whole run
                self._record(symbol, pdf.name, info, "error", error=f"{type(exc).__name__}: {exc}"[:300])
                res["files_failed"] += 1
                log(f"  FAILED {symbol}/{pdf.name}: {exc}")
                continue
            self._add_chunks(symbol, pdf.name, info, chunks)       # an embedding error stops the run; it can be resumed
            self._record(symbol, pdf.name, info, "done", stats=stats, size=size, overlap=overlap)
            res["files_done"] += 1
            res["chunks"] += stats["chunks"]
            log(f"  {symbol}/{pdf.name}: {stats['pages']} pages, {stats['empty_pages']} empty, {stats['chunks']} chunks")
            on_file(pdf.name, stats["pages"], stats["chunks"])
        return res

    def _add_chunks(self, symbol, file, info, chunks) -> None:
        doc_type, year, month = info
        for i in range(0, len(chunks), EMBED_BATCH):
            batch = chunks[i:i + EMBED_BATCH]
            vectors = self.gateway.embed([c.text for c in batch], role="embedding", agent="rag_ingest").vectors
            if len(vectors) != len(batch):
                raise RagError(f"embedding returned {len(vectors)} vectors for {len(batch)} chunks")
            self.collection.upsert(
                ids=[f"{symbol}/{file}/{c.page}/{c.n}" for c in batch],
                embeddings=vectors,
                documents=[c.text for c in batch],
                metadatas=[{"symbol": symbol, "doc_type": doc_type, "year": year, "month": month,
                            "file": file, "page": c.page, "chunk": c.n} for c in batch])

    def _status(self, symbol: str, file: str):
        with closing(self._connect()) as con:
            row = con.execute("SELECT status FROM files WHERE collection=? AND symbol=? AND file=?",
                              (self.name, symbol, file)).fetchone()
        return row["status"] if row else None

    def _record(self, symbol, file, info, status, *, stats=None, error="", size=None, overlap=None) -> None:
        stats = stats or {}
        doc_type, year, _ = info if info else ("", 0, "")
        with closing(self._connect()) as con, con:
            con.execute(
                "INSERT INTO files(collection, symbol, file, doc_type, year, pages, empty_pages, chunks, size, overlap,"
                " status, error, updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(collection, symbol, file) DO UPDATE SET doc_type=excluded.doc_type, year=excluded.year,"
                " pages=excluded.pages, empty_pages=excluded.empty_pages, chunks=excluded.chunks, size=excluded.size,"
                " overlap=excluded.overlap, status=excluded.status, error=excluded.error, updated=excluded.updated",
                (self.name, symbol, file, doc_type, year, stats.get("pages", 0), stats.get("empty_pages", 0),
                 stats.get("chunks", 0), size, overlap, status, error, time.time()))

    # ------------------------------------------------------------------ run records
    def start_run(self, command: str) -> int:
        with closing(self._connect()) as con, con:
            return int(con.execute("INSERT INTO runs(collection, started, command, status) VALUES(?,?,?,'running')",
                                   (self.name, time.time(), command)).lastrowid)

    def finish_run(self, run_id: int, status: str, totals: dict | None = None, note: str = "") -> None:
        totals = totals or {}
        with closing(self._connect()) as con, con:
            con.execute("UPDATE runs SET finished=?, status=?, files_done=?, files_skipped=?, files_failed=?, chunks=?, note=? WHERE id=?",
                        (time.time(), status, totals.get("files_done", 0), totals.get("files_skipped", 0),
                         totals.get("files_failed", 0), totals.get("chunks", 0), note[:500], run_id))

    def run_rows(self, limit: int = 20) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM runs WHERE collection=? ORDER BY id DESC LIMIT ?", (self.name, limit)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ state
    def mark_complete(self) -> None:
        with closing(self._connect()) as con, con:
            con.execute("UPDATE collections SET complete=1, completed=? WHERE collection=?", (time.time(), self.name))

    def is_complete(self) -> bool:
        with closing(self._connect()) as con:
            row = con.execute("SELECT complete FROM collections WHERE collection=?", (self.name,)).fetchone()
        return bool(row and row["complete"])

    def file_rows(self) -> list[dict]:
        with closing(self._connect()) as con:
            rows = con.execute("SELECT * FROM files WHERE collection=? ORDER BY symbol, file", (self.name,)).fetchall()
        return [dict(r) for r in rows]

    def status(self) -> dict:
        rows = self.file_rows()
        done = [r for r in rows if r["status"] == "done"]
        return {"collection": self.name, "complete": self.is_complete(), "files_done": len(done),
                "files_failed": sum(r["status"] == "error" for r in rows),
                "stocks": len({r["symbol"] for r in done}), "pages": sum(r["pages"] for r in done),
                "empty_pages": sum(r["empty_pages"] for r in done), "chunks": self.collection.count()}

    # ------------------------------------------------------------------ search
    def search(self, query: str, *, symbol: str | None = None, doc_type: str | None = None, year: int | None = None,
               top_k: int = 8, allow_partial: bool = False) -> list[dict]:
        if not allow_partial and not self.is_complete():
            raise RagError(f"collection '{self.name}' is not finished, so it is not searched yet")
        filters = [{k: v} for k, v in (("symbol", symbol), ("doc_type", doc_type), ("year", year)) if v is not None]
        where = None if not filters else filters[0] if len(filters) == 1 else {"$and": filters}
        count = self.collection.count()
        if count == 0:
            return []
        vector = self.gateway.embed([query], role="embedding", agent="rag_search").vectors[0]
        found = self.collection.query(query_embeddings=[vector], n_results=min(top_k, count), where=where,
                                      include=["documents", "metadatas", "distances"])
        hits = []
        for text, meta, dist in zip(found["documents"][0], found["metadatas"][0], found["distances"][0]):
            hits.append({"text": text, **meta, "score": round(1.0 - float(dist), 4)})
        return hits
