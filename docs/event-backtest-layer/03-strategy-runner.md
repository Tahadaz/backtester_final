# Event-Conditioned Strategy Runner — `core/quant_core/research/event_strategy.py`

New flat module, `core/quant_core/research/event_strategy.py`. Turns a canonical events DataFrame (from [02-event-sources.md](02-event-sources.md)) into a tradeable signal, then feeds that signal through two independent, already-existing paths: the UI-facing replay backtest and the WFO parameter sweep.

## `events_to_signal_series`

```python
def events_to_signal_series(
    events: pd.DataFrame,        # symbol, event_date, sign?, event_id — one symbol at a time
    calendar: pd.Index,          # target stock's session calendar (from load_ohlcv_for_symbol)
    hold_days: int = 5,
    sign_mode: str = "from_events",   # "from_events" | "always_long" | "always_short"
    overlap_policy: str = "extend",   # "extend" | "net"
) -> pd.Series:                  # {-1, 0, +1}, indexed like `calendar`
    ...
```

### Entry timing — reuse of the existing open-to-open semantics

These are the verified semantics of the two `analytics.py` helpers, which this module must match exactly rather than reinvent:

- `_next_index_dates(index)` (`services/api/app/routers/analytics.py:741`) — for each calendar date in the index, returns the *next* date in that index (shifted-by-one lookup table; the last date maps to itself).
- `_macro_execution_price_series(stock_prices, *, return_method, close_col, open_col)` (analytics.py:747) — when `return_method ∈ {"open_to_open", "open_to_close"}` and `open_col` is present, the execution price is `stock_prices[open_col].shift(-1)` and the execution date is `_next_index_dates(stock_prices.index)`. Otherwise it falls back to same-day close.

Consequence, stated as the one-line rule implementers must preserve:

> **The position implied by the signal on session `t` is executed at the Open of session `t+1`.**

This is deliberate: a signal computed from information available by the close of session `t` cannot be traded until the next session opens.

How `events_to_signal_series` composes with this:

1. An event whose PIT-available date (after the 18:00 rule and day-0 snap — see [01-methodology.md](01-methodology.md)) is session `d` produces a signal flip **effective on session `d`**.
2. When that series is fed to `_build_macro_backtest_replay` with `return_method="open_to_open"`, the entry executes at `Open[d+1]` — the lag lives entirely in `_macro_execution_price_series`, unchanged.
3. The signal series must therefore **not** embed its own one-session lag. Embedding one would double-lag the entry to `Open[d+2]`. `event_strategy.py` stays a pure signal producer.

### Hold and sign semantics

- The signal holds its value for `hold_days` sessions from the entry session (inclusive), then resets to `0` unless a new event re-triggers it.
- `sign_mode` values:

| `sign_mode` | Behavior |
|---|---|
| `"from_events"` (default) | Use the adapter's `sign` column. Unsigned events (no `sign`) default to `+1` (long-only) — no direction can be assumed without a signed hypothesis. |
| `"always_long"` | Force `+1` regardless of event sign. |
| `"always_short"` | Force `-1`. Used e.g. to test whether geopolitical shocks trade better short independent of the adapter's fixed `sign=-1` convention. |

### Overlap policy

Two events for the same symbol within `hold_days` of each other:

| `overlap_policy` | Behavior | When to use |
|---|---|---|
| `"extend"` (default) | Reset the hold-days countdown from the newer event's entry session; the position stays open continuously. | Matches how a desk would not exit-then-reenter on a fresh confirming print. |
| `"net"` | Position = sign of the sum of currently-active event signs each session. Same-direction events reinforce (still capped at ±1); an opposing pair nets to `0`. | Testing whether conflicting signals should cancel. |

Both policies are per-symbol. Cross-symbol netting is out of scope — each symbol's replay/WFO run is independent, matching how `_build_macro_backtest_replay` already operates per-symbol.

## Replay path — feeds `_build_macro_backtest_replay` unmodified

```python
replay = _build_macro_backtest_replay(
    stock_prices=stock_prices,        # unchanged: load_ohlcv_for_symbol(db, symbol)
    close_col=close_col, open_col=open_col,
    stock_close=stock_close,
    aligned_factors={"EVENT": stock_close},   # see caveat below: an empty dict would make the replay return None
    signal=events_to_signal_series(events_for_symbol, stock_prices.index, hold_days, sign_mode, overlap_policy),
    spec=types.SimpleNamespace(factor_id="EVENT", signal_name=f"event_{event_type}", requires=()),
    forward_returns=None,             # falls back internally to stock_close.pct_change().shift(-1)
    return_method="open_to_open",
    cost_bps=cost_bps,
)
```

`_build_macro_backtest_replay` is consumed **exactly as it exists today** — no code change, no new parameter. What it already handles (verified against the live function body, analytics.py:762):

- Position from signal: `position[signal > signal_threshold] = 1.0`, `position[signal < -signal_threshold] = -1.0` — a `{-1,0,+1}` event signal with the default `signal_threshold=0.0` maps directly to full positions.
- Costs: `cost_rate = cost_bps / 10_000` applied on `|position.diff()|` each change.
- Equity, peak-relative drawdown, and the `trade_ledger` (`ACHAT`/`VENTE` rows with `prix_execution`, `equity`, `cout`, `execution_date` from `_macro_execution_price_series`).

Two adaptation notes for the caller:

1. **`spec` stand-in**: the function only touches `spec.factor_id`, `spec.signal_name`, `spec.requires`. Event strategies pass a lightweight `types.SimpleNamespace` — the exact pattern already used in `services/api/tests/test_macro_factor_replay.py` — instead of a real `FactorSignalSpec`.
2. **Caveat — `aligned_factors={}` returns `None`**: the function's first statement is `primary_factor = aligned_factors.get(spec.factor_id)` → `return None` when missing. An event strategy has no macro factor series, so the caller must pass a harmless primary "factor": use the stock's own close (`aligned_factors={"EVENT": stock_close}` with `spec.factor_id="EVENT"`). `factor_close` then charts as the stock itself and `factor_close_by_id` stays empty (`requires=()`); the `/sentiment-events` frontend treats the factor overlay as absent for event replays.

This replay is the backtest the `/sentiment-events` UI's "Études d'événements" panel renders (see [`../alt-data-foundation/03-api-ui.md`](../alt-data-foundation/03-api-ui.md)).

## WFO path — event-conditioned parameter sweep

The verified WFO entry point (`core/quant_core/wfo/engine.py`, re-exported from `core/quant_core/wfo/__init__.py`):

```python
run_wfo_engine(
    *,
    data_length: int,
    config: WalkForwardConfig,                 # train_bars, oos_bars, step_bars=None, min_walk_forwards=5
    evaluate_window: Callable[[WalkForwardWindow], WindowScoreResult],
    max_lookback: int = 0,
) -> EngineResult                              # windows, wfe, robustness_ratio, single_window_dominance
```

Key properties the wrapper relies on:

- The engine is intentionally generic — it does **not** know about `FactorSignalSpec` or any specific signal type.
- The caller supplies an `evaluate_window` closure that, given a `WalkForwardWindow` (`train_start/end`, `oos_start/end` bar indices), returns a `WindowScoreResult` whose `raw_scores` / `is_returns` / `oos_returns` / `oos_sharpes` are **dicts keyed by an arbitrary variant id**.
- Existing precedent for this exact pattern: `core/quant_core/signal_engine/wfo_signal.py::evaluate_window` (~line 535) — builds a `pool` of TA variants once, then loops `for i, variant in enumerate(pool)` computing IS/OOS return and Sharpe per pool index.

The event-strategy WFO wrapper (`event_strategy.py::run_event_wfo`) follows the same shape, not a `FactorSignalSpec`-native integration (the original plan sketch's "wrap as a FactorSignalSpec-compatible signal fn" overstates how automatic this is — there is no generic FactorSignalSpec→WFO adapter to plug into; every WFO caller writes its own `evaluate_window`):

1. Build the parameter pool as the cross product of `ParameterRange(min_value, max_value, step).values()` for `hold_days` (e.g. `ParameterRange(1, 15, 1)`) and `signal_threshold` (e.g. `ParameterRange(0.0, 0.5, 0.25)` — kept for interface symmetry with `_build_macro_backtest_replay`'s `signal_threshold`, though with a `{-1,0,+1}` event signal it is typically left at 0). Each `(hold_days, threshold)` pair is one pool entry, indexed `0..len(pool)-1`.
2. `evaluate_window(window)`: for each pool entry, slice `events_to_signal_series(...)` and the symbol's close/forward-return arrays to `window.train_start:window.train_end` (IS) and `window.oos_start:window.oos_end` (OOS), compute the position-based strategy return (same position/cost logic as the replay path, reimplemented over arrays rather than calling `_build_macro_backtest_replay` per window for performance — `_build_macro_backtest_replay` is the UI-facing single-run path, not the per-window-per-variant WFO inner loop), derive IS return, OOS return, and OOS Sharpe, and populate `raw_scores`/`is_returns`/`oos_returns`/`oos_sharpes` keyed by pool index.
3. `WalkForwardConfig(train_bars, oos_bars, step_bars=None, min_walk_forwards=5)` — same dataclass fields as every other WFO caller in the repo (`core/quant_core/wfo/config.py`); no event-specific fields needed since the event signal is just another bar-indexed series once `events_to_signal_series` has materialized it over the calendar.
4. `run_wfo_engine(data_length=len(calendar), config=config, evaluate_window=evaluate_window)` returns `EngineResult` (`windows`, `wfe`, `robustness_ratio`, `single_window_dominance`) exactly as for TA/factor WFO runs — full reuse of the existing promotion-adjacent machinery (`compute_wfe`, `compute_robustness_ratio`, `compute_single_window_dominance`), nothing new to build there.
5. The winning `(hold_days, threshold)` per window and the aggregate OOS Sharpe/WFE feed the **event-conditioned WFO OOS Sharpe > 0 net of 25 bps/side** promotion gate in [04-multiple-testing.md](04-multiple-testing.md).

## Tests

`core/tests/test_event_strategy.py`, mirroring the fixture style of `services/api/tests/test_macro_factor_replay.py` (synthetic `pd.bdate_range` OHLCV frame, hand-built events DataFrame, `types.SimpleNamespace` spec stand-in, asserting on `trade_ledger` side sequencing, `dates[0]`, `equity[-1]`, `drawdown[-1]`). Additional cases specific to this module: overlap-policy `"extend"` vs `"net"` divergence on a synthetic two-event-within-hold-window fixture; entry-lag assertion (position on event day `d` only affects `equity` starting from execution at `Open[d+1]`, verified against a synthetic price jump placed exactly at `Open[d+1]` so a correct implementation captures it and an off-by-one implementation would not); WFO pool-index scoring on a 2×2 `(hold_days, threshold)` grid with a synthetic series where one combination is known to dominate.
