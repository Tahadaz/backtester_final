# Repository And Data Audit

Generated: 2026-07-06T14:29:58.946189+00:00

## Code-Grounded Mapping

| file/module                                                       | relevant function                                       | reuse/add                                                        | defect/caveat                                                                                                       |
|:------------------------------------------------------------------|:--------------------------------------------------------|:-----------------------------------------------------------------|:--------------------------------------------------------------------------------------------------------------------|
| core/quant_core/fundamentals/cross_section/panel.py               | build_pit_panel                                         | Reused canonical PIT panel, added 1m horizon                     | Fallback publication lags still dominate rows                                                                       |
| core/quant_core/fundamentals/cross_section/ic_study.py            | compute_ic_table/_load_rows_from_db/_build_price_loader | Reused DB/price loaders and IC conventions                       | Existing SFC FMOM uses dt.date.today().year; not reused for Model C                                                 |
| core/quant_core/fundamentals/valuation.py                         | compute_symbol_valuations                               | Reused for Model B with PIT snapshots and fixed base assumptions | Historical WACC/assumption vintages unavailable; this is reconstructed PIT, not persisted historical desk valuation |
| services/api/app/models.py                                        | FundamentalConsensusEstimate                            | Audited for analyst data                                         | Consensus range is recent only; no true historical revision signal                                                  |
| core/quant_core/fundamentals/cross_section/methodology_bakeoff.py | run_bakeoff                                             | Added four-methodology comparison                                | Small universe; residual regressions intentionally parsimonious                                                     |

## Database Counts

|   fundamental_annual_metric |   fundamental_period_metric |   fundamental_consensus_estimate |   fundamental_ensemble_result |   fundamental_valuation_result |   market_data_store |   stock_master |   fundamental_cross_section_score | consensus_range                                              | persisted_valuation_range                                                                                                                                                  |
|----------------------------:|----------------------------:|---------------------------------:|------------------------------:|-------------------------------:|--------------------:|---------------:|----------------------------------:|:-------------------------------------------------------------|:---------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|                      164138 |                      142458 |                              357 |                          2139 |                          14973 |                  91 |             73 |                                71 | (datetime.date(2026, 5, 25), datetime.date(2026, 6, 28), 37) | (datetime.datetime(2026, 5, 26, 11, 42, 7, 991269, tzinfo=datetime.timezone.utc), datetime.datetime(2026, 7, 6, 13, 23, 39, 749920, tzinfo=datetime.timezone.utc), 73, 36) |
