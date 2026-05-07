# 08 — Variant Detail: Trade Register, Execution, Plots

**File**: `core/quant_core/signal_engine/variant_detail.py`

---

## Purpose

The variant detail module generates everything needed for deep inspection of a single variant: trade-by-trade execution ledger, performance metrics, per-window plots, and aggregate diagnostics. This is what powers the variant detail page at `/signals/variant/[id]`.

---

## Entry Point

```python
def compute_variant_detail(
    ohlcv: pd.DataFrame,
    close: np.ndarray,
    variant: VariantDef,
    oos_windows: list[OOSWindowResult],
    *,
    volume: np.ndarray | None = None,
    cost_bps: float = 10.0,
    cooldown_bars: int = 0,
) -> dict
```

Returns a dict with: `plots`, `trade_ledger`, `trade_performance`, `metrics`, `per_window`.

---

## Trade Register (`_extract_trade_register`)

The trade register produces one row per position change (fill), tracking full cash flow and P&L.

### Execution Model

**Timing**: Signal fires at close of bar `i` → execution at open of bar `i+1`

This models the practical reality that:
1. The indicator value is known at market close
2. The decision is made after close
3. The trade is executed at the next market open

There is no look-ahead bias because the signal at bar `i` uses only data from bars `[0, i]`.

### Cost-Adjusted Carry Price (CMP)

Each position has a carry price that includes transaction costs:
- **Long entry**: `CMP = execution_price + cost_per_share`
- **Short entry**: `CMP = execution_price - cost_per_share`

Where `cost_per_share = execution_price × cost_bps / 10,000`

### Position Transitions

**Open** (flat → long or flat → short):
- Capitalize cost into CMP
- `tresorerie -= execution_price` (long) or `tresorerie += execution_price` (short)
- `pnl_realise = 0` (no realized P&L yet)

**Close** (long → flat or short → flat):
- Long close: `pnl_realise = execution_price - CMP - cost`
- Short close: `pnl_realise = CMP - execution_price - cost`
- Update tresorerie accordingly

**Flip** (long → short or short → long):
- Close existing position (realize P&L)
- Open new position at CMP

**Force-close at window end**:
- Any open position at the last bar of an OOS window is closed at the last bar's close price
- This ensures clean P&L accounting per window

### Trade Ledger Columns

| Column | Type | Description |
|--------|------|-------------|
| `date` | ISO date | Execution date (bar i+1) |
| `side` | "ACHAT" / "VENTE" | Direction of the fill |
| `prix_execution` | float | Execution price (next bar open) |
| `close_du_jour` | float | Close price of execution day |
| `position` | float | Position after fill: +1, -1, or 0 |
| `tresorerie` | float | Cumulative cash balance |
| `pnl_realise` | float | Realized P&L from this fill (closing fills only) |
| `pnl_latent` | float | Mark-to-market unrealized P&L |
| `cout` | float | Transaction cost for this fill |
| `oos_window` | int | Window index this fill belongs to |

---

## Trade Performance Summary (`_trade_performance_summary`)

Computes aggregate statistics from the trade ledger. Only counts **closing fills** (fills where P&L is realized):

| Metric | Description |
|--------|-------------|
| `total_fills` | Total fill rows in ledger |
| `closing_fills` | Fills with realized P&L (opens excluded) |
| `win_rate` | % of closing fills with positive P&L |
| `avg_win_pnl` | Average P&L of winning closes |
| `avg_loss_pnl` | Average P&L of losing closes |
| `profit_factor` | Gross wins / Gross losses |
| `total_pnl_realise` | Sum of all realized P&L |
| `total_cost` | Sum of all transaction costs |
| `max_consecutive_wins` | Longest winning streak |
| `max_consecutive_losses` | Longest losing streak |

---

## Indicator Computation (`_compute_indicator`)

Computes the raw indicator values for chart overlay:

### Overlay Indicators (on price chart)

**SMA (`price_vs_sma`)**: SMA line over candlesticks
```python
{"type": "overlay", "name": "SMA-20", "values": sma_array}
```

**EMA (`price_vs_ema`)**: EMA line over candlesticks
```python
{"type": "overlay", "name": "EMA-20", "values": ema_array}
```

**EMA Cross (`ema_cross`)**: Two EMA lines
```python
{"type": "overlay_dual", "name": "EMA(12,26)", "fast": fast_ema, "slow": slow_ema}
```

**SMA Cross (`sma_cross`)**: Two SMA lines (existing archetype)
```python
{"type": "overlay_dual", "name": "SMA(10,20)", "fast": fast_sma, "slow": slow_sma}
```

**Ichimoku (`ichi_cloud`)**: Tenkan/Kijun lines + cloud shading
```python
{"type": "overlay_cloud", "name": "Ichimoku(9,26,52)",
 "tenkan": tenkan_array, "kijun": kijun_array,
 "senkou_a": senkou_a_array, "senkou_b": senkou_b_array}
```

**PSAR (`psar_trend`)**: SAR dots on price chart
```python
{"type": "overlay_dots", "name": "PSAR(0.02,0.20)", "values": sar_array}
```

**VWAP (`vwap_dev`)**: VWAP line with threshold bands
```python
{"type": "overlay_band", "name": "VWAP(20,1.0%)",
 "center": vwap_array, "upper": upper_array, "lower": lower_array}
```

### Secondary Y-Axis Indicators (subplot below price)

**RSI (`rsi_level`)**:
```python
{"type": "secondary_yaxis", "name": "RSI(14)", "values": rsi_array,
 "thresholds": [30, 70], "y_range": [0, 100]}
```

**Stochastic (`stoch_level`)**:
```python
{"type": "secondary_yaxis", "name": "Stoch(14,3)",
 "k_line": k_array, "d_line": d_array,
 "thresholds": [20, 80], "y_range": [0, 100]}
```

**CCI (`cci_level`)**:
```python
{"type": "secondary_yaxis", "name": "CCI(20)", "values": cci_array,
 "thresholds": [-100, 100]}
```

**MFI (`mfi_level`)**:
```python
{"type": "secondary_yaxis", "name": "MFI(14)", "values": mfi_array,
 "thresholds": [20, 80], "y_range": [0, 100]}
```

**UO (`uo_level`)**:
```python
{"type": "secondary_yaxis", "name": "UO(7,14,28)", "values": uo_array,
 "thresholds": [30, 70], "y_range": [0, 100]}
```

**MACD (`macd_cross`)**:
```python
{"type": "secondary_yaxis", "name": "MACD(12,26,9)",
 "macd_line": macd, "signal_line": signal, "histogram": hist}
```

**ROC (`roc_zero`)**:
```python
{"type": "secondary_yaxis", "name": "ROC(12)", "values": roc_array,
 "thresholds": [0]}
```

**TRIX (`trix_zero`)**:
```python
{"type": "secondary_yaxis", "name": "TRIX(15)", "values": trix_array,
 "thresholds": [0]}
```

**ADX (`adx_trend`)**:
```python
{"type": "secondary_yaxis", "name": "ADX(14)",
 "plus_di": plus_di_array, "minus_di": minus_di_array, "adx": adx_array,
 "thresholds": [25]}
```

**TSI (`tsi_zero`)**:
```python
{"type": "secondary_yaxis", "name": "TSI(25,13)", "values": tsi_array,
 "thresholds": [0]}
```

**OBV (`obv_trend`)**:
```python
{"type": "secondary_yaxis", "name": "OBV-EMA(20)",
 "obv": obv_array, "ema_values": ema_array}
```

**CMF (`cmf_flow`)**:
```python
{"type": "secondary_yaxis", "name": "CMF(21)", "values": cmf_array,
 "thresholds": [-0.05, 0.05]}
```

**A/D Line (`ad_trend`)**:
```python
{"type": "secondary_yaxis", "name": "A/D-EMA(20)",
 "ad_line": ad_array, "ema_values": ad_ema_array}
```

**Force Index (`fi_trend`)**:
```python
{"type": "secondary_yaxis", "name": "FI-EMA(13)", "values": fi_ema_array,
 "thresholds": [0]}
```

### New Plot Types

Three new overlay types support the expanded indicator set:

- **`overlay_cloud`**: For Ichimoku — draws two lines (tenkan, kijun) and a filled cloud area between senkou_a and senkou_b (green when senkou_a > senkou_b, red otherwise)
- **`overlay_dots`**: For PSAR — draws dot markers at SAR values (green dots below price, red above)
- **`overlay_band`**: For VWAP — draws center line with shaded upper/lower band

---

## Plot Generation

Three Plotly JSON figures are generated:

### 1. Price + Indicator + Signal
- Candlestick or line chart of close prices
- Indicator overlay (SMA line) or secondary subplot (RSI, MACD, OBV)
- Signal markers: green triangles (buy), red triangles (sell)
- OOS window shading (alternating background rectangles)

### 2. Equity Curve
- Cumulative returns line per OOS window
- Each window starts at 100K
- Green for profitable windows, red for losing

### 3. Drawdown
- Peak-to-trough drawdown line
- Shaded area below zero
- Per-window coloring

### Per-Window Plots
Each OOS window gets its own set of the 3 plots, plus:
- Window-specific trade ledger
- Window-specific metrics
- Start/end dates and validity flag

---

## Frontend Variant Detail Page

**Route**: `/signals/variant/[id]?symbol=XXX&horizon=medium&cooldown=0`

### 3-Tab Layout

**Tab 1: Comparaison**
- Pipeline stepper with clickable stages (filters variant table)
- Table of **all 30 variants** (sorted, paginated):
  - Columns: #, Variante, Signal, CAGR, Sharpe, Max DD, PnL, Fen+, Score, Statut
  - Rank badges: gold (#1), silver (#2), bronze (#3)
  - Sort dropdown: Score, CAGR, Sharpe, PnL
  - Status badges: Sélectionné (green), Redondant (amber), Éliminé (gray), Non-viable (red)
  - **Expandable rows**: click to show backtest data
    - Per-window selector buttons
    - Tabs: Graphiques (3 Plotly charts), Métriques (grid), Performance Trades (stats), Registre Trades (full ledger)

**Tab 2: Fenêtres OOS**
- Table of OOS windows:
  - Columns: #, Période, Bars, Trades, Return moy., Sharpe, Max DD, Win%, Valide
  - Sharpe colored: green if > 0, red if < 0
  - Validity: OK or --

**Tab 3: Fiabilité**
- Large reliability score (%)
- Viable / Non-viable badge
- 4-component decomposition with progress bars
- OOS metrics grid

---

## API Endpoints

### POST /strategy/signal/variant-detail
Returns full variant context: robustness, all variants comparison, funnel counts, correlation matrix.

### POST /strategy/signal/variant-backtest
Returns backtest artifacts: plots, trade ledger, trade performance, metrics, per-window detail.

Both accept: `{variant_id, symbol, horizon, timeframe, cost_bps, cooldown_bars}`
