r"""Export all market data to Excel (one sheet per stock).

Usage:
    cd <repo-root>
    set S3_ENDPOINT_URL=http://localhost:9000
    set S3_ACCESS_KEY_ID=minio
    set S3_SECRET_ACCESS_KEY=minio12345
    .venv\Scripts\python scripts\export_market_data.py

Output:
    market_data_export.xlsx (one sheet per stock with OHLCV data)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path

import boto3
from botocore.config import Config
import pandas as pd
from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

# Database connection - update if your DB is elsewhere
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
)

# MinIO/S3 configuration (matching API config)
S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID", "minio")
S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", "minio12345")
S3_BUCKET = "quant-artifacts"

# Output file
OUTPUT_FILE = REPO_ROOT / "market_data_export_v2.xlsx"


def get_s3_client():
    """Create boto3 S3 client configured for MinIO (matching API config)."""
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT_URL,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
        use_ssl=False,
        verify=False,
    )


def get_all_symbols(engine) -> list[str]:
    """Get all unique symbols from market_data_store table."""
    query = text("""
        SELECT DISTINCT symbol
        FROM market_data_store
        WHERE timeframe = '1D'
        ORDER BY symbol
    """)
    with engine.connect() as conn:
        result = conn.execute(query)
        return [row.symbol for row in result]


def get_object_key_for_symbol(engine, symbol: str) -> str | None:
    """Get the market_data_store object_key for a symbol."""
    query = text("""
        SELECT object_key
        FROM market_data_store
        WHERE symbol = :symbol AND timeframe = '1D'
        ORDER BY created_at DESC
        LIMIT 1
    """)
    with engine.connect() as conn:
        result = conn.execute(query, {"symbol": symbol})
        row = result.fetchone()
        return row.object_key if row else None


def load_ohlcv_from_parquet(s3_client, object_key: str, symbol: str) -> pd.DataFrame:
    """Load OHLCV data from a parquet file in S3/MinIO."""
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=object_key)
        body = response["Body"].read()
        df = pd.read_parquet(BytesIO(body))
        
        # Normalize columns - find OHLCV columns
        ohlcv_cols = []
        for std_col in ["Open", "High", "Low", "Close", "Volume"]:
            for col in df.columns:
                if col.upper() == std_col.upper():
                    ohlcv_cols.append((std_col, col))
                    break
        
        if not ohlcv_cols:
            print(f"  Skipping {symbol} - no OHLCV columns found")
            return pd.DataFrame()
        
        # Build result with Date index
        # IMPORTANT: Reset index to avoid alignment issues with timezone-aware indices
        df = df.reset_index()
        
        # Find date column
        date_col = None
        for col in ["Date", "date", "Timestamp", "timestamp", "Datetime", "datetime"]:
            if col in df.columns:
                date_col = col
                break
        
        if date_col:
            result = pd.DataFrame()
            result["Date"] = pd.to_datetime(df[date_col], errors="coerce").dt.tz_localize(None)
            result = result.dropna(subset=["Date"])
        elif "Date" in df.columns:
            result = pd.DataFrame()
            result["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.tz_localize(None)
            result = result.dropna(subset=["Date"])
        else:
            print(f"  Skipping {symbol} - no date column found")
            return pd.DataFrame()
        
        # Use .values to get numpy arrays and avoid index alignment issues
        for std_col, df_col in ohlcv_cols:
            result[std_col] = pd.to_numeric(df[df_col].values, errors="coerce")
        
        result = result.set_index("Date").sort_index()
        
        # Remove timezone info if present (Excel doesn't support timezones)
        if result.index.tz is not None:
            result.index = result.index.tz_localize(None)
        
        return result
        
    except Exception as e:
        print(f"  Error loading {symbol}: {type(e).__name__}: {e}")
        return pd.DataFrame()


def main():
    print(f"Connecting to database: {DATABASE_URL}")
    engine = create_engine(DATABASE_URL)
    
    # Get all symbols
    print("Fetching symbols from dataset_ticker...")
    symbols = get_all_symbols(engine)
    print(f"Found {len(symbols)} symbols")
    
    if not symbols:
        print("No symbols found. Exiting.")
        return
    
    # Initialize S3 client
    print(f"Initializing S3 client (endpoint: {S3_ENDPOINT_URL})...")
    s3_client = get_s3_client()
    
    # Test S3 connection
    try:
        s3_client.head_bucket(Bucket=S3_BUCKET)
        print(f"Connected to S3 bucket: {S3_BUCKET}")
    except Exception as e:
        print(f"Warning: Could not verify S3 bucket: {e}")
    
    # Export each symbol to a separate sheet
    print(f"Exporting to {OUTPUT_FILE}...")
    sheets_written = 0
    errors = []
    
    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        for i, symbol in enumerate(symbols):
            if (i + 1) % 10 == 0:
                print(f"  Progress: {i + 1}/{len(symbols)}")
            
            # Get object_key for this symbol
            object_key = get_object_key_for_symbol(engine, symbol)
            if not object_key:
                errors.append((symbol, "no object_key found"))
                continue
            
            # Load OHLCV data from parquet
            df = load_ohlcv_from_parquet(s3_client, object_key, symbol)
            if df.empty:
                errors.append((symbol, "empty data"))
                continue
            
            # Reset index to get Date as column
            df = df.reset_index()
            
            # Write to Excel sheet (sanitize sheet name)
            sheet_name = symbol[:31]  # Excel sheet name limit
            df.to_excel(writer, sheet_name=sheet_name, index=False)
            sheets_written += 1
    
    print(f"\nDone! Exported {sheets_written} sheets to {OUTPUT_FILE}")
    
    if errors:
        print(f"\nErrors ({len(errors)} symbols):")
        for sym, err in errors[:10]:
            print(f"  {sym}: {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
    
    if sheets_written > 0:
        print(f"File size: {OUTPUT_FILE.stat().st_size / 1024 / 1024:.2f} MB")
    else:
        print("\nNo data exported!")
        if OUTPUT_FILE.exists():
            OUTPUT_FILE.unlink()


if __name__ == "__main__":
    main()