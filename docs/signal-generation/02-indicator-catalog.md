# Signal Generation — Indicator Catalog

**Files:** `core/quant_core/indicators.py`, `core/quant_core/optimize.py` (fast numpy implementations)

Every indicator is a **pure mathematical transformation** of OHLCV data into a derived series. Indicators carry no directional intent — they are features. The strategy adapter layer applies decision rules to produce signals.

---

## 1. Simple Moving Average (SMA)

### Mathematical definition

```
SMA(t, w) = (1/w) * Σ_{i=0}^{w-1} Close(t-i)
```

### Properties
- **Inputs:** Close
- **Parameters:** `window: int` (number of bars)
- **Output:** Single series, same length as input (first `w-1` values are NaN)
- **Warmup:** `window` bars
- **Statistical property:** Low-pass filter — removes fluctuations shorter than `w` bars
- **Lag:** `(w-1)/2` bars (symmetric lag of a moving average filter)

### Implementation (fast path)
```python
# optimize.py — sma_cumsum()
def sma_cumsum(close: np.ndarray, window: int) -> np.ndarray:
    """O(n) SMA via cumulative sum trick. No DataFrame overhead."""
    cs = np.empty(len(close) + 1, dtype=np.float64)
    cs[0] = 0.0
    cs[1:] = np.cumsum(close)
    out = np.full(len(close), np.nan, dtype=np.float64)
    out[window - 1:] = (cs[window:] - cs[:len(close) - window + 1]) / window
    return out
```

### Economic rationale
SMA smooths noise to reveal underlying trend direction. `Close > SMA(w)` indicates the current price is above the w-bar average, suggesting upward drift. This is the simplest trend-following feature.

**References:**
- Faber, M. (2007). "A Quantitative Approach to Tactical Asset Allocation." *Journal of Wealth Management*.
- Moskowitz, T., Ooi, Y.H., Pedersen, L.H. (2012). "Time Series Momentum." *Journal of Financial Economics*, 104(2), 228–250.

---

## 2. Exponential Moving Average (EMA)

### Mathematical definition

```
EMA(t, span) = α * Close(t) + (1 - α) * EMA(t-1, span)
where α = 2 / (span + 1)
```

### Properties
- **Inputs:** Close
- **Parameters:** `span: int`
- **Output:** Single series
- **Warmup:** ~2×span bars for convergence
- **Statistical property:** Infinite impulse response (IIR) filter — recent bars weighted exponentially more
- **Advantage over SMA:** Less lag for same smoothing, more responsive to recent price changes

### Implementation
```python
# optimize.py — ema()
def ema(close: np.ndarray, span: int) -> np.ndarray:
    alpha = 2.0 / (span + 1.0)
    out = np.empty_like(close)
    out[0] = close[0]
    for i in range(1, len(close)):
        out[i] = alpha * close[i] + (1 - alpha) * out[i - 1]
    return out
```

---

## 3. Relative Strength Index (RSI)

### Mathematical definition (Wilder's smoothing)

```
Δ(t) = Close(t) - Close(t-1)
U(t) = max(Δ(t), 0)      # upward change
D(t) = max(-Δ(t), 0)     # downward change

avg_U(t) = ((period - 1) * avg_U(t-1) + U(t)) / period   # Wilder's smoothing
avg_D(t) = ((period - 1) * avg_D(t-1) + D(t)) / period

RS(t) = avg_U(t) / avg_D(t)
RSI(t) = 100 - 100 / (1 + RS(t))
```

### Properties
- **Inputs:** Close
- **Parameters:** `period: int` (typically 14)
- **Output:** Series bounded in [0, 100]
- **Warmup:** `period + 1` bars
- **Interpretation:** RSI < 30 = oversold (potential reversal up), RSI > 70 = overbought (potential reversal down)
- **Statistical property:** Momentum oscillator — measures the ratio of average gains to average losses over a lookback

### Implementation
```python
# optimize.py — rsi_wilder()
def rsi_wilder(close: np.ndarray, period: int) -> np.ndarray:
    delta = np.diff(close, prepend=np.nan)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    # Wilder's smoothing (recursive EMA with alpha = 1/period)
    avg_gain = np.empty_like(close)
    avg_loss = np.empty_like(close)
    avg_gain[:period + 1] = np.nan
    avg_loss[:period + 1] = np.nan
    avg_gain[period] = np.mean(gain[1:period + 1])
    avg_loss[period] = np.mean(loss[1:period + 1])
    for i in range(period + 1, len(close)):
        avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gain[i]) / period
        avg_loss[i] = (avg_loss[i - 1] * (period - 1) + loss[i]) / period
    rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)
    return 100.0 - 100.0 / (1.0 + rs)
```

### Economic rationale
RSI captures the speed and magnitude of recent price changes. Extreme readings (oversold/overbought) often precede reversals in range-bound markets. In trending markets, RSI can confirm momentum (sustained high readings in uptrend).

**References:**
- Wilder, J.W. (1978). *New Concepts in Technical Trading Systems*.
- Chong, T.T.L. & Ng, W.K. (2008). "Technical Analysis and the London Stock Exchange." *Applied Financial Economics*, 18, 1121–1132.

---

## 4. MACD (Moving Average Convergence Divergence)

### Mathematical definition

```
MACD_line(t) = EMA(Close, fast) - EMA(Close, slow)
Signal_line(t) = EMA(MACD_line, signal)
Histogram(t) = MACD_line(t) - Signal_line(t)
```

### Properties
- **Inputs:** Close
- **Parameters:** `fast: int` (default 12), `slow: int` (default 26), `signal: int` (default 9)
- **Output:** 3 series (MACD line, signal line, histogram)
- **Warmup:** `slow + signal` bars (conservative: 35)
- **Statistical property:** Bandpass filter — captures momentum in the frequency band between fast and slow EMA periods

### Implementation
```python
# optimize.py — macd_pack()
def macd_pack(close: np.ndarray, fast: int, slow: int, sig: int) -> tuple:
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, sig)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram
```

### Economic rationale
MACD measures the convergence/divergence of two exponential trends. When the fast EMA pulls away from the slow EMA, momentum is accelerating. The signal line crossing provides timing.

**References:**
- Appel, G. (2005). *Technical Analysis: Power Tools for Active Investors*. FT Press.

---

## 5. Bollinger Bands

### Mathematical definition

```
Middle(t) = SMA(Close, window)
Upper(t) = Middle(t) + k * StdDev(Close, window)
Lower(t) = Middle(t) - k * StdDev(Close, window)

%B(t) = (Close(t) - Lower(t)) / (Upper(t) - Lower(t))
Bandwidth(t) = (Upper(t) - Lower(t)) / Middle(t)
```

### Properties
- **Inputs:** Close
- **Parameters:** `window: int` (default 20), `k: float` (default 2.0, std dev multiplier)
- **Output:** Upper band, lower band, middle band (+ derived %B, bandwidth)
- **Warmup:** `window` bars
- **Statistical property:** Adaptive envelope — bands widen in high-volatility periods, narrow in low-volatility periods. ~95% of prices fall within 2σ bands under normality.

### Economic rationale
Mean reversion signal: prices touching the lower band are statistically extreme and may revert upward. Bandwidth contraction ("squeeze") often precedes volatility expansion.

**References:**
- Bollinger, J. (2001). *Bollinger on Bollinger Bands*. McGraw-Hill.

---

## 6. On-Balance Volume (OBV)

### Mathematical definition

```
OBV(t) = OBV(t-1) + sign(Close(t) - Close(t-1)) * Volume(t)

where sign(x) = +1 if x > 0, -1 if x < 0, 0 if x = 0
```

### Properties
- **Inputs:** Close, Volume
- **Parameters:** none (the cumulative series), or `obv_span: int` for EMA smoothing
- **Output:** Cumulative volume series
- **Warmup:** 1 bar + `obv_span` if using EMA
- **Statistical property:** Accumulation/distribution indicator — rising OBV with rising price confirms trend; divergence (price up, OBV down) suggests weakness

### Implementation
```python
# optimize.py — obv_array()
def obv_array(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    signs = np.sign(np.diff(close, prepend=close[0]))
    return np.cumsum(signs * volume)
```

### Economic rationale
Volume precedes price — informed traders accumulate shares before price moves. OBV divergence from price trend can signal impending reversals.

**References:**
- Granville, J. (1963). *Granville's New Key to Stock Market Profits*.
- Llorente, G. et al. (2002). "Dynamic Volume-Return Relation of Individual Stocks." *Review of Financial Studies*.

---

## 7. Stochastic Oscillator (%K, %D)

### Mathematical definition

```
%K(t) = 100 * (Close(t) - Low_min(t, k_window)) / (High_max(t, k_window) - Low_min(t, k_window))
%K_smooth(t) = SMA(%K, smooth_k)    # optional smoothing
%D(t) = SMA(%K_smooth, d_window)     # signal line
```

### Properties
- **Inputs:** Close, High, Low
- **Parameters:** `k_window: int` (default 14), `d_window: int` (default 3), `smooth_k: int` (default 1)
- **Output:** %K and %D, both bounded in [0, 100]
- **Warmup:** `k_window + smooth_k + d_window` bars
- **Interpretation:** %K < 20 = oversold, %K > 80 = overbought; %K crossing %D provides timing

### Implementation
```python
# optimize.py — stoch_kd_arrays()
def stoch_kd_arrays(close, high, low, k_window, d_window, smooth_k):
    lowest = rolling_min(low, k_window)
    highest = rolling_max(high, k_window)
    raw_k = 100.0 * (close - lowest) / np.where(highest - lowest == 0, 1e-10, highest - lowest)
    k = sma_cumsum(raw_k, smooth_k) if smooth_k > 1 else raw_k
    d = sma_cumsum(k, d_window)
    return k, d
```

---

## 8. VWAP (Volume-Weighted Average Price)

### Mathematical definition

```
VWAP(t, w) = Σ_{i=t-w+1}^{t} (Close(i) * Volume(i)) / Σ_{i=t-w+1}^{t} Volume(i)
```

### Properties
- **Inputs:** Close, Volume
- **Parameters:** `window: int`
- **Output:** Single series
- **Warmup:** `window` bars
- **Economic meaning:** Average price weighted by volume — represents the "fair" price where most volume transacted. Institutional traders use VWAP as execution benchmark.

### Implementation
```python
# optimize.py — rolling_vwap_array()
def rolling_vwap_array(close, volume, window):
    pv = close * volume
    cum_pv = np.cumsum(pv)
    cum_v = np.cumsum(volume)
    # Rolling window via cumsum trick
    out = np.full_like(close, np.nan)
    out[window - 1:] = (cum_pv[window - 1:] - np.r_[0, cum_pv[:-window]]) / \
                        np.where(cum_v[window - 1:] - np.r_[0, cum_v[:-window]] == 0, 1e-10,
                                 cum_v[window - 1:] - np.r_[0, cum_v[:-window]])
    return out
```

---

## 9. Ichimoku Cloud

### Mathematical definition

```
Tenkan-sen (Conversion)  = (Highest_High(tenkan) + Lowest_Low(tenkan)) / 2
Kijun-sen (Base)         = (Highest_High(kijun) + Lowest_Low(kijun)) / 2
Senkou Span A (Lead A)   = (Tenkan + Kijun) / 2, shifted forward by 'shift' bars
Senkou Span B (Lead B)   = (Highest_High(senkou_b) + Lowest_Low(senkou_b)) / 2, shifted forward
Chikou Span (Lagging)    = Close, shifted backward by 'shift' bars
```

### Properties
- **Inputs:** Close, High, Low
- **Parameters:** `tenkan: int` (9), `kijun: int` (26), `senkou_b: int` (52), `shift: int` (26)
- **Output:** 4 series (Tenkan, Kijun, Span A, Span B)
- **Warmup:** `senkou_b + shift` bars (78 with defaults)
- **The "cloud":** Area between Span A and Span B — acts as dynamic support/resistance

### Economic rationale
Ichimoku is a complete trend-identification system from Japanese technical analysis. Price above the cloud = bullish; below = bearish. Tenkan > Kijun confirms momentum direction. The cloud's thickness indicates trend strength.

**References:**
- Hosoda, G. (1969). Original Ichimoku work (Japanese).
- Elliott, N. (2007). *Ichimoku Charts*. Harriman House.

---

## 10. Rolling Standard Deviation

### Mathematical definition

```
σ(t, w) = sqrt((1/(w-1)) * Σ_{i=0}^{w-1} (Close(t-i) - SMA(t,w))²)
```

### Properties
- **Inputs:** Close
- **Parameters:** `window: int`
- **Output:** Realized volatility series
- **Used by:** Bollinger Bands (bands = SMA ± k*σ)
- **Statistical property:** Estimate of local return standard deviation

---

## Indicator Dependency Graph

```
Close ──┬── SMA(window) ──── Bollinger Upper/Lower
        │
        ├── EMA(span) ──┬── MACD line (EMA_fast - EMA_slow)
        │               └── Signal line (EMA of MACD)
        │
        ├── RSI(period) ── [0..100] oscillator
        │
        ├── Rolling Std(window) ── Bollinger Bands
        │
        └── OBV(Close, Volume) ── OBV EMA(span)

Close + Volume ── VWAP(window)

Close + High + Low ──┬── Stochastic %K/%D
                     └── Ichimoku (Tenkan, Kijun, Span A, Span B)
```
