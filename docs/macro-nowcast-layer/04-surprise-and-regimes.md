# Surprise Engine, Regime Flags, Registry Wiring (Phase B5)

Three deliverables, all thin transformations of B3/B4 outputs into shapes
the existing platform machinery already consumes.

---

## 1. Surprise Engine

New file: `core/quant_core/research/nowcast/surprise.py`.

On every `macro_release` row flipping to `status='released'`:

```
surprise_raw = actual_value − nowcast(series, as_of = release_date − 1 day)
surprise_z   = surprise_raw / expanding_std(past surprise_raw values for this series)
```

- The nowcast lookup is the latest `nowcast_value` row with `as_of_date`
  strictly before the release date — the model's genuine pre-print
  expectation, never a same-day or post-print value.
- Standardization uses the **expanding** std of that series' own past
  surprises (min ~8 observations before a z is emitted; earlier surprises
  are stored raw with `NaN` z). Expanding, not rolling — same
  thin-sample reasoning as B3's expanding-window harness.

**Two output shapes per underlying series:**

| Series | Shape | Consumer |
|---|---|---|
| `SURPR_MA_CPI`, `SURPR_US_CPI` | **Event-shaped**: values only on release dates, no fill between | Plan C event studies (`docs/event-backtest-layer/`), where a filled series would corrupt the event-window definition |
| `SURPR_MA_CPI_LAST`, `SURPR_US_CPI_LAST` | **Forward-filled daily**: last surprise carried forward until the next print | Conditioning/IC studies (`05-validation-gates.md`), where a daily-aligned series is required by `align_factor_to_target()` |

Both are exported via the derived-factor pattern (`macro_factor_meta` row
with `source_kind='derived'`, parquet under
`build_market_store_object_key(series_id, "1D")` with the surprise in the
`Close` column — the convention that makes existing factor readers work
unchanged; see
[`../alt-data-foundation/01-pit-event-store.md`](../alt-data-foundation/01-pit-event-store.md)).

---

## 2. Regime Flags

New file: `core/quant_core/research/nowcast/regimes.py`. Daily {0,1}
derived factor series:

| Flag | Definition |
|---|---|
| `REGIME_MA_INFL_RISING` | 3-month slope of `NOWCAST_MA_CPI` > 0 |
| `REGIME_GLOBAL_TIGHTENING` | Composite of ingested US inputs: e.g. Cleveland Fed nowcast rising AND last Fed decision ≥ hold (exact frozen definition at pre-registration) |
| `REGIME_MA_EASING` | `BAM_POLICY_RATE` P(hike)−P(cut) below a fixed negative threshold (cut-leaning), frozen at pre-registration |

**Zero changes needed in the consuming machinery — verified against the
actual code:**

- `core/quant_core/research/factors/conditions.py::evaluate_condition()`
  takes a `FactorConditionMeta` plus a plain 1-D float array of
  "factor closing prices (already lag-aligned)" and supports the `level`
  form (`_level_condition`, line 91): `factor_close vs threshold` with
  direction `above`/`below`, NaN → False. A {0,1} flag series consumed with
  `form="level", threshold=0.5, direction="above"` is exactly "regime flag
  is on" — no new condition form required.
- `core/quant_core/research/factors/conditioned_variants.py::compose_and_signal()`
  AND-gates any TA signal with any boolean mask from `evaluate_condition`,
  and `make_conditioned_variant()` wraps any `FactorConditionMeta` into a
  `{ta_family}@fx` variant. Neither function knows or cares that the
  underlying series is a nowcast-derived flag rather than VIX — the flag
  plugs in purely by existing as a factor series in `market_data_store`
  with a `macro_factor_meta` row.

The only wiring is data-level: seed `macro_factor_meta` rows for the flag
series (so `get_macro_series()` surfaces them) and — if the flags should be
channel-gated in Factor×TA candidate generation — add entries to
`services/worker/research/channel_tags.yaml`, which
`_build_channel_tag_gate()` in `services/worker/tasks/factor_x_ta_batch.py`
turns into the `{factor_ticker: [sectors]}` gate consumed by
`generate_factor_conditioned_candidates()`.

---

## 3. FactorSignalSpec Registry Wiring: `BAM_RATE_DIR`

`core/quant_core/research/factors/signals.py` defines the frozen dataclass
(verified, lines 120–128):

```python
@dataclass(frozen=True)
class FactorSignalSpec:
    factor_id: str           # canonical macro ID; matches MacroSeriesSpec.canonical_id
    signal_name: str         # unique key: "vix_zscore", "dxy_momentum", ...
    fn: Callable | None      # None for multi-factor signals (handled by dispatcher)
    default_params: dict     # frozen at pre-registration; must not be mutated
    channel_filter: tuple    # empty → all sectors; non-empty → sector must be in tuple
    citation: str
    requires: tuple          # factor_ids needed; defaults to (factor_id,)
```

**Proposed entry appended to `REGISTERED_FACTOR_SIGNALS`** (plus a new
signal function `bam_rate_dir_signal(series, hike_threshold, cut_threshold)`
in the same file mapping the daily P(hike)−P(cut) series to {−1, 0, +1}:
above `hike_threshold` → −1 for rate-sensitive longs, below `cut_threshold`
→ +1, else 0; thresholds frozen at pre-registration):

```python
FactorSignalSpec(
    factor_id="BAM_RATE_DIR",
    signal_name="bam_rate_direction",
    fn=bam_rate_dir_signal,
    default_params={"hike_threshold": 0.25, "cut_threshold": -0.25},  # frozen at pre-registration
    channel_filter=("banks", "insurance", "real_estate"),
    citation="policy-rate transmission channel (BAM→rate-sensitive sectors)",
    requires=("BAM_RATE_DIR",),
)
```

### channel_filter semantics — verified, with one implementation caveat

The proposed tuple `("banks", "insurance", "real_estate")` is **exactly the
tuple already used** on the existing `US10Y`/`us10y_shock` spec
(`signals.py` line 173) and matches the slug taxonomy in
`services/worker/research/channel_tags.yaml` (`sectors:` block: `banks:
"Banques"`, `insurance: "Assurances"`, `real_estate: "Immobilier"`, …). So
the channel names in the plan are consistent with the codebase's own
convention.

**Caveat the implementer must handle**: `is_applicable(spec, sector)`
(`signals.py` line 198) compares `sector.lower()` against the tuple — it
expects the *English slug* (`"banks"`), but the actual sector strings stored
in `stock_master.sector` are **French display labels** (`"Banques"`,
`"Assurances"`, `"Immobilier"` — see `services/api/app/masi_tickers.py` and
migration `f1e2d3c4b5a6_normalize_masi_sector_labels.py`), and
`_get_stock_sector()` in `services/worker/tasks/factor_x_ta_batch.py` merely
lowercases them (`"banques"` ≠ `"banks"`). The `channel_tags.yaml`
`sectors:` block documents the slug→French mapping but no code currently
applies it in the `is_applicable` path. Wherever the `BAM_RATE_DIR` spec is
evaluated per-stock, the caller must translate the French
`stock_master.sector` label to its slug via that `sectors:` mapping (or the
gate silently never matches — the same latent mismatch already affects the
`US10Y` and `BRENT` specs, whose gating in the Factor×TA path instead flows
through `channel_tags.yaml` tags + `_filter_conditions_by_channel()`, which
compares against the same slugs and has the same French-label caveat).
Recommended: a tiny `sector_slug(label: str) -> str` helper reading the
YAML `sectors:` mapping, added where the spec is consumed — flagged in
[`06-phases.md`](06-phases.md) as an explicit B5 work item.

Once the spec entry exists and `BAM_RATE_DIR` exists as a derived factor
series, the existing compute (`compute_factor_signal()`), relevance
(`compute_factor_relevance()`), and WFO machinery operate on it unchanged —
that is the entire point of routing the classifier's output through the
registry rather than building a bespoke pipeline.

## What This Phase Does Not Do

- Does not modify `conditions.py`, `conditioned_variants.py`, `alignment.py`,
  or any evaluator — the only code change outside `nowcast/` is the
  appended spec entry + signal function in `signals.py` (and the sector-slug
  helper if placed there).
- Does not promote `BAM_RATE_DIR` anywhere — registry presence makes it
  *testable* by B6, nothing more.
