# Prompt context: how user prompts and agent prompts are handled

Saved 2026-11-19, updated 2026-11-21 (00:30 IST; old versions `PROMPT_CONTEXT.v1.md` to `.v6.md`). Companion to `GLOBAL_CONTEXT.md` (architecture) and `STATUS_AND_PROGRESS.md` (tracker).
This file covers what the user types, how it is understood and routed, and the prompts the agents use.

**Legend:** BUILT = code exists and is tested. PLANNED = agreed in discussion, no code yet. ASSUMED = my default, not yet confirmed by the user.

## 1. Prompt flow (one user message)

```
user message
  -> prompt_enhancer   (PLANNED, mostly plain code)
  -> guardrails        (PLANNED, plain code: G1 to G8)
  -> router            (BUILT as plain keyword code, no model call; an LLM router is PLANNED)
  -> agent(s)          (technical, fundamental, research analyst BUILT; portfolio, compare PLANNED)
  -> synthesizer       (PLANNED, adds sources, data date, disclaimer G7)
```

Rules that apply to every step:
- Callers name a model **role** (`chat`, `router`, `embedding`, `summary`, `judge`) to the gateway, never a provider or model.
- Numbers come from tools (SQL or Python), never from the model or from vector similarity.
- Only Nifty 50 stocks are covered.
- The logs keep a preview of the question (80 characters), not the full text, unless full logging is turned on (default: previews only, ASSUMED).

## 2. Prompt enhancer (PLANNED)

Slim, mostly plain code. No generic LLM rewriting of the user's words.

| Step | How | LLM? |
|---|---|---|
| Resolve names to symbols ("Infosys" to INFY, "Tata Motors" to TMPV) using `Reference-Files/nifty-50.csv` | code | no |
| Resolve dates ("last month", "this year") against the latest data date, not today's date | code | no |
| Follow-up with no symbol ("and its RSI?") | rewrite using the previous turn's symbol | one call, only in this case |
| Missing or unclear symbol or portfolio size | ask a clarifying question, do not guess | no |
| Unknown company (Tesla, Apple) | pass to guardrail G1, which blocks it | no |

## 3. Routes (PLANNED, from the Phase 1 design plus later additions)

| Route | Meaning | Example prompt | Tools or agent |
|---|---|---|---|
| `technical` | Price, trend, indicators | "Latest price and 52-week range of TCS" | `agent_technical` (BUILT): `get_latest_quote`, `get_52w_high_low` |
| `fundamental` | Financials and documents | "Five-year revenue CAGR of Asian Paints"; "Key risks in the latest Reliance annual report" | `agent_fundamental`: financials tools, `rag_search_documents` |
| `research` | Combined view, "should I invest" | "Give me a research view on INFY" | `agent_research_analyst` (BUILT; reached today through the `both` route) |
| `portfolio` | Build, check or rebalance a portfolio | "Make a 5-stock low-risk portfolio and show its drawdown" | `agent_portfolio_manager` |
| `compare` | Head-to-head between stocks (ASSUMED) | "Compare INFY and TCS" | `agent_compare` |
| `both` | Technical and fundamental in parallel | "Which stocks have rising revenue but falling price?" | both agents |
| `out_of_scope` | Not the Nifty 50, or not about stocks | "Add Tesla to my portfolio" | guardrail G1 reply, no agent call |

**BUILT 2026-11-20 (keyword version): `project-code/router.py`.** Plain code, no model call. It returns `technical`, `fundamental`, `both` or `documents`. `documents` (annual report, transcript, presentation, earnings call, management said...) wins over everything and runs `agent_fundamental`, which has `rag_search_documents` (changed 2026-11-20 11:50; the fixed "not connected" reply is gone). A comparison word (`compare`, `versus`, `vs`, `which is better`) with no price or financial word is `both`. A question with both a financial word and a price word is `both`: both agents run and each answer is labelled. A question with no keyword goes to `technical`. Whole-word matching; phrases such as "price to book" and "return on equity" are not counted as price words. 19 tests in `test_router.py`. `portfolio`, `compare` and `out_of_scope` routes do not exist yet. (`research` is not a separate label: open requests go to `both`, which runs the analyst.)

**Router additions 2026-11-20/21 (62 tests):**
- Spoken and plural forms of "conference call" count as `documents` words: con call(s), con-call, concalls, earnings calls, analyst call(s).
- Topic words that live in calls and reports count as `documents` words: capex, capital expenditure, guidance, order book, attrition.
- A **`RESEARCH` list** for open requests: research, analyse, full analysis, tell me about, how is, should I invest, undervalued, cheap, pros and cons, what do you think, summary of, and similar. It fires only when the question has no fundamental or technical word, and sends it to `both`.
- Side effect: "tell me about" now routes to `both`. A word-boundary test was reworded to "pricey salesmen are everywhere".
- Why "Is TCS a good stock to buy" first seemed not to run the analyst: before the RESEARCH list, open questions such as "How is TCS doing?" went to the technical agent alone. Now it shows `Route: research` and about 8 model calls in the tools box.
- **Which prompts run the analyst:** any question routed `both`: a financial word plus a price word ("Revenue growth and RSI of ITC"), a comparison with no domain word ("Compare TCS and INFY"), or an open request ("Is TCS a good stock to buy", "Should I invest in INFY", "Tell me about RELIANCE").

**Superseded 2026-11-21: for `both`, `ui_app.answer()` now calls the research analyst (section 6.3a), which splits the question with one model call. The older text follows.** For `both`, `ui_app.answer()` passes each agent a one-line `focus` rule ("answer only the price part" or "only the financial-statement part"). **Known weakness:** the fundamental agent often replies "no tool data" when the question also mentions RSI (3 of 8 probes called a tool). Options not yet chosen: one model call to split the question into two clauses; plain-code splitting at "and"; or ask users to ask one thing at a time.

**Planned LLM router:** one call at temperature 0 on the `router` role (default `mistral:7b`). **Quality on `mistral:7b` has not been tested.** `mistral:7b` failed at tool calling in live tests, so test routing before relying on it. The fallback is `gemma4:12b`. It can replace `route()` with no change to callers.

## 4. Prompts the app must handle

### 4.1 Single-stock questions (BUILT for technical)
| Prompt | Result today |
|---|---|
| "How is TCS doing technically?" | Calls `get_latest_quote` and `get_indicators`. Answer cites the close, SMAs, RSI, MACD and the data date. |
| "Compare INFY and HCLTECH" | Calls `compare_stocks` once. |
| "What is the RSI of ITC?" | Calls `get_indicators`. Checked live: 66.47. |
| "What about Apple stock?" | Calls `get_latest_quote`, gets "not one of the Nifty 50", and says so. No numbers invented. |

### 4.2 Portfolio prompts (PLANNED)
| Prompt | Expected behaviour |
|---|---|
| "Build a 5-stock low-risk portfolio" | Score all 50 by code, pick 5, resolve sector clashes, show weights, risk, data date, disclaimer. |
| "Build a portfolio of 8 stocks" | Blocked by **G2**: "A portfolio can hold 4 to 6 stocks. You asked for 8. Choose up to 6, or I can pick the top 6." |
| "Build a portfolio of 3 stocks" | Blocked by **G3** (ASSUMED): fewer than 4. |
| "Add Tesla and Infosys to my portfolio" | **G1**: "Tesla is not in the Nifty 50. This app covers only the 50 Nifty 50 stocks." Infosys is accepted. |
| "Give me 4 different portfolio ideas, 4 to 6 stocks each" | See section 5. |
| "Put 60% in banks" | **G5** warning: more than 50% in one sector. |
| A portfolio that includes TMPV | **G6** warning: under one year of price history. TMPV has 260 trading days (checked in DuckDB), so whether it triggers depends on how the code defines "one year" (252 or 260 days, or calendar dates). Decide this when `guardrails.py` is written. |

### 4.3 Out-of-scope and unsafe prompts (PLANNED)
- Non-Nifty 50 stock, crypto, mutual funds, a stock not in the list: G1, polite refusal, offer the nearest Nifty 50 option.
- "Will TCS go up tomorrow?" or "Guarantee me returns": no forecast promises. Answer with evidence for and against, and the G7 disclaimer.
- "Buy" or "sell" instructions: the app describes evidence, it does not give personal investment advice.

## 5. Multi-portfolio prompts and the compare agent (PLANNED, ASSUMED)

Example: "Give me 4 different portfolio ideas, with 4 to 6 stocks in each."

| Step | Who | LLM calls |
|---|---|---|
| 1. Read the request: 4 portfolios, 4 to 6 stocks each | prompt enhancer, router | 0 to 1 |
| 2. Score all 50 stocks once | `scorecard.py` (code only) | 0 |
| 3. Build 4 candidate portfolios by weighting the same scores differently | code | 0 |
| 4. Where a portfolio holds two or more stocks from one sector, pick one | `agent_compare` | about 1 per unique conflict |
| 5. Check each portfolio against the guardrails | `guardrails.py` | 0 |
| 6. Write one short rationale per portfolio | `agent_portfolio_manager` | 4 |

Design decisions (ASSUMED, to confirm):
- **Each portfolio is a strategy**: momentum, low risk, quality and valuation (once fundamentals exist), balanced. Otherwise the four lists are near copies.
- **Overlap limit**: any two portfolios share at most 3 stocks. If not possible, say so.
- **Size**: the manager picks 4, 5 or 6 per portfolio; an explicit "exactly 5 each" overrides it.
- **Cap**: at most 5 portfolios per request (each adds model calls).
- **Sector grouping** for the compare trigger is the Industry Group (26 groups). 13 groups have two or more stocks: Banks 5, Automobiles 5, Finance 4, IT - Software 4, Pharma 3, and eight groups with 2. The user has not confirmed this choice. The alternative is the finer Industry column (for example "Private Sector Bank" vs "Public Sector Bank").
- **Code picks the winner, the model writes the reason.** Close score gaps are labelled a close call. Pairs that are not like-for-like are flagged (NTPC generates power, POWERGRID transmits it; SBIN is public sector, the other four banks are private).
- **Depth**: `agent_portfolio_manager` -> `agent_compare` -> `agent_technical` / `agent_fundamental` is exactly depth 3. `agent_compare` must not call `agent_research_analyst`; it uses `scorecard.py` directly.
- **Cache** compare results per sector group, candidate set, strategy and data date.
- **Budget**: the default per-request limits (12 model calls, 40,000 tokens) are too small. Use a budget per portfolio with an overall ceiling.
- **Time** (estimate, not measured): about 1.5 to 3 minutes locally on `gemma4:12b`, slower on EC2 CPU. Show progress as each portfolio finishes.
- Until fundamentals exist, strategies use price factors only, and the output says so.
- If the user names their own two stocks from one sector, ask whether they want both. Do not drop one silently.

## 6. Agent system prompts

### 6.1 `agent_technical` (BUILT, in `project-code/agent_technical.py`)
```
You are the technical analysis agent in a Nifty 50 research app.
Rules:
- Use the tools to get every number. Never quote a price, return or indicator you did not get from a tool.
- Only Nifty 50 stocks are covered. If a tool says a stock is not covered, say so plainly.
- Call only the tools you need. Usually one to three calls are enough.
- State the data date (as_of) once. If a tool returns a caveat or note, pass it on in one short sentence.
- Describe what the indicators show (trend, momentum, volatility). Do not promise returns. Do not say buy or sell.
- Keep the answer short: a few lines or a small list, not an essay.
```
Enforced in code, not only by the prompt:
- If the model answers with no tool call, the agent sends one reminder ("You must call at least one tool to get the data before you answer. Do not write numbers from memory or placeholders. Call the right tool now."). A second no-tool answer is replaced by: "I have no tool data for this question, so I will not guess numbers. Try naming one of the Nifty 50 stocks, for example: 'How is TCS doing technically?'"
- Tool arguments are validated by LangGraph `ToolNode`. A bad argument or an unknown tool goes back to the model as an error message.
- The shared `Budget` stops the loop at the model-call, tool-call and token limits and at agent depth 3.

### 6.2 `agent_fundamental` (BUILT 2026-11-20, in `project-code/agent_fundamental.py`)
Subclass of `TechnicalAgent`: same loop, own tools (7 wrappers over `mcp_fundamentals.py`), own prompt. The prompt says:
- Use the tools for every number. Never quote a sales, profit, ratio or valuation figure you did not get from a tool.
- Only Nifty 50. SBILIFE has no workbook: say its statements are missing.
- The workbooks state no unit: say "in the workbook's units (probably Rs crore)" once when quoting amounts. Ratios and growth are percentages.
- Banks, finance companies and insurers: no operating margin, interest cover or debt to equity. Pass on the tool's warning.
- Which tool for what: `fsa_get_financials` (lines), `fsa_get_quarterly`, `fsa_compute_growth` (growth and CAGR), `fsa_compute_ratios` (margins, ROE, ROA), `fsa_get_valuation` (P/E, price to book, market cap), `fsa_list_line_items` when unsure of names.
- For several stocks, call the tool once per stock and show the results side by side.
- For "how did X grow over N years": quote `start_value`, `end_value` and `cagr_pct` from `fsa_compute_growth` with `years=N`. Use `years=1` only for year-on-year. (Added after the model reported five year-on-year rows as 5-year growth.)
- No buy or sell, no predictions. For risks, strategy, management comments, outlook or reasons: call `rag_search_documents` (symbol, and doc_type when named); cite file and page for each point; take no number from it; if `found=false`, say no passage was found. ITC and TRENT have no transcripts, BAJAJ-AUTO no presentations, INFY no documents. News is not available. **Updated 2026-11-20 11:50 when `rag_search_documents` was added (8 tools).**
- Short answers.
Same code rules as 6.1 (reminder, "no tool data" refusal, `ToolNode` argument checks, shared `Budget`). Gateway role `chat`, agent name `agent_fundamental`, route label `fundamental`.

Live results on `gemma4:12b` are in `STATUS_AND_PROGRESS.md` (7 questions, all answered correctly or declined correctly).

### 6.3a `agent_research_analyst` (BUILT 2026-11-21, in `project-code/agent_research_analyst.py`)
No tools of its own. Two prompts, both on the `chat` role:
1. **Split prompt:** cut the question into a technical part (price, trend, indicators) and a fundamental part (growth, margins, ROE, valuation, and what documents say), and return JSON (fenced JSON is accepted). It asks the fundamental half to cover growth, margins, ROE, valuation and documents (added after the TCS answer was thin). If the JSON is unreadable, both agents get the whole question plus the "answer only your half" note.
2. **Merge prompt:** write one answer from the two specialist answers. It must not add numbers or citations the specialists did not give. For "should I buy" questions it states that it cannot advise, then lists evidence for and evidence against (added after the answer ignored the buy question).

Enforced in code: a number in the merged answer that no specialist gave makes it fall back to the two labelled specialist answers plus a note; `strip_unsupported_citations` removes bracketed page citations no specialist gave (the answer had shown "(Technical Analyst, p. 1)"); one specialist failing or being stopped by the budget does not stop the other; if only one part is needed, that specialist's answer is returned with no merge call. One shared budget: 24 model calls, 40 tool calls, 80,000 tokens. Live times on `gemma4:12b`: 59 s, 82 s, 136 s.

### 6.3 Other agents (PLANNED, wording not written)
| Agent | Prompt must say |
|---|---|
| `agent_fundamental` (when `rag_search_documents` exists) | Cite the document and page for every claim from `rag_search_documents`. Say when a stock has no transcript (ITC and TRENT no transcripts; BAJAJ-AUTO no presentations; INFY has no PDFs). |
| `agent_research_analyst` (scorecard version, later) | Write prose around numbers computed by `scorecard.py`. Give evidence for and against. No buy or sell verdict. Always add the G7 disclaimer. (The built version is section 6.3a and does not use a scorecard.) |
| `agent_compare` | Take the code ranking as given. Explain the winner in a few lines. Name the deciding factor. Label a close call. Flag non-like-for-like pairs. |
| `agent_portfolio_manager` | Use tool outputs for weights, risk and drawdown. Show each guardrail alert. Respect 4 to 6 stocks, 5% to 40% weights. |
| Router | Return one route name from the list in section 3 and nothing else. Temperature 0. |
| Synthesizer | Combine agent outputs, keep sources and the data date, add the G7 disclaimer and the unadjusted-price note. |

## 7. Guardrail wording (PLANNED, from the Phase 1 design)
| ID | Rule | Action |
|---|---|---|
| G1 | Nifty 50 only | Block |
| G2 | 7 or more stocks in a portfolio | Block |
| G3 | Fewer than 4 stocks (ASSUMED) | Block |
| G4 | Weights sum to 100%, each 5% to 40% (ASSUMED) | Block |
| G5 | More than 50% in one sector | Warn |
| G6 | Under 1 year of price history | Warn |
| G7 | Disclaimer, data date, unadjusted-price note on every answer | Always |
| G8 | Per-request limits on model calls, tool calls, tokens, depth | Stop. Budget part is BUILT in `budget.py`. |

## 8. Model choice per prompt role (BUILT, in `model_settings.py`)
| Role | Default | Why |
|---|---|---|
| chat (agents) | `gemma4:12b`, think off | Only models that called tools correctly in live tests: `gemma4:12b` and `gemma4:e4b`. `mistral:7b` and `phi4-mini` did not. |
| router | `mistral:7b`, temperature 0 | Faster. Untested for routing. |
| summary | `mistral:7b` | No tool calling needed. |
| judge | `gemma4:12b`, think off, temperature 0 | Should differ from the model that wrote the answer; warn if the same. |
| embedding | `nomic-embed-text` | 768 dimensions. |

## 9. Open prompt questions
1. Sector grouping for `agent_compare`: Industry Group (assumed) or the finer Industry.
2. Whether `compare` is a router route for user questions, or used only inside portfolio building.
3. Overlap limit between portfolios (assumed 3), and the cap of 5 portfolios per request.
4. Whether a "buy or sell" question gets a refusal or an evidence summary (assumed: evidence summary plus the disclaimer). **Built that way in the analyst** ("I cannot advise", then evidence for and against). The user has not confirmed it.
5. Router model: the router is plain code today. Whether to build an LLM router at all, and if so whether `mistral:7b` works or `gemma4:12b` is needed. (`router`, `summary` and `judge` roles are set in settings but no code calls them.)
6. Full-text logging of prompts: off by default (assumed).

## 10. Real prompts that failed in the chat (2026-11-20)

**Added 01:40:** "check financial statement of infosys" was answered by the technical agent, which said it had no access to financial statements and offered technical analysis. Cause: the chat had only the technical agent. **Fixed** by the router (now `fundamental`; returns the 5-year P&L table). "10 good points from last 5 years of annual reports of TCS" now routes to `documents` and gets the "not connected" reply. "Revenue growth and RSI of ITC" (mixed) is only partly fixed, see section 3.

Seen by the user in the web app. Use them as test cases for the router, the refusal rule and `rag_search_documents`.

| Prompt typed | What happened | Why | State |
|---|---|---|---|
| "What are the stock avaialbel for query" (typo kept) | Listed the top 5 gainers and losers and called them "the stocks available", with an invented "among others in the index" | No tool listed the stocks, so the agent used `top_movers` | **Fixed:** new `list_stocks` tool and a prompt rule. Live check on `gemma4:12b` returns all 50 with name and industry group. |
| "Give me 10 good points from last 5 years of annual reports of TCS." | Answered with TCS price returns (1 day to 1 year) and a technical summary | The chat agent has only price tools. It has no document search and does not refuse questions it cannot answer | **Not fixed.** Needs `rag_search_documents` and an out-of-scope refusal (router or prompt rule). |

Expected behaviour once fixed:
- A document question for an indexed stock returns passages with file and page, and says how many annual reports were found. TCS has 3 indexed in the trial (2024, 2025, 2026), and the full build adds 5 per stock, so "last 5 years" can be answered only up to the reports present.
- A question with no matching passage (score below the cutoff) says "not found in the documents".
- A question the current agent cannot answer (documents, financials, portfolios) says so in one line and does not substitute price data.

**Added 2026-11-21:**
| Prompt | What happened | State |
|---|---|---|
| "Find 4 stocks which shows higher capex in con calls?" | Went to the technical agent: "con calls" and "capex" were not keywords | **Fixed** (router additions). Now `documents`: a 4-stock table with file and page (ADANIPORTS Transcript_May_2019 p. 12, ONGC Nov_2025 p. 5, BHARTIARTL Feb_2024 p. 5, ETERNAL Aug_2024 p. 9). **Rows not checked against the transcripts.** |
| "Is TCS a good stock to buy" | Answer had invented citations, ignored the buy question, thin fundamental half | **Fixed** in the analyst (see 6.3a). The full answer was not read to the end after the fix. |
| "Give me 2 portfolio ideas for long term and short term" | Goes to the technical agent and repeats stocks | **Not fixed.** Needs the portfolio route (a plain "not connected" reply first). |
| "weather in Mumbai", non-Nifty stocks | Fall to `technical`; the weather question scores 0.63 against the 0.65 cutoff | **Not fixed.** Needs the out-of-scope route. |
| "attrition" (one word, transcripts, TCS) | `found=False` (short query below the cutoff) | **Not fixed.** Tool description should ask for a full descriptive query. |

Search questions that returned good passages on the TCS trial (use after the tool exists): attrition and hiring (transcripts), deal pipeline and TCV, generative AI demand, operating margin and wage hikes, key risks (annual report), governance, dividend policy. Weak or empty by design: acquisitions (accounting notes only), an off-topic question (best score 0.52), any stock not yet indexed.
