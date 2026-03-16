# Signal Generation — Optimization Engine

**File:** `core/quant_core/optimize.py` (~2,900 lines)

The optimization engine searches for parameter combinations where signal intent translates into positive economic value after transaction costs. It is **not** a strategy selector — it finds the parameter region where a given signal family works best.

---

## Entry Point

```python
def run_optimization(
    base_spec: EngineSpec,        # Base backtest specification (data config, portfolio config, etc.)
    active_params: List[ParamDef], # Parameters to search over
    cfg: OptimizeConfig,          # Method, n_trials, seed, objective
) -> Tuple[TrialResult, pd.DataFrame, Dict, EngineSpec, pd.DataFrame, OptimizeTiming]:
    """
    Returns:
    - best_result: TrialResult for the winning parameter combination
    - top_df: DataFrame of top-K results
    - best_params: Dict of winning parameters
    - best_spec: EngineSpec with winning params applied
    - ranked_df: Full ranked results DataFrame
    - timing: OptimizeTiming with performance metrics
    """
```

---

## Step-by-Step Flow

### Step 1: Load Market Data (once)

```python
# Estimate warmup bars from the largest possible indicator lookback
warmup = estimate_warmup_bars_from_params(strategy_kind, max_params)

# Load OHLCV with warmup padding
md = load_market_data(base_spec, extra_warmup_bars=warmup)
```

The data is loaded **once** and shared across all trials. The extra warmup bars ensure indicators are valid on the first evaluation bar.

### Step 2: Align to Common Index

```python
# Inner intersection: only timestamps present in ALL symbols
common_idx = intersect_all_symbol_indices(md)

# Extract numpy arrays per symbol (no DataFrames in the hot loop)
close_by_sym = {sym: md[sym]["Close"].values for sym in symbols}
high_by_sym  = {sym: md[sym]["High"].values  for sym in symbols}
low_by_sym   = {sym: md[sym]["Low"].values   for sym in symbols}
vol_by_sym   = {sym: md[sym]["Volume"].values for sym in symbols}
```

### Step 3: Build Indicator Bank (once)

```python
# Adapter declares all indicators needed across the entire parameter grid
bank_request = adapter.required_bank(base_spec, active_params)

# Compute all indicators for all symbols
bank = build_bank(close_by_sym, high_by_sym, low_by_sym, vol_by_sym, bank_request)
```

See [05-indicator-bank.md](./05-indicator-bank.md) for details.

### Step 4: Generate Candidate Parameters

**Grid search:**
```python
def _iter_grid(params: List[ParamDef]) -> Iterator[Dict[str, Any]]:
    """Cartesian product of all parameter ranges."""
    # ParamDef(key="strategy.sma_window", kind="int", domain=(10, 250, 1))
    # → generates {10, 11, 12, ..., 250} for this parameter
    # Cross-product with all other parameters
```

**Random search:**
```python
def _iter_random(params: List[ParamDef], n_trials: int, seed: int) -> Iterator[Dict[str, Any]]:
    """Uniform random sampling from parameter domains."""
    # With deduplication: tracks seen parameter hashes to avoid duplicates
```

### Step 5: Trial Loop

```python
eval_cache: Dict[frozenset, TrialResult] = {}
portfolio_engine = PortfolioEngine(portfolio_config)  # Hoisted outside loop

for candidate_params in candidates:
    # Deduplication check
    cache_key = frozenset(candidate_params.items())
    if cache_key in eval_cache:
        timing.cache_hits += 1
        continue

    # Parameter validation (adapter-specific constraints)
    if not adapter.validate_params(candidate_params):
        continue  # e.g., fast_window >= slow_window → skip

    # Evaluate
    result = _eval_one_trial(
        adapter, symbols, bank, close_by_sym, high_by_sym, low_by_sym, vol_by_sym,
        open_by_sym, candidate_params, base_spec, portfolio_engine
    )

    eval_cache[cache_key] = result
    timing.cache_misses += 1
```

### Step 6: Per-Trial Evaluation (`_eval_one_trial`)

```python
def _eval_one_trial(adapter, symbols, bank, close, high, low, vol, open_px,
                     params, base_spec, portfolio_engine) -> TrialResult:

    # 1. Generate signals (fast numpy path)
    signal_arrays = adapter.make_signal_arrays_fast(
        symbols, bank, close, high, low, vol, params, base_spec
    )
    # signal_arrays = {"ATW": np.array([0, 0, 1, 1, 1, -1, 0, ...]), ...}

    # 2. Run portfolio stats via Numba kernel (per symbol)
    total_pnl = 0.0
    total_trades = 0
    for sym in symbols:
        stats = portfolio_engine.run_stats_only_arrays(
            open_px=open_px[sym],
            close_px=close[sym],
            sig=signal_arrays[sym],
        )
        total_pnl += stats.pnl
        total_trades += stats.n_fills

    # 3. Compute summary metrics
    cagr = compute_cagr(total_pnl, initial_cash, n_bars)
    efficiency = total_pnl / max(1e-10, total_trades * avg_notional) if total_trades > 0 else 0.0

    return TrialResult(pnl=total_pnl, cagr=cagr, n_fills=total_trades, efficiency=efficiency)
```

**Key invariant:** No DataFrame allocations, no plot generation, no BacktestReport construction in the trial loop. Only numpy arrays and Numba-compiled kernels.

### Step 7: Ranking

```python
# Sort by primary objective (PnL or CAGR)
ranked = sorted(all_results, key=lambda r: r.pnl, reverse=True)

# Top-K results get "today's signal" computed
for result in ranked[:top_k]:
    result.latest_signal = _latest_signal_for_params(adapter, bank, close, params)

# Materialize winner: run full BacktestEngine.run() ONCE for the best params
best_spec = apply_params_to_spec(base_spec, ranked[0].params)
winner_report = BacktestEngine(best_spec).run()
```

---

## ParamDef — Parameter Definitions

```python
@dataclass(frozen=True)
class ParamDef:
    key: str        # "strategy.sma_fast_window", "portfolio.cooldown_bars"
    kind: str       # "int", "float", "choice"
    domain: Any     # (lo, hi, step) for int/float, [v1, v2, ...] for choice
    cast: Callable  # Type conversion function
    enabled: bool   # Whether this param is active in the search
```

### Default Parameter Catalog

| Strategy | Parameter | Kind | Domain |
|----------|-----------|------|--------|
| ma_cross | `strategy.sma_fast_window` | int | (5, 60, 1) |
| ma_cross | `strategy.sma_slow_window` | int | (20, 250, 1) |
| sma_price | `strategy.sma_window` | int | (10, 250, 1) |
| rsi | `strategy.rsi_window` | int | (5, 100, 1) |
| rsi | `strategy.rsi_oversold` | float | (10, 40, 10) |
| rsi | `strategy.rsi_overbought` | float | (60, 90, 10) |
| macd | `strategy.fast` | int | (5, 50, 1) |
| macd | `strategy.slow` | int | (20, 200, 1) |
| macd | `strategy.signal` | int | (5, 50, 1) |
| bollinger | `strategy.bb_window` | int | (10, 100, 1) |
| bollinger | `strategy.bb_k` | float | (2.0, 5.0, 0.5) |
| obv | `strategy.obv_span` | int | (5, 200, 1) |
| stoch_vwap | `strategy.k_window` | int | (5, 60, 1) |
| stoch_vwap | `strategy.d_window` | int | (2, 20, 1) |
| stoch_vwap | `strategy.smooth_k` | int | (1, 10, 1) |
| stoch_vwap | `strategy.vwap_window` | int | (5, 100, 1) |
| *all* | `portfolio.cooldown_bars` | int | (0, 30, 1) |
| *all* | `portfolio.buy_pct_cash` | float | (0.25, 1.1, 0.25) |
| *all* | `portfolio.sell_pct_shares` | float | (0.25, 1.1, 0.25) |

---

## OptimizeTiming

```python
@dataclass
class OptimizeTiming:
    load_ms: float           # Market data load time
    bank_ms: float           # Indicator bank build time
    trial_total_ms: float    # Cumulative time across all trials
    n_trials_run: int        # Trials actually evaluated
    avg_trial_ms: float      # Average trial time
    cache_hits: int          # Duplicate params skipped
    cache_misses: int        # Params actually computed
    profile_text: str | None # cProfile output if profiling enabled
```

---

## Optimization Configuration

```python
@dataclass
class OptimizeConfig:
    method: str = "random"     # "grid" or "random"
    n_trials: int = 100        # For random search
    seed: int = 42             # Reproducibility
    objective: str = "pnl"     # Ranking criterion
    top_k: int = 20            # Number of top results to return
```

---

## Anti-Overfitting Measures

1. **Deduplication** — `eval_cache` prevents evaluating identical parameter sets
2. **Parameter validation** — Adapters reject invalid combinations (e.g., fast ≥ slow for MA cross)
3. **Warmup padding** — Indicators are warmed up before the evaluation window starts
4. **Walk-forward validation** — see [07-walk-forward-validation.md](./07-walk-forward-validation.md)
5. **Materialize-winner-only** — Full BacktestReport generated only for the best result, not for every trial

---

## References

- Bergstra, J. & Bengio, Y. (2012). "Random Search for Hyper-Parameter Optimization." *JMLR*, 13, 281–305. — Random search is competitive with grid search
- López de Prado, M. (2018). *AFML*, Chapter 11 — "The Dangers of Backtesting"
