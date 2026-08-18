# Implementation contract — Portefeuille tab PIT backtest (Revision 5, final)

**Revision 5 (2026-07-17) — final, ready for direct implementation.** This contract makes the Portefeuille tab a rigorous point-in-time backtest of the decisions the **existing dashboard methodology** would have made at each weekly historical `as_of`, using only information available then, executed through an explicit MASI execution policy.

**Scope boundary (binding):** Rev 5 **freezes** the dashboard's current statistical methodology — evidence construction, ranking, the n ≥ 30 sample rule, luck and label-shuffle tests with their current adjustments, and actionability semantics — exactly as implemented today, versioned as the v5 methodology. Rev 5 does **not** introduce PSR/DSR/MinTRL, revised evidence grades, BH/FDR correction, relaxed shuffle/luck gates, or any other statistical redesign; those belong to a separately versioned future Rev 6. Rev 5 proves **PIT correctness and deterministic replay under the frozen methodology** — it does not prove, and must not claim to prove, statistical edge validity. Rev 5 persists the evidence consumed by its frozen methodology and every rejection reason, making it the unbiased baseline against which Rev 6's statistical changes will later be measured. Rev 6 will use a new builder and methodology-version bump, then rematerialize from the authoritative persisted score and OOS sources through the same PIT infrastructure; it does not require rebuilding the schema or replay engine.

**Audience:** implementing agent (Codex) with repo access, no prior discussion. Implement phase by phase in order; run each phase's blocking tests before moving on.

**Relationship to other briefs:** `docs/ai/pit-store-first-portfolio-backtest.md` — already implemented in the uncommitted working tree; Phase 2 audits it, does not reimplement it. `docs/ai/portfolio-backtest-mtm-fix.md` — shelved, do NOT implement.

## Core objective and layering

Produce **one canonical historical portfolio**. Rev 5 separates three layers that today are conflated:

1. **Point-in-time signal reconstruction** — category scores, aggregate, bucket, direction, evidence, rebuilt from persisted history only.
2. **Dashboard ranking/actionability semantics** — the existing rules, centralized in one shared function so live and historical paths cannot diverge.
3. **Market-specific execution capabilities** — what MASI permits, applied at replay time only.

> Core invariant: a signal can be historically actionable and rankable while being non-executable as a *new position* in the selected market. For MASI, an actionable winning **short** is persisted with full evidence, ranked, eligible as `reconstructed_dashboard_winner`, audited — and at execution it closes an existing matching long at the next available Open but never opens a short.

The ledger must make the Jan–May 2024 and Oct 2024–Jan 2025 windows directly diagnosable week by week: which decisions were made, which were rejected and why, which winners were vetoed by gates, which longs were liquidated by short signals.

## Architecture facts (verified 2026-07-17; several files carry uncommitted changes — re-anchor if drifted)

- **Dashboard actionability** (`_best_signal_rank`, `services/api/app/services/dashboard_builder.py:1298-1322`): returns `None` when bucket/direction is not actionable (`_is_actionable_edge_bucket` :183-190 — actionable iff buy/strong_buy∧long or sell/strong_sell∧short), when `n < 30` or `gates["n"]` is false (:1302-1307), or when expected return (`action_expected_return_net → expected_return_net`) is missing or ≤ 0 (:1309-1313). **A missing edge score does NOT reject**: `penalized = ci_lower if not None else expected*0.5` (ci fallback `action_expected_return_net_ci_lower → expected_return_net_ci_lower`), `rank_score = edge_score if not None else penalized` (:1315-1320). Rank tuple: `(2 if proven else 1, rank_score, penalized, expected)`.
- **Materializer divergences to remove** (`services/worker/tasks/historical_portfolio_backtest.py`): drops shorts (`_direction` :54-57, applied :115-116), requires `edge_score is not None` (:146-147 — stricter than the dashboard), ranks with raw `edge_score` and no penalized fallback (:170-175), bakes *user run costs* into evidence (:94-95, :135) while the dashboard uses `settings.EDGE_COST_BPS_PER_SIDE` (`config.py:72`, default 33.0; used at `dashboard_builder.py:978, 1333, 1606`).
- **Replay currently re-ranks under user gates** (worker :454-469): filters stored rows to long + `passes_edge_policy`, then takes max rank per key — this can promote a runner-up the dashboard never displayed. Replaced by winner-only replay (Phase 5).
- **Strict deserialization**: `_opportunity_from_json` (worker :267-273) = `HistoricalOpportunity(**raw)`; `candidate_lookup` (:471-475) deserializes **every** stored row — hence the decision/opportunity storage split below.
- **Store**: `historical_trade_opportunity` (`models.py:2003-2032`) — unique `(decision_date, symbol, horizon, variant)`, `accepted`, `rank_json`, `opportunity_json` NOT NULL, `input_hash`, FK `materialization_run_id`; **no version column**. `HistoricalPortfolioBacktestRun` (:1935): `config_json`, no input_hash.
- **Constants**: `METHODOLOGY_VERSION = "pit-dashboard-opportunity-portfolio-edge-policy-v4"`, `DECISION_HORIZONS = ("weekly","monthly","quarterly")`, `CAPACITY_SCENARIOS` (`core/quant_core/historical_portfolio.py:28-30`). Category vocabulary is **French**: `("tendance","momentum","oscillation","volume")` (`core/quant_core/research/decision_bakeoff.py:22`); persistence stays French, UI translates.
- **Universe**: canonical MASI resolution = `list_signal_universe(db)` + `is_masi_dashboard_member(row)` (`services/api/app/services/market_universe.py`).
- **Router** (`routers/historical_portfolio_backtest.py`): `GET /{run_id}` at :200 — the new `/decisions` route must be declared before it.
- **Frontend** (`frontend/components/signals/portfolio-backtest-panel.tsx`): default export returns `SnapshotAuditLegacyPanel` (:1669); the PIT panel (:1451) also embeds the legacy panel in a `<details>` (:1659). Both legacy renderings are removed (one-canonical-portfolio rule).
- **Typed OOS structures exist**: `OosWindow`/`OosSample`/`oos_sample_for` in `core/quant_core/research/oos_index.py` (pure, loader-injected).
- **Literal snapshots**: ~13 `DashboardSnapshot` dates (May–Jul 2026) — audit fixtures only, never a source of trades.

## Known limitations (documented in results payload + UI note)

Universe survivorship (today's MASI membership ⇒ upward bias). Foundation assumption: `SignalScoreHistory.is_oos` rows are genuinely fold-scoped (inherited). Historical winner reconstruction uses named PIT substitutes where live inputs don't exist historically (see Phase 3); the fidelity audit quantifies the effect diagnostically.

## Non-goals

No new short positions on MASI (capabilities layer; short *signals* are first-class). No implemented short-book execution anywhere (see reserved interface). No changes to cash accounting, Kelly math, capacity math, or Edge computation internals. No statistical-methodology changes (Rev 6). No fabricated `DashboardSnapshot` rows. No second user-facing portfolio curve. No historical index-membership reconstruction.

---

## Storage contract (v5)

`historical_trade_opportunity` after the Phase 1 migration:

| column | type | contract |
|---|---|---|
| `methodology_version` | String(80), NOT NULL, indexed, in unique key | backfilled via `materialization_run_id → run.methodology_version`; literal v4 string only where the run row is missing |
| `status` | String(32), NOT NULL, indexed, DB CHECK | **computation status only**: `no_price_data, no_score_data, stale_score, insufficient_history, evidence_unavailable, evaluated` |
| `actionable` | Boolean, NOT NULL default false, indexed | set **solely** by the shared rank/actionability function; true only on `evaluated` rows |
| `reconstructed_dashboard_winner` | Boolean, NOT NULL default false, indexed with `decision_date` | ≤ 1 true per (version, date, symbol, horizon); only `actionable` rows (either direction) may be true; backfilled v4 rows all false |
| `accepted` | unchanged | frozen legacy v4 field; never renamed/reinterpreted; not written by v5 |
| `decision_json` | JSONB, NOT NULL | field list below |
| `opportunity_json` | JSONB, **nullable** | non-null iff `actionable = true` (long OR short): exact current `HistoricalOpportunity` serialization (direction may be `"short"`), so `_opportunity_from_json` works untouched |

New unique key: `(methodology_version, decision_date, symbol, horizon, variant)`.

**Status precedence (computation pipeline only — first match wins):**
`no_price_data → no_score_data → stale_score → insufficient_history → evidence_unavailable → evaluated`

- `evidence_unavailable` = evaluation reached evidence construction but it failed or produced no usable sample. `evaluated` = category scores, aggregate, bucket, direction, and evidence all computed — **including neutral buckets and shorts** (the dashboard computes evidence for every mode; so does v5).
- **Actionability is not a status.** For `evaluated` rows the shared function decides `actionable` and, when false, writes `actionability_reasons` from the closed set: `neutral_bucket`, `insufficient_dashboard_sample` (n < 30 or `gates.n` false), `non_positive_expectancy`, `invalid_bucket_direction`. A missing edge score is **not** a rejection — the penalized fallback ranks it, exactly as `_best_signal_rank` does.
- The materializer's old `<3 selection observations` rejection is removed from actionability (it was never a dashboard rule). Actionable rows may carry empty/short `selection_observations`; sizing failure is a replay-time rejection (existing Kelly-unavailable path in `simulate_sleeve`), recorded in the run ledger, never in the PIT decision row.

**`decision_json` fields (all keys always present; null/`"unavailable"` when unknown):** `status` (mirrors column), `signal_direction` (`"long"|"short"|"neutral"|null`), `actionable` (mirrors column), `actionability_reasons` (list; `[]` iff actionable), `rank` (list | null — shared tuple, present iff actionable), `category_scores` (exactly the four French keys, each float or `"unavailable"`), `aggregate_score` (float | null), `bucket` (string | null), `computation_rejection_reasons` (list; why a pre-`evaluated` status was assigned; `[]` for evaluated rows), `execution_eligible` (bool — may this open a NEW position under the instrument's capabilities), `execution_rejection_reason` (string | null, e.g. `"short_entry_not_supported_masi"`), `evidence` (canonical payload or null): exactly `edge_score, edge_score_components, expected_return_net, action_expected_return_net, ci_lower_net, action_expected_return_net_ci_lower, hit_ci_lower, proven_edge_net, gates, mc_luck_pvalue_net_adj, label_shuffle_pvalue_net_adj, freshness_status, selection_n, proof_n, n, exit_lag_bars, entry_price_kind, exit_price_kind, return_calc_method, edge_methodology_version, mc_iterations, mc_seed, decision_edge_cost_bps`.

This evidence payload records the evidence consumed by the frozen v5 methodology — including the luck/shuffle p-values with their **current** adjustments — for auditability. It is not claimed to contain the raw observations required to derive a different methodology. Rev 6 will rematerialize from the authoritative persisted score and OOS sources through this same PIT infrastructure under a new methodology version; no Rev 5 schema expansion for future statistical methods is required.

**Invariants**: `status='evaluated'` ⇒ `evidence` non-null (else status must be `evidence_unavailable`); `actionable=true` ⇒ `status='evaluated'` ∧ `actionability_reasons=[]` ∧ `opportunity_json` non-null; `actionable=false` ⇒ `opportunity_json` null. `execution_action` is deliberately NOT persisted (position-dependent; replay-time output in the run's trade/event ledger).

**Edge-evidence source of truth**: `decision_json.evidence` is authoritative. Read-time `passes_edge_policy` consumes it; `HistoricalOpportunity.provenance` duplicates it for compatibility only; semantic validation asserts Edge-policy field equality between the two; the frontend drill-down reads `decision_json.evidence`.

**v4 backfill `decision_json`** (every key explicit): `status="evaluated"`, `actionable=true`, `actionability_reasons=[]`, `signal_direction`/`bucket` from `opportunity_json`, `rank` from `rank_json`, four `category_scores="unavailable"`, `aggregate_score=null`, `computation_rejection_reasons=[]`, `execution_eligible=true`, `execution_rejection_reason=null`, `evidence` from `opportunity_json.provenance` plus `"evidence_source":"legacy_provenance"`, `"legacy_backfill":true`.

## Decision cost — frozen methodology constant

```python
# core/quant_core/historical_portfolio.py, beside METHODOLOGY_VERSION
V5_DECISION_EDGE_COST_BPS = 33.0   # pinned to deployed settings.EDGE_COST_BPS_PER_SIDE at implementation time
```

- Both the dashboard evidence path and the materializer use this literal for v5 evidence construction and winner selection. It is part of the methodology definition: **changing it requires a METHODOLOGY_VERSION bump.** Fixed methodology inputs and seeds make recomputation deterministic for an unchanged source generation; the Phase-4 source-watermark guard prevents a computation from an older generation overwriting newer rows.
- Pin the literal to the currently deployed `settings.EDGE_COST_BPS_PER_SIDE` (default 33.0, `config.py:72`) so pinning freezes today's behavior instead of changing the live dashboard. **Config-drift guard test**: `settings.EDGE_COST_BPS_PER_SIDE == V5_DECISION_EDGE_COST_BPS` — an operator changing the setting gets an explicit failure demanding a version bump, never silent divergence.
- Run-level `cost_bps_per_side` / `slippage_bps_per_side` remain runtime-configurable and apply only to portfolio fills (entries, scheduled exits, liquidations, TP/SL, performance). They never affect historical ranking or decision reconstruction.

## Execution capabilities, winner-only replay, and gates

```python
@dataclass(frozen=True)
class ExecutionCapabilities:
    allow_long: bool = True
    allow_short: bool = False
    short_signal_closes_long: bool = True
    allow_same_bar_reversal: bool = False

def execution_capabilities_for(symbol: str, universe: str) -> ExecutionCapabilities: ...
```

MASI cash equities: `ExecutionCapabilities(allow_long=True, allow_short=False, short_signal_closes_long=True, allow_same_bar_reversal=False)`.

**Winner/gate contract (replaces the re-rank-under-gates at worker :454-469, which is deleted):**
1. Exactly one `reconstructed_dashboard_winner` is persisted per (date, symbol, horizon) when the shared function finds one.
2. **Replay considers only that winner.** The other seven mode records are audit-only. Replay never recomputes candidates.
3. Run-level Edge gates (`min_edge_score`, `required_edge_conditions`, consuming `decision_json.evidence`) may veto the winner's **new entry** — nothing is traded for that key and the veto is recorded (`skip_reason="user_gate_rejected_winner"`). **A runner-up is never promoted**, including when the winner is non-executable.
4. **Liquidation ignores run-level gates**: a dashboard-actionable winning short always closes the matching long — gates control new risk, not risk reduction. A short with no existing position produces no trade regardless of gates (the non-executable decision is still recorded).

**Execution mapping — selected winner only; decisions known after close on D; actions at the next available session ≥ D+1:**

| winner | existing lot for (symbol, horizon)? | action |
|---|---|---|
| long (passes run gates) | no | `enter_long` — per stored `entry_lag_bars`/`entry_price_kind` (engine entry mechanics unchanged) |
| long (fails run gates) | no | `no_action` + recorded veto; no runner-up |
| long | yes | `hold` — never duplicate (one-live-lot) |
| short | yes (long) | `exit_long` — liquidate at next available Open (**gates not consulted**) |
| short | no | `no_action` — never create a MASI short; decision recorded as non-executable |
| *(no actionable winner)* | yes (long) | `hold` — keep the scheduled J+ exit |
| *(no actionable winner)* | no | `no_action` |

**Short-triggered liquidation contract**: executes no earlier than D+1 Open; next available Open if D+1 has no bar; normal run-level costs/slippage; cancels the lot's scheduled J+ exit and any remaining TP/SL state — exactly one exit per lot; `exit_reason="short_signal_liquidation"` + execution delay recorded; affects only the matching `(symbol, horizon)` sleeve; never reverses into a short on the same bar or any bar. Liquidations are decision-driven ⇒ present in the baseline AND every TP/SL scenario. Same-open precedence: liquidation vs TP/SL gap-fill at the same Open → identical fill price, recorded reason `short_signal_liquidation`.

**Liquidation attributability (diagnostics, not a second portfolio):**
- Run diagnostics include: count of `short_signal_liquidation` exits, their total realized P&L, and the exposure reduction they caused (liquidated notional as % of equity at fill), per horizon and total.
- **Audit-only counterfactual**: for each liquidated lot, when the originally scheduled exit date has an available price, compute the return the lot would have realized at its scheduled exit under the same run costs; report per-lot `counterfactual_scheduled_exit_return`, the delta vs the actual liquidation fill, and the aggregate `liquidation_policy_pnl_delta`. This diagnostic **never** alters cash, holdings, equity curves, canonical performance, or PIT decisions — it exists so the report can separate changes caused by PIT reconstruction from changes caused by the ratified liquidation policy. Missing later price ⇒ `counterfactual: "unavailable"`.

**Future shortable markets — declared, not implemented.** `allow_short=True` is a reserved interface. The execution-policy layer must raise `UnsupportedCapabilityError("short execution not implemented")` at policy construction if any resolved capability has `allow_short=True`. Borrow availability, borrow costs, margin, short barrier calculations, covering/reversal timing, and short-side TP/SL each require their own specified contract before that flag may become operational. No capability flag may silently enter an unimplemented branch.

## Fidelity contract

Two different guarantees; do not conflate them.

**Blocking (automated, release-gating):**
- **Live equivalence**: with identical inputs and `as_of = today`, the refactored dashboard path and the shared builder produce byte-equivalent ranking-relevant output (winner variant, direction incl. short, bucket, rank tuple inputs, actionability + reasons) across the universe. Any diff fails CI. CI runs against a **checked-in sanitized golden fixture**; it never depends on live DB contents.
- **Determinism**: identical inputs ⇒ identical outputs, twice in one process and across processes (fixed seeds).
- **PIT safety**: look-ahead sentinels — appending future-dated scores, OHLCV, or OOS rows must not change any earlier decision or `input_hash`.
- **Persisted-data correctness**: builder consumes persisted OOS rows and score history as specified; any incorrect use found by the audit (a mismatch triaged to `suspected_defect`, below) blocks release until fixed or reclassified with evidence.

**Diagnostic (reported, never a pass/fail threshold):**
- The **historical snapshot audit** compares reconstruction against the ~13 literal `DashboardSnapshot` rows. Eligible denominator = every (snapshot date, symbol, horizon) with an actionable `best_signal` (shorts included). Comparison tuple = *(variant, direction, bucket, exit_rule)* with `exit_rule = (entry_lag_bars, entry_price_kind, exit_lag_bars, exit_price_kind, return_calc_method)`; absent-from-both = match, absent-from-one = mismatch; missing reconstruction = full mismatch inside the denominator.
- The audit report contains: eligible observation count; full-tuple match count; direction match count; both match proportions; **two-sided 90% Wilson score confidence intervals** for both proportions; and one machine-readable reason per mismatch from the closed set `missing_reconstructable_input` (a live input has no persisted historical counterpart), `documented_substitute_divergence` (a named Phase-3 substitute produced a different value), `suspected_defect` (neither of the above explains it).
- **No fixed minimum N and no 90%/95% release threshold.** These proportions are diagnostic because only a limited number of literal snapshots exist and some historical inputs require documented substitutes. A small denominator is reported as *limited precision* (the Wilson interval makes this explicit) — it is neither success nor failure. Every `suspected_defect` must be triaged: confirmed defects are release-blocking via the blocking category above; the other two classes are documented limitations.
- Return-evidence sample adequacy (how many OOS observations make an edge statistically trustworthy) is a **different problem** from categorical fidelity auditing and is deferred to Rev 6.

---

## Implementation phases (dependency-ordered)

### Phase 1 — Schema, migration, serialization, and API contracts

**Prerequisites:** none. **Outputs:** migrated store, frozen JSON contracts, declared API surface.

1. Migration implementing the storage contract above: new columns (`methodology_version`, `status` + CHECK, `actionable`, `reconstructed_dashboard_winner`, `decision_json` NOT NULL, `opportunity_json` made nullable), new unique key, indexes, version backfill via `materialization_run_id → run.methodology_version`, v4 `decision_json` backfill with every key explicit.
2. Run schema: add `stop_loss_pct` (`0 < x < 1`) and `take_profit_pct` (`0 < x <= 10`) to `HistoricalPortfolioRunCreate`; both optional; validation errors are 422.
3. Universe contract: server resolves MASI as `list_signal_universe(db)` + `is_masi_dashboard_member` + active + canonical market data. Materialization always covers the full resolved universe; run-level `symbols[]` filters replay only and must be ⊆ resolved universe else 422 listing offenders; the resolved list is persisted into run and materialization configs. Requested windows clamp to supported score-history coverage; 422 if empty after clamping.
4. Ledger endpoint contract: `GET .../decisions`, declared **before** `GET /{run_id}` (router :200). Filters: `start_date, end_date, symbol, horizon, status, actionable, signal_direction, winners_only, methodology_version` (default v5). Page ≤ 200 rows. `winners_only`: v5 ⇒ `reconstructed_dashboard_winner=true` with `winner_semantics:"v5_reconstructed_dashboard_winner"`; explicit v4 ⇒ legacy `accepted=true` with `winner_semantics:"v4_legacy_accepted_edge_policy"`.

**Failure behavior:** migration is transactional; backfill failure rolls back. **Compatibility:** v4 rows preserved under their original version; `accepted` untouched; existing endpoints unchanged. **Blocking tests:** migration up/down on a copy; v4 backfill produces schema-complete `decision_json`; unique-key enforcement; 422 paths; `/decisions` route order + pagination + every filter + both `winners_only` semantics.

### Phase 2 — Versioning, deduplication, and job lifecycle

**Prerequisites:** Phase 1. **Outputs:** v5 version machinery, safe concurrent enqueues, reconciled job states.

1. Bump `METHODOLOGY_VERSION` to `...-v5` and add `V5_DECISION_EDGE_COST_BPS` beside it. v4 rows/runs are never relabeled.
2. Run deduplication/reuse requires **full normalized user-config equality** (incl. TP/SL, symbols, gates, costs). `config_json["_system"]` is reserved for server-generated materialization metadata and is removed before equality comparison; any client request containing a top-level `_system` key is rejected with 422. No `run_config_hash` column. Stored opportunity `input_hash` values are never touched by run-level config, TP/SL included.
3. Enqueue-time overlap handling: re-check under `SELECT ... FOR UPDATE` on the run table; overlapping materialization with a known `rq_job_id` ⇒ chain via RQ `depends_on`; job id not yet recorded ⇒ proceed unchained (the Phase-4 advisory lock guarantees safety).
4. Reconciliation: on list/poll, reconcile DB `queued`/`running` rows against RQ. Transition to `failed` only on authoritative signals — `NoSuchJobError` or terminal status (`failed`, `canceled`, `stopped`). A `deferred` job whose dependency terminally failed ⇒ dependent DB rows (materialization and backtest alike) `failed`; nothing stays deferred/queued indefinitely. Redis connectivity failure ⇒ skip the cycle, DB untouched. Run once at rollout: the two currently abandoned runs flip to `failed`; succeeded materializations untouched.
5. Audit — don't reimplement — the already-implemented store-first gap-fill machinery (`docs/ai/pit-store-first-portfolio-backtest.md`) against its E2E protocol; fix only failures. Log actual min/max `SignalScoreHistory` OOS dates before any seeding.

**Failure behavior:** reconciliation is idempotent and read-safe; dedup falls back to creating a new run on any comparison ambiguity. **Compatibility:** v4 audit remains reachable via explicit `methodology_version`. **Blocking tests:** NoSuchJob/terminal ⇒ failed; deferred-with-failed-dependency ⇒ failed; running/queued untouched; Redis ConnectionError ⇒ untouched; idempotence; differing TP/SL configs never reuse runs; server-generated `_system` metadata does not prevent reuse; client-supplied `_system` ⇒ 422; concurrent enqueues chain or serialize.

### Phase 3 — Shared pure as-of decision/evidence builder (frozen dashboard semantics)

**Prerequisites:** Phase 2 (constants). **Outputs:** `core/quant_core/signal_ranking.py` used by dashboard, materializer, and audits.

1. **Typed contract (pure, no DB; callers load):**

   ```python
   OosInput = OosSample | tuple[pd.Timestamp, ...]   # fold-aware (live) | explicit PIT-safe dates (historical)

   @dataclass(frozen=True)
   class AsOfInputs:
       symbol: str; horizon: str; variant: str; as_of: pd.Timestamp
       category_series: Mapping[str, pd.Series]   # French canonical keys; caller guarantees index <= as_of
       prices: pd.DataFrame | None                # OHLCV <= as_of; None => no_price_data
       oos: OosInput
       live_score: float | None                   # dashboard live score when as_of=today; None => derive from series
       decision_edge_cost_bps: float              # ALWAYS V5_DECISION_EDGE_COST_BPS — never user run costs
       mc_iterations: int; mc_seed: int           # from materialization config; defaults 500 (floor 100) / 5107

   @dataclass(frozen=True)
   class AsOfDecision:
       status: str; signal_direction: str | None
       category_scores: dict[str, float | str]; aggregate_score: float | None; bucket: str | None
       actionable: bool; actionability_reasons: list[str]; rank: tuple | None
       evidence: dict | None                      # canonical payload; non-null iff status == "evaluated"
       selection_cutoff: str | None; proof_cutoff: str | None
       selection_observations: tuple[SelectionObservation, ...]   # exits strictly < as_of; MAY be empty
       opportunity: HistoricalOpportunity | None  # complete, iff actionable (long OR short)
       computation_rejection_reasons: list[str]

   def build_asof_decision(inputs: AsOfInputs) -> AsOfDecision: ...
   ```

2. **The shared rank/actionability function is the sole rankability authority**, mirroring `_best_signal_rank` exactly (see Architecture facts): actionable bucket/direction (both directions), `n ≥ 30` and `gates.n`, positive expected return with its fallback chain, penalized fallback for missing edge score, tuple `(2 if proven else 1, rank_score, penalized, expected)`. `dashboard_builder.py` and the materializer both call it; the copies are deleted. Status precedence never decides rankability.
3. **Deterministic algorithms (named in code comments):** score at as_of = `live_score` else last aggregate value ≤ as_of (stale ⇒ `stale_score`); exit-timing selection = fold windows when `OosSample` given, else first ⌊2n/3⌋ chronological OOS dates ≤ as_of (the documented PIT substitute); proof metrics recomputed over ALL OOS observations in the selected bucket with exits strictly < as_of (mirroring `_apply_wfo_all_oos_proof_to_edge`, `dashboard_builder.py:1019`, point-in-time); every observation used has `exit_date < as_of`; shorts follow the identical path with short-direction observations; evidence computed for every `evaluated` row, neutral buckets included. Luck/label-shuffle statistics are computed exactly as the current dashboard computes them — same estimators, same adjustments, same gates; no methodological edits.
4. Wire the **blocking fidelity tests** (live equivalence on the golden fixture, determinism, config-drift guard) as permanent CI regression tests.

**Failure behavior:** expected data-quality outcomes (missing price/score data, stale score, insufficient history, or evidence construction returning no usable sample) are represented in validated inputs/return values and produce the corresponding computation status without exceptions. The pure builder contains no broad exception handler. Any exception — including `RuntimeError`, assertion failure, serialization failure, or programming error — propagates to the materialization job; the final replace-slice is not attempted, the run becomes `failed` in a separate transaction, and `error_message` preserves the exception type and message. **Compatibility:** live dashboard output is byte-identical after the refactor (that is the blocking test). **Blocking tests:** live equivalence; determinism; look-ahead sentinels; actionability parity (n<30 ⇒ `insufficient_dashboard_sample`; expected ≤ 0 ⇒ `non_positive_expectancy`; hold ⇒ `neutral_bucket`; edge_score=None with positive expectancy ⇒ actionable and ranked via penalized fallback); shorts rank; decision evidence independent of run-level costs; config-drift guard; injected unexpected builder exception ⇒ failed run with the previous ledger unchanged.

### Phase 4 — Complete PIT ledger materialization

**Prerequisites:** Phase 3. **Outputs:** grid-complete, semantically validated v5 ledger.

0. **Cost benchmark gate**: run one 90-day chunk over the full universe through the complete production path: initial normalized input load + source hash, full-grid evidence computation (shorts and neutrals included), final authoritative input reload + hash comparison, advisory-lock acquisition, delete/insert validation, and transaction commit. Persist per-stage elapsed time, input-row/hash counts, output-row count, and total elapsed time in `progress_json`. Extrapolate from the complete measured path; projected sequential full rebuild > 7 days ⇒ **stop and report** before proceeding.
1. **Explicit grid**: `resolved MASI universe × weekly decision dates (MASI index trading calendar) × DECISION_HORIZONS × 8 modes`, independent of load success — missing-data and neutral rows are real rows with real statuses. An empty grid never yields successful coverage (materializer fails the run).
2. **Concurrency and source-generation guard**: evidence computation runs unlocked. As it loads inputs and before evidence computation begins, the job hashes the normalized objects actually consumed by the builder: resolved-universe membership, weekly calendar dates, cleaned OHLCV, score-history inputs, persisted OOS inputs, and methodology version. The exact `source_watermark` contract is:
   - SHA-256 stream beginning with UTF-8 domain prefix `pit-v5-source-watermark-v1\n`;
   - one record per line with exact JSON-array shape `[family, natural_key_array, payload]`, encoded as UTF-8 canonical JSON using separators `(',', ':')`, `ensure_ascii=False`, and `allow_nan=False`;
   - records sorted by input family and normalized natural key; mappings recursively sorted by normalized key; semantic sequence order retained;
   - Unicode strings normalized to NFC; dates encoded as `{"$date":"YYYY-MM-DD"}`; datetimes converted to UTC and encoded as `{"$datetime":"YYYY-MM-DDTHH:MM:SS.ffffffZ"}`; integers and booleans remain native JSON values;
   - finite floats encoded as `{"$float":"<float.hex()>"}` (preserving negative zero); NaN, positive infinity, negative infinity, and null encoded respectively as `{"$float":"nan"}`, `{"$float":"+inf"}`, `{"$float":"-inf"}`, and `{"$null":true}`.

   Store the captured digest at `HistoricalOpportunityMaterializationRun.config_json["_system"]["source_watermark_v1"]`. `pg_advisory_xact_lock(hashtext(methodology_version))` wraps the final source recheck → delete → insert → validate → commit transaction. Under that lock, rebuild the normalized source objects for the same scope, recompute the digest, and compare it with the captured value. A mismatch rolls back without deleting or inserting ledger rows. Also reject the commit when another successful overlapping v5 materialization with a later `(created_at, id)` already exists. Only an unchanged observed source generation with no newer successful overlapping run may execute the replace-slice. The watermark detects changes observed between the two loads; it does not claim atomic locking of object-store changes occurring after the final load. The newer-successful-run guard independently prevents an older computation from overwriting a newer ledger. A source mismatch or superseded commit is marked `failed` in a **separate** transaction with `progress_json.stage="failed"`, `progress_json.failure_reason="stale_input"`, and an explanatory `error_message`; retry reloads inputs and recomputes evidence. Other validation failures are likewise marked `failed` separately with their violated invariant.
3. **Semantic validation (inside the transaction, before success):** one row per natural key, total = grid size; every row stamped with the run's version + id; `status` within the CHECK enum; `category_scores` schema complete; `status='evaluated'` ⇒ `evidence` non-null; `actionable` ⇒ (`status='evaluated'` ∧ `actionability_reasons=[]` ∧ `opportunity_json` non-null); ¬`actionable` ⇒ `opportunity_json` null; ≤ 1 winner per (date, symbol, horizon) and every winner actionable per the shared function; Edge-policy field equality between `decision_json.evidence` and `opportunity_json.provenance` on actionable rows; `evidence.decision_edge_cost_bps == V5_DECISION_EDGE_COST_BPS` on every evaluated row; `input_hash` recomputes identically for a deterministic sample of `min(200, all)` rows.
4. **Winner stamping**: `reconstructed_dashboard_winner` via `build_asof_decision` + the shared function over all 8 modes; shorts fully eligible.
5. Full rebuild over actual score-history coverage (subject to gate 0).

**Failure behavior:** any validation, source-watermark, or supersession failure ⇒ atomic rollback with no ledger mutation + `failed` run in a separate transaction; diagnostics name the violated invariant or `failure_reason="stale_input"`. **Compatibility:** v4 rows remain untouched by the replace-slice (version in the delete predicate). **Blocking tests:** grid completeness incl. `no_price_data`/`no_score_data` rows; status-precedence determinism; every stored candidate deserializes through `_opportunity_from_json` unchanged; validation-failure rollback + failed-run transition; **PostgreSQL advisory-lock integration tests** (pytest marker; SQLite cannot exercise advisory locks) proving both normal serialization and that an older computation from a different source generation cannot overwrite a newer ledger; source-watermark stability for unchanged inputs; source-watermark change for every covered input family; replace-slice version isolation; `input_hash` stability sentinel.

### Phase 5 — Portfolio replay through execution capabilities

**Prerequisites:** Phase 4. **Outputs:** winner-only replay with MASI execution policy, TP/SL overlay, liquidation diagnostics.

1. **Winner-only replay** per the winner/gate contract above; the old re-rank path (worker :454-469) is deleted; replay loads winners (plus existing-lot state for `hold` continuity), applies run gates to the winner only, routes through `ExecutionCapabilities` + the mapping table, and executes liquidations gate-free. Persist the event ledger at `HistoricalPortfolioBacktestRun.diagnostics_json["execution_events_v1"]` with one baseline event per replayed `(decision_date, symbol, horizon)` key, including keys with no winner or trade; barrier-scenario events are added only when that scenario's action differs. Every event has all keys present: `methodology_version`, `scenario` (`baseline|barrier`), `decision_date`, `action_date`, `symbol`, `horizon`, `winner_variant`, `signal_direction`, `actionable`, `execution_eligible`, `execution_action` (`enter_long|hold|exit_long|no_action|skip`), `reason`, `position_before` (`flat|long`), `position_after` (`flat|long`), `opportunity_input_hash`, `fill_price`, `quantity`, `notional`, and `delay_sessions`; unavailable values are null. This ledger is the authoritative source for execution actions, vetoes, delays, skips, and liquidation attribution; `trades_json` remains the source for completed trade economics.
2. **TP/SL barrier overlay** on frozen decisions: evaluation strictly after the entry bar, strictly before the scheduled exit date (entry bar: conservative skip; exit day: stored exit executes). Gap through barrier → fill at Open; else intraday Low ≤ stop → stop level, High ≥ TP → TP level; both touched same bar unresolved → stop wins. Early fill cancels the scheduled exit — exactly one exit; cash reconciles. Missing bar → skip, resume; no bars left → engine's existing exit handling. Costs/slippage on actual fills. Liquidations occur in baseline and scenario alike; same-open liquidation outranks barrier attribution.
3. **Response contract**: existing response fields (incl. `all_scenarios` and benchmarks) retain their names and meanings. Rev 5 adds versioned `winner_semantics` and liquidation diagnostics; barriers add a sibling `barrier_scenario` for the run's selected `capacity_fraction` only, with its config echoed. When TP/SL is absent, `barrier_scenario` is absent. Canonical performance may differ from v4 because winner-only replay and short-signal liquidation are intentional v5 behavioral changes; compatibility means existing clients can still deserialize the retained fields, not byte identity with the old response.
4. **Liquidation diagnostics + audit-only counterfactual** per the attributability contract above.

**Failure behavior:** missing prices for a winner ⇒ recorded skip with reason (never silent drop; `_load_prices`'s silent-drop behavior is surfaced as skip reasons). **Compatibility:** existing response fields remain backward-deserializable; v5 diagnostic fields are additive, and `barrier_scenario` is absent when no TP/SL is configured. **Blocking tests:** replay consumes persisted winners without reranking; long winner failing gates ⇒ no trade, veto recorded, no promotion; flat sleeve + short winner ⇒ no trade, decision recorded; long sleeve + short winner ⇒ exactly one `short_signal_liquidation` exit at next available Open, correct sleeve, no reversal, **even when the winner fails run gates**; missing next-day bar ⇒ next available Open; barrier precedence incl. same-open liquidation; scheduled-exit cancellation + cash conservation; counterfactual never changes canonical outputs; `allow_short=True` ⇒ `UnsupportedCapabilityError`; existing-field backward deserialization; `barrier_scenario` absent without TP/SL; additive liquidation-diagnostics schema validation; opportunity hashes unchanged by TP/SL.

### Phase 6 — UI, historical-fidelity audit, and drill-down

**Prerequisites:** Phase 5. **Outputs:** one canonical portfolio in the product; diagnostic audit; problematic-period report.

1. **One canonical portfolio**: the PIT panel (`PointInTimePortfolioBacktestPanel`) becomes the default `PortfolioBacktestPanel` export; the legacy `SnapshotAuditLegacyPanel` rendering is **removed from the Portefeuille tab entirely** — both the default return (:1669) and the embedded `<details>` (:1659). No second portfolio curve is exposed. (Legacy endpoint code may remain server-side; it simply has no Portefeuille rendering.) Label the curve as a PIT reconstruction under the frozen v5 methodology; do not present it as proof of edge validity.
2. **UI distinguishes the four states** for every decision row: actionable signal, dashboard winner, execution eligibility, resulting execution action (incl. `short_signal_liquidation` events and gate vetoes). Drill-down shows the winner, all 8 mode records with status + actionability reasons, the four category scores (UI translates; persistence stays French), authoritative `decision_json.evidence`, and ranking rationale. Active horizon = primary displayed sleeve; combined portfolio secondary.
3. **Historical snapshot audit** per the Fidelity contract: operational script against the live snapshot table producing the Wilson-interval report with per-mismatch reasons; CI variant against the checked-in fixture. Small denominators reported as limited precision.
4. **Problematic-period drill-down**: add the DB-backed script `scripts/audit_pit_portfolio_windows.py`. It requires `--run-id`; accepts repeatable `--window START:END` (defaults: `2024-01-01:2024-05-31` and `2024-10-01:2025-01-31`); and accepts `--output-dir` (default `results/pit-portfolio-window-audit/<run-id>/`). The destination must not already exist. The script reads persisted decisions, `diagnostics_json.execution_events_v1`, and `trades_json` only — never recomputes signals — writes all artifacts to a sibling temporary directory, validates them, then renames that directory to the destination so failures leave no partial report. It produces `summary.json`, `weekly_attribution.csv`, and `decision_details.jsonl`. Emit one row per decision week × symbol × horizon with all applicable reason flags plus one `primary_attribution` chosen by this precedence: `missing_data → actionability_rejection → no_actionable_winner → gate_veto → sizing_rejection → short_signal_liquidation → long_entry → hold_existing_exposure → flat_no_action`. Exit nonzero when the run is not `succeeded`, the destination exists, a requested window is outside ledger coverage, or required decision/event records are missing. No new API endpoint is added for this report.

**Failure behavior:** audit script failures never block materialization; they exit nonzero with an explicit error and do not leave partially published output files. **Compatibility:** `pytest services/api/tests -q`, `pytest services/worker/tests -q`, `cd frontend && npm run build` all green. **Blocking tests:** PIT panel is the default and the legacy panel is unreachable from the tab; out-of-universe symbol ⇒ 422; audit report contains Wilson intervals and machine-readable mismatch reasons; deterministic fixture runs produce the three specified JSON/CSV/JSONL artifacts; the two default windows produce week-by-week attributions from persisted ledger data alone.

---

## Acceptance — blocking vs diagnostic

**Blocking (must pass before v5 becomes the default view):**
1. No input with a timestamp after `as_of` influences any decision (sentinels: scores, OHLCV, OOS rows, evidence observations, category inputs).
2. Identical live/historical inputs ⇒ identical ranking-relevant outputs (golden-fixture CI test).
3. Complete semantic grid, including missing-data and neutral rows; all Phase-4 invariants.
4. Every candidate opportunity deserializes through existing replay code unchanged.
5. Winner-only replay: no reranking, no runner-up promotion, veto recording; liquidations ignore gates; flat-sleeve short winners create no trade; long sleeves liquidate correctly (sleeve isolation, next-available-open, barrier precedence, scheduled-exit cancellation); `diagnostics_json.execution_events_v1` contains one schema-complete baseline event per replay key and any differing barrier event.
6. Decision evidence independent of user-selected execution costs; config-drift guard green.
7. Deterministic materialization, safe under concurrent enqueues (Postgres advisory-lock integration tests); canonical source hashing is stable across process/dictionary order, repeated loads, and equivalent timezone representations; every covered decision-relevant input family changes the hash; source-watermark and newer-run guards prevent stale overwrite; failed dependencies and Redis/job failures reconcile correctly.
8. v4/v5 isolation: version-filtered APIs, `accepted` untouched, replace-slice scoped by version.
9. Full test suites + frontend build green.

**Diagnostic (reported, never gates):**
10. Historical snapshot audit: match proportions with two-sided 90% Wilson intervals, per-mismatch machine-readable reasons, limited-precision statement for small denominators. Only mismatches triaged to confirmed defects feed back into the blocking category.
11. Liquidation diagnostics + counterfactual `liquidation_policy_pnl_delta`.
12. `scripts/audit_pit_portfolio_windows.py` produces deterministic week-by-week JSON/CSV/JSONL attribution artifacts for Jan–May 2024 and Oct 2024–Jan 2025 without recomputing signals.

## Ratified product decisions

1. One canonical portfolio: the Rev 5 PIT reconstruction. No legacy curve anywhere in the Portefeuille tab. Literal snapshots are audit fixtures, not trade sources.
2. Statistical methodology frozen at current dashboard semantics, versioned v5; all statistical redesign deferred to Rev 6; Rev 5 is the unbiased baseline for measuring it.
3. MASI capabilities: `allow_long=true, allow_short=false, short_signal_closes_long=true, allow_same_bar_reversal=false`.
4. Short signals are fully evidenced, ranked, stored, and winner-eligible; execution policy — not the signal layer — prevents opening shorts.
5. Winning short over a matching long ⇒ liquidation at next available Open, exactly one `short_signal_liquidation` exit, in baseline and all scenarios; same-open attribution favors `short_signal_liquidation`; liquidation ignores run gates.
6. Winner-only replay: gates veto, never promote.
7. Frozen decision cost `V5_DECISION_EDGE_COST_BPS = 33.0`; any change requires a methodology-version bump.
8. Fidelity: live equivalence is blocking; the historical snapshot audit is diagnostic with Wilson intervals — no fixed minimum N, no fixed match-percentage release threshold.
9. Persisted category keys stay French; UI translates.
10. `accepted` is frozen v4 legacy; v5 winners live in `reconstructed_dashboard_winner`; `winner_semantics` is explicit in APIs.
11. `allow_short=true` raises `UnsupportedCapabilityError` until a dedicated short-execution contract exists.

## Public schema/API/type changes

- **DB**: `historical_trade_opportunity` — new columns `methodology_version`, `status` (CHECK), `actionable`, `reconstructed_dashboard_winner`, `decision_json`; `opportunity_json` becomes nullable; new unique key incl. version; new indexes. No changes to `HistoricalPortfolioBacktestRun` columns.
- **API**: new `GET .../decisions` (declared before `/{run_id}`); `HistoricalPortfolioRunCreate` gains `stop_loss_pct`, `take_profit_pct`; run/materialization configs persist the resolved universe; client-supplied top-level `_system` is rejected with 422; responses gain `barrier_scenario` (conditional), liquidation diagnostics, `winner_semantics`, and the versioned `diagnostics.execution_events_v1` array. The problematic-period report is a script, not an endpoint.
- **Types**: `core/quant_core/signal_ranking.py` — `AsOfInputs`, `AsOfDecision`, `OosInput`, `build_asof_decision`, shared rank/actionability function; `ExecutionCapabilities` + `execution_capabilities_for` + `UnsupportedCapabilityError`; `V5_DECISION_EDGE_COST_BPS`.

## Migration and compatibility

- v4 rows keep their original `methodology_version` (backfilled from materialization runs; literal v4 string only where the run row is missing) and are never relabeled, reinterpreted, or deleted; the v5 replace-slice filters on version.
- v4 audit queries pass `methodology_version` explicitly and get `accepted`-based winner semantics.
- The v5 rebuild is mandatory and covers actual `SignalScoreHistory` OOS coverage only, gated by the one-chunk cost benchmark and its 7-day stop condition.
- Existing response fields retain their names and meanings. Rev 5 diagnostics are additive, and `barrier_scenario` is absent when no TP/SL is supplied; v5 results are not required to match v4 because winner-only replay and short-signal liquidation intentionally change behavior.

## Implementation checklist

- [ ] P1: migration + backfills; TP/SL schema; universe resolution + 422s; `/decisions` route (order, filters, pagination, `winner_semantics`)
- [ ] P2: version bump + `V5_DECISION_EDGE_COST_BPS`; reserved server `_system` config namespace + 422; user-config normalization/dedup; FOR-UPDATE enqueue re-check + `depends_on` chaining; RQ reconciliation (+ rollout run); store-first machinery audit
- [ ] P3: `signal_ranking.py` builder + shared rank function; dashboard + materializer refactored onto it; expected-status handling with unexpected-exception propagation; golden fixture; live-equivalence, determinism, sentinel, parity, drift-guard and injected-exception tests
- [ ] P4: complete-path 90-day benchmark incl. both source loads/hashes and final transaction (stop if > 7-day projection); canonical watermark v1; stale/superseded commit rejection; advisory-lock transaction; grid materialization; semantic validation; winner stamping; full rebuild
- [ ] P5: winner-only replay (delete :454-469 path); capabilities layer + `UnsupportedCapabilityError`; schema-complete `diagnostics_json.execution_events_v1`; short-signal liquidation; TP/SL overlay + conditional `barrier_scenario`; additive liquidation diagnostics + counterfactual; existing-field backward-deserialization tests
- [ ] P6: PIT panel default + legacy panel removal; four-state UI + drill-down; Wilson-interval snapshot audit; deterministic `audit_pit_portfolio_windows.py` JSON/CSV/JSONL artifacts
- [ ] Acceptance: all blocking tests green; diagnostic reports produced and attached to the release notes
