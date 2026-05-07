import boto3
from botocore.config import Config
import pandas as pd
from io import BytesIO
from sqlalchemy import create_engine, text

# DB
engine = create_engine('postgresql+psycopg2://app:app@127.0.0.1:5555/quant')
with engine.connect() as conn:
    result = conn.execute(text("SELECT object_key FROM market_data_store WHERE symbol = 'ATW' AND timeframe = '1D' ORDER BY created_at DESC LIMIT 1"))
    row = result.fetchone()
    print('object_key:', row.object_key if row else None)
    obj_key = row.object_key if row else None

# S3
s3 = boto3.client('s3', endpoint_url='http://localhost:9000', aws_access_key_id='minio', aws_secret_access_key='minio12345', config=Config(signature_version='s3v4'), use_ssl=False, verify=False)
resp = s3.get_object(Bucket='quant-artifacts', Key=obj_key)
df = pd.read_parquet(BytesIO(resp['Body'].read()))
print('Parquet shape:', df.shape)
print(df.head(3))

# Now test the export function logic
result = pd.DataFrame()
result["Date"] = df.index
for std_col, df_col in [("Open", "Open"), ("High", "High"), ("Low", "Low"), ("Close", "Close"), ("Volume", "Volume")]:
    result[std_col] = pd.to_numeric(df[df_col], errors="coerce")

result = result.set_index("Date").sort_index()
if result.index.tz is not None:
    result.index = result.index.tz_localize(None)

print('Result shape:', result.shape)
print(result.head(3))