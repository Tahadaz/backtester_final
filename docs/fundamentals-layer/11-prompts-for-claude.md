# Prompts for Claude (or another assistant) in this repo

Ready-to-paste prompts grounded in this codebase. Each assumes the assistant has read access to the repo and to the fundamentals layer docs.

> All prompts reference real file paths. If the assistant says "I can't find X" the assumption is broken — check the path or the prompt.

---

## Universe-level prompts

### 1. Audit a new workbook upload

```
I just uploaded the workbook at `/path/to/new_upload.xlsx`. Run Playbook 1 from `docs/fundamentals-layer/10-modelling-playbooks.md`:

1. Read the FundamentalImport row for the most recent upload by ordering on `imported_at DESC` in the `fundamental_import` table.
2. Report status, latest_snapshot_count, annual_metric_count, quality_issue_count.
3. For the 3 symbols with the largest market cap in the import, fetch `snapshot.scores` and report:
   - component_count
   - overall, value, quality, growth, risk, cash_flow, health
   - ensemble.fair_value_base, ensemble.confidence_score
4. Flag any of: component_count < 6, ensemble confidence < 0.5, quality_issue_count > 5 per symbol.

Use the existing services API endpoints when possible, not raw SQL. Reference: `services/api/app/routers/fundamentals.py`.
```

### 2. Find overvalued symbols (reverse DCF screen)

```
I want a list of symbols where the reverse DCF implies a perpetual growth rate above 7%. These are candidates for being priced as if the market expects unrealistic growth.

For each symbol with a recent `FundamentalLatestSnapshot`:
1. Read the reverse_dcf valuation from `FundamentalValuationResult` (model="reverse_dcf").
2. Pull `outputs.implied_perpetual_growth` from the JSONB.
3. Filter for implied_perpetual_growth > 0.07.
4. Report: symbol, current_price, market_cap, sector, implied_perpetual_growth, current FCF_Yield.
5. Sort descending by implied_perpetual_growth.

Reference the methodology in `docs/fundamentals-layer/06-valuation-models.md#7-reverse-dcf-diagnostic`.
```

### 3. Coverage report — who's missing data

```
For my coverage universe in `services/api/app/services/market_universe.py`, report which symbols have:
- No FundamentalLatestSnapshot row at all (uncovered)
- A snapshot older than 180 days (stale)
- A snapshot with component_count < 5 (partially-scored)
- Quality issues with severity="error"

Group by market_region (MASI, US, European, Asian). Report counts per group, then list the symbols in each bucket.

Goal: identify which symbols need a re-upload or a yfinance refresh.
```

---

## Single-symbol prompts

### 4. Full walkthrough of a symbol's valuation

```
For symbol {SYMBOL}, walk me through how each of the 7 valuation models produced its fair value:

1. Read `FundamentalLatestSnapshot` and the related `FundamentalValuationResult` rows.
2. For each model, summarize in 3-5 lines:
   - inputs used (especially the values pulled from snapshot.metrics)
   - which warnings fired
   - the confidence ladder (base → after warnings → after proxy haircut)
   - the fair_value produced
3. Identify which model is the swing vote in the ensemble (highest weight).
4. Read `ensemble.fair_value_base / current_price - 1` and explain the upside.
5. If `model_dispersion (high - low) / base > 0.5`, identify the two models driving the disagreement.

Reference: `docs/fundamentals-layer/06-valuation-models.md` and `docs/fundamentals-layer/07-ensemble-and-confidence.md`.
```

### 5. Pillar score drilldown

```
For symbol {SYMBOL}, drill into each of the 6 pillar scores:

1. List the metrics that fed each pillar (from `VALUE_METRICS`, `QUALITY_METRICS`, etc. in `core/quant_core/fundamentals/scoring.py`).
2. For each metric, show: snapshot.metrics[metric], cohort percentile.
3. Identify the 3 metrics driving the highest pillar score and the 3 driving the lowest.
4. Compare against same-sector peers — does this symbol look attractive within sector, or is it cohort-wide outperformance/underperformance?

Note: scoring is sector-bucketed when enough peers exist, with market fallback for thin cohorts.
```

### 6. Diagnose a wide fair-value range

```
For symbol {SYMBOL}, the ensemble band is showing more than 50% width relative to base. Run Playbook 2 from `docs/fundamentals-layer/10-modelling-playbooks.md`:

1. Sort per-model fair values by distance from ensemble base.
2. For the top 2 outliers, open `FundamentalValuationResult.inputs` and `.outputs`.
3. Identify which inputs are causing the divergence.
4. If `relative_multiples` is an outlier, check `peer_stats[metric].count` and `peer_stats[metric].scope`.
5. Report findings and a recommendation: trust the ensemble vs flag for manual override.
```

### 7. Compare two consecutive snapshots

```
For symbol {SYMBOL}, compare the two most recent `FundamentalLatestSnapshot` rows (by `imported_at DESC`):

1. For each of the 6 pillar scores, show: old value, new value, delta.
2. Identify which metrics changed the most (top 5 by |Δpercentile|).
3. For each top mover, show: old metric value, new metric value, root cause if obvious.
4. Identify whether the change is "real" (new fiscal year reported) or "data" (workbook re-cut with different inputs).

Note: requires both old and new snapshots to be persisted; if only one exists you'll need to check the audit table (TBD as of this writing).
```

---

## Assumption-tuning prompts

### 8. Generate a sector-level assumption override

```
I want to override default assumptions for the Banques sector. Generate a JSON body suitable for `PUT /fundamentals/stocks/{any_bank_symbol}/assumptions/base` with `scope_type="sector"` and `scope_key="Banques"`.

Justify each override:
- cost_of_equity (default 10.5%): suggest a value reflecting typical Moroccan bank beta
- wacc (default 10.5%): for banks, set equal to cost_of_equity (capital structure is regulatory, not optimization)
- terminal_growth (default 3%): suggest a value reflecting long-term Moroccan banking ROE convergence
- fade_years (default 5): suggest if banks need a longer fade than non-financials
- stable_payout_ratio (default 55%): suggest based on observed Moroccan bank payout discipline

Reference `docs/fundamentals-layer/08-assumptions-and-defaults.md` and `docs/fundamentals-layer/10-modelling-playbooks.md#playbook-6`.

Format the response as both:
1. A valid JSON body for the PUT endpoint.
2. A short narrative (4-6 lines) explaining the rationale.
```

### 9. Generate bull/base/bear scenario assumption sets

```
For symbol {SYMBOL}, generate three FundamentalAssumptionSet JSON bodies — one for each scenario (bear, base, bull). Symbol-scoped (`scope_type="symbol"`, `scope_key="{SYMBOL}"`).

For the bear case:
- Lower growth_cap (e.g. 4-5%)
- Raise cost_of_equity by 100-200bps to reflect risk premium
- Lower terminal_growth toward inflation only (2%)

For the bull case:
- Raise growth_cap (e.g. 10-12%)
- Lower cost_of_equity by 100bps
- Raise terminal_growth by 50bps

Reference `docs/fundamentals-layer/12-known-issues-and-limitations.md#-v11` for the multi-scenario implementation notes. Bear/base/bull scenarios are now supported.
```

### 10. Sensitivity walk

```
For symbol {SYMBOL}, walk the ensemble fair value through a grid of (WACC, terminal_growth) values:

WACC: 0.08, 0.09, 0.10, 0.11, 0.12
terminal_growth: 0.02, 0.025, 0.03, 0.035, 0.04

For each combination, override the assumption set, fetch the new ensemble.fair_value_base, and produce a 5x5 table.

Use `PUT /fundamentals/stocks/{symbol}/assumptions/base` to set each combination, then `GET /fundamentals/stocks/{symbol}/valuation`.

Note: the manual process can be replaced by `GET /fundamentals/stocks/{symbol}/sensitivity` for standard WACC/terminal-growth grids.

Reset the assumption set to the original values when done.
```

---

## Code-review prompts

### 11. Check for double-counted metrics

```
Read `core/quant_core/fundamentals/scoring.py`. Identify all metric names that appear in MORE than one `*_METRICS` tuple (VALUE_METRICS, QUALITY_METRICS, GROWTH_METRICS, DIVIDEND_METRICS, RISK_METRICS, CASH_FLOW_METRICS).

For each duplicated metric:
1. Report which tuples it's in.
2. Identify whether this is intentional (the metric captures multiple dimensions of fundamental health) or a leak (the metric was added to one tuple and forgotten in another).

Reference: `docs/fundamentals-layer/12-known-issues-and-limitations.md#-s1` for the discussion.
```

### 12. Verify the methodology references in this docs folder

```
For every link in `docs/fundamentals-layer/12-known-issues-and-limitations.md` that references a file path or line number (format: `valuation.py:NNN` or `scoring.py:NNN`), check that the line number is still accurate against HEAD.

For each stale reference, propose the correct line number. Output as a table:
| docs reference | claimed source | actual source | suggested fix |
```

### 13. Diff the current valuation engine against the recommended fixes

```
Read `docs/fundamentals-layer/12-known-issues-and-limitations.md` issue V1 (FCFE proxy uses raw FCF).

1. Locate the current implementation in `core/quant_core/fundamentals/valuation.py:_fcfe_dcf`.
2. Compare against the proposed `_fcfe_start` helper in the doc.
3. Identify the minimum-viable changeset needed to apply V1's fix:
   - which functions to add
   - which existing code to modify
   - which tests need to be written

Output the changeset as a unified diff. Don't apply it — just propose it.
```

---

## Strategy and decision prompts

### 14. Generate a buy/hold/sell shortlist from the universe

```
From the most recent fundamental snapshots, produce a shortlist of buy/hold/sell candidates. Criteria:

BUY candidates (must satisfy ALL):
- ensemble.upside_pct > 0.15 (15% upside)
- ensemble.confidence_score > 0.7
- usable_model_count >= 3
- snapshot.scores.overall > 60
- snapshot.scores.risk > 50 (i.e. not a leveraged train wreck)
- snapshot.diagnostics.dupont.score > 75 (book quality)

SELL candidates (must satisfy ALL):
- ensemble.upside_pct < -0.15 (15% downside)
- ensemble.confidence_score > 0.7
- snapshot.scores.overall < 40

HOLD: everything else with valid data.

Group by sector and report top 5 buy, top 5 sell within each sector. Include a one-line rationale per name.

Caveat: percentile ranks are sector-bucketed only when peer count is sufficient. Buy/sell list should be reviewed manually before any action.
```

### 15. Stress-test the ensemble across COE perturbations

```
For symbol {SYMBOL}, run a robustness check: how stable is the ensemble's BUY/HOLD/SELL classification under perturbations?

For COE in [9%, 9.5%, 10%, 10.5%, 11%, 11.5%, 12%]:
1. Override assumptions.
2. Fetch ensemble.upside_pct.
3. Classify: BUY (>15%), HOLD ([-15%, +15%]), SELL (<-15%).

Report the result as a table. If the classification flips between BUY and SELL across this range, the ensemble is too COE-sensitive for an investment decision. Recommend further sensitivity analysis before acting.

Use the same workflow as Playbook 10 (sensitivity walk).
```

---

## Architectural prompts

### 16. Plan the next implementation phase

```
Read `docs/fundamentals-layer/12-known-issues-and-limitations.md`. Of the 21 numbered issues, identify:

1. Which 3 are highest-priority for accuracy of intrinsic valuation (focus on V1-V6 and S1-S3).
2. Which 3 are highest-priority for cohort-level analytical correctness (focus on S2, S7, S9).
3. Which would benefit the user without changing engine semantics (S6, V9).

For each, estimate: complexity (LOC), test surface, risk of breaking existing valuations, and dependencies on other fixes.

Output a 3x3 matrix (priority x complexity) and a recommended Phase A / B / C grouping.
```

### 17. Cross-reference against academic sources

```
Read `docs/fundamentals-layer/06-valuation-models.md` and `docs/fundamentals-layer/13-methodology-and-sources.md`.

For each of the 7 valuation models, compare the implementation in `core/quant_core/fundamentals/valuation.py` against the standard academic formulation:

- FCFF/FCFE DCF → Damodaran "Investment Valuation" Ch 14-15
- DDM (Gordon growth) → Williams 1938, refined Gordon 1956
- Residual income → Ohlson 1995
- Justified multiples → Damodaran "Damodaran on Valuation" Ch 9
- Relative multiples → standard sector comp methodology

For each discrepancy, identify:
- The standard formulation.
- The current implementation.
- Whether the deviation is justified (intentional simplification, MAD market context, etc.) or accidental.
```

---

## How to use these prompts effectively

1. **Always include the relevant doc paths** in the prompt body so the assistant grounds its answers.
2. **Be specific about what to read** — `services/api/app/services/fundamentals.py:execute_import_run` not "the fundamentals code".
3. **Ask for an explicit output format** (table, JSON, diff) rather than freeform prose.
4. **Spot-check the numerical answers** against a manual calculation for the first few symbols.
5. **If the answer doesn't match this layer's documented behaviour**, the doc is wrong OR the code drifted — both deserve a follow-up.

## See also

- [10-modelling-playbooks.md](10-modelling-playbooks.md) — the playbooks these prompts automate.
- [12-known-issues-and-limitations.md](12-known-issues-and-limitations.md) — the issues you might be diagnosing.
