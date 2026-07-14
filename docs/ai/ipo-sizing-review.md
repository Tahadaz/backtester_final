# Review: T2S IPO Scenario & Exit-Horizon Upgrade (Codex proposal)

**Reviewer:** Claude (Fable 5) — adversarial model review, no code modified.
**Date:** 2026-07-13
**Scope inspected:** `ipo-subscription.ts`, `ipo-store.ts`, `ipo-subscription-panel.tsx`, `ipo-data.ts`, `ipo-valuation-card.tsx`, `ipo-subscription.selftest.ts`. All numbers below were produced by **running the actual production module** (`npx tsx`) with the default T2S settings (capital 500 000 MAD, retail, 3%, 12 blocked days, 5 exit sessions, `IPO_JOINT_PRESETS`).

## 0. Ground truth from executing the current model

| Quantity | Value |
|---|---|
| Mixture E[pop] | **+21.95%** |
| Per-capita caps (cold/central/hot) | 51.25 / 29.90 / 11.96 shares (round 1 never completes in any preset scenario) |
| Retail recommendation | **60 shares = 13 380 MAD**, E[alloc] 29.85 shares, satisfaction 49.8% |
| E[net profit] at Q* | **+1 134.6 MAD**, annualized ≈ 180% |
| Financing cost at Q* | 14.5–18.1 MAD per scenario (negligible) |
| Worst leaf | cold-bear: **−1 732 MAD** at joint prob 7.5%; total P(loss) = 17.25% |
| Kelly search | `fullKellyFraction = 5.0` — **the scan upper bound**, not an optimum. Log-growth is monotonically increasing on [0, 5] because E[pop] ≈ +22% vs worst loss −15%. Half-Kelly cap = 2.5 × capital = 1.25 M MAD → **never binds**. |
| Institutional at 500k | ineligible (min 13 452 shares ≈ 3.0 M MAD) |

Two structural facts drive everything: (a) the retail optimum sits at the **max per-capita cap across scenarios** (~51–60 shares), far below capital; (b) the Kelly ceiling is currently **decorative** — the recommendation would be identical without it.

## 1. What I agree with

1. **Surfacing the probability editors + auto-balance to exactly 100%.** Today `safeProbabilities` silently renormalizes whatever the user types (`ipo-subscription.ts:183-190`), so the numbers displayed in the editor are *not* the numbers used. Hidden normalization is worse than either error message or auto-balance. Displaying joint leaf probabilities and labeling everything "Hypothèse utilisateur" is right.
2. **Calendar-day financing.** Confirmed bug-class issue: `exitDays` is documented and labeled as *trading sessions* ("Séances de sortie", AMMC ±20% limit context) but is fed into a `/360` money-market formula (`ipo-subscription.ts:378`) and into annualization (`:386`). 5 sessions ≈ 7 calendar days → financing understated ~29% on the exit leg (immaterial in MAD today, but wrong by construction and it biases annualized returns).
3. **`first_executable` ≠ J1.** Vicenne and SGTM were *réservées à la hausse* at J1 — a +10% reservation with no volume is a mark, not an exit. The current single-`pop` model implicitly assumes the pop is realizable at `exitDays`; separating executable observations from reservation marks is correct.
4. **SGTM evidence expansion, and the aggregate-vs-Type-II split specifically.** The current base-rate row shows "2,94% moy." only. The official technical results give Type II satisfaction **33.48%** → Type II oversubscription ≈ **3×**, while the "hot / SGTM-like" preset uses `oversubRetail: 75`. The preset conflates *turnout* (171k subscribers — the true SGTM anchor) with *oversubscription* (which for SGTM Type II was ~3×, because the offer was 4.8 Bn MAD). The rename to "High demand — SGTM turnout anchor" plus structured per-tranche fields fixes a real confusion, not a cosmetic one.
5. **Keeping allocation mechanics untouched.** The Type II two-round iteration and Type I pro-rata code is the best-tested part of the module (self-test §1–4); horizons should only vary the return path and financing window.
6. **v4→v5 migration with `needsHorizonReview`,** and "Restore calibrated defaults" separate from capital/tranche reset.
7. **J5 as default sizing horizon,** with all horizons displayed and one explicit horizon driving the verdict.

## 2. What I disagree with

1. **27 free return parameters is assumption explosion.** 3 horizons × 9 leaves, hand-set, on an evidence base of ~6 Casablanca IPOs (half with `estimated: true`, several réservées). Nobody can calibrate `J20 | hot, bear` separately from `J5 | hot, bear`. **Change:** store **J5 as the single anchored return per leaf** (9 numbers, as today), *derive* `first_executable` mechanically from the reservation-limit regime (see §5.2), and make J20 a per-demand-state drift adjustment (3 numbers) or explicitly n.d. — 12 parameters instead of 27, and `first_executable` can never contradict the limit rules.
2. **Keeping Kelly on gross pops (the proposal leaves this as an open question — I'm answering it: no).** Evidence above: the log-growth optimum doesn't exist inside the scan range; `fullKelly = 5` is an artifact of `MAX_FRACTION`, and half-Kelly never binds. Gross pops are also the wrong distribution twice over: (a) retail engages the *requested* amount (100% coverage) while the pop accrues only on the *allocated* amount — the true return on engaged capital at Q* is pop × satisfaction − financing, roughly half the gross pop and shrinking as Q grows; (b) it ignores financing drag entirely. "Show Kelly per horizon" without fixing the distribution just multiplies a broken number by three.
3. **Pure proportional auto-balance has known pathologies.** Setting any sibling to 100% zeroes the others; lowering it back redistributes *equally* (proportions destroyed — the operation is not reversible). Sequential edits are non-commutative: editing A then B drifts A. **Change:** pin-and-lock semantics — a field the user edited stays locked (until group reset); redistribution happens proportionally among *unlocked* siblings only; equal split when unlocked weights sum to zero; exact-100 guaranteed by assigning the rounding remainder to the largest unlocked sibling. This is the standard mixer-channel pattern and it makes multi-field editing predictable.
4. **`first_executable` as a *selectable sizing horizon* should be guarded.** If the leaf's first executable observation is flagged reservation-only (no volume), sizing on it is sizing on an unachievable exit. Either exclude it from `selectedExitHorizon` or hard-warn and fall back to J5 for the verdict.
5. **Migration detail:** copying the old single pop into all three horizons produces `first_executable = +45%` in hot-bull — impossible under the ±20% session-1 limit. Since `first_executable` should be derived (see §2.1), migration should copy the pop into **J5 only**, derive `first_executable`, set J20 = J5, and flag `needsHorizonReview`. Copying an impossible number and flagging it is strictly worse than never materializing it.
6. **Day-count plumbing: use dates, not two more day-count fields.** T2S lists 27/07 but settles 31/07 — J5 (session 5 ≈ 31/07–03/08) means the allocated-amount financing leg is ~0–3 calendar days, not "5 sessions". A per-leaf `calendarFinancingDays` hand-maintained per horizon will silently disagree with `sessionNumber`. **Change:** store the deal's date anchors once (subscription close, allocation, settlement, first quote — all already known prospectus facts) and compute calendar financing days per horizon from session number + a trading-calendar helper. One source of truth, testable.

## 3. Quantitative / modeling risks

- **Bull-market prior baked into "calibrated defaults."** Every 2024–25 anchor popped; the presets put only 17.25% joint probability on a loss and E[pop] +22%. Rock (1986) is cited, but a genuine winner's-curse calibration would put the *cold* state's E[pop] near zero or negative (currently +7.1%). Add a "stress" preset (or a cold state with E[pop] ≤ 0) so users see how fast the verdict flips.
- **Hindsight bias in SGTM horizon returns:** deriving J5/J20 from SGTM's realized path and seeding them as *hot-state* defaults is fitting the hot scenario to the single most extreme observation on record. Keep SGTM facts in the evidence table; keep T2S leaf returns as labeled hypotheses.
- **`expectedAnnualizedReturn` averages annualized returns across scenarios** with different engaged-capital bases; at Q*=60 it headline-reads ≈180%/yr on a 17-day, 13.4k-MAD trade. Fine as diagnostics, misleading as a headline; prefer MAD profit + period return (already the verdict basis).
- **Probability editing + auto-balance can create false confidence:** a UI that always shows a clean 100% looks calibrated even when the inputs are vibes. The "Hypothèse utilisateur" labeling and joint-leaf display are the mitigations — keep them prominent, not collapsible-only.
- **Institutional Kelly interaction:** with coverage 0, engaged capital = allocated only, so a fixed `maxAllocatedExposureMad` translates to enormous *requested* amounts (Kelly `maxSubscriptionMad` already returns 2.99 M on 500k capital). Any Kelly fix must be per-engaged-capital or the institutional path stays unbounded in practice.

## 4. Recommended TypeScript data shape

```ts
export type IpoExitHorizon = "first_executable" | "j5" | "j20"

// Per bear/base/bull leaf. J5 is the anchored assumption; first_executable is
// DERIVED from the session-limit regime; J20 defaults to j5Return + demand-state drift.
export type IpoLeafPath = {
  j5Return: number                    // user/preset hypothesis (today's `pop`)
  j20DriftVsJ5?: number               // optional, per leaf or inherited from demand state
  needsHorizonReview?: boolean        // set by v4→v5 migration
}

export type IpoDerivedHorizonPoint = {
  horizon: IpoExitHorizon
  priceReturn: number
  sessionNumber: number               // 1-based trading session
  calendarFinancingDays: number       // computed from deal dates + sessions
  executable: boolean                 // false = reservation/mark only
}

export type IpoDealDates = {          // prospectus facts, stored once on the deal
  subscriptionClose: string           // "2026-07-17"
  allocation: string                  // "2026-07-22"
  settlement: string                  // "2026-07-31"
  firstQuote: string                  // "2026-07-27"
}

export type IpoSessionLimitRegime = { firstSessions: number; firstLimit: number; laterLimit: number }
// AMMC 23/06/2026: { firstSessions: 5, firstLimit: 0.20, laterLimit: 0.10 }

export type IpoSubscriptionSettingsV5 = Omit<IpoSubscriptionSettings, "version"> & {
  version: 5
  selectedExitHorizon: IpoExitHorizon // default "j5"
  lockedProbabilities?: Record<string, true>  // pin-and-lock auto-balance state
}
```

Historical evidence rows (`ipo-data.ts`) get the proposal's expanded structure as-is (per-tranche prices/satisfaction/counts, per-horizon observed returns with `executable` + `observed | estimated` + source URL). That part of the proposal is right; keep facts and hypotheses in different types so the UI can't blur them.

## 5. Recommended engine / data-flow changes

1. **Derive `first_executable`:** given `j5Return` and the limit regime, walk sessions: cumulative return caps at ±20% (sessions 1–5) then ±10%; the first session where the path is inside the limit (would trade rather than reserve) is `sessionNumber`, `executable = true`; if the leaf return exceeds the cumulative cap through session 1, session 1 is a reservation (`executable = false` at J1). Pure function, ~15 lines, fully testable, zero new assumptions.
2. **Calendar-day computation:** `calendarDaysBetween(settlement, sessionDate(firstQuote, sessionNumber))` with a weekend-aware helper (holidays can be ignored at this precision, documented). Blocked-leg days from close→allocation as today.
3. **Kelly on net leaf P&L per engaged capital, at the candidate Q:** for each (scenario, pop) leaf compute `r_leaf = profitMad / capitalEngagedMad` (both already computed in `subscriptionEconomics`), then maximize `Σ p·log(1 + f·r_leaf)`. It becomes Q-dependent — evaluate at each grid point and constrain the scan (cheap: grid is ≤ a few hundred points). If the optimizer still rails at the scan bound, **display "Kelly non contraignant" honestly instead of a number**. Alternatively (simpler, arguably better for a one-shot bet): replace the ceiling with a max-worst-leaf-loss budget (e.g. worst leaf ≤ x% of capital) and demote Kelly to diagnostics.
4. **Auto-balance:** pin-and-lock as in §2.3, implemented in the store layer (pure function on the settings object) so the self-test can exercise it without React.
5. **Verdict wiring:** `selectedExitHorizon` picks which derived horizon feeds `subscriptionEconomics`; allocation params untouched; the three-horizon comparison is three calls to the same engine.

## 6. Required tests (delta to the proposal's list)

Proposal's list is good; add:
- **Kelly sanity:** on the net-P&L distribution, full Kelly is finite *or* the result is flagged `railed: true` — never a silent scan-bound artifact (regression for today's `fullKelly = 5`).
- **Auto-balance:** commutativity of editing A then B vs B then A with locks; reversibility (100 → back) preserves locked values; rounding remainder lands on largest unlocked; total exactly 100 in floating point (use integer basis points internally).
- **`first_executable` derivation:** +45% leaf → session 1 reserved (non-executable), executable session ≥ 2 under {5, ±20%, ±10%}; −15% leaf → executable session 1; boundary exactly +20%.
- **Calendar days:** J5 from firstQuote 27/07/2026 (Mon) → session 5 = 31/07 (Fri) → allocated-leg financing days vs settlement 31/07 = 0; J20 spans weekends correctly.
- **Migration:** v4 blob → v5 preserves capital/tranche/coverage/probabilities; J5 = old pop; first_executable derived (not equal to pop when pop > limit); `needsHorizonReview` set; v5 round-trips idempotently.
- **SGTM row:** aggregate 2.94% and Type II 33.48% stored in distinct fields; assert the hot preset's turnout anchor (N) cites SGTM while its oversubscription does *not* claim to be SGTM's.
- Keep the existing §1–7 self-tests green unchanged (allocation mechanics must not move).

## 7. Final recommended design (deltas from the proposal)

Adopt the proposal with five changes:

1. **Leaf returns:** anchor on J5 only (9 hypotheses); **derive** `first_executable` from the AMMC session-limit regime; J20 = J5 + per-demand-state drift (3 numbers, optional). Not 27 free parameters.
2. **Kelly:** move to net, allocation- and financing-adjusted leaf P&L per engaged capital (Q-dependent), or replace the binding role with a worst-leaf loss budget; never display a scan-bound artifact as "the Kelly fraction". This is a fix the proposal only raised as a question — it should be in scope, because today the ceiling the UI advertises does nothing.
3. **Auto-balance:** pin-and-lock (locked = user-edited), proportional over unlocked only, integer-basis-point exactness. Pure proportional-over-siblings is not predictable enough for sequential edits.
4. **Dates over day-counts:** store deal date anchors once; compute per-horizon calendar financing days. Do not hand-maintain `calendarFinancingDays` per leaf per horizon.
5. **Guard `first_executable` as a sizing horizon** when the derived observation is reservation-only; verdict falls back to J5 with an explicit notice.

Everything else — visibility of probabilities, joint-leaf display, SGTM evidence structure with the official CSE/AMMC sources, the rename, v4→v5 migration with review flags, J5 default, preserved allocation mechanics, local-only persistence — approved as proposed.

---
*Next step per the agreed workflow: Codex critiques this memo and appends below; one reconciliation round; then a short decision record.*
