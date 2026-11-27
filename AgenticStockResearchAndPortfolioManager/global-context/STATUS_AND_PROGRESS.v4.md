# Status and progress: Agentic Research and Portfolio Maker

Updated 2026-11-20 (01:40 local). Previous versions kept as `STATUS_AND_PROGRESS.v1.md`, `.v2.md` and `.v3.md` (no-delete rule).
Read `GLOBAL_CONTEXT.md` first for the layout, rules and architecture. This file is the task tracker:
what is done, what is pending, and what you can run on the console now.
Prompt handling (routes, example prompts, agent prompts, the multi-portfolio and compare-agent design) is in `PROMPT_CONTEXT.md`.
RAG (documents, chunking, build script, measured numbers, Excel findings, open questions) is in `RAG_CONTEXT.md`.

**State at 2026-11-20 01:35:** **160 tests pass** (`project-code/tests/`, 15 files). Ollama is up. The web app is up at **http://127.0.0.1:8502**, restarted at about 01:30, so it runs the router and both agents.
**The full document index build is RUNNING in the background** (PID in `runtime/run/rag_build.pid`, log `runtime/logs/rag_build.log`).
At 01:33 it was at stock 16 of 50, 35% (161,061 of about 465,393 chunks), 34.6 chunks per second, ETA about 2 h 26 m, 509 files done, 0 failed.

## 1. Done

| Area | What exists | Verified how |
|---|---|---|
| Layout and config | `config/paths.json` is the only place paths are written (entries `rag_db` and `fundamentals_duckdb` added). `project-code/config.py` reads it. `bin/*.sh` start and stop Ollama and the app. `config/arpm.env` exists (Ollama URL only; **admin password still empty**). | `test_config.py`, `test_architecture_rules.py` |
| Provider adapters | `providers.py`: Ollama, OpenAI-compatible, Hugging Face. | Ollama live. The other two with mocked HTTP only. |
| Model settings | `model_settings.py`: per-role provider and model, chunking and retrieval values, audit log. **Defaults: chat `gemma4:12b` (think off), router `mistral:7b`, embedding `nomic-embed-text`, summary `mistral:7b`, judge `gemma4:12b`.** | `test_gateway.py`, `test_rag_build.py` |
| AI gateway | `gateway.py`: role-based chat and embed, retry once, usage log with tokens and tokens per second, `test_connection`. | `test_gateway.py`, live |
| Price database | `prices_db.py`: `arpm.duckdb`, 55,167 rows, 23 Mar 2022 to 13 Nov 2026. | `test_prices_db.py` |
| Indicators | `indicators.py`: SMA, EMA, RSI, MACD, Bollinger, ATR, returns, 52-week high and low. | `test_indicators.py` |
| Market data tools | `market_data.py` and `mcp_market_data.py`: 10 tools including `list_stocks`. Tool calls now run under a lock (see "Problems" below). | `test_market_data.py`, live over stdio |
| MCP client, budgets | `mcp_client.py`, `budget.py` (limits on model calls, tool calls, tokens, depth 3). | `test_agent_technical.py` |
| Technical agent | `agent_technical.py`: ten LangChain `@tool` functions over the MCP server, run by LangGraph `ToolNode`. **Refactored 2026-11-20** into a subclassable class (`agent_name`, `system_prompt`, `reminder`, `no_data_answer`, hooks `_make_tools()` and `_call()`). Old file kept as `agent_technical.v1.py`. | Scripted tests; live on `gemma4:12b` |
| RAG chunker, store, build script | `rag_chunker.py`, `rag_store.py`, `rag_build.py`, `bin/rag_build*.sh`. Details in `RAG_CONTEXT.md`. | `test_rag_chunker.py` (11), `test_rag_store.py` (10), `test_rag_build.py` (11); TCS trial live; full run in progress |
| Web app | `app_ui.py` and `ui_app.py`. **Chat tab now routes (2026-11-20):** `get_agents()` builds a `TechnicalAgent` (server `market-data`) and a `FundamentalAgent` (server `fundamentals`); `answer(question, session)` calls `router.route()` and runs one agent, both agents (`both`), or none (`documents`). Tools-used box shows `[agent] tool(args)`, the route and the budget. Admin tab behind `ARPM_ADMIN_PASSWORD`: Models, Providers, Chunking and index status, Usage log, Change log. Port **8502**. | `test_ui_app.py` (9 tests: technical, fundamental, mixed, documents, plus the Admin tests); live through `answer()` with `live_chat.py` |
| **Router (NEW 2026-11-20)** | `router.py`: plain keyword code, **no model call**. Routes: `technical`, `fundamental`, `both` (a financial word and a price word), `documents` (annual report, transcript, presentation, earnings call...). Documents win over everything. No keyword goes to `technical`. Whole-word matching. Phrases such as "price to book" and "return on equity" are removed before the technical check. The planned LLM router (role `router`, `mistral:7b`, untested) can replace `route()` later with no change to callers. | `test_router.py` (19) |
| **Mixed-question focus (NEW 2026-11-20)** | `TechnicalAgent.run(..., focus="")` appends one rule line to the system prompt. For `both`, `ui_app.answer()` tells each agent to answer only its half. Single-route questions pass no focus. | `test_ui_app.py`; live: partly works, see "Known weakness" in pending 3 |
| **Document questions refused (NEW 2026-11-20)** | A `documents` route returns a fixed reply ("not connected to this chat yet") and runs no agent, so the annual-report question no longer gets price returns. | `test_ui_app.py`; live |
| **Fundamentals database** | `fundamentals_db.py` reads the 49 Excel workbooks (`Data Sheet`) into `project-db/fundamentals.duckdb`: tables `fin_values(symbol, section, label, period_end, value)`, `fin_meta`, `build_info`. **49 stocks, 20,747 values**, SBILIFE missing, no duplicate keys. A rebuild renames the old file to a dated name. The two `Total` rows become `Total liabilities` and `Total assets`. Run: `bin/run_py.sh fundamentals_db.py`. | `test_fundamentals_db.py` (8) |
| **Fundamentals tools** | `fundamentals.py` (`Fundamentals` class: `company_type`, `coverage`, `list_line_items`, `get_financials`, `get_quarterly`, `compute_growth`, `compute_ratios`, `get_valuation`) and `mcp_fundamentals.py` (**7 MCP tools**, calls run under a lock). Banks, finance companies and insurers get a warning and no operating margin, interest cover, debt to equity or EV to sales. Operating margin = `(PBT + depreciation + interest - other income) / sales`, checked against the workbook's own Operating Profit for TCS. | `test_fundamentals.py` (15); direct call; live through the agent |
| **Fundamental agent (NEW 2026-11-20)** | `agent_fundamental.py`: `FundamentalAgent` subclasses `TechnicalAgent`, seven LangChain `@tool` wrappers over the `fundamentals` MCP server, own system prompt (numbers from tools only, unit uncertain, no industrial ratios for banks and insurers, SBILIFE missing, Nifty 50 only, no documents or news, growth and CAGR guidance). Gateway role `chat`, agent name `agent_fundamental`, route `fundamental`. | `test_agent_fundamental.py` (9, scripted gateway plus real server, includes a parallel-call test). Live on `gemma4:12b` with `live_fundamental.py`, see below |
| Architecture test | The failing `test_no_hard_coded_database_or_data_paths_in_code` was caused by two docstrings naming `project-db`. Reworded in `fundamentals.py` and `fundamentals_db.py`. | 160 pass |

### Live results through the chat path (`live_chat.py`, `gemma4:12b`, 2026-11-20)
| Question | Route | Result |
|---|---|---|
| check financial statement of infosys (the user's screenshot question) | fundamental | Correct 5-year P&L table: INFY sales 178,650 and net profit 29,440 in FY26. 68 s (first call, model load). |
| What is the RSI of TCS? | technical | 50.39 as of 2026-11-13 |
| 10 good points from last 5 years of TCS annual reports | documents | Refused with the "not connected" reply, no agent ran |
| What are the P/E and ROE of HDFCBANK? | fundamental | P/E 16.55x, ROE 12.97% (first run printed "16.55%"; prompt fixed) |
| Revenue growth and RSI of ITC | both | **Unreliable.** Technical half correct (RSI 66.47). Fundamental half answered "no tool data" in 2 of 2 final runs; a first run worked. Probes: 3 of 8 runs called a tool. |

### Live results of the fundamental agent (`gemma4:12b`, 2026-11-20)
| Question | Result |
|---|---|
| TCS net profit growth over 5 years | Correct after a fix: 32,430 to 49,210, CAGR 8.70% |
| Compare operating margin and ROE of TCS, INFY and WIPRO | TCS and INFY tabulated; WIPRO refused as not Nifty 50 |
| Compare ROE of INFY and TCS | Correct table (TCS 45.89%, INFY 31.71% for FY26) |
| HDFCBANK operating margin | Refused, bank warning passed on |
| SBILIFE revenue | Reported as missing |
| TCS management comments on AI in the annual report | Declined: this agent has only the numbers |
| RELIANCE P/E and market cap | P/E 22.90, market cap 1,849,897.53 (workbook units) |

### Model comparison (19 Nov 2026, M1 Pro, one run each)
| Model | Uses tools? | Result |
|---|---|---|
| `gemma4:12b` | Yes | Correct numbers, 10 to 48 s per question. **Chosen as chat default.** |
| `gemma4:e4b` | Yes | Correct, 28 to 50 s |
| `mistral:7b` | No | Wrote placeholders and invented numbers. Kept for router and summary only. |
| `phi4-mini` | No | Printed the tool JSON as text |

### Problems found, and what was done
| Problem | Cause | Fix |
|---|---|---|
| "What are the stock available" returned top movers | No stock-list tool | New `list_stocks` tool and prompt line. **Fixed, tested.** |
| "10 good points from last 5 years of TCS annual reports" returned price returns | The chat has no document tool and the agent does not refuse out-of-scope questions | **Not fixed yet.** See pending 2 and 3. |
| **`get_financials` crashed with "connection is busy" (2026-11-20)** | The model asked for several tools in one turn. LangGraph runs them in parallel threads, and one DuckDB connection serves one call at a time. | Lock around each tool call in `mcp_fundamentals.py` and `mcp_market_data.py`. Test runs 4 parallel calls, 5 times. **Fixed.** |
| **Model reported year-on-year rows as 5-year growth (2026-11-20)** | `compute_growth` with `years=5` returns rows of 5-year growth, and the old description said "gap in years" | Tool description and prompt rewritten. Live rerun correct. **Fixed.** |
| Port 8501 did not open | The app was down, probably stopped with a cancelled tool call | Port 8502, app started in its own session. Cause not confirmed. |
| Background jobs died when a tool call ended | Child stayed in the tool's session | `bin/rag_build_bg.sh` and `bin/start_app.sh` use `perl POSIX::setsid`. The build survives. |

## 2. Pending (in build order)

| # | Task | Notes |
|---|---|---|
| 0 | **Let the full RAG build finish** (running) | About 2 h 26 m left at 01:33. Marks the collection complete only if all 50 stocks finish with no failed file. Then: `sqlite3 project-db/rag_ingest.sqlite "select status,count(*) from files group by status"`, `du -sh project-db/chroma`. TCS stays at 3 annual reports (run `bin/rag_build_bg.sh --symbols TCS --annual-reports 5` to add 2 more). |
| 1 | **`search_documents` tool** | Query, symbol, doc type, year; returns passages with file and page; "not found" below a score cutoff (about 0.6, untuned). Test it against a fake store now; test it on the real index when the build is complete. **Decision needed: put it on `agent_fundamental` behind the router, or as its own document agent.** |
| 2 | **Router and out-of-scope refusal: keyword router DONE 2026-11-20** | `router.py` handles technical, fundamental, both and documents. **Still open:** (a) refusal of non-stock topics ("Add Tesla", "weather") and non-Nifty stocks is not routed (they fall to `technical`, whose tools say "not covered"); (b) the LLM router on `mistral:7b` is untested; (c) `compare`, `research` and `portfolio` routes do not exist yet. |
| 3 | **Fundamental agent in the chat: DONE 2026-11-20 (01:30).** The user's screenshot ("check financial statement of infosys") was answered by the technical agent because `ui_app.py` built only that agent; the agent code was done but not connected. Fixed with `router.py` and `ui_app.answer()`. App restarted on port 8502. **Known weakness (open):** mixed questions ("Revenue growth and RSI of ITC") run both agents, but the fundamental agent often replies "no tool data" when the question mentions RSI (3 of 8 probes called a tool). Single-topic questions work. See the "Mixed-question decision" item below. |
| 4 | Guardrails (`guardrails.py`) | G1 to G8 from `GLOBAL_CONTEXT.md`. G8 limits exist in `budget.py`. Define "one year of history" for G6 (TMPV has 260 days). |
| 5 | Prompt enhancer | `prompt_enhancer.py`. |
| 6 | Research analyst | `scorecard.py` (code only) and `agent_research_analyst.py` (stub). Can use the fundamentals tools for quality and valuation scores. |
| 6b | `agent_compare` and multi-portfolio requests | Design in `PROMPT_CONTEXT.md` sections 5 and 9. Needs `scorecard.py` and the portfolio manager first. |
| 7 | Portfolio manager | `mcp_portfolio.py` and `agent_portfolio_manager.py` (stub). |
| 8 | Admin tab additions | Document search box, build runs, usage charts, re-index with estimate and confirmation, call-tree view (gateway stores `parent_id`), fundamentals build info. |
| 9 | CLI chat | One command to ask questions and see the tool trace. `live_models.py` (technical) and `live_fundamental.py` (fundamental) do this today. |
| 10 | After the RAG build | Tune the score cutoff on more stocks. Check table quality in annual reports. Check INFY (no PDFs). |

### Smaller items and open questions (waiting on the user unless stated)
- **`ARPM_ADMIN_PASSWORD`** is empty in `config/arpm.env`, so the Admin tab is locked.
- **`config/setup.sh`** still pulls only `mistral:7b` and `nomic-embed-text`. It needs `gemma4:12b` (7.7 GB).
- **`prices_db.build()`** overwrites `arpm.duckdb` (no-delete rule). Proposed: rename the old file to a dated name first, as `fundamentals_db.py` already does. PID files are removed with `rm -f` (proposed: keep). Waiting.
- **Architecture HTML** lacks eight areas and has stale numbers. Proposed: a new versioned file. Waiting.
- **Sector grouping for the compare agent** (Industry Group assumed, 26 groups) and whether `compare` is a router route. Waiting.
- **UpGrad API:** documentation or an example request is needed. The external provider is a generic OpenAI-compatible adapter, never run against a real service.
- **Where `search_documents` goes** (item 1 above). Waiting.
- **Units:** workbooks state no unit. Values look like crore rupees. The agent says "probably Rs crore".
- **Mac must stay awake** and Ollama up for the full RAG build. If it stops, run `bin/rag_build_bg.sh --annual-reports 5` again; finished files are skipped.
- **`bin/start_app.sh` change was only checked for 10 s after start.**
- **Mixed-question decision (waiting):** how to fix the unreliable fundamental half of "both" questions. Options: (1) one extra model call that splits the question into a technical clause and a fundamental clause (accurate, adds seconds); (2) plain code that cuts at "and" or "," (fast, brittle); (3) tell the user to ask one thing at a time. Not decided.
- **Scratch files** left in `project-code/` (none imported by the app, none deleted): `live_models.py`, `live_fundamental.py`, `live_chat.py` (new: runs the chat's `answer()` with real agents and the real model), `rag_check.py`, `rag_check2.py`, `ui_smoke.py`, **`_probe.py`** (throwaway, rewritten several times for probes; safe to remove if you allow it).
- **EC2:** no GPU on m6i/m7i/m8i. `gemma4:12b` will be slow. Test `gemma4:e4b` and the embedding speed there first.
- **Price data caveat:** prices are not adjusted for splits, bonuses or demergers. 14 stocks have one-day moves over 25%.
- **Fundamentals data caveats:** SBILIFE has no workbook. Banks, finance companies and insurers have no industrial ratios. Industry groups: Banks (AXISBANK, HDFCBANK, ICICIBANK, KOTAKBANK, SBIN), Finance (BAJFINANCE, BAJAJFINSV, JIOFIN, SHRIRAMFIN), Insurance (HDFCLIFE, SBILIFE). `mcp_fundamentals.py` has no tool-listing test; the agent test checks that the tool names match the server.

## 3. Excel financials: layout (MEASURED 2026-11-20, now loaded by `fundamentals_db.py`)

- **49 workbooks, not 50.** Only **SBILIFE** has none. M&M's file is `Financials_M_M.xlsx`. The loader handles the file name.
- **All 49 share one layout.** Everything needed is in sheet `Data Sheet` (93 rows): `META` (company name, face value, current price, market cap), `PROFIT & LOSS` (15 labels), `Quarters` (9 labels), `BALANCE SHEET` (16 labels, `Total` twice), `CASH FLOW:` (4 labels), `PRICE:`, `DERIVED:`.
- **Annual columns:** 10 years (TCS 2017-03-31 to 2026-03-31). **Quarterly columns:** later dates only (TCS from 2024-06-30).
- **Banks and insurers use the same labels with different meaning** (HDFC Bank: `Sales` is total income, `Interest` is an expense, `Borrowings` include deposits).
- **Units:** none stated. Values look like crore rupees.

## 4. What you can try on the console now

Run from the project root. `bin/run_py.sh` loads `config/arpm.env` and uses the venv Python.

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

# Search the index (stocks already indexed; TCS first)
bin/run_py.sh rag_check2.py

# Run all 160 tests
cd project-code && .venv/bin/python -m pytest tests -q -p no:cacheprovider -W ignore && cd ..

# Ask the technical agent (gemma4:12b, 10 to 50 s)
bin/run_py.sh live_models.py gemma4:12b "How is TCS doing technically?" "What are the stocks available?"

# Ask the FUNDAMENTAL agent (new)
bin/run_py.sh live_fundamental.py gemma4:12b "How has TCS net profit grown over the last 5 years?" "Compare ROE of INFY and TCS" "What is the P/E of RELIANCE?" "What is the operating margin of HDFCBANK?"

# The whole chat path (router + both agents, real model), without the browser
bin/run_py.sh live_chat.py "check financial statement of infosys" "What is the RSI of TCS?" "10 good points from TCS annual reports" "Revenue growth and RSI of ITC"

# Which route does a question take? (no model)
bin/run_py.sh -c "from router import route; print(route('check financial statement of infosys'))"

# Fundamentals without a model
bin/run_py.sh -c "from fundamentals import Fundamentals as F; import json; print(json.dumps(F().compute_ratios('TCS', 3), indent=1)[:900])"
bin/run_py.sh -c "from fundamentals import Fundamentals as F; print(F().coverage())"
bin/run_py.sh fundamentals_db.py            # rebuild fundamentals.duckdb (old file kept under a dated name)

# Price tools, no model involved
bin/run_py.sh -c "from market_data import MarketData as M; import json; print(json.dumps(M().get_indicators('INFY'), indent=1))"

# Does each model role answer?
bin/run_py.sh -c "from gateway import Gateway; g=Gateway(); print(g.test_connection('chat')); print(g.test_connection('embedding'))"

# Rebuild the price database (replaces the old file; see open questions)
bin/run_py.sh prices_db.py
```

Not available yet: document search from the chat (annual-report questions get a "not connected" reply), reliable mixed price-and-financial questions, guardrails, the LLM router, portfolios, call-tree view.
