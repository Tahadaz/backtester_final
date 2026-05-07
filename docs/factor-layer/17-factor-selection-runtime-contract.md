# 17 — Factor Selection Runtime Contract

## Overview

Factor x TA uses a monitored, per-stock factor-selection layer before it generates technical cross-product variants. The active factor set is independent for each `(stock, horizon)` pair and is capped at three factors.

## Selection Schema

`stock_factor_relevance` is keyed by `(symbol, horizon, factor_canonical_id)`.

Important fields:
- `rank`: deterministic top-3 rank for the selected horizon.
- `ic`, `ic_t_stat`, `bh_p_adj`: Stage 1 IC screen diagnostics.
- `lasso_coef`: final Adaptive LASSO coefficient.
- `regime_start`, `low_confidence`, `history_n_days`: structural-break context.
- `cusum_status`: authoritative active-state field; only `valid` rows are eligible.
- `next_forced_recal`: quarterly backstop recalibration target.

`stock_factor_stage1_cache` stores horizon-aware BH-FDR survivors and is used by the nightly monitor for cheap partial replacement.

## Runtime Flow

1. Full calibration runs for `short`, `mid`, and `long`.
2. Stage 1 screens transformed macro factors with Spearman IC, Newey-West HAC t-stats, and BH-FDR correction.
3. Stage 2 detects the current regime; short histories are marked `low_confidence=true`.
4. Stage 3 selects at most three factors via Adaptive LASSO with purged time-series CV.
5. If the active top-3 changes, existing Factor x TA Signal Engine and WFO rows are deleted for that `(symbol, horizon)` and both pipelines are re-enqueued.
6. Nightly monitoring runs RecursiveLS CUSUM and CUSUM-SQ per selected factor. Invalidated factors are replaced from Stage 1 cache when possible; otherwise the remaining factors continue as `N-1`.

## Horizon Vocabulary

Selection state uses:

```text
short | mid | long
```

Signal Engine and WFO APIs continue to use:

```text
short | medium | long
```

The shared adapter maps `mid` to `medium` at queueing and result-invalidation boundaries.

## UI Contract

The Signal page keeps `view=factor_x_ta` as a backward-compatible alias, but it renders through the same shared Signal-page hierarchy as native TA.

Analytics "Facteurs Macro" is a read-only diagnostic surface. Factor creation, updates, activation, and source management remain on the Data page.
