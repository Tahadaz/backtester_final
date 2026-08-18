# Validation Gates (A6)

The sentiment layer is research-only until its exported series pass a
pre-registered IC study. This document specifies the Plan-A study design and
the four numeric gates. The shared cross-layer machinery — FDR policy,
promotion criteria, verdict-artifact conventions — lives in
[../alt-data-foundation/02-validation-policy.md](../alt-data-foundation/02-validation-policy.md)
and is cited, not restated.

## What is tested

Every exported `SENT_*` factor series
([04-aggregation-and-factors.md](04-aggregation-and-factors.md)):
`SENT_MA_MACRO`, `SENT_MA_MARKETS`, `SENT_GLOBAL_GEOPOL`,
`SENT_COMMODITIES`, plus each coverage-eligible `SENT_SYM_{TICKER}` series
— against **MASI closes** (index level for the topic_region series; the
matching stock's closes additionally for each `SENT_SYM_*` series).

## Study design — full reuse of existing IC machinery

No new statistics code. The study is a thin driver over three existing
modules, whose real signatures are:

1. **`core/quant_core/research/factors/relevance.py::compute_factor_relevance`**

   ```python
   def compute_factor_relevance(
       factor_id: str,
       factor_series: pd.Series,
       stock_prices: Dict[str, pd.Series],
       lag_rule: str = "precede_open",
       max_staleness: int = 3,
       forward_horizon: int = 1,
       nw_bandwidth: int = 5,
       cv_window: int = 63,
       min_obs: int = 30,
       as_of: Optional[str] = None,
   ) -> FactorRelevanceMatrix
   ```

   Called once per (SENT series, horizon) with
   `lag_rule="precede_open"` (the alignment goes through
   `research/alignment.py::align_factor_to_target` internally;
   `contemporaneous` is forbidden for this layer per the PIT join rule in
   [../alt-data-foundation/01-pit-event-store.md](../alt-data-foundation/01-pit-event-store.md))
   and `forward_horizon` ∈ **{1, 5, 21}** sessions. Each returned
   `FactorStockPair` carries `ic`, `t_stat` (Newey–West, via
   `stats/ic.py::_newey_west_var`), `p_value`, `ic_cv`, `n_obs`,
   `significant`.

2. **`core/quant_core/research/stats/fdr.py`** — applied across the full
   tested grid:

   ```python
   def benjamini_hochberg(p_values: list[float], q: float = 0.10) -> list[bool]
   def bh_adjusted_pvalues(p_values: list[float]) -> list[float]
   ```

   The "grid" over which BH is run is every (series × target × horizon)
   pair the study evaluates, **pre-registered before the study runs** — no
   post-hoc pruning of tested combinations (per the shared policy's
   multiple-testing rules).

3. **`core/quant_core/research/stats/ic.py`** — supplies the Newey–West
   variance (`_newey_west_var(x, bandwidth)`) and Spearman rank IC
   (`_spearman_corr`, `rank_ic(signal, forward_returns)`) that
   `compute_factor_relevance` builds on; `ic_decay_curve(signal, prices,
   horizons)` is additionally run per series for the diagnostic report
   (decay shape across horizons {1, 2, 3, 5, 10}), though it is not itself
   a gate input.

Driver: `core/quant_core/research/sentiment/ic_study.py::run_sentiment_ic_study(as_of: str) -> SentimentICVerdict`,
plus an RQ entry point `services/worker/tasks/sentiment_ic_study.py` for
on-demand runs (manually triggered; not scheduled until the layer has
enough live history to make a weekly cadence meaningful).

## The four numeric gates

A `SENT_*` series **passes** only if all four hold, per (series, target,
horizon) claim:

| # | Gate | Threshold |
|---|---|---|
| 1 | Newey–West IC t-stat | `t ≥ 2.0` (from `FactorStockPair.t_stat`) |
| 2 | Multiple-testing survival | claim survives Benjamini–Hochberg at `q = 0.10` across the full pre-registered grid (`benjamini_hochberg(all_p_values, q=0.10)`) |
| 3 | Coverage | the series has `n_items ≥ 3` on **≥ 60% of trading sessions** in the evaluation window (from `alt_sentiment_daily.n_items`) — an index computed from one or two articles a day is not a series, it's anecdotes |
| 4 | Sign stability | the rolling 63-session mean IC has the same sign as the full-sample IC in **≥ 60% of rolling 63d windows** (window length matches `compute_factor_relevance`'s `cv_window=63` default) — kills series whose full-sample IC is an artifact of one regime |

Failing any gate → the series stays research-only. There is no partial
credit and no gate-shopping across horizons: each (series, target, horizon)
claim is evaluated independently, and only claims passing all four are
listed as pass in the verdict.

## Pre-cutoff LLM history: upper bound, never promotable

Scores whose underlying article predates the scoring model's training
cutoff are structurally suspect (lookahead bias — see
[00-overview.md](00-overview.md#why-sentiment) and
[02-llm-scoring.md](02-llm-scoring.md#lookahead-bias-provenance)). The
study therefore runs **twice**:

- **Live-collected sample**: only scores where the provenance columns show
  scoring happened contemporaneously with publication (post-deployment
  live pipeline). This is the only sample whose gate passes are
  **promotion-eligible**.
- **Full-history sample** (includes backfilled 2019+ articles scored years
  after publication): labeled `pit_grade='upper_bound'` throughout, per
  the shared policy. Reported separately in the verdict artifact and any
  UI surface, always with the upper-bound caveat, **never
  promotion-eligible** regardless of how well it gates. Its only
  legitimate use is as a ceiling estimate: if even the contaminated
  upper-bound sample fails the gates, the live sample will not pass them
  either, which is an early kill-switch worth having years before the
  live sample is large enough to test.

Practical consequence: gate evaluation on the live sample cannot begin
until the live pipeline has accumulated a meaningful window (gate 3's
coverage requirement implicitly enforces a minimum elapsed time). The
layer's docs and UI must not present upper-bound results as validation.

## Verdict artifact

Each study run writes one JSON verdict artifact to S3 under
`alt_data/studies/sentiment_ic/{as_of}.json`:

```json
{
  "study": "sentiment_ic",
  "as_of": "2026-09-30",
  "pit_grade": "live" ,
  "grid": [
    {
      "series": "SENT_MA_MACRO",
      "target": "MASI",
      "horizon": 5,
      "ic": 0.041,
      "nw_t": 2.31,
      "p_value": 0.021,
      "bh_q_survives": true,
      "coverage_pct": 0.71,
      "sign_stability_pct": 0.66,
      "n_obs": 412,
      "gates_passed": [1, 2, 3, 4],
      "verdict": "pass"
    }
  ],
  "summary": {"tested": 42, "passed": 1, "coverage_failures": 18},
  "provenance": {"prompt_versions": ["v1"], "models": ["..."], "code_version": "..."}
}
```

Two artifacts per run date when both samples are evaluated — one with
`pit_grade='live'`, one with `pit_grade='upper_bound'` (filename suffix
`_upper_bound`). Format details (required provenance keys, retention)
follow the shared verdict-artifact conventions in
[../alt-data-foundation/02-validation-policy.md](../alt-data-foundation/02-validation-policy.md).

## Tests

`core/tests/test_sentiment_ic_study.py` — synthetic-series fixtures with a
known injected IC (gates 1–2 pass/fail on constructed data), coverage-gate
arithmetic (gate 3), sign-stability windowing (gate 4), and
upper-bound-vs-live sample splitting on the provenance columns.
