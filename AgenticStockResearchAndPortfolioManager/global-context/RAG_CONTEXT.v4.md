# RAG context: document search over PDFs, and how Excel financials are handled

Updated 2026-11-20 (01:40). Previous versions kept as `RAG_CONTEXT.v1.md`, `.v2.md` and `.v3.md` (no-delete rule). Companion to `GLOBAL_CONTEXT.md` (architecture), `STATUS_AND_PROGRESS.md` (tracker) and `PROMPT_CONTEXT.md` (prompts).
Everything here follows the no-delete rule in `GLOBAL_CONTEXT.md`: old collections and old files are kept, new versions are added beside them.

**Legend:** BUILT = code exists and is tested. PLANNED = agreed in discussion, no code yet. ASSUMED = my default, not confirmed by the user. MEASURED = I ran it on this machine.

## 1. State on 2026-11-20

| Item | State |
|---|---|
| RAG code | **BUILT and tested** (26 tests): `rag_chunker.py` (PDF text to page chunks, tier selection), `rag_store.py` (Chroma store, resumable ingest, search with citations, run records), `rag_build.py` (command-line build with progress and ETA), `bin/rag_build.sh`, `bin/rag_build_bg.sh`, `bin/rag_build_stop.sh`. |
| Search tool for the chat | **NOT built.** `search_documents` does not exist as an agent tool. The chat cannot read documents: since 2026-11-20 the keyword router sends annual-report, transcript and presentation questions to a fixed "not connected yet" reply. Only the Admin tab status panel and my scratch scripts (`rag_check.py`, `rag_check2.py`) use the store. |
| Vector store | `project-db/chroma/`, collection `ollama_local-nomic-embed-text-page-c1000-o150`. Per-file records in `project-db/rag_ingest.sqlite` (tables `files`, `runs`, `collections`). |
| Indexed so far | TCS trial: 17 files, 1,413 pages, 5,067 chunks. **Full build for all 50 stocks started 2026-11-20 00:15** (`bin/rag_build_bg.sh --annual-reports 5`). At 01:33: stock 16 of 50, 35% (161,061 of about 465,393 chunks), 34.6 chunks per second, ETA about 2 h 26 m, 509 files done, 0 failed. |
| Collection status | **Not complete.** It is marked complete only when all 50 stocks finish with no failed file. Search refuses an incomplete collection (`allow_partial=True` is for tests and scripts). |
| PDF reader | PyMuPDF 2.1, now in `requirements.txt`. MEASURED: a 337-page annual report reads in about 2 s. |
| Embedding | `nomic-embed-text` through the gateway, role `embedding`, 768 dimensions. About 25 to 42 chunks per second on the M1 Pro (varies from run to run). |
| Settings | Chunking `{"size": 1000, "overlap": 150, "split": "page"}`. Retrieval `{"top_k": 8, "reranker": None}`. Both in `project-db/settings.sqlite`. |

### How the build is logged (2026-11-20)
- **Log file:** `runtime/logs/rag_build.log`. Each run starts with a `=====` header with the time and the command, then `RUN <id> started (pid ...)`.
- **Per file:** one line with pages, empty pages and chunks. **Progress line** after every file: stock number, chunks done and total, percent, chunks per second, elapsed time, ETA.
- **Per stock:** a line with the stock's totals. **End of run:** totals, then the final index status.
- **Failures:** `FAILED <stock>/<file>: <reason>` and the run goes on. A stop (`bin/rag_build_stop.sh`) writes `STOPPED`, an exception writes `ERROR`, both with totals so far and what to run next.
- **Database records:** table `runs` (start, finish, command, status `running|complete|partial|stopped|error`, counts) and table `files` (one row per file: status `done|error`, pages, empty pages, chunks, size, overlap, error text). Check with `sqlite3 project-db/rag_ingest.sqlite "select status,count(*) from files group by status"`.
- **Limit:** a run killed hard (power loss, `kill -9`) leaves its `runs` row as `running`. The log's last line shows where it stopped.

### Measured numbers (2026-11-20, whole Nifty 50, quick page count, about 7 s)
| Scope | Files | Pages | Chunks (estimate at 1000/150, 3.6 chunks per page) |
|---|---|---|---|
| Tier 1: all transcripts | 999 | 21,138 | about 76,000 |
| Tier 2: latest 3 annual reports per stock | 147 | 60,103 | about 216,000 |
| Tier 2: latest 5 annual reports per stock (derived: 5-report total minus tiers 1 and 3) | 241 | 96,751 | about 348,000 |
| Tier 3: latest 5 presentations per stock | 237 | 11,387 | about 41,000 |
| Tiers 1 to 3 with 3 annual reports | 1,383 | 92,628 | about 333,000 |
| **Tiers 1 to 3 with 5 annual reports (the running build)** | **1,477** | **129,276** | **about 465,000** |

The chunk figure is an estimate (3.6 chunks per page, taken from the TCS trial: 5,067 chunks from 1,413 pages). The exact total will be in the log. The tier rows were measured with the default of 3 annual reports; the 5-report row is derived from the measured 5-report total. Use `--exact-estimate` for an exact count (about 8 s per stock). The earlier plan's figure of 222,000 chunks for tiers 1 to 3 was too low for this data.

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

## 3. Tiers (BUILT as options; the earlier plan's size estimates are replaced by section 1)

| Tier | Content | Size (earlier estimate) |
|---|---|---|
| 1 | All transcripts (Excel is not embedded, see section 6) | 21,138 pages (measured) |
| 2 | Latest N annual reports per stock (`--annual-reports`, default 3; the running build uses 5) | 60,103 pages at N=3 (measured); 96,751 at N=5 (derived from the measured totals) |
| 3 | Latest 5 presentations per stock (fixed in `rag_chunker.py`, `LATEST_PRESENTATIONS`) | 11,387 pages (measured) |
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

### Rebuild script (BUILT 2026-11-20: `rag_build.py`)
The user wants to change the chunking later, for example from 1000/150 to 1500/200, without code changes. Design:
- Size, overlap, split, tier and stock list are command-line options. Defaults come from the saved settings.
- **Each setting gets its own collection**, named by `SettingsStore.embedding_collection()`, for example `ollama_local-nomic-embed-text-page-c1500-o200`. A rebuild adds a new collection next to the old one. **Nothing is deleted** (no-delete rule). Old vectors stay until the user decides otherwise.
- Queries read the collection that matches the current settings. Switching the setting switches the collection only once the new one is complete. A half-built collection is never queried.
- **Resumable:** a run records each file as done. If it stops (a cancelled command, a crash), the next run continues from where it stopped.
- Embedding goes only through the gateway (`gateway.embed`, role `embedding`), so switching Ollama, Hugging Face or the UpGrad API needs no change here. A different embedding model gives a different collection.
- Runs in the background, writes progress to `runtime/logs/`, and shows a time estimate with a confirmation prompt before a long run.
- Run on one stock first (a trial), then the full tiers. Long jobs must be run as background processes with logs, because tool calls were cancelled before and background installs died when the call ended.

Open: which first-run setting (1000/150, 1500/200, or a one-stock comparison of both). The user asked for a rebuild script so the choice is reversible.

## 5. RAG design (store and build BUILT; search tool for the chat PLANNED)

Pipeline:
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
| Numbers and ratios from the statements | Loaded into DuckDB (`fundamentals_db.py`, 49 stocks, 20,747 values). Queried with the 7 tools of `mcp_fundamentals.py` (`list_line_items`, `get_financials`, `get_quarterly`, `compute_growth`, `compute_ratios`, `get_valuation`, `coverage`) through `agent_fundamental.py`. **BUILT 2026-11-20**, tested live. |
| Meaning in documents | RAG over PDFs |
| Mixed | `agent_fundamental` uses both and cites each |

Optional extra (ASSUMED): code generates one short summary sentence per stock and year from the table (for example "TCS FY2022: sales 191,754, net profit 38,327") and embeds it, so text search can find the right stock and year. The number itself still comes from the table.

### Workbook layout (MEASURED on 2026-11-19)
- 48 of 50 workbooks have the same layout: sheets `Profit & Loss`, `Quarters`, `Balance Sheet`, `Cash Flow`, `Customization`, `Data Sheet`. The `Data Sheet` has the section headings `META`, `PROFIT & LOSS`, `BALANCE SHEET`, `CASH FLOW:`, `PRICE:`, `DERIVED:` (the `Quarters` block sits inside `Data Sheet` too, and its heading is not upper case).
- Rows are labelled items (Sales, Employee Cost, Net profit...). Columns are report dates. For TCS the annual columns start at 2017-03-31, and the quarters at 2024-06-30. TCS `Data Sheet` has 93 rows and 11 columns.
- **No workbook: SBILIFE only.** (Corrected 2026-11-20: **M&M has a workbook**, `Financials_M_M.xlsx`, with `&` written as `_`. 49 workbooks in total.) The agent must say so for SBILIFE.
- **Checked 2026-11-20:** all 49 workbooks use the same row labels in every section, banks and insurers included. The labels are the same but the meaning differs for banks, insurers and finance companies (for example `Sales` is total income, `Interest` is interest expense, `Borrowings` includes deposits). Industrial ratios must not be computed for them without a warning. Full layout notes are in `STATUS_AND_PROGRESS.md` section 3.
- Values are in the company's reporting units (crore rupees for Screener). Confirm the unit before showing it to users.

## 7. Decisions and open questions

Decided:
1. Excel financials go to DuckDB and SQL tools, not into the vector store (2026-11-19).
2. The chunking settings must be changeable later through a rebuild script (2026-11-19). Built 2026-11-20.
3. Each chunking or embedding setting has its own collection, and old collections are kept (no-delete rule).
4. Embedding goes only through the gateway.
5. Build the index for all 50 stocks now, with the latest 5 annual reports per stock (user, 2026-11-20). Logging added (user asked).

Open:
1. **`search_documents` tool for the agent** (query, symbol, document type, year; file and page in the result; "not found" below a score cutoff). Not built. Where it goes: `agent_fundamental` behind the router (cleaner; the agent's prompt already says it has only the numbers and must decline text questions, so that line changes when the tool is added) or its own document agent. Waiting on the user. It can be built and tested against a fake store before the index finishes.
2. **Score cutoff.** Good matches scored 0.65 to 0.76, an off-topic question 0.52 on TCS. About 0.6 is a guess. Tune on more stocks once the index is complete.
3. **Table quality in annual reports** is unchecked. The sample searches returned prose only.
4. **Annual-report count for TCS:** the 17 TCS files are from the earlier trial with 3 annual reports. Run `bin/rag_build_bg.sh --symbols TCS --annual-reports 5` after the full build to add 2 more.
5. Whether to embed generated Excel summary sentences (ASSUMED optional extra, section 6).
6. Disk: 257 GiB free before the full build. The size of the full collection is not measured yet. Check `du -sh project-db/chroma` when it finishes.
7. UpGrad embedding API: documentation needed before relying on it. A different embedding model means a new collection and a new full build (about 3 h on this Mac).
8. INFY has no PDFs. The log should show no files for it. Not yet confirmed in the running build.

## 8. Risks

- **Run time.** The full build is about 3 h 20 m on the M1 Pro (the early estimate of 1.3 to 1.6 h was for fewer pages). On EC2 CPU instances embedding will be slower. Test there before a full run. Hosted embedding (Hugging Face or UpGrad) may be faster but sends text off the machine.
- **The Mac must stay awake** and Ollama must stay up. A sleep or crash stops the run. It resumes from the last finished file.
- **Disk growth.** Each setting adds a collection. Check free space before a second build.
- **Tables in annual reports** may be read as jumbled text by the PDF reader. This is the main quality risk. Check after the build.
- **Pages with no text** (scans, image-only slides) give no chunks. TCS: 29 of 1,413 pages. The totals for all stocks will be in the final status line.
- **Cancelled tool calls.** Several long commands were cancelled in this project, and a background job died once when its tool call ended. The ingest is resumable, and the background script now starts in its own session.
- **Copyright and privacy.** Documents are public filings. They stay local unless an external embedding provider is enabled.
