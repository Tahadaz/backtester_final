# Overview and Research Question

## Station Mandate

This layer adds three tightly coupled deliverables:

1. **A rigorous signal-evaluation dashboard** measuring OOS predictive ability of existing TA signals with a desk-grade statistical battery.
2. **A macro-factor research layer** covering VIX, SP500, Brent, DXY, EURUSD, and US10Y ingestion, calendar-aware alignment, descriptive relevance, and pure factor-only strategies.
3. **A production Factor x TA runtime** where selected macro factors gate existing TA variants through a no-look-ahead AND composition persisted under `variant='factor_x_ta'`.

Phase 2 is implemented as an additive runtime path. The empirical claim is still conditional: Factor x TA must beat the native TA baseline under the registered tests before it can be described as value-adding.

---

## Research Question

> Do macro-state indicators improve the out-of-sample risk-adjusted performance of signals on MASI equities beyond what each native TA signal set produces alone, after controlling for multiple testing and transaction costs?

**Null hypothesis**: No macro factor improves the OOS Sharpe of any TA signal family on any MASI equity after the registered multiple-testing controls.

This is testable, pre-registered, and comparable to a native TA baseline.

---

## Why This Layer Exists

The native signal engine produces TA signals through the A-G pipeline and WFO. Prior regime paths were stock-internal only:

- Kaufman ER in `signal_engine/regime.py`
- SMA200+ADX in `decision/regime.py`

The factor layer adds macro ingestion, cross-market calendar alignment, factor selection, and `factor_x_ta` replay so macro-conditioned claims can be tested without mutating native TA behavior.

---

## Scope

| Capability | Phase 0 | Phase 1 | Phase 2 |
|---|---|---|---|
| Signal stats dashboard for existing TA | Done | - | - |
| Macro data ingestion and calendar alignment | Done | - | - |
| Descriptive factor relevance per stock | Done | - | - |
| Pure factor-only strategies | - | Done | - |
| Conditional Factor x TA composition | - | - | Implemented |
| Factor x TA WFO and replay/backtest | - | - | Implemented |

---

## Methodology Posture

The layer is literature-backed, pre-registered, FDR-controlled, and explicit about null outcomes.

A result of "no factor improves signal X for stock Y" is a deliverable, not a failure.

Phase 1 and Phase 2 rule definitions are frozen under `services/worker/research/`. No post-hoc parameter tuning should be introduced in code or documentation.

---

## What This Layer Does Not Do

- Change native `legacy` or `expanded` Signal Engine/WFO behavior.
- Add fundamental data.
- Guarantee every stock/horizon has selected macro factors.
- Treat no-signal Factor x TA outcomes as crashes.
- Add live trading integration.
- Add HMM/Bayesian shrinkage/horseshoe priors; those remain future research.
