# Brief 48 — Empirically-weighted valuation ensemble (PIT backtest → IC) (Sonnet)

**Owner:** Sonnet implementer · **Branch:** `feature/fundamental-ui-consolidation` · **Supersedes the
weighting parts of** brief 47.
**Goal:** Stop guessing valuation-model ensemble weights. Determine them **empirically** — weight each
model by how well its undervaluation signal historically predicted **forward price returns** — using a
point-in-time backtest and the existing factor-IC machinery. **Pilot-gated**: prove there is
predictive signal before building the weighting; if there isn't, stop and reframe valuation as a
reference, not a return predictor.

> This replaces opinion-based ground truth (BKGR optimism vs DCF pessimism) with the only ground
> truth a backtesting shop should use: realized forward returns.

---

## 0. Why (settled context — don't relitigate)

- BKGR audit: the fixture is internally coherent (ratings monotone with upside) and price-current
  (~1% drift), **but structurally optimistic** — 30/35 Buy/Accumulate, 1 Sell, median upside +26%.
  Its cross-sectional ranking is low-information. **BKGR is a sanity reference, not a target.**
- Three anchors: BKGR +26% (optimistic) · market/peer (`relative_multiples`) ~0% · intrinsic DCF/DDM
  ensemble −40% (conservative). No model rank-correlates with BKGR (all Spearman ≈ 0).
- Equal-weighting depressed intrinsic models with the market-tracking peer model produces the −40%
  ensemble. The right weights are unknown — so **measure them against returns.**

**Expect a possibly-deflating result and embrace it:** MASI is illiquid and flow-driven; fundamentals
may have weak short-horizon IC. The pilot's job is to tell you the truth either way.

---

## Phase 1 — PILOT: does any model predict forward returns? (cheap, decisive — do this first)

### 1a. Point-in-time (PIT) valuation replay harness
Build a replay that, for each stock S and each historical as-of date T (use fiscal-year-ends FY2021…
FY2024 — whatever the data supports), recomputes **each valuation model's implied upside** using
**only data available at T**:
- statements: `fundamental_annual_metric` rows with `statement_year <= T` only — **no look-ahead**.
- price at T: from `market_data_store` / OHLCV history (`core/quant_core/data.py`), the close on/just
  before T.
- reuse the existing model functions in `core/quant_core/fundamentals/valuation.py`
  (`_fcff_dcf`, `_fcfe_dcf`, `_ddm`, `_residual_income`, `justified_multiples`, `relative_multiples`).
  Feed them the PIT snapshot/history — do NOT call the live latest-data path.
- output per (model, S, T): `upside_pct = fair_value(T)/price(T) - 1`.

**Look-ahead discipline is the whole ballgame** — if any future statement or price leaks in, the
backtest is worthless. Add an assertion that every input row's date ≤ T.

### 1b. Forward returns
For each (S, T): `fwd_return = price(T + H) / price(T) - 1`, H = 12 months (fundamentals are
long-horizon). Use the same PIT price source. Drop pairs where price(T+H) is missing.

### 1c. Per-model IC (reuse existing machinery)
Per as-of period T, compute the **cross-sectional Spearman IC** between each model's `upside_pct` and
`fwd_return` across stocks. Reuse the factor-relevance/IC code where it fits
(`core/quant_core/research/...` — `compute_factor_relevance`, `evaluate_direct_factor`,
`direct_ic_composite_score`, HAC t-stats). Then per model report:
- mean IC across periods, IC stdev / t-stat (honest about small n), # periods, # pairs.
- Survivorship: use `data/universe/bvc_pit_universe.csv` (has `delisting_date`) so delisted names are
  included at the T's where they were live — don't silently drop losers.

Print an IC table:
```
model               periods  pairs   mean_IC   t-stat
relative_multiples     4       ~260    ?         ?
ddm                    ...
...
```

### 1d. GATE / off-ramp (mandatory — stop and report)
- **If ≥2-3 models show positive, reasonably-stable IC** (right sign across most periods, non-trivial
  magnitude — don't demand a huge t-stat on 4 periods, but it must not be noise) → proceed to Phase 2.
- **If everything is ~0 / sign-flipping** → **STOP.** Write up "no reliable valuation IC on MASI at
  this horizon," and the conclusion is: keep equal-weight (or market-anchored) as a *fair-value
  reference*, surface valuation as context not a rating, and leave alpha to the technical signal
  engine. Do NOT build the weighting machinery on noise.

**Report the IC table and your gate decision before writing any Phase 2 code.**

---

## Phase 2 — IC-shrunk ensemble weighting (only if the pilot passes)

- Weight each model `w_m ∝ max(0, shrunk_IC_m)`, **shrunk hard toward equal weight** to avoid
  overfitting 4-5 periods: `w = (1-λ)·equal + λ·ic_weight`, λ small (~0.3-0.5). No free optimizer.
- Validate **out-of-sample**: estimate weights on earlier periods, test ensemble IC on later periods
  (expanding-window / leave-last-period-out — reuse the WFO infra). The IC-weighted ensemble must beat
  equal-weight **out of sample**, or revert to equal-weight.
- Wire the chosen weights into the ensemble aggregation that writes `fundamental_ensemble_result`
  (`model_weights_json`). Keep weights as data/config, not hardcoded, so they can be re-estimated.

---

## Acceptance criteria
1. PIT replay is provably look-ahead-free (assertion + a unit test feeding it future data and
   confirming it's excluded).
2. Pilot produces an honest per-model IC table with t-stats and a documented gate decision.
3. If proceeding: IC-shrunk ensemble beats equal-weight on **out-of-sample** IC; no coverage
   regression (overlap/quorum stable); core suite green.
4. If stopping: a written conclusion + recommended framing (reference, not rating) committed to the
   brief.
5. BKGR validator run as a **sanity check only** (report the deltas; do not optimize toward them).

## Guardrails
- **No look-ahead, no survivorship bias.** PIT statements (`statement_year <= T`) and PIT prices only;
  include delisted names via the PIT universe.
- **Small sample → shrinkage, not optimization.** 4-5 annual periods can rank models loosely; they
  cannot support precise fitted weights. Shrink toward equal; report uncertainty.
- **Out-of-sample or it doesn't count.** Never estimate and evaluate weights on the same periods.
- Keep the brief-31 sanity caps; this changes weights, not the models' guardrails.
- It is a **valid and acceptable outcome** to conclude "fundamentals don't predict MASI returns at
  this horizon" and stop. Honesty > a fitted weight vector that's really noise.
- Backend-only.
