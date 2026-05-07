# Overview and Research Question

## Station Mandate

This layer adds two tightly coupled deliverables, in order:

1. **A rigorous signal-evaluation dashboard** measuring OOS predictive ability of existing TA signals on short horizons (1/2/3/5/10 day forward returns), with the full statistical battery a trading desk would expect.
2. **A macro-factor research layer** — ingestion of VIX / SP500 / Brent / DXY / EURUSD / US10Y, calendar-aware alignment, per-stock descriptive relevance study, then pure factor-only strategies evaluated in the same dashboard.

Phase 2 (conditional factor × TA composition) is **explicitly deferred** until Phase 0–1 results are in. This protects against the data-mining trap.

---

## Research Question (Bank-Grade Framing)

> *Do macro-state indicators (VIX, DXY, Brent, SP500, EURUSD, US10Y) improve the out-of-sample risk-adjusted performance of signals on MASI equities, beyond what each signal set produces alone, after controlling for multiple testing and transaction costs?*

**Null hypothesis**: No macro factor improves the OOS Sharpe of any TA signal family on any MASI equity after BH-FDR correction at q = 0.10.

**This is testable, pre-registered, and comparable to a baseline.**

---

## Context: Why This Layer Exists

The signal engine produces TA signals through the A–G pipeline and WFO. Two prior regime attempts:
- Kaufman ER in `signal_engine/regime.py`
- SMA200+ADX in `decision/regime.py`

…are stock-internal only (no macro inputs) and collapse to equal weights under the OOS gate. There is no macro factor infrastructure, no cross-market calendar alignment, and critically **no statistical evaluation surface** proving current signals have OOS predictive ability. Without that surface, there is no scientific way to prove a future factor layer adds value.

---

## Scope

| | Phase 0 | Phase 1 | Phase 2 (deferred) |
|---|---|---|---|
| Signal stats dashboard (existing TA) | ✅ | — | — |
| Macro data ingestion + calendar alignment | ✅ | — | — |
| Descriptive factor-relevance per stock (FDR-controlled) | ✅ | — | — |
| Pure factor-only strategies | — | ✅ | — |
| Conditional TA × factor composition | — | — | separate plan |

---

## Methodology Posture

Literature-backed, pre-registered, FDR-controlled, with honest null reporting.

**A result of "no factor improves signal X for stock Y" is a deliverable, not a failure.**

Every metric on the dashboard is cited. Every Phase 1 rule is frozen in `docs/research/phase1_pre_registration.yaml` before any backtest runs. No post-hoc parameter tuning.

---

## What This Layer Does NOT Do

- Modify `signal_engine/ensemble.py` weighting
- Change any existing regime path (`signal_engine/regime.py`, `decision/regime.py`)
- Add fundamental data
- HMM / Bayesian shrinkage / horseshoe priors (deferred pending Phase 0–1 results)
- Live trading integration
- Nikkei ingestion (no plausible channel to MASI; correlation is a spurious proxy of global risk already captured by VIX)
