# Start here (next session)

Written 2026-11-18. Read this first, then `AGENT_PLAN.md` (decisions) and `PROGRESS.md` (log).

## Layout decision (user, 2026-11-18)
Two separate projects. **The app code never goes into `screener-document-download/`.**

```
Agentic Stock Research and Portfolio Manager/     <- parent folder the user will create (name as given by the user)
├── screener-document-download/    this folder: downloaders + data. Unchanged by the app. App reads it, read-only.
└── Project-Code/                  NEW: all agents, MCP servers, DB and RAG code. Own .venv, tests, context, app_data/.
```
The sibling position of `Project-Code/` is my assumption. Tell me the real path tomorrow.
The app's name is **Agentic Research and Portfolio Maker** (do not use "StockWood").

### What the app reads from this folder (read-only)
| Path | Used for |
|---|---|
| `data_stock_bhavcopy_nifty50/<SYMBOL>.csv` | Prices (technical and portfolio agents) |
| `data/<SYMBOL>/Financials_<SYMBOL>.xlsx` | Structured financials (fundamental agent) |
| `data/<SYMBOL>/*.pdf` | Documents for RAG (fundamental agent) |
| `Reference-Files/nifty-50.csv` | The 50-stock list, industry group and snapshot ratios (guardrail G1) |
| `data_nse_index/<date>/NIFTY_50.csv` | Alternative source of the 50-stock list |

The app must **never** read or copy `screener_auth.json`, `secret/`, `download_tracker.txt`, `downloaded_history.json` or `logs/`.
Everything the app writes (Chroma vectors, DuckDB, SQLite usage log, saved portfolios) goes under `Project-Code/app_data/`, not here.
That also means the 5 to 14 GB vector store sits wherever `Project-Code` lives. Check free space there.

### Config rule for the new project
Give the app one setting for the data location, for example `ARPM_DATA_ROOT=<path to screener-document-download>`, and build every data path from it.
Do not derive data paths from the app's own folder. This keeps the two folders independent and lets you move either one.

## State at the end of today
| Area | State |
|---|---|
| Downloader and tests | Done. `--index Nifty50` and `--stock SYM` added. 233 tests pass: `cd code && python3 -m unittest discover -s tests -p "test_*.py"` |
| Prices | `data_stock_bhavcopy_nifty50/` has 50 files, 57,767 rows, 23 Mar 2022 to 13 Nov 2026. Rebuild with `python3 code/bhavcopy_index_filter.py` |
| Documents | `data/` has 50 folders, about 15 GB. INFY is Excel only. See the gaps list in `AGENT_PLAN.md` |
| Plan page | `html/IITKGP-Agentic-NIFTY50-Plan.html` (v2), uses the new app name |
| App code | **Nothing real is built.** Only an empty skeleton exists, in the wrong place (see next section) |

## Leftovers I created inside this folder (they conflict with the new layout)
| Item | What it is | Suggested action |
|---|---|---|
| `agentic_research_portfolio_maker/` | Empty packages plus `config.py` (998 bytes, 1 file). No logic | Delete, or move into `Project-Code/` and fix `config.py` to use `ARPM_DATA_ROOT` |
| `.venv/` | Python 3.12 environment, 475 MB | Delete. Recreate it inside `Project-Code/` |
| `requirements.txt` | Pinned versions of the app's packages | Move to `Project-Code/` |
| `context/*.md`, `html/IITKGP-Agentic-NIFTY50-Plan.html` | Plan and notes | Keep here as the record. Copy this file and `AGENT_PLAN.md` into `Project-Code/` as its starting context |

I have not deleted or moved any of these. Say the word and I will, once you tell me where `Project-Code` is.

## Do these first tomorrow
1. **Stop everything running** before moving anything. Only Ollama was running when I checked.
2. **Move folders on the same disk**, as whole units. A copy of `data/` (15 GB) will not fit comfortably with about 30 GiB free on a 97%-full disk.
3. **If `screener-document-download/` moves:** run the checks below. The downloader uses paths relative to its own folder, so it should still work.
   ```bash
   cd code && python3 -m unittest discover -s tests -p "test_*.py"      # expect 233 OK
   cd .. && python3 code/bhavcopy_index_filter.py                       # expect unchanged=50
   python3 code/download_screener_docs.py --stock INFY --dry-run        # needs a valid screener_auth.json
   ```
   `run.txt` line 1 has the old absolute path. Edit it.
4. **Create the environment in `Project-Code/`:**
   ```bash
   cd <Project-Code>
   uv venv --python 3.12 .venv
   uv pip install --python .venv/bin/python -r requirements.txt
   ```
5. **Check Ollama:** `ollama list` should show `mistral:7b`, `gemma4:12b` and `nomic-embed-text`. It lives outside both folders.
6. **Check free disk space:** `df -h ~`.

## Things to look for
- **Wrong Python.** The default `python3` is 3.9.6 and cannot run the app. Use the `.venv` of `Project-Code`.
- **MCP version.** `mcp==2.3.0` is the v2 SDK. Use `from mcp.server.mcpserver import MCPServer` and `@mcp.tool()`. `mcp.server.fastmcp` does not exist.
- **Long Ollama runs.** Run benchmarks in the background with `nohup` and poll the log. Two long foreground runs timed out. Do not run two models at once.
- **`gemma4` thinking mode.** Pass `think=False` for speed.
- **Chroma collection names** need at least 3 characters.
- **Price files.** Dates are text like `13-Nov-2026`, so convert with `strptime(trim(DATE1), '%d-%b-%Y')`. Header names have a leading space after each comma, so strip them. DuckDB reads the numeric columns correctly.
- **Prices are unadjusted** for splits, bonuses and demergers. TMPV has only 276 days.
- **Index file** includes the `NIFTY 50` index row. Skip any symbol containing a space.
- **Secrets.** I did not open `secret/VM02_Embeddings_Access.zip`; the listing command was cancelled. Treat it as private.
- **Cancelled commands.** Several tool calls were cancelled today. After any interruption, check what was actually written before assuming it applied.

## Decisions still needed (defaults in brackets)
1. Local model for the router and agents: [`mistral:7b`, faster; `gemma4:12b`, stronger and about 25% slower].
2. Minimum portfolio size, since you only gave the upper limit of 6: [block fewer than 4].
3. Weight limits per stock: [5% minimum, 40% maximum].
4. Admin tab access: [password from an environment variable].
5. Logging: [question previews only; full text is opt-in].
6. Langfuse: [add after Phase 4 with a slim Admin tab]. Not installed. It needs a container runtime (Podman is installed, its VM has 2 GiB and is too small).
7. Fill the data gaps first with `python3 code/download_screener_docs.py --index Nifty50 --force`? [Yes, in the background. INFY PDFs may stay blocked by a 403.]
8. Containers: [not yet. Build in the venv first, then add a Dockerfile and compose file, with Ollama kept on the Mac for the GPU].
9. Exact path of `Project-Code/` and the parent folder name.

## Next steps in order (Phase 1, in `Project-Code/`)
1. `config.py` with `ARPM_DATA_ROOT`, then the **gateway** with a SQLite usage log (tests first).
2. Price layer: DuckDB over `data_stock_bhavcopy_nifty50/*.csv`, plus indicators (SMA, EMA, RSI, MACD, Bollinger, ATR), checked against hand-computed values.
3. `market-data` MCP server.
4. Technical LangGraph agent and a small command-line chat to try it.
5. End-to-end check against Ollama, then update the progress log.

Then Phase 2 (fundamentals), 3 (document RAG tiers), 4 (guardrails, router, Chat tab), 5 (portfolio agent), 6 (Admin tab).

## Measured numbers worth remembering
Extraction 78 to 128 pages/s. Embedding about 60 chunks/s (`nomic-embed-text`, 768 dimensions). Chroma about 15.4 KB per chunk.
`mistral:7b` about 25 tokens/s, `gemma4:12b` about 18.5 tokens/s. Tiers 1 to 3: about 222k chunks, 1.3 to 1.6 hours, about 5.4 GB.
Full set: about 790k chunks, 4.7 to 5.6 hours, about 14.4 GB.
