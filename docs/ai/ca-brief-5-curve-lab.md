# Codex Brief 5 — Curve lab (cut-first scope)

**Program:** `docs/cross-asset-product/00-program-plan.md` — §4 guardrails binding. This brief is **D8: cut-first**. Nothing depends on it. If the token budget is thin after Brief 4, do not start it; the product is complete without it.
**Prerequisite:** Brief 4 merged and green (this reuses `rates.py` and `fixed_income`).
**Base spec:** `docs/offshore-lab/00-response.md` §5 Phase 3, and `docs/trader-prep/04-build-track.md` §Build 3 for what it is meant to teach.
**Scope:** curve snapshots and curve trades. No new engine, no new ledger, no new component folder.

## 1. Guardrails

Program §4 verbatim. Additionally: the curve views are **new views inside the Brief 2 rates tab**, not a new route. Reuse `risk_measures` from `fixed_income` for DV01 — do not recompute it inline.

## 2. Content

**Ingestion** via the existing macro pattern (`core/quant_core/macro.py`) and the Brief 2/4 FRED path:
- UST par yields — FRED `DGS*` (already wired in Brief 4)
- Euro-area AAA curve — ECB SDW
- MAD reference curve — BAM

**Analytics:**
- Curve snapshots, and 2s10s / 5s30s spread history
- Steepener/flattener classification into the four regimes (bull/bear × steepener/flattener), labelled on your own historical data
- Roll-down as carry — what the position earns if the curve does not move
- **DV01-neutral curve-trade simulator**: size two legs to equal DV01, then P&L is the spread move, not the level move. A curve trade that is not DV01-neutral is a directional duration bet wearing a disguise; the simulator must show the residual DV01 explicitly rather than assuming it away.

## 3. Files to create

```
core/quant_core/cross_asset/curve_lab.py          # spreads, regimes, roll-down, DV01-neutral sizing
core/tests/test_ca_curve_lab.py
```

## 4. Files you may modify (nothing else)

- `services/api/app/routers/cross_asset_research.py` + matching schemas — curve endpoints
- `services/api/app/services/cross_asset/datasources.py` — ECB and BAM curve paths
- The Brief 2 rates-tab components — curve snapshot, spread history, trade simulator views
- `frontend/lib/api.ts`

## 5. Tests

- `test_ca_curve_lab`: DV01-neutral sizing produces equal and opposite DV01 within tolerance, and residual DV01 is reported; roll-down sign is correct on an upward-sloping curve; the four regimes classify correctly on hand-built cases.

## 6. Acceptance

1. Curve snapshots and 2s10s/5s30s history render inside the rates tab.
2. The trade simulator reports residual DV01 rather than assuming perfect neutrality.
3. No new route, no new component folder, no new ledger.
4. Full suite green.
