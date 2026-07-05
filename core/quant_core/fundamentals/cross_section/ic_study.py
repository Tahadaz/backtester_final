from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from sqlalchemy import create_engine, text

from quant_core.factor_selection.direct import _hac_t_stat, _nw_maxlags
from quant_core.fundamentals.cross_section.composite import compute_sfc
from quant_core.fundamentals.cross_section.panel import PanelConfig, build_pit_panel, load_universe
from quant_core.fundamentals.cross_section.pillars import PillarConfig, compute_pillar_scores
from quant_core.significance import monte_carlo_luck_test

SIGNALS = ("pillar_val", "pillar_qual", "pillar_fmom", "pillar_pmom", "sfc")
HORIZONS = ("3m", "6m", "12m")


def _spearman(left: pd.Series, right: pd.Series) -> float:
    val = pd.to_numeric(left, errors="coerce").corr(pd.to_numeric(right, errors="coerce"), method="spearman")
    return float(val) if val is not None and math.isfinite(float(val)) else float("nan")


def _hac_mean_t_stat(values: list[float]) -> float:
    series = pd.Series([v for v in values if math.isfinite(float(v))], dtype=float)
    if len(series) < 3:
        return 0.0
    try:
        fit = sm.OLS(series, np.ones((len(series), 1))).fit(
            cov_type="HAC",
            cov_kwds={"maxlags": _nw_maxlags(len(series))},
        )
        value = float(fit.tvalues.iloc[0])
    except Exception:
        return 0.0
    return value if math.isfinite(value) else 0.0


def benjamini_hochberg(pvalues: list[float], *, alpha: float = 0.10) -> list[dict[str, float | bool]]:
    clean = [(i, float(p)) for i, p in enumerate(pvalues) if math.isfinite(float(p))]
    m = len(clean)
    out = [{"pvalue": float(p), "qvalue": float("nan"), "reject": False} for p in pvalues]
    if m == 0:
        return out
    ordered = sorted(clean, key=lambda item: item[1])
    min_q = 1.0
    q_by_i: dict[int, float] = {}
    for rank, (idx, p) in reversed(list(enumerate(ordered, start=1))):
        min_q = min(min_q, p * m / rank)
        q_by_i[idx] = min_q
    max_rank = 0
    for rank, (_, p) in enumerate(ordered, start=1):
        if p <= alpha * rank / m:
            max_rank = rank
    rejected = {idx for rank, (idx, _) in enumerate(ordered, start=1) if rank <= max_rank}
    for idx, q in q_by_i.items():
        out[idx]["qvalue"] = float(min(q, 1.0))
        out[idx]["reject"] = idx in rejected
    return out


def _norm_pvalue(t_stat: float) -> float:
    if not math.isfinite(t_stat):
        return 1.0
    return float(2.0 * (1.0 - (0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))))


def compute_ic_table(frame: pd.DataFrame, *, split: str, variant_id: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for signal in SIGNALS:
        for horizon in HORIZONS:
            by_date = []
            for as_of, sub in frame.groupby("as_of_date"):
                pairs = sub[[signal, f"fwd_return_{horizon}"]].replace([np.inf, -np.inf], np.nan).dropna()
                if len(pairs) < 5:
                    continue
                ic = _spearman(pairs[signal], pairs[f"fwd_return_{horizon}"])
                if math.isfinite(ic):
                    by_date.append((as_of, ic, len(pairs)))
            values = [x[1] for x in by_date]
            mean_ic = float(np.mean(values)) if values else float("nan")
            t_stat = _hac_mean_t_stat(values)
            pooled = frame[[signal, f"fwd_return_{horizon}"]].replace([np.inf, -np.inf], np.nan).dropna()
            pooled_t = _hac_t_stat(pooled[f"fwd_return_{horizon}"], pooled[signal]) if len(pooled) >= 3 else 0.0
            rows.append(
                {
                    "variant_id": variant_id,
                    "split": split,
                    "signal": signal,
                    "horizon": horizon,
                    "periods": len(values),
                    "pairs": int(sum(x[2] for x in by_date)),
                    "mean_ic": mean_ic,
                    "nw_t_stat": t_stat,
                    "pooled_hac_t_stat": pooled_t,
                    "pvalue": _norm_pvalue(t_stat),
                }
            )
    return pd.DataFrame(rows)


def chronological_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dt.date | None]:
    dates = sorted(pd.to_datetime(frame["as_of_date"]).dt.date.unique())
    if len(dates) < 2:
        return frame.iloc[0:0].copy(), frame.copy(), None
    split_date = dates[len(dates) // 2]
    selection = frame[pd.to_datetime(frame["as_of_date"]).dt.date < split_date].copy()
    proof = frame[pd.to_datetime(frame["as_of_date"]).dt.date >= split_date].copy()
    return selection, proof, split_date


def tercile_backtest(frame: pd.DataFrame, *, cost_bps: float, horizon: str = "3m") -> dict[str, Any]:
    returns = []
    turnovers = []
    prev_top: set[str] = set()
    for _, sub in frame.dropna(subset=["sfc", f"fwd_return_{horizon}"]).groupby("as_of_date"):
        ranked = sub.sort_values("sfc", ascending=False)
        if len(ranked) < 9:
            continue
        n_top = max(1, len(ranked) // 3)
        top = ranked.head(n_top)
        top_symbols = set(top["symbol"].astype(str))
        universe_ret = float(ranked[f"fwd_return_{horizon}"].mean())
        top_ret = float(top[f"fwd_return_{horizon}"].mean())
        turnover = 1.0 if not prev_top else len(top_symbols.symmetric_difference(prev_top)) / max(len(top_symbols | prev_top), 1)
        prev_top = top_symbols
        cost = (float(cost_bps) / 10000.0) * 2.0 * turnover
        returns.append(top_ret - universe_ret - cost)
        turnovers.append(turnover)
    sig = monte_carlo_luck_test(returns, metric="total_return", n_iter=1000, seed=42, periods_per_year=12, block_mean=3)
    return {
        "horizon": horizon,
        "cost_bps": float(cost_bps),
        "periods": len(returns),
        "mean_spread": float(np.mean(returns)) if returns else float("nan"),
        "total_spread": float(np.prod(1.0 + np.asarray(returns, dtype=float)) - 1.0) if returns else float("nan"),
        "avg_turnover": float(np.mean(turnovers)) if turnovers else float("nan"),
        "bootstrap_pvalue": sig.get("pvalue"),
    }


def run_study(panel: pd.DataFrame, *, price_by_symbol: dict[str, pd.Series | None]) -> dict[str, Any]:
    variants = [
        ("pmom_6_1", PillarConfig(pmom_months=6)),
        ("pmom_12_1", PillarConfig(pmom_months=12)),
    ]
    variant_frames: dict[str, pd.DataFrame] = {}
    selection_tables = []
    for variant_id, cfg in variants:
        scored = compute_sfc(compute_pillar_scores(panel, price_by_symbol=price_by_symbol, config=cfg))
        selection, _, split_date = chronological_split(scored)
        variant_frames[variant_id] = scored
        selection_tables.append(compute_ic_table(selection, split="selection", variant_id=variant_id))
    selection_ic = pd.concat(selection_tables, ignore_index=True) if selection_tables else pd.DataFrame()
    chooser = selection_ic[(selection_ic["signal"] == "sfc") & (selection_ic["horizon"] == "6m")].copy()
    if chooser.empty:
        chosen_variant = "pmom_6_1"
    else:
        chooser["sort_t"] = chooser["nw_t_stat"].fillna(-999.0)
        chooser["sort_ic"] = chooser["mean_ic"].fillna(-999.0)
        chosen_variant = str(chooser.sort_values(["sort_t", "sort_ic"], ascending=False).iloc[0]["variant_id"])
    chosen_frame = variant_frames[chosen_variant]
    _, proof, split_date = chronological_split(chosen_frame)

    proof_tables = []
    for variant_id, full in variant_frames.items():
        _, variant_proof, _ = chronological_split(full)
        proof_tables.append(compute_ic_table(variant_proof, split="proof", variant_id=variant_id))
    proof_ic = pd.concat(proof_tables, ignore_index=True) if proof_tables else pd.DataFrame()
    fdr = benjamini_hochberg(proof_ic["pvalue"].tolist(), alpha=0.10) if not proof_ic.empty else []
    if not proof_ic.empty:
        proof_ic["fdr_qvalue"] = [x["qvalue"] for x in fdr]
        proof_ic["fdr_reject_10pct"] = [x["reject"] for x in fdr]

    bt33 = tercile_backtest(proof, cost_bps=33.0, horizon="3m")
    bt75 = tercile_backtest(proof, cost_bps=75.0, horizon="3m")
    chosen_proof = proof_ic[proof_ic["variant_id"] == chosen_variant] if not proof_ic.empty else proof_ic
    composite_rows = chosen_proof[chosen_proof["signal"] == "sfc"] if not chosen_proof.empty else chosen_proof
    ic_pass = bool(((composite_rows["mean_ic"] > 0) & (composite_rows["nw_t_stat"] >= 2.0)).any()) if not composite_rows.empty else False
    spread_pass = bool(
        math.isfinite(float(bt33["mean_spread"]))
        and bt33["mean_spread"] > 0
        and math.isfinite(float(bt75["mean_spread"]))
        and bt75["mean_spread"] >= 0
    )
    verdict = "PASS" if ic_pass and spread_pass else "FAIL"
    config = {
        "methodology_version": "sfc_phase1_2026_07_05",
        "chosen_variant": chosen_variant,
        "variants_evaluated": [v[0] for v in variants],
        "selection_proof_split_date": split_date.isoformat() if split_date else None,
        "horizons": list(HORIZONS),
        "equal_pillar_weights": True,
        "fdr_family_test_count": int(len(proof_ic)),
    }
    config_hash = hashlib.sha256(json.dumps(config, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return {
        "selection_ic": selection_ic,
        "proof_ic": proof_ic,
        "chosen_variant": chosen_variant,
        "split_date": split_date,
        "backtest_33bps": bt33,
        "backtest_75bps": bt75,
        "verdict": verdict,
        "ic_pass": ic_pass,
        "spread_pass": spread_pass,
        "config": config,
        "config_hash": config_hash,
    }


def format_results_markdown(result: dict[str, Any]) -> str:
    selection = result["selection_ic"].round(4)
    proof = result["proof_ic"].round(4)
    lines = [
        "# 61 - SFC IC study results",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        f"Config hash: `{result['config_hash']}`",
        f"Chosen selection-half variant: `{result['chosen_variant']}`",
        f"Selection/proof split date: `{result['split_date']}`",
        "",
        "## Selection-half variants",
        "",
        selection.to_markdown(index=False) if not selection.empty else "_No selection IC rows._",
        "",
        "## Proof-half IC with BH-FDR",
        "",
        proof.to_markdown(index=False) if not proof.empty else "_No proof IC rows._",
        "",
        "## Tercile spread backtest",
        "",
        pd.DataFrame([result["backtest_33bps"], result["backtest_75bps"]]).round(6).to_markdown(index=False),
        "",
        "## Gate verdict",
        "",
        f"Verdict: **{result['verdict']}**",
        f"Composite IC gate passed: `{result['ic_pass']}`",
        f"Net spread gate passed: `{result['spread_pass']}`",
        "",
        "The proof-half FDR family includes every selection-half variant carried to proof.",
    ]
    return "\n".join(lines) + "\n"


def _load_rows_from_db() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str | None]]:
    db_url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
    engine = create_engine(db_url, pool_pre_ping=True)
    annual_q = text("""
        SELECT fam.symbol, fam.company_name, fam.statement_year, fam.metric_name, fam.metric_value,
               fam.as_of_date, fam.source_document_id, fsd.publication_date
        FROM fundamental_annual_metric fam
        LEFT JOIN fundamental_source_document fsd ON fsd.id = fam.source_document_id
        WHERE fam.statement_year >= 2016
        ORDER BY fam.symbol, fam.statement_year, fam.metric_name
    """)
    period_q = text("""
        SELECT fpm.symbol, fpm.company_name, fpm.fiscal_year AS statement_year,
               fpm.period_type, fpm.period_label, fpm.period_end_date,
               fpm.metric_name, fpm.metric_value, fpm.source_document_id,
               fsd.publication_date
        FROM fundamental_period_metric fpm
        LEFT JOIN fundamental_source_document fsd ON fsd.id = fpm.source_document_id
        WHERE fpm.fiscal_year >= 2016
        ORDER BY fpm.symbol, fpm.fiscal_year, fpm.period_type, fpm.metric_name
    """)
    consensus_q = text("""
        SELECT symbol, fiscal_year, metric, value, source, as_of_date
        FROM fundamental_consensus_estimate
        ORDER BY symbol, fiscal_year, metric, as_of_date
    """)
    sector_q = text("SELECT symbol, sector FROM stock_master WHERE symbol IS NOT NULL")
    with engine.connect() as conn:
        annual = [dict(r._mapping) for r in conn.execute(annual_q)]
        try:
            period = [dict(r._mapping) for r in conn.execute(period_q)]
        except Exception:
            period = []
        try:
            consensus = [dict(r._mapping) for r in conn.execute(consensus_q)]
        except Exception:
            consensus = []
        sectors = {str(r[0]).strip().upper(): (str(r[1]).strip() if r[1] else None) for r in conn.execute(sector_q)}
    return annual, period, consensus, sectors


def _build_price_loader() -> tuple[Any, dict[str, pd.Series | None]]:
    import boto3

    db_url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
    s3_endpoint = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin")
    s3_bucket = os.environ.get("S3_BUCKET", "quant-artifacts")
    s3 = boto3.client("s3", endpoint_url=s3_endpoint, aws_access_key_id=access_key, aws_secret_access_key=secret_key)
    engine = create_engine(db_url, pool_pre_ping=True)
    keys: dict[str, str] = {}
    with engine.connect() as conn:
        for r in conn.execute(text("SELECT symbol, object_key FROM market_data_store WHERE timeframe='1D' AND object_key IS NOT NULL")):
            keys[str(r[0]).strip().upper()] = str(r[1])
    cache: dict[str, pd.Series | None] = {}

    def load(symbol: str) -> pd.Series | None:
        sym = str(symbol).strip().upper()
        if sym in cache:
            return cache[sym]
        key = keys.get(sym)
        if not key:
            cache[sym] = None
            return None
        try:
            resp = s3.get_object(Bucket=s3_bucket, Key=key)
            df = pd.read_parquet(BytesIO(resp["Body"].read()))
            if not isinstance(df.index, pd.DatetimeIndex):
                for col in ("timestamp", "Timestamp", "date", "Date"):
                    if col in df.columns:
                        df = df.set_index(col)
                        break
            df.index = pd.to_datetime(df.index).tz_localize(None)
            col = next((c for c in ("Close", "close", "Adj Close") if c in df.columns), None)
            cache[sym] = df[col].sort_index().dropna() if col else None
        except Exception:
            cache[sym] = None
        return cache[sym]

    return load, cache


def main() -> None:
    parser = argparse.ArgumentParser(description="PIT SFC cross-sectional IC study")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--out", default="docs/fundamentals-layer/61-sfc-ic-study-results.md")
    args = parser.parse_args()

    annual, period, consensus, sectors = _load_rows_from_db()
    universe = load_universe()
    price_loader, price_cache = _build_price_loader()
    cfg = PanelConfig(
        start=pd.Timestamp(args.start).date() if args.start else None,
        end=pd.Timestamp(args.end).date() if args.end else None,
    )
    panel = build_pit_panel(
        annual_rows=annual,
        period_rows=period,
        consensus_rows=consensus,
        price_loader=price_loader,
        universe_df=universe,
        config=cfg,
        sectors=sectors,
    )
    result = run_study(panel, price_by_symbol=price_cache)
    markdown = format_results_markdown(result)
    Path(args.out).write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"Wrote {args.out}")
    print(f"GATE VERDICT: {result['verdict']}")


if __name__ == "__main__":
    main()
