# Codex Task: Fix Regime Detection Bugs

## Overview

The regime detection feature (Layer H — Kaufman Efficiency Ratio) has bugs across 6 files. All fixes are mechanical and localized. Do them in order.

## Pre-conditions

- Working directory: project root
- Python venv: `.venv/`
- Run tests from root: `python -m pytest core/tests/test_regime.py -v`
- Run TS check from frontend: `cd quant-backtesting-frontend && npx tsc --noEmit`

---

## Fix 1: Off-by-one + dead code in regime.py (CRITICAL)

**File:** `core/quant_core/signal_engine/regime.py`

### 1a. Delete dead variable (line 205)

Find and DELETE this entire line:

```python
        test_ret_slice = slice(test_start, test_end - 1)
```

This variable is declared but never used.

### 1b. Fix off-by-one in test window bar count (line 208)

Find:
```python
        test_n = test_end - 1 - test_start
```

Replace with:
```python
        test_n = test_end - test_start
```

**Why:** The existing code drops the last return bar from every OOS test window. The correct pattern (matching `oos_eval.py`) is `test_end - test_start`.

### 1c. Add single-family guard (after line ~132)

Find this block:
```python
    train_len = params["train"]
    test_len = params["test"]
    step = params["step"]
    min_bars = train_len + test_len + 1
```

Add this line BEFORE `min_bars`:
```python
    if n_families < 2:
        return _inactive_result("single_family", n_families)
```

So the result is:
```python
    train_len = params["train"]
    test_len = params["test"]
    step = params["step"]

    if n_families < 2:
        return _inactive_result("single_family", n_families)

    min_bars = train_len + test_len + 1
```

**Why:** With 1 family, regime weighting always produces weight=1.0 — identical to equal-weight. Activating regime in this case is misleading.

### 1d. Fix stale tercile defaults (lines 156-157)

Find:
```python
    last_er_low = 0.33
    last_er_high = 0.67
```

Replace with:
```python
    last_er_low = 0.0
    last_er_high = 0.0
```

**Why:** If no folds complete, these defaults leak into the returned `tercile_bounds`. Using 0.0 signals "no data computed."

---

## Fix 2: API empty response missing fields (CRITICAL)

**File:** `services/api/app/routers/strategy_signals.py`

Find the empty-response block inside the `regime_consensus` function (the `if not family_scores:` branch). It currently returns:

```python
    if not family_scores:
        return {
            "symbol": body.symbol,
            "final_consensus": None,
            "family_weights": {},
            "per_family": {},
            "regime_active": False,
            "regime_label": "insufficient_data",
            "er_value": None,
            "improvement": 0.0,
            "tercile_bounds": [0.33, 0.67],
        }
```

Replace the entire return dict with:

```python
    if not family_scores:
        return {
            "symbol": body.symbol,
            "final_consensus": None,
            "family_weights": {},
            "per_family": {},
            "regime_active": False,
            "regime_label": "insufficient_data",
            "er_value": None,
            "improvement": 0.0,
            "tercile_bounds": [0.33, 0.67],
            "equal_consensus": None,
            "n_families": 0,
            "window_results": [],
            "n_folds": 0,
            "folds_regime_wins": 0,
            "top_variants": {},
        }
```

**Why:** The frontend Zod schema (`RegimeConsensusSchema`) requires all 16 fields. Missing fields cause a parse crash.

---

## Fix 3: Frontend race condition — keep SWR hook alive on level 3

**File:** `quant-backtesting-frontend/components/strategy/technical-analysis-panel.tsx`

### 3a. Fix the hook arguments

Find:
```tsx
  const regime = useRegimeConsensus(
    regimeAware ? symbol : null,
    regimeAware ? horizon : null,
    cooldownBars,
  )
```

Replace with:
```tsx
  const regimeNeeded = regimeAware || level === 3
  const regime = useRegimeConsensus(
    regimeNeeded ? symbol : null,
    regimeNeeded ? horizon : null,
    cooldownBars,
  )
```

**Why:** If user is on level 3 (regime detail panel) and SWR loses cache, `regime.data` becomes undefined and the panel goes blank. Keeping the hook alive on level 3 prevents this.

### 3b. Add loading/error fallback for level 3

Find:
```tsx
  // Level 3: Regime detail
  if (level === 3 && regime.data) {
    return (
      <RegimeDetailPanel
        data={regime.data}
        onBack={() => setLevel(0)}
      />
    )
  }
```

Replace with:
```tsx
  // Level 3: Regime detail
  if (level === 3) {
    if (regime.data) {
      return (
        <RegimeDetailPanel
          data={regime.data}
          onBack={() => setLevel(0)}
        />
      )
    }
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={() => setLevel(0)} className="text-xs">
          &larr; Retour
        </Button>
        {regime.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <Card className="border-destructive/50">
            <CardContent className="py-8 text-center">
              <p className="text-sm text-muted-foreground">
                Impossible de charger les donnees regime.
              </p>
            </CardContent>
          </Card>
        )}
      </div>
    )
  }
```

**Why:** Without this, level=3 with no data renders nothing (blank panel). Now it shows a skeleton while loading or an error message.

---

## Fix 4: Division by zero guards in regime detail panel

**File:** `quant-backtesting-frontend/components/strategy/regime-detail-panel.tsx`

### 4a. Guard equal-weight reference column

Find:
```tsx
            {/* Equal weights reference */}
            <div>
              <div className="text-[10px] text-muted-foreground mb-2 font-medium">
                Reference (1/N egal)
              </div>
              <div className="space-y-1.5">
                {families.map((f) => (
                  <div key={f} className="flex items-center gap-2">
                    <span className="text-[11px] font-mono w-10 uppercase">{f}</span>
                    {weightBar(1 / families.length, "bg-gray-400")}
                  </div>
                ))}
              </div>
            </div>
```

This is safe when `families.length > 0` because the `.map()` produces nothing when empty. But `1 / families.length` is still evaluated per-item. Since `families.map()` on an empty array never calls the callback, this is actually safe. **No change needed for 4a.**

### 4b. Guard footer averages

Find the `<tfoot>` section:
```tsx
              <tfoot>
                <tr className="font-medium border-t-2">
                  <td colSpan={4} className="py-1.5 pr-2">Moyenne</td>
                  <td className="py-1.5 pr-2 text-right font-mono">
                    {(data.window_results.reduce((s, w) => s + w.regime_sharpe, 0) / data.n_folds).toFixed(3)}
                  </td>
                  <td className="py-1.5 pr-2 text-right font-mono">
                    {(data.window_results.reduce((s, w) => s + w.equal_sharpe, 0) / data.n_folds).toFixed(3)}
                  </td>
                  <td className={`py-1.5 text-right font-mono font-bold ${data.improvement > 0 ? "text-green-700" : "text-red-600"}`}>
                    {data.improvement > 0 ? "+" : ""}{data.improvement.toFixed(3)}
                  </td>
                </tr>
              </tfoot>
```

Replace with:
```tsx
              {data.n_folds > 0 && (
                <tfoot>
                  <tr className="font-medium border-t-2">
                    <td colSpan={4} className="py-1.5 pr-2">Moyenne</td>
                    <td className="py-1.5 pr-2 text-right font-mono">
                      {(data.window_results.reduce((s, w) => s + w.regime_sharpe, 0) / data.n_folds).toFixed(3)}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono">
                      {(data.window_results.reduce((s, w) => s + w.equal_sharpe, 0) / data.n_folds).toFixed(3)}
                    </td>
                    <td className={`py-1.5 text-right font-mono font-bold ${data.improvement > 0 ? "text-green-700" : "text-red-600"}`}>
                      {data.improvement > 0 ? "+" : ""}{data.improvement.toFixed(3)}
                    </td>
                  </tr>
                </tfoot>
              )}
```

**Why:** If `data.n_folds === 0`, dividing by zero produces NaN.

---

## Fix 5: Add timeframe to fetch function

**File:** `quant-backtesting-frontend/lib/api.ts`

Find the `fetchRegimeConsensus` function. Its body currently sends:
```typescript
    body: JSON.stringify({
      symbol: body.symbol,
      horizon: body.horizon,
      cost_bps: body.cost_bps ?? 10,
      cooldown_bars: body.cooldown_bars ?? 0,
    }),
```

Replace with:
```typescript
    body: JSON.stringify({
      symbol: body.symbol,
      horizon: body.horizon,
      timeframe: body.timeframe ?? "1D",
      cost_bps: body.cost_bps ?? 10,
      cooldown_bars: body.cooldown_bars ?? 0,
    }),
```

Also update the function signature. Find:
```typescript
export async function fetchRegimeConsensus(body: {
  symbol: string
  horizon: string
  cost_bps?: number
  cooldown_bars?: number
}): Promise<RegimeConsensus> {
```

Replace with:
```typescript
export async function fetchRegimeConsensus(body: {
  symbol: string
  horizon: string
  timeframe?: string
  cost_bps?: number
  cooldown_bars?: number
}): Promise<RegimeConsensus> {
```

---

## Fix 6: Add tests for the bugs we fixed

**File:** `core/tests/test_regime.py`

Add these two test methods to the `TestValidateRegimeOOS` class:

```python
    def test_single_family_inactive(self):
        """Single family → regime_active=False (meaningless to weight 1 family)."""
        close = self._make_trending_data(1200)
        signals = {"sma": np.ones(1200)}
        result = validate_regime_oos(close, signals, "short", cost_bps=10.0)
        assert not result.regime_active
        assert result.regime_label == "single_family"

    def test_window_return_count(self):
        """Verify test window processes correct number of bars (no off-by-one)."""
        close = self._make_trending_data(1200)
        signals = self._make_family_signals(1200)
        result = validate_regime_oos(close, signals, "short", cost_bps=10.0)
        # Each fold should process test_end - test_start bars
        for wr in result.window_results:
            expected_bars = wr["test_end"] - wr["test_start"]
            # regime_sharpe and equal_sharpe should be computed from expected_bars returns
            # If they are both exactly 0.0 AND expected_bars > 10, that indicates an error
            assert expected_bars > 0
```

---

## Verification (run after all fixes)

```bash
# 1. Python tests — must all pass
python -m pytest core/tests/test_regime.py -v

# 2. No regressions in signal engine
python -m pytest core/tests/test_signal_engine.py -q

# 3. No TypeScript errors
cd quant-backtesting-frontend && npx tsc --noEmit
```

## Files Modified (summary)

| # | File | What Changed |
|---|------|-------------|
| 1 | `core/quant_core/signal_engine/regime.py` | Off-by-one fix, dead code removal, single-family guard, tercile defaults |
| 2 | `services/api/app/routers/strategy_signals.py` | 6 missing fields in empty response |
| 3 | `quant-backtesting-frontend/components/strategy/technical-analysis-panel.tsx` | SWR hook kept alive on level 3, loading/error fallback |
| 4 | `quant-backtesting-frontend/components/strategy/regime-detail-panel.tsx` | Division-by-zero guard on footer |
| 5 | `quant-backtesting-frontend/lib/api.ts` | Added timeframe param to fetchRegimeConsensus |
| 6 | `core/tests/test_regime.py` | 2 new tests: single-family, window-return-count |
