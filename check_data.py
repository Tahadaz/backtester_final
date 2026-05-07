import pandas as pd
xl = pd.ExcelFile('market_data_export.xlsx')
print(f'Total sheets: {len(xl.sheet_names)}')
total_rows = 0
for sheet in xl.sheet_names:
    df = pd.read_excel(xl, sheet_name=sheet)
    total_rows += len(df)
print(f'Total rows across all sheets: {total_rows}')