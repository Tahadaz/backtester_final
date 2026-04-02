# 09 — API Data Flow and Frontend Contracts

---

## Purpose

WFO is compute-heavy and produces rich, multi-layered results. This document defines the API request/response schemas, per-window detail endpoints, frontend display sections, caching strategy, and progress reporting.

---

## WFO Request Payload

```json
POST /api/backtest/wfo

{
  "strategy_id": "str — reference to saved strategy definition",
  "wfo_config": {
    "start_date": "2012-01-02",
    "end_date": "2024-12-31",
    "test_period_start": "2023-01-02 (optional — auto-computed if omitted)",
    "horizon": "medium",
    "is_oos_ratios": [0.25, 0.30, 0.35],
    "cost_model": {
      "brokerage_bps": 5.0,
      "commission_bps": 3.0,
      "slippage_bps": 2.0,
      "tva_rate": 0.10
    },
    "volume_gate": 10000,
    "cooldown_bars": 3
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `strategy_id` | string | ID of the strategy defined on the strategy page |
| `start_date` | date | WFO analysis start date |
| `end_date` | date | End of available data |
| `test_period_start` | date (optional) | If provided, WFO stops here; remaining data = test period. If omitted, system maximizes WFO windows and reserves remaining data. |
| `horizon` | enum | short / medium / long — determines parameter ranges and window constraints |
| `is_oos_ratios` | float[] | OOS/IS ratios to test (default [0.25, 0.30, 0.35]) |
| `cost_model` | object | Transaction cost components |
| `volume_gate` | int | Minimum daily volume for a stock to be tradeable |
| `cooldown_bars` | int | Minimum bars between position changes |

---

## WFO Results Response

```json
{
  "viable": true,
  "strategy_id": "...",
  "horizon": "medium",

  "winning_config": {
    "is_bars": 2520,
    "oos_bars": 756,
    "is_oos_ratio": 0.30,
    "n_walk_forwards": 10,
    "wfe": 0.62,
    "wfe_threshold": 0.50,
    "robustness_ratio": 0.70
  },

  "windows": [
    {
      "index": 0,
      "is_start_date": "2012-01-02",
      "is_end_date": "2022-01-02",
      "oos_start_date": "2022-01-03",
      "oos_end_date": "2025-01-02",
      "is_prom": 0.0342,
      "is_smoothed_prom": 0.0318,
      "is_winner_params": {"sma_period": 45, "entry_threshold": 35},
      "oos_return": 0.082,
      "oos_profitable": true,
      "oos_n_trades": 12,
      "optimization_profile": {
        "pct_profitable": 0.34,
        "distribution_check": true,
        "shape_check": true,
        "passes": true
      }
    }
  ],

  "final_params": {
    "sma_period": 48,
    "entry_threshold": 32,
    "exit_threshold": -15,
    "stop_loss_pct": 0.08
  },

  "statistical_validation": {
    "monte_carlo": {
      "p_value": 0.003,
      "n_simulations": 10000,
      "actual_final_equity": 1.145,
      "actual_percentile": 95.2,
      "percentile_bands": {
        "p5": 0.92, "p25": 0.98, "p50": 1.02, "p75": 1.08, "p95": 1.14
      },
      "simulated_curves": "[[...10000 equity curves, each as array of floats...]]",
      "actual_curve": "[...equity curve as array of floats...]",
      "significant": true
    },
    "deflated_sharpe": {
      "observed_sharpe": 1.23,
      "benchmark_sharpe": 0.78,
      "dsr_statistic": 2.14,
      "p_value": 0.016,
      "skewness": -0.34,
      "kurtosis": 4.12,
      "n_variants_tested": 1230,
      "significant": true
    },
    "all_passed": true
  },

  "sizing": {
    "n_oos_trades": 85,
    "win_rate": 0.565,
    "avg_win": 3200.0,
    "avg_loss": 2100.0,
    "wl_ratio": 1.524,
    "kelly_fraction": 0.280,
    "half_kelly_fraction": 0.140
  },

  "test_period": {
    "start_date": "2023-07-01",
    "end_date": "2024-12-31",
    "n_bars": 378,
    "total_return": 0.145,
    "cagr": 0.097,
    "sharpe": 1.23,
    "max_drawdown": 0.087,
    "calmar": 1.115,
    "n_trades": 14,
    "win_rate": 0.571,
    "profit_factor": 1.82,
    "equity_curve": [[...dates...], [...values...]],
    "trades": [...]
  },

  "all_configs_tested": [
    {
      "is_bars": 2520,
      "oos_bars": 630,
      "ratio": 0.25,
      "n_walk_forwards": 12,
      "wfe": 0.55
    },
    {
      "is_bars": 2520,
      "oos_bars": 756,
      "ratio": 0.30,
      "n_walk_forwards": 10,
      "wfe": 0.62
    },
    {
      "is_bars": 2520,
      "oos_bars": 882,
      "ratio": 0.35,
      "n_walk_forwards": 8,
      "wfe": 0.58
    }
  ],

  "diagnostics": {
    "total_variants_tested": 1230,
    "total_is_evaluations": 12300,
    "computation_time_seconds": 145.2,
    "failed_profile_windows": [3, 7]
  }
}
```

### Not-Viable Response

When no configuration achieves WFE >= 50%:

```json
{
  "viable": false,
  "strategy_id": "...",
  "best_wfe": 0.34,
  "best_config": { ... },
  "all_configs_tested": [ ... ],
  "diagnostics": {
    "recommendation": "Strategy optimization does not transfer to OOS reliably. Consider simplifying parameter space or trying different indicators.",
    "failed_profile_windows": [1, 3, 5, 7, 9],
    "total_variants_tested": 1230
  }
}
```

---

## Per-Window Detail Endpoint

```json
GET /api/backtest/wfo/{run_id}/window/{window_index}

Response:
{
  "window_index": 3,
  "is_start_date": "...",
  "is_end_date": "...",
  "oos_start_date": "...",
  "oos_end_date": "...",

  "optimization_landscape": {
    "param_values": [5, 6, 7, ..., 40],
    "raw_proms": [0.012, 0.015, ...],
    "smoothed_proms": [0.013, 0.014, ...],
    "winner_index": 23,
    "pct_profitable": 0.34
  },

  "oos_detail": {
    "equity_curve": [[...dates...], [...values...]],
    "trades": [...],
    "metrics": {
      "total_return": 0.082,
      "sharpe": 0.95,
      "max_drawdown": 0.045,
      "n_trades": 12
    }
  }
}
```

This endpoint supports drill-down into individual walk-forward windows. The frontend uses it to render optimization profile charts and per-window equity curves.

---

## Frontend Sections

### Section 1: WFO Results Table

Analogous to Pardo Table 11.1. One row per walk-forward window:

| Window | IS Period | IS PROM | IS Params | OOS Period | OOS Return | OOS Profitable | Profile |
|--------|-----------|---------|-----------|------------|------------|----------------|---------|
| 1 | 2012-2022 | 0.034 | SMA=45 | 2022-2025 | +8.2% | Yes | Pass |
| 2 | 2013-2023 | 0.029 | SMA=48 | 2023-2026 | +5.1% | Yes | Pass |
| ... | | | | | | | |

Summary row: WFE, robustness ratio, total OOS trades.

### Section 2: Optimization Profiles

For each IS window, a chart showing:
- X-axis: parameter values
- Y-axis: PROM (raw and smoothed)
- Highlighted: winner (smoothed PROM maximum)
- Shaded: profitable parameter region
- Annotations: % profitable, distribution check result

For multi-dimensional parameters (RSI, MACD): heatmap with smoothing visualization.

### Section 3: Parameter Evolution Chart

Line chart showing how the optimal parameter drifts across IS windows:

```
Window:  1    2    3    4    5    6    7    8
SMA:    45   48   42   50   48   52   48   48
```

Stable parameters across windows indicate robustness. Large jumps indicate regime sensitivity.

### Section 4: Statistical Validation

Summary panel with three pass/fail metrics:

```
Walk-Forward Efficiency    62%       Pass (>= 50%)
Monte Carlo p-value        0.003    Pass (< 0.05)
Deflated Sharpe Ratio      2.14     Pass (p < 0.05)

Verdict: STATISTICALLY VALIDATED
```

Below the summary: **Monte Carlo equity curve fan chart** (Plotly):
- 10,000 simulated equity curves drawn as semi-transparent gray lines
- Percentile bands (5th, 25th, 50th, 75th, 95th) as shaded regions
- Actual strategy equity curve as bold colored line
- Right margin: histogram of simulated final equity values with actual strategy marked
- Annotation: "Strategy final equity at Xth percentile"

### Section 5: Sizing Summary

```
Kelly Sizing (from OOS trades)
------------------------------
OOS trades:        85
Win rate:          56.5%
Avg win:           3,200 MAD
Avg loss:          2,100 MAD
W/L ratio:         1.52
Kelly fraction:    28.0%
Half-Kelly:        14.0%
```

### Section 6: Test Period Results

Standard backtest display:
- Equity curve
- Key metrics (return, Sharpe, drawdown, Calmar)
- Trade ledger with full detail

---

## Caching and Performance

WFO is compute-heavy. For a strategy with 1,000 parameter combinations tested across 10 walk-forward windows in 3 configurations:

```
Total simulations = 1,000 combos x 10 windows x 3 configs = 30,000 backtests
```

### Caching Strategy

```
Cache key = hash(strategy_definition + wfo_config + data_version)
```

| Level | What's cached | TTL | Invalidation |
|-------|--------------|-----|--------------|
| Full result | Complete WFO response | 24h | Strategy change, new data |
| Per-config | Each (IS, OOS) config result | 24h | Same |
| Per-window | Individual IS optimization results | 7d | Data change only |
| Price data | OHLCV arrays for each stock | Until new data | New upload/update |

### Parallelization Opportunities

```
Level 1: Per-stock parallelism    (each stock in universe runs independently)
Level 2: Per-config parallelism   (each IS/OOS configuration runs independently)
Level 3: Per-window parallelism   (each walk-forward window can run independently)
Level 4: Per-combo vectorization  (parameter combinations within one IS window)
```

Levels 1-3 are embarrassingly parallel. Level 4 benefits from NumPy vectorization.

---

## Progress Reporting

WFO can take minutes to complete. The API uses Server-Sent Events (SSE) for progress updates:

```
GET /api/backtest/wfo/{run_id}/progress

event: progress
data: {"phase": "config_1_of_3", "window": "5_of_10", "pct": 45, "elapsed_s": 34}

event: progress
data: {"phase": "config_1_of_3", "window": "8_of_10", "pct": 72, "elapsed_s": 58}

event: complete
data: {"run_id": "...", "viable": true, "wfe": 0.62}
```

The frontend displays a progress bar with:
- Current configuration being tested (e.g., "Config 2/3: IS=2520, OOS=756")
- Current walk-forward window (e.g., "Window 5/10")
- Overall percentage
- Elapsed time and estimated time remaining

---

## Error Handling

| Error | HTTP Status | Response |
|-------|-------------|----------|
| Strategy not found | 404 | `{"error": "Strategy not found", "strategy_id": "..."}` |
| Insufficient data | 422 | `{"error": "Insufficient data for WFO", "detail": "Need X bars, have Y"}` |
| No feasible configs | 422 | `{"error": "No feasible IS/OOS configurations", "detail": "..."}` |
| Computation timeout | 504 | `{"error": "WFO computation timed out", "elapsed_s": 600}` |
| Invalid parameters | 400 | `{"error": "Invalid WFO config", "detail": "..."}` |
