# Brief 45 — StockAnalysis canonical cutover + archetype-aware N/R elimination (Sonnet)

**Owner:** Sonnet implementer
**Branch:** `feature/fundamental-ui-consolidation` (current)
**Goal:** Make StockAnalysis the single source of truth for fundamentals, collapse the duplicate
`Clean_*`/French alias schema to one canonical set, compute **all** ratios from raw 3-statement data
(never store scraped ratios) **with the correct ratio set per company archetype (industrial / bank /
insurance)**, and as the concrete success metric, **eliminate "N/R" (Not Rated) recommendations on
the fundamental signal page** for every covered symbol — banks included. Leave the Gemini/BVC scraper
**dormant but intact** (do not delete it).

> Read this whole brief + the files it references before writing any code. Then post your
> phase-by-phase plan and the exact files for Phase 0 for confirmation.

---

## 0. Background — why symbols show "N/R" (verify, don't re-investigate)

1. `frontend/components/strategy/signal-fundamental-view.tsx:1647-1651` — `recommendationLabel(null) → "N/R"`. A row is N/R iff `recommendation` is null.
2. `recommendation` is null when scoring/valuation produce no aggregate score.
3. `services/api/app/services/fundamental_signal_engine.py:223-226` — aggregate is `None` → status `failed`, label `Indisponible` → N/R.
4. `core/quant_core/fundamentals/scoring.py:26-32` — pillar scores need canonical metric names (`PER`, `Price_to_Book`, `ROE`, `ROA`, margins, growth, etc.).
5. Legacy BVC/Gemini data stores metrics under inconsistent aliases (`Clean_*`, French) and stores **scraped** ratios the scorer can't read; the value pillar also needs **price-derived** metrics the provider doesn't currently compute.

**Fix:** clean canonical re-ingest via StockAnalysis + a central, **archetype-aware** ratio layer that
produces every scorer input from raw lines = scores compute = `recommendation` non-null = no N/R.

### Coverage audit (already done — DO NOT repeat)
- StockAnalysis covers **75/75** active symbols in `data/universe/bvc_pit_universe.csv`.
- Spot-check: AFI, EQD, ZDJ, NEJ, VCN, TGC → full 2020/21–2025 statements (102 raw metrics each).
- **IBC** → listed but no statement tables; expected to stay N/R (acceptable). Must surface as an
  explicit no-coverage quality issue, not a silent N/R. Do NOT fall back to Gemini for it.

---

## 0b. THE ARCHETYPE DIMENSION (this is the part that must not be skipped)

Banks (ATW, BCP, BOA, CIH, CDM, BCI/BMCI, …) and insurers (WAA, SAH, ATL, AGM, …) are a large share of
MASI and have fundamentally different statements. Industrial ratios (`Operating_Margin`, `Current_Ratio`,
`Cash_Ratio`, `Debt_to_Equity`, `NetDebt_to_EBITDA`, `EV_to_EBITDA`, `Interest_Coverage`, FCF anything)
are **meaningless for banks** and must NOT be computed or scored for them. Banks need bank ratios; ranking
must be **against bank peers only**.

What already exists (reuse, don't reinvent):
- `core/quant_core/fundamentals/cgnc_mapping.py:93` `infer_statement_archetype(metric_names) -> "bank"|"insurance"|"cgnc_social"|"ifrs_consolidated"|...`
- `cgnc_mapping.py:55` `FINANCIAL_ARCHETYPES = {"bank", "insurance"}`
- `cgnc_mapping.py:56-69` `FINANCIAL_SUPPRESSED_METRICS` (Capex/EBITDA/EV_to_EBITDA/FCF_*/Net_Debt/Price_to_Sales…)
- `valuation.py` is already archetype-aware (`test_bank_valuation.py` drives bank/insurer assumptions via `_financial_archetype`).
- The StockAnalysis provider already scrapes bank lines: `Net_Interest_Income`, `Total_Interest_Income`,
  `Interest_Income_on_Loans`, `Interest_Paid_on_Deposits`, `Total_NonInterest_Income`,
  `Revenues_Before_Loan_Losses`, `Provision_for_Loan_Losses`, `Loans_Net`, `Customer_Deposits`.

**Two bugs to fix in detection (critical):**
- `infer_statement_archetype` only matches **French** tokens (`BANK_FIELD_TOKENS`/`INSURANCE_FIELD_TOKENS`).
  StockAnalysis banks emit **English** line names → would be misclassified as industrial. Extend
  `BANK_FIELD_TOKENS` with English tokens (`net_interest_income`, `interest_income_on_loans`,
  `interest_paid_on_deposits`, `customer_deposits`, `total_deposits`, `net_loans`,
  `provision_for_loan_losses`) and `INSURANCE_FIELD_TOKENS` likewise if StockAnalysis exposes premium lines.
- Detection must consider **non-null** metrics only. The provider writes bank keys for everyone (null for
  industrials); detecting on key presence would mis-flag industrials. Pass only non-null metric names, or
  add a `infer_statement_archetype_from_values(metrics: dict)` helper that filters nulls first.

Insurance note: StockAnalysis may not expose true insurance-format statements for MASI insurers. If a
symbol can't be confidently classified as insurance from its lines, treat it as a generic **financial**
(suppress industrial ratios, compute ROE/ROA/PER/P_B/Dividend_Yield) and emit an `archetype_uncertain`
info quality issue. Optionally fall back to `StockMaster.sector`/industry for the hint. Don't over-build insurers.

---

## Existing assets to REUSE (do not rebuild)
- `core/quant_core/fundamentals/providers/stockanalysis_provider.py` — `StockAnalysisFundamentalProvider`.
- `services/worker/tasks/refresh_stockanalysis_fundamentals.py` — `refresh_stockanalysis_universe()`.
- `core/quant_core/fundamentals/cgnc_mapping.py` — archetype detection, alias groups, suppressed-metric set.
- `core/quant_core/data.py` — market price source for price-derived ratios.

---

## Phase 0 — Canonical schema + archetype-aware ratios module + tests (foundation; do first)

### 0a. `cgnc_mapping.py` — canonical names, aliases, archetype detection fix
- `CANONICAL_METRICS: frozenset[str]` — all names scoring/valuation read, derived from `scoring.py`'s
  metric tuples PLUS the raw items ratios are built from: `Revenue, NetIncome, EBIT, EBITDA, Gross_Profit,
  Total_Assets, Total_Equity, Total_Debt, Net_Debt, Cash, Current_Assets, Current_Liabilities,
  Interest_Expense, Income_Tax_Expense, CAF, Operating_Cash_Flow, Free_Cash_Flow, Capital_Expenditures,
  Depreciation_Amortization, Dividendes, Shares_Outstanding`
  **PLUS bank/insurer raw lines:** `Net_Interest_Income, Total_Interest_Income, Interest_Income_on_Loans,
  Interest_Paid_on_Deposits, Total_NonInterest_Income, Revenues_Before_Loan_Losses,
  Provision_for_Loan_Losses, Loans_Net, Customer_Deposits, PNB, Cout_du_risque`.
- `METRIC_ALIASES: dict[str, tuple[str, ...]]` (canonical → legacy twins). Include at least:
  - `Revenue` → `("Chiffre_daffaires","Clean_Chiffre_daffaires")`
  - `NetIncome` → `("Resultat_net","Net_Income","Clean_Resultat_net")`
  - `EBIT` → `("Resultat_dexploitation",)`; `EBITDA` → `("Excedent_brut_dexploitation",)`
  - `Gross_Profit` → `("Marge_brute","Marge_Brute")`
  - `Depreciation_Amortization` → `("Dotations_dexploitation","DandA")`
  - `Total_Assets` → `("Total_Actif",)`; `Total_Equity` → `("Capitaux_propres","Clean_Capitaux_propres","Equity")`
  - `Total_Debt` → `("Dettes_de_financement","Debt_Total")`; `Net_Debt` → `("NetDebt",)`
  - `Cash` → `("Tresorerie_Actif","Cash_and_Equivalents","CFS_Ending_Cash")`
  - `Operating_Cash_Flow` → `("CF_Operating","Flux_de_tresorerie_lies_a_lactivite","Flux_tresorerie_activites_operationnelles")`
  - `CAF` → `("Capacite_dautofinancement",)`
  - `Current_Assets` → `("Actif_circulant",)`; `Current_Liabilities` → `("Passif_circulant",)`
  - `Dividendes` → `("Dividends_Paid","Clean_Dividendes")`
  - `Interest_Expense` → `("Charges_Interets",)`; `Income_Tax_Expense` → `("Impots_sur_les_resultats",)`
  - bank: `PNB` → `("Produit_Net_Bancaire",)`; `Loans_Net` → `("Creances_sur_la_clientele",)`;
    `Cout_du_risque` → `("Cost_of_Risk",)`
- `_ALIAS_TO_CANONICAL` (inverted, built at load), `resolve_metric_name(name)->str` (identity if unknown),
  `canonicalize_metrics(dict)->dict` (canonical wins if non-null, else alias value promoted).
- **Detection fix:** extend `BANK_FIELD_TOKENS` with the English tokens listed in §0b; add
  `infer_statement_archetype_from_values(metrics: dict) -> str` that filters null values then calls
  `infer_statement_archetype`.

### 0b. New `core/quant_core/fundamentals/ratios.py`
Pure (no IO). `compute_ratios(raw_by_year, *, archetype, price, shares) -> dict[int, dict[str, float]]`.
Branch on `archetype`:

**Industrial (default):**
- margins: `Operating_Margin=EBIT/Revenue`, `Net_Margin=NetIncome/Revenue`, `FCF_Margin=Free_Cash_Flow/Revenue`,
  `Operating_CF_Margin=Operating_Cash_Flow/Revenue`, `CAF_Margin=CAF/Revenue`
- returns: `ROA=NetIncome/Total_Assets`, `ROE=NetIncome/avg(Total_Equity[y],[y-1])` (cross-year loop)
- leverage/health: `Debt_to_Equity`, `NetDebt_to_Equity`, `NetDebt_to_EBITDA`, `Equity_Multiplier=Total_Assets/Total_Equity`,
  `Current_Ratio=Current_Assets/Current_Liabilities`, `Cash_Ratio=Cash/Current_Liabilities`,
  `Interest_Coverage=EBIT/Interest_Expense`
- growth: `Revenue_Growth`, `EBIT_Growth`, `NetIncome_Growth` (YoY, needs prior year)
- price (latest year only; null if price/shares None): `Market_Cap_Calc=price*shares`,
  `EV_Calc=Market_Cap_Calc+Net_Debt`, `PER=Market_Cap_Calc/NetIncome`, `Price_to_Book=Market_Cap_Calc/Total_Equity`,
  `Price_to_Sales=Market_Cap_Calc/Revenue`, `EV_to_EBITDA=EV_Calc/EBITDA`,
  `FCF_Yield=Free_Cash_Flow/Market_Cap_Calc`, `Dividend_Yield=Dividendes/Market_Cap_Calc`

**Bank:** compute ONLY:
- `ROE` (avg equity), `ROA`, `Net_Margin=NetIncome/Revenue` (Revenue = bank total revenue / PNB),
  `Equity_Multiplier=Total_Assets/Total_Equity`
- `Net_Interest_Margin = Net_Interest_Income / avg(Total_Assets)` (proxy for earning assets; fallback `/Total_Assets[y]`)
- `Cost_to_Income = Operating_Expenses / Revenue` (Operating_Expenses already maps from "Total Non-Interest Expense")
- `Loans_to_Deposits = Loans_Net / Customer_Deposits`
- `Cost_of_Risk = abs(Provision_for_Loan_Losses) / Loans_Net`
- growth: `Revenue_Growth`, `NetIncome_Growth`
- price (latest only): `PER`, `Price_to_Book`, `Dividend_Yield` **only** (NO EV/EBITDA, P/S, FCF yield)
- Do NOT emit any metric in `FINANCIAL_SUPPRESSED_METRICS` for banks.

**Insurance / uncertain-financial:** ROE, ROA, Net_Margin, Equity_Multiplier, growth, + price PER/P_B/Div_Yield.
Suppress industrial-only ratios. (Combined ratio only if premium/claims lines are actually present.)

Invariant: reads only `raw_by_year`; never accepts/emits a scraped ratio key; pure (input unmodified).

### 0c. Tests
- `core/tests/test_ratios.py` — industrial fixture (hand-checked golden values, 1e-9 tol; price present
  and price=None cases; purity check) **AND a bank fixture** (raw with `Net_Interest_Income`,
  `Loans_Net`, `Customer_Deposits`, `Provision_for_Loan_Losses`, `Operating_Expenses`, no EBITDA/FCF):
  assert bank ratios present and correct, and that suppressed industrial ratios (`EV_to_EBITDA`,
  `Current_Ratio`, `Debt_to_Equity`, `FCF_Margin`) are **absent**.
- `core/tests/test_metric_canonicalize.py` — every alias resolves to its canonical; idempotent;
  unknown passes through; `{"Clean_Chiffre_daffaires":1.0,"Revenue":2.0}→{"Revenue":2.0}`;
  `{"Clean_Chiffre_daffaires":1.0}→{"Revenue":1.0}`; no alias maps to two canonicals (collision test).
- Extend `core/tests/test_cgnc_mapping.py` / `test_bank_valuation.py`: assert
  `infer_statement_archetype_from_values` classifies a StockAnalysis-style **English** bank metrics dict as `"bank"`,
  and an industrial dict (bank keys present but null) as **not** bank.

---

## Phase 1 — Provider + ingestion emit canonical raw only; ratios wired with archetype + price
- `stockanalysis_provider.py`: stop emitting alias twins and inline ratios (the `Clean_*`, `Marge_Brute`,
  `Resultat_dexploitation`, and the `ROE/ROA/Net_Margin/...` block ~lines 446-559). Emit **raw canonical
  statement lines only** — including the bank lines, which it already fetches.
- `refresh_stockanalysis_fundamentals.py`: after building the workbook, per symbol:
  1. determine archetype via `infer_statement_archetype_from_values(latest non-null metrics)`,
  2. look up current price (from `core/quant_core/data.py`) + shares,
  3. call `ratios.compute_ratios(raw_by_year, archetype=…, price=…, shares=…)`, merge into each year +
     the latest snapshot, and stash `archetype` in `snapshot.source`/diagnostics so scoring can read it,
  4. then `_persist_workbook`.

## Phase 2 — StockAnalysis = source of truth; Gemini dormant
- Do NOT delete `services/worker/tasks/targeted_bvc_fundamentals.py` or its scripts. Disable triggers
  only (grep `execute_bvc_fundamental_import`, `execute_targeted_bvc_fundamental_import`, `targeted_bvc`);
  gate behind explicit opt-in / manual-only. Add header note: "DORMANT — superseded by
  refresh_stockanalysis_universe (brief 45)."
- New `scripts/purge_legacy_fundamental_aliases.py` (idempotent, **dry-run default**, `--apply` to write):
  delete `Clean_*` + scraped-ratio rows from `FundamentalAnnualMetric`/period metrics; strip alias keys
  from `FundamentalLatestSnapshot.metrics_json`. Print counts.

## Phase 3 — Readers via resolver
- Route `Clean_*`/alias reads through `resolve_metric_name`/`canonicalize_metrics`: `scoring.py`,
  `valuation.py`, `screens.py`, `projection.py`, `signal_backtest.py`,
  `services/api/app/services/fundamentals.py`, `frontend/lib/fundamental-statement-utils.js`,
  `frontend/components/data/fundamentals-catalog.tsx`. Frontend de-dupes display so each metric shows once.

## Phase 3b — Archetype-aware scoring (the piece that makes differentiation real)
In `core/quant_core/fundamentals/scoring.py` (`score_fundamental_snapshots`, lines ~355-404):
- Resolve each snapshot's archetype (from the value stashed in Phase 1, else
  `infer_statement_archetype_from_values`).
- Select pillar metric sets **per archetype**:
  - bank quality = `(ROE, ROA, Net_Margin, Net_Interest_Margin, Cost_to_Income[lower])`;
    bank risk = `(Cost_of_Risk[lower], Equity_Multiplier[lower])`;
    bank value = `(PER, Price_to_Book, Dividend_Yield)`; bank cash_flow pillar = omitted.
  - industrial = current tuples.
  - Add `Cost_to_Income`, `Cost_of_Risk`, `Loans_to_Deposits` to `LOWER_IS_BETTER` where appropriate.
- **Segment peer cohorts by archetype** in `_metric_percentiles` (rank banks vs banks, industrials vs
  industrials) — pass an `archetypes: dict[str,str]` map; reuse the existing sector-segmentation
  machinery. `_weighted_score` already renormalizes over present pillars, so an omitted bank cash_flow
  pillar is fine as long as coverage ≥ 0.5.
- Suppress `FINANCIAL_SUPPRESSED_METRICS` for financial archetypes so they never enter a bank's pillars.
- Tests: a bank snapshot scores on bank metrics, gets non-null `value`/`quality`/`risk`, and is never
  ranked on `EV_to_EBITDA`/`Current_Ratio`/`Debt_to_Equity`.

## Phase 4 — Re-ingest + verify
- Run `refresh_stockanalysis_universe()` for the full active universe; confirm N/R only for
  genuinely-uncovered names (IBC-class) — **banks must NOT be N/R**.

---

## Acceptance criteria
1. `refresh_stockanalysis_universe` over 75 active symbols → ≥74 succeed; IBC fails with an explicit
   no-coverage quality issue.
2. Fundamental signal page: **0 N/R for covered symbols, banks included.**
3. Every bank snapshot has `archetype == "bank"`, carries bank ratios (NIM, Cost_to_Income,
   Loans_to_Deposits, Cost_of_Risk, ROE, ROA, Price_to_Book) and **no** industrial-only ratios; banks
   are percentile-ranked against bank peers only.
4. No snapshot stores any `Clean_*` key or scraped ratio.
5. All existing fundamentals tests pass + new Phase 0c/3b tests pass.
6. Gemini/BVC code still imports and runs if manually invoked (dormant, not deleted).

## Verification commands (repo root, `.venv`)
```bash
.venv/Scripts/python.exe -m pytest core/tests/ services/api/tests -k "fundamental or ratio or scoring or canonical or bank or cgnc" -q
.venv/Scripts/python.exe scripts/purge_legacy_fundamental_aliases.py        # dry-run preview
# archetype spot-check on a real bank (ATW) and industrial (AFI)
.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'.'); from core.quant_core.fundamentals.providers.stockanalysis_provider import StockAnalysisFundamentalProvider as P; from core.quant_core.fundamentals.cgnc_mapping import infer_statement_archetype_from_values as a; [print(s, a({k:v for k,v in P(retries=1).fetch(s).latest_snapshots[0].metrics.items() if v is not None})) for s in ('ATW','AFI')]"
```

## Guardrails
- Backend-first; land Phase 0 + tests before readers (Phase 3/3b) or frontend. One commit per phase — no big-bang.
- Destructive DB cleanup defaults to dry-run; `--apply` only AFTER canonical re-ingest so readers never see a gap.
- Do not delete the Gemini/BVC path.
- If anything in §0/§0b doesn't match the code as found, STOP and report — don't paper over it.
