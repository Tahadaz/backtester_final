# Brief 54 — Forward-estimate layer: consensus anchor + model forecaster (Path C)

**Status:** PLAN ONLY — no implementation yet. Discuss/approve before building.
**Owner:** TBD (likely split: BKGR adapter + wiring = Sonnet/Codex; model forecaster + validation = lead).
**Branch policy:** non-main feature branch, no PR to `origin/main` (deployed app). Backend-only.
**Predecessors:** brief 49 (consensus design, superseded on source ordering), brief 53 (Phase-0 coverage probe — the evidence base for this plan), briefs 47/48 (growth-input remediation + IC-weighted ensemble), brief 44 (bias remediation).

---

## 0. Why this brief exists (the problem, restated with evidence)

The valuation engine is **trailing/mechanical**. `relative_multiples` — one of only two positive-IC models (brief 48) — applies peer multiples to *trailing/normalized* earnings (`valuation.py:_normalized_flow_multiple`, ~line 1428: `market_cap / 3y-avg net income`). The projection layer derives forward growth from `0.5·CAGR_3y + 0.5·last-year`, faded to terminal (`projection.py:build_projection`, ~line 218-249) — extrapolation, not a forecast. Validated against the BKGR Jun-2026 scorecard the engine runs **~32pp below** the street with ~0.48 directional agreement, because BKGR values off forward 2026e/2027e EPS × target multiples. Closing that forward gap is the remaining methodology ceiling.

**Methodology decision (settled with the user):** Path **C**, sequenced **A-first** — external analyst consensus as the forward *anchor*, a model forecaster as the *fallback + independent cross-check*, blended by stated policy (not a fitted weight). Success metric = **anchor credibility primary**; return-IC is a non-degradation guardrail only, honoring brief 48's finding that valuation barely ranks 12-month returns on MASI.

## 1. What the Phase-0 probe changed (brief 53 + its 2026-06-28 MarketScreener addendum)

Two sources, two tiers:

- **BKGR stock-guide PDF — the broad, free anchor.** Explicit `BPA` (EPS) and `PER` for **2026e/2027e**, **37 MASI names**, clean text layer (pypdf, no OCR), cross-checks to ±0.2× of spot. Single broker (BMCE Capital). EPS+PER only (no revenue decomposition). → **broad fallback tier, Priority 1 to build.**
- **MarketScreener — the deep, multi-analyst tier-1 source (liquid names).** A full forward model per name (net sales, EBITDA, EBIT, net income, CAPEX, **FCF**, **EPS, DPS**, target, **# analysts**, 2026e–2028e), server-rendered, cross-checks BKGR closely (IAM EPS 6.20 vs 6.3). Provides **forward revenue + margins** → the one thing BKGR lacks. **Coverage is the liquid subset** (sample analyst depth: IAM 3, HPS 3, CMA 1 — genuine ≥2-analyst is a subset). **Access is quota-walled** (see §1b): no free bulk scraping.
- **Attijari morning briefs are trailing-only** (0 BPA across 261 PDFs). Brief 49's "Attijari-first forward" ordering is **refuted**; leave the Attijari adapter aimed at trailing actuals.

### 1a. The circularity we designed around (resolved)
BKGR is both a forward source *and* our headline benchmark. Feeding the engine BKGR forward EPS collapses the −32pp gap *by construction* — fitting, not validation. **Decision: separate anchor source from validation source.** BKGR-gap shrinkage is reported only as a *labelled sanity number* ("partly mechanical — BKGR is an input"), never the success gate. The anchor is validated against (a) **realized actuals as they print**, (b) **MarketScreener multi-analyst consensus** (now a genuine, independent cross-check — the spike confirmed it differs from BKGR, esp. on targets), and (c) the **model forecaster** as an independent third opinion / divergence flag.

### 1b. Access reality for MarketScreener (decisive constraint)
The real-Chrome spike hit MarketScreener's **free-navigation quota**: after ~a dozen hits per session, both programmatic `fetch` (content-stripped shell) and rendered navigation (redirect to subscription wall) are gated. **There is no free bulk scrape, and plain `curl_cffi`-at-volume will not work.** Decision (with user): build a **low-rate, paced scraper within the free quota** — rotating sessions, consent/session-cookie handling, on-disk cache, a few names per visit, accreting coverage over time — behind the same `ConsensusSource` interface, fully isolated so it can never block BKGR or the valuation. Quotes are **ID-addressable** and Casablanca names sit in a **contiguous ID block** (CDM 1408690 … IAM 1408717), so enumeration is cheap once inside the quota.

## 2. Architecture overview

```
                 ┌─────────────────────┐
  BKGR PDF ──────▶│  ConsensusSource    │   (Protocol; adapters are pluggable)
  (broad, free)  │  adapters            │
  MarketScreener ▶│  (BKGR ⊕ MS,        │   MS = paced scraper, liquid subset,
  (deep, quota)  │   median-reconciled) │        hard-isolated
                 └─────────┬───────────┘
                           ▼
            fundamental_consensus_estimate         ← new table, tagged is_estimate, never commingled
            (symbol, fiscal_year, metric, value,      with reported actuals
             source, as_of_date, currency, raw_label)
                           ▼
            reconcile_consensus()  (median across sources; latest per (sym,yr,metric,src) wins)
                           ▼
    service layer injects forward view into `assumptions` dict ──────────┐
                                                                          ▼
   ┌──────────────── core/quant_core/fundamentals (PURE, no DB) ─────────────────┐
   │ build_projection(): stage-1 base seeded from forward view where present     │
   │ relative_multiples: forward EPS → forward P/E (THE high-leverage upgrade)    │
   │ model forecaster [Phase 4]: forward revenue/margin/EPS; fallback + crosscheck│
   │ compute_valuation_ensemble(): UNCHANGED (brief-48 IC weights preserved)      │
   └─────────────────────────────────────────────────────────────────────────────┘
```

**Key design constraint:** `core/quant_core/fundamentals` is DB-free — it consumes plain dataclasses + an `assumptions` dict. The consensus store is read at the **service layer** and the reconciled forward view is injected via `assumptions` (same pattern as `_midcycle_basis`/peer medians already use). This keeps the core pure and unit-testable, and means the PIT backtest harness can pass a forward view explicitly.

### 2a. Which source upgrades which model (honest scoping)
The two positive-IC models (brief 48) need different inputs, and the sources now map cleanly onto them:

| Model | Needs | Best source | Fallback |
|---|---|---|---|
| `relative_multiples` (forward P/E) | forward **EPS** | BKGR (37 names) **or** MarketScreener | model forecaster |
| `fcff_dcf` stage-1 | forward **revenue + margin/FCF** | **MarketScreener only** (BKGR lacks it) | model forecaster |
| `ddm`, `residual_income` | forward **NI / dividends** | BKGR or MarketScreener | model forecaster |

So: **BKGR broadly upgrades the earnings/equity models for all 37 names; MarketScreener additionally upgrades `fcff_dcf` for the liquid subset; the model forecaster (Phase 4) backstops both wherever neither source covers** (the ~50 thin names and all pre-2026 history). This is the core Path-C argument — consensus and model upgrade *different* IC-bearing models rather than competing on one, and the two consensus sources are complementary (breadth vs depth).

## 3. Phases

### Phase 1 — Consensus store + adapter interface + BKGR adapter  (Priority 1)
**Goal:** forward EPS/PER for 37 names in a normalized, tagged store; adding a source is one adapter.
1. **Schema:** new `FundamentalConsensusEstimate` model + alembic migration, following existing `fundamental_*` table conventions (`models.py`): columns `symbol, fiscal_year, period_type, metric, value, source, as_of_date, currency, raw_label, is_estimate(server_default true), data_source(String(16))`, plus created/updated. Unique/upsert key: `(symbol, fiscal_year, metric, source)` — latest `as_of_date` wins. Metric canonical set: `EPS_Forward, NetIncome_Forward, Revenue_Forward, PER_Forward, Target_Price, Rating`.
2. **Adapter Protocol:** `class ConsensusSource(Protocol): name: str; fetch(symbols) -> list[ConsensusEstimate]`. Tiny runner fans out across enabled adapters and upserts.
3. **BKGR adapter:** generalize the brief-53 probe script into an adapter — parse the per-company panels (`2024 | 2025 | 2026e | 2027e` for BPA/DPA/PER/DY) + the synthesis table (target, rating). **Company→ticker join** is the fragile part: use the synthesis-table target price as a cross-check key + a name map; unit-test the mapping for all 37 names. `as_of_date` = guide's "priced as of" date (~2026-05-25). Emits `EPS_Forward, PER_Forward, NetIncome_Forward (=BPA×shares), Target_Price, Rating`.
4. **Reconciliation:** `reconcile_consensus()` = median across sources, keep all raw rows + contributing sources for audit. Pure function (median / source-priority / mean swappable).
5. **Tests:** BKGR parse → expected BPA/PER for ~5 named tickers; estimate-vs-actual isolation; reconciliation; upsert/latest-wins.

**Gate:** print per-source `(symbol, fiscal_year, EPS_Forward)` counts. (Known GO from brief 53; re-confirms post-implementation.)

### Phase 2 — MarketScreener paced-scraper adapter (tier-1, liquid subset)
**Goal:** genuine multi-analyst forward **revenue + margin + EPS + target + # analysts** for the liquid names, behind the same `ConsensusSource` interface, *within* the free-navigation quota — the independent source that de-circularizes validation and feeds `fcff_dcf`.
1. **Fetcher:** low-rate, paced (rotating sessions, consent/session-cookie handling, on-disk cache, a few names per visit, generous sleeps, backoff on the `nopopin-freenav` redirect). Enumerate Casablanca via the contiguous ID block; persist `(id → ticker)` map once. **Hard-isolated**: any quota/anti-bot failure is caught and logged, never propagates to BKGR or valuation.
2. **Normalize** the served finances HTML into `Revenue_Forward, NetIncome_Forward, EPS_Forward, PER_Forward, Target_Price, Rating, analyst_count` per `(symbol, fiscal_year)`; tag `source="marketscreener"`, `as_of_date` = fetch date.
3. **Coverage report:** how many BKGR-37 names reach ≥2 analysts (the tier-1 set), accreted over runs.
4. **Reconciliation now multi-source:** where BKGR and MarketScreener overlap, store both raw + a median; surface disagreement (esp. targets) rather than silently averaging.
5. **Tests:** HTML-fixture parse (saved sample), per-source isolation (simulated quota wall → no exception escapes), reconciliation with two sources.

> Effort/ToS note: paced scraping is fragile and ToS-gray; keep it isolated and cache aggressively. If it proves too brittle, the same adapter swaps to a paid feed with no change downstream.

### Phase 3 — Wire forward estimates into valuation (mechanical fallback)
1. **Forward P/E (highest leverage):** in `relative_multiples`, when reconciled `EPS_Forward` exists, value the per-share earnings base off **forward** EPS (apply peer/sector target PER to forward EPS) instead of trailing/normalized NI. Trace `_normalized_flow_multiple` → relative valuation; identify the single injection point. Keep brief-44 thin-comp + brief-31 sanity caps intact.
2. **`fcff_dcf` stage-1:** where MarketScreener `Revenue_Forward` (+ implied margin) exists, seed `build_projection` stage-1 revenue/margin from it; else model forecaster (Phase 4); else mechanical. This is the `fcff_dcf` upgrade BKGR can't provide.
3. **Earnings/equity models:** seed `ddm` near-term dividends and `residual_income` near-term NI from forward NI where present.
4. **Fallback:** no consensus for a (symbol, year) → model/mechanical path. **No coverage regression, no new N/R.**
5. **Ensemble untouched:** `compute_valuation_ensemble` + `ic_ensemble_weights.json` unchanged — change the *forward input*, not the weighting (brief-48 guardrail).
6. **PIT discipline:** a consensus value is valid only from its `as_of` forward. Live (2026+) valuation uses it; the historical PIT backtest (2021-24) has no consensus → model/mechanical path. **Implication:** the consensus path is NOT exercised by the PIT return-IC backtest — it is validated by face-validity + realized-actuals only (§5).

### Phase 4 — Model forward forecaster (the B layer)
**Goal:** an independent, *backtestable-on-forecast-accuracy* forward view. Two jobs: (a) replace the naive-CAGR fallback in `build_projection` where consensus is absent (most names/years and all pre-2026 history); (b) cross-check consensus and flag >X% divergence.
1. **Model:** lightweight next-year forecaster for revenue growth / EBIT margin / EPS from fundamentals + momentum + sector factors. Start simple (regularized cross-sectional, sector-relative mean-reversion + momentum); resist over-parameterization (only ~70 names × ~9 annual years).
2. **Validation = forecast accuracy** (the data-rich, honest part): expanding-window, predict next-year *realized* revenue/EPS, score RMSE/MAE/hit-rate **vs naive CAGR baseline**. Must beat CAGR to ship as the fallback.
3. **Wiring:** where it beats CAGR, it becomes the projection fallback (and the fcff_dcf forward revenue/margin source). Behind the same `assumptions` injection seam.

### Phase 5 — Blend policy + validation harness
1. **Blend = stated policy, not fitted weight:** MarketScreener-when-present (tier-1, multi-analyst) → else BKGR (broad) → else model → else mechanical. Record provenance per (symbol, year, metric). Surface BKGR↔MarketScreener disagreement as desk context.
2. **Validation (success = anchor credibility primary):**
   - **Anchor face-validity:** realized-actuals check (as FY2025/FY2026 actuals land, compare prior consensus forward EPS → actual; track error); spot-check brief-47 worst names (TQM, AKT, SID, MSA) for analyst-plausible forward-P/E values.
   - **Forecast accuracy:** model beats naive CAGR (Phase 3 metric).
   - **BKGR-gap shrinkage:** reported as a **labelled sanity number** ("partly mechanical — BKGR is input"), NOT a gate. Cross-check rank-agreement too.
   - **Return-IC NON-DEGRADATION guardrail:** run `pit_ic_backtest.py`; the forward upgrade (model path on history) must not *reduce* the brief-48 IC. Note explicitly that the consensus path has no PIT history to test.
3. **Full core suite green.**

## 4. Guardrails (carry forward from briefs 31/44/48/49)
- **Estimates ≠ actuals** — tagged `is_estimate`, isolated table; a forecast must never pollute reported history.
- **Per-source isolation** — one source failing never breaks others or the valuation.
- **Graceful fallback** — consensus is an upgrade, not a hard dependency; no coverage regression / no new N/R.
- **PIT discipline** — consensus valid only from `as_of` forward; never value a 2024 as-of with a 2026 estimate.
- **Preserve** brief-31 sanity caps, brief-44 thin-comp/review routing, brief-48 IC weights — change the forward *input* only.
- **Validation independence** — never validate the BKGR-fed engine against BKGR as the success gate.
- **Backend-only.**

## 5. Risks / open questions
1. **MarketScreener access fragility (biggest risk)** — free-navigation quota; paced scraper is brittle + ToS-gray and may never reach full liquid-set coverage in one pass. *Mitigated:* hard isolation, aggressive caching, accrete-over-time, BKGR covers breadth regardless, and the adapter can swap to a paid feed unchanged. **Open:** exact ≥2-analyst count across BKGR-37 (quota-walled mid-spike) — the scraper quantifies it.
2. **Single-broker BKGR** — not true consensus; circular vs benchmark. *Mitigated* by §1a validation-source separation (validate vs realized actuals + MarketScreener + model, never vs BKGR).
3. **BKGR PDF cadence/staleness** — quarterly editions; need `as_of` handling + re-parse-on-new-PDF; stale forward EPS between editions.
4. **Company→ticker join** — fragile for both BKGR (PDF name match) and MarketScreener (ID-block map); robust mapping + full-name unit tests required.
5. **Units/shares consistency** — forward BPA is MAD/share; reconcile with the engine's `Shares_Outstanding` (NI_forward = BPA × shares) so DCF/RI seeding matches; MarketScreener net income is in MAD millions.
6. **`fcff_dcf` forward dependency** — only MarketScreener (liquid subset) or the model can supply forward revenue/margin. Where neither covers, `fcff_dcf` stays mechanical (acceptable — `relative_multiples` still upgraded via BKGR).
7. **Thin estimation for the model** — ~70 names × ~9 annual years; overfitting risk. Keep it simple; forecast-accuracy gate is the discipline.

## 6. Explicitly NOT doing
- Not changing the ensemble weighting / IC machinery.
- Not claiming backtested *alpha* from the forward layer (brief 48 stands; valuation is a fair-value reference).
- Not paying for a data feed yet — paced scraper within the free quota first (adapter can swap to paid later, unchanged).
- Not touching the trailing Attijari adapter (correctly trailing-only).
- No frontend work.

## 7. Suggested sequencing & rough effort
1. **Phase 1** (schema + adapter Protocol + BKGR adapter + reconciliation) — ~1–2 days.
2. **Phase 3** wiring on BKGR only (forward-P/E + earnings models + fallback + tests) — ~1–2 days. **First shippable increment** — closes the gap for 37 names without any scraping.
3. **Phase 2** (MarketScreener paced-scraper adapter) — runs in parallel/after; accretes the liquid-set revenue+consensus; unlocks the `fcff_dcf` upgrade + de-circularized validation.
4. **Phase 4** (model forecaster + accuracy backtest) — research-paced; backstops both.
5. **Phase 5** (blend + validation harness) — ~1 day on top.

> Note the deliberate ordering: **BKGR-only wiring ships first** (Phase 1 → Phase 3 on BKGR) so the headline −32pp gap closes for 37 names with zero scraping risk; the MarketScreener scraper (Phase 2) then layers depth + independence onto the liquid subset.
