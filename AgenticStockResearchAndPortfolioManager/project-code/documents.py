"""documents: search the annual reports, transcripts and presentations that were indexed by rag_build.py.

Used by the `rag_search_documents` tool of the fundamentals MCP server. Rules:
- Only a finished collection is searched (RagStore refuses otherwise).
- Every passage carries file and page, so the answer can cite its source.
- A match below `min_score` is treated as "not found". Numbers never come from here: the financial tools give those.
"""
from __future__ import annotations

from rag_store import RagError

DOC_TYPES = ("transcript", "annual_report", "presentation")
MIN_SCORE = 0.65         # cosine similarity. Measured 2026-11-20 on the full index: real questions 0.67 to 0.74,
#                          off-topic 0.40 to 0.54, "weather in Mumbai" 0.63 (the word Mumbai is in the documents)
MAX_TOP_K = 10
MAX_CHARS = 900          # per passage, keeps the tool result small for the model


class DocumentsError(RuntimeError):
    pass


class Documents:
    def __init__(self, store=None, min_score: float = MIN_SCORE, max_chars: int = MAX_CHARS):
        self._store = store
        self.min_score = min_score
        self.max_chars = max_chars

    @property
    def store(self):
        if self._store is None:
            from rag_store import RagStore
            self._store = RagStore()
        return self._store

    def search(self, query: str, symbol: str | None = None, doc_type: str | None = None, year: int | None = None,
               top_k: int = 5) -> dict:
        if not query or not query.strip():
            raise DocumentsError("query is empty")
        if doc_type is not None and doc_type not in DOC_TYPES:
            raise DocumentsError(f"doc_type must be one of {', '.join(DOC_TYPES)}")
        top_k = max(1, min(int(top_k), MAX_TOP_K))
        symbol = symbol.upper().strip() if symbol else None
        try:
            hits = self.store.search(query.strip(), symbol=symbol, doc_type=doc_type, year=year, top_k=top_k)
        except RagError as exc:
            raise DocumentsError(str(exc)) from exc
        except Exception as exc:        # embedding model down, setting missing, Chroma problem: tell the agent plainly
            raise DocumentsError(f"document search is unavailable: {exc}") from exc
        passages = [self._passage(h) for h in hits if h["score"] >= self.min_score]
        if not passages:
            return {"found": False, "passages": [],
                    "message": "No passage in the indexed documents matches this question well enough. Say so; do not guess."}
        return {"found": True, "passages": passages}

    def _passage(self, hit: dict) -> dict:
        text = " ".join(hit["text"].split())
        if len(text) > self.max_chars:
            text = text[:self.max_chars].rstrip() + "..."
        return {"symbol": hit["symbol"], "doc_type": hit["doc_type"], "year": hit["year"], "month": hit.get("month", ""),
                "file": hit["file"], "page": hit["page"], "score": hit["score"], "text": text}
