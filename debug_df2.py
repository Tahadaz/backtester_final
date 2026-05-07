import boto3
from botocore.config import Config
import pandas as pd
from io import BytesIO

s3 = boto3.client('s3', endpoint_url='http://localhost:9000', aws_access_key_id='minio', aws_secret_access_key='minio12345', config=Config(signature_version='s3v4'), use_ssl=False, verify=False)
resp = s3.get_object(Bucket='quant-artifacts', Key='market_data/symbols/ATW/ohlcv.parquet')
df = pd.read_parquet(BytesIO(resp['Body'].read()))

# Exact copy from export script
result = pd.DataFrame()
result["Date"] = df.index
print('After Date assignment:')
print(result.head(3))
print()

for std_col, df_col in [("Open", "Open"), ("High", "High"), ("Low", "Low"), ("Close", "Close"), ("Volume", "Volume")]:
    print(f'Assigning {std_col} from {df_col}')
    print(f'  df[{df_col}] type: {type(df[df_col])}')
    print(f'  df[{df_col}] head: {df[df_col].head(3).tolist()}')
    result[std_col] = pd.to_numeric(df[df_col], errors="coerce")
    print(f'  result[{std_col}] head: {result[std_col].head(3).tolist()}')
    print()

result = result.set_index("Date").sort_index()
if result.index.tz is not None:
    result.index = result.index.tz_localize(None)

print('Final result:')
print(result.head(3))