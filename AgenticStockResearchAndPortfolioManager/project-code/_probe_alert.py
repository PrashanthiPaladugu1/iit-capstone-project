"""Scratch: real MCP tools + scripted model. Shows what the user would see for the refusals you reported."""
from mcp_client import McpServer
from agent_technical import TechnicalAgent
from agent_news import NewsAgent
from agent_portfolio_manager import PortfolioManager
from guardrail_rules import with_alerts
from providers import ChatResult

class Gw:
    def __init__(self, *r): self.r = list(r); self.n = 0
    def chat(self, role, messages, tools=None, **kw):
        self.n += 1; x = self.r.pop(0); x.call_id = self.n; x.cost = None; return x
def call(name, **a): return ChatResult(text="", tool_calls=[{"id": f"c{name}", "name": name, "arguments": a}], tokens_in=1, tokens_out=1)
def say(t): return ChatResult(text=t, tokens_in=1, tokens_out=1)

with McpServer("market-data", "mcp_market_data.py") as srv:
    out = TechnicalAgent(Gw(call("get_indicators", symbol="ADANIGAS"), say("ADANIGAS is not covered.")), srv).run("Analyze Adani GAS")
    print("== Analyze Adani GAS (technical)\n" + with_alerts(out.answer, out.alerts) + "\n")
with McpServer("news", "mcp_news.py") as srv:
    out = NewsAgent(Gw(call("news_search", stock="Tesla"), say("No news for Tesla.")), srv).run("Latest news on Tesla")
    print("== Latest news on Tesla\n" + with_alerts(out.answer, out.alerts) + "\n")
with McpServer("portfolio", "mcp_portfolio.py") as srv:
    out = PortfolioManager(Gw(call("portfolio_build", size=10), say("A portfolio holds 4 to 6 stocks.")), srv).run("Create a portfolio of 10 stocks")
    print("== Create a portfolio of 10 stocks\n" + with_alerts(out.answer, out.alerts) + "\n")
    out = PortfolioManager(Gw(call("portfolio_evaluate", symbols=["TCS","INFY","WIPRO","HCLTECH","TECHM"]), say("Checked.")), srv).run("Make a portfolio of TCS, INFY, WIPRO, HCLTECH, TECHM")
    print("== five IT stocks\n" + with_alerts(out.answer, out.alerts) + "\n")
    out = PortfolioManager(Gw(call("portfolio_evaluate", symbols=["TCS","INFY","HCLTECH","TECHM","LT"]), say("Checked.")), srv).run("Make a portfolio of TCS, INFY, HCLTECH, TECHM, LT")
    print("== four IT + LT\n" + with_alerts(out.answer, out.alerts))
