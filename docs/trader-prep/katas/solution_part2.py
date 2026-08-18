import pandas as pd
trade=pd.read_csv("trades.csv")
mark=pd.read_csv("marks.csv")
trades=pd.DataFrame(trade)
marks=pd.DataFrame(mark)
trades["net_position"] = trades["quantity"] * trades["price"]*trades["side"].apply(lambda x: 1 if x=="buy" else -1)
summary=pd.DataFrame(trades.groupby("symbol")["net_position"].sum())
summary["avg_entry_price"]=trades.groupby("symbol").apply(lambda x: (x["quantity"]*x["price"]).sum()/x["quantity"].sum())
summary["latest_mark"]=marks.groupby("symbol")["close"].last()
summary["unrealized_pnl"]=(summary["latest_mark"]-summary["avg_entry_price"])*summary["net_position"]
