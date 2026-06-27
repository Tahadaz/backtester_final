# 41 — Expand verification coverage: fix the T4 false-NR + finish the doc-fetch for real-minority names

> **Status.** Plan-only. Claude has not modified code. **Sanctioned exception** to INDEX rule #5 only insofar as it touches `_group_basis_roe` (the ROE the equity models consume). Mostly it fixes the tie-out check `_t4_group_basis_roe` and re-runs brief-38's correction loop for a *named* short list. No fabricated numbers.
>
> **Priority: P1 — coverage.** After 38→39→40 the *shown* numbers are sane, but only **12 of 73** names are verified; **61 are NR**, and **47 of those fail on T4 (group-basis ROE) alone.** Diagnosis: 37 of the 47 have **no/immaterial minorities** — total equity *is* group equity — but T4 only accepts a separately-reported `Equity_Group` line, so it falsely NR's them. A desk tool that NR's 84% of its universe is unusable; this is the single highest-leverage coverage fix and most of it needs **no new data**.
>
> **Plugin rubric anchor.** `financial-analysis:audit-xls` (a ratio is valid when its components tie out — for a no-minority company, group = consolidated by definition), `equity-research:model-update`.

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `docs/fundamentals-layer/38-codex-data-integrity-remediation.md` — the tie-out gate + correction loop this brief extends.
3. `core/quant_core/fundamentals/integrity.py`:
   - `_t4_group_basis_roe` (`:307`) — looks up `RNPG`/`Equity_Group` aliases; returns `unavailable` when either is missing (`:333`); else compares **stored ROE** vs recomputed `RNPG/group_equity` at `pass_threshold=0.02` (`:353`). Both behaviours cause the false-NR.
4. `core/quant_core/fundamentals/valuation.py` — `_group_basis_roe` (`:1208`) and its use at `:1763`: the ROE the equity models consume must apply the **same** minority-aware fallback so check and engine agree.
5. `services/api/app/services/fundamentals.py` — `fundamental_data_verification` write path, `_data_unverified_reason`, and brief-38's correction/`source_url` re-read loop.
6. `services/api/app/models.py` — `FundamentalDataVerification`.

> If a cited line has shifted, report the new line and proceed.

---

## 1. Evidence (live, post-40, 2026-06-06)

47 names fail `t4_group_basis_roe`. Classified by whether the group/consolidated split is *material*:

| class | count | meaning | fix |
|---|---|---|---|
| **No / immaterial minority** | **37** | `Total_Equity ≈ group equity`, `Net_Income ≈ RNPG` — but the filing reports one equity line, so the `Equity_Group`/`RNPG` aliases are absent → T4 `unavailable` → false NR | **§3.1 recalibration (no new data)** |
| **Real minority** | **10** | genuinely consolidated (ATW, BOA, CMA, DHO, …); group figures are absent and must come from the filing | **§3.2 doc-fetch** |
| no total equity | 0 | — | — |

Stored ROEs on the no-minority set are plausible (CIH 11.4%, ATH 6.9%, CSR 12.2%, CMG, DWY, …). They are not corrupt — they're just not *verifiable as group-basis* by the current check, because for a single-entity company there is no group/consolidated distinction to verify.

---

## 2. Root cause

| # | Cause | Fix |
|---|---|---|
| RC1 | `_t4_group_basis_roe` requires a separately-reported `Equity_Group`/`RNPG`; a company with no minorities reports only `Capitaux_propres`/`Resultat_net`, so T4 returns `unavailable` → the gate NR's it, even though group = consolidated for that company. | §3.1 |
| RC2 | When stored ROE *is* present, T4 gates on it matching the recomputed group ROE within 2% — but the stored ROE field is unreliable (established in brief 38) and shouldn't be the arbiter; the engine should **use** the recomputed group ROE, not gate on the stored field. | §3.1 |
| RC3 | The 10 real-minority names legitimately lack group figures; brief-38's hand-read loop only covered ~13 names and skipped these. | §3.2 |

---

## 3. The fix

**3.1 — Minority-aware T4 (unlocks the ~37; no new data).**
Determine minority materiality from observed data:
- If a `Minority_Interest`/`Interets_minoritaires` line exists and `|MI| / Total_Equity > ε` **or** a reported `Equity_Group` exists with `(Total_Equity − Equity_Group)/Total_Equity > ε` → **material minority** → require the true group figures (unchanged; → §3.2 if absent).
- Otherwise (**no/immaterial minority**): by definition `RNPG = Net_Income` and `group_equity = Total_Equity`. T4 computes group ROE = `Net_Income / Total_Equity`, **passes if that ROE is finite and plausible** (T7 band), and records `t4_basis="no_minority_total_equity"`. Do **not** gate on the stored ROE field — use the recomputed value.
- `ε` is a documented registry materiality threshold (e.g. 5%), with `derivation`/`source`/`plausible_range`.
- **`_group_basis_roe` (valuation.py:1208) must apply the identical fallback**, so DDM/justified/RI consume `Net_Income/Total_Equity` for no-minority names (check and engine agree). For material-minority names it still requires the true group figures or the model is `unavailable`.

> This is correct accounting, not a fabrication: for a company without minorities, consolidated equity *is* shareholders' equity. The number isn't invented — it's the same `Total_Equity` already observed, correctly labelled.

**3.2 — Finish the doc-fetch for the ~10 real-minority names.**
> **Implementation note (Brief 42).** The FY2025 priority reingestion completes
> this deferred read loop for the priority cohort with
> `data/corrections/fy2025/<SYMBOL>.json` proof artifacts and the
> `--fy2025-reingestion` remediation mode. Real minority lines are either cited
> from the filing and tied out on group basis, or the symbol/year is left
> `data_unverified`/NR with the specific failed checks.

Run brief-38's correction loop (Codex reads the official `source_url` filing itself, extracts `RNPG` + `Capitaux propres part du groupe`, with page/line provenance) for the material-minority set: **ATW, BOA, CMA, DHO** + the rest of the 10 (Codex re-derives the full list from §3.1's classifier — do not hardcode). Tie out (T4 on true group basis) and verify; stockanalysis.com fallback; anything that still can't tie out stays NR with reason. **Confirm the capability precondition (fetch + parse) first**, same as brief 38; if unavailable, these 10 stay NR and that's reported, not faked.

**3.3 — Re-validate.**
Re-run the verification + an all-scenario revalue. Expect verified count to rise from 12 toward **~49** (37 unlocked) and up to **~59** if the 10 fetches succeed. Confirm the newly-verified names produce **sane** valuations under the post-39/40 engine (no new >+150%/<−95% tails — brief 40's gate must hold), and re-score the BKGR overlap.

---

## 4. Acceptance criteria

1. `python -m pytest core/tests/ -q` + touched API tests pass from the worktree root.
2. No name with no/immaterial minority is NR'd **solely** on T4; group ROE for those = `Net_Income/Total_Equity`, recorded with `t4_basis="no_minority_total_equity"`.
3. `_group_basis_roe` and `_t4_group_basis_roe` use the **same** minority-aware logic (check and engine cannot disagree).
4. Material-minority names are **not** silently fallen back to total equity (that would understate ROE — the inverse error); they verify from the filing or stay NR with `needs_group_figures`.
5. Verified count rises materially (target ≥45 of 73); newly-verified names carry **no** new pathological tails (40's sanity gate holds); produce a before/after verified-count + BKGR-overlap table.
6. New tests: `core/tests/test_t4_minority_aware.py` (no-minority → total-equity basis passes; real-minority without group figures → still requires them; engine ROE matches the check; immaterial-minority threshold honored).
7. Docs `38-...` + `13-methodology-and-sources.md` note the minority-materiality rule.

---

## 5. What NOT to do

- **Do not** fall back to total equity for **material-minority** names — that understates group ROE and re-introduces the consolidated/group confusion brief 38 fixed (the inverse of the BCP error). The fallback is valid **only** when minorities are genuinely immaterial.
- **Do not** fabricate or estimate group figures for the real-minority set — fetch from the filing, or NR.
- **Do not** loosen the *other* tie-out checks (T1/T2/T3/T6/T7) to raise coverage — only T4's group-basis logic changes.
- **Do not** gate on the stored ROE field — recompute and use the derived value; the stored field is a cross-check, not the arbiter.
- **Do not** touch the combiner (40), cost-of-capital (39), scenario logic (35), or the model formulas.

## 6. Relationship & what's left after

- Builds directly on **38** (same gate/loop) and is independent of 39/40 (which fixed *how verified names are valued*). 41 fixes *how many* names are verified.
- After 41, the main remaining gap is the deferred **forward-estimate decision** (trailing engine vs BKGR's forward targets on growth names like CDM −16 vs +40).

## Open questions (Codex: confirm before coding)

- Materiality threshold `ε` for "immaterial minority" — propose a value (e.g. 5% of equity) with `derivation`/`source`; show how many of the 47 land each side of it.
- RNPG fallback source for no-minority names: `Net_Income` vs `Resultat_net` (consolidated) — confirm they're equal for these names (T3 already checks this) and pick one.
- Re-derive the exact material-minority list from §3.1's classifier and report it before fetching (don't trust the indicative ATW/BOA/CMA/DHO names).
- Capability precondition for §3.2 (fetch + parse the BVC filings), same as brief 38 — report up front; if unavailable, the 10 stay NR.
