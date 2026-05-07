# 14 — Phase 2 Implementation Roadmap

> Step-by-step implementation order with acceptance criteria. Each code step is paired with its docs update.

## Status

| Step | Description | Status |
|---|---|---|
| 2.0 | Doc skeleton (13–16 stubs) | ✅ Done |
| 2.1 | Architectural smoke test | ✅ Done |
| 2.2 | Conditions library | ✅ Done |
| 2.3 | Composition library + naming | ✅ Done |
| 2.4 | Pre-registration freeze | ✅ Done |
| 2.5a | domain.py — FactorConditionMeta + VariantDef.factor_condition | ✅ Done |
| 2.5b | oos_eval.py — precomputed_signal bypass | ✅ Done |
| 2.5c | candidates.py — generate_factor_conditioned_candidates | ✅ Done |
| 2.6 | DB migration — stock_factor_config | Pending |
| 2.7 | Worker mode branch (mode='factor_x_ta') | Pending |
| 2.8 | API endpoints | Pending |
| 2.9 | Frontend Factor×TA tab + factor-selector | Pending |
| 2.10 | Analytics integration | Pending |
| 2.11 | Run Phase 2 backtest + write-up | Pending |

---

## Step 2.6 — DB migration (stock_factor_config)

**File**: new Alembic migration in `services/api/app/alembic/versions/`

**Schema**:
```sql
CREATE TABLE stock_factor_config (
    id          SERIAL PRIMARY KEY,
    stock_symbol VARCHAR(20) NOT NULL,
    factor_ticker VARCHAR(20) NOT NULL,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE (stock_symbol, factor_ticker)
);
```

Seed rows: for each stock in `phase2_pre_registration.yaml` universe × 6 factor tickers, `enabled=true`.

**Acceptance**: migration applies cleanly; seed rows exist; `SELECT * FROM stock_factor_config` returns 48+ rows.

---

## Step 2.7 — Worker mode branch

**File**: `services/worker/tasks/signal_backtest_batch.py`

Add `mode: str = 'ta_only'` parameter. When `mode='factor_x_ta'`:
1. Load aligned factor arrays for the stock (from macro store).
2. Evaluate all pre-registered factor conditions via `evaluate_condition`.
3. Build cross-product candidates via `generate_factor_conditioned_candidates` (channel-gated).
4. For each conditioned variant:
   - Compute native TA signal via `compute_signal_array(close, ta_variant)`.
   - Compose via `compose_and_signal(ta_signal, condition_mask)`.
   - Call `evaluate_variant_oos(..., precomputed_signal=composed)`.
5. Run Layers C–G unchanged.

**Acceptance**: one stock (e.g. ATW) produces a ranked list of factor-conditioned variants with DSR, Sharpe, and FDR flags populated.

---

## Step 2.8 — API endpoints

**File**: `services/api/app/routers/signals.py`

New endpoints:
- `GET /signals/{stock}/factors/config` — returns current per-stock factor toggles.
- `PUT /signals/{stock}/factors/config` — updates toggles; schedules re-evaluation in background.
- `GET /signals/{stock}?mode=factor_x_ta` — returns Factor×TA variant ranking and current signals.

Pydantic schemas in `services/api/app/schemas/signals.py` (or `analytics.py`):
- `FactorConfigItem`: `{factor_ticker, enabled}`.
- `FactorConfigResponse`: `{stock_symbol, factors: list[FactorConfigItem]}`.

**Acceptance**: `curl /signals/ATW/factors/config` returns JSON with 6 factors all enabled. `curl -X PUT` toggles one factor and returns updated config.

---

## Step 2.9 — Frontend

**New file**: `frontend/components/signals/factor-selector.tsx`
- 6 factor toggles (default all on).
- Save on change via `PUT /signals/{stock}/factors/config`.
- Shows factor ticker + short description.

**Modify**: `frontend/app/signals/page.tsx` (or equivalent signal-family page):
- Add tab strip: "TA" (existing, unchanged) | "Factor × TA" (new tab).
- Factor × TA tab:
  - Renders `FactorSelector` at the top.
  - Below: same variant-ranking table as TA tab, fed by `mode=factor_x_ta` API.
  - Factor condition badge on each row (e.g. "@ vix_z20_below_neg1").

**Modify**: `frontend/app/signals/variant/[id]/page.tsx`:
- When variant has `factor_condition` populated, render a badge showing the condition details.

**Acceptance**: `/signals` page shows both tabs; toggling a factor in the selector triggers re-fetch; variant drill-down shows factor badge for conditioned variants.

---

## Step 2.10 — Analytics integration

**Modify**: `frontend/app/analytics/page.tsx`:
- Add `mode` filter: "TA only" | "Factor×TA" | "Both" (default).
- Factor-conditioned variants intermixed with TA variants, sortable by DSR.

**Modify**: `frontend/app/analytics/[symbol]/[variantId]/page.tsx`:
- When variant is factor-conditioned, render comparison panel:
  - Side-by-side equity curves: conditioned vs native TA baseline.
  - Bootstrap CI band on incremental Sharpe (lower bound > 0 → "value-adding").
  - Factor condition details card.

**Acceptance**: analytics drill-down for a factor-conditioned variant shows comparison panel with incremental Sharpe and CI.

---

## Step 2.11 — Run and write-up

1. Commit + tag `phase2_pre_registration.yaml` (git tag `phase2-preregistration`).
2. Run worker in `mode='factor_x_ta'` for full universe.
3. Run BH-FDR per stock across Factor×TA variants.
4. Bootstrap incremental Sharpe for FDR-surviving variants.
5. Write `docs/factor-layer/16-phase2-results.md` and `docs/research/phase2_results.md`.

**Acceptance**: at least one stock has ≥1 value-adding conditioned variant; at least one stock has zero value-adding conditioned variants (honest null reporting).
