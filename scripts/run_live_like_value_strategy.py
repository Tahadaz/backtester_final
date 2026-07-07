"""Driver for the live-like B/M / CF/P strategy backtest (2026-07-06 continuation).

Reuses the already-computed, repaired panel_characteristics.csv from the prior
data-quality-repair session's characteristic study run rather than re-running
the ~3 minute full pipeline, and loads full daily price series directly for
the vintage engine's price lookups.
"""
import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", os.environ.get("S3_ACCESS_KEY", "minio"))
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", os.environ.get("S3_SECRET_KEY", "minio12345"))
os.environ.setdefault("S3_BUCKET", "quant-artifacts")

from core.quant_core.fundamentals.cross_section.characteristic_study import _full_price_loader
from core.quant_core.fundamentals.cross_section.live_like_strategy import (
    LiveLikeConfig,
    TRUSTED_UNIVERSE_EXCLUSIONS,
    build_vintage_holdings_by_date,
    combine_sleeves,
    eligibility_mask,
    run_semiannual_backtest,
    run_vintage_backtest,
    summarize_performance,
)

PANEL_PATH = Path("research-out/data-quality-forensic-repair/2026-07-06/characteristic-study-after-repair/20260706-194324/panel_characteristics.csv")
OUT_DIR = Path("research-out/live-like-value-strategy") / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel = pd.read_csv(PANEL_PATH)
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date
    panel = eligibility_mask(panel)

    print("Loading full daily price series (for vintage-engine price lookups)...")
    price_frames = _full_price_loader()
    price_by_symbol = {sym: df["Close"] if "Close" in df else None for sym, df in price_frames.items()}

    # MASI benchmark
    masi_close = None
    if "MASI" in price_frames and "Close" in price_frames["MASI"]:
        masi_close = pd.to_numeric(price_frames["MASI"]["Close"], errors="coerce").dropna()

    config = LiveLikeConfig()

    # --- Phase 2: exclusion report ---
    exclusion_rows = []
    for as_of, sub in panel.groupby("as_of_date"):
        exclusion_rows.append(
            {
                "as_of_date": as_of,
                "total_listed": len(sub),
                "eligible_universe": int(sub["eligible_universe"].sum()),
                "eligible_bm": int(sub["eligible_bm"].sum()),
                "eligible_cfp": int(sub["eligible_cfp"].sum()),
                "excluded_sah": int((sub["symbol"] == "SAH").sum()),
            }
        )
    exclusion_df = pd.DataFrame(exclusion_rows)
    exclusion_df.to_csv(OUT_DIR / "exclusion_reasons.csv", index=False)

    # --- Phase 3-4: build S1, S2, S3 vintage holdings ---
    s1_holdings = build_vintage_holdings_by_date(panel, strategy="S1_bm", config=config)
    s2_holdings = build_vintage_holdings_by_date(panel, strategy="S2_cfp", config=config)
    s3_holdings = build_vintage_holdings_by_date(panel, strategy="S3_composite", config=config)

    # --- Phase 5: run vintage engine (primary) + semiannual (robustness) ---
    s1 = run_vintage_backtest(s1_holdings, price_by_symbol=price_by_symbol, config=config)
    s2 = run_vintage_backtest(s2_holdings, price_by_symbol=price_by_symbol, config=config)
    s3 = run_vintage_backtest(s3_holdings, price_by_symbol=price_by_symbol, config=config)
    s4 = combine_sleeves(s1, s2)

    s1_semi = run_semiannual_backtest(s1_holdings, price_by_symbol=price_by_symbol, config=config)
    s2_semi = run_semiannual_backtest(s2_holdings, price_by_symbol=price_by_symbol, config=config)
    s3_semi = run_semiannual_backtest(s3_holdings, price_by_symbol=price_by_symbol, config=config)

    for name, df in [("S1_bm", s1), ("S2_cfp", s2), ("S3_composite", s3), ("S4_sleeves", s4)]:
        df.to_csv(OUT_DIR / f"monthly_realized_returns_{name}.csv", index=False)
    for name, df in [("S1_bm", s1_semi), ("S2_cfp", s2_semi), ("S3_composite", s3_semi)]:
        df.to_csv(OUT_DIR / f"semiannual_realized_returns_{name}.csv", index=False)

    # Benchmark monthly returns aligned to panel dates
    bench_returns = None
    if masi_close is not None:
        all_dates = sorted(s1_holdings)
        bench_rows = []
        for i in range(1, len(all_dates)):
            start, end = all_dates[i - 1], all_dates[i]
            s = masi_close[masi_close.index <= pd.Timestamp(start)]
            e = masi_close[masi_close.index <= pd.Timestamp(end)]
            if s.empty or e.empty:
                continue
            bench_rows.append({"as_of_date": end, "benchmark_return": float(e.iloc[-1] / s.iloc[-1] - 1.0)})
        bench_df = pd.DataFrame(bench_rows)
        bench_df.to_csv(OUT_DIR / "benchmark_returns.csv", index=False)
        bench_returns = bench_df.set_index("as_of_date")["benchmark_return"]

    metrics = {}
    for name, df in [("S1_bm", s1), ("S2_cfp", s2), ("S3_composite", s3), ("S4_sleeves", s4)]:
        metrics[name] = summarize_performance(df, periods_per_year=12, benchmark_returns=bench_returns)
    if bench_returns is not None:
        bench_df2 = pd.DataFrame({"as_of_date": bench_returns.index, "net_return": bench_returns.values, "turnover": 0.0})
        metrics["MASI_benchmark"] = summarize_performance(bench_df2, periods_per_year=12)

    for name, df in [("S1_bm", s1_semi), ("S2_cfp", s2_semi), ("S3_composite", s3_semi)]:
        metrics[f"{name}_semiannual"] = summarize_performance(df, periods_per_year=2)

    (OUT_DIR / "strategy_metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(metrics).T.to_csv(OUT_DIR / "strategy_metrics.csv")

    print(f"\nWritten to {OUT_DIR}")
    print(json.dumps(metrics, indent=2, default=str))


if __name__ == "__main__":
    main()
