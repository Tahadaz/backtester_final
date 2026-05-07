import csv
import json
from pathlib import Path

SRC = Path(r"c:\Users\taha\Downloads\iLoveZIP_Create\factor_lab_outputs\static_summary.csv")
OUT = Path(__file__).parent.parent / 'docs' / 'presentations' / 'factor_summary.json'
OUT.parent.mkdir(parents=True, exist_ok=True)

assets = ["ATW","BCP","BMCE","IAM","Managem","CMT","Addoha","LafargeHolcim","Ciments","Cosumar","Wafa"]
# We'll match if asset string startswith one of names (case-insensitive)
summary = {}
with SRC.open('r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        asset = row['asset']
        for a in assets:
            if asset.lower().startswith(a.lower()):
                summary.setdefault(a, []).append({
                    'factor': row['factor'],
                    'n_obs': int(row['n_obs']),
                    'spearman_corr': float(row['spearman_corr']),
                    'spearman_p': float(row['spearman_p']),
                    'beta_hac_t': float(row['beta_hac_t']),
                    'beta_hac_p': float(row['beta_hac_p']),
                    'r2': float(row['r2']) if row['r2'] else None
                })

with OUT.open('w', encoding='utf-8') as f:
    json.dump(summary, f, indent=2)

print('Wrote', OUT)
