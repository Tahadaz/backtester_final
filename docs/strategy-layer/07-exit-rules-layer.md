# Strategy Layer — Exit Rules Layer

## What

The Exit Rules section defines **when to reduce or close a position** and **how much exposure to release per exit**. It mirrors the structure of entry rules: a list of exits, each with a rule parameter and a sizing parameter, supporting the same 5 configuration options (A–E).

Exit rules are **separate from the Risk layer**. Risk parameters (stop loss, take profit, time stop) act as a global safety net. Exit rules act on indicator scores — they close positions based on strategy logic, not emergency conditions.

## Why

A single exit threshold creates the same rigidity problem as a single entry threshold:

- A trend follower may want to trim when momentum fades, and fully exit when the trend reverses
- A mean reverter may want to take partial profit as RSI normalizes, and close fully when RSI reaches the opposite extreme

Multiple exit levels with graduated exposure reduction enable these strategies naturally.

As with entries, the A-E label is descriptive metadata. Runtime behavior is driven by the actual threshold and sizing field modes on each exit rule.

## Exit Rule Structure

Each exit in the list has:

```ts
type ExitRule = {
  id: string
  label: string                    // e.g., "Exit 1", "Trend Fade"
  rule: RuleParameter              // conditions to trigger
  sizing: SizingParameter          // exposure reduction for this exit
  config_option: "A" | "B" | "C" | "D" | "E"
}
```

### Rule Parameter

Same syntax as entry rules — a condition expression using family scores:

```
trend_score < -1.0 OR momentum_score < -0.5
```

All the same score variables and operators are available.

### Sizing Parameter

The exposure **reduction** for this exit, expressed as a percentage of the current position:

- **Manual**: user sets an exact reduction percentage (e.g., reduce by 50%)
- **Direct WFO sizing**: the reduction itself is optimized as a normal leaf WFO parameter (`reduction_pct`)
- **Kelly from WFO**: the raw Kelly fraction is WFO-derived, then multiplied by a modifier

For `kelly_wfo`, the Phase 1 rule is:

```
final exit reduction = Kelly(from WFO) x modifier
```

The raw Kelly number is always WFO-derived. The modifier is the separate risk dial and may be manual or WFO-optimized.

## The 5 Configuration Options

The options mirror entry rules exactly:

| Option | Rule | Sizing | WFO Params per Exit |
|--------|------|--------|---------------------|
| A | Manual thresholds | Manual % reduction | 0 |
| B | Manual thresholds | Kelly/WFO reduction | 1 |
| C | WFO thresholds | Manual % reduction | N (one per threshold) |
| D | WFO thresholds | Kelly/WFO reduction | N + 1 |
| E | Full WFO (joint) | Full WFO (joint) | Variable |

Fixed-rule direct `wfo` reduction and fixed-rule `kelly_wfo` reduction are Phase 1 runtime features. True Option E remains the later structure-discovery workflow.

**Option E for exits** works the same way as for entries: WFO discovers the optimal number of exit levels, the thresholds for each, and the exposure reduction per level, all jointly optimized. PROM penalizes unnecessary exit levels.

## Relationship Between Entries and Exits

### Partial Exits

Exits can partially close a position. If the total position is 100% of allocation and Exit 1 reduces by 40%, the remaining position is 60%.

```
Full position: 100% of allocation (from entries)
  Exit 1 triggers: reduce by 40% → remaining 60%
  Exit 2 triggers: reduce by 60% of remaining → remaining 24%
  Exit 3 triggers: reduce by 100% of remaining → flat
```

### Exit Reductions Are Relative

Each exit's sizing parameter is a percentage of the **current** position, not the original position. This prevents over-selling:

- If the position has already been partially exited, a "50% reduction" means 50% of what remains
- This ensures the total reduction never exceeds 100%

### Entry-Exit Independence

Entry rules and exit rules are independently configured:

- An entry can trigger while an exit is pending (not typically — conflicting signals usually mean one side dominates)
- The system does not require a 1:1 mapping between entries and exits
- A strategy can have 2 entry levels and 3 exit levels, or vice versa

## Concrete Examples

### Example 1: Trend Following Exits (Option A)

```
Strategy Type: Trend Following

Exit 1 — "Momentum Fade":
  Rule:   momentum_score < 0.0
  Sizing: Reduce by 50%
  
Exit 2 — "Trend Reversal":
  Rule:   trend_score < -1.0 OR momentum_score < -1.0
  Sizing: Reduce by 100% (close remaining)
```

Logic: When momentum fades (MACD histogram turns negative), trim half. When the trend actually reverses, close everything. This implements deterioration-based exit — the position is reduced on weakening conviction, not just on full reversal.

### Example 2: Mean Reversion Exits (Option C)

```
Strategy Type: Mean Reversion

Exit 1 — "Partial Normalization":
  Rule:   oscillation_score > WFO(min=40, max=55, step=5)
  Sizing: Reduce by 50%
  
Exit 2 — "Full Normalization":
  Rule:   oscillation_score > WFO(min=55, max=70, step=5)
  Sizing: Reduce by 100%
```

Logic: As RSI normalizes from oversold, take partial profit. When RSI reaches neutral/overbought, close the rest. WFO optimizes the exact RSI thresholds.

### Example 3: Full WFO Exits (Option E)

```
WFO search space:
  Number of exits: try 2, 3, 4 levels
  Per exit: threshold per score + reduction %
  Objective: maximize PROM (jointly with entry optimization)
```

The optimizer discovers that 2 exit levels work best:
- Level 1: momentum_score < -0.3, reduce by 60%
- Level 2: trend_score < -1.5, reduce by 100%

## Default WFO Exit Threshold Presets by Horizon

Exit thresholds now use the same horizon-scoped default policy as entry thresholds. The meaning is similar, but the economic interpretation is slightly different: entry thresholds answer "when is conviction strong enough to get in?", while exit thresholds answer "when has conviction weakened enough, or normalized enough, to get out?"

### Continuous score thresholds

For deterioration exits (`<` or `<=` on signed conviction scores):

| Horizon | Default range |
|--------|---------------|
| Short | -2.0 to -0.5 step 0.25 |
| Medium | -3.0 to -0.5 step 0.5 |
| Long | -4.0 to -1.0 step 0.5 |

For strength-based exits or closing short positions (`>` or `>=`):

| Horizon | Default range |
|--------|---------------|
| Short | 0.5 to 2.0 step 0.25 |
| Medium | 0.5 to 3.0 step 0.5 |
| Long | 1.0 to 4.0 step 0.5 |

Why these ranges make sense:

- A short-horizon strategy should usually trim or exit as soon as deterioration is visible, because the thesis decays quickly.
- A long-horizon strategy should be more tolerant of small reversals, so its default exit scan stretches further before declaring the thesis broken.
- Using the same signed bands as entries keeps the language of conviction consistent across the page. A `-1.0` exit threshold means a real deterioration in the same score units that the entry logic used to justify the trade.

### Oscillation thresholds

For normalization/profit-taking exits from oversold entries (`>` or `>=`):

| Horizon | Default range |
|--------|---------------|
| Short | 65 to 90 step 5 |
| Medium | 60 to 85 step 5 |
| Long | 55 to 80 step 5 |

For capitulation-style exits or closing short mean-reversion trades (`<` or `<=`):

| Horizon | Default range |
|--------|---------------|
| Short | 10 to 35 step 5 |
| Medium | 15 to 40 step 5 |
| Long | 20 to 45 step 5 |

Why these ranges make sense:

- For long mean-reversion trades, the most common exit question is "how far has RSI normalized?" The upper bands therefore anchor around familiar regions such as 55, 60, 70, and 80.
- Short horizons can wait for sharper snap-backs, so they allow higher normalization levels.
- Long horizons should not require extremely rare oscillator extremes to take profit. Their band relaxes toward the center because longer-period oscillators normalize more slowly and rarely print the most extreme readings.
- A step of `5` matches the natural semantics traders already use for bounded oscillators and avoids the false precision problem described in the WFO methodology.

## Exit vs Risk Layer

The distinction is important:

| Exit Rules | Risk Layer |
|-----------|------------|
| Based on indicator scores | Based on price levels and time |
| Strategy logic (thesis weakening) | Safety net (emergency stop) |
| Partial reductions common | Usually full position close |
| Gradual, conviction-based | Binary, threshold-based |
| Optimizable by WFO | Some parameters WFO-optimizable |

A position may be closed by either mechanism. The risk layer always has priority — if the stop loss is hit, the position closes regardless of what exit rules say.

## Inputs

- family scores from Signal Construction
- exit rules configuration from the draft
- current position state (for reduction calculations)
- WFO scan ranges (for options C, D, E)

## Outputs

- list of exit rules with conditions and reduction sizing
- WFO parameter count contribution
- exit rule preview (which bars would have triggered exits under current parameters)

## Edge Cases

### No exit rules defined

If the user has not added any exit rules:

- the strategy relies entirely on the Risk layer for exits (stop loss, take profit, time stop)
- the review section should warn: "No indicator-based exit rules. Exits depend solely on risk parameters."
- the strategy can still be valid — some traders prefer pure risk-based exits

### All exits trigger simultaneously

If all exit conditions are met on the same bar:

- exits execute in order (Exit 1, then Exit 2, etc.)
- each applies its reduction to the remaining position after the previous exit
- if Exit 1 closes 100%, Exit 2 has nothing to close

### Exit triggers with no open position

If an exit condition is met but there is no open position:

- the exit is ignored (nothing to close)
- this is not an error

## Cross-Links

- Entry rules mirror this structure: see [06-entry-rules-layer.md](./06-entry-rules-layer.md)
- Risk layer provides the safety net: see [08-risk-layer.md](./08-risk-layer.md)
- WFO parameter count feeds the review: see [09-review-and-backtest-handoff.md](./09-review-and-backtest-handoff.md)
- Deterioration-based exit is supported by Kaufman (1995) and Wilder (1978): see [12-methodology-and-sources.md](./12-methodology-and-sources.md)
