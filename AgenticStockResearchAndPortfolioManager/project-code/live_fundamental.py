"""Run agent_fundamental on a real local model.  bin/run_py.sh live_fundamental.py gemma4:12b "<question>" ..."""
import sys, time, tempfile
sys.path.insert(0, ".")
from pathlib import Path
from model_settings import SettingsStore
from gateway import Gateway
from mcp_client import McpServer
from agent_fundamental import FundamentalAgent

model = sys.argv[1]
tmp = Path(tempfile.mkdtemp())
st = SettingsStore(tmp / "s.sqlite")
st.set_role("chat", "ollama_local", model)
gw = Gateway(settings=st, usage_db=tmp / "u.sqlite")
with McpServer("fundamentals", "mcp_fundamentals.py") as s:
    agent = FundamentalAgent(gw, s)
    for q in sys.argv[2:]:
        t = time.time()
        try:
            r = agent.run(q, session="live")
        except Exception as e:
            print(f"[{model}] Q: {q} -> ERROR {e}"); continue
        print(f"\n[{model}] Q: {q} ({time.time()-t:.1f}s) tools={[(x['tool'], x['arguments']) for x in r.tool_trace]} {r.budget} {r.stopped_early}")
        print(r.answer[:900])
