# Strategy Layer — Entry Rules Layer

## What

The Entry Rules section defines **when to open or increase a position** and **how much exposure to take per entry**. It replaces the old "Execution Layer" which combined entry, holding, and exit logic into one section.

Entry rules are structured as a **list of entries**. The user can add as many entry levels as needed. Each entry has exactly two parameters:

1. **Rule parameter** — the conditions that trigger this entry
2. **Sizing parameter** — the exposure allocated to this entry

## Why

A single entry threshold is too rigid for real trading:

- A trend follower might want a small initial position when the trend is young, and a larger addition when momentum confirms
- A mean reverter might want to scale in: a small position at RSI < 30, more at RSI < 20, maximum at RSI < 15

Multiple entry levels with graduated sizing enable these strategies naturally. The 5 configuration options (A–E) give the user full control over how much of this is manual vs WFO-optimized.

## Entry Rule Structure

Each entry in the list has:

```ts
type EntryRule = {
  id: string
  label: string                    // e.g., "Entry 1", "Aggressive Add"
  rule: RuleParameter              // conditions to trigger
  sizing: SizingParameter          // exposure for this entry
  config_option: "A" | "B" | "C" | "D" | "E"
}
```

### Rule Parameter

A condition expression using family scores and boolean operators:

```
trend_score > 2.0 AND momentum_score > 1.0
```

Available score variables:
- `trend_score` — from the Tendance family
- `momentum_score` — from the Momentum family
- `oscillation_score` (or `rsi_score`) — from the Oscillation family
- `volume_score` — from the Volume family

Available operators:
- Comparison: `>`, `<`, `>=`, `<=`, `==`
- Boolean: `AND`, `OR`
- Grouping: parentheses `()`

### Sizing Parameter

The exposure for this entry, expressed as a percentage of the portfolio allocation for this stock:

- **Manual**: user sets an exact percentage (e.g., 30% of allocated capital)
- **Kelly from WFO**: the backtest engine computes optimal sizing using the Kelly criterion applied to WFO out-of-sample results
- **WFO-optimized**: the optimizer determines the exposure as part of the joint optimization

## The 5 Configuration Options

### Option A: Manual Rule + Manual Sizing

The user sets both the rule conditions and the sizing manually.

```
Entry 1:
  Rule:   trend_score > 2.0 AND momentum_score > 1.0
  Sizing: 50% of allocation
  
Entry 2:
  Rule:   trend_score > 3.0 AND momentum_score > 2.0 AND volume_score > 0.05
  Sizing: 50% of allocation (add to position)
```

WFO parameters from this entry section: **0**. Full manual control.

**When to use**: The user has clear conviction about when and how much to enter. Suitable for discretionary traders who want the system to execute their judgment.

### Option B: Manual Rule + Kelly from WFO

The user defines the entry conditions. WFO computes optimal sizing using Kelly criterion from OOS results.

```
Entry 1:
  Rule:   trend_score > 2.0 AND momentum_score > 1.0
  Sizing: Kelly(modifier=0.5) from WFO OOS metrics
```

WFO parameters from this entry: **1** (Kelly sizing derived from optimization results). The rule thresholds are fixed.

**When to use**: The user trusts their entry logic but wants data-driven position sizing.

### Option C: WFO Thresholds + Manual Sizing

WFO optimizes the threshold values in the rule conditions. The user fixes the sizing.

```
Entry 1:
  Rule:   trend_score > WFO(min=0.5, max=4.0, step=0.5) 
          AND momentum_score > WFO(min=0.5, max=3.0, step=0.5)
  Sizing: 50% of allocation
```

WFO parameters from this entry: **2** (trend threshold, momentum threshold). The structure of the rule (which scores, which operators) is fixed by the user.

**When to use**: The user knows which indicators matter but wants the optimizer to find the best thresholds.

### Option D: WFO Thresholds + Kelly from WFO

Both thresholds and sizing are optimized.

```
Entry 1:
  Rule:   trend_score > WFO(min=0.5, max=4.0, step=0.5)
          AND momentum_score > WFO(min=0.5, max=3.0, step=0.5)
  Sizing: Kelly(modifier=WFO) from WFO OOS metrics
```

WFO parameters from this entry: **3** (trend threshold, momentum threshold, Kelly sizing).

**When to use**: Systematic traders who want the optimizer to determine both when and how much to enter.

### Option E: Full WFO

WFO discovers the optimal number of entry levels, the thresholds for each, AND the exposure per level — all jointly optimized.

```
WFO search space:
  Number of entries: try 2, 3, 4 levels
  Per entry: threshold per score + exposure %
  Objective: PROM (Pessimistic Return on Margin)
```

**How it works:**

1. WFO tries 2 entry levels, optimizes thresholds + exposures
2. WFO tries 3 entry levels, optimizes thresholds + exposures
3. WFO tries 4 entry levels, optimizes thresholds + exposures
4. PROM naturally penalizes too many levels (more levels = more trades = more cost = lower PROM unless the levels genuinely add value)

**Constraint**: Option E is only available when the rule parameters are also WFO-optimized (joint optimization). You cannot have the number of entries auto-discovered while the thresholds within each entry are manually fixed — the two must be optimized together.

WFO parameters from this section: **variable** (depends on how many levels and score variables the optimizer explores).

**When to use**: Maximum optimization freedom. Best for stocks with long data history (>12 years) where the optimizer has enough data to avoid overfitting.

## Concrete Examples

### Example 1: Trend Following on IAM (Option A)

```
Strategy Type: Trend Following
Signal Construction: SMA(50), MACD(12,26,9), RSI(14), OBV(20)

Entry 1 — "Initial Position":
  Rule:   trend_score > 1.5 AND momentum_score > 0.5
  Sizing: 40% of allocation
  
Entry 2 — "Momentum Confirmation":
  Rule:   trend_score > 2.5 AND momentum_score > 1.5 AND volume_score > 0.03
  Sizing: 60% of allocation (adds to position)
  
Filter (applied to all entries):
  Skip if oscillation_score > 80  (RSI overbought — don't chase)
```

Total exposure if both entries trigger: 100% of stock allocation.

### Example 2: Mean Reversion on BCP (Option C)

```
Strategy Type: Mean Reversion
Signal Construction: SMA(200), MACD(12,26,9), RSI(14), OBV(20)

Entry 1 — "Oversold Level 1":
  Rule:   oscillation_score < WFO(min=20, max=35, step=5)
          AND trend_score > WFO(min=-1.0, max=1.0, step=0.5)
  Sizing: 33% of allocation
  
Entry 2 — "Oversold Level 2":
  Rule:   oscillation_score < WFO(min=10, max=25, step=5)
  Sizing: 33% of allocation
  
Entry 3 — "Deep Oversold":
  Rule:   oscillation_score < WFO(min=5, max=15, step=5)
  Sizing: 34% of allocation
```

WFO parameters: 4 (two thresholds in Entry 1, one each in Entry 2 and 3). Total exposure if all trigger: 100%.

### Example 3: Full WFO on ATW (Option E)

```
Strategy Type: Trend Following
Signal Construction: all parameters WFO-optimized

Entry Rules: Full WFO
  Score variables: trend_score, momentum_score
  Number of levels: WFO tries 2, 3, 4
  Per level: threshold + exposure
  Objective: maximize PROM
```

The optimizer discovers that 3 levels work best:
- Level 1: trend_score > 1.2, exposure 25%
- Level 2: trend_score > 2.1 AND momentum_score > 0.8, exposure 35%
- Level 3: trend_score > 3.0 AND momentum_score > 1.5, exposure 40%

## Summary Table: Configuration Options

| Option | Rule | Sizing | WFO Params per Entry | User Control |
|--------|------|--------|---------------------|--------------|
| A | Manual thresholds | Manual % | 0 | Maximum |
| B | Manual thresholds | Kelly from WFO | 1 | High |
| C | WFO thresholds | Manual % | N (one per threshold) | Medium |
| D | WFO thresholds | Kelly from WFO | N + 1 | Low |
| E | Full WFO (joint) | Full WFO (joint) | Variable | Minimum |

## Inputs

- family scores from Signal Construction
- entry rules configuration from the draft
- stock OHLCV data (for preview)
- WFO scan ranges (for options C, D, E)

## Outputs

- list of entry rules with conditions and sizing
- WFO parameter count contribution
- entry rule preview (which bars would have triggered entries under current parameters)

## Edge Cases

### No entry rules defined

If the user has not added any entry rules:

- the review section should flag this as blocking
- the strategy cannot be sent to backtest

### Overlapping entries

Multiple entries may trigger on the same bar (all conditions satisfied simultaneously):

- all triggered entries execute in order
- total exposure is capped by the risk layer's max position %

### Entry with zero sizing

If an entry rule has 0% sizing:

- the entry is effectively disabled
- the UI should suggest removing it or setting a non-zero size

## Cross-Links

- Family scores are computed by Signal Construction: see [05-signal-construction-layer.md](./05-signal-construction-layer.md)
- Exit rules mirror this structure: see [07-exit-rules-layer.md](./07-exit-rules-layer.md)
- Risk layer caps total exposure: see [08-risk-layer.md](./08-risk-layer.md)
- WFO parameter count feeds the review: see [09-review-and-backtest-handoff.md](./09-review-and-backtest-handoff.md)
- PROM as the WFO objective is from Pardo (2008): see [12-methodology-and-sources.md](./12-methodology-and-sources.md)
