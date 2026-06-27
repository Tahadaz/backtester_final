# 27 — Codex brief: materialised comps view (P2 quick win)

> **Rubric.** `~/.claude/plugins/cache/claude-for-financial-services/financial-analysis/0.1.1/skills/comps-analysis/SKILL.md` and `~/.claude/plugins/cache/claude-for-financial-services/market-researcher/0.1.1/skills/comps-analysis/SKILL.md`.
>
> **Why.** Danger D8. The peer cohort and the per-metric statistics exist inside the valuation engine (`_peer_stats`) but nothing exposes them as a *table*. Two analysts can disagree about which peers were used because the cohort is implicit. Brief 27 materialises a single comps artefact per symbol.

---

## Files Codex MUST read first

1. `core/quant_core/fundamentals/valuation.py` `_peer_stats` (around line 229) and `_relative_multiples` and `_justified_multiples` — to know which metrics and which cohort logic already exist. Re-use; do not parallel-implement.
2. `core/quant_core/fundamentals/scoring.py` `_percentile_scores` (around line 70) — the percentile / z-score engine reused here.
3. `services/api/app/schemas/fundamentals.py` — current envelope.
4. `docs/fundamentals-layer/20-claude-design-handoff.md` Comparables tab — reuse field names.

---

## Scope

A `compute_comps_table(symbol, snapshot, peers)` function that produces ONE dict per call, plus the API surface to retrieve it. No new persistence; the table is computed at envelope time and ridden along.

Out of scope: separate "comps page" workbook export (lives in brief 29).

---

## What the table contains

Rows = peer symbols + the subject + a stats footer.
Columns = a fixed list of metrics:

Operating block:
- `revenue_ttm`
- `revenue_growth_3y`
- `gross_margin`
- `ebitda_margin`
- `fcf_margin`
- `roe`
- `roic`

Valuation block:
- `pe_ttm`
- `pb`
- `ev_ebitda`
- `ev_sales`
- `dividend_yield`
- `fcf_yield`

The metric name list lives in a module-level constant `COMPS_METRIC_KEYS` in `valuation.py` (or a `comps.py` sibling). Codex MUST verify each key already exists in `snapshot.metrics` — if a key does not exist in any snapshot the codebase ever produces, do NOT add it to the constant in this brief; flag back instead.

### Stats footer (5 rows under the data rows)

For each metric column: `Max`, `75th percentile`, `Median`, `25th percentile`, `Min`. NaN-tolerant (skip `None`). Percentile is the inclusive linear interpolation (`numpy.quantile` style); single peer → all five rows equal that value (the implementation handles this without raising).

### Subject row highlights

The subject's row carries `z_score` and `pct_dev_from_median` per metric (re-use `_percentile_scores` output, do not recompute). UI uses these for the cell colour grading.

---

## Function signature

```python
def compute_comps_table(
    subject: FundamentalSnapshot,
    peers: list[FundamentalSnapshot],
) -> dict[str, Any]:
    """
    Returns:
      {
        "subject_symbol": str,
        "cohort_scope": str,                  # "sector" | "market" | "manual"
        "peer_symbols": list[str],
        "metric_keys": list[str],             # = COMPS_METRIC_KEYS, in fixed order
        "rows": [                             # one per peer + subject; subject first
            {
              "symbol": str,
              "is_subject": bool,
              "values": dict[metric_key, float | None],
              "z_scores": dict[metric_key, float | None],     # subject only; None for peers
              "pct_dev_from_median": dict[metric_key, float | None],
            },
            ...
        ],
        "stats": {
          metric_key: {"max": float|None, "p75": float|None, "median": float|None,
                       "p25": float|None, "min": float|None, "n": int}
        },
      }
    """
```

`peers` is supplied by the caller — Codex does NOT introduce a new peer-selection algorithm here. The caller uses the SAME `_peer_stats` cohort that the relative multiples model already uses. Reuse the helper that produces `peer_symbols`, do not branch.

`cohort_scope` mirrors the existing `_peer_stats` `scope` tag.

---

## Wiring point

In the worker/API layer that builds the per-symbol envelope (the same layer that triggers brief 26's sensitivity grids), call `compute_comps_table` once and attach to the envelope under a top-level `comps_table` field. Do not call it from inside the valuation engine — keep that path lean.

---

## API surface

`PerSymbolEnvelopeOut` (current name TBD by Codex's reading) gains:
```
comps_table: CompsTableOut | None
```

`CompsTableOut` is a pydantic mirror of the dict above.

---

## UI spec update

Update `docs/fundamentals-layer/20-claude-design-handoff.md` Comparables tab:
- A single table with sticky header, subject row pinned at top.
- Footer with the five-row stats block, visually separated.
- Cell colouring rule: for the subject row, green if `pct_dev_from_median < -0.10` on a "low-is-good" metric (e.g. `pe_ttm`), red if `> 0.10`; reversed for "high-is-good" metrics. Codex declares the directionality table inside the spec (`"low_is_good": {"pe_ttm", "pb", "ev_ebitda", "ev_sales"}`, the rest are high-is-good).
- Tooltip on each cell shows the source year and any `is_proxy=True` flag.

---

## Tests

`core/tests/test_comps_table.py`:
- `test_table_includes_all_metric_keys` — output `metric_keys == COMPS_METRIC_KEYS`.
- `test_subject_row_first_and_flagged` — `rows[0].is_subject is True`.
- `test_stats_skip_none` — peer with `revenue_ttm=None` does not poison the median.
- `test_single_peer_cohort` — one peer → all five stats equal that peer's value, `n=1` (or `n=2` if subject counted — choose; Codex picks one and documents).
- `test_z_score_zero_when_subject_equals_median` — synthetic input.
- `test_no_mutation_of_inputs` — pre/post equality on subject and peers.

---

## Acceptance criteria

- [ ] Tests green.
- [ ] `comps_table` field present in envelope for any symbol with a valid cohort.
- [ ] When `_relative_multiples` returns `scope="market"` (cohort fell back), `comps_table.cohort_scope == "market"`.
- [ ] No change to fair-value outputs.
- [ ] `COMPS_METRIC_KEYS` is documented as a module-level public constant; UI consumers can rely on its order.
