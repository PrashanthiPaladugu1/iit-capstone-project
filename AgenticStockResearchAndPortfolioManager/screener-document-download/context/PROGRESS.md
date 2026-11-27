# Progress log

Newest state first. Update this file whenever work is done.
Last updated: 2026-11-18 (Nifty 50 scope + agent plan v2; local build of the agent app STARTED). See AGENT_PLAN.md and 'Agent build log'.

## Working agreement
- Work autonomously, no per-step approval requests, until the code is complete.
- TDD: write/extend a test first, watch it fail, then implement. All Python lives in `code/`, tests in `code/tests/`.
- Long shell commands get cancelled in the assistant sandbox: run them in the background, or give the user
  the command to run in their own terminal. Do not write outside the project folder (blocked).

## Current state (read this first)
- **Code is complete and working.** 218 unit tests pass (`cd code && python3 -m unittest discover -s tests -p "test_*.py"`).
- Entry point: `python3 code/download_screener_docs.py` (see CONTEXT.md for layout and flags).
- User validated INFY downloads fine from Screener (login + Export to Excel + documents).
- User ran `--all --dry-run --limit 20` (nothing downloaded; 594 files listed) and then a real run of
  `--all --limit 20` which they stopped with Ctrl+C after 2/20 stocks (log `logs/run_20261115_012528.*`):
  20MICRONS 38 files, 21STCENMGM 16 files, 360ONE 38 files in `data/`. Interrupt handling, resume hint and
  summary JSON worked as designed: `Resume with: ... --csv <file> --start 2`.
- Ready-to-use Colab notebook: `screener_colab.ipynb` (project root). See "Google Colab" below.
- `downloaded_history.json` now holds: 20MICRONS 38, 21STCENMGM 16, 360ONE 38, INFY 57, MEESHO 6, TCS 10.

## Update 2026-11-18 (Nifty 50 scope + agent plan)
- [x] `--index NAME` added to `cli.py`: reads `Reference-Files/<name>.csv` (case/`-`/`_` ignored, e.g. `--index Nifty50` -> `nifty-50.csv`); works with `--start/--limit/--workers`. `REFERENCE_DIR` in `config.py`, `find_index_csv()` in `symbols_csv.py`.
- [x] `--stock SYM` added as an alias of `-s/--symbols` (repeatable). Explicit symbols beat `--index/--all/--csv`.
- [x] `code/bhavcopy_index_filter.py`: reads stock list from newest `data_nse_index/<date>/NIFTY_50.csv` (skips the `NIFTY 50` row), reads all `data_stock_bhavcopy/sec_bhavdata_full_DDMMYYYY.csv` in date order, writes one `<SYMBOL>.csv` per stock to `data_stock_bhavcopy_nifty50/` (EQ series by default; `--series`, `--index`, `--out`). Idempotent: unchanged files are not rewritten, stale ones removed. 50 files, 57,767 rows, 7.2 MB, INFY 23-Mar-2022 -> 13-Nov-2026.
- [x] Tests: 233 pass (`code/tests/test_bhavcopy_index_filter.py` new; `test_cli.py` extended).
- [x] `data/` was cleaned: the 48 old folders were moved out (to `~/Downloads/data-archive-for-delete`, since removed by the user). `data/` now holds the Nifty 50 downloads (50 folders, ~15 GB, 3,406 PDFs: 667 annual reports, 999 transcripts, 1,740 presentations; 49 Excel; 27 zip).
- [x] Architecture/plan drafted (v2 adds portfolio agent, guardrails, AI gateway, Admin tab): `html/IITKGP-Agentic-NIFTY50-Plan.html` (earlier blueprint: `html/IITKGP-AgenticStockReserach.html`). Decisions in `context/AGENT_PLAN.md`. **Nothing of the agent is built yet; waiting for the user to confirm the plan.**
- Coverage gaps in `data/`: INFY has Excel only (no PDFs); SBILIFE has no Excel; ITC and TRENT have no transcripts; BAJAJ-AUTO has no presentations; BSE/JIOFIN/ETERNAL have 3-5 annual reports. Fix: re-run `python3 code/download_screener_docs.py --index Nifty50 --force` (INFY PDFs may 403, see Known limitations).
- Disk was 19 GiB free at 97% used on 2026-11-18. Watch it before building the vector store.

## Agent build log (local build, started 2026-11-18)
App name: **Agentic Research and Portfolio Maker**. Code location: separate `Project-Code/` folder (own venv and tests), NOT this folder. The skeleton here is a leftover.
- LAYOUT DECISION 2026-11-18: app code does NOT live in this folder. It goes in a separate `Project-Code/` folder (agents, MCP servers, DB, RAG),
  which reads this folder's data read-only via `ARPM_DATA_ROOT`. This folder stays downloaders + data. See `context/START_HERE_NEXT_SESSION.md`.
- [x] Venv created (uv, Python 3.12), deps pinned in `requirements.txt` (mcp 2.x: `mcp.server.mcpserver.MCPServer`). These sit in THIS folder by mistake; move to Project-Code.
- [x] App named **Agentic Research and Portfolio Maker**; plan page and context updated.
- [x] Empty skeleton `agentic_research_portfolio_maker/` (config.py only, no logic) created here BEFORE the layout decision. Delete or move to Project-Code.
- [ ] Phase 1 (in Project-Code): gateway + usage log, price DB + indicators, market-data MCP, technical agent  <- NEXT
- [ ] Phase 1: venv, gateway + usage log, price DB + indicators, market-data MCP, technical agent
- [ ] Phase 2: fundamentals structured tools
- [ ] Phase 3: document RAG tiers
- [ ] Phase 4: guardrails, router, Chat tab (Langfuse decision here)
- [ ] Phase 5: portfolio agent
- [ ] Phase 6: Admin tab

## Done
- [x] Downloader: cookie-JSON auth, watchlist, incremental history, parsing, polite 1-2s delays, retries, logging.
- [x] Export to Excel (CSRF form POST) from `/consolidated/`; verified live for INFY and MEESHO.
- [x] Output layout `data/{SYMBOL}/`.
- [x] Modular refactor under `code/` (one task per module; see CONTEXT.md).
- [x] `context/` folder with CONTEXT.md and this file.
- [x] Symbols from the Screener screen-export CSV (`equitydata-screener-all-stocks-20261113.csv`, 5,541 stocks,
      from https://www.screener.in/screens/2225666/equitydata-screener-all-stocks/): `code/symbols_csv.py`,
      flags `--csv`, `--all`, `--start`, `--limit`. Slug = NSE Code else BSE Code (3,246 NSE, 2,295 BSE-only;
      `/company/{bse_code}/` verified live).
- [x] Progress + logs: `code/progress.py`; each run writes `logs/run_<timestamp>.log` and `.summary.json`.
      Terminal/log lines per stock: `[n/total] pct | SYMBOL | elapsed ETA` and
      `SYMBOL done: new= skipped= failed= | n/total (pct) | total new= skipped= failed= | elapsed ETA`.
- [x] Bug found by tests and fixed: `--dry-run` did not count the Excel export in `new`.
- [x] Parallel downloads (user request): `--workers N` (1-8, default 1). User rule: **one stock runs end to end on
      a single thread; no parallelism inside a stock** (parallel only across different stocks). TDD: 17 new tests.
      Thread-safe history (lock + `record_entry`), thread-safe `Progress` (+ `resume_offset`), per-worker
      session/fetcher, `stop` event for Ctrl+C / expired session. Notebook cell 2 has `WORKERS = 3`.
      NOT yet tried against the live site; each worker keeps its own 1-2s delay so N workers = ~N x request rate
      (Screener may rate-limit, 429s are retried with backoff). Start with 2-3.
- [x] NSE downloaders (user request; ported from the Colab notebooks in `downloaders/`), plain `requests`, no Chrome:
      * `code/nse_indices.py` -> `data_nse_index/<YYYYMMDD>/<INDEX>.csv` + `NSE_ALL_INDICES_<ts>.csv`.
        Fixes vs notebook: requests by NSE's short `indexSymbol` (display name returned 0 rows for 84/139 indices),
        real JSON keys (notebook's high/low/ltP/ptsC30d columns were always "-"), `empty` count, header-only files redone.
        Live run with `--force`: new=139 skipped=0 empty=0 failed=0. An earlier non-forced rerun logged skipped=3 on a
        cleared folder; cause not found, the forced run was clean.
      * `code/nse_bhavcopy.py` -> `data_stock_bhavcopy/sec_bhavdata_full_DDMMYYYY.csv`, `--days` (default 1700),
        `--end-date`, `--force`. Fixes vs notebook: checks HTTP status (notebook saved NSE's 404 HTML as .csv on holidays),
        validates the CSV header, replaces bad files. Live test `--days 10`: 8 files saved, valid CSV.
        The full default run is ~1,215 files (~400 KB each, ~480 MB) and ~25 min at the 1-1.5 s delay: NOT run yet.
      Both: 218 unit tests pass in total; logs in `logs/nse_*.log` / `logs/bhavcopy_*.log`.
- [x] `screener_documents_downloader2.ipynb` (user request): parallel Colab notebook, 9 cells (8 code, JSON/nbformat valid,
      python cells parse). Settings: START/LIMIT/PILOT/WORKERS(4)/TYPES/EXCEL/FORCE/MIN_DELAY/MAX_DELAY. Flow: Drive +
      full file check (all 17 modules) -> settings -> dry-run -> pilot batch -> health check (counts HTTP 429 / "Giving up" /
      403 / expired session in the last log and advises lowering or raising WORKERS) -> full batch -> status (incl.
      tracker count) -> unmount. Not yet run on Colab. Original `screener_colab.ipynb` kept as is.
- [x] `docs/REFRESH_AUTH.md` + `code/refresh_auth.py` (user request, for when the password changes / cookie expires): logs in at
      `/login/` with e-mail + password (CSRF token + Referer), writes a Playwright-style `screener_auth.json`
      (chmod 600; old file kept as `.json.bak`). Password via hidden prompt or env `SCREENER_PASSWORD`, never a CLI arg.
      Run: `python3 code/refresh_auth.py --username you@example.com`. 13 offline tests. NOT verified live (needs the
      user's credentials); may fail if Screener shows a captcha or the account uses Google sign-in.
- [x] `download_tracker.txt` + `--force` (user request): `code/tracker.py`, flags `--tracker FILE`, `--force`.
      One finished symbol per line (uppercase; `#` comments and blanks ignored; hand-editable). Tracked symbols are
      skipped before any request. A symbol is added only after a REAL run (not `--dry-run`) that finished it with
      failed=0 and no stop/interrupt; failed/crashed/interrupted stocks are retried next run. Progress total counts only
      remaining stocks. Resume hint maps back to the position in the full CSV list. Tracker file does not exist until
      the first stock completes (not seeded with earlier downloads: INFY/MEESHO/TCS/20MICRONS/21STCENMGM get one
      fast re-check, then are tracked). 18 new tests.
      CAVEAT: the tracker does not remember `--types`/`--no-excel`, and a tracked stock is never re-checked for NEW
      filings; use `--force` (cheap: existing files are skipped by history) for daily incremental runs or to add types.
- [x] Google Colab notebook `screener_colab.ipynb` (7 cells, JSON/nbformat validated, python cells parse):
      mount Drive + file check, settings (START/LIMIT/TYPES/EXCEL), dry-run test, real batch, status
      (totals, stocks/files/GB on Drive, last log lines), `drive.flush_and_unmount()`. Not yet run on Colab.
- [x] Old test downloads moved into `data/`; history reconciled with disk.

## What gets downloaded (answers to user questions)
- Default (no `--types`): Excel + annual reports + transcripts + PPTs. `--types` only narrows documents;
  Excel stays on unless `--no-excel`. There is NO "Excel only" mode (`--only-excel` not built).
- Never downloaded: Announcements, Credit ratings, AI Summary, REC (audio).
- `--types transcript ppt` was only a suggestion to cut size (annual reports are 5-15 MB each, up to 15 per stock).
- Volume estimate from dry run: ~30 files/stock (up to 60-80), so the full CSV is ~150,000 files, likely hundreds of GB,
  and weeks at the polite 1-2s delay. Plan on batches and `--types`/`--since` style limits.

## Run commands
```
python3 code/download_screener_docs.py --all --dry-run --limit 20         # preview, downloads nothing
python3 code/download_screener_docs.py --all --start 0 --limit 200        # everything for a batch
python3 code/download_screener_docs.py --all --start 0 --limit 200 --workers 3   # 3 stocks at a time
python3 code/download_screener_docs.py --all --force --workers 3          # ignore download_tracker.txt, re-check every stock
python3 code/download_screener_docs.py --all --start 0 --limit 200 --types transcript ppt   # smaller
python3 code/download_screener_docs.py --all --start 0 --limit 200 --no-excel               # without Excel
```
Watch live in the terminal or `tail -f logs/run_*.log`. Re-running skips everything already downloaded.
Note: `run.txt` in the project root is the user's own command cheat-sheet; lines 23-25 ("Excel only") are wrong.

## Google Colab
- Notebook: `screener_colab.ipynb`. Upload the project folder to `MyDrive/screener-document-download/`.
- Files to copy (16 Python files in `code/` + `screener_auth.json` + the stock CSV). Optional: `watchlist.txt`;
  `downloaded_history.json` + `data/` together (to skip files already downloaded). Do NOT copy `code/tests/`,
  `code/experiments/`, `context/`, `logs/`, `.DS_Store`.
- Colab limits: ~90 min idle disconnect, ~12h max (free). Re-run cells 1, 2, 4 to resume. Free Drive = 15 GB.
- Risks: Screener may treat Google IPs differently (cell 3 dry run tests it); `screener_auth.json` is a live login,
  keep it in private Drive only; cookies expire eventually.

## Browser probe experiment (done; fallback not built)
`code/experiments/pw_probe.py` (throwaway, not part of the app). Run: `python3 code/experiments/pw_probe.py --headed`.
- A) Playwright with `screener_auth.json` as storage_state clicks **Export to Excel** -> works (33,536 byte xlsx).
- Headless Chromium and `ctx.request.get` still get 403 / "Access Denied" on infosys.com.
- The user's headed run produced `data/_probe/ir.pdf` (2,075,881 bytes, valid `%PDF-`), so a visible real browser CAN
  fetch the PDF that `requests` gets 403 on => a browser fallback for 403 hosts is feasible.
- Not built. `data/_probe/` can be deleted.

## Known limitations
- Some company IR sites return HTTP 403 to scripts (infosys.com, investor.meesho.com). Logged as failures, retried each run.
- Some BSE links return HTML instead of a PDF (seen: 20MICRONS PPT_Apr_2018 "not a PDF (content-type=text/html)")
  or 404; retried every run. Some hosts time out (seen: primeinfobase.in for 360ONE Annual_Report_2024 after 3 retries).
- Dead links are retried forever (no give-up counter).

## Pending / ideas (all optional, ask the user first)
- [ ] `--since YEAR` to skip old filings and cut volume (offered, not requested yet).
- [ ] `--only-excel` mode (offered, not requested yet).
- [ ] Browser fallback for 403 hosts (feasible per probe; not requested yet).
- [ ] Give-up-after-N-failures for dead links.
- [ ] Schedule daily (cron/launchd), e.g. `0 8 * * * cd <project> && python3 code/download_screener_docs.py --all --types transcript ppt`.
- [ ] `.gitignore` for `screener_auth.json`, `data/`, `logs/`.
- [ ] Cleanup: delete `data/_probe/`; stale test logs in `logs/` if wanted.

## Notes
- The CSV is a Screener screen export; refresh by re-exporting from the screen URL above.
- `screener_auth.json` holds live credentials. Keep it out of version control and out of public notebooks.
- Known doc typo left by the user's manual edit: none remaining (fixed in this rewrite).
