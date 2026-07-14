# Validation & Gating Policy

Unified policy across Plan A (sentiment), Plan B (macro nowcasting), and Plan C (event backtesting). Every numeric threshold in this document is a **hard gate**, not a guideline: a study that fails a gate is filed as a negative result (verdict artifact still written, see [Verdict-artifact convention](#verdict-artifact-convention)) and the underlying series/model stays on the research tab only.

This policy exists because of the thin-sample warning in [00-overview.md](00-overview.md#thin-sample-warnings): Morocco macro series are structurally low-frequency (~120 CPI prints, ~48 BAM meetings/decade), and even sentiment series — while daily — are being tested against a large candidate grid (per-topic, per-region, per-symbol series × multiple horizons). Both conditions are classic false-discovery setups. The mitigations are the same three tools used everywhere else in this repo's research layers: pre-registration, multiple-testing correction, and out-of-sample validation — reused from the factor layer, not reinvented.

## Reused statistical machinery (verified)

All three layers' gates are computed with the existing stats/relevance modules — no new statistical library is introduced.

**`core/quant_core/research/stats/fdr.py`** (verified functions):
```
def benjamini_hochberg(...)        # BH-FDR procedure — the primary multiple-testing control used everywhere below
def bh_adjusted_pvalues(p_values: list[float]) -> list[float]   # convenience wrapper returning adjusted p (q) values
def harvey_liu_sharpe_haircut(...) # Sharpe-ratio multiple-testing haircut (reused for WFO promotion gates, Plan C)
```

**`core/quant_core/research/stats/ic.py`** (verified functions):
```
def _newey_west_var(x: np.ndarray, bandwidth: Optional[int] = None) -> float   # HAC variance estimator
def rank_ic(signal: pd.Series, forward_returns: pd.Series) -> float            # Spearman rank IC
def ic_decay_curve(...)                                                        # IC across multiple horizons
def conditional_return_tstat(...)                                              # regime-conditioned t-stats
```
Newey-West t-stats for IC series (used by the sentiment gate below) are built from `rank_ic()` + `_newey_west_var()` — the same combination `docs/factor-layer/05-statistical-battery.md` documents for the macro factor layer.

**`core/quant_core/research/factors/relevance.py`** (verified functions/classes):
```
class FactorStockPair
class FactorRelevanceMatrix
def compute_ic_series(...)
def compute_pair_relevance(...)
def compute_factor_relevance(...)   # the main entry point — used as-is against SENT_*/SURPR_*/REGIME_* series
```
`compute_factor_relevance` already implements the horizon sweep ({1,5,21}-day), `precede_open` alignment, and IC aggregation that the macro factor layer uses (`docs/factor-layer/06-descriptive-relevance-study.md`); the sentiment and nowcast gates below call it unmodified against the new derived series, exactly as they'd call it against any existing macro factor — this is the payoff of writing derived series through the `macro_factor_meta` reuse path described in [01-pit-event-store.md](01-pit-event-store.md#s3-layout).

**PIT alignment**: every study behind these gates aligns via `core/quant_core/research/alignment.py::align_factor_to_target(..., lag_rule="precede_open")` per [THE PIT JOIN RULE](01-pit-event-store.md#the-pit-join-rule). `contemporaneous` alignment invalidates a study regardless of how it otherwise scores against the gates below.

---

## Gate 1 — Sentiment IC gate (Plan A, phase A6)

Applies to every `SENT_*` derived series (per-topic, per-region, per-symbol) before it may be considered for promotion. Full study design in `../sentiment-layer/05-validation-gates.md`; this section is the canonical gate definition referenced from there.

| Criterion | Threshold |
|---|---|
| IC significance | Newey-West-adjusted IC t-statistic ≥ **2.0** (computed via `rank_ic` + `_newey_west_var`, as above) |
| Multiple-testing survival | Survives **BH-FDR q ≤ 0.10** across the full tested grid (all series × all horizons {1,5,21} tested together, one `benjamini_hochberg` call, not per-series) |
| Coverage | ≥ **60%** of trading sessions in the study window have `n_items ≥ 3` for that subject (from `alt_sentiment_daily.n_items`) — a series that is mostly empty cannot be said to have been "tested" |
| Sign stability | IC sign is stable in ≥ **60%** of rolling 63-trading-day windows (roughly one quarter) across the study window |

**All four must pass simultaneously.** A series with a strong average IC but poor coverage (e.g., a thinly-covered small-cap symbol) fails on coverage even if the other three pass — this is deliberate: an IC computed on 20% of sessions is not evidence about the other 80%.

**Pre-cutoff LLM history is reported separately as an upper bound**, per the `pit_grade` propagation rule in [01-pit-event-store.md](01-pit-event-store.md#3-pit_grade39upper_bound39-propagation). A study that only has `upper_bound` data available (e.g., early backfill period before live scoring began) computes and reports the same four statistics, but the verdict artifact is explicitly `promotable=false` regardless of the numbers, with `reason="upper_bound_only"`.

## Gate 2 — Nowcast gate (Plan B, phase B3)

Applies to the Morocco CPI nowcast (and any future nowcast series built the same way). Full harness design in `../macro-nowcast-layer/03-inflation-nowcast.md`.

| Criterion | Threshold |
|---|---|
| Accuracy vs. naive benchmark | RMSE ratio (`RMSE(model) / RMSE(naive_ar_benchmark)`) **< 0.95**, computed over an expanding-window out-of-sample harness (`nowcast/evaluate.py::expanding_window_oos`) spanning **≥ 36 OOS months** |
| Statistical significance of the improvement | Diebold-Mariano test **p < 0.10** (one-sided: model forecast errors significantly smaller than naive-AR errors) |

**Both must pass.** If either fails, the nowcast that is actually published to `nowcast_value` **is the naive AR benchmark itself**, labeled `model_version='ar_benchmark'` — not withheld entirely, because the AR benchmark still has value as the input to the surprise engine (Plan B, phase B5) even when the more sophisticated ridge-bridge model doesn't clear the bar. This is a deliberate "fail open to the honest baseline" design, distinct from the sentiment/event gates, which fail closed (research-tab-only, nothing promoted).

36 OOS months is chosen because it is roughly the point at which an expanding-window harness against ~120 total historical CPI prints has accumulated enough re-estimation cycles for the RMSE ratio and DM test to be meaningfully powered, while leaving enough initial-window months for the model to have a non-degenerate training set.

## Gate 3 — BAM rate-direction classifier gate (Plan B, phase B4)

Applies to the BAM policy-rate direction classifier. Full design in `../macro-nowcast-layer/03-rate-classifier.md`.

| Criterion | Threshold |
|---|---|
| Calibration | Leave-one-out (LOO) cross-validated log-loss **<** climatology baseline (a model that always predicts the historical unconditional hike/hold/cut frequencies) |
| Discrimination | **≥ 60%** directional hit-rate on non-hold meetings only (i.e., excluding meetings where the base rate itself didn't move — a "hold" prediction on a "hold" meeting is not evidence of directional skill) |

**Both must pass.** LOO-CV (not k-fold) is used because the sample is small (~48 meetings) and meetings are not exchangeable across time in a way that would make a random k-fold split meaningful — LOO with profile-likelihood confidence intervals is the honest-uncertainty choice for a sample this size, per the design note in the original plan (`hey-so-i-was-rustling-zebra.md`, phase B4). Climatology, not a coin flip, is the baseline, because rate meetings are not 50/50 events (holds dominate) — beating a coin flip is a much weaker bar than beating the empirical base rate.

## Gate 4 — Event-study promotion gates (Plan C, phase C4)

Applies to every `(event_type, window, benchmark)` cell in the pre-registered grid (see `../event-backtest-layer/04-multiple-testing.md`). This is the strictest gate set in the whole initiative because event studies are the most exposed to multiple-testing inflation (four event types × four windows × three benchmarks = up to 48 grid cells tested together).

| Criterion | Threshold |
|---|---|
| Sample size | **n ≥ 30** events in the cell (below this, CAAR standard errors are not treated as reliable regardless of how they compute) |
| Multiple-testing survival | Post-BH **q ≤ 0.05** across the **full pre-registered grid** (stricter than the q ≤ 0.10 used for research-display purposes within a single event-type family — see [Two-tier FDR policy](#two-tier-fdr-policy-plan-c) below) |
| Effect robustness | Block-bootstrap confidence interval on CAAR **excludes 0** (`bootstrap_iters=2000` per `EventStudyConfig`, see `../event-backtest-layer/01-methodology.md`) |
| Tradability | Event-conditioned walk-forward-optimized **OOS Sharpe > 0**, net of **25 bps/side** transaction costs (reuses the existing WFO promotion machinery — `run_wfo_engine` — per `../event-backtest-layer/03-strategy-runner.md`) |
| Stability | CAAR has the **same sign** in both halves of the sample period (split at the midpoint by event date) |

**All five must pass.** This is a strict AND, not a scoring function — an event-study cell that clears four of five gates is not promoted; it is filed as `promotable=false` with the failing gate named in the verdict artifact.

### Two-tier FDR policy (Plan C)

Because the pre-registered grid is large, event studies use **two different BH-FDR thresholds for two different purposes**, both computed via `benjamini_hochberg`:

1. **q ≤ 0.10 within an event-type family** (e.g., all window×benchmark combinations for "macro releases" tested together) — this is the threshold used for **research-tab display**: a cell that clears this bar is shown on `/sentiment-events` with its raw p-value, its BH-adjusted q-value, and n_events, but is not eligible for backtest/strategy promotion.
2. **q ≤ 0.05 across the full grid** (every event type × window × benchmark combination tested together in one BH pass) — this is the threshold used for **promotion eligibility** (Gate 4 above).

The UI always shows all three numbers side by side (raw p, BH q, n_events) so a viewer can see exactly how much of the significance survived correction — this is a requirement, not a nice-to-have, given how easy it is for a raw p-value on a 48-cell grid to look significant by chance alone.

---

## Verdict-artifact convention

Every gate evaluation — pass or fail — writes a JSON verdict artifact to S3, using the same `core/quant_core/s3_keys.py`-style canonical-key discipline as the rest of the repo (a new key-builder function, `build_alt_data_study_object_key(study_kind, subject_key, run_date)`, is added alongside `build_news_raw_object_key` in the F1 work package's companion code, since both layers write under the `alt_data/` S3 prefix).

**Layout**:
```
alt_data/studies/sentiment_ic/{subject_key}/{run_date}.json        # Gate 1
alt_data/studies/nowcast_validation/{series_id}/{run_date}.json    # Gates 2 and 3
alt_data/studies/event_study/{event_type}__{window}__{benchmark}/{run_date}.json   # Gate 4
```

**Verdict JSON shape** (common envelope across all three layers, extended with layer-specific metric blocks):

```json
{
  "study_kind": "sentiment_ic",
  "subject_key": "SENT_MA_MACRO",
  "run_date": "2026-07-13",
  "window": {"start": "2019-01-01", "end": "2026-07-10"},
  "pit_grade_composition": {"live_days": 812, "upper_bound_days": 1103},
  "metrics": {
    "nw_ic_tstat": 1.74,
    "bh_q": 0.14,
    "coverage_pct": 0.71,
    "sign_stability_pct": 0.55
  },
  "gates": {
    "ic_tstat_ge_2_0": false,
    "bh_q_le_0_10": false,
    "coverage_ge_60pct": true,
    "sign_stability_ge_60pct": false
  },
  "promotable": false,
  "reason": "failed: ic_tstat_ge_2_0, bh_q_le_0_10, sign_stability_ge_60pct",
  "code_version": "<git sha>",
  "generated_at": "2026-07-13T18:15:00Z"
}
```

Key fields every verdict shares: `promotable` (bool, the single source of truth for "may this touch Signal/Dashboard"), `reason` (human-readable, names every failing gate — not just the first one, so a re-run after a partial fix shows visible progress), `pit_grade_composition` (so a viewer can immediately see how much of the window is upper-bound-only), and `code_version` (git SHA of the code that produced the study, for reproducibility — mirrors how the factor layer's descriptive relevance study records its provenance, `docs/factor-layer/06-descriptive-relevance-study.md`).

Verdicts are **never overwritten** — each `run_date` is a new key. The `/ingest-health` and per-panel endpoints (see [03-api-ui.md](03-api-ui.md)) always read the **latest** `run_date` for a given subject, but historical verdicts remain in S3 for audit and for the sign-stability/regression checks that need to compare a study's outcome over time.

## Nothing reaches Signal/Dashboard before gates

This is the single hard rule that makes the rest of this policy enforceable rather than aspirational:

- **No table row, derived factor series, or computed value from any of the three alt-data layers is read by any Signal Engine, WFO, Dashboard, or Portefeuille code path**, regardless of how it scores on its gate, unless a verdict artifact with `promotable=true` exists for it.
- The **only** consumer of not-yet-gated (or permanently-failed) alt-data is the `/sentiment-events` research tab (see [03-api-ui.md](03-api-ui.md)), which is explicitly labeled as research-only and is not linked from the Signal or Dashboard navigation.
- A series that passes its gate does not automatically get wired into the production Signal Engine or WFO — passing the gate makes it **eligible**; actually wiring a promoted series into `FactorSignalSpec` (the `BAM_RATE_DIR` case in Plan B, `../macro-nowcast-layer/04-surprise-and-regimes.md`) or into a strategy variant is a separate, explicit follow-up change, reviewed on its own merits, not an automatic consequence of a verdict flipping to `true`.
- `pit_grade='upper_bound'` data is **permanently** excluded from promotion (see [01-pit-event-store.md](01-pit-event-store.md#3-pit_grade39upper_bound39-propagation)) — there is no future date at which historical upper-bound sentiment scores become promotion-eligible; only newly-collected `live` data can ever clear Gate 1.
