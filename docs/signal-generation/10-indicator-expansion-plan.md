# 10 — Indicator Expansion: 4 → 20 Indicators Implementation Plan

> **Audience**: Codex / implementation agent
> **Scope**: Add 16 new indicators (4 new per family) to the existing A→G signal pipeline
> **Constraint**: Zero changes to pipeline logic (Layers C–E–G unchanged). Only extend registries, dispatchers, and display.

---

## Final Indicator List (20 total)

### TENDANCE — signal_type: `"trend"` — Labels: Haussier / Baissier / Neutre

| # | Family ID | Archetype | Signal Rule | Signal Style | Params | Source |
|---|-----------|-----------|-------------|-------------|--------|--------|
| 1 | `sma` ✓ | `price_vs_sma` | `close > SMA(w)` → +1, `close < SMA(w)` → -1 | state | `window` | Murphy (1999) |
| 2 | `ema` | `price_vs_ema` | `close > EMA(w)` → +1, `close < EMA(w)` → -1 | state | `window` | Murphy (1999) |
| 3 | `ema_cross` | `ema_cross` | `EMA(fast) > EMA(slow)` → +1, `EMA(fast) < EMA(slow)` → -1 | state | `fast`, `slow` | Murphy (1999) |
| 4 | `ichimoku` | `ichi_cloud` | `close > cloud_top AND tenkan > kijun` → +1, `close < cloud_bottom AND tenkan < kijun` → -1, else 0 | state | `tenkan`, `kijun`, `senkou_b` | Hosoda (1969) |
| 5 | `psar` | `psar_trend` | `close > SAR` → +1, `close < SAR` → -1 | state | `af_step`, `af_max` | Wilder (1978) |

### MOMENTUM — signal_type: `"momentum"` — Labels: Momentum haussier / Momentum baissier / Pas de momentum

| # | Family ID | Archetype | Signal Rule | Signal Style | Params | Source |
|---|-----------|-----------|-------------|-------------|--------|--------|
| 6 | `macd` ✓ | `macd_cross` | `MACD_line > signal_line` → +1, else → -1 | event | `fast`, `slow`, `signal` | Appel (1979) |
| 7 | `roc` | `roc_zero` | `ROC(n) > 0` → +1, `ROC(n) < 0` → -1, `ROC(n) == 0` → 0 | state | `period` | Murphy (1999) |
| 8 | `trix` | `trix_zero` | `TRIX(n) > 0` → +1, `TRIX(n) < 0` → -1, `TRIX(n) == 0` → 0 | state | `period` | Hutson (1983) |
| 9 | `adx` | `adx_trend` | `(+DI > -DI) AND (ADX > threshold)` → +1, `(-DI > +DI) AND (ADX > threshold)` → -1, `ADX < threshold` → 0 | state | `period`, `adx_threshold` | Wilder (1978) |
| 10 | `tsi` | `tsi_zero` | `TSI > 0` → +1, `TSI < 0` → -1, `TSI == 0` → 0 | state | `long_period`, `short_period` | Blau (1991) |

### OSCILLATION — signal_type: `"oscillator"` — Labels: Survendu / Suracheté / Normal

| # | Family ID | Archetype | Signal Rule | Signal Style | Params | Source |
|---|-----------|-----------|-------------|-------------|--------|--------|
| 11 | `rsi` ✓ | `rsi_level` | `RSI < oversold` → +1, `RSI > overbought` → -1, else → 0 | event | `period`, `oversold`, `overbought` | Wilder (1978) |
| 12 | `stochastic` | `stoch_level` | `(%K < 20) AND (%K > %D)` → +1, `(%K > 80) AND (%K < %D)` → -1, else → 0 | event | `k_period`, `d_period` | Lane (1984) |
| 13 | `cci` | `cci_level` | `CCI < -100` → +1, `CCI > +100` → -1, else → 0 | event | `period` | Lambert (1980) |
| 14 | `mfi` | `mfi_level` | `MFI < oversold` → +1, `MFI > overbought` → -1, else → 0 | event | `period`, `oversold`, `overbought` | Quong & Soudack (1989) |
| 15 | `uo` | `uo_level` | `UO < 30` → +1, `UO > 70` → -1, else → 0 | event | `period_1`, `period_2`, `period_3` | Williams (1985) |

### VOLUME — signal_type: `"volume"` — Labels: Accumulation / Distribution / Neutre

| # | Family ID | Archetype | Signal Rule | Signal Style | Params | Source |
|---|-----------|-----------|-------------|-------------|--------|--------|
| 16 | `obv` ✓ | `obv_trend` | `OBV > EMA(OBV)` → +1, `OBV < EMA(OBV)` → -1 | state | `ema_period` | Granville (1963) |
| 17 | `cmf` | `cmf_flow` | `CMF(n) > +0.05` → +1, `CMF(n) < -0.05` → -1, else → 0 | state | `period` | Chaikin (1986) |
| 18 | `ad` | `ad_trend` | `A/D > EMA(A/D)` → +1, `A/D < EMA(A/D)` → -1 | state | `ema_period` | Williams (1972) |
| 19 | `vwap` | `vwap_dev` | `close > VWAP × (1+seuil)` → +1, `close < VWAP × (1-seuil)` → -1, else → 0 | state | `period`, `threshold_pct` | Berkowitz (1988) |
| 20 | `fi` | `fi_trend` | `EMA(ForceIndex, n) > 0` → +1, `EMA(ForceIndex, n) < 0` → -1 | state | `period` | Elder (1993) |

---

## Parameter Grids Per Horizon (30 candidates each)

### TENDANCE

#### `ema` — `price_vs_ema` (30 window values)

Same parameter grid as `sma` — the EMA window has the same economic meaning as the SMA window (lookback period), just with exponential weighting.

| Horizon | Windows (30 values) |
|---------|---------------------|
| Short | 3, 5, 7, 8, 10, 12, 13, 15, 17, 18, 20, 22, 23, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65, 75, 90 |
| Medium | 10, 15, 18, 20, 22, 25, 27, 30, 33, 35, 38, 40, 45, 48, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200, 250 |
| Long | 20, 30, 40, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 140, 150, 160, 175, 190, 200, 220, 240, 260, 280, 300, 330, 350, 375, 400 |

#### `ema_cross` — `ema_cross` (30 fast×slow combinations)

| Horizon | Fast (6 values) | Slow (5 values) | Total |
|---------|----------------|-----------------|-------|
| Short | 5, 8, 10, 12, 15, 20 | 20, 25, 30, 40, 50 | 30 |
| Medium | 10, 15, 20, 25, 30, 40 | 50, 60, 75, 100, 150 | 30 |
| Long | 20, 30, 40, 50, 60, 75 | 100, 120, 150, 200, 250 | 30 |

Constraint: `fast < slow` always. Generate all valid `fast × slow` pairs, take first 30.

#### `ichimoku` — `ichi_cloud` (30 parameter triplets)

Standard Ichimoku uses (9, 26, 52). We explore a neighborhood scaled by horizon.

| Horizon | Tenkan (5) | Kijun (3) | Senkou B (2) | Total |
|---------|-----------|----------|-------------|-------|
| Short | 7, 9, 12, 15, 18 | 22, 26, 30 | 44, 52 | 30 |
| Medium | 9, 12, 15, 18, 22 | 26, 30, 40 | 52, 65 | 30 |
| Long | 12, 15, 18, 22, 26 | 30, 40, 52 | 65, 80 | 30 |

Constraint: `tenkan < kijun < senkou_b` always.

#### `psar` — `psar_trend` (30 af_step × af_max combinations)

Standard Parabolic SAR: af_step=0.02, af_max=0.20. We explore around these values.

| Horizon | af_step (6) | af_max (5) | Total |
|---------|------------|-----------|-------|
| Short | 0.01, 0.015, 0.02, 0.025, 0.03, 0.04 | 0.15, 0.20, 0.25, 0.30, 0.40 | 30 |
| Medium | 0.01, 0.015, 0.02, 0.025, 0.03, 0.04 | 0.15, 0.20, 0.25, 0.30, 0.40 | 30 |
| Long | 0.005, 0.01, 0.015, 0.02, 0.025, 0.03 | 0.10, 0.15, 0.20, 0.25, 0.30 | 30 |

Long horizon uses smaller af_step (slower acceleration) and smaller af_max (tighter trailing).

### MOMENTUM

#### `roc` — `roc_zero` (30 period values)

ROC period = lookback for `(close - close[n]) / close[n]`.

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 25, 27, 30, 33, 35, 40, 45, 50, 55, 60, 65 |
| Medium | 5, 7, 10, 12, 14, 15, 18, 20, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 175, 200 |
| Long | 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 175, 190, 200, 225, 250, 280, 300, 350 |

#### `trix` — `trix_zero` (30 period values)

TRIX period = EMA period for triple smoothing. Needs longer periods than ROC because of triple smoothing.

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65, 75 |
| Medium | 10, 12, 14, 15, 18, 20, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200, 250 |
| Long | 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 160, 175, 190, 200, 225, 250, 280, 300, 330, 375, 400 |

#### `adx` — `adx_trend` (30 period × threshold combinations)

| Horizon | Period (10) | ADX Threshold (3) | Total |
|---------|-----------|-------------------|-------|
| Short | 7, 9, 10, 11, 12, 13, 14, 15, 18, 20 | 20, 25, 30 | 30 |
| Medium | 10, 12, 14, 15, 18, 20, 22, 25, 28, 30 | 20, 25, 30 | 30 |
| Long | 14, 18, 20, 22, 25, 28, 30, 35, 40, 50 | 20, 25, 30 | 30 |

ADX threshold at 20, 25, 30 tests how strict the "trend exists" filter needs to be.

#### `tsi` — `tsi_zero` (30 long × short combinations)

Standard TSI: long=25, short=13. We explore around those values.

| Horizon | Long Period (6) | Short Period (5) | Total |
|---------|----------------|-----------------|-------|
| Short | 15, 18, 20, 22, 25, 30 | 7, 9, 11, 13, 15 | 30 |
| Medium | 20, 22, 25, 28, 30, 35 | 9, 11, 13, 15, 18 | 30 |
| Long | 25, 28, 30, 35, 40, 50 | 11, 13, 15, 18, 22 | 30 |

Constraint: `long_period > short_period` always.

### OSCILLATION

#### `stochastic` — `stoch_level` (30 k × d combinations)

Standard Stochastic: %K=14, %D=3. Thresholds are fixed at 20/80 (hardcoded in signal function, not candidate params).

| Horizon | K Period (10) | D Period (3) | Total |
|---------|-------------|-------------|-------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15 | 3, 5, 7 | 30 |
| Medium | 7, 9, 10, 12, 14, 17, 20, 21, 25, 30 | 3, 5, 7 | 30 |
| Long | 10, 14, 17, 20, 21, 25, 28, 30, 35, 40 | 3, 5, 7 | 30 |

#### `cci` — `cci_level` (30 period values)

CCI period = lookback for typical price moving average. Thresholds are fixed at ±100 (hardcoded in signal function).

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 23, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65 |
| Medium | 10, 12, 14, 15, 18, 20, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200, 250 |
| Long | 14, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 160, 175, 190, 200, 225, 250, 280, 300, 330, 375, 400 |

#### `mfi` — `mfi_level` (30 = 10 periods × 3 threshold pairs)

Same structure as RSI — period × threshold grid. MFI thresholds: (20, 80), (15, 85), (10, 90).

| Horizon | Periods (10) | Thresholds (3 pairs) | Total |
|---------|-------------|---------------------|-------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15 | (20,80), (15,85), (10,90) | 30 |
| Medium | 7, 9, 10, 12, 14, 17, 20, 21, 25, 30 | (20,80), (15,85), (10,90) | 30 |
| Long | 10, 14, 17, 20, 21, 25, 28, 30, 35, 40 | (20,80), (15,85), (10,90) | 30 |

#### `uo` — `uo_level` (30 triplets)

Standard UO: (7, 14, 28). We explore around those values. Thresholds 30/70 are hardcoded.

| Horizon | Period 1 (5) | Period 2 (3) | Period 3 (2) | Total |
|---------|------------|------------|-------------|-------|
| Short | 5, 6, 7, 8, 10 | 12, 14, 16 | 24, 28 | 30 |
| Medium | 7, 8, 10, 12, 14 | 14, 18, 21 | 28, 35 | 30 |
| Long | 10, 12, 14, 18, 21 | 21, 28, 35 | 42, 56 | 30 |

Constraint: `period_1 < period_2 < period_3` always. Generate valid triplets, take first 30.

### VOLUME

#### `cmf` — `cmf_flow` (30 period values)

CMF period = lookback for Chaikin Money Flow. Threshold ±0.05 is hardcoded in signal function.

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 21, 22, 25, 27, 28, 30, 33, 35, 38, 40, 42, 45, 48, 50, 55, 60, 65 |
| Medium | 10, 12, 14, 15, 18, 20, 21, 22, 25, 28, 30, 33, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 90, 100, 110, 120, 130, 150, 175, 200 |
| Long | 14, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 90, 100, 110, 120, 130, 150, 160, 175, 190, 200, 225, 250, 280, 300, 330, 375, 400 |

#### `ad` — `ad_trend` (30 ema_period values)

Same grid as OBV — A/D Line is a cumulative series smoothed by an EMA, same logic.

| Horizon | EMA Periods (30 values) |
|---------|------------------------|
| Short | Same as SMA short windows |
| Medium | Same as SMA medium windows |
| Long | Same as SMA long windows |

#### `vwap` — `vwap_dev` (30 period × threshold combinations)

Rolling VWAP over N periods, with threshold for deviation. For daily data, VWAP = sum(close × volume) / sum(volume) over rolling window.

| Horizon | Period (10) | Threshold % (3) | Total |
|---------|-----------|-----------------|-------|
| Short | 5, 7, 10, 12, 14, 15, 18, 20, 25, 30 | 0.5, 1.0, 2.0 | 30 |
| Medium | 10, 14, 20, 25, 30, 40, 50, 60, 75, 100 | 0.5, 1.0, 2.0 | 30 |
| Long | 20, 30, 40, 50, 60, 75, 100, 120, 150, 200 | 0.5, 1.0, 2.0 | 30 |

#### `fi` — `fi_trend` (30 period values)

Force Index EMA period. Force Index = (close - prev_close) × volume, then smoothed with EMA.

| Horizon | Periods (30 values) |
|---------|---------------------|
| Short | Same as SMA short windows |
| Medium | Same as SMA medium windows |
| Long | Same as SMA long windows |

---

## Indicator Computation Formulas

Each formula below must be implemented in `indicator_series.py`. All return arrays aligned to `close` with NaN warmup.

### Tendance

```python
def compute_ema_series(close, period) -> np.ndarray:
    """EMA with NaN warmup."""
    # Use optimize.ema(close, period). First period-1 bars = NaN.

def compute_ema_cross_series(close, fast, slow) -> tuple[np.ndarray, np.ndarray]:
    """Return (fast_ema, slow_ema) arrays."""

def compute_ichimoku_series(high, low, close, tenkan, kijun, senkou_b) -> dict:
    """Return dict with tenkan_sen, kijun_sen, senkou_a, senkou_b, cloud_top, cloud_bottom."""
    # tenkan_sen = (highest_high(tenkan) + lowest_low(tenkan)) / 2
    # kijun_sen = (highest_high(kijun) + lowest_low(kijun)) / 2
    # senkou_a = (tenkan_sen + kijun_sen) / 2
    # senkou_b = (highest_high(senkou_b) + lowest_low(senkou_b)) / 2
    # cloud_top = max(senkou_a, senkou_b)
    # cloud_bottom = min(senkou_a, senkou_b)
    # NOTE: Senkou spans are normally shifted forward 26 periods for display.
    #       For signal computation, use UNSHIFTED values (current bar assessment).

def compute_psar_series(high, low, close, af_step, af_max) -> np.ndarray:
    """Return SAR array. Standard Wilder algorithm."""
    # Start: SAR = first bar low (assume initial uptrend)
    # af starts at af_step, increments by af_step on each new extreme, capped at af_max
    # SAR[i] = SAR[i-1] + af × (EP - SAR[i-1])
    # Flip when price crosses SAR
```

### Momentum

```python
def compute_roc_series(close, period) -> np.ndarray:
    """ROC = (close - close[n]) / close[n] × 100. First n bars = NaN."""

def compute_trix_series(close, period) -> np.ndarray:
    """TRIX = 100 × (EMA3[i] - EMA3[i-1]) / EMA3[i-1]
    where EMA3 = EMA(EMA(EMA(close, period), period), period).
    First 3*(period-1) bars = NaN."""

def compute_adx_series(high, low, close, period) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (+DI, -DI, ADX) arrays. Wilder smoothing."""
    # +DM = max(high - prev_high, 0) if (high - prev_high) > (prev_low - low) else 0
    # -DM = max(prev_low - low, 0) if (prev_low - low) > (high - prev_high) else 0
    # TR = true_range(high, low, close)
    # +DI = 100 × wilder_smooth(+DM, period) / wilder_smooth(TR, period)
    # -DI = 100 × wilder_smooth(-DM, period) / wilder_smooth(TR, period)
    # DX = 100 × |+DI - -DI| / (+DI + -DI)
    # ADX = wilder_smooth(DX, period)

def compute_tsi_series(close, long_period, short_period) -> np.ndarray:
    """TSI = 100 × EMA(EMA(momentum, long), short) / EMA(EMA(|momentum|, long), short)
    where momentum = close - close[1]. Range approx [-100, +100]."""
```

### Oscillation

```python
def compute_stochastic_series(high, low, close, k_period, d_period) -> tuple[np.ndarray, np.ndarray]:
    """Return (%K, %D) arrays.
    %K = 100 × (close - lowest_low(k)) / (highest_high(k) - lowest_low(k))
    %D = SMA(%K, d_period)
    Range: [0, 100]."""

def compute_cci_series(high, low, close, period) -> np.ndarray:
    """CCI = (typical_price - SMA(typical_price, period)) / (0.015 × mean_deviation)
    where typical_price = (high + low + close) / 3.
    Unbounded, typically oscillates ±300."""

def compute_mfi_series(high, low, close, volume, period) -> np.ndarray:
    """MFI = 100 - 100 / (1 + positive_flow / negative_flow)
    where flow = typical_price × volume, positive when typical_price rises.
    Range: [0, 100]. Essentially volume-weighted RSI."""

def compute_uo_series(high, low, close, p1, p2, p3) -> np.ndarray:
    """Ultimate Oscillator = 100 × (4×avg1 + 2×avg2 + avg3) / 7
    where avg_n = sum(buying_pressure, n) / sum(true_range, n).
    buying_pressure = close - min(low, prev_close).
    Range: [0, 100]."""
```

### Volume

```python
def compute_cmf_series(high, low, close, volume, period) -> np.ndarray:
    """CMF = sum(CLV × volume, period) / sum(volume, period)
    where CLV = ((close - low) - (high - close)) / (high - low).
    Range: [-1, +1]."""

def compute_ad_series(high, low, close, volume) -> np.ndarray:
    """A/D Line (cumulative): AD[i] = AD[i-1] + CLV[i] × volume[i]
    where CLV = ((close - low) - (high - close)) / (high - low).
    Handle high == low (CLV = 0)."""

def compute_vwap_series(close, volume, period) -> np.ndarray:
    """Rolling VWAP = rolling_sum(close × volume, period) / rolling_sum(volume, period).
    First period-1 bars = NaN."""

def compute_force_index_series(close, volume, period) -> np.ndarray:
    """Force Index = EMA((close - prev_close) × volume, period).
    First period bars = NaN."""
```

---

## OHLCV Data Requirements

Several new indicators need `high`, `low`, `close`, `volume` — not just `close` and `volume`.

### Current signature:
```python
def _signal_fn(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray
```

### Required change:
The signal dispatch signature must be extended to accept `high` and `low` arrays. Two options:

**Option A (recommended)**: Add `high` and `low` as optional kwargs to `compute_signal_array()` and pass them through:
```python
def compute_signal_array(close, variant, *, volume=None, high=None, low=None) -> np.ndarray
```

Signal functions that need OHLC data declare it:
```python
@register_signal("ichimoku", "ichi_cloud")
def _ichi_signal(close, params, volume, *, high=None, low=None):
    ...
```

**Option B**: Pass a single `ohlcv` dict. More disruptive.

**Indicators needing high/low**: ichimoku, psar, adx, stochastic, cci, mfi, uo, cmf, vwap (9 of 16 new indicators).

### Upstream changes:
- `evaluate_variant_oos()` must accept and forward `high`, `low` arrays
- `run_family_ensemble_full()` must accept and forward `high`, `low` arrays
- API router must extract `high`, `low` from OHLCV DataFrame and pass them
- The `_get_or_compute()` cache function must include these in the computation call

---

## File-by-File Implementation Checklist

### Phase 1: Backend Signal Engine (core layer)

#### 1.1 `core/quant_core/signal_engine/domain.py`

Update two constants:

```python
FAMILY_SIGNAL_TYPE = {
    # Tendance
    "sma": "trend", "ema": "trend", "ema_cross": "trend",
    "ichimoku": "trend", "psar": "trend",
    # Momentum
    "macd": "momentum", "roc": "momentum", "trix": "momentum",
    "adx": "momentum", "tsi": "momentum",
    # Oscillation
    "rsi": "oscillator", "stochastic": "oscillator", "cci": "oscillator",
    "mfi": "oscillator", "uo": "oscillator",
    # Volume
    "obv": "volume", "cmf": "volume", "ad": "volume",
    "vwap": "volume", "fi": "volume",
}

CATEGORY_FAMILIES = {
    "tendance": ["sma", "ema", "ema_cross", "ichimoku", "psar"],
    "momentum": ["macd", "roc", "trix", "adx", "tsi"],
    "oscillation": ["rsi", "stochastic", "cci", "mfi", "uo"],
    "volume": ["obv", "cmf", "ad", "vwap", "fi"],
}
```

Add momentum label mapping in `signal_type_label()`:

```python
# Momentum labels (new):
# > 50: "Fort momentum haussier"
# 15–50: "Momentum haussier"
# -15–15: "Pas de momentum"
# -50–-15: "Momentum baissier"
# < -50: "Fort momentum baissier"
```

Add momentum variant labels in `variant_signal_label()`:

```python
# Momentum families: +1 → "MOMENTUM HAUSSIER", -1 → "MOMENTUM BAISSIER", 0 → "NEUTRE"
```

#### 1.2 `core/quant_core/signal_engine/indicator_series.py`

Add all 16 new computation functions listed in the "Indicator Computation Formulas" section above.

**Performance note**: Use NumPy vectorized operations. Avoid Python loops on bar data. For Ichimoku rolling min/max, use `np.lib.stride_tricks` or `pd.Series.rolling`. For PSAR, a Python loop is unavoidable (state-dependent), but keep it tight.

**Reuse existing helpers**: `ema()`, `rsi_wilder()`, `macd_pack()`, `obv_array()` from `core.quant_core.optimize` are already available.

#### 1.3 `core/quant_core/signal_engine/candidates.py`

Add 16 new `@register_family` generators. Each must:
1. Return exactly 30 `VariantDef` objects
2. Use `_make_variant(family, archetype, params, horizon)` helper
3. Define horizon-specific parameter grids as module-level dicts

Add to `variant_min_history()`:
```python
# New warmup estimates:
# ema: window
# ema_cross: slow
# ichimoku: senkou_b
# psar: 2 (minimal)
# roc: period
# trix: 3 * period
# adx: 2 * period (DI smoothing + ADX smoothing)
# tsi: long_period + short_period
# stochastic: k_period + d_period
# cci: period
# mfi: period
# uo: period_3 (largest)
# cmf: period
# ad: 1 (cumulative)
# vwap: period
# fi: period
```

#### 1.4 `core/quant_core/signal_engine/oos_eval.py`

Add 16 new `@register_signal` functions.

Update `compute_signal_array()` signature to accept `high`, `low` kwargs.

Add new archetypes to `_EVENT_SIGNAL_ARCHETYPES` set:
```python
_EVENT_SIGNAL_ARCHETYPES = {
    "sma_cross", "macd_cross", "rsi_level",
    # New event-style:
    "stoch_level", "cci_level", "mfi_level", "uo_level",
}
```

All other new archetypes are state-style (position-level, not action-intent).

**Signal implementations** (pseudocode for each):

```python
@register_signal("ema", "price_vs_ema")
def _ema_signal(close, params, volume, *, high=None, low=None):
    ema_arr = compute_ema_series(close, int(params["window"]))
    return np.where(close > ema_arr, 1.0, np.where(close < ema_arr, -1.0, 0.0))

@register_signal("ema_cross", "ema_cross")
def _ema_cross_signal(close, params, volume, *, high=None, low=None):
    fast = compute_ema_series(close, int(params["fast"]))
    slow = compute_ema_series(close, int(params["slow"]))
    return np.where(fast > slow, 1.0, np.where(fast < slow, -1.0, 0.0))

@register_signal("ichimoku", "ichi_cloud")
def _ichi_signal(close, params, volume, *, high=None, low=None):
    ichi = compute_ichimoku_series(high, low, close,
        int(params["tenkan"]), int(params["kijun"]), int(params["senkou_b"]))
    bullish = (close > ichi["cloud_top"]) & (ichi["tenkan_sen"] > ichi["kijun_sen"])
    bearish = (close < ichi["cloud_bottom"]) & (ichi["tenkan_sen"] < ichi["kijun_sen"])
    return np.where(bullish, 1.0, np.where(bearish, -1.0, 0.0))

@register_signal("psar", "psar_trend")
def _psar_signal(close, params, volume, *, high=None, low=None):
    sar = compute_psar_series(high, low, close,
        float(params["af_step"]), float(params["af_max"]))
    return np.where(close > sar, 1.0, np.where(close < sar, -1.0, 0.0))

@register_signal("roc", "roc_zero")
def _roc_signal(close, params, volume, *, high=None, low=None):
    roc = compute_roc_series(close, int(params["period"]))
    return np.where(roc > 0, 1.0, np.where(roc < 0, -1.0, 0.0))

@register_signal("trix", "trix_zero")
def _trix_signal(close, params, volume, *, high=None, low=None):
    trix = compute_trix_series(close, int(params["period"]))
    return np.where(trix > 0, 1.0, np.where(trix < 0, -1.0, 0.0))

@register_signal("adx", "adx_trend")
def _adx_signal(close, params, volume, *, high=None, low=None):
    plus_di, minus_di, adx = compute_adx_series(
        high, low, close, int(params["period"]))
    threshold = float(params["adx_threshold"])
    bullish = (plus_di > minus_di) & (adx > threshold)
    bearish = (minus_di > plus_di) & (adx > threshold)
    return np.where(bullish, 1.0, np.where(bearish, -1.0, 0.0))

@register_signal("tsi", "tsi_zero")
def _tsi_signal(close, params, volume, *, high=None, low=None):
    tsi = compute_tsi_series(close,
        int(params["long_period"]), int(params["short_period"]))
    return np.where(tsi > 0, 1.0, np.where(tsi < 0, -1.0, 0.0))

@register_signal("stochastic", "stoch_level")
def _stoch_signal(close, params, volume, *, high=None, low=None):
    k, d = compute_stochastic_series(high, low, close,
        int(params["k_period"]), int(params["d_period"]))
    buy = (k < 20) & (k > d)
    sell = (k > 80) & (k < d)
    return np.where(buy, 1.0, np.where(sell, -1.0, 0.0))

@register_signal("cci", "cci_level")
def _cci_signal(close, params, volume, *, high=None, low=None):
    cci = compute_cci_series(high, low, close, int(params["period"]))
    return np.where(cci < -100, 1.0, np.where(cci > 100, -1.0, 0.0))

@register_signal("mfi", "mfi_level")
def _mfi_signal(close, params, volume, *, high=None, low=None):
    mfi = compute_mfi_series(high, low, close, volume, int(params["period"]))
    oversold = float(params["oversold"])
    overbought = float(params["overbought"])
    return np.where(mfi < oversold, 1.0, np.where(mfi > overbought, -1.0, 0.0))

@register_signal("uo", "uo_level")
def _uo_signal(close, params, volume, *, high=None, low=None):
    uo = compute_uo_series(high, low, close,
        int(params["period_1"]), int(params["period_2"]), int(params["period_3"]))
    return np.where(uo < 30, 1.0, np.where(uo > 70, -1.0, 0.0))

@register_signal("cmf", "cmf_flow")
def _cmf_signal(close, params, volume, *, high=None, low=None):
    cmf = compute_cmf_series(high, low, close, volume, int(params["period"]))
    return np.where(cmf > 0.05, 1.0, np.where(cmf < -0.05, -1.0, 0.0))

@register_signal("ad", "ad_trend")
def _ad_signal(close, params, volume, *, high=None, low=None):
    ad_line = compute_ad_series(high, low, close, volume)
    ad_ema = ema(ad_line, int(params["ema_period"]))
    return np.where(ad_line > ad_ema, 1.0, np.where(ad_line < ad_ema, -1.0, 0.0))

@register_signal("vwap", "vwap_dev")
def _vwap_signal(close, params, volume, *, high=None, low=None):
    vwap = compute_vwap_series(close, volume, int(params["period"]))
    threshold = float(params["threshold_pct"]) / 100.0
    upper = vwap * (1 + threshold)
    lower = vwap * (1 - threshold)
    return np.where(close > upper, 1.0, np.where(close < lower, -1.0, 0.0))

@register_signal("fi", "fi_trend")
def _fi_signal(close, params, volume, *, high=None, low=None):
    fi = compute_force_index_series(close, volume, int(params["period"]))
    return np.where(fi > 0, 1.0, np.where(fi < 0, -1.0, 0.0))
```

#### 1.5 `core/quant_core/signal_engine/current_signal.py`

Add indicator value dispatch for all 16 new families in `_get_indicator_value()`:

| Family | Return value at last bar |
|--------|------------------------|
| `ema` | EMA value |
| `ema_cross` | slow EMA value |
| `ichimoku` | tenkan_sen value |
| `psar` | SAR value |
| `roc` | ROC value |
| `trix` | TRIX value |
| `adx` | ADX value |
| `tsi` | TSI value |
| `stochastic` | %K value |
| `cci` | CCI value |
| `mfi` | MFI value |
| `uo` | UO value |
| `cmf` | CMF value |
| `ad` | A/D Line value |
| `vwap` | VWAP value |
| `fi` | Force Index EMA value |

Add explanation builder for each in `_build_explanation()`:

```python
# Example for ADX:
# "ADX(14) = 32.5 (+DI=28.1, -DI=15.3) → ADX > 25, +DI > -DI → MOMENTUM HAUSSIER"
```

#### 1.6 `core/quant_core/signal_engine/variant_detail.py`

Add indicator plot dispatch in `_compute_indicator()` for all 16 new families:

| Family | Plot Type | What to Display |
|--------|-----------|-----------------|
| `ema` | `overlay` | EMA line on price chart |
| `ema_cross` | `overlay_dual` | Fast + slow EMA lines |
| `ichimoku` | `overlay_cloud` (new) | Tenkan, Kijun lines + cloud shading (senkou_a/senkou_b fill) |
| `psar` | `overlay_dots` (new) | SAR dots on price chart |
| `roc` | `secondary_yaxis` | ROC line, zero reference |
| `trix` | `secondary_yaxis` | TRIX line, zero reference |
| `adx` | `secondary_yaxis` | +DI, -DI, ADX lines + threshold horizontal |
| `tsi` | `secondary_yaxis` | TSI line, zero reference |
| `stochastic` | `secondary_yaxis` | %K, %D lines + 20/80 thresholds |
| `cci` | `secondary_yaxis` | CCI line + ±100 thresholds |
| `mfi` | `secondary_yaxis` | MFI line + oversold/overbought thresholds |
| `uo` | `secondary_yaxis` | UO line + 30/70 thresholds |
| `cmf` | `secondary_yaxis` | CMF line + ±0.05 thresholds |
| `ad` | `secondary_yaxis` | A/D Line + EMA line |
| `vwap` | `overlay_band` (new) | VWAP line + upper/lower threshold bands |
| `fi` | `secondary_yaxis` | Force Index EMA + zero reference |

New plot types needed: `overlay_cloud`, `overlay_dots`, `overlay_band`.

#### 1.7 `core/quant_core/signal_engine/ensemble.py`

Update `run_family_ensemble_full()` to accept and forward `high`, `low` arrays.

No changes to ensemble logic — it's family-agnostic by design.

#### 1.8 Volume validation

The existing `_validate_obv_volume_data()` check should be extended (or generalized) to all volume-dependent families: `obv`, `cmf`, `ad`, `vwap`, `fi`, `mfi`.

Rename or generalize to `_validate_volume_data(family, symbol, ohlcv, volume)`.

---

### Phase 2: API Layer

#### 2.1 `services/api/app/schemas/strategy_signals.py`

Update regex patterns:

```python
# FamilyEnsembleRequest.family:
pattern=r"^(sma|ema|ema_cross|ichimoku|psar|macd|roc|trix|adx|tsi|rsi|stochastic|cci|mfi|uo|obv|cmf|ad|vwap|fi)$"

# IndicatorSeriesRequest.indicator: same pattern

# SignalZoneChartRequest.enabled_families: update default list
enabled_families: list[str] = Field(default=["sma", "rsi", "macd", "obv"])
# Keep default at original 4 for backward compatibility
```

#### 2.2 `services/api/app/routers/strategy_signals.py`

**Indicator labels**: Add label functions for all 16 new families. Group by signal_type:
- All trend families share `_trend_label()` (rename `_sma_label`)
- All momentum families share `_momentum_label()` (new)
- All oscillator families share `_oscillator_label()` (rename `_rsi_label`)
- All volume families share `_volume_label()` (rename `_obv_label`)

**Param validation**: Add `_validate_indicator_params()` cases for all 16 new families:

```python
if indicator == "ema":
    if keys != {"window"}: raise ...
    return {"window": _int_param(params, "window", 2, 500)}
elif indicator == "ema_cross":
    if keys != {"fast", "slow"}: raise ...
    fast = _int_param(params, "fast", 2, 200)
    slow = _int_param(params, "slow", 3, 500)
    if fast >= slow: raise HTTPException(422, "fast must be < slow")
    return {"fast": fast, "slow": slow}
# ... etc for each family
```

**OHLCV forwarding**: Extract `high`, `low` from DataFrame and pass to `run_family_ensemble_full()`:

```python
high = ohlcv["High"].values.astype(np.float64)
low = ohlcv["Low"].values.astype(np.float64)
```

**Volume validation**: Generalize OBV-specific validation to all volume-dependent families.

---

### Phase 3: Frontend

#### 3.1 `frontend/components/strategy/technical-analysis-panel.tsx`

Update `CATEGORIES` array:

```typescript
const CATEGORIES = [
  {
    id: "tendance",
    label: "Tendance",
    description: "Direction du marché",
    families: [
      { id: "sma", label: "SMA" },
      { id: "ema", label: "EMA" },
      { id: "ema_cross", label: "EMA Cross" },
      { id: "ichimoku", label: "Ichimoku" },
      { id: "psar", label: "Parabolic SAR" },
    ],
  },
  {
    id: "momentum",
    label: "Momentum",
    description: "Vitesse du mouvement",
    families: [
      { id: "macd", label: "MACD" },
      { id: "roc", label: "ROC" },
      { id: "trix", label: "TRIX" },
      { id: "adx", label: "ADX" },
      { id: "tsi", label: "TSI" },
    ],
  },
  {
    id: "oscillation",
    label: "Oscillation",
    description: "Extrêmes statistiques",
    families: [
      { id: "rsi", label: "RSI" },
      { id: "stochastic", label: "Stochastic" },
      { id: "cci", label: "CCI" },
      { id: "mfi", label: "MFI" },
      { id: "uo", label: "Ultimate Osc." },
    ],
  },
  {
    id: "volume",
    label: "Volume",
    description: "Pression achat/vente",
    families: [
      { id: "obv", label: "OBV" },
      { id: "cmf", label: "CMF" },
      { id: "ad", label: "A/D Line" },
      { id: "vwap", label: "VWAP" },
      { id: "fi", label: "Force Index" },
    ],
  },
]
```

Add toggle logic: each family should have an enabled/disabled state that controls whether its ensemble is fetched and included in the aggregate score.

#### 3.2 `frontend/components/strategy/indicator-explorer.tsx`

Update `IndicatorFamilyKey` type and `FAMILY_ORDER`:

```typescript
type IndicatorFamilyKey =
  | "sma" | "ema" | "ema_cross" | "ichimoku" | "psar"
  | "macd" | "roc" | "trix" | "adx" | "tsi"
  | "rsi" | "stochastic" | "cci" | "mfi" | "uo"
  | "obv" | "cmf" | "ad" | "vwap" | "fi"

const FAMILY_ORDER: IndicatorFamilyKey[] = [
  "sma", "ema", "ema_cross", "ichimoku", "psar",
  "macd", "roc", "trix", "adx", "tsi",
  "rsi", "stochastic", "cci", "mfi", "uo",
  "obv", "cmf", "ad", "vwap", "fi",
]
```

Add default params for initial state:

```typescript
// New families initial state:
ema: { enabled: false, params: { window: 20 } },
ema_cross: { enabled: false, params: { fast: 12, slow: 26 } },
ichimoku: { enabled: false, params: { tenkan: 9, kijun: 26, senkou_b: 52 } },
psar: { enabled: false, params: { af_step: 0.02, af_max: 0.20 } },
roc: { enabled: false, params: { period: 12 } },
trix: { enabled: false, params: { period: 15 } },
adx: { enabled: false, params: { period: 14, adx_threshold: 25 } },
tsi: { enabled: false, params: { long_period: 25, short_period: 13 } },
stochastic: { enabled: false, params: { k_period: 14, d_period: 3 } },
cci: { enabled: false, params: { period: 20 } },
mfi: { enabled: false, params: { period: 14, oversold: 20, overbought: 80 } },
uo: { enabled: false, params: { period_1: 7, period_2: 14, period_3: 28 } },
cmf: { enabled: false, params: { period: 21 } },
ad: { enabled: false, params: { ema_period: 20 } },
vwap: { enabled: false, params: { period: 20, threshold_pct: 1.0 } },
fi: { enabled: false, params: { period: 13 } },
```

#### 3.3 `frontend/lib/api.ts`

No schema changes needed — `FamilyCombinedSignalSchema` is already family-agnostic. The `family` field is a `z.string()`, not an enum.

---

### Phase 4: Tests

#### 4.1 `core/tests/test_signal_engine/`

For each new family, write:

1. **Candidate generation test**: Verify `generate_candidates(family, horizon)` returns exactly 30 `VariantDef` objects for each horizon
2. **Signal contract test**: Verify output is correct length, values in {-1, 0, +1}, NaN-free
3. **Known-value test**: For a simple synthetic price series, verify the signal matches expected output
4. **Warmup test**: Verify first N bars are 0 (flat) where N = indicator warmup

**Example test structure**:
```python
def test_ema_candidates_count():
    for h in ("short", "medium", "long"):
        candidates = generate_candidates("ema", h)
        assert len(candidates) == 30

def test_ema_signal_contract():
    close = np.random.randn(500).cumsum() + 100
    variant = generate_candidates("ema", "medium")[0]
    sig = compute_signal_array(close, variant)
    assert len(sig) == len(close)
    assert set(np.unique(sig)).issubset({-1.0, 0.0, 1.0})
    assert not np.any(np.isnan(sig))
```

---

## Performance Considerations

1. **Vectorized computation**: All indicator formulas must use NumPy operations, not Python loops (except PSAR which is inherently sequential)
2. **Cache existing helpers**: Reuse `ema()`, `rsi_wilder()`, `obv_array()` from `core.quant_core.optimize`
3. **PSAR loop**: Use `@njit` (Numba) for the Parabolic SAR computation loop if performance matters
4. **Parallel families**: The API already runs families independently. Adding more families doesn't slow existing ones.
5. **30 candidates per family**: Each new family adds exactly 30 OOS evaluations. On modern hardware this is seconds, not minutes.

---

## Implementation Order

Implement in this order to enable incremental testing:

1. **`indicator_series.py`** — All computation functions (pure math, no dependencies)
2. **`domain.py`** — Update FAMILY_SIGNAL_TYPE, CATEGORY_FAMILIES, label functions
3. **`candidates.py`** — All 16 new `@register_family` generators
4. **`oos_eval.py`** — All 16 new `@register_signal` dispatchers + high/low signature change
5. **`current_signal.py`** — Indicator value dispatch + explanation builders
6. **`variant_detail.py`** — Plot dispatch for all new families
7. **`ensemble.py`** — Forward high/low through pipeline
8. **API schemas** — Regex patterns
9. **API router** — Param validation + label functions + high/low forwarding
10. **Frontend panel** — CATEGORIES update
11. **Frontend explorer** — Family state + default params
12. **Tests** — Per-family contract tests

---

## Verification Checklist

- [ ] `python -m pytest core/tests/ -q` — all existing tests pass
- [ ] Each of 20 families generates exactly 30 candidates per horizon
- [ ] Each signal function returns {-1, 0, +1} array of correct length
- [ ] Frontend shows 5 families per category with correct labels
- [ ] Variant detail page renders correct plot type for each family (overlay, secondary axis, cloud, dots)
- [ ] A/D Line, Ichimoku cloud, PSAR dots render correctly in variant detail
- [ ] Toggle UI allows enabling/disabling individual families
- [ ] Aggregate score correctly averages enabled families only
- [ ] Volume validation works for all volume-dependent families (cmf, ad, vwap, fi, mfi)
