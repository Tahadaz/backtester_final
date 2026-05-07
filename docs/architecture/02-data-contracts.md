# 02 — Data Contracts and Inter-Station Flow

This document specifies how data flows between the four stations: what each station produces, what the next station expects, and the shared types that bind them together.

---

## Station-to-Station Contracts

### Data → Signal

**Producer:** Data page (market data ingestion and storage)
**Consumer:** Signal engine backend (`market_data_loader.py`)

| Artifact | Format | Location |
|----------|--------|----------|
| OHLCV per symbol | Parquet (DatetimeIndex, Open/High/Low/Close/Volume columns) | `market_data_store/{symbol}/1D` in S3/MinIO |
| Stock catalog | PostgreSQL `stock_master` table | `symbol`, `display_name`, `sector`, `is_tracked`, `data_as_of` |
| Holiday calendar | JSON | `holidays_casablanca.json` |

**Contract assumptions (signal engine expects):**
- DatetimeIndex is sorted ascending, no duplicate dates
- Close column is never NaN for trading days
- Volume may be zero/NaN for some stocks (OBV family validates >1% non-zero)
- At least 252 bars of history for any signal computation

**Loading functions:**
- `load_close_for_symbol(db, symbol, timeframe="1D") → np.ndarray`
- `load_ohlcv_for_symbol(db, symbol, timeframe="1D") → pd.DataFrame`

### Signal → Strategy

**Producer:** Signal page (7-layer pipeline + indicator explorer)
**Consumer:** Strategy page (strategy configuration)

The signal page does not produce a structured payload for the strategy page. Instead, it produces **knowledge** that the user carries:

| What the user learns | Where it comes from | How it informs strategy |
|---------------------|--------------------|-----------------------|
| Which families have predictive power for a stock | Ensemble scores, family rankings | Choose which families to include in entry/exit rules |
| Which parameter ranges work | Representative variants, OOS windows | Set WFO scan ranges (or fix manual values) |
| Continuous score thresholds | Indicator explorer tab, score labels | Set entry/exit threshold values |
| Signal reliability | Robustness decomposition | Decide how much to trust each indicator |

**Shared indicator definitions (same in both pages):**

| Family | Scoring formula | Signal page usage | Strategy page usage |
|--------|----------------|-------------------|---------------------|
| SMA | `(close - SMA) / ATR` | Continuous score in Indicateurs tab | Entry/exit rule threshold variable |
| RSI | `RSI(period)` [0, 100] | Continuous score in Indicateurs tab | Entry/exit rule threshold variable |
| MACD | `MACD_histogram / ATR` | Continuous score in Indicateurs tab | Entry/exit rule threshold variable |
| OBV | `(OBV - OBV_EMA) / OBV_EMA` | Continuous score in Indicateurs tab | Entry/exit rule threshold variable |

**Critical invariant:** The strategy page uses the **same scoring formulas** as the signal page's indicator explorer (doc `signal-generation/12-indicator-explorer.md` = doc `strategy-layer/05-signal-construction-layer.md`). A threshold the user discovered on the Indicateurs tab works identically in the strategy's entry rules.

### Strategy → Backtest

**Producer:** Strategy page ("Open in Backtest" action)
**Consumer:** Backtest page (WFO engine)

**Handoff payload:**

```ts
type BacktestHandoff = {
  strategy_id: string
  strategy_name: string
  portfolio: PortfolioConfig       // universe, capital, allocation_method
  stocks: Record<string, StockStrategyConfig>  // per-stock configs
  wfo_params: WFOParamManifest     // which params are WFO-flagged, with scan ranges
  total_wfo_param_count: number
  warnings: string[]               // non-blocking review warnings
}
```

**Contract assumptions (backtest expects):**
- All WFO-flagged parameters have valid scan ranges (min < max, step > 0)
- All indicator families referenced in entry/exit rules exist in the 4-family registry
- At least one stock in the basket
- Each stock has at least one entry rule and either exit rules or risk parameters

**Backtest page adds its own configuration:**
- WFO start date
- Horizon (determines window sizes)
- Cost model (brokerage, commission, slippage, TVA)
- Volume gate, cooldown

### Backtest → Strategy (Feedback Loop)

**Producer:** Backtest results
**Consumer:** Strategy page (user-initiated)

| Result | How it flows back |
|--------|------------------|
| Optimal parameters | User reviews → manually updates strategy |
| Kelly sizing | User clicks "Appliquer le sizing" → writes to strategy, status becomes `modified` |
| WFE verdict | User reviews → decides whether to revise strategy |
| Test period equity curve | User reviews → decides whether strategy is viable |

**This is NOT automatic.** Backtest results belong to the backtest run. The user must explicitly choose to apply findings back to the strategy. See `backtest-layer/07-sizing-from-oos.md` § "Sizing Value Lifecycle" for the full three-state model.

---

## Shared Types

These types appear across all stations and must remain consistent:

| Type | Values | Used by |
|------|--------|---------|
| `symbol` | MASI ticker string (e.g. "IAM", "ATW", "BCP") | All 4 pages |
| `horizon` | `"short" \| "medium" \| "long"` | Signal, Strategy, Backtest |
| `timeframe` | `"1D"` (daily bars; only value in v1) | All 4 pages |
| `cost_bps` | `float` (default 10.0, range 0–100) | Signal, Backtest |
| `cooldown_bars` | `int` (default 0, range 0+) | Signal, Strategy, Backtest |
| `family` | `"sma" \| "rsi" \| "macd" \| "obv"` | Signal, Strategy, Backtest |

### Horizon Semantics

The word "horizon" appears in two contexts — they are related but distinct:

| Context | Meaning | Values |
|---------|---------|--------|
| **Signal engine** | OOS evaluation train/test windows | short: 252/63, medium: 504/126, long: 756/252 bars |
| **Backtest WFO** | Determines parameter ranges and IS window constraint (IS ≥ 10 × max_lookback) | IS window size is dynamic, NOT 252/504/756 |

The signal engine horizons and WFO research presets use the same default window values (252/504/756) by design — see `signal-generation/07-current-signal-and-ensemble.md` § "Dual Horizon System". But the backtest IS window is always larger than the signal engine train window because of the degrees-of-freedom constraint (Pardo Ch.6 p.163).

---

## API Endpoint Inventory

### Data Page

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/market-data/catalog` | Stock catalog with freshness |
| GET | `/market-data/health` | System-wide data health |
| POST | `/market-data/upload` | Excel file upload |
| POST | `/market-data/refresh` | Trigger Bourse refresh |
| GET | `/market-data/{symbol}/ohlcv` | OHLCV data for charting |
| GET | `/market-data/{symbol}/availability` | Per-day data availability calendar |

(18 endpoints total — see `data-layer/03-backend-endpoints.md` for full list)

### Signal Page

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/strategy/signal/family-ensemble` | Full A→G pipeline for one (family, symbol, horizon) |
| POST | `/strategy/signal/batch-scores` | Aggregate scores for stock sidebar |
| POST | `/strategy/signal/variant-detail` | Single variant detail (all 30 candidates, funnel, correlation) |
| POST | `/strategy/signal/variant-backtest` | Variant backtest artifacts (trades, plots, metrics) |
| POST | `/strategy/signal/regime-consensus` | Regime-weighted family consensus |
| POST | `/strategy/signal/zone-chart` | Multi-family signal zone visualization |
| POST | `/strategy/signal/indicator-series` | Raw indicator time series + continuous score (Indicateurs tab) |
| POST | `/strategy/signal/sma-ensemble` | SMA-specific ensemble (legacy) |

### Strategy Page

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/strategies` | List saved strategies |
| GET | `/strategies/{id}` | Load strategy |
| POST | `/strategies` | Create strategy |
| PUT | `/strategies/{id}` | Update strategy |
| POST | `/strategies/{id}/duplicate` | Duplicate strategy |
| PUT | `/strategies/{id}/archive` | Archive strategy |

### Backtest Page

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/backtest/wfo` | Submit WFO analysis |
| GET | `/backtest/wfo/{run_id}` | Get WFO results |
| GET | `/backtest/wfo/{run_id}/window/{idx}` | Per-window detail |
| GET | `/backtest/wfo/{run_id}/progress` | SSE progress stream |

---

## Cross-Links

- Data contracts detail: [../data-layer/03-backend-endpoints.md](../data-layer/03-backend-endpoints.md)
- Signal API detail: [../signal-generation/09-api-and-frontend.md](../signal-generation/09-api-and-frontend.md)
- Strategy handoff: [../strategy-layer/09-review-and-backtest-handoff.md](../strategy-layer/09-review-and-backtest-handoff.md)
- Backtest API: [../backtest-layer/10-api-data-flow-and-frontend-contracts.md](../backtest-layer/10-api-data-flow-and-frontend-contracts.md)
- Sizing lifecycle: [../backtest-layer/07-sizing-from-oos.md](../backtest-layer/07-sizing-from-oos.md)
