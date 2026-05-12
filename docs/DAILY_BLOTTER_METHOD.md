# Daily Blotter Method

The dashboard's operational output is the daily blotter. It is an advisory trade-prep layer, not an execution engine.

## Timing

- Signals are observed after the latest completed daily bar.
- Edge statistics use open-to-open forward returns: Open(T+1) to Open(T+1+d).
- Tickets are valid for the next open only.
- Entry, stop, and target levels are reference levels for the desk because the app does not ingest live or intraday data.

## Action Mapping

- `long_only` is the default side policy.
- In `long_only`, buy/strong-buy signals can become `BUY`, `HOLD`, or `WATCH`.
- In `long_only`, sell/strong-sell signals become `AVOID` when there is no position, or `EXIT`/`REDUCE` when there is an existing long position.
- In `long_short`, bearish signals can become `SELL_SHORT` only if sizing, edge, liquidity, and entry-zone checks pass.

## Portfolio State

Manual positions are the source of truth for portfolio follow-up. The blotter compares the current position to the model ticket:

- no position + executable long ticket -> `BUY`
- existing long + still bullish -> `HOLD`, `BUY`, or `REDUCE` depending target shares
- existing long + bearish edge -> `EXIT`
- no position + bearish edge in long-only mode -> `AVOID`
- valid edge but outside the entry zone -> `WATCH`

## Evidence Shown Per Row

Each row keeps the research evidence attached to the operational action:

- Action E[R] after costs
- optimized holding period and return method
- proven-edge status
- HRP/Kelly-constrained size
- entry zone, stop, target, and R/R
- liquidity cap and no-trade reasons
- proof link back to the signal page

## Current Limitations

- Holding-period selection is an OOS historical optimum over the horizon band. Treat it as triage, not a guarantee.
- Stops and targets cannot be proactively enforced without live or intraday data.
- Manual fills must be kept current; stale positions will produce stale blotter actions.
- Short-selling requires a real borrow/mandate process and should not be enabled by default.
