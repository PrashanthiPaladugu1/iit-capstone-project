# RAG context: document search over PDFs, and how Excel financials are handled

Saved 2026-11-19. Companion to `GLOBAL_CONTEXT.md` (architecture), `STATUS_AND_PROGRESS.md` (tracker) and `PROMPT_CONTEXT.md` (prompts).
Everything here follows the no-delete rule in `GLOBAL_CONTEXT.md`: old collections and old files are kept, new versions are added beside them.

**Legend:** BUILT = code exists and is tested. PLANNED = agreed in discussion, no code yet. ASSUMED = my default, not confirmed by the user. MEASURED = I ran it on this machine.

## 1. State on 2026-11-19

| Item | State |
|---|---|
| RAG code (`rag_*.py`) | **None written yet.** No chunker, no store, no ingest script, no search tool. |
| Vector store | **Not created.** `project-db/chroma/` does not exist. Nothing is embedded. |
| PDF reader | PyMuPDF 2.1 installed in `project-code/.venv` (MEASURED: the TCS 2025 annual report, 337 pages and about 1,050,000 characters, reads in 2.0 s). **Not yet added to `requirements.txt`.** Its install also added `pymupdf-layout`, `pymupdf4llm` and `tabulate`. |
| Vector database | `chromadb` 1.5.9 installed and in `requirements.txt`. |
| Embedding model | `nomic-embed-text` through the gateway, role `embedding`, 768 dimensions. Connection test passes (about 0.6 s). |
| Settings | In `project-db/settings.sqlite`. Chunking `{"size": 1000, "overlap": 150, "split": "page"}`. Retrieval `{"top_k": 8, "reranker": None}`. |
| Current collection name | `ollama_local-nomic-embed-text-page-c1000-o150` (from `SettingsStore.embedding_collection()`). |
| User decision pending | Which chunk size for the first full run. See section 4. |

## 2. What is in the documents (MEASURED)

`screener-document-download/data/<SYMBOL>/` holds 3,406 PDFs, 50 Excel workbooks and 27 zip files. The app reads it read-only.

| Document family | File name pattern | PDF count | What it is |
|---|---|---|---|
| Presentations | `PPT_<Mon>_<Year>.pdf` (some `_2` copies) | about 1,433 | Investor slides. Little text per page. |
| Transcripts | `Transcript_<Mon>_<Year>.pdf` | about 970 | Earnings-call transcripts. Q and A text. |
| Annual reports | `Annual_Report_<Year>.pdf` | about 667 | Long, with tables and notes. A TCS report is 337 pages. |

Coverage gaps (MEASURED on 2026-11-19, so the agent must say "not available" and never guess):
| Stock | Annual reports | Transcripts | Presentations | Excel |
|---|---|---|---|---|
| TCS | 14 | 12 | 2 | yes |
| RELIANCE | 14 | 19 | 41 | yes |
| INFY | 0 | 0 | 0 | yes |
| ITC | 14 | 0 | 35 | yes |
| TRENT | 15 | 0 | 12 | yes |
| BAJAJ-AUTO | 15 | 18 | 0 | yes |
| SBILIFE | 9 | 19 | 16 | **no** |
| M&M | not checked | not checked | not checked | **no** |

The other 43 stocks were not checked one by one here. The full per-stock counts must be produced by the ingest script.

## 3. Tiers (PLANNED, from the earlier plan, estimates not re-measured)

| Tier | Content | Size (earlier estimate) |
|---|---|---|
| 1 | All transcripts, plus Excel summaries | about 21,000 pages |
| 2 | Latest 3 annual reports per stock | about 40,000 pages |
| 3 | Latest 4 to 6 presentations per stock | about 11,500 pages |
| Tiers 1 to 3 together | | about 222,000 chunks, 1.3 to 1.6 hours, about 5.4 GB |
| Everything | | about 790,000 chunks, 4.7 to 5.6 hours, about 14.4 GB |

These came from the earlier plan at the 1,000-character setting. Re-measure with a one-stock trial before relying on them. The embedding speed on the M1 Pro and the page counts were estimates.

## 4. Chunking settings and the rebuild script

### Current default
**1,000 characters, 150 overlap (15%), split by page, top-k 8.** About 150 to 200 words, roughly 250 tokens, a third of a typical annual-report page. A chunk never crosses a page, so every chunk has one page number for citations.

Allowed by `model_settings.py` (enforced): size 200 to 8,000, overlap from 0 to less than half the size, split `page` or `section`, top_k 1 to 50. **`section` split is allowed by the settings but is not built.**

### Trade-offs (my assessment, not measured here)
| Setting | Good for | Risk |
|---|---|---|
| 1,000 / 150 | Transcripts: an answer is a few sentences | Annual-report tables can lose their column headings when cut |
| 1,500 / 200 | Fewer chunks, a faster run, fewer broken tables | Less precise passages |

Doubling the size roughly halves the chunk count and the embedding time.

### Rebuild script (PLANNED, requested 2026-11-19, being built)
The user wants to change the chunking later, for example from 1000/150 to 1500/200, without code changes. Design:
- Size, overlap, split, tier and stock list are command-line options. Defaults come from the saved settings.
- **Each setting gets its own collection**, named by `SettingsStore.embedding_collection()`, for example `ollama_local-nomic-embed-text-page-c1500-o200`. A rebuild adds a new collection next to the old one. **Nothing is deleted** (no-delete rule). Old vectors stay until the user decides otherwise.
- Queries read the collection that matches the current settings. Switching the setting switches the collection only once the new one is complete. A half-built collection is never queried.
- **Resumable:** a run records each file as done. If it stops (a cancelled command, a crash), the next run continues from where it stopped.
- Embedding goes only through the gateway (`gateway.embed`, role `embedding`), so switching Ollama, Hugging Face or the UpGrad API needs no change here. A different embedding model gives a different collection.
- Runs in the background, writes progress to `runtime/logs/`, and shows a time estimate with a confirmation prompt before a long run.
- Run on one stock first (a trial), then the full tiers. Long jobs must be run as background processes with logs, because tool calls were cancelled before and background installs died when the call ended.

Open: which first-run setting (1000/150, 1500/200, or a one-stock comparison of both). The user asked for a rebuild script so the choice is reversible.

## 5. Planned RAG design

Pipeline (PLANNED):
```
PDF -> PyMuPDF text per page -> chunk (size, overlap, split) -> embed through gateway (role "embedding")
    -> Chroma collection <provider>-<model>-<split>-c<size>-o<overlap>
search_documents(query, symbol?, doc_type?, year?) -> top_k chunks with source file, page, symbol, doc type, date
```

Each chunk stores as metadata: symbol, document type (annual report, transcript, presentation), period or year, file name, page number, chunk number. Search can filter on symbol, type and year.

Rules:
- **Numbers never come from similarity search.** Figures come from the DuckDB tools. RAG is for meaning: risks, strategy, management comments, reasons.
- **Every answer from documents cites the file and page.** If nothing relevant is found, say so.
- **Missing documents are stated**, for example: "ITC has no transcripts in the data."
- **Pages with no text** (scanned pages, image-only slides) give no chunks. The script must count and report them. OCR is not planned.
- **Retrieval:** top-k 8, no reranker (default).
- **Summary role** (`mistral:7b` by default) can shorten retrieved passages. It is not used for numbers.
- **Judge role** scores groundedness and citations during evaluation, and should differ from the model that wrote the answer.
- **Re-index** is needed when the embedding model, the chunk size, the overlap or the split changes. The Admin tab must show a time estimate and ask for confirmation first (PLANNED).
- **External providers** (Hugging Face, UpGrad) send document text off this machine. They are off by default and need an explicit per-role opt-in with a warning. If UpGrad requires the embedding to run on their API, switch the `embedding` role in the Admin tab, then build a new collection. The UpGrad API format is unknown. A document or example request is still needed.

## 6. Excel financial statements (decided 2026-11-19)

**RAG is not the main method for the Excel workbooks.** They are tables. Chunking cuts a number away from its label and year, similarity search matches meaning and not numbers, and ratios need calculation.

| Question type | Method |
|---|---|
| Numbers and ratios from the statements | Load into DuckDB. Query with `mcp_fundamentals.py` tools (for example `get_financials`, `compute_growth`). PLANNED. |
| Meaning in documents | RAG over PDFs |
| Mixed | `agent_fundamental` uses both and cites each |

Optional extra (ASSUMED): code generates one short summary sentence per stock and year from the table (for example "TCS FY2022: sales 191,754, net profit 38,327") and embeds it, so text search can find the right stock and year. The number itself still comes from the table.

### Workbook layout (MEASURED on 2026-11-19)
- 48 of 50 workbooks have the same layout: sheets `Profit & Loss`, `Quarters`, `Balance Sheet`, `Cash Flow`, `Customization`, `Data Sheet`. The `Data Sheet` has the section headings `META`, `PROFIT & LOSS`, `BALANCE SHEET`, `CASH FLOW:`, `PRICE:`, `DERIVED:` (the `Quarters` block sits inside `Data Sheet` too, and its heading is not upper case).
- Rows are labelled items (Sales, Employee Cost, Net profit...). Columns are report dates. For TCS the annual columns start at 2017-03-31, and the quarters at 2024-06-30. TCS `Data Sheet` has 93 rows and 11 columns.
- **No workbook: M&M and SBILIFE.** Their structured financials are unavailable. The agent must say so.
- **Not checked:** whether banks and insurers use different row labels from industrial companies. Ratios such as debt-to-equity do not mean the same for a bank. Check this before writing the loader.
- Values are in the company's reporting units (crore rupees for Screener). Confirm the unit before showing it to users.

## 7. Decisions and open questions

Decided:
1. Excel financials go to DuckDB and SQL tools, not into the vector store (2026-11-19).
2. The chunking settings must be changeable later through a rebuild script (2026-11-19).
3. Each chunking or embedding setting has its own collection, and old collections are kept (no-delete rule, 2026-11-19).
4. Embedding goes only through the gateway.

Open:
1. First-run setting: 1000/150 (saved default), 1500/200, or a one-stock comparison first.
2. Tiers for the first full run: Tiers 1 to 3 (assumed) or something smaller.
3. Whether to embed the generated Excel summary sentences.
4. Banks and insurers: do their Excel labels differ? (check before the loader)
5. Add `pymupdf` to `requirements.txt` (needed, otherwise a fresh VM cannot read PDFs).
6. Disk: 250 GiB were free on 2026-11-19, and the plan needs 5 to 14 GB per full collection. A second chunking setting adds a second collection of that size.
7. UpGrad embedding API: documentation needed before relying on it.

## 8. Risks

- **Run time.** 1.3 to 1.6 hours (estimate) on the M1 Pro. On EC2 CPU instances embedding will be slower. Test there before a full run. Hosted embedding (Hugging Face or UpGrad) may be faster but sends text off the machine.
- **Disk growth.** Each setting adds a collection. Keep an eye on free space. Disk went from 18 GiB free to 250 GiB free earlier on 2026-11-19, so check it before a heavy step.
- **Tables in annual reports** may be read as jumbled text by the PDF reader. This is the main quality risk, and a trial on one stock will show it.
- **Cancelled tool calls.** Several long commands were cancelled in this project. The ingest must be resumable and run in the background.
- **Copyright and privacy.** Documents are public filings. They stay local unless an external embedding provider is enabled.
