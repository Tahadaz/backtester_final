# 12 — Indicator Explorer (Indicateurs Tab)

> **Status:** Implemented / partial. The Signals page has an indicator tab with chart, sidebar, parameter controls, and live indicator-series API calls. This document remains the product/methodology reference for that explorer, with current implementation notes below.

---

## Purpose

The existing Signals page has one tab — **Consensus** — which shows the 7-layer ensemble pipeline output (Layers A through G). The Consensus tab answers: *"What is the combined, OOS-validated signal for this stock?"*

The **Indicateurs** tab answers a different question: *"What does each indicator actually look like on this stock's data, and how strong is its reading right now?"*

This is a **pure visualization and live score reading** tool. The user explores what indicators look like on actual stock data with quantified signal strength before deciding which to use in a strategy. There is no strategy definition, no backtesting, and no portfolio construction on this tab. It is exploratory by design.

The distinction matters: the Consensus tab shows signals that have been through the full OOS evaluation, robustness scoring, and ensemble pipeline. The Indicateurs tab shows raw indicator values and their continuous scores — useful for building intuition, but not OOS-validated.

---

## Layout

The tab uses a two-panel layout:

```
+-----------------------------------------------+------------------+
|                                                |                  |
|         Stock Chart (Main Area)                |   Indicator      |
|                                                |   Sidebar        |
|   ┌─────────────────────────────────────┐      |                  |
|   │  OHLCV Candlestick / Line Chart     │      |   [Families]     |
|   │  + Overlay indicators (SMA lines)   │      |   [Parameters]   |
|   └─────────────────────────────────────┘      |   [Toggles]      |
|                                                |                  |
|   ┌─────────────────────────────────────┐      |                  |
|   │  Sub-panel: RSI (0-100)             │      |                  |
|   └─────────────────────────────────────┘      |                  |
|                                                |                  |
|   ┌─────────────────────────────────────┐      |                  |
|   │  Sub-panel: MACD Histogram          │      |                  |
|   └─────────────────────────────────────┘      |                  |
|                                                |                  |
+-----------------------------------------------+------------------+
```

- **Main panel**: OHLCV candlestick or line chart with overlay indicators (e.g., SMA lines drawn on the price axis).
- **Sub-panels**: Oscillator and volume indicators rendered in their own vertically stacked panels below the main chart. Each sub-panel has its own y-axis appropriate to the indicator (0-100 for RSI, arbitrary units for MACD histogram, cumulative volume for OBV).
- **Sidebar**: Right panel listing indicator families, individual indicators, parameter controls, and toggle switches.

Standard charting controls apply: zoom, pan, date range selection, crosshair with tooltip values. The frontend charting library is Plotly, already used elsewhere in the application (see `components/run/plotly-chart.tsx`).

---

## Sidebar Structure

The sidebar organizes indicators into 4 families following Elder's (1993) classification principle: indicators from different categories capture orthogonal market dimensions; indicators from the same category are largely redundant.

### Family Hierarchy

Each family is expandable. Clicking the family header reveals available indicator types within it. Each indicator type can be toggled on/off independently.

| Family | Category | Current frontend indicators |
|--------|----------|-----------------------------|
| **Tendance** | Trend-following | SMA, EMA, EMA Cross, Ichimoku, PSAR |
| **Momentum** | Trend acceleration | MACD, ROC, TRIX, ADX, TSI |
| **Oscillation** | Mean-reversion | RSI, Stochastic, CCI, MFI, UO |
| **Volume** | Volume-based | OBV, CMF, AD, VWAP, FI |

The current frontend indicator list is defined in `frontend/components/strategy/indicator-config.ts`. Keep that file as the implementation source of truth for indicator keys, default parameters, and slider bounds.

### Parameter Controls

Each indicator exposes its configurable parameters as sliders or numeric inputs in the sidebar. The table below is the original four-indicator subset; current complete ranges live in `frontend/components/strategy/indicator-config.ts`.

| Indicator | Parameters | Default | Range |
|-----------|-----------|---------|-------|
| SMA | Period | 20 | 5-500 |
| RSI | Period | 14 | 2-50 |
| MACD | Fast period, Slow period, Signal period | 12, 26, 9 | 2-100, 5-200, 2-50 |
| OBV | EMA smoothing period | 20 | 5-100 |

Parameter changes update the chart in real-time. The sidebar also shows the current continuous score and signal label for each active indicator (see next section).

### Toggle Behavior

- Users can add and remove indicators freely by toggling them on/off.
- Multiple indicators from different families can be active simultaneously.
- Multiple indicators from the same family can also be active (e.g., SMA-20 and SMA-50) — this is an exploration tool, not the OOS pipeline.
- Toggling an indicator off removes it from the chart and hides its score display.

---

## Indicator Score Display

This is the key feature that distinguishes the Indicateurs tab from a generic charting tool. When an indicator is toggled on, the tab displays its **continuous score** and **signal label** in a header bar above the chart or sub-panel.

### Why Continuous Scores?

The signal engine pipeline (Layers A-G) internally reduces indicator readings to discrete signals (+1, 0, -1). This is appropriate for the OOS evaluation framework, which measures directional accuracy.

But for exploration, the user needs to see *how far* the indicator is from neutral — not just its direction. A price that is 0.5 ATR above SMA and a price that is 4.0 ATR above SMA both produce a +1 trend signal, but they carry very different information about trend strength and mean-reversion risk.

Continuous scores preserve this information.

### Scoring Formulas by Family

#### SMA (Tendance): ATR-Normalized Distance

```
score = (Price - SMA) / ATR
```

The numerator measures how far price has deviated from the moving average. Division by ATR (Average True Range) normalizes the score so that it is comparable across stocks with different price levels and volatilities (Wilder 1978).

**Example**: Price = 130, SMA(20) = 140, ATR(14) = 5

```
score = (130 - 140) / 5 = -2.0
```

A score of -2.0 means price is 2 ATR below its moving average — a strong bearish reading.

**Interpretation scale**:

| Score Range | Label | Interpretation |
|-------------|-------|----------------|
| > +2.0 | Fortement Haussier | Price far above SMA; strong uptrend or overextension |
| +0.5 to +2.0 | Haussier | Price above SMA; uptrend |
| -0.5 to +0.5 | Neutre | Price near SMA; no clear trend |
| -2.0 to -0.5 | Baissier | Price below SMA; downtrend |
| < -2.0 | Fortement Baissier | Price far below SMA; strong downtrend or overextension |

**Source**: Murphy (1999) Ch. 9 — moving average as trend proxy. ATR normalization per Wilder (1978) Ch. 3.

#### RSI (Oscillation): Direct Value

```
score = RSI(period)
```

RSI is already a bounded oscillator on [0, 100] (Wilder 1978). No normalization is needed — the value itself is the score.

**Example**: RSI(14) = 25 on a recent pullback.

**Interpretation scale** (following Wilder's original thresholds):

| Score Range | Label | Interpretation |
|-------------|-------|----------------|
| >= 70 | Surachete | Overbought; potential mean-reversion down |
| 50 to 70 | Haussier | Bullish momentum |
| 30 to 50 | Baissier | Bearish momentum |
| <= 30 | Survendu | Oversold; potential mean-reversion up |

**Source**: Wilder (1978) Ch. 1 — original RSI definition and 30/70 thresholds.

#### MACD (Momentum): ATR-Normalized Histogram

```
score = MACD_histogram / ATR
```

The MACD histogram (MACD line minus signal line) measures the rate of change of the trend. Like the SMA score, division by ATR normalizes across stocks.

**Example**: MACD histogram = +3.2, ATR(14) = 5

```
score = 3.2 / 5 = +0.64
```

**Interpretation scale**:

| Score Range | Label | Interpretation |
|-------------|-------|----------------|
| > +1.5 | Fortement Haussier | Strong positive momentum acceleration |
| +0.3 to +1.5 | Haussier | Positive momentum |
| -0.3 to +0.3 | Neutre | No clear momentum |
| -1.5 to -0.3 | Baissier | Negative momentum |
| < -1.5 | Fortement Baissier | Strong negative momentum acceleration |

**Source**: Appel (2005) Ch. 3 — MACD histogram as momentum proxy. ATR normalization per Wilder (1978).

#### OBV (Volume): Self-Normalized Deviation

```
score = (OBV - OBV_EMA) / OBV_EMA
```

OBV is cumulative and stock-specific, so it cannot be normalized by ATR (which is price-based). Instead, we normalize by OBV's own exponential moving average, producing a fractional deviation that is comparable across stocks.

**Example**: OBV = 1,050,000, OBV_EMA(20) = 1,000,000

```
score = (1,050,000 - 1,000,000) / 1,000,000 = +0.05
```

A score of +0.05 means OBV is 5% above its smoothed trend — moderate accumulation.

**Interpretation scale**:

| Score Range | Label | Interpretation |
|-------------|-------|----------------|
| > +0.10 | Forte Accumulation | Volume strongly confirms upward price movement |
| +0.03 to +0.10 | Accumulation | Volume confirms upward price movement |
| -0.03 to +0.03 | Neutre | Volume is neutral |
| -0.10 to -0.03 | Distribution | Volume confirms downward price movement |
| < -0.10 | Forte Distribution | Volume strongly confirms downward price movement |

**Source**: Granville (1963) — OBV as cumulative volume indicator. Self-normalization is standard practice for non-stationary cumulative indicators (Murphy 1999, Ch. 7).

### Why ATR Normalization?

Two of four scoring formulas use ATR as the denominator. This is deliberate:

1. **Cross-stock comparability**: A 10-point move means different things for a stock trading at 50 vs 500. ATR captures the stock's typical daily range, making scores dimensionless.
2. **Cross-volatility comparability**: During high-volatility periods, a 10-point move is less significant than during low-volatility periods. ATR adapts automatically.
3. **Established practice**: Wilder (1978) introduced ATR specifically as a volatility normalizer for technical indicators. It remains the standard approach (Murphy 1999, Elder 1993).

RSI does not need ATR normalization because it is already self-normalized by construction (ratio of average gains to average losses). OBV uses self-normalization because it is a cumulative volume measure, not a price measure.

---

## Signal Labels

Signal labels follow the existing taxonomy used throughout the signal engine (see `07-current-signal-and-ensemble.md`). Labels are family-specific:

| Family | Possible Labels |
|--------|----------------|
| Tendance (SMA) | Fortement Haussier, Haussier, Neutre, Baissier, Fortement Baissier |
| Oscillation (RSI) | Surachete, Haussier, Baissier, Survendu |
| Momentum (MACD) | Fortement Haussier, Haussier, Neutre, Baissier, Fortement Baissier |
| Volume (OBV) | Forte Accumulation, Accumulation, Neutre, Distribution, Forte Distribution |

Labels are derived deterministically from the continuous score using the thresholds defined above. They are display-only — no downstream computation depends on them.

---

## Relationship to Other Pages

### Consensus Tab (Signals Page)

The Consensus tab is unchanged. It continues to show the 7-layer OOS-validated ensemble scores. The Indicateurs tab is a sibling tab on the same page, not a replacement.

Key difference: Consensus scores are OOS-validated and ensemble-weighted. Indicateurs scores are raw, real-time, single-indicator readings with no OOS validation.

### Strategy Page

The Strategy page (future) uses the same continuous score formulas in entry/exit rules. This is by design — the user explores scores on the Indicateurs tab, builds intuition for thresholds (e.g., "SMA score < -1.5 seems to mark good entry points"), then uses those thresholds in strategy definition.

### Data Page

The Data page shows raw OHLCV data. The Indicateurs tab adds computed indicators on top of that data. They share the same underlying price/volume series.

---

## Technical Notes

### Backend

- **Indicator computation** reuses existing `compute_signal_array()` from `core/quant_core/signal_engine/oos_eval.py`. This function already computes the underlying indicator values (SMA, RSI, MACD, OBV) as intermediate steps before producing discrete signals.
- **Current API endpoint**: `POST /strategy/signal/indicator-series`. The frontend calls it through `fetchIndicatorSeries()` in `frontend/lib/api.ts`. It returns raw indicator time series, optional overlays, current continuous score, current label, and ATR where applicable.
- **Response schema** (indicative):

```json
{
  "symbol": "IAM",
  "indicator": "sma",
  "params": {"period": 20},
  "series": {
    "dates": ["2025-01-02", "2025-01-03", "..."],
    "values": [138.5, 138.7, "..."],
    "close": [140.0, 139.5, "..."]
  },
  "current_score": -0.32,
  "current_label": "Neutre",
  "atr": 4.85
}
```

### Frontend

- **Charting library**: Plotly (already used in `components/run/plotly-chart.tsx`).
- **State management**: Each active indicator is an independent entry in component state, with its own parameters, series data, and score. Toggling adds/removes entries.
- **Real-time parameter updates**: Parameter changes trigger a new API call with updated query parameters. Debounce slider input (300ms) to avoid excessive requests.

### Performance Considerations

- Indicator computation is lightweight (SMA, RSI, MACD, OBV are all O(n) in bar count). No caching is needed for single-stock requests.
- Multiple active indicators require multiple API calls (one per indicator). These can be parallelized on the frontend.
- For stocks with very long histories (>5000 bars), the chart should default to showing the most recent 1-2 years with scroll-to-load for earlier data.

---

## References

- Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors*. FT Press. — MACD indicator design and histogram interpretation.
- Elder, A. (1993). *Trading for a Living*. Wiley. — Indicator family classification (trend, oscillator, volume); the principle of using indicators from different categories.
- Granville, J. (1963). *Granville's New Key to Stock Market Profits*. Prentice-Hall. — On-Balance Volume as cumulative volume indicator.
- Murphy, J.J. (1999). *Technical Analysis of the Financial Markets*. NYIF. — Moving average taxonomy, indicator overlay vs oscillator distinction, volume analysis.
- Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*. Trend Research. — RSI definition, ATR as volatility normalizer.
