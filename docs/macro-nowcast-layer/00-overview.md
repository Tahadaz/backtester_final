# Overview and Research Question

## Station Mandate

**Nowcasting** = a continuously-updating estimate of a macro indicator (or of its
policy consequence) built from public data that arrives at higher frequency than
the indicator itself, so the estimate exists *before* the official print. This
layer builds two Morocco nowcasts (CPI inflation, BAM policy-rate direction) and
ingests three ready-made US nowcasts, then turns all of them into three
consumable outputs for the existing signal stack: a **surprise engine**, a
**BAM rate-direction factor signal**, and a set of **regime flags**.

This is Plan B of the three alternative-data layers. It shares its event store,
PIT join rule, and validation policy with Plan A (news sentiment) — see
[`../alt-data-foundation/00-overview.md`](../alt-data-foundation/00-overview.md).
It does not depend on Plan A or Plan C to ship; B1–B5 can run standalone.

---

## Why Nowcasts, Not Just Raw Series

The factor layer (`docs/factor-layer/`) already ingests raw macro *levels*
(VIX, Brent, EURUSD, US10Y, …) and reacts to their momentum/zscore/level. That
answers "is the level high or rising." It cannot answer "did the print
surprise anyone" — because a raw level has no expectation to be measured
against.

Professional macro desks solve this with consensus survey data (Bloomberg
ECFC, Reuters poll medians). Morocco has no such survey. **The fix is to build
the consensus ourselves**: a nowcast produced from information available
*before* the print is, by construction, the model's own expectation of that
print. The surprise engine then computes

```
surprise = actual − nowcast(as_of = release_date − 1 day)
```

standardized by the expanding standard deviation of past surprises. This is
the same logic equity/rates desks use around known-in-advance consensus
figures, adapted to a market where no consensus figure exists — the nowcast
*is* the consensus, self-generated and fully point-in-time.

---

## Build Morocco / Ingest US

Two symmetric-looking problems, two different decisions:

| | Morocco (HCP CPI, BAM rate) | US (CPI, GDP, activity) |
|---|---|---|
| Decision | **Build** | **Ingest** |
| Why | No public nowcast exists for Morocco; this is the genuinely new capability the layer exists to deliver. | The Cleveland Fed inflation nowcast, Atlanta Fed **GDPNow**, and NY Fed **Weekly Economic Index (WEI)** are already free, published, methodologically vetted daily/weekly downloads. Re-deriving them in-house would duplicate work with strictly worse quality than the source institutions' own models. |
| Effort | New feature engineering, two small models, an OOS harness, a release calendar. | A CSV/API client and a PIT-vintage table. No modeling. |

US nowcasts feed the layer as **inputs** (their surprises condition regime
flags such as `REGIME_GLOBAL_TIGHTENING`) — see
[`04-surprise-and-regimes.md`](04-surprise-and-regimes.md) — not as
Morocco-market signals in their own right.

---

## Three Outputs

1. **Surprise engine** (`04-surprise-and-regimes.md`) — event-dated
   standardized surprises for MA CPI and US CPI, usable directly in Plan C
   event studies and as conditioning inputs elsewhere.
2. **BAM rate-direction signal** (`03-rate-classifier.md`) — P(hike) − P(cut)
   per quarterly Bank Al-Maghrib decision, wired into the existing
   `FactorSignalSpec` registry with `channel_filter=("banks", "insurance",
   "real_estate")`. Banks are the single largest MASI sector by weight
   (materially double-digit, commonly cited near a third of the index;
   confirm the exact live weight against current index composition at
   implementation) and real estate is structurally rate-sensitive
   (financing cost of leverage, cap-rate discounting) — this is the layer's
   highest-value deliverable for the production signal stack.
3. **Regime flags** (`04-surprise-and-regimes.md`) — daily {0,1} derived
   factor series (`REGIME_MA_INFL_RISING`, `REGIME_GLOBAL_TIGHTENING`,
   `REGIME_MA_EASING`) that condition *existing* TA/factor variants through
   `conditions.py`/`conditioned_variants.py` with zero code changes, because
   a regime flag is just another factor series to that machinery.

---

## Honest Thin-Sample Framing

This layer forecasts genuinely rare events:

- **HCP CPI**: ~12 prints/year → ~120 prints over a decade. Enough for an
  expanding-window OOS harness, not enough for elaborate models.
- **BAM policy decisions**: quarterly meetings → ~4/year, ~40–48/decade, and
  most are "hold" (few informative hike/cut examples). Leave-one-out CV, not
  k-fold; profile-likelihood confidence intervals, not asymptotic normal
  approximations; climatology (base-rate) as the baseline to beat, not zero.

Every model in this layer therefore ships with an explicit numeric kill-switch
gate (`02-inflation-nowcast.md`, `03-rate-classifier.md`) and a documented
fallback that is *itself* useful (the AR benchmark still powers the surprise
engine even if the fancier model never clears its gate). "The nowcast adds
nothing beyond the naive benchmark" is a valid, publishable outcome here, not
a failed deliverable.

---

## Phase Map

| Phase | Deliverable | Doc |
|---|---|---|
| B1 | Input-series ingestion (Yahoo seeds + FRED/ALFRED + CSV sources) | [`01-data-sources.md`](01-data-sources.md) |
| B2 | Morocco release calendar + actuals (scrape-or-seed) | [`01-data-sources.md`](01-data-sources.md) |
| B3 | Morocco CPI nowcast + OOS harness + gate | [`02-inflation-nowcast.md`](02-inflation-nowcast.md) |
| B4 | BAM rate-direction classifier + gate | [`03-rate-classifier.md`](03-rate-classifier.md) |
| B5 | Surprise engine, regime flags, registry wiring | [`04-surprise-and-regimes.md`](04-surprise-and-regimes.md) |
| B6 | Validation gates (IC + WFO promotion) | [`05-validation-gates.md`](05-validation-gates.md) |

**Ordering**: `B1 ∥ B2 → B3 → B4 ∥ B5 → B6`. B1 and B2 have no dependency on
each other and can run in parallel. B3 needs both (features from B1, PIT
calendar from B2). B4 and B5 both depend only on B3 (the CPI nowcast feeds
BAM's inflation-gap feature and the surprise engine) and can run in parallel
with each other. B6 needs both B4 and B5's outputs to exist. Full
implementation-unit breakdown (files, reuse, tests, E2E) is in
[`06-phases.md`](06-phases.md).

---

## Cross-References

- Shared PIT event store, `macro_release`/`nowcast_value` schemas, S3 layout:
  [`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md)
- Validation gates, FDR policy, promotion criteria shared across all three
  layers: [`../alt-data-foundation/02-validation-policy.md`](../alt-data-foundation/02-validation-policy.md)
- Research-tab API/UI surface (nowcast-vs-actual panel, BAM probability
  speedometer): [`../alt-data-foundation/03-api-ui.md`](../alt-data-foundation/03-api-ui.md)

## What This Layer Does Not Do

- Does not build US macro models — Cleveland Fed / Atlanta Fed / NY Fed
  outputs are ingested, not re-derived.
- Does not touch Signal/Dashboard product pages until B6's gates pass; all
  intermediate outputs are research-only.
- Does not replace the existing factor layer's raw-level signals (VIX, Brent,
  DXY, …) — it adds a distinct *surprise* and *policy-direction* dimension on
  top of them.
- Does not assume BAM or HCP publish a machine-readable calendar or API —
  see [`01-data-sources.md`](01-data-sources.md) for the hand-seeded
  calendar fallback.
