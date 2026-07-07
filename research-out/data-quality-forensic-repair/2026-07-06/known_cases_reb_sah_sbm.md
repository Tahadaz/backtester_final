# Forensic Findings: REB, SAH, SBM (Phase 4)

All values below pulled live from the `quant` Postgres DB on 2026-07-06 (see `duplicate_conflicts.md` for the raw query outputs). External corroboration via web search where noted.

---

## REB (Rebab Company) — B/M anomaly (~41.9)

**Classification: D — wrong field mapping (document-to-symbol mis-tagging), NOT a genuine economic extreme.**

### Root cause, confirmed exactly

`fundamental_source_document` has 228 rows tagged `symbol='REB'`. Only 39 of them (`company_name='Rebab Company'` / `'REBAB COMPANY'`) are genuinely Rebab Company filings. The other 189 are filings for four **entirely different** listed companies:

| company_name in doc row | count | real ticker |
|---|---|---|
| MAGHREBAIL | 45 | MAB |
| MAGHREB OXYGENE | 50 | MOX |
| SOCIETE DE PROMOTION PHARMACEUTIQUE DU MAGHREB S.A (Promopharm) | 43 | (not in this registry check) |
| SOCIETE MAGHREBINE DE MONETIQUE | 51 | — |

**Why REB specifically**: the ticker string `"REB"` is a literal substring of `"Maghreb"` (case-insensitive: magh**reb**ail, magh**reb** oxygène, du magh**reb**, magh**reb**ine). This is the signature of a naive substring-match (`if ticker.lower() in company_name.lower()` or equivalent) used somewhere in the BVC targeted-ingestion process (`data_source='bvc'`, filename `targeted_bvc_fundamentals_manual-all-masi-bvc-all-periods-20260603.jsonl`) to resolve "which filing belongs to symbol REB." The exact producing script was not located in the current tree in the time available (candidate: an ad-hoc/agent-driven BVC scraping session, since the source filename is tagged `manual`); this is flagged as **unresolved / needs follow-up** to find and patch the actual matching code so it cannot recur for any other short ticker that happens to be a substring of a longer company name (also check other 2-3 letter tickers, e.g. is there a ticker that's a substring of "Attijariwafa", "Managem", etc.).

### Downstream effect on the B/M anomaly

For fiscal years 2020, 2023, 2024, 2025, `fundamental_annual_metric.Total_Equity` (raw name `Capitaux_propres_YYYY`) for symbol REB is actually **Maghrebail's or Promopharm's or Maghreb Oxygène's** book equity, not Rebab's:

| Year | "REB" Total_Equity (mislabeled) | Actual source document |
|---|---|---|
| 2022 | 24,000,192.62 | doc 22 — genuinely Rebab Company FY2022 (this is why 2022 looks fine) |
| 2024 | 530,925,751.86 | doc 30 — Promopharm FY2024 |
| 2025 | 319,225,000.00 | doc 32 — Maghreb Oxygène FY2025 |
| 2020 (from separately-checked doc 78) | 921,090,000.00 | doc 78 — Maghrebail FY2022 |

The user-flagged B/M ≈ 41.9 reproduces exactly: `530,925,751.86 (mislabeled "REB" 2024 book equity, actually Promopharm) / 12,660,718 (REB's real 2024 MarketCap_Calc) = 41.93`.

### External verification of the correct value

Web search (casablancabourse.com, ilboursa.com, zonebourse.com, bourseflow.com) confirms REB currently trades around **95 MAD/share**; with 176,456 shares outstanding (consistent across every import in the DB, and consistent with `stock_master.shares_outstanding`), that implies a market cap of ≈ **16.8M MAD**, matching the DB's own `MarketCap_Calc` series (12.66M–18.53M MAD, 2024–2026) far better than the corrupted equity figures. Rebab Company's real book equity is on the order of the `stockanalysis`-sourced ~24–26M MAD figures (2020–2025), which are internally consistent and imply a plausible B/M near 1.4–1.6 — not 41.9.

**Verdict: the extreme B/M is 100% a data-pipeline bug (wrong company's filing attributed to REB), not a genuine valuation extreme.** Repair requires (1) deleting/relabeling the 189 mis-tagged `fundamental_source_document` rows and their derived `fundamental_annual_metric` rows for REB, (2) re-deriving REB's real FY2020/2023/2024/2025 book equity from the correct Rebab Company filings, (3) auditing whether the same substring-match bug corrupted any other symbol (scan below found 65 symbols with >1 distinct `company_name` under one ticker — REB is by far the worst offender; the rest are casing/formatting variants of the *same* company and are not bugs, but each was individually spot-checked only for REB in this pass — full audit of the other 64 is Phase 5/unresolved work).

---

## SAH (Sanlam Maroc, formerly Saham Assurance) — market-cap conflict (203M/265M vs 5.97B)

**Classification: B (source conflict), likely I/H (corporate-action or price-vintage mismatch) — partially resolved, not fully closed.**

Confirmed live in DB: `Shares_Outstanding` for SAH is **identical (4,116,874) across every import and every year 2021–2025**, and matches `stock_master.shares_outstanding`. So the conflict is *not* a share-count problem — it's in the price feeding `MarketCap_Calc = price × shares`:

| Year | MarketCap_Calc | Implied price (÷4,116,874) | Import / source |
|---|---|---|---|
| 2021 | 203,494,225 | ≈49.4 MAD | workbook (`485e070c` and 2 others) |
| 2021 | 5,969,000,000 | ≈1,449.9 MAD | stockanalysis (`5041cea6`) |
| 2022 | 264,896,395.5 | ≈64.3 MAD | workbook |
| Current (canonical snapshot) | 12,268,284,520 | ≈2,980 MAD | — |

External check: SAH's current live price is **2,765 MAD/share** (Bourse de Casablanca fiche, via web search), i.e. price × shares ≈ 11.4B MAD, close to the canonical snapshot's 12.27B. A ~49–64 MAD share price is implausible for this stock at any point in its recent history — SAH/Sanlam Maroc (formerly SAHAM Assurance, renamed 2022) has traded in the thousands of MAD per share. The 203M/265M figures are almost certainly built from a badly wrong or wrongly-scaled historical price input, not a real 2021–2022 valuation.

### Resolution

Checking `Price_to_Book` (also workbook-sourced, so independent of the `MarketCap_Calc`/`Shares_Outstanding` join logic) confirms the pattern is systemic, not a one-off:

| Year | workbook Price_to_Book | stockanalysis Price_to_Book | ratio |
|---|---|---|---|
| 2021 | 0.0384 | 1.13 | 29.4x |
| implied by MarketCap_Calc | 203,494,225 | 5,969,000,000 | 29.3x |

A P/B of 0.038 (i.e. trading at 3.8% of book value) is economically implausible for a solvent, licensed insurer — that level signals near-insolvency, which Sanlam Maroc was not. The ~29.3x factor recurs consistently across 2021–2024 in the same workbook import lineage, which rules out a random per-year data error and points to a **single wrong input (most likely price, possibly a wrong-vintage share count) baked into the source analyst workbook's own P/B and market-cap formula columns**, not corrected anywhere downstream because those columns are ingested verbatim (`workbook.py`) rather than recomputed from `price × shares` at read time.

**Verdict: the 203M/265M/201M `MarketCap_Calc` and associated P/B, P/S figures for SAH in the `workbook`-sourced imports (`41f6f31f`, `485e070c`, `7b152ba5`, `948a355d`, `9a065c37`, `e8645d46`) are wrong by a consistent ~29.3x factor and should not be used.** The `stockanalysis`-sourced 5.97B (2021) and the current canonical snapshot (~12.27B) are far more consistent with the real share count (4,116,874, confirmed stable everywhere) and the real current price (2,765 MAD, confirmed via Bourse de Casablanca). Repair: for SAH, prefer `stockanalysis`/canonical-snapshot market cap over `workbook` market cap for all years; do not delete the workbook rows (preserve for provenance/conflict log) but exclude them from any live factor computation via the duplicate-resolution hierarchy. **Not yet done**: identifying the exact wrong number in the source Excel file itself (would require opening `fundamental_data_all_structured_market_formula_factors*.xlsx` directly, which was not done this session), and checking whether the same ~29x-style systemic workbook error recurs for any other symbol (only SAH was checked).

---

## SBM (Société des Boissons du Maroc) — EBITDA/EV yield anomaly

**Classification: E — enterprise-value construction bug, confirmed.**

Confirmed live in DB for fiscal year 2023 (import `41f6f31f`/`485e070c`/etc.):

```
Total_Debt (2023)      = 224,580,000
Cash       (2023)       = 145,890,000
Total_Debt - Cash        = 78,690,000
EnterpriseValue (2023)  = 78,689,000   <- matches Total_Debt - Cash almost exactly
```

The stored `EnterpriseValue` for 2023 is just **net debt alone** — the market-cap term was never added. Correct EV should be `MarketCap_Calc (2023) + Net_Debt (2023)`; with the stockanalysis-sourced 2023 market cap of 6,387,000,000 and Net_Debt of -944,860,000 (net cash position), the economically correct EV is closer to **~5.44B**, not 78.7M — a ~69x understatement. Any EBITDA/EV yield computed against the 78.7M figure for 2023 would be wildly overstated (this is very likely the origin of the flagged ~28.2% figure, though the exact combination of EBITDA-year and EV-year that produces exactly 28.2% was not isolated in this pass — flagged for the extreme-value audit, Phase 5).

External check: current SBM EBITDA ≈648.4M MAD, market cap ≈5.94B MAD (Zonebourse/Boursenews), consistent with the DB's own 2025 figures (EBITDA 523.75M, MarketCap_Calc 5,942,271,300) — the *current-year* figures in the DB look economically sane; the bug is specifically in how one or more **historical years'** EV was constructed (net-debt-only, market-cap term dropped), not a global mis-definition.

**Verdict: genuine EV-construction defect for at least FY2023; needs a systematic re-check of every symbol/year where `EnterpriseValue ≈ Total_Debt - Cash` (i.e., market cap silently 0/missing at computation time) — this is a mechanical SQL check, not yet run across the full universe (Phase 5/6 follow-up).**
