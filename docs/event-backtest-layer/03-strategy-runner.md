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

**Entry timing** — matches the existing open-to-open execution semantics in `analytics.py`, not a new convention:

- `_next_index_dates(index)` (analytics.py:741) returns, for each calendar date, the *next* date in the index (shifted-by-one lookup table).
- `_macro_execution_price_series(stock_prices, return_method, close_col, open_col)` (analytics.py:747): when `return_method` is `open_to_open`/`open_to_close`, execution happens at `stock_prices[open_col].shift(-1)` on `_next_index_dates(stock_prices.index)` — i.e., **the position taken on session t is executed at the Open of session t+1**, not at t's own close or open. This is deliberate: a signal computed from information available by the close of session t cannot be traded until the next session opens.
- `events_to_signal_series` reuses this exact semantics for event entries: an event whose PIT-available/day-0-snapped date is session `d` produces a signal flip **effective on session `d`**, which — when the resulting series is later run through `_build_macro_backtest_replay` with `return_method="open_to_open"` — is executed at the Open of session `d+1`. The signal series itself does not embed the one-session execution lag; that lag lives entirely in `_macro_execution_price_series`, unchanged. This keeps `event_strategy.py` a pure signal producer and avoids double-lagging.
- The signal holds for `hold_days` sessions from the entry session (inclusive), then resets to 0 unless a new event re-triggers it.
- `sign_mode="from_events"` uses the adapter's `sign` column (unsigned events default the position to `+1`, i.e. long-only, since a mean-reversion/momentum direction cannot be assumed without a signed hypothesis); `"always_long"`/`"always_short"` override for research sweeps that want to test a fixed direction against a known-unsigned event type (e.g. testing whether geopolitical shocks are better traded short regardless of the adapter's fixed `sign=-1` risk-off convention).
- **Overlap policy** (two events for the same symbol within `hold_days` of each other): `"extend"` (default) resets the hold-days countdown to `hold_days` from the newer event's entry session, keeping the position open continuously rather than flattening between two events of the same type — mirrors how a systematic desk would not exit-then-immediately-reenter on a fresh confirming print. `"net"` computes the position as the sign of the sum of currently-active event signs at each session (so two same-direction events reinforce toward `+1`/`-1` unchanged, but an opposing pair can net to `0`) — this is the configuration to use when testing whether conflicting signals should cancel out. Both policies are per-symbol; cross-symbol netting is out of scope (each symbol's replay/WFO run is independent, matching how `_build_macro_backtest_replay` already operates per-symbol).

## Replay path — feeds `_build_macro_backtest_replay` unmodified

```python
replay = _build_macro_backtest_replay(
    stock_prices=stock_prices,        # unchanged: load_ohlcv_for_symbol(db, symbol)
    close_col=close_col, open_col=open_col,
    stock_close=stock_close,
    aligned_factors={},               # event strategies have no macro-factor overlay; empty dict is valid
    signal=events_to_signal_series(events_for_symbol, stock_prices.index, hold_days, sign_mode, overlap_policy),
    spec=types.SimpleNamespace(factor_id="EVENT", signal_name=f"event_{event_type}", requires=()),
    forward_returns=None,             # falls back internally to stock_close.pct_change().shift(-1)
    return_method="open_to_open",
    cost_bps=cost_bps,
)
```

`_build_macro_backtest_replay` is consumed **exactly as it exists today** — no code change, no new parameter. It already handles: position sizing from the signal via `signal_threshold` (`position[signal > threshold] = 1.0`, etc. — a `{-1,0,+1}` signal with the default `signal_threshold=0.0` maps directly to a full position), cost application on each position change (`cost_bps`), equity compounding, drawdown, and the `trade_ledger` (`ACHAT`/`VENTE` rows with `prix_execution`, `equity`, `cout`). The `spec` argument only needs `factor_id`/`signal_name`/`requires` — event strategies pass a lightweight stand-in (`types.SimpleNamespace`, matching the pattern already used in `services/api/tests/test_macro_factor_replay.py`) instead of a real `FactorSignalSpec`, since there is no macro factor series to chart alongside the stock in `factor_close`/`factor_close_by_id` (those come back empty/absent, which the frontend must treat as optional — event-study replays have no secondary factor overlay to plot). This is the backtest the `/sentiment-events` UI's "Études d'événements" panel renders (see [`../alt-data-foundation/03-api-ui.md`](../alt-data-foundation/03-api-ui.md)).

## WFO path — event-conditioned parameter sweep

`run_wfo_engine` (`core/quant_core/wfo/engine.py`) is intentionally generic: `run_wfo_engine(*, data_length, config: WalkForwardConfig, evaluate_window: Callable[[WalkForwardWindow], WindowScoreResult], max_lookback=0) -> EngineResult`. It does **not** know about `FactorSignalSpec` or any specific signal type — the caller supplies an `evaluate_window` closure that, given a window (`train_start/end`, `oos_start/end` bar indices), returns a `WindowScoreResult` with `raw_scores`/`is_returns`/`oos_returns`/`oos_sharpes` **dicts keyed by an arbitrary "variant" id**. The existing precedent for this pattern is `core/quant_core/signal_engine/wfo_signal.py`'s `evaluate_window` (around line 535): it builds a `pool` of TA variants once, then inside `evaluate_window` loops `for i, variant in enumerate(pool)` computing IS/OOS return and Sharpe per variant index and populating the four dicts keyed by `i`.

The event-strategy WFO wrapper (`event_strategy.py::run_event_wfo`) follows the same shape, not a `FactorSignalSpec`-native integration (the original plan sketch's "wrap as a FactorSignalSpec-compatible signal fn" overstates how automatic this is — there is no generic FactorSignalSpec→WFO adapter to plug into; every WFO caller writes its own `evaluate_window`):

1. Build the parameter pool as the cross product of `ParameterRange(min_value, max_value, step).values()` for `hold_days` (e.g. `ParameterRange(1, 15, 1)`) and `signal_threshold` (e.g. `ParameterRange(0.0, 0.5, 0.25)` — kept for interface symmetry with `_build_macro_backtest_replay`'s `signal_threshold`, though with a `{-1,0,+1}` event signal it is typically left at 0). Each `(hold_days, threshold)` pair is one pool entry, indexed `0..len(pool)-1`.
2. `evaluate_window(window)`: for each pool entry, slice `events_to_signal_series(...)` and the symbol's close/forward-return arrays to `window.train_start:window.train_end` (IS) and `window.oos_start:window.oos_end` (OOS), compute the position-based strategy return (same position/cost logic as the replay path, reimplemented over arrays rather than calling `_build_macro_backtest_replay` per window for performance — `_build_macro_backtest_replay` is the UI-facing single-run path, not the per-window-per-variant WFO inner loop), derive IS return, OOS return, and OOS Sharpe, and populate `raw_scores`/`is_returns`/`oos_returns`/`oos_sharpes` keyed by pool index.
3. `WalkForwardConfig(train_bars, oos_bars, step_bars=None, min_walk_forwards=5)` — same dataclass fields as every other WFO caller in the repo (`core/quant_core/wfo/config.py`); no event-specific fields needed since the event signal is just another bar-indexed series once `events_to_signal_series` has materialized it over the calendar.
4. `run_wfo_engine(data_length=len(calendar), config=config, evaluate_window=evaluate_window)` returns `EngineResult` (`windows`, `wfe`, `robustness_ratio`, `single_window_dominance`) exactly as for TA/factor WFO runs — full reuse of the existing promotion-adjacent machinery (`compute_wfe`, `compute_robustness_ratio`, `compute_single_window_dominance`), nothing new to build there.
5. The winning `(hold_days, threshold)` per window and the aggregate OOS Sharpe/WFE feed the **event-conditioned WFO OOS Sharpe > 0 net of 25 bps/side** promotion gate in [04-multiple-testing.md](04-multiple-testing.md).

## Tests

`core/tests/test_event_strategy.py`, mirroring the fixture style of `services/api/tests/test_macro_factor_replay.py` (synthetic `pd.bdate_range` OHLCV frame, hand-built events DataFrame, `types.SimpleNamespace` spec stand-in, asserting on `trade_ledger` side sequencing, `dates[0]`, `equity[-1]`, `drawdown[-1]`). Additional cases specific to this module: overlap-policy `"extend"` vs `"net"` divergence on a synthetic two-event-within-hold-window fixture; entry-lag assertion (position on event day `d` only affects `equity` starting from execution at `Open[d+1]`, verified against a synthetic price jump placed exactly at `Open[d+1]` so a correct implementation captures it and an off-by-one implementation would not); WFO pool-index scoring on a 2×2 `(hold_days, threshold)` grid with a synthetic series where one combination is known to dominate.
