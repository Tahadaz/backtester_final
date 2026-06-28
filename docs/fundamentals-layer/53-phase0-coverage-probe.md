# Phase 0 — Forward-Estimate Coverage Probe (MASI)

**Date:** 2026-06-27  
**Scope:** Which sources yield forward EPS / forward P/E for MASI-listed stocks, at what coverage, and with what access?  
**Method:** READ-ONLY. Probe scripts in `scratch/probe_attijari_cached.py`, `scratch/probe_bkgr_pdf.py`, `scratch/probe_bkgr_summary.py`. Web searches and targeted WebFetch. No DB writes.

---

## 1. Headline Verdict

**The "forward P/E off forward EPS" plan is GO — but the primary source is BKGR, a single broker, not a multi-analyst consensus.**

The BKGR stock guide (`bkgr-stock-guide-juin-2026.pdf`, 42 pages, June 2026 edition) contains explicit forward BPA (EPS) and PER for 2026e and 2027e across all 10 probe tickers and 37 total MASI names. The PDF has a parseable text layer (pypdf extracted it cleanly). This is the only source with complete, machine-readable, explicitly-labelled forward EPS covering the full MASI universe.

The Attijari morning-brief parser (existing adapter) yields only trailing actuals — zero forward BPA/PER anywhere in 261 cached PDFs. Web sources (MarketScreener, Investing.com) carry forward EPS consensus for the largest 3-5 MASI names (IAM, ATW, BCP) but are anti-bot or partially paywalled.

The plan needs one qualification: BKGR forward estimates are one analyst house's projections, not a market consensus. Use them as the primary forward anchor and document the single-source risk.

---

## 2. Per-Source Table

| Source | Reachable? | Forward EPS (BPA)? | Forward P/E? | Target Price? | Fiscal Years | MASI Coverage | Access / Notes |
|---|---|---|---|---|---|---|---|
| **BKGR stock guide PDF** (in repo) | YES — local PDF | YES — explicit 2026e / 2027e | YES | YES | 2024 / 2025 / 2026e / 2027e | 37 companies (all major MASI names) | PDF with text layer; pypdf parses cleanly. Single-broker (BMCE Capital). Published quarterly. |
| **Attijari morning briefs** (casablanca-bourse.com) | YES — 261 PDFs cached | NO — trailing actuals only | NO | NO | 2023-2026 actuals (comparison tables) | ~15 names actively covered in sample | DB adapter exists; yields RNPG/DPA/CA trailing. NOT forward. |
| **BKGR website** (bmcecapitalglobalresearch.com) | Login required | YES (in publications) | YES | YES | 2025e / 2026e / 2027e | Full MASI | Subscription-walled. Stock guides published quarterly. PDF is image or text-layer TBD for newer PDFs. |
| **MarketScreener / Zonebourse** | 403 anti-bot | YES — confirmed by search snippets | YES | YES | 2025 / 2026 / 2027 | IAM, ATW, BCP confirmed; likely 5-8 MASI | JS-rendered; 403 on WebFetch. Data exists but requires Playwright or API. Multi-analyst consensus (3-8 analysts per name). |
| **Investing.com** | Partial (free tier) | Partial — forward EPS behind paywall | Partial | YES (free) | 2026 visible in snippets | ATW, BCP confirmed; ~3 names | Premium needed for full forward EPS. Free tier shows price target + consensus rating only. |
| **StockAnalysis.com** (cbse) | YES — open | NO — no forward EPS shown | YES (fwd P/E ratio shown) | NO | Trailing only | IAM, ATW listed | Open access; shows forward P/E as a derived ratio but no analyst EPS breakdown. |
| **TradingView** (CSEMA) | YES — open | NO — only trailing EPS shown | NO forward | Price targets only | Trailing + recent actuals | IAM, ATW, BCP listed | No earnings forecast module visible for MASI. Upcoming earnings shows "—". |
| **SimplyWallSt** | 403 blocked | YES (per search snippets) | YES | YES | 2026 / 2027 | ATW confirmed; likely wider | Login-walled + anti-bot. Search confirms ATW coverage with EPS forecasts. |
| **Attijari CIB** (attijaricib.com) | YES — research notes accessible | YES — BPA in notes | YES — PER in notes | YES | 2026 / 2027 | IAM confirmed; likely 10-15 names | PDFs are scanned images (DCTDecode streams); pypdf cannot extract text. Single-broker. |
| **Zawya** | Partially reachable | NOT FOUND — news portal only | NO | NO | N/A | IAM listed | Renders as news/navigation; no financial data page accessible via WebFetch. |
| **leboursier.ma** | DNS FAILED | Unknown | Unknown | Unknown | Unknown | Unknown | DNS resolution failed from probe environment (likely geo-restricted or offline). |
| **casabourse.ma** | 403 | Unknown | Unknown | Unknown | Unknown | MASI universe | Official exchange site. 403 for company detail pages. |
| **african-markets.com** | 403 | Unknown | Unknown | Unknown | Unknown | IAM, ATW, BCP listed | 403 blocked. |
| **CDG Capital** (cdgcapitalbourse.ma) | Reachable homepage | Not found publicly | Not found | Not found | N/A | Unknown | No public research portal found. Research seems distributed privately. |
| **GuruFocus** (CAS:IAM) | 403 | Unknown | Unknown | Unknown | Unknown | IAM listed | 403 blocked. |

---

## 3. Attijari Deep-Dive

**Probe:** 30 cached PDFs scanned from `.cache/attijari_morning_briefs/` (20 from 2025–2026, 10 from 2024). 261 total cached PDFs available.

### Fiscal-Year Histogram (table-column appearances)

| Year | Count | Classification |
|---|---|---|
| 2023 | 1 | trailing actual |
| 2024 | 9 | trailing actual |
| 2025 | 8 | trailing actual (most in March–June 2026 PDFs reporting FY2025 results) |
| 2026 | 1 | trailing actual (Q1 2026 results in a brief dated April/May 2026) |
| 2027 | 0 | — |

All 2026 appearances represent **actual results published in 2026**, not forecasts. The format is always "year N-1 vs year N, Variation %" — never "year N+1e" or "2026e."

### Distinct Raw Metric Labels (parsed rows, all 30 PDFs)

```
RNPG                    — net income (group share)
Résultat net consolidé  — consolidated net income
Résultat net            — net income
DPA (DH)                — dividend per share (Moroccan stocks)
DPA (DT)                — dividend per share (Tunisian stocks)
Marge nette             — net margin
Marge opérationnelle    — operating margin
Marge RBE               — banking net interest margin
Chiffre d'affaires      — revenue
REX                     — operating profit
PNB                     — banking net banking income
RBE                     — banking gross operating income
Coût du risque          — cost of risk (banking)
```

### Forward Earnings Verdict

| Metric | Present? | Notes |
|---|---|---|
| BPA (EPS per share) | **NO — 0 occurrences** | Not a label used in morning brief format |
| PER (P/E ratio) | **NO — 0 real occurrences** | One false positive from regex match on "opérationnelle" |
| RNPG forward | **NO** | RNPG appears only for trailing actual periods |
| DPA forward | **NO** | DPA appears only as a trailing actual |
| Forward year (2026e/2027e) | **NOT PRESENT** | Year columns are always actual reporting periods |

**VERDICT:** Attijari morning briefs do NOT yield forward EPS or forward P/E. They are news flashes reporting just-released actual results in a standardised `(prior year | current year | % change)` format. The existing parser correctly extracts trailing RNPG, DPA, CA, and margins. To add forward estimates, a new adapter is needed.

---

## 4. BKGR Deep-Dive

**Source:** `bkgr-stock-guide-juin-2026.pdf` (42 pages). Probe: `scratch/probe_bkgr_summary.py`.

### Document Structure

- Pages 1-3: Cover, ticker abbreviations, synthesis table (all 37 names, current price, target, rating)
- Pages 4-41: One page per company with a financial panel
- Priced as of: **25 May 2026**

### Column Structure (per company)

```
En MAD   2024   2025   2026e   2027e
BPA      x.x    x.x    x.x     x.x
DPA      x.x    x.x    x.x     x.x
PER      x.xx   x.xx   x.xx    x.xx
D/Y      x.x%   x.x%   x.x%    x.x%
```

Most companies use `2024 | 2025 | 2026e | 2027e`. A few (where 2025 results were not yet published) use `2024 | 2025e | 2026e | 2027e`.

### Forward BPA / PER for Sample Tickers (2026e and 2027e)

| Ticker | Name | BPA 2025 | BPA 2026e | BPA 2027e | PER 2026e | PER 2027e | Target (MAD) | Rating |
|---|---|---|---|---|---|---|---|---|
| IAM | Itissalat Al-Maghrib | 7.9 | **6.3** | 6.5 | **14.7x** | 14.3x | 130 | Acheter |
| ATW | Attijariwafa Bank | 49.5 | **54.0** | 58.0 | **12.9x** | 12.1x | 910 | Acheter |
| BCP | Banque Centrale Populaire | 22.2 | **25.3** | 27.1 | **9.5x** | 8.9x | 405 | Acheter |
| LHM | Holcim Maroc | 92.6 | **94.6** | 103.1 | **19.7x** | 18.1x | 2,428 | Acheter |
| CSR | Cosumar | 7.4 | **7.2** | 9.1 | **25.4x** | 20.2x | 220 | Accumuler |
| TQM | TAQA Morocco | 41.6 | **44.0** | 47.5 | **40.9x** | 37.9x | 2,977 | Acheter |
| MNG | Managem | 252.3 | **415.3** | 388.6 | **39.9x** | 42.6x | 12,135 | Conserver |
| LBV | Label Vie | 248.8e | **272.6** | — | **14.1x** | — | 4,414 | Accumuler |
| CMA | Ciments du Maroc | 95.6 | **90.6** | 96.4 | **18.5x** | 17.4x | 2,150 | Acheter |
| SID | Sonasid | 69.7 | **85.9** | 93.6 | **24.1x** | 22.1x | 2,845 | Acheter |

*Note: LBV used 2023/2024/2025e/2026e columns; 2027e not shown for that name. BPA cross-check: BPA 2026e × PER 2026e ≈ current price in every case (verified for all 10 tickers).*

### Year-Mention Distribution

| Year token | Occurrences in full text |
|---|---|
| 2024 | 81 (actuals, baseline column) |
| 2025 | 170 (most recent actuals) |
| 2025E | 9 (a few names with pending 2025 results) |
| **2026E** | **97** |
| **2027E** | **74** |
| 2028 | 5 (narrative text only) |

**VERDICT:** BKGR is a confirmed, complete source of forward BPA (EPS) and forward PER for the MASI universe, covering 37 names with 2026e and 2027e. The PDF text layer is intact and parseable via pypdf — the probe extracted all 37 company panels successfully. This is single-broker (BMCE Capital Global Research) analyst research, not a multi-analyst consensus, but it is real, explicit, labelled forward EPS — exactly what the forward P/E plan requires.

---

## 5. Recommendation to Lead

### Source Priority

**1. BKGR stock guide PDF (build adapter first — 1-2 days effort)**

Already in repo. Text layer parses cleanly. The probe script (`scratch/probe_bkgr_summary.py`) already demonstrates correct extraction of BPA/PER/DPA for all 37 tickers. The only work needed is: (a) map company page number to ticker symbol using the target price as a join key from the synthesis table, (b) write a structured parser that outputs `(symbol, fiscal_year, is_estimate, BPA, DPA, PER, DY, target_price, rating, priced_as_of_date)` rows. No network call needed — we receive quarterly PDF updates. This is 2026e AND 2027e for all sample tickers.

**Risk:** Single-broker. If BKGR revises an estimate between quarterly publications, we will not see it. Mitigation: supplement with web source when available.

**2. MarketScreener / Zonebourse API (build second — higher effort, higher value)**

MarketScreener has multi-analyst consensus BPA for IAM (6.87 for 2026e, 7.00 for 2027e — confirmed via search snippet), ATW, and BCP. These aggregate 3-8 analysts. The site is anti-bot (403 on plain WebFetch). A Playwright-based scraper or a MarketScreener/Zonebourse data API subscription (they sell data access) would give consensus estimates. Worth pursuing for the 5-7 most liquid MASI names. Do NOT build this before the BKGR adapter — it is higher effort and narrower coverage.

**3. Attijari CIB research notes (low priority, de-scope)**

Accessible at attijaricib.com but PDFs are scanned images (not text-layer). Extracting data requires OCR. Single-broker. Covers fewer names than BKGR. De-scope for now; revisit only if BKGR PDF ceases publication.

### Plan Status: "Forward P/E off Forward EPS"

**GO.** The BKGR stock guide supplies explicit forward BPA for all 10 probe tickers for 2026e and 2027e. The forward P/E plan can be executed immediately after building the BKGR adapter.

**One re-scoping caveat:** The 37-name BKGR universe is the liquid/covered MASI universe. Smaller uncovered names (perhaps 10-15 illiquid tickers outside BKGR's universe) will have no forward EPS from any source found in this probe. For those names, fall back to trailing P/E or target-anchored valuation. Document this clearly in the forward-estimate layer logic.

**Do NOT re-scope to targets-only.** Target price alone is insufficient — it blends the analyst's P/E assumption with their EPS forecast and cannot be decomposed into a forward P/E signal without the underlying BPA. The BKGR data provides both separately. Targets-only would be a significant regression from the available evidence.

---

## Addendum (2026-06-28) — MarketScreener real-Chrome spike

Run via the Claude browser extension (real logged-in Chrome session), after the user pivoted toward genuine multi-analyst consensus. Read-only.

**Findings:**
- **MarketScreener serves a full multi-analyst forward model for Casablanca names** at `/quote/stock/<slug>--<id>/finances/` — net sales, EBITDA, EBIT, EBT, net income, net debt, CAPEX, **free cash flow**, margins, ROE/ROA, DPS, BVPS, **EPS**, share count, P/E, EV/Sales, dividend yield, for **2026e / 2027e / 2028e** plus history — and a consensus block with **# analysts, mean rating, average target price**. Initially openly viewable (no login) and **server-rendered** (estimate tables present in served HTML).
- **Cross-checks BKGR closely** (de-circularizes validation). IAM: MarketScreener EPS 2026e **6.20** vs BKGR **6.3**; P/E **14.8x** vs **14.7x**; independent target **107.67** vs BKGR **130**.
- **Critically richer than BKGR for `fcff_dcf`:** provides forward **revenue + margins + FCF**, not just EPS. So MarketScreener upgrades `fcff_dcf`; BKGR (EPS+PER) upgrades `relative_multiples`.
- **Quotes resolve by numeric ID** (slug cosmetic); Casablanca names occupy a **contiguous ID block** (CDM 1408690, CMA 1408696, CTM 1408700, HPS 1408706, LESU 1408710, IAM 1408717) → universe is enumerable by scanning the block.
- **Analyst depth varies (sample): IAM 3, HPS 3, CMA 1.** Genuine multi-analyst (≥2) is a *subset*; many names are single-analyst.

**Access reality (decisive):** MarketScreener enforces a **free-navigation quota**. After ~a dozen page/fetch hits in a session, *both* programmatic same-origin `fetch` (returns a content-stripped ~284 KB shell regardless of ID) **and** rendered navigation (redirect to `…/services/solutions/?…nopopin-freenav redirect` subscription wall) are gated. **There is no free bulk scraping.** Production ingestion therefore requires either a paid subscription/API, or a **low-rate, paced scraper** (rotating sessions, consent/session-cookie handling, on-disk cache, a few names/visit) that accretes coverage over time — NOT naive bulk fetch / not plain `curl_cffi` at volume.

**Decision taken (with user):** MarketScreener is a **tier-1 enrichment + independent cross-check** for the most liquid names (forward revenue/margin for `fcff_dcf` + non-circular consensus for validation), accessed via a **low-rate scraper within the free quota**, behind the same `ConsensusSource` interface. **BKGR remains the free, broad anchor** (37 names). The full ≥2-analyst coverage count across the BKGR-37 was not finished in-browser (quota wall) — the paced scraper will accrete it. See brief 54 for the resulting plan.

## Appendix: Probe Scripts

- `scratch/probe_attijari_cached.py` — scans 30 cached Attijari morning-brief PDFs, reports year histogram and metric labels
- `scratch/probe_bkgr_pdf.py` — extracts BPA/PER/DPA context and year mentions from BKGR PDF
- `scratch/probe_bkgr_summary.py` — structured per-page BPA/PER/DPA extraction + company page detection
