# Project context

Incremental daily downloader for Screener.in documents, driven by a logged-in session cookie.

## Goal
For every symbol in `watchlist.txt`, fetch from `https://www.screener.in/company/{SYMBOL}/consolidated/`:
- the **Export to Excel** workbook (financials),
- **Annual Reports** (BSE/NSE links),
- **Concall Transcripts** and **PPTs** (skip `AI Summary` and `REC`).

Only new filings are downloaded on each run.

## Layout
```
screener-document-download/
├── code/                         all Python source (one module per task)
│   ├── download_screener_docs.py entry point (thin; calls cli.main)
│   ├── cli.py                    argparse + run orchestration + exit codes
│   ├── pipeline.py               per-symbol workflow (page -> excel -> docs)
│   ├── html_parser.py            parse #documents (annual reports, concalls)
│   ├── excel_export.py           "Export to Excel" form POST (CSRF) -> .xlsx
│   ├── file_downloader.py        single-file download, filename picking, PDF check
│   ├── http_client.py            Fetcher: random 1-2s delay, retry/backoff
│   ├── auth.py                   screener_auth.json -> requests.Session
│   ├── history.py                downloaded_history.json load/atomic save
│   ├── tracker.py                download_tracker.txt (finished symbols, thread-safe)
│   ├── nse_indices.py            NSE all-index constituents -> data_nse_index/<date>/ (standalone)
│   ├── nse_bhavcopy.py           NSE daily bhavcopy CSVs -> data_stock_bhavcopy/ (standalone)
│   ├── bhavcopy_index_filter.py  data_stock_bhavcopy/ daily files -> data_stock_bhavcopy_nifty50/<SYMBOL>.csv (stock list from data_nse_index/<date>/NIFTY_50.csv)
│   ├── refresh_auth.py           log in with e-mail/password -> new screener_auth.json (standalone tool; doc: docs/REFRESH_AUTH.md)
│   ├── watchlist.py              watchlist.txt reader
│   ├── symbols_csv.py            Screener screen-export CSV -> slugs (NSE else BSE code), find_latest_csv
│   ├── progress.py               per-run counts, %, totals, ETA, summary JSON
│   ├── models.py                 Doc dataclass, AuthError
│   ├── fs_utils.py               sanitize_filename, now_iso
│   ├── log_setup.py              logging config
│   ├── config.py                 constants and default paths
│   ├── experiments/pw_probe.py   throwaway Playwright probe (not part of the app, see PROGRESS.md)
│   └── tests/                    unittest suite (support.py = fakes, fixtures/company.html)
├── context/                      this folder: context + progress tracking
├── data/{SYMBOL}/                downloaded files (output; currently the Nifty 50 only)
├── data_stock_bhavcopy/          daily NSE bhavcopy CSVs (all symbols)
├── data_stock_bhavcopy_nifty50/  one CSV per Nifty 50 stock (built by bhavcopy_index_filter.py)
├── data_nse_index/<YYYYMMDD>/    NSE index constituent snapshots (NIFTY_50.csv = 50 stocks + index row)
├── Reference-Files/              index lists for --index (nifty-50.csv, ...)
├── html/                         architecture documents (open in a browser)
├── secret/                       private material, never commit or share
├── logs/                         run_<timestamp>.log + run_<timestamp>.summary.json (one pair per run)
├── screener_colab.ipynb          ready-to-run Google Colab notebook (see PROGRESS.md)
├── screener_documents_downloader2.ipynb   parallel Colab notebook (WORKERS, pilot batch, 429 health check)
├── run.txt                       user's own command cheat-sheet (not code)
├── watchlist.txt                 input symbols (one per line, # comments)
├── screener_auth.json            REAL session cookies (secret, do not commit/share)
├── screener_auth.example.json    template for the above
└── downloaded_history.json       {SYMBOL: {url: {file,type,label,downloaded_at}}}
```

## Run
```
python code/download_screener_docs.py                 # watchlist
python code/download_screener_docs.py -s INFY --dry-run
python code/download_screener_docs.py --types transcript ppt --no-excel
```
Symbol sources (priority): `-s`/`--symbols`/`--stock` > `--index NAME` (file in `Reference-Files/`, e.g. `--index Nifty50`) > `--csv FILE` / `--all` (newest CSV in project root) > `watchlist.txt`. `--start N --limit N` apply to `--index/--csv/--all`. `--index` cannot be combined with `--all/--csv`.
Flags: `-s`, `--csv`, `--all`, `--start`, `--limit`, `-w`, `-a`, `--history`, `-o`, `--types`, `--no-excel`,
`--standalone`, `--min-delay`, `--max-delay`, `--workers`, `--tracker`, `--force`, `--dry-run`, `-v`, `--log-dir`, `--log-file`.
Tracker: `download_tracker.txt` (project root, `code/tracker.py`) lists finished symbols, one per line. Tracked symbols are
skipped unless `--force`. Added only after a real run with failed=0 and no stop; never on `--dry-run`. Thread-safe append.
`downloaded_history.json` still tracks individual files; the tracker is a stock-level shortcut on top of it.
Parallelism: `--workers N` (1-8, default 1) runs N different stocks at the same time. One stock = one task =
one thread, end to end (page -> Excel -> every document, in order); nothing inside a stock is parallel.
Each worker thread has its own `requests.Session` + `Fetcher` (own 1-2s delays), so request rate = N x sequential.
Shared state is thread-safe: `history.py` (one lock for the dict + atomic file save, `record_entry`),
`progress.py` (lock; `begin` counts started stocks; `resume_offset()` = contiguous finished prefix, used for
the `--start` resume hint because workers finish out of order). `process_symbol(..., stop=Event)` lets
Ctrl+C / expired session stop workers between documents.
Every run logs to `logs/run_<timestamp>.log` plus a `.summary.json` (totals, symbols with failures, interrupted?).
Exit codes: 0 ok, 1 some downloads failed, 2 bad input, 3 session expired, 130 interrupted.

## Key facts learned (verified against the live site)
- Auth file is Playwright `storage_state` format; `sessionid` + `csrftoken` cookies.
- Documents HTML: `#documents div.annual-reports ul.list-links > li > a` and
  `#documents div.concalls ul.list-links > li` (date div + `a.button-chip` Transcript/PPT/REC;
  AI Summary is a `<button>`, so it is naturally ignored).
- Export to Excel is `<button aria-label="Export to Excel" formaction="/user/company/export/{id}/">`
  inside a POST form with `csrfmiddlewaretoken`. Plain `requests` can POST it; returns an .xlsx.
- Incremental key is the document URL. Failed downloads are not recorded, so they retry next run.
- Excel is a snapshot, so it is overwritten every run (history key `__excel__`).
- Some company IR sites (e.g. infosys.com, investor.meesho.com) return HTTP 403 to scripted clients;
  a few BSE links return 404. These are logged as failures and retried each run.
- Old annual reports can be `.zip` (NSE archive); extension is kept from the URL.
- Duplicate labels get `_2`, `_3` suffixes.

## Testing
`cd code && python3 -m unittest discover -s tests -p "test_*.py"` (233 tests, offline, ~0.9s).
Development is TDD: add a failing test first, then implement.

## Known issues / ideas
- The app uses plain `requests` (no browser window). Playwright is only used by the experiment
  `code/experiments/pw_probe.py`. A headed run fetched the infosys.com PDF that `requests` gets 403 on,
  so a browser fallback is feasible but not built. See PROGRESS.md.
- 403s from some IR sites persist even with browser-like headers + Referer (bot protection),
  and headless Chromium is blocked on infosys.com too.
- Dead links (404 / HTML instead of PDF) are retried forever; could add a "give up after N failures" record.
- Volume is huge: ~30 files/stock x 5,541 stocks. Use batches (`--start/--limit`) and `--types`.
- Long runs should be started in the background (foreground commands were being cancelled).

## Where things stand
See PROGRESS.md "Current state" for what was last run, what is validated, and the optional next steps.

## Agent project (planned, not built)
Router-led multi-agent chat app for the Nifty 50 only: technical agent (bhavcopy prices) + fundamental agent
(Screener Excel + RAG over PDFs), via MCP servers, LangGraph, Chroma, DuckDB, Ollama, Streamlit.
Decisions and open questions: `context/AGENT_PLAN.md`. Visual plan: `html/IITKGP-Agentic-NIFTY50-Plan.html`.

### Agent app layout (being built; see AGENT_PLAN.md)
The app **Agentic Research and Portfolio Maker** is built in a separate `Project-Code/` folder (agents, MCP servers, DB, RAG) and reads this folder's data read-only through `ARPM_DATA_ROOT`. Nothing of the app belongs here. Leftover skeleton here: `agentic_research_portfolio_maker/`, `.venv/`, `requirements.txt`.
