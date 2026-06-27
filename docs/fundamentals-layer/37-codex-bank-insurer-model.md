# 37 — Genuine bank / insurer valuation (equity-side, bank accounting)

> **Status.** Plan-only. Claude has not modified code. This is a **sanctioned exception** to INDEX rule #5: it adds a sector-specific path inside the financial branch of the engine (`_residual_income`, `_ddm`, `_relative_multiples`, `_justified_multiples`, the projection) and stops the ingestion fabricating industrial metrics for financials. It introduces no new data source, currency, or MCP.
>
> **Priority: P1 — methodology correctness.** Banks and insurers are currently valued as if they were industrial companies: the ingestion fabricates `EBITDA`, `EnterpriseValue`, `EV_to_EBITDA`, `Capex`, `Free_Cash_Flow` for them, and the engine projects `revenue → EBIT → capex → FCF` on line items a bank does not have. This produces the ATW residual-income = 0 and the MLE residual-income = +8,805% failures.
>
> **Plugin rubric anchor.** `financial-analysis:comps-analysis` (P/B, P/E, P/TBV for banks; **no** EV/EBITDA for financials), `financial-analysis:dcf-model` (financials valued equity-side via DDM / excess-return, discounted at cost of equity, no enterprise bridge). Decided methodology: **equity-side standard** (confirmed with maintainer).

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `docs/fundamentals-layer/06-valuation-models.md` — keep consistent; add a "financials" subsection.
3. `core/quant_core/fundamentals/cgnc_mapping.py`:
   - `BANK_FIELD_TOKENS` (`:48`), `classify(...)` returning `"bank"` (`:76`).
   - The **unconditional** derivations that fabricate industrial metrics for banks: `EBITDA = EBIT + Dotations` (`:161-162`), `Free_Cash_Flow` from CFO+investing / CFO−capex (`:173-177`), `Capex` (`:130, :138`). These run regardless of `classify`.
4. `core/quant_core/fundamentals/valuation.py`:
   - `FINANCIAL_SECTOR_TOKENS` (`:497`), `_is_financial` (`:813`).
   - `_eligible_models` (`:1268`) — already gates FCFF/FCFE **off** for financials (`:1285, :1289`); keep and extend.
   - `_relative_multiples` (`:2539`) — uses `EV_to_EBITDA` (`:2575-2615`) regardless of sector (`ev_multiple_skipped_missing_bridge` is what ATW hits).
   - `_justified_multiples` (`:2443`, `is_financial` arg `:2449`) — justified P/B = (ROE−g)/(CoE−g) already present.
   - `_residual_income` (`:2278`, `is_financial` arg) and `_ddm` — both currently consume the **industrial** projection.
   - The financial branch in the terminal-growth/CoC path (`:1728` `_is_financial(sector)` → firm path "not_used_for_financials").
5. `core/quant_core/fundamentals/projection.py` — `build_projection` and the driver block (`:184-305`, `:530-660`). The bank path forks here.
6. DB reality check (already verified): banks carry the correct line items — `PNB`, `RBE`, `Marge_RBE`, `Net_Interest_Income`, `Cout_du_risque`, `Customer_Deposits`, `Loans_Net`, `Provision_for_Loan_Losses`, `Capitaux_propres`, `ROE`, `Dividend_Payout`, `Price_to_Book`, `PER`, `Net_Income`/`RNPG` — **and also** fabricated `EBITDA`/`EV_to_EBITDA`/`Capex`/`Free_Cash_Flow` that must be suppressed for them.

> If a cited line has shifted, report the new line and proceed.

---

## 1. Principle (inherits brief 34 §1)

A bank/insurer fair value uses **only equity-side, bank-accounting** inputs. Enterprise-value metrics (EBITDA, EV/EBITDA, EV/Sales, FCFF, Capex, net-debt bridge) are **not applicable** to financials — for these names they must be **absent**, not fabricated. Every number remains Observed, Derived, or a documented registry Assumption; a missing required bank input → the dependent model is `unavailable`, never back-filled.

Why equity-side: for a bank, debt (deposits, interbank funding) is **raw material**, not financing, so "enterprise value" and "free cash flow to the firm" are meaningless. Banks/insurers are valued on **equity**: P/B vs ROE, P/E, dividend discount, and residual income (excess return over cost of equity). This is the universal desk standard.

---

## 2. The fix

**2.1 — Stop fabricating industrial metrics for financials (`cgnc_mapping.py`).**
Gate the derivations at `:130, :138, :161-162, :173-177` on `classify(...) not in {"bank","insurance"}`. For financials, **do not** synthesize `EBITDA`, `Free_Cash_Flow`, `Capex`, or a derived `EnterpriseValue`/`EV_to_EBITDA`. If the upstream feed (yfinance via `normalize_yfinance.py`) already populated those for a financial, **drop them** for bank/insurer classification (or never map them). Net effect: a bank snapshot exposes PNB/RBE/cost-of-risk/NI/equity and bank ratios (P/B, P/E), and no EV/EBITDA/FCF. Models that need EBITDA/FCF then correctly report `unavailable` for financials instead of running on a fabricated number.

> Add an `insurance` classification alongside `bank` in `classify` if not present (tokens: `assurance`, `insurance`, `takaful`). `FINANCIAL_SECTOR_TOKENS` already covers the valuation-side `_is_financial`; align the two classifiers so "bank", "insurance" are the financial sub-types.

**2.2 — Sector-aware relative multiples (`_relative_multiples`).**
For financials, the eligible ratio set is **P/B and P/E only** (banks may also use **P/PNB** if `PNB` peer medians exist — the financials analogue of P/Sales). **Exclude `EV_to_EBITDA`, `EV_to_Sales`, `Price_to_Sales`** for financials — do not attempt them, do not emit `ev_multiple_skipped_missing_bridge` for a bank (it should never be tried). Drive this from the sector classification, not the global `relative_multiple_ratio_mask`; document the per-sector ratio set in the registry meta.

**2.3 — Bank/insurer projection (`projection.py`).**
Add a financial branch to `build_projection` (or a sibling `build_financial_projection` it dispatches to when `_is_financial(sector)`), projecting the **equity-side chain** from Observed history — no revenue→EBIT→capex→FCF:
- **Bank chain:** `PNB` (top line) grows at its Observed trailing growth (same anti-seasonality rules as brief-34/horizon work) → `RBE` via Observed median `Marge_RBE` (RBE/PNB) → minus **cost of risk** at Observed median `Cout_du_risque / Loans_Net` (or /PNB) → pre-tax → net income via Observed effective tax → roll **book equity**: `BV_t = BV_{t-1} + NI_t − dividends_t`, dividends from Observed payout. No capex, no working capital, no FCFF/FCFE.
- **Insurer chain:** if premium/PNB-equivalent and combined-ratio data are absent (likely for the BVC feed), project net income from Observed median ROE × book equity and roll equity as above — i.e. drive RI/DDM directly off ROE and payout. Flag `insurer_simplified_roe_projection` so the consumer sees the simplification.
- **Every driver is Observed-median-or-unavailable** (brief 34 §1): if a bank lacks ≥N years of `Marge_RBE` or `Cout_du_risque`, fall back to peer-median (Observed) and flag, else mark the projection-dependent models `unavailable`. **No invented margins or cost-of-risk constants.**

**2.4 — RI / DDM consume the equity-side projection.**
- `_residual_income` for financials: use the bank/insurer projected book-equity and net-income path (2.3); excess return = `NI_t − CoE × BV_{t-1}`, discounted at **cost of equity**; terminal via the equity terminal-growth path already in the engine. No `max(0.0, …)` floor (brief-34 A1: non-positive → `unavailable`).
- `_ddm` for financials: Gordon / two-stage on Observed dividends, sustainable `g = retention × ROE` (already the method) using the bank's Observed ROE and payout; discount at CoE.
- Confidence is **earned** (brief-34 A2): no `is_financial → "high"`. A bank with full PNB/RBE/cost-of-risk history and agreeing models earns high confidence on the merits.

**2.5 — Eligibility matrix (extends brief-34 §B3 / `_eligible_models`).**
- **Bank:** `justified_multiples` (P/B, P/E), `relative_multiples` (P/B, P/E, P/PNB), `ddm`, `residual_income` eligible. FCFF/FCFE/reverse_dcf **not** eligible (already gated). Headline = median of eligible, non-outlier (brief-34 combiner).
- **Insurer:** same as bank minus P/PNB (use P/B, P/E + DDM + ROE-driven RI).
- Discount rate for all financial models = **cost of equity**; never WACC; no net-debt bridge (the `_is_financial` firm-path skip at `:1728` already encodes this — keep).

---

## 3. Tests

`core/tests/test_bank_valuation.py`:
- A bank fixture (PNB/RBE/Cout_du_risque/Capitaux_propres/ROE/payout present; EBITDA/EV/FCF absent) yields positive RI and DDM fair values, no `ev_multiple_skipped` warning, and headline from P/B-ROE / P/E / DDM / RI only.
- `cgnc_mapping` does **not** synthesize EBITDA/FCF/Capex for a `bank`/`insurance` classified company (assert those keys are absent).
- `_relative_multiples` for a financial uses only {P/B, P/E, (P/PNB)} and never attempts EV/EBITDA.
- A bank missing `Marge_RBE` history with no peer fallback → projection-dependent models `unavailable` (no invented margin).
- Insurer fixture without PNB → `insurer_simplified_roe_projection` path, positive fair value, flagged.
- Confidence is not auto-"high" for a thin-data financial (brief-34 A2 regression for the bank path).
- Cross-check on real names after revalue: ATW residual_income is positive and finite; no financial in the universe carries a live `EBITDA`/`EV_to_EBITDA`.

---

## 4. Acceptance criteria

1. `python -m pytest core/tests/ -q` + new tests pass from the worktree root.
2. After revalue, **no** bank/insurer has a fabricated `EBITDA`/`EV_to_EBITDA`/`Capex`/`Free_Cash_Flow` in its snapshot, and none attempts EV/EBITDA in `_relative_multiples`.
3. ATW (and other banks) produce finite, positive, equity-side fair values from RI/DDM/justified-P-B/P-E; the ATW RI=0 and MLE RI=+8,805% failures are gone.
4. Bank fair values are discounted at cost of equity, with no net-debt bridge anywhere in the financial path.
5. Every financial driver is Observed / peer-median / `unavailable` — grep proves no invented margin or cost-of-risk constant in the bank projection.
6. Docs `06-valuation-models.md` (+ `13-methodology-and-sources.md`) document the bank/insurer equity-side methodology and the suppressed-metric rule.

---

## 5. What NOT to do

- Do not value any financial on EV/EBITDA, EV/Sales, P/Sales, FCFF, or a net-debt bridge.
- Do not fabricate EBITDA/FCF/Capex/EV for financials anywhere (ingestion or engine).
- Do not assert confidence by sector (brief-34 A2).
- Do not invent margins, cost-of-risk, or growth — Observed/peer-median/`unavailable` only (brief-34 §1).
- Do not add forward consensus, embedded-value feeds, or any new data source (note EV/combined-ratio gaps as future work).
- Do not touch the non-financial path, the scenario logic (brief 35), or canonical resolution (brief 36).

## Open questions (Codex: fill in, do not improvise)

- Confirm the exact sector field available to classify bank vs insurance vs general at valuation time (`stock_master.sector`? `cgnc_mapping.classify`? the snapshot?) and that bank/insurer tags are reliable for the BVC universe. List the financial names and their resolved class before coding.
- Confirm whether peer medians for `Marge_RBE` and `Cout_du_risque` are computable from the existing `_peer_stats` cohort or need a financials-only cohort.
- Confirm whether `P/PNB` peer data exists; if not, banks use P/B + P/E only and P/PNB is dropped (do not fabricate it).
