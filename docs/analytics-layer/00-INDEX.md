# Analytics Layer — Document Index

**Page mandate**: Evaluate the predictive ability of TA signal scores over historical bars, surface per-stock expected returns and directional accuracy per signal bucket, and rank the full universe by information coefficient. Produces presentation-grade evidence for whether a signal has genuine edge.

**Status**: Implemented end-to-end. Score history populated via `score_history_batch` worker. Leaderboard and per-stock matrix live at `/analytics` route (TA tab).

---

## Document Map

| # | Document | Description |
|---|---|---|
| 01 | [01-overview.md](01-overview.md) | Page anatomy, tabs/subtabs, user workflow, what questions this page answers |
| 02 | [02-data-flow.md](02-data-flow.md) | Pipeline: signal_score_history → API → frontend rendering |
| 03 | [03-bucket-matrix-per-stock.md](03-bucket-matrix-per-stock.md) | **Par action** subtab: full methodology — buckets, mean forward return, bootstrap CI, hit rate, Wilson CI |
| 04 | [04-leaderboard-top-signaux.md](04-leaderboard-top-signaux.md) | **Top signaux** subtab: full methodology — Spearman IC, Newey-West t-stat, leaderboard ranking |
| 05 | [05-category-combinations-and-monotonicity.md](05-category-combinations-and-monotonicity.md) | Category-combinations panel: monotonicity score Δ, subset enumeration, interpretation |
| 06 | [06-methodology-and-sources.md](06-methodology-and-sources.md) | Academic citations, URLs, recommended reading |

---

## Cross-Layer Dependencies

- **Signal-generation layer** → `signal_engine_family_result.representatives_json` + `wfo_signal_summary.representatives_json` feed into `score_history_batch`, which fills `signal_score_history`.
- **Data layer** → OHLCV store provides close prices for forward-return computation. `load_ohlcv_for_symbol()` is called at request time by the analytics router.
- **Factor layer** → `docs/factor-layer/` covers macro-factor analytics (separate tab). Cross-references `docs/analytics-layer/06-methodology-and-sources.md` for shared statistical citations.
- **Backtest layer** → `docs/backtest-layer/08-statistical-validation.md` covers backtest-level stats (Sharpe, MaxDD). Analytics layer covers signal-level stats (IC, hit rate, expected return).

## What This Layer Does NOT Do

- Modify signal weights or ensemble logic — read-only evaluation.
- Run backtests — that is the backtest layer.
- Evaluate macro factors — that is the factor layer (`docs/factor-layer/`).
- Fix the leaderboard category-filter limitation (documented as known in `04-leaderboard-top-signaux.md`).
