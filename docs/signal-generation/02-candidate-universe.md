# 02 — Layer A: Candidate Universe Generation

**File**: `core/quant_core/signal_engine/candidates.py`

---

## Purpose

Layer A generates a structured set of 30 candidate variants per (family, horizon) combination. These candidates are not random — each parameter point is chosen based on practitioner conventions, economic reasoning, and horizon-appropriate scaling.

The candidate universe is deliberately small and structured because:
- **Multiple testing cost**: every additional candidate increases the chance of false positives (Harvey et al. 2016)
- **Computational cost**: each candidate goes through full OOS evaluation (Layer B)
- **Interpretability**: each candidate should have a clear human-readable description

## Horizon Mapping (Recalibrated)

The current candidate universe follows the recalibration in [14-indicator-recalibration.md](./14-indicator-recalibration.md):

| Horizon | Thesis duration | Canonical 1D bar band |
|---------|-----------------|-----------------------|
| `short` | 1 week to 1 month | 5-20 bars |
| `medium` | 1 month to 3-4 months | 21-80 bars |
| `long` | 6 months to 1 year+ | 120-250 bars |

The 80-120 bar zone is intentionally excluded. Where a family cannot honestly span that full structural band because of bounded-oscillator math, its long-horizon grid is treated as a long-thesis filter rather than a literal 6-12 month clock.

For implementation details, the engine still enforces exactly 30 candidates per `(family, horizon)` pair:

- Single-parameter families widen the upper bound when the ideal band has fewer than 30 integers.
- Multi-parameter families use small deterministic base grids and canonical ordering.
- Threshold-extended families use period x threshold Cartesian products to keep 30 slots without stretching the period beyond what the indicator can support.

---

## Registry Architecture

Candidates are registered via a decorator pattern:

```python
@register_family(family="sma")
def _sma_candidates(horizon: str) -> list[VariantDef]:
    ...
```

Public entry point:
```python
generate_candidates(family: str, horizon: str) → list[VariantDef]
```

Raises `ValueError` if family or horizon is unknown. This ensures new families must be explicitly registered.

---

## The 20 Indicator Families (4 categories × 5)

> Each category groups 5 indicator families that answer the same market question.
> Every family generates exactly 30 candidates per horizon — the pipeline scales linearly.

---

### Category: TENDANCE (5 families)

**Signal type**: `trend` — Labels: Haussier / Baissier / Neutre
**Question answered**: "Le prix est-il en tendance haussière ou baissière ?"

#### 1. SMA (Simple Moving Average)

**Archetype**: `price_vs_sma`
**Signal rule**: +1 if close > SMA(window), -1 if close < SMA(window), 0 otherwise
**Economic rationale**: Price above its moving average indicates an uptrend. This is the simplest and most widely used trend indicator (Murphy 1999, Chapter 9). The SMA acts as a dynamic support/resistance level.

**Parameter**: `window` (lookback period in bars)

| Horizon | Windows (30 values) |
|---------|--------------------|
| Short | 3, 5, 7, 8, 10, 12, 13, 15, 17, 18, 20, 22, 23, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65, 75, 90 |
| Medium | 10, 15, 18, 20, 22, 25, 27, 30, 33, 35, 38, 40, 45, 48, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200, 250 |
| Long | 20, 30, 40, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 140, 150, 160, 175, 190, 200, 220, 240, 260, 280, 300, 330, 350, 375, 400 |

**Scaling rationale**: Short-term horizons use faster SMAs (3–90) to capture short-lived trends. Long-term horizons use slower SMAs (20–400) to capture structural trends. The overlap region (20–90) is common across all horizons — these are the "classic" SMA periods widely used by practitioners.

#### 2. EMA (Exponential Moving Average)

**Archetype**: `price_vs_ema`
**Signal rule**: +1 if close > EMA(window), -1 if close < EMA(window), 0 otherwise
**Economic rationale**: EMA places more weight on recent prices than SMA, making it faster to react to trend changes (Murphy 1999, Ch. 9). While SMA is a lagging filter, EMA captures trend shifts earlier — the two are complementary and will typically have low-to-moderate correlation for the same lookback period.

**Parameter**: `window` (lookback period in bars)

| Horizon | Windows (30 values) |
|---------|--------------------|
| Short | Same as SMA short |
| Medium | Same as SMA medium |
| Long | Same as SMA long |

**Scaling rationale**: Same as SMA — the EMA window has the same economic meaning (lookback), just with exponential weighting.

#### 3. EMA Cross (Dual EMA Crossover)

**Archetype**: `ema_cross`
**Signal rule**: +1 if EMA(fast) > EMA(slow), -1 if EMA(fast) < EMA(slow), 0 otherwise
**Economic rationale**: Dual MA crossover is the classic trend-following signal (Murphy 1999, Ch. 9). The fast EMA captures short-term momentum; the slow EMA represents the trend. Crossover = momentum aligning with (or against) trend.

**Parameters**: `fast` (short EMA), `slow` (long EMA)

| Horizon | Fast (6 values) | Slow (5 values) | Total |
|---------|----------------|-----------------|-------|
| Short | 5, 8, 10, 12, 15, 20 | 20, 25, 30, 40, 50 | 30 |
| Medium | 10, 15, 20, 25, 30, 40 | 50, 60, 75, 100, 150 | 30 |
| Long | 20, 30, 40, 50, 60, 75 | 100, 120, 150, 200, 250 | 30 |

Constraint: `fast < slow` always. Generate all valid pairs, take first 30.

#### 4. Ichimoku (Ichimoku Kinko Hyo)

**Archetype**: `ichi_cloud`
**Signal rule**: +1 if `close > cloud_top AND tenkan > kijun`, -1 if `close < cloud_bottom AND tenkan < kijun`, 0 otherwise (inside cloud or conflicting)
**Economic rationale**: Ichimoku is a multi-period equilibrium system developed by Hosoda (1969). It measures trend direction through the cloud (support/resistance zone) and momentum through the tenkan/kijun cross. Its methodology is fundamentally different from MA-based indicators, ensuring low correlation with SMA/EMA signals.

**Parameters**: `tenkan` (short period), `kijun` (medium period), `senkou_b` (long period)

| Horizon | Tenkan (5) | Kijun (3) | Senkou B (2) | Total |
|---------|-----------|----------|-------------|-------|
| Short | 7, 9, 12, 15, 18 | 22, 26, 30 | 44, 52 | 30 |
| Medium | 9, 12, 15, 18, 22 | 26, 30, 40 | 52, 65 | 30 |
| Long | 12, 15, 18, 22, 26 | 30, 40, 52 | 65, 80 | 30 |

Constraint: `tenkan < kijun < senkou_b` always.

**Cloud computation**: `cloud_top = max(senkou_a, senkou_b)`, `cloud_bottom = min(senkou_a, senkou_b)`. Senkou spans are used unshifted for signal computation (current-bar assessment).

#### 5. Parabolic SAR (Stop and Reverse)

**Archetype**: `psar_trend`
**Signal rule**: +1 if `close > SAR` (dots below price = uptrend), -1 if `close < SAR` (dots above price = downtrend)
**Economic rationale**: Created by Wilder (1978), PSAR provides a trailing stop that accelerates as the trend strengthens. It is the only indicator with a built-in reversal mechanism. Wilder notes it works best in trending markets (~30% of the time); the OOS evaluation naturally penalizes it in ranging markets.

**Parameters**: `af_step` (acceleration factor increment), `af_max` (maximum acceleration)

| Horizon | af_step (6) | af_max (5) | Total |
|---------|------------|-----------|-------|
| Short | 0.01, 0.015, 0.02, 0.025, 0.03, 0.04 | 0.15, 0.20, 0.25, 0.30, 0.40 | 30 |
| Medium | 0.01, 0.015, 0.02, 0.025, 0.03, 0.04 | 0.15, 0.20, 0.25, 0.30, 0.40 | 30 |
| Long | 0.005, 0.01, 0.015, 0.02, 0.025, 0.03 | 0.10, 0.15, 0.20, 0.25, 0.30 | 30 |

Long horizon uses smaller af_step (slower acceleration) and smaller af_max (tighter trailing) because structural trends move more slowly.

**Note**: PSAR always produces a directional signal (never 0) — the SAR is always either above or below price.

---

### Category: MOMENTUM (5 families)

**Signal type**: `momentum` — Labels: Momentum haussier / Momentum baissier / Pas de momentum
**Question answered**: "Le mouvement s'accélère-t-il ou décélère-t-il ?"

#### 6. MACD (Moving Average Convergence/Divergence)

Existing — see below.

#### 7. ROC (Rate of Change)

**Archetype**: `roc_zero`
**Signal rule**: +1 if ROC(n) > 0, -1 if ROC(n) < 0, 0 if ROC(n) == 0
**Economic rationale**: ROC = `(close - close[n]) / close[n] × 100` — the simplest momentum measure: raw percentage price change over N periods (Murphy 1999, Ch. 10). Positive ROC = price rising, negative = price falling.

**Parameter**: `period`

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 25, 27, 30, 33, 35, 40, 45, 50, 55, 60, 65 |
| Medium | 5, 7, 10, 12, 14, 15, 18, 20, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 175, 200 |
| Long | 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 175, 190, 200, 225, 250, 280, 300, 350 |

#### 8. TRIX (Triple Exponential Average Rate of Change)

**Archetype**: `trix_zero`
**Signal rule**: +1 if TRIX(n) > 0, -1 if TRIX(n) < 0, 0 if TRIX(n) == 0
**Economic rationale**: TRIX = rate of change of a triple-smoothed EMA (Hutson 1983, *Stocks & Commodities*). Triple smoothing eliminates noise that causes false signals in ROC and MACD. TRIX > 0 means the smoothed trend is still accelerating upward.

**Parameter**: `period` (EMA period for each of the 3 smoothings)

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65, 75 |
| Medium | 10, 12, 14, 15, 18, 20, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200, 250 |
| Long | 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 160, 175, 190, 200, 225, 250, 280, 300, 330, 375, 400 |

**Warmup**: 3 × (period - 1) bars (three successive EMAs).

#### 9. ADX/DMI (Average Directional Index / Directional Movement)

**Archetype**: `adx_trend`
**Signal rule**: +1 if `+DI > -DI AND ADX > threshold`, -1 if `-DI > +DI AND ADX > threshold`, 0 if `ADX < threshold`
**Economic rationale**: Created by Wilder (1978). The Directional Movement system measures how much of each day's range extends beyond the prior day's range (+DM = upward, -DM = downward). ADX averages the directional movement into a trend-strength reading. The neutral zone (ADX < threshold) avoids false signals in trendless markets.

**Parameters**: `period` (smoothing), `adx_threshold` (minimum ADX for signal)

| Horizon | Period (10) | ADX Threshold (3) | Total |
|---------|-----------|-------------------|-------|
| Short | 7, 9, 10, 11, 12, 13, 14, 15, 18, 20 | 20, 25, 30 | 30 |
| Medium | 10, 12, 14, 15, 18, 20, 22, 25, 28, 30 | 20, 25, 30 | 30 |
| Long | 14, 18, 20, 22, 25, 28, 30, 35, 40, 50 | 20, 25, 30 | 30 |

#### 10. TSI (True Strength Index)

**Archetype**: `tsi_zero`
**Signal rule**: +1 if TSI > 0, -1 if TSI < 0, 0 if TSI == 0
**Economic rationale**: TSI = double-smoothed momentum normalized by double-smoothed absolute momentum (Blau 1991, *Stocks & Commodities*). It measures what fraction of price movement is directional vs. noise. Range approximately [-100, +100]. TSI > 0 means net momentum is upward.

**Parameters**: `long_period` (first EMA), `short_period` (second EMA)

| Horizon | Long Period (6) | Short Period (5) | Total |
|---------|----------------|-----------------|-------|
| Short | 15, 18, 20, 22, 25, 30 | 7, 9, 11, 13, 15 | 30 |
| Medium | 20, 22, 25, 28, 30, 35 | 9, 11, 13, 15, 18 | 30 |
| Long | 25, 28, 30, 35, 40, 50 | 11, 13, 15, 18, 22 | 30 |

Constraint: `long_period > short_period` always.

---

### Category: OSCILLATION (5 families)

**Signal type**: `oscillator` — Labels: Survendu / Suracheté / Normal
**Question answered**: "Le prix est-il à un extrême statistique ?"

#### 11. RSI (Relative Strength Index)

**Archetype**: `rsi_level`
**Signal rule**: +1 if RSI < oversold (buy on weakness), -1 if RSI > overbought (sell on strength), 0 otherwise
**Economic rationale**: Extreme RSI indicates overextension that tends to revert (Wilder 1978). Oversold = excessive selling, likely bounce. Overbought = excessive buying, likely pullback.

**Parameters**: `period` (lookback), `oversold` (lower threshold), `overbought` (upper threshold)

| Horizon | Periods (10 values) | Thresholds (3 pairs) |
|---------|---------------------|---------------------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15 | (30,70), (25,75), (20,80) |
| Medium | 7, 9, 10, 12, 14, 17, 20, 21, 25, 30 | (30,70), (25,75), (20,80) |
| Long | 10, 14, 17, 20, 21, 25, 28, 30, 35, 40 | (30,70), (25,75), (20,80) |

**30 candidates** = 10 periods × 3 threshold pairs

**Threshold rationale**: (30,70) is the Wilder standard. (25,75) and (20,80) are stricter — they trade less frequently but with higher conviction. Including all three tests whether the signal works better with standard or extreme thresholds.

#### 12. Stochastic Oscillator

**Archetype**: `stoch_level`
**Signal rule**: +1 if `%K < 20 AND %K > %D` (oversold + rising), -1 if `%K > 80 AND %K < %D` (overbought + falling), 0 otherwise
**Economic rationale**: Created by George Lane (1984). Stochastic measures where the close sits within the recent high-low range. Unlike RSI which uses price momentum, Stochastic uses price *position* — genuinely different input, ensuring low correlation. The %K/%D cross confirms the direction of mean-reversion.

**Parameters**: `k_period` (%K lookback), `d_period` (%D smoothing)

| Horizon | K Period (10) | D Period (3) | Total |
|---------|-------------|-------------|-------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15 | 3, 5, 7 | 30 |
| Medium | 7, 9, 10, 12, 14, 17, 20, 21, 25, 30 | 3, 5, 7 | 30 |
| Long | 10, 14, 17, 20, 21, 25, 28, 30, 35, 40 | 3, 5, 7 | 30 |

**Note**: Thresholds (20, 80) are hardcoded in the signal function — standard practitioner convention.

#### 13. CCI (Commodity Channel Index)

**Archetype**: `cci_level`
**Signal rule**: +1 if `CCI < -100` (oversold), -1 if `CCI > +100` (overbought), 0 otherwise
**Economic rationale**: Created by Donald Lambert (1980, *Commodities Magazine*). CCI measures deviation of typical price `(H+L+C)/3` from its moving average, normalized by mean deviation. Readings beyond ±100 indicate statistically extreme conditions. Uses a fundamentally different input (typical price) and normalization (mean deviation) than RSI or Stochastic.

**Parameter**: `period`

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 23, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65 |
| Medium | 10, 12, 14, 15, 18, 20, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200, 250 |
| Long | 14, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 160, 175, 190, 200, 225, 250, 280, 300, 330, 375, 400 |

**Note**: Thresholds (±100) are hardcoded — the Lambert standard, capturing ~20-30% of readings.

#### 14. MFI (Money Flow Index)

**Archetype**: `mfi_level`
**Signal rule**: +1 if `MFI < oversold`, -1 if `MFI > overbought`, 0 otherwise
**Economic rationale**: Created by Quong & Soudack (1989, *TASC*). MFI is "volume-weighted RSI" — it incorporates volume into the momentum calculation. When volume diverges from price, MFI produces a different signal than RSI, making it a genuinely complementary oscillator.

**Parameters**: `period`, `oversold`, `overbought`

| Horizon | Periods (10) | Thresholds (3 pairs) | Total |
|---------|-------------|---------------------|-------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15 | (20,80), (15,85), (10,90) | 30 |
| Medium | 7, 9, 10, 12, 14, 17, 20, 21, 25, 30 | (20,80), (15,85), (10,90) | 30 |
| Long | 10, 14, 17, 20, 21, 25, 28, 30, 35, 40 | (20,80), (15,85), (10,90) | 30 |

**Note**: MFI requires volume data. Same threshold structure as RSI but stricter pairs because MFI is already more selective (volume-weighted).

#### 15. Ultimate Oscillator

**Archetype**: `uo_level`
**Signal rule**: +1 if `UO < 30` (oversold), -1 if `UO > 70` (overbought), 0 otherwise
**Economic rationale**: Created by Larry Williams (1985, *TASC*). UO combines three timeframes (short/medium/long buying pressure) into one oscillator, weighted 4:2:1 favoring the shortest. This multi-timeframe approach reduces false divergences that plague single-period oscillators.

**Parameters**: `period_1` (short), `period_2` (medium), `period_3` (long)

| Horizon | Period 1 (5) | Period 2 (3) | Period 3 (2) | Total |
|---------|------------|------------|-------------|-------|
| Short | 5, 6, 7, 8, 10 | 12, 14, 16 | 24, 28 | 30 |
| Medium | 7, 8, 10, 12, 14 | 14, 18, 21 | 28, 35 | 30 |
| Long | 10, 12, 14, 18, 21 | 21, 28, 35 | 42, 56 | 30 |

Constraint: `period_1 < period_2 < period_3` always.

---

### Category: VOLUME (5 families)

**Signal type**: `volume` — Labels: Accumulation / Distribution / Neutre
**Question answered**: "Le volume confirme-t-il le mouvement de prix ?"

---

> **Note**: MACD (family #6) and OBV (family #16) are listed below in their original doc position. Their category assignments are: MACD → Momentum, OBV → Volume.

### MACD (Moving Average Convergence/Divergence) — Momentum family #6

**Archetype**: `macd_cross`
**Signal rule**: +1 if MACD line > signal line (bullish crossover), -1 if MACD line < signal line (bearish crossover), 0 otherwise
**Economic rationale**: MACD measures the acceleration of trend by comparing short-term vs long-term EMAs (Appel 1979). A positive MACD-to-signal crossover indicates increasing bullish momentum.

**Parameters**: `fast` (short EMA), `slow` (long EMA), `signal` (signal EMA)

| Horizon | Fast (5) | Slow (3) | Signal (2) |
|---------|----------|----------|------------|
| Short | 6, 8, 10, 12, 15 | 16, 20, 26 | 7, 9 |
| Medium | 8, 10, 12, 15, 18 | 20, 26, 30 | 7, 9 |
| Long | 10, 12, 15, 18, 20 | 26, 30, 35 | 9, 12 |

**30 candidates** = 5 fast × 3 slow × 2 signal

**Parameter rationale**: The classic MACD uses (12, 26, 9). We explore a neighborhood around this canonical choice, scaling fast/slow periods with the horizon.

### OBV (On-Balance Volume) — Volume family #16

**Archetype**: `obv_trend`
**Signal rule**: +1 if OBV > EMA(OBV, period), -1 if OBV < EMA(OBV, period), 0 otherwise
**Economic rationale**: OBV accumulates volume on up-days and distributes on down-days (Granville 1963). When OBV rises above its moving average, buying pressure is accumulating — a confirmation signal for trend direction.

**Parameter**: `ema_period` (EMA smoothing of OBV)

| Horizon | EMA Periods (30 values) |
|---------|------------------------|
| Short | Same as SMA short windows |
| Medium | Same as SMA medium windows |
| Long | Same as SMA long windows |

**Scaling rationale**: OBV is a cumulative series, so its smoothing period should match the trend horizon — same logic as SMA window selection.

#### 17. CMF (Chaikin Money Flow)

**Archetype**: `cmf_flow`
**Signal rule**: +1 if `CMF(n) > +0.05` (buying pressure), -1 if `CMF(n) < -0.05` (selling pressure), 0 otherwise
**Economic rationale**: Created by Marc Chaikin (1986). CMF measures money flow over a window using the Close Location Value: `CLV = ((C-L)-(H-C))/(H-L)`. Unlike OBV (cumulative, binary up/down), CMF is windowed and uses where in the bar's range the close fell — different input, different time horizon, low correlation.

**Parameter**: `period`

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 21, 22, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65 |
| Medium | 10, 12, 14, 15, 18, 20, 21, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200 |
| Long | 14, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 160, 175, 190, 200, 225, 250, 280, 300, 330, 375, 400 |

**Note**: Threshold ±0.05 is hardcoded — practitioner convention to filter noise around zero.

#### 18. A/D Line (Accumulation/Distribution Line)

**Archetype**: `ad_trend`
**Signal rule**: +1 if `A/D > EMA(A/D)`, -1 if `A/D < EMA(A/D)`, 0 if equal
**Economic rationale**: Developed by Williams (1972), adapted by Chaikin. The A/D Line is cumulative: `AD[i] = AD[i-1] + CLV[i] × volume[i]`. Unlike OBV's binary up/down, A/D weights each bar by where in the range the close fell. This distinguishes between a close near the high (strong accumulation) vs. a close barely above prior close (weak OBV signal).

**Parameter**: `ema_period` (EMA smoothing of A/D Line)

| Horizon | EMA Periods (30 values) |
|---------|------------------------|
| Short | Same as SMA short windows |
| Medium | Same as SMA medium windows |
| Long | Same as SMA long windows |

#### 19. VWAP Deviation (Volume-Weighted Average Price)

**Archetype**: `vwap_dev`
**Signal rule**: +1 if `close > VWAP × (1 + threshold%)`, -1 if `close < VWAP × (1 - threshold%)`, 0 within band
**Economic rationale**: VWAP = rolling `sum(close × volume) / sum(volume)` — the price institutions benchmark against (Berkowitz et al. 1988, *Journal of Finance*). When price deviates significantly from VWAP, it signals institutional imbalance.

**Parameters**: `period`, `threshold_pct`

| Horizon | Period (10) | Threshold % (3) | Total |
|---------|-----------|-----------------|-------|
| Short | 5, 7, 10, 12, 14, 15, 18, 20, 25, 30 | 0.5, 1.0, 2.0 | 30 |
| Medium | 10, 14, 20, 25, 30, 40, 50, 60, 75, 100 | 0.5, 1.0, 2.0 | 30 |
| Long | 20, 30, 40, 50, 60, 75, 100, 120, 150, 200 | 0.5, 1.0, 2.0 | 30 |

**Note**: For daily data, VWAP is computed as a rolling window (not intraday reset).

#### 20. Force Index

**Archetype**: `fi_trend`
**Signal rule**: +1 if `EMA(ForceIndex, n) > 0`, -1 if `EMA(ForceIndex, n) < 0`, 0 if zero
**Economic rationale**: Created by Alexander Elder (1993, *Trading for a Living*). Force Index = `(close - prev_close) × volume`. It directly measures the "force" behind a move: large price change + high volume = strong force. Smoothed with EMA to reduce noise. Fundamentally different from OBV/CMF/A/D because it multiplies price change by volume rather than using binary direction or CLV.

**Parameter**: `period` (EMA smoothing of raw Force Index)

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | Same as SMA short windows |
| Medium | Same as SMA medium windows |
| Long | Same as SMA long windows |

---

## Variant ID Generation

**File**: `core/quant_core/signal_engine/_hashing.py`

Each variant gets a deterministic, stable identifier:

```python
def compute_variant_id(family: str, params: dict) -> str:
    canonical = {"_family": family.strip().lower()}
    canonical.update(dict(sorted(params.items())))
    content = json.dumps(canonical, sort_keys=True, allow_nan=False, default=str)
    hex16 = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"sv_{hex16}"
```

**Format**: `sv_<16 hex chars>` (e.g., `sv_a1b2c3d4e5f6g7h8`)

**Properties**:
- Deterministic: same (family, params) always produces the same ID
- Stable: ID doesn't change if code is refactored
- Collision-resistant: SHA256 truncated to 64 bits — sufficient for 120 variants
- Human-scannable: `sv_` prefix identifies it as a signal variant

---

## VariantDef Dataclass

```python
@dataclass(frozen=True)
class VariantDef:
    variant_id: str       # "sv_<hex16>"
    family: str           # "sma", "ema", "ema_cross", "ichimoku", "psar",
                          # "macd", "roc", "trix", "adx", "tsi",
                          # "rsi", "stochastic", "cci", "mfi", "uo",
                          # "obv", "cmf", "ad", "vwap", "fi"
    archetype: str        # one archetype per family (see table above)
    params: dict          # {"window": 20} or {"fast": 12, "slow": 26, "signal": 9}
    description: str      # "SMA-20 Price-Level (medium)"
```

Frozen (immutable) to prevent accidental mutation during pipeline processing.

---

## Why 30 Candidates?

The choice of 30 per family is deliberate:

1. **Statistical**: With 30 candidates and a 5% false positive rate, ~1.5 candidates would pass by chance. The viability gate (40% positive windows + 3 valid windows) is much stricter than 5%, so the actual false positive rate is lower.

2. **Computational**: 30 candidates × 20 families = 600 total. Each goes through full OOS evaluation (~5–15 windows per candidate). Families are independent and cacheable, so this runs in seconds per family on modern hardware.

3. **Coverage**: 30 parameter points provide good coverage of the economically meaningful parameter space without testing every integer. The grid is denser in the "sweet spot" (e.g., SMA 10–50 for medium horizon) and sparser at the extremes.

4. **Extensibility**: Each family adds exactly 30 candidates — the pipeline scales linearly. The redundancy reduction (Layer E) handles any correlation between families within the same category.
