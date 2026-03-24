# 02 — Layer A: Candidate Universe Generation

**File**: `core/quant_core/signal_engine/candidates.py`

---

## Purpose

Layer A generates a structured set of 30 candidate variants per (family, horizon) combination. These candidates are not random — each parameter point is chosen based on practitioner conventions, economic reasoning, and horizon-appropriate scaling.

The candidate universe is deliberately small and structured because:
- **Multiple testing cost**: every additional candidate increases the chance of false positives (Harvey et al. 2016)
- **Computational cost**: each candidate goes through full OOS evaluation (Layer B)
- **Interpretability**: each candidate should have a clear human-readable description

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

## The 4 Families

### SMA (Simple Moving Average)

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

### RSI (Relative Strength Index)

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

### MACD (Moving Average Convergence/Divergence)

**Archetype**: `macd_cross`
**Signal rule**: +1 if MACD line > signal line (bullish crossover), -1 if MACD line < signal line (bearish crossover), 0 otherwise
**Economic rationale**: MACD measures the acceleration of trend by comparing short-term vs long-term EMAs (Appel 2005). A positive MACD-to-signal crossover indicates increasing bullish momentum.

**Parameters**: `fast` (short EMA), `slow` (long EMA), `signal` (signal EMA)

| Horizon | Fast (5) | Slow (3) | Signal (2) |
|---------|----------|----------|------------|
| Short | 6, 8, 10, 12, 15 | 16, 20, 26 | 7, 9 |
| Medium | 8, 10, 12, 15, 18 | 20, 26, 30 | 7, 9 |
| Long | 10, 12, 15, 18, 20 | 26, 30, 35 | 9, 12 |

**30 candidates** = 5 fast × 3 slow × 2 signal

**Parameter rationale**: The classic MACD uses (12, 26, 9). We explore a neighborhood around this canonical choice, scaling fast/slow periods with the horizon.

### OBV (On-Balance Volume)

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
    family: str           # "sma", "rsi", "macd", "obv"
    archetype: str        # "price_vs_sma", "rsi_level", "macd_cross", "obv_trend"
    params: dict          # {"window": 20} or {"fast": 12, "slow": 26, "signal": 9}
    description: str      # "SMA-20 Price-Level (medium)"
```

Frozen (immutable) to prevent accidental mutation during pipeline processing.

---

## Why 30 Candidates?

The choice of 30 per family is deliberate:

1. **Statistical**: With 30 candidates and a 5% false positive rate, ~1.5 candidates would pass by chance. The viability gate (40% positive windows + 3 valid windows) is much stricter than 5%, so the actual false positive rate is lower.

2. **Computational**: 30 candidates × 4 families = 120 total. Each goes through full OOS evaluation (~5–15 windows per candidate). This runs in seconds on modern hardware.

3. **Coverage**: 30 parameter points provide good coverage of the economically meaningful parameter space without testing every integer. The grid is denser in the "sweet spot" (e.g., SMA 10–50 for medium horizon) and sparser at the extremes.

4. **Extensibility**: Adding a 5th family adds exactly 30 more candidates — the pipeline scales linearly.
