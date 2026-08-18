# Validation Gates (Phase B6)

Model-level gates (B3's RMSE/DM gate, B4's LOO gates) established that the
nowcasts beat their naive baselines. B6 asks the separate, market-facing
question: **do the derived series predict MASI returns?** Nothing from this
layer touches a product page until the answer survives the gates below.
Policy shared with Plans A and C is defined once in
[`../alt-data-foundation/02-validation-policy.md`](../alt-data-foundation/02-validation-policy.md);
this page only specifies the nowcast-specific test grid and thresholds.

---

## IC Harness (reused, not rebuilt)

Reuse the sentiment-layer harness verbatim — which is itself the factor
layer's existing machinery:

- `core/quant_core/research/factors/relevance.py::compute_factor_relevance()`
  — per-(factor, stock) IC with Newey–West t-stats, `lag_rule="precede_open"`
  (the `contemporaneous` rule is forbidden for all alt-data layers, per the
  shared PIT join rule), `max_staleness` sized to the series' natural print
  frequency (a monthly-updating `*_LAST` series is legitimately "stale" for
  ~21 sessions; set `max_staleness` accordingly rather than letting the
  default 3-session guard NaN out the whole series — this is a parameter
  choice, not a code change).
- `core/quant_core/research/stats/fdr.py::benjamini_hochberg()` /
  `bh_adjusted_pvalues()` for multiple-testing control across the full grid.

### Test grid (frozen at pre-registration)

| Dimension | Values |
|---|---|
| Series | `SURPR_MA_CPI_LAST`, `SURPR_US_CPI_LAST`, `REGIME_MA_INFL_RISING`, `REGIME_GLOBAL_TIGHTENING`, `REGIME_MA_EASING`, `BAM_RATE_DIR` |
| Targets | Bank names (sector `Banques`), real-estate names (sector `Immobilier`), MASI index |
| Horizons | per the shared validation policy's standard horizon set |

Banks and real estate are the pre-registered target set because they are the
economically-motivated transmission channels (rate sensitivity — same logic
as the `channel_filter` on the `BAM_RATE_DIR` spec,
[`04-surprise-and-regimes.md`](04-surprise-and-regimes.md)); MASI is the
aggregate sanity check. Testing all ~70 MASI names would triple the grid
and dilute FDR power for no hypothesis-driven reason.

### Gates (all must hold, per series×target family)

- **Newey–West IC t ≥ 2.0**, and
- survives **Benjamini–Hochberg FDR at q = 0.10** across the entire
  pre-registered grid above (not per-cell).

Failures are recorded as null results, not retried with tweaked parameters
— the grid is frozen.

---

## Additional Promotion Path for the Rate-Direction Signal

`BAM_RATE_DIR` is the only series intended to become a *tradeable signal*
(the surprises and regime flags are conditioning inputs). It therefore
additionally requires the platform's standard promotion pipeline before
touching Signal/Dashboard pages:

1. IC gates above, **and**
2. the standard **WFO OOS evaluation** through
   `core/quant_core/wfo/engine.py::run_wfo_engine()` — the spec appended in
   B5 makes `BAM_RATE_DIR` sweep-able by the existing WFO machinery like
   any registered factor signal — **and**
3. **cost-adjusted OOS performance** per the platform's existing promotion
   criteria (net of the standard per-side cost assumption used by the
   backtest layer; see `docs/backtest-layer/03-prom-and-objective-function.md`
   for the objective and `../alt-data-foundation/02-validation-policy.md`
   for the cross-layer promotion wording).

Note the structural honesty problem: with quarterly meetings, `BAM_RATE_DIR`
changes value only ~4 times/year, so WFO folds contain very few independent
signal transitions. Expect wide OOS confidence bands; the default outcome is
"park, don't promote," and that is an acceptable published result.

---

## Verdict Artifacts

Every B6 run (pass or fail) writes a verdict artifact to S3 under
`alt_data/studies/nowcast_validation/` — same bucket-layout convention as
Plan A's `alt_data/studies/sentiment_ic/` (see
[`../alt-data-foundation/02-validation-policy.md`](../alt-data-foundation/02-validation-policy.md)
for the artifact schema: grid definition, raw ICs/t-stats, BH-adjusted
q-values, pass/fail per gate, data-coverage window, `pit_grade`, code/config
hash). The research tab reads promotion status from these artifacts, never
from ad-hoc recomputation.

## What This Phase Does Not Do

- Does not relax any threshold when results are "almost significant."
- Does not test series or targets outside the frozen grid.
- Does not let `SURPR_*` or `REGIME_*` series become standalone tradeable
  signals — only `BAM_RATE_DIR` has a promotion path; the others are
  conditioning/event inputs by design.
