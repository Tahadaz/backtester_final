# Doc 55 — Perfect-foresight IC study: would forward seeding of the intrinsic models ever have worked?

**Status:** RESEARCH RESULT — read-only study, no production changes.
**Date:** 2026-07-02.
**Script:** `services/api/scripts/perfect_foresight_ic.py` (uncommitted research script).
**Predecessors:** brief 48 (PIT IC backtest → `core/quant_core/fundamentals/ic_ensemble_weights.json`, 2026-06-20: ddm IC = −0.188, residual_income IC = 0.0 → both carry **zero** ensemble weight), brief 54 (forward-estimate seeding of `build_projection()` via `forward_net_income` / `forward_revenue` / `forward_fiscal_year`).

---

## 1. Question

Brief 54 seeds the year-1 net income (and revenue path) of the intrinsic models — **ddm, residual_income, fcff_dcf** — from consensus forward estimates. Real consensus rows (`fundamental_consensus_estimate`) only exist as of 2026, so a true point-in-time replay of the *seeded* models is impossible for history.

This study answers the next-best question empirically: **if the forward seed had been perfectly accurate — the realized next-fiscal-year NetIncome/Revenue, unknowable at the as-of date — would the seeded models have produced positive cross-sectional IC against 12-month forward returns on MASI?**

Perfect foresight is a deliberate, isolated leakage that **upper-bounds** what any real consensus feed could contribute. If even perfect knowledge of next year's earnings doesn't produce IC, the zero ensemble weights are structural, not a data-availability artifact.

## 2. Method

Everything except the seed is strictly PIT and reuses `core/quant_core/fundamentals/pit_ic_backtest.py` verbatim (same loaders, `_filter_pit_history` with its look-ahead assertion, `_build_pit_snapshot`, PIT prices from the market-data store, survivorship-free universe from `data/universe/bvc_pit_universe.csv`, Spearman IC per period with the ≥5-pair cutoff, Newey–West t on the IC series).

For each `(symbol, T)`, `T ∈ {2020…2024}` (forward window ends 2025-12-31; T=2025 has no forward price):

- **Arm A (baseline):** `compute_symbol_valuations()` with default assumptions — byte-for-byte the call the brief-48 backtest makes.
- **Arm B (seeded):** identical call plus the exact assumptions-dict keys the live path injects (`services/api/app/services/fundamentals.py` → `consensus.load_forward_view`):
  - `forward_fiscal_year = L + 1` where `L` = latest PIT statement year (mirrors the live anchor `_fwd_year = latest_statement_year + 1`);
  - `forward_net_income` = **realized** NetIncome for FY `L+1`, read from the full (non-PIT) history through the projection layer's own `_pick_best_row_per_year` alias/outlier resolution;
  - `forward_revenue` = realized Revenue for FY `L+1` when positive.

**Pairing discipline:** a `(symbol, T, model)` observation enters the IC computation only if **both** arms produced a finite, non-`unavailable` upside — the comparison is exactly paired. A symbol enters a period only if realized forward NI exists and is > 0 (the projection's `_fwd_ni_seeded` gate requires `_fwd_ni > 0`; 12 symbol-periods dropped for non-positive forward NI, 2 for missing).

No parameter fitting, no optimization, single pre-registered run.

## 3. Results (paired, FY2020–FY2024 as-of dates, 12-month forward returns)

2020 produced 0 model pairs (same as the brief-48 baseline run), so 4 effective periods for ddm/residual_income/relative_multiples and 3 for fcff_dcf.

| model | arm | periods | pairs | mean IC | IC std | t-stat | per-period IC (2021 / 2022 / 2023 / 2024) |
|---|---|---:|---:|---:|---:|---:|---|
| **ddm** | baseline | 4 | 119 | **−0.239** | 0.176 | −3.85 | −0.321 / −0.383 / +0.014 / −0.264 |
| | perfect-foresight | 4 | 119 | **+0.078** | 0.409 | 0.57 | +0.643 / −0.333 / +0.025 / −0.023 |
| | Δ (seeded − base) | | | +0.316 | | | seeded > 0 in **2/4** periods |
| **residual_income** | baseline | 4 | 106 | **−0.180** | 0.379 | −1.17 | −0.700 / +0.029 / +0.160 / −0.210 |
| | perfect-foresight | 4 | 106 | **+0.126** | 0.356 | 1.04 | −0.300 / +0.543 / +0.241 / +0.021 |
| | Δ (seeded − base) | | | +0.307 | | | seeded > 0 in **3/4** periods |
| **fcff_dcf** | baseline | 3 | 73 | **+0.302** | 0.260 | 2.62 | — / +0.600 / +0.179 / +0.126 |
| | perfect-foresight | 3 | 73 | **+0.485** | 0.361 | 3.22 | — / +0.900 / +0.245 / +0.309 |
| | Δ (seeded − base) | | | +0.183 | | | seeded > 0 in **3/3** periods |
| **relative_multiples** (ref) | baseline | 4 | 143 | +0.232 | 0.043 | 20.5 | +0.283 / +0.182 / +0.247 / +0.216 |
| | perfect-foresight | 4 | 143 | +0.231 | 0.043 | 19.8 | (unchanged; see §4 spillover note) |

Cross-section sizes: 5–9 names per model in 2021–22, 42–54 in 2023–24 (per-period pair counts in the results JSON). Seed fired for 5/6/8/52/64 symbols in 2020–2024 respectively.

## 4. Diagnostics and caveats

- **Seed non-firing (18 symbol-periods, mostly banks pre-2023):** ATW/BCP/CDM at early as-of dates have no PIT PNB history, so `_build_bank_projection` returns an empty projection and the seed cannot fire — *the live consensus path would behave identically*, so these names stay in the paired set with both arms equal. This dilutes the seeded arm toward baseline, i.e. the reported seeded ICs are conservative for the covered subset.
- **relative_multiples spillover (−0.001):** its EV/EBITDA leg can read normalized projection EBITDA in capex-heavy contexts (`ev_ebitda_uses_normalized_projection_ebitda`), which the seeded revenue path slightly moves for a couple of names in 2023. Negligible; confirms the reference model is otherwise seed-invariant.
- **Statistical honesty:** 4 (3 for fcff) annual periods; the 2021–22 cross-sections are 5–9 names, so single-period ICs there are ±0.3–0.7 noise (ddm's +0.643 in 2021 is 7 names). t-stats on a 3–4 point IC series are indicative only. The IC std of the seeded ddm arm (0.41) exceeds its mean fourfold.
- **Upper bound by construction:** these are *perfect-foresight* numbers. A real consensus feed carries forecast error, coverage gaps, and publication lag; realized ICs from actual consensus will be strictly worse than this ceiling.

## 5. Verdict against the pre-stated decision rule

> Rule: perfect-foresight IC for ddm/residual_income ~0 or negative → zero weights are **structural**; keep band/reference framing. Materially positive (right sign in most periods, non-trivial magnitude) → seeded models earn provisional shrunk weight; re-estimate once real consensus history accrues.

- **ddm — zero weight is STRUCTURAL.** Even with perfect knowledge of next-year net income, mean IC is +0.08 with sign instability (positive in only 2/4 periods, IC std 0.41, t = 0.57), and the mean is carried by one 7-name period (2021: +0.64). Dividends do not price MASI at a 12-month horizon; no realistic consensus feed can rescue this model. Keep it at zero weight / band-reference display.
- **residual_income — borderline, watch-list, no weight yet.** Perfect foresight flips it from −0.18 to +0.13 with the right sign in 3/4 periods (t ≈ 1.0). That meets the letter of "right sign in most periods, non-trivial magnitude" — but it is an *upper bound* on a 4-period sample, and a realistic consensus would land somewhere between −0.18 and +0.13. Recommendation: **do not grant weight now**; re-estimate with real consensus rows once ≥2 fiscal years of consensus history accrue (earliest useful re-run: after FY2027 forward returns close). This is the one intrinsic model where seeding is economically capable of mattering.
- **fcff_dcf — seeding helps a model that already earns weight.** +0.30 → +0.48, improved in every period. This supports keeping the brief-54 forward seeding live on the fcff path (where the live IC weights already assign it 0.54).
- **Framing consequence:** even at the perfect-foresight ceiling, ddm (+0.08) and residual_income (+0.13) remain below relative_multiples' unseeded, stable +0.23 (IC std 0.04). The band/reference framing of the fundamentals layer stands; forward seeding is an accuracy upgrade for the fcff/comparables complex, not a rehabilitation path for DDM.

## 6. Reproduction

```
.venv/Scripts/python.exe services/api/scripts/perfect_foresight_ic.py \
    --years 2020 2021 2022 2023 2024 --json <out.json>
```

DB access is read-only (reuses `pit_ic_backtest` loaders; DB `127.0.0.1:5555/quant`, prices from the MinIO market-data store). Raw results JSON archived with the session scratchpad (`perfect_foresight_ic_results.json`).
