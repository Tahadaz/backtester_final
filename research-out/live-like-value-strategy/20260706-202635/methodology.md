# Methodology — Live-Like B/M and CF/P Strategy Backtest

## Engine (Phase 1 & 5)

Old `methodology_bakeoff.py::portfolio_table` is now explicitly marked in code as **predictive diagnostic only** — it samples overlapping 6-month forward returns monthly and its `net_sharpe`/`max_drawdown`/`equity` are not valid sequential P&L (see the docstring warning added at `methodology_bakeoff.py:380`). It is unchanged and still used for cross-sectional IC research; it must never feed a live-strategy return engine.

A new module, `core/quant_core/fundamentals/cross_section/live_like_strategy.py`, implements the actual return engine used here:

- **Six overlapping monthly vintages** (primary spec): each month forms a new equal-weight top-tercile portfolio ("vintage"), held for 6 months, 1/6 of total capital per active vintage slot. During the first 5 months, fewer than 6 vintages are active and the unallocated capital sits in cash (0% return) — the honest behavior of actually starting this scheme from a cold start, not an approximation.
- **Semiannual non-overlapping rebalance** (robustness check): form once every 6 months, hold to the next rebalance, no vintages.
- Monthly realized return = capital-weighted sum of each active vintage's realized one-month price return, computed from real end-of-month prices (`_pit_price` from the existing `portfolio_backtest.py` engine) — never from a stored overlapping forward-return column.
- Turnover: `one_way_turnover` (reused from `portfolio_backtest.py`) between consecutive months' full combined portfolio weight vectors.
- Costs: `(cost_bps/10000) * 2 * turnover`, `cost_bps=33` (the repository's existing `DEFAULT_COST_BPS`, used as-is per the instruction not to search for a favorable cost level).

11 unit tests (`core/tests/test_live_like_strategy.py`) pass, including a synthetic proof that a stock returning +5%/month for 12 months produces the correct ~5%/month realized return once the portfolio is fully ramped (6 active vintages) — not the ~34%/month a naive "compound the overlapping 6-month forward spread every month" error would produce (verified: `1.05**6 - 1 ≈ 34%` vs actual `5%`, a >6x difference).

## Signals (Phase 3, frozen, not redefined after seeing results)

Uses the exact canonical `book_to_market_raw` and `cashflow_price_raw` columns from `characteristic_study.py` (2026-07-06 canonical definitions: negative book equity excluded for B/M; bank/insurance excluded for CF/P). Cross-sectional ranking is by raw value, not a fitted score. S3's composite is `0.5*percentile(B/M) + 0.5*percentile(CF/P)` — no fitted weights.

## Strategies (Phase 4)

- **S1**: B/M top tercile, long-only, equal-weight.
- **S2**: CF/P top tercile (CF/P-eligible names only), long-only, equal-weight.
- **S3**: Equal-rank composite top tercile (names with both signals valid).
- **S4**: 50/50 capital split between independently-run S1 and S2 vintage sleeves, combined at the realized-return level (`combine_sleeves`), never by averaging overlapping predictive spreads.

## Data source

Reused the already-computed, live-repaired `panel_characteristics.csv` from the prior data-quality-repair session's `characteristic_study.py` run (`20260706-194324`) rather than recomputing — same repaired DB state, same canonical definitions. Full daily price series loaded fresh from the object store for the vintage engine's price lookups.
