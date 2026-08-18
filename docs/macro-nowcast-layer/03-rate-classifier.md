# BAM Rate-Direction Classifier (Phase B4)

## Target

Bank Al-Maghrib policy-rate direction per quarterly Conseil de la Banque
meeting: a probability triple **P(hike), P(hold), P(cut)** for each
scheduled meeting in `macro_release` (series `BAM_POLICY_RATE`,
calendar-seeded per [`01-data-sources.md`](01-data-sources.md) §4). The
persisted product signal is the scalar **P(hike) − P(cut)** written to
`nowcast_value` rows under `series_id='BAM_POLICY_RATE'` (with
`target_period` = the meeting quarter and `as_of_date` = the estimation
date), then exported as a derived daily factor series for the registry
wiring in [`04-surprise-and-regimes.md`](04-surprise-and-regimes.md).

---

## Features (per meeting)

New file: `core/quant_core/research/nowcast/rate_classifier.py`. Feature
rows follow the same PIT discipline as `features.py`
([`02-inflation-nowcast.md`](02-inflation-nowcast.md)): every input carries
`available_at`, assembly asserts `available_at ≤ as_of_date` where
`as_of_date` is strictly before the meeting date.

| Feature | Construction | Rationale |
|---|---|---|
| Inflation-nowcast gap | `NOWCAST_MA_CPI` (as of meeting − 1 day) minus BAM's implicit inflation target. BAM has no formal published point target; use ~2% as the implicit comfort level, treated as a fixed constant documented in the pre-registration — confirm the constant against BAM's published monetary-policy reports at implementation, do not fit it. | The single most policy-relevant input; central banks react to expected inflation vs target, and the B3 nowcast is exactly that expectation. |
| Last 2 Fed decisions | Direction of the two most recent FOMC rate decisions before the BAM meeting (from FRED policy-rate series, `01-data-sources.md` §2), encoded −1/0/+1 each. | Imported policy pressure through the USD leg of the peg. |
| Last 2 ECB decisions | Same encoding for the two most recent ECB Governing Council decisions. | EUR leg of the peg. |
| Fed/ECB weighting | Combined external-policy feature = **0.40 × Fed + 0.60 × ECB**, matching the MAD peg basket (~60% EUR / 40% USD — the same basket weights already documented on the `EURUSD` spec in `core/quant_core/macro.py`). | The peg mechanically transmits anchor-currency policy; weight by the basket, don't estimate the weights from ~48 observations. |
| Brent 3m trend | 3-month % change in Brent (MAD terms optional; confirm which the LOO harness prefers) as of meeting − 1 day. | Imported energy inflation pressure — the main exogenous shock channel for an oil-importing pegged economy. |
| Credit-growth proxy (optional) | If a scrapeable BAM monthly credit-aggregate series exists (probe at implementation; BAM publishes monetary statistics bulletins), 3m credit growth. **Model must work without it** — same optional-degrade posture as the fuel-price probe. | Domestic demand-pressure channel. |

Deliberately short list. With ~48 meetings and hold as the dominant class,
every additional feature costs more in variance than it can plausibly buy
in signal; the feature set is frozen at pre-registration (same integrity
rule as `docs/factor-layer/11-pre-registration.md`).

---

## Model: Ordered Logistic + Hand-Rule Fallback

Cut/hold/hike is an **ordered** outcome — the natural model is ordered
logistic regression via `statsmodels.miscmodels.ordinal_model.OrderedModel`
(statsmodels is already a platform dependency; the API worker previously
crash-looped on a statsmodels import issue that was fixed in the value-
strategy hardening work, so the dependency is known-present in the Docker
images — verify the version exposes `OrderedModel` at implementation).

**Explicit hand-rule fallback** (pure function in the same file,
`hand_rule_rate_direction(features) → (p_hike, p_hold, p_cut)`): a small,
documented decision table, e.g. — nowcast gap > +0.5pp **and** weighted
external-policy feature tightening → hike-leaning (deterministic
probabilities like 0.6/0.35/0.05); gap < −0.5pp and external easing →
cut-leaning; otherwise hold-heavy climatology-shaded probabilities. Exact
thresholds are frozen at pre-registration. The fallback exists for the same
reason the AR benchmark exists in B3: with ~48 observations the fitted
model can easily be *worse* than a transparent rule, and the gate below
decides which one gets published — `nowcast_value.model_version` records
`'ordered_logit'` or `'hand_rule'` accordingly.

---

## Validation: Leave-One-Out CV and Honest Uncertainty

With ~48 meetings:

- **Leave-one-out CV** (not k-fold): fit on 47 meetings, predict the held-
  out one, repeat for all meetings. LOO is the maximum-data-efficiency
  scheme and the only one that doesn't waste observations at this sample
  size; it also matches the one-meeting-ahead deployment reality.
- **Profile-likelihood confidence intervals** on the ordered-logit
  coefficients, not Wald/asymptotic-normal intervals — the asymptotics that
  justify Wald intervals are not credible at n≈48 with a dominant class.
- **Honest-uncertainty framing** in every artifact and UI surface: the
  published probabilities carry wide intervals, and the research tab must
  display them as such (see the BAM-probability panel spec in
  [`../alt-data-foundation/03-api-ui.md`](../alt-data-foundation/03-api-ui.md)).
  A P(hike)=0.55 from this model is a lean, not a call.

---

## Gate B4

**Published as `ordered_logit` only if both hold on LOO results:**

- **LOO log-loss < climatology baseline** — climatology = the uncondit­ional
  historical class frequencies (mostly hold). A model that can't beat "always
  predict the base rates" has learned nothing.
- **≥ 60% directional hit-rate on non-hold meetings** — on the subset of
  meetings where BAM actually moved, the model's argmax between hike and cut
  must be right at least 60% of the time. This prevents a degenerate model
  from passing the log-loss gate purely by predicting hold confidently and
  never committing on the meetings that matter.

**Else**: publish the hand rule (`model_version='hand_rule'`), which still
produces a usable P(hike)−P(cut) series for the registry wiring and keeps
the downstream signal machinery exercised. Re-evaluate at each new meeting
(one new observation per quarter — the gate can flip as evidence
accumulates, mirroring the B3 re-check discipline).

## What This Phase Does Not Do

- Does not estimate the peg basket weights, the implicit inflation target,
  or the hand-rule thresholds from data — all are fixed constants frozen at
  pre-registration.
- Does not model the *size* of rate moves, only direction.
- Does not promote the signal to any product page — that requires B6's full
  IC + WFO promotion path ([`05-validation-gates.md`](05-validation-gates.md)).
