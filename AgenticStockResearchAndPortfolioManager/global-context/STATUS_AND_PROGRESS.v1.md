# Status and progress: Agentic Research and Portfolio Maker

Saved 2026-11-19. Read `GLOBAL_CONTEXT.md` first for the layout, rules and architecture. This file is the task tracker:
what is done, what is pending, and what you can run on the console now.
Prompt handling (routes, example prompts, agent prompts, the multi-portfolio and compare-agent design) is in `PROMPT_CONTEXT.md`.
RAG (documents, chunking, rebuild script, Excel handling, open questions) is in `RAG_CONTEXT.md`.

Checked on 2026-11-19: **67 tests pass** (`project-code/tests/`, 7 files). Ollama is up. The Streamlit app is not built yet (`app_ui.py` is a placeholder).

## 1. Done

| Area | What exists | Verified how |
|---|---|---|
| Layout and config | `config/paths.json` is the only place paths are written. `project-code/config.py` reads it. `bin/*.sh` start and stop Ollama and the app. `config/setup.sh` is written. `config/arpm.env` was created from the example (Ollama URL only; admin password still empty). | `test_config.py`, `test_architecture_rules.py` (no hard-coded paths, only `providers.py` talks to models) |
| Provider adapters | `providers.py`: Ollama, OpenAI-compatible, Hugging Face. | Ollama live. The other two with mocked HTTP only. |
| Model settings | `model_settings.py`: per-role provider and model, chunking and retrieval values, audit log. **Defaults: chat `gemma4:12b` (think off), router `mistral:7b`, embedding `nomic-embed-text`, summary `mistral:7b`, judge `gemma4:12b`.** | `test_gateway.py` |
| AI gateway | `gateway.py`: role-based chat and embed, retry once, usage log with tokens and tokens per second, `test_connection`. | `test_gateway.py`, live |
| Price database | `prices_db.py`: builds `project-db/arpm.duckdb` from the CSVs. 55,167 rows after removing 2,600 exact duplicates. 23 Mar 2022 to 13 Nov 2026. | `test_prices_db.py` |
| Indicators | `indicators.py`: SMA, EMA, RSI, MACD, Bollinger, ATR, returns, 52-week high and low. SMA(20) for TCS checked independently: 2477.135. | `test_indicators.py` |
| Market data tools | `market_data.py` (9 tools) and `mcp_market_data.py` (the MCP server). | `test_market_data.py`, live over stdio |
| MCP client | `mcp_client.py`: starts an MCP server as a child process and calls its tools. | `test_agent_technical.py`, live |
| Budgets | `budget.py`: shared limits for model calls, tool calls, tokens and agent depth (max 3). | `test_agent_technical.py` |
| Technical agent | `agent_technical.py`: nine LangChain `@tool` functions that call the MCP server, run by LangGraph `ToolNode`. Calls the model only through the gateway. An answer with no tool call is rejected once, then replaced by a "no tool data" message. | Scripted tests, plus live runs on `gemma4:12b`, `gemma4:e4b` |

### Model comparison (19 Nov 2026, M1 Pro, one run each)
| Model | Uses tools? | Result |
|---|---|---|
| `gemma4:12b` | Yes | Correct numbers, 10 to 34 s per question. **Chosen as chat default.** |
| `gemma4:e4b` | Yes | Correct, 28 to 50 s |
| `mistral:7b` | No (0 of 4 questions) | Wrote placeholders and invented numbers before the no-tool-call rule was added. Now always ends in "no tool data". Kept for router and summary only. |
| `phi4-mini` | No | Printed the tool JSON as text |

## 2. Pending (in build order)

| # | Task | Notes |
|---|---|---|
| 1 | **CLI chat** | One command to ask `agent_technical` questions and see the tool trace and token budget. Not written. |
| 2 | Guardrails (`guardrails.py`) | G1 to G8 from `GLOBAL_CONTEXT.md`. G8 limits already exist in `budget.py`. Define "one year of history" for G6 (TMPV has 260 days). |
| 2b | `agent_compare` and multi-portfolio requests (added 2026-11-19, not built) | When a portfolio has 2+ stocks in one sector, code ranks them and the agent explains the winner. Design and open questions in `PROMPT_CONTEXT.md` sections 5 and 9. Needs `scorecard.py` and the portfolio manager first. |
| 3 | Fundamentals data and tools | Excel to DuckDB, `mcp_fundamentals.py`, `agent_fundamental.py` (still a stub). |
| 4 | Document RAG | Chroma, chunking, embeddings through the gateway, tiers 1 to 3, `search_documents` tool. |
| 5 | Prompt enhancer, router, Chat tab | `prompt_enhancer.py`, `router.py`, replace the placeholder `app_ui.py`. Router on `mistral:7b` is untested. |
| 6 | Research analyst | `scorecard.py` (code only) and `agent_research_analyst.py` (stub). |
| 7 | Portfolio manager | `mcp_portfolio.py` and `agent_portfolio_manager.py` (stub). |
| 8 | Admin tab | Usage charts, Model settings, re-index with confirmation, audit log. Needs `ARPM_ADMIN_PASSWORD`. |
| 9 | Gateway: parent call ID for the call tree | The gateway already stores `parent_id`. The Admin tab view is not built. |

### Smaller items and open questions
- **`config/setup.sh`** still pulls only `mistral:7b` and `nomic-embed-text`. It needs `gemma4:12b` added for the new chat default, or a fresh VM will fail. **Waiting on your answer** (a 7.7 GB download).
- **Leftovers in `screener-document-download/`:** the old `agentic_research_portfolio_maker/`, `.venv/` (475 MB) and `requirements.txt`. **Decided: keep them** (no-delete rule in `GLOBAL_CONTEXT.md`). They are marked superseded.
- **No-delete rule (2026-11-19):** nothing in this project folder is deleted. Newer versions are added beside the old ones. Three places in the current code still overwrite or remove files (`prices_db.build()` replaces the DuckDB file; PID files are removed with `rm -f`; SQLite rows are updated). **Waiting on your answer** on whether to change them. Details in the rule section.
- **Architecture HTML:** still missing eight areas from the old plan (router examples, portfolio tool table, guardrail alert examples, gateway detail, Admin tab detail, local setup table, "done when" criteria, some confirm-list items). **Waiting on your answer** about merging them. It also has stale numbers (see GLOBAL_CONTEXT change log).
- **UpGrad API:** documentation or an example request is still needed. The external provider is a generic OpenAI-compatible adapter, never run against a real service.
- **EC2:** no GPU on m6i/m7i/m8i. `gemma4:12b` will be slow on CPU. Test `gemma4:e4b` there before deciding.
- **`project-code/live_models.py`:** a scratch script that runs the technical agent on one model. Kept at your request. Usage: `bin/run_py.sh live_models.py <model> "<question>"`.
- **Price data caveat:** prices are not adjusted for splits, bonuses or demergers. 14 stocks have one-day moves over 25%.

## 3. What you can try on the console now

Run these from the project root (`AgenticStockResearchAndPortfolioManager/`). `bin/run_py.sh` loads `config/arpm.env` and uses the venv Python.

```bash
# Is everything up? (Ollama up, app DOWN is expected: the app is not built)
bin/status.sh

# Run all 67 tests
cd project-code && .venv/bin/python -m pytest tests -q -p no:cacheprovider -W ignore && cd ..

# Where do paths come from?
bin/run_py.sh config.py show

# Price tools, no model involved
bin/run_py.sh -c "from market_data import MarketData as M; import json; m=M(); print(json.dumps(m.get_latest_quote('TCS'), indent=1))"
bin/run_py.sh -c "from market_data import MarketData as M; import json; print(json.dumps(M().get_indicators('INFY'), indent=1))"
bin/run_py.sh -c "from market_data import MarketData as M; import json; print(json.dumps(M().top_movers('1M', 3), indent=1))"
bin/run_py.sh -c "from market_data import MarketData as M; import json; print(json.dumps(M().compare_stocks(['TCS','INFY']), indent=1))"

# Does each model role answer? (a tiny call each)
bin/run_py.sh -c "from gateway import Gateway; g=Gateway(); print(g.test_connection('chat')); print(g.test_connection('embedding'))"

# Current model per role
bin/run_py.sh -c "from model_settings import SettingsStore as S; [print(r.role, r.provider, r.model, r.params) for r in S().list_roles()]"

# Ask the technical agent (uses gemma4:12b; takes 10 to 35 s)
bin/run_py.sh live_models.py gemma4:12b "How is TCS doing technically?" "Compare INFY and HCLTECH" "What about Apple stock?"

# Try another model on the same questions
bin/run_py.sh live_models.py gemma4:e4b "What is the RSI of ITC?"

# The last model calls: agent, model, tokens in, tokens out, tokens per second
bin/run_py.sh -c "from gateway import Gateway; [print(r['agent'], r['model'], r['tokens_in'], r['tokens_out'], r['tokens_per_s']) for r in Gateway().usage_rows(5)]"

# Rebuild the price database from the CSVs (about 1 s)
bin/run_py.sh prices_db.py
```

Not available yet: a chat prompt, the web app, fundamentals, document search, guardrails, the router, portfolios and the Admin tab.
