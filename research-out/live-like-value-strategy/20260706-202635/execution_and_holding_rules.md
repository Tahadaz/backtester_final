# Execution & Holding Rules (Phase 6-9)

## Timing

Signal availability follows the existing PIT panel's `availability_date` logic (90-day fallback lag on annual statements, as audited in the prior session's `pit_fallback_audit.md`). Formation happens at each monthly panel date using only signal values already available as of that date (no same-date look-ahead — enforced by the panel's own `_assert_no_lookahead` guard, inherited here since this reuses the same panel). **Execution timing within the month is not modeled beyond the existing monthly panel cadence** — this backtest uses month-end-to-month-end price ratios directly rather than a separate next-open/next-close execution lag; this is a simplification, documented rather than hidden: a `LiveLikeConfig.execution_lag_days` field exists in the engine for future use but is not currently wired into the price lookup (`_pit_price` looks up the closest available price at-or-before the target date, effectively a close-to-close convention).

## Corporate actions & price basis (Phase 7)

Prices are sourced from the existing OHLCV object-store pipeline (`market_data_store`); **not independently re-verified this session** for split/dividend adjustment. Whether the "Close" series used is raw or adjusted was not re-audited here — this is inherited risk from the existing price pipeline, not newly introduced or newly verified. **Total-return performance is not claimed** — if dividends are not reflected in the price series, realized returns understate true total return. This is a documented limitation, not resolved this session.

## Transaction costs (Phase 8)

Primary assumption: 33 bps round-trip-equivalent (`DEFAULT_COST_BPS`, the repository's existing convention, used as-is — not tuned for this task). No sensitivity bands (low/high cost) were computed this session due to time; only the single primary assumption is reported.

## Turnover (Phase 9)

Computed via `one_way_turnover` on the full combined portfolio weight vector month-to-month (entering vintage + expiring vintage + unchanged survivors), not a naive "compare this month's top set to last month's" shortcut. Average monthly turnover (invested period): S1 3.5%, S2 5.9%, S3 4.6% — low, consistent with the vintage structure (only 1/6 of capital turns over in a typical month from one expiring/entering vintage pair).
