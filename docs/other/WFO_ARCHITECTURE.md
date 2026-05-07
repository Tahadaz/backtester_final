# Walk-Forward Optimization: Full Architecture Reference

This document traces the complete lifecycle of a Walk-Forward Optimization (WFO) run — from user configuration through execution, persistence, API retrieval, and final UI rendering. It also documents the UI redesign implemented in `feat/wfo-strategy-results`.

---

## Table of Contents

1. [What WFO Is](#1-what-wfo-is)
2. [Run Configuration (Spec)](#2-run-configuration-spec)
3. [Worker Execution Pipeline](#3-worker-execution-pipeline)
4. [Database Persistence](#4-database-persistence)
5. [API Retrieval Layer](#5-api-retrieval-layer)
6. [Frontend Data Flow](#6-frontend-data-flow)
7. [UI Architecture: Per-Strategy-Kind Tab](#7-ui-architecture-per-strategy-kind-tab)
8. [Data Structures Reference](#8-data-structures-reference)
9. [Key Invariants](#9-key-invariants)
10. [Limitations and Known Gaps](#10-limitations-and-known-gaps)

---

## 1. What WFO Is

Walk-Forward Optimization (WFO) is an out-of-sample validation methodology for trading strategies. Instead of optimizing on the full historical period (which risks overfitting), it splits the data into rolling windows:

```
Time →
|──── Train 1 ────|── Test 1 ──|
          |──── Train 2 ────|── Test 2 ──|
                    |──── Train 3 ────|── Test 3 ──|
                                      |──── Holdout ──|
```

- **Selection folds (Train + Test):** N candidates (parameter variants) are tested on each fold's training period. Each candidate is evaluated on the test period. Fold results are aggregated across all folds to pick the single best candidate ("winner").
- **Holdout fold:** The final winner's parameters are applied to a completely held-out period never seen during selection. This is the authoritative OOS result.

The backtester supports two WFO modes:
- **Standard WFO** (`walk_forward.enabled = true`, single horizon)
- **Simple WFO multi-horizon** (`ui_mode = "simple_wfo_multi_horizon"`) — runs three independent WFO pipelines in parallel for short/medium/long horizons

---

## 2. Run Configuration (Spec)

A run is created via `POST /runs`. The request body includes a `spec_json` field that drives the entire pipeline.

Relevant spec fields for WFO:

```json
{
  "ui_mode": "simple_wfo_multi_horizon",
  "optimization": {
    "walk_forward": {
      "enabled": true,
      "multi_horizon": true,
      "horizons": ["short", "medium", "long"],
      "horizon": "short",
      "train": { "value": 6, "unit": "months" },
      "test":  { "value": 2, "unit": "months" },
      "step":  { "value": 1, "unit": "months" },
      "end_date_policy": "latest",
      "resolved_start_date": "2022-01-01",
      "resolved_end_date": "2024-12-31"
    }
  }
}
```

Relevant files:
- `services/api/app/routers/runs.py` — `POST /runs` (validates + stores spec, ~line 939)
- `services/api/app/schemas/runs.py` — request/response schemas

---

## 3. Worker Execution Pipeline

Entry point: `services/worker/tasks/execute_run.py` → `execute_run(run_id)`

### 3.1 High-Level Flow

```
execute_run(run_id)
  │
  ├── Load run + spec from DB
  ├── Materialize dataset (S3 → temp file)
  ├── Detect run_type: "optimization" | "backtest"
  │
  └── [optimization branch]
        │
        ├── For each symbol:
        │     ├── run_optimization(spec, symbol, data)
        │     │     ├── build_bank() — precompute indicators once
        │     │     ├── For each trial (param variant):
        │     │     │     └── _eval_one_trial() → scalar metrics (no fills)
        │     │     └── Return: ranked_results[], timing
        │     │
        │     └── [if WFO enabled]
        │           ├── simple_wfo_multi_horizon() OR wfo_pipeline()
        │           │     ├── For each horizon:
        │           │     │     ├── For each selection fold (rolling window):
        │           │     │     │     ├── run_optimization() on train period
        │           │     │     │     └── Evaluate top-K candidates on test period
        │           │     │     ├── Aggregate fold results → rank candidates
        │           │     │     ├── Select winner (lowest mean rank across folds)
        │           │     │     └── Evaluate winner on holdout period
        │           │     └── Return: rows[] (per fold per candidate), wfo_summary
        │           │
        │           ├── _persist_walk_forward_folds()    → run_fold table
        │           ├── _persist_wfo_holdout_fold()      → run_fold table
        │           ├── _persist_wfo_sentinel()          → run_fold table (summary row)
        │           └── _persist_strategy_leaderboard()  → strategy_leaderboard table
        │
        └── _persist_optimization_timing()  → run_metric table
```

### 3.2 Key Functions in execute_run.py

| Function | Lines (approx) | Purpose |
|---|---|---|
| `_persist_walk_forward_folds()` | 1756–1960 | Writes selection fold rows (one per candidate per fold) |
| `_persist_wfo_holdout_fold()` | 1644–1698 | Writes the holdout fold row for the winner |
| `_persist_wfo_sentinel()` | 1701–1753 | Writes the authoritative `wfo_summary` as a sentinel row |
| `_persist_strategy_leaderboard()` | ~3100 | Writes leaderboard rows (best params + summary metrics) |
| `_persist_optimization_timing()` | ~2742 | Writes timing metrics to run_metric |

### 3.3 WFO Selection Process

Within each fold:
1. `run_optimization()` tests N candidates (parameter variants) on the training period using the Numba fast path
2. The top-K candidates (by objective function score) are evaluated on the test period
3. Each candidate receives a rank within this fold (1 = best test score)

Across all selection folds:
1. Each candidate accumulates a rank in each fold it appeared in
2. The winner is the candidate with the **lowest mean rank** across all folds
3. `selection_reason` in `WfoSelectedWinner` describes the tie-breaking logic

After selection:
- The winner's parameters are fixed
- The winner is evaluated on the holdout period (no optimization, pure OOS backtest)
- The holdout result is the definitive performance estimate

### 3.4 `trial_id` — Candidate Identity

Each candidate is identified by a deterministic hash of `(strategy_kind, params_dict)`:

```python
# core/quant_core/pipeline.py
trial_id = compute_trial_id(strategy_kind, params_dict)
```

`trial_id` is stored in:
- `strategy_leaderboard.trial_id` (DB column)
- `run_fold.fold_artifacts["trial_id"]` (JSONB field, extracted at API level)
- `wfo_summary.by_strategy_kind[sk].selected_winner.trial_id`
- `wfo_summary.by_strategy_kind[sk].candidate_summaries[].trial_id`

**Important:** For older runs (before `trial_id` was added to `fold_artifacts`), `fold.trial_id` may be `""`. This affects winner-fold matching in the UI (see §7).

---

## 4. Database Persistence

### 4.1 `run_fold` Table

Primary storage for all fold-level data.

```sql
CREATE TABLE run_fold (
    id              BIGINT PRIMARY KEY AUTOINCREMENT,
    run_id          UUID NOT NULL REFERENCES run(id),
    fold_index      INTEGER NOT NULL,           -- encoded: logical_fold * 1000 + trial_rank
    strategy_kind   VARCHAR(128) NOT NULL DEFAULT '',
    train_start     TIMESTAMPTZ,
    train_end       TIMESTAMPTZ,
    test_start      TIMESTAMPTZ,
    test_end        TIMESTAMPTZ,
    fold_metrics_json  JSONB DEFAULT '{}',      -- performance metrics
    fold_artifacts     JSONB DEFAULT '{}',      -- metadata + wfo_summary (sentinel only)
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(run_id, strategy_kind, fold_index)
);
```

**`fold_index` encoding:**
- Selection folds: `logical_fold_number * 1000 + trial_rank` (e.g., fold 3, rank 2 → 3002)
- Holdout fold: `logical_fold * 1000 + 1` (is_holdout=True in fold_artifacts)
- Sentinel row: `fold_index = 0`, `strategy_kind = "__wfo_summary__"`

**`fold_metrics_json` keys (selection folds):**
```json
{
  "objective_value": 1.234,
  "stat.pnl": 5420.0,
  "stat.cagr": 0.184,
  "stat.sharpe": 1.82,
  "stat.max_drawdown": -0.083,
  "stat.win_pct": 0.62,
  "stat.n_fills": 47,
  "strategy_kind": "rsi_strategy",
  "trial_id": "abc12345..."
}
```

**`fold_artifacts` keys (selection folds):**
```json
{
  "is_holdout": false,
  "trial_id": "abc12345...",
  "horizon": "short",
  "symbol": "ATPL",
  "n_selection_folds": 8
}
```

**Sentinel row** (`fold_index=0`, `strategy_kind="__wfo_summary__"`):
The `fold_artifacts` of the sentinel contains the full authoritative `wfo_summary`:
```json
{
  "is_sentinel": true,
  "schema_version": 1,
  "wfo_summary": {
    "by_strategy_kind": {
      "rsi_strategy": {
        "candidate_summaries": [...],
        "selected_winner": { "trial_id": "...", "fold_count": 8, "rank_mean": 2.3, ... },
        "final_holdout": { "test_start": "...", "pnl": 4250, "cagr": 0.184, "sharpe": 1.82, ... }
      }
    }
  }
}
```

### 4.2 `strategy_leaderboard` Table

Stores final optimization results for display. One row per `(run_id, symbol, strategy_kind, rank)`.

```sql
CREATE TABLE strategy_leaderboard (
    run_id          UUID,
    symbol          VARCHAR,
    strategy_kind   VARCHAR,
    rank            INTEGER,           -- 1 = best, higher = worse
    trial_id        VARCHAR,
    pnl             FLOAT,
    cagr            FLOAT,
    total_return    FLOAT,
    sharpe          FLOAT,
    max_drawdown    FLOAT,
    win_pct         FLOAT,
    efficiency      FLOAT,
    n_fills         INTEGER,
    signal_label    VARCHAR,
    signal_today    FLOAT,
    signal_date     TIMESTAMPTZ,
    best_params_json  JSONB,
    UNIQUE(run_id, symbol, strategy_kind, rank)
);
```

For WFO runs, `rank=1` represents the selected winner. The metrics stored here are the **holdout period metrics** (not cross-fold averages).

### 4.3 `run_metric` Table

Stores named scalar metrics per run. Used for optimization timing, aggregated backtest stats, etc.

Relevant keys for WFO timing: `opt.load_ms`, `opt.bank_ms`, `opt.trial_total_ms`, `opt.cache_hits`, `opt.cache_misses`.

---

## 5. API Retrieval Layer

### 5.1 `GET /runs/{run_id}/walk-forward`

**File:** `services/api/app/routers/runs.py`, ~line 1328

Returns the full WFO structure for a run. This is the primary data source for the frontend's WFO display.

**Processing steps:**
1. Load all `run_fold` rows for the run
2. Separate sentinel row (`fold_index=0, strategy_kind="__wfo_summary__"`)
3. Extract `wfo_summary.by_strategy_kind` from sentinel's `fold_artifacts`
4. Decode non-sentinel rows:
   - `fold_logical = fold_index // 1000`
   - `trial_rank = fold_index % 1000`
   - `trial_id = fold_artifacts.get("trial_id", "")`
5. Compute aggregate stats across selection folds
6. Return structured `RunWalkForward` payload

**Key payload shape:**
```typescript
type RunWalkForward = {
  run_id: string
  mode: string | null
  horizon: string | null
  resolved_start_date: string | null
  resolved_end_date: string | null
  windows: { train: object; test: object; step: object }
  aggregate: { fold_count: number; n_selection_folds: number; objective_mean: number | null }
  n_selection_folds: number
  strategy_kinds: string[]
  by_strategy_kind: Record<string, WfoStrategyKindSummary>  // from sentinel
  legacy_aggregation: boolean
  folds: RunFold[]  // all non-sentinel rows
}
```

### 5.2 `GET /runs/{run_id}/leaderboard`

Returns `strategy_leaderboard` rows, optionally filtered by `symbol`, `strategy_kind`, `best_only`.

For WFO runs, `rank=1` rows contain the winner's aggregated metrics (holdout-period performance). Higher ranks contain other tested candidates' leaderboard entries.

### 5.3 `GET /runs/{run_id}/decisions/{symbol}`

Returns `strategy_decision` rows — opportunity/confidence scoring computed separately after optimization. Not part of the WFO selection process itself.

---

## 6. Frontend Data Flow

All WFO data is consumed in a single page component:

**File:** `quant-backtesting-frontend/app/runs/[runId]/page.tsx`

### 6.1 Data Hooks

```typescript
// Leaderboard (winner per strategy per symbol)
const { data: leaderboard } = useLeaderboard(runId, { best_only: false })

// WFO fold structure + per-kind summaries
const { data: walkForward } = useRunWalkForward(runId)
```

`walkForward` is loaded once for the whole page and referenced in multiple rendering contexts.

### 6.2 Derived Computed State

Before rendering, several `useMemo` hooks derive:
- `symbols` — all symbols from leaderboard + metrics + artifacts
- `selectedSymbolBestRows` — best row per strategy kind for the selected symbol
- `selectedSymbolAllRows` — all ranked rows for selected symbol (filtered by selected horizon if simpleWFO)
- `strategyKindsForSelectedSymbol` — unique strategy kinds for the symbol
- `horizonFilteredLeaderboard` — leaderboard filtered to `selectedHorizon` (simpleWFO only)

### 6.3 Rendering Decision (isSimpleWfoOptimization)

```
isSimpleWfoOptimization =
  spec.ui_mode === "simple_wfo_multi_horizon"
  OR walkForwardSpecConfig.multi_horizon === true
```

This flag gates several rendering paths:
- `true`: horizon tabs (Short/Medium/Long) shown above stock tabs; decision tab hidden; WFO card hidden
- `false`: standard WFO layout with global WFO card; decision tab available

---

## 7. UI Architecture: Per-Strategy-Kind Tab

### 7.1 Background (Before This Refactor)

The per-strategy-kind tabs were built for a simple optimization workflow. For a strategy like `rsi_strategy`, the tab showed:
- Top 5 ranked candidate rows from `strategy_leaderboard` (rank 1–5)
- For each: strategy_kind, rank, CAGR, PnL, Trades, Win%, MaxDD, Sharpe, params diff vs rank #1
- A "Show" button to open the detail panel

This was adequate before WFO: rank 1 was the clear winner, ranks 2–5 were alternatives to compare.

**After WFO was introduced, this layout became misleading:**
- "Rank" no longer had a clear meaning (it came from a multi-fold selection process)
- There was no visibility into HOW the winner was selected (fold history, mean rank, selection reason)
- The holdout (OOS) result — the only reliable performance estimate — was buried elsewhere

### 7.2 New Layout (feat/wfo-strategy-results)

**File changed:** `quant-backtesting-frontend/app/runs/[runId]/page.tsx`

**What changed:** The `strategyKindsForSelectedSymbol.map((kind) => { ... })` block was rewritten. A new helper `foldMetric()` was added.

The tab now has two render paths controlled by `hasUsableWfoData`:

```
hasUsableWfoData = (
  candidateSummaries.length > 0
  AND (selectedWinner !== null OR holdout !== null OR winnerSelectionFolds.length > 0)
)
```

#### Path A: WFO Layout (when `hasUsableWfoData === true`)

Shown for standard WFO runs with persisted sentinel data.

**Block 1 — Out-of-Sample Holdout Result**

The top block. Shows the definitive OOS verdict:
- Period: `test_start → test_end`
- Metrics: PnL, CAGR, Sharpe, MaxDD, Win%, Trades

Source: `walkForward.by_strategy_kind[kind].final_holdout`

**Block 2 — Selected Winner**

Identifies the winning candidate:
- **Primary label:** strategy params (human-readable via `strategyOnlyPreview(winnerCandidate.params)`)
- **Secondary:** short trial_id hash (first 8 chars)
- **Selection metadata:** selection_reason, n_selection_folds, objective_mean, rank_mean

Source: `walkForward.by_strategy_kind[kind].selected_winner` + `.candidate_summaries.find(c.is_winner)`

**Block 3 — Candidate Comparison Table**

Replaces the old "top 5 variants" table. One row per tested candidate, sorted by `rank_mean` ascending (best first). Winner row highlighted green.

Columns: Variant (params) | Folds | Obj. Mean | Sharpe Mean | PnL Mean | MaxDD Mean | Rank Mean | ★

Source: `walkForward.by_strategy_kind[kind].candidate_summaries[]`

**Block 4 — Winner Fold Timeline**

Shows the winner's test-period performance in each selection fold, sorted chronologically.

Columns: Fold | Train | Test | Objective | PnL | CAGR | Sharpe

Fold matching uses `trial_id`:
- `winnerTrialId = selectedWinner.trial_id ?? winnerCandidate.trial_id ?? ""`
- If `winnerTrialId !== ""`: filter folds by `fold.trial_id === winnerTrialId`
- If `winnerTrialId === ""` (old run): show empty state message — **no approximate fallback**

Source: `walkForward.folds.filter(f => f.strategy_kind === kind && f.trial_id === winnerTrialId && !f.is_holdout)`

#### Path B: Legacy Variations Table (fallback)

Rendered when:
- `isSimpleWfoOptimization === true` (multi-horizon WFO — handled separately by horizon tabs)
- `hasUsableWfoData === false` (old runs, missing sentinel, or no candidates)

Preserves the original layout exactly: top 5 leaderboard rows with params delta vs rank #1.

### 7.3 New Helper: `foldMetric()`

Added near other utility functions (~line 277 in page.tsx):

```typescript
function foldMetric(m: Record<string, unknown>, ...keys: string[]): number | null {
  for (const key of keys) {
    const val = key.split(".").reduce<unknown>(
      (o, k) => (o !== null && o !== undefined && typeof o === "object"
        ? (o as Record<string, unknown>)[k]
        : undefined),
      m
    )
    if (val !== null && val !== undefined && Number.isFinite(Number(val))) return Number(val)
  }
  return null
}
```

Handles both flat keys (`"pnl"`) and dot-path keys (`"stat.pnl"`) — both appear in `fold_metrics_json` depending on the pipeline version.

### 7.4 What Is NOT Changed

| Component | Status |
|---|---|
| Overview tab (best row per strategy) | Unchanged |
| Decision tab | Unchanged |
| Left-panel symbol list | Unchanged |
| Global WFO card (run-level config summary) | Unchanged — kept as config/aggregate summary |
| All hooks, API endpoints, schemas | Unchanged |
| Backend worker / DB | Unchanged |

---

## 8. Data Structures Reference

### Frontend Types (from `lib/api.ts`)

```typescript
type RunFold = {
  fold_index: number
  fold_logical: number
  trial_rank: number
  strategy_kind: string
  is_holdout: boolean
  trial_id: string           // "" if not stored on old runs
  train_start: string | null
  train_end: string | null
  test_start: string | null
  test_end: string | null
  fold_metrics_json: Record<string, unknown>
  fold_artifacts: Record<string, unknown>
  created_at: string
}

type WfoCandidateSummary = {
  trial_id: string
  params?: Record<string, unknown>
  fold_count: number
  objective_mean: number | null
  objective_std: number | null
  pnl_mean: number | null
  sharpe_mean: number | null
  max_drawdown_mean: number | null
  win_pct_mean: number | null
  rank_mean: number | null
  is_winner: boolean
}

type WfoSelectedWinner = {
  trial_id: string
  fold_count: number
  objective_mean: number | null
  rank_mean: number | null
  n_selection_folds: number
  selection_reason: string | null
}

type WfoFinalHoldout = {
  test_start: string | null
  test_end: string | null
  pnl: number | null
  cagr: number | null
  sharpe: number | null
  max_drawdown: number | null
  win_pct: number | null
  n_fills: number | null
  objective_value: number | null
}

type WfoStrategyKindSummary = {
  // Standard WFO: flat structure
  candidate_summaries: WfoCandidateSummary[]
  selected_winner: WfoSelectedWinner | null
  final_holdout: WfoFinalHoldout | null
  // Multi-horizon: nested by horizon name
  by_horizon?: Record<string, WfoHorizonData>
}
```

---

## 9. Key Invariants

1. **Sentinel is the only authoritative source for `wfo_summary`** — do not reconstruct it from fold rows
2. **`selected_winner.trial_id` identifies the winner** — match fold rows by this, never by `trial_rank === 1`
3. **`strategy_leaderboard.rank=1` is the winner** — but its metrics are holdout-period results, not fold averages
4. **Fold rows are NOT per-symbol** — the `run_fold` table has no `symbol` column; folds represent the run's time-series windows applied across all symbols
5. **No approximate fold attribution** — if `trial_id` is missing, show empty state; never show `trial_rank=1` rows as "winner folds"
6. **MaxDD is stored as a negative float** (e.g., `-0.083`) — display with `formatPercent()` unchanged; do not invert sign
7. **simpleWFO multi-horizon** uses `by_horizon` nesting in `by_strategy_kind` — the flat `candidate_summaries` / `selected_winner` / `final_holdout` fields are populated per-horizon, accessed via `.by_horizon[horizonName]`

---

## 10. Limitations and Known Gaps

| Issue | Impact | Status |
|---|---|---|
| `fold.trial_id === ""` on runs before `trial_id` was stored in `fold_artifacts` | Block 4 (fold timeline) shows empty state instead of winner history | Known; old runs are unaffected functionally |
| Multi-horizon (simpleWFO) per-kind summary not rendered in WFO layout | simpleWFO runs fall back to legacy variations table | Acceptable for now; handled by horizon tabs |
| Fold data is run-level (no `symbol` column) | Cannot show per-symbol fold performance in multi-symbol runs | Architectural: changing would require DB migration |
| Candidate `params` field may be `undefined` in old `wfo_summary` payloads | Block 3 Variant column shows `strategyOnlyPreview(undefined)` → falls back to `"--"` | Handled by `parseBestParams()` in the helper chain |
| `fold_metrics_json` key format varies by pipeline version (`"pnl"` vs `"stat.pnl"`) | `foldMetric()` tries both, returns first match | Handled |
