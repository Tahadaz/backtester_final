# Fundamental Analysis — Desk-Grade Rigor Upgrade Plan

> Status: **Plan complete; Phase 0 partially executed** (46-field scraper schema implemented +
> pilot-validated 2026-06-01). All six workstreams fully specified below.
> Owner: taha · Started 2026-06-01

## Context — why this work exists

The app already has an institutionally-broad fundamental engine (7 valuation models, ensemble,
sensitivity, integrity checks, calibrated Moroccan assumptions in
`core/quant_core/fundamentals/`). The goal is to take it from *"strong first start"* to
*"a trading desk would rely on it."* A diagnosis against a desk audience surfaced four blocking
gaps, all of which this plan closes:

1. **Uniform cost of equity / no beta.** `cost_of_equity` is a flat `0.089` for every stock
   (`valuation.py:27`, "default beta=1.0"). Every name shares one discount rate — the first thing
   a desk flags.
2. **No real forward estimates.** The DCF uses last-reported FCF × a single fading growth rate
   chosen by a silent fallback chain (`_fcf_growth_input`). It is a back-of-envelope DCF, not a
   driver-based forecast the desk can interrogate.
3. **No point-in-time (PIT) discipline.** Fundamentals are keyed by `statement_year` only;
   `period_end_date` is synthesized as `{year}-12-31` (`workbook.py:325`). There is no record of
   *when* a figure became public, so the signal cannot be backtested without look-ahead bias.
4. **Reasoning is computed but hidden.** `projected_fcf`, sensitivity grids, model weights and
   confidence already exist in the persisted payloads but are never rendered. The product presents
   as a data terminal, not a valuation argument.

Intended outcome: each model is **understood, justifiable, and controllable** — every assumption
visible and sourced, every estimate traceable, and the signal demonstrably predictive on
point-in-time data.

## Evidence base (validated 2026-06-01)

**Scraper status & data diagnosis** (`C:\Users\taha\Downloads\fama french`, corpus
`data/raw/all_results.jsonl`, validated 2026-06-01): BVC-API → PDF → Gemini extraction. The current
prompt (`pdf_parser_llm.py` `FIELDS`) only requests **15 condensed fields** — this is a *prompt
limitation, not a PDF limitation*. Source PDFs are full statutory reports (CPC, Bilan, Tableau de
flux), so **full 3-statement extraction is achievable by expanding the schema + re-extracting**
(Phase 0). Current corpus coverage:

- 80 companies with ≥1 successful annual extraction; **fiscal years 2022–2025 only** (depth: 39 cos
  have 4y, 28 have 3y, 10 have 2y, 3 have 1y).
- Per-year: 2022=75 · 2023=74 · 2024=71 · 2025=43 (2025 still publishing).
- **Gaps:** (a) **pre-2022 (2016–2021) never scraped** — scope was narrowed (see
  `backup_before_2022_scope` backup); needed for the 5y+ backtest. (b) **868 failed annual docs**
  (overall ~48% fetch/parse failure) need retry. (c) field breadth = 15 condensed → must expand.

→ **Target = full 3-statement model via scraper upgrade** (46-field CGNC schema, now implemented and
pilot-validated — see Phase 0.0), NOT a downgrade. Driver-FCF fallback applies *only* to names that
genuinely do not disclose a cash-flow statement after re-extraction (true reporting gaps, not
extraction misses).

**Publication dates** already captured (`field_vactory_date` → `Publication_Date`) and persisted to
`fundamental_source_document.publication_date`, BUT only linked to `fundamental_period_metric` —
NOT to `fundamental_annual_metric` / `fundamental_latest_snapshot`, the layers the engine consumes.
→ Phase 1 closes this gap.

**History depth:** PIT-clean data is 2022–2025 today; `run_last_10_years.ps1` can extend to ~10y.
**Scrape reliability:** ~48% of fetch attempts FAILED → re-runs need retry/repair.

**Price/beta inputs:** daily OHLCV for ~80 MASI names + index levels (MASI, MASI-20) already in
`market_data_store`, joinable by normalized symbol. No returns/covariance/beta code exists yet.

## Architecture — six workstreams, in dependency order

```
Phase 0  Scraper Upgrade + Historical Backfill ──┐ (full 3-statement fields; 2016–2025; retry fails)
            │                                     │
Phase 1  PIT Data Foundation ────────────────────┤ (dated, normalized data into the engine layers)
            │                                     │
Phase 2  Cost of Capital (beta+WACC) ────────────┤
            │                                     ├─► Phase 4  PIT Signal Backtest (the desk exhibit)
Phase 3  Forward Estimates (3-statement) ────────┘
            │
Cross-cutting  Presentation/UI (per-model sub-tabs; assumptions tab; justification visuals)
```

Sequencing rationale: the full 3-statement, multi-year, dated dataset (P0) is the raw material;
P1 wires it into the engine with PIT discipline; that substrate feeds stock-specific discount rates
(P2) and forecasts (P3); the backtest (P4) needs all of it PIT-correct. UI built incrementally.

### Execution roadmap (what runs in parallel vs. blocks)

Two tracks can start **immediately and in parallel**, because they share no dependency:
- **Track A — Data (long pole):** Phase 0 scraper engineering (flux fix + RFA-prioritization) →
  mass RFA-first backfill 2016–2025. Gemini quota/time heavy; kick off early so data is ready.
- **Track B — Beta engine (Phase 2.1):** independent of the scraper — it consumes price/index data
  already in `market_data_store`. Can be built and tested now.

Then the dependent chain:
1. **M0 — Data ready** (Track A done): full 3-statement, 2016–2025, dated, ≥5y for MASI-20.
2. **M1 — PIT foundation** (Phase 1): `as_of_date` wired, 46-field mapping, `get_snapshot_as_of`.
   *Needs M0 flowing (can start on schema while backfill runs).*
3. **M2 — Cost of capital** (Phase 2.2/2.3): live WACC + assumptions registry/tab. *Needs M1 + Track B.*
4. **M3 — Forward estimates** (Phase 3): projection engine + estimation tab. *Needs M1 + M2.*
5. **M4 — PIT backtest** (Phase 4): the desk exhibit. *Needs M1+M2+M3 PIT-correct.*
6. **UI** (cross-cutting): ships incrementally as M2/M3 land (render-what's-computed first).

Backend-first within each milestone (engine + tests, then API, then UI), per the established workflow.

---

## Phase 0 — Scraper upgrade + historical backfill

**Goal:** make the scraper capture the **full 3-statement line items** for **2016–2025**, and close
the failure backlog — so Phases 1/3 have real data, not a 15-field condensed subset.

### 0.0 Pilot validation (run 2026-06-01, `scratch/pilot_full_3statement.py`)
Upgraded 46-field CGNC schema tested on 6 reports. **Result: full 3-statement extraction validated.**
- Full reports (RFA) returned 27–43/46 fields; every full report tied out `Total_Actif = Total_Passif`
  to the dirham (0.00%). Disway returned a complete linked 3-statement incl. ESG soldes
  (Valeur_ajoutee, **Excedent_brut_dexploitation ≈ EBITDA**), full Bilan, full Flux.
- Press releases (CP) returned only 4–5 fields → **document type is the dominant lever.** Corpus has
  253 CP/notice annual docs (avg 7 fields) vs 190 RFA. **77/80 companies already have ≥1 RFA** (only
  3 are CP-only) → re-scraping RFA-first with the new schema unlocks near-universal coverage.
- Three archetypes confirmed: **CGNC/social** (full ESG), **IFRS-consolidated** (no ESG soldes; derive
  EBITDA = EBIT + Dotations), **bank** (PNB; bank P&L; no industrial CPC/ESG).
- One bug: Managem (full RFA) returned 0 flux — financial-page selector missed the tableau de flux.

### 0.1 Expand the extraction schema — classical CGNC / Plan Comptable Marocain labels
Field keys are ASCII (no accents/spaces, underscore-joined) so they stay valid JSON keys and match
the `^(.+)_(\d{4})$` convention, but the terminology follows Moroccan statutory accounting (CGNC),
with IFRS-consolidated equivalents accepted by the prompt. Extend `FIELDS` in
`src/scraper/pdf_parser_llm.py` to:

**CPC — Compte de Produits et Charges (income statement)**
- `Chiffre_daffaires` (Ventes de biens et services produits / CA ; **PNB** pour les banques)
- `Achats_revendus_de_marchandises`
- `Achats_consommes_de_matieres_et_fournitures`
- `Autres_charges_externes`
- `Impots_et_taxes`
- `Charges_de_personnel`
- `Dotations_dexploitation`
- `Autres_charges_dexploitation`
- `Resultat_dexploitation`
- `Resultat_financier`
- `Resultat_courant`
- `Resultat_non_courant`
- `Impots_sur_les_resultats`
- `Resultat_net`
- `Resultat_net_part_du_groupe` (comptes consolidés)

**ESG — État des Soldes de Gestion (soldes intermédiaires — needed for margins & EV/EBITDA)**
- `Marge_brute`
- `Valeur_ajoutee`
- `Excedent_brut_dexploitation` (**EBE ≈ EBITDA**)
- `Capacite_dautofinancement` (CAF)

**BILAN — Actif**
- `Immobilisations_incorporelles`
- `Immobilisations_corporelles`
- `Immobilisations_financieres`
- `Actif_immobilise`
- `Stocks`
- `Creances_de_lactif_circulant` (Clients et comptes rattachés + autres débiteurs)
- `Titres_et_valeurs_de_placement`
- `Actif_circulant`
- `Tresorerie_Actif`
- `Total_Actif`

**BILAN — Passif**
- `Capital_social`
- `Reserves_consolidees_et_report_a_nouveau`
- `Capitaux_propres`
- `Capitaux_propres_part_du_groupe`
- `Interets_minoritaires`
- `Dettes_de_financement`
- `Provisions_durables_pour_risques_et_charges`
- `Dettes_du_passif_circulant` (Fournisseurs et comptes rattachés + autres créditeurs)
- `Passif_circulant`
- `Tresorerie_Passif`
- `Total_Passif`

**Tableau de Financement (CGNC) / Tableau des Flux de Trésorerie (IFRS)**
- `Variation_du_besoin_de_financement_global` (ΔBFG / ΔBFR)
- `Flux_de_tresorerie_lies_a_lactivite` (flux opérationnels IFRS)
- `Flux_de_tresorerie_lies_aux_investissements` (Capex / acquisitions d'immobilisations)
- `Flux_de_tresorerie_lies_au_financement`
- `Dividendes_distribues`
- `Variation_de_tresorerie`

- **Prompt rules:** keep scope discipline (Comptes Consolidés / IFRS préférés, sinon Comptes
  Sociaux — ne pas mélanger les périmètres), `Part du groupe` préférée, milliers/millions→MAD de
  base, parenthèses = négatif, banques: PNB = Chiffre_daffaires. Keep the `_sanitize_keys` allow-list
  in sync with the new `FIELDS`.
- **Pilot before mass re-run:** extract ~5–8 representative reports (une banque, un industriel, une
  valeur peu liquide), compare to the PDF, measure per-field hit-rate and tie-outs
  (`Total_Actif = Total_Passif`; `EBE` cohérent avec `Resultat_dexploitation + Dotations`;
  CAF reconciles). Trim any line the pilot shows is unreliably extracted. Only scale once it passes.

### 0.2 Document prioritization (the biggest lever — from pilot)
- Prefer the **full RFA / rapport financier annuel** over CP press-releases when both exist for a
  `(company, fiscal_year)`. The pilot showed RFA → 27–43 fields vs CP → 4–5. Use
  `is_relevant_financial_publication` + URL/title patterns (`rfa`, `rapport financier annuel`,
  `rapport annuel`) to rank candidates; only fall back to CP when no RFA exists (3 of 80 names).
- Persist a `document_kind` (RFA / CP / notice) on `fundamental_source_document` so Phase 1 can
  prefer the richest source per company-year.

### 0.3 Improve extraction reliability (attack the ~48% failure rate + the flux gap)
- Investigate `failed_output_*` artifacts to categorize failures (download vs parse vs LLM-JSON).
- **Flux page-targeting (pilot bug):** Managem RFA returned 0 flux — the page selector missed the
  tableau de flux. Add flux-specific page keywords and extend the page budget / late-page scan in
  `_identify_financial_pages` so the cash-flow statement is reliably included.
- OCR fallback + retry/key-rotation already present — tune page selection + chunking.
- Re-queue the **868 failed annual** docs (URLs already known from the corpus).

### 0.4 Backfill history 2016–2021 + complete 2025
- Widen the normalizer year filter (`DEFAULT_START_YEAR=2022` → 2016) and run the BVC publication
  fetch for older fiscal years (the API hosts them; `run_last_10_years.ps1` already parameterizes
  `HistoryYears`). Each annual report also carries the prior-year column, so coverage compounds.
- **Incremental only:** dedup by `(company, fiscal_year, period_type, period_label)` (signature
  already computed in `run_full_pipeline.py`) **AND** field-completeness — re-extract a prior
  SUCCESS only if it lacks the new full-3-statement fields. Never re-scrape an already-complete cell.

### 0.5 Re-validate coverage
- Re-run the coverage diagnosis (the script used 2026-06-01) and assert acceptance:
  ≥5 annual years for the MASI-20 backtest universe; full-3-statement (IS+BS+CF) present for the
  large majority; remaining gaps documented as true non-disclosure.

**Phase 0 tests/checks:** pilot extraction tie-outs (BS balances, CF reconciles); `_sanitize_keys`
accepts new fields and rejects unknowns; dedup skips complete cells and re-does incomplete ones;
post-backfill coverage report meets acceptance thresholds.

### Phase 0 — status
- **Field list: RESOLVED.** The 46-field CGNC schema is implemented in `pdf_parser_llm.py` and
  validated by the 0.0 pilot (perfect tie-outs on full reports). Remaining work is engineering, not
  open questions: RFA-prioritized re-scrape (0.2), flux page-targeting fix (0.3), 2016–2021 backfill
  (0.4). The mass re-scrape will consume Gemini quota/time — schedule as a managed run.

---

## Phase 1 — Point-in-time data foundation

**Goal:** every fundamental figure the valuation engine reads carries an `as_of_date` (the date it
became public), and the 46 CGNC scraper fields land in the engine's annual-metric schema with that
date.

### 1.1 Carry publication date into the consumed layers
- **Schema (alembic, `services/api/alembic/versions/`):** add nullable `as_of_date: Date` and
  `source_document_id: UUID` to `fundamental_annual_metric` and `fundamental_latest_snapshot`
  (`services/api/app/models.py`). `fundamental_source_document.publication_date` already exists —
  reuse it as the source of truth; do not invent a parallel date.
- **Backfill:** for existing rows, set `as_of_date` from the linked `fundamental_source_document`
  where resolvable; else leave NULL (legacy, flagged). Follow the existing canonical-key/backfill
  migration pattern already used in the repo (see `backfill_object_keys.py` precedent).
- **Domain (`core/quant_core/fundamentals/domain.py`):** add `as_of_date: date | None` to
  `AnnualMetricRow` and `FundamentalSnapshot`. Thread it through ingestion (`workbook.py`,
  `normalize_yfinance.py`, BVC import in `targeted_bvc_fundamentals.py`).

### 1.2 Map the 46 CGNC fields → engine annual metrics
- Define a single mapping table (CGNC field → app metric name), e.g. `Chiffre_daffaires`→Revenue,
  `Resultat_dexploitation`→EBIT, `Excedent_brut_dexploitation`→EBITDA, `Resultat_net`→Net Income,
  `Capitaux_propres`→Equity, `Dettes_de_financement`→Debt, `Tresorerie_Actif`→Cash,
  `Stocks`/`Creances_de_lactif_circulant`/`Dettes_du_passif_circulant`→working-capital components,
  `Flux_de_tresorerie_lies_aux_investissements`→Capex, `Capacite_dautofinancement`→CAF, etc.
- **Derived metrics (from pilot):** when `Excedent_brut_dexploitation` (EBE) is absent — IFRS
  reporters & banks — derive **EBITDA = Resultat_dexploitation + Dotations_dexploitation**; flag as
  derived. When `Flux_..._lies_a_lactivite` is absent, fall back to CAF − ΔBFG.
- **Archetype handling:** tag each company CGNC-social / IFRS-consolidated / bank (from which fields
  populate) so the valuation engine picks the right model family (already partly done via
  `FINANCIAL_SECTOR_TOKENS`) and the right EBITDA path.
- Reuse the scraper's normalization (`fundamental_normalizer.py` 1000× scale + dividend-sign fixes)
  — port or import its logic rather than re-deriving.
- Each mapped metric inherits `as_of_date = source_document.publication_date`, preferring the
  richest `document_kind` (RFA > CP) when multiple sources exist for a company-year.

### 1.3 Extend history (data-collection task, parallelizable)
- Run `run_last_10_years.ps1` (annual) to backfill 2016–2025 with publication dates.
- Add retry/repair for the ~48% FAILED rate (re-queue failed `Source_URL`s; the existing
  `failed_output_*` artifacts identify them).
- Acceptance: ≥5 annual years of PIT data for the MASI-20 names at minimum (backtest universe).

### 1.4 PIT accessor (the contract everything else uses)
- New helper: `get_snapshot_as_of(symbol, as_of: date)` → reconstructs the fundamental snapshot
  using only rows with `as_of_date <= as_of`. This is the single guard against look-ahead bias and
  is consumed by both the valuation recompute and Phase 4 backtest.

**Phase 1 tests:** as_of stamping on ingest; backfill correctness; `get_snapshot_as_of` excludes
future-dated rows; BVC field mapping round-trips through normalization.

---

## Phase 2 — Cost of capital: per-stock beta, live WACC, assumptions registry

**Goal:** kill the uniform-discount-rate problem. Every stock gets its own beta → its own cost of
equity → its own WACC, all built up transparently from named, editable assumptions.

### 2.1 Beta engine — `core/quant_core/fundamentals/cost_of_capital.py` (new)
- **Inputs:** daily OHLCV from `market_data_store` for the stock and the market proxy
  (default broad **MASI**), joined on normalized symbol (`normalize_symbol`, `data.py:826`).
- **Returns / window:** institutional default (per `dcf-model` skill) is **5-year monthly** beta vs the
  market index. For thin Moroccan names that is only 60 obs and still staleness-prone, so default to
  **2-year weekly** here with **5-year monthly** offered as an alternative — both exposed as registry
  assumptions (`beta_window`, `beta_frequency`) so the choice is visible/justifiable. Inner-join on
  common periods.
- **Standard path (normal liquidity):** OLS slope `beta = cov(r_stock, r_mkt) / var(r_mkt)`.
  Record `r²` and observation count.
- **Liquidity gate (decides which path):** classify a name as *very low liquidity* if its
  **zero-return-week fraction** (weeks the stock didn't move) exceeds a threshold **τ** OR traded
  weeks < N. Only these names get the robust treatment — everyone else uses plain OLS, per the
  agreed direction.
  - *Recommended default:* τ = 30% zero-return weeks, or < 60 valid weeks of ~104. (Tunable; lives
    in the assumptions registry so it is itself visible/justifiable.)
- **Robust path (very low liquidity only):**
  1. **Dimson (1 lag):** regress stock return on contemporaneous *and* prior-week market return;
     beta = sum of the two slopes (corrects delayed reaction of slow-trading stocks).
  2. **Blume shrink:** `beta_adj = 0.67·beta_raw + 0.33·1.0` (standard drift-to-market).
  3. **Peer-beta fallback:** if even Dimson is unstable (too few non-zero weeks / r² ~ 0), use the
     sector median *unlevered* beta relevered at the name's own D/E. Sector comes from the existing
     sector field used by `_relative_multiples`.
- **Levered/unlevered:** store raw (levered) beta; expose unlever/relever helper for the peer
  fallback using `D/E` from `Dettes_de_financement` / `Capitaux_propres` and `tax_rate`.
- **Persistence:** new `FundamentalBetaHistory(symbol, as_of, beta, method, r2, n_obs,
  zero_week_frac, liquidity_flag, proxy)` — `as_of` makes betas PIT-consistent for Phase 4.

### 2.2 Live WACC build-up (computed, not stored)
- Replace the flat `cost_of_equity = 0.089` constant with a derivation evaluated at use time:
  - `cost_of_equity = risk_free_rate + beta · equity_risk_premium`  (CAPM)
  - `wacc = w_e·Ke + w_d·Kd·(1 − tax_rate)`
- Capital weights `w_e/w_d`: default 70/30 (current) but allow per-name override from balance-sheet
  leverage (`Dettes_de_financement` vs market cap). Return the full build-up dict in the model
  `inputs` so the UI can render every term.
- Touch points: `valuation.py` model fns (`_fcff_dcf`, `_fcfe_dcf`, `_ddm`, `_residual_income`,
  `_justified_multiples`) read `cost_of_equity`/`wacc` from the resolved-assumptions dict; inject the
  computed values there via `resolve_assumptions` so no model body changes shape.

### 2.3 Assumptions registry + Assumptions tab
- **Backend:** promote `DEFAULT_ASSUMPTIONS` (`valuation.py:23`) into structured `ASSUMPTION_META`:
  per key → `{value, label, unit, derivation, source, plausible_range, scope}`. The existing
  calibration comment block (`valuation.py:17-22`) becomes machine-readable data. Serve via new
  `GET /fundamentals/methodology` (single source of truth; frontend stops hardcoding
  `MODEL_FORMULA_META`).
- **Global permanent edits:** rf, ERP, tax, terminal_growth, capital weights, liquidity τ — editable
  at **desk scope** via existing `FundamentalAssumptionSet(scope_type='desk')`; writes are versioned
  (append-only) so changes are auditable. Per-symbol still via `FundamentalAssumptionOverride`.
  Resolution order already implemented in `make_overrides_loader` / `resolve_assumptions`:
  default → desk → sector → symbol.
- **Assumptions tab (UI):** one table listing **every assumption of every model**, grouped by
  model, each row showing current value, provenance badge, derivation, source, and range, with
  inline edit (global or per-stock). Recompute triggers via existing recompute endpoint.

**Phase 2 tests:** beta math vs a hand-computed fixture; liquidity gate routes a known thin name to
robust path; WACC build-up reproduces 7.86% at beta=1.0/defaults; editing ERP at desk scope moves
every stock's Ke; methodology endpoint returns all keys with sources.

### Phase 2 — open decision (needs your input)
- **Liquidity threshold τ** and the *market proxy*: I recommend τ = 30% zero-return weeks and broad
  **MASI** as proxy. Both are stored in the registry so they stay visible/editable — but confirm
  you're happy with these defaults, or we tune τ after seeing the zero-return distribution across
  your 80 names (I can compute that empirically before fixing the number).

## Phase 3 — Forward estimates: driver-based 3-statement projection

**Goal:** replace the silent single-growth shortcut (`_fcf_growth_input`) with an explicit,
year-by-year, **driver-based** forecast whose every assumption is derived from history by a stated
rule, shown to the user, and editable. This is what makes the DCF *justifiable* rather than a black box.

### 3.1 The projection model (linked 3-statement, 5-year explicit + terminal)
Per stock × scenario, project years t+1…t+5 from the latest PIT actuals:

```
Revenue_t+i      = Revenue_t+i-1 × (1 + g_rev_i)             # g_rev fades to terminal
EBIT_t+i         = Revenue_t+i × ebit_margin_i               # margin mean-reverts
NOPAT_t+i        = EBIT_t+i × (1 − tax_rate)
Reinvestment_i   = Capex_i + ΔWC_i − D&A_i
   Capex_i       = Revenue_t+i × capex_pct_i
   ΔWC_i         = ΔRevenue_i × wc_pct                        # WC as % of incremental sales
FCFF_t+i         = NOPAT_t+i − Reinvestment_i
```

Balance-sheet linkage (with the full 3-statement fields from Phase 0): retained earnings roll
forward (Equity_t+i = Equity_t+i-1 + NetIncome_i − Dividends_i); debt held flat unless overridden;
cash is the plug. The three statements tie out for every name with full disclosure (the large
majority after Phase 0).

- **One projection feeds every intrinsic model** (no per-model re-derivation): FCFF DCF uses FCFF;
  FCFE DCF uses FCFF − after-tax interest ± debt flows; **DDM** uses projected dividends
  (`payout × NetIncome_i`); **RIM** uses the projected book value + ROE path. All from the same series.
- **Discounting convention:** adopt the **mid-year convention** (periods 0.5, 1.5, …; institutional
  default per the `dcf-model` skill) and apply it uniformly across the DCF family; expose as a registry
  assumption so it is explicit and toggleable.

### 3.2 How each driver's DEFAULT is derived (the rigor core — "how we get the estimates")
Every default is a **rule on the company's own PIT history**, not a guess. Each is overridable and
each carries a provenance string the UI shows.

| Driver | Default rule | Rationale |
|---|---|---|
| Revenue growth `g_rev` | Year 1 = blend(last-3y revenue CAGR, last-1y growth); then **fade linearly** to `terminal_growth` by year 5 | Anchors on demonstrated growth, mean-reverts to GDP-like terminal (no perpetual heroics) |
| EBIT margin | Start at trailing-3y average margin; **mean-revert** toward that average if last year is an outlier | Margins are mean-reverting; avoids extrapolating a peak/trough |
| Tax rate | `tax_rate` from assumptions (default 35%); use effective rate if cleanly derivable | Consistent with WACC tax shield |
| Capex % of revenue | Trailing-3y `|Capex|/Revenue` average | Reinvestment scales with the business |
| Working-capital % | Trailing `(Actif_circulant − Passif_circulant)/Revenue`, applied to *incremental* sales | Growth consumes WC |
| D&A | Trailing `Dotations/Revenue` × revenue | Keeps reinvestment net of non-cash |

- **Divergence flags:** when a chosen/edited driver diverges from its historical anchor beyond a
  band (e.g. growth > 1.5× historical CAGR), flag it in `warnings` and the UI.
- **Fallback (only names that genuinely don't disclose a cash-flow statement after Phase 0):** skip
  the full BS/CF linkage; project FCFF directly from Revenue→EBIT→NOPAT minus a reinvestment estimate
  from capex_pct (default to sector median capex% when the name's own is missing). Confidence is
  capped, mirroring the existing proxy-confidence convention.

### 3.3 Wiring into valuation
- New module `core/quant_core/fundamentals/projection.py`: `build_projection(snapshot, history,
  assumptions, scenario, overrides) -> Projection` (per-year IS/BS/CF + FCFF/FCFE series + a
  per-driver `DriverEstimate` evidence object carrying history + rule + inputs — see §3.5).
- `_fcff_dcf` / `_fcfe_dcf` consume `Projection.fcff/fcfe` instead of `_dcf_cash_flows(fcf, growth,…)`.
  Keep the old path as the fallback for names with no usable history (graceful degradation).
- Emit the **terminal-value-as-%-of-EV** diagnostic and the full projected series in `outputs`
  (already persisted via `FundamentalValuationResult.outputs_json`).
- **Persistence:** new `FundamentalProjection(symbol, scenario, fiscal_year, line_item,
  projected_value, evidence_json, as_of, is_override)` — `evidence_json` stores the `DriverEstimate`
  (history + rule + inputs + divergence, §3.5) so the UI renders justifications without recompute.
  Driver edits stored alongside (reuse the override pattern). PIT `as_of` so Phase 4 can reconstruct
  the forecast available at each date.

### 3.4 Estimation UI (two layers: shared projection in Synthèse + per-model conversion)
Mirrors the institutional model→valuation split (standalone "Estimations" tab removed):
- **Shared operating projection** — built once, shown in the `[Synthèse]` sub-tab: the editable
  **driver grid** (rows = drivers, cols = years t+1…t+5) pre-filled with §3.2-derived defaults (each
  cell shows provenance on hover + divergence flag), driving the linked **IS / CF / BS** projection
  and Bull/Base/Bear scenarios. **Reset-to-derived** + **save as override** persist per stock.
- **Per-model conversion** — each model sub-tab's "Estimation" step takes the shared projection and
  shows only *its* cash-flow series (FCFF / FCFE / dividends / book-value path), its **FCF trajectory
  chart** (bars Year 1–5; callout **TV = X% of EV**, flag if >75%), and its own sensitivity. No
  re-entry of revenue/margin drivers per model — they reference the shared projection.
- **Justification visuals (§3.5) are embedded throughout** — each driver in the grid and each model's
  cash-flow series carries its history→projection chart + derivation line + divergence badge, so growth
  and FCF estimates are never bare numbers.

### 3.5 Estimation justification — every estimate ships with its evidence (history + derivation)
**Principle:** no projected number appears without showing *where it came from*. Both quantities we
estimate — the **growth rate** and the **future free cash flow** — must be visually traceable to the
company's own history and to the rule that produced them.

**Backend — `DriverEstimate` (emitted by `build_projection`, persisted in `FundamentalProjection`):**
```
DriverEstimate {
  name                # e.g. "revenue_growth", "ebit_margin", "fcff"
  projected_by_year   # the forecast series t+1..t+5
  method              # human rule, e.g. "blend(3y CAGR 5.1%, last-yr 8.0%) → fade to g_term 2.5%"
  inputs              # the numbers feeding the rule (the CAGR, last-yr, terminal, weights)
  historical_series   # the ACTUALS used as anchor (last 5–7y of the metric)
  anchor_value        # the historical anchor the estimate is measured against
  divergence          # signed gap of the estimate vs anchor (+ flag if beyond band)
}
```

**Two flagship justifications (the ones you called out):**
1. **Growth-rate decomposition — "where did the growth rate come from?"** A chart overlaying the
   company's *actual* historical growth series — **revenue growth, EBIT growth, net-income growth,
   FCF growth** — with the series the estimate is anchored to highlighted, and the **fade path** drawn
   from Year-1 down to terminal growth. Caption states the rule + numbers (e.g. "Croissance Yr1 6.2 %
   = mélange(CAGR revenus 3 ans 5.1 %, dernière année 8.0 %) → converge vers 2.5 %"). This literally
   shows revenue-growth vs EBIT-growth vs … and which one drives the assumption.
2. **FCF estimation bridge — "where did the FCF come from?"** Actual **historical FCF** as solid bars
   + **projected FCF** as lighter bars on the same axis (so the forecast is read against the track
   record), plus a per-year **build-up waterfall**: Revenu → EBIT (×marge) → NOPAT (−impôt) →
   −réinvestissement (Capex + ΔBFR − D&A) = **FCFF**. The forecast is thus decomposed into its drivers,
   each of which has its own `DriverEstimate`.

**UI:** every estimated driver in the Synthèse projection grid and in each model sub-tab's Estimation
step renders: the **history → projection chart**, a **one-line derivation**, and a **divergence badge**;
expand shows `inputs`. Reuse `core/quant_core/research/stats` + a charting lib already in `frontend/`.

### 3.6 Projection integrity checks (institutional standard, per the `3-statement-model` skill)
The projected statements must pass the same checks a desk applies to any 3-statement model — extend the
existing `FundamentalIntegrityReport` (currently historicals-only) to cover **each projected year**:
- **Balance-sheet balance:** `Total_Actif = Total_Passif` (= 0 within tolerance) every projected year.
- **Cash tie-out:** CF ending cash = BS cash; beginning cash = prior-year ending cash.
- **Retained-earnings roll-forward:** `Equity_t = Equity_{t-1} + NetIncome_t − Dividends_t` (the §3.1 link).
- **Net-income link:** IS net income = CF starting net income.
- **Margin hierarchy (definitional):** Gross margin ≥ EBITDA margin ≥ EBIT margin ≥ net margin.
- **Scenario hierarchy:** Bull ≥ Base ≥ Bear for revenue, EBITDA, FCF and margins (flag violations).
- **Sign conventions:** Capex/ΔWC as use-of-cash (negative to FCF); dividends negative in CFF.
- **No circularity by design:** debt held flat → interest is not modelled dynamically, so no
  interest→NI→cash→debt loop. If a debt schedule is added later, enable iterative calc + a circuit breaker.
Surface pass/derived/warn/fail per check in each model's *Preuves & avertissements* panel, and haircut
confidence on `fail` (mirrors the existing integrity-haircut convention).

**Phase 3 tests:** driver defaults reproduce from a fixture history; projection ties out (BS balances,
cash plug correct, RE roll-forward) for a full-data name; **margin & scenario hierarchies hold**;
no-CF fallback produces capped-confidence FCFF; editing a driver changes fair value deterministically;
divergence flag fires when growth >> historical CAGR; **`DriverEstimate` carries the correct
historical_series and the derivation string matches the rule.**

### Phase 3 — open decisions (needs your input)
- **Forecast horizon:** keep **5 explicit years + Gordon terminal** (matches current
  `forecast_years=5`), or longer? 5 is desk-standard for stable names — recommended.
- **Terminal method:** Gordon growth (current) vs exit-multiple cross-check. Recommend showing
  **both** (Gordon as primary, implied exit EV/EBITDA as a sanity flag) once Phase 3 lands.

## Phase 4 — Point-in-time signal backtest

**Goal:** the single exhibit a desk actually believes — *does cheapness on our fundamental signal
predict forward returns, out-of-sample, with no look-ahead?* Only possible because Phase 1 stamped
`as_of_date` and `get_snapshot_as_of` reconstructs history correctly.

### 4.1 Engine — `core/quant_core/fundamentals/signal_backtest.py` (new)
- **Universe:** MASI names with both price history and ≥1 PIT fundamental snapshot at the date.
  Default backtest universe = MASI-20 (liquid; clean returns), with full-MASI as a secondary run.
- **Signal (per name, per rebalance date `d`):** from `get_snapshot_as_of(symbol, d)` →
  recompute ensemble → take **`upside_pct`** (primary) and the **composite pillar score** (secondary).
  Run both so we can compare which has the better information ratio.
- **Rebalance cadence:** monthly snapshot of the latest *available* (PIT) fundamentals; rank the
  universe into quintiles by signal; long top quintile / (optionally) short bottom; hold to next
  rebalance. Forward returns from `market_data_store` daily closes.
- **No look-ahead guard:** a fundamental row is only usable at `d` if `as_of_date <= d`. Asserted
  in the engine and covered by a test that injects a future-dated row and confirms it is excluded.
- **Costs:** apply a per-rebalance transaction-cost haircut (bps; in the assumptions registry).

### 4.2 Exhibits (reuse existing stats where possible)
- **Quintile spread:** forward-return by signal quintile (the headline bar chart).
- **Rank-IC + IC decay:** reuse `rank_ic()` / `ic_decay_curve()` in
  `core/quant_core/research/stats/ic.py` — Spearman of signal vs N-day forward returns, with
  Fisher-z confidence bands. This is the desk's preferred rigor metric.
- **Hit-rate, long-short equity curve, turnover.**
- Reuse `core/quant_core/risk.py` (`_sharpe_from_returns`, drawdown) for curve stats.

### 4.3 Persistence + API + exhibit page
- `FundamentalSignalBacktest(run_id, signal, universe, rebalance, as_of, quintile_returns_json,
  ic_json, equity_curve_json, params_json)`.
- `POST /fundamentals/signal-backtest` (enqueue) + `GET …/{run_id}` (results).
- Frontend exhibit page: quintile bars, IC-decay line, equity curve — the slide for the desk.

**Phase 4 tests:** future-dated row excluded (look-ahead guard); quintile assignment deterministic
on a fixture; IC sign matches a constructed monotone signal; costs reduce net return.

### Phase 4 — open decisions (needs your input)
- **Signal:** I'll run **both** `upside_pct` and the composite pillar score and report which
  predicts better — unless you want a single pre-committed signal.
- **Long-only vs long-short:** long-only top-quintile is the cleaner first exhibit (shorting MASI is
  often impractical). Recommend long-only headline + long-short as a secondary view.

---

## Cross-cutting — Presentation / UI (built incrementally on Phases 1–3)

The backend already computes most of this; the work is rendering it. Main files:
`frontend/components/strategy/signal-fundamental-view.tsx` (3.6k lines — refactor as we go),
`frontend/components/dashboard-v1/fundamental-directions-tab.tsx`, `frontend/lib/api.ts` (types).

### Per-model detail architecture (the organizing principle)
Each of the 7 valuation models gets its **own self-contained view** (like Comparables today), because
assumptions, estimates and sensitivity are all **model-specific** — there is no single growth number
or single sensitivity across models. This aligns the UI with the data model: `FundamentalValuationResult`
is already one row per `(symbol, scenario, model)` with its own `inputs_json`/`outputs_json`/`warnings`/
`methodology`, so this is mostly a frontend reorganization, not new backend.

- **Navigation:** **sub-tabs inside the existing "Valorisation" top tab** — `[Synthèse]` + one sub-tab
  per model `[FCFF][FCFE][DDM][Résiduel][M. justifié][M. relatif][DCF inversé]`. Each model sub-tab
  renders a reusable `ModelDetailPanel`.
- **Top-level tabs after this change:** Thèse / **Valorisation** / Qualité & ROE — **both** the
  standalone **"Estimations" AND "Comparables" tabs are REMOVED**. Neither is a valuation *method*;
  each is an **input to** models, so each folds into Valorisation (see below).
- **No input layer is a top-level tab** — every one of the 7 methods is a sub-tab, and its input lives
  with it, or in `[Synthèse]` when broadly shared. The placement rule is **scope**, not specialness:
  - **Operating projection** (Revenue → marges → IS/CF/BS → scénarios) feeds *many* models (FCFF, FCFE,
    informs DDM/RIM) → **broadly shared → lives in `[Synthèse]`**, built once (no de-sync across sub-tabs).
  - **Peer comparables** feed only the two multiples models → **family-specific → lives in the
    `[M. relatif]` sub-tab** (the current Comparables view, relocated), referenced by `[M. justifié]`.
- **Pattern confirmed via the `dcf-model` + `initiating-coverage` skills:** shared financial model →
  per-method valuation + its own sensitivity → football field triangulation.
- **`[Synthèse]` sub-tab** = the **football field** (each method's fair-value range as a horizontal bar,
  current price overlaid) triangulating the 7 — the institutional "do the methods agree?" exhibit —
  plus the shared operating projection that feeds them.
- **`ModelDetailPanel` template (consistent across models, adapts to type):**
  1. *Header* — juste valeur, upside %, confidence badge.
  2. *Hypothèses utilisées* — only this model's assumptions, incl. the **WACC/Ke build-up**
     (rf + β·ERP → Ke; weights → WACC) from `ASSUMPTION_META`. Inline-editable → recompute.
  3. *Estimation* — this model's projection: FCFF (FCFF DCF) · FCFE (FCFE DCF) · dividends+sustainable
     growth (DDM) · book value+ROE path (RIM) · implied multiples (justified) · peer median (relative)
     · implied-g diagnostic (reverse DCF). Driver provenance shown per Phase 3.
  4. *Formule instanciée* — the formula with this stock's own numbers (e.g. `FV = 4.20/(8.9%−2.5%) = 65.6`).
  5. *Sensibilité* — **this model's** parameters only (FCFF: WACC×g heatmap; DDM: Ke×payout; relative:
     peer-set composition), so it is unambiguous which model the sensitivity belongs to. *(Requires
     per-model sensitivity grids — see Phase 2 note below.)*
  6. *Preuves & avertissements* — statement evidence rows + warnings + confidence decomposition.
- Drives display from the `/methodology` endpoint (Phase 2.3), replacing the static TS
  `MODEL_FORMULA_META` (kills TS/Python drift).

### Backend note unlocked by this design
- **Per-model sensitivity:** the sensitivity engine must emit grids **per intrinsic model** keyed to
  that model's own parameter (WACC for FCFF; Ke/terminal-g for FCFE/DDM/RIM; peer-set for relative),
  not one shared grid. Fold into Phase 2 sensitivity work.
- **Grid spec (per `dcf-model` skill):** **odd N×N (5×5)** so the **center cell = base case** —
  axis = `[base−2·step, base−step, base, base+step, base+2·step]`; the center must equal the model's
  actual fair value (built-in sanity check). Render as a heatmap with the base cell highlighted.

### Comparables & multiples rigor (M. relatif & M. justifié — per the `comps-analysis` skill)
Upgrade `_relative_multiples` / the `[M. relatif]` sub-tab beyond "apply the median":
- **Full quartile distribution** per multiple (P/E, EV/EBITDA, P/B, P/S): **Max / 75th / Median / 25th /
  Min**, with the subject company's own multiple marked in the distribution — so the user sees whether it
  trades rich or cheap vs peers, not just a point median.
- **Peer hygiene (exclude rather than force):** drop **negative / NM multiples** (e.g. negative-EBITDA
  name → exclude from EV/EBITDA, fall back to EV/Revenue or P/B); **winsorize** at p10/p90; flag
  **different fiscal-year-ends**; require the existing `peer_min_count` (≥3) else widen to sector→market.
- **Show the peer set used** (which names, why) + each peer's multiple — the `[M. relatif]` input section.
- **EBITDA definition consistency:** EV/EBITDA must use the *same* EBITDA as the DCF family
  (`Excedent_brut_dexploitation`, else EBIT + Dotations) so multiples and intrinsic models agree.

### Inputs live in the model (standalone "Estimations" AND "Comparables" tabs removed)
Per the institutional pattern, neither forward estimates nor peer comparables are standalone tabs —
they are *inputs* consumed by valuation methods. So:
- Remove the top-level **"Estimations"** tab → the **shared operating projection** is built **once** in
  `[Synthèse]` (revenue/margins/IS/CF/BS + scenarios, §3.2 rules); each model sub-tab renders only the
  model-specific cash-flow derived from it. Reuse `fundamental-estimates-utils.js` here, not a standalone view.
- Remove the top-level **"Comparables"** tab → the current peer-benchmarking view becomes the input
  section of the **`[M. relatif]`** sub-tab, referenced by `[M. justifié]`.
- Every estimated quantity must ship with its **justification visual** (Phase 3.5): historical actuals
  + the projection + the derivation, so no number is unexplained.

### Other UI (shared across the hub)
- **Football field** (Synthèse): per-method fair-value bars + current price — the triangulation exhibit.
- **Score-pillar explainers:** popover decomposing each pillar into its percentile inputs + weight
  (data already in `scores_json`).
- **Assumptions tab** (Phase 2) — every assumption of every model in one auditable table.
- **Confidence decomposition** surfaced inside each `ModelDetailPanel` (step 6 above).

## Verification (end-to-end, per phase)

- P1: ingest a known filing → confirm `as_of_date` set; `get_snapshot_as_of(t)` hides later filings.
- P2: pick a high-beta and a low-beta name → confirm different Ke/WACC and different fair values;
  edit ERP in the assumptions tab → values move.
- P3: edit a revenue-growth driver → projected FCF and DCF fair value recompute; TV% shown; every
  estimate (growth, FCF) shows its **history + derivation** (growth decomposition chart; FCF bridge).
- P4: run backtest → cheap-quintile outperforms, with PIT data (no look-ahead).
- Tests green: `python -m pytest core/tests/ services/api/tests/ -q`.

## Decisions log

**Resolved**
- Full 3-statement via **scraper upgrade**, not model downgrade. *(46-field CGNC schema implemented +
  pilot-validated; perfect BS tie-outs.)*
- Field schema = **classical CGNC / Plan Comptable Marocain** labels (CPC, ESG, Bilan, Tableau de
  financement), IFRS equivalents accepted.
- Backtest history target = **5+ years** → requires the 2016–2025 backfill.
- **EBITDA** = `Excedent_brut_dexploitation` when present; else **derive EBIT + Dotations** (IFRS/banks).
- **Document priority:** RFA (full report) over CP (press release).
- Beta = **OLS** for normal-liquidity names; robust path (Dimson+Blume / peer-beta) **only** for very
  low-liquidity names.
- rf / ERP / tax etc. live in an **editable assumptions registry** (desk-scope permanent edits +
  per-symbol overrides), surfaced in an **Assumptions tab**.
- **Per-model UI:** each of the 7 models gets its own self-contained view (like Comparables) via
  **sub-tabs inside the Valorisation tab** (`[Synthèse]` + 7 model sub-tabs), each rendering a reusable
  `ModelDetailPanel`; assumptions/estimation/sensitivity rendered per model. Requires per-model
  sensitivity grids (folded into Phase 2).
- **Standalone "Estimations" AND "Comparables" tabs REMOVED** (justified via `dcf-model` +
  `initiating-coverage` skills). Neither is a valuation *method* — both are *inputs* to models, so both
  fold into Valorisation by the same rule. Placement by **scope**: operating projection (broadly shared)
  → `[Synthèse]`; peer comparables (multiples-only) → `[M. relatif]` sub-tab. Top-level tabs become
  **Thèse / Valorisation / Qualité & ROE**.
- **Synthèse = football field** (per-method fair-value bars vs price) + the shared projection.
- **Every estimate must be justified visually** (history + derivation) — see Phase 3.5.

**Open (recommended default in italics — confirm at implementation time, not blocking the plan)**
- Liquidity threshold **τ**: *30% zero-return weeks* (tune after plotting the empirical distribution
  across the 80 names).
- Market proxy for beta: *broad MASI* (MASI-20 as secondary).
- Forecast horizon: *5 explicit years + Gordon terminal*; terminal cross-checked with implied exit
  EV/EBITDA.
- Backtest signal: *run both `upside_pct` and composite score*, report which predicts better.
- Backtest stance: *long-only top-quintile headline* + long-short secondary.
- Backtest assumptions: *apply current rf/ERP across history* (testing signal ranking power, not rate
  regimes); revisit if regime sensitivity matters.

## Progress log
- **2026-06-01:** Diagnosis complete. Scraper schema upgraded to 46 CGNC fields + prompt rules
  (`fama french/src/scraper/pdf_parser_llm.py`); pilot (`scratch/pilot_full_3statement.py`) validated
  full 3-statement extraction on 6 reports. Plan authored end-to-end.
- **Next:** Phase 0 flux page-targeting fix + RFA-prioritization, then mass backfill (Track A);
  Phase 2.1 beta engine can start in parallel (Track B).
- **2026-06-01 (final review):** Audited the plan against the `financial-analysis/dcf-model`,
  `3-statement-model`, and `comps-analysis` skills + `equity-research/initiating-coverage`. Added:
  projected-statement integrity checks (§3.6: BS balance, cash tie-out, RE roll-forward, margin &
  scenario hierarchies); comparables/multiples rigor (quartile distribution + peer hygiene +
  EBITDA-definition consistency); DDM/RIM drawing from the shared projection; mid-year discounting
  convention; fixed the stale "estimation tab" reference. Plan is implementation-ready for Codex.
- **2026-06-01 (Phase 2.1 / Track B):** Added `cost_of_capital.py` beta engine (2y weekly OLS,
  zero-return liquidity gate, Dimson+Blume robust path, peer relevered fallback, leverage helpers)
  plus `FundamentalBetaHistory` persistence and tests. Targeted tests:
  `python -m pytest core/tests/test_cost_of_capital.py services/api/tests/test_fundamental_beta_history.py -q`
  passed (5 passed). Full backend suite attempted with
  `python -m pytest core/tests/ services/api/tests/ -q`: 1249 passed, 20 failed from pre-existing
  Plotly/Narwhals `xbbg._core` Bloomberg DLL loading and market-universe share-field fixture issues,
  not from the beta engine changes.
- **2026-06-01 (Phase 0.2-0.4 / Track A code-ready):** Updated the scraper code in
  `C:\Users\taha\Downloads\fama french` for RFA-first document priority with `Document_Kind`, flux
  page targeting, failed-annual retry queue/failure categorization, 2016 default start year, and
  full-3-statement-completeness-aware dedup. Added `README_fundamental_backfill.md` with dry-run and
  managed-run commands. Tests: `python -m pytest test_fundamental_normalizer.py test_pipeline_document_priority.py -q`
  passed (8 passed). Smoke dry-run with `--max-pages 0 --max-docs 1 --retry-failed` completed without
  downloading PDFs or calling Gemini. Mass Gemini backfill not run.
  - **2026-06-01 (Phase 1 / PIT data foundation):** Added nullable `as_of_date` and
    `source_document_id` to annual metrics and latest snapshots, plus `document_kind` on source
    documents, with a conservative Alembic backfill from existing document lineage. Added CGNC-to-engine
    mapping (`Revenue`, `EBITDA`, `Free_Cash_Flow`, leverage/cash/working-capital aliases), EBITDA and
  CFO/FCF derivations, archetype tagging, BVC period-metric sync into the consumed annual/latest
  layers, and `get_snapshot_as_of(...)` look-ahead guard. Targeted tests:
  `python -m pytest core/tests/test_cgnc_mapping.py core/tests/test_cost_of_capital.py services/api/tests/test_fundamentals_pit.py services/api/tests/test_fundamental_beta_history.py -q`
  passed (10 passed); affected API tests passed (9 passed); Alembic heads = `e2f3a4b5c6d7`.
  Full backend suite attempted with `python -m pytest core/tests/ services/api/tests/ -q`: 1258
    passed, 20 failed from the same pre-existing Plotly/Narwhals `xbbg._core` Bloomberg DLL loading
    and market-universe share-field fixture issues, not from Phase 1 changes.
  - **2026-06-01 (Phase 2.2-2.3 / WACC + assumptions registry):** Promoted valuation assumptions into
    structured `ASSUMPTION_META`, served `GET /fundamentals/methodology`, made `wacc` and
    `cost_of_equity` computed from PIT beta/CAPM/default capital weights at resolution time, and added
    append-only desk/symbol assumption updates with computed-field guardrails. The UI now consumes the
    methodology registry, exposes a French Hypotheses tab, supports symbol and desk-scope assumption
    saves, and shows the full cost-of-capital build-up in valuation model inputs. Targeted tests:
    `python -m pytest core/tests/test_cost_of_capital.py services/api/tests/test_fundamentals_assumption_overrides.py
    services/api/tests/test_fundamentals_workflow_api.py -q` passed (12 passed). Frontend checks:
    `npm run build` and `npx tsc --noEmit` passed. Full backend suite attempted with
    `python -m pytest core/tests/ services/api/tests/ -q`: 1260 passed, 20 failed from the same
    pre-existing Plotly/Narwhals `xbbg._core` Bloomberg DLL loading and market-universe share-field
    fixture issues, not from Phase 2 changes.
  - **2026-06-01 (Phase 3 / Forward estimates projection engine):** Added the shared 5-year
    driver-based 3-statement projection engine with `DriverEstimate` evidence, no-CF driver fallback,
    mid-year discounting, terminal-value diagnostics, projected-statement integrity checks, and
    scenario-hierarchy checks. FCFF, FCFE, DDM, and residual-income models now consume the shared
    projection; `FundamentalProjection` persists per-line PIT forecast evidence; the valuation UI now
    shows the French shared operating projection grid inside Valorisation. Targeted tests:
    `python -m pytest core/tests/test_projection.py core/tests/test_cost_of_capital.py
    services/api/tests/test_fundamental_projection_persistence.py
    services/api/tests/test_fundamentals_assumption_overrides.py
    services/api/tests/test_fundamentals_workflow_api.py -q` passed (18 passed). Frontend checks:
    `npx tsc --noEmit` and `npm run build` passed. Full backend suite attempted with
    `python -m pytest core/tests/ services/api/tests/ -q`: 1266 passed, 20 failed from the same
    pre-existing Plotly/Narwhals `xbbg._core` Bloomberg DLL loading and market-universe share-field
    fixture issues, not from Phase 3 changes.
  - **2026-06-01 (Phase 4 / PIT signal backtest):** Added the point-in-time fundamental signal
    backtest engine with rebalance-date look-ahead guard, deterministic quintile assignment,
    long-only top-quintile headline, IC/IC-decay, turnover, holdings, and equity-curve exhibits.
    Added `FundamentalSignalBacktest` persistence, Alembic migration, `POST /fundamentals/signal-backtest`,
    `GET /fundamentals/signal-backtest/{run_id}`, and a French Backtest tab that renders quintile
    returns, IC decay, latest holdings, and the equity curve. Targeted tests:
    `python -m pytest core/tests/test_fundamental_signal_backtest.py
    services/api/tests/test_fundamental_signal_backtest_api.py -q` passed (6 passed). Frontend
    checks: `npx tsc --noEmit` and `npm run build` passed. Full backend suite attempted with
    `python -m pytest core/tests/ services/api/tests/ -q`: 1272 passed, 20 failed from the same
    pre-existing Plotly/Narwhals `xbbg._core` Bloomberg DLL loading and market-universe share-field
    fixture issues, not from Phase 4 changes. Live Phase 4 production results still depend on the
    user-managed Track A Gemini backfill.
  - **2026-06-01 (Cross-cutting UI consolidation):** Consolidated the French fundamentals UI so
    Valorisation now owns `[Synthese]` plus one sub-tab per valuation model, including `M. relatif`
    for peer comparables. The former top-level Estimations and Comparables tabs are folded into
    Synthese / M. relatif, while the assumptions registry and Phase 4 Backtest remain top-level
    workflow tabs. Frontend checks: `npx tsc --noEmit` and `npm run build` passed.
