"""Live check of agent_news on the real feeds and the real model. bin/run_py.sh live_news.py"""
import sys
import time

sys.path.insert(0, ".")
from agent_news import NewsAgent
from agent_research_analyst import ResearchAnalyst
from agent_technical import TechnicalAgent
from agent_fundamental import FundamentalAgent
from gateway import Gateway
from mcp_client import McpServer
from model_settings import SettingsStore

gw = Gateway(settings=SettingsStore())
news_server = McpServer("news", "mcp_news.py").start()
agent = NewsAgent(gw, news_server)
try:
    for q in ["Any news on TCS this week?", "What is the sentiment around Infosys over the last 7 days?",
              "What is the market news today?", "Any news on Wipro?"]:
        t = time.time()
        out = agent.run(q, session="live-news")
        print(f"\n=== {q}  ({time.time() - t:.1f}s, {out.budget}, stopped={out.stopped_early!r}, reminders={out.reminders})")
        print("tools:", [(c["tool"], c["arguments"], c["ok"]) for c in out.tool_trace])
        print(out.answer[:1500])
    if "--analyst" in sys.argv:
        tech = TechnicalAgent(gw, McpServer("market-data", "mcp_market_data.py").start())
        fund = FundamentalAgent(gw, McpServer("fundamentals", "mcp_fundamentals.py").start())
        analyst = ResearchAnalyst(gw, tech, fund, news=agent)
        q = "Tell me the RSI of TCS and the latest news on it"
        t = time.time()
        out = analyst.run(q, session="live-news")
        print(f"\n=== ANALYST: {q}  ({time.time() - t:.1f}s, {out.budget}, stopped={out.stopped_early!r})")
        print([(c["agent"], c["tool"]) for c in out.tool_trace])
        print(out.answer[:1800], "\nNOTE:", out.note)
finally:
    news_server.close()
