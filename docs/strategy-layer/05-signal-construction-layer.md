# Strategy Layer — Signal Construction Layer

## What

The Signal Construction section defines **which indicators to use and how to compute their scores** for each stock in the basket. For each of the four indicator families, the user chooses:

1. Which indicator type within the family (e.g., SMA vs EMA vs DEMA for Tendance)
2. What parameters that indicator uses (e.g., SMA period = 50)
3. Whether those parameters are manually fixed or marked for WFO optimization

This section replaces the old "Signal Selection" layer. The key difference: instead of just enabling/disabling families, the user now configures how each family's indicator is constructed and scored.

## Why

The signal engine (Phase 1) discovers which indicators have predictive power using a fixed set of archetypes and parameter grids. The strategy layer needs to go further:

- The user may want a specific indicator type not in the default archetype
- Different stocks may need different parameters
- Some parameters should be fixed (based on domain knowledge), while others should be optimized by WFO

Signal Construction bridges the gap between "the signal engine says SMA works" and "I want SMA(50) for IAM but SMA(200) for BCP, with MACD parameters optimized by WFO."

## The Four Indicator Families

### Available Now (v1)

| Family | Category (FR) | v1 Indicator | Score Range | Notes |
|--------|--------------|-------------|-------------|-------|
| **Tendance** | Tendance | SMA | Unbounded (ATR-normalized) | Price-vs-MA as trend proxy |
| **Momentum** | Momentum | MACD | Unbounded (ATR-normalized) | Histogram as momentum proxy |
| **Oscillation** | Oscillation | RSI | 0–100 (native) | Relative strength as extremity measure |
| **Volume** | Volume | OBV | Unbounded (ratio) | Cumulative volume as confirmation |

### Planned Future Additions

| Family | Future Indicators | Status |
|--------|------------------|--------|
| Tendance | EMA, DEMA | Designed, not implemented |
| Momentum | Stochastic, CCI | Designed, not implemented |
| Oscillation | Williams %R | Designed, not implemented |
| Volume | VWAP, MFI | Designed, not implemented |

## Continuous Scoring Formulas

Each indicator family produces a **continuous score** — not a binary buy/sell signal. Continuous scores enable graduated entry and exit at multiple conviction levels (see [06-entry-rules-layer.md](./06-entry-rules-layer.md)).

### Tendance (SMA)

```
trend_score = (Price - SMA(period)) / ATR(14)
```

- **Positive** when price is above the MA (bullish trend)
- **Negative** when price is below the MA (bearish trend)
- **Magnitude** reflects how many ATR units price has moved away from the MA
- A score of +2.0 means price is 2 ATR above the SMA — a strong trend reading

### Momentum (MACD)

```
momentum_score = MACD_histogram(fast, slow, signal) / ATR(14)
```

Where `MACD_histogram = MACD_line - signal_line` and `MACD_line = EMA(fast) - EMA(slow)`.

- **Positive** when momentum is bullish (MACD above signal line)
- **Negative** when momentum is bearish
- **Magnitude** reflects momentum strength in ATR units

### Oscillation (RSI)

```
oscillation_score = RSI(period)
```

RSI is already bounded [0, 100] and does not require ATR normalization.

- **Low values** (< 30) indicate oversold conditions — potential mean-reversion entry
- **High values** (> 70) indicate overbought conditions — potential mean-reversion entry (short) or trend filter
- **Mid-range** (30–70) indicates no extreme — neutral

### Volume (OBV)

```
volume_score = (OBV - OBV_EMA(period)) / OBV_EMA(period)
```

This is a percentage deviation of OBV from its own exponential moving average.

- **Positive** when volume flow is accumulating faster than average
- **Negative** when volume flow is distributing
- **Magnitude** reflects the strength of the volume divergence

## ATR Normalization Rationale

Three of the four families use ATR(14) as a normalizer. This serves a critical purpose:

1. **Cross-stock comparability** — A 10 MAD move means very different things for a stock trading at 50 MAD vs one at 500 MAD. ATR normalization expresses the move in volatility units.

2. **Cross-volatility comparability** — A stock may have different volatility regimes at different times. ATR normalization automatically adjusts the score scale.

3. **Entry/exit threshold consistency** — When entry rules use thresholds like `trend_score > 2.0`, that threshold means the same thing across all stocks: "price is 2 ATR above the SMA."

RSI does not need ATR normalization because it is already a self-normalizing oscillator bounded between 0 and 100.

**Source**: Wilder (1978) introduced ATR specifically for this purpose — measuring "true range" as a volatility-adjusted unit for comparing price movements.

## Three Construction Modes

### Mode 1: Manual

The user sets exact indicator types and parameters:

```
Tendance:   SMA, period = 50
Momentum:   MACD, fast = 12, slow = 26, signal = 9
Oscillation: RSI, period = 14
Volume:     OBV, ema_period = 20
```

All parameters are fixed. WFO parameter count from this section: **0**.

**When to use**: The user has strong domain knowledge about which parameters work for this stock, or wants full control.

### Mode 2: Semi-WFO

The user picks the indicator types but defines scan ranges for WFO to find optimal parameters:

```
Tendance:   SMA, period = WFO(min=20, max=200, step=10)
Momentum:   MACD, fast = WFO(min=8, max=16, step=2), slow = 26, signal = 9
Oscillation: RSI, period = 14
Volume:     OBV, ema_period = WFO(min=10, max=50, step=5)
```

Some parameters are fixed, others are flagged for WFO. WFO parameter count from this section: **3** (SMA period, MACD fast, OBV ema_period).

**When to use**: The user knows which indicator types to use but wants the optimizer to find the best parameters.

### Mode 3: Full-WFO

WFO chooses the best indicator type per family AND the optimal parameters:

```
Tendance:   type = WFO([SMA, EMA, DEMA]), parameters = WFO(...)
Momentum:   type = WFO([MACD, Stochastic, CCI]), parameters = WFO(...)
```

Both the type selection and the parameter search are part of the optimization. WFO parameter count: higher.

**When to use**: The user wants maximum optimization flexibility. Only available when multiple indicator types per family are implemented (future).

**Note**: In v1, only one indicator type per family is available, so Full-WFO reduces to Semi-WFO with all parameters flagged for optimization.

## Per-Family Configuration

For each family, the Signal Construction section shows:

| Field | Manual | Semi-WFO | Full-WFO |
|-------|--------|----------|----------|
| Indicator type | User selects | User selects | WFO selects |
| Parameters | User sets exact values | User sets scan ranges | WFO determines |
| Score preview | Computed from fixed params | Shown for current (seed) values | Shown for current (seed) values |
| WFO param count | 0 | N (one per flagged param) | N + type selection |

## Score Preview

When the user configures indicator parameters (or seed values for WFO), the backend can compute a preview of the indicator scores for the focused stock. This preview shows:

- current score value
- recent score history (sparkline)
- score distribution (histogram)

This helps the user calibrate entry/exit thresholds in the next sections.

## Inputs

- per-stock indicator configuration from the draft
- OHLCV data for the stock
- ATR(14) for normalization
- available indicator types per family (v1: one per family)

## Outputs

- per-family continuous scores for the stock
- WFO parameter count contribution from this section
- score preview data for the UI

## Edge Cases

### Indicator type not yet available

If the user's saved config references an indicator type not yet implemented (e.g., EMA):

- the section should show a warning: "EMA is not yet available. Using SMA as fallback."
- the fallback should be explicit, not silent

### Insufficient data for parameter

If the SMA period is 200 but the stock has only 150 bars:

- the section should warn: "SMA(200) requires at least 200 bars. This stock has 150."
- the score cannot be computed; downstream sections should reflect this

### All families disabled

If no families are configured:

- entry/exit rules cannot reference any scores
- the review section should flag this as blocking

## Cross-Links

- The scoring formulas produce the inputs for entry rules: see [06-entry-rules-layer.md](./06-entry-rules-layer.md)
- ATR normalization rationale is supported by Wilder (1978): see [12-methodology-and-sources.md](./12-methodology-and-sources.md)
- The signal engine's archetype system (Phase 1) is described in [../signal-generation/02-candidate-universe.md](../signal-generation/02-candidate-universe.md)
- Strategy type influences the suggested indicator ordering: see [04-strategy-type-layer.md](./04-strategy-type-layer.md)
