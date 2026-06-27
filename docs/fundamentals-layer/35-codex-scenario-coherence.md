# 35 — Scenario coherence (co-compute bear/base/bull atomically; enforce ordering)

> **Status.** Plan-only. Claude has not modified code. Scope: the recompute/revalue call paths and persistence in `services/api/app/` and the worker, plus a coherence guard in the read path. It does **not** change the seven-model engine math (that is briefs 30/31/34) — it changes *when and how the three scenarios are computed and stored together*.
>
> **Priority: P0 — correctness of what the UI shows.** A live symbol can display `base < bear == bull` because the three scenarios were computed at different times against different runs. This is a data-coherence bug, not a valuation-math bug.
>
> **Plugin rubric anchor.** `financial-analysis:dcf-model` (Bear/Base/Bull is one model run with three assumption blocks, not three independent valuations), brief 25 (per-symbol scenarios), brief 32 (base-anchored headline).

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `services/api/app/routers/fundamentals.py`:
   - `recompute_fundamentals` (`:3463`) — the universe revalue endpoint; **default `scenario="base"` recomputes base only**. This is the proximate bug.
   - `_fundamental_recompute_scenarios` (`:524`), `recompute_fundamental_signals` (`:3357`), `recompute_fundamental_betas` (`:2923` → `:2948`).
   - `_auto_scenario_from_ensembles` (`:539`) and the overlay read (`derive_research_overlay`).
3. `services/api/app/services/fundamentals.py`:
   - `VALUATION_SCENARIOS = ("bear","base","bull")` (`:68`).
   - `recompute_symbol_valuations` (`:3771`) and `recompute_symbol_valuations_all_scenarios` (`:3965`) — the latter just loops the three sequentially; nothing makes the trio atomic or stamps a shared run id.
   - `derive_research_overlay` (`:364`) and the per-scenario ensemble read (`:404-408`, filtered by `import_id` + `scenario`).
4. `services/api/app/services/weekly_recompute_policy.py` (`:27`, `:108`, `:133`) — the scheduled recompute; confirm whether it recomputes all three scenarios or base only.
5. `services/api/app/models.py` — `FundamentalEnsembleResult` (`:855`) columns, especially `computed_at`, `scenario`, `import_id`.

> If a cited line has shifted, report the new line and proceed.

---

## 1. Evidence (live, 2026-06-05)

For Managem (`MNG`), import `46bd54cb`:

| scenario | fair_value_base | models | computed_at |
|---|---|---|---|
| base | 2,817 | 4 | **2026-06-05 12:26** |
| bear | 6,750 | 6 | 2026-06-04 15:27 |
| bull | 6,750 | 6 | 2026-06-04 15:27 |

`base` was recomputed by the recent revalue; `bear`/`bull` are **stale from the previous run** and happen to be equal. Result: the UI shows `base < bear == bull`, which is nonsensical.

**The scenario math itself is fine when co-computed.** Import `2b00e6a5` (same symbol, one coherent run) shows `bear 4,303 < base 4,800 < bull 8,327` — correctly ordered and differentiated. So this brief does **not** fix scenario CAPM add-ons; it guarantees the three scenarios are always computed **together from one snapshot in one run** and never displayed mixed.

---

## 2. Root causes

| # | Cause | Fix |
|---|---|---|
| SC1 | Default revalue (`recompute_fundamentals`, `scenario="base"`) recomputes **base only**; bear/bull left stale. | §3.1 |
| SC2 | `recompute_symbol_valuations_all_scenarios` loops scenarios but does not stamp a shared run identity, so a partial/failed loop leaves a mixed-vintage trio. | §3.2 |
| SC3 | Read path assembles base/bear/bull independently by `(import_id, scenario)` with no check that they came from the same run → silently serves a mixed trio. | §3.3 |
| SC4 | No invariant test that, for one run, `fair_value(bear) ≤ fair_value(base) ≤ fair_value(bull)` (monotone in discount rate) and the trio shares a vintage. | §3.4 |

---

## 3. The fix

**3.1 — All revalue/recompute entry points compute the full trio by default.**
- In `recompute_fundamentals` (`:3463`): change the default so a revalue recomputes **all three scenarios** (`recompute_symbol_valuations_all_scenarios`) unless the caller *explicitly* asks for a single scenario for a narrow diagnostic. The "base-only" fast path must not be the default the UI/scheduler hits.
- Audit every caller of `recompute_symbol_valuations(... scenario="base")` (`:3165, :3201, :3224, :3304, :3336, :3390, :3435, :3471`) and the weekly policy: any path that refreshes a symbol for *display* must refresh the trio. A single-scenario recompute is allowed only for an explicit single-scenario request.

**3.2 — Make the trio atomic and vintage-stamped.**
- Add a shared run stamp so a base/bear/bull set is provably one computation. Two acceptable options (pick the simpler that fits the schema):
  - **(A, preferred)** Reuse `computed_at`: in `recompute_symbol_valuations_all_scenarios`, compute one `run_ts = now()` and persist all three scenarios' `computed_at = run_ts` in a single transaction; commit once at the end (all-or-nothing). No migration needed.
  - **(B)** Add a nullable `valuation_run_id UUID` column to `fundamental_ensemble_result` (+ matching column on `fundamental_valuation_result`), set identically for the three scenarios of one run. Migration `down_revision` = current head (Codex confirms).
- The build must compute the three scenarios from the **same snapshot + same base projection inputs** (scenario differences are only the CAPM add-ons / assumption overrides, per brief 25/IB-grade Phase 2). Confirm `recompute_symbol_valuations` already loads the snapshot once per call; if it reloads per scenario, hoist the load into `_all_scenarios` and pass it down (no behaviour change, just shared inputs).

**3.3 — Read path refuses a mixed-vintage trio.**
- In `derive_research_overlay` / wherever the three scenarios are read for the signal page: load all three for the canonical `import_id`, and if they do **not** share a vintage (same `computed_at` under option A, or same `valuation_run_id` under B), treat the trio as **stale** → serve the **base** scenario only, set the bear/bull band to `null`, and attach a `scenario_trio_stale` flag the UI can surface ("scénarios en cours de recalcul"). Never serve `base` from run N next to `bear/bull` from run N−1.
- Headline rating/target stay **base-anchored** (brief 32 G1) — do not let the displayed bear/bull move the headline.

**3.4 — Tests.**
`services/api/tests/test_scenario_coherence.py`:
- A universe revalue with the default arguments recomputes all three scenarios for every symbol (assert three rows per symbol share one vintage afterward).
- A symbol whose three scenarios have mismatched vintages is served base-only with `scenario_trio_stale=True`.
- Ordering invariant: for a symbol with nonzero scenario add-ons, `fair_value_base(bear) ≤ fair_value_base(base) ≤ fair_value_base(bull)` within one run. (If a model is `unavailable` in one scenario the ordering is checked on the comparable subset; document the rule.)
- Headline target == base scenario target regardless of which scenario the request selected (brief 32 G1 regression).

---

## 4. Acceptance criteria

1. `python -m pytest core/tests/ -q` + the new API tests pass from the worktree root.
2. After a full universe revalue, **no** symbol has a base/bear/bull trio spanning more than one run vintage.
3. The ordering invariant holds for all symbols with nonzero scenario add-ons; Managem specifically shows `bear ≤ base ≤ bull`.
4. The UI signal page never renders `base < bear == bull` (verified by re-pulling `fundamental_ensemble_result` for MNG and 5 other names).
5. Docs `07-ensemble-and-confidence.md` + `08-assumptions-and-defaults.md` note the atomic-trio rule and the stale-trio fallback.

---

## 5. What NOT to do

- Do not change scenario CAPM add-ons or the seven-model math (briefs 25/30/31/34 own that).
- Do not let the displayed scenario drive the headline (base-anchored only).
- Do not introduce a new currency/FX layer or external fetch.
- Do not "fix" the equal bear/bull by clamping — they will differ correctly once co-computed; if a symbol legitimately yields equal bear/bull (e.g. relative-multiple-dominated), that is allowed as long as the trio is one vintage and ordered.

## Open questions (Codex: fill in, do not improvise)

- Confirm whether option A (shared `computed_at`) is sufficient given how the read path currently sorts, or whether option B (`valuation_run_id`) is needed to disambiguate same-second writes. Report the read-path ordering before choosing.
- Confirm the weekly policy's current scenario coverage (`weekly_recompute_policy.py`) and whether it must move to the trio path.
