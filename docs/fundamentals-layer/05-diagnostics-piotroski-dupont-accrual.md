# Diagnostics: Piotroski-lite, DuPont, accrual quality

Three accounting-quality probes feed the adjusted `quality` score and `diagnostics.accounting_discipline`. Balance-sheet `health` is now scored separately from liquidity/coverage metrics. All logic lives in `core/quant_core/fundamentals/scoring.py`.

## 1. Piotroski-lite (`_piotroski_lite` at `scoring.py:174`)

Adapted from Piotroski (2000) F-score. The original uses 9 binary tests; this implementation uses 9 trend-and-level checks.

### The 9 checks

| # | Check | Lower-better? | Source |
|---|---|---|---|
| 1 | `positive_roa` | No | latest `ROA` > 0 |
| 2 | `positive_free_cash_flow` | No | latest `Free_Cash_Flow` > 0 |
| 3 | `roa_improving` | No | latest `ROA` > previous `ROA` |
| 4 | `cash_flow_exceeds_earnings` | No | latest `Free_Cash_Flow` > latest net income (proxy if needed) |
| 5 | `leverage_decreasing` | Yes (lower D/E is improvement) | latest `Debt_to_Equity` < previous |
| 6 | `liquidity_improving` | No | latest `Current_Ratio` > previous |
| 7 | `operating_margin_improving` | No | latest `Operating_Margin` > previous |
| 8 | `asset_turnover_improving` | No | latest `Asset_Turnover` > previous |
| 9 | `positive_revenue_growth` | No | `Revenue_Growth` > 0 |

### Scoring

```python
score = 100.0 × len(passed) / len(available)
```

A check is "available" only when both the latest and previous value are present. Missing data → check is skipped (no penalty).

### Output

```python
{
    "score": float,           # 0-100, clipped
    "points": int,            # checks passed
    "available_points": int,  # checks runnable
    "max_points": 9,
    "checks": [
        {"name": "positive_roa", "available": True, "passed": True, "value": 0.08},
        ...
    ],
    "net_income_source": "reported_resultat_net" | "revenue_times_net_margin" | None,
}
```

### Worked example

Snapshot for a Moroccan industrial firm:
- `ROA` = 7% (positive) → pass #1
- `Free_Cash_Flow` (latest) = MAD 850M (positive) → pass #2
- `ROA` previous = 5% → 7% > 5% → pass #3
- Net income (latest) = MAD 1100M → FCF 850 < 1100 → fail #4
- `Debt_to_Equity` (latest) = 0.6, previous = 0.5 → 0.6 > 0.5 → fail #5
- `Current_Ratio` (latest) = 1.8, previous = 1.7 → pass #6
- `Operating_Margin` (latest) = 12%, previous = 11% → pass #7
- `Asset_Turnover` (latest) = 0.9, previous = 0.95 → 0.9 < 0.95 → fail #8
- `Revenue_Growth` = 6% → pass #9

Passed: 6, Available: 9 → **score = 100 × 6 / 9 = 66.7**

This 66.7 feeds `diagnostics.accounting_discipline` along with the DuPont score.

## 2. DuPont bridge (`_dupont` at `scoring.py:151`)

Tests whether the reported ROE reconciles with N×A×EM-implied ROE (Net margin × Asset turnover × Equity multiplier).

### The math

```python
net_margin       = Net_Margin (as ratio)
asset_turnover   = Asset_Turnover
equity_multiplier= Equity_Multiplier

implied_roe      = net_margin × asset_turnover × equity_multiplier
reported_roe     = ROE (as ratio)
gap              = |implied_roe - reported_roe|

score = 100 - min(100, gap × 500)
```

### Output

```python
{
    "net_margin": float | None,
    "asset_turnover": float | None,
    "equity_multiplier": float | None,
    "implied_roe": float | None,
    "reported_roe": float | None,
    "roe_bridge_gap": float | None,
    "score": float | None,
}
```

### Interpretation

| Gap (absolute) | Score | What it means |
|---|---|---|
| < 0.005 | 97-100 | DuPont reconciles cleanly — high data quality |
| 0.005-0.02 | 90-97 | Minor noise — usually period averaging |
| 0.02-0.05 | 75-90 | Worth a look — could be definitional |
| 0.05-0.10 | 50-75 | Probably an input error |
| > 0.10 | < 50 | Don't trust the snapshot for analytical use |

### Worked example

- Net_Margin = 8% (= 0.08)
- Asset_Turnover = 0.95
- Equity_Multiplier = 1.8
- ROE reported = 14%

implied_roe = 0.08 × 0.95 × 1.8 = **0.1368**
reported_roe = 0.14
gap = |0.1368 - 0.14| = 0.0032
score = 100 - min(100, 0.0032 × 500) = 100 - 1.6 = **98.4**

Clean reconciliation → DuPont score = 98.4.

### Why this matters

The DuPont bridge is a free data-quality check. If reported ROE is, say, 18% but implied is 9%, something is off with the inputs (often `Equity_Multiplier` was read from the wrong cell). Don't trust the snapshot's ROE until the gap closes.

## 3. Accrual quality (`_accrual_quality` at `scoring.py:206`)

Adapted from Sloan (1996). High accruals — i.e., earnings substantially above operating cash — predict mean-reversion (lower future earnings). Cash conversion captures this.

### The math

```python
fcf            = latest Free_Cash_Flow
net_income     = latest Resultat_net (or revenue × net_margin proxy)

cash_conversion = fcf / |net_income|
accrual_ratio   = (net_income - fcf) / |net_income|

score = 50 + max(-50, min(50, cash_conversion × 35))   # clipped to [0, 100]
```

### Output

```python
{
    "score": float | None,         # 0-100
    "cash_conversion": float | None,
    "accrual_ratio": float | None,
    "net_income_source": str | None,  # "reported_resultat_net" | "revenue_times_net_margin"
}
```

### Interpretation

| cash_conversion | Score | Earnings quality |
|---|---|---|
| 1.5+ | 100 (capped) | Excellent — cash exceeds earnings |
| 1.0-1.5 | 85-100 | Strong |
| 0.8-1.0 | 78-85 | Good |
| 0.5-0.8 | 67-78 | Acceptable |
| 0.2-0.5 | 57-67 | Suspect — accruals dominate |
| 0-0.2 | 50-57 | Weak — almost all earnings on paper |
| < 0 | < 50 | Red flag — negative FCF with positive earnings |

### Worked example

- Free_Cash_Flow = MAD 850M
- Net_Income = MAD 1,100M

cash_conversion = 850 / 1100 = **0.773**
accrual_ratio = (1100 - 850) / 1100 = **0.227**
score = 50 + 0.773 × 35 = 50 + 27.05 = **77.05**

Reasonable earnings quality — fairly high cash conversion suggests the income is mostly real.

### Why this matters

A firm reporting 14% earnings growth with cash_conversion = 0.4 is converting only 40% of earnings to cash — the gap is accruals (receivables, inventory build, capitalized R&D, etc.). These reverse over time. The scoring engine gives credit only to earnings backed by cash.

## How the three combine

In `score_fundamental_snapshots` (`scoring.py:232`):

```python
dupont = _dupont(snapshot)
piotroski = _piotroski_lite(snapshot, symbol_history)
accrual = _accrual_quality(snapshot, symbol_history)

accounting_discipline = mean(piotroski.score, dupont.score)
accrual_score = accrual.score                                # accrual_quality

quality_raw = _score_group(symbol, percentiles, QUALITY_METRICS)
quality_adjusted = mean(quality_raw, accounting_discipline, accrual_score)
```

So:
- **Health pillar** = average of Piotroski + DuPont
- **Quality pillar (adjusted)** = average of raw percentile + accounting discipline + accrual
- **Accrual_quality** is exposed separately on the snapshot

⚠️ Naming concerns:
- Health is now balance-sheet health; accounting discipline is a diagnostic.
- Adjusted quality preserves `quality_raw` and `quality_components`.

---

# Step-by-step algorithm traces

This section shows what each diagnostic does internally — the per-check expansion, the data lineage, and the score computation.

## Trace — Piotroski-lite (`_piotroski_lite` at `scoring.py:174`)

### Step P1 — Resolve net income (with proxy fallback)

*What:* call `_net_income_proxy(snapshot, history)`. Returns reported `Resultat_net` if present in history, else `Revenue × Net_Margin` (proxy).
*Why:* Piotroski check #4 (cash flow > net income) needs a net-income number. Workbooks sometimes omit the income statement line but provide net margin — the proxy keeps the check available.
*Where:* `scoring.py:140-148`.
*Result:* `(net_income_value, source_label)`. Source is `"reported_resultat_net"` or `"revenue_times_net_margin"`. Persisted as `piotroski.net_income_source` for audit.

### Step P2 — Run each check, mark availability

*What:* sequentially evaluate the 9 checks. Each check builds:
```
{
    "name": str,                # e.g. "positive_roa"
    "available": bool,          # both latest and previous values needed for trend checks
    "passed": bool | None,
    "value": float | None       # the value that drove the decision
}
```

*Why:* checks that can't be evaluated (missing data) are marked unavailable, not failed — this prevents penalty for data gaps.
*Where:* `scoring.py:180-191`.
*Result:* a list of 9 dicts.

### Step P3 — Score from passed/available ratio

*What:* `score = 100 × len(passed) / len(available)`. Skipped checks reduce the denominator, not the numerator.
*Why:* preserves comparability across symbols with different metric coverage.
*Where:* `scoring.py:194-195`.
*Result:* score 0-100, clipped.

### Step P4 — Persist for downstream

*What:* return `{score, points, available_points, max_points: 9, checks, net_income_source}`.
*Why:* downstream consumers (the quality adjustment and the UI) get the full breakdown, not just the score.
*Where:* `scoring.py:196-203`.

### Worked example — IRD-INDUS

Snapshot inputs: ROA latest=7%, ROA previous=5%, FCF latest=850M, FCF previous=700M, NetIncome latest=1100M, NetIncome previous=1000M, D/E latest=0.6, D/E previous=0.5, Current_Ratio latest=1.8, prev=1.7, Operating_Margin latest=12%, prev=11%, Asset_Turnover latest=0.9, prev=0.95, Revenue_Growth=6%.

| # | Check | Available? | Logic | Result |
|---|---|---|---|---|
| 1 | positive_roa | Yes | 7% > 0 | **pass** |
| 2 | positive_free_cash_flow | Yes | 850 > 0 | **pass** |
| 3 | roa_improving | Yes | 7% > 5% | **pass** |
| 4 | cash_flow_exceeds_earnings | Yes | 850 < 1100 | **fail** |
| 5 | leverage_decreasing | Yes | 0.6 > 0.5 (D/E went UP, so worse) | **fail** |
| 6 | liquidity_improving | Yes | 1.8 > 1.7 | **pass** |
| 7 | operating_margin_improving | Yes | 12% > 11% | **pass** |
| 8 | asset_turnover_improving | Yes | 0.9 < 0.95 | **fail** |
| 9 | positive_revenue_growth | Yes | 6% > 0 | **pass** |

Passed = 6, Available = 9 → **score = 66.7**.

The output dict is:
```json
{
    "score": 66.7,
    "points": 6,
    "available_points": 9,
    "max_points": 9,
    "checks": [{"name": "positive_roa", "available": true, "passed": true, "value": 0.07}, ...],
    "net_income_source": "reported_resultat_net"
}
```

This 66.7 contributes to `accounting_discipline = mean(piotroski.score, dupont.score)` in the scoring pipeline.

## Trace — DuPont bridge (`_dupont` at `scoring.py:151`)

### Step D1 — Extract the three components

*What:* pull `Net_Margin`, `Asset_Turnover`, `Equity_Multiplier`, `ROE` from the snapshot (all as ratios via `_ratio`).
*Why:* DuPont decomposes ROE = Net Margin × Asset Turnover × Equity Multiplier. Each component is independently verifiable.
*Where:* `scoring.py:152-155`.
*Result:* four numbers (or Nones if missing).

### Step D2 — Compute implied ROE

*What:* `implied_roe = net_margin × asset_turnover × equity_multiplier`. Only computed if all three are present.
*Why:* this is what reported ROE *should* equal if the income statement and balance sheet are internally consistent.
*Where:* `scoring.py:156-158`.
*Result:* implied ROE or None.

### Step D3 — Compute the bridge gap

*What:* `gap = |implied_roe - reported_roe|`. Only computed if both are present.
*Why:* small gap = clean data; large gap = something wrong with one of the inputs.
*Where:* `scoring.py:159`.
*Result:* gap value or None.

### Step D4 — Convert gap to a 0-100 score

*What:* `score = 100 − min(100, gap × 500)`. A gap of 0.002 maps to score 99; a gap of 0.20 maps to score 0.
*Why:* the multiplier 500 calibrates "1% gap = 5 score points lost" — anchored so that a clean DuPont yields ~95+ and a meaningfully broken one drops below 50.
*Where:* `scoring.py:161-162`.
*Result:* score 0-100.

### Step D5 — Persist the full breakdown

*What:* return `{net_margin, asset_turnover, equity_multiplier, implied_roe, reported_roe, roe_bridge_gap, score}`.
*Why:* the UI shows each component so an analyst can spot which input is wrong.
*Where:* `scoring.py:163-171`.

### Worked example — IRD-INDUS

Snapshot: Net_Margin=8%, Asset_Turnover=0.95, Equity_Multiplier=1.8, ROE=14%.

- implied_roe = 0.08 × 0.95 × 1.8 = **0.1368**
- reported_roe = 0.14
- gap = |0.1368 − 0.14| = **0.0032**
- score = 100 − min(100, 0.0032 × 500) = 100 − 1.6 = **98.4**

DuPont is clean (gap = 0.32%, well within "minor noise"). Score = 98.4.

This 98.4 contributes to `accounting_discipline = mean(98.4, 66.7) = 82.55` for IRD-INDUS.

## Trace — Accrual quality (`_accrual_quality` at `scoring.py:206`)

### Step A1 — Resolve FCF and net income

*What:* pull latest `Free_Cash_Flow` from history. Resolve net income via `_net_income_proxy` (same helper as Piotroski).
*Why:* both numbers are needed for cash conversion.
*Where:* `scoring.py:207-209`.

### Step A2 — Eligibility gate

*What:* if either is None, OR if net income is zero, return `{score: None, ...}` with `net_income_source` for audit.
*Why:* the math degenerates without both; clean fallback rather than NaN.
*Where:* `scoring.py:209-210`.

### Step A3 — Compute cash conversion and accrual ratio

*What:*
- `cash_conversion = fcf / |net_income|` — higher means earnings are mostly cash, not accruals.
- `accrual_ratio = (net_income − fcf) / |net_income|` — the share of earnings sitting in accruals.
*Why:* Sloan (1996) shows that high-accrual firms underperform — earnings without cash backing tend to reverse. Cash conversion is the inverse of the accrual problem.
*Where:* `scoring.py:211-212`.

### Step A4 — Map cash conversion to a 0-100 score

*What:* `score = 50 + max(-50, min(50, cash_conversion × 35))`, then clipped to [0, 100].
*Why:* calibrates so cash_conversion = 1.0 → score = 85 (good); cash_conversion = 0.5 → score = 67 (acceptable); cash_conversion = 0 → score = 50 (red flag).
*Where:* `scoring.py:213`.
*Result:* score in [0, 100].

### Step A5 — Persist

*What:* return `{score, cash_conversion, accrual_ratio, net_income_source}`.
*Why:* UI shows cash_conversion as the headline number; score for the composite quality pillar.
*Where:* `scoring.py:214-219`.

### Worked example — IRD-INDUS

Snapshot: FCF latest = 850M, Net_Income latest = 1100M.

- cash_conversion = 850 / 1100 = **0.773**
- accrual_ratio = (1100 − 850) / 1100 = **0.227**
- score = 50 + 0.773 × 35 = 50 + 27.05 = **77.05**

Cash conversion is in the "acceptable" zone — about 77% of net income converts to FCF. The remaining 23% is sitting in accruals (receivables, inventory build, capitalized R&D, etc.) and is at risk of reversing over time.

This 77.05 feeds `quality_adjusted = mean(quality_raw, accounting_discipline, accrual_score)` in the scoring pipeline.

## How the three diagnostics combine

In `score_fundamental_snapshots` (`scoring.py:351-357`):

```python
dupont = _dupont(snapshot)                                       # 98.4 for IRD-INDUS
piotroski = _piotroski_lite(snapshot, symbol_history)            # 66.7
accrual = _accrual_quality(snapshot, symbol_history)             # 77.05

accounting_discipline = mean(piotroski.score, dupont.score)      # mean(66.7, 98.4) = 82.55
accrual_score = accrual.score                                    # 77.05

quality_raw = _score_group(symbol, percentiles, QUALITY_METRICS) # e.g. 57.0
quality_adjusted = mean(quality_raw, accounting_discipline, accrual_score)
                 = mean(57.0, 82.55, 77.05)
                 = 72.2
```

The headline `snapshot.scores["quality"] = 72.2`. The raw and components live in `snapshot.scores["quality_raw"]` and `snapshot.scores["quality_components"]` for audit.

Meanwhile `snapshot.diagnostics["accounting_discipline"] = 82.55` (renamed from "health" pre-v3 per S5 fix) and `snapshot.diagnostics["accrual_quality"]` carries the full dict.

The pillar called **health** in v3 is computed separately from `HEALTH_METRICS = (Current_Ratio, Cash_Ratio, Interest_Coverage)` — actual balance-sheet health, not accounting discipline.

## See also

- [04-pillars-and-scoring.md](04-pillars-and-scoring.md) — how these scores feed the 6 pillars.
- [10-modelling-playbooks.md](10-modelling-playbooks.md#playbook-5) — using the DuPont gap as a diagnostic.
- [13-methodology-and-sources.md](13-methodology-and-sources.md) — academic references.
