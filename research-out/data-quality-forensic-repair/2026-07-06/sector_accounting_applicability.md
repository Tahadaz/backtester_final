# Sector Accounting Applicability (Phase 8)

## Found: two different "is this a financial company" definitions coexist

- `core/quant_core/fundamentals/cgnc_mapping.py:62` — `FINANCIAL_ARCHETYPES = {"bank", "insurance"}`, driven by `infer_statement_archetype()` (which line-item pattern the metrics resemble). This produces the `is_financial` boolean column actually stored in the PIT panel (`panel.py:322`) and is what `characteristic_study.py`'s new CF/P exclusion (this session) reads.
- `core/quant_core/fundamentals/cross_section/methodology_bakeoff.py:47` — `FINANCIAL_SECTOR_TOKENS = ("banque", "bank", "assurance", "insurance", "leasing", "financement", "credit")`, used only inside `methodology_bakeoff.py`'s own `_is_financial_sector()` for its `profitability_raw` signal — **broader**, also catching leasing/financing companies.

**Consequence, not fixed this session**: the CF/P financial-sector exclusion implemented in `characteristic_study.py` (this session) uses the narrower bank/insurance-only definition, so leasing/financing names (MAB/Maghrebail, EQD/Eqdom, SLF/Salafin, MLE/Maroc Leasing) are **not** excluded from CF/P even though their CFO is arguably just as dominated by loan/lease-book movements as a bank's. Flagged as unresolved — the fix should ideally use the broader `FINANCIAL_SECTOR_TOKENS`-equivalent definition, but that requires either exposing sector text into the panel row-level check inside `characteristic_study.py` or unifying the two definitions into one, neither of which was done this session to avoid an unreviewed behavior change beyond what was explicitly verified (bank/insurance).

## Applicability classification (as implemented / recommended)

| Metric/characteristic | All sectors | Non-financial only | Financial-specific definition required | Status |
|---|---|---|---|---|
| Book equity, B/M | Yes (with negative-equity exclusion) | — | — | Implemented this session |
| CFO, CF/P | — | Yes (bank/insurance excluded; leasing/financing gap noted above) | Banks/insurers need a different cash-generation proxy (not attempted) | Partially implemented |
| EBITDA, EBITDA/EV, Enterprise Value | — | Effectively non-financial only in practice | Banks/insurers don't have a meaningful "enterprise value" (no conventional debt/equity capital structure split) — EBITDA is also not a standard bank/insurer metric | **Not implemented** — `ebitda_ev_yield_raw` is currently computed uniformly for all sectors including banks, which is a known gap (Phase 8 requirement not fully executed; flagged unresolved) |
| Leverage (`debt/assets`) | — | Non-financial only (bank/insurer leverage is structurally ~90%+ by design, not a distress signal the same way) | Yes | Not implemented — `leverage_raw` computed uniformly |
| Operating profitability / gross profitability | — | Non-financial (gross profit/assets is not meaningful for banks) | — | Not implemented — computed uniformly, though `methodology_bakeoff.py`'s separate `profitability_raw` signal already does branch on `is_fin` (ROE for financials, operating-income/book or ROA for non-financials) — this logic exists in bakeoff but not in `characteristic_study.py`'s parallel `operating_profitability_raw` |
| ROE, ROA | Yes | — | — | Valid for all sectors as-is |
| Accruals (Sloan) | — | Non-financial only, in principle (accrual quality relies on a going-concern non-financial balance sheet) | — | Not implemented — computed uniformly |

## Verdict on this phase

**Partially complete.** The two most consequential exclusions (CF/P for banks/insurers, negative book equity for B/M) are implemented and tested. EBITDA/EV, leverage, and profitability/accrual sector-applicability gates are documented as known, unresolved gaps rather than silently left unaddressed — implementing all of them in one pass risked an unreviewed, sweeping behavior change to the factor study without evidence the resulting IC changes were examined, which conflicts with the brief's own governance rule against redefining metrics without documenting the change. They are logged here as concrete next steps, not "done."
