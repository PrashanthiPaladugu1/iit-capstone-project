# Agent plan: Nifty 50 multi-agent chat (v2; user said 'build locally' on 2026-11-18, build started)

Status: **designed, not built.** Visual version: `html/IITKGP-Agentic-NIFTY50-Plan.html`.
Date: 2026-11-18. Scope: **Nifty 50 only** (compute limit).

## Goal
Chat app with a router that sends each question to a technical agent (Nifty 50 price files) or a
fundamental agent (Screener documents), using MCP tools and RAG. Fully local.

## Architecture (decided)
- UI: Streamlit chat.
- Orchestration: LangGraph. Router node -> `technical` | `fundamental` | `both` | `out_of_scope` -> synthesizer with citations.
- Technical agent -> MCP server `market-data` -> DuckDB over `data_stock_bhavcopy_nifty50/<SYMBOL>.csv`.
  Tools: get_ohlcv, get_returns, get_52w_high_low, get_delivery_pct, get_indicators (SMA/RSI/MACD, computed in Python), top_movers, compare_stocks.
- Fundamental agent -> MCP server `fundamentals`: structured tools (get_financials, compute_cagr) over the
  `Financials_<SYM>.xlsx` "Data Sheet" loaded into DuckDB, plus `search_documents` (RAG over PDFs, filters: symbol, doc_type, year).
- RAG: Chroma + `nomic-embed-text` (already installed in Ollama). Chunk metadata: symbol, doc_type, period, page, file.
- LLM: local Ollama. Installed: gemma4:12b, gemma4:e4b, mistral:7b, phi4-mini, llama3.2:1b. Verify tool-calling support before choosing.
- Numbers always come from tools (SQL/Python), never from the LLM or from vector similarity.

## Data facts (measured 2026-11-18)
- `data/`: 50 folders, ~15 GB; 3,406 PDFs (667 annual reports ~282 pages avg, 999 transcripts ~21, 1,740 presentations ~46) = ~288k pages;
  49 Excel (sheets: Profit & Loss, Quarters, Balance Sheet, Cash Flow, Customization, Data Sheet); 27 zip.
- PDFs sampled (45) all had a text layer (no OCR needed); `pdftotext` installed.
- Prices: `data_stock_bhavcopy_nifty50/` 50 files, 57,767 rows, EQ only, 23-Mar-2022 -> 13-Nov-2026. TMPV only 276 rows.
- Index file `data_nse_index/<date>/NIFTY_50.csv` = snapshot of constituents + day's quotes, NOT history and no membership dates.
- Gaps: INFY Excel only; SBILIFE no Excel; ITC/TRENT no transcripts; BAJAJ-AUTO no presentations; BSE/JIOFIN/ETERNAL 3-5 annual reports.
- Bhavcopy prices are NOT adjusted for splits/bonuses/demergers, so long-range returns can be wrong.

## Machine
M1 Pro, 32 GB RAM, Python 3.9.6 default (MCP SDK needs >= 3.10 -> create a 3.11/3.12 venv). Installed: chromadb, langgraph, langchain,
ollama, pandas, openpyxl, pypdf, streamlit. Not installed: duckdb, mcp. Disk: 19 GiB free (97% used) on 2026-11-18.

## Staged RAG ingestion (compute limit)
1. Tier 1: Excel financials + all transcripts (~21k pages).
2. Tier 2: latest 3 annual reports per stock (~40k pages).
3. Tier 3: latest 4-6 presentations per stock; older annual reports only if needed.
Measure embedding speed on Tier 1 before committing to Tier 2/3.

## Build order (proposed)
1. venv + DuckDB loader + `market-data` MCP + technical LangGraph agent (no embeddings needed).
2. Fundamentals structured tools (Excel -> DuckDB).
3. RAG Tier 1, then 2, 3.
4. Router + Streamlit app + evaluation questions.

## Open questions for the user
1. Confirm the architecture and the staged ingestion.
2. Which Ollama model for the router/agents (gemma4:12b vs mistral:7b)?
3. Fill the data gaps first (re-run `--index Nifty50 --force`)? INFY PDFs may be blocked (403).
4. Keep point-in-time Nifty 50 snapshots (keep each `data_nse_index/<date>/` folder) for later membership history?
5. (Answered 2026-11-18) App name is **Agentic Research and Portfolio Maker**, not StockWood. Package/folder: `agentic_research_portfolio_maker/`.

## v2 additions (2026-11-18, requested by the user)
Visual: `html/IITKGP-Agentic-NIFTY50-Plan.html` (v2). Still nothing built.

### Portfolio agent (third agent)
- Real tool-calling agent with its own MCP server `portfolio` (reads prices + financials; saved portfolios in SQLite).
- Start modes: user names the stocks, or gives a goal and the agent picks 4-6 using technical + fundamental scores.
- Tools: validate_portfolio, suggest_portfolio, build_portfolio (equal, inverse-vol, risk parity, min-variance, max-Sharpe),
  portfolio_metrics, sector_exposure, allocate_capital, backtest_portfolio, compare_portfolios, swap_stock, rebalance_plan,
  save/load/list_portfolios.
- Data limits: no Nifty 50 index history on disk (only a 1-day snapshot) -> beta uses an equal-weight proxy of the 50 stocks;
  prices unadjusted for splits/bonuses/demergers -> backtest caveat.

### Guardrails (plain code, run before the router AND again inside the portfolio MCP tools)
- G1 every stock must be in the Nifty 50 list -> block + alert.
- G2 portfolio of 7+ distinct stocks -> block + alert. G3 fewer than 4 -> block (ASSUMPTION: user only specified the upper limit).
- G4 weights sum to 100%, each within min/max (defaults 5% / 40%, ASSUMED, configurable) -> block.
- G5 > 50% in one sector (industry group from `Reference-Files/nifty-50.csv`) -> warn. G6 < 1 year of prices (e.g. TMPV 276 days) -> warn.
- G7 disclaimer + data date + unadjusted-price note on every portfolio answer. G8 per-question limits on tool calls, loop steps, tokens -> stop.
- Every trigger is logged for the Admin tab.

### AI gateway + tokenomics
- One Python wrapper through which EVERY Ollama call goes (chat and embeddings). Later can become a separate service.
- Verified on this machine (2026-11-18): Ollama returns prompt_eval_count, eval_count, total_duration, load_duration,
  prompt_eval_duration, eval_duration on each response; tokens/sec = eval_count / eval_duration. All 5 chat models list `tools`.
- Log row per call: time, session, agent, graph node, route, model, tokens in/out, durations, tokens/sec, status, error, tool calls + latency,
  guardrail events. Question preview only by default; full text logging is an opt-in setting.
- Cost: local models have no per-token fee. Show tokens and time; optional "what-if cost" = tokens x a per-model rate the user enters. No prices pre-filled.
- Controls: model allow-list and model per agent, timeouts, max loop steps, token budget per question/session/day, one retry.

### Admin tab (Streamlit, password from an env var, Plotly charts)
KPIs (requests, tokens in/out, median + p95 latency, tokens/sec, error rate, guardrail triggers, budget used, what-if cost);
charts: tokens over time, route mix, tokens by agent, tokens by model, speed + cold-start by model, latency box plot by agent,
tool-call counts + latency, guardrail events by rule, embedding tokens per RAG tier; request log table, top-10 costliest questions,
read-only controls panel.

### Router
Still a workflow node (one LLM call that picks a route: technical | fundamental | portfolio | both | out_of_scope), not an agent.
Option to become a supervisor agent in Phase 4+ only if test questions need dependent multi-step plans.

### Updated build order
1. venv + gateway with usage logging + DuckDB + `market-data` MCP + technical agent.  2. Fundamentals structured tools.
3. RAG Tier 1, then 2, 3 (embedding speed measured via the gateway).  4. Guardrails + router + Chat tab.
5. Portfolio agent + `portfolio` MCP.  6. Admin tab.

### Open questions (v2)
Confirm G3 (<4 blocked) and weight limits; admin access method; logging default; local model choice; data-gap re-download; (folder name answered, see decisions).

## Decisions and facts added 2026-11-18 (after v2)

### User decisions
- **App name: Agentic Research and Portfolio Maker** (user, 2026-11-18). Do NOT use "StockWood". Python package/folder `agentic_research_portfolio_maker/`. UI title uses the full name.
- **Build locally** in a Python virtual environment (NOT in containers now). Dockerizing is a later, optional step (see below).
- Langfuse: user asked if it can be included; recommended option = Langfuse + a slim Admin tab, added AFTER Phase 4. Not decided finally; do not install yet.
- Model choice, G3 (<4 stocks blocked), weight limits 5%/40%, admin password via env var, preview-only logging:
  not explicitly answered. Working defaults used in the build: G3 on, 5%/40%, env-var password, previews only, default model `mistral:7b` for
  speed with `gemma4:12b` selectable (both support tools). Change on request.

### Measured on this machine (2026-11-18)
- PDF text extraction (pdftotext): 78 pages/s transcripts, 128 annual reports, 101 presentations.
- Embedding nomic-embed-text (768 dims): ~60 chunks/s at 744 chars; model loads in 0.2 s.
- Chroma 10,000 chunks (random vectors, text + metadata): 157 MB = ~15.4 KB/chunk, add ~700/s, filtered query 23 ms. (Earlier "2-4 GB for everything" was wrong; full set ~12 GB.)
- mistral:7b ~25 tok/s, gemma4:12b ~18.5 tok/s (think=False), both ~3 s load; gemma4:12b runs 100% on the Apple GPU (mlx).
- Real text per page: annual report ~3,000 chars, transcript ~2,600, presentation ~650. ~672M chars total = ~0.79M chunks @1000 chars/15% overlap.
- Staged plan: Tiers 1-3 = ~74k pages, ~222k chunks, ~1.3-1.6 h compute, ~5.4 GB disk. Everything: ~288k pages, ~790k chunks, ~4.7-5.6 h, ~14.4 GB.
  (Tier 3 = latest 5 decks per stock = ~11.5k pages, not 20k.)
- Dev effort estimate ~5-7 working days; typical answer ~20-45 s on gemma4:12b.
- Disk free fluctuates 19-35 GiB (97-98% used). Check before heavy steps.

### Environment
- Python 3.10, 3.12, 3.13 are installed (Homebrew), plus `uv` and `pyenv`. Project venv uses Python 3.12 via uv. Default `python3` is 3.9.6 (leave alone).
- Podman 5.8.1 installed, no Docker, no compose tool; Podman VM = 5 CPU, 2 GiB RAM (too small), never started.

### Langfuse notes
- Self-hosted v3/v4 = 6 services (web, worker, ClickHouse, MinIO, Redis, PostgreSQL); docs: >=4 cores/16 GiB for a VM, blog says 4 GB RAM min (8 recommended), ~20 GB disk.
  Needs a container runtime. Stores full prompts by default (conflicts with preview-only default; check SDK masking).

### Dockerizing (later, optional)
- Containerize app + 3 MCP servers + Chroma (+ Langfuse profile). **Keep Ollama on the Mac host** (containers on macOS cannot use the Apple GPU);
  containers reach it at host.containers.internal:11434. Mount data read-only, strict .dockerignore (data/, logs/, secret/, screener_auth.json, .git, context/).
  Needs: compose tool, Podman VM resized to 4-8 GiB.

### Build log (update as built)
See `context/PROGRESS.md` section "Agent build log".

### Layout decision (2026-11-18)
- App code lives in a separate `Project-Code/` folder (all agents, MCP servers, DB, RAG code), **not** in `screener-document-download/`.
  This folder stays downloaders + data and is only read by the app. Generated data (Chroma, DuckDB, usage log, portfolios) goes to `Project-Code/app_data/`.
- Data location is a single setting, `ARPM_DATA_ROOT`. The app must not read `screener_auth.json`, `secret/`, tracker, history or logs.
- The user will also place both under a new parent folder (named "Agentic Stock Research and Portfolio Manager" in the user's message). App name stays **Agentic Research and Portfolio Maker**.
- Handoff, move steps and gotchas: `context/START_HERE_NEXT_SESSION.md`.
