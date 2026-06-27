# Fundamentals v3 resolved issue log

This file is now a historical review log for the fundamentals engine. The 21 issues below were the v2 review surface and have been implemented in v3 across valuation, scoring, persistence, API, frontend contracts, and tests.

When an issue body says "current implementation", read that as **pre-v3 behavior**. Current v3 behavior is summarized here:

- **V1-V6:** valuation math now uses debt-flow-adjusted FCFE when possible, sustainable DDM growth, residual-income spread fade, FCF-growth preference, explicit net-debt bridge warnings, and justified-multiple growth fade.
- **V13 / V14:** DDM now uses an H-model fade instead of mixing growth rates inside one Gordon formula, and residual income now keeps year 1 at full ROE before fading to zero spread. V2 and V3 below are kept for history and marked **superseded by V13 / V14**.
- **V7-V12:** defaults now use 8.51% WACC, valuation/ensemble rows carry currency, reverse DCF is diagnostic-only, ensembles include model-dispersion and Monte Carlo bands, bear/base/bull scenarios persist, and a sensitivity matrix endpoint exists.
- **Brief 34:** the systematic over/under-valuation remediation is shipped. Fabricated zero fair-value floors now return unavailable, operational projection drivers use observed history -> peer median -> unavailable, price-anchored implied-price clamps and family/base-weight heuristics are retired, cyclical issuers use mid-cycle observed normalization, ensemble confidence is additive, and the recommendation ladder is expected-return-versus-cost-of-equity.
- **Brief 38:** display-facing valuation is gated by source-data verification. The tie-out layer recomputes balance sheet equality, group-basis BVPS/ROE, income-label consistency, vintage consistency, reused integrity checks, and plausibility from raw annual lines. Curated official corrections carry document URL plus page/line/label provenance. Symbols that cannot tie out are persisted as `data_unverified` and return NR rather than a fabricated or clamped fair value.
- **S1-S9:** scoring now uses non-overlapping pillar metric sets, sector buckets with market fallback, minimum cohort rules, dividend as a diagnostic, true balance-sheet health, quality audit components, partial-coverage fields, magnitude diagnostics, and trailing-average diagnostics.

The over/under-valuation entries closed by Brief 34 are kept below as historical review context only. They should not be read as current behavior.

**Severity legend:**
- 🔴 **Logic concern** — math doesn't match textbook, or there's a silent failure mode
- 🟡 **Configuration smell** — a default that's likely wrong in production
- 🔵 **Missing institutional feature** — works as designed but lacks something standard analysts expect

---

## Valuation engine (`core/quant_core/fundamentals/valuation.py`)

### 🔴 V1 — FCFE proxy uses raw FCF

**Where:** `_fcfe_dcf` at `valuation.py:342`.

**Symptom:** the model hard-codes `warnings = ["fcfe_proxy_from_free_cash_flow"]` and treats FCF as FCFE. True FCFE = FCFF − after-tax interest + net borrowing. For leveraged firms this overstates equity value because interest is never deducted.

**Why it matters:** `proxy_weight_cap = 0.25` haircuts the ensemble weight, but the per-model fair value displayed in the UI is still the raw (overstated) number. Analysts looking at the per-model breakdown see misleading data.

**Fix recipe:**

```python
def _fcfe_start(snapshot, history, assumptions):
    """Build FCFE from FCF + interest after tax + net borrowing.
    Returns (fcfe_value, source_label, is_proxy)."""
    fcf, fcf_source = _fcf_start(snapshot, history)
    if fcf is None:
        return None, None, True

    tax_rate = float(assumptions.get("tax_rate", DEFAULT_ASSUMPTIONS["tax_rate"]))
    interest = _latest_metric(history, "Interest_Expense", "Charges_Interets") or 0.0
    interest_after_tax = interest * (1.0 - tax_rate)

    issuance = _latest_metric(history, "Debt_Issuance") or 0.0
    repayment = _latest_metric(history, "Debt_Repayment") or 0.0
    net_borrowing = issuance - repayment

    # If we have NO debt-flow data, fall back to proxy (current behaviour)
    if interest == 0.0 and issuance == 0.0 and repayment == 0.0:
        return fcf, fcf_source, True

    fcfe = fcf - interest_after_tax + net_borrowing
    return fcfe, f"{fcf_source}_adjusted_for_debt_flows", False
```

Then in `_fcfe_dcf`:
- When `is_proxy=True` → keep current behaviour (warning + capped weight).
- When `is_proxy=False` → drop the proxy warning, no weight cap, `base_confidence = "high"` if 3+ years of FCF history, else `"medium"`.

**Acceptance:** a symbol with `Interest_Expense` and `Debt_Issuance` populated produces an FCFE DCF with `is_proxy=False` and a fair value that differs from the FCFF DCF by the after-tax interest + net borrowing delta. For an unleveraged firm the two converge.

---

### 🔴 V2 — DDM growth uses NetIncome_Growth instead of sustainable growth  *(superseded by [V13](#-v13--ddm-mixes-two-growth-rates-in-a-single-stage-gordon-formula))*

**Where:** `_ddm` at `valuation.py:392`.

**Symptom:** `growth = _growth(snapshot.metrics.get("NetIncome_Growth") or snapshot.metrics.get("Revenue_Growth"), ...)`.

**Why it matters:** DDM's growth rate should be **dividend** growth, or the sustainable growth `g = ROE × retention_ratio` (Gordon). Using NetIncome_Growth captures earnings growth but ignores payout-policy constraints. A firm paying 80% of earnings out has a sustainable dividend growth ceiling of `ROE × 0.20`, not the full earnings-growth rate.

**Fix recipe:**

```python
def _sustainable_dividend_growth(snapshot, history, assumptions):
    """g = ROE × (1 - payout), capped at growth_cap, floor at -5%."""
    roe = _ratio(snapshot.metrics.get("ROE"))
    payout = _ratio(snapshot.metrics.get("Dividend_Payout"))
    if payout is None or payout < 0 or payout > 1.5:
        payout = float(assumptions["stable_payout_ratio"])
    retention = max(0.0, min(1.0, 1.0 - payout))
    if roe is None:
        # Fallback: use NetIncome growth, but mark as proxy
        return _growth(
            snapshot.metrics.get("NetIncome_Growth")
            or snapshot.metrics.get("Revenue_Growth"),
            float(assumptions["growth_cap"]),
        ), "earnings_growth_proxy"
    g = roe * retention
    g = max(-0.05, min(float(assumptions["growth_cap"]), g))
    return g, "sustainable_growth_from_roe_retention"
```

Use the returned `source_label` to add a warning when the proxy fallback fires.

**Acceptance:** for a Moroccan bank with ROE=15%, payout=55% (default), the implied DDM growth becomes `0.15 × 0.45 = 6.75%`, not whatever NetIncome_Growth reads. For dividend-aristocrat-like profiles with very high payout (>90%), growth approaches zero — matching textbook Gordon.

---

### 🔴 V3 — Residual income has no spread fade  *(superseded by [V14](#-v14--residual-income-fade-starts-at-year-1))*

**Where:** `_residual_income` at `valuation.py:422`.

**Symptom:** `fair = book_value + book_value * (roe - cost) / (cost - terminal_growth)`. The ROE−COE spread is treated as a perpetuity discounted at `(cost − terminal_growth)`.

**Why it matters:** real Ohlson RI fades the spread to zero (or to industry-average ROE) over a competitive-erosion horizon. The current formula gives Moroccan banks with reported ROE=15% and COE=10.5% a `0.045 / 0.075 = 60%` premium to book — perpetually. No competitive erosion is modelled. This is one of the strongest fair-value contributors in the current ensemble for financials, so the over-statement bleeds directly into headline numbers.

**Fix recipe:**

```python
def _residual_income_with_fade(snapshot, current_price, assumptions, scenario, is_financial):
    """RI with linear fade of ROE to terminal ROE over fade_years."""
    cost = float(assumptions["cost_of_equity"])
    terminal_growth = float(assumptions["terminal_growth"])
    fade_years = int(assumptions["fade_years"])
    terminal_roe = cost + terminal_growth  # spread → 0 at terminal year
    pb = _positive(snapshot.metrics.get("Price_to_Book"))
    roe = _ratio(snapshot.metrics.get("ROE"))
    book_value = current_price / pb if current_price and pb else None
    if book_value is None or roe is None or cost <= terminal_growth:
        return _unavailable(snapshot, scenario, "residual_income", current_price, "missing_inputs")

    # Build per-year RI projection with fading ROE
    bv = book_value
    pv_ri = 0.0
    for year in range(1, fade_years + 1):
        fade = year / fade_years
        roe_y = roe * (1.0 - fade) + terminal_roe * fade
        ri = bv * (roe_y - cost)
        pv_ri += ri / ((1.0 + cost) ** year)
        bv = bv * (1.0 + roe_y * (1.0 - float(assumptions["stable_payout_ratio"])))

    # Terminal: residual income at terminal_growth (which is zero spread → zero RI)
    terminal_value = 0.0
    fair = max(0.0, book_value + pv_ri + terminal_value / ((1.0 + cost) ** fade_years))
    return _result(...)
```

**Acceptance:** for ROE=15%, COE=10.5%, terminal_growth=3%, fade_years=5, the fair_value should be materially lower than today's no-fade output (by 10–25% depending on the spread). Symbols where reported ROE ≈ COE produce fair_value ≈ book_value, matching textbook expectation.

---

### 🔴 V4 — FCFF DCF uses revenue growth as FCF-growth proxy

**Where:** `_fcff_dcf` at `valuation.py:318`.

**Symptom:** `growth = _growth(snapshot.metrics.get("Revenue_Growth") or snapshot.metrics.get("NetIncome_Growth"), ...)`.

**Why it matters:** revenue growth and FCF growth diverge during margin transitions. A firm in margin expansion has FCF growing faster than revenue; margin compression has the opposite. The current implementation silently uses revenue growth, biasing fair values during transitional periods.

**Fix recipe:**

```python
def _fcf_growth_input(snapshot, history, assumptions):
    """Prefer reported FCF-style growth signals; fall back to revenue/income."""
    cap = float(assumptions["growth_cap"])
    candidates = [
        ("FCF_Growth", "reported_fcf_growth"),
        ("OperatingCF_Growth", "reported_operating_cf_growth"),
        ("NetIncome_Growth", "earnings_growth_proxy"),
        ("Revenue_Growth", "revenue_growth_proxy"),
    ]
    for metric_name, source in candidates:
        value = snapshot.metrics.get(metric_name)
        if value is not None:
            return _growth(value, cap), source
    # Fall back to series CAGR if metric not present
    fcf_series = _metric_series(history, "Free_Cash_Flow")
    if len(fcf_series) >= 4 and fcf_series[0] > 0:
        cagr = (fcf_series[-1] / fcf_series[0]) ** (1.0 / (len(fcf_series) - 1)) - 1.0
        return max(-0.05, min(cap, cagr)), "fcf_series_cagr"
    return 0.03, "default_3pct_no_data"
```

Use the returned `source` in `inputs["fcf_growth_source"]` so the UI can show the analyst which signal drove the projection.

**Acceptance:** for a symbol with a reported FCF_Growth metric, that's the value used; for a symbol with only Revenue_Growth, that's used with a warning attached.

---

### 🔴 V5 — Net debt fallback to zero overstates equity for leveraged firms

**Where:** `_fcff_dcf` at `valuation.py:319`.

**Symptom:** `net_debt = _latest_metric(history, "NetDebt") or 0.0`.

**Why it matters:** if `NetDebt` is missing from the workbook, the equity bridge silently uses zero, overstating equity value by the entire debt amount. No warning is emitted.

**Fix recipe:**

```python
def _net_debt_bridge(history):
    """Return (net_debt, source_label, has_warning)."""
    nd = _latest_metric(history, "NetDebt")
    if nd is not None:
        return nd, "reported_net_debt", False
    debt = _latest_metric(history, "Total_Debt", "Debt_Total")
    cash = _latest_metric(history, "Cash_and_Equivalents", "Cash")
    if debt is not None and cash is not None:
        return debt - cash, "computed_from_debt_minus_cash", False
    if debt is not None:
        return debt, "debt_only_cash_missing", True
    return 0.0, "missing_net_debt_bridge", True
```

In `_fcff_dcf`, if `has_warning=True`, append `"missing_net_debt_bridge"` to warnings and cap confidence at `"medium"`.

**Acceptance:** a workbook with `Total_Debt=100, Cash=20` produces net_debt=80 with source "computed_from_debt_minus_cash" and no warning. A workbook with neither produces net_debt=0, warning, capped confidence.

---

### 🔴 V6 — Justified multiples clips growth to terminal_growth

**Where:** `_justified_multiples` at `valuation.py:449`.

**Symptom:** `growth = min(terminal_growth, sustainable_growth) if sustainable_growth > terminal_growth else sustainable_growth`. This collapses to `min(terminal_growth, sustainable_growth)` regardless of which branch fires.

**Why it matters:** for genuine growth firms with `sustainable_growth > terminal_growth`, justified P/B and P/E are capped artificially. The post-V6 engine fades from sustainable growth toward terminal growth over `fade_years` instead of clipping immediately to terminal.

**Fix recipe:**

```python
def _justified_growth(sustainable_growth, terminal_growth, fade_years):
    """Linearly fade from sustainable to terminal over fade_years."""
    if sustainable_growth <= terminal_growth:
        return sustainable_growth
    years = max(1, int(fade_years))
    steps = [
        sustainable_growth * (1.0 - i / years)
        + terminal_growth * (i / years)
        for i in range(years + 1)
    ]
    return sum(steps) / len(steps)
```

Use this `_justified_growth` in `_justified_multiples` instead of the current min/branch.

**Acceptance:** for ROE=18%, payout=40% → sustainable=10.8%, terminal=3%, fade=5 → justified growth becomes the linear average ≈ 6.9% (not clipped to 3%). For a defensive sustainable_growth < terminal_growth, behaviour is unchanged.

> ✅ **V6 fix is shipped** — `_justified_growth` is in `valuation.py` and is used by `_justified_multiples`.

---

### 🔴 V13 — DDM mixes two growth rates in a single-stage Gordon formula

**Where:** `_ddm` at `valuation.py:525`.

```python
fair = dividend * (1.0 + growth) / (cost - terminal_growth) if dividend and cost > terminal_growth else None
```

**Symptom:** the numerator uses `growth` (sustainable, ~6 %) returned by `_sustainable_dividend_growth` (the V2 fix). The denominator uses `terminal_growth` (~3 %). Gordon's constant-growth formula requires the same `g` on both sides. No standard model (single-stage Gordon, two-stage, H-model) produces this combination.

**Why it matters:** the result has no clean economic interpretation. For a stock with sustainable = 6 %, terminal = 3 %, cost = 10.5 %, the buggy multiple on D₀ is 14.13× — sitting between a terminal-only Gordon (13.73×) and a sustainable-only Gordon (23.6×) without a defensible derivation. The error grows with the gap `(sustainable − terminal)`, so it is largest for cyclicals and high-payout names. Field symptom: on Managem the DDM prints ~1 532 MAD while RI prints ~950 MAD; V13 is roughly half of that 60 % gap.

**Fix recipe (H-model — see brief 30 for full spec):**

```python
H = fade_years / 2.0
spread = max(0.0, growth - terminal_growth)
if dividend and cost > terminal_growth:
    fair = dividend * ((1.0 + terminal_growth) + H * spread) / (cost - terminal_growth)
else:
    fair = None
```

This degenerates to single-Gordon at terminal `g` when sustainable growth is below terminal, expands monotonically with `fade_years`, and aligns with how `_justified_multiples` already uses fade.

**Acceptance:** see brief 30, tests `test_ddm_h_model_collapses_to_terminal_gordon_when_growth_equals_terminal`, `test_ddm_h_model_lies_between_two_single_stage_gordons`, `test_ddm_returns_none_when_cost_le_terminal_growth`, `test_ddm_inputs_expose_fade_years_and_h_factor`.

> ✅ **V13 fix is shipped** — `_ddm` now uses the H-model formula and exposes `fade_years` / `h_factor` in its inputs.

---

### 🔴 V14 — Residual income fade starts at year 1

**Where:** `_residual_income` at `valuation.py:582`, the per-year loop:

```python
for year in range(1, fade_years + 1):
    fade = year / fade_years           # year=1 → fade = 1/N (already fading)
    year_roe = roe * (1.0 - fade) + cost * fade
```

**Symptom:** at `year = 1` with `fade_years = 5`, `fade = 0.20`. ROE is already pulled 20 % of the way toward cost of equity in the first projection year — there is no constant-ROE explicit horizon.

**Why it matters:** textbook Ohlson RI is `B₀ + Σ PV(RI_t)` with constant ROE for an explicit horizon, then a fade to zero spread. Starting the fade in year 1 front-loads the convergence and systematically suppresses near-term residual income for any firm where `ROE > r`. For a high-ROE firm like Managem this understates fair value by 15 – 30 % — the other half of the 950 / 1 532 gap.

**Fix recipe (simple shift — see brief 30 for the two-horizon alternative):**

```python
fade = (year - 1) / fade_years   # year = 1 → fade = 0 (full ROE)
year_roe = roe * (1.0 - fade) + cost * fade
```

The terminal year of the loop now sits at `fade_years + 1` where `fade = 1` and `RI = 0`, preserving the existing "no terminal value needed" invariant.

If Codex picks the explicit-horizon variant, add `ri_explicit_years` (default 3) to `DEFAULT_ASSUMPTIONS` and update `08-assumptions-and-defaults.md`.

**Acceptance:** see brief 30, tests `test_residual_income_year1_uses_full_roe`, `test_residual_income_reaches_zero_spread_at_horizon_end`, `test_residual_income_strictly_higher_than_pre_v14_for_high_roe_firms`, `test_ddm_and_ri_agree_within_15pct_on_clean_inputs`. The last one is the regression invariant: V13 + V14 together must bring DDM and RI to within 15 % on the synthetic snapshot pinned in the test.

> ✅ **V14 fix is shipped** — `_residual_income` uses the simple-shift variant (`fade = (year - 1) / fade_years`) and includes the zero-spread terminal projected year.

---

### 🟡 V7 — Default WACC equals default cost of equity

**Where:** `DEFAULT_ASSUMPTIONS` at `valuation.py:18-19`. `cost_of_equity = wacc = 0.105`.

**Symptom:** implies 100% equity financing globally. Per-symbol overrides via `FundamentalAssumptionSet` would fix this, but the global default is rarely overridden.

**Why it matters:** FCFF DCF discounts at WACC; for a typical Moroccan corporate with 30-40% debt, WACC should be 8-9%, not 10.5%. Using COE as WACC understates fair value across the board.

**Fix recipe:**

Update `DEFAULT_ASSUMPTIONS`:

```python
DEFAULT_ASSUMPTIONS: dict[str, float] = {
    "risk_free_rate": 0.035,
    "equity_risk_premium": 0.055,
    "country_risk_premium": 0.015,
    "cost_of_equity": 0.105,
    "cost_of_debt": 0.055,
    "tax_rate": 0.30,
    # WACC default assumes 70% equity / 30% debt (MAD market average)
    # WACC = 0.70 × 0.105 + 0.30 × 0.055 × (1 - 0.30) = 0.0851
    "wacc": 0.0851,
    "default_debt_weight": 0.30,
    "default_equity_weight": 0.70,
    "terminal_growth": 0.03,
    "forecast_years": 5.0,
    "fade_years": 5.0,
    "growth_cap": 0.08,
    "stable_payout_ratio": 0.55,
    "peer_min_count": 3.0,
    "proxy_weight_cap": 0.25,
}
```

Add a comment in `08-assumptions-and-defaults.md` documenting the implied capital structure.

**Acceptance:** running the engine against a leveraged industrial yields a fair_value materially higher than today's output (because the discount rate dropped from 10.5% to 8.5%). Banks (where COE = WACC by construction in current methodology) should set both equal via their assumption set override.

---

### 🟡 V8 — Currency is not tagged on results

**Where:** `ValuationResult` and `EnsembleResult` in `domain.py`; consumed throughout `valuation.py`.

**Symptom:** `fair_value`, `current_price`, and `upside_pct` have no currency field. `_upside` divides them without unit checking.

**Why it matters:** today everything is MAD because the only ingestion path is the workbook. The moment yfinance lands a USD or EUR symbol with MAD-tuned assumptions still active, the upside number is meaningless and there is no guard.

**Fix recipe:**

Add `currency: str | None = "MAD"` to `ValuationResult` and `EnsembleResult`. Add a `currency` field on `FundamentalSnapshot.source` populated by both providers. In `compute_valuation_ensemble`, if `snapshot.currency != assumption_set.currency`, exclude the model and emit `currency_mismatch`.

**Acceptance:** USD-quoted yfinance symbols don't blend with MAD assumptions; mismatch is surfaced to the UI.

---

### 🟡 V9 — Reverse DCF returns fair_value = current_price

**Where:** `_reverse_dcf` at `valuation.py:530`.

**Symptom:** `fair_value=current_price`, so the model always shows 0% upside in the UI. The actual diagnostic is `implied_perpetual_growth` in `outputs`.

**Why it matters:** the per-model row in the UI looks like a useless duplicate of current price. Users can't see "what growth rate does the market price imply?" without expanding the inputs JSON.

**Fix recipe:**

```python
# Change in _reverse_dcf:
return _result(
    snapshot=snapshot,
    scenario=scenario,
    model="reverse_dcf",
    fair_value=None,                              # was: current_price
    current_price=current_price,
    confidence=confidence,
    inputs={...},
    outputs={
        "implied_perpetual_growth": implied,
        "interpretation": (
            f"Market implies {implied*100:.1f}% perpetual FCF growth at WACC={assumptions['wacc']*100:.1f}%. "
            f"Compare to your sustainable growth estimate."
        ) if implied is not None else None,
    },
    warnings=warnings,
    methodology="Reverse DCF diagnostic. fair_value intentionally None; primary read is implied_perpetual_growth.",
    family="diagnostic",
)
```

UI: render diagnostic rows differently (badge "Diagnostic", show `implied_perpetual_growth` as the headline number).

**Acceptance:** Reverse DCF appears in the per-model table with a Diagnostic badge, showing "Implied growth: 4.2%" instead of "Fair value: MAD 245.30 (0% upside)".

---

### 🔵 V10 — Ensemble band is not probabilistic

**Where:** `compute_valuation_ensemble` at `valuation.py:555`.

**Symptom:** `fair_low = min(fair_base, ordered[low_index][0])`, `fair_high = max(fair_base, ordered[high_index][0])`. The band reflects model dispersion, not a confidence interval.

**Why it matters:** UI consumers see "fair value MAD 45–62" and reasonably assume a confidence interval. It's actually "the Q1 and Q3 of model outputs, bounded by the weighted mean".

**Fix recipe:**

Add a Monte Carlo overlay:

```python
def _monte_carlo_fair_value(model_runner, snapshot, history, assumptions, n_samples=500):
    """Sample fair values under perturbed assumptions."""
    samples = []
    for _ in range(n_samples):
        perturbed = {
            **assumptions,
            "wacc": assumptions["wacc"] + random.gauss(0, 0.005),
            "terminal_growth": assumptions["terminal_growth"] + random.gauss(0, 0.005),
            "growth_cap": assumptions["growth_cap"] + random.gauss(0, 0.01),
        }
        try:
            result = model_runner(snapshot, history, current_price, perturbed, scenario)
            if result.fair_value is not None:
                samples.append(result.fair_value)
        except Exception:
            continue
    if not samples:
        return None, None, None
    samples.sort()
    return (
        samples[int(0.05 * len(samples))],   # P5
        samples[int(0.50 * len(samples))],   # P50
        samples[int(0.95 * len(samples))],   # P95
    )
```

Surface as `monte_carlo_low / monte_carlo_base / monte_carlo_high` on `EnsembleResult`, alongside the existing `fair_value_low/base/high` (renamed to `model_dispersion_low/base/high` for clarity).

**Acceptance:** new fields appear on the ensemble result; UI labels the existing band "Model dispersion" and the new band "Monte Carlo 5/95".

---

### 🔵 V11 — No scenarios beyond `"base"`

**Where:** `compute_symbol_valuations` accepts `scenario` but never branches on it.

**Symptom:** the schema `FundamentalAssumptionSet.scenario` supports bull / base / bear, but `compute_symbol_valuations` runs the same numbers regardless.

**Why it matters:** institutional valuation always shows a range. Single point estimates communicate false precision.

**Fix recipe:**

```python
def compute_symbol_valuations_all_scenarios(
    *, snapshot, history, peer_snapshots, sectors, assumption_sets, scenarios=("bear", "base", "bull"),
):
    """Run the full valuation pipeline for each scenario."""
    out = {}
    for scenario in scenarios:
        assumptions = assumption_sets.get(scenario, DEFAULT_ASSUMPTIONS)
        eligibility, results = compute_symbol_valuations(
            snapshot=snapshot, history=history, peer_snapshots=peer_snapshots,
            sectors=sectors, assumptions=assumptions, scenario=scenario,
        )
        out[scenario] = {"eligibility": eligibility, "valuations": results}
    return out
```

Default scenario assumption sets (suggested):
- **bear**: `growth_cap=0.04, terminal_growth=0.02, wacc=0.095, cost_of_equity=0.115`
- **base**: current `DEFAULT_ASSUMPTIONS`
- **bull**: `growth_cap=0.12, terminal_growth=0.035, wacc=0.075, cost_of_equity=0.095`

Persist all three in `FundamentalEnsembleResult` (one row per scenario, already supported by the schema).

**Acceptance:** UI shows three columns side-by-side (Bear / Base / Bull) for fair value and upside.

---

### 🔵 V12 — No sensitivity output

**Where:** `compute_symbol_valuations` doesn't expose `∂(fair_value)/∂(WACC)` or `∂(fair_value)/∂(g)`.

**Why it matters:** standard analyst practice is a 2D heatmap showing fair value as a function of WACC and terminal_growth, so analysts can see how sensitive their conclusion is.

**Fix recipe:**

```python
def compute_sensitivity(
    *, snapshot, history, base_assumptions,
    axis_x="wacc", axis_y="terminal_growth",
    range_x=(0.07, 0.13), range_y=(0.01, 0.05), steps=5,
):
    """Return a 5x5 matrix of fair_value_base under perturbed axes."""
    import numpy as np
    xs = np.linspace(range_x[0], range_x[1], steps)
    ys = np.linspace(range_y[0], range_y[1], steps)
    matrix = []
    for y in ys:
        row = []
        for x in xs:
            perturbed = {**base_assumptions, axis_x: float(x), axis_y: float(y)}
            _, results = compute_symbol_valuations(
                snapshot=snapshot, history=history,
                peer_snapshots=[], sectors={}, assumptions=perturbed, scenario="base",
            )
            ensemble = compute_valuation_ensemble(snapshot.symbol, "base", results)
            row.append(ensemble.fair_value_base)
        matrix.append(row)
    return {"axis_x": axis_x, "axis_y": axis_y, "xs": xs.tolist(), "ys": ys.tolist(), "matrix": matrix}
```

Surface as a new endpoint `GET /fundamentals/stocks/{symbol}/sensitivity?axis_x=wacc&axis_y=terminal_growth`. UI renders a 5×5 heatmap on the valuation tab.

**Acceptance:** analyst can see, at a glance, that fair value swings from MAD 200 to MAD 320 across the plausible (WACC, g) range — and can refine their assumptions accordingly.

---

## Scoring engine (`core/quant_core/fundamentals/scoring.py`)

### 🔴 S1 — Metric overlap across pillars (double-counting)

**Where:** `scoring.py:24-29`.

**Symptom:**
- `Debt_to_Equity` appears in `QUALITY_METRICS` (line 25) AND `RISK_METRICS` (line 28).
- `FCF_Margin` appears in `QUALITY_METRICS` AND `CASH_FLOW_METRICS` (line 29).
- `FCF_Yield` appears in `VALUE_METRICS` (line 24) AND `CASH_FLOW_METRICS`.

**Why it matters:** with `OVERALL_WEIGHTS = {value:0.20, quality:0.22, growth:0.16, risk:0.14, cash_flow:0.14, health:0.14}`, leverage is counted in both quality (0.22) and risk (0.14), so a deleveraging firm gets credit at a combined effective weight of 0.36 on that one factor. FCF metrics are similarly over-counted.

**Fix recipe:**

Two options — pick one explicitly and document:

**Option A (deduplicate):**

```python
VALUE_METRICS = ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA", "FCF_Yield", "Dividend_Yield")
QUALITY_METRICS = ("ROE", "ROA", "Operating_Margin", "Net_Margin")
GROWTH_METRICS = ("Revenue_Growth", "EBIT_Growth", "NetIncome_Growth")
DIVIDEND_METRICS = ("Dividend_Yield", "Dividend_Coverage", "Dividend_Payout")
RISK_METRICS = ("Debt_to_Equity", "NetDebt_to_EBITDA", "Current_Ratio", "Cash_Ratio")
CASH_FLOW_METRICS = ("FCF_Margin", "Operating_CF_Margin", "CAF_Margin")
```

(FCF_Yield stays in value only; FCF_Margin stays in cash_flow only; Debt_to_Equity stays in risk only.)

**Option B (keep overlap, document the rationale):**

Add a paragraph in `04-pillars-and-scoring.md` explaining that leverage is intentionally weighted in both quality and risk because it captures two distinct dimensions: capital efficiency (quality) and solvency cushion (risk). Adjust `OVERALL_WEIGHTS` to renormalize for the overlap.

**Recommendation:** Option A. It produces cleaner mental model and the user can always combine pillars themselves if they want.

**Acceptance:** After deduplication, no metric appears in more than one `*_METRICS` tuple.

---

### 🔴 S2 — No sector-bucketed normalization

**Where:** `_metric_percentiles` at `scoring.py:72`.

**Symptom:** `_metric_percentiles` ranks across the whole universe regardless of sector. The valuation peer logic (`_peer_stats` in `valuation.py:191`) correctly buckets by sector with market fallback; `scoring.py` does NOT mirror this pattern.

**Why it matters:** cyclicals (banks, real estate) and defensives (utilities, telcos) get blended into the same PER ranking. Utilities look perma-cheap; tech-style names look perma-expensive. The scoring system gives misleading "value" signals.

**Fix recipe:**

```python
def _metric_percentiles_by_sector(
    snapshots, sectors, *, peer_min_count=3
) -> dict[str, dict[str, dict[str, float | str]]]:
    """Per-metric, per-symbol: {symbol: {percentile, scope}}."""
    rows = list(snapshots)
    metric_names = sorted({metric for row in rows for metric in row.metrics})
    out = {}
    for metric in metric_names:
        out[metric] = {}
        # Group symbols by sector
        by_sector = defaultdict(dict)
        market_values = {}
        for row in rows:
            value = _clean(row.metrics.get(metric))
            if value is None:
                continue
            sector = sectors.get(row.symbol)
            market_values[row.symbol] = value
            if sector:
                by_sector[sector][row.symbol] = value

        for sector_name, sector_values in by_sector.items():
            if len(sector_values) >= peer_min_count:
                scores = _percentile_scores(
                    sector_values, lower_is_better=metric in LOWER_IS_BETTER
                )
                for symbol, score in scores.items():
                    out[metric][symbol] = {"score": score, "scope": "sector"}

        # Market fallback for symbols whose sector group was too thin
        market_scores = _percentile_scores(
            market_values, lower_is_better=metric in LOWER_IS_BETTER
        )
        for symbol, score in market_scores.items():
            if symbol not in out[metric]:
                out[metric][symbol] = {"score": score, "scope": "market"}
    return out
```

Update `_score_group` and `score_fundamental_snapshots` to consume the new structure; surface `scope` in the snapshot diagnostics.

**Acceptance:** a Moroccan bank's `Value` score is now relative to other banks, not vs. utilities. Sector scope is surfaced per pillar score.

---

### 🔴 S3 — Single-symbol scoring silently returns 50.0

**Where:** `_percentile_scores` at `scoring.py:64`.

**Symptom:** `if n == 1: return {ordered[0][0]: 50.0}`. A symbol scored against an empty cohort gets a flat 50 on every metric — looks "neutral" but is actually "uncomputed".

**Why it matters:** this is the exact failure mode that the yfinance ingestion plan must work around. Per-symbol ingest hits this path and stamps a meaningless "50" into the database, which then surfaces in the UI as if it were a real score.

**Fix recipe:**

```python
def _percentile_scores(values, *, lower_is_better, min_cohort=3):
    if not values:
        return {}
    n = len(values)
    if n < min_cohort:
        # Mark as insufficient — don't fabricate a score
        return {symbol: None for symbol in values}
    ordered = sorted(values.items(), key=lambda item: item[1])
    scores = {}
    for rank, (symbol, _) in enumerate(ordered):
        pct = 100.0 * rank / (n - 1)
        scores[symbol] = 100.0 - pct if lower_is_better else pct
    return scores
```

Propagate `None` correctly through `_score_group` and `_weighted_score` (the latter already handles None members).

**Acceptance:** a yfinance symbol ingested alone against an empty non-MASI cohort produces `scores_json = {"value": None, "quality": None, ..., "component_count": 0.0}`, NOT `{"value": 50.0, ...}`. After the rescore pass (Phase −1.2 in the integration plan), real scores appear.

---

### 🟡 S4 — `dividend` score is computed but excluded from `OVERALL_WEIGHTS`

**Where:** `OVERALL_WEIGHTS` at `scoring.py:31`; `snapshot.scores["dividend"]` set at line 269.

**Symptom:** dividend pillar is computed and surfaced in the snapshot but has no weight in the overall score. Six pillars sum to 1.00; dividend is exposed as `snapshot.scores["dividend"]` separately.

**Why it matters:** ambiguous design. Either dividend should contribute to overall, or it's a diagnostic and should move to `snapshot.diagnostics`.

**Fix recipe:**

Pick one:

**Option A (diagnostic):** move `dividend_score` from `snapshot.scores` to `snapshot.diagnostics["dividend"]` and rename to clarify it's not part of overall.

**Option B (include in overall):** rebalance weights as e.g.:

```python
OVERALL_WEIGHTS = {
    "value": 0.18,
    "quality": 0.20,
    "growth": 0.15,
    "risk": 0.13,
    "cash_flow": 0.13,
    "health": 0.13,
    "dividend": 0.08,
}
```

**Recommendation:** Option A. Dividend yield already feeds `VALUE_METRICS` indirectly (`Dividend_Yield`), and dividend policy is a strategic choice that doesn't reflect underlying quality.

**Acceptance:** either `snapshot.scores` no longer has a `dividend` key, OR `OVERALL_WEIGHTS` includes a dividend weight that sums to 1.0.

---

### 🟡 S5 — "Health" is actually accounting discipline

**Where:** `score_fundamental_snapshots` at `scoring.py:252`, computing `health_score = avg(piotroski_score, dupont_score)`.

**Symptom:** what's labelled "health" is actually two earnings-quality probes (Piotroski-lite for accounting trends, DuPont for ROE bridge consistency). Neither captures balance-sheet health (interest coverage, current ratio, debt service capacity).

**Why it matters:** an analyst sees `health=80` and assumes the firm is financially robust. The score actually says "the income statement and balance sheet articulate cleanly" — a different statement.

**Fix recipe:**

Two options:

**Option A (rename):** rename `health` → `accounting_discipline` everywhere (snapshot, API, UI). Keep formula unchanged.

**Option B (recompute):** make `health` actually be balance-sheet health, computed from `RISK_METRICS`:

```python
HEALTH_METRICS = ("Current_Ratio", "NetDebt_to_EBITDA", "Interest_Coverage", "Cash_Ratio")

# In score_fundamental_snapshots, replace:
health_score = _score_group(snapshot.symbol, percentiles, HEALTH_METRICS)

# Move the old health to diagnostics:
snapshot.diagnostics["accounting_discipline"] = _clip_score(
    _avg([piotroski.get("score"), dupont.get("score")])
)
```

**Recommendation:** Option B, paired with surfacing `accounting_discipline` as a diagnostic. The user can pick which to weight.

**Acceptance:** `snapshot.scores["health"]` reflects balance-sheet ratios; `snapshot.diagnostics["accounting_discipline"]` carries the Piotroski+DuPont composite.

---

### 🟡 S6 — `adjusted_quality` overwrites raw quality without audit trail

**Where:** `score_fundamental_snapshots` at `scoring.py:255-267`.

**Symptom:** `adjusted_quality = avg(quality_score, health_score, accrual_score)` is written to both `parts["quality"]` and `snapshot.scores["quality"]`. The raw percentile-derived quality is discarded.

**Why it matters:** a user looking at `quality=72` can't break it down into "raw percentile 60, Piotroski 80, accrual 70 → adjusted 70". The audit trail is hidden.

**Fix recipe:**

```python
snapshot.scores = {
    "overall": _weighted_score(parts),
    "value": value_score,
    "quality": adjusted_quality,            # headline (current behaviour)
    "quality_raw": quality_score,           # raw percentile rank, NEW
    "quality_components": {                 # NEW
        "raw_percentile": quality_score,
        "piotroski_lite": piotroski.get("score"),
        "dupont_bridge": dupont.get("score"),
        "accrual_quality": accrual_score,
    },
    "growth": growth_score,
    "dividend": dividend_score,
    "risk": risk_score,
    "cash_flow": cash_flow_score,
    "health": health_score,
    "accrual_quality": accrual_score,
    "component_count": float(sum(score is not None for score in parts.values())),
}
```

UI can expand `quality_components` in a tooltip / expander.

**Acceptance:** snapshot now carries enough detail to explain "why is quality 72" without re-running the engine.

---

### 🟡 S7 — `_weighted_score` renormalizes silently over partial coverage

**Where:** `_weighted_score` at `scoring.py:222`.

**Symptom:** weights are renormalized over present pillars. A symbol with only `value` computed gets `overall = value_score`. `component_count` is exposed (line 274) but the UI doesn't visibly flag partial-coverage rows.

**Why it matters:** a symbol with 1/6 pillars and a symbol with 6/6 pillars produce visually identical `overall` scores. Users can't tell at a glance which scores are trustworthy.

**Fix recipe:**

```python
def _weighted_score(parts):
    present = [(name, value) for name, value in parts.items() if value is not None]
    if not present:
        return None, None
    weight_sum = sum(OVERALL_WEIGHTS[name] for name, _ in present)
    if weight_sum <= 0:
        return None, None
    raw = sum(float(value) * OVERALL_WEIGHTS[name] for name, value in present) / weight_sum
    coverage = weight_sum / sum(OVERALL_WEIGHTS.values())
    # Optional: only return non-None if coverage >= 0.5
    if coverage < 0.5:
        return None, coverage
    return _clip_score(raw), coverage
```

Return tuple `(overall, coverage_pct)`. Surface `coverage_pct` in `snapshot.scores["overall_coverage_pct"]`. UI flags rows with `coverage_pct < 0.7` with a "Partial" chip.

**Acceptance:** symbol with `value=70, quality=80` and nothing else returns `overall=None` (coverage 0.42 < 0.5 threshold); symbol with 5/6 pillars returns a real overall with `coverage_pct=0.85`.

---

### 🔵 S8 — Percentile-only ranking discards magnitude

**Where:** `_percentile_scores` at `scoring.py:58`.

**Symptom:** a stock at PER 5 vs sector medians {8, 10, 12} ranks identically (percentile 100) to a stock at PER 1 vs medians {30, 50, 80}. The second is dramatically cheaper but the scoring system treats them the same.

**Why it matters:** percentiles are robust to outliers (good for thin universes) but discard magnitude information that an analyst actually wants.

**Fix recipe:**

Add a parallel `z_score` and `pct_deviation_from_median` output alongside percentile:

```python
def _metric_breakdown(values, *, lower_is_better):
    if len(values) < 3:
        return {symbol: None for symbol in values}
    import statistics
    vals = list(values.values())
    median_v = statistics.median(vals)
    stdev_v = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    out = {}
    for symbol, v in values.items():
        z = (v - median_v) / stdev_v if stdev_v > 0 else 0.0
        pct_dev = (v / median_v - 1.0) if median_v else 0.0
        sign = -1 if lower_is_better else 1
        out[symbol] = {
            "value": v,
            "median": median_v,
            "z_score": sign * z,
            "pct_dev": sign * pct_dev,
        }
    return out
```

Persist both `percentile` and `magnitude` (z_score + pct_dev) per metric per symbol. UI can pick which to display.

**Acceptance:** snapshot's `diagnostics["metric_breakdown"]` now contains per-metric magnitude information.

---

### 🔵 S9 — No time-weighted smoothing

**Where:** all pillar scores use `latest_metric` only.

**Symptom:** cyclicals swing year-over-year. A bank at the cyclical trough has low ROE → low quality → low overall. A bank at the cyclical peak has high ROE → high quality → high overall. The same firm flips from "buy" to "sell" purely on cycle phase.

**Why it matters:** institutional analysis smooths cyclicals over 3-5 year windows. Latest-only scoring biases toward end-of-cycle positions.

**Fix recipe:**

Add a `_trailing_average` helper and use it for cyclical-sensitive pillars (Value, Growth):

```python
def _trailing_average(history, metric_name, years=3):
    series = _series(history, metric_name)
    if len(series) < years:
        return None
    return mean(value for _, value in series[-years:])

# In score_fundamental_snapshots:
# Compute both latest and trailing for each metric
# Expose both in snapshot.diagnostics:
snapshot.diagnostics["smoothing"] = {
    "ROE_latest": snapshot.metrics.get("ROE"),
    "ROE_trailing_3y": _trailing_average(symbol_history, "ROE", 3),
    "FCF_Margin_latest": snapshot.metrics.get("FCF_Margin"),
    "FCF_Margin_trailing_3y": _trailing_average(symbol_history, "FCF_Margin", 3),
    # ... for each cyclical-sensitive metric
}
```

UI can offer a toggle "Latest / 3y trailing" on the value and quality pillars.

**Acceptance:** snapshot diagnostics now include trailing-averaged metric values for cyclical sensitivity analysis.

---

## How Codex should use this document

1. **Read once front-to-back** to internalize the design philosophy and the issues.
2. **Pick a severity bucket** to work through. Recommended order: 🔴 logic concerns first (V1–V6, S1–S3), then 🟡 configuration smells (V7–V9, S4–S7), then 🔵 missing features (V10–V12, S8–S9).
3. **For each issue, follow the fix recipe verbatim.** Each recipe is self-contained — the diff target, the helper structure, and the acceptance test are spelled out.
4. **Write unit tests first** for each fix. Existing test patterns under `core/tests/test_fundamentals*` are the template.
5. **Update assumption-set defaults via migration**, not by editing source. The schema supports per-symbol / per-sector overrides — use it.
6. **Each fix should be one PR.** Don't bundle V1+V2+V3 — bundle V1 with its test and the doc update in `06-valuation-models.md`.
7. **Update `14-implementation-roadmap.md`** as issues close so the file reflects current state.

## Cross-references

- Methodology references for each fix: see `13-methodology-and-sources.md`.
- Worked examples for each model: see `06-valuation-models.md`.
- Pillar definitions: see `04-pillars-and-scoring.md`.
- Default-assumption rationale: see `08-assumptions-and-defaults.md`.
