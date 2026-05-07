# Strategy Layer — Signal Construction Layer

## What

The Signal Construction section defines **which indicators to use and how to compute their scores** for each stock in the basket. For each of the four indicator families, the user chooses:

0. Which **strategy horizon** is active (`short`, `medium`, `long`)
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

The horizon selector belongs in this section because horizon meaning is primarily about indicator construction. The selected horizon drives:

- signal previews for the focused stock
- the active WFO search space used across entry, exit, and risk
- the preset ranges surfaced to the backtest handoff

## The Four Indicator Families

### Available Indicators (20 total, 5 per category)

| Category | Family ID | Indicator | Score Range | Source |
|----------|-----------|-----------|-------------|--------|
| **Tendance** | `sma` | SMA | Unbounded (ATR-normalized) | Murphy (1999) |
| | `ema` | EMA | Unbounded (ATR-normalized) | Murphy (1999) |
| | `ema_cross` | EMA Cross | Unbounded (ATR-normalized) | Murphy (1999) |
| | `ichimoku` | Ichimoku | Unbounded (ATR-normalized) | Hosoda (1969) |
| | `psar` | Parabolic SAR | Unbounded (ATR-normalized) | Wilder (1978) |
| **Momentum** | `macd` | MACD | Unbounded (ATR-normalized) | Appel (1979) |
| | `roc` | Rate of Change | Unbounded (percentage) | Murphy (1999) |
| | `trix` | TRIX | Unbounded (percentage) | Hutson (1983) |
| | `adx` | ADX/DMI | 0–100 (native) | Wilder (1978) |
| | `tsi` | TSI | ~[-100, +100] (native) | Blau (1991) |
| **Oscillation** | `rsi` | RSI | 0–100 (native) | Wilder (1978) |
| | `stochastic` | Stochastic | 0–100 (native) | Lane (1984) |
| | `cci` | CCI | Unbounded (~±300) | Lambert (1980) |
| | `mfi` | MFI | 0–100 (native) | Quong & Soudack (1989) |
| | `uo` | Ultimate Oscillator | 0–100 (native) | Williams (1985) |
| **Volume** | `obv` | OBV | Unbounded (ratio) | Granville (1963) |
| | `cmf` | CMF | [-1, +1] (native) | Chaikin (1986) |
| | `ad` | A/D Line | Unbounded (ratio) | Williams (1972) |
| | `vwap` | VWAP Deviation | Unbounded (percentage) | Berkowitz (1988) |
| | `fi` | Force Index | Unbounded (ATR-normalized) | Elder (1993) |

## Continuous Scoring Formulas

Each indicator family produces a **continuous score** — not a binary buy/sell signal. Continuous scores enable graduated entry and exit at multiple conviction levels (see [06-entry-rules-layer.md](./06-entry-rules-layer.md)).

### Tendance

Each trend indicator produces a continuous score using ATR normalization:

| Indicator | Continuous Score Formula |
|-----------|------------------------|
| SMA | `(close - SMA(w)) / ATR(14)` |
| EMA | `(close - EMA(w)) / ATR(14)` |
| EMA Cross | `(EMA(fast) - EMA(slow)) / ATR(14)` |
| Ichimoku | `(close - kijun_sen) / ATR(14)` |
| PSAR | `(close - SAR) / ATR(14)` |

- **Positive** when price is above the reference (bullish trend)
- **Negative** when price is below (bearish trend)
- **Magnitude** reflects ATR units of deviation

### Momentum

| Indicator | Continuous Score Formula |
|-----------|------------------------|
| MACD | `MACD_histogram / ATR(14)` |
| ROC | `ROC(n)` (already a percentage) |
| TRIX | `TRIX(n) × 1000` (scaled for readability) |
| ADX | `(+DI - -DI) × (ADX / 50)` (direction × strength) |
| TSI | `TSI` (already [-100, +100]) |

### Oscillation

Oscillators are already bounded and do not require ATR normalization:

| Indicator | Continuous Score | Range |
|-----------|-----------------|-------|
| RSI | `RSI(period)` | [0, 100] |
| Stochastic | `%K` | [0, 100] |
| CCI | `CCI(period)` | unbounded (~±300) |
| MFI | `MFI(period)` | [0, 100] |
| UO | `UO(p1,p2,p3)` | [0, 100] |

### Volume

| Indicator | Continuous Score Formula |
|-----------|------------------------|
| OBV | `(OBV - OBV_EMA) / OBV_EMA` (percentage deviation) |
| CMF | `CMF(period)` (already [-1, +1]) |
| A/D | `(A/D - A/D_EMA) / abs(A/D_EMA)` (percentage deviation) |
| VWAP | `(close - VWAP) / VWAP × 100` (percentage deviation) |
| Force Index | `EMA(FI) / ATR(14)` (ATR-normalized) |

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

## Horizon-Scoped Search Spaces

Each WFO parameter stores three presets internally:

- `short`
- `medium`
- `long`

Only the currently selected strategy horizon is editable at a time. Its preset is copied into the active `scan_min / scan_max / scan_step` fields that the review and backtest layers consume.

If a legacy saved strategy only has one WFO range, that range is copied to all three presets on load.

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

Default indicator search spaces follow the horizon table from the backtest methodology:

| Family | Short | Medium | Long |
|-------|-------|--------|------|
| SMA | 5-20 step 1 | 21-80 step 1 | 120-250 step 5 |
| RSI period | 5-14 step 1 | 14-28 step 1 | 21-50 step 1 |
| MACD fast | 5-10 step 1 | 10-18 step 1 | 18-30 step 1 |
| MACD slow | 12-20 step 1 | 22-45 step 1 | 50-100 step 2 |
| MACD signal | 5-9 step 1 | 7-12 step 1 | 9-18 step 1 |
| OBV EMA | 5-20 step 1 | 21-80 step 1 | 120-250 step 5 |

### Why these indicator intervals make sense

These defaults are not arbitrary UI placeholders. They are the first-pass search policy the app uses because they balance three things at once:

1. financial meaning
2. horizon meaning
3. WFO tractability

**Financial meaning**

- Short-horizon indicators should react to moves that matter over days to a few weeks. That is why their lookbacks stay short and their step sizes stay fine.
- Medium-horizon indicators should smooth part of the noise while still reacting to earnings cycles, sector moves, and multi-week swings.
- Long-horizon indicators should capture structural drift, regime persistence, and macro trend, which requires longer windows and coarser steps.

**Economic meaning**

- A short-horizon trader cares more about responsiveness than smoothness. Missing the turn by 10-20 bars can erase the edge.
- A long-horizon trader cares more about avoiding churn than about shaving a few bars off a moving-average period. The economic question is usually "is this a structural trend?" not "is 83 better than 84?"

**Logical meaning**

- Step size becomes coarser as the range widens because adjacent long lookbacks are economically similar. Testing every single value creates false precision without creating meaning.
- This follows the same WFO logic described in the backtest methodology: enough candidates to explore the domain, not so many that the optimizer spends its effort fitting noise.

### Why the app now uses the same horizon logic outside indicators

Signal Construction is where horizon is defined because horizon primarily describes how quickly information should decay inside the strategy. Once that choice is made, the same horizon should also shape:

- entry thresholds
- exit thresholds
- Kelly modifier search
- ATR stop distance
- reward-to-risk target
- cooldown length
- time stop length

Otherwise the app would mix a short-horizon signal engine with long-horizon risk geometry, or a long-horizon signal with intraday-like threshold ranges. The new design keeps those pieces economically consistent.

### Defaults are seeds, not hard caps

The implemented default tables are used as sensible starting presets. They are not a hard restriction:

- every WFO parameter stores separate `short`, `medium`, and `long` presets
- the active strategy horizon decides which preset is surfaced and handed to review/backtest
- if the current saved seed value sits outside the default band, the app widens the preset to include that value rather than silently overwriting it

That last rule matters because defaults should guide the search, not erase prior intent.

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
