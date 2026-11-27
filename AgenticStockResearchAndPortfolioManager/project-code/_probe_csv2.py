from router import route
from screener import Screener
s = Screener()
qs = ["show me NIFTY 50 Stocks with PE RSI OPM NPM", "Which Nifty stock has the highest ROCE?", "FII holding of HDFCBANK",
      "lowest PE stocks in Nifty 50", "stocks with promoter holding above 60", "PEG ratio of INFY", "industry PE of TCS",
      "NPM and OPM of RELIANCE", "SBILIFE PE", "show me stocks with PE and 52 week high", "debt to equity of LT",
      "Which stocks have RSI above 70", "Is TCS cheap", "how has FII holding of HDFCBANK changed"]
for q in qs: print(f"{route(q):12} {q}")
print()
t = s.get_table(["pe","roce"], sort_by="roce", limit=3); print("top ROCE", [r[:3] for r in t["rows"]], t["note"][:60])
t = s.get_table(["promoter_holding"], min_values={"promoter_holding": 60}); print("promoter>60:", t["count"], [r[0] for r in t["rows"]][:6])
t = s.get_table(["rsi"], min_values={"rsi": 70}); print("RSI>70:", t["count"])
h = s.get_history("HDFCBANK","fii_holding"); print("HDFCBANK FII", h["first"], "->", h["latest"], h["count"], "dates")
