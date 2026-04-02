# Strategy Layer — Strategy Type Layer

## What

The Strategy Type section is the first configuration choice within each per-stock tab. It sets a **label** — Trend Following or Mean Reversion — that organizes the rest of the UI and provides intuitive guidance for indicator roles.

The strategy type does **not** assign hard-coded roles to indicators. It does **not** change the available indicator families. It does **not** alter scoring formulas. It is a structural label that helps the user think about their approach.

## Why

The same four indicator families (Tendance, Momentum, Oscillation, Volume) can serve fundamentally different trading philosophies:

- A **trend follower** buys when indicators confirm a directional move and exits when that move weakens.
- A **mean reverter** buys when indicators suggest an extreme that is likely to snap back.

Without this label, the user must mentally track which philosophy they are applying. The label makes the intent explicit, which matters for:

- UI organization (entry/exit rule templates, default suggestions)
- Review clarity (the reviewer knows what logic the strategy is trying to implement)
- Team communication (other operators can see the strategy intent at a glance)

## Two Strategy Types

### Trend Following

**Core thesis**: a detected trend will continue. Enter in the direction of the trend; exit when the trend weakens.

The intuitive indicator roles in a trend-following context:

| Family | Intuitive Role | What it provides |
|--------|---------------|-----------------|
| **Tendance** (SMA) | Direction | Is price above or below the moving average? Identifies the trend. |
| **Momentum** (MACD) | Momentum confirmation | Is the trend accelerating or decelerating? Confirms strength. |
| **Oscillation** (RSI) | Overextension filter | Has price stretched too far in the trend direction? Warns of potential pullback. |
| **Volume** (OBV) | Volume confirmation | Does volume support the price move? Validates participation. |

**Typical trend-following logic:**
- Enter when `trend_score > X AND momentum_score > Y`
- Filter: skip entry if `rsi_score > Z` (overextended)
- Exit when `trend_score < A OR momentum_score < B`

### Mean Reversion

**Core thesis**: an extreme indicator reading will revert to the mean. Enter against the extreme; exit when the indicator normalizes.

The intuitive indicator roles in a mean-reversion context:

| Family | Intuitive Role | What it provides |
|--------|---------------|-----------------|
| **Oscillation** (RSI) | Primary signal | Has price reached an oversold/overbought extreme? The main entry trigger. |
| **Tendance** (SMA) | Trend filter | Is there a strong trend that might prevent reversion? Safety check. |
| **Momentum** (MACD) | Momentum context | Is momentum slowing? Supports the reversion thesis. |
| **Volume** (OBV) | Confirmation | Does volume support the reversal? Validates the setup. |

**Typical mean-reversion logic:**
- Enter when `rsi_score < X` (oversold) AND `trend_score > Y` (not in a crashing trend)
- Exit when `rsi_score > Z` (normalized)

## Important: Roles Are Guidance, Not Hard-Coded

The roles described above are **descriptive guidance** — they help the user think about which conditions to set up. They are **not** enforced by the system.

The entry/exit rules (see [06-entry-rules-layer.md](./06-entry-rules-layer.md) and [07-exit-rules-layer.md](./07-exit-rules-layer.md)) encode the actual strategy logic. A user can select "Trend Following" and still use RSI as a primary entry signal if they choose. The label organizes intent; the rules encode behavior.

What the strategy type label **does** affect:

- Default entry/exit rule templates suggested by the UI
- Ordering and emphasis of indicator families in the Signal Construction section
- Language used in the Review summary ("trend-following strategy on IAM" vs "mean-reversion strategy on IAM")

What the strategy type label **does NOT** affect:

- Available indicator families (all four are always available)
- Scoring formulas (same formulas regardless of type)
- WFO optimization (the optimizer does not know or care about the label)

## Same Indicators, Different Strategies

This is a key architectural insight: the four indicator families are **tools**, not strategies. A hammer can build a house or break a wall. Similarly:

- SMA detects trend direction. A trend follower trades *with* it; a mean reverter uses it as a *filter against* getting caught in a strong trend.
- RSI detects extreme readings. A trend follower uses it to *avoid* entering at extremes; a mean reverter uses it to *seek* extremes as entry points.
- MACD detects momentum. Both types use it — a trend follower wants strong momentum; a mean reverter wants fading momentum.
- OBV detects volume flow. Both types use it for confirmation — but what they are confirming differs.

The scoring formulas remain identical. The interpretation happens in the entry/exit rules, not in the indicator calculations.

## UI Behavior

### Collapsed summary

Shows:
- Strategy type label ("Suivi de Tendance" or "Retour a la Moyenne")
- One-line description of the approach

### Expanded body

Shows:
- Type selector (two options)
- Indicator role guidance table (contextual to the selected type)
- Brief explanation of typical entry/exit logic for this type
- "This label organizes your strategy intent. The actual trading logic is defined in Entry Rules and Exit Rules."

## Inputs

- user selection (one of two types)

## Outputs

- `strategy_type: "trend_following" | "mean_reversion"`
- contextual guidance for downstream sections

## Edge Cases

### Type changed after rules are configured

If the user changes the strategy type after already configuring entry/exit rules:

- the existing rules are **not** deleted
- a warning is shown: "Entry/exit rules were configured for [old type]. Review them to ensure they match your new intent."
- the user can choose to reset rules to the new type's defaults or keep existing rules

## Cross-Links

- Signal Construction uses the type to suggest indicator ordering: see [05-signal-construction-layer.md](./05-signal-construction-layer.md)
- Entry Rules use the type for default templates: see [06-entry-rules-layer.md](./06-entry-rules-layer.md)
- Exit Rules use the type for default templates: see [07-exit-rules-layer.md](./07-exit-rules-layer.md)
- The indicator families themselves are described in [../signal-generation/00-INDEX.md](../signal-generation/00-INDEX.md)
