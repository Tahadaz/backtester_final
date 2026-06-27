# 42 — Complete FY2025 re-ingestion for the priority cohort (mandatory per-name proof-of-read)

> **Status.** Plan-only. Claude has not modified code. **Sanctioned** to touch the remediation/ingestion path and canonical-snapshot assignment. This is **not** an engine change — it is the data-acquisition step that briefs 38 and 41 specified but **did not execute** (38 corrected ~13 names; 41 fetched **0**). No fabricated numbers.
>
> **Priority: P0 — ASAP. This is the actual fix; everything downstream is blocked on it.** The ingested data is incomplete: for the bank/holding cohort there is **no complete, single-vintage FY2025 statement set anywhere in the DB** — current-year group equity is stale (2022/2023) or absent, and bank P&L (PNB/RBE/coût du risque) is scattered across other imports. No combiner/CoE/minority/canonical logic can value these names correctly because the figures don't exist in usable form. They must be **read from the official FY2025 filings**.
>
> **Plugin rubric anchor.** `equity-research:model-update` (verify/refresh actuals against the filing), `financial-analysis:audit-xls` (one complete, tied-out statement set).

---

## 0. Files Codex MUST read first (gate — confirm line numbers)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `docs/fundamentals-layer/38-codex-data-integrity-remediation.md` — the tie-out gate + the doc-read loop this brief **completes**. §3 Step A (Codex reads the filing itself) is the core; it was under-executed.
3. `services/api/scripts/remediate_fundamentals.py` — the existing correction-set vehicle; extend it to carry a **complete** statement set, not just a few ratio fields.
4. `services/api/app/models.py` — `FundamentalSourceDocument` (`source_url`), `FundamentalImport`, `FundamentalLatestSnapshot` (`is_canonical`), `FundamentalAnnualMetric`, `FundamentalDataVerification`.
5. `core/quant_core/fundamentals/integrity.py` — the T1–T7 tie-out checks the re-ingested set must pass.
6. `core/quant_core/fundamentals/minority.py` + `cgnc_mapping.py` — the label mapping the extracted figures land in.

> If a cited line has shifted, report the new line and proceed.

---

## 1. Evidence — no complete FY2025 set exists; it must be re-read

Latest year available **across all imports**, per bank:

| | group equity | RNPG | PNB |
|---|---|---|---|
| ATW | **2023** | 2025 | 2025 |
| BCP | **2022** | none | none |
| BOA | **2022** | 2025 | 2022 |
| BCI | **none** | 2025 | 2025 |
| CIH | none | none | none |

ATW's canonical import literally holds `Capitaux_propres` (consolidated) FY2025 next to `Capitaux_propres_part_du_groupe` FY**2023** and **no** PNB — an internally year-mismatched, incomplete record. Pooling imports cannot fix it (current-year group equity isn't anywhere). **The only source of the missing figures is the official FY2025 filing**, which is linked in `fundamental_source_document.source_url` and which Codex has confirmed it can fetch + parse (3,178 docs; PDF parse OK; BVC host needs the **TLS-verification-disabled fallback** that already worked).

---

## 2. Priority cohort (~20 names)

Construct as the union of, then finalize to the ~20 with the worst gaps:
- **Financials** (bank/insurance, `stock_master.sector`): ATW, BCP, BOA, BCI, CIH, CFG, WAA, ATL, SAH.
- **Material-minority verified-on-consolidated** (from brief-41 reclassification): ATW, BAL, BOA, CDM, CMA, CMT, COL, DHO, LHM, MUT, OUL, SAH, SID, ZDJ.
- **Deeply-negative verified vs a BKGR Buy** (likely mis-data): HPS, RDS, SMI, SOT, TGC, VCN, TMA, SID.

Codex re-derives and reports the final list before fetching. Do the cohort completely; do **not** sample.

---

## 3. The work — one complete, single-vintage FY2025 statement set per name

For each cohort symbol, Codex itself fetches and **reads** the official FY2025 filing(s) at `source_url` and extracts the **full** set (verbatim, with units), then writes it as one **single-vintage FY2025** record:

- **Bilan:** Total Actif; Total Passif; Capitaux propres (total); **Capitaux propres part du groupe**; **Intérêts minoritaires**; Dettes de financement; Trésorerie.
- **CPC / état des soldes:** Chiffre d'affaires (industrials) **or PNB (banks)**; EBE/EBITDA (industrials) **or RBE (banks)**; **Coût du risque (banks)**; Résultat d'exploitation; Résultat net (consolidated); **RNPG (résultat net part du groupe)**.
- **Per-share / capital:** Shares outstanding; dividend per share / payout; fiscal year + reporting basis (consolidated IFRS).
- Record per figure: **source_url + page/line + verbatim label + value + unit** (the proof-of-read artifact, §4).
- Run T1–T7 (integrity.py) on the extracted FY2025 set; it must tie out (A=L+E, equity=BVPS×shares, NI=Résultat_net, group ROE = RNPG/group equity now computable on **one** year, single vintage). Where it ties out → `verified`; persist as the symbol's canonical FY2025 import (`is_canonical`), single-vintage, so the valuation uses it.
- stockanalysis.com remains the independent cross-check; a figure the filing and stockanalysis disagree on (beyond tolerance) stays flagged, not averaged.
- Anything genuinely not in the filing (e.g. a bank that truly doesn't disclose a line) → that field `unavailable` with the reason; the name is NR only if a tie-out-critical figure is missing — never fabricated.

---

## 4. Enforcement — mandatory per-name proof-of-read (this is the point)

Briefs 38 and 41 skipped Step A by *classifying names as fine and moving on*. That escape is closed:

- For **every** priority-cohort symbol, Codex must commit a **proof-of-read artifact** (e.g. `data/corrections/fy2025/<SYMBOL>.json`) containing, per extracted figure: `source_url`, `page`, `verbatim_label`, `value`, `unit`.
- **Acceptance FAILS if any priority-cohort name lacks a proof-of-read artifact** with the Bilan group + minority lines and (for financials) the PNB/RBE/coût-du-risque lines. "Classified as no-minority / fine / skipped" is **not** an acceptable outcome for a cohort name — if the filing genuinely lacks a line, the artifact must quote the filing section showing its absence.
- No figure may enter the canonical FY2025 record without a citation in the artifact. No transcribing without a page reference; no re-running the Gemini auto-extractor as a substitute for reading.
- The capability precondition (fetch + parse, TLS-verify-disabled fallback) must be reconfirmed and reported up front; if it regresses, **stop and report** — do not silently fall back to classification.

---

## 5. Acceptance criteria

1. `python -m pytest core/tests/ -q` + touched API tests pass from the worktree root.
2. Every priority-cohort name has a committed proof-of-read artifact with the required lines (or a quoted filing section proving a line's absence).
3. After re-ingestion + revalue: ATW, BOA, BCP, BCI have **FY2025** group equity + RNPG present and **used** (group ROE = RNPG/group equity, single vintage, no consolidated fallback); banks have FY2025 PNB/RBE/coût-du-risque present and **consumed by brief-37's bank model**.
4. The cohort's headline ROE/valuation now derives from a single-vintage FY2025 tied-out set; report before/after upside per name and the BKGR overlap re-score.
5. No new pathological tails (brief-40 gate holds); names that still can't tie out from the filing are NR with a specific reason (not silently consolidated).
6. Docs `02-data-flow.md`, `13-methodology-and-sources.md`, brief 38/41 updated to note the FY2025 re-ingestion and that proof-of-read is mandatory for the cohort.

---

## 6. What NOT to do

- **Do not** classify a cohort name as "fine/no-minority/skip" to avoid reading its filing — that is the failure mode this brief exists to stop. Read the filing or report you cannot fetch it.
- **Do not** mix vintages — the canonical record is single-year FY2025; FY2023 group equity is not acceptable as the FY2025 group equity.
- **Do not** fabricate, estimate, or carry-forward a missing figure; quote the filing or mark `unavailable`/NR.
- **Do not** average filing vs stockanalysis when they disagree — flag it.
- **Do not** touch the engine math (37/39/40), the scenario logic (35), or widen the tie-out tolerances to force a pass.

## 7. Open questions (Codex: confirm before fetching)

- Reconfirm fetch+parse capability (TLS-verify-disabled fallback) and report; list any cohort `source_url` that 404s or isn't the actual FY2025 filing (resolve via the scraper's URL discovery if needed — for URL resolution only, not extraction).
- Report the finalized ~20 cohort list and, per name, how many distinct FY2025 source documents back it.
- For names with multiple FY2025 documents (e.g. RFA vs press release), state which you read and why (prefer the full RFA / états financiers).
- Confirm where the complete extracted set is persisted (extend `remediate_fundamentals.py` correction set) and how it is marked the canonical single-vintage import the valuation reads.
