# Edge Metrics + Intranet Deployment — Implementation Plan

> **Status:** Plan document, intended to be reviewed and implemented by Codex.
> On approval, copy this file to `docs/plans/edge-deploy-plan.md` in the repository so Codex picks it up alongside the source tree. The plan file in `~/.claude/plans/` is the working copy.

## 2026-05-07 Implementation Amendment - Horizon, Holdout, WFO Edge Contract

This amendment supersedes any older `short` / `medium` / `long` terminology in this plan. The live signal stack must use `weekly`, `monthly`, and `quarterly`.

| Horizon key | Prediction intent | Reference forward grid | Signal-engine terminal holdout | WFO train / OOS / step |
|---|---:|---:|---:|---:|
| `weekly` | 1-5 trading days | `[1, 3, 5]`, reference 5d | last 60 trading bars | 252 / 21 / 21 bars |
| `monthly` | 6-21 trading days | `[6, 10, 15, 21]`, reference 21d | last 180 trading bars | 504 / 63 / 63 bars |
| `quarterly` | 22-63 trading days | `[22, 42, 63]`, reference 63d | last 360 trading bars | 756 / 126 / 126 bars |

Old `short`, `medium`, and `long` rows are legacy diagnostics and must be recomputed under the new keys. Costs are 33 bps per side: one buy or sell leg costs 33 bps, and a direct flip costs 66 bps.

Signal Engine Edge is in-sample TA selection on pre-holdout data, then Edge is tested only on the untouched terminal holdout. WFO Edge uses the latest completed WFO OOS fold as primary Edge and recent completed OOS folds as diagnostics; it must not use the Signal Engine terminal holdout.

Every persisted WFO fold must include indices and dates: `train_start_idx`, `train_end_idx`, `oos_start_idx`, `oos_end_idx`, `train_start_date`, `train_end_date`, `oos_start_date`, `oos_end_date`.

Dashboard triage: actionable requires WFO A/B, source-appropriate Edge pass, and no severe local-neighborhood fragility; watch covers WFO C, weak-positive Edge, or mixed local sensitivity; hidden/diagnostic covers WFO D/F, negative Edge, or local-neighborhood fragility in most folds. The previous "catastrophic fold" gate is deprecated as a primary rule.

## 2026-05-07 Amendment B — Edge sampling and bootstrap discipline

Refines the Edge methodology in §3 and §4 in two areas: how the Edge sample is sourced for each `source ∈ {signal_engine, wfo}`, and what kind of bootstrap drives each statistic. Supersedes any conflicting language in the original §3.2, §4.1.b, §4.1.c-NEW, §4.2.a, and the prior 2026-05-07 amendment's "WFO Edge uses the latest completed WFO OOS fold as primary Edge" line.

### B.1 — WFO Edge sample = union of ALL completed OOS folds

Earlier text said WFO Edge uses "the latest completed WFO OOS fold." **Replace with: WFO Edge sample = the concatenation of every completed OOS fold** for that `(symbol, horizon, category, variant)`. Each fold contributes:
- its winner-parameter score series (which assigns the bucket label for OOS bars within that fold), and
- its forward returns over its OOS window.

Concatenated, the WFO sample is large by construction. Example: monthly WFO (`504/63/63`) over ~5 years of bars → ~12–14 folds × 63 OOS bars ≈ **750+ OOS observations** before recent-window capping.

The "latest completed OOS fold" is **not the sample** — it is a *diagnostic* surfaced in the drill-down panel as "ER / HR sur le dernier fold" alongside the cumulative number. Disagreement between the latest-fold value and the cumulative value is a regime-change signal (informative, not a gate).

Bucket assignment is strictly OOS: within each fold, the score that classifies a bar comes from the **winner-parameters of that fold**, evaluated on bars within that fold's OOS window. Never a globally-fitted score evaluated retroactively on past dates.

### B.2 — Signal Engine Edge sample = whatever the terminal holdout gives, badge `insufficient` on n < 30

For `source = "signal_engine"`: use the entire terminal holdout (60 / 180 / 360 bars per the §1 horizon contract) as the Edge sample. **No overlap-tricks, no inflation.** When n at the configured forward horizon falls below 30, badge fires `insufficient` (grey) and `proven_edge = False`. This is acceptable by design — SE ranks indicators in-sample; its Edge claim is structurally weak. Users wanting a strong Edge claim consult the WFO source.

Concretely in `build_edge_payload`:

```python
if source == "signal_engine":
    sample_returns = se_holdout_forward_returns(symbol, horizon)        # small: ~12–60 obs
elif source == "wfo":
    sample_returns = wfo_concatenated_oos_forward_returns(symbol, horizon)  # large: 100s of obs
if len(sample_returns) < 30:
    return EdgeMetrics(..., n=len(sample_returns), proven_edge=False, badge="insufficient")
```

The recent-window cap (§3.3, `n_target=60`, `max_lookback_years=3`) is applied **after** WFO concatenation, not per-fold — i.e., "last 60 OOS observations across the union of folds within the last 3 years."

### B.3 — Bootstrap audit (verified against the codebase)

| Statistic | Function | Bootstrap kind | Autocorrelation-aware? |
|---|---|---|---|
| Mean / ER CI in `bucketed_forward_returns` | `stationary_bootstrap_ci()` (`research/stats/robustness.py:108`) | Stationary block (Politis-Romano) | **Yes ✓** |
| Hit-rate CI | `wilson_ci()` (`research/stats/hit_rate.py:46`) | Analytical | N/A |
| **MC luck p-value** | `monte_carlo_luck_test()` (`significance.py:62`, line 97) | **IID centered-return** | **No ✗** |
| Backtest MC paths | `stationary_block_bootstrap()` (`risk.py:97`) | Stationary block | Yes ✓ |

The ER CI is already block-aware. **The MC luck test that drives the Edge `mc` gate is IID** and inflates significance under overlapping forward returns. Required fix in Workstream A.2:

- Add a `block_mean: int | None = None` parameter to `monte_carlo_luck_test`. When set, draw blocks from the centered series via the same Politis-Romano scheme used in `risk.py::stationary_block_bootstrap`. Default `None` preserves existing IID behavior for non-overlapping callers.
- **Rule for Edge use:** call with `block_mean = max(2, horizon)` when the forward-return horizon > 1; `block_mean = None` when horizon = 1.
- Same fix applies to `monte_carlo_label_shuffle_test` (the new test in §4.1.c-NEW): when shuffling within an autocorrelated series, the shuffle preserves block structure (shuffle of contiguous blocks of length ≈ horizon, not single bars).

### B.4 — Sections that change as a result of this amendment

When reading §3 / §4 below, treat these spots as overridden:
- §3.2 (OOS-only forward-return statistics) — for `source="wfo"`, sample is "union of fold OOS windows," not "single fold."
- §3.3 (Recent-window sample policy) — applies to the *concatenated* WFO sample, capped at last 60 obs / 3 years.
- §3.7 (Four gates) — `mc` gate's MC luck test must run with `block_mean = max(2, horizon)` for horizon > 1.
- §4.1.b (`oos_sample_for`) — for `source="wfo"`, returns fold-scoped OOS observations that preserve fold id, winner variant, and OOS date range; the Edge consumer concatenates those observations, not just a naked date set.
- §4.1.c-NEW (`monte_carlo_label_shuffle_test`) — block-aware shuffle when horizon > 1.
- §4.2.a (`build_edge_payload`) — branches on source per B.2; calls block-aware MC tests per B.3.

## 2026-05-07 Amendment C — Definitional fixes (parameter neighborhood, gates, triage)

Closes ambiguities in the prior amendments. Pins the numerical thresholds Codex needs to implement triage rules, parameter-neighborhood robustness, and gate semantics. Where this amendment contradicts earlier text it supersedes it.

### C.1 — Local parameter neighborhood = ±10% rounded up; 95% CI on OOS metric

For each WFO fold's winner parameter `p*`, the local neighborhood `N(p*)` is the set of grid points `p` satisfying

```
|p − p*| <= ceil(0.10 * p*)
```

Examples: `p* = 14` → `|p − 14| ≤ 2` → `N = {12, 13, 14, 15, 16}` (intersected with the actual discrete grid). `p* = 50` → `N = {45..55}`. For multi-dimensional parameters (MACD `(fast, slow, signal)`, Ichimoku `(9, 26, 52)`, etc.), compute the neighborhood independently per dimension; the joint neighborhood is the Cartesian intersection with the actual grid. **Cap at 25 neighbors max** — if the joint neighborhood would exceed 25, sample 25 deterministically by L1 distance from `p*` (ties broken lexicographically; seeded for reproducibility).

For each `p ∈ N(p*)`, evaluate the OOS metric on the **same** fold's OOS window. The metric is the **OOS edge ratio** (`mean / std` of forward returns at horizon `h`, no annualization) — chosen over OOS Sharpe because it stays meaningful at small samples.

Compute a **95% percentile bootstrap CI** over `{metric(p) : p ∈ N(p*)}` using an ordinary deterministic percentile bootstrap over the scalar neighbor metrics. Do **not** use a stationary/block bootstrap here: neighbor metrics are a small cross-section of parameter variants, not an autocorrelated time series.

Fragility class **per fold**:

| Class | Rule on the neighborhood 95% CI of OOS edge ratio |
|---|---|
| `stable` | CI fully on the same sign as `metric(p*)` AND `metric(p*) ∈ [CI_lo, CI_hi]` |
| `mixed`  | CI straddles 0, OR `metric(p*)` lies outside `[CI_lo, CI_hi]` (winner is an outlier in its own neighborhood — classic overfit signal) |
| `severe` | 95% CI fully on the *opposite* sign of `metric(p*)`, OR `> 50%` of `N(p*)` produces `metric(p) < 0` |

Aggregation **across folds** for the dashboard's "local-neighborhood fragility" badge:

| Aggregate label | Rule |
|---|---|
| no severe fragility | `< 30%` of folds classified as `severe` |
| mixed local sensitivity | `30% ≤ severe + mixed share < 60%` |
| fragility in most folds | `≥ 60%` of folds classified as `severe` OR `mixed` |

These thresholds are explicit and testable.

### C.2 — All confidence intervals at 95%, alpha pinned at every call site

Every Edge-stack CI uses **α = 0.05 → 95% CI** — mean ER (`stationary_bootstrap_ci`), hit rate (`wilson_ci`), neighborhood fragility (C.1), MC luck-null quantiles where displayed in the drill-down, label-shuffle null. **Pass `alpha=0.05` explicitly at every call site** (no relying on defaults), so a future ripgrep for `alpha=` produces a complete audit trail.

### C.3 — Triage state ↔ Edge gate definitions, pinned

The prior triage amendment used "weak-positive Edge" and "negative Edge" without thresholds. Pinned:

| State | Definition |
|---|---|
| `proven` | All 4 gates pass: `mc` (block-aware `p < 0.01`) AND `wilson` (`hit_ci_lower > 0.50`) AND `bh` (direction-correct ER beats B&H) AND `n` (`n ≥ 30`). |
| `weak-positive` | `n` AND `bh` pass, AND **at least one** of `{mc, wilson}` passes, but NOT all four. |
| `neutral` | `n` passes; neither `bh` nor `wilson` passes. |
| `negative` | `n` passes AND `bh` fails AND `wilson` lower bound below 0.50 (signal underperforms B&H and is no better than coinflip). |
| `insufficient` | `n < 30`. Grey badge regardless of other gate values. |

The drill-down panel always shows the per-gate truth table; the dashboard tile surfaces only the 5-state label.

### C.4 — Recent-folds diagnostic = last 3 completed OOS folds (fixed count, not time window)

"Recent completed OOS folds as diagnostics" → **the last 3 completed OOS folds** by `oos_end_date`. Fixed count, not a time window. For monthly WFO (`63/63`), 3 folds ≈ 9 months — enough for a regime-stability read without overweighting old structure. The drill-down panel renders these 3 folds as a small bar chart (one bar per fold's OOS edge ratio, with 95% CI whiskers per fold).

If fewer than 3 completed folds exist (early WFO), render the available folds and label `"régime trop court pour diagnostic"`. Do not extrapolate.

### C.5 — Direction-corrected gates (consolidates a subtlety in the existing code)

Per the existing `bucketed_forward_returns` code (`score_history.py:312–316`), hit rate is **already direction-aware**: `hits = sum(r > 0)` for buy buckets, `sum(r < 0)` for sell buckets. The Edge `wilson` gate therefore uses `hit_ci_lower > 0.50` for **both** long and short directions — no sign flip required at the gate level. The earlier §3.7 wording mentioning `hit_ci_upper < 0.50` for short buckets was incorrect against the existing code; ignore it.

The `bh` gate compares ER to B&H in the bucket-direction sense:
- Long buckets (`buy`, `strong_buy`): pass iff `expected_return > bh_expected_return`.
- Short buckets (`sell`, `strong_sell`): pass iff `expected_return < bh_expected_return` (the short signal must be more negative than the unconditional drift; a short that returns 0 while B&H returns +1% is a fail).
- `hold`: gate is N/A; bucket renders "Pas de signal aujourd'hui" with no Edge tile.

## 2026-05-07 Amendment D — Drop the buy-and-hold gate

The `bh` gate (compare `expected_return` to a passive buy-and-hold benchmark) is **removed** from the Edge methodology. Rationale: the strategy is signal-gated and per-trade; B&H is unconditional and frictionless. Making the comparison fair requires asymmetric cost adjustment that adds methodological surface without buying real rigor. The remaining three gates already make the honest claim.

### D.1 — Three-gate `proven_edge`

```
proven_edge := mc & wilson & n
```

| Gate | Pass condition |
|---|---|
| `mc` | block-aware Monte Carlo luck `p < 0.01` (block_mean = max(2, horizon) for horizon > 1) |
| `wilson` | hit-rate Wilson 95% lower bound > 0.50 (direction-aware via the existing bucket-direction code) |
| `n` | `n >= 30` |

### D.2 — Updated `EdgeMetrics` shape

- Remove field `bh_expected_return`.
- `EdgeGates` drops the `bh: bool` field; now has only `mc`, `wilson`, `n`.
- Everything else (`expected_return`, `hit_rate`, `hit_ci_lower`, `hit_ci_upper`, `expectancy` decomposition, `edge_ratio`, `profit_factor`, `mc_luck_pvalue`, `label_shuffle_pvalue`, `n`, `window_*`, `methodology_version`) unchanged.

### D.3 — Triage state machine, repinned (supersedes §C.3)

| State | Definition |
|---|---|
| `proven` | n passes AND mc passes AND wilson passes (Wilson LB > 0.50). |
| `weak-positive` | n passes AND **exactly one** of `{mc, wilson}` passes. |
| `neutral` | n passes; neither mc nor wilson passes; Wilson **upper** bound ≥ 0.50 (signal isn't statistically demonstrable as wrong-directional). |
| `negative` | n passes; Wilson **upper** bound < 0.50 (statistically wrong-directional with 95% confidence). |
| `insufficient` | n < 30. Grey badge regardless of other gate values. |

### D.4 — Dashboard / drill-down changes

- 4-gate checklist becomes a **3-gate checklist** (drop the "Bat le buy-and-hold" row).
- 33 bps/side cost is still surfaced in the drill-down as **informational** (next to ER and the expectancy decomposition), not as a gate input.
- "Méthodologie / limites" accordion: remove any cost-adjustment caveat tied to B&H. Keep the multi-testing, MC-null-shape, and recent-regime caveats.
- Triage filter "Edge prouvé seulement" semantics unchanged — it shows rows where `proven_edge=True`.

### D.5 — Plan sections this supersedes

- §3.7 (Four gates → **three** gates): drop the `bh` row; `proven_edge` is now a 3-AND.
- §4.2.a (`EdgeMetrics` / `EdgeGates`): remove `bh_expected_return` and `bh: bool` fields.
- §4.2.b endpoint response: `EdgeMetricsOut` mirrors the dataclass change.
- §4.2.d tests: drop `test_proven_edge_fails_when_er_below_bh`. Add `test_negative_state_when_wilson_upper_below_half`.
- §3.8 honest-framing copy: drop the "beats buy-and-hold" sentence; the demo-talking-point is now "the signal's magnitude is non-zero AND its direction is reliable AND we have enough data."
- §C.3 (Triage state ↔ Edge gate definitions): superseded by §D.3 above.
- §C.5 (direction-corrected gates): drop the second paragraph ("The `bh` gate compares ER to B&H..."); keep the hit-rate-direction-awareness paragraph.

### D.6 — `bh_expected_return` is no longer computed

`build_edge_payload` no longer calls `_calculate_forward_returns(prices, h)` over the unconditional OOS sample. Saves a small amount of compute per call, simplifies cache key, and removes one source of stale-cache bugs.

## 2026-05-07 Amendment E — Cost-aware Edge metrics (gross/net toggle)

Costs were dropped from the `bh` gate (Amendment D), but the user wants ER and dependent metrics to be **viewable both gross and net of cost**, with a UI toggle. This amendment defines the contract.

### E.1 — Strategy-perspective return convention (read carefully)

Per-trade return from the strategy's perspective, with direction baked in:

```python
# r is the raw forward return at horizon h from _calculate_forward_returns()
# direction ∈ {long, short, none} from direction_for_bucket(bucket)
# c = DEFAULT_COST_BPS_PER_SIDE * 1e-4 = 0.0033 (per side; round-trip = 2c = 66 bps)
def strategy_return(r: float, direction: str, c: float, include_costs: bool) -> float:
    sign = +1 if direction == "long" else (-1 if direction == "short" else 0)
    if sign == 0:                  # hold bucket: no trade
        return 0.0
    gross = sign * r               # positive = good, regardless of direction
    return gross - 2*c if include_costs else gross
```

Every cost-sensitive metric below is computed from this `strategy_return` view; the user-facing sign convention is unambiguous (positive = made money).

### E.2 — `EdgeMetrics` shape, gross/net pairs

Cost-sensitive fields gain `_gross` / `_net` variants. Cost-invariant fields stay singular.

| Field | Gross | Net | Notes |
|---|---|---|---|
| `expected_return` | `expected_return_gross` | `expected_return_net` | mean of `strategy_return(r, dir, c, include_costs)` |
| `expectancy` | `expectancy_gross: ExpectancyDecomp` | `expectancy_net: ExpectancyDecomp` | `p_win` is cost-invariant; `avg_win` and `avg_loss` differ; expectancy field within the decomp recomputes |
| `edge_ratio` | `edge_ratio_gross` | `edge_ratio_net` | std is cost-invariant (flat per-trade shift); `edge_ratio_net = (mean − 2c) / std` |
| `profit_factor` | `profit_factor_gross` | `profit_factor_net` | recomputed: each per-trade return is shifted before bucketing into wins / losses |
| `mc_luck_pvalue` | `mc_luck_pvalue_gross` | `mc_luck_pvalue_net` | both run with the same `block_mean` (B.3); the centered-bootstrap operates on the cost-shifted series for `_net` |
| `label_shuffle_pvalue` | `label_shuffle_pvalue_gross` | `label_shuffle_pvalue_net` | same |
| `hit_rate`, `hit_ci_lower`, `hit_ci_upper` | single value (cost-invariant) | — | cost is flat per trade, doesn't change which trades won |
| `n`, `window_*`, `bucket`, `direction`, `methodology_version` | single value | — | structural |
| **NEW** `cost_bps_per_side: float` | — | — | the value used to compute the `_net` columns; default 33; allows the frontend to display "net of 33 bps" precisely |

### E.3 — `EdgeGates` and `proven_edge`, gross/net pairs

```python
@dataclass(frozen=True)
class EdgeGates:
    mc_gross:  bool   # mc_luck_pvalue_gross < 0.01
    mc_net:    bool   # mc_luck_pvalue_net   < 0.01
    wilson:    bool   # cost-invariant
    n:         bool   # cost-invariant

@dataclass(frozen=True)
class EdgeMetrics:
    ...
    proven_edge_gross: bool   # mc_gross & wilson & n
    proven_edge_net:   bool   # mc_net   & wilson & n
```

A signal can be `proven` gross but not net (cost is the killer) — that's exactly the failure mode we want surfaced.

### E.4 — Triage state machine driven by the *displayed* mode

The dashboard has a global toggle: **`[Coûts inclus]`** (default) / **`[Coûts exclus]`**. The triage state (`proven` / `weak-positive` / `neutral` / `negative` / `insufficient` per §D.3) is computed against `proven_edge_net` when the toggle is on `Coûts inclus`, and against `proven_edge_gross` when on `Coûts exclus`. **Default = `Coûts inclus` (net)** — the more honest stance.

`weak-positive` redefined under the toggle:
- Net mode: `n` passes AND exactly one of `{mc_net, wilson}` passes.
- Gross mode: `n` passes AND exactly one of `{mc_gross, wilson}` passes.

`negative` is unchanged — Wilson upper bound < 0.50, cost-invariant.

### E.5 — Drill-down panel changes

The drill-down shows **both** gross and net values side-by-side, regardless of the toggle, so the supervisor can see the cost impact directly:

```
┌──────────────────────────────────────────────────────────┐
│  ER       gross +1.84%      net +1.18%   (cost −0.66%)   │
│  Edge     gross  0.42       net  0.27                    │
│  PF       gross  1.62       net  1.38                    │
│  MC p     gross  0.004      net  0.018  (block-aware)    │
│  Hit      64%   [IC 95% : 56% – 72%]   (sans coûts)      │
└──────────────────────────────────────────────────────────┘
```

The 3-gate checklist visualizes the gates **for the currently-selected mode** (gross or net) with pass/fail icons. The "Méthodologie / limites" accordion gains a one-line note: *"Coûts par aller : 33 bps (configurable). En mode net, les coûts d'aller-retour (66 bps) sont déduits de chaque trade avant calcul d'ER, expectance, ratio d'edge, profit factor et p-valeur MC. Le hit rate ne dépend pas des coûts."*

### E.6 — Feature flag and persistence

- Toggle state persisted in the user's frontend preference (localStorage `bt.edge.includeCosts: true|false`, default `true`).
- Backend env var `EDGE_COST_BPS_PER_SIDE` (default 33) overrides the cost used for `_net` computations. Cache key includes this value so changing it invalidates stale caches.
- `cost_bps_per_side` is also a query param on `/analytics/edge?cost_bps=33` — defaults to env, allows ad-hoc what-if analysis without server restart.

### E.7 — Test additions

- `test_strategy_return_long_subtracts_round_trip_cost`
- `test_strategy_return_short_subtracts_round_trip_cost_after_sign_flip`
- `test_hold_bucket_strategy_return_is_zero`
- `test_edge_ratio_net_equals_gross_minus_cost_over_std`
- `test_profit_factor_net_lower_than_gross_when_costs_nonzero`
- `test_proven_edge_gross_true_net_false_when_cost_kills_mc`
- `test_proven_edge_invariant_to_cost_when_cost_is_zero`
- `test_endpoint_cost_bps_query_param_overrides_env_default`

### E.8 — Plan sections this supersedes

- §3.4 (canonical expectancy) — applies to both gross and net (`avg_win`, `avg_loss`, `expectancy` recomputed with cost-shifted returns for `_net`); `p_win` is single-valued.
- §3.5 (profit factor) — extended to net via cost-shifted per-trade returns.
- §3.6 (edge ratio) — extended to net via `(mean − 2c) / std`.
- §4.2.a `EdgeMetrics` and `EdgeGates` — replace single-valued cost-sensitive fields with `_gross`/`_net` pairs per E.2 and E.3.
- §4.2.d test list — augmented with E.7.
- §C.3 / §D.3 (triage state machine) — extended with the toggle-driven semantics in E.4.

### C.6 — Other ambiguities tagged for Codex to flag, not yet decided

Codex must raise each of these as a clarifying question to the user **before** implementing the affected sub-phase:

1. **Cost calibration.** 33 bps/side is the locked contract per the §1 amendment. Codex should verify against actual MASI fill data once a sample is available. If average all-in cost (commission + spread + impact) exceeds 50 bps/side on liquid MASI mid-caps, the contract must be revisited — many marginal-edge symbols would flip from `proven` to `negative` purely on cost. Not a v1 blocker; flag for v2.
2. **Recompute migration.** Switching `short/medium/long` → `weekly/monthly/quarterly` invalidates `signal_engine_global_result`, `signal_engine_family_result`, `wfo_signal_summary`, `wfo_global_signal`, and `signal_score_history`. Codex must propose a staged backfill (one horizon per night, one variant at a time) and define rollback (snapshot the legacy-horizon rows to `*_legacy_horizons` tables before deleting). Live-dashboard behaviour during migration: serve only horizons whose backfill is complete; horizons in progress show "recompute en cours."
3. **`methodology_version` format.** Proposal: `"YYYY-MM-DD"` of the latest amendment-rule edit, compared lexicographically; bumps invalidate every Edge cache. Confirm before implementing the cache key.
4. **Auth.js signup approval UX.** `users.is_active = false` default + admin approval. v1: a SQL-only "approve user" runbook in `docs/ops/auth.md` (no UI); admin page is post-demo work.
5. **"Edge prouvé seulement" filter ↔ `bucket = hold` interaction.** Proposal: when the filter is on, rows with `bucket = hold` are hidden entirely (consistent with "show me only actionable opportunities"). Confirm.
6. **WFO fold-metadata backfill shape.** `wfo_signal_summary.folds_json` is JSONB, so the required fold metadata (`train_start_idx`, `train_end_idx`, `oos_start_idx`, `oos_end_idx`, `train_start_date`, `train_end_date`, `oos_start_date`, `oos_end_date`) does **not** require an Alembic migration unless the team deliberately chooses physical columns. The required v1 work is a defensive parser plus staged recompute/backfill of JSON fold payloads before any Edge code relies on those fields.

## 0. Audience and tone for this document

This is a *contract* with Codex. Every section is written so that an implementing agent can act without re-deriving intent. Treat ambiguity as a bug — when something here is unclear, flag it before implementing.

The plan covers two largely independent workstreams:
- **Workstream A — Edge metrics and methodology hardening** (backend-heavy; the supervisor demo content)
- **Workstream B — Intranet deployment** (infra; ships the demo on company wifi)

Workstream A can be developed locally without B. B unblocks the supervisor handoff.

---

## 1. Architectural decisions — locked

| Concern | Decision | Reason |
|---|---|---|
| **Hosting** | All services (frontend + API + worker + Postgres + Redis + MinIO + Caddy) deploy on a **single Oracle Cloud Always-Free Ampere A1 VM** (4 OCPU, 24 GB RAM, ARM64) via docker-compose | VM already provisioned; user wants single-vendor, single-cost-center, intranet-only |
| **Frontend hosting** | **Inside the same docker-compose**, served by Caddy. Drop Vercel. | Vercel is public-by-default; user requires the app to be reachable only from the company network |
| **Auth** | **Auth.js v5** (NextAuth) with the existing Postgres as the user store via Drizzle adapter. Drop Supabase. | Self-host everything; no external auth dependency |
| **Auth provider** | Credentials provider (email + bcrypt password) for v1; magic-link via SMTP if a relay is available | Intranet, small user list, no social logins needed |
| **Backend ↔ frontend trust** | Auth.js issues HS256 JWT signed with `NEXTAUTH_SECRET`; FastAPI verifies the same secret on every request | Stateless, no shared session table to keep in sync |
| **Network access control** | Caddy IP-allowlist on the company's egress NAT IP(s) + a wireguard "break-glass" path for the maintainer | Oracle Cloud has a public IP; without an allowlist the app is internet-reachable, which contradicts the intranet requirement |
| **CI/CD** | GitHub Actions → multi-arch buildx → GHCR → SSH `docker compose pull && up -d` to the Oracle VM | Free, simple, already common in the codebase's neighbourhood |
| **Account model** | Per-user ownership + `visibility ∈ {private, public}` toggle on user-scoped tables | Future-proofs sharing; private by default |
| **Deferred non-goals** | k8s, partitioning, SSO, audit log, multi-region HA, broker integration, multiple-hypothesis correction, regime-windowed Edge | Documented limitations; explicitly out of scope |

### 1.1 The "company wifi only" requirement — non-trivial

Oracle Cloud gives you a **public IP**. "Only on company wifi" means we have to add an explicit gate. Three viable patterns; pick one and implement it as part of Workstream B before exposing the demo:

| Option | How it works | Cost | Effort |
|---|---|---|---|
| **A. Caddy IP allowlist** *(recommended for v1)* | Caddy `@office { remote_ip <CIDR> }` matcher rejects everything outside the company's egress IP block. | Free | 30 min |
| **B. Tailscale / WireGuard** | VM joins a Tailnet; only Tailnet members reach it. | Tailscale free for ≤100 devices | 1–2 h |
| **C. Real on-prem** | Move the VM into the company network (not Oracle). | Hardware/VLAN | days |

**Decision required from user:** which option, and what is the company's egress IP / CIDR? Codex must NOT proceed with Workstream B Phase B.4 (DNS + TLS) without this answer.

---

## 2. Existing code — what to reuse, what to fix

Codex must read these files end-to-end before implementing. File:line pointers and findings:

### 2.1 `core/quant_core/research/score_history.py`

| Function | Line | Status |
|---|---|---|
| `_bucket_for(score)` | 42 | **Reuse as-is.** Fixed thresholds (`+50/+15/-15/-50`). No look-ahead risk from bucket boundary computation. |
| `_calculate_forward_returns(prices, h, method)` | 205 | **Reuse as-is.** Implements `close_to_close`, `open_to_open`, `close_to_open`, `open_to_close` with correct shifts. |
| `bucketed_forward_returns(score_series, prices, fwd_horizons, …)` | 253 | **REQUIRES MODIFICATION (W A.1).** Today it computes statistics over the entire `aligned_idx` (line 286–293). Has no parameter to constrain to OOS dates. Fix detailed in §4.1.b. |

`BUCKET_NAMES = ("strong_sell", "sell", "hold", "buy", "strong_buy")` (line 38).

### 2.2 `core/quant_core/significance.py`

| Function | Line | Status |
|---|---|---|
| `monte_carlo_luck_test(returns, metric, n_iter, seed, periods_per_year)` | 62 | **Reuse, but the null is "centered-return bootstrap" (line 92).** It tests whether the observed Sharpe / total-return is unlikely under H0: "underlying distribution has zero mean." It is **not** a bucket-informativeness test. Two implications: (1) it's still a useful gate (rejects buckets whose returns are noise around zero); (2) it does NOT prove the bucket carries more information than another bucket. Document this honestly. See §4.1.c for an additional label-shuffle test we will add. |
| `evaluate_significance(returns_by_key, …)` | 125 | Reuse-able if we want per-bucket significance in one call. |

### 2.3 `core/quant_core/research/stats/hit_rate.py`

| Function | Line | Status |
|---|---|---|
| `wilson_ci(k, n, alpha)` | 46 | **Reuse as-is.** Returns `(lower, upper)` for a binomial proportion. |

### 2.4 Persistence — where OOS lives

| Table | Model file | OOS information |
|---|---|---|
| `wfo_signal_summary` | `services/api/app/models.py:672` | `folds_json` (line 687) contains per-fold IS/OOS returns + window dates. Must be parsed to reconstruct OOS date ranges per (symbol, category, horizon, variant). |
| `wfo_global_signal` | `services/api/app/models.py:716` | Top-level consensus only — no fold-level OOS data. |
| `signal_engine_family_result` | `services/api/app/models.py:769` | `family_detail_json` (line 795) — verbatim `_build_family_snapshot()` output. Codex must read `_build_family_snapshot()` to determine whether OOS dates are present and in what shape. **If absent**, we must extend it; spec in §4.1.b.iii. |
| `signal_engine_global_result` | `services/api/app/models.py:823` | Aggregate — no fold-level OOS. |
| `signal_score_history` | per project memory: per-bar score history (date/symbol/source/category/horizon composite PK) | Source of truth for the score series fed into `bucketed_forward_returns`. Codex must check whether each row carries an `is_oos` flag; **if not**, Workstream A.1 includes adding it via alembic. |

### 2.5 Indicator parameter registry

Codex must read `core/quant_core/signal_engine/domain.py` (and `family_registry.py` if it exists) to find the indicator-parameter search space. The horizon-aware parameter cap (§4.1.d) must be applied at search-space construction time, not at evaluation time, so that capped searches never visit slow parameters and don't pollute the cached results.

### 2.6 Frontend dashboard

`frontend/app/v1/page.tsx` (385 lines today) is the page to restructure. The leaderboard payload that feeds it: per project memory, `services/api/app/routers/runs.py::list_strategy_leaderboard` is the prime suspect — Codex must verify and report the actual endpoint before §4.4.

---

## 3. Methodology specification — non-negotiable contract

Every Edge value displayed on the dashboard must satisfy these properties. Violations are bugs, not stylistic differences.

### 3.1 The bucket is the day's actual signal — never anything else

For each opportunity row at horizon h on the dashboard:

```
bucket(symbol, h) := bucket_label_from(latest_score(symbol, h, source))
```

There is **no `pick_best_bucket` function**, no "best-historical-bucket" override, no UI affordance to pick a different bucket in v1. The day's signal *is* the bucket. This solves the selection-bias problem cleanly because we are not choosing the bucket; the signal chooses it for us.

### 3.2 OOS-only forward-return statistics

All Edge statistics for a `(symbol, horizon, source)` cell must be computed using **only** the source-appropriate OOS sample defined by `oos_sample_for(symbol, horizon, source)`:

- **For `source = "wfo"`:** the concatenation of completed fold OOS observations, where each observation's score/bucket comes from that fold's winner parameters. Keep fold identity and winner metadata for diagnostics.
- **For `source = "signal_engine"`:** the terminal holdout sample for the active horizon: 60 / 180 / 360 bars for weekly / monthly / quarterly. The holdout is not used for parameter selection.

No buy-and-hold benchmark is computed or used as a gate.

### 3.3 Recent-window sample policy

For the bucket-cell statistics, take the **most recent N OOS observations** of the same bucket label, with:
- `N_target = 60`, `N_min = 30`
- Bounded by `max_lookback_years = 3` regardless of N
- If `n < 30`, badge fires **`insufficient`** (grey), not `proven_edge`

The window must be defined symmetrically across all symbols and horizons displayed in a single dashboard render — i.e., the window endpoint for every cell is the latest OOS date of the (symbol, horizon, source) up to *today*, not "today" globally. This avoids cross-symbol date mismatches when symbols have different data availability.

### 3.4 Canonical expectancy decomposition

For a bucket with OOS forward returns `r_1 … r_n` and `direction ∈ {long, short}`:

```
wins   = { r_i :  sgn(r_i) == sgn_for(direction) }   # long: r_i > 0; short: r_i < 0
losses = { r_i :  sgn(r_i) != sgn_for(direction) }   # zero treated as loss
P_win  = |wins|   / n
P_loss = |losses| / n
avg_win  = mean(wins)   if wins   else 0
avg_loss = mean(losses) if losses else 0   # negative number for long, positive for short
expectancy_canonical = P_win * avg_win - P_loss * avg_loss   # for short, sign-flip the whole thing so positive = good
expectancy_arith = mean(r_i)
# Invariant: expectancy_canonical == expectancy_arith (within 1e-9). Both are surfaced to satisfy quant audiences.
```

For `strong_buy` and `buy` buckets: `direction = long`. For `strong_sell` and `sell`: `direction = short`. For `hold`: skip — Edge tile renders nothing for `hold` buckets (the symbol is not actionable today).

### 3.5 Profit factor

```
pos_sum = sum(r_i for r_i in r if r_i > 0)
neg_sum = sum(-r_i for r_i in r if r_i < 0)
profit_factor = pos_sum / neg_sum  if neg_sum > 0 else None  # None means "all wins; cannot compute"
```

Frontend renders `None` as `—` with tooltip "Pas de pertes dans l'échantillon." It is not the same as 0 or ∞; do not coerce.

### 3.6 Edge ratio

```
edge_ratio = mean(r) / std(r, ddof=1)   if n > 1 and std > 0 else None
```

This is a per-trade signal-to-noise ratio. The display label is **"Ratio d'edge"**, not "Sharpe." The tooltip explains the formula and explicitly disclaims the Sharpe analogy.

### 3.7 The three gates — definition of "Proven Edge"

`proven_edge_net := mc_net & wilson & n`; `proven_edge_gross := mc_gross & wilson & n`. Dashboard default is net (`Coûts inclus`).

| Gate | Pass condition | Threshold rationale |
|---|---|---|
| `mc_gross` / `mc_net` | block-aware `mc_luck_pvalue_* < 0.01` | Stricter than 0.05; partial mitigation for deferred multiple-testing correction |
| `wilson` | `hit_ci_lower > 0.50`; hit definition is already direction-aware | Wilson lower bound clears the random-direction baseline |
| `n` | `n >= 30` | Floor for the Wilson CI to be meaningful |

The drill-down panel shows pass/fail per gate with the actual value vs threshold for each. **No gate has a UI affordance to override.**

### 3.8 Honest framing — for the demo

The drill-down's "Methodology" section must include these three caveats verbatim (Codex implements as a static accordion at the bottom of the panel):

> **Limites assumées.** (1) Pas de correction multi-hypothèses sur les p-valeurs : avec ~76 symboles × 3 horizons × 2 sources, on attend ~5% de faux positifs au seuil p < 0.05 ; le seuil est durci à p < 0.01 pour partiellement compenser. (2) Le test de Monte Carlo employé (`bootstrap_centered_returns`) teste si la moyenne des retours est non nulle, pas si l'étiquette de bucket est informative. Un test complémentaire de permutation des étiquettes est calculé séparément (voir §4.1.c) et exposé dans la même panneau. (3) Toutes les statistiques sont calculées sur la fenêtre des 30–60 dernières observations OOS (≤ 3 ans) — pertinentes pour le régime actuel, peu fiables hors régime.

---

## 4. Workstream A — Edge metrics & methodology hardening

Estimated total: **3.5–5 working days**, sequenced as follows. Sub-phases A.1 and A.2 must complete before A.3; A.3 and A.4 can overlap.

### 4.1 — Phase A.1 · OOS-aware foundation (1.5–2 days)

#### A.1.a — Audit `_build_family_snapshot()` and `signal_score_history` for OOS markers (½ day, *gate before everything else*)

Codex deliverables:

1. Read `core/quant_core/signal_engine/` to find `_build_family_snapshot` and any per-bar score-history producer.
2. Determine: does each row in `signal_score_history` already carry a flag indicating whether the score for that (date, symbol, source) was produced via an out-of-sample fit? If yes, name the column and the semantics in a one-paragraph audit note inserted into this plan as §4.1.a-finding. If no, propose a column to add (e.g., `is_oos BOOLEAN NOT NULL DEFAULT false`) with an alembic migration; backfill semantics specified in A.1.b.iii.
3. Read `WfoSignalSummary.folds_json` schema by inspecting at least 5 production rows. Document the JSON shape for `folds_json[*].oos_window` (or whatever the field is called) in §4.1.a-finding. If the shape is heterogeneous across rows, propose a defensive parser.

**STOP here and report findings before continuing.** A.1.b depends on these answers.

#### §4.1.a-finding — Audit results (2026-05-07)

Live-DB audit run against `infra-quant_postgres-1` (`quant` DB, `app` user). Sample sizes: `signal_score_history` 1,395,306 rows across `source ∈ {engine_legacy=354027, engine_expanded=606534, wfo=434745}`; `wfo_signal_summary` 1808 rows total, 847 with non-empty `folds_json` arrays (8–12 folds each).

**1. Producer locations (correcting a plan reference).**

The `_build_family_snapshot` symbol cited in §2.4 / §4.1.a step 1 lives only in `frontend/scripts/export-scores.py:390` — that copy is a *re-builder* used by an offline export script, **not** the production writer. The actual production writer for `signal_engine_family_result.family_detail_json` is `_build_family_detail_json` at `services/api/app/services/signal_engine_persistence.py:152` (called from `:730` and `:1094`). This is the function the rest of this plan should reason about; treat references to `_build_family_snapshot` in §2.4 / §6 as aliases for `_build_family_detail_json`.

The per-bar score-history producer is `services/worker/tasks/score_history_batch.py` — `run_score_history_for_symbol()` at `:150`, with the actual row-write happening in `_replace_history()` at `:78`. It rebuilds the per-bar series from persisted representatives via `core/quant_core/research/score_history.py::build_engine_category_series` and `build_wfo_category_series`, then DELETEs+INSERTs the entire `(symbol, source, horizon)` slice. It has no concept of IS vs OOS at write time — the series spans the entire OHLCV index reachable from the representative's parameters.

**2. `signal_score_history` OOS marker — ABSENT. Must add.**

Live `\d` confirms columns are `(date, symbol, source, category, horizon, score_pct)` — exactly the ORM shape at `services/api/app/models.py:864-883`. The PK is the full natural key; there is no `is_oos`, no `holdout_flag`, no provenance column. The `source` column distinguishes engine variant from WFO but does not split IS vs OOS within either.

Within `source = 'wfo'`, every persisted bar from the entire OHLCV history is materialized — including bars before the first WFO fold's `oos_start` (no fold has yet selected a winner) and bars inside training windows of later folds. None of this is currently filterable from the table alone.

**Proposed schema change** (resolves Open item #1 in §7):
```sql
ALTER TABLE signal_score_history
    ADD COLUMN is_oos BOOLEAN NOT NULL DEFAULT false;
```
Migration filename: `services/api/alembic/versions/<rev>_add_is_oos_to_signal_score_history.py`. The column is non-nullable with `DEFAULT false` so the upgrade is online-safe on Postgres 11+ (no table rewrite). The PK does not include `is_oos`; legacy rows keep `false` and are functionally treated as IS (conservative — they will never enter Edge samples). Backfill is **not** attempted in the migration; instead, A.1.b follows the policy of §B.2 (terminal-N-bars-per-horizon for `signal_engine`) and `_replace_history` is updated to set `is_oos=true` for bars that fall inside fold OOS windows when source='wfo' (resolution detail in A.1.b.iii). Until the next score-history rebuild lands, the `is_oos=false` default + the §B.2 holdout fallback ensure callers do not double-count.

**3. `WfoSignalSummary.folds_json[*]` shape — homogeneous, but bar-index based.**

Sampled all 847 non-empty rows. Distinct keys present in `folds_json[0]`:
```
index, train_start, train_end, oos_start, oos_end,
is_return, oos_return, oos_sharpe,
winner_variant_id, winner_description, winner_prom,
profile_passes, profile_reason, profile_pct_profitable,
oos_profitable
```
**Critical:** every persisted fold uses **integer bar indices** for `train_start`, `train_end`, `oos_start`, `oos_end`. 0 of 847 rows carry the `*_date` keys that the writer at `services/worker/tasks/wfo_signal_batch.py:161` (`_build_folds_json`) emits when an `index` argument is supplied. In production the writer is invoked at `:339` with `ohlcv.index` — but the sampled rows pre-date that change (or the call-site evolution; live DB shows none have dates yet). **A.1.b must convert bar-index → timestamp by reloading the symbol's OHLCV index**, not by reading the JSON dates.

Other gotchas observed:
- `winner_variant_id` and `winner_description` may be empty string `""` (not null) when the winner pool is unavailable at write time. `OosWindow.winner_variant_id` should treat `""` as None.
- `oos_end` is exclusive in the bar-index space (matches `_window_date(end_exclusive=True)` at `:188-190`). The downstream `OosWindow.end` should keep it inclusive in date-space, so the conversion is `dates[oos_end - 1]`.
- All 15 keys are present in every sampled row — the shape is homogeneous. The defensive parser proposed for A.1.b can therefore be lean: tolerate the optional `*_date` keys for forward-compat, fall back to bar-index → timestamp resolution otherwise. No multi-version branching needed.

**`OosWindow` from a fold row** (concrete A.1.b spec):
```python
def _fold_to_window(fold: dict, ohlcv_index: pd.DatetimeIndex) -> OosWindow:
    s = int(fold["oos_start"]); e = int(fold["oos_end"])
    start = pd.Timestamp(fold.get("oos_start_date") or ohlcv_index[s])
    end   = pd.Timestamp(fold.get("oos_end_date")   or ohlcv_index[e - 1])  # exclusive → inclusive
    wv = (fold.get("winner_variant_id") or "").strip() or None
    return OosWindow(fold_id=int(fold["index"]), start=start, end=end,
                     winner_variant_id=wv, winner_params=None)
```
`winner_params` is not in the JSON; if A.1.b needs it, A.1.b must look it up via `winner_variant_id` against `representatives_json` on the same `WfoSignalSummary` row.

**Resolution of §7 open items.** Item #1 (OOS marker on `signal_score_history`) → resolved by the migration above. Item #2 (`folds_json` shape) → resolved; shape is homogeneous, parser spec given. A.1.b can proceed.

#### A.1.b — `oos_sample_for(symbol, horizon, source) -> OosSample`  (½ day)

New module: `core/quant_core/research/oos_index.py`. Pure functions only. No I/O — receives data via injected loaders so it is unit-testable with synthetic inputs. The key design constraint: WFO Edge cannot be represented as a plain date set, because bucket assignment must be tied to the fold winner that produced the OOS score on that date.

```python
@dataclass(frozen=True)
class OosWindow:
    fold_id: str | int | None
    start: pd.Timestamp  # inclusive
    end:   pd.Timestamp  # inclusive
    winner_variant_id: str | None = None
    winner_params: dict[str, Any] | None = None

@dataclass(frozen=True)
class OosSample:
    source: Literal["wfo", "signal_engine"]
    horizon: Literal["weekly", "monthly", "quarterly"]
    windows: tuple[OosWindow, ...]
    dates: pd.DatetimeIndex  # sorted union, convenience only
    score_mode: Literal["fold_scoped_winner", "terminal_holdout"]

def oos_windows_from_wfo(folds_json: list[dict]) -> list[OosWindow]:
    """Parse WfoSignalSummary.folds_json into normalized OOS windows.
    Tolerates the actual fold shape established in A.1.a-finding."""

def oos_sample_for_signal_engine(score_history_rows: Iterable[ScoreRow],
                                 holdout_bars: int) -> OosSample:
    """Returns the terminal holdout sample. If signal_score_history lacks an
    is_oos marker, derive the holdout from the final N trading bars per horizon."""

def oos_sample_for(*, symbol: str, horizon: Literal["weekly", "monthly", "quarterly"],
                   source: Literal["wfo", "signal_engine"],
                   wfo_loader: Callable, score_history_loader: Callable) -> OosSample:
    """Top-level entry. Returns fold-scoped OOS windows plus the convenience date union.
    Caches by (symbol, horizon, source, content_hash) for the duration of a request."""
```

**Tests** in `core/tests/test_oos_index.py`:
- `test_wfo_folds_simple`: synthetic `folds_json` with two non-overlapping windows; assert returned `OosWindow` list matches.
- `test_wfo_folds_overlapping`: deliberately overlapping windows; assert merged correctly.
- `test_wfo_folds_missing_field`: shape variation; assert defensive parser returns what it can without raising.
- `test_signal_engine_filters_is_rows`: two rows with `is_oos=True`, one with `is_oos=False`; assert the IS row is excluded.
- `test_oos_date_index_union_when_sources_combined`: integration shape (does not need a real DB).

#### A.1.c — Refactor `bucketed_forward_returns` to be OOS-aware (½ day)

**File:** `core/quant_core/research/score_history.py:253`.

Add an `oos_dates: pd.DatetimeIndex | None = None` keyword-only parameter. **Default `None` preserves current behavior** — do not break existing callers (per project memory: 91+ tests must stay green).

```python
def bucketed_forward_returns(
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    fwd_horizons: Iterable[int],
    *,
    n_bootstrap: int = 5000,
    return_calc_method: str = "close_to_close",
    oos_dates: pd.DatetimeIndex | None = None,   # NEW
    recent_window: tuple[int, int] | None = None, # NEW: (n_min, n_target). When set, after OOS filter, take the most recent up to n_target obs per (bucket, h) cell.
    max_lookback_years: float | None = None,      # NEW: hard ceiling
) -> list[dict[str, Any]]:
```

Logic order (insert immediately after `aligned_idx` is computed at line 281):

```python
if oos_dates is not None:
    aligned_idx = aligned_idx.intersection(pd.DatetimeIndex(oos_dates))
if max_lookback_years is not None and len(aligned_idx) > 0:
    cutoff = aligned_idx.max() - pd.Timedelta(days=int(365.25 * max_lookback_years))
    aligned_idx = aligned_idx[aligned_idx >= cutoff]
```

The recent-window-per-bucket sub-selection happens inside the existing per-bucket loop (after `sub = df[df["bucket"] == b]`):

```python
if recent_window is not None:
    n_min, n_target = recent_window
    sub = sub.sort_index().tail(int(n_target))
    if len(sub) < n_min:
        cells.append(_empty_cell(b, h, n=int(len(sub))))
        continue
```

**Tests** in `core/tests/test_bucketed_forward_returns_oos.py`:
- `test_oos_filter_preserves_existing_behavior_when_none`: existing semantics unchanged when `oos_dates=None`. Run on a fixture that exists today (or build one from synthetic data).
- `test_oos_filter_drops_is_dates`: synthetic series where IS rows have `+5%` returns and OOS rows have `0%` returns; assert that `oos_dates=<OOS only>` yields `mean ≈ 0`, `oos_dates=None` yields `mean > 0`.
- `test_max_lookback_years_caps_window`: 5-year synthetic; `max_lookback_years=2` excludes years 0–3.
- `test_recent_window_picks_last_N`: 200 rows in a bucket; `recent_window=(30,60)` returns stats over the last 60.
- `test_insufficient_sample_emits_empty_cell`: `recent_window=(30,60)` with only 25 rows → `_empty_cell` with n=25.

#### A.1.d — Horizon-aware indicator parameter caps (½ day)

**File:** `core/quant_core/signal_engine/domain.py` (or the file where the indicator search space is constructed — Codex confirms in A.1.a-finding).

Add a constant and helper:

```python
HORIZON_PARAM_CAP: dict[str, dict[str, int]] = {
    "short":  {"sma": 20,  "ema": 20,  "rsi": 14, "macd_slow": 13, "stoch": 14, "obv_ema": 20, "ichimoku_kijun": 26},
    "medium": {"sma": 50,  "ema": 50,  "rsi": 21, "macd_slow": 26, "stoch": 14, "obv_ema": 21, "ichimoku_kijun": 26},
    "long":   {"sma": 200, "ema": 100, "rsi": 21, "macd_slow": 26, "stoch": 21, "obv_ema": 50, "ichimoku_kijun": 52},
}

def cap_param_grid(grid: dict[str, list[int]], horizon: str, family: str) -> dict[str, list[int]]:
    """Filter grid in-place; remove parameter values above the horizon cap.
    Raises if every value of a required parameter would be filtered out."""
```

Apply at search-space construction time in every place a parameter grid is built per family. Codex enumerates these call sites in the implementation report.

**Cache invalidation.** The change of search space changes the input hash that `signal_engine_family_result.input_hash` (line 806) uses. Codex confirms the hash includes a version of `HORIZON_PARAM_CAP` (or bumps a global `SIGNAL_ENGINE_VERSION` constant that flows into the hash) so that prior caches are invalidated automatically on deploy.

**Tests** in `core/tests/test_horizon_param_cap.py`:
- For each horizon × each family in the registry, assert no value in the constructed grid exceeds its cap.
- Assert that running the cap on an already-capped grid is idempotent.

### 4.2 — Phase A.2 · Edge module + endpoint + caching (1.5–2 days)

#### A.2.a — `core/quant_core/research/edge.py` (½ day)

Pure functions only. Imports from `score_history` and `significance` only — no DB, no SQLAlchemy.

```python
@dataclass(frozen=True)
class ExpectancyDecomp:
    p_win: float
    avg_win: float        # signed: positive for long, negative for short (because "win" means in-direction)
    p_loss: float
    avg_loss: float       # signed: opposite of avg_win
    expectancy: float     # P_win*avg_win - P_loss*avg_loss; compare equal to arithmetic mean

@dataclass(frozen=True)
class EdgeGates:
    mc_gross: bool
    mc_net: bool
    wilson: bool
    n: bool

@dataclass(frozen=True)
class EdgeMetrics:
    symbol: str
    horizon: Literal["weekly", "monthly", "quarterly"]
    source: Literal["signal_engine", "wfo"]
    bucket: str                # one of BUCKET_NAMES
    direction: Literal["long", "short", "none"]
    n: int
    window_start: pd.Timestamp | None
    window_end:   pd.Timestamp | None
    expected_return_gross: float | None
    expected_return_net: float | None
    hit_rate: float | None
    hit_ci_lower: float | None
    hit_ci_upper: float | None
    expectancy_gross: ExpectancyDecomp | None
    expectancy_net: ExpectancyDecomp | None
    edge_ratio_gross: float | None
    edge_ratio_net: float | None
    profit_factor_gross: float | None
    profit_factor_net: float | None
    mc_luck_pvalue_gross: float | None
    mc_luck_pvalue_net: float | None
    label_shuffle_pvalue_gross: float | None
    label_shuffle_pvalue_net: float | None
    proven_edge_gross: bool
    proven_edge_net: bool
    gates: EdgeGates
    methodology_version: str   # bump on any algo change so frontend can detect stale cache

def compute_canonical_expectancy(returns: np.ndarray, direction: Literal["long", "short"]) -> ExpectancyDecomp: ...
def compute_profit_factor(returns: np.ndarray) -> float | None: ...
def compute_edge_ratio(mean: float, std: float) -> float | None: ...
def direction_for_bucket(bucket: str) -> Literal["long", "short", "none"]: ...
def build_edge_payload(*, symbol, horizon, source, score_series, prices,
                       oos_sample: OosSample, today_bucket: str, cost_bps_per_side=33.0,
                       n_min=30, n_target=60, max_lookback_years=3.0,
                       mc_iter=2000, mc_seed=42) -> EdgeMetrics: ...
```

`build_edge_payload` orchestrates source-specific sampling, applies the recent-window cap after WFO concatenation, computes gross and net strategy-perspective returns, runs block-aware MC tests for gross and net, computes the cost-invariant Wilson gate, and returns gross/net `EdgeMetrics`. It does not compute or gate against buy-and-hold.

#### A.1.c-NEW — `monte_carlo_label_shuffle_test` (½ day, slotted with A.2.a)

The existing `monte_carlo_luck_test` does centered-return bootstrap. We need a complementary test with the right null for bucket informativeness. Add to `core/quant_core/significance.py`:

```python
def monte_carlo_label_shuffle_test(
    score_series: pd.Series,
    forward_returns: pd.Series,
    *,
    bucket: str,
    n_iter: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """H0: bucket assignment is uninformative — i.e., shuffling the score-to-date
    mapping gives a distribution of bucket-mean-returns equivalent to the observed.
    Returns the same shape as monte_carlo_luck_test. The 'observed' field is the
    actual bucket mean; the null is built by shuffling score_series's index labels
    (preserving the marginal score distribution) and recomputing the bucket mean."""
```

Tests:
- `test_label_shuffle_pvalue_close_to_one_when_no_signal`: random scores → p-value ~uniform → for a single iter with n_iter=2000, expect p ≥ 0.4 most of the time.
- `test_label_shuffle_pvalue_low_when_strong_signal`: deterministic positive return on `strong_buy` dates only → p-value < 0.01.
- `test_label_shuffle_seed_determinism`: same seed twice → identical p-value.

This adds `label_shuffle_pvalue` to `EdgeMetrics`. The drill-down panel surfaces it as a **secondary** check; it does **not** participate in the `proven_edge` gate (one MC test in the gate is enough; the second is for transparency).

#### A.2.b — Endpoint and caching (½ day)

**Endpoint:** `GET /analytics/edge` in `services/api/app/routers/analytics.py`.

Query params (all required unless marked):
- `symbol: str`
- `horizon: Literal["weekly", "monthly", "quarterly"]`
- `source: Literal["signal_engine", "wfo"]`
- `cost_bps: float = 33.0` (optional override; default is the locked 33 bps/side contract)

Response: `EdgeMetricsOut` Pydantic model in `services/api/app/schemas/edge.py` mirroring the dataclass exactly. Use `model_config = ConfigDict(from_attributes=True)`.

**Caching:**
- Redis key: `edge:v{methodology_version}:{source}:{symbol}:{horizon}:{score_revision_hash}`
- TTL: 25 hours (24 + buffer to outlast the next EOD refresh under DST quirks)
- `score_revision_hash` is the SHA-256 of `(data_as_of, latest score_series row count, latest folds_json hash)` per (symbol, horizon, source). When any of those change, cache key changes, no invalidation needed.
- Cold-cache behavior: endpoint returns `null` body and `200 OK` with header `X-Edge-Cache: cold`. Frontend renders shimmer.

**Warming task:** `services/worker/tasks/refresh_edge_cache.py::warm_edge_cache(symbols, horizons, sources)`. Triggered by APScheduler immediately after the daily 20:00 Africa/Casablanca score refresh, and on-demand via `POST /analytics/edge/warm` (admin-only — see Workstream B auth).

#### A.2.c — Dashboard payload integration (½ day)

Codex first verifies the leaderboard endpoint feeding `frontend/app/v1/page.tsx` (project memory points at `services/api/app/routers/runs.py::list_strategy_leaderboard`). Once confirmed:

- Extend `StrategyLeaderboardOut` schema with `edge: EdgeMetricsOut | None`.
- In the assembler, look up the cached Edge for each `(symbol, current_horizon, source)`. Source is selected by the user via the existing score-source toggle (see project memory on `dashboard_score_source`). If `EDGE_INLINE_LIMIT` (env, default 200ms) elapses, return `null` for the rest and let the frontend fetch them per row via `/analytics/edge`.

#### A.2.d — Tests

`core/tests/test_edge_metrics.py`:
- `test_canonical_expectancy_matches_arithmetic_within_1e9` — invariant (3.4)
- `test_canonical_expectancy_short_signal_inverts_sign`
- `test_profit_factor_no_losses_returns_none`
- `test_profit_factor_no_wins_returns_zero`
- `test_profit_factor_known_value` — fixture: `[+1, +2, -1, -2]` → PF = 3/3 = 1.0
- `test_edge_ratio_zero_std_returns_none`
- `test_proven_edge_all_gates_pass` — synthetic data engineered to pass each gate
- `test_proven_edge_fails_when_n_below_30`
- `test_proven_edge_fails_when_mc_pvalue_above_threshold`
- `test_proven_edge_fails_when_wilson_lower_below_half`
- `test_proven_edge_fails_when_er_below_bh`
- `test_oos_filter_excludes_is_dates_end_to_end`

`services/api/tests/test_edge_endpoint.py`:
- `test_happy_path` — warm cache returns full payload
- `test_cold_cache_returns_null_with_header`
- `test_source_switch_returns_different_payload`
- `test_unknown_symbol_returns_404`
- `test_horizon_zero_returns_422`

### 4.3 — Phase A.3 · Dashboard restyle from Claude design (1.5–2 days)

Source of truth: `C:\tmp\claude_design\project\ui_kits\app\01-dashboard.html`. Tokens and atoms in `_shared.css` and `colors_and_type.css` next to it.

#### A.3.a — Atoms (½ day)

Extract reusable shadcn-flavored components in `frontend/components/ui/` and `frontend/components/dashboard/`:

| Component | File | Spec |
|---|---|---|
| `SignalBadge` | `frontend/components/ui/signal-badge.tsx` | Props `family: 'trend'\|'momentum'\|'oscillation'\|'volume'\|'composite'`, `score: number`. Maps score to one of 5 levels (per §3.7-style thresholds). Renders the right French label per family (the design's `famLabel` / `aggLabel`) with the right token class (`sig-bull-strong` … `sig-bear-strong`). |
| `Eyebrow` | `frontend/components/ui/eyebrow.tsx` | Tailwind: `text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground`. |
| `Segmented` | `frontend/components/ui/segmented.tsx` | Pill row with active = card-with-shadow. Generic typed by option value. |
| `SetupStep` | `frontend/components/dashboard/setup-step.tsx` | `{ index, title, options, value, hint, onChange }`. Renders the design's `.step` block. |
| `KpiTile` | `frontend/components/dashboard/kpi-tile.tsx` | `{ label, value, sub, tone? }`. Renders the design's `.stat` block. |
| `EdgeTile` | `frontend/components/dashboard/edge-tile.tsx` | Detailed below. |
| `EdgePanel` | `frontend/components/dashboard/edge-panel.tsx` | Detailed below. |

#### A.3.b — Restructure `frontend/app/v1/page.tsx`

Layout, top to bottom:

1. Page header (`Tableau de Bord V1`, sub line, action buttons `[Filtres][Exporter][Recalculer]`). Reuse the design.
2. KPI strip — 4 tiles: `Univers actif` / `Signaux haussiers` / `Signaux baissiers` / `E[R] médian (opt.)` (the last derives from the new Edge data — median of `expected_return` across rows where `proven_edge=true`).
3. 5 setup steps row: `1. Horizon` (Court/Moyen/Long), `2. Univers` (Actions/Secteurs/Indices), `3. Source` (Signal Engine/WFO/Les deux), `4. Catégorie` (Toutes/Très liq./Mid), `5. S/R` (Off/Auto/Manuel).
4. Market hierarchy tabs (`mktabs`) + sub-tabs (`subtabs`).
5. Filter bar with chips: liquidity (active/inactive amber), sector dropdown, search input, glossary link, **new**: `[ ] Edge prouvé seulement` toggle.
6. Signal table:
   - Columns (per design 01-dashboard, **defer 7J sparkline column**):
     - `[ ]` selection / `Ticker` / `Nom` / `Prix` / `Var.` / `ADV20` / `Trend.` / `Mom.` / `Osc.` / `Vol.` / `Signal` / `E[R]` (with period selector) / `Hit% [IC 95%]` / `→`
   - The Edge tile lives in the existing card layout above the row, OR (preferred) as a wide column on the rightmost side called `Edge` showing edge ratio + small expectancy decomposition.
   - Default sort: `proven_edge desc → edge_ratio desc → opportunity_score desc`.
7. Footer note (E[R] formula + IC explanation + glossary link).

#### A.3.c — `EdgeTile` spec

Compact card visible on every row (or as a column cell, depending on the layout chosen in A.3.b):

```
┌─────────────────────────────────┐
│  Edge ratio                  ★  │   ← star = Proven Edge badge (green); hollow if not
│  +0,42                          │   ← edge_ratio formatted with sign and locale
│  +1,8% · 64% · PF 1,42 · n=42   │   ← ER · HR · PF · n  (one line, mono)
│  42 obs OOS · 18 mois           │   ← window
└─────────────────────────────────┘
```

Click → opens `EdgePanel` for that row.

States: cold-cache → shimmer; `bucket == "hold"` → tile renders dim "Pas de signal aujourd'hui" with no metrics; `n < 30` → grey badge "Insuffisant" with tooltip "Échantillon < 30 obs OOS".

#### A.3.d — `EdgePanel` spec

Slide-over panel (use existing `Sheet` component from `frontend/components/ui/sheet.tsx`), opened from the tile.

Sections, top to bottom:

1. **Header** — `<symbol> · <horizon>j · source: <Signal Engine|WFO>` toggle for source (refetches on change). Bucket label as a read-only chip (no override affordance, per §3.1).
2. **3-gate checklist for selected mode (default net / `Coûts inclus`):**
   ```
   ✓ Test de chance MC : p = 0.004 (< 0.01)
   ✓ Wilson LB : 0.58 (> 0.50)
   ✓ Échantillon : 42 (≥ 30)
   ```
3. **Test complémentaire (label shuffle)** — `Label-shuffle MC : p = 0.012` with one-line explainer.
4. **Décomposition de l'expectance** — table:
   ```
   P(gain)  = 0.61    avg_gain = +2.10%
   P(perte) = 0.39    avg_perte = -1.40%
   E = 0.61·2.10 - 0.39·1.40 = +0.74%   ← matches mean returns
   ```
5. **Distribution des retours OOS du bucket** — small histogram (Recharts bar). 20 bins between min and max, vertical guide at zero.
6. **Méthodologie / limites** — accordion with the verbatim text from §3.8.
7. **Lien** — "Voir matrice prédictive complète" → `/analytics?symbol=<sym>&horizon=<h>`.

#### A.3.e — Frontend API client

`frontend/lib/api.ts`:
- `EdgeMetricsSchema` (Zod) mirroring `EdgeMetricsOut`.
- `fetchEdge(symbol: string, horizon: TradingHorizon, source: 'signal_engine'|'wfo', costBps = 33): Promise<EdgeMetrics | null>` — returns `null` on cold-cache.

#### A.3.f — Feature flag

Env var `NEXT_PUBLIC_EDGE_ENABLED` (default `true`). When `false`:
- `EdgeTile` returns `null`.
- The `Edge prouvé seulement` filter and the badge-first sort are hidden.
- The `E[R]` and `Hit% [IC 95%]` columns fall back to `—` (or the columns are hidden — Codex picks the cleaner of the two; document the choice).

### 4.4 — Phase A.4 · Verification

| Check | How |
|---|---|
| All A.1 / A.2 unit tests green | `python -m pytest core/tests/test_oos_index.py core/tests/test_bucketed_forward_returns_oos.py core/tests/test_horizon_param_cap.py core/tests/test_edge_metrics.py services/api/tests/test_edge_endpoint.py -q` |
| Full backend suite still green | `python -m pytest core/tests/ -q` (must be ≥ existing pass count) |
| Manual API check | `curl 'http://localhost:8000/analytics/edge?symbol=ATW&horizon=21&source=signal_engine'` returns sensible JSON; gates parse; mean ≈ canonical expectancy. |
| Source switch | Same call with `source=wfo` returns a different payload. |
| Frontend build | `npm --prefix frontend run typecheck && npm --prefix frontend run build` clean. |
| Demo dry-run | Pick 2–3 symbols where `proven_edge=true`. Walk: row → drill-down → 4 gates → decomposition → histogram → cross-link. Pick 1 with `false`. Pick 1 with `bucket=hold`. Pick 1 with `n<30`. All four states render without error. |

---

## 5. Workstream B — Intranet deployment (single-VM, all-Docker)

Estimated total: **2–3 working days** parallel to or after A.

### 5.1 — Phase B.1 · Stack composition (½ day)

**Single docker-compose stack** running on the Oracle VM, reachable behind Caddy with IP allowlist:

```
caddy            (80, 443 public; IP-allowlisted)
  ├── frontend   (Next.js standalone; port 3000)
  ├── api        (FastAPI; port 8000)
  └── (Auth.js shares the frontend container — no separate service)
worker           (RQ; no exposed port)
postgres         (port 5432; only on internal network)
redis            (port 6379; only on internal network)
minio            (port 9000 + 9001 console; admin-only path under Caddy)
```

Frontend Dockerfile becomes a real production build:

```Dockerfile
# frontend/Dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
```

`frontend/next.config.js` must set `output: 'standalone'` for the multi-stage build to produce `server.js`.

`infra/docker-compose.gcp.yml` adds a `frontend` service pulling `ghcr.io/<owner>/bt-frontend:<tag>`.

### 5.2 — Phase B.2 · Auth.js v5 + Postgres adapter (1–1.5 days)

**Why Auth.js v5 specifically:** v5 (`next-auth@beta` as of writing) is the App Router-native API. It supports the Drizzle adapter for Postgres, JWT sessions out of the box, and clean middleware integration.

#### B.2.a — Schema

Auth.js owns four tables: `users`, `accounts`, `sessions`, `verification_tokens`. They live in the existing Postgres database, in the public schema (avoids needing Auth.js to know about a separate schema). Migration via Drizzle:

- `frontend/auth/schema.ts` defines the four tables with the exact shape the Drizzle Auth.js adapter expects. This is **separate from** the SQLAlchemy models — Drizzle only writes/reads these four tables; SQLAlchemy never touches them.
- `frontend/auth/migrate.ts` is a one-shot runner: `npm run db:auth-migrate` applies missing migrations on deploy. Add to the deploy workflow.

#### B.2.b — Auth.js config

`frontend/auth/index.ts`:

```ts
import NextAuth from "next-auth"
import Credentials from "next-auth/providers/credentials"
import { DrizzleAdapter } from "@auth/drizzle-adapter"
import { db } from "./db"
import bcrypt from "bcryptjs"
import { z } from "zod"

const Creds = z.object({ email: z.string().email(), password: z.string().min(8) })

export const { auth, handlers, signIn, signOut } = NextAuth({
  adapter: DrizzleAdapter(db),
  session: { strategy: "jwt" },
  trustHost: true,            // intranet: Caddy fronts us; X-Forwarded-Host trusted
  pages: { signIn: "/login" },
  providers: [
    Credentials({
      credentials: { email: {}, password: {} },
      authorize: async (raw) => {
        const parsed = Creds.safeParse(raw)
        if (!parsed.success) return null
        const u = await db.query.users.findFirst({ where: eq(users.email, parsed.data.email) })
        if (!u || !u.passwordHash) return null
        const ok = await bcrypt.compare(parsed.data.password, u.passwordHash)
        return ok ? { id: u.id, email: u.email } : null
      },
    }),
  ],
  callbacks: {
    jwt: ({ token, user }) => { if (user) token.uid = user.id; return token },
    session: ({ session, token }) => { session.user.id = token.uid as string; return session },
  },
})
```

`frontend/middleware.ts`:

```ts
export { auth as middleware } from "@/auth"
export const config = { matcher: ["/((?!api/auth|_next|login|signup|favicon|public).*)"] }
```

`frontend/app/api/auth/[...nextauth]/route.ts` exports `handlers.GET` and `handlers.POST`.

`frontend/app/login/page.tsx`, `frontend/app/signup/page.tsx`, `frontend/app/account/page.tsx` — minimal shadcn forms; signup writes to `users` with `bcrypt.hash(password, 12)` and an admin must approve (a `users.is_active BOOLEAN DEFAULT false` column gate). For v1 with a small user list this is acceptable; document that signup is "request access" not "instant access".

#### B.2.c — FastAPI verifies Auth.js JWT

Auth.js with `session.strategy: "jwt"` issues a **JWE-encrypted JWT** by default (using `NEXTAUTH_SECRET`). FastAPI must decrypt and verify.

Two clean options; pick **option 2** for simplicity:

- **Option 1:** Auth.js custom `encode/decode` using HS256 plain JWT; FastAPI verifies HS256 with `python-jose`. Trade-off: weakens token confidentiality (anyone who reads the cookie sees claims).
- **Option 2 (recommended):** Frontend's API proxy at `frontend/app/api/[...path]/route.ts` reads `auth()` server-side, gets the user id, and forwards to the backend with a short-lived **internal JWT** signed by `INTERNAL_JWT_SECRET` (HS256). The browser never sees this token. FastAPI verifies HS256.

```ts
// frontend/app/api/[...path]/route.ts (sketch)
import { auth } from "@/auth"
import jwt from "jsonwebtoken"

export async function GET(req: Request, ctx: { params: { path: string[] } }) {
  const session = await auth()
  if (!session?.user) return new Response("Unauthorized", { status: 401 })
  const internalToken = jwt.sign(
    { sub: session.user.id, email: session.user.email },
    process.env.INTERNAL_JWT_SECRET!,
    { algorithm: "HS256", expiresIn: "5m" }
  )
  const url = `${process.env.API_BASE}/${ctx.params.path.join("/")}${new URL(req.url).search}`
  return fetch(url, { headers: { Authorization: `Bearer ${internalToken}` } })
}
// (and similar for POST/PUT/PATCH/DELETE)
```

`services/api/app/auth.py::get_current_user` decodes the HS256 token, returns `User(id=UUID(claims["sub"]), email=claims["email"])`.

#### B.2.d — Multi-tenancy schema

Same migration as in §6.1 (W A's parallel deliverable, but not required for the demo). Codex implements after Workstream A ships:
- Add `owner_id UUID NOT NULL` and `visibility ENUM('private','public') NOT NULL DEFAULT 'private'` to: `run`, `dataset`, `saved_strategy`, `strategy_decision`, `strategy_leaderboard`, `signal_backtest_run`, `wfo_signal_summary`. **Not** to shared catalogs.
- Backfill `owner_id` to a seed admin user; set NOT NULL.
- All routers filter `or_(owner_id == user.id, visibility == 'public')` on read and require `owner_id == user.id` on write.

### 5.3 — Phase B.3 · Image build, registry, deploy (1 day)

`.github/workflows/build-images.yml`:

```yaml
name: build-images
on:
  push: { branches: [main], paths: ['services/**', 'core/**', 'frontend/**', 'pyproject.toml'] }
jobs:
  build:
    runs-on: ubuntu-latest
    permissions: { contents: read, packages: write }
    strategy:
      matrix: { svc: [api, worker, frontend] }
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - uses: docker/build-push-action@v5
        with:
          context: .
          file: services/${{ matrix.svc == 'frontend' && 'frontend' || matrix.svc }}/Dockerfile
          platforms: linux/arm64
          push: true
          tags: |
            ghcr.io/${{ github.repository_owner }}/bt-${{ matrix.svc }}:${{ github.sha }}
            ghcr.io/${{ github.repository_owner }}/bt-${{ matrix.svc }}:latest
          cache-from: type=gha
          cache-to:   type=gha,mode=max
```

(File path mapping for `frontend` is messy — the workflow above uses a ternary; if your matrix expression doesn't permit it, split into three jobs or add a `dockerfile` matrix key.)

`.github/workflows/deploy-vm.yml`:

```yaml
name: deploy-vm
on:
  workflow_run:
    workflows: [build-images]
    types: [completed]
    branches: [main]
jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - uses: appleboy/ssh-action@v1
        with:
          host:     ${{ secrets.ORACLE_HOST }}
          username: deploy
          key:      ${{ secrets.ORACLE_SSH_KEY }}
          script: |
            set -euo pipefail
            cd /opt/bt
            git fetch && git reset --hard origin/main
            docker compose --env-file /etc/bt/env pull
            docker compose --env-file /etc/bt/env run --rm api alembic -c alembic.ini upgrade head
            docker compose --env-file /etc/bt/env run --rm frontend npm run db:auth-migrate
            docker compose --env-file /etc/bt/env up -d --remove-orphans
            docker image prune -f
      - name: smoke
        run: |
          curl -fsS https://api.${{ secrets.DOMAIN }}/health
          curl -fsS https://app.${{ secrets.DOMAIN }}/login | grep -q "Connexion"
```

ARM64 build validation pre-commit: run locally `docker buildx build --platform linux/arm64 -f services/worker/Dockerfile .` to surface numba/numpy issues before pushing the workflow.

### 5.4 — Phase B.4 · Caddy IP allowlist + DNS (½ day, blocked on §1.1 decision)

`infra/Caddyfile.gcp` excerpt:

```
{
  email <ops@<domain>>
}

(office_only) {
  @office {
    remote_ip <COMPANY_EGRESS_CIDR>     # e.g., 196.200.10.0/24
    remote_ip <MAINTAINER_VPN_CIDR>     # e.g., a Tailscale 100.64.0.0/10
  }
  handle @office {
    respond ""                          # placeholder; real handlers per route
  }
  handle {
    respond "Forbidden" 403
  }
}

api.<domain> {
  import office_only
  reverse_proxy api:8000
  encode gzip
  log { output file /var/log/caddy/api.log }
}

app.<domain> {
  import office_only
  reverse_proxy frontend:3000
  encode gzip
  log { output file /var/log/caddy/app.log }
}
```

`COMPANY_EGRESS_CIDR` is the variable Codex must obtain from the user before this phase ships.

DNS: two A records pointing at the Oracle reserved public IP. Caddy auto-issues Let's Encrypt certs.

### 5.5 — Phase B.5 · Observability, backups, runbook (½ day)

- **Sentry** SDKs in API (`sentry_sdk[fastapi]`) and frontend (`@sentry/nextjs`). Free tier (~5k events/mo).
- **Caddy access logs** rotate daily via `logrotate`.
- **Postgres backups**: cron on the VM, `pg_dump -Fc | gzip` to a separate MinIO bucket `bt-backups`, 30-day retention via MinIO lifecycle. Restore runbook in `docs/ops/restore.md`.
- **Uptime check**: UptimeRobot free pinging `/health` every 5 min, email on 2 consecutive failures.
- **Idle-reclaim heartbeat**: a tiny systemd timer on the VM that GETs `/health` every 10 minutes from `localhost`. Generates enough internal traffic that the VM never hits Oracle's idle threshold.

---

## 6. Critical files reference

| Workstream | Sub-phase | File | Role |
|---|---|---|---|
| A | A.1.a | `core/quant_core/signal_engine/`, `services/api/app/models.py:769-983` | Audit; insert findings into §4.1.a-finding |
| A | A.1.b | `core/quant_core/research/oos_index.py` (NEW) | OOS date-set construction |
| A | A.1.b | `core/tests/test_oos_index.py` (NEW) | OOS date-set tests |
| A | A.1.c | `core/quant_core/research/score_history.py:253` | Add `oos_dates`, `recent_window`, `max_lookback_years` params |
| A | A.1.c | `core/tests/test_bucketed_forward_returns_oos.py` (NEW) | OOS-aware tests |
| A | A.1.d | `core/quant_core/signal_engine/domain.py` | `HORIZON_PARAM_CAP`, `cap_param_grid` |
| A | A.1.d | `core/tests/test_horizon_param_cap.py` (NEW) | Cap behavior tests |
| A | A.1.c-NEW | `core/quant_core/significance.py` | `monte_carlo_label_shuffle_test` |
| A | A.2.a | `core/quant_core/research/edge.py` (NEW) | Pure Edge metrics module |
| A | A.2.b | `services/api/app/routers/analytics.py` | New `/analytics/edge` endpoint + warm endpoint |
| A | A.2.b | `services/api/app/schemas/edge.py` (NEW) | Pydantic models |
| A | A.2.b | `services/worker/tasks/refresh_edge_cache.py` (NEW) | Cache warmer |
| A | A.2.c | `services/api/app/routers/runs.py::list_strategy_leaderboard` | Attach `edge` per row |
| A | A.2.d | `core/tests/test_edge_metrics.py` (NEW), `services/api/tests/test_edge_endpoint.py` (NEW) | Tests |
| A | A.3 | `frontend/app/v1/page.tsx`, `frontend/components/ui/{signal-badge,eyebrow,segmented}.tsx`, `frontend/components/dashboard/{setup-step,kpi-tile,edge-tile,edge-panel}.tsx`, `frontend/lib/api.ts` | Restyle + Edge UI |
| B | B.1 | `frontend/Dockerfile`, `frontend/next.config.js`, `infra/docker-compose.gcp.yml` | Frontend in Docker |
| B | B.2 | `frontend/auth/{index.ts,schema.ts,db.ts,migrate.ts}` (NEW), `frontend/middleware.ts`, `frontend/app/{login,signup,account}/page.tsx` (NEW), `frontend/app/api/[...path]/route.ts`, `frontend/app/api/auth/[...nextauth]/route.ts` (NEW), `services/api/app/auth.py` | Auth.js + JWT verify |
| B | B.3 | `.github/workflows/build-images.yml`, `.github/workflows/deploy-vm.yml`, `.github/workflows/ci.yml` (NEW) | CI/CD |
| B | B.4 | `infra/Caddyfile.gcp` | IP allowlist + DNS |
| B | B.5 | `services/api/app/main.py` (Sentry init), `frontend/sentry.{client,server,edge}.config.ts`, `docs/ops/restore.md` (NEW) | Observability + backups |

---

## 7. Open items / blocking inputs

Codex must obtain answers to these before the corresponding phase ships:

1. **§4.1.a-finding** — does `signal_score_history` already carry an OOS marker? Resolve before A.1.b.
2. **§4.1.a-finding** — what is the actual JSON shape of `WfoSignalSummary.folds_json[*]`? Resolve before A.1.b.
3. **§4.2.c** — confirm `services/api/app/routers/runs.py::list_strategy_leaderboard` is the dashboard payload assembler; if not, name the actual endpoint.
4. **§1.1** — company egress CIDR for Caddy IP allowlist (or chosen alternative: Tailscale, on-prem). Resolve before B.4.
5. **Domain name** for `api.<domain>` and `app.<domain>`. Resolve before B.4.
6. **Maintainer VPN / break-glass path** — how does the maintainer reach the box from home? (Tailscale on a personal device is the simplest.)
7. **SMTP relay availability** — if the company has one, switch Auth.js from Credentials to magic-link (cleaner UX). Otherwise stay with Credentials.

## 8. Sequencing recommendation

Realistic 5–7 working day plan:

| Day | Workstream A (backend/edge) | Workstream B (deploy) |
|---|---|---|
| 1 | A.1.a audit, A.1.b oos_index | B.1 frontend Docker spec |
| 2 | A.1.c bucketed_forward_returns refactor + tests | B.2.a/b Auth.js scaffolding |
| 3 | A.1.d param caps, A.1.c-NEW label shuffle test | B.2.c FastAPI JWT verify |
| 4 | A.2.a/b edge module + endpoint + caching | B.3 CI/CD workflows |
| 5 | A.2.c/d leaderboard integration + tests | B.4 Caddy + DNS (after egress CIDR known) |
| 6 | A.3 dashboard restyle + Edge UI | B.5 backups + Sentry |
| 7 | A.4 verification + demo dry-run | smoke test in prod |

Workstream B is mostly independent of A; both can run in parallel if Codex has bandwidth.

## 9. Demo dry-run checklist

Before showing the supervisor:
- 2–3 symbols where badge fires green; rehearse: row → drill-down → **3 gates (`mc`/`wilson`/`n` per Amendment D)** → canonical expectancy decomposition (gross + net side-by-side per Amendment E.5) → histogram → label-shuffle pvalue → cross-link.
- 1 symbol with badge=false; show *which* gate fails and why.
- 1 symbol with `bucket=hold`; show the dim "Pas de signal aujourd'hui" state.
- 1 symbol with `n<30`; show the grey "Insuffisant" state.
- One-line answers ready:
  - *"Multiple-testing correction?"* → "Deferred. Stricter `p < 0.01` partially mitigates. Proper FDR in next iteration."
  - *"Bucket selection bias?"* → "We measure the bucket the signal selected today, not the best historical bucket. No selection."
  - *"Look-ahead?"* → "All ER/HR/PF computed on OOS forward returns only. WFO test windows + signal-engine OOS reconstruction. Audit + tests in `test_oos_index.py` and `test_bucketed_forward_returns_oos.py`."
  - *"What's your null hypothesis?"* → "Two complementary tests. Centered-return bootstrap (`monte_carlo_luck_test`) tests if the bucket's mean is non-zero. Label-shuffle test (`monte_carlo_label_shuffle_test`) tests if bucket assignment is informative."
  - *"Regime stability?"* → "Stats over the last 30–60 OOS observations, ≤ 3-year ceiling. Designed for current regime. Not robust to a regime break — known limitation."

---

## 10. Out-of-scope (post-demo, in priority order)

1. Multi-tenancy schema migration (W B.2.d) — needed before opening signup beyond the seed admin.
2. Data engineering hardening: CASCADE on FKs, run retention with `is_pinned`, pg_dump cron, MinIO orphan cleanup, missing indexes.
3. Remaining UI ports from the Claude design: Data, Glossary, Signals, Strategy, Backtest, Analytics. Header refactor + font swap to Roboto/Roboto Mono.
4. Multiple-hypothesis correction (BH-FDR) on Edge p-values across the dashboard.
5. Regime-windowed Edge view (rolling 12 / 24 month).
6. Determinism layer: pinned RNG seeds in `run.spec_json`, code-SHA stamping on results, library-version capture, immutable data snapshots.
7. Audit log: append-only "who viewed/modified what when".
8. Corporate-actions handling (splits, dividends, suspensions, holiday calendars) in the equity data layer.
