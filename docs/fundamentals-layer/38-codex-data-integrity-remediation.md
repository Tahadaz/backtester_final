# 38 — Data integrity remediation (tie-out gate + source re-verification)

> **Status.** Plan-only. Claude has not modified code. Scope: a reconciliation/tie-out engine; a correction pipeline in which **Codex itself fetches and reads the official source documents** (linked in `fundamental_source_document.source_url`) for the defective stocks and extracts the figures by hand, with **stockanalysis.com** as the independent second source; and a hard gate so the valuation engine never runs on figures that do not tie out. No seven-model engine math change.
>
> **Priority: P0 — PREREQUISITE. Run before trusting any output of briefs 34–37.** The valuation engine produces garbage (BCP −46% with high value+quality scores; STROC +6,000%; LHM ROE 1,386%) because the **input data is corrupt**, not because the math is wrong. No downstream fix matters until the inputs tie out.
>
> **Plugin rubric anchor.** `financial-analysis:audit-xls` (balance-sheet integrity: A = L + E, cash tie-out, NI link; one source of truth, recompute don't trust), `equity-research:model-update` (verify actuals against the filing).

---

## 0. Files Codex MUST read first (gate — confirm line numbers/symbols)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding rules.
2. `docs/fundamentals-layer/22-codex-3statement-integrity.md` + `core/quant_core/fundamentals/integrity.py` — the existing integrity checks (A=L+E, cash tie-out, NI link). **Extend these; do not fork.**
3. `services/api/app/models.py`:
   - `FundamentalSourceDocument` (`:629`) — **`source_url` (NOT NULL) is the link to the official company financial doc**, with `symbol`, `fiscal_year`, `period_type`, `document_kind`, `raw_json`, `status`. This is the asset that makes re-verification possible.
   - `FundamentalLatestSnapshot`, `FundamentalAnnualMetric`, `FundamentalEnsembleResult`.
4. `services/worker/tasks/targeted_bvc_fundamentals.py` — re-extracts BVC fundamentals; note it **shells out to the separate scraper repo** (`fama french`, `_python_executable(fama_dir)` `:104`) and needs the **Gemini API key** (user-supplied, never persisted). Per-symbol targeting via `_stock_rows` (`:42`)/`_target_company_terms` (`:70`).
5. `services/worker/tasks/refresh_stockanalysis_fundamentals.py` — per-symbol ingest via `StockAnalysisFundamentalProvider`; **in-repo, no external key** (HTTP to `https://stockanalysis.com/quote/cbse/{symbol}`). `_selected_stocks(db, symbols)` (`:40`).
6. `core/quant_core/fundamentals/cgnc_mapping.py` — the line-item mapping (where total-vs-group / units errors are introduced).
7. `services/api/scripts/dedup_fundamental_metrics.py` — existing cleanup script; match its CLI style.

> If a cited line has shifted, report the new line and proceed.

---

## 1. Evidence — the data is the disease (audit of 73 names, 2026-06-05)

≥21/73 names trip a hard internal inconsistency; the true rate is higher because the audit only catches *contradictions* (it can't see a silently-wrong single value, and the engine also blends a separate **snapshot** copy that disagrees with the annual history). Four defect classes, with proof:

| Class | Example | Proof |
|---|---|---|
| **Scale / units error** | LHM equity = 156M but NI = 2,166M → ROE **1,386%** (real equity ~12B = BVPS 521 × 23.4M sh); COL equity = 15.9B vs market cap ~1.3B (P/B 0.08, impossible); STR `Net_Income` 1.16B vs `Resultat_net` 0.5M (2,300×) | stored numbers off by 47×–2,300× |
| **Group vs consolidated basis** | BCP ROE used = 7.1% (group NI ÷ **consolidated** equity incl. ~25B minorities); group basis = ~12% → flips the sign. 9 names with >15% minority gap (CDM, CMT, JET, LBV, M2M, MDP, MSA, SAH, TQM) | ROE built from mismatched numerator/denominator |
| **Year mismatch / staleness** | BCP canonical import = **FY2023**; RNPG/group equity last present **FY2022** while consolidated is FY2025; resolver picks latest *per metric* → ratios span years | components from different fiscal years |
| **Snapshot ≠ annual history** | BCP valuation used ROE 7.14% / BVPS 190 that **do not exist in its annual table** (a second, separately-sourced copy) | two disagreeing fundamental sources per name |

The unifying rule we will enforce: **a figure is usable only if it ties out.** We have the official documents (linked), so this is verifiable, not a judgement call.

---

## 2. The tie-out rule set (the heart — all checks recompute from raw lines, never trust stored ratios)

For each symbol, on **one chosen fiscal year and one basis**, assert (tolerances in the registry, documented):

| ID | Check | Rule |
|---|---|---|
| T1 | Balance-sheet integrity | `Total_Assets ≈ Total_Liabilities + Total_Equity` (±0.5%) |
| T2 | Equity ↔ per-share | `Total_Equity ≈ Book_Value_Per_Share × Shares` (±2%); recompute BVPS = equity/shares, **discard** stored BVPS if it disagrees |
| T3 | Income label consistency | `Net_Income ≈ Resultat_net` (same year, ±1%); `RNPG ≤ Net_Income`; `Equity_group ≤ Total_Equity` |
| T4 | ROE reconciles | recompute from raw lines only. If minority interests/group-equity gaps are material, use true group basis `RNPG / group equity` and require group figures from the filing; if minorities are absent or immaterial (`minority_materiality_epsilon`), group basis is `NetIncome / Total_Equity` with `t4_basis=no_minority_total_equity`. Stored ROE is diagnostic only. |
| T5 | Single vintage | every component of a statement comes from the **same `fiscal_year`**; the snapshot equals the latest annual row (no snapshot/annual divergence) |
| T6 | Cash tie-out + NI link | reuse `integrity.py` (CFS ending cash ≈ BS cash; NI top-of-CFS ≈ NI bottom-of-IS) |
| T7 | Plausibility bands | `0 < P/E < 60`, `0 < P/B < 10`, `|EBIT margin| < 60%`, revenue/market-cap ratio sane, equity > 0 — bands in registry, flag (not silently clamp) |

Output: a per-symbol **defect report** `{symbol, year, failed_checks[], offending_metrics[]}`. This is the productionized, expanded version of the audit script (extend it to read the snapshot source too).

---

## 3. The correction pipeline (Codex implements as an idempotent worker/script)

> **Implementation note (Brief 42).** The FY2025 priority reingestion materializes this
> hand-read loop as `data/corrections/fy2025/<SYMBOL>.json` plus
> `services/api/scripts/remediate_fundamentals.py --fy2025-reingestion`. The
> apply path replaces canonical FY2025 annual rows with cited observed figures
> and derived formulas only; unavailable filing lines remain auditable in the
> artifact and tie-out-critical gaps produce `data_unverified`/NR.

For every symbol with a non-empty defect report:

**Step A — Codex reads the official source document itself and extracts the figures by hand (authoritative).**
This is the core of the remediation and the user's explicit instruction: **do not delegate to the Gemini pipeline that may have produced the error — Codex goes to the official document and scrapes it directly.**
For each defective `(symbol, fiscal_year)`:
1. Look up the official-doc URL(s) in `fundamental_source_document.source_url` (these are the BVC-published filings — RFA/états financiers — already linked per symbol/year).
2. **Fetch the document and read it directly.** Download the PDF (the URL is a real BVC filing), convert to text/tables, and **Codex reads the actual financial statements** — Bilan (Total Actif / Total Passif / Capitaux propres / Capitaux propres part du groupe), CPC or état des soldes (Résultat net / RNPG / PNB / RBE for banks), and the cover/notes for shares outstanding and the fiscal year. Codex extracts the **exact reported figures**, not a re-run of any extractor.
3. Record, per extracted figure, **document URL + page/line + the verbatim label** it came from (e.g. `"Capitaux propres part du groupe" p.4 = 32 957 549 (kMAD)`), so the value is auditable and re-checkable.
4. Run the tie-out checks (§2) on the hand-extracted set.
> **Why hand-extraction, not the scraper:** the corruption (LHM equity 75× off, BCP group-vs-consolidated, STROC `Net_Income` vs `Resultat_net`) originated in the automated extraction/mapping path. Re-running that path can reproduce the same error. Codex reading the filing is the independent ground truth. If Codex's reading reveals a systematic *mapping* bug (e.g. `cgnc_mapping` mapped *capital social* → `Total_Equity`), fix `cgnc_mapping.py` in this repo so future imports don't repeat it, and note it.
> **Capability precondition (confirm first):** Codex must verify it can (a) fetch the `source_url` (network egress to the BVC host) and (b) parse the PDF (a text/table extractor available in-env). If a document is unreachable or unparseable, record that and fall through to Step B. Do **not** invent figures for an unreachable document.

**Step B — Cross-check / fill from stockanalysis.com (independent second source).**
For any field Codex could not read from the official doc (unreachable/unparseable) or where the hand-extracted set still fails tie-out, fetch via `refresh_stockanalysis_fundamentals.py` (in-repo, no key). Use it to (i) **fill** missing figures and (ii) **arbitrate**: if the official-doc reading and stockanalysis agree (±tolerance) and the pair ties out, accept; if they disagree, the figure stays unverified. The official document (Step A) is the higher-authority source when both are available and both tie out.

**Step C — Tie-out gate (the arbiter).**
After A+B, re-run §2. A symbol is `verified` **only if it now ties out**. Record per-corrected-field provenance: `source ∈ {official_doc, stockanalysis, reported}`, and for `official_doc` the **URL + page/line + verbatim label** Codex read it from, plus which checks it now passes.

**Step D — Fail policy: must tie out or NR.**
A symbol that still fails after both sources is marked **`data_unverified`** → the valuation engine returns **NR** for it (no fair value, no rating), surfaced in the UI with the specific failed checks. **Never** fabricate, clamp, or value on a figure that does not tie out (this is the user's explicit instruction: figures must tie out because we have the official documents).

---

## 4. Persistence & idempotency

- Store the verification state per (symbol, fiscal_year): `verified | data_unverified` + `failed_checks[]` + per-field provenance (incl. the `official_doc` URL + page/line + verbatim label for hand-extracted figures). Reuse `fundamental_quality_issue` if it fits; else a small table (migration `down_revision` = current head, Codex confirms).
- Persist Codex's hand-extracted figures as a curated correction set (e.g. `core/tests/fixtures/` or a `data/corrections/` JSON keyed by symbol+year+metric, with provenance) so the remediation is **auditable and re-applies deterministically** without re-reading the PDFs every run.
- One CLI: `services/api/scripts/remediate_fundamentals.py --symbols ... [--apply]` — dry-run by default; prints the defect report, the figures Codex read from each official doc (with page refs), the stockanalysis cross-check, and the post-correction tie-out result. Re-runnable from the curated correction set.
- The valuation read path checks the verification state and returns NR for `data_unverified` names.

---

## 5. Tests

`core/tests/test_data_tieout.py` + `services/api/tests/test_remediation.py`:
- Synthetic LHM-type row (equity 47× too small) fails T2/T1; after a corrected source it ties out; if no source corrects it → `data_unverified` → NR.
- STROC-type row (`Net_Income` ≠ `Resultat_net` 2,300×) fails T3 → NR until corrected.
- BCP-type material-minority row without true group figures fails T4; when RNPG and group equity are present, group-basis recompute (RNPG/group equity) ties out and yields ROE ~12% (positive justified P/B). Stored ROE mismatches are logged, not gating.
- Year-mismatch row (RNPG 2022 + equity 2025) fails T5; single-vintage selection fixes or NRs it.
- A `verified` name passes all checks and is valued; a `data_unverified` name returns NR with reasons (no fabricated fair value).
- A hand-extracted figure loaded from the curated correction set carries `official_doc` provenance (URL + page + label) and, once applied, the symbol ties out.
- Provenance is recorded for every corrected field.
- The pipeline is idempotent (second run re-applies the curated correction set; no re-reading of PDFs, no change to already-verified names).

---

## 6. Acceptance criteria

1. `python -m pytest core/tests/ -q` + new API tests pass from the worktree root.
2. Every one of the 73 names is either **`verified` (ties out on T1–T7)** or **`data_unverified` → NR** — no name is valued on figures that fail tie-out.
3. The named offenders are resolved or NR'd: LHM equity, COL equity, STR scale/`Net_Income`-vs-`Resultat_net`, BCP group-basis ROE, the 9 minority-gap names.
4. Each corrected figure that came from an official document carries auditable provenance: `official_doc` URL + page/line + verbatim label Codex read it from (so any reviewer can open the filing and confirm the number). stockanalysis-sourced figures carry the stockanalysis URL.
5. The valuation engine reads the verification state and emits NR for unverified names.
6. Docs `02-data-flow.md`, `12-known-issues-and-limitations.md`, `13-methodology-and-sources.md` updated: the tie-out rule set, the re-verification pipeline, and the must-tie-out-or-NR policy.

---

## 7. What NOT to do

- **Do not** fabricate, clamp, interpolate, or carry forward a figure to make it tie out. Tie out from a real source, or NR.
- **Do not** transcribe a figure from a document you did not actually read — every `official_doc` value must have a real page/line citation. No guessing a number to make T1–T7 pass.
- **Do not** re-run the Gemini/BVC auto-extractor as the *primary* correction for Step A — Codex reads the filing itself; the auto-extractor's output is exactly what is under suspicion.
- **Do not** trust stored ratio fields (`ROE`, `Book_Value_Per_Share`, `Price_to_Book`) — recompute from raw lines; the audit proves they are unreliable.
- **Do not** mix consolidated and group bases within one ratio; per-share/ROE = group basis.
- **Do not** call BVC/stockanalysis from a request handler — only from worker tasks / the remediation script.
- **Do not** touch the seven-model math (34/37), scenario logic (35), or the UI design tokens.

---

## 8. Relationship to briefs 34–37

- **38 precedes them.** 34 (math), 35 (scenario coherence), 37 (bank model) only produce trustworthy numbers once inputs tie out.
- **36 (canonical snapshot) is complementary:** 36 picks *which* import is canonical and purges clutter; 38 verifies the *figures inside* the canonical import are correct. Land 38's tie-out gate and 36's canonical pointer together if convenient, but they are separable.

## Open questions (Codex: confirm BEFORE coding; do not improvise)

- **Capability precondition for Step A:** confirm Codex's environment can (a) make network requests to the BVC host in `source_url`, and (b) extract text/tables from the linked PDFs. If either is unavailable, say so up front — Step A cannot be done by hand-reading without it, and the plan falls back to stockanalysis.com + flagging the rest NR. Do not silently skip Step A.
- **Is `source_url` a direct file or a landing page?** Inspect a few rows: if it points to an HTML landing page rather than the PDF, determine how to resolve the actual filing URL (the `fama french` scraper already does this discovery — reuse its logic/output for URL resolution only, not for the figure extraction).
- **Volume:** count the distinct official documents across the defective names (symbols × years × statements). Report it so the manual-read pass is scoped; if it is very large, propose batching by symbol.
- For LHM/COL specifically: once you read the filing, state whether the stored bad equity was an **extraction** error or a **mapping** error (`cgnc_mapping` mapped the wrong line item / units). If mapping, fix `cgnc_mapping.py` here so future imports don't repeat it; report the root cause per name.
- Confirm whether `fundamental_quality_issue` can hold the verification state + provenance or a new table is needed.
- Confirm stockanalysis.com coverage for the Casablanca tickers that fail (does `cbse/{symbol}` resolve for each defective name?). List any with no stockanalysis coverage — those can only be fixed from the official BVC doc.
