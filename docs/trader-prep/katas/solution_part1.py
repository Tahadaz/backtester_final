import pandas as pd
trade=pd.read_csv("trades.csv")
trades=pd.DataFrame(trade)
trades["net_position"] = trades["quantity"] * trades["price"]*trades["side"].apply(lambda x: 1 if x=="buy" else -1)
