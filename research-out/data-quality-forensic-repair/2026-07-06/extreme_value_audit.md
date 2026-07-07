# Extreme-Value / Systemic Audit (Phase 5-6, partial)

## Finding 1 (major, confirmed): EnterpriseValue silently computed as Net Debt only across ~150 symbol-years

Mechanical SQL check across the entire `fundamental_annual_metric` table: for every row where `metric_name='EnterpriseValue'`, compare against `Total_Debt - Cash` for the same symbol/year (any import). **150 distinct symbol-year combinations** match within 3% — i.e. the stored EV is (almost certainly) actually just net debt, with the market-cap term dropped or zero at computation time.

Affected symbols include large, liquid, heavily-researched names, not just thin small-caps: **ATW, BCP, BOA, IAM, MNG, CFG, EQD, LBV, MUT, TQM, WAA**, plus dozens of smaller names (full list of 150 rows in the query log; representative sample in `known_cases_reb_sah_sbm.md` for SBM).

**Classification: E (denominator/component error), root cause in the source workbook.** These `EnterpriseValue` values are ingested verbatim from the analyst-curated Excel (`fundamental_data_all_structured_market_formula_factors*.xlsx` via `workbook.py`) — they are not recomputed by this repo's Python code. The pattern (EV = Debt − Cash exactly, market cap term absent) is the signature of a spreadsheet formula where the `MarketCap` input cell was blank/0 for that symbol/year (most commonly the case for older or thinly-covered years), and the formula silently treated the missing input as zero rather than raising an error or leaving the cell blank.

**Impact**: any factor or valuation computation that reads `EnterpriseValue` directly from this metric (rather than recomputing `MarketCap_Calc + Net_Debt` fresh, as `pit_ic_backtest.py:198-201` does) will be corrupted for these 150 symbol-years — EV/EBITDA, EBITDA/EV yield, and any EV-based valuation multiple. This is a plausible mechanism for the SBM anomaly and likely others not yet individually verified.

**Not yet done**: 
- Confirming this doesn't also corrupt `characteristic_study.py`'s `EnterpriseValue` reads (flagged in the pipeline reconstruction as reading a stored field rather than recomputing — this needs to be checked directly against the 150-row list).
- A full recomputation of the correct EV for all 150 rows using `MarketCap_Calc (same year) + Net_Debt (same year)` where both are available, and flagging as unresolved where market cap is genuinely unavailable for that year (not a bug, just missing data).
- Extending the same style of mechanical check to Book_Equity, EBITDA vs revenue-implied bounds, and other fields (Phase 5/6, not started this session — 73 MASI symbols × up to 10 years × ~10 metrics is a large but mechanical sweep).

## Finding 2 (confirmed, scoped): REB document mis-mapping

See `known_cases_reb_sah_sbm.md`. 189 of 228 `fundamental_source_document` rows tagged `symbol='REB'` are actually filings for Maghrebail, Maghreb Oxygène, Promopharm, and Société Maghrebine de Monétique — caused by "REB" being a literal substring of "Maghreb". This directly explains the flagged B/M ≈ 41.9.

**Not yet done**: the same substring-collision check was not run for every 2-3 letter ticker in the registry (e.g., is any ticker a substring of "Managem", "Attijariwafa", "Compagnie Minière de Touissit", etc. — "MIC" is a plausible collision candidate given "Microdata"/"MICRODATA" already appears in the same-company variant list, this needs a dedicated check).

## Not yet started (full Phase 5 scope)

Percentile tables (p0.1/p1/p5/median/p95/p99/p99.9) for all raw fields and derived characteristics across the full universe — this requires pulling the full panel into pandas and is a natural next step, not completed in this session due to scope.
