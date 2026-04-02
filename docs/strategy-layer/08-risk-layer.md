# Strategy Layer — Risk Layer

## What

The Risk section defines **global safety parameters** that protect the portfolio independently of entry/exit rule logic. These are hard boundaries — they override strategy signals when triggered.

Risk parameters are **separate from exit rules**. Exit rules close positions based on indicator scores (thesis weakening). Risk parameters close positions based on price levels, time, and portfolio limits (emergency conditions).

## Why

Even a well-designed entry/exit rule system needs a safety net:

- An indicator score may not update fast enough during a flash crash
- A mean-reversion strategy can be catastrophically wrong if the stock keeps falling
- A position held too long accumulates opportunity cost
- A portfolio concentrated in one stock or one sector carries uncompensated risk

The Risk layer ensures that no single failure in the signal or rule logic can produce unbounded loss.

## Risk Parameters

### Stop Loss

Defines the maximum acceptable loss per trade.

| Mode | Description | WFO-Optimizable |
|------|------------|-----------------|
| Manual % | Fixed percentage below entry price (e.g., -5%) | No |
| ATR-based | `entry_price - ATR(14) * multiplier` | Yes (multiplier) |
| WFO-optimized | Optimizer finds the best stop distance | Yes |

**ATR-based stops** are preferred because they adapt to the stock's volatility. A 5% stop on a low-volatility stock may be too tight (whipsawed by noise); the same 5% on a high-volatility stock may be too loose (absorbs too much loss before triggering).

Formula for long positions:
```
stop_price = entry_price - ATR(14) * atr_stop_multiplier
```

For short positions:
```
stop_price = entry_price + ATR(14) * atr_stop_multiplier
```

Default `atr_stop_multiplier`: 2.0 (the stop is 2 ATR below entry for longs).

**Source**: Wilder (1978) introduced ATR as a measure of "normal" price fluctuation. Placing stops beyond normal fluctuation reduces the chance of being stopped out by noise.

### Take Profit

Defines a target price at which to lock in gains.

| Mode | Description | WFO-Optimizable |
|------|------------|-----------------|
| Manual % | Fixed percentage above entry price (e.g., +10%) | No |
| R:R target | Risk-reward ratio applied to stop distance (e.g., 2:1) | Yes (ratio) |
| WFO-optimized | Optimizer finds the best target distance | Yes |

**R:R target mode** ties the take-profit to the stop loss:
```
take_profit = entry_price + (entry_price - stop_price) * rr_ratio
```

For example, if the stop is 2 ATR below entry and R:R = 2.0, the target is 4 ATR above entry.

Default `rr_ratio`: 2.0.

### Trade Cooldown

Defines the minimum number of bars between closing one trade and opening the next on the same stock.

| Mode | Description | WFO-Optimizable |
|------|------------|-----------------|
| Manual bars | Fixed number of bars (e.g., 5 bars) | No |
| WFO-optimized | Optimizer finds the best cooldown period | Yes |

**Why cooldown matters**: Without a cooldown, the system can close a trade on bar N and immediately re-enter on bar N+1 if the entry conditions are still met. This creates churn: high transaction costs, frequent whipsaws, and unrealistic backtest results.

Default: 5 bars.

### Time Stop

Defines the maximum number of bars a position can be held before forced exit.

| Mode | Description | WFO-Optimizable |
|------|------------|-----------------|
| Manual bars | Fixed max holding period (e.g., 60 bars) | No |
| WFO-optimized | Optimizer finds the best max holding period | Yes |

**Why time stops matter**: A position that has not reached its target or stop after a long period is consuming capital without resolution. A time stop frees that capital for other opportunities.

Default: 60 bars (approximately 3 months of daily bars).

### Max Position %

Defines the maximum portfolio allocation to a single stock.

| Mode | Description | WFO-Optimizable |
|------|------------|-----------------|
| Manual % | Fixed cap (e.g., 20%) | **No — always manual** |

This is **always manual** because it reflects the user's risk appetite, not an optimization target. A user who is comfortable with 30% concentration has a different risk profile than one who caps at 10%. The optimizer should not override that judgment.

Default: 20%.

### Max Sector %

Defines the maximum portfolio allocation to a single sector.

| Mode | Description | WFO-Optimizable |
|------|------------|-----------------|
| Manual % | Fixed cap (e.g., 40%) | **No — always manual** |

Same rationale as max position % — this is a risk appetite parameter, not an optimization target.

Default: 40%.

**Sector handling**: If a stock has no sector, it is bucketed as `Unknown`. The `Unknown` bucket still participates in the sector cap. It must not be excluded from risk control.

## WFO Parameter Count from Risk

Each WFO-optimizable parameter adds to the total WFO parameter count:

| Parameter | WFO-Optimizable | Params if WFO |
|-----------|-----------------|---------------|
| Stop loss (ATR multiplier) | Yes | 1 |
| Take profit (R:R ratio) | Yes | 1 |
| Trade cooldown | Yes | 1 |
| Time stop | Yes | 1 |
| Max position % | No | 0 |
| Max sector % | No | 0 |

Maximum WFO parameters from the risk section: **4**.

## Parameter Interactions

### Stop Loss vs Exit Rules

Both can close a position. Priority:

1. Stop loss always executes if triggered (price-based, immediate)
2. Exit rules execute on the next bar open (indicator-based, at rebalance)

If the stop loss is hit intra-bar and an exit rule also triggers on the same bar, the stop loss takes precedence.

### Take Profit vs Exit Rules

Same priority: take profit executes before exit rules if both trigger on the same bar.

### Cooldown and Entry Rules

During the cooldown period after a trade closes:

- entry rule conditions are still evaluated (for preview/display)
- but no new position is opened
- the UI should show "Cooldown: X bars remaining"

### Time Stop and Exit Rules

If the time stop fires:

- the entire remaining position is closed
- any pending exit rules for that stock are cleared
- this is a full exit, not partial

## Summary Table

| Parameter | Default | Range | WFO | Priority |
|-----------|---------|-------|-----|----------|
| Stop loss | 2.0 ATR | 0.5–5.0 ATR | Yes | Highest — executes immediately |
| Take profit | 2.0 R:R | 1.0–5.0 R:R | Yes | High — executes at target |
| Cooldown | 5 bars | 0–20 bars | Yes | Prevents re-entry |
| Time stop | 60 bars | 10–252 bars | Yes | Forces exit on timeout |
| Max position % | 20% | 5–50% | No | Caps entry sizing |
| Max sector % | 40% | 10–100% | No | Caps sector exposure |

## Inputs

- risk configuration from the draft
- ATR(14) per stock
- entry price per stock (for stop/target calculations)
- sector mapping per stock (for sector cap)

## Outputs

- computed stop loss price per stock
- computed take profit price per stock
- cooldown status per stock
- time stop status per stock
- position and sector cap status
- WFO parameter count contribution

## Edge Cases

### Stop loss and take profit at the same distance

If R:R = 1.0 and stop distance equals target distance:

- both are valid but the strategy has no edge in geometry
- the review section should warn: "R:R = 1.0. The strategy requires a win rate > 50% to be profitable."

### ATR not computable

If the stock has insufficient data for ATR(14):

- the risk section should use the manual % fallback
- the UI should warn: "Insufficient data for ATR-based stops. Using manual percentage."

### Max position % exceeded by entry rules

If entry rules would allocate more than max position %:

- the risk cap takes precedence
- the last entry that would exceed the cap is reduced to fit
- the review section should flag this: "Entry rules capped by max position %."

## Cross-Links

- Entry rules define the sizing that risk caps: see [06-entry-rules-layer.md](./06-entry-rules-layer.md)
- Exit rules provide indicator-based exits alongside risk exits: see [07-exit-rules-layer.md](./07-exit-rules-layer.md)
- WFO parameter count feeds the review: see [09-review-and-backtest-handoff.md](./09-review-and-backtest-handoff.md)
- ATR normalization rationale: Wilder (1978) — see [12-methodology-and-sources.md](./12-methodology-and-sources.md)
