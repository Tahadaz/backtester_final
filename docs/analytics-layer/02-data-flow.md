# Analytics Layer — Data Flow

## Pipeline Overview

```
signal_engine_family_result          wfo_signal_summary
(representatives_json per family)    (representatives_json per category)
              │                                │
              └──────────────┬────────────────┘
                             ▼
                  score_history_batch worker
              (compute_variant_signal_array per bar)
                             │
                             ▼
                   signal_score_history
              (date, symbol, source, category, horizon, score_pct)
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
    GET /predictive-   GET /predictive-  GET /predictive-ability/
        ability        ability/leaderboard  combinations
    (per-stock matrix) (universe ranking)  (category subsets)
              │              │              │
              └──────────────┴──────────────┘
                             │
                      Frontend (SWR hooks)
                    bucket-matrix.tsx
                    top-signaux-leaderboard.tsx
                    predictive-ability-panel.tsx
```

---

## Step 1 — Score History Population

The `score_history_batch` RQ worker task fills the `signal_score_history` table.

**For engine sources** (`engine_legacy`, `engine_expanded`):
1. Loads `signal_engine_family_result` rows where `status='succeeded'` for `(symbol, horizon, variant)`.
2. Groups family rows by category (using `CATEGORY_FAMILIES` or `LEGACY_CATEGORY_FAMILIES` mapping).
3. For each family, calls `compute_variant_signal_array(close, variant_def, ...)` from `core/quant_core/signal_engine/variant_detail.py` — returns a `{-1, 0, +1}` signal array for every bar.
4. Weights variants by `reliability_weight` (or `normalized_weight` as fallback), combines into a weighted sum, scales to `[−100, +100]`.
5. Averages family signals within each category → per-bar category score.
6. Upserts one `signal_score_history` row per `(date, symbol, source, category, horizon)`.

**For WFO source** (`wfo`):
1. Loads `wfo_signal_summary` rows where `status='succeeded'` for `(symbol, horizon)`.
2. Each row's `representatives_json` holds category-level representatives.
3. Same weighted signal reconstruction as above, per category.

**Implementation**: `services/worker/tasks/score_history_batch.py`, functions `build_engine_category_series` and `build_wfo_category_series` in `core/quant_core/research/score_history.py`.

---

## Step 2 — Score History DB Schema

Table: `signal_score_history`

| Column | Type | Description |
|---|---|---|
| `date` | date | Bar date |
| `symbol` | str | Ticker (e.g. `ATW`) |
| `source` | str | `engine_legacy` / `engine_expanded` / `wfo` |
| `category` | str | `tendance` / `momentum` / `oscillation` / `volume` |
| `horizon` | str | `short` / `medium` / `long` |
| `score_pct` | float | Score in `[−100, +100]` |

One row per `(date, symbol, source, category, horizon)`. For 73 symbols × 3 horizons × 2 engine variants × 4 categories × ~1500 bars ≈ 2.6M rows for engine sources.

---

## Step 3 — API Request Time

When the frontend requests the per-stock matrix or leaderboard:

```python
# Load raw per-category score series from DB
series_by_cat = _load_score_history(db, symbol=symbol, source=source, horizon=horizon)
# Returns: {"tendance": pd.Series, "momentum": pd.Series, ...}

# Aggregate selected categories into one composite score
score = aggregate_subset(series_by_cat, cats)
# Returns: pd.Series of daily composite scores in [−100, +100]

# Compute bucketed forward-return metrics
cells = bucketed_forward_returns(score, prices, fwd_horizons)
# Returns: list of cell dicts, one per (bucket, fwd_h)
```

**Implementation**: `services/api/app/routers/analytics.py` (`_load_score_history`, `get_predictive_ability`), `core/quant_core/research/score_history.py` (`aggregate_subset`, `bucketed_forward_returns`).

---

## Step 4 — Frontend Rendering

**Per-stock matrix** (`bucket-matrix.tsx`):
- SWR hook `usePredictiveAbility(symbol, source, horizon, categories, fwdHorizons)` fetches `GET /analytics/predictive-ability`.
- Renders a 5-row × N-column grid. Each cell shows mean return (large) and hit rate + N (small).
- Color intensity encodes mean return magnitude (green = positive, red = negative).

**Leaderboard** (`top-signaux-leaderboard.tsx`):
- SWR hook `usePredictiveAbilityLeaderboard(engineHorizon)` fetches `GET /analytics/predictive-ability/leaderboard`.
- Rows sorted by `mean_ic` descending. Color coding same as matrix.

**Category panel** (`predictive-ability-panel.tsx`):
- Category checkboxes trigger refetch of the per-stock matrix with updated `categories` parameter.
- Combinations panel fetches `GET /analytics/predictive-ability/combinations` and shows Δ score per subset.

---

## Caching

**Leaderboard**: in-process dict `_LEADERBOARD_CACHE` keyed by `(engine_horizon, lookback_days, return_calc_method)`. Cleared when score-history is updated (via `_invalidate_leaderboard_cache()`).

**Per-stock matrix**: no server-side cache — computed on every request. SWR provides client-side caching with a 30-second revalidation window.

**Category combinations**: no server-side cache. Uses `n_bootstrap=50` (vs 300 for the main matrix) to keep latency acceptable.
