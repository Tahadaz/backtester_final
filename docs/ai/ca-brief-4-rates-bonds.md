# Codex Brief 4 — Rates & bonds vertical

**Program:** `docs/cross-asset-product/00-program-plan.md` — §4 guardrails, §5 reuse, §6 invariants binding.
**Prerequisite:** Briefs 1–3 merged and green.
**Base spec:** `docs/ai/offshore-lab-phase1-fixed-income.md` for the calculator. The rates sleeve (§5 below) has no prior spec — it is new here.
**Scope:** three connected pieces — the bond calculator's math, the calculator product surface, and the `bond_duration` return kind that finally connects bonds to the backtest engine.
**Ship gate:** `pytest core/tests/test_fixed_income_*.py` green; the calculator route returns full analytics; a bond TSM run completes through the Brief 1 engine.

> **§3 is removable.** Program §7 records that `core/quant_core/fixed_income/` was left a RED scaffold on purpose, because the module bodies were meant to be hand-written as trader-prep Build 1. If the owner reclaims that, delete §3 and build everything else — the tests in `core/tests/test_fixed_income_*.py` are the interface either way, and nothing else in this brief moves.

## 1. Guardrails (binding)

Program §4 verbatim. Do not explore the repo; do not read `graphify-out/*`; create nothing outside §6; modify nothing outside §7. **No new frontend components in `components/cross-asset/`** — the rates tab lights up by adding `"rates"` to the Brief 2 components. The calculator is the one exception: it is a stateless tool with no run record, so it gets its own small route and components (§4).

## 2. Why this brief is ordered last

`bond_duration` (§5) needs duration and convexity at every historical date, and those come from the calculator's `risk_measures`. Building the calculator first and the sleeve second means the bond math is written once and used twice. Do not shortcut §5 with a hardcoded duration constant.

## 3. Fixed-income module bodies — *removable, see banner*

`core/quant_core/fixed_income/` currently has five modules where every function raises `NotImplementedError`. Fill the bodies. **Do not change any signature** and do not touch the test files — they are the acceptance harness and they were written first.

The public API, from `core/quant_core/fixed_income/__init__.py`:

| Module | Functions |
|---|---|
| `daycount.py` | `year_fraction`, `accrual_fraction_icma` |
| `cashflows.py` | `BondDefinition`, `CashFlow`, `generate_schedule`, `previous_coupon_date` |
| `pricing.py` | `accrued_interest`, `dirty_price`, `clean_price`, `yield_to_maturity`, `current_yield` |
| `riskmeasures.py` | `RiskMeasures`, `risk_measures` |
| `scenarios.py` | `ShockResult`, `shock_table`, `carry` |

The docstrings already in those files are the spec — follow them exactly. The load-bearing ones:

- **Discounting** is periodic compounding at coupon frequency `f`: a flow `t` periods from settlement has `DF = (1 + y/f)^(-t)`. The first flow's `t` is the day-count-consistent fractional period from settlement to the next coupon; each later flow adds a whole period.
- **`accrued_interest`** = `100 · coupon_rate / f · accrual_fraction(prev_coupon → settlement)`, using the bond's own convention (period-aware ICMA where applicable). Zero on a coupon date.
- **`yield_to_maturity`**: Newton-Raphson with analytic derivative; fall back to bisection on `[-0.99, 10.0]` if Newton has not converged in 50 iterations. Converged when `|P(y) − P_target| < 1e-10` in dirty-price space. `ValueError` with a clear message if the target is not bracketed. Exactly one of `clean`/`dirty` must be supplied.

Pure functions only: no I/O, no DB, no FastAPI. `datetime.date` for dates, `float` for money, per-100 quotation.

**Acceptance for this section:** all four existing test files pass unmodified, including the property tests (price falls when yield rises; `dirty = clean + accrued`; duration approximation error grows with `|Δy|` and convexity absorbs most of it).

## 4. Calculator product surface

Per the base spec. Stateless: no DB, no migration, no worker.

Endpoints on a new router, existing API-key auth: one to price a bond from a quote (yield or price) returning the full analytics set — cash flows, accrued, clean/dirty, YTM, current yield, Macaulay/modified duration, convexity, DV01, yield-shock scenarios, holding-period carry — with the transparency envelope, and one for the shock table. Unavailable values are `null`.

Route `/offshore-lab`: bond input form, analytics panel, cash-flow table, shock-scenario table, interpretation block. French labels, English quant terms, visible units.

## 5. Rates sleeve — `bond_duration` return kind (new spec)

This is the piece that makes bonds a first-class asset class in the engine rather than a calculator off to one side.

**The problem.** Rates arrive as **levels, not prices**. `^TNX` is stored as an OHLCV `Close` (`core/quant_core/macro.py:147`), and FRED `DGS*` series are par yields. A naive `pct_change` on a yield is financially meaningless — this is flagged as a blocker in the master design (`docs/offshore-lab/01-cross-asset-research-lab.md` §3) and is exactly what Brief 1's `NotImplementedError("bond_duration: Brief 4")` was reserving space for.

**The construction.** For a constant-maturity par-yield series, synthesize a par bond at each date and convert the yield change into a return:

```
r_t  =  y_{t-1} · τ                    (carry — accrual over the period)
      −  D_mod(t-1) · Δy_t             (duration — the first-order price move)
      +  0.5 · C(t-1) · (Δy_t)²        (convexity — the second-order correction)
```

- `D_mod` and `C` come from `risk_measures` on a par bond struck at `y_{t-1}` with the series' maturity — **not** a constant. This is the reuse §2 is about.
- Every input is lagged: the return over `(t-1, t]` uses risk measures known at `t-1`. Program §6.2 applies, and the shift test must cover this path.
- `τ` is the day-count fraction for the period, explicit in `ReturnSpec`, not implied.
- Excess return subtracts the cash rate; state whether the series is total or excess in the envelope.

**Data.** FRED `DGS2`, `DGS5`, `DGS10`, `DGS30`, via the Brief 2 `datasources.py` FRED path (same key handling, same loud failure when absent).

**Strategies.** The same TSM and carry signals from Brief 1, on the bond return series — no new signal code. Carry for a bond sleeve is the roll-down-adjusted yield pickup over the holding period.

**Honesty constraint.** A duration-approximated par-bond return is a **model**, not a traded instrument. `replication_fidelity = "adapted"`, and every run carries a `warnings` entry saying the return series is duration-approximated from par yields rather than reconstructed from traded bond or futures prices. This is not optional garnish — it is the difference between a defensible sleeve and a misleading one.

## 6. Files to create

```
services/api/app/schemas/offshore_lab.py
services/api/app/routers/offshore_lab.py
frontend/app/offshore-lab/page.tsx
frontend/components/offshore/bond-form.tsx
frontend/components/offshore/bond-analytics-panel.tsx
frontend/components/offshore/cashflow-table.tsx
frontend/components/offshore/shock-scenario-table.tsx
frontend/components/offshore/interpretation-block.tsx
core/quant_core/cross_asset/rates.py                 # par-bond return construction (§5)
services/api/tests/test_offshore_lab_router.py
core/tests/test_ca_rates.py
```

## 7. Files you may modify (nothing else)

- `core/quant_core/fixed_income/*.py` — bodies only, **signatures unchanged** (§3; skip if §3 is deleted)
- `core/quant_core/cross_asset/returns.py` — `bond_duration` now delegates to `rates.py`; dispatch signature unchanged
- `services/api/app/main.py` — one `include_router` for the calculator
- `services/api/app/services/cross_asset/datasources.py` — add the FRED `DGS*` path
- The Brief 2 cross-asset components — handle `"rates"`
- `frontend/lib/api.ts` — schemas/fetchers for the calculator and the rates sleeve
- The sidebar/nav component — one entry "Offshore Lab" → `/offshore-lab`

## 8. Tests

- `core/tests/test_fixed_income_*.py` — the four existing files, **unmodified**, green.
- `test_ca_rates`: the decomposition reproduces a hand-computed return on a synthetic yield path; the convexity term has the right sign for both a rally and a selloff; duration is recomputed per date (a test that fails if you hardcode a constant); the lag test — risk measures at `t-1` only.
- `test_offshore_lab_router`: full analytics payload; a bad quote returns a structured `422`; envelope fields present.
- Extend the cross-asset router test with a rates run that completes and carries the duration-approximation warning.

## 9. Acceptance

1. All four `test_fixed_income_*` files pass unmodified.
2. `/offshore-lab` prices a bond and shows cash flows, risk measures and shock scenarios.
3. A bond TSM run completes through the **Brief 1 engine** with `ReturnSpec.kind="bond_duration"`, and its warning states the return is duration-approximated.
4. Duration and convexity are recomputed per date from `risk_measures` — no hardcoded constant.
5. Zero new components under `components/cross-asset/`.
6. No file outside §6/§7 created or modified; full suite green.
