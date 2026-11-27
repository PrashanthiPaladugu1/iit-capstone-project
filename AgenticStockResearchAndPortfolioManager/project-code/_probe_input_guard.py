import time
import input_guard
from router import route
t = time.time(); g = input_guard.default_guard(); print(f"built in {time.time()-t:.2f}s")
qs = ["Create a portfolio of 10 stocks", "Create a portfolio of 2 stocks: TCS and INFY", "create a postfolio of 10 stocks",
      "Analyze Adani GAS", "Analyze Infosys", "Latest news on Tesla", "Compare TCS with Wipro", "Create a portfolio of 5 stocks",
      "Is HCLTECH a good buy", "RSI of TECHM and news on LT", "Analyze Tata Motors", "Is Bank of India better than SBIN",
      "Give me 2 portfolio ideas for long term and short term", "Top 10 stocks by RSI", "tell me about the premier league",
      "How is Britannia doing", "Is Vedanta cheap", "Analyze Zomato", "Nifty 50 PE", "Analyze Eternal"]
for q in qs:
    r = route(q); res = g.check(q, portfolio=(r == "portfolio"))
    print(f"{('BLOCK ' + ','.join(b['id'] for b in res.blocks)) if res.blocked else 'pass':12} [{r:9}] {q}")
    for a in res.alerts: print("      ", a)
