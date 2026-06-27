# 52 — Archetype-aware coverage gates + bank/insurer statement UI, implementer: TBD

> **Status. Plan-only. No code changed by the author of this plan.** Deliverable per user: a phased brief; do not implement until the user delegates.
>
> **Premise.** The fundamental *data* is not lost. 73/73 symbols hold a canonical snapshot (70 from StockAnalysis, 66 of them FY2025), with rich metrics (33–89 latest, 171–331 annual). Bank/insurer line items **are** scraped (`Net_Interest_Income`, `Premiums_Earned`, `Loans_Net`, `Customer_Deposits` — `stockanalysis_provider.py:431-474`). The "lots of missing data" the user sees has **two** causes:
> 1. **The coverage / missing-data gate in the API is archetype-blind.** It demands `Revenue`, `Operating_Cash_Flow`, `EBITDA`, `Capex`, `Free_Cash_Flow`, `Debt_to_Equity`, `FCF_Yield` from *every* stock. Banks/insurers structurally do not report these (they are in `FINANCIAL_SUPPRESSED_METRICS`), so every bank/insurer is false-flagged. The UI also renders generic industrial statements (Revenue / Chiffre d'affaires) for them.
> 2. **A real but small coverage tail.** 5–7 symbols are not on the rich FY2025 StockAnalysis canonical: `NKL`, `SNP` → old *workbook* FY2024; one symbol on `investing.com` FY2021; plus thin StockAnalysis scrapes (`HPS`, `TGC` = 14 metrics) where the cash-flow page under-parsed.
>
> **User decisions (2026-06-27).** (a) Scrape = **gap-fill only** (do not disturb the 66 good FY2025 snapshots). (b) Bank/insurer = **full archetype treatment** (gates + dedicated UI statements + verify models consume the lines). (c) Deliverable = **this plan only**.
>
> **The engine is already archetype-aware** in scoring, ratios, valuation and projection — `_pillar_metrics_for_archetype` (`scoring.py:389`) selects `BANK_*` / `FINANCIAL_*` pillar tuples; `ratios.py:291` builds bank NIM/C-I/L-D; `valuation.py` and `projection.py` branch on `bank`/`insurance`. The work is therefore concentrated at the **edges**: the coverage/missing gate, the DTOs, and the UI — not a model rewrite.

---

## 0. Files the implementer MUST read first (gate — confirm current line numbers, tree shifts)

1. `docs/fundamentals-layer/21-codex-briefs-INDEX.md` — binding anti-hallucination rules. No fabricated numbers anywhere; observed values or `unavailable`.
2. `services/api/app/routers/fundamentals.py`:
   - `REQUIRED_COVERAGE_METRICS` (`:120`) — `("Current_Price","PER","Price_to_Book","ROE","Debt_to_Equity","FCF_Yield")`. **`Debt_to_Equity`/`FCF_Yield` are bank-irrelevant.**
   - `CORE_MISSING_METRIC_LABELS` (`:150`) / `CORE_MISSING_METRIC_CATEGORIES` (`:157`) — include `Revenue`, `Operating_Cash_Flow`.
   - `SUPPLEMENTAL_MISSING_METRIC_GROUPS` (`:164`) — `EBIT, EBITDA, D&A, Total_Debt, Cash, Free_Cash_Flow, Capex` (all suppressed for financials).
   - `LATEST_MISSING_METRIC_GROUPS` (`:174`) — `FCF_Yield, Debt_to_Equity`.
   - `_missing_financial_check_specs` (`:1236`) and `_missing_financial_data_summary` (`:1254`) — the builder. **Not archetype-aware.**
   - `get_fundamental_coverage` (`:1899`); `missing_metrics` built at `:1956` straight off `REQUIRED_COVERAGE_METRICS`.
3. `services/api/app/services/fundamentals.py`:
   - `CORE_STATEMENT_METRIC_GROUPS` (`:298`, imported into router at `:82`) — `Revenue, NetIncome, Total_Assets, Total_Equity, Operating_Cash_Flow`. **`Revenue` + `Operating_Cash_Flow` are the false-flag drivers for financials.**
   - `REQUIRED_GATE_METRIC_GROUPS` (`:320`) + `_metric_groups_complete` (`:351`) — the *verification/ratability* gate. Already bank-friendly (`Total_Actif/Passif/Capitaux_propres/Resultat_net`); confirm it is **not** also demanding industrial lines.
   - Archetype is read from the snapshot via `source_json["archetype"]` (fallback chain in `scoring.py:_get_archetype:384`). **Confirmed in DB: `source_json->>'archetype'` = `bank` (ATW, BCP, …), `insurance` (WAA, …), absent = industrial.**
4. `core/quant_core/fundamentals/cgnc_mapping.py`:
   - `BANK_FIELD_TOKENS` (`:53`), `INSURANCE_FIELD_TOKENS` (`:61`), `FINANCIAL_ARCHETYPES` (`:62`), `FINANCIAL_SUPPRESSED_METRICS` (`:63`), `CANONICAL_METRICS` bank/insurer block (`:95-99`, `:114-116`), `infer_statement_archetype` (`:231`).
5. `core/quant_core/fundamentals/scoring.py` — `_get_archetype` (`:384`), `_pillar_metrics_for_archetype` (`:389`), and the `BANK_*_METRICS` / `FINANCIAL_*_METRICS` tuples it selects.
6. `services/worker/tasks/refresh_stockanalysis_fundamentals.py` — `_selected_stocks` (`:48`), `_missing_coverage_symbols` (`:60`), `recompute_symbol_valuations_all_scenarios` (import `:30`). **Gap-fill targeting already exists here.**
7. `frontend/lib/fundamental-statement-utils.js` — `FINANCIAL_STATEMENT_TABS` (`:1`), `STATEMENT_ROWS` (`:130`), `METRIC_ALIASES` (`:27`), `buildFinancialStatementTable` (`:404`), `STATEMENT_ROWS[tab]` lookup (`:385`).
8. `frontend/components/data/fundamentals-catalog.tsx` — `FundamentalFinancialTab` (`:58`), `FINANCIAL_TABS` (`:60`), `missingMetricRows` (`:263`), `MissingFinancialDataPanel` (`:555`).
9. `services/api/app/schemas/fundamentals.py` — `FundamentalStockDetailOut` (`:324`, has `sector`+`coverage`, **no `archetype`**), `MissingFinancialDataSummaryOut`, `FundamentalCoverageRow`.

> If a cited line shifted, report the new line and proceed. Do not guess.

---

## 1. Evidence (live DB, `is_canonical=true`, 2026-06-27)

**Canonical source × year (73 symbols):**

| source | year | symbols |
|---|---|---|
| stockanalysis | 2025 | 66 |
| stockanalysis | 2024 | 4 |
| workbook | 2024 | 2 (`NKL`, `SNP`) |
| investing.com | 2021 | 1 |

**Missing-field distribution (`/fundamentals/stocks/{sym}.missing_financial_data.total_missing`, 71 reachable):** min 0, median 0, max 12; **36 symbols are 0-missing**; 12 are ≥4.

**Top "missing" metrics (count of symbols):** `Capex` 19, `EBITDA` 18, `Free_Cash_Flow` 17, `Debt_to_Equity` 17, `Operating_Cash_Flow` 16, `Depreciation_Amortization` 13, `Total_Debt` 9, `Cash_and_Equivalents` 9, `EBIT` 9. **Every one of these is in `FINANCIAL_SUPPRESSED_METRICS` or is industrial-only** → the gate is asking financials for data that does not exist for them by construction.

**Worst symbols and why:**
- `CIH`, `BCI` — `source_json.archetype = bank`; 20–21 metrics; flagged for EBITDA/Capex/OCF they never report → **100% false flags.**
- `NKL` (Distribution), `SNP` (Chimie) — canonical = **workbook FY2024**, **zero StockAnalysis snapshots** → genuine gap-fill targets.
- `HPS`, `TGC` — StockAnalysis FY2025 but only 14 metrics → **cash-flow page under-parsed** → genuine gap-fill targets.

**Universe (from `stock_master`):** banks = `ATW, BCI, BCP, BOA, CDM, CFG, CIH` (+ any with `sector ilike 'banqu%'`); insurers = `AFM, AGM, ATL, SAH, WAA`.

### 1b. The bank valuation symptom (user report: BCP "valorisation = only comparables", "Chiffre d'affaires empty")

Tracing BCP's `/fundamentals/stocks/BCP` valuation bundle to the DB shows **all seven models are NR** on the canonical import (`17fa82d2`), every one carrying `data_unverified_nr:t2_equity_per_share`. The "only comparables" the user sees is the API's `_latest_available_valuation_bundle` (`fundamentals.py:871`) falling back to an **older** import whose comparable survived; the empty *Chiffre d'affaires* is the industrial statement UI rendering a bank.

Across the financial universe (canonical import, base scenario):

| symbol | `source_json.archetype` | verif status | failing check | `Equity_Group` present | rated models |
|---|---|---|---|---|---|
| ATW, BCP, BOA | bank | **data_unverified** | `t2_equity_per_share` | **no** | **0** |
| BCI, CIH | **None (mis-detected)** | data_unverified / verified | `t3_income_consistency` / — | yes | 0 / 3 |
| AFM | **None (mis-detected)** | data_unverified | `t4_group_basis_roe; t7` | no | 0 |
| CDM, CFG, AGM, ATL, SAH, WAA | bank / insurance | verified | — | — | 4 |

Two failures hide here, **both confirmed against live data**:

- **RC-5 — stale verification rows NR the big banks.** ATW/BCP/BOA carry material minority interest (BCP: group equity 41.45bn vs consolidated 62.43bn → minority ≈ 34%). The StockAnalysis import does **not** ingest `Equity_Group`/`Minority_Interest`, so the persisted `t2` check (written **2026-06-21**) divided consolidated `Total_Equity` by shares, got BVPS 285 vs stored 181.86, and **failed → all models NR**. **But the current (uncommitted) `integrity.py` `_t2_equity_per_share` (`:236`) is already minority-aware** (`T2_MINORITY_WARN_FRACTION=0.45`, `T2_MINORITY_MAX_FRACTION=0.60`, `:232-233`). Running it on BCP's live data returns **`pass`** (implied minority 36.2% < 0.45). **The DB is simply stale — the engine was fixed but the snapshots were never re-verified/re-rated.** A recompute re-rates ATW/BCP/BOA. (Reproduce: `_t2_equity_per_share({'Total_Equity':57956000000,'Shares_Outstanding':203312473,'Book_Value_Per_Share':181.86})` → `status='pass'`.)
- **RC-6 — archetype mis-detection NRs/derails other financials.** `BCI`, `CIH`, `AFM` persist `source_json.archetype = None` and are scored/valued as **industrial** — so they hit industrial checks (`t3`, `t4`, `t7`) and industrial pillars/models. `infer_statement_archetype` over their metric names did not fire (bank/insurer tokens absent from their import) and there is no `sector`-based fallback at persist time (`stock_master.sector` is `Banques`/`Assurances`).

> The user notes bank data **was** scraped — correct: the issue is not acquisition but (RC-5) stale persisted verification/valuation and (RC-6) archetype not stamped on the snapshot, plus the archetype-blind UI/coverage of §2.

---

## 2. Root causes

- **RC-1 — Archetype-blind coverage/missing gate.** `_missing_financial_check_specs` (`:1236`) builds from `CORE_STATEMENT_METRIC_GROUPS` + `SUPPLEMENTAL_MISSING_METRIC_GROUPS` + `LATEST_MISSING_METRIC_GROUPS` with no archetype branch, and `REQUIRED_COVERAGE_METRICS` is a flat tuple. Banks/insurers are judged against the industrial statement shape.
- **RC-2 — `archetype` not surfaced to the API edge or the UI.** The router has the snapshot (hence `source_json["archetype"]`) but never reads it; `FundamentalStockDetailOut`/`FundamentalCoverageRow` don't carry it; the frontend can only guess from `sector`.
- **RC-3 — Generic statement UI.** `FINANCIAL_STATEMENT_TABS` + `STATEMENT_ROWS` are a single industrial layout (Revenue/Chiffre d'affaires, EBITDA, FCF). Banks/insurers have no dedicated income/cash-flow view, so their real lines (PNB/NII, cost of risk, deposits, loans; premiums, claims, combined ratio) are not presented and their suppressed lines render as blanks.
- **RC-4 — Coverage tail.** 5–7 symbols not on rich FY2025 StockAnalysis canonical (workbook FY2024 / investing.com FY2021 / thin scrape). Independent of RC-1–3.

---

## 3. Remediation — phased, backend-first

### Phase 0 — Recompute / re-verify the existing canonical book (backend, highest ROI, no scrape) ⭐⭐

This is the **cheapest, highest-impact** step and directly fixes the user's BCP report. The engine already verifies BCP correctly (RC-5); the persisted rows are stale.

1. Run the existing recompute path (`recompute_symbol_valuations_all_scenarios`, imported in `refresh_stockanalysis_fundamentals.py:30`, and the verification-coupling recompute from brief 50) over **all canonical symbols** — no re-scrape, just re-verify + re-rate against the current `integrity.py` and valuation engine.
2. Confirm the verification rows refresh: `ATW, BCP, BOA` move `data_unverified → verified` (minority-aware `t2` now passes), and their valuation models repopulate (`fair_value` non-null, weight > 0).
3. Guard: do not let a recompute *downgrade* a currently-verified name without a logged `failed_checks` reason (catch regressions from the same run).

**Acceptance:** `ATW, BCP, BOA` are `verified` with ≥4 rated models on their canonical import; no canonical name silently loses its rating. Re-run the §1b table — the "rated models = 0" rows for correctly-detected banks become non-zero. (RC-6 names BCI/CIH/AFM still need Phase 3b.)

> Why separate from Phase 1: Phase 0 touches **no scraping** and re-rates the whole book; Phase 1 only acquires the missing data for the coverage tail. Phase 0 should land first — it likely resolves the visible BCP symptom on its own.

### Phase 1 — Gap-fill ingest + recompute (backend, low risk, no schema change)

Goal: lift the 5–7 tail symbols onto rich StockAnalysis canonical **without touching the 66 good FY2025 snapshots**.

1. Use the existing worker entrypoint `refresh_stockanalysis_fundamentals.py`. `_missing_coverage_symbols` (`:60`) already enumerates under-covered symbols; extend its predicate so a symbol is "needs refresh" when **any** of:
   - no StockAnalysis snapshot exists for it (`NKL`, `SNP`, investing.com name), OR
   - canonical `latest_statement_year < max(FY across book)` (stale FY2024/2021), OR
   - canonical metric count below an archetype-appropriate floor (industrial < ~40, bank/insurer < ~18) **after** archetype suppression — do not count suppressed metrics against financials.
2. Run the refresh **targeted** to that symbol list (`_selected_stocks(db, symbols=[...])`), then `recompute_symbol_valuations_all_scenarios` for just those symbols.
3. If a symbol's cash-flow page genuinely under-parses again (e.g. `HPS`/`TGC`), record it in an audit JSON under `data/stockanalysis_*_audits/` (existing convention) and **do not** fail the whole run — it stays partial with a logged reason, not a silent gap.

**Acceptance:** every industrial symbol's canonical is FY2025 StockAnalysis with ≥ core statement groups present; the investing.com FY2021 symbol is replaced or explicitly waived in an audit file. No FY2025 snapshot that is already complete is re-ingested.

> Note: this phase deliberately does **not** "re-scrape everything." Per the user, gap-fill only.

### Phase 2 — Archetype-aware coverage/missing gate (backend, the core fix) ⭐

This is what removes the false "missing" flags. All edits in `services/api/app/routers/fundamentals.py` unless noted.

1. **Introduce archetype-keyed spec tables.** Replace the three flat group tuples with a dict keyed by archetype `∈ {"industrial","bank","insurance"}`:
   - `industrial` = today's groups verbatim (no behavior change for industrials).
   - `bank` required statement lines: `Net_Interest_Income` (alias `PNB`), `Total_NonInterest_Income`, `Provision_for_Loan_Losses` (alias `Cout_du_risque`), `NetIncome`, `Loans_Net`, `Customer_Deposits`, `Total_Assets`, `Total_Equity`; latest ratios: `PER`, `Price_to_Book`, `ROE`, `Net_Interest_Margin`, `Cost_to_Income`, `Loans_to_Deposits`.
   - `insurance` required statement lines: `Premiums_Earned`, `Policy_Benefits` (claims), `Policy_Acquisition_Costs`, `NetIncome`, `Total_Assets`, `Total_Equity`; latest ratios: `PER`, `Price_to_Book`, `ROE`, `Combined_Ratio`.
   - For `bank`/`insurance`, **exclude** `Revenue, EBIT, EBITDA, D&A, Free_Cash_Flow, Capex, Operating_Cash_Flow, Total_Debt, Debt_to_Equity, FCF_Yield` from the missing checks (they are `FINANCIAL_SUPPRESSED_METRICS` ∪ industrial-only). Reuse `FINANCIAL_SUPPRESSED_METRICS` as the suppression source so the two definitions never drift.
2. **Thread archetype through.** `_missing_financial_check_specs(archetype)` and `_missing_financial_data_summary(..., archetype)` take the archetype; the caller resolves it from `snapshot.source_json.get("archetype")` (fallback `infer_statement_archetype` over the latest annual metric names, then `_financial_archetype_for_sector(sector)` for the workbook tail). Default `"industrial"` when absent.
3. **`REQUIRED_COVERAGE_METRICS` → per-archetype.** Add `REQUIRED_COVERAGE_METRICS_BY_ARCHETYPE`; `get_fundamental_coverage` (`:1956`) selects by the row's archetype. Bank/insurer set drops `Debt_to_Equity`/`FCF_Yield`, adds `Net_Interest_Margin`/`Cost_to_Income` (bank) or `Combined_Ratio` (insurer).
4. **Keep `REQUIRED_GATE_METRIC_GROUPS` (ratability) as-is** unless step 0 reading shows it demands an industrial-only line; it already uses bank-friendly totals. Do not loosen the ratability gate as a side effect.

**Acceptance:** `BCP, ATW, CIH, BCI, WAA, AFM, AGM, ATL, SAH` report `total_missing` reflecting only genuinely-absent *archetype-relevant* lines (target: 0 for the fully-scraped banks/insurers). Industrial symbols' missing counts are **unchanged** from today (regression guard).

### Phase 3 — Surface `archetype` on the API edge (backend, small)

1. Add `archetype: str` (default `"industrial"`) to `FundamentalStockDetailOut` (`schemas/fundamentals.py:324`) and `FundamentalCoverageRow`. Populate from the resolved archetype (Phase 2 step 2).
2. Mirror in `frontend/lib/api.ts` Zod schemas for the detail and coverage rows (`archetype: z.string().default("industrial")` — schema already uses this idiom elsewhere, e.g. `:1306`).

**Acceptance:** `/fundamentals/stocks/BCP` and `/fundamentals/coverage` return `archetype` for every row; existing fields unchanged.

### Phase 3b — Archetype-detection robustness (backend, fixes RC-6) ⭐

`BCI`, `CIH`, `AFM` persist `archetype = None` and are mis-treated as industrial. Make detection deterministic for the MASI financials:

1. In the ingestion/persist path where `source_json["archetype"]` is stamped (`services/api/app/services/fundamentals.py:3478-3487`, `infer_statement_archetype`), add a **`stock_master.sector` fallback**: when value-based inference returns `unknown`/`None`, map sector `Banques → bank`, `Assurances → insurance` (reuse `BANK_SECTOR_TOKENS`/`INSURANCE_SECTOR_TOKENS`, `valuation.py:666-667`, and `_financial_archetype_for_sector`, `services/fundamentals.py:966`). Stamp the result on the snapshot so `_get_archetype` (which reads `source_json.archetype`) resolves it everywhere downstream.
2. Backfill-stamp existing canonical snapshots in the Phase 0 recompute (no re-scrape) so BCI/CIH/AFM pick up the right archetype and re-rate on the financial path.

**Acceptance:** every `Banques`/`Assurances` symbol resolves `archetype ∈ {bank, insurance}` in `source_json` and in the API DTO; none resolve `industrial`. BCI/CIH/AFM re-rate on the financial path (their `t3`/`t4`/`t7` industrial-only failures no longer apply).

### Phase 4 — Archetype-aware statement UI (frontend) ⭐

All edits in `frontend/lib/fundamental-statement-utils.js` + `frontend/components/data/fundamentals-catalog.tsx`.

1. **Archetype-specific tabs + rows.** Key `FINANCIAL_STATEMENT_TABS` and `STATEMENT_ROWS` by archetype:
   - **bank** income tab → "Produit Net Bancaire (PNB / NII)", "Commissions / produits hors intérêts", "Coût du risque", "Résultat net"; balance tab → "Créances clientèle (Loans)", "Dépôts clientèle", "Total actif", "Capitaux propres"; ratios tab → NIM, Coefficient d'exploitation (C/I), Loans/Deposits, ROE, ROA, P/B, PER. **No cash-flow tab** (or a disabled tab with an explanatory note) — banks don't report an industrial CF statement.
   - **insurer** income tab → "Primes acquises", "Charges de sinistres (claims)", "Frais d'acquisition", "Résultat net"; ratios tab → Ratio combiné, ROE, P/B, PER.
   - **industrial** → today's layout unchanged.
2. `buildFinancialStatementTable(detail, tab, periodType)` (`:404`) selects the row set via `STATEMENT_ROWS_BY_ARCHETYPE[archetype][tab]`, using `detail.archetype` from Phase 3 (fallback: map `sector` "Banques"→bank, "Assurances"→insurance).
3. **`MissingFinancialDataPanel` (`:555`)** already consumes `detail.missing_financial_data`; after Phase 2 it shows the archetype-correct list automatically. Add a one-line caption naming the archetype ("Établissement bancaire — lignes industrielles non applicables") so a 0-missing bank reads as *intentional*, not empty.

**Acceptance:** opening a bank shows PNB/NII, cost of risk, loans, deposits and bank ratios (no Revenue/Chiffre d'affaires, no FCF tab); an insurer shows premiums/claims/combined ratio; an industrial is visually unchanged.

### Phase 5 — Verify models consume archetype lines (backend, mostly verification)

The pillars/valuation already branch on archetype. Confirm — and only patch if broken — that:
1. `_pillar_metrics_for_archetype` (`scoring.py:389`) bank/insurer tuples reference lines that the StockAnalysis provider actually writes (`Net_Interest_Income`, `Loans_Net`, `Customer_Deposits`, `Net_Interest_Margin`, `Cost_to_Income`, `Combined_Ratio`). Cross-check each name against `CANONICAL_METRICS` (`cgnc_mapping.py:95-116`) and against a live `fundamental_annual_metric` sample for `BCP`/`WAA`.
2. Bank/insurer valuation path (`valuation.py` financial/insurer models, `projection.py:709,1111`) produces a non-NR result for the fully-scraped banks/insurers. If any bank is still NR, capture the gate reason — it likely belongs to brief 44/50 territory (verification coupling), not this brief.

**Acceptance:** `BCP, ATW, WAA` produce non-NR ratings whose pillar inputs are the bank/insurer lines (spot-check `scores_json.quality_components` / `metric_breakdown`).

---

## 4. Tests (add; do not weaken existing)

- `services/api/tests/test_fundamentals_coverage_archetype.py` (new): for a synthetic bank snapshot carrying `source_json.archetype="bank"` with NII/loans/deposits but no Revenue/OCF/EBITDA → `missing_financial_data.total_missing == 0`; for an insurer with premiums/combined ratio → 0; for an industrial missing OCF → still flagged (regression guard).
- Extend `services/api/tests/test_fundamental_frontend_contract.py` to assert `archetype` is present on detail + coverage rows.
- Frontend: extend `frontend/lib/fundamental-statement-utils.test.mjs` — bank archetype yields the PNB/cost-of-risk income rows and omits the CF tab; insurer yields premiums/combined-ratio; industrial unchanged.
- Worker: extend `services/worker/tests/test_targeted_bvc_fundamentals.py` (or a new `test_refresh_stockanalysis_gapfill.py`) to assert `_missing_coverage_symbols` selects the stale/thin/uncovered symbols and **excludes** already-complete FY2025 ones.

Full suite must stay green: `python -m pytest core/tests/ services/api/tests/ services/worker/tests/ -q` and `cd frontend && npm test`.

---

## 5. Acceptance criteria (whole brief)

1. Banks/insurers with fully-scraped data report **0** false "missing" fields; industrial missing counts are byte-identical to today (no industrial regression).
2. `/fundamentals/coverage` and `/fundamentals/stocks/{sym}` carry `archetype`.
3. The fundamentals UI renders bank statements (PNB/NII, cost of risk, loans, deposits, bank ratios) and insurer statements (premiums, claims, combined ratio); industrial view unchanged.
4. The 5–7 coverage-tail symbols are on rich FY2025 StockAnalysis canonical or explicitly waived in an audit file.
5. Bank/insurer pillar + valuation inputs are the archetype lines, verified on `BCP`/`ATW`/`WAA`.

---

## 6. Reproduction / verification commands

```bash
# Canonical source × year
python - <<'PY'
import psycopg2
c=psycopg2.connect(host='127.0.0.1',port=5555,dbname='quant',user='app',password='app');cur=c.cursor()
cur.execute("""select i.data_source,s.latest_statement_year,count(*)
 from fundamental_latest_snapshot s join fundamental_import i on s.import_id=i.id
 where s.is_canonical group by 1,2 order by 1,2""")
[print(r) for r in cur.fetchall()]
PY

# Per-symbol missing summary (before/after Phase 2) for the banks/insurers
for S in BCP ATW CIH BCI WAA AFM AGM ATL SAH; do
  curl -s "http://127.0.0.1:8000/fundamentals/stocks/$S" \
   | python -c "import sys,json;d=json.load(sys.stdin);m=d['missing_financial_data'];print('$S',d.get('archetype'),'total_missing=',m['total_missing'],[i['metric_name'] for i in m['items']])"
done

# archetype source of truth
python - <<'PY'
import psycopg2
c=psycopg2.connect(host='127.0.0.1',port=5555,dbname='quant',user='app',password='app');cur=c.cursor()
cur.execute("select symbol, source_json->>'archetype' from fundamental_latest_snapshot where is_canonical order by 2 nulls last,1")
[print(r) for r in cur.fetchall()]
PY
```

---

## 7. Sequencing & ownership

Phase 2 is the single highest-leverage change (removes the false flags the user is reacting to) and is self-contained backend. Recommended order: **2 → 3 → 4** (the visible fix), then **1** (coverage tail) and **5** (verification) in parallel. Phases 2–3 and 5 are Python/pytest — Codex-suitable mechanical work given the anchors above. Phase 4 is the only one needing UI judgement (tab/row curation) and is best done with a screenshot pass (`frontend/scripts/capture-fundamental-screens.mjs` already exists).
