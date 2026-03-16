# Signal Generation — Signal Semantics & Contract

**Files:** `core/quant_core/strategy.py` (SignalFrame), `core/quant_core/portfolio.py` (interpretation)

---

## The Signal Frame Contract

### SignalFrame dataclass

```python
@dataclass
class SignalFrame:
    signals: pd.DataFrame
    # Index:   DatetimeIndex (aligned to market data timestamps)
    # Columns: symbol names (e.g., "ATW", "BCP", "IAM")
    # Values:  float64 in {-1.0, 0.0, +1.0}

    validity: Optional[pd.DataFrame]
    # Same shape as signals
    # True = signal is valid (indicator has warmed up)
    # False = signal should be ignored (warmup period)
    # None = all signals considered valid

    meta: Dict[str, Any]
    # Strategy signature, parameter values, notes
```

### Signal Values

| Value | Meaning | Portfolio interpretation (long-only) |
|-------|---------|-------------------------------------|
| `+1.0` | **BUY intent** — indicator says conditions favor going long | Open or maintain long position |
| `0.0` | **NEUTRAL** — no directional conviction | Hold current position (no change) |
| `-1.0` | **EXIT intent** — indicator says conditions no longer favor long | Close or reduce long position |

**Critical distinction:** Signals express **intent**, not orders. The portfolio layer interprets intent under constraints:
- `+1` with `buy_pct_cash=0.5` → buy with 50% of available cash
- `-1` in long-only mode → sell position (not short-sell)
- Signal change during `cooldown_bars` → ignored

---

## Signal Timing Convention

```
Day t:     Signal computed using data available at Close(t)
Day t+1:   Portfolio interprets signal → fills at Open(t+1)
Day t+1:   Mark-to-market at Close(t+1)
```

This is the **signal at close, fill at next open** convention. It avoids look-ahead bias: the signal at time `t` uses only information available at or before `t`.

### Why this matters

If you compute `signal(t)` using `Close(t)` and also fill at `Close(t)`, you are implicitly assuming you can observe the closing price and execute at that same price — which is impossible in practice. The next-open fill convention is conservative and realistic.

---

## NaN Policy

Strategy adapters must handle the warmup period where indicators are not yet valid.

### `nan_policy = "flat"` (default)
```python
# During warmup: output signal = 0.0 (hold flat, no exposure)
# Rationale: conservative — don't take positions based on invalid indicators
```

### `nan_policy = "nan"`
```python
# During warmup: output signal = NaN
# Downstream consumer decides how to handle
# Useful for research (distinguish "no opinion" from "hold")
```

### Implementation
```python
# In strategy generate_signals():
if self.spec.params.nan_policy == "flat":
    signals = signals.fillna(0.0)
# else: leave NaN in place
```

---

## Multi-Symbol Alignment

When generating signals for multiple symbols simultaneously:

1. **Index union:** All symbols must share the same DatetimeIndex
2. **Missing bars:** If symbol A has data on day X but symbol B doesn't, the behavior depends on context:
   - During optimization: inner join (only dates where ALL symbols have data)
   - During single-symbol backtest: not applicable
3. **Independent signals:** Each symbol's signal is computed independently — no cross-symbol dependencies in the current adapter implementations

### Alignment code (optimize.py)
```python
# Inner-intersect all symbols to a common index
common_idx = bars[symbols[0]].index
for sym in symbols[1:]:
    common_idx = common_idx.intersection(bars[sym].index)
# Slice all arrays to common_idx
```

---

## Validity Mask

The `validity` DataFrame in SignalFrame marks which signal values are trustworthy:

```python
validity[t, sym] = True   # Indicator is warmed up, signal is meaningful
validity[t, sym] = False  # Indicator is in warmup, signal should be ignored
```

### Warmup estimation

```python
# optimize.py — estimate_warmup_bars_from_params()
def estimate_warmup_bars_from_params(strategy_kind, params) -> int:
    """Conservative warmup estimate based on strategy and its parameters."""
    if strategy_kind == "ma_cross":
        return max(params.get("sma_fast_window", 15), params.get("sma_slow_window", 50))
    elif strategy_kind == "rsi":
        return params.get("rsi_window", 14) + 1
    elif strategy_kind == "ichimoku":
        return params.get("senkou_b", 52) + params.get("shift", 26)
    # ...
```

The optimizer pads the data load with extra warmup bars at the front, computes indicators on the full padded range, then slices back to the user's requested window. This ensures indicators are valid from bar 1 of the evaluation period.

---

## Signal vs Trade vs Fill

```
Signal layer (this doc):
  signal[t] ∈ {-1, 0, +1}     — directional intent at time t

Portfolio layer:
  desired_position[t] = f(signal[t], constraints)
  trade[t] = desired_position[t] - current_position[t]

Execution layer:
  fill[t+1] = trade[t] executed at Open(t+1) with costs
  position[t+1] = position[t] + fill[t+1]
  pnl[t+1] = position[t+1] * (Close(t+1) - Open(t+1)) + position[t] * (Open(t+1) - Close(t))
```

### What the signal layer controls
- Whether to be long, flat, or short at each timestamp
- How quickly signals change (related to indicator lookback)

### What the signal layer does NOT control
- Position size (set by `buy_pct_cash`, `sell_pct_shares`)
- Transaction costs (set by `cost_model`)
- Rebalancing frequency (set by `rebalance_policy`)
- Trade cooldown (set by `cooldown_bars`)
- Volume constraints (set by `use_participation_cap`, `use_volume_gate`)

This separation is fundamental to the signal-as-information philosophy.
