# 03 — PROM and Objective Function

**Reference**: Pardo (2008) Ch.9 p.239

---

## Purpose

Every optimization needs an objective function — a single number that ranks parameter sets from worst to best within an IS window. The choice of objective function is one of the most consequential design decisions in any optimization system.

This system uses **PROM (Pessimistic Return on Margin)** as the objective function, following Pardo's recommendation. PROM is specifically designed for trading strategy evaluation and has properties that standard financial metrics (Sharpe, profit factor, raw P&L) lack.

---

## PROM Formula

```
PROM = {[AW x (#WT - sqrt(#WT))] - [AL x (#LT + sqrt(#LT))]} / Capital
```

Where:
- `#WT` = number of winning trades
- `AW` = average win (mean profit of winning trades, in currency)
- `#LT` = number of losing trades
- `AL` = average loss (mean loss of losing trades, in currency, positive value)
- `Capital` = account equity

### Component Breakdown

**Pessimistic winning component:**
```
Adjusted wins = AW x (#WT - sqrt(#WT))
```
Reduces the win count by `sqrt(#WT)`. With 9 winning trades, the adjustment is `9 - 3 = 6` — a 33% reduction. With 100 winning trades: `100 - 10 = 90` — only a 10% reduction. Small samples are penalized heavily.

**Pessimistic losing component:**
```
Adjusted losses = AL x (#LT + sqrt(#LT))
```
Increases the loss count by `sqrt(#LT)`. Same asymmetry: small samples see larger adjustments.

**Net PROM:**
```
PROM = (Adjusted wins - Adjusted losses) / Capital
```
Normalized by capital to produce a return-on-capital measure.

---

## Natural Small-Sample Penalty

The square-root adjustment is PROM's key innovation. Consider:

| #WT | sqrt(#WT) | Adjustment | Effective win count |
|-----|-----------|------------|-------------------|
| 4 | 2.0 | 50% | 2.0 |
| 9 | 3.0 | 33% | 6.0 |
| 25 | 5.0 | 20% | 20.0 |
| 100 | 10.0 | 10% | 90.0 |
| 400 | 20.0 | 5% | 380.0 |

The same pattern applies to the loss side (but in the opposite direction — inflating losses).

**Effect on optimization:**
- A parameter set with 5 trades and 80% win rate gets heavily penalized
- A parameter set with 50 trades and 60% win rate may score higher
- This prevents the optimizer from selecting parameters that produce few but lucky trades
- Parameters that generate a statistically meaningful number of trades are naturally favored

---

## Why PROM Over Alternatives

### vs. Sharpe Ratio

Sharpe ratio = mean(returns) / std(returns). Problems for IS optimization:

1. **No trade-count penalty** — A parameter with 3 trades can have an excellent Sharpe from pure luck
2. **Distribution sensitivity** — Assumes returns are approximately normal, which trading strategies rarely produce
3. **Denominator instability** — With few observations, std(returns) is unreliable

PROM explicitly penalizes small trade counts through the square-root term.

### vs. Profit Factor

Profit factor = gross profits / gross losses. Problems:

1. **No trade-count penalty** — Same issue as Sharpe
2. **No capital normalization** — A strategy that risks the entire account and a conservative strategy are not comparable
3. **Undefined when no losses** — A lucky streak makes profit factor infinite

### vs. Raw P&L

Total profit. Problems:

1. **No risk adjustment** — A strategy that makes 10% with 50% drawdown scores the same as one that makes 10% with 5% drawdown
2. **No trade-count penalty** — A single lucky trade produces the same P&L as 50 consistent trades
3. **Not comparable across different IS windows** — Longer windows naturally produce more total P&L

### vs. PROM

PROM addresses all of these:

| Property | Sharpe | Profit Factor | Raw P&L | PROM |
|----------|--------|---------------|---------|------|
| Trade-count penalty | No | No | No | Yes (sqrt) |
| Capital-normalized | No | No | No | Yes |
| Handles small samples | Poorly | Poorly | Poorly | By construction |
| Defined for all outcomes | Yes | No (div/0) | Yes | Yes |
| Penalizes lucky outliers | Weakly | No | No | Yes |

---

## Cost Adjustment

All trades used in PROM computation include transaction costs. The PROM formula operates on **net** trade P&Ls, not gross P&Ls.

```python
def compute_trade_pnl(entry_price, exit_price, direction, cost_bps):
    gross_pnl = direction * (exit_price - entry_price)
    cost = cost_bps / 10_000 * (entry_price + exit_price)  # round-trip
    net_pnl = gross_pnl - cost
    return net_pnl
```

This means PROM naturally penalizes strategies that trade too frequently — each trade incurs costs, reducing AW and increasing AL. A strategy that trades every day must produce sufficient gross profits to overcome daily transaction costs, which in the Moroccan market (with brokerage, commission, slippage, and TVA) can be significant.

---

## PROM Implementation

```python
def compute_prom(trades: list[Trade], capital: float) -> float:
    """
    Compute Pessimistic Return on Margin (Pardo Ch.9 p.239).

    Args:
        trades: List of completed trades with net P&L
        capital: Account equity for normalization

    Returns:
        PROM value (higher is better, can be negative)
    """
    if len(trades) == 0:
        return float('-inf')

    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [abs(t.net_pnl) for t in trades if t.net_pnl <= 0]

    n_wt = len(wins)
    n_lt = len(losses)
    aw = mean(wins) if n_wt > 0 else 0.0
    al = mean(losses) if n_lt > 0 else 0.0

    adj_wins = aw * (n_wt - sqrt(n_wt)) if n_wt > 0 else 0.0
    adj_losses = al * (n_lt + sqrt(n_lt)) if n_lt > 0 else 0.0

    prom = (adj_wins - adj_losses) / capital
    return prom
```

### Edge Cases

| Condition | Behavior | Rationale |
|-----------|----------|-----------|
| No trades | Return `-inf` | Parameter that generates no trades is worst possible |
| All wins, no losses | `adj_losses = 0` | PROM = adjusted wins / capital (still penalized by sqrt on wins) |
| All losses, no wins | `adj_wins = 0` | PROM = -adjusted losses / capital (negative, penalized by sqrt on losses) |
| 1 trade, winning | `aw * (1 - 1) = 0` | PROM = 0. A single trade carries zero information. |
| 1 trade, losing | `al * (1 + 1) = 2*al` | PROM = -2*al/capital. A single losing trade is doubly penalized. |

The 1-trade case is particularly elegant: a single winning trade produces PROM = 0, meaning the optimizer cannot be seduced by a lucky single trade. This is exactly the behavior we want.

---

## Capital Parameter

Pardo's original PROM formula uses futures margin as the denominator. For equities (our context), we use account equity — the capital allocated to this stock via HRP allocation on the strategy page.

```
Capital = account_equity * allocation_weight_for_stock
```

This makes PROM a return-on-allocated-capital measure, comparable across stocks with different allocations.
