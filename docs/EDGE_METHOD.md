# Edge Method

This document defines the Edge payload used by the dashboard, signal proof page, and portfolio selection flow.

## Return Semantics

Edge separates two return concepts:

- `Stock E[R]`: raw forward return of the stock over the selected horizon.
- `Action E[R]`: return from the signal action after applying direction.

For buy buckets, action return equals stock return before costs:

```text
buy / strong_buy -> long action
Action return = stock forward return
```

For sell buckets, action return is bearish/short-style research return:

```text
sell / strong_sell -> short action
Action return = -1 * stock forward return
```

So a sell signal with positive `Action E[R]` means the stock historically fell after that signal. It does not mean the stock had positive forward return.

`expected_return_gross` and `expected_return_net` remain backward-compatible aliases for action expected return. New UI should prefer `action_expected_return_*` and `stock_expected_return`.

## Entry, Exit, And Holding Period

Dashboard Edge uses realistic next-session entry semantics:

```text
Signal observed after close T
Entry reference = Open(T+1)
Exit reference = Open(T+1+d)
Return method = open_to_open
```

The dashboard does not use a fixed `d` by default. It selects the best net action expected return inside the horizon band:

- weekly: `d = 1..5`
- monthly: `d = 6..21`
- quarterly: `d = 22..63`

The selected day count is returned as `fwd_horizon_bars`. The selection metric is `max_net_action_expected_return`. Ties prefer higher hit rate, then shorter holding period.

This Edge metric is still a fixed-holding-period study. It is not the same as a trade ledger that exits when a later neutral/sell/buy signal appears.
Because `d` is selected from a candidate band, treat it as an OOS historical optimum for triage; it is not a guarantee that the same holding period will remain optimal in the next regime.

## Recency And Regime Freshness

Edge does not treat all available history as equally relevant. The proof sample is capped by horizon, then a stricter freshness slice checks whether the latest regime still agrees with the historical estimate:

| Horizon | Proof max age | Freshness slice |
|---|---:|---:|
| weekly | 1 year | 3 months |
| monthly | 2 years | 6 months |
| quarterly | 3 years | 1 year |

The proof cutoff is anchored to the latest available OOS/proof date, not to the latest occurrence of the current bucket. This prevents an old bucket from passing by defining its own stale sample.

The primary Edge proof targets the most recent 60 same-bucket observations and every Edge proof/evidence sample has a hard maximum of 100 observations. When more than 100 observations are available, the newest 100 are used.

Freshness is not a standalone statistical proof. It is a regime-confirmation gate. A proven row requires at least 10 same-bucket observations in the freshness slice, positive recent action expectancy, and recent directional hit rate of at least 50%.

Methodological basis:

- Adaptive market behavior means edges can decay as market structure and competition change (Lo, 2004).
- Estimation windows under breaks require a bias/variance tradeoff rather than a universal full-history rule (Pesaran and Timmermann, 2007).
- Daily overlapping forward returns are dependence-heavy, so the main proof still uses the existing Wilson, Monte Carlo, label-shuffle, and bootstrap machinery.

## Cost Handling

Gross action return excludes trading costs. Net action return subtracts a round-trip cost:

```text
net action return = gross action return - 2 * cost_bps_per_side
```

The default cost is configured by `EDGE_COST_BPS_PER_SIDE`.

Execution and cost assumptions:

- 33 bps/side is the desk fee schedule.
- Execution is assumed at the opening auction, so no spread is crossed.
- Market impact is bounded by the blotter's ADV participation cap.
- These assumptions must be validated against live fills.

## Proven Edge Gates

A row is marked proven only when all gates pass:

- enough OOS observations: `n >= N_MIN`
- directional Wilson lower bound above 50%
- Monte Carlo luck test p-value below threshold
- label-shuffle p-value below threshold
- freshness gate confirms the latest regime
- positive action expected return after the selected cost mode

Current thresholds live in `core/quant_core/research/edge.py`.

## Dashboard Interpretation

Dashboard labels must use `Action E[R]`, not vague `E[R]`.

For decision review:

- Buy rows are long candidates.
- Sell rows are bearish/short research candidates.
- Whether a bearish candidate is executable depends on desk and market rules.
- The signal page and backtest page must preserve the side policy used for proof.

## Dashboard Portfolio Ticket

The dashboard selected basket calls `POST /api/dashboard/portfolio-ticket`.

Request inputs:

- selected symbols
- horizon and Edge source
- side policy: `long_only` or `long_short` (`long_only` is the default for the Moroccan cash-equity blotter)
- total capital, cash buffer, max position, max sector, and Kelly shrink

Sizing flow:

1. Edge decides direction and whether the signal is proven.
2. Support/resistance plus ATR builds the next-session entry zone, stop, and target.
3. HRP creates the base basket weights from recent close history.
4. Kelly shrink caps each symbol weight from the proven action expectancy.
5. Position, sector, cash, and liquidity caps produce final shares.

The ticket is for the next session open. `entry_reference_price_type=last_close_proxy` means the displayed entry price is a reference from the latest close, not a guaranteed fill. The execution condition is `execute_next_open_only_if_open_remains_in_entry_zone`.

## Cache Versioning

The Edge cache key includes `METHODOLOGY_VERSION`. Any change to Edge formula, payload shape, or proven-edge gates must bump this version and warm the cache after deployment.
