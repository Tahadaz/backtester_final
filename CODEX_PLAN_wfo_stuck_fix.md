# Fix: Normalize WFO result contract + unblock stuck run

## Problem

The WFO result has a structural issue: full window `detail` dicts (containing `raw_proms` with 100+ candidate entries and `oos_ledger` with all trades) are duplicated in TWO places:

1. `result["windows"]` → stored in `stock_row.result_json` (one big JSON blob per stock)
2. Top-level `"windows"` → stored in separate `StrategyBacktestWindow` rows (one row per window, with `summary_json` and `detail_json`)

This duplication exists in BOTH the viable AND not_viable return paths. The not_viable path (recently changed to include windows) makes the `result_json` blob so large that the worker appears to hang.

Additionally, `run.status = "completed"` is not a recognized status — the system uses `queued/running/succeeded/failed`.

## Fix 1 — Normalize: `result["windows"]` stores summaries only (both paths)

**File:** `core/quant_core/strategy_plan/wfo.py`

The convention: `result["windows"]` (which goes into `result_json`) should only contain lightweight summaries. The full detail is always available in `StrategyBacktestWindow` rows via the top-level `"windows"` key.

### 1a. Viable path (line ~1031)

Find:
```python
        "windows": winning_config["windows"],
```
(inside the `stock_result = {` dict, around line 1031)

Replace with:
```python
        "windows": [
            {"window_index": w.get("window_index"), "summary": w.get("summary")}
            for w in winning_config["windows"]
        ],
```

### 1b. Not-viable path (inside the `if not viable_configs:` block, ~line 911)

Find:
```python
                "windows": best_config["windows"],
```
(inside the `"result": {` sub-dict of the not_viable return)

Replace with:
```python
                "windows": [
                    {"window_index": w.get("window_index"), "summary": w.get("summary")}
                    for w in best_config["windows"]
                ],
```

In both cases, the TOP-LEVEL `"windows"` key (last key in each return dict) stays unchanged — it feeds `StrategyBacktestWindow` rows with full detail.

## Fix 2 — Use `"succeeded"` instead of `"completed"` for run status

**File:** `services/worker/tasks/strategy_backtest_runs.py`

**Line 373** — change:

```python
run.status = "succeeded" if succeeded > 0 else ("completed" if not_viable > 0 and failed == 0 else "failed")
```

to:

```python
run.status = "succeeded" if (succeeded > 0 or (not_viable > 0 and failed == 0)) else "failed"
```

## Verification

```bash
python -m pytest core/tests/test_strategy_plan_wfo.py core/tests/test_wfo_engine.py core/tests/test_strategy_plan_backtest.py -q
```

Then run a WFO backtest — it should finish quickly and show per-stock results with window summaries and rejection reasons.
