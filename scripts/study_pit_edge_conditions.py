from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION, _execution_details
from core.quant_core.research.masi_condition_discovery import (
    DEFAULT_FEATURES,
    DiscoveryConfig,
    run_horizon_study,
)
from services.api.app import models
from services.api.app.db import _ensure_session_factory
from services.worker.tasks.historical_portfolio_backtest import _load_prices, _opportunity_from_json


def _normalized_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    index = pd.DatetimeIndex(pd.to_datetime(data.index))
    if index.tz is not None:
        index = index.tz_localize(None)
    data.index = index.normalize()
    return data[~data.index.duplicated(keep="last")].sort_index()


def _column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    return next((name for name in names if name in frame.columns), None)


def _market_features(frame: pd.DataFrame, decision_date: Any, prefix: str) -> dict[str, float | None]:
    data = _normalized_frame(frame)
    data = data.loc[data.index <= pd.Timestamp(decision_date).normalize()]
    close_column = _column(data, ("Close", "close", "Adj Close"))
    if close_column is None or data.empty:
        return {}
    close = pd.to_numeric(data[close_column], errors="coerce").dropna()
    returns = close.pct_change().dropna()
    output: dict[str, float | None] = {}
    for window in (20, 60, 120):
        output[f"{prefix}_return_{window}"] = (
            float(close.iloc[-1] / close.iloc[-window - 1] - 1.0) if len(close) > window else None
        )
    for window in (20, 60):
        output[f"{prefix}_volatility_{window}"] = (
            float(returns.tail(window).std(ddof=1) * np.sqrt(252.0)) if len(returns) >= window else None
        )
    output[f"{prefix}_drawdown_60"] = (
        float(close.iloc[-1] / close.tail(60).max() - 1.0) if len(close) >= 20 else None
    )
    for window in (50, 200):
        output[f"{prefix}_ma_distance_{window}"] = (
            float(close.iloc[-1] / close.tail(window).mean() - 1.0) if len(close) >= window else None
        )
    volume_column = _column(data, ("Volume", "volume"))
    if prefix == "stock" and volume_column is not None:
        volume = pd.to_numeric(data[volume_column], errors="coerce")
        aligned = pd.concat([close.rename("close"), volume.rename("volume")], axis=1).dropna().tail(20)
        output["stock_adv20"] = float((aligned["close"] * aligned["volume"]).mean()) if len(aligned) == 20 else None
    return output


def _benchmark_return(
    frame: pd.DataFrame,
    *,
    entry_date: Any,
    exit_date: Any,
    entry_kind: str,
    exit_kind: str,
) -> float | None:
    data = _normalized_frame(frame)
    entry_column = _column(data, ("Open", "open")) if entry_kind == "open" else _column(data, ("Close", "close", "Adj Close"))
    exit_column = _column(data, ("Open", "open")) if exit_kind == "open" else _column(data, ("Close", "close", "Adj Close"))
    entry = pd.Timestamp(entry_date).normalize()
    exit_ = pd.Timestamp(exit_date).normalize()
    if entry_column is None or exit_column is None or entry not in data.index or exit_ not in data.index:
        return None
    entry_price = float(data.loc[entry, entry_column])
    exit_price = float(data.loc[exit_, exit_column])
    return exit_price / entry_price - 1.0 if entry_price > 0 else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if pd.isna(value) if not isinstance(value, (str, bool)) else False:
        return None
    return value


def build_candidate_frame(db, methodology: str, cost_bps: float, slippage_bps: float):
    runs = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
        methodology_version=methodology,
    ).order_by(models.HistoricalOpportunityMaterializationRun.created_at.asc()).all()
    succeeded_ids = [row.id for row in runs if row.status == "succeeded"]
    masi_symbols = {
        str(row.symbol).upper()
        for row in db.query(models.StockMaster).filter(
            models.StockMaster.market_region == "masi",
            models.StockMaster.asset_type == "equity",
        ).all()
    }
    stored = (
        db.query(models.HistoricalTradeOpportunity).filter(
            models.HistoricalTradeOpportunity.materialization_run_id.in_(succeeded_ids),
            models.HistoricalTradeOpportunity.symbol.in_(sorted(masi_symbols)),
        ).all()
        if succeeded_ids else []
    )
    prices = _load_prices(db, sorted({row.symbol.upper() for row in stored} | {"MASI"}))
    masi = prices.get("MASI")
    total_cost = 2.0 * (float(cost_bps) + float(slippage_bps)) / 10_000.0
    records: list[dict[str, Any]] = []
    for row in stored:
        opportunity = _opportunity_from_json(row.opportunity_json or {})
        stock_frame = prices.get(opportunity.symbol.upper())
        execution = _execution_details(opportunity, stock_frame) if stock_frame is not None else None
        if execution is None or masi is None:
            continue
        masi_return = _benchmark_return(
            masi,
            entry_date=execution["entry_date"], exit_date=execution["exit_date"],
            entry_kind=opportunity.entry_price_kind, exit_kind=opportunity.exit_price_kind,
        )
        if masi_return is None:
            continue
        direction_sign = 1.0 if opportunity.direction == "long" else -1.0
        gross = (execution["exit_price"] / execution["entry_price"] - 1.0) * direction_sign
        net = float(gross - total_cost)
        provenance = opportunity.provenance or {}
        components = provenance.get("edge_score_components") or {}
        rank = list(opportunity.rank) + [0.0] * (4 - len(opportunity.rank))
        bucket_strength = {
            "strong_sell": -2.0, "sell": -1.0, "neutral": 0.0,
            "buy": 1.0, "strong_buy": 2.0,
        }.get(str(opportunity.bucket).lower(), 0.0)
        record = {
            "decision_date": opportunity.decision_date,
            "entry_date": execution["entry_date"], "exit_date": execution["exit_date"],
            "symbol": opportunity.symbol.upper(), "horizon": opportunity.horizon,
            "variant": opportunity.variant, "bucket": opportunity.bucket,
            "signal_strength": bucket_strength,
            "realized_net_return": net, "masi_return": float(masi_return),
            "masi_alpha": float(net - masi_return),
            "rank_proven": float(rank[0]), "rank_edge": float(rank[1]),
            "rank_ci": float(rank[2]), "rank_expected": float(rank[3]),
            "edge_score": provenance.get("edge_score"),
            "expected_return_net": provenance.get("expected_return_net"),
            "ci_lower_net": provenance.get("ci_lower_net"),
            "hit_ci_lower": provenance.get("hit_ci_lower"),
            "proof_n": provenance.get("n", provenance.get("proof_n")),
            "mc_luck_pvalue_net_adj": provenance.get("mc_luck_pvalue_net_adj"),
            "label_shuffle_pvalue_net_adj": provenance.get("label_shuffle_pvalue_net_adj"),
        }
        for name in ("sample_n", "bootstrap_er", "wilson", "mc_luck", "label_shuffle", "freshness"):
            record[f"component_{name}"] = components.get(name)
        record.update(_market_features(stock_frame, opportunity.decision_date, "stock"))
        record.update(_market_features(masi, opportunity.decision_date, "masi"))
        records.append(record)
    return pd.DataFrame(records), runs


def _markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# MASI PIT Condition Discovery", "",
        f"- Status: **{payload['status']}**",
        f"- Methodology: `{payload['methodology']}`",
        f"- Candidate rows: {payload['candidate_rows']}",
        f"- Decision dates: {payload['decision_dates']}",
        f"- Symbols: {payload['symbols']}",
        "- Universe: data-backed Moroccan equities tagged `market_region=masi`; exact historical index membership is unavailable.",
        "- Objective: positive net return after costs and positive same-window MASI alpha.", "",
        "## Horizon results", "",
        "| Horizon | Status | OOS trades | Net return (95% CI) | MASI alpha (95% CI) | Final rules |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for result in payload["horizons"]:
        policy = result.get("final_policy") or {}
        rules = " AND ".join(
            f"{rule['feature']} {rule['operator']} {rule['threshold']:.6g}" for rule in policy.get("rules") or []
        ) or "None"
        lines.append(
            f"| {result['horizon']} | {result['status']} ({result.get('validation_status', result['status'])}) | {result['outer_trade_count']} | "
            f"{result.get('outer_mean_net_return')} {result.get('outer_mean_net_return_ci95')} | "
            f"{result.get('outer_mean_masi_alpha')} {result.get('outer_mean_masi_alpha_ci95')} | {rules} |"
        )
    lines.extend([
        "", "## Rejected and lower-ranked rules", "",
    ])
    for result in payload["horizons"]:
        lines.append(f"### {result['horizon'].title()}")
        alternatives = ((result.get("final_policy") or {}).get("rejected_rule_examples") or [])[:3]
        if not alternatives:
            lines.append("No evaluable alternatives.")
        for item in alternatives:
            rules = " AND ".join(
                f"{rule['feature']} {rule['operator']} {rule['threshold']:.6g}" for rule in item["rules"]
            )
            lines.append(
                f"- `{rules}` - net={item['mean_net_return']}, alpha={item['mean_masi_alpha']}, "
                f"q={item['alpha_qvalue']}; reasons: {', '.join(item['rejection_reasons'])}."
            )
        lines.append("")
    lines.extend([
        "", "## Approval rule", "",
        "A policy is accepted only with at least 15 outer-fold trades, positive 95% lower bounds for both net return and MASI alpha, positive alpha in a majority of folds, leave-one-symbol-out stability, and corrected inner-search significance.",
        "", "No production trading policy is changed by this report.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover transparent PIT MASI-alpha trading conditions.")
    parser.add_argument("--methodology", default=METHODOLOGY_VERSION)
    parser.add_argument("--output-dir", default="results/pit_edge_condition_discovery")
    parser.add_argument("--cost-bps-per-side", type=float, default=33.0)
    parser.add_argument("--slippage-bps-per-side", type=float, default=5.0)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--min-train-dates", type=int, default=52)
    parser.add_argument("--outer-test-dates", type=int, default=13)
    parser.add_argument("--seed", type=int, default=5107)
    args = parser.parse_args()

    db = _ensure_session_factory()()
    frame, runs = build_candidate_frame(
        db, args.methodology, args.cost_bps_per_side, args.slippage_bps_per_side,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_dir / "pit_candidates.csv", index=False)
    run_statuses = Counter(row.status for row in runs)
    coverage_complete = bool(runs) and all(row.status == "succeeded" for row in runs)
    config = DiscoveryConfig(
        min_train_dates=args.min_train_dates, outer_test_dates=args.outer_test_dates,
        bootstrap_samples=args.bootstrap_samples, seed=args.seed,
    )
    horizon_payloads = []
    outer_frames = []
    for horizon in ("weekly", "monthly", "quarterly"):
        result = run_horizon_study(frame, horizon=horizon, features=DEFAULT_FEATURES, config=config)
        outer = result.pop("outer_rows")
        if len(outer):
            outer_frames.append(outer)
        if not coverage_complete:
            result["validation_status"] = result["status"]
            result["status"] = "preliminary"
        horizon_payloads.append(result)
    outer_output = pd.concat(outer_frames, ignore_index=True) if outer_frames else pd.DataFrame()
    outer_output.to_csv(output_dir / "outer_holdout_trades.csv", index=False)
    payload = {
        "status": "complete" if coverage_complete else "preliminary",
        "approval_eligible": coverage_complete,
        "methodology": args.methodology,
        "run_statuses": dict(run_statuses),
        "candidate_rows": len(frame),
        "decision_dates": int(frame["decision_date"].nunique()) if len(frame) else 0,
        "symbols": int(frame["symbol"].nunique()) if len(frame) else 0,
        "cost_bps_per_side": args.cost_bps_per_side,
        "slippage_bps_per_side": args.slippage_bps_per_side,
        "features": list(DEFAULT_FEATURES),
        "config": asdict(config),
        "horizons": horizon_payloads,
    }
    clean = _jsonable(payload)
    (output_dir / "study.json").write_text(json.dumps(clean, indent=2), encoding="utf-8")
    (output_dir / "REPORT.md").write_text(_markdown_report(clean), encoding="utf-8")
    print(json.dumps({
        "status": clean["status"], "output_dir": str(output_dir),
        "candidate_rows": clean["candidate_rows"],
        "horizons": [{"horizon": row["horizon"], "status": row["status"]} for row in clean["horizons"]],
    }, indent=2))


if __name__ == "__main__":
    main()
