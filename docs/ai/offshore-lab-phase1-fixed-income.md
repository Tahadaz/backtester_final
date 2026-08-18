# Implementation brief — Offshore Markets Lab, Phase 1: Fixed-income calculation engine

**For:** Codex (implementation agent). This brief is self-contained; everything needed is here or in the repository.
**Scope:** Phase 1 only. Do not build curves, credit spreads, FX, commodities, persistence, or anything from later phases (`docs/offshore-lab/00-response.md` describes them for context only).
**Hard rule:** do not modify any existing equity/signal/dashboard functionality. Only touch the files listed in "Files to create/modify".

## Goal

A stateless fixed-rate bullet-bond calculator: the user enters a bond and a quote (yield or price), the app returns the full analytics set (cash flows, accrued, clean/dirty price, YTM, current yield, Macaulay/modified duration, convexity, DV01, yield-shock scenarios, holding-period carry) with an educational transparency envelope. No database changes, no migrations, no worker changes.

## Repository context (verified)

- Backend: FastAPI. App factory `create_app()` in `services/api/app/main.py`; routers live in `services/api/app/routers/` and are registered in `main.py`; they use API-key auth (`Depends(auth.require_api_key)` — copy the pattern from any existing router, e.g. `services/api/app/routers/analytics.py`).
- Pure quant code lives in the installable package `core/quant_core/` and must not import SQLAlchemy, FastAPI, or app settings.
- Frontend: Next.js App Router in `frontend/app/`, TypeScript. API calls go through `frontend/lib/api.ts` (zod schemas + fetchers, SWR for GET-style data; a plain POST helper is fine here) and are proxied via `frontend/app/api/[...path]/`. UI components in `frontend/components/`, shadcn-style primitives in `frontend/components/ui/`.
- Tests: pytest. Core tests in `core/tests/`, API tests in `services/api/tests/` (FastAPI TestClient patterns are already used there). Frontend tests are optional for this slice.

## Files to create

```
core/quant_core/fixed_income/__init__.py      # re-export public API
core/quant_core/fixed_income/daycount.py
core/quant_core/fixed_income/cashflows.py
core/quant_core/fixed_income/pricing.py
core/quant_core/fixed_income/riskmeasures.py
core/quant_core/fixed_income/scenarios.py
services/api/app/schemas/offshore_lab.py
services/api/app/routers/offshore_lab.py
frontend/app/offshore-lab/page.tsx
frontend/components/offshore/bond-form.tsx
frontend/components/offshore/bond-analytics-panel.tsx
frontend/components/offshore/cashflow-table.tsx
frontend/components/offshore/shock-scenario-table.tsx
frontend/components/offshore/interpretation-block.tsx
core/tests/test_fixed_income_daycount.py
core/tests/test_fixed_income_pricing.py
core/tests/test_fixed_income_risk.py
core/tests/test_fixed_income_scenarios.py
services/api/tests/test_offshore_lab_router.py
```

## Files to modify (minimally)

- `services/api/app/main.py`: register the new router (one `include_router`, same pattern as the others).
- `frontend/lib/api.ts`: zod schemas + two POST fetchers.
- The sidebar/navigation component where `dashboard`/`signals` links are declared (locate it under `frontend/components/`): add one entry "Offshore Lab" → `/offshore-lab`.

## Core module specification (`core/quant_core/fixed_income/`)

Pure functions, dataclasses/plain types only, `datetime.date` for dates, `float` for money (per-100 quotation).

### `daycount.py`

```python
def year_fraction(start: date, end: date, convention: str) -> float
```

Conventions (exact strings): `"30E/360"`, `"ACT/ACT-ICMA"`, `"ACT/365F"`.
- `30E/360` (Eurobond basis): d1=min(d1,30), d2=min(d2,30); ((y2−y1)·360 + (m2−m1)·30 + (d2−d1))/360.
- `ACT/ACT-ICMA` is period-relative; expose the ICMA form as
  `accrual_fraction_icma(start, end, period_start, period_end, frequency) -> float` = actual_days(start,end) / (frequency · actual_days(period_start,period_end)); `year_fraction` may raise for ICMA to force callers to use the period-aware function.
- `ACT/365F`: actual days / 365.

### `cashflows.py`

```python
@dataclass(frozen=True)
class BondDefinition:
    face_value: float          # default 100.0
    currency: str              # ISO code, display only
    coupon_rate: float         # decimal p.a., e.g. 0.05
    coupon_frequency: int      # 1 or 2
    maturity_date: date
    day_count: str             # one of the three conventions
    redemption: float = 100.0  # per 100 face

@dataclass(frozen=True)
class CashFlow:
    date: date
    amount: float              # per 100 face
    kind: str                  # "coupon" | "redemption"

def generate_schedule(bond: BondDefinition, settlement: date) -> list[CashFlow]
```

- Coupon dates generated **backwards from maturity** at 12/frequency-month steps (use month arithmetic, clamp day-of-month, e.g. via `dateutil.relativedelta` if already a dependency, else implement clamped month-add).
- Include only flows strictly after settlement. Final flow includes redemption.
- Regular coupon amount per 100: `100 · coupon_rate / frequency` (this holds for all three conventions on regular periods; do not recompute regular coupons via day count).
- Also expose `previous_coupon_date(bond, settlement) -> date` (the notional coupon date ≤ settlement, from the same backward roll) for accrued interest.

### `pricing.py`

```python
def accrued_interest(bond, settlement) -> float
def dirty_price(bond, settlement, ytm: float) -> float
def clean_price(bond, settlement, ytm: float) -> float
def yield_to_maturity(bond, settlement, clean: float | None = None, dirty: float | None = None) -> float
def current_yield(bond, clean: float) -> float          # annual coupon per 100 / clean
```

- Discounting: periodic compounding at coupon frequency f. For a flow at time t (in periods from settlement): `DF = (1 + y/f)^(−t)`. Period count t for the first flow uses the fractional period from settlement to next coupon (day-count-consistent: ICMA fraction for ACT/ACT-ICMA; for 30E/360 and ACT/365F use year_fraction(settlement, next_coupon)/ (1/f) capped to [0,1]); subsequent flows add whole periods. This is standard street convention.
- Accrued: `100 · coupon_rate / f · accrual_fraction(prev_coupon, settlement within the current period)` using the bond's convention (ICMA period-aware where applicable).
- YTM solver: Newton–Raphson with analytic derivative, fall back to bisection on [−0.99, 10.0] if Newton fails to converge in 50 iterations; convergence when |P(y) − P_target| < 1e−10 (dirty-price space). Raise `ValueError` with a clear message if unbracketed.
- Yield is quoted per annum, compounded at coupon frequency (semiannual bond-equivalent for f=2).

### `riskmeasures.py`

```python
@dataclass(frozen=True)
class RiskMeasures:
    macaulay_duration: float   # years
    modified_duration: float   # years, MacDur / (1 + y/f)
    convexity: float           # years^2, standard second-derivative convexity
    dv01_per_100: float        # price change per 100 face for 1bp, positive number
def risk_measures(bond, settlement, ytm) -> RiskMeasures
```

- Macaulay: cash-flow-weighted average time in years (period times / f).
- DV01 computed **analytically** as `modified_duration · dirty_price · 0.0001` (tests compare it against central-difference repricing).

### `scenarios.py`

```python
@dataclass(frozen=True)
class ShockResult:
    shock_bp: float
    exact_clean: float
    exact_pnl_per_100: float           # vs base dirty price, exact repricing
    approx_pnl_duration: float          # −ModDur·P·Δy
    approx_pnl_duration_convexity: float  # + 0.5·C·P·Δy²
    approx_error: float
def shock_table(bond, settlement, base_ytm, shocks_bp: list[float]) -> list[ShockResult]
def carry(bond, settlement, base_ytm, horizon_days: int) -> dict
```

- `carry`: unchanged-yield carry — coupon income received in the horizon plus pull-to-par (dirty price at horizon date, same yield) minus starting dirty price; return components separately (`coupon_income`, `pull_to_par`, `total_per_100`). Label in docstring: this excludes roll-down (needs a curve; later phase).

## API specification

Two endpoints in `services/api/app/routers/offshore_lab.py`, prefix `/offshore-lab`, API-key auth like existing routers. Pydantic models in `services/api/app/schemas/offshore_lab.py`.

1. `POST /offshore-lab/bond/analytics`
   Request: `{ bond: BondDefinitionIn, settlement_date: date, quote: { type: "yield" | "clean_price" | "dirty_price", value: float }, notional: float = 1_000_000 }`
   Response: transparency envelope (below) with `results` containing: `ytm`, `clean_price`, `dirty_price`, `accrued_interest`, `current_yield`, `macaulay_duration`, `modified_duration`, `convexity`, `dv01_per_100`, `dv01_position` (scaled by notional/100), `cashflows: [{date, amount, kind}]`.
2. `POST /offshore-lab/bond/scenarios`
   Request: analytics request + `shocks_bp: list[float]` (default `[-100,-50,-25,-10,-1,0,1,10,25,50,100]`) + `holding_period_days: int | None`.
   Response: envelope with `results.shock_table` (list of ShockResult fields, plus position-scaled P&L) and `results.carry` when horizon supplied.

**Transparency envelope** — every response has exactly these top-level fields:

```json
{
  "inputs": { /* echo of the request */ },
  "methodology": "Discounted cash flows at a flat yield compounded at coupon frequency; Newton-Raphson YTM solver; analytic duration/convexity/DV01.",
  "data_source": "user-entered",
  "calculation_date": "<server date ISO>",
  "assumptions": ["bullet redemption", "no default or optionality", "flat yield to maturity", "<day_count> day count", "yield compounded <frequency>x per year"],
  "units": { "prices": "per 100 face", "ytm": "decimal per annum", "durations": "years", "convexity": "years^2", "dv01_per_100": "<currency> per 1bp per 100 face", "dv01_position": "<currency> per 1bp for notional" },
  "warnings": [ /* e.g. "settlement within 30 days of maturity: duration approximations degrade" */ ],
  "results": { ... },
  "interpretation": "<generated sentence(s)>"
}
```

Interpretation must be generated from the actual numbers, notional, and currency, e.g.: *"A position DV01 of 72.10 MAD means this 1,000,000 MAD position gains or loses approximately 72 MAD for each 1 basis-point parallel move in its yield. The duration approximation assumes small moves; for ±100bp the convexity term matters (see scenario table)."*

Validation errors (settlement ≥ maturity, coupon_rate < 0, frequency ∉ {1,2}, unknown day_count, quote value ≤ 0 for prices) → HTTP 422 with a message naming the offending field.

## Frontend specification

- `frontend/app/offshore-lab/page.tsx`: page titled "Offshore Markets Lab — Calculateur obligataire" (app is French-labelled; keep French labels, English financial terms are fine, e.g. "DV01", "duration").
- `bond-form.tsx`: inputs for all BondDefinition fields + settlement date + quote type/value + notional; sensible defaults (100 face, annual, 30E/360, T+2 settlement, yield quote).
- `bond-analytics-panel.tsx`: results grid; each metric row has label, value with unit, and an info tooltip explaining what it means and how a trader uses it (source the text from the envelope's `units` + short static explainers).
- `cashflow-table.tsx`, `shock-scenario-table.tsx`: plain tables (shadcn table primitives from `frontend/components/ui/`); the shock table shows exact vs duration vs duration+convexity P&L and the approximation error per shock.
- `interpretation-block.tsx`: renders `methodology`, `assumptions`, `warnings`, `interpretation` from the envelope, always visible (not hidden behind a tooltip).
- Wire via `frontend/lib/api.ts` with zod schemas mirroring the response envelope. Client-side validation minimal; trust server 422 messages.

## Tests (must all pass; expected values to 4 decimal places)

`core/tests/test_fixed_income_pricing.py` — textbook vectors (settlement on a coupon date so accrued = 0; pick e.g. settlement 2026-07-15, annual coupons every 07-15, maturity 2031-07-15 for the 5y cases; use 30E/360 unless stated):

| Case | Expected |
|---|---|
| 5y, 5% annual, YTM 5% | clean = 100.0000 (par identity) |
| 5y, 6% annual, YTM 4% | clean = 108.9036 |
| 5y, 4% annual, YTM 6% | clean = 91.5753 |
| 10y zero (coupon_rate 0, f=1), YTM 5% | clean = 61.3913; MacDur = 10.0000; ModDur = 9.5238 |
| 10y, 8% semiannual, YTM 6% (BEY) | clean = 114.8775 |
| Accrued, 6% annual, 30E/360, exactly half a period elapsed | accrued = 3.0000 |

`core/tests/test_fixed_income_pricing.py` (round-trips) and `test_fixed_income_risk.py` / `test_fixed_income_scenarios.py` (properties):
- price→yield→price round-trip within 1e−8 for all vector bonds and for premium/discount/near-maturity (3-month remaining) bonds.
- price strictly decreasing in yield; convexity > 0 for all vector bonds.
- `dv01_per_100` ≈ (P(y−1bp) − P(y+1bp))/2 within 1e−6 per 100.
- duration-only approximation error grows with |Δy| and adding the convexity term reduces |error| for ±100bp shocks.
- carry components sum to total; zero horizon → zero carry.
- invalid inputs raise (`settlement ≥ maturity`, negative coupon, unknown convention).

Optional independent cross-check: if `QuantLib` is importable (`pytest.importorskip`), reprice the 5y 6%/4% and 10y 8% semi/6% cases with QuantLib and assert agreement within 1e−4 per 100. Add `QuantLib` to `requirements-dev.txt` only (never a runtime dependency).

`services/api/tests/test_offshore_lab_router.py` (TestClient):
- analytics endpoint from yield and from clean price agree with core functions;
- all envelope fields present and non-empty;
- 422 paths return field-naming messages;
- scenarios endpoint: shock 0 has zero P&L; table length matches request.

## Acceptance criteria

1. All new tests pass; the full existing test suite still passes (`pytest core/tests services/api/tests`).
2. `core/quant_core/fixed_income/` imports nothing from `services/`, SQLAlchemy, or FastAPI.
3. No database models or migrations added; no existing files modified beyond the three listed.
4. The page at `/offshore-lab` renders, computes a bond end-to-end against the running API, and displays cash flows, analytics, shock table, and the interpretation block.
5. Every numeric shown in the UI has a visible unit.
