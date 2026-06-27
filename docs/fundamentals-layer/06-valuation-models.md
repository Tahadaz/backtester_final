# Valuation models

The engine runs up to **7 valuation models per symbol**, each gated by eligibility rules. Non-diagnostic models that produce a finite fair value survive into a robust ensemble with equal inclusion weight after cross-model outlier rejection. This document covers each model's formula, inputs, eligibility, confidence cascade, and a worked Moroccan-context example. Known limitations are surfaced inline with links to [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md).

**v3 status:** the previously-surfaced valuation limitations V1-V12 are implemented. Inline warning callouts that mention "current implementation" describe pre-v3 behavior and are retained for methodology history until the worked examples are fully refreshed.

**Brief 34 discipline:** every valuation input is either observed, derived from observed history/peers, or a documented registry assumption. Operational projection drivers use history first, then same-sector peer medians from `stock_master.sector`, then `unavailable`; they are not silently filled with placeholder numbers. Non-positive intrinsic equity values return `fair_value=None` with a warning, not a zero floor.

**Brief 34 ensemble/rating update:** relative and justified multiple outputs are no longer clamped to a band around current market price. Discipline is applied across models: the ensemble drops cross-model outliers by MAD around the model median, then uses the median of surviving model fair values. The API's 5-tier rating ladder compares expected total return (`target/current - 1 + dividend yield`) with the symbol's cost of equity.

**Brief 39 cost-of-capital update:** display-facing valuation uses the stored per-symbol `fundamental_beta_history` beta in CAPM. The model input is `cost_of_equity = max(risk_free_rate + beta * equity_risk_premium, cost_of_equity_floor, risk_free_rate)`, with the default floor set to 6.5% (`3.5% rf + 0.5 * 6.0% ERP`). A missing beta uses the documented default beta `1.0` and is flagged with `beta_source="default_beta"`; illiquid/proxy beta rows carry a confidence haircut. DDM, residual income, and justified multiples share one ROE basis: `RNPG / average group equity` recomputed from verified raw lines.

| Model | Family | Ensemble inclusion | When it wins |
|---|---|---|---|
| FCFF DCF | Intrinsic | Equal survivor weight | Non-financial, positive FCF history |
| Residual income | Intrinsic | Equal survivor weight | Financials (banks, insurers) |
| FCFE DCF | Intrinsic | Equal survivor weight if usable | Non-financial, leveraged firms; debt-flow-adjusted when inputs exist, otherwise lower-confidence proxy |
| Justified multiples | Relative | Equal survivor weight | Stable firms with clear payout policy |
| DDM | Intrinsic | Equal survivor weight | Dividend payers with stable history |
| Relative multiples | Relative | Equal survivor weight | When enough sector/market peer data exists |
| Reverse DCF | **Diagnostic** | Excluded | Always (informational only) |

All formulas live in `core/quant_core/fundamentals/valuation.py`.

---

## Scenario governance

The valuation engine computes and persists `bear`, `base`, and `bull` ensembles for each symbol. The `base` ensemble is the house headline: it drives the research-ticket `recommendation`, `target_price`, `conviction`, and target-price revision direction. Selecting `bear` or `bull` in the UI changes the detailed valuation view and scenario diagnostics, but it does not move the headline call.

The former `auto` behavior no longer selects the scenario closest to the current market price for the headline. Requests that omit a scenario, or pass `scenario=auto`, resolve to `base`. The closest-to-price scenario is still calculated and exposed as a market-implied diagnostic so analysts can see whether the market is trading nearer to bear, base, or bull without changing the official recommendation.

Scenario probabilities are assumptions (`scenario_probability_bear/base/bull`) and are normalized to 100% by the assumption resolver. The frontend expected-value display reads the normalized API payload instead of hardcoding probabilities.

---

## 1. FCFF DCF (Free Cash Flow to Firm, Discounted)

**Function:** `_fcff_dcf` (`valuation.py:305`).

**Equation:**

```
For year t in 1..forecast_years:
    fade_t = t / forecast_years
    growth_t = g_initial × (1 - fade_t) + terminal_growth × fade_t
    fcf_t   = fcf_{t-1} × (1 + growth_t)
    pv_t    = fcf_t / (1 + WACC)^t

EV = Σ pv_t + terminal_value / (1 + WACC)^forecast_years
where terminal_value = fcf_T × (1 + terminal_growth) / (WACC - terminal_growth)

Equity = EV - NetDebt
Fair value per share = Equity / shares_outstanding; if Equity <= 0, the model is unavailable with a warning
```

**Inputs:**
- `FCF_start`: latest reported `Free_Cash_Flow`, or proxy via `MarketCap × FCF_Yield` or `Revenue × FCF_Margin` (see `_fcf_start` at `valuation.py:274`).
- `g_initial`: from observed FCF/cash-flow growth when available, then proxy growth signals or history CAGR; missing required drivers make the projection unavailable.
- `WACC`: from assumptions or live API cost-of-capital build-up.
- `terminal_growth`: from assumptions, with current source default 2.5%.
- `forecast_years`: 5 default.
- `NetDebt`: latest reported, computed from debt minus cash when possible, otherwise warns and caps confidence.
- `shares_outstanding`: from snapshot.

**Eligibility:**
- `not _is_financial(sector)` — banks/insurers/leasing excluded.
- `has_fcf_proxy = True` (FCF metric, FCF_Yield, FCF_Margin, or 3+ years positive FCF history).

**Confidence:**
- Start `"high"` if ≥3 positive FCF years in history, else `"medium"`.
- Downgraded by `_confidence` per warning count.

**Worked example — Moroccan industrial (synthetic):**

| Input | Value |
|---|---|
| FCF (latest) | MAD 1,200M |
| Revenue_Growth | 6% |
| WACC | 10.5% |
| terminal_growth | 3% |
| forecast_years | 5 |
| NetDebt | MAD 1,500M |
| Shares outstanding | 100M |

Year-by-year projection (fade from 6% to 3%):

| Year | growth | FCF (MAD M) | PV (MAD M) |
|---|---|---|---|
| 1 | 5.4% | 1264.8 | 1144.6 |
| 2 | 4.8% | 1325.5 | 1085.7 |
| 3 | 4.2% | 1381.2 | 1023.6 |
| 4 | 3.6% | 1430.9 | 959.5 |
| 5 | 3.0% | 1473.8 | 894.7 |

Terminal value at year 5 = 1473.8 × 1.03 / (0.105 − 0.03) = MAD 20,233M
PV(TV) = 20,233 / 1.105^5 = MAD 12,288M
EV = sum of PVs + PV(TV) = 5,108 + 12,288 = MAD 17,396M
Equity = 17,396 − 1,500 = MAD 15,896M
Fair value per share = 15,896 / 100 = **MAD 158.96**

---

## 2. FCFE DCF (Free Cash Flow to Equity, Discounted)

**Function:** `_fcfe_dcf` (`valuation.py:342`).

> **v3 behavior:** FCFE uses FCF adjusted for after-tax interest and net borrowing when debt-flow inputs exist. If debt-flow detail is unavailable, FCF is still used as a proxy with capped confidence and lower observed-input quality.

**Current equation (proxy):**

```
Identical to FCFF DCF, but:
- discount rate = cost_of_equity (not WACC)
- no NetDebt bridge (FCFE is already equity-level cash flow)
- input "fcfe_proxy_start" = same FCF source as FCFF
```

**Eligibility:**
- Same as FCFF DCF.

**Confidence:**
- Hard-coded `"medium"` start because of proxy nature.
- `proxy=True` flag demotes data quality/confidence; the ensemble no longer applies a separate proxy weight cap.

**Worked example — same Moroccan industrial as above:**

Same FCF projection (since proxy uses same input), discounted at COE = 10.5% (happens to equal WACC default):
Sum of PVs = 5,108M (same)
TV = 1473.8 × 1.03 / (0.105 - 0.03) = MAD 20,233M
PV(TV) = 12,288M
Equity (FCFE proxy) = 5,108 + 12,288 = MAD 17,396M  ← NO NetDebt bridge
Fair value per share = 17,396 / 100 = **MAD 173.96**

Note this is **higher** than the FCFF result (158.96) because the NetDebt bridge is skipped. After [V1 is fixed](12-known-issues-and-limitations.md#-v1--fcfe-proxy-uses-raw-fcf), proper FCFE = FCF − interest_after_tax + net_borrowing should land between the two, depending on leverage.

---

## 3. DDM (Dividend Discount Model — Gordon, H-model variant after V13)

**Function:** `_ddm` (`valuation.py:525`). Sustainable-growth helper: `_sustainable_dividend_growth` (`valuation.py:394`).

**Equation (post brief 30 / V13 fix):**

```
H = fade_years / 2
spread = max(0, sustainable_growth - terminal_growth)
Fair value = dividend_per_share × ((1 + terminal_growth) + H × spread) / (cost_of_equity - terminal_growth)
```

This is the Fuller-Hsia H-model: dividends grow above trend for an explicit fade period, then revert to `terminal_growth` in perpetuity. It degenerates to single-stage Gordon at terminal `g` when `sustainable_growth ≤ terminal_growth`.

V13 is shipped: the engine no longer mixes sustainable growth in the numerator with terminal growth in the denominator.

**Inputs:**
- `dividend_per_share`:
  - First: latest `Dividendes` / `Clean_Dividendes` divided by `Shares_Outstanding`.
  - Else: `current_price × Dividend_Yield`.
- `sustainable_growth`: from `_sustainable_dividend_growth` — `ROE × (1 − payout)` capped at `growth_cap`, floor at −5 %. Falls back to `NetIncome_Growth` / `Revenue_Growth` if ROE is missing (warning `using_earnings_growth_proxy`).
- `cost_of_equity`, `terminal_growth`, `fade_years`: from assumptions (10.5 %, 3 %, 5 by default).

**Eligibility:**
- `_has_dividend(snapshot, history)` — either `Dividend_Yield > 0` or last-year `Dividendes > 0`.

**Confidence:**
- `"high"` if `Dividend_Yield` is present, else `"medium"`. Warnings demote per the standard cascade.

**Worked example — Moroccan utility (post-V13 numbers):**

| Input | Value |
|---|---|
| Current price | MAD 145 |
| Dividend_Yield | 5.5 % |
| ROE | 12 % |
| Dividend_Payout | 60 % |
| Cost of equity | 10.5 % |
| Terminal growth | 3.0 % |
| Fade years | 5 |

Dividend per share = 145 × 0.055 = MAD 7.98
Sustainable growth = 0.12 × (1 − 0.60) = 4.8 %
H = 5 / 2 = 2.5
Spread = 0.048 − 0.03 = 1.8 %
Fair value = 7.98 × ((1 + 0.03) + 2.5 × 0.018) / (0.105 − 0.03)
&nbsp;&nbsp;&nbsp; = 7.98 × (1.03 + 0.045) / 0.075
&nbsp;&nbsp;&nbsp; = 7.98 × 14.33 ≈ **MAD 114.3**

Upside vs price ≈ −21.2 % (downside). The H-model expands fair value vs a pure terminal-g Gordon (MAD 109.6) by exactly the contribution of the explicit fade. Cross-check with FCFF DCF and reverse DCF.

---

## 4. Residual Income (Ohlson)

**Function:** `_residual_income` (`valuation.py:582`).

**Equation (post brief 30 / V14 fix, simple-shift variant):**

```
book_value_per_share = current_price / Price_to_Book
B_0 = book_value_per_share

For year t in 1..fade_years + 1:
    fade_t   = (t - 1) / fade_years          # year 1 → 0 (full ROE)
    ROE_t    = ROE × (1 - fade_t) + cost_of_equity × fade_t
    RI_t     = B_{t-1} × (ROE_t - cost_of_equity)
    pv_t     = RI_t / (1 + cost_of_equity)^t
    B_t      = B_{t-1} × (1 + ROE_t × retention)

Fair value = B_0 + PV(residual income); if the result is <= 0, the model is unavailable with a warning
```

The terminal year sits where `fade = 1` and `RI = 0`, so no continuing-value term is needed.

V14 is shipped: year 1 now uses full current ROE, and the final projected year reaches zero residual-income spread.

**Inputs:**
- `book_value_per_share`: proxied from `current_price / Price_to_Book` (correct at the snapshot date by definition; requires PB and Price from the same snapshot).
- `ROE`, `Dividend_Payout` (drives `retention = 1 − payout`): ROE is recomputed as group-basis `RNPG / average group equity` from verified raw lines. Payout falls back to `stable_payout_ratio` when missing / out of range, with warning `using_stable_payout_assumption`.
- `cost_of_equity`, `fade_years`: from assumptions.

**Eligibility:**
- `has_book_roe = (Price_to_Book > 0) AND (ROE is not None)`.

**Confidence:**
- `"high"` only when book value is observed, net-income history is deep enough, ROE is available, and the model has no warnings.
- `"medium"` when ROE or net-income history exists but the evidence is thinner.
- `"unavailable"` when the model cannot produce a defensible positive value.
- Financial-sector classification never grants high confidence by itself.

**Financial-sector path (banks / insurers):**
- Financial snapshots suppress industrial valuation fields: `EBITDA`, `EV_to_EBITDA`, `EV_to_Sales`, `Price_to_Sales`, `Capex`, `Free_Cash_Flow`, `FCF_Yield`, `FCF_Margin`, `EnterpriseValue`, and `Net_Debt`.
- Banks use an equity-side projection when bank drivers exist: `PNB` growth from observed trailing growth or peer median, `RBE` from observed or peer `Marge_RBE`, cost of risk from observed or peer `Cout_du_risque / Loans_Net` (or `/ PNB`), net income after observed effective tax, and book-equity rollforward `BV_t = BV_{t-1} + NI_t - dividends_t`.
- If a bank has PNB but lacks observed or peer-derived `Marge_RBE` or cost of risk, projection-dependent RI is unavailable. If no PNB history exists at all, RI can fall back to the legacy P/B-ROE equation, flagged `bank_projection_unavailable_using_pb_roe_fallback`; verified rows still use group-basis ROE from raw lines.
- Insurers use a flagged ROE/book-equity projection (`insurer_simplified_roe_projection`) when premium and combined-ratio data are absent.
- All financial intrinsic models discount at cost of equity; no net-debt bridge or enterprise-value conversion is used.

**Worked example — Moroccan bank (post-V14 numbers):**

| Input | Value |
|---|---|
| Current price | MAD 380 |
| Price_to_Book | 1.8 |
| ROE | 14 % |
| Dividend_Payout | 60 % → retention 40 % |
| Cost of equity | 10.5 % |
| Fade years | 5 |

B₀ = 380 / 1.8 ≈ MAD 211.1

| Year | fade | ROE_t | RI_t = B_{t-1}·(ROE_t − r) | PV @ 10.5 % | B_t after retention |
|---:|:---:|:---:|---:|---:|---:|
| 1 | 0.00 | 14.0 % | 211.1 × 0.035 = 7.39 | 6.69 | 211.1 × (1 + 0.14 × 0.4) ≈ 222.9 |
| 2 | 0.20 | 13.3 % | 222.9 × 0.028 = 6.24 | 5.11 | 222.9 × (1 + 0.133 × 0.4) ≈ 234.8 |
| 3 | 0.40 | 12.6 % | 234.8 × 0.021 = 4.93 | 3.66 | 234.8 × (1 + 0.126 × 0.4) ≈ 246.6 |
| 4 | 0.60 | 11.9 % | 246.6 × 0.014 = 3.45 | 2.32 | 246.6 × (1 + 0.119 × 0.4) ≈ 258.4 |
| 5 | 0.80 | 11.2 % | 258.4 × 0.007 = 1.81 | 1.10 | 258.4 × (1 + 0.112 × 0.4) ≈ 269.9 |
| 6 | 1.00 | 10.5 % | 269.9 × 0 = 0 | 0 | — |

Σ PV(RI) ≈ 18.9
Fair value ≈ 211.1 + 18.9 ≈ **MAD 230**

Note: this is below current price (380 → upside ≈ −39 %) and **above** what the pre-V14 fade-from-year-1 would print on the same inputs (≈ MAD 215). The mathematical link to justified P/B holds at the matching `g`: with constant ROE and constant `g`, RI fair / B₀ = (ROE − g) / (r − g) — see §5.

---

## 5. Justified Multiples

**Function:** `_justified_multiples` (`valuation.py`).

**Equation:**

```
normalized_ROE = RNPG / average group equity from verified raw lines
sustainable_growth = normalized_ROE * (1 - payout_ratio)          (capped at growth_cap)
if sustainable_growth <= terminal_growth:
    growth = sustainable_growth
else:
    H = fade_years / 2
    h_model_factor = ((1 + terminal_growth) + H * (sustainable_growth - terminal_growth))
                     / (cost_of_equity - terminal_growth)
    growth = (h_model_factor * cost_of_equity - 1) / (h_model_factor + 1)

justified_PB = (normalized_ROE - growth) / (cost_of_equity - growth)
justified_PE = payout * (1 + growth) / (cost_of_equity - growth)

implied_price_PB_raw = current_price * justified_PB / Price_to_Book
implied_price_PE_raw = current_price * justified_PE / PER

fair_value = median(raw implied prices)
```

Post-V6 behavior no longer clips growth to `terminal_growth`. Post-brief-39 behavior uses group-basis ROE from verified raw lines instead of stored ratio fields. Post-brief-34 behavior removes the old price-anchored clamp; raw implied prices flow to the model median and cross-model outlier rejection is handled only at the ensemble layer.

**Inputs:**
- `ROE` recomputed as group-basis `RNPG / average group equity` from verified raw lines; `Dividend_Payout`, `Price_to_Book`, `PER` from snapshot.
- `cost_of_equity`, `terminal_growth`, `fade_years`, `stable_payout_ratio`, `growth_cap` from assumptions.

**Eligibility:**
- `has_book_roe` OR `Price_to_Earnings > 0`.

**Confidence:**
- `"medium"` if any implied price computed.
- `"unavailable"` if neither.
- Confidence is demoted by warnings and is not upgraded merely because the issuer is a bank or insurer.

**Worked example — Moroccan bank (continuing from RI example):**

| Input | Value |
|---|---|
| Current price | MAD 380 |
| Price_to_Book | 1.8 |
| PER | 13 |
| ROE | 14% |
| Dividend_Payout | 60% |
| Cost of equity | 10.5% |

retention = 1 - 0.60 = 0.40
sustainable_growth = 0.14 × 0.40 = 5.6% (under growth_cap of 8%)
H = 5 / 2 = 2.5
h_model_factor = ((1 + 0.03) + 2.5 * (0.056 - 0.03)) / (0.105 - 0.03) = 14.60
growth = (14.60 * 0.105 - 1) / (14.60 + 1) = **3.42%**

justified_PB = (0.14 - 0.0342) / (0.105 - 0.0342) = 1.494
justified_PE = 0.60 * 1.0342 / (0.105 - 0.0342) = 8.76

implied_price_PB = 380 * 1.494 / 1.8 = **MAD 315.4**
implied_price_PE = 380 * 8.76 / 13 = **MAD 256.1**

Because two justified prices are available, fair_value = median(PB, PE) = **MAD 285.8**.

The post-V6 growth treatment is conservative versus the old linear-average proxy: it recognizes the temporary growth premium, but values it as a finite H-model phase instead of embedding the average growth rate forever. Post-brief-34 no longer constrains justified multiple outputs against current market price; cross-model outlier rejection handles unbounded targets uniformly across all models.

---

## 6. Relative Multiples (Peer Median)

**Function:** `_relative_multiples` (`valuation.py:484`).

**Equation:**

```
For each non-financial metric in {PER, Price_to_Book, Price_to_Sales, EV_to_EBITDA}:
    own_multiple =
        PER: MarketCap / trailing_3y_avg_net_income when available, else spot PER
        P/S: MarketCap / trailing_3y_avg_revenue when available, else spot P/S
        P/B and EV/EBITDA: spot snapshot multiple
    peer_median = median of metric across peer cohort
    implied_price = current_price × peer_median / own_multiple

For financials:
    use only PER and Price_to_Book
    add Price_to_PNB only when own and peer P/PNB observations exist
    never use Price_to_Sales, EV_to_EBITDA, EV_to_Sales, FCFF, or a net-debt bridge

fair_value = median of implied_prices across the metrics used
```

**Peer cohort selection** (`_peer_stats` at `valuation.py:191`):
- First try: same-sector symbols with the metric present.
- If count < `peer_min_count` (default 3): fall back to whole-universe (market) median.
- The fallback path is tracked per-metric as `scope = "sector"` or `"market"`.

**Inputs:**
- Multiples from snapshot, with PER/P-Sales normalized from annual history when possible.
- Peer snapshots from the same import cohort.
- Sector map from `stock_master`.

**Eligibility:**
- Non-financials: at least one of `(PER, Price_to_Book, Price_to_Sales, EV_to_EBITDA)` is positive in the snapshot.
- Financials: at least one of `(PER, Price_to_Book, Price_to_PNB)` is positive, with P/PNB included only when observed peer data exists.

**Confidence:**
- `"high"` if ≥3 metrics produced an implied price.
- `"medium"` if 2.
- `"low"` if 1.
- `"unavailable"` if 0.

**Worked example — Moroccan industrial vs sector peers:**

Symbol IRD (synthetic) — Industrial:

| Multiple | Own | Sector peers' median | Implied price |
|---|---|---|---|
| PER | 18 | 14 | 245 × 14/18 = 190.6 |
| Price_to_Book | 2.2 | 1.6 | 245 × 1.6/2.2 = 178.2 |
| Price_to_Sales | 1.4 | 1.0 | 245 × 1.0/1.4 = 175.0 |
| EV_to_EBITDA | 10 | 8 | 245 × 8/10 = 196.0 |

Current price = MAD 245.
Fair value = median(190.6, 178.2, 175.0, 196.0) = **MAD 184.4**
Upside = 184.4/245 - 1 = **-24.7%** (the symbol trades at a premium to peers).

If only 2 peers existed in the Industrial sector, the engine would fall back to whole-universe medians and `scope` would shift to `"market"` for each metric (with a quality flag on the snapshot).

---

## 7. Reverse DCF (Diagnostic)

**Function:** `_reverse_dcf` (`valuation.py:515`).

> ⚠️ **Known issue [V9](12-known-issues-and-limitations.md#-v9--reverse-dcf-returns-fair_value--current_price):** currently returns `fair_value = current_price`, so the UI shows 0% upside. The actual diagnostic is `implied_perpetual_growth` in `outputs`. After V9 fix, `fair_value=None` and the diagnostic is rendered differently.

**Equation:**

```
implied_perpetual_growth = WACC - FCF_Yield
```

i.e., "what perpetual growth rate would justify today's price under our WACC?"

**Inputs:**
- `MarketCap_Calc` and `Current_Price` (both required for eligibility check).
- `FCF_Yield` from snapshot.
- `wacc` from assumptions.

**Eligibility:**
- Has market cap AND current price.

**Confidence:**
- `"medium"` always (it's a diagnostic).

**Worked example — Moroccan industrial:**

| Input | Value |
|---|---|
| MarketCap | MAD 24,500M |
| FCF_Yield | 4.9% |
| WACC | 10.5% |

implied_perpetual_growth = 0.105 - 0.049 = **5.6%**

Interpretation: the market is pricing this stock as if FCF will grow at 5.6% forever. Cross-check against the firm's sustainable growth (`g = ROE × retention`). If sustainable growth is, say, 7% the price is reasonable (market is pessimistic). If sustainable growth is 3% the price is rich.

This is the **complement** to the other intrinsic models: they ask "what is fair value?"; reverse DCF asks "what does the market believe?".

---

## How models interact (the ensemble)

See [07-ensemble-and-confidence.md](07-ensemble-and-confidence.md) for the full breakdown. Short version:

```
For each model m in {fcff_dcf, fcfe_dcf, ddm, residual_income, justified_multiples, relative_multiples}:
    if eligible AND fair_value computed AND confidence != "unavailable":
        accumulate fair_value as a candidate

reject cross-model outliers around the candidate median:
    if >=4 candidates: median +/- ensemble_outlier_mad_k * 1.4826 * MAD
    else: broad median-relative guardrail from the assumption registry

fair_value_base = median(surviving fair values)
fair_value_mean = mean(surviving fair values)        # diagnostic only
fair_value_low/high = Q1/Q3 or min/max of survivors
model_weights = equal inclusion weights across survivors
confidence_score = weighted sum of coverage, model agreement, and observed-input quality
```

Reverse DCF is **always excluded** from the ensemble (family="diagnostic").

## Model selection heuristic

Quick guide for analysts:

| Firm profile | Trust most |
|---|---|
| Stable industrial, positive FCF, low leverage | FCFF DCF |
| Bank or insurer | Residual income + Justified P/B |
| Dividend-paying utility | DDM + Justified P/E |
| High-growth firm, peers exist | Relative multiples (P/S, EV/EBITDA) |
| Holding company / conglomerate | Relative multiples (P/B) + ensemble |
| Cyclical at trough | Check `diagnostics.smoothing` and consider sensitivity/scenario outputs |
| Distressed | None of these — engine likely returns low confidence |

If the ensemble fair value disagrees with one specific model by >30%, that model is the "swing vote" — read its warnings and inputs carefully before trusting the ensemble.

---

# Step-by-step algorithm traces

This section walks through what happens **inside each model** when `compute_symbol_valuations` is called. For every model:

1. **Input ingestion** — what data is pulled from the snapshot, with the fallback chain.
2. **Computation steps** — numbered. Each step states *What* (the operation), *Why* (the textbook/discipline reason), *Where* (file:line), and *Result* (the intermediate value).
3. **Output assembly** — what's persisted in `ValuationResult.inputs` and `.outputs` for the UI to render.
4. **Worked numerical example** — every intermediate value shown explicitly.

These traces reflect the **v3 engine** (post-V1–V12 fixes). They use a synthetic Moroccan industrial (IRD-INDUS) and a Moroccan bank (ATWB) as running examples. Numbers are illustrative.

---

## Trace 1 — FCFF DCF (`_fcff_dcf` at `valuation.py:419`)

### Input ingestion

The model reads from three sources:

| Input | Source | Fallback chain |
|---|---|---|
| Starting FCF | `_fcf_start` (`valuation.py:312`) | 1. `Free_Cash_Flow` from history → 2. `MarketCap × FCF_Yield` → 3. `Revenue × FCF_Margin` → 4. None |
| Growth rate | `_fcf_growth_input` | observed FCF/cash-flow growth, then earnings/revenue proxy, then history CAGR; missing inputs make the dependent projection unavailable instead of injecting a placeholder |
| Net debt | `_net_debt_bridge` | `NetDebt` from history, then `Total_Debt - Cash`; missing or partial bridges are warning-bearing data-quality issues |
| WACC, terminal_growth, forecast_years, growth_cap | assumption set | scenario default → global → sector → symbol-scoped (see `08-assumptions-and-defaults.md`) |
| Shares outstanding | `Shares_Outstanding` from snapshot | none |

### Computation steps

**Step 1 — Resolve starting FCF.**
*What:* call `_fcf_start(snapshot, history)`.
*Why:* the DCF horizon's first year cash flow is the anchor. Reported FCF preferred over derived because derived values inherit definitional differences (margin × revenue assumes operating consistency).
*Where:* `valuation.py:421`.
*Result:* `(fcf, fcf_source)` — e.g. `(1200.0, "reported_free_cash_flow")` for IRD-INDUS.

**Step 2 — Resolve growth input.**
*What:* call `_fcf_growth_input(snapshot, history, assumptions)`.
*Why:* growth rate drives ~60% of fair value in a 5y DCF. Preference is given to direct FCF growth signals because they don't carry margin-bias (V4 fix — was Revenue_Growth-only pre-v3).
*Where:* `valuation.py:432`.
*Result:* `(growth, growth_source, is_proxy)` — e.g. `(0.06, "reported_fcf_growth", False)`. If `is_proxy=True`, the source name is appended to warnings.

**Step 3 — Resolve net debt bridge.**
*What:* call `_net_debt_bridge(history)`.
*Why:* FCFF DCF computes enterprise value; equity value = EV − net debt. Missing net debt would overstate equity by the full debt amount.
*Where:* `valuation.py:435`.
*Result:* `(net_debt, net_debt_source, warning_needed)` — e.g. `(1500.0, "reported_net_debt", False)`. If warning_needed, `"missing_net_debt_bridge"` joins warnings.

**Step 4 — Eligibility & sanity gates.**
*What:* check that `fcf > 0`, `shares > 0`, `WACC > terminal_growth`.
*Why:* DCF degenerate cases — negative starting cash, zero shares, or terminal growth ≥ discount rate all produce nonsense or division-by-zero.
*Where:* `valuation.py:423-430`.
*Result:* one or more entries appended to `warnings` if a gate fails. If gates pass, proceed to step 5.

**Step 5 — Project cash flows with linear growth fade.**
*What:* call `_dcf_cash_flows(start=fcf, growth=g_initial, terminal_growth=g_terminal, discount_rate=WACC, years=5)`. Inside, for each year t ∈ {1..5}: compute `fade_t = t/5`, `step_growth = g_initial × (1−fade_t) + g_terminal × fade_t`, then `fcf_t = fcf_{t-1} × (1 + step_growth)` and discount.
*Why:* linear growth fade smooths the transition from initial to terminal — avoids the cliff that flat-growth DCFs produce at year forecast_years + 1.
*Where:* `valuation.py:403`.
*Result:* `(projected_fcf_list, present_value_with_terminal)`. The list has 5 values; the second element is the enterprise value PV.

**Step 6 — Bridge enterprise value to equity.**
*What:* `equity_value = enterprise_value - net_debt`.
*Why:* if the bridge produces non-positive equity value, the model returns `fair_value=None` with `fcf_dcf_unavailable_nonpositive_equity_value`; it is not floored to zero.
*Where:* `valuation.py:443`.
*Result:* equity value in MAD M.

**Step 7 — Per-share fair value.**
*What:* `fair = equity_value / shares_outstanding`.
*Why:* the analyst's reference point is share price, not market cap.
*Where:* `valuation.py:443`.
*Result:* fair value per share.

**Step 8 — Assign confidence.**
*What:* base = `"high"` if `≥3 years of positive FCF history`, else `"medium"`. Then `_confidence(base, warnings, proxy=False)` haircuts based on warning count.
*Why:* a stable 3+ year positive FCF run is empirical evidence the firm generates real cash. Without it, the DCF rests on weaker ground.
*Where:* `valuation.py:444-445`.
*Result:* one of `"high"`, `"medium"`, `"low"`, `"unavailable"`.

### Output assembly

```json
inputs: {
    "fcf_start": 1200.0,
    "fcf_source": "reported_free_cash_flow",
    "growth": 0.06,
    "fcf_growth_source": "reported_fcf_growth",
    "wacc": 0.0851,
    "terminal_growth": 0.03,
    "net_debt": 1500.0,
    "net_debt_source": "reported_net_debt"
}
outputs: {
    "projected_fcf": [1252.8, 1303.7, 1352.4, 1397.7, 1438.6]
}
```

### Worked example — IRD-INDUS

Inputs from snapshot: FCF=1200, Revenue_Growth=8%, FCF_Growth=6%, NetDebt=1500, Shares=100, WACC=8.51% (v3 default), terminal_growth=3%, forecast_years=5.

| Year | fade_t | step_growth | FCF (MAD M) | Discount factor | PV (MAD M) |
|---|---|---|---|---|---|
| 1 | 0.20 | 6.0% × 0.8 + 3.0% × 0.2 = **5.4%** | 1200 × 1.054 = **1264.8** | 1.0851 | 1165.6 |
| 2 | 0.40 | 6.0% × 0.6 + 3.0% × 0.4 = **4.8%** | 1264.8 × 1.048 = **1325.5** | 1.0851² = 1.1774 | 1125.6 |
| 3 | 0.60 | 6.0% × 0.4 + 3.0% × 0.6 = **4.2%** | 1325.5 × 1.042 = **1381.2** | 1.0851³ = 1.2775 | 1081.3 |
| 4 | 0.80 | 6.0% × 0.2 + 3.0% × 0.8 = **3.6%** | 1381.2 × 1.036 = **1430.9** | 1.0851⁴ = 1.3862 | 1032.4 |
| 5 | 1.00 | 6.0% × 0.0 + 3.0% × 1.0 = **3.0%** | 1430.9 × 1.030 = **1473.8** | 1.0851⁵ = 1.5042 | 979.8 |

Sum of explicit-period PVs = 5384.7 MAD M.

Terminal value at year 5 = `1473.8 × 1.03 / (0.0851 − 0.03) = 1517.9 / 0.0551 = 27,548 MAD M`.
PV of terminal = `27,548 / 1.5042 = 18,313 MAD M`.

Enterprise value = 5384.7 + 18,313 = **23,698 MAD M**.
Equity value = 23,698 − 1500 = **22,198 MAD M**.
Fair value per share = 22,198 / 100 = **MAD 221.98**.

Note: this is materially higher than the pre-v3 worked example (which used WACC=10.5%). The drop in WACC from V7 fix lifts intrinsic value across all FCFF DCFs.

### What each warning means

| Warning | Triggers when | Effect |
|---|---|---|
| `missing_positive_fcf` | `fcf ≤ 0` after fallback chain | fair_value = None |
| `missing_shares` | shares not in snapshot | fair_value = None |
| `wacc_not_above_terminal_growth` | `WACC ≤ terminal_growth` | fair_value = None |
| `earnings_growth_proxy` / `revenue_growth_proxy` | growth source is income-statement, not cash-flow | confidence may demote |
| `missing_net_debt_bridge` | NetDebt missing AND Total_Debt missing | confidence demotes; bridge assumed zero |

---

## Trace 2 — FCFE DCF (`_fcfe_dcf` at `valuation.py:469`)

### Input ingestion

| Input | Source |
|---|---|
| Starting FCFE | `_fcfe_start` (`valuation.py:359`): if debt-flow data present (`Interest_Expense`, `Debt_Issuance`, `Debt_Repayment`), computes `FCF − after_tax_interest + net_borrowing`; else falls back to raw FCF with `is_proxy=True` |
| Growth | `NetIncome_Growth` or `Revenue_Growth`, capped at `growth_cap` |
| Cost of equity | from assumptions |
| Terminal growth, forecast_years | from assumptions |
| Shares outstanding | snapshot |

### Computation steps

**Step 1 — Resolve FCFE start.**
*What:* `_fcfe_start(snapshot, history, assumptions)`. If `Interest_Expense`, `Debt_Issuance`, or `Debt_Repayment` are present → compute proper FCFE = FCF − interest × (1 − tax_rate) + (issuance − repayment). Else fall back to raw FCF with `is_proxy=True`.
*Why:* true FCFE captures the leverage effect on equity cash flow. The proxy is honest about the limitation (V1 fix).
*Where:* `valuation.py:471`.
*Result:* `(fcfe, source_label, is_proxy)`. Example: `(1080.0, "reported_free_cash_flow_adjusted_for_debt_flows", False)`.

**Step 2 — Sanity gates.**
*What:* check `fcfe > 0`, `shares > 0`, `cost_of_equity > terminal_growth`.
*Why:* identical motivation to FCFF gates.
*Where:* `valuation.py:475-482`.

**Step 3 — Project at cost of equity.**
*What:* call `_dcf_cash_flows(start=fcfe, ..., discount_rate=cost_of_equity, ...)`.
*Why:* FCFE is an equity-level cash flow, so discount at the cost of equity (not WACC). No net-debt bridge needed — leverage is already inside FCFE.
*Where:* `valuation.py:488`.
*Result:* `(projected_fcfe, equity_value)`.

**Step 4 — Per-share fair value.**
*What:* `fair = equity_value / shares` when equity value is positive; otherwise the model is unavailable. No EV→Equity bridge.
*Where:* `valuation.py:490`.
*Result:* fair value per share.

**Step 5 — Confidence + proxy treatment.**
*What:* base = `"high"` if not proxy AND ≥3 years positive FCF history, else `"medium"`. Then `_confidence(base, warnings, proxy=is_proxy)` haircuts on proxy and warnings.
*Why:* proxy automatically demotes high confidence and lowers observed-input quality in the ensemble confidence formula.
*Where:* `valuation.py:491-492`.

### Output assembly

```json
inputs: {
    "fcfe_start": 1080.0,
    "fcfe_source": "reported_free_cash_flow_adjusted_for_debt_flows",
    "growth": 0.05,
    "cost_of_equity": 0.105,
    "terminal_growth": 0.03
}
outputs: {
    "projected_fcfe": [...]
}
```

### Worked example — IRD-INDUS (with debt-flow data)

Assume: FCF=1200, Interest_Expense=80, Tax_Rate=30%, Debt_Issuance=100, Debt_Repayment=50.

Step 1: FCFE = 1200 − 80 × (1 − 0.30) + (100 − 50) = 1200 − 56 + 50 = **MAD 1194 M**, `is_proxy=False`.

Steps 2-3: project at COE = 10.5%, terminal_growth = 3%, growth = 5% (from NetIncome_Growth). Using the same fade mechanism as FCFF DCF:

| Year | step_growth | FCFE (MAD M) | Discount factor (1.105^t) | PV (MAD M) |
|---|---|---|---|---|
| 1 | 5%×0.8 + 3%×0.2 = 4.6% | 1248.9 | 1.105 | 1130.2 |
| 2 | 5%×0.6 + 3%×0.4 = 4.2% | 1301.4 | 1.2210 | 1066.0 |
| 3 | 5%×0.4 + 3%×0.6 = 3.8% | 1350.8 | 1.3492 | 1001.2 |
| 4 | 5%×0.2 + 3%×0.8 = 3.4% | 1396.7 | 1.4909 | 936.8 |
| 5 | 5%×0.0 + 3%×1.0 = 3.0% | 1438.6 | 1.6474 | 873.2 |

Sum explicit PVs = 5007.4 MAD M.
Terminal = `1438.6 × 1.03 / (0.105 − 0.03) = 1481.8 / 0.075 = 19,757 MAD M`.
PV(terminal) = `19,757 / 1.6474 = 11,994 MAD M`.
Equity value = 5007.4 + 11,994 = **16,991 MAD M**.
Fair value per share = 16,991 / 100 = **MAD 170.0**.

Compare with the FCFF DCF result (MAD 221.98). The gap = 22,198 − 16,991 = 5,207 MAD M, which corresponds roughly to the value impact of leverage being captured directly in cash flow vs being deducted at the EV bridge. Both are valid — they answer slightly different questions ("what's the firm worth?" vs "what's the equity holder's cash flow worth?").

If `Interest_Expense` etc. are missing, the model falls back to raw FCF, sets `is_proxy=True`, and appends warning `"fcfe_proxy_from_free_cash_flow"`. The fair value can still survive, but proxy status lowers confidence/data quality rather than creating a separate ensemble weight cap.

---

## Trace 3 — DDM (`_ddm` at `valuation.py:525`)

### Input ingestion

| Input | Source |
|---|---|
| Dividend per share | latest `"Dividendes"` / shares if present, else `current_price × Dividend_Yield` |
| Growth | `_sustainable_dividend_growth` (V2 fix): `g = ROE × (1 − payout)`, capped at growth_cap; fallback to `NetIncome_Growth` if ROE missing |
| Cost of equity, terminal_growth, fade_years | assumption set |

### Computation steps

**Step 1 — Resolve dividend per share.**
*What:* prefer total dividends / shares; fallback to `current_price × Dividend_Yield`.
*Why:* reported total dividends tie to the latest audited period; yield fallback covers market-only snapshots.
*Where:* `_ddm`.
*Result:* `dividend_per_share`. If missing, `"missing_positive_dividend"` warning fires.

**Step 2 — Resolve sustainable growth.**
*What:* call `_sustainable_dividend_growth(snapshot, history, assumptions)`. Returns `g = group_basis_ROE × (1 − payout)` when RNPG and group equity tie out; else falls back to earnings growth with `using_earnings_growth_proxy` warning.
*Why:* DDM growth must be **dividend** growth. The sustainable identity `g = ROE × retention` is the textbook ceiling on dividend growth (V2 fix replaced NetIncome_Growth).
*Where:* `_sustainable_dividend_growth`.
*Result:* `(growth, source, warnings)`.

**Step 3 — Apply H-model DDM formula.**
*What:* `fair = D × ((1 + terminal_growth) + H × max(0, g − terminal_growth)) / (cost_of_equity − terminal_growth)`, with `H = fade_years / 2`.
*Why:* sustainable dividend growth can exceed terminal growth temporarily, but it should not be embedded as a perpetuity. The H-model values that temporary spread over the fade horizon.
*Where:* `_ddm`.
*Result:* fair value per share, or None if `cost_of_equity ≤ terminal_growth`.

**Step 4 — Confidence.**
*What:* base `"high"` if `Dividend_Yield` present, else `"medium"`. Haircut by warnings.
*Where:* `_ddm`.

### Output assembly

```json
inputs: {
    "dividend_per_share": 7.98,
    "growth": 0.045,
    "growth_source": "sustainable_growth_from_roe_retention",
    "cost_of_equity": 0.105,
    "terminal_growth": 0.03,
    "fade_years": 5,
    "h_factor": 2.5
}
```

### Worked example — Moroccan utility

Snapshot: Current_Price=145, Dividend_Yield=5.5%, ROE=12%, Dividend_Payout=60%, COE=10.5%, terminal_growth=3%, fade_years=5.

Step 1: dividend = 145 × 0.055 = **MAD 7.98**.
Step 2: retention = 1 − 0.60 = 0.40; sustainable growth = 0.12 × 0.40 = **4.8%**.
Step 3: H = 5 / 2 = 2.5; spread = 4.8% − 3.0% = 1.8%.
Step 4: fair = 7.98 × ((1 + 0.03) + 2.5 × 0.018) / (0.105 − 0.03) = **MAD 114.3**.

Upside = 114.3 / 145 − 1 = **−21.2%** (downside). The dividend stream alone doesn't justify the price. Cross-check with FCFF DCF and reverse DCF before concluding.

---

## Trace 4 — Residual Income (`_residual_income` at `valuation.py:582`)

### Input ingestion

| Input | Source |
|---|---|
| Book value per share | `current_price / Price_to_Book` (proxy from market price; flagged if missing) |
| ROE | verified raw lines: RNPG / average group equity |
| Payout (for reinvestment in book) | snapshot.metrics, fallback to stable_payout_ratio |
| Cost of equity, fade_years | assumption set |

### Computation steps

**Step 1 — Resolve book value per share.**
*What:* `book_value_per_share = current_price / Price_to_Book`.
*Why:* book value isn't directly in the snapshot; the P/B ratio + price recovers it. Proxy is acceptable because the ratio is an analyst-vetted output.
*Where:* `_residual_income`.
*Result:* book value per share, or None (warning `missing_book_value_proxy`).

**Step 2 — Resolve retention rate.**
*What:* `retention = 1 − payout`. If payout is missing or out-of-range, use `stable_payout_ratio` default (warning `using_stable_payout_assumption`).
*Why:* retention drives how book value grows year-over-year. Without payout discipline, RI projections explode unrealistically.
*Where:* `_residual_income`.

**Step 3 — Project residual income with shifted linear ROE fade.**
*What:* for year t ∈ {1..fade_years + 1}: compute `fade_t = (t − 1)/fade_years`, `roe_t = roe × (1−fade_t) + cost_of_equity × fade_t`, then `RI_t = book_t × (roe_t − cost_of_equity)` and `book_{t+1} = book_t × (1 + roe_t × retention)`.
*Why:* the ROE-COE spread is the source of excess returns. V14 keeps year 1 at full current ROE, then fades to zero spread at the terminal projected year.
*Where:* `_residual_income`.
*Result:* list of projected residual income values, each discounted at cost_of_equity.

**Step 4 — Sum to get fair value.**
*What:* `fair = book_value + PV(RI_t)`.
*Why:* fair value = book + present value of all future excess returns. By year `fade_years + 1`, RI ≈ 0 (spread closed), so no terminal value beyond.
*Where:* `_residual_income`.

**Step 5 — Confidence.**
*What:* base confidence is earned from observed book value, ROE/net-income history, proxy status, and warning count. RI is eligible for financials, but sector alone no longer grants a high-confidence floor.
*Where:* `_residual_income`.

### Output assembly

```json
inputs: {
    "book_value_per_share": 211.11,
    "roe": 0.14,
    "cost_of_equity": 0.105,
    "fade_years": 5,
    "payout": 0.60
}
outputs: {
    "projected_residual_income": [
        {"year": 1, "roe": 0.1400, "book_value": 211.11, "residual_income": 7.39},
        {"year": 2, "roe": 0.1330, "book_value": 222.93, "residual_income": 6.24},
        ...
    ]
}
```

### Worked example — ATWB (Moroccan bank)

Snapshot: Current_Price=380, P/B=1.8, ROE=14%, Payout=60% → retention=40%, COE=10.5%, fade_years=5.

Book value per share = 380 / 1.8 = **MAD 211.11**.

| Year | fade_t | roe_t | book (start) | RI = book × (roe_t − 0.105) | PV factor | PV(RI) |
|---|---|---|---|---|---|---|
| 1 | 0.00 | **14.00%** | 211.11 | 211.11 × 0.0350 = **7.39** | 1.105 | 6.69 |
| 2 | 0.20 | 14%×0.8 + 10.5%×0.2 = **13.30%** | 222.93 | 222.93 × 0.0280 = **6.24** | 1.2210 | 5.11 |
| 3 | 0.40 | 14%×0.6 + 10.5%×0.4 = **12.60%** | 234.79 | 234.79 × 0.0210 = **4.93** | 1.3492 | 3.65 |
| 4 | 0.60 | 14%×0.4 + 10.5%×0.6 = **11.90%** | 246.63 | 246.63 × 0.0140 = **3.45** | 1.4909 | 2.32 |
| 5 | 0.80 | 14%×0.2 + 10.5%×0.8 = **11.20%** | 258.37 | 258.37 × 0.0070 = **1.81** | 1.6474 | 1.10 |
| 6 | 1.00 | **10.50%** | 269.94 | 269.94 × 0.0000 = **0.00** | 1.8204 | 0.00 |

Σ PV(RI) = 6.69 + 5.11 + 3.65 + 2.32 + 1.10 + 0 = **18.87 MAD**.
Fair value = 211.11 + 18.87 = **MAD 229.98**.

Compare against pre-V14 fade-from-year-1: the shifted fade lifts fair value because the first projection year now uses full ROE. The old no-fade perpetuity would still be much higher, so the downside conclusion remains disciplined.

Cross-check: upside = 229.98 / 380 − 1 = **−39.5%** (downside) — the bank looks substantially overvalued by RI even after the V14 correction.

---

## Trace 5 — Justified Multiples (`_justified_multiples` in `valuation.py`)

### Input ingestion

| Input | Source |
|---|---|
| ROE, payout, P/B, PER | ROE from verified raw lines; payout/P/B/PER from snapshot |
| Cost of equity, terminal_growth, fade_years, growth_cap, stable_payout_ratio | assumption set |

### Computation steps

**Step 1 — Resolve retention and sustainable growth.**
*What:* same logic as DDM: `retention = 1 − payout`, `sustainable_growth = ROE × retention` capped at `growth_cap`. Use `stable_payout_ratio` if payout missing/invalid.
*Where:* `_justified_multiples`.

**Step 2 — Apply H-model growth conversion (post-V6).**
*What:* `_justified_growth(sustainable_growth, terminal_growth, fade_years, cost_of_equity)` — if sustainable growth is above terminal growth, the helper prices the finite fade as an H-model and solves for the Gordon-equivalent growth rate.
*Why:* pre-v3 growth was clipped to `min(terminal, sustainable)`. The first V6 fix used a linear average, but plugging that average into a perpetuity overstated temporary growth. The H-model keeps the supernormal phase finite.
*Where:* `_justified_growth`.

**Step 3 — Compute justified P/B and P/E.**
*What:*
- `justified_PB = (ROE − growth) / (cost_of_equity − growth)` (Damodaran derivation from Gordon).
- `justified_PE = payout × (1 + growth) / (cost_of_equity − growth)`.
*Why:* both are the closed-form multiples consistent with the firm's ROE, payout, growth, and required return.
*Where:* `_justified_multiples`.

**Step 4 — Translate to implied prices.**
*What:* `implied_price_PB = current_price × justified_PB / current_PB`, similarly for PE.
*Why:* if the firm's *current* P/B is less than its *justified* P/B, the market is mispricing — implied price = current × (justified / current) shows where it "should" trade.
*Where:* `_justified_multiples`.

**Step 5 — Aggregate.**
*What:* use the median of the raw implied prices.
*Why:* the median is robust to one bad multiple. Any extreme that is inconsistent with the rest of the model set is handled later by cross-model outlier rejection, not by a price-anchored clamp inside this model.
*Where:* `_justified_multiples`.

### Output assembly

```json
inputs: {
    "roe": 0.14,
    "payout": 0.60,
    "sustainable_growth": 0.056,
    "growth": 0.0342,
    "growth_model": "h_model_equivalent",
    "terminal_growth": 0.03,
    "fade_years": 5,
    "cost_of_equity": 0.105
}
outputs: {
    "implied_prices": {
        "justified_pb": 315.4,
        "justified_pe": 256.1
    },
    "implied_prices_raw": {
        "justified_pb": 315.4,
        "justified_pe": 256.1
    },
    "justified_multiples": {"implied_pb": 1.494, "implied_pe": 8.76},
    "multiple_deltas": {"implied_pb_vs_current": -0.17, "implied_pe_vs_current": -0.33}
}
```

### Worked example — ATWB (continuing from RI)

Snapshot: Current_Price=380, P/B=1.8, PER=13, ROE=14%, Payout=60%, COE=10.5%, terminal_growth=3%, fade_years=5.

Step 1: retention=0.40, sustainable_growth = 0.14 × 0.40 = **5.6%** (under cap of 8%).

Step 2: Since 5.6% > 3% (terminal), apply the H-model conversion:
- H = 5 / 2 = **2.5**
- h_model_factor = ((1 + 0.03) + 2.5 × (0.056 − 0.03)) / (0.105 − 0.03) = **14.60**
- equivalent growth = (14.60 × 0.105 − 1) / (14.60 + 1) = **3.42%**

Step 3:
- `justified_PB = (0.14 − 0.0342) / (0.105 − 0.0342) = **1.494**`.
- `justified_PE = 0.60 × 1.0342 / (0.105 − 0.0342) = **8.76**`.

Step 4:
- `implied_price_PB = 380 × 1.494 / 1.8 = **MAD 315.4**`.
- `implied_price_PE = 380 × 8.76 / 13 = **MAD 256.1**`.

Step 5: fair_value = median(PB, PE) = **MAD 285.8**.

Note the V6 impact: pre-v3 growth was clipped to 3%, giving `justified_PB = (0.14 − 0.03) / (0.105 − 0.03) = 1.467` and implied_price_PB = 309.6. The H-model-equivalent growth raises the P/B implied price modestly to 315.4 while avoiding the overstatement that came from using a linear-average growth rate as a perpetuity.

---

## Trace 6 — Relative Multiples (`_relative_multiples` at `valuation.py:638`)

### Input ingestion

| Input | Source |
|---|---|
| Own multiples (PER, Price_to_Book, Price_to_Sales, EV_to_EBITDA) | snapshot, except PER/P-Sales prefer 3-year history-normalized flow denominators |
| Peer median per metric + cohort scope (sector vs market) + cohort count | `_peer_stats` at `valuation.py:229` |
| Current price | snapshot |

### Computation steps

**Step 1 — Build peer statistics.**
*What:* `_peer_stats(snapshots, sectors, target_symbol, peer_min_count)` iterates all other symbols in the import cohort. For each of 4 multiples (PER, P/B, P/S, EV/EBITDA), it collects positive values into:
- `grouped[metric]` — same-sector peers only.
- `fallback[metric]` — all peers in the universe.
Then for each metric, if `len(grouped) ≥ peer_min_count` (default 3), use sector median + `scope="sector"`; else fall back to market median + `scope="market"`.
*Why:* sector cohorts are the right reference for cyclicality and growth profile, but Moroccan equity sectors are often too thin (<3 peers). The market fallback prevents the model from going dark on thin sectors.
*Where:* `valuation.py:229-258`.
*Result:* `peer_stats = {"PER": {"median": 14.0, "count": 5, "scope": "sector"}, ...}`.

**Step 2 — Compute implied prices per multiple.**
*What:* for each metric in `peer_stats`:
- `own = normalized own multiple` (PER = MarketCap / 3-year average net income; P/S = MarketCap / 3-year average revenue; P/B and EV/EBITDA use spot)
- `peer = peer_stats[metric]["median"]`
- `implied_price = current_price x peer / own`
*Why:* if the firm's own multiple is X and peers trade at Y, the firm should trade at a price proportional to Y/X relative to current. Higher own multiple → implied price lower (overvalued vs peers); lower own → higher (undervalued).
*Where:* `_relative_multiples` in `valuation.py`.
*Result:* `implied = {"PER": 190.6, "Price_to_Book": 178.2, "EV_to_EBITDA": 196.0, ...}`.

**Step 3 — Aggregate via median.**
*What:* `fair_value = median(implied.values())`.
*Why:* median is robust to one outlier multiple (e.g. PER distorted by negative earnings).
*Where:* `valuation.py:651`.

**Step 4 — Confidence based on cohort breadth.**
*What:*
- ≥3 metrics with implied prices → base `"high"`.
- 2 metrics → `"medium"`.
- 1 metric → `"low"`.
- 0 → `"unavailable"`.
*Why:* more independent metrics = more robust peer signal.
*Where:* `valuation.py:652`.

### Output assembly

```json
inputs: {
    "peer_stats": {
        "PER": {"median": 14.0, "count": 5, "scope": "sector"},
        "Price_to_Book": {"median": 1.6, "count": 5, "scope": "sector"},
        "Price_to_Sales": {"median": 1.0, "count": 4, "scope": "sector"},
        "EV_to_EBITDA": {"median": 8.0, "count": 28, "scope": "market"}
    },
    "own_multiples": {"PER": 18.0, "Price_to_Book": 2.2, "Price_to_Sales": 1.4, "EV_to_EBITDA": 10.0},
    "own_multiple_basis": {"PER": "market_cap_over_3y_avg_net_income", "Price_to_Sales": "market_cap_over_3y_avg_revenue"}
}
outputs: {
    "implied_prices": {
        "PER": 190.6,
        "Price_to_Book": 178.2,
        "Price_to_Sales": 175.0,
        "EV_to_EBITDA": 196.0
    },
    "implied_prices_raw": {
        "PER": 190.6,
        "Price_to_Book": 178.2,
        "Price_to_Sales": 175.0,
        "EV_to_EBITDA": 196.0
    }
}
```

### Worked example — IRD-INDUS

Current price = MAD 245. Own multiples vs sector peers (4 peers for PER/PB/PS, 1 peer for EV/EBITDA → market fallback):

| Metric | Own (snapshot) | Peer median | Cohort | n | Implied price |
|---|---|---|---|---|---|
| PER | 18 | 14 | sector | 5 | 245 × 14/18 = **MAD 190.6** |
| Price_to_Book | 2.2 | 1.6 | sector | 5 | 245 × 1.6/2.2 = **MAD 178.2** |
| Price_to_Sales | 1.4 | 1.0 | sector | 4 | 245 × 1.0/1.4 = **MAD 175.0** |
| EV_to_EBITDA | 10 | 8 | market | 28 | 245 × 8/10 = **MAD 196.0** |

fair_value = median(190.6, 178.2, 175.0, 196.0) = (178.2 + 190.6) / 2 = **MAD 184.4**.
Upside = 184.4 / 245 − 1 = **−24.7%** — the symbol trades at a 25% premium to peers.

The `scope` column tells the analyst that EV/EBITDA used the **market median** (only 1 same-sector peer; sector group was too thin). Treat that line with extra caution — the cohort is heterogeneous.

If the user changes the sector classification on `stock_master` (e.g. moves the symbol from "Industries" to "Industries lourdes"), the peer cohort changes and the implied prices change accordingly. This is why sector hygiene matters.

---

## Trace 7 — Reverse DCF (`_reverse_dcf` at `valuation.py:669`)

> **This is the model the user specifically called out.** Reverse DCF answers: "what perpetual growth rate would justify today's price under our WACC?" — the inverse of "what's fair value given growth?".

### Input ingestion

| Input | Source |
|---|---|
| Market cap | `MarketCap_Calc` from snapshot (eligibility gate) |
| Current price | snapshot (eligibility gate) |
| FCF Yield | `FCF_Yield` from snapshot (the actual computation input) |
| WACC | assumption set |

### Computation steps

**Step 1 — Eligibility check.**
*What:* require both market cap AND current price to be present.
*Why:* without market cap we can't reason about the market's implicit cash-flow valuation. The model is a market-listening exercise.
*Where:* `valuation.py:267`, eligibility evaluation in `_eligible_models`.
*Result:* either proceed, or return `_unavailable`.

**Step 2 — Pull FCF yield.**
*What:* `fcf_yield = _ratio(snapshot.metrics["FCF_Yield"])`.
*Why:* FCF Yield = FCF / Market Cap. It's already the "cash return" the market is buying today.
*Where:* `valuation.py:672`.
*Result:* a fraction (e.g. 0.049). If missing/non-positive → warning `missing_fcf_yield_for_reverse_dcf`, `implied = None`.

**Step 3 — Solve for implied growth.**
*What:* `implied_perpetual_growth = WACC − FCF_Yield`.
*Why:* the Gordon DCF says `MarketCap = FCF × (1 + g) / (WACC − g)`. Solving for g when `MarketCap / FCF = 1 / FCF_Yield` gives `g = WACC − FCF_Yield` (taking the first-order approximation, ignoring the `(1+g)` numerator effect).
*Where:* `valuation.py:675`.
*Result:* a perpetual growth rate (e.g. 0.0361 = 3.61%).

**Step 4 — Build interpretation narrative.**
*What:* outputs.interpretation = `"Market implies {implied×100:.1f}% perpetual FCF growth at WACC={wacc×100:.1f}%."`.
*Why:* a number alone is opaque. The narrative tells the analyst what to compare against (their own growth estimate, sustainable growth from `g = ROE × retention`).
*Where:* `valuation.py:689-693`.

**Step 5 — Return WITHOUT a fair value.**
*What:* explicitly set `fair_value=None`, `family="diagnostic"`.
*Why:* the model doesn't answer "what's fair value?" — it answers "what does the market think?". Returning `current_price` as fair value (pre-v3 behavior) misled users into seeing "0% upside" everywhere (V9 fix).
*Where:* `valuation.py:679-697`.
*Result:* `ValuationResult(fair_value=None, family="diagnostic", outputs={implied_perpetual_growth, interpretation})`. Always excluded from the ensemble.

### Output assembly

```json
inputs: {
    "market_cap": 24500.0,
    "fcf_yield": 0.049,
    "wacc": 0.0851
}
outputs: {
    "implied_perpetual_growth": 0.0361,
    "interpretation": "Market implies 3.6% perpetual FCF growth at WACC=8.5%."
}
```

### Worked example — IRD-INDUS

Inputs: MarketCap=24,500 MAD M, FCF_Yield=4.9%, WACC=8.51% (v3 default).

Step 3: `implied_perpetual_growth = 0.0851 − 0.049 = **3.61%**`.

Interpretation: the market is pricing IRD-INDUS as if FCF will grow at 3.61% forever. Cross-check:
- Recent FCF growth = 6% (above implied → market is pessimistic → potential bargain).
- Sustainable growth = ROE × retention. If IRD-INDUS has ROE=12% and pays 50% out, sustainable = 12% × 50% = 6% (matches FCF growth — market is more pessimistic than fundamentals warrant).
- Long-term GDP + inflation = ~5% (above implied 3.61% — market is below trend GDP).

All three checks agree: market expects substantially below-trend growth. IRD-INDUS may be undervalued by intrinsic methods (consistent with the FCFF DCF result of MAD 221.98 above its current price).

### How to use reverse DCF in practice

| Implied growth vs ... | Means |
|---|---|
| < terminal_growth | Market expects sub-economic growth — usually overly pessimistic, possibly a recovery play |
| ≈ terminal_growth | Market expects nothing special — fairly priced if your model agrees |
| > terminal_growth but ≤ sustainable_growth | Market expects above-average growth, justifiable if fundamentals support it |
| > sustainable_growth | Market expects more than the firm can mechanically deliver — possible overvaluation |
| > growth_cap (8%) | Market is pricing in heroic growth — high reversion risk |

### What each warning means

| Warning | Triggers when | Effect |
|---|---|---|
| `missing_fcf_yield_for_reverse_dcf` | `FCF_Yield ≤ 0` or absent | `implied_perpetual_growth = None`, model can't run |

---

## Cross-trace summary

Each model produces a `ValuationResult` with the same shape. The differences are in **which inputs are read** and **which computation steps run**. The table below summarizes the per-model trace structure so an analyst can compare them at a glance:

| Model | Primary inputs | Key outputs | Trace length | Where it dominates |
|---|---|---|---|---|
| FCFF DCF | FCF, growth, WACC, NetDebt, shares | `projected_fcf` list | 8 steps | Non-financial firms with FCF history |
| FCFE DCF | FCFE (or proxy), COE, growth, shares | `projected_fcfe` list | 5 steps | Leveraged non-financials with debt-flow data |
| DDM | Dividend per share, sustainable growth, COE | (no array outputs) | 4 steps | Dividend-paying utilities and mature names |
| Residual income | Book value, ROE, COE, retention, fade_years | `projected_residual_income` array | 5 steps | Financials (banks, insurers) |
| Justified multiples | ROE, payout, growth, COE | `implied_prices` dict (PB, PE) | 5 steps | Stable firms with clear payout |
| Relative multiples | Own multiples, peer stats with scope | `implied_prices` dict per metric | 4 steps | Sectors with 3+ comparables |
| Reverse DCF | Market cap, FCF Yield, WACC | `implied_perpetual_growth`, interpretation | 5 steps | Diagnostic — every symbol |

For the ensemble construction (how these 7 outputs collapse into one fair value range), see [07-ensemble-and-confidence.md](07-ensemble-and-confidence.md).

For the assumptions hierarchy that feeds COE, WACC, terminal growth into every model, see [08-assumptions-and-defaults.md](08-assumptions-and-defaults.md).

---

## See also

- [04-pillars-and-scoring.md](04-pillars-and-scoring.md) — how the same snapshot feeds the 6-pillar quality score.
- [07-ensemble-and-confidence.md](07-ensemble-and-confidence.md) — confidence cascade and band construction.
- [08-assumptions-and-defaults.md](08-assumptions-and-defaults.md) — what each assumption means and how to override.
- [10-modelling-playbooks.md](10-modelling-playbooks.md) — diagnostic workflows when models disagree.
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md) — fix recipes for all surfaced limitations.
- [13-methodology-and-sources.md](13-methodology-and-sources.md) — academic references.
