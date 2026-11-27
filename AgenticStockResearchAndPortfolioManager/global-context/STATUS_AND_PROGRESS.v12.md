# Status and progress: Agentic Research and Portfolio Maker

Updated 2026-11-26 (16:30 IST). Previous versions kept as `STATUS_AND_PROGRESS.v1.md` to `.v10.md` (no-delete rule; `.v10.md` is the 23 Nov state).
Read `GLOBAL_CONTEXT.md` first for the layout, rules and architecture. This file is the task tracker:
what is done, what is pending, and what you can run on the console now.
Prompt handling (routes, example prompts, agent prompts, the multi-portfolio and compare-agent design) is in `PROMPT_CONTEXT.md`.
RAG (documents, chunking, build script, measured numbers, Excel findings, open questions) is in `RAG_CONTEXT.md`.

**State at 2026-11-26 16:30 IST:** **593 tests pass** (`project-code/tests/`, 29 files; full run 26 Nov, 21 s). **Restart the app before using anything built on 26 Nov (including the new Admin Guardrails tab)** (`bin/stop_app.sh && bin/start_app.sh`): `get_agents()` is cached, so a running app has no news agent, no `parallel` setting and no `[router]` invoke lines. The web app runs at **http://127.0.0.1:8502**. It has a ChatGPT-style chat (saved conversations, sidebar search) and an Admin view.
**Built 26 Nov (section 1e):** the **news agent** (`agent_news.py`, `news_tools.py`, `mcp_news.py`, role `sentiment`, route `news`, third specialist of the research analyst); an optional **parallel mode** for the analyst (Admin, Agents tab, off by default; no speed-up measured); **"Tools used" now shows who invoked whom** (`[router] invoke_agent_...`, `[research] invoke_agent_...`, `[portfolio]`, `[news]`).
**Start here next session:** section 2 "Pending": item N1 (finish the news agent: live-blog filter and prompt fixes are done; still open: check the Admin Models tab, sentiment accuracy set, architecture page), then item 0 (the stuck screener question, still undiagnosed), then item 1 (Admin Tokenomics tab). **This file's 23 Nov text said the portfolio manager was a stub and 327 tests; both are stale, see section 1d and 1e.**
**Built 22 Nov (section 1c):** Screener snapshot data (`screener.duckdb`, `screener_db.py`, `screener.py`), three `screener_*` tools in `mcp_fundamentals.py` (now 11 tools) and `agent_fundamental.py`, a `SCREENER` word list in `router.py` (74 route tests), 34 new tests. **Built 23 Nov:** architecture HTML sections 3.1 to 3.5 (traffic flow chat app to router to agents, and how the research analyst works with the two specialists), `screener.duckdb` added to the data layer, 2.1 inventory and MCP table.
**Built since the last update (2026-11-20 14:00 to 2026-11-21 00:00):** ChatGPT-style chat UI with saved conversations (`chat_store.py`, `chats_db`); keyword-router additions (conference-call wordings, capex, guidance, order book, attrition, a `RESEARCH` list); **research analyst** (`agent_research_analyst.py`, runs for the `both` route); **tokenomics Part 1** (cost in the gateway, rates, daily cap, `tokenomics.py`); architecture HTML rewritten (15 sections); EC2 sizing answered; Langfuse decision. Details in section 1b.
**Architecture HTML updated 2026-11-21 evening** (see pending item 8).
**Open defect (23 Nov):** the web app showed "Working..." for ever on "show me NIFTY 50 PE RSI OMP NPM" (typo OMP, no word "stocks"). `app.log` had no traceback and `usage.sqlite` had no row for it, so no model call was made. **Cause not found.** Details in section 1c.
**Not built yet:** Admin Tokenomics tab (Part 2), optional Langfuse tracing (Part 3), prompt enhancer, out-of-scope refusal, **`agent_compare`** (file does not exist). The portfolio manager and guardrails G1 to G7 **are built** (section 1d); a live run after the prompt change is not recorded.
**Full document index:** finished 2026-11-20 04:16 (4 h 01 m): 1,477 files, 0 failed, 49 stocks, 129,276 pages (1,016 empty), 528,991 chunks, 6.1 GB. Collection `ollama_local-nomic-embed-text-page-c1000-o150`.

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
| Web app | `app_ui.py` and `ui_app.py`. **(Superseded by section 1b: ChatGPT-style UI.)** **Chat tab now routes (2026-11-20):** `get_agents()` builds a `TechnicalAgent` (server `market-data`) and a `FundamentalAgent` (server `fundamentals`); `answer(question, session)` calls `router.route()` and runs one agent, both agents (`both`), or none (`documents`). Tools-used box shows `[agent] tool(args)`, the route and the budget. Admin tab behind `ARPM_ADMIN_PASSWORD`: Models, Providers, Chunking and index status, Usage log, Change log. Port **8502**. | `test_ui_app.py` (9 tests: technical, fundamental, mixed, documents, plus the Admin tests); live through `answer()` with `live_chat.py` |
| **Router (2026-11-20; extended, see 1b)** | `router.py`: plain keyword code, **no model call**. Routes: `technical`, `fundamental`, `both` (a financial word and a price word), `documents` (annual report, transcript, presentation, earnings call...). Documents win over everything. No keyword goes to `technical`. Whole-word matching. Phrases such as "price to book" and "return on equity" are removed before the technical check. The planned LLM router (role `router`, `mistral:7b`, untested) can replace `route()` later with no change to callers. | `test_router.py` (74 since 22 Nov) |
| **Mixed-question focus (NEW 2026-11-20)** | `TechnicalAgent.run(..., focus="")` appends one rule line to the system prompt. For `both`, `ui_app.answer()` tells each agent to answer only its half. Single-route questions pass no focus. | `test_ui_app.py`; live: partly works, see "Known weakness" in pending 3 |
| **Document questions (CHANGED 2026-11-20 11:50)** | The `documents` route now runs `agent_fundamental` with `rag_search_documents`. The fixed "not connected" reply was removed from `ui_app.py`. | `test_ui_app.py::test_document_question_goes_to_the_fundamental_agent`; live on `gemma4:12b` |
| **Fundamentals database** | `fundamentals_db.py` reads the 49 Excel workbooks (`Data Sheet`) into `project-db/fundamentals.duckdb`: tables `fin_values(symbol, section, label, period_end, value)`, `fin_meta`, `build_info`. **49 stocks, 20,747 values**, SBILIFE missing, no duplicate keys. A rebuild renames the old file to a dated name. The two `Total` rows become `Total liabilities` and `Total assets`. Run: `bin/run_py.sh fundamentals_db.py`. | `test_fundamentals_db.py` (8) |
| **Fundamentals tools** | `fundamentals.py` (`Fundamentals` class: `company_type`, `coverage`, `list_line_items`, `get_financials`, `get_quarterly`, `compute_growth`, `compute_ratios`, `get_valuation`) and `mcp_fundamentals.py` (7 numeric MCP tools, 8 with `rag_search_documents`, **11 since 22 Nov with the three `screener_*` tools**; calls run under a lock). Banks, finance companies and insurers get a warning and no operating margin, interest cover, debt to equity or EV to sales. Operating margin = `(PBT + depreciation + interest - other income) / sales`, checked against the workbook's own Operating Profit for TCS. | `test_fundamentals.py` (15); direct call; live through the agent |
| **Fundamental agent (NEW 2026-11-20)** | `agent_fundamental.py`: `FundamentalAgent` subclasses `TechnicalAgent`, seven LangChain `@tool` wrappers over the `fundamentals` MCP server, own system prompt (numbers from tools only, unit uncertain, no industrial ratios for banks and insurers, SBILIFE missing, Nifty 50 only, no documents or news, growth and CAGR guidance). Gateway role `chat`, agent name `agent_fundamental`, route `fundamental`. | `test_agent_fundamental.py` (9, scripted gateway plus real server, includes a parallel-call test). Live on `gemma4:12b` with `live_fundamental.py`, see below |
| Architecture test | (2026-11-20) The failing `test_no_hard_coded_database_or_data_paths_in_code` was caused by two docstrings naming `project-db`. Reworded in `fundamentals.py` and `fundamentals_db.py`. | 160 pass |

## 1b. Done since 2026-11-20 14:00 (new in this update)

| Area | What exists | Verified how |
|---|---|---|
| **ChatGPT-style web app** | `ui_app.py` and `app_ui.py` rewritten (old copies `ui_app.v1.py`, `ui_app.v2.py`, `app_ui.v1.py`). New chat button, saved conversations in the sidebar grouped by day (`group_label`), sidebar search, a tools-used box under each answer. **The sidebar has no delete button on purpose (no-delete rule).** Admin view: Models, Providers, Chunking and RAG, Usage log, Change log (locked until `ARPM_ADMIN_PASSWORD` is set). | `test_ui_app.py` (24), screenshots `runtime/screens/welcome.png`, `conversation.png`. **Not yet seen by screenshot:** the top of a conversation, the Admin view, sidebar search. |
| **Chat history store** | `chat_store.py`, class `ChatStore` (`new_conversation`, `get`, `add_message` with trace and budget, `messages`, `list_conversations(query)`), file `project-db/chats.sqlite`, path entry `chats_db`. `config/paths.v1.json` is the copy from before the entry was added. | `test_chat_store.py` (10) |
| **Router additions** | `router.py` (old copy `router.v1.py`). Added: spoken and plural forms of "conference call" (con call(s), con-call, concalls, earnings calls, analyst call(s)); topic words that live in calls and reports (capex, capital expenditure, guidance, order book, attrition); a new **`RESEARCH` list** for open requests (research, analyse, full analysis, tell me about, how is, should I invest, undervalued, cheap, pros and cons, what do you think, summary of...). The RESEARCH rule fires only when no fundamental or technical word is present, and sends the question to `both`. Side effect: "tell me about" now routes to `both` (one old word-boundary test was reworded to "pricey salesmen are everywhere"). | `test_router.py` (62). Live: "Find 4 stocks which shows higher capex in con calls?" now goes to `documents` and returns a 4-stock table with file and page. **Rows not checked against the transcripts.** |
| **Research analyst** | `agent_research_analyst.py`, class `ResearchAnalyst(gateway, technical, fundamental)`, no tools of its own. Flow: (1) one `chat` call splits the question into a technical part and a fundamental part (fenced JSON accepted; if unreadable, both agents get the whole question plus an "answer only your half" note); (2) both specialists run on one shared budget (`new_budget()`: 24 model calls, 40 tool calls, 80,000 tokens); (3) one `chat` call writes the merged answer. **Checks on the merge:** any number no specialist gave makes it fall back to the two labelled specialist answers with a note; `strip_unsupported_citations` removes bracketed page citations no specialist gave; one failed or stopped specialist does not kill the other. If only one part is needed, that specialist answers with no synthesis call. Used for the `both` route only (`ui_app.answer()` appends `result.note`). Old copy `agent_research_analyst.v1.py` (the stub). | `test_agent_research_analyst.py` (27, scripted gateway). Live on `gemma4:12b`: "Revenue growth and RSI of ITC" 59 s; "Compare TCS and INFY" 82 s; "Is TCS a good stock to buy" 136 s. **Untested live:** split-failure fallback, stopped-specialist path. |
| **Tokenomics Part 1 (gateway cost)** | `model_settings.py`: new `rates` table with `get_rate`, `set_rate`, `list_rates` (local providers with no rate cost 0; external providers with no rate are "unknown", never guessed); new `cost_cap` setting `{"daily": None}`; every rate change audited. `gateway.py`: new usage columns `cost_in`, `cost_out`, `cost_total`, `cost_known` (added with `ALTER TABLE`, old rows kept); cost set on `result.cost`; `summary(by)` for day, role, model, agent or provider; `spend_today()`, `cost_cap_state()`, `recent_sessions()`, `session_calls()`; paid calls raise `GatewayError("daily cost cap reached...")` once the cap is hit, local calls are never blocked. `budget.py`: `max_cost`, `cost`, a cost-limit check, `after_model_call(tokens_in, tokens_out, cost=None)`; `summary()` now includes `"cost"`. `providers.py`: `cost` field on `ChatResult` and `EmbedResult`. New `tokenomics.py`: `what_if(tokens_in, tokens_out, rates)` and `call_tree(rows)` (handles missing parents and cycles). Backups: `model_settings.v1.py`, `gateway.v1.py`, `budget.v1.py`, `providers.v1.py`. **All rates are empty. No prices were invented.** | `test_tokenomics.py` (26); `test_gateway.py` |
| **Research-quality fixes (from the user's TCS screenshots)** | Defect 1: merged answer carried invented citations like "(Technical Analyst, p. 1)" because the number check ignores small whole numbers. Fixed by `strip_unsupported_citations`. Defect 2: answer ignored the buy question. Synthesis prompt now says it cannot advise and gives evidence for and against. Defect 3: fundamental half too thin. Split prompt now asks for growth, margins, ROE, valuation and documents. | Live: "Is TCS a good stock to buy" gave "I cannot advise...", an Evidence For list, a Delivery % point and a Strategy point from management documents. **The output was cut at 900 characters by the script, so "Evidence Against" and the final citations were not seen. Check next.** |
| **Stale-cache bug (found by the user's screenshot)** | After `SettingsStore.get_rate` was added, the running app still held the old cached settings object, and every chat failed with "'SettingsStore' object has no attribute 'get_rate'". **Rule: restart the app after every code or settings change (`bin/stop_app.sh && bin/start_app.sh`).** Three failed chats from this are kept in `chats.sqlite` (no-delete). | Restarted; chat works |
| **Test and tooling additions** | `pytest.ini` ignores `*.vN.py` backups. `tests/test_architecture_rules.py` now allows `providers.vN.py` backups. `ui_shot.py` drives headless Chrome over the DevTools protocol (the plain `--screenshot` flag only captures Streamlit's loading skeleton). Backups of the UI tests: `tests/test_ui_app.v1.py`, `v2.py`. | 293 pass |
| **Architecture HTML** | `global-architecture/Nifty50-Project-Status-and-Work-Plan.html` rewritten as 15 sections: status, data and gaps, colour-coded architecture, six flow charts, agents, router, MCP tools, RAG, gateway, web app, code and tests, guardrails, to-do, risks, EC2 sizing. Old file kept as `...v1.html` (stale on purpose). **(Updated later the same day to cover the analyst, tokenomics and 293 tests; see pending item 8.)** | Opened and read |

### Decisions made this period
- **Langfuse (user said "take my approval for everything in one go"):** Option C is the base: extend the app's own usage log and Admin view. Langfuse is an **optional add-on that stays off unless keys are set** in `config/arpm.env`. The user noted Langfuse can run locally (LangSmith is cloud-only). Self-hosted Langfuse (v4 docs) needs a web container, a worker container, Postgres, ClickHouse, Redis or Valkey and S3-style storage, and has no plain-process install. With the no-Docker rule, the routes are Langfuse Cloud or a Compose box on another machine (Podman exists at `/opt/homebrew/bin/podman`, not used). **The Langfuse SDK API has not been checked yet; check the current docs before coding.**
- **Rates:** left empty. Local Ollama is free. Nothing is priced until the user enters rates in the Admin tab.
- **EC2 sizing (an estimate, nothing measured on EC2):** 16 GB RAM floor with `gemma4:12b` (about 14 to 16 GB used; 4 to 6 GB with an external `chat` API), 8 vCPU for a usable pace, 50 GB gp3 disk (about 25 GB used). Try **m7i.xlarge** first; move to **m7i.2xlarge** if compare and research answers are slow. The 15 GB `data` folder is needed only for rebuilds: copy `project-db/chroma` instead of rebuilding (4 h on the Mac, slower on CPU).
- **Which model runs at each step:** `chat` = `gemma4:12b` runs every agent call, the analyst split and the analyst merge; `embedding` = `nomic-embed-text` runs every document search and the index build; the router is plain code (no model); `router` and `summary` roles (`mistral:7b`) and `judge` (`gemma4:12b`) are set but **never called by any code**.

### Speeds on the Mac (M1 Pro, 32 GB, MEASURED, one run each)
First call after a restart 40 to 68 s (model load). Single-topic answers 8 to 37 s. Compare and research answers 60 to 136 s. The Mac is under memory pressure from other applications; the project itself is small (app about 75 MB, Ollama about 26 MB idle).

### Live results through the chat path (`live_chat.py`, `gemma4:12b`, 2026-11-20)
| Question | Route | Result |
|---|---|---|
| check financial statement of infosys (the user's screenshot question) | fundamental | Correct 5-year P&L table: INFY sales 178,650 and net profit 29,440 in FY26. 68 s (first call, model load). |
| What is the RSI of TCS? | technical | 50.39 as of 2026-11-13 |
| 10 good points from last 5 years of TCS annual reports | documents | **Now answered (11:45):** 10 points with file and page, from `rag_search_documents` (Annual_Report_2022 p. 109, 2023 p. 89, 2024 p. 72). Earlier it was refused with the "not connected" reply. |
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
| **`fsa_get_financials` crashed with "connection is busy" (2026-11-20)** | The model asked for several tools in one turn. LangGraph runs them in parallel threads, and one DuckDB connection serves one call at a time. | Lock around each tool call in `mcp_fundamentals.py` and `mcp_market_data.py`. Test runs 4 parallel calls, 5 times. **Fixed.** |
| **Model reported year-on-year rows as 5-year growth (2026-11-20)** | `fsa_compute_growth` with `years=5` returns rows of 5-year growth, and the old description said "gap in years" | Tool description and prompt rewritten. Live rerun correct. **Fixed.** |
| Port 8501 did not open | The app was down, probably stopped with a cancelled tool call | Port 8502, app started in its own session. Cause not confirmed. |
| Background jobs died when a tool call ended | Child stayed in the tool's session | `bin/rag_build_bg.sh` and `bin/start_app.sh` use `perl POSIX::setsid`. The build survives. |

## 1e. Done 2026-11-26: news agent, parallel mode, invoke lines (tests first, 515 tests pass)

**Agent layout the user asked for:** `agent_technical`, `agent_fundamental` and `agent_news` are **independent**. Only the **research analyst** (and the router, for a single-topic question) calls them. `agent_news` is its own class: it does **not** subclass `TechnicalAgent`, and has its own prompt, loop and MCP server.

| Area | What exists | Verified how |
|---|---|---|
| **News data** | `news_tools.py`, class `NewsTools`: reads **10 RSS feeds from 5 Indian sites**: Economic Times (Markets stocks, Markets all, Company news, Industry, Tech and IT, Economy), Mint (Markets), Business Standard (Markets), Hindu BusinessLine (Markets), NDTV Profit (Latest). Title, link, date and source only; **no article pages are downloaded**. Matches headlines to the 50 Nifty stocks by company name (`ALIASES`; short names such as ITC, Trent, TCS, BEL need exact capitals; "SBI Life" is not SBIN; "BSE" alone is the exchange). Newest first, same story removed across feeds, at most 4 per site, feeds cached 15 min, one broken feed is named and the rest still answer. `days` must be a whole number 1 to 30. | `test_news_tools.py` (72) |
| **Sentiment** | `NewsTools.sentiment`: one gateway call (role **`sentiment`**) labels up to 12 headlines positive, negative or neutral; **code adds up the counts**. A bad or missing label is counted `unlabelled`, never guessed. Labels are reused in a session, so a repeat costs no call. Role `sentiment` added to `model_settings.py` (`ROLES`, default `gemma4:12b`, `think` off, `temperature` 0); editable in Admin. Test on 26 Nov: 12 real TCS headlines in 8.5 s on `gemma4:12b`; `gemma4:12b`, `mistral:7b` and `phi4-mini` agreed on 9 to 10 of 12. **Accuracy is not measured (no labelled set).** | `test_news_tools.py` |
| **MCP server** | `mcp_news.py`, server `news`, 3 tools: `news_search(stock, days, limit)`, `news_sentiment(stock, days)`, `news_market(days, limit)`. Errors come back as `{"error": ...}` text. | `test_news_tools.py`, `test_agent_news.py` (real server) |
| **Agent** | `agent_news.py`, class `NewsAgent`, name `agent_news`. Own loop (max 12 steps plus the shared Budget), one reminder then a fixed "no news data" answer when the model answers without a tool, a bad tool name or argument goes back to the model as an error, results cut at 6,000 characters. Prompt: headlines only, source and date with every item, say "no headline found" instead of "nothing happened", no price prediction, no buy or sell, no claim that a headline caused a price move. Run state is local, so one instance can answer two questions at once. | `test_agent_news.py` (20) |
| **Analyst and news** | `ResearchAnalyst(gateway, technical, fundamental, parallel=False, news=None)`. With a news agent the split prompt is `SPLIT_PROMPT_NEWS` (a `news` part only when the user asks about news; "research TCS" does not call it). New `parse_parts`; `parse_split` unchanged. The merge adds `NEWS_MERGE_RULES` only when a news answer exists. | `test_news_integration.py` (34) |
| **Router** | New `NEWS` list in `router.py`: news, headline(s), sentiment, announcement(s), latest on, what is happening, in the news, buzz, rumour(s). Route **`news`** for a news word alone; **`both`** when a price or statement word is also present (goes to the analyst). A portfolio or document word still wins. | `test_news_integration.py` (13 route cases) |
| **UI** | `get_agents()` builds `NewsAgent` with its own `news` MCP server and passes it to the analyst. `answer()` handles route `news`; with no news agent it says so and does not use the other agents. Welcome text mentions news. | `test_news_integration.py` |
| **Tools used: who invoked whom** | The panel now starts with `[router] invoke_agent_research_analyst({"question": ...})`, `[router] invoke_agent_portfolio_manager(...)` or `[router] invoke_agent_news(...)`. The analyst adds `[research] invoke_agent_technical(...)`, `invoke_agent_fundamental(...)`, `invoke_agent_news(...)` (the question it handed down) before each specialist's own calls. Portfolio and news tool calls carry the `[portfolio]` and `[news]` labels. **Not done:** single-agent technical and fundamental routes still show no `[router]` line. | `test_agent_research_analyst.py`, `test_ui_app.py` |
| **Parallel mode** | `ResearchAnalyst.parallel` runs the specialists in threads. `Budget` now has a lock and per-branch depth (`branch()`, `current_depth()`); `Gateway._last_cost` is per thread. Admin has a new **Agents** tab with a checkbox ("Run the technical and fundamental agents at the same time"), stored as setting `agents` `{"parallel": false}`; `answer()` reads it before **every** mixed question, so a change needs no restart. **Default off.** Live test "Compare TCS with INFY" on `gemma4:12b`: **187.5 s sequential, 188.1 s parallel** (6 against 8 model calls, 17 against 23 tool calls, 20,163 against 45,533 tokens; one run each, the model chose different tools). No time saved here; the reason is not confirmed (probably Ollama serving one request at a time). Re-test on a provider that serves requests side by side. | `test_parallel_analyst.py` (13), `test_ui_app.py` |

### Live results of the news agent (26 Nov 2026, real feeds, `gemma4:12b`)
- "Any news on TCS this week?" 35.7 s: 2 headlines with source, date and link, counts 1 positive and 1 neutral. "Sentiment around Infosys, 7 days" 23.3 s: 4 headlines, 3 positive and 1 neutral, said fewer than 5 is not a trend. "Market news today" 41.3 s: 5 headlines. "Any news on Wipro?" 2.7 s: "not a Nifty 50 stock". All 10 feeds answered 200.
- **Through the analyst:** "Tell me the RSI of TCS and the latest news on it" 56 s, 6 model calls, 3 tool calls: `[research] invoke_agent_technical`, `[technical] get_indicators`, `[research] invoke_agent_news`, `[news] news_search`, `[news] news_sentiment`. Answer had RSI 50.39 (as of 2026-11-13), 2 headlines and the counts.
- **Seen problems (not fixed):** (1) live-blog pages such as "TCS Share Price Highlights: TCS Stock Price History" pass as news; (2) the model wrote `fetched_at` as `2026-11-26T16:26:05:30` (the tool gave `...16:26+05:30`); (3) it called both `news_search` and `news_sentiment` when one was enough; (4) only 2 to 4 headlines per stock, because the feeds are general market feeds; (5) the analyst's merge step was skipped for this question (the answer shows the two specialist sections joined), so check what the merge does with headlines.
- **Fixed later on 26 Nov (523 tests pass; backups `news_tools.v1.py`, `agent_news.v1.py`, `tests/test_news_tools.v1.py`, `tests/test_agent_news.v1.py`):** problems (1) to (3). `parse_feed` drops titles matching live-blog and price-page patterns (`_NOT_NEWS`). The prompt now asks for one tool and for `fetched_at` copied exactly. Live re-run: "Any news on TCS" 24.4 s, 1 tool call (`news_search`); "sentiment around Infosys" 19.7 s, 1 tool call (`news_sentiment`), 3 headlines, 3 positive, `fetched_at` copied correctly; "market news today" 39.7 s; analyst question 41.8 s, but the news agent there still called **both** `news_search` and `news_sentiment` (the user asked for "latest news on it"; not changed). The live-blog filter was checked by unit tests only; no live headline list was compared before and after.
- **Problem (5), merge skipped:** from the code, the merge is skipped only when the split names a single specialist (`len(answers) == 1`); that is by design. Not confirmed what the split returned in that run (split output was not logged).
- **Sources left out:** Moneycontrol (newest item April 2024), Financial Express (invalid XML), Zee Business (HTTP 403), Google News search (price-page spam and "share price prediction" pages), NSE announcements API (HTTP 301, needs a browser session). Terms of use of the five sites were **not** reviewed; robots.txt had no rule against the feed paths for ET, Moneycontrol, Mint and Business Standard (Hindu BusinessLine and NDTV Profit not checked).

### Answers given to the user this session (kept so they need not be asked again)
- **Compare TCS with Infosys today:** route `both`, research analyst, split, technical then fundamental, one merge call. **No `agent_compare` yet.** RAG is used only if the fundamental agent chooses `rag_search_documents`; INFY has no documents indexed. "Infosys" to INFY is done by the model (tools take symbols only). Traced from the code, **not run live**.
- **The two specialists ran one after the other** until the parallel option; they still do by default.
- **Which agents are built:** technical, fundamental, research analyst, portfolio manager, news. **Not built:** `agent_compare`, `prompt_enhancer`.
- **Pattern for a new agent:** a tool-calling agent (own class, own MCP server), an orchestrator (calls other agents on a shared Budget), or one with its own data. Wiring: `get_agents()`, a router word list and rule, a branch in `answer()`, tests, architecture page.

### Tracker and page notes
- **Updated later on 26 Nov:** the page now has the news agent, parallel mode and invoke lines (new section 3.7 and 5.5), the portfolio manager and guardrails as built (1, 3, 5.4, 7, 12), `portfolio` and `news` routes (3.1, 4.1, 6), 523 tests in 27 files (KPI card, 11.2), and the open items (13). Backup of the page before this edit: `...Work-Plan.v5.html`. HTML tag balance was checked by script; the page was **not rendered or viewed in a browser**. Line counts in 11.1 for the older groups are still from 21 Nov. Earlier the same day the page got section 3.6 "Compare TCS with Infosys" and the `portfolio` route in 3.1; backup `...Work-Plan.v4.html` is the copy from before that.
- Scratch scripts added: `time_parallel.py`, `live_news.py` (keep or remove; ask first).

## 1f. Done 2026-11-26 (evening): Admin Guardrails tab (tests first, 593 tests pass)

- **What it is:** Admin has a new **Guardrails** tab (between Agents and Usage log). It lists 33 built-in rows (G1 to G8 original, A1 to A7 checks that already exist in code or prompts, P1 to P18 the review) with timing, strength, state and locked, and lets the admin **add, remove and switch on or off custom rules**. Files: `guardrail_rules.py` (catalog, validation, check, prompt block), `model_settings.py` (setting `guardrails`, table `guardrail_events`, `log_guardrail_event`, `guardrail_events`, `guardrail_stats`), `ui_app.py` (`answer()` now applies the rules, `_answer()` holds the old routing, `_guardrails_panel`), prompt hook `extra_rules` on `TechnicalAgent` (so fundamental and portfolio too), `NewsAgent` and `ResearchAnalyst` (merge prompt only). Tests: `tests/test_guardrail_rules.py` (49), `tests/test_guardrail_wiring.py` (21). Backups: `ui_app.v4.py`, `model_settings.v2.py`, `agent_technical.v2.py`, `agent_news.v2.py`, `agent_research_analyst.v2.py`, `tests/test_ui_app.v4.py`.
- **Two kinds of custom rule:** *keyword* (words in the question, checked in code before routing; action block or warn; **hard** but only matches the typed words) and *prompt* (one sentence added to the agent prompts; **soft**, the model can ignore it). 30 rules at most; ids `C1`, `C2`... are never reused; applies to the next question with no restart; every change is in the Change log.
- **Built-in rows are read-only.** No on/off switch for G1 to G8, A1 to A7 or planned P rows exists yet; switches would have to be wired into each guardrail's code, one at a time. G1, G7 and G8 are marked locked.
- **Event log (review item P6, now built):** a keyword rule that fires writes a row (rule, action, 120-character question summary, session). The tab shows counts, last time and the last 50 events. Built-in portfolio rules G1 to G7 do **not** write events yet.
- **Checked:** 593 tests pass. The tab was rendered with Streamlit's test harness and its tables, checkboxes and buttons were printed back (scratch script `_probe_guardrails.py`). **Not checked:** the tab in a real browser; a prompt rule changing a real model's answer; a keyword rule on a live chat question; the analyst's split call does not get prompt rules.
- **Known limits:** a keyword rule does not understand meaning ("target price" is not caught by "price target"); the match is whole-word, case-insensitive; a blocked question is still saved in the chat history, with route `guardrail`.
- **Review of 26 Nov (18 proposed guardrails, P1 to P18):** P6 built, the other 17 are listed as planned in the tab. Order proposed: P1, P2 first (out-of-scope route and one resolver), then P3 and P5, then P4 and P7 to P10; run one-off checks for P12 (standalone or consolidated) and P13 (price gaps) before building them. Thresholds in P3, P8, P10, P11 and P14 have no data behind them and need the user's decision.

## 1d. Done 2026-11-23: portfolio feature (tests first, 369 tests pass)

Built: `guardrails.py` (G1 to G7 in plain code), `scorecard.py` (momentum, quality, valuation, risk; seven strategies), `portfolio.py` (picks one stock per industry group, equal or inverse-volatility weights held to 5% to 40%, buy-and-hold replay of the past), `mcp_portfolio.py` (4 tools: `portfolio_scorecard`, `portfolio_suggest`, `portfolio_build`, `portfolio_evaluate`), `agent_portfolio_manager.py` (`PortfolioManager`, was a one-line stub), a `PORTFOLIO` word list in `router.py` (route `portfolio`; a document word still wins), and the wiring in `ui_app.py` (welcome text and example updated; with no manager the chat says so and does not use the price agents). `live_chat.py` now also starts the portfolio server.

Checked live on `gemma4:12b` through the chat path: "Make a 5-stock low-risk portfolio" (37 s, one `portfolio_build` call, table plus the footer); "Give me 2 portfolio ideas for long term and short term" (45 s, two calls with different strategies); "Add Tesla and Infosys to my portfolio of TCS and ITC" (G1 block shown, no replay).

Facts and limits: a one-day move above 25% is treated as a split and left out of volatility and returns (14 stocks have one). TMPV (260 days) is not warned; ETERNAL, JIOFIN and SHRIRAMFIN are checked against the 252-day rule by `guardrails.py`. The scorecard ranks stocks against each other; it is not a forecast. G8 (the budget) is `budget.py`.

Found in the live runs: the model once changed the replay window to 365 and then 30 days because of the words "long term" and "short term". The prompt now says to leave `days` at 252 unless the user names a period. The model also changed Tesla to TSLA before the tool call (the tool reported it as outside the Nifty 50, so the guardrail held). Not yet checked again after the prompt change.

Not done: saving portfolios (`portfolios.sqlite` is configured but not created), rebalancing and monitoring, correlation, `agent_compare`, the prompt enhancer.

## 1c. Done 2026-11-22: Screener snapshot data and the `screener_*` tools

The user asked that prompts such as "show me NIFTY 50 Stocks with PE RSI OPM NPM" be answered from the Screener CSV snapshots in `screener-document-download/data_csv_screener/`, with tools named `screener_*` inside the fundamental agent. Built tests first.

| Area | What exists | Verified how |
|---|---|---|
| **Data copied in** | `EquityData-All-Stocks.zip` (from Downloads) copied into `data_csv_screener/`, unzipped to `EquityData-All-Stocks/` (45 files in 43 dated folders), and all 45 CSVs copied flat into `data_csv_screener/` (byte-identical). **The zip, the subfolders and the flat copies all remain: 94 MB duplicated (question below).** | `cmp` of each file |
| **Paths** | `config/paths.json`: new keys `screener_csv_dir` and `screener_duckdb`. Old copy `config/paths.v2.json`. | `test_config.py`, `test_architecture_rules.py` |
| **Loader** | `screener_db.py` builds `project-db/screener.duckdb`: Nifty 50 rows only (guardrail G1), the **last file per day wins**, a rebuild keeps the old DB under a dated name. Result: 45 files, 43 days, 50 stocks, 2,150 rows, 536 KB. Rebuild: `bin/run_py.sh screener_db.py`, then restart the app. | `test_screener.py` (19) |
| **Query class** | `screener.py`, class `Screener`: `get_table(metrics, sort_by, descending, limit, min_values, max_values, industry_group)` (at most 50 rows), `get_snapshot(symbol)`, `get_history(symbol, metric, limit)`. Aliases: pe, pb, opm, npm, gpm, roce, de, ev, fii, dii, promoter, peg, sector and others. For banks, finance companies and insurers the OPM and GPM columns, debt to equity and enterprise value are blanked with a note. An unknown metric raises `ScreenerError` with the valid list (the tool returns it as text). Every result carries the snapshot date and a "not live data" caveat. | `test_screener.py` |
| **MCP tools** | `mcp_fundamentals.py` now has **11 tools**: 7 `fsa_*`, `rag_search_documents`, and **`screener_get_table`, `screener_get_snapshot`, `screener_get_history`**. Old copy `mcp_fundamentals.v1.py`. | `test_screener.py`, live |
| **Agent** | `agent_fundamental.py`: three wrappers and one prompt paragraph (when to use the screener tools, quote the snapshot date, say a value is "-" for banks, take no number from anywhere else). Old copy `agent_fundamental.v1.py`. | `test_agent_fundamental.py` (13, 3 new) |
| **Router** | `router.py`: new `SCREENER` list (pe, opm, npm, gpm, peg, peg ratio, industry pe, holding, holdings, promoter, fii, dii, debt to equity, d/e, ev, enterprise value, eps, screener). A Screener word counts as fundamental. **Next to a Screener word, RSI and MACD are not counted as technical** (the Screener table carries them). "Revenue growth and RSI of INFY" still routes to `both`. Old copies `router.v2.py`, `router.v1.py`. | `test_router.py` (74), `test_router.v1.py` is the old one |
| **Live run** | "show me NIFTY 50 Stocks with PE RSI OPM NPM" went to `fundamental`, called `screener_get_table(metrics=['pe','rsi','opm','npm'])` and returned a 50-row table dated 2026-11-20, with "-" for bank OPM. **103 s.** The printed answer was cut at 900 characters, so rows after GRASIM were **not compared with the data**. `live_chat.py` now honours `ARPM_SHOW` (old copy `live_chat.v1.py`). | one live run |
| **Tests** | Full suite **327 passed** (23 Nov). | `pytest_full.log` |

### Facts about the Screener CSVs (measured 22 Nov)
- 45 files, 43 dates from 5 Jun to 20 Nov 2026, not daily. Gaps are mostly 1 to 6 days, with three long ones (17, 32 and 41 days). 2 Sep has two identical files. On 10 Nov the second file differs (its market-cap-based columns were re-run); the loader keeps the later one.
- 62 columns, about 5,300 to 5,550 companies per file. All 50 Nifty stocks are in every file, **including SBILIFE**, which has no Excel workbook.
- **Changes daily:** price, market cap, EV, P/E, P/B, PEG, RSI, MACD, DMAs, volume, industry P/E. **Changes only at result refreshes:** sales, profit, margins, EPS, ROCE, D/E, holdings (47 stocks changed on 16 Aug and again on 10 Nov).
- **Not in the Excel workbooks:** TTM P/E, industry P/E, PEG, ROCE, D/E, promoter, FII, DII and public holding with changes, growth, latest-quarter OPM, NPM and GPM, dividend yield, DMAs, volume.
- **CSV against the current agent:** `fsa_get_valuation` P/E (market cap over the last annual profit) differs from the CSV TTM P/E by a median of 11.8% and a maximum of 94%. Worst: TMPV (1.16 against 20.65, demerger one-off), HINDALCO (15.6 against 8.98), ADANIENT (39.8 against 114). Workbook market cap against CSV: median 1.9%, maximum 9.8%. CSV TTM sales equals the workbook's last four quarters exactly. Latest-quarter net profit differs slightly (TCS 13,934 CSV against 13,884 workbook), cause unknown. INDIGO has no P/E in the latest file.
- Spot values from tool checks: top ROCE NESTLEIND 84.14, TCS 63.03, BSE 59.99; 7 stocks with promoter holding above 60; 16 with RSI above 70; HDFCBANK FII holding 44.05 to 39.39 over 43 dates; TCS P/E range 13.69 to 16.40.

### The stuck question (23 Nov, NOT solved)
- Question: "show me NIFTY 50 PE RSI OMP NPM" (OMP is a typo for OPM). The web app showed "Working..." and never finished.
- Evidence: `runtime/logs/app.log` had no traceback. `curl` to port 8502 returned 200. Ollama `/api/ps` listed no loaded model. The Streamlit process and its two MCP children were at 0% CPU. `usage.sqlite` had **no row** for the question (newest row was an older "Compare INFY and TCS" synthesis), and `chats.sqlite` did not hold it either. So **no model call was made**, and the hang is before `gateway.chat`: agent creation, an MCP stdio call, or the Streamlit rerun and thread.
- Not yet tested: reproduce with `ARPM_SHOW=9000 bin/run_py.sh live_chat.py "show me NIFTY 50 PE RSI OMP NPM"` in the background with a log (the 23 Nov attempt was cancelled by the tool timeout before it produced output). Do not use `ui_shot.py` with a question.
- Likely fixes once found, each tests first: a "did you mean OPM" suggestion for an unknown metric, a timeout on MCP tool calls, and a visible error instead of an endless "Working...".

### Gaps seen in the screener work (not fixed)
- "Which stocks have RSI above 70" routes to `technical`, which has no all-stock RSI screen, so the screener tool is not reached.
- The model re-types a 50-row table (103 s, risk of transcription errors). A table rendered straight from the tool result in the UI would be faster and exact.
- Throwaway scripts `_probe_csv.py` and `_probe_csv2.py` are in `project-code/` (not imported by the app).

## 2. Pending (in build order)

| # | Task | Notes |
|---|---|---|
| N1 | **Finish the news agent** | **Done 26 Nov:** live-blog filter, one-tool prompt, `fetched_at` copied exactly. **Still open:** open the Admin Models tab and check the `sentiment` role is listed and editable; add a labelled headline set to measure sentiment accuracy and compare models; log the split output to see why a merge is skipped; review each site's terms of use. (The architecture page is updated, see section 1e.) Decide: should the portfolio manager or compare answers include a news line? |
| N2 | **Live run of the portfolio manager after the prompt change** | Built 23 Nov; the check that `days` stays 252 and that "2 portfolio ideas" no longer repeats stocks is not recorded. |
| G | **Guardrails: next steps** | Tab is built (section 1f). Next: open it in a browser; make built-in rows switchable one at a time (portfolio G2 to G6 first); build P1 and P2 (universe check before routing, one resolver), then P3 and P5. Ask the user to confirm thresholds. `ARPM_ADMIN_PASSWORD` is set (non-empty) in `config/arpm.env`, so Admin opens after sign-in. Earlier notes in this tracker that call it empty are out of date (checked 26 Nov; the value itself was not read). |
| N3 | **`[router]` invoke line for the single-agent routes** | Technical, fundamental and documents show no invoke line yet. |
| 0a | **Chart feature** ("generate python code and line chart for nifty 50 stocks") | Not built. Today it routes to `technical`, which has no chart tool, so the model says it cannot. Plan: `charts.py` (normalised to 100, jumps flagged), an MCP tool `chart_prices`, `st.line_chart` plus `st.code` in the UI; price file path read from config. `matplotlib` is not installed. |
| 0 | **Diagnose the stuck screener question** | See section 1c. Reproduce without touching the real chat history, find where it hangs (before `gateway.chat`), then add: fuzzy suggestions for unknown metrics, a timeout on MCP tool calls, a visible error. Tests first. Then answer "will it work for screener prompts" honestly: it works at tool level and in one live run (103 s); gaps are RSI-only routing, typos, the slow 50-row re-typing and unchecked rows after GRASIM. |
| 1 | **Tokenomics Part 2: Admin "Tokenomics" tab** | Add the tab to `render_admin()` in `ui_app.py` (now: Models, Providers, Chunking and RAG, Usage log, Change log). Show tokens and cost per day, role, model and agent (`gateway.summary`), speed, a what-if table (`tokenomics.what_if`), the call tree (`recent_sessions`, `session_calls`, `call_tree`), a daily-cap editor and a rates editor. **Write the UI tests first.** `make()` in `tests/test_ui_app.py` sets `get_gateway` to `None`, so the tests need a small fake gateway. Update `usage_rows` and the Usage log panel for the new cost columns. Restart the app after. |
| 2 | **Tokenomics Part 3: optional Langfuse tracing** | **Check the current Langfuse SDK docs first (not verified).** Plan: keys from environment variables in `config/arpm.env`, off by default, pinned in `requirements.txt`; traced inside `gateway.py` only (one generation per gateway call, the session id as the Langfuse session, nested spans for agent loops and `McpClient.call_tool()`); a privacy switch (previews only, or nothing) because document text would otherwise leave the machine; fail-safe (background sends with a timeout, chat works if Langfuse is down); tests with a fake transport; check the architecture test does not flag the SDK; compare one real trace with the `usage.sqlite` rows. |
| 3 | **Check the analyst's full answer** | Run "Is TCS a good stock to buy" again and read the whole output: "Evidence Against" and the final citations were cut off last time. Also test live the split-failure fallback and the stopped-specialist path. |
| 4 | ~~Portfolio route~~ **BUILT 23 Nov** (section 1d). `scorecard.py`, `portfolio.py`, `mcp_portfolio.py` and `agent_portfolio_manager.py` exist; the old "known defect" is probably fixed (live check: item N2). |
| 5 | **Out-of-scope refusal route** | Non-stock topics and non-Nifty stocks currently fall to `technical`. "weather in Mumbai" scores 0.63 against the 0.65 cutoff. |
| 6 | **`rag_search_documents` tool description** | Tell the model to write a full descriptive query. The single word "attrition" (`doc_type=transcript`, TCS) returned `found=False`; "employee attrition rate and hiring" scored 0.74 and found a TCS April 2023 transcript. Short queries score below the 0.65 cutoff. |
| 7 | **UI visual check** | **Top of a conversation is DONE** (`runtime/screens/conversation_top.png`, captured 20 Nov 19:15: title, user bubble, Technical and Fundamental headings, search box, Recents all render). Still to capture: the Admin view and a sidebar search with results, with `ui_shot.py` (`ARPM_TOP=1`, `ARPM_CLICK="Compare TCS vs INFY"`). The whole-file `ui_app.py` edits for the analyst also need a visual check. **Do not pass a question to `ui_shot.py`**: it writes to the real chat history. |
| 8 | ~~Update the architecture HTML~~ **DONE 2026-11-21 (evening).** Page updated with the analyst (new flow 4.7, section 5.3), tokenomics (flow 4.8, gateway section), new router rules, 293 tests, measured line counts, TMPV 260 rows, EC2 notes and the Langfuse decision. Previous copy `Nifty50-Project-Status-and-Work-Plan.v2.html`. Rendered and checked by screenshot (top, sections 3, 4.1 to 4.8). Open: optional "superseded" banner on `.v1.html` (ask first). |
| 9 | ~~Guardrails (`guardrails.py`)~~ **BUILT 23 Nov** (G1 to G7 in plain code, section 1d). G8 is `budget.py`. Open: define "one year of history" for G6 (TMPV has 260 days). |
| 10 | Prompt enhancer | `prompt_enhancer.py`. |
| 11 | `agent_compare` and multi-portfolio requests | **`agent_compare.py` does not exist.** Design in `PROMPT_CONTEXT.md` sections 5 and 9 (code ranks, the model explains, depth 3, uses `scorecard.py` directly). `scorecard.py` and the portfolio manager now exist, so it is unblocked. "Compare TCS with Infosys" meanwhile goes `both` to the analyst (section 1e). |
| 12 | Admin tab additions | Document search box, build runs, re-index with estimate and confirmation, fundamentals build info. (Usage charts and the call-tree view are item 1.) |
| 13 | CLI chat | One command to ask and see the tool trace. `live_chat.py`, `live_models.py` and `live_fundamental.py` do this today. |
| 13b | **Remaining Screener enhancements** | Make valuation answers use the CSV TTM P/E and label the source; an ownership view (the history tool exists); P/E against industry P/E and the stock's own range; a cross-check warning between CSV and workbook; router words for the rest; render a screener table directly in the UI. |
| 14 | Smaller checks | Listing test for `mcp_fundamentals.py`; price jump detector; possibly an LLM router; add 2 more TCS annual reports (`bin/rag_build_bg.sh --symbols TCS --annual-reports 5`); tune the 0.65 cutoff on more questions (measured on about 8); check table quality in annual reports; verify the 4 capex rows against their transcripts. |
| 15 | Real tests of Hugging Face and the UpGrad API | Needs UpGrad's documentation. Those adapters have run against mocked HTTP only. |

**Done and removed from this list:** RAG build, `rag_search_documents`, keyword router, fundamental agent in the chat, research analyst (was item 6), tokenomics Part 1, ChatGPT-style UI.

### Questions waiting on the user
- **`ARPM_ADMIN_PASSWORD`**: found non-empty in `config/arpm.env` on 26 Nov (value not read). Confirm with the user that it is a real password and not a placeholder.
- Add `gemma4:12b` (7.7 GB) to `config/setup.sh`? It still pulls only `mistral:7b` and `nomic-embed-text`.
- Should `prices_db.build()` keep the old DuckDB under a dated name (it overwrites today)? PID files are removed with `rm -f` (proposed: keep).
- Sector grouping for `agent_compare` (Industry Group assumed, 26 groups), and whether `compare` is a router route.
- UpGrad API documentation or an example request (base URL, model names, key).
- The portfolio decision (see item 4).
- Permission to remove the throwaway `_probe.py`, `_probe_split.py`, `_probe_csv.py` and `_probe_csv2.py` (kept under the no-delete rule).
- **New:** keep the Screener zip and the 43 dated subfolders? They duplicate the 45 flat CSVs (94 MB).
- **New:** `screener.duckdb` holds only the Nifty 50 rows (my choice, per guardrail G1). Should it hold all 5,500 companies, for sector medians?
- Which models they plan to run on EC2 (decides 32 GB versus 64 GB).
- Add the "superseded" banner to `Nifty50-Project-Status-and-Work-Plan.v1.html`?

### Smaller items (not waiting on the user)
- **Units:** workbooks state no unit. Values look like crore rupees. The agent says "probably Rs crore".
- **Mac must stay awake** and Ollama up for any index build. A stopped build resumes: `bin/rag_build_bg.sh --annual-reports 5` (finished files are skipped).
- **`bin/start_app.sh`** was checked for 10 s after start only.
- **Mixed-question reliability:** the analyst (split, run, merge) replaced the older "focus" line for the `both` route. The old open decision is closed. The split is one extra model call.
- **Scratch files** in `project-code/` (none imported by the app, none deleted): `ui_shot.py`, `live_chat.py` (builds the analyst too), `live_fundamental.py`, `live_models.py`, `rag_check.py`, `rag_check2.py`, `ui_smoke.py`, `_probe.py`, `_probe_split.py`.
- **`screener-document-download/agentic_research_portfolio_maker/`** is an old copy the app does not use. Leave it alone.
- **EC2:** no GPU on m6i, m7i or m8i. `gemma4:12b` will be slow. Test `gemma4:e4b` and embedding speed there first.
- **Price data caveat:** prices are not adjusted for splits, bonuses or demergers. 14 stocks have one-day moves over 25%.
- **Fundamentals data caveats:** SBILIFE has no workbook. Banks, finance companies and insurers have no industrial ratios. Industry groups: Banks (AXISBANK, HDFCBANK, ICICIBANK, KOTAKBANK, SBIN), Finance (BAJFINANCE, BAJAJFINSV, JIOFIN, SHRIRAMFIN), Insurance (HDFCLIFE, SBILIFE).

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

# Run all 327 tests (about 15 s; run in the background with a log if the tool call is cancelled)
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
bin/run_py.sh screener_db.py                # rebuild screener.duckdb from the CSVs (old file kept under a dated name; restart the app after)
bin/run_py.sh -c "from screener import Screener as S; import json; print(json.dumps(S().get_table(['pe','rsi'], sort_by='pe', limit=5), indent=1)[:900])"

# Price tools, no model involved
bin/run_py.sh -c "from market_data import MarketData as M; import json; print(json.dumps(M().get_indicators('INFY'), indent=1))"

# Does each model role answer?
bin/run_py.sh -c "from gateway import Gateway; g=Gateway(); print(g.test_connection('chat')); print(g.test_connection('embedding'))"

# Rebuild the price database (replaces the old file; see open questions)
bin/run_py.sh prices_db.py
```

# Restart the app (ALWAYS after a code or settings change; a running app caches old objects)
bin/stop_app.sh && bin/start_app.sh

# Screenshot of the running app (headless Chrome over the DevTools protocol). Do not pass a question.
bin/run_py.sh ui_shot.py ../runtime/screens/<name>.png        # env: ARPM_URL, ARPM_WAIT, ARPM_CLICK, ARPM_TOP

# Tokenomics numbers without the UI
bin/run_py.sh -c "from gateway import Gateway; g=Gateway(); print(g.summary('role')); print(g.spend_today()); print(g.cost_cap_state())"

Not available yet: the fix for the stuck screener question, the Admin Tokenomics tab, Langfuse tracing, guardrails, the LLM router, portfolios, out-of-scope refusal.
