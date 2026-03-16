# Signal Generation — Indicator Bank & Pre-Computation

**File:** `core/quant_core/optimize.py`

The indicator bank is the performance-critical layer that pre-computes all indicators needed across an optimization run **exactly once**, then serves them to individual trial evaluations via array lookup.

---

## Why a Bank?

In an optimization with 1,000 trials over SMA windows [5, 10, 15, ..., 250]:

**Without bank (naive):**
```
Trial 1: compute SMA(5), SMA(50), run portfolio  → 2 SMA computations
Trial 2: compute SMA(10), SMA(50), run portfolio → 2 SMA computations (SMA(50) duplicated!)
...
Trial 1000: compute SMA(60), SMA(250)            → 2 SMA computations
Total: 2,000 SMA computations (massive redundancy)
```

**With bank:**
```
Build bank: compute SMA(5), SMA(10), SMA(15), ..., SMA(250) once → 50 SMA computations
Trial 1: lookup bank["SMA_5"], bank["SMA_50"]    → 0 computations
Trial 2: lookup bank["SMA_10"], bank["SMA_50"]   → 0 computations
...
Total: 50 SMA computations (40× faster)
```

---

## BankRequest Dataclass

```python
@dataclass(frozen=True)
class BankRequest:
    sma: set[int] = field(default_factory=set)
    # All SMA windows needed across the entire optimization
    # Example: {5, 10, 15, 20, 25, 30, ..., 250}

    rsi: set[int] = field(default_factory=set)
    # All RSI periods needed
    # Example: {5, 7, 10, 14, 21, 30, 50}

    ema: set[int] = field(default_factory=set)
    # All EMA spans needed (for MACD, OBV EMA, etc.)

    macd: set[tuple[int, int, int]] = field(default_factory=set)
    # All (fast, slow, signal) triplets
    # Example: {(12, 26, 9), (5, 35, 5), (8, 21, 9)}

    std: set[int] = field(default_factory=set)
    # Rolling standard deviation windows (for Bollinger)

    obv_ema: set[int] = field(default_factory=set)
    # EMA spans applied to OBV series

    vwap: set[int] = field(default_factory=set)
    # Rolling VWAP windows

    stoch: set[tuple[int, int, int]] = field(default_factory=set)
    # (k_window, d_window, smooth_k) triplets

    ichimoku: set[tuple[int, int, int, int]] = field(default_factory=set)
    # (tenkan, kijun, senkou_b, shift) tuples
```

---

## Bank Construction

### `build_bank()` function

```python
def build_bank(
    close_by_sym: Dict[str, np.ndarray],
    high_by_sym: Dict[str, np.ndarray],
    low_by_sym: Dict[str, np.ndarray],
    vol_by_sym: Dict[str, np.ndarray],
    req: BankRequest,
) -> Dict[str, Dict[str, np.ndarray]]:
    """
    Returns: {symbol: {indicator_key: numpy_array}}

    Example:
    bank["ATW"]["sma_20"]       → np.ndarray of length N
    bank["ATW"]["rsi_14"]       → np.ndarray of length N
    bank["ATW"]["macd_12_26_9"] → np.ndarray of length N (MACD line)
    bank["ATW"]["macd_sig_12_26_9"] → np.ndarray (signal line)
    bank["ATW"]["stoch_k_14_3_1"] → np.ndarray (%K)
    bank["ATW"]["stoch_d_14_3_1"] → np.ndarray (%D)
    """
```

### Computation order

For each symbol:

1. **SMA** — `sma_cumsum(close, window)` for each window in `req.sma`
   - Key format: `sma_{window}` → e.g., `sma_20`, `sma_50`

2. **EMA** — `ema(close, span)` for each span in `req.ema`
   - Key format: `ema_{span}`
   - Cached in `ema_close_cache` to avoid recomputation (MACD reuses EMA values)

3. **RSI** — `rsi_wilder(close, period)` for each period in `req.rsi`
   - Key format: `rsi_{period}`

4. **MACD** — `macd_pack(close, fast, slow, sig)` for each triplet in `req.macd`
   - Key format: `macd_{fast}_{slow}_{sig}` (MACD line), `macd_sig_{f}_{s}_{sig}` (signal line)

5. **Rolling Std** — for each window in `req.std`
   - Key format: `std_{window}`

6. **OBV + EMA** — `obv_array(close, volume)` then `ema(obv, span)` for each span in `req.obv_ema`
   - Key format: `obv` (raw), `obv_ema_{span}` (smoothed)

7. **VWAP** — `rolling_vwap_array(close, volume, window)` for each window in `req.vwap`
   - Key format: `vwap_{window}`

8. **Stochastic** — `stoch_kd_arrays(close, high, low, k, d, smooth)` for each triplet
   - Key format: `stoch_k_{k}_{d}_{smooth}`, `stoch_d_{k}_{d}_{smooth}`

9. **Ichimoku** — `ichimoku_arrays(close, high, low, tenkan, kijun, senkou_b, shift)` for each tuple
   - Key format: `ichi_tenkan_{t}_{k}_{s}_{sh}`, `ichi_kijun_...`, `ichi_spana_...`, `ichi_spanb_...`

---

## How Adapters Request Bank Contents

Each adapter's `required_bank()` method inspects the optimization parameter grid and declares all unique indicator values:

```python
class MACrossAdapter(StrategyAdapter):
    def required_bank(self, base_spec, active_params):
        req = BankRequest()
        for param in active_params:
            if param.key == "strategy.sma_fast_window":
                lo, hi, step = param.domain
                req.sma.update(range(lo, hi + 1, step))
            elif param.key == "strategy.sma_slow_window":
                lo, hi, step = param.domain
                req.sma.update(range(lo, hi + 1, step))
        return req
```

This ensures the bank contains every SMA window that any trial might need.

---

## How Trials Consume the Bank

During the trial loop, each candidate parameter set looks up pre-computed arrays:

```python
class MACrossAdapter(StrategyAdapter):
    def make_signal_arrays_fast(self, symbols, bank, bars_close, ..., params, ...):
        fast_w = params["strategy.sma_fast_window"]
        slow_w = params["strategy.sma_slow_window"]
        result = {}
        for sym in symbols:
            fast_sma = bank[sym][f"sma_{fast_w}"]  # O(1) lookup
            slow_sma = bank[sym][f"sma_{slow_w}"]  # O(1) lookup
            signal = np.where(fast_sma > slow_sma, 1.0, 0.0)
            result[sym] = signal
        return result
```

No indicator computation happens during the trial loop — only array comparisons and lookups.

---

## Performance Impact

Benchmark results (from `docs/optimization_diagnosis.md`):

| Phase | Time (no bank) | Time (with bank) | Speedup |
|-------|---------------|-----------------|---------|
| 100 trials, SMA cross | ~1800ms | ~48ms | **38×** |
| Bank build (one-time) | — | ~5ms | — |
| Per-trial (avg) | ~18ms | ~0.2ms | **90×** |

The bank transforms optimization from O(trials × indicators) to O(indicators + trials).

---

## Caching Strategy

### EMA Cache
```python
ema_close_cache = {}  # {(symbol, span): np.ndarray}
# MACD(12, 26, 9) needs EMA(12) and EMA(26)
# If EMA(12) was already computed for another MACD variant, reuse it
```

### Bank-Level Dedup
The `BankRequest` uses `set` types — adding SMA window 50 twice is automatically deduplicated.

### Eval Cache (trial-level)
```python
eval_cache = {}  # {frozenset(params.items()): TrialResult}
# If two parameter combinations hash identically, skip re-evaluation
```
