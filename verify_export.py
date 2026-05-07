import pandas as pd
xl = pd.ExcelFile('market_data_export_v2.xlsx')
print(f'Sheets: {len(xl.sheet_names)}')
total = 0
for s in ['ATW', 'BCP', 'IAM', 'ADH', 'ADI']:
    df = pd.read_excel(xl, sheet_name=s)
    print(f'  {s}: {len(df)} rows, {df.notna().sum().sum()} non-null')
    total += len(df)
print(f'Total sample: {total}')