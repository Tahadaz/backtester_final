# Phase 2 Scoping Note

## Context

Phase 1 delivers research-panel-only evaluation of six pre-registered macroeconomic factor signals. Results are published in `docs/research/phase1_results.md` with FDR-adjusted verdicts. Phase 2 is **conditional on Phase 1 evidence justifying operational integration**.

## What Phase 2 Would Be

Phase 2 integrates **profitable factor signals** into the live signal engine for conditional composite strategies. Specifically:

### Scope: TA × Macro Composition

If Phase 1 shows one or more signals with:
- **DSR > 0** (defensible Sharpe after overfitting penalty)
- **PSR > 0.80** (>80% posterior probability Sharpe > 0)
- **FDR pass at q=0.10** (survives multiple-testing correction)
- **Positive out-of-sample Sharpe net of costs** on ≥3 distinct sectors

Then Phase 2 would design a **composition layer** combining factor signals with existing TA signals:

```
Composite Signal = f( TA signals, Factor signals, regime state )
```

Example compositions:
- **Risk-sentiment gate**: Ignore all long signals when VIX z-score is critical; elevate short bias.
- **Channel amplification**: When BRENT momentum is positive, amplify long signals for materials/mining.
- **Conditional entry/exit**: Use SP500+VIX confirmation to gate high-frequency (h=1d) TA signals; use Brent for h=5d.

### Scope: Variant & Strategy Adaptation

Each strategy adapter (MACross, RSI, MACD, Bollinger, OBV, StochVWAP, Ichimoku) would gain:

1. **Optional factor-signal input** — TA rules remain unchanged; factors are layered on top.
2. **New registry entry** — `FactorVariantSignal(base_ta_spec, factor_specs, composition_fn)`.
3. **Updated `make_signal_arrays_fast()`** — compute factor signals alongside TA indicators, then combine.

### Scope: New Pre-Registration

Operational integration requires a **new pre-registration** (separate from Phase 1) that freezes:
- Which factor signals are active (based on Phase 1 FDR verdicts).
- Composition logic (e.g., weights, gates, thresholds).
- Live-trading decision rules (entry/exit protocols, position sizing, max leverage).
- Holdout test period and go-live gates (e.g., "only go live if holdout Sharpe > 0.3 for 30 days").

## Evidence Required for Phase 2 Justification

Phase 2 is conditional on **ALL** of the following:

| Condition | Reason |
|-----------|--------|
| ≥1 signal shows DSR > 0 | Defensible alpha after overfitting haircut |
| ≥1 signal shows PSR > 0.80 | >80% confidence Sharpe > 0, not chance |
| ≥1 signal passes FDR at q=0.10 | Survives correction for 6-signal search |
| ≥3 stocks show fdr_pass=true for ≥1 signal | Generalizability across universe |
| Sharpe net of 33 bps commission is positive | Survives realistic Moroccan market costs |
| IC decay < 0.3 at any horizon | Signal is stable, not lucky mean-reversion |

If Phase 1 shows **all signals with DSR < 0 and PSR < 0.5**, Phase 2 is **cancelled** — the evidence does not support operational deployment.

## Data-Mining Risks Mitigated by Phase 1 Design

### Multiple Comparisons
- **6 signals × 8 seed stocks × 5 horizons = 240 tests**.
- Benjamini-Hochberg FDR at q=0.10 controls false-discovery rate; expect ~24 false rejections tolerated.
- Any signal passing FDR has <10% risk of being spurious across the cohort.

### Overfitting Penalties
- **DSR (Deflated Sharpe)**: Penalizes Sharpe for number of trials and variance of trial outcomes.
- **Bootstrap CI**: Re-sampling under the null distributes Sharpe estimates; narrow CI suggests genuine signal, wide CI suggests noise.
- **PSR (Probabilistic Sharpe)**: Bayesian shrinkage toward zero; high PSR requires both large Sharpe and low uncertainty.

### Replicability Safeguards
- **Pre-registration locks rules** — no post-hoc tweaking to chase results.
- **Out-of-sample evaluation** — we evaluate on all available history, not train/test split; this is intentional to maximize data and is addressed by Newey-West t-stat (blocks for autocorrelation).
- **Economic interpretation required** — each signal has an academic citation and economic narrative (e.g., "yield shock → duration headwind"); nonsensical correlations are unlikely to replicate.

## Phase 2 Failure Modes

Even if Phase 1 justifies Phase 2 initiation, operational deployment can fail:

| Failure Mode | Mitigation |
|--------------|-----------|
| **Live market costs exceed backtest estimates** | Pre-registration lock on 33 bps; live cost monitoring. |
| **Regime change (structural break)** | Set go-live gate: holdout Sharpe > 0.3 for 30 trading days. |
| **Liquidity issues in live execution** | Start with seed symbols only; auto-expand off until holdout period passes. |
| **Drawdown tolerance exceeded** | Position sizing tied to DSR confidence interval width. |
| **Composition creates collinearity** | Correlation analysis in Phase 2 pre-registration design. |

## Phase 2 Initiation Decision

**Timeline**: Phase 1 results ready ~2026-05-15 (after eval completion and write-up).

**Decision Gate**: Once `phase1_results.md` is filled with verdicts:
1. **If 0 signals pass FDR** → close Phase 1 as honest null; phase 2 not initiated.
2. **If 1–2 signals pass FDR with DSR > 0** → Phase 2 is **optional** (low confidence; requires supervisor approval).
3. **If 3+ signals pass FDR with DSR > 0 and PSR > 0.80** → Phase 2 is **recommended** (high confidence; initiate pre-registration design).

## Composition Design (Preliminary)

If Phase 2 is approved, the composition layer will be designed as:

```python
def composite_signal(
    ta_signal: pd.Series,           # from existing TA strategy
    factor_signals: dict[str, pd.Series],  # from Phase 1 winners
    regime_label: str = "neutral"   # from regime detection
) -> pd.Series:
    """
    Combine TA and factor signals.
    Returns composite signal in {-2, -1, 0, +1, +2} with strength modulation.
    """
    ...
```

The exact logic (e.g., multiplication vs gating vs amplitude modulation) will be frozen in a new pre-registration before any Phase 2 backtests run.

## Summary

**Phase 2 is not automatic.** It is contingent on Phase 1 evidence showing:
- Statistical significance (FDR pass) on multiple signals
- Practical robustness (DSR > 0, PSR > 0.8)
- Generalizability (pass on ≥3 stocks)

If Phase 1 reveals honest nulls, Phase 2 is **not initiated**, and the project pivots to alternative factor research or TA refinement per supervisory guidance.
