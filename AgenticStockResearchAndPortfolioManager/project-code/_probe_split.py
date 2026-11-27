import json, sys, time
sys.path.insert(0, ".")
from gateway import Gateway
from model_settings import SettingsStore
PROMPT = """Split a stock question into two self-contained parts.
technical: price, trend, returns, RSI, MACD, moving averages, volatility, 52-week, movers, volume.
fundamental: financial statements, sales, profit, growth, margins, ROE, ratios, P/E, valuation, debt, dividends, and anything from annual reports, transcripts or presentations.
Each part must repeat the stock names so it makes sense alone. Use "" for a part the question does not ask.
Answer with JSON only: {"technical": "...", "fundamental": "..."}"""
QS = ["Revenue growth and RSI of ITC", "Is TCS trend good and what is its net profit?", "compare infosys and tcs",
      "RSI of TCS", "P/E and 1 year return of HDFCBANK", "What did Reliance management say about margins and how has the price moved?"]
gw = Gateway(settings=SettingsStore())
for role in sys.argv[1:]:
    print("==", role)
    for q in QS:
        t = time.time()
        r = gw.chat(role, [{"role": "system", "content": PROMPT}, {"role": "user", "content": q}], params={"temperature": 0})
        print(f"{time.time()-t:4.1f}s | {q} -> {r.text.strip()[:260]}")
