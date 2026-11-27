# Status and progress: Agentic Research and Portfolio Maker

Updated 2026-11-21 (00:20 IST). Previous versions kept as `STATUS_AND_PROGRESS.v1.md` to `.v7.md` (no-delete rule).
Read `GLOBAL_CONTEXT.md` first for the layout, rules and architecture. This file is the task tracker:
what is done, what is pending, and what you can run on the console now.
Prompt handling (routes, example prompts, agent prompts, the multi-portfolio and compare-agent design) is in `PROMPT_CONTEXT.md`.
RAG (documents, chunking, build script, measured numbers, Excel findings, open questions) is in `RAG_CONTEXT.md`.

**State at 2026-11-21 00:20 IST:** **293 tests pass** (`project-code/tests/`, 20 files; run again at 00:20). Ollama is up. The web app runs at **http://127.0.0.1:8502** (restarted about 22:38 the evening before; it answers 200). It has a ChatGPT-style chat (saved conversations, sidebar search) and an Admin view.
**Start here next session:** section 2 "Pending", item 1 (Admin Tokenomics tab). The order of work is in that table.
**Built since the last update (2026-11-20 14:00 to 2026-11-21 00:00):** ChatGPT-style chat UI with saved conversations (`chat_store.py`, `chats_db`); keyword-router additions (conference-call wordings, capex, guidance, order book, attrition, a `RESEARCH` list); **research analyst** (`agent_research_analyst.py`, runs for the `both` route); **tokenomics Part 1** (cost in the gateway, rates, daily cap, `tokenomics.py`); architecture HTML rewritten (15 sections); EC2 sizing answered; Langfuse decision. Details in section 1b.
**Architecture HTML updated 2026-11-21 evening** (see pending item 8).
**Not built yet:** Admin Tokenomics tab (Part 2), optional Langfuse tracing (Part 3), portfolio manager, guardrails G1 to G7, prompt enhancer, out-of-scope refusal, compare agent.
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
| **Router (2026-11-20; extended, see 1b)** | `router.py`: plain keyword code, **no model call**. Routes: `technical`, `fundamental`, `both` (a financial word and a price word), `documents` (annual report, transcript, presentation, earnings call...). Documents win over everything. No keyword goes to `technical`. Whole-word matching. Phrases such as "price to book" and "return on equity" are removed before the technical check. The planned LLM router (role `router`, `mistral:7b`, untested) can replace `route()` later with no change to callers. | `test_router.py` (62 now) |
| **Mixed-question focus (NEW 2026-11-20)** | `TechnicalAgent.run(..., focus="")` appends one rule line to the system prompt. For `both`, `ui_app.answer()` tells each agent to answer only its half. Single-route questions pass no focus. | `test_ui_app.py`; live: partly works, see "Known weakness" in pending 3 |
| **Document questions (CHANGED 2026-11-20 11:50)** | The `documents` route now runs `agent_fundamental` with `rag_search_documents`. The fixed "not connected" reply was removed from `ui_app.py`. | `test_ui_app.py::test_document_question_goes_to_the_fundamental_agent`; live on `gemma4:12b` |
| **Fundamentals database** | `fundamentals_db.py` reads the 49 Excel workbooks (`Data Sheet`) into `project-db/fundamentals.duckdb`: tables `fin_values(symbol, section, label, period_end, value)`, `fin_meta`, `build_info`. **49 stocks, 20,747 values**, SBILIFE missing, no duplicate keys. A rebuild renames the old file to a dated name. The two `Total` rows become `Total liabilities` and `Total assets`. Run: `bin/run_py.sh fundamentals_db.py`. | `test_fundamentals_db.py` (8) |
| **Fundamentals tools** | `fundamentals.py` (`Fundamentals` class: `company_type`, `coverage`, `list_line_items`, `get_financials`, `get_quarterly`, `compute_growth`, `compute_ratios`, `get_valuation`) and `mcp_fundamentals.py` (7 numeric MCP tools (8 with `rag_search_documents`), calls run under a lock). Banks, finance companies and insurers get a warning and no operating margin, interest cover, debt to equity or EV to sales. Operating margin = `(PBT + depreciation + interest - other income) / sales`, checked against the workbook's own Operating Profit for TCS. | `test_fundamentals.py` (15); direct call; live through the agent |
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

## 2. Pending (in build order)

| # | Task | Notes |
|---|---|---|
| 1 | **Tokenomics Part 2: Admin "Tokenomics" tab** | Add the tab to `render_admin()` in `ui_app.py` (now: Models, Providers, Chunking and RAG, Usage log, Change log). Show tokens and cost per day, role, model and agent (`gateway.summary`), speed, a what-if table (`tokenomics.what_if`), the call tree (`recent_sessions`, `session_calls`, `call_tree`), a daily-cap editor and a rates editor. **Write the UI tests first.** `make()` in `tests/test_ui_app.py` sets `get_gateway` to `None`, so the tests need a small fake gateway. Update `usage_rows` and the Usage log panel for the new cost columns. Restart the app after. |
| 2 | **Tokenomics Part 3: optional Langfuse tracing** | **Check the current Langfuse SDK docs first (not verified).** Plan: keys from environment variables in `config/arpm.env`, off by default, pinned in `requirements.txt`; traced inside `gateway.py` only (one generation per gateway call, the session id as the Langfuse session, nested spans for agent loops and `McpClient.call_tool()`); a privacy switch (previews only, or nothing) because document text would otherwise leave the machine; fail-safe (background sends with a timeout, chat works if Langfuse is down); tests with a fake transport; check the architecture test does not flag the SDK; compare one real trace with the `usage.sqlite` rows. |
| 3 | **Check the analyst's full answer** | Run "Is TCS a good stock to buy" again and read the whole output: "Evidence Against" and the final citations were cut off last time. Also test live the split-failure fallback and the stopped-specialist path. |
| 4 | **Portfolio route** | First a plain "portfolio building is not connected yet" reply, so the false "strong fundamentals" claim stops. Then `scorecard.py`, `mcp_portfolio.py` and a real `agent_portfolio_manager` (now a one-line stub). **Known defect:** "Give me 2 portfolio ideas for long term and short term" goes to the technical agent and repeats stocks. |
| 5 | **Out-of-scope refusal route** | Non-stock topics and non-Nifty stocks currently fall to `technical`. "weather in Mumbai" scores 0.63 against the 0.65 cutoff. |
| 6 | **`rag_search_documents` tool description** | Tell the model to write a full descriptive query. The single word "attrition" (`doc_type=transcript`, TCS) returned `found=False`; "employee attrition rate and hiring" scored 0.74 and found a TCS April 2023 transcript. Short queries score below the 0.65 cutoff. |
| 7 | **UI visual check** | **Top of a conversation is DONE** (`runtime/screens/conversation_top.png`, captured 20 Nov 19:15: title, user bubble, Technical and Fundamental headings, search box, Recents all render). Still to capture: the Admin view and a sidebar search with results, with `ui_shot.py` (`ARPM_TOP=1`, `ARPM_CLICK="Compare TCS vs INFY"`). The whole-file `ui_app.py` edits for the analyst also need a visual check. **Do not pass a question to `ui_shot.py`**: it writes to the real chat history. |
| 8 | ~~Update the architecture HTML~~ **DONE 2026-11-21 (evening).** Page updated with the analyst (new flow 4.7, section 5.3), tokenomics (flow 4.8, gateway section), new router rules, 293 tests, measured line counts, TMPV 260 rows, EC2 notes and the Langfuse decision. Previous copy `Nifty50-Project-Status-and-Work-Plan.v2.html`. Rendered and checked by screenshot (top, sections 3, 4.1 to 4.8). Open: optional "superseded" banner on `.v1.html` (ask first). |
| 9 | Guardrails (`guardrails.py`) | G1 to G7. G8 is built (`budget.py`). Define "one year of history" for G6 (TMPV has 260 days). |
| 10 | Prompt enhancer | `prompt_enhancer.py`. |
| 11 | `agent_compare` and multi-portfolio requests | Design in `PROMPT_CONTEXT.md` sections 5 and 9. Needs `scorecard.py` and the portfolio manager first. |
| 12 | Admin tab additions | Document search box, build runs, re-index with estimate and confirmation, fundamentals build info. (Usage charts and the call-tree view are item 1.) |
| 13 | CLI chat | One command to ask and see the tool trace. `live_chat.py`, `live_models.py` and `live_fundamental.py` do this today. |
| 14 | Smaller checks | Listing test for `mcp_fundamentals.py`; price jump detector; possibly an LLM router; add 2 more TCS annual reports (`bin/rag_build_bg.sh --symbols TCS --annual-reports 5`); tune the 0.65 cutoff on more questions (measured on about 8); check table quality in annual reports; verify the 4 capex rows against their transcripts. |
| 15 | Real tests of Hugging Face and the UpGrad API | Needs UpGrad's documentation. Those adapters have run against mocked HTTP only. |

**Done and removed from this list:** RAG build, `rag_search_documents`, keyword router, fundamental agent in the chat, research analyst (was item 6), tokenomics Part 1, ChatGPT-style UI.

### Questions waiting on the user
- A real **`ARPM_ADMIN_PASSWORD`** (empty in `config/arpm.env`, so the Admin view is locked).
- Add `gemma4:12b` (7.7 GB) to `config/setup.sh`? It still pulls only `mistral:7b` and `nomic-embed-text`.
- Should `prices_db.build()` keep the old DuckDB under a dated name (it overwrites today)? PID files are removed with `rm -f` (proposed: keep).
- Sector grouping for `agent_compare` (Industry Group assumed, 26 groups), and whether `compare` is a router route.
- UpGrad API documentation or an example request (base URL, model names, key).
- The portfolio decision (see item 4).
- Permission to remove the throwaway `_probe.py` and `_probe_split.py` (kept under the no-delete rule).
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

# Run all 293 tests (about 13 s; run in the background with a log if the tool call is cancelled)
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

# Restart the app (ALWAYS after a code or settings change; a running app caches old objects)
bin/stop_app.sh && bin/start_app.sh

# Screenshot of the running app (headless Chrome over the DevTools protocol). Do not pass a question.
bin/run_py.sh ui_shot.py ../runtime/screens/<name>.png        # env: ARPM_URL, ARPM_WAIT, ARPM_CLICK, ARPM_TOP

# Tokenomics numbers without the UI
bin/run_py.sh -c "from gateway import Gateway; g=Gateway(); print(g.summary('role')); print(g.spend_today()); print(g.cost_cap_state())"

Not available yet: the Admin Tokenomics tab, Langfuse tracing, guardrails, the LLM router, portfolios, out-of-scope refusal.
