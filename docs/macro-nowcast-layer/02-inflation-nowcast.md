# Morocco Inflation Nowcast (Phase B3)

## Target

Monthly HCP CPI, both transforms persisted as separate `nowcast_value` rows
under distinct `series_id`s:

- `NOWCAST_MA_CPI_YOY` — year-over-year CPI growth.
- `NOWCAST_MA_CPI_MOM` — month-over-month CPI growth.

The exported derived factor series consumed by the rest of the platform
(`04-surprise-and-regimes.md`, `05-validation-gates.md`) is `NOWCAST_MA_CPI`
(y/y, the conventional headline figure); m/m is retained for the surprise
engine's shorter-horizon event studies in Plan C.

---

## Feature Set and PIT Assembly

New file: `core/quant_core/research/nowcast/features.py`.

Every feature row is assembled **as of** a target month's forecast date and
must satisfy `available_at ≤ as_of_date` for every input — the assembly
function asserts this explicitly (raises, does not silently drop) before
returning a row, because a silent PIT violation here would inflate the OOS
harness's apparent skill.

| Feature | Source | Transform | Lag / availability |
|---|---|---|---|
| Brent in MAD, m/m | `BRENT` (Yahoo, existing) × `MADUSD` (Yahoo, new — [`01-data-sources.md`](01-data-sources.md)) | % change, month-end vs prior month-end | `available_at` = last trading day of the month (T-0, same calendar month as the target print) |
| Wheat, m/m | `WHEAT` (`ZW=F`, new) | % change, month-end vs prior month-end | same as Brent |
| FAO Food Price Index, last print | CSV source (`01-data-sources.md` §3) | level or m/m, whichever the OOS harness finds more predictive — confirm at implementation | FAO publishes ~first week of month+1 for month; `available_at` = FAO's own publish date, not month-end |
| EURMAD / MADUSD, m/m | Yahoo (new, §1) | % change, month-end vs prior month-end | same as Brent |
| Prior CPI prints / HCP subindices | `macro_release` (series `MA_CPI_YOY`, `MA_CPI_MOM`, and subindex series if HCP publishes them separately) | lagged levels/differences (AR terms) | `available_at` = the **true** HCP release date read from `macro_release.release_time`, i.e. the actual PIT lag from HCP's own calendar (`01-data-sources.md` §4) — not an assumed fixed lag |

`available_at` is carried on every feature row (not just asserted and
discarded) so the OOS harness (§ below) can reconstruct, for any historical
`as_of_date`, exactly what a forecaster running the model live would have
known — this is the same discipline as `align_factor_to_target()` in
`core/quant_core/research/alignment.py`, applied to monthly macro data
instead of daily equity/factor series.

---

## Models

New file: `core/quant_core/research/nowcast/models.py`, target **under 200
lines total** for both models combined — this is a deliberate
simplicity-over-fancy constraint. With ~120 monthly observations, a
model with more free parameters than a low-order AR + linear bridge
regression will overfit before it generalizes; the OOS gate below is the
actual arbiter of whether added complexity earned its keep, not a priori
model sophistication.

Both models are **pure functions**: `(history_df, target_period) → (point:
float, std: float)`. No hidden state, no class instances holding fit
results across calls — each call re-estimates from scratch on the data
visible as of that call, which is what makes the expanding-window harness
below correct by construction (there is no way to accidentally leak a
future-fitted parameter into a past prediction).

1. **`naive_ar_benchmark(history_df, target_period) → (point, std)`**
   Seasonal AR on y/y CPI: regress the target month's y/y print on its own
   lags (e.g. AR(1) or AR(1) + 12-month seasonal term — confirm exact order
   via the OOS harness, not by pre-selection). This is the floor every
   fancier model must beat, and — per the gate below — the label the
   published nowcast falls back to when it doesn't.

2. **`ridge_bridge_nowcast(history_df, target_period) → (point, std)`**
   Ridge-regularized bridge regression: target y/y CPI on the assembled
   feature set (Brent-in-MAD, wheat, FAO FPI, FX, AR terms). Ridge
   (L2) is chosen over OLS specifically because the feature count is not
   small relative to ~120 observations — regularization is required to keep
   the coefficient estimates stable expanding-window to expanding-window,
   not just to improve one-shot in-sample fit. `std` is the ridge model's
   residual-based predictive standard error, not a training-fit residual.

Both models operate on monthly-resampled data; no intraday/daily modeling
inside this file — daily-frequency inputs are already reduced to monthly
features by `features.py` before either model sees them.

---

## Expanding-Window OOS Harness

New file: `core/quant_core/research/nowcast/evaluate.py`, function
`expanding_window_oos(...)`:

1. Start from the earliest month with a full feature row and a next-month
   actual to score against.
2. For each subsequent month, **re-estimate both models using only data
   with `available_at` ≤ that month's forecast date**, produce a one-step-
   ahead prediction for the next HCP print, then reveal the actual and
   score.
3. Repeat, expanding the training window by one month each iteration
   (never a rolling/fixed window — expanding is the correct discipline
   given the sample is already thin; discarding old months for a rolling
   window would throw away scarce information for no benefit at this
   sample size).
4. Aggregate: **RMSE ratio** = RMSE(`ridge_bridge_nowcast`) /
   RMSE(`naive_ar_benchmark`) over the OOS window, plus a
   **Diebold–Mariano test** (Diebold & Mariano, 1995, *JBES*) on the paired
   OOS squared-error loss differentials to test whether the RMSE
   improvement is statistically distinguishable from noise, not just a
   lower point estimate on a ~36-observation sample.

---

## Gate B3

**Published as `ridge_bridge_nowcast` only if both hold:**

- RMSE ratio < 0.95 over **≥ 36 OOS months** (3 years — the minimum window
  the harness requires before the gate is even evaluated; fewer months
  means "not enough evidence yet," which routes to the fallback below, not
  to a provisional pass).
- Diebold–Mariano p < 0.10.

**Else**: the published `NOWCAST_MA_CPI` value **is** the AR benchmark's
output, persisted with `nowcast_value.model_version = 'ar_benchmark'`. This
is not a degraded/disabled state — the AR benchmark still fully powers the
surprise engine (`04-surprise-and-regimes.md`) and the BAM classifier's
inflation-gap feature (`03-rate-classifier.md`); it is simply the honest
label for "the added complexity of the bridge model didn't earn its keep on
current evidence." Re-evaluate the gate on every scheduled refresh (below)
as the OOS window grows — a model that fails the gate at 36 months can pass
it later at 60 months without any code change, purely from more evidence
accumulating.

---

## Refresh Cadence

Daily task `refresh_nowcasts`, **18:30 Mon–Fri Africa/Casablanca** (after the
market close and after that day's macro-series ingestion), per the
`ScheduleSpec` pattern in `services/api/app/services/scheduler_registry.py`
(see [`06-phases.md`](06-phases.md) for the exact registry entry). Each run:

1. Re-assembles the current month's feature row (features already available
   `as_of` today).
2. Produces a fresh `(point, std)` from whichever model currently holds the
   gate (re-checked each run, not cached indefinitely).
3. Writes a `nowcast_value` row (`series_id='NOWCAST_MA_CPI'`,
   `as_of_date=today`, `target_period=<current or next HCP period>`,
   `model_version`) and upserts the derived factor series `NOWCAST_MA_CPI`
   via the same parquet/DB pattern `ingest_macro_series.py` already uses for
   Yahoo series, so downstream `align_factor_to_target()` calls treat it
   identically to any other factor series.

Because the nowcast only changes meaningfully when its underlying monthly
inputs change (Brent/wheat/FX move daily but the *nowcast itself* is a
monthly-target estimate), most daily runs will re-emit a value close to the
prior day's — this is expected and not a bug; the daily cadence exists so
the nowcast reacts same-day to input moves (e.g. an oil price shock)
without waiting for month-end.

## What This Phase Does Not Do

- Does not use HMMs, Bayesian shrinkage, or any model class the factor
  layer has already ruled out of scope for the same thin-sample reasons
  (`docs/factor-layer/01-overview-and-research-question.md`, "What This
  Layer Does Not Do").
- Does not backtest the m/m or subindex nowcasts through the same rigor as
  y/y unless/until they are promoted for their own use (§ Target above) —
  they are retained for Plan C event-study granularity but the gate in this
  document is scoped to the published `NOWCAST_MA_CPI` (y/y) series.
- Does not skip the gate re-check on any refresh — `model_version` can flip
  between `ar_benchmark` and a bridge-model label across time as OOS
  evidence accumulates or degrades.
