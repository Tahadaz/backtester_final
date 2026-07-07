# Field-Mapping Audit (Phase 7)

Canonical alias resolution lives in one shared dict, `METRIC_ALIASES` (`core/quant_core/fundamentals/cross_section/methodology_bakeoff.py:35-45`), imported by both `characteristic_study.py` and re-used transitively by `final_model_validation.py` (which consumes `characteristic_study.py`'s output panel rather than recomputing fields itself — see below). This is better than the "three fully independent implementations" hypothesized in the original pipeline reconstruction; the actual duplication is narrower.

## Mapping table

| Canonical field | `METRIC_ALIASES` key | Aliases checked (first non-null wins) | Status |
|---|---|---|---|
| Book equity | `book_equity` | `Total_Equity, Shareholders_Equity, Clean_Capitaux_propres, Capitaux_propres, Common_Equity` | **B — acceptable proxy, but see risk below** |
| Total assets | `assets` | `Total_Assets, Total_Actif, Actif_Total, Clean_Total_Assets` | A — canonical |
| Revenue | `revenue` | `Revenue, Chiffre_daffaires, Clean_Chiffre_daffaires` | A — canonical |
| Operating income | `operating_income` | `Operating_Income, EBIT, Resultat_Exploitation, Clean_Resultat_Exploitation` | C — sector-specific caveat: EBIT and "Resultat_Exploitation" are not identical line items in French GAAP (EBIT typically excludes some non-operating items reflected in "resultat d'exploitation"); treated as interchangeable here, acceptable proxy but not exact |
| Net income | `net_income` | `NetIncome, Net_Income, Clean_Resultat_net, Resultat_net, RNPG, Resultat_net_part_du_groupe` | **D — inconsistent across issuers**: mixes *consolidated net income* (Resultat_net) with *group-share net income* (RNPG / Resultat_net_part_du_groupe), which differ for any issuer with minority interests. Whichever alias appears first in a given row's metrics dict wins — this is itself a nondeterminism risk (not row-duplication, but *within-row* field-selection ambiguity) not yet resolved. |
| CFO | `cash_flow_ops` | `Operating_Cash_Flow, Cash_Flow_Operations, CFO` | B — acceptable proxy, but see CF/P canonical definition doc for financial-sector exclusion |
| Debt | `debt` | `Total_Debt, Debt_Total, Dettes_de_financement` | A — canonical |
| Cash | `cash` | `Cash_and_Equivalents, Cash, Tresorerie_Actif` | A — canonical |
| Market cap | n/a (direct) | `MarketCap_Calc, Market_Cap`, else `close * Shares_Outstanding` | **E — was broken** for SAH (fixed via exclusion, see `known_cases_reb_sah_sbm.md`) and for REB (fixed via document remap) |
| EBITDA | n/a (direct) | `EBITDA` only, no aliases | A for coverage, but **E — was broken** for 150 symbol-years (EnterpriseValue construction, now repaired) |
| Enterprise value | n/a (direct) | `EnterpriseValue` (stored field, not recomputed at read time in `characteristic_study.py`) | **E — was broken**, now repaired for 2,168 of 2,273 flagged rows |

## Confirmed systemic bug found during this audit (not previously known): net_income alias ambiguity

The `net_income` alias list mixes **RNPG (group share)** and **Resultat_net (consolidated total, before minority allocation)** with no preference rule — for any issuer with meaningful minority interests, ROE, ROA, and earnings-yield could silently use either the consolidated or group-share figure depending on which was ingested first for that symbol/year. This directly parallels the REB and EV bugs in spirit (systemic mapping ambiguity affecting many issuers, not just one). **Not repaired this session** — flagged as unresolved (Category D), needs a canonical choice (recommend group-share/RNPG for consistency with book-equity-per-share style ratios, since book equity aliases already favor consolidated figures net of minorities in most French-GAAP reporting) and an explicit priority order in `METRIC_ALIASES`, plus a scan for how many symbol-years are actually affected (not run this session).

## `final_model_validation.py` is not an independent field-mapping implementation

It imports `characteristic_study.py`'s frozen output CSV (`panel_characteristics.csv`) and re-derives z-scores/portfolios from already-computed `book_to_market_raw`/`cashflow_price_raw` columns — it does not re-read `METRIC_ALIASES` or recompute ratios from raw metrics. This means the two B/M repairs made in `characteristic_study.py` this session (negative-book-equity exclusion, financial-sector CF/P exclusion) will only reach `final_model_validation.py` once `characteristic_study.py` is re-run and its output path is refreshed — done as part of Workstream 3 below.

## Sector-specific and unresolved items

See `sector_accounting_applicability.md` for the full sector-applicability classification of each derived characteristic.
