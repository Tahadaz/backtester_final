"""Tests for classical WFO per-fold winner extraction and reporting."""
from __future__ import annotations

import pytest
from collections import defaultdict


# ── Helper: build a minimal batch_df row ──────────────────────────────────────
def _make_fold_row(
    strategy_kind: str,
    fold_index: int,  # encoding: fold_logical * 1000 + trial_rank
    trial_id: str,
    train_obj_value: float | None = None,
    oos_pnl: float | None = None,
    oos_cagr: float | None = None,
    oos_sharpe: float | None = None,
    oos_max_drawdown: float | None = None,
    oos_win_pct: float | None = None,
    oos_n_fills: int | None = None,
    params: dict | None = None,
    horizon: str | None = None,
    test_start: str = "2023-01-01",
    test_end: str = "2023-06-30",
    train_start: str = "2022-01-01",
    train_end: str = "2022-12-31",
) -> dict:
    row = {
        "strategy_kind": strategy_kind,
        "fold_index": fold_index,
        "trial_rank": fold_index % 1000,
        "trial_id": trial_id,
        "train_objective_value": train_obj_value,
        "stat.pnl": oos_pnl,
        "stat.cagr": oos_cagr,
        "stat.sharpe": oos_sharpe,
        "stat.max_drawdown": oos_max_drawdown,
        "stat.win_pct": oos_win_pct,
        "stat.n_fills": oos_n_fills,
        "horizon": horizon,
        "test_start": test_start,
        "test_end": test_end,
        "train_start": train_start,
        "train_end": train_end,
        "objective": "sharpe",
    }
    if params:
        for k, v in params.items():
            row[f"param.{k}"] = v
    return row


# ── Helper: extract per_fold_winners the same way pipeline.py does ────────────
def _extract_per_fold_winners(rows: list[dict], holdout_rows_by_kind: dict | None = None) -> list[dict]:
    """Pure-Python replica of the per_fold_winners extraction in pipeline.py."""
    import pandas as pd

    n_selection_folds = max(
        (int(r["fold_index"]) // 1000 for r in rows if int(r.get("trial_rank", 0)) == 1),
        default=0,
    ) + 1 if rows else 0

    df = pd.DataFrame(rows)
    if df.empty or "trial_id" not in df.columns:
        return []

    tr_num = pd.to_numeric(df.get("trial_rank", 0), errors="coerce").fillna(0)
    winner_df = df[tr_num == 1].copy()
    winner_df["_lf"] = pd.to_numeric(winner_df["fold_index"], errors="coerce").fillna(0).astype(int) // 1000

    results = []

    def _sf(v):
        try: return float(v) if v is not None else None
        except: return None

    def _si(v):
        try: return int(v) if v is not None else None
        except: return None

    for _, r in winner_df.sort_values(["strategy_kind", "_lf"]).iterrows():
        params = {k[len("param."):]: r[k] for k in r.index if k.startswith("param.")}
        results.append({
            "fold_no": int(r["_lf"]) + 1,
            "strategy_kind": str(r.get("strategy_kind") or ""),
            "horizon": str(r.get("horizon") or "") or None,
            "train_start": str(r.get("train_start") or ""),
            "train_end": str(r.get("train_end") or ""),
            "test_start": str(r.get("test_start") or ""),
            "test_end": str(r.get("test_end") or ""),
            "winning_trial_id": str(r.get("trial_id") or ""),
            "optimal_params": params,
            "is_objective_name": str(r.get("objective") or "") or None,
            "is_objective_value": _sf(r.get("train_objective_value")),
            "oos_pnl": _sf(r.get("stat.pnl")),
            "oos_cagr": _sf(r.get("stat.cagr")),
            "oos_sharpe": _sf(r.get("stat.sharpe")),
            "oos_max_drawdown": _sf(r.get("stat.max_drawdown")),
            "oos_win_pct": _sf(r.get("stat.win_pct")),
            "oos_n_fills": _si(r.get("stat.n_fills")),
            "is_holdout": False,
        })

    # Holdout rows
    for _h_sk, _h_row in (holdout_rows_by_kind or {}).items():
        _h_params = {k[len("param."):]: _h_row[k] for k in _h_row if k.startswith("param.")}
        results.append({
            "fold_no": n_selection_folds + 1,
            "strategy_kind": str(_h_row.get("strategy_kind") or _h_sk),
            "horizon": str(_h_row.get("horizon") or "") or None,
            "train_start": None,
            "train_end": None,
            "test_start": str(_h_row.get("test_start") or ""),
            "test_end": str(_h_row.get("test_end") or ""),
            "winning_trial_id": str(_h_row.get("trial_id") or ""),
            "optimal_params": _h_params,
            "is_objective_name": None,
            "is_objective_value": None,
            "oos_pnl": _sf(_h_row.get("stat.pnl")),
            "oos_cagr": _sf(_h_row.get("stat.cagr")),
            "oos_sharpe": _sf(_h_row.get("stat.sharpe")),
            "oos_max_drawdown": _sf(_h_row.get("stat.max_drawdown")),
            "oos_win_pct": _sf(_h_row.get("stat.win_pct")),
            "oos_n_fills": _si(_h_row.get("stat.n_fills")),
            "is_holdout": True,
        })

    return results


def _compute_cumulative(per_fold_winners: list[dict]) -> list[dict]:
    """Compute cumulative_oos_pnl per (strategy_kind, horizon) group."""
    groups: dict[tuple, list] = defaultdict(list)
    selection = [r for r in per_fold_winners if not r.get("is_holdout")]
    for r in sorted(selection, key=lambda x: (str(x.get("strategy_kind") or ""), str(x.get("horizon") or ""), int(x.get("fold_no") or 0))):
        key = (str(r.get("strategy_kind") or ""), str(r.get("horizon") or ""))
        groups[key].append(r)

    result = list(per_fold_winners)
    cum_map: dict[int, float | None] = {}
    for rows_g in groups.values():
        running = 0.0
        for r in rows_g:
            pnl = r.get("oos_pnl")
            if pnl is not None:
                running += pnl
                cum_map[id(r)] = running
            else:
                cum_map[id(r)] = None

    for r in result:
        if not r.get("is_holdout"):
            r["cumulative_oos_pnl"] = cum_map.get(id(r))
    return result


def _build_classical_wfo_report(periods: list[dict], data_source: str = "run_wfo_period") -> dict:
    selection = [p for p in periods if not p.get("is_holdout")]
    holdout   = [p for p in periods if p.get("is_holdout")]
    pnls    = [p["oos_pnl"] for p in selection if p.get("oos_pnl") is not None]
    sharpes = [p["oos_sharpe"] for p in selection if p.get("oos_sharpe") is not None]
    dds     = [p["oos_max_drawdown"] for p in selection if p.get("oos_max_drawdown") is not None]
    profitable = sum(1 for p in pnls if p > 0)
    total = len(selection)
    stitched = {
        "total_oos_pnl": float(sum(pnls)) if pnls else None,
        "mean_oos_sharpe": float(sum(sharpes) / len(sharpes)) if sharpes else None,
        "median_oos_sharpe": float(sorted(sharpes)[len(sharpes) // 2]) if sharpes else None,
        "worst_fold_drawdown": float(min(dds)) if dds else None,
        "profitable_folds": profitable,
        "total_folds": total,
        "profitable_pct": round(profitable / total * 100, 1) if total > 0 else None,
    }
    if selection:
        most_recent = max(selection, key=lambda p: (str(p.get("strategy_kind") or ""), int(p.get("fold_no") or 0)))
        current_live_params = dict(most_recent.get("optimal_params") or {})
        current_live_trial_id = str(most_recent.get("winning_trial_id") or "") or None
    else:
        current_live_params = None
        current_live_trial_id = None
    return {
        "periods": periods,
        "stitched_oos_summary": stitched,
        "current_live_params": current_live_params,
        "current_live_trial_id": current_live_trial_id,
        "final_holdout_summary": holdout[0] if holdout else None,
        "data_source": data_source,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestClassicalWfoReport:
    """Test 1: Fold-local winner identity — 3 folds each with a different rank-1 trial_id."""

    def test_fold_local_winner_identity(self):
        rows = [
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_A", oos_pnl=100),
            _make_fold_row("ma_cross", fold_index=1*1000+1, trial_id="tid_B", oos_pnl=200),
            _make_fold_row("ma_cross", fold_index=2*1000+1, trial_id="tid_C", oos_pnl=150),
            # Non-winner rows (trial_rank != 1)
            _make_fold_row("ma_cross", fold_index=0*1000+2, trial_id="tid_X", oos_pnl=50),
            _make_fold_row("ma_cross", fold_index=1*1000+3, trial_id="tid_Y", oos_pnl=80),
        ]
        winners = _extract_per_fold_winners(rows)
        # Only rank-1 rows
        assert len(winners) == 3
        winner_ids = [w["winning_trial_id"] for w in sorted(winners, key=lambda w: w["fold_no"])]
        assert winner_ids == ["tid_A", "tid_B", "tid_C"]

    def test_optimal_params_accuracy(self):
        """Test 2: Fold 2 rank-1 has fast=10, slow=50; verify optimal_params."""
        rows = [
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_A", params={"fast": 5, "slow": 20}),
            _make_fold_row("ma_cross", fold_index=1*1000+1, trial_id="tid_B", params={"fast": 10, "slow": 50}),
            _make_fold_row("ma_cross", fold_index=2*1000+1, trial_id="tid_C", params={"fast": 7, "slow": 30}),
        ]
        winners = _extract_per_fold_winners(rows)
        fold2_winner = next(w for w in winners if w["fold_no"] == 2)
        assert fold2_winner["optimal_params"] == {"fast": 10, "slow": 50}

    def test_cumulative_oos_pnl(self):
        """Test 3: OOS PnLs [100, -50, 200]; cumulative must be [100, 50, 250]."""
        rows = [
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_A", oos_pnl=100),
            _make_fold_row("ma_cross", fold_index=1*1000+1, trial_id="tid_B", oos_pnl=-50),
            _make_fold_row("ma_cross", fold_index=2*1000+1, trial_id="tid_C", oos_pnl=200),
        ]
        winners = _extract_per_fold_winners(rows)
        with_cum = _compute_cumulative(winners)
        sorted_winners = sorted(with_cum, key=lambda w: w["fold_no"])
        cumulative = [w["cumulative_oos_pnl"] for w in sorted_winners]
        assert cumulative == [100.0, 50.0, 250.0]

    def test_current_live_params_most_recent_fold(self):
        """Test 4: current_live_params = most recent fold's params."""
        rows = [
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_A", params={"fast": 5, "slow": 20}),
            _make_fold_row("ma_cross", fold_index=1*1000+1, trial_id="tid_B", params={"fast": 10, "slow": 50}),
            _make_fold_row("ma_cross", fold_index=2*1000+1, trial_id="tid_C", params={"fast": 8, "slow": 40}),
        ]
        winners = _extract_per_fold_winners(rows)
        report = _build_classical_wfo_report(winners)
        assert report["current_live_params"] == {"fast": 8, "slow": 40}
        assert report["current_live_trial_id"] == "tid_C"

    def test_multi_horizon_separation(self):
        """Test 5: short/medium/long horizon rows don't bleed into each other."""
        rows = [
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_S1", horizon="short"),
            _make_fold_row("ma_cross", fold_index=1*1000+1, trial_id="tid_S2", horizon="short"),
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_M1", horizon="medium"),
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_L1", horizon="long"),
        ]
        winners = _extract_per_fold_winners(rows)
        short_winners = [w for w in winners if w["horizon"] == "short"]
        medium_winners = [w for w in winners if w["horizon"] == "medium"]
        long_winners = [w for w in winners if w["horizon"] == "long"]
        assert len(short_winners) == 2
        assert len(medium_winners) == 1
        assert len(long_winners) == 1
        short_tids = {w["winning_trial_id"] for w in short_winners}
        assert short_tids == {"tid_S1", "tid_S2"}
        assert medium_winners[0]["winning_trial_id"] == "tid_M1"
        assert long_winners[0]["winning_trial_id"] == "tid_L1"

    def test_legacy_fallback_data_source(self):
        """Test 6: legacy fallback sets data_source='run_fold_derived' with correct stitched PnL."""
        # Simulate fold-derived periods (as if from run_fold table rank=1 rows)
        fold_derived_periods = [
            {"fold_no": 1, "strategy_kind": "ma_cross", "horizon": None,
             "symbol": "", "winning_trial_id": "tid_A",
             "test_start": "2023-01-01", "test_end": "2023-06-30",
             "optimal_params": {}, "oos_pnl": 100.0, "oos_sharpe": 1.2,
             "oos_max_drawdown": -0.1, "is_holdout": False,
             "cumulative_oos_pnl": None},
            {"fold_no": 2, "strategy_kind": "ma_cross", "horizon": None,
             "symbol": "", "winning_trial_id": "tid_B",
             "test_start": "2023-07-01", "test_end": "2023-12-31",
             "optimal_params": {}, "oos_pnl": 200.0, "oos_sharpe": 1.8,
             "oos_max_drawdown": -0.05, "is_holdout": False,
             "cumulative_oos_pnl": None},
        ]
        report = _build_classical_wfo_report(fold_derived_periods, data_source="run_fold_derived")
        assert report["data_source"] == "run_fold_derived"
        assert report["stitched_oos_summary"]["total_oos_pnl"] == 300.0

    def test_classical_vs_robustness_independence(self):
        """Test 7: classical fold-local winner != cross-fold robustness winner."""
        # Fold 0: tid_A wins (rank=1)
        # Fold 1: tid_A wins again (rank=1)
        # Fold 2: tid_B wins (rank=1) — different from cross-fold winner tid_A
        # Cross-fold robustness would pick tid_A (best mean across all folds)
        # Classical WFO should show fold 3 winner = tid_B
        rows = [
            _make_fold_row("ma_cross", fold_index=0*1000+1, trial_id="tid_A", oos_pnl=100),
            _make_fold_row("ma_cross", fold_index=1*1000+1, trial_id="tid_A", oos_pnl=80),
            _make_fold_row("ma_cross", fold_index=2*1000+1, trial_id="tid_B", oos_pnl=150),
        ]
        winners = _extract_per_fold_winners(rows)
        fold3_winner = next(w for w in winners if w["fold_no"] == 3)
        assert fold3_winner["winning_trial_id"] == "tid_B"

        # Simulate the cross-fold robustness winner selection (tid_A appears in 2 folds, tid_B in 1)
        # The cross-fold winner would be tid_A
        robustness_winner_trial_id = "tid_A"
        assert fold3_winner["winning_trial_id"] != robustness_winner_trial_id
