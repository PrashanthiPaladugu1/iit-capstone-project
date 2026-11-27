import sys
sys.path.insert(0, ".")
from model_settings import SettingsStore
from gateway import Gateway
from mcp_client import McpServer
from agent_fundamental import FundamentalAgent
gw = Gateway(settings=SettingsStore())
q = "Revenue growth and RSI of ITC"
variants = {
 "A": "The question may have two parts. Ignore any price or indicator part (RSI, trend, price); another agent handles it. Always call a tool for the financial-statement part first, then answer only that part.",
 "B": "Only the financial-statement part of the question is yours. Do not call a tool for, or answer, anything about prices or indicators. You must call a financial tool now for the rest.",
}
with McpServer("fundamentals", "mcp_fundamentals.py") as s:
    a = FundamentalAgent(gw, s)
    for name, f in variants.items():
        for i in range(4):
            r = a.run(q, session="probe", focus=f)
            print("RES", name, i, [t["tool"] for t in r.tool_trace], r.reminders, r.answer[:70].replace("\n", " "))
