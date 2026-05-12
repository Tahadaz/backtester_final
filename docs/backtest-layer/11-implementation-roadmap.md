# 10 — Implementation Roadmap

---

## Dependencies

The backtest layer (Phase 3) depends on:

| Dependency | Phase | What it provides |
|-----------|-------|------------------|
| Strategy page redesign | Phase 2 | Strategy definition with WFO-flagged parameters, entry/exit rules (Options A-E), risk parameters, scan intervals |
| Indicator explorer | Phase 1 | Indicator types and continuous scoring functions used in strategy rules |
| Signal engine | Existing | `compute_signal_array`, indicator families, horizon definitions |
| Data layer | Existing | OHLCV data, stock universe, market calendar |
| Cost model | Existing | Brokerage, commission, slippage, TVA configuration |

**Critical dependency:** The strategy page must provide a structured definition of which parameters are WFO-flagged, with their scan ranges and steps. Without this, the WFO engine has nothing to optimize.

---

## Implementation Order

### Stage 1: Core WFO Engine

**Scope:** The rolling walk-forward framework without indicator-specific logic.

```
Files:
  core/quant_core/wfo/engine.py         — main WFO orchestrator
  core/quant_core/wfo/config.py         — configuration enumeration
  core/quant_core/wfo/window.py         — IS/OOS window management
  core/tests/test_wfo_engine.py         — unit tests

Deliverables:
  - Enumerate feasible (IS, OOS) configurations given data length and constraints
  - Roll IS+OOS windows through data
  - IS window: accept a scoring function, return ranked parameter sets
  - OOS window: simulate IS winner, return metrics
  - Configuration selection by WFE
```

**Verification:**
- Unit test: given synthetic data with known patterns, WFO finds the correct parameter
- Unit test: IS window sizing respects DF constraint (IS >= 10 x max_lookback)
- Unit test: OOS windows do not overlap

### Stage 2: PROM Computation

**Scope:** Implement PROM as the objective function.

```
Files:
  core/quant_core/wfo/prom.py           — PROM formula
  core/tests/test_prom.py               — unit tests

Deliverables:
  - compute_prom(trades, capital) -> float
  - Edge case handling (no trades, all wins, all losses, 1 trade)
  - Cost-adjusted trade P&L computation
```

**Verification:**
- Unit test: PROM with known inputs matches hand-calculated values
- Unit test: 1 winning trade -> PROM = 0
- Unit test: PROM penalizes small samples (9 trades scored lower than 100 trades with same ratios)

### Stage 3: Neighbor-Averaging

**Scope:** Parameter smoothing for 1D, 2D, and 3D families.

```
Files:
  core/quant_core/wfo/neighbor_avg.py   — smoothing functions
  core/tests/test_neighbor_avg.py       — unit tests

Deliverables:
  - neighbor_average_1d(prom_dict, k=1) -> smoothed_dict
  - neighbor_average_nd(prom_dict, axes, k=1) -> smoothed_dict
  - Boundary handling (edge parameters have fewer neighbors)
```

**Verification:**
- Unit test: 1D smoothing with known spike should select plateau center
- Unit test: boundary parameters are smoothed with available neighbors only
- Unit test: 2D smoothing (RSI) averages along both axes

### Stage 4: Optimization Profile + WFE Validation

**Scope:** IS window quality checks and WFE computation.

```
Files:
  core/quant_core/wfo/profile.py        — optimization profile checks
  core/quant_core/wfo/wfe.py            — WFE computation
  core/tests/test_profile.py            — unit tests
  core/tests/test_wfe.py                — unit tests

Deliverables:
  - check_optimization_profile(proms) -> ProfileResult
  - compute_wfe(windows) -> float
  - Not-viable detection and diagnostic generation
  - Robustness ratio computation
```

**Verification:**
- Unit test: profile rejects window with < 5% profitable
- Unit test: profile rejects window with outlier winner
- Unit test: WFE computation matches hand-calculated values
- Integration test: full WFO pipeline on synthetic data produces expected WFE

### Stage 5: Option E Integration

**Scope:** Auto-discovery of entry/exit level count.

```
Files:
  core/quant_core/wfo/option_e.py       — level count search
  core/tests/test_option_e.py           — unit tests

Deliverables:
  - Search over level_count in [2, 3, 4]
  - Joint optimization with indicator parameters
  - Ordering constraints (increasing thresholds, non-decreasing exposures)
  - PROM-based level count selection
```

**Verification:**
- Unit test: with synthetic data where 2 levels is optimal, Option E selects 2
- Unit test: ordering constraints are enforced
- Unit test: parameter count warnings trigger at correct thresholds

### Stage 6: Sizing from OOS

**Scope:** Kelly criterion from concatenated OOS trades.

```
Files:
  core/quant_core/wfo/sizing.py         — Kelly computation
  core/tests/test_sizing_wfo.py         — unit tests

Deliverables:
  - collect_oos_trades(winning_config) -> list[Trade]
  - compute_trade_stats(trades) -> TradeStats
  - compute_kelly_fraction(stats) -> KellyResult
  - Half-Kelly display
  - Small sample warning
```

**Verification:**
- Unit test: Kelly with known inputs matches hand-calculated values
- Unit test: warning triggers when n_trades < 30
- Unit test: negative Kelly returns fraction = 0

### Stage 7: Test Period

**Scope:** Run optimized strategy on held-out data.

```
Files:
  core/quant_core/wfo/test_period.py    — test period execution
  core/tests/test_test_period.py        — unit tests

Deliverables:
  - partition_data(data, wfo_end, total_length) -> test_data
  - run_test_period(test_data, final_params, kelly, cost_model) -> TestResult
  - Short test period warning
  - No test period handling
```

**Verification:**
- Unit test: test period data has no overlap with WFO data
- Unit test: short period warning triggers at < 126 bars
- Integration test: full pipeline end-to-end on synthetic data

### Stage 8: API and Frontend

**Scope:** REST endpoints, SSE progress, frontend components.

```
Files:
  services/api/app/routers/backtest_wfo.py     — API endpoints
  services/api/app/schemas/backtest_wfo.py     — Pydantic schemas
  frontend/components/backtest/wfo-results.tsx
  frontend/components/backtest/optimization-profile.tsx
  frontend/components/backtest/parameter-evolution.tsx
  frontend/components/backtest/sizing-summary.tsx
  frontend/components/backtest/test-period-results.tsx
  frontend/hooks/use-wfo.ts

Deliverables:
  - POST /api/backtest/wfo — submit WFO analysis
  - GET /api/backtest/wfo/{run_id} — get results
  - GET /api/backtest/wfo/{run_id}/window/{idx} — per-window detail
  - GET /api/backtest/wfo/{run_id}/progress — SSE progress stream
  - Frontend: WFO results table, optimization profiles, parameter evolution, sizing, test period
```

**Verification:**
- API integration test: submit WFO, poll progress, retrieve results
- Frontend: manual testing with real Moroccan stock data
- End-to-end: strategy definition -> WFO -> results display

---

## Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| WFO produces correct WFE | Unit tests with synthetic data where true WFE is known |
| PROM matches Pardo's formula | Hand-calculated test cases |
| Neighbor-averaging selects plateaus | Synthetic landscapes with known structure |
| Optimization profile rejects degenerate windows | Edge case tests |
| Kelly sizing matches formula | Known-input tests |
| Test period is fully held-out | Verify no data overlap via index assertions |
| API returns structured results | Schema validation tests |
| Progress reporting works | SSE integration test |
| Not-viable strategies are flagged | Synthetic overfitted strategy test |
| Parameter count warnings trigger | Threshold tests |

---

## Estimated Timeline

| Stage | Effort | Cumulative |
|-------|--------|------------|
| 1. Core WFO engine | 1 week | 1 week |
| 2. PROM | 2 days | ~1.5 weeks |
| 3. Neighbor-averaging | 2 days | ~2 weeks |
| 4. Profile + WFE | 3 days | ~2.5 weeks |
| 5. Option E | 3 days | ~3 weeks |
| 6. Sizing | 1 day | ~3 weeks |
| 7. Test period | 1 day | ~3.5 weeks |
| 8. API + Frontend | 1 week | ~4.5 weeks |

Total estimate: approximately 4-5 weeks of focused development, assuming Phase 2 (strategy page) is complete.
