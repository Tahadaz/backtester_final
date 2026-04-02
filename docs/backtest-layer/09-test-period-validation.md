# 08 — Test Period Validation

---

## Purpose

The test period is data remaining **after** the WFO period ends. It was never seen by any part of the optimization process — not during IS optimization, not during OOS validation, not during configuration selection. This makes it the **strongest validation available**.

```
|<---------- WFO period ----------->|<--- test period --->|
|  IS  | OOS | IS  | OOS | IS | OOS |                     |
|  win1       win2        win3       |  pure out-of-sample |

Data timeline ---------------------------------------------------------->
```

---

## Data Partitioning

The user sets the WFO start date on the backtest page. The WFO period runs from that start date through the last OOS window. Everything after is the test period.

```python
def partition_data(data, wfo_start_date, winning_config):
    wfo_start_idx = date_to_index(data, wfo_start_date)

    # WFO uses data from wfo_start_idx through end of last OOS window
    last_oos_end = winning_config.windows[-1].oos_end_idx
    wfo_data = data[wfo_start_idx : last_oos_end]

    # Test period = everything after WFO
    test_data = data[last_oos_end:]

    return wfo_data, test_data
```

### How Much Test Data?

The test period length depends on:
- Total data available
- WFO start date (user-controlled)
- Number and size of walk-forward windows (determined by configuration)

**Typical scenarios for Moroccan stocks (10-15 years of data):**

| Horizon | WFO period | Typical test period | Assessment |
|---------|-----------|--------------------|----|
| Short | 3-4 years | 1-2 years | Good |
| Medium | 5-8 years | 2-5 years | Good |
| Long | 8-15 years | 0-5 years | Often limited |

---

## What Runs on the Test Period

The WFO-optimized strategy with:
1. **Final parameters** — from the last IS window of the winning configuration (doc 05)
2. **WFO-derived sizing** — Kelly fraction from concatenated OOS trades (doc 07)
3. **Full cost model** — same brokerage, commission, slippage, TVA as the WFO period
4. **Same execution constraints** — volume gate, cooldown

```python
def run_test_period(test_data, final_params, kelly_fraction, cost_model):
    """
    Run the fully optimized strategy on held-out test data.

    This is a standard backtest — no optimization, no parameter search.
    Just execute the strategy as-is and record results.
    """
    trades = simulate_strategy(
        data=test_data,
        params=final_params,
        position_size=kelly_fraction,
        cost_model=cost_model,
    )

    return compute_backtest_metrics(trades, test_data)
```

---

## Results Display

### Equity Curve

Cumulative return of the strategy on the test period, plotted over time. Shows growth trajectory, drawdown periods, and recovery.

### Key Metrics

| Metric | Description |
|--------|-------------|
| Total return | Cumulative return over test period |
| CAGR | Compound annual growth rate |
| Sharpe ratio | Annualized risk-adjusted return |
| Max drawdown | Largest peak-to-trough decline |
| Calmar ratio | CAGR / max drawdown |
| Win rate | % of trades profitable (on test period) |
| Profit factor | Gross profits / gross losses |
| Number of trades | Total trades executed |
| Average trade duration | Mean holding period |

### Trade Ledger

Full list of trades with:

| Field | Description |
|-------|-------------|
| Entry date | When the position was opened |
| Entry price | Execution price |
| Exit date | When the position was closed |
| Exit price | Execution price |
| Direction | Long / Short |
| Size | Position size (from Kelly) |
| Gross P&L | Before costs |
| Costs | Transaction costs for this trade |
| Net P&L | After costs |
| Return % | Net P&L / entry value |
| Duration | Bars held |

---

## Interpretation

### Test Period Results vs. WFO OOS Results

| Aspect | WFO OOS windows | Test period |
|--------|-----------------|-------------|
| Data seen during optimization? | No (OOS) | No |
| Parameters fixed during evaluation? | Yes (IS winner for each window) | Yes (last IS winner) |
| Part of WFE computation? | Yes | No |
| Part of Kelly computation? | Yes (trade stats) | No |
| Independent of all optimization? | Partially (configuration selection uses WFE from OOS) | **Fully** |

The test period is the only evaluation where **no aspect of the data** influenced any optimization decision. Even the OOS windows in WFO indirectly influenced the configuration selection (via WFE). The test period is purely held-out.

### What to Expect

Realistic expectations for test period performance relative to WFO OOS:

- **Similar to OOS returns:** Good sign — the strategy generalizes beyond the WFO period
- **Somewhat lower than OOS:** Normal — some degradation is expected as markets evolve
- **Significantly lower than OOS:** Warning — the WFO configuration selection may itself be overfitted
- **Negative:** The strategy may not be viable despite passing WFO checks

The test period is a **reality check**, not a guarantee. A strategy that passes WFO with good WFE but fails the test period deserves serious scrutiny.

---

## Short Test Period Warning

If the test period contains fewer than approximately 126 bars (~6 months), results are statistically unreliable:

```python
MIN_TEST_BARS = 126  # ~6 months at 252 bars/year

if len(test_data) < MIN_TEST_BARS:
    warning = (
        f"Test period is only {len(test_data)} bars "
        f"(~{len(test_data)/252:.1f} years). "
        f"Results are displayed but have low statistical power. "
        f"Consider extending data or adjusting WFO start date."
    )
```

The system still displays results — any out-of-sample data is better than none — but the warning is prominent.

### When There Is No Test Period

If the WFO period consumes all available data (last OOS window extends to the end of the data), there is no test period. This happens most often with:
- Long horizon strategies with limited data
- WFO start date set too early, consuming all data for walk-forward windows

In this case, the system displays:

```
Test period: No data available after WFO period.

The strategy was validated through WFO only (WFE and OOS windows).
For additional validation, either:
  - Move WFO start date forward to reserve test data
  - Wait for more market data to accumulate
```

The WFO results (WFE, OOS window profitability) remain valid — the test period is an additional layer of validation, not a replacement for WFO.

---

## Why This Matters

The test period closes the last potential loophole in the validation chain:

```
IS optimization     -> validated by OOS windows (WFE)
Configuration selection -> validated by test period
Test period         -> not validated (there is nothing left)
```

This is the fundamental limit of finite data. With 15 years of Moroccan stock data, we can build a three-layer validation chain (IS -> OOS -> test). Each layer catches a different type of overfitting:

| Layer | What it catches |
|-------|-----------------|
| OOS windows | Parameter overfitting (IS winner doesn't transfer) |
| WFE threshold | Configuration overfitting (wrong IS/OOS window sizes) |
| Test period | Process overfitting (the entire WFO procedure found spurious patterns) |

No single layer is sufficient. Together, they provide the strongest evidence available that a strategy has genuine predictive value.
