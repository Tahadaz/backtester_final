# 16 — Signal-Evidence Metrics Hardening + Real Alpha/Beta

**Status:** spec approved, pending Codex implementation
**Owner:** taha
**Branches touched:**
- Part A → worktree `.codex/worktrees/signal-evidence-institutional-metrics` (branch `feature/signal-evidence-institutional-metrics`)
- Part B → the S/R UI coupling, done in the **same institutional worktree** (that is where `signal-evidence-tab.tsx` lives) so it is forward-compatible with the `feature/sr-desk-grade` backend contract.

**Do not touch** the dirty `feature/forward-estimate-layer` tree.

---

## Why this brief exists

Codex shipped an "institutional metrics" panel on the stitched-WFO evidence tab. A quant review found it is ~60% signal, ~40% false precision at our sample sizes:

- **Keep (robust at low N):** profit factor, avg win/loss + payoff ratio, and the sample-quality block (honest `n≥30` disclosure).
- **Noise dressed as rigor (gate behind sample size):** Sortino, Calmar, annualized/downside vol, and especially **p05/p95 "tail" returns** — a 5th percentile off ~30 trades is just the worst observation, not a VaR.
- **Redundant:** `expectancy_net` duplicates `expected_return_net`.
- **Basis bug:** headline Sharpe is per-trade net returns annualized ×√252 (wrong — assumes 252 trades/yr) sitting next to a path-based Sortino, implying a comparability that does not exist.
- **Actually missing:** there is **no alpha/beta**. On a mostly-long MASI book, benchmark-relative beta is the single most important exposure metric we lack — half the "edge" could just be long-beta in a rising market.

This brief cleans up the panel and adds real alpha/beta, reusing existing benchmark infrastructure.

---

## Global guardrails (non-negotiable)

1. **Reuse, don't rebuild.** Regression math reuses the OLS in `core/quant_core/fundamentals/cost_of_capital.py` (`_ols_beta`) or a thin shared helper promoted from it. No second covariance formula.
2. **Parity is proven, not assumed.** Every metric present in both Python (`_evidence.py`) and JS (`signal-evidence-range.js`) is covered by a shared golden-fixture test (Task A6). No metric ships without it.
3. **Honesty over completeness.** Noisy small-sample metrics render only when `min_sample_pass` is true.
4. All annualization bases are internally consistent and **labeled** in the UI.

---

## PART A — Institutional-metrics panel

### A1 — Remove redundant expectancy
`expectancy_net` == `expected_return_net` (both `mean(net_returns)`). Delete the duplicate.
- `_evidence.py`: remove `"expectancy_net"` from `_evidence_trade_distribution_metrics`.
- `api.ts`: remove `expectancy_net` from `SignalEvidenceStitchedMetricsSchema`.
- `signal-evidence-range.js`: remove from `distributionMetrics` and the `empty` block.
- `signal-evidence-tab.tsx`: point the "Expectancy" tile at `metrics.expected_return_net` (keep median detail).

### A2 — Fix the Sharpe/Sortino basis mismatch

**A2a — correct trade-level Sharpe annualization** (both `_evidence.py` and `signal-evidence-range.js`; JS `sharpe()` hardcodes √252):
```
years           = max(len(dates), 1) / 252
trades_per_year = n_trades / years                 # n_trades = len(net_returns)
sharpe_trade    = mean(net)/std(net) * sqrt(trades_per_year)   # std ddof=1; None if n_trades<2 or std<=0
```
Headline StatCard stays "Trade Sharpe", detail `"per-trade, freq-annualized"`.

**A2b — add a path-based Sharpe** so the Risk block is one coherent daily-basis cluster:
```
sharpe_path = mean(path)/std(path) * sqrt(252)     # path = _evidence_path_returns(equity); None if <2 obs or std<=0
```
Add `sharpe_path` to payload/schema/JS; render next to Sortino, both detailed `"daily path basis"`. Sortino, `sharpe_path`, `annualized_volatility`, `downside_volatility`, `calmar` now form a consistent path-return cluster.

### A3 — Gate noisy metrics behind sample size (UI only)
In `signal-evidence-tab.tsx`, split Risk & Distribution tiles:
- **Always show:** Profit factor, Avg win/loss + payoff, Expectancy, Max drawdown.
- **Only when `metrics.min_sample_pass === true`:** Sortino, `sharpe_path`, Calmar, Ann./downside vol, **p05/p95 tail**. When false, render one muted line: `"Distribution & tail metrics hidden — n<30 (audit only)"`.

Do **not** delete these from the payload (kept for API/audit); only gate display.

### A4 — Attach benchmark return series to the stitched payload
- `_evidence.py` constant: `EVIDENCE_BENCHMARK_SYMBOL = "MASI"`. **Verify the exact ticker key** in the prices table via `load_close_for_symbol(db, "MASI")`; if stored as `MASI.CS`/`MASI.MA`, use that. If benchmark load fails, degrade gracefully (`benchmark_status="unavailable"`, alpha/beta `None`) — never raise.
- In the stitched builder (caller near `_evidence.py:1467`, which has `db`/`price_index`), load benchmark close via the already-imported `load_close_for_symbol`, reindex to `dates` (ffill limit ~3 bars; gaps stay NaN), compute index-aligned per-bar simple returns:
```
benchmark_returns[0] = None
benchmark_returns[i] = bclose[i]/bclose[i-1] - 1   (None where either side missing or <=0)
```
- Add `benchmark_returns: list[float|None]` (len == len(dates)) and `benchmark_symbol: str` to the stitched payload and the frontend `stitched` object. Extend `api.ts`: `benchmark_returns: z.array(z.number().nullable()).optional()`, `benchmark_symbol: z.string().nullable().optional()`.

### A5 — Real alpha/beta (effective-book, exposure-adjusted)
Regress the **traded book's** daily path returns on the benchmark's daily returns. This blends the stock's beta with time-in-market — it is the real market exposure of the book, **not** the underlying stock's textbook beta. Document in docstring + UI tooltip.

Shared helper (promote `_ols_beta` from `cost_of_capital.py` to a shared pure module, e.g. `core/quant_core/research/stats/regression.py`, and reuse it):
```
def market_model(strat_ret, bench_ret, *, periods_per_year=252, min_obs=20):
    # pair only indices where BOTH finite; require paired n>=min_obs AND nonzero-strat days>=10
    beta          = cov(strat,bench,ddof=1)/var(bench,ddof=1)   # None if var<=0
    alpha_daily   = mean(strat) - beta*mean(bench)
    alpha_annualized = alpha_daily * periods_per_year           # linear ×252, labeled
    r2            = corr(strat,bench)**2
    return {beta, alpha_annualized, r2, n_obs, reason}          # reason in {ok, insufficient_overlap, benchmark_unavailable}
```
- Strategy stream = index-aligned per-bar path returns from `equity` (keep flat 0 days — they pull beta toward true average exposure).
- Add metrics: `beta`, `alpha_annualized`, `alpha_r2`, `alpha_n_obs`, `alpha_reason`, echo `benchmark_symbol`.
- Mirror `marketModel()` in `signal-evidence-range.js` with identical math, recomputing per range from the shipped `benchmark_returns`.
- New "Market Exposure" `DiagnosticSection`, gated behind `min_sample_pass` AND `alpha_reason==="ok"` (else one muted line with the reason):
  - `Beta (vs {benchmark_symbol})` — `formatFiniteNumber(beta,2)`, detail `"traded-book exposure"`.
  - `Alpha (ann.)` — `formatPercent(alpha_annualized)`, tone `metricTone`, detail `"×252 intercept"`.
  - `Fit R²` — `formatNumber(alpha_r2,2)`, detail `"{alpha_n_obs} paired days"`.
- Extend `api.ts` with the five nullable fields.

### A6 — Golden-fixture parity test (locks Python ↔ JS)
- `services/api/tests/fixtures/evidence_metrics_golden.json`:
  `{ "inputs": { net_returns, equity, dates, benchmark_returns }, "expected": { ...all shared metrics... } }`
  Use a case with **≥35 trades** (exercises `min_sample_pass`) and a benchmark series with known covariance so beta/alpha are analytically checkable.
- Python: in `test_signal_evidence_institutional_metrics.py`, load fixture, call helpers, assert each `expected` within abs tol `1e-9`.
- JS: in `frontend/lib/signal-evidence-range.test.mjs`, load the **same** JSON, assert parity within `1e-9`.
- Comment in both: *"Change a formula → regenerate this fixture and update BOTH sides."*

### A7 — Test coverage
Extend `test_signal_evidence_institutional_metrics.py`:
- Perfect-correlation stream → `beta≈known`, `r2≈1`.
- Flat equity → `beta≈0`, `alpha≈0`, reason reflects low nonzero days.
- Benchmark unavailable → alpha fields `None`, `alpha_reason="benchmark_unavailable"`, no exception.
- n<30 → distribution metrics compute but `min_sample_pass=False`.
- Trade-Sharpe freq annualization matches `mean/std*sqrt(n_trades/years)`.

---

## PART B — S/R integration (institutional worktree UI)

`feature/sr-desk-grade` changes overlay `status` from `"ready"` to a decision string (`"actionable"`/`"research_only"`/…). The UI at `signal-evidence-tab.tsx:152` gates on `status === "ready"` and will blank the overlay after merge.

**B1 — Tolerate both contracts** in `SrOverlaySummary`:
```
const decision = overlay.decision ?? overlay.status
const ready = (overlay.status === "ready" || decision === "actionable") && overlay.overlay_metrics
```
Add `decision`, `validation`, `reason` as optional fields to the overlay schema in `api.ts`. When `decision` is present but not `"actionable"`, render a muted badge with `overlay.reason` (e.g. `"failed_validation_gates"`) instead of hiding — a tested-and-rejected overlay is information.

**B2 — Empirical gate check (run and report, in the `sr-desk-grade` worktree):**
```
python analysis/sr_overlay_uplift_study.py
```
Report actionable vs research_only counts in the PR. If ~everything is `research_only`, that is the gate correctly reporting no post-cost edge — **do not loosen thresholds to manufacture actionable results.** Flag for human review.

---

## Acceptance criteria
- [ ] `pytest services/api/tests/test_signal_evidence_institutional_metrics.py` green (incl. alpha/beta + parity).
- [ ] `node --test frontend/lib/signal-evidence-range.test.mjs` green (incl. golden fixture).
- [ ] `pytest services/api/tests/test_strategy_signals_variant_detail.py services/api/tests/test_strategy_signals_support_resistance.py` green.
- [ ] `node --check frontend/lib/signal-evidence-range.js` clean.
- [ ] `git diff --check` clean (CRLF ok).
- [ ] No metric present in both Py and JS lacks a golden-fixture assertion.
- [ ] `min_sample_pass=false` hides Sortino/Calmar/vol/tail/alpha-beta and shows the audit note.
- [ ] `graphify update .` run in the worktree.
- [ ] PR description states the A5 basis note ("effective-book beta, not stock beta") and the B2 uplift-study numbers.

**Out of scope:** Portefeuille tab, the `forward-estimate-layer` tree, any `research/edge` threshold changes.

## Design decisions locked
1. **Effective-book beta** (regress the traded equity path), not the underlying stock's beta — this is the book's real market exposure for a long-only MASI book.
2. **Linear ×252 alpha annualization** (standard for excess-return alpha), not geometric.
