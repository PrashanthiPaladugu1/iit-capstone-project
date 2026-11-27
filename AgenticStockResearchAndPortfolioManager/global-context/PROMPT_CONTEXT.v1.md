# Prompt context: how user prompts and agent prompts are handled

Saved 2026-11-19. Companion to `GLOBAL_CONTEXT.md` (architecture) and `STATUS_AND_PROGRESS.md` (tracker).
This file covers what the user types, how it is understood and routed, and the prompts the agents use.

**Legend:** BUILT = code exists and is tested. PLANNED = agreed in discussion, no code yet. ASSUMED = my default, not yet confirmed by the user.

## 1. Prompt flow (one user message)

```
user message
  -> prompt_enhancer   (PLANNED, mostly plain code)
  -> guardrails        (PLANNED, plain code: G1 to G8)
  -> router            (PLANNED, one LLM call, role "router")
  -> agent(s)          (technical BUILT; the rest PLANNED)
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
| `fundamental` | Financials and documents | "Five-year revenue CAGR of Asian Paints"; "Key risks in the latest Reliance annual report" | `agent_fundamental`: financials tools, `search_documents` |
| `research` | Combined view, "should I invest" | "Give me a research view on INFY" | `agent_research_analyst` |
| `portfolio` | Build, check or rebalance a portfolio | "Make a 5-stock low-risk portfolio and show its drawdown" | `agent_portfolio_manager` |
| `compare` | Head-to-head between stocks (ASSUMED) | "Compare INFY and TCS" | `agent_compare` |
| `both` | Technical and fundamental in parallel | "Which stocks have rising revenue but falling price?" | both agents |
| `out_of_scope` | Not the Nifty 50, or not about stocks | "Add Tesla to my portfolio" | guardrail G1 reply, no agent call |

Routing is one LLM call at temperature 0 on the `router` role (default `mistral:7b`). **Router quality on `mistral:7b` has not been tested.** `mistral:7b` failed at tool calling in live tests, so test routing before relying on it. The fallback is `gemma4:12b`.

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

### 6.2 Other agents (PLANNED, wording not written)
| Agent | Prompt must say |
|---|---|
| `agent_fundamental` | Numbers from the financials tools only. Cite the document and page for every claim from `search_documents`. Say when a stock has no Excel or no transcript (INFY Excel only; SBILIFE no Excel; ITC and TRENT no transcripts; BAJAJ-AUTO no presentations). |
| `agent_research_analyst` | Write prose around numbers computed by `scorecard.py`. Give evidence for and against. No buy or sell verdict. Always add the G7 disclaimer. |
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
4. Whether a "buy or sell" question gets a refusal or an evidence summary (assumed: evidence summary plus the disclaimer).
5. Router model: confirm `mistral:7b` works, or use `gemma4:12b`.
6. Full-text logging of prompts: off by default (assumed).
