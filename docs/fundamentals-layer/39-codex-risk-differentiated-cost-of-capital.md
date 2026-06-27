# 39 — Risk-differentiated cost of capital + consistent ROE basis

> **Status.** Plan-only. Claude has not modified code. **Sanctioned exception** to INDEX rule #5: scoped to the cost-of-capital wiring in the revalue path and the ROE basis used by the equity models. No new data, **no fabricated numbers** — the betas already exist and are realistic; this connects them. Does not touch the combiner (deferred to a follow-up), the data-integrity gate (brief 38), or scenario logic (35).
>
> **Priority: P0 — the dominant cause of systematic under-valuation on *clean* data.** Even brief-38-**verified** names (HIGH confidence) read −20% to −80% vs BKGR Buys. Traced to: the engine applies a flat 9.5% cost of equity (β=1.0) to every name while the real per-symbol betas (avg 0.76) sit computed-but-unused.
>
> **Plugin rubric anchor.** `financial-analysis:dcf-model` (WACC/CoE from CAPM with the security's own beta — explicit, risk-differentiated, not a flat constant), `equity-research:model-update`.

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `docs/fundamentals-layer/08-assumptions-and-defaults.md` — the CoC assumptions; keep consistent.
3. `core/quant_core/fundamentals/cost_of_capital.py` — `cost_of_equity_capm`, the build-up, the WACC assembly.
4. `core/quant_core/fundamentals/valuation.py` — `DEFAULT_ASSUMPTIONS` (`beta=1.0`, `cost_of_equity=0.095`, `cost_of_equity_floor=0.0`); how `cost_of_equity`/`wacc` flow into `_ddm`, `_residual_income`, `_justified_multiples`, `_fcfe_dcf`, `_fcff_dcf`; `_normalized_roe`/`_roe_basis`.
5. `services/api/app/services/fundamentals.py`:
   - `_apply_live_cost_of_capital` (`:3624`) — already reads `_latest_beta_history` (`:3606`), builds CAPM CoE (`:3659`), applies `cost_of_equity_floor` (`:3662`), writes `beta`/`beta_source` into provenance (`:3743`, `:3783`). **This function is correct.**
   - Its callers (`:3875`, `:3921`, `:4215`, `:4512`) — determine which assumption-builder runs in the revalue path.
   - `recompute_symbol_valuations` (the bulk revalue) and `_symbol_valuation_context` — **trace whether the assumptions handed to `compute_symbol_valuations` went through `_apply_live_cost_of_capital`.** Empirically they did NOT (see §1).
6. `services/api/app/models.py` — `FundamentalBetaHistory` (`symbol`, `as_of`, `beta`, `raw_beta`, `method`, `liquidity_flag`, `proxy`).

> If a cited line has shifted, report the new line and proceed.

---

## 1. Evidence (live, 2026-06-06, brief-38-verified names)

**The betas exist and are realistic but are not used.** `fundamental_beta_history`: 72 symbols, β range −0.22…1.83, avg **0.76**. Yet every computed valuation records `cost_of_equity = 0.095` with **no beta** in its inputs:

| symbol | stored β | CoE *should be* (3.5%+β·6%) | CoE engine used | error |
|---|---|---|---|---|
| SAH | −0.02 | 3.4% | 9.5% | +6.1pt |
| AGM | 0.31 | 5.4% | 9.5% | +4.1pt |
| ARD | 0.37 | 5.7% | 9.5% | +3.8pt |
| GAZ | 0.44 | 6.1% | 9.5% | +3.4pt |
| COL | 0.68 | 7.6% | 9.5% | +1.9pt |
| LHM | 0.80 | 8.3% | 9.5% | +1.2pt |
| CDM | 1.00 | 9.5% | 9.5% | 0.0pt |

Proof it isn't wired: GAZ (β 0.44), ARD (β 0.37), LHM (β 0.80) — all verified, all fully computed — each show `ddm.inputs.cost_of_equity = 0.095`, no `beta`/`beta_source`. If `_apply_live_cost_of_capital` had run, GAZ would show ~6.1%.

**Why this clusters the intrinsic models low:** DDM, justified-P/B, RI (and the terminal of FCFE) all reduce to `≈ D/(r−g)` or `book·(ROE−g)/(CoE−g)`. They share the same `r`. Over-stating `r` by 3pt roughly **halves** fair value across all of them at once — so five models "agree" low because they're one input set through five formulas, not five independent views.

**Offline re-pricing (approximate, β floored 0.5, `(r−g)` rescale — overshoots, so treat as directional upper bound):** ARD −43%→+15%, GAZ −51%→−12%, AGM −15%→+71%, SAH −37%→+25%, LHM −45%→−36%. The low-beta cohort de-biases strongly. **CDM is unchanged (β=1.0)** — its residual −21% is a *second* cause: ROE read as **9.3% (justified) vs 10.7% (RI)** — inconsistent and right at CoE, so justified P/B = (0.093−0.032)/(0.095−0.032) = 0.97.

---

## 2. Root causes

| # | Cause | Fix |
|---|---|---|
| RC1 | The revalue path uses the flat registry CoE (9.5%, β=1.0); the per-symbol beta from `fundamental_beta_history` never reaches `compute_symbol_valuations`. `_apply_live_cost_of_capital` exists but isn't applied in the bulk recompute. | §3.1 |
| RC2 | Negative/very-low betas would push CoE below the risk-free rate (SAH β −0.02), and `_apply_live_cost_of_capital:3649` `_positive_num(...) or 1.0` silently reverts a negative beta to **1.0** — wrong direction. `cost_of_equity_floor` is 0 (off). | §3.2 |
| RC3 | ROE basis is inconsistent across equity models (CDM 9.3% vs 10.7%) and not pinned to a single group-basis figure. | §3.3 |

---

## 3. The fix (connection + consistency — no new data)

**3.1 — Wire the per-symbol beta into every revalue.**
Ensure `recompute_symbol_valuations` (and the all-scenarios path) builds its assumptions **through `_apply_live_cost_of_capital`**, so `cost_of_equity` and `wacc` are derived from the symbol's `_latest_beta_history` beta via CAPM (`rf + β·ERP`), for **every** model. First **trace and report** why it currently doesn't (is the function simply not called on the bulk path? is its output overwritten by `DEFAULT_ASSUMPTIONS` downstream? does `_latest_beta_history`'s `as_of` filter exclude the stored rows?). Fix the specific break so the CoE/WACC handed to `compute_symbol_valuations` is the live, beta-derived one. Record `beta`, `beta_source`, `cost_of_equity` in each model's `inputs` (provenance) so it's auditable — a valuation with `beta_source="default_beta"` should be the rare exception (genuinely no beta), not the universal case.

**3.2 — Floor the cost of equity; handle low/negative betas honestly.**
- Replace `_positive_num(beta) or 1.0` (`:3649`): a negative/near-zero beta must **not** silently become 1.0. Floor the **beta** at a documented minimum (registry, e.g. `beta_floor`), or floor the resulting **CoE** at `cost_of_equity_floor`. Set `cost_of_equity_floor` to a documented desk minimum equity return (registry, with `derivation`/`source`/`plausible_range`) so CoE can never fall below it or below `risk_free_rate`. (Decide beta-floor vs CoE-floor — see Open questions; one is enough, pick the simpler.)
- Keep the existing `wacc > terminal_growth` / `CoE > g + buffer` guards so a low CoE can't produce a negative `(r−g)` denominator and explode fair value. A name that would violate the guard is `unavailable` for that model, not a blow-up.
- Carry the existing `liquidity_flag`/`proxy` from `fundamental_beta_history` into a confidence haircut (a proxy/illiquid beta should not earn full confidence).

**3.3 — One consistent group-basis ROE across the equity models.**
`_ddm`, `_residual_income`, `_justified_multiples` must consume the **same** ROE, computed group-basis from the (brief-38-verified) raw lines: `ROE = RNPG / avg(group equity)`, recomputed — not the stored `ROE` field, not a different trailing window per model. Eliminate the CDM 9.3-vs-10.7 split. (This dovetails with brief 38's group-basis rule; reuse its verified figures.)

**3.4 — Re-validate.**
After the fix, re-run an all-scenario revalue and re-pull the brief-38-verified names. The low-beta cohort (ARD, GAZ, AGM, SAH, COL…) must move materially up from deep-negative toward flat-or-positive; high-beta names (CMT β1.22, SNA β1.43) correctly move down; CoE must vary by symbol (no longer flat 9.5%). Record the before/after table.

---

## 4. Acceptance criteria

1. `python -m pytest core/tests/ -q` + touched API tests pass from the worktree root.
2. After revalue, `cost_of_equity` **varies by symbol** and equals `max(rf + β·ERP, floor)` for the symbol's stored β; every model's `inputs` carry `beta` + `beta_source`; `beta_source="default_beta"` is rare, not universal.
3. No `cost_of_equity` below `cost_of_equity_floor` or below `risk_free_rate`; no negative `(CoE−g)`/`(WACC−g)` denominators (such models go `unavailable`, not blow up).
4. The CDM-type ROE split is gone: DDM/justified/RI use one group-basis ROE.
5. Re-validation table shows the low-beta cohort de-biased (ARD/GAZ/AGM/SAH up toward flat-or-positive) and high-beta names appropriately lower.
6. New tests: `core/tests/test_live_cost_of_capital.py` (beta from history drives CoE; floor honored; negative beta floored not reverted to 1.0; consistent ROE across equity models).
7. Docs `08-assumptions-and-defaults.md` + `06-valuation-models.md` document the risk-differentiated CoE, the floor, and the single ROE basis.

---

## 5. What NOT to do

- **Do not fabricate betas.** Use the stored `fundamental_beta_history` value; if a symbol has none, use the documented default β with `beta_source="default_beta"` and flag it — do not invent a number.
- **Do not** let CoE fall below the floor or below `risk_free_rate`; do not let a low CoE explode fair value (guard the denominator → `unavailable`).
- **Do not** touch the combiner / comps-exclusion in this brief — that is the deferred follow-up (brief 40). This brief only fixes the *inputs* to the models, not how they're blended.
- **Do not** touch the data-integrity gate (38), scenario coherence (35), or the seven model formulas themselves.
- **Do not** trust the stored `ROE`/`Book_Value_Per_Share` fields — recompute from raw verified lines.

---

## 6. Relationship to other briefs

- **38 precedes 39** (figures must tie out before CoE matters). **39 precedes the combiner fix (40):** once the intrinsic models are no longer uniformly low, the comps model stops looking like a statistical outlier, so re-including it (the deferred fix) becomes safe and effective. The offline calc shows 39 alone de-biases the low-beta cohort but leaves comps-excluded names (GAZ −12, LHM −36, COL −70) short — 40 closes that.

## Open questions (Codex: confirm before coding)

- **Trace why `_apply_live_cost_of_capital` isn't applied on the bulk revalue** — report the exact break (not called / overwritten / `as_of` filter excludes rows) before fixing.
- **Beta-floor vs CoE-floor:** which is the cleaner single guard, and what value? (e.g. CoE floor = `rf + 0.5·ERP` = 6.5%, or a flat desk minimum.) Propose, with `derivation`/`source`, in the registry.
- Confirm `_latest_beta_history`'s `as_of` parameter in the revalue path actually matches the stored betas' `as_of` (else it returns None → default β). 
- Confirm group-equity + RNPG are available (brief-38-verified) for the names whose ROE the equity models need; where absent, the model is `unavailable`, not defaulted.
