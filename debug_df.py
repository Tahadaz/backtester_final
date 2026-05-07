import boto3
from botocore.config import Config
import pandas as pd
from io import BytesIO

s3 = boto3.client('s3', endpoint_url='http://localhost:9000', aws_access_key_id='minio', aws_secret_access_key='minio12345', config=Config(signature_version='s3v4'), use_ssl=False, verify=False)
resp = s3.get_object(Bucket='quant-artifacts', Key='market_data/symbols/ATW/ohlcv.parquet')
df = pd.read_parquet(BytesIO(resp['Body'].read()))

print('Type:', type(df))
print('Index type:', type(df.index))
print('Columns:', df.columns.tolist())
print()
print('df["Open"]:', df["Open"].head(3))
print()
print('df.Open:', df.Open.head(3))
print()
print('df.iloc[:, 0]:', df.iloc[:, 0].head(3))