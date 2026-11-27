"""Runs the chat's answer() path (router + real agents + real gemma model). bin/run_py.sh live_chat.py "<question>" ..."""
import os
import sys, time
sys.path.insert(0, ".")
import ui_app

# Plain objects instead of Streamlit's cache so this runs outside the browser.
import types
from model_settings import SettingsStore
from gateway import Gateway
from mcp_client import McpServer
from agent_technical import TechnicalAgent
from agent_fundamental import FundamentalAgent

gw = Gateway(settings=SettingsStore())
servers = [McpServer("market-data", "mcp_market_data.py").start(), McpServer("fundamentals", "mcp_fundamentals.py").start(),
           McpServer("portfolio", "mcp_portfolio.py").start()]
agents = {"technical": TechnicalAgent(gw, servers[0]), "fundamental": FundamentalAgent(gw, servers[1])}
from agent_research_analyst import ResearchAnalyst
agents["research"] = ResearchAnalyst(gw, agents["technical"], agents["fundamental"])
from agent_portfolio_manager import PortfolioManager
agents["portfolio"] = PortfolioManager(gw, servers[2])
ui_app.get_agents = lambda: agents
try:
    for q in sys.argv[1:]:
        t = time.time()
        item = ui_app.answer(q, "live-chat")
        print(f"\nQ: {q}\nroute={item['route']} ({time.time()-t:.1f}s) tools={[(c.get('agent'), c['tool'], c['arguments']) for c in item['trace']]}")
        print(item["text"][:int(os.environ.get("ARPM_SHOW", "900"))])
finally:
    for s in servers:
        s.close()
