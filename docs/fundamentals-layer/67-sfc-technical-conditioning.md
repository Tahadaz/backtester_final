# 67 - SFC technical conditioning

Generated: 2026-07-06T11:21:13.404090+00:00
Selection/proof split date: `2023-07-31`

## Proof-half technical IC within SFC terciles

| tercile   | horizon   |   pairs |   mean_ic |   nw_t_stat |   pvalue |   hit_rate |   mean_signed_forward_return |   fdr_qvalue | fdr_reject_10pct   |
|:----------|:----------|--------:|----------:|------------:|---------:|-----------:|-----------------------------:|-------------:|:-------------------|
| top       | 3m        |     415 |    0.1387 |      2.2269 |   0.026  |     0.5446 |                       0.0852 |       0.0467 | True               |
| top       | 6m        |     376 |    0.1562 |      1.9698 |   0.0489 |     0.5479 |                       0.1774 |       0.0728 | True               |
| top       | 12m       |     298 |    0.0615 |      0.7599 |   0.4473 |     0.5872 |                       0.3934 |       0.4473 | False              |
| middle    | 3m        |     371 |    0.1216 |      2.3824 |   0.0172 |     0.4852 |                       0.031  |       0.0467 | True               |
| middle    | 6m        |     334 |    0.1512 |      1.906  |   0.0567 |     0.5    |                       0.0649 |       0.0728 | True               |
| middle    | 12m       |     256 |    0.198  |      4.6181 |   0      |     0.543  |                       0.1499 |       0      | True               |
| bottom    | 3m        |     330 |    0.099  |      2.2801 |   0.0226 |     0.4697 |                       0.0254 |       0.0467 | True               |
| bottom    | 6m        |     298 |    0.0971 |      1.5809 |   0.1139 |     0.4698 |                       0.0492 |       0.1281 | False              |
| bottom    | 12m       |     238 |    0.167  |      4.0736 |   0      |     0.4706 |                       0.1544 |       0.0002 | True               |

## Practical decomposition

| subset         | horizon   |   pairs |   mean_ic |   nw_t_stat |   hit_rate |   mean_signed_forward_return |
|:---------------|:----------|--------:|----------:|------------:|-----------:|-----------------------------:|
| full_universe  | 3m        |    1116 |    0.1278 |      5.2763 |     0.5027 |                       0.0495 |
| full_universe  | 6m        |    1008 |    0.1416 |      2.9887 |     0.5089 |                       0.1022 |
| full_universe  | 12m       |     792 |    0.1602 |      4.6416 |     0.5379 |                       0.2429 |
| non_bottom_sfc | 3m        |     786 |    0.1268 |      3.4516 |     0.5165 |                       0.0596 |
| non_bottom_sfc | 6m        |     710 |    0.1553 |      2.7769 |     0.5254 |                       0.1245 |
| non_bottom_sfc | 12m       |     554 |    0.1254 |      2.4594 |     0.5668 |                       0.2809 |
| top_sfc_only   | 3m        |     415 |    0.1387 |      2.2269 |     0.5446 |                       0.0852 |
| top_sfc_only   | 6m        |     376 |    0.1562 |      1.9698 |     0.5479 |                       0.1774 |
| top_sfc_only   | 12m       |     298 |    0.0615 |      0.7599 |     0.5872 |                       0.3934 |

## Event-window overlay check

| subset          | horizon   |   pairs |   mean_ic |   nw_t_stat |
|:----------------|:----------|--------:|----------:|------------:|
| top_all_dates   | 3m        |     415 |    0.1387 |      2.2269 |
| top_all_dates   | 6m        |     376 |    0.1562 |      1.9698 |
| top_all_dates   | 12m       |     298 |    0.0615 |      0.7599 |
| top_event_dates | 3m        |     388 |    0.1238 |      1.9831 |
| top_event_dates | 6m        |     349 |    0.1436 |      1.9228 |
| top_event_dates | 12m       |     271 |    0.071  |      0.8363 |

## Verdict

Verdict: **technical IC broad across SFC terciles; SFC does not condition the technical signal (no veto, no overlay)**
Technical predictive power is present across top, middle, and bottom SFC terciles, so SFC does not usefully condition the technical signal.
No live sizing is changed by this study.

