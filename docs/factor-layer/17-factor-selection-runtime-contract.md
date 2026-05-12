# 17 - Factor Selection Runtime Contract

Factor x TA uses a monitored per-stock factor-selection layer before it generates technical cross-product variants. The selected factor set is independent for each stock and forecast horizon.

## Storage Schema

`stock_factor_relevance` is keyed by:

```text
(symbol, horizon, factor_canonical_id)
```

where `horizon` is a selection horizon:

```text
short | mid | long
```

Important fields:
- `rank`: deterministic rank among selected factors.
- `ic`, `spearman_ic`, `pearson_corr`, `ic_t_stat`, `bh_p_adj`: Stage 1 diagnostics.
- `relevance_score`, `selected_reason`: direct-selection score and reason.
- `cusum_status`: authoritative active flag; only `valid` rows are eligible.
- `regime_start`, `low_confidence`, `history_n_days`: structural-break and sample-size context.
- `next_forced_recal`: quarterly backstop recalibration target.

`stock_factor_stage1_cache` stores horizon-aware screening candidates for replacement/diagnostics.

## Horizon Vocabulary

Runtime APIs and persisted Signal Engine/WFO rows use canonical trading horizons:

```text
weekly | monthly | quarterly
```

Factor selection storage uses:

```text
short | mid | long
```

The shared adapter is:

| Runtime/API | Selection DB |
|---|---|
| `weekly` | `short` |
| `monthly` | `mid` |
| `quarterly` | `long` |

Legacy UI aliases are also accepted:

| Legacy alias | Runtime/API | Selection DB |
|---|---|---|
| `short` | `weekly` | `short` |
| `medium` | `monthly` | `mid` |
| `long` | `quarterly` | `long` |

## Selection Flow

1. Full calibration runs for `short`, `mid`, and `long`.
2. Stage 1 screens transformed macro factors with Spearman IC, Newey-West HAC t-stats, and BH-FDR.
3. Stage 2 detects the current regime; short histories are marked `low_confidence=true`.
4. Stage 3 selects at most the active factors for the horizon and persists them as `cusum_status='valid'`.
5. If the active set changes, all Factor x TA Signal Engine/WFO rows for the mapped runtime horizon are invalidated.
6. Refresh jobs are re-enqueued for both Signal Engine and WFO.

## Runtime Selection Rules

When the Factor x TA worker runs:

1. Query `stock_factor_relevance` for valid selected rows.
2. If the query succeeds and returns an empty set, return `no_signal`; do not fall back to every factor.
3. If the selection schema/query is unavailable, fall back to `stock_factor_config` for local/dev compatibility and log a warning.
4. Apply stock factor toggles from `stock_factor_config`.
5. Apply channel tags from `channel_tags.yaml`.
6. Load factor OHLCV and align it to the stock calendar before condition evaluation.

## Invalidation Contract

`invalidate_factor_x_ta_results(db, symbol, selection_horizon)` deletes rows for the mapped runtime horizon from:

- `signal_engine_family_result`
- `signal_engine_global_result`
- `wfo_signal_summary`
- `wfo_global_signal`

Example:

```text
selection horizon mid -> runtime horizon monthly
```

Only `variant='factor_x_ta'` rows are deleted. Native `legacy` and `expanded` rows are untouched.

## UI Contract

- Signal page view `factor_x_ta` is backed by the same shared Signal-page hierarchy as native TA.
- Factor-selection diagnostics should send either canonical runtime horizons or legacy aliases; the backend normalizes both.
- Analytics factor tabs are read-only diagnostics.
- Factor creation, factor metadata, and source management remain on the Data page.

## Valid Empty States

The UI should treat these as completed empty states, not crashes:

- no active selected factors for the stock/horizon
- factor series missing or stale after alignment
- no channel-applicable conditions
- no robust survivors after Signal Engine/WFO filtering
