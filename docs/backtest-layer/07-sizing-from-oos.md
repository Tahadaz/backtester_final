# 07 — Sizing from OOS Trades

**References**: Kelly (1956), Thorp (2006), Pardo (2008) Ch.11

---

## Purpose

The strategy page allows users to manually input win rate and win/loss ratio for Kelly sizing — with the honest label "a calibrer" (to be calibrated). WFO provides that calibration: win rate and W/L ratio are computed from concatenated OOS trades, producing position sizing grounded in observed out-of-sample performance rather than manual estimates.

Phase 1 uses this information in two distinct ways:

1. **Execution-time Kelly estimate** — used during walk-forward execution without lookahead
2. **Authoritative OOS Kelly report** — computed from concatenated OOS trades of the winning configuration after the WFO run completes

The distinction matters. Pardo-style walk-forward discipline does not allow the engine to use future OOS outcomes to size the very OOS window being tested.

---

## Data Source: Concatenated OOS Trades

From the winning WFO configuration, concatenate all trades from all OOS windows:

```python
def collect_oos_trades(winning_config: WFOConfig) -> list[Trade]:
    """
    Collect all trades from OOS windows of the winning configuration.

    These trades are truly out-of-sample: each OOS window used parameters
    optimized on a non-overlapping IS window. No OOS data was seen during
    any optimization step.
    """
    all_trades = []
    for window in winning_config.windows:
        all_trades.extend(window.oos_trades)
    return all_trades
```

**Why concatenation is valid:**
- Each OOS window's trades used parameters optimized on a separate IS window
- OOS windows do not overlap (step = OOS length, standard Pardo WFA)
- No OOS data point was used in any optimization decision
- The concatenated trades represent the strategy's performance on truly unseen data across multiple market regimes

---

## Trade Statistics

```python
def compute_trade_stats(trades: list[Trade]) -> TradeStats:
    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]

    win_rate = len(wins) / len(trades)  # W
    avg_win = mean([t.net_pnl for t in wins]) if wins else 0.0
    avg_loss = mean([abs(t.net_pnl) for t in losses]) if losses else 1.0
    wl_ratio = avg_win / avg_loss if avg_loss > 0 else float('inf')  # R

    return TradeStats(
        n_trades=len(trades),
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        wl_ratio=wl_ratio,
    )
```

---

## Kelly Criterion

```
Kelly fraction = W - (1 - W) / R
```

Where:
- `W` = win rate (probability of a winning trade)
- `R` = win/loss ratio (average win / average loss)

### Derivation

Kelly (1956) derived the optimal fraction of capital to risk on each bet to maximize the long-term growth rate of wealth. For a binary outcome (win with probability W, lose with probability 1-W) with payoff ratio R:

```
f* = W - (1-W) / R
```

This is the fraction that maximizes `E[log(wealth)]` — the expected logarithm of wealth, which is equivalent to maximizing the geometric growth rate.

### Implementation

```python
def compute_kelly_fraction(stats: TradeStats) -> KellyResult:
    W = stats.win_rate
    R = stats.wl_ratio

    if R <= 0 or W <= 0:
        return KellyResult(fraction=0.0, reason="No positive expectancy")

    kelly = W - (1 - W) / R

    if kelly <= 0:
        return KellyResult(fraction=0.0, reason="Negative Kelly — no edge")

    return KellyResult(
        fraction=kelly,
        win_rate=W,
        wl_ratio=R,
        n_trades=stats.n_trades,
    )
```

### Example

```
From OOS trades:
  n_trades = 85
  n_wins = 48, n_losses = 37
  win_rate W = 48/85 = 0.565
  avg_win = 3,200 MAD, avg_loss = 2,100 MAD
  wl_ratio R = 3200/2100 = 1.524

Kelly fraction = 0.565 - (1 - 0.565) / 1.524
               = 0.565 - 0.435 / 1.524
               = 0.565 - 0.285
               = 0.280

Optimal Kelly: risk 28.0% of allocated capital per trade
```

---

## How Kelly Replaces Manual Sizing

On the strategy page, the sizing section has:

```
Win rate:      [manual input] "a calibrer"
W/L ratio:     [manual input] "a calibrer"
Kelly fraction: [computed from above]
```

After WFO:

```
Win rate:      0.565  (from 85 OOS trades)
W/L ratio:     1.524  (from 85 OOS trades)
Kelly fraction: 0.280  (computed)

Source: Walk-Forward Analysis, 12 OOS windows, 85 total trades
```

The manually-input values are **replaced** by the WFO-derived values. The user can still override, but the default becomes the statistically grounded estimate.

---

## Confidence and Sample Size

Kelly's formula assumes the true win rate and W/L ratio are known. With finite OOS trades, we have estimates with uncertainty.

**Minimum trade count:** With fewer than 30 OOS trades, the Kelly estimate is unreliable. The system warns:

```
if stats.n_trades < 30:
    warning = (f"Only {stats.n_trades} OOS trades. "
               f"Kelly estimate has high uncertainty. "
               f"Consider using half-Kelly (f/2) as a conservative approach.")
```

**Half-Kelly:** A common practical adjustment — use f/2 instead of f. This sacrifices approximately 25% of the growth rate (since growth is quadratic near the optimum) while substantially reducing variance. The system displays both full Kelly and half-Kelly:

```
Kelly fraction:      0.280  (full)
Half-Kelly fraction: 0.140  (conservative)
OOS trade count:     85
```

---

## Why This Extension Beyond Pardo is Justified

Pardo (2008) does not discuss Kelly criterion. He uses PROM for parameter selection and WFE for validation, but does not address position sizing. Our extension:

1. **Uses OOS data only** — the Kelly inputs come from concatenated OOS trades, which were never seen during optimization. There is no data snooping.

2. **Is additive, not a modification** — the WFO pipeline (PROM, neighbor-averaging, WFE) is unchanged. Kelly sizing is computed after WFO completes, using WFO's outputs as inputs.

3. **Follows standard practice** — Kelly criterion is a foundational result in information theory (Kelly 1956) with extensive application to trading (Thorp 2006, Vince 1990). It is the mathematically optimal sizing rule given known win rate and payoff ratio.

4. **Solves a real problem** — the "a calibrer" fields on the strategy page were an honest acknowledgment that win rate and W/L ratio should come from data, not guesses. WFO provides that data.

The alternative — leaving sizing as manual input — is strictly worse. It introduces human bias (overconfidence in win rate, underestimation of losses) into the one parameter that most directly controls risk of ruin.

## Phase 1 Kelly execution rule

For `kelly_wfo`, the implemented sizing rule is:

```
final size = Kelly(from WFO) x modifier
```

Where:

- the raw Kelly number is always WFO-derived
- the modifier is the separate risk dial
- the modifier may be manual or WFO-optimized

If a window does not have enough usable information to estimate Kelly safely, execution falls back to that rule's `manual_pct` and records a warning.

---

## Sizing Value Lifecycle

The sizing values follow an explicit three-state lifecycle across the strategy and backtest pages:

### State 1 — Before WFO (Strategy Page)

The strategy page stores placeholder sizing values:

```ts
sizing: {
  mode: "manual",
  win_rate: null,        // displayed as "À calibrer"
  wl_ratio: null,        // displayed as "À calibrer"
  kelly_fraction: null
}
```

The user can optionally enter manual estimates, but the system encourages calibration via WFO.

### State 2 — After WFO (Backtest Results)

WFO computes sizing from concatenated OOS trades:

```ts
backtest_result.sizing: {
  win_rate: 0.58,
  wl_ratio: 1.42,
  kelly_fraction: 0.167,
  half_kelly: 0.084,
  n_trades: 47,
  source: "wfo_oos"
}
```

Displayed in backtest results Section 3 (Sizing Results). This value is **run-local** — it belongs to the backtest run, not the strategy.

### State 3 — Apply Back to Strategy (User Action)

The backtest results page offers an explicit "Appliquer le sizing" action. When clicked:

1. The computed `win_rate`, `wl_ratio`, and `kelly_fraction` are written to the strategy's sizing fields
2. The strategy status changes to `modified`
3. The user must save the strategy to persist the change

This is a deliberate user action, not automatic. Rationale: auto-persisting would overwrite the user's draft without consent, and different WFO runs may produce different sizing values.
