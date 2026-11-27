# Status and progress: Agentic Research and Portfolio Maker

Updated 2026-11-20 (00:25 local). Previous version kept as `STATUS_AND_PROGRESS.v1.md` (no-delete rule).
Read `GLOBAL_CONTEXT.md` first for the layout, rules and architecture. This file is the task tracker:
what is done, what is pending, and what you can run on the console now.
Prompt handling (routes, example prompts, agent prompts, the multi-portfolio and compare-agent design) is in `PROMPT_CONTEXT.md`.
RAG (documents, chunking, build script, measured numbers, Excel findings, open questions) is in `RAG_CONTEXT.md`.

**State at 2026-11-20 00:20:** 106 tests pass (`project-code/tests/`, 11 files). Ollama is up. The web app is up at **http://127.0.0.1:8502**.
**The full document index build is RUNNING in the background** (PID in `runtime/run/rag_build.pid`, log `runtime/logs/rag_build.log`).
At 00:19 it was at 2% (9,646 of about 465,393 chunks), 38.7 chunks per second, ETA about 3 h 16 m, 0 failed files.

## 1. Done

| Area | What exists | Verified how |
|---|---|---|
| Layout and config | `config/paths.json` is the only place paths are written (new entry `rag_db`). `project-code/config.py` reads it. `bin/*.sh` start and stop Ollama and the app. `config/arpm.env` exists (Ollama URL only; **admin password still empty**). | `test_config.py`, `test_architecture_rules.py` |
| Provider adapters | `providers.py`: Ollama, OpenAI-compatible, Hugging Face. | Ollama live. The other two with mocked HTTP only. |
| Model settings | `model_settings.py`: per-role provider and model, chunking and retrieval values, audit log. `embedding_collection(chunking=None)` now accepts command-line chunking values. **Defaults: chat `gemma4:12b` (think off), router `mistral:7b`, embedding `nomic-embed-text`, summary `mistral:7b`, judge `gemma4:12b`.** | `test_gateway.py`, `test_rag_build.py` |
| AI gateway | `gateway.py`: role-based chat and embed, retry once, usage log with tokens and tokens per second, `test_connection`. | `test_gateway.py`, live |
| Price database | `prices_db.py`: `project-db/arpm.duckdb`, 55,167 rows, 23 Mar 2022 to 13 Nov 2026. | `test_prices_db.py` |
| Indicators | `indicators.py`: SMA, EMA, RSI, MACD, Bollinger, ATR, returns, 52-week high and low. | `test_indicators.py` |
| Market data tools | `market_data.py` and `mcp_market_data.py`: **10 tools** (new today: `list_stocks`, all 50 stocks with name and industry group). | `test_market_data.py`, live over stdio |
| MCP client, budgets | `mcp_client.py`, `budget.py` (limits on model calls, tool calls, tokens, depth 3). | `test_agent_technical.py` |
| Technical agent | `agent_technical.py`: ten LangChain `@tool` functions over the MCP server, run by LangGraph `ToolNode`. System prompt now says `top_movers` is not the list of available stocks. | Scripted tests; live on `gemma4:12b` ("What are the stock avaialbel for query" now calls `list_stocks` and returns all 50) |
| **RAG chunker** | `rag_chunker.py`: page-based chunks (size and overlap are options), file-name parser, tier selection (`annual_reports` and `presentations` counts are options), page counter, PDF reader (PyMuPDF). | `test_rag_chunker.py` (11 tests) |
| **RAG store** | `rag_store.py`: one Chroma collection per setting, resumable ingest (each file recorded in `project-db/rag_ingest.sqlite`), embedding only through `gateway.embed`, search with symbol, document type and year filters and file/page citations, a collection is searched only after `mark_complete()`, run records in a `runs` table. | `test_rag_store.py` (10 tests, fake embedder) |
| **RAG build script** | `rag_build.py` with `bin/rag_build.sh` (foreground), `bin/rag_build_bg.sh` (background, own session so it survives the end of a tool call), `bin/rag_build_stop.sh` (safe stop). Options: `--size`, `--overlap`, `--tiers`, `--annual-reports N`, `--symbols`, `--trial`, `--estimate-only`, `--exact-estimate`, `--yes`. Writes a progress line with chunks, rate and ETA after every file, a line per stock, run totals, and records `stopped` or `error` runs. | `test_rag_build.py` (11 tests); TCS trial run live; full run in progress |
| **RAG trial on one stock** | TCS only: 17 files, 1,413 pages, 5,067 chunks, 29 pages with no text, 0 failures, about 3 minutes. Searches returned relevant passages with file and page (risk management, deal wins, attrition, margins, dividends). An off-topic question scored 0.52 against 0.68 to 0.76 for real matches. | Live searches on 9 questions |
| **Web app** | `app_ui.py` (entry, 6 lines) and `ui_app.py` (logic). Chat tab (technical questions only, says so, shows tools used and budget). Admin tab behind `ARPM_ADMIN_PASSWORD` with Models (save and test connection per role), Providers, Chunking and index status, Usage log, Change log. Port **8502** (changed from 8501 on request). The old placeholder is kept as `app_ui_placeholder_v0.txt`. | `test_ui_app.py` (6 tests with Streamlit `AppTest`); live ITC RSI question through the page code (66.47); page and health check return 200 |

### Model comparison (19 Nov 2026, M1 Pro, one run each)
| Model | Uses tools? | Result |
|---|---|---|
| `gemma4:12b` | Yes | Correct numbers, 10 to 48 s per question. **Chosen as chat default.** |
| `gemma4:e4b` | Yes | Correct, 28 to 50 s |
| `mistral:7b` | No | Wrote placeholders and invented numbers. Kept for router and summary only. |
| `phi4-mini` | No | Printed the tool JSON as text |

### Problems found by use today, and what was done
| Problem (seen by the user) | Cause | Fix |
|---|---|---|
| "What are the stock available" returned top gainers and losers | No tool for the stock list, so the agent used `top_movers` | New `list_stocks` tool and a prompt line. **Fixed, tested.** |
| "10 good points from last 5 years of annual reports of TCS" returned price returns | The chat has no document search tool, and the agent does not refuse out-of-scope questions | **Not fixed yet.** See pending 1 and 2. |
| Port 8501 did not open | The app was down, probably stopped with a cancelled tool call | Port set to 8502, app started in its own session. Reason not confirmed. |
| Background jobs died when a tool call ended | Child process stayed in the tool's session | `bin/rag_build_bg.sh` and `bin/start_app.sh` now start through `perl POSIX::setsid` |

## 2. Pending (in build order)

| # | Task | Notes |
|---|---|---|
| 0 | **Let the full RAG build finish** (running now) | About 3 h 20 m from 00:15. It marks the collection complete only if all 50 stocks finish with no failed file. Then check: `sqlite3 project-db/rag_ingest.sqlite "select status,count(*) from files group by status"`. TCS stays at 3 annual reports (run again with `--symbols TCS --annual-reports 5` to add 2 more; finished files are skipped). |
| 1 | **`search_documents` tool in the chat** | Tool for the agent: query, symbol, doc type, year; returns passages with file and page; says "not found" below a score cutoff (about 0.6, not tuned). Needs the index to be complete. Decide: put it on the current agent (quick) or build the router first. |
| 2 | **Refuse out-of-scope questions** | The technical agent must say "I cannot read documents or financials yet" instead of answering a different question. Fix with the router or a prompt rule. |
| 3 | **Fundamentals: Excel to DuckDB and `mcp_fundamentals.py`, then `agent_fundamental.py`** (user asked 2026-11-20 to build in parallel; layout findings below, no code written yet) | See section 3. Tables: profit and loss, quarters, balance sheet, cash flow, price, derived. Tools such as `get_financials`, `compute_growth`, `compute_ratios`, plus `search_documents`. The agent file is still a stub. |
| 4 | Guardrails (`guardrails.py`) | G1 to G8 from `GLOBAL_CONTEXT.md`. G8 limits exist in `budget.py`. Define "one year of history" for G6 (TMPV has 260 days). |
| 5 | Prompt enhancer, router | `prompt_enhancer.py`, `router.py`. Router on `mistral:7b` is untested. |
| 6 | Research analyst | `scorecard.py` (code only) and `agent_research_analyst.py` (stub). |
| 6b | `agent_compare` and multi-portfolio requests | Design in `PROMPT_CONTEXT.md` sections 5 and 9. Needs `scorecard.py` and the portfolio manager first. |
| 7 | Portfolio manager | `mcp_portfolio.py` and `agent_portfolio_manager.py` (stub). |
| 8 | Admin tab additions | Search box for the document index (stock, type, question, top 8 with file, page, score); build runs from the `runs` table; usage charts; re-index with time estimate and confirmation; call-tree view (gateway already stores `parent_id`). |
| 9 | CLI chat | One command to ask the agent questions and see the tool trace. `live_models.py` does this today for the technical agent. |

### Smaller items and open questions (waiting on the user unless stated)
- **`ARPM_ADMIN_PASSWORD`** is empty in `config/arpm.env`, so the Admin tab is locked. Set it and restart (`bin/stop_app.sh`, then `bin/start_app.sh`).
- **`config/setup.sh`** still pulls only `mistral:7b` and `nomic-embed-text`. It needs `gemma4:12b` (7.7 GB). A fresh VM will fail without it.
- **`prices_db.build()`** overwrites `arpm.duckdb` (no-delete rule). Proposed: rename the old file to a dated name first. PID files are removed with `rm -f` (proposed: keep). Waiting on a decision.
- **Architecture HTML** still lacks eight areas from the old plan and has stale numbers. Proposed: a new versioned file. Waiting.
- **Sector grouping for the compare agent** (Industry Group assumed, 26 groups) and whether `compare` is a router route. Waiting.
- **UpGrad API:** documentation or an example request is needed. The external provider is a generic OpenAI-compatible adapter, never run against a real service.
- **Mac must stay awake** and Ollama up for the full RAG build. If it stops, run `bin/rag_build_bg.sh --annual-reports 5` again; finished files are skipped.
- **`bin/start_app.sh` change was not tested** beyond staying up 10 s after start. The cause of the earlier outage on 8501 is not confirmed.
- **Scratch files** left in `project-code/`: `live_models.py` (kept at the user's request), `rag_check.py`, `rag_check2.py`, `ui_smoke.py`. None is imported by the app. Not deleted (no-delete rule).
- **EC2:** no GPU on m6i/m7i/m8i. `gemma4:12b` will be slow on CPU and so will embedding. Test `gemma4:e4b` and the embedding speed there first.
- **Price data caveat:** prices are not adjusted for splits, bonuses or demergers. 14 stocks have one-day moves over 25%.

## 3. Excel financials: findings for the fundamental agent (MEASURED 2026-11-20)

- **49 workbooks, not 50.** `data/` has 50 stock folders. Only **SBILIFE** has no workbook. **M&M has one**, named `Financials_M_M.xlsx` (the `&` becomes `_`). The earlier note that M&M has no Excel was wrong. The path pattern `financials_file` in `paths.json` uses `Financials_{symbol}.xlsx`, so it will miss M&M and the loader must handle the file name.
- **All 49 share one layout** (checked: row labels in every section match TCS exactly, including banks and insurers: HDFCBANK, HDFCLIFE, BAJFINANCE were opened). Sheets: `Profit & Loss`, `Quarters`, `Balance Sheet`, `Cash Flow`, `Customization`, `Data Sheet`. Everything needed is in `Data Sheet` (93 rows).
- **Row blocks in `Data Sheet`:** `META` (rows 5 to 9: company name in row 1, face value, current price, market cap), `PROFIT & LOSS` (row 15 heading, row 16 `Report Date`, rows 17 to 31), `Quarters` (row 40, dates row 41, rows 42 to 50), `BALANCE SHEET` (row 55, dates row 56, rows 57 to 72), `CASH FLOW:` (row 80, dates row 81, rows 82 to 85), `PRICE:` (row 90), `DERIVED:` (row 92, `Adjusted Equity Shares in Cr`).
- **Labels:** annual P&L: Sales, Raw Material Cost, Change in Inventory, Power and Fuel, Other Mfr. Exp, Employee Cost, Selling and admin, Other Expenses, Other Income, Depreciation, Interest, Profit before tax, Tax, Net profit, Dividend Amount. Quarters: Sales, Expenses, Other Income, Depreciation, Interest, Profit before tax, Tax, Net profit, Operating Profit. Balance sheet: Equity Share Capital, Reserves, Borrowings, Other Liabilities, Total, Net Block, Capital Work in Progress, Investments, Other Assets, Total (second), Receivables, Inventory, Cash & Bank, No. of Equity Shares, New Bonus Shares, Face value. Cash flow: Cash from Operating, Investing and Financing Activity, Net Cash Flow. Note `Total` appears twice in the balance sheet (liabilities and assets).
- **Annual columns:** 10 years (TCS: 2017-03-31 to 2026-03-31). Quarterly columns: later dates only (TCS from 2024-06-30).
- **Banks and insurers use the same labels but the meaning differs.** HDFC Bank: `Sales` 73,271 is total income, `Interest` 38,042 is interest expense, `Borrowings` 741,550 are mostly deposits. HDFC Life `Sales` is premium and income, `Other Mfr. Exp` is mostly claims and benefits. **Industrial ratios (debt to equity, interest cover, operating margin) must not be computed for banks, insurers or finance companies** without a warning or a separate rule. Industry group in `nifty-50.csv` can mark them (Banks, Finance, Insurance).
- **Units:** the sheets show no unit. Values look like crore rupees (TCS sales 117,966 in FY17). Confirm before showing to users.
- **My exploration script failed at the end** on a row index (the sheet has fewer rows than I assumed for the last query). No data was changed. The scratch scripts are in `/tmp`, not in the project.

## 4. What you can try on the console now

Run these from the project root. `bin/run_py.sh` loads `config/arpm.env` and uses the venv Python.

```bash
# Is everything up? (Ollama, app on port 8502)
bin/status.sh

# Watch the document index build, and check it
tail -f runtime/logs/rag_build.log
grep PROGRESS runtime/logs/rag_build.log | tail -1
sqlite3 project-db/rag_ingest.sqlite "select status, count(*) from files group by status"
sqlite3 project-db/rag_ingest.sqlite "select id, status, files_done, files_failed, chunks from runs order by id desc limit 5"
bin/rag_build_stop.sh                       # stop it safely (finished files stay)
bin/rag_build_bg.sh --annual-reports 5      # start or continue it in the background
bin/rag_build.sh --estimate-only            # page counts and a time estimate (about 7 s)

# Search the index (works for the stocks already indexed; TCS first)
bin/run_py.sh rag_check2.py

# Run all 106 tests
cd project-code && .venv/bin/python -m pytest tests -q -p no:cacheprovider -W ignore && cd ..

# Ask the technical agent from the console (uses gemma4:12b; 10 to 50 s)
bin/run_py.sh live_models.py gemma4:12b "How is TCS doing technically?" "What are the stocks available?"

# Price tools, no model involved
bin/run_py.sh -c "from market_data import MarketData as M; import json; print(json.dumps(M().list_stocks(), indent=1)[:600])"
bin/run_py.sh -c "from market_data import MarketData as M; import json; print(json.dumps(M().get_indicators('INFY'), indent=1))"

# Does each model role answer?
bin/run_py.sh -c "from gateway import Gateway; g=Gateway(); print(g.test_connection('chat')); print(g.test_connection('embedding'))"

# Rebuild the price database (note: replaces the old file; see open questions)
bin/run_py.sh prices_db.py
```

Not available yet: document search from the chat, fundamentals, guardrails, the router, portfolios, the call-tree view.
