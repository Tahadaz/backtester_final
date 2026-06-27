# Pillars and scoring

The scoring engine ranks each snapshot against the current cohort across 6 pillars, then blends pillar scores into a single composite. All logic lives in `core/quant_core/fundamentals/scoring.py`.

## The six pillars

| Pillar | Weight | Code constant | Captures |
|---|---|---|---|
| Quality | 0.22 | `QUALITY_METRICS` | Profitability and margin quality |
| Value | 0.20 | `VALUE_METRICS` | Cheapness vs earnings, book, sales, EBITDA, cash flow |
| Growth | 0.16 | `GROWTH_METRICS` | Revenue, EBIT, net income growth |
| Risk | 0.14 | `RISK_METRICS` | Leverage and capital-structure risk |
| Cash flow | 0.14 | `CASH_FLOW_METRICS` | Cash generation, conversion |
| Health | 0.14 | `HEALTH_METRICS` | Liquidity and interest coverage |

Weights sum to 1.00. Defined in `OVERALL_WEIGHTS` at `scoring.py:31`.

Dividend is now a diagnostic, not a weighted pillar. Dividend yield remains part of Value; dividend coverage/payout are exposed in `diagnostics.dividend`.

Post-brief-31 note: when 3-year annual history exists, the Value and Quality percentile inputs use trailing averages for their cyclical-sensitive metrics. The latest value, trailing averages, and actual `scoring_input` are exposed under `diagnostics["smoothing"]`.

## Per-pillar metric composition

### Value (`VALUE_METRICS`)

```python
("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA", "FCF_Yield", "Dividend_Yield")
```

Direction: PER / P_B / P_S / EV_EBITDA → **lower is better** (in `LOWER_IS_BETTER` set). FCF_Yield / Dividend_Yield → **higher is better**.

### Quality (`QUALITY_METRICS`)

```python
("ROE", "ROA", "Operating_Margin", "Net_Margin")
```

Direction: all higher-better.

### Growth (`GROWTH_METRICS`)

```python
("Revenue_Growth", "EBIT_Growth", "NetIncome_Growth")
```

All higher-better.

### Risk (`RISK_METRICS`)

```python
("Debt_to_Equity", "NetDebt_to_EBITDA", "Equity_Multiplier")
```

All lower-better.

### Cash flow (`CASH_FLOW_METRICS`)

```python
("FCF_Margin", "Operating_CF_Margin", "CAF_Margin")
```

All higher-better.

### Health (`HEALTH_METRICS`)

Computed from liquidity and coverage metrics:

```python
("Current_Ratio", "Cash_Ratio", "Interest_Coverage")
```

The old Piotroski + DuPont composite moved to `diagnostics.accounting_discipline`.

### Dividend (`DIVIDEND_METRICS`) — exposed but not in `OVERALL_WEIGHTS`

```python
("Dividend_Coverage", "Dividend_Payout")
```

## The percentile-ranking algorithm

For each metric, every snapshot is ranked against every other snapshot in the cohort. The algorithm (`_percentile_scores` at `scoring.py:58`):

```python
def _percentile_scores(values, *, lower_is_better, min_cohort=3):
    if not values:
        return {}
    if len(values) < min_cohort:
        return {symbol: None for symbol in values}
    ordered = sorted(values.items(), key=lambda item: item[1])
    n = len(ordered)
    scores = {}
    for rank, (symbol, _) in enumerate(ordered):
        pct = 100.0 * rank / (n - 1)
        scores[symbol] = 100.0 - pct if lower_is_better else pct
    return scores
```

Notes:
- Percentiles are sector-bucketed when at least three peers exist; otherwise the market cohort is used.
- Cohorts with fewer than three symbols return `None`, not a fabricated neutral score.
- Magnitude diagnostics are persisted in `diagnostics.metric_breakdown`.

## How pillar scores combine into one

Per pillar, the engine averages the percentile rank across the pillar's metrics:

```python
def _score_group(symbol, percentiles, metrics):
    return _avg([percentiles[m][symbol] for m in metrics if symbol in percentiles[m]])
```

Then `OVERALL_WEIGHTS` weighted-average across pillars:

```python
def _weighted_score(parts):
    present = [(name, value) for name, value in parts.items() if value is not None]
    weight_sum = sum(OVERALL_WEIGHTS[name] for name, _ in present)
    return sum(value * OVERALL_WEIGHTS[name] for name, value in present) / weight_sum
```

The blended score now returns `overall_coverage_pct`; if weighted coverage is below 50%, `overall` is left `None`.

## The quality adjustment (extra step)

Quality is **not** just the percentile rank of `QUALITY_METRICS`. The engine does:

```python
quality_raw = _score_group(symbol, percentiles, QUALITY_METRICS)
quality_adjusted = mean(quality_raw, accounting_discipline, accrual_quality_score)

snapshot.scores["quality"] = quality_adjusted    # The headline value
```

The raw percentile rank is preserved as `quality_raw`, and the full audit trail is in `quality_components`.

## Final snapshot.scores shape

```python
snapshot.scores = {
    "overall": float,            # Weighted average over 6 pillars
    "overall_coverage_pct": float,
    "value": float,
    "quality": float,            # Adjusted (raw + accounting discipline + accrual)
    "quality_raw": float,
    "quality_components": dict,
    "growth": float,
    "risk": float,
    "cash_flow": float,
    "health": float,
    "accrual_quality": float,
    "component_count": float,    # 0-6, how many pillars contributed
}
```

## Worked example — Moroccan industrial vs cohort of 12

Synthetic numbers:

| Metric | IRD's value | Sector peers (median) | IRD's percentile | Direction |
|---|---|---|---|---|
| PER | 18 | 14 | 25 | lower-better |
| Price_to_Book | 2.2 | 1.6 | 30 | lower-better |
| FCF_Yield | 5.5% | 4.0% | 75 | higher-better |
| ROE | 11% | 13% | 35 | higher-better |
| ROA | 6% | 7% | 40 | higher-better |
| Operating_Margin | 12% | 10% | 65 | higher-better |
| Debt_to_Equity | 0.4 | 0.7 | 75 | lower-better |
| FCF_Margin | 11% | 9% | 70 | higher-better |
| Revenue_Growth | 7% | 5% | 75 | higher-better |
| NetIncome_Growth | 9% | 6% | 80 | higher-better |
| Current_Ratio | 1.8 | 1.6 | 60 | higher-better |
| NetDebt_to_EBITDA | 0.5 | 1.5 | 85 | lower-better |

Pillar computations:

- **Value** = mean(25, 30, _, _, 75, _) = **43.3** (only 3 of 6 value metrics shown)
- **Quality (raw)** = mean(35, 40, 65, _, 70, 75) = **57.0**
- **Growth** = mean(7, 9) → mean(75, 80) = **77.5**
- **Risk** = mean(75, 85, 60, _) = **73.3**
- **Cash flow** = mean(70, _, _, _) = **70.0** (only 1 of 4 cash flow metrics)
- **Health (Piotroski + DuPont)** = composite (skipped here)

Quality adjusted = mean(57.0, accounting_discipline, accrual_score). Assume accounting discipline=68, accrual=72 -> **65.7**.

Overall (weighted):
```
0.22×65.7 + 0.20×43.3 + 0.16×77.5 + 0.14×73.3 + 0.14×70.0 + 0.14×health_in_pillar
```
= 14.5 + 8.7 + 12.4 + 10.3 + 9.8 + 9.5 = **65.2**

The symbol scores 65 overall — above the cohort median (50) but not exceptional. Value (43) is the weakest pillar (the stock is more expensive than typical peers). Growth (77) is the strongest. The picture is "moderately growing industrial trading at a premium to peers". Whether to buy depends on whether the growth trajectory justifies the value premium — exactly the question a fundamental analyst should ask next.

---

# Step-by-step algorithm trace — scoring pipeline

This section traces what happens when `score_fundamental_snapshots(snapshots, annual_metrics, sectors=..., peer_min_count=3)` is called. Every step shows what is computed, why, and where (file:line).

## Phase A — Cohort-level percentile computation

The first phase runs **once across all snapshots in the cohort**, building a lookup of `{metric_name → {symbol → {score, scope}}}`.

### Step A1 — Collect metric values

*What:* iterate every snapshot's `metrics` dict and group by metric name → `{metric: {symbol: value}}`.
*Why:* percentile ranking requires the full cross-sectional distribution per metric before any symbol can be ranked.
*Where:* `_metric_percentiles` (`scoring.py:107`).
*Result:* a dict keyed by metric, value = `{symbol: float}` for every symbol that has the metric.

### Step A2 — Bucket by sector (S2 — v3 fix)

*What:* for each metric:
  1. Group symbol values by sector using the `sectors` argument (typically `stock_master.sector`).
  2. For each sector with ≥ `peer_min_count` (default 3) members, compute percentile ranks **within the sector** using `_percentile_scores(values, lower_is_better=...)`. Mark scope as `"sector"`.
  3. For symbols whose sector group was too thin, fall back to **whole-universe** percentile ranks. Mark scope as `"market"`.

*Why:* PER 15 for a utility is cheap; PER 15 for a tech-equivalent is expensive. Mixing them produces meaningless rankings. The peer-min-count threshold mirrors the same discipline as relative-multiples (`_peer_stats` in valuation.py).
*Where:* `_metric_percentiles` (`scoring.py:107`).
*Result:* `{metric: {symbol: {score: float|None, scope: "sector"|"market", value: float, ...}}}`.

### Step A3 — Handle single-symbol cohorts (S3 — v3 fix)

*What:* `_percentile_scores` (`scoring.py:68`) checks `n < min_cohort` (default 3). If so, returns `{symbol: None}` for every symbol in that group.
*Why:* a cohort of 1 has no comparison data; returning 50 (the pre-v3 behavior) silently fabricated "neutral" scores that the UI then displayed as authoritative.
*Where:* `scoring.py:68-74`.
*Result:* `None` propagates downstream; pillars built on a single-symbol cohort end up with `coverage_pct = 0` rather than misleading flat scores.

### Step A4 — Build the magnitude diagnostic (S8 — v3 addition)

*What:* `_metric_breakdown` (`scoring.py:82`) computes per-metric: median, z-score, percent deviation from median, both with direction applied. Stored alongside percentile.
*Why:* a stock at PER 5 vs cohort {8, 10, 12} ranks identically to PER 1 vs {30, 50, 80}. Magnitude preserves the cheaper-is-cheaper signal that percentile flattens.
*Where:* `scoring.py:82-105`.
*Result:* per-metric dict entry like `{score: 100, scope: "sector", value: 5.0, median: 10.0, z_score: 1.87, pct_dev: -0.5}`.

## Phase B — Per-symbol pillar assembly

This loops over each snapshot and builds the pillar scores from the percentile lookup.

### Step B1 — Score each pillar

For each pillar P with metrics `{m1, m2, ..., mk}`:

*What:* compute `_score_group(symbol, percentiles, P_METRICS)`:
```
pillar_score = mean of percentile scores for metrics in P that this symbol has a value for
```
*Why:* mean is robust to a single missing metric; median would also work but mean preserves linearity when comparing pillars.
*Where:* `_score_group` (`scoring.py:158`).
*Result:* `value_score`, `quality_score`, `growth_score`, `risk_score`, `cash_flow_score`, `health_score` — one per pillar.

### Step B2 — Run the three accounting-quality diagnostics

*What:* per-symbol:
- `dupont = _dupont(snapshot)` — N×A×EM bridge gap.
- `piotroski = _piotroski_lite(snapshot, symbol_history)` — 9-check score.
- `accrual = _accrual_quality(snapshot, symbol_history)` — cash conversion score.
*Why:* these are accounting-quality probes, not pillars in their own right. They feed quality adjustment (B3) and accounting-discipline diagnostics.
*Where:* `scoring.py:351-355`.
*Result:* three dicts each carrying a `score` field (0-100) and detailed components.

### Step B3 — Compute the quality adjustment (S6 — v3 audit trail)

*What:*
```
accounting_discipline = mean(piotroski.score, dupont.score)
accrual_score         = accrual.score
quality_adjusted      = mean(quality_raw, accounting_discipline, accrual_score)
```

Both `quality_raw` (the percentile-derived headline) AND the three components are persisted, so the UI can show the full breakdown.
*Why:* a single "quality = 70" is opaque. Storing the raw plus the three adjusters lets the user understand "the raw percentile was 60 but Piotroski was 80 and accrual was 70, so adjusted is 70".
*Where:* `scoring.py:354-357`.
*Result:* `adjusted_quality` becomes the headline; `quality_raw` and `quality_components` preserved.

### Step B4 — Compose overall score (S7 — v3 partial-coverage handling)

*What:* call `_weighted_score(parts)` where `parts = {value, quality, growth, risk, cash_flow, health}`.

Inside, weights renormalize only over **present** (non-None) pillars. The function returns `(overall_score, coverage_pct)`:
```
weight_sum = sum of OVERALL_WEIGHTS for present pillars
overall    = (Σ value × OVERALL_WEIGHTS[name]) / weight_sum
coverage   = weight_sum / sum(OVERALL_WEIGHTS.values())
if coverage < 0.5: overall = None   # partial-coverage guard
```

*Why:* pre-v3, a symbol with only 1/6 pillars produced an "overall" indistinguishable from a fully-covered one. Returning coverage and gating on 50% prevents misleading display.
*Where:* `_weighted_score` (`scoring.py:316`).
*Result:* `(overall, overall_coverage_pct)`.

### Step B5 — Build the trailing-average diagnostic (S9 — v3 addition)

*What:* for each metric in `TRAILING_METRICS = ("ROE", "ROA", "Revenue_Growth", ...)`:
```
{
    "latest": snapshot.metrics[m],
    "trailing_3y": _trailing_average(symbol_history, m, 3),
    "trailing_5y": _trailing_average(symbol_history, m, 5)
}
```
*Why:* cyclicals swing year-over-year. The trailing average is the cycle-smoothed alternative. The UI can toggle latest vs trailing on pillar displays.
*Where:* `scoring.py:381-388`.
*Result:* `diagnostics["smoothing"]` dict.

### Step B6 — Persist scope and breakdown diagnostics

*What:* save per-pillar `scope` (sector vs market median pathway), plus `metric_breakdown` (from A4), into `snapshot.diagnostics`.
*Why:* surfaces the data-quality information the UI needs to render confidence chips and tooltips.
*Where:* `scoring.py:367-380, 409-418`.

## Phase C — Final snapshot shape

After Phase B for one symbol, the snapshot's `scores` and `diagnostics` look like this:

```python
snapshot.scores = {
    "overall": 65.2,
    "overall_coverage_pct": 1.0,           # fully-covered symbol
    "value": 43.3,
    "quality": 65.7,                       # adjusted
    "quality_raw": 57.0,                   # raw percentile only
    "quality_components": {
        "raw_percentile": 57.0,
        "accounting_discipline": 68.0,
        "piotroski_lite": 66.7,
        "dupont_bridge": 69.3,
        "accrual_quality": 72.0,
    },
    "growth": 77.5,
    "risk": 73.3,
    "cash_flow": 70.0,
    "health": 65.0,                        # real balance-sheet health (S5 fix)
    "accrual_quality": 72.0,
    "component_count": 6.0,
}

snapshot.diagnostics = {
    "dupont": {...},
    "piotroski_lite": {...},
    "accrual_quality": {...},
    "accounting_discipline": 68.0,         # renamed from old "health" (S5)
    "dividend": {                          # S4 — diagnostic, not in overall
        "score": 70.0,
        "metrics": ("Dividend_Coverage", "Dividend_Payout"),
    },
    "score_scopes": {
        "value": "sector",                 # this symbol's pillar used sector medians
        "quality": "sector",
        ...
    },
    "metric_breakdown": {                  # S8 — per-metric magnitude
        "PER": {"score": 25, "scope": "sector", "value": 18, "median": 14, "z_score": -1.0, "pct_dev": 0.29},
        ...
    },
    "smoothing": {                         # S9 — trailing averages
        "ROE": {"latest": 0.11, "trailing_3y": 0.115, "trailing_5y": 0.118},
        ...
    },
}
```

## End-to-end worked example — IRD-INDUS

Continuing the worked example from earlier in this doc (Section "Worked example — Moroccan industrial vs cohort of 12"):

**Phase A** runs once for the cohort. For PER, 12 industrial firms produce a sorted list, IRD-INDUS at PER=18 ranks at percentile 25 within sector (since lower-better). For ROE, IRD-INDUS at 11% ranks at percentile 35 within sector. All percentiles produced.

**Phase B** runs for IRD-INDUS specifically:
- **B1:** Value = mean(25, 30, _, _, 75, _) = 43.3. Quality (raw) = mean(35, 40, 65, _, 70, 75) = 57.0. Growth = mean(75, 80) = 77.5. Risk = mean(75, 85, 60, _) = 73.3. Cash flow = mean(70, _, _, _) = 70.0. Health (balance sheet) = mean(60, 65, _) = 62.5 (synthetic).
- **B2:** DuPont = 98, Piotroski = 67, Accrual = 77 (from per-symbol diagnostics).
- **B3:** accounting_discipline = mean(98, 67) = 82.5. quality_adjusted = mean(57.0, 82.5, 77) = **72.2**.
- **B4:** overall = (0.22 × 72.2 + 0.20 × 43.3 + 0.16 × 77.5 + 0.14 × 73.3 + 0.14 × 70.0 + 0.14 × 62.5) / 1.0 = (15.88 + 8.66 + 12.40 + 10.26 + 9.80 + 8.75) = **65.75**. Coverage = 1.0 (all 6 pillars present).
- **B5:** trailing_3y(ROE) computed from annual_metrics, e.g. 0.115 vs latest 0.11.

IRD-INDUS lands at overall ~66 — moderately good. Strongest pillars are growth (77.5), quality (72.2 after adjustment), risk (73.3). Weakest is value (43.3, the stock is expensive vs sector). The story matches the valuation result (IRD-INDUS trades at a 25% premium to peers per relative multiples, see Trace 6 in `06-valuation-models.md`).

## What the UI / API sees

After scoring, every snapshot persists into `FundamentalLatestSnapshot.scores_json` and `diagnostics_json`. The API endpoints in `services/api/app/routers/fundamentals.py` then surface this to the frontend without further computation. See [09-api-data-flow-and-frontend-contracts.md](09-api-data-flow-and-frontend-contracts.md) for the response shapes.

## See also

- [05-diagnostics-piotroski-dupont-accrual.md](05-diagnostics-piotroski-dupont-accrual.md) — the three sub-scores that feed `quality_adjusted` and `accounting_discipline`.
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md) — fixes for S1-S9.
- [10-modelling-playbooks.md](10-modelling-playbooks.md) — how to interpret pillar scores in context.
