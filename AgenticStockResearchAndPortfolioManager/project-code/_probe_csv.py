import pandas as pd, numpy as np, duckdb
from config import get
from fundamentals import Fundamentals
n = pd.read_pickle("/tmp/arpm/nifty_snaps.pkl")
last = n[n.snap_date==n.snap_date.max()].sort_values("snap_time").drop_duplicates("NSE Code",keep="last").set_index("NSE Code")
F = Fundamentals()
rows=[]
for s in last.index:
    try: v = F.get_valuation(s)
    except Exception as e: rows.append((s,None,None,None,None,None,None)); continue
    r = last.loc[s]
    rows.append((s, v["pe"], r["Price to Earning"], v["price_to_book"], r["Price to book value"], v["market_cap"], r["Market Capitalization"]))
d = pd.DataFrame(rows, columns=["sym","pe_agent","pe_csv","pb_agent","pb_csv","cap_wb","cap_csv"]).set_index("sym")
d["pe_diff%"] = ((d.pe_agent-d.pe_csv)/d.pe_csv*100).round(1)
d["cap_diff%"] = ((d.cap_wb-d.cap_csv)/d.cap_csv*100).round(1)
print("market cap workbook vs CSV 20 Nov:  median abs diff %", d["cap_diff%"].abs().median(), " max", d["cap_diff%"].abs().max())
print("P/E agent (cap / last annual profit) vs CSV P/E: median abs diff %", d["pe_diff%"].abs().median(), " max", d["pe_diff%"].abs().max())
print(d.sort_values("pe_diff%", key=abs, ascending=False).head(8).to_string())
# price: CSV vs price DB
c = duckdb.connect(str(get("duckdb_file")), read_only=True)
px = c.execute("select symbol, close from prices where date=(select max(date) from prices)").fetchdf().set_index("symbol")
print("price DB last date:", c.execute("select max(date) from prices").fetchone())
j = last[["Current Price"]].join(px, how="inner"); j["d%"]=((j["Current Price"]-j["close"])/j["close"]*100).round(2)
print("CSV 20 Nov price vs price DB 13 Nov close: median abs %", j["d%"].abs().median())
print("workbook price vs CSV price 20 Nov: ", (pd.Series({s: F.get_valuation(s)["current_price"] for s in last.index}) - last["Current Price"]).abs().max())
