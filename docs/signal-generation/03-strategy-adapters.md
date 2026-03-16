# Signal Generation — Strategy Adapters

**Files:** `core/quant_core/strategy.py` (runtime strategies), `core/quant_core/optimize.py` (optimization adapters)

Strategy adapters bridge the indicator catalog and the signal frame contract. Each adapter applies a **decision rule** to one or more indicators, producing a directional intent signal.

---

## Adapter Registry

```python
# optimize.py
STRATEGY_ADAPTERS = {
    "ma_cross":    MACrossAdapter(),
    "sma_price":   PriceAboveSMAAdapter(),
    "rsi":         RSIStrategyAdapter(),
    "macd":        MACDStrategyAdapter(),
    "bollinger":   BollingerAdapter(),
    "obv":         OBVAdapter(),
    "stoch_vwap":  StochVWAPAdapter(),
    "ichimoku":    IchimokuAdapter(),
}
```

Each adapter implements:
- `required_bank(base_spec, active_params) → BankRequest` — declare which indicators to precompute
- `make_signal_arrays_fast(symbols, bank, bars, params, spec) → Dict[str, np.ndarray]` — fast numpy signal generation
- `validate_params(params) → bool` — parameter constraint checking

---

## 1. MA Cross (`ma_cross`)

**Economic thesis:** Trend-following via dual moving average crossover. When the fast MA rises above the slow MA, the short-term trend has turned up relative to the longer-term trend, suggesting sustained upward momentum.

**Decision rule:**
```
signal(t) = +1  if  SMA(Close, fast_window)(t) > SMA(Close, slow_window)(t)
          = -1  if  SMA(Close, fast_window)(t) < SMA(Close, slow_window)(t)  [and allow_short]
          =  0  otherwise
```

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `sma_fast_window` | int | 5–60 | 15 | 1 |
| `sma_slow_window` | int | 20–250 | 50 | 1 |
| `allow_short` | bool | — | false | — |

**Constraint:** `fast_window < slow_window` (validated by adapter)

**Warmup:** `max(fast_window, slow_window)` bars

**Bank request:** SMA for all fast windows + all slow windows across the parameter grid

---

## 2. Price vs SMA (`sma_price`)

**Economic thesis:** Simplest trend filter — if price is above its moving average, the trend is up. Less prone to whipsaws than dual-MA crossover since it uses only one indicator.

**Decision rule (level mode):**
```
signal(t) = +1  if  Close(t) > SMA(Close, window)(t)
          = -1  if  Close(t) < SMA(Close, window)(t)  [and allow_short]
          =  0  otherwise
```

**Decision rule (cross mode):**
```
signal(t) = +1  if  Close(t) crosses above SMA(t)  (Close(t-1) ≤ SMA(t-1) and Close(t) > SMA(t))
          = -1  if  Close(t) crosses below SMA(t)
          =  0  otherwise (hold previous)
```

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `sma_window` | int | 10–250 | 50 | 1 |
| `signal_mode` | choice | level, cross | level | — |
| `allow_short` | bool | — | false | — |

**Warmup:** `window` bars

---

## 3. RSI (`rsi`)

**Economic thesis:** Mean reversion at extremes — RSI readings below 30 indicate oversold conditions where selling pressure may be exhausted; above 70 indicates overbought where buying pressure may be exhausted. In momentum mode, extreme RSI confirms trend strength.

**Decision rule (reversal mode):**
```
signal(t) = +1  if  RSI(t) < low_threshold     (oversold → buy the dip)
          = -1  if  RSI(t) > high_threshold    (overbought → sell the rip)
          =  0  otherwise
```

**Decision rule (momentum mode):**
```
signal(t) = +1  if  RSI(t) > high_threshold    (strong momentum → chase)
          = -1  if  RSI(t) < low_threshold     (weak momentum → exit)
          =  0  otherwise
```

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `rsi_window` | int | 5–100 | 14 | 1 |
| `rsi_oversold` | float | 10–40 | 30 | 10 |
| `rsi_overbought` | float | 60–90 | 70 | 10 |
| `mode` | choice | reversal, momentum | reversal | — |
| `allow_short` | bool | — | false | — |

**Warmup:** `rsi_window + 1` bars

---

## 4. MACD (`macd`)

**Economic thesis:** Momentum detection via the difference between two exponential trends. When the fast EMA pulls away from the slow EMA (positive MACD line), short-term momentum exceeds long-term, suggesting continuation.

**Decision rule (zero trigger):**
```
signal(t) = +1  if  MACD_line(t) > 0    (fast EMA above slow EMA)
          = -1  if  MACD_line(t) < 0    [and allow_short]
          =  0  otherwise
```

**Decision rule (cross trigger):**
```
signal(t) = +1  if  MACD_line(t) crosses above Signal_line(t)
          = -1  if  MACD_line(t) crosses below Signal_line(t)
          =  0  otherwise (hold previous)
```

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `fast` | int | 5–50 | 12 | 1 |
| `slow` | int | 20–200 | 26 | 1 |
| `signal` | int | 5–50 | 9 | 1 |
| `trigger` | choice | zero, cross | zero | — |
| `allow_short` | bool | — | false | — |

**Constraint:** `fast < slow`

**Warmup:** `slow + signal` bars

---

## 5. Bollinger Bands (`bollinger`)

**Economic thesis:** Mean reversion — when price touches the lower band (2σ below the mean), it has moved to a statistically extreme level and is likely to revert toward the mean. Uses volatility-adaptive thresholds rather than fixed levels.

**Decision rule:**
```
upper(t) = SMA(t, window) + k * StdDev(t, window)
lower(t) = SMA(t, window) - k * StdDev(t, window)

signal(t) = +1  if  Close(t) < lower(t)    (oversold → buy)
          = -1  if  Close(t) > upper(t)    (overbought → exit/sell)
          =  0  otherwise
```

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `bb_window` | int | 10–100 | 20 | 1 |
| `bb_k` | float | 2.0–5.0 | 2.0 | 0.5 |
| `allow_short` | bool | — | false | — |

**Warmup:** `bb_window` bars

---

## 6. OBV (`obv`)

**Economic thesis:** Volume leads price — informed market participants accumulate shares before price moves up. OBV above its EMA indicates net accumulation; below indicates distribution.

**Decision rule:**
```
signal(t) = +1  if  OBV(t) > EMA(OBV, span)(t)    (accumulation)
          = -1  if  OBV(t) < EMA(OBV, span)(t)    (distribution)
          =  0  otherwise
```

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `obv_span` | int | 5–200 | 20 | 1 |
| `allow_short` | bool | — | false | — |

**Inputs:** Close + Volume

**Warmup:** `obv_span` bars

---

## 7. Stochastic + VWAP (`stoch_vwap`)

**Economic thesis:** Multi-confirmation signal combining price position (Stochastic oscillator), momentum (%K/%D crossover), and institutional flow (VWAP). Requires agreement across multiple dimensions to generate a signal, reducing false positives.

**Decision rule (BUY conditions — any one sufficient):**
1. `%K crosses above %D` AND `%K < 20` AND `%D < 20` AND `Close > VWAP` (oversold reversal + institutional buying)
2. `%K ∈ [50,80]` AND `%D ∈ [50,80]` AND `Close > VWAP` (mid-momentum continuation)
3. `%K crosses above %D` AND `%K < 80` AND `%D < 80` AND `Close > VWAP` (general momentum + VWAP confirmation)

**Decision rule (SELL conditions — override BUY):**
1. `%K crosses below %D` AND `%K > 80` AND `%D > 80` AND `Close < VWAP` (overbought reversal + institutional selling)
2. `%K ∈ [20,50]` AND `%D ∈ [20,50]` AND `Close < VWAP` (weakening momentum)
3. `%K crosses below %D` AND `%K > 20` AND `%D > 20` AND `Close < VWAP` (general weakness)

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `k_window` | int | 5–60 | 14 | 1 |
| `d_window` | int | 2–20 | 3 | 1 |
| `smooth_k` | int | 1–10 | 1 | 1 |
| `vwap_window` | int | 5–100 | 20 | 1 |
| `allow_short` | bool | — | false | — |

**Inputs:** Close + High + Low + Volume

**Warmup:** `k_window + smooth_k + d_window + vwap_window` bars

---

## 8. Ichimoku Cloud (`ichimoku`)

**Economic thesis:** Complete trend identification system. Price above the cloud with Tenkan > Kijun = bullish trend confirmed. The cloud acts as dynamic support/resistance; its thickness reflects trend strength.

**Decision rule:**
```
cloud_top(t) = max(Span_A(t), Span_B(t))
cloud_bot(t) = min(Span_A(t), Span_B(t))

signal(t) = +1  if  Close(t) > cloud_top(t)  AND  Tenkan(t) > Kijun(t)   (breakout + momentum)
          = -1  if  Close(t) < cloud_bot(t)  AND  Tenkan(t) < Kijun(t)   (breakdown + weakness)
          =  0  otherwise  (inside cloud or mixed signals)
```

**Parameters:**
| Name | Type | Range | Default | Step |
|------|------|-------|---------|------|
| `tenkan` | int | — | 9 | (fixed) |
| `kijun` | int | — | 26 | (fixed) |
| `senkou_b` | int | — | 52 | (fixed) |
| `shift` | int | — | 26 | (fixed) |
| `allow_short` | bool | — | false | — |

Note: Ichimoku parameters are typically kept at defaults (the original Hosoda parameters were designed for 6-day Japanese trading weeks; modern 5-day adaptation uses 9/26/52).

**Warmup:** `senkou_b + shift` bars (78)

---

## Signal Quality Comparison

| Adapter | Params | Overfitting risk | Signal frequency | Lag |
|---------|--------|-----------------|-----------------|-----|
| sma_price | 1 | Very low | Medium | Medium |
| ma_cross | 2 | Low | Low | High |
| rsi | 3 | Medium | Medium | Low |
| macd | 3 | Medium | Low-Medium | Medium |
| bollinger | 2 | Low | Low | Medium |
| obv | 1 | Very low | Medium | Low |
| stoch_vwap | 4 | High | Low | Medium |
| ichimoku | 4 (fixed) | Low | Low | High |

*Lower overfitting risk and fewer parameters are preferred for out-of-sample robustness.*
