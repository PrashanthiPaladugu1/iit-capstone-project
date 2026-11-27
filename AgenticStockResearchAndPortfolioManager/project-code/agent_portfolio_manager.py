"""agent_portfolio_manager: builds and checks small Nifty 50 portfolios (4 to 6 stocks).

It reuses the loop in agent_technical.py (model node, LangGraph ToolNode, shared Budget, "no tool data, no answer" rule)
and changes the tools (wrappers over the `portfolio` MCP server), the system prompt and the agent name. Stock picks, weights,
guardrail checks and the past replay are all computed by code in portfolio.py, never by the model.

    agent = PortfolioManager(gateway, server)       # server = McpServer("portfolio", "mcp_portfolio.py")
    result = agent.run("Make a 5-stock low-risk portfolio", session="s1")
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from agent_technical import TechnicalAgent, TechnicalResult

AGENT = "agent_portfolio_manager"
PortfolioResult = TechnicalResult

SYSTEM_PROMPT = """You are the portfolio manager agent in a Nifty 50 research app. You build and check small portfolios of
4 to 6 Nifty 50 stocks. A scorecard ranks the 50 stocks on momentum, quality, valuation and risk. Code picks the stocks, sets the
weights, checks the guardrails and replays the past. You explain the result.
Rules:
- Take every stock, weight, score and return from a tool. Never name a stock, weight or number you did not get from a tool.
- Use portfolio_build for "make or build a portfolio" (strategy balanced, momentum, low_risk, quality, value, long_term or
  short_term; weighting equal or inverse_vol; size 4 to 6, 5 if the user gives none). "Long term" means long_term, "short term"
  means short_term, "safe" or "low risk" means low_risk, "growth" or "momentum" means momentum.
- For several portfolio ideas, call portfolio_build once per idea, each with a different strategy, and show them one after another.
- Use portfolio_evaluate when the user names the stocks (and weights). Use portfolio_scorecard to show a ranking. Use
  portfolio_suggest only for a list of picks without weights.
- Only Nifty 50 stocks are covered. If a tool says a stock is not in the Nifty 50, say so and leave it out. Do not swap in another.
- A portfolio holds 4 to 6 stocks, each 5% to 40%. If the user asks for another size, say it is 4 to 6 and offer a size in range.
- Leave days at 252 (one year of trading days). Change it only when the user names a period, and then 1 year is 252, 6 months
  is 126. "Long term" and "short term" pick the strategy, not the replay window.
- Show every guardrail block and warning the tool returns. If a guardrail blocks, say what must change and do not show a replay.
- The replay is the past with the weights bought on day one and held. Call it "in the past", never a forecast or expected return.
  Say it ignores costs and tax. Prices are not adjusted for splits: pass on any jump_days or flags in one short sentence.
- Say which data dates apply (as_of) once. A scorecard score is 0 worst to 100 best among the 50 stocks, and a high risk score
  means low volatility.
- Do not say buy or sell and do not predict. End every portfolio answer with the footer text the tool returned, which says it is
  not investment advice.
- Keep it short: a small table of stocks, industry group, weight and score, then two or three lines on what it shows."""

REMINDER = ("You must call at least one tool to get the data before you answer. "
            "Do not write stocks, weights or numbers from memory. Call the right tool now.")
NO_DATA_ANSWER = ("I have no tool data for this question, so I will not invent a portfolio. "
                  "Try: 'Make a 5-stock low-risk portfolio of Nifty 50 stocks'.")


def make_tools(call) -> list[BaseTool]:
    """The tools this agent may use. `call(name, arguments)` runs one tool on the MCP server and returns text."""

    @tool
    def portfolio_scorecard(strategy: str = "balanced", limit: int = 10) -> str:
        """Rank the Nifty 50 stocks for a strategy, best first, at most 25 rows. strategy is balanced, momentum, low_risk, quality, value, long_term or short_term. Each row has total, momentum, quality, valuation and risk (0 worst to 100 best; a high risk score means low volatility). Past data only; not a forecast."""
        return call("portfolio_scorecard", {"strategy": strategy, "limit": limit})

    @tool
    def portfolio_suggest(strategy: str = "balanced", size: int = 5, include: list[str] | None = None,
                          exclude: list[str] | None = None) -> str:
        """Pick 4 to 6 Nifty 50 stocks for a strategy, one per industry group, best first. include forces stocks in, exclude keeps stocks out. No weights and no replay; use portfolio_build for those."""
        return call("portfolio_suggest", {"strategy": strategy, "size": size, "include": include, "exclude": exclude})

    @tool
    def portfolio_build(strategy: str = "balanced", size: int = 5, weighting: str = "equal", include: list[str] | None = None,
                        exclude: list[str] | None = None, days: int = 252) -> str:
        """Build one portfolio of 4 to 6 Nifty 50 stocks: picks, weights (5% to 40% each, adding to 100%), guardrail result and a buy-and-hold replay of the last `days` trading days. strategy is balanced, momentum, low_risk, quality, value, long_term or short_term. weighting is equal or inverse_vol. Call it again with a different strategy for another portfolio. The result has a footer that must be shown."""
        return call("portfolio_build", {"strategy": strategy, "size": size, "weighting": weighting, "include": include,
                                        "exclude": exclude, "days": days})

    @tool
    def portfolio_evaluate(symbols: list[str], weights: dict[str, float] | None = None, days: int = 252) -> str:
        """Check a portfolio the user named: guardrail blocks and warnings, and (when nothing blocks) a buy-and-hold replay of the last `days` trading days. weights are percentages per symbol (equal if omitted). The result has a footer that must be shown."""
        return call("portfolio_evaluate", {"symbols": symbols, "weights": weights, "days": days})

    return [portfolio_scorecard, portfolio_suggest, portfolio_build, portfolio_evaluate]


class PortfolioManager(TechnicalAgent):
    agent_name = AGENT
    system_prompt = SYSTEM_PROMPT
    reminder = REMINDER
    no_data_answer = NO_DATA_ANSWER

    def run(self, question: str, *, route: str = "portfolio", **kw) -> PortfolioResult:
        return super().run(question, route=route, **kw)

    def _make_tools(self) -> list[BaseTool]:
        return make_tools(self._run_tool)
