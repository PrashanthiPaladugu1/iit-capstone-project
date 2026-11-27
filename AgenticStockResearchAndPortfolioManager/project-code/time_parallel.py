"""Times the research analyst, sequential then parallel, on the real model. bin/run_py.sh time_parallel.py "<question>" """
import sys
import time

sys.path.insert(0, ".")
from agent_fundamental import FundamentalAgent
from agent_research_analyst import ResearchAnalyst
from agent_technical import TechnicalAgent
from gateway import Gateway
from mcp_client import McpServer
from model_settings import SettingsStore

question = sys.argv[1] if len(sys.argv) > 1 else "Compare TCS with INFY"
gw = Gateway(settings=SettingsStore())
servers = [McpServer("market-data", "mcp_market_data.py").start(), McpServer("fundamentals", "mcp_fundamentals.py").start()]
tech, fund = TechnicalAgent(gw, servers[0]), FundamentalAgent(gw, servers[1])
try:
    for parallel in (False, True):
        analyst = ResearchAnalyst(gw, tech, fund, parallel=parallel)
        t = time.time()
        out = analyst.run(question, session=f"time-{'par' if parallel else 'seq'}")
        print(f"\nparallel={parallel}  {time.time() - t:.1f}s  budget={out.budget}  stopped={out.stopped_early!r}")
        print("tools:", [(c["agent"], c["tool"]) for c in out.tool_trace])
        print(out.answer[:500])
finally:
    for s in servers:
        s.close()
