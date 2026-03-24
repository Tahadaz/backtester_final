# 03 — Layer B: Out-of-Sample Evaluation

**File**: `core/quant_core/signal_engine/oos_eval.py`

---

## Purpose

Layer B evaluates each candidate variant using walk-forward out-of-sample (OOS) windows. This is the engine's primary defense against overfitting: the signal is generated using data the evaluation window has never seen.

> *"An in-sample backtest is not a backtest — it is a fitting exercise."* — Pardo (2008)

---

## Signal Dispatch Registry

Signal computation functions are registered via a decorator:

```python
@register_signal(family="sma", archetype="price_vs_sma")
def _sma_signal(close: np.ndarray, params: dict, volume: np.ndarray) -> np.ndarray:
    ...
```

Public entry point:
```python
compute_signal_array(close, variant, *, volume=None) → np.ndarray
```

### Signal Contract (Enforced)

Every signal function must satisfy:

1. **Length**: `len(output) == len(close)` — one signal per bar
2. **Values**: Each element ∈ {-1.0, 0.0, +1.0} — no fractional positions
3. **Warmup**: First `warmup` bars padded with 0.0 (flat = no position)
4. **NaN handling**: Any NaN in output → 0.0

These invariants are enforced after every signal computation. Violations raise `ValueError`.

### Signal Implementations

**SMA (`price_vs_sma`)**:
```
sma = rolling_mean(close, window)
signal[i] = +1 if close[i] > sma[i], -1 if close[i] < sma[i], else 0
warmup = window - 1 bars
```

**RSI (`rsi_level`)**:
```
rsi = wilder_rsi(close, period)
signal[i] = +1 if rsi[i] < oversold    # buy on weakness
signal[i] = -1 if rsi[i] > overbought  # sell on strength
signal[i] = 0 otherwise
warmup = period bars
```

Note: RSI signals are **actions** (+1 = buy action), not positions. They are converted to positions via forward-fill before return computation.

**MACD (`macd_cross`)**:
```
macd_line = ema(close, fast) - ema(close, slow)
signal_line = ema(macd_line, signal)
signal[i] = +1 if macd_line[i] > signal_line[i], -1 otherwise
warmup = slow + signal - 1 bars
```

**OBV (`obv_trend`)**:
```
obv[i] = obv[i-1] + (volume[i] if close[i] > close[i-1] else -volume[i])
obv_ema = ema(obv, ema_period)
signal[i] = +1 if obv[i] > obv_ema[i], -1 otherwise
warmup = ema_period bars
```

---

## Walk-Forward OOS Evaluation

```python
def evaluate_variant_oos(
    close: np.ndarray,
    variant: VariantDef,
    horizon: str,
    cost_bps: float = 10.0,
    *,
    cooldown_bars: int = 0,
    volume: np.ndarray | None = None,
) -> list[OOSWindowResult]
```

### Horizon Parameters

From `domain.py`:

| Horizon | Train | Test | Step | Max Years |
|---------|-------|------|------|-----------|
| Short | 252 | 63 | 63 | 5 |
| Medium | 504 | 126 | 126 | 10 |
| Long | 756 | 252 | 252 | 20 |

- **Train**: Number of bars for in-sample (used for indicator warmup, not for parameter fitting — the signal engine doesn't optimize parameters, it evaluates fixed variants)
- **Test**: Number of bars for OOS evaluation
- **Step**: How far to advance between windows (= test length, so no overlap)
- **Max years**: Maximum history to use (252 bars/year)

### Window Rolling Algorithm

```
n = len(close)
if n < train + test + 1: return []   # insufficient data

for start in range(0, n - train - test, step):
    train_window = close[start : start + train]     # warmup only
    test_window  = close[start + train : start + train + test]

    # Signal is computed on FULL array (causal), then sliced
    signal_full = compute_signal_array(close, variant)
    signal_oos  = signal_full[start + train : start + train + test]
```

**Key insight**: The signal is computed on the **entire** close array, but only the OOS portion is evaluated. Because indicators are causal (each bar depends only on past bars), there is no look-ahead bias. The train window provides warmup for the indicator.

### Return Computation

For each OOS window:

```python
# Price returns
price_ret[i] = close[train + i + 1] / close[train + i] - 1

# Position (from signal)
position = signal_oos  # for trend signals (SMA, MACD, OBV)
# or: position = forward_fill(signal_oos)  # for action signals (RSI)

# Transaction costs
cost[i] = cost_factor × |position[i] - position[i-1]|
# where cost_factor = cost_bps / 10_000

# Net returns
net_ret[i] = position[i] × price_ret[i] - cost[i]
```

### Metrics Per Window

| Metric | Formula | Notes |
|--------|---------|-------|
| `mean_return_net` | `mean(net_ret)` | Average daily return after costs |
| `sharpe` | `mean(net_ret) / std(net_ret) × √252` | Annualized Sharpe ratio |
| `max_drawdown` | `max((peak - equity) / peak)` | Where peak = cummax(equity) |
| `total_return` | `prod(1 + net_ret) - 1` | Cumulative return |
| `cagr` | `(1 + total_return)^(252/n_bars) - 1` | Annualized return |
| `pnl` | `100,000 × total_return` | P&L on 100K nominal |
| `n_trades` | `sum(|diff(position)| > 0)` | Position changes |
| `fraction_positive_bars` | `mean(net_ret > 0)` | % of days with positive return |
| `is_valid` | `n_bars >= 20` | Minimum window size |

### Minimum Window Requirement

A window is marked `is_valid = True` only if `n_bars >= 20`. This prevents tiny residual windows (e.g., 5 bars at the end of the series) from distorting aggregate statistics.

The function returns results only if **≥3 valid windows** exist. This ensures that robustness scoring (Layer C) has enough data points.

---

## Cost Model

**Reference**: Chan (2008), Chapter 2 — "The Cost of Trading"

Transaction costs are modeled as a proportional fee on each position change:

```python
cost_factor = cost_bps / 10_000
cost[i] = cost_factor × |position[i] - position[i-1]|
```

**Default**: 10 bps (0.10%) per leg. Configurable via `cost_bps` parameter.

**Why position-change basis?** This captures the economic reality: a signal that flips between buy and sell every day incurs enormous costs, while a signal that holds a position for weeks incurs minimal costs. The cost model naturally penalizes over-trading.

**Action → Position conversion** (RSI only): RSI signals are actions (+1 = enter long, -1 = enter short, 0 = do nothing). These are forward-filled into positions before cost computation.

---

## Cooldown Mechanism

```python
def apply_cooldown(sig: np.ndarray, cooldown_bars: int) -> np.ndarray
```

After a signal change at bar `i`, the next `cooldown_bars` bars are forced to hold the same value. This models the practical reality that:
- Frequent signal flips are expensive (whipsaw)
- Some time is needed after a position change to observe its effect
- Short-term noise can cause spurious reversals

**Default**: 0 (no cooldown). Configurable via the frontend "Cooldown bars" input.

**Example** (cooldown=2):
```
Original:  [+1, +1, -1, +1, -1, -1, +1]
Cooldown:  [+1, +1, -1, -1, -1, -1, +1]
                       ^^  ^^  — held for 2 bars after change
```

---

## OOSWindowResult Dataclass

```python
@dataclass
class OOSWindowResult:
    window_index: int           # 0, 1, 2, ...
    train_start: int            # bar index (inclusive)
    train_end: int              # bar index (exclusive)
    test_start: int             # bar index (inclusive)
    test_end: int               # bar index (exclusive)
    n_trades: int               # position changes in window
    mean_return_net: float      # average daily net return
    sharpe: float               # annualized Sharpe
    max_drawdown: float         # max peak-to-trough
    fraction_positive_bars: float
    n_bars: int                 # test window bars
    is_valid: bool              # n_bars >= 20
    total_return: float         # cumulative return
    cagr: float                 # compound annual growth rate
    pnl: float                  # P&L on 100K nominal
```
