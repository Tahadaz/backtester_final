# 67 - SFC technical conditioning

Generated: 2026-07-06T10:40:17.168733+00:00
Selection/proof split date: `2023-07-31`

## Proof-half technical IC within SFC terciles

| tercile   | horizon   |   pairs |   mean_ic |   nw_t_stat |   pvalue |   hit_rate |   mean_signed_forward_return |   fdr_qvalue | fdr_reject_10pct   |
|:----------|:----------|--------:|----------:|------------:|---------:|-----------:|-----------------------------:|-------------:|:-------------------|
| top       | 3m        |     401 |    0.1368 |      2.4643 |   0.0137 |     0.5362 |                       0.0866 |       0.0206 | True               |
| top       | 6m        |     365 |    0.147  |      2.0709 |   0.0384 |     0.5397 |                       0.1805 |       0.0493 | True               |
| top       | 12m       |     293 |    0.0501 |      0.7198 |   0.4717 |     0.587  |                       0.4017 |       0.4717 | False              |
| middle    | 3m        |     375 |    0.1297 |      3.0229 |   0.0025 |     0.4853 |                       0.0331 |       0.0056 | True               |
| middle    | 6m        |     333 |    0.2137 |      3.1669 |   0.0015 |     0.5075 |                       0.0693 |       0.0054 | True               |
| middle    | 12m       |     249 |    0.2616 |      5.738  |   0      |     0.5261 |                       0.1538 |       0      | True               |
| bottom    | 3m        |     340 |    0.1107 |      2.4898 |   0.0128 |     0.4824 |                       0.0238 |       0.0206 | True               |
| bottom    | 6m        |     310 |    0.0842 |      1.2814 |   0.2    |     0.4742 |                       0.0455 |       0.225  | False              |
| bottom    | 12m       |     250 |    0.1419 |      3.1229 |   0.0018 |     0.492  |                       0.1455 |       0.0054 | True               |

## Practical decomposition

| subset         | horizon   |   pairs |   mean_ic |   nw_t_stat |   hit_rate |   mean_signed_forward_return |
|:---------------|:----------|--------:|----------:|------------:|-----------:|-----------------------------:|
| full_universe  | 3m        |    1116 |    0.1278 |      5.2763 |     0.5027 |                       0.0495 |
| full_universe  | 6m        |    1008 |    0.1416 |      2.9887 |     0.5089 |                       0.1022 |
| full_universe  | 12m       |     792 |    0.1602 |      4.6416 |     0.5379 |                       0.2429 |
| non_bottom_sfc | 3m        |     776 |    0.1269 |      3.2652 |     0.5116 |                       0.0608 |
| non_bottom_sfc | 6m        |     698 |    0.1637 |      2.8265 |     0.5244 |                       0.1274 |
| non_bottom_sfc | 12m       |     542 |    0.1366 |      2.4534 |     0.559  |                       0.2878 |
| top_sfc_only   | 3m        |     401 |    0.1368 |      2.4643 |     0.5362 |                       0.0866 |
| top_sfc_only   | 6m        |     365 |    0.147  |      2.0709 |     0.5397 |                       0.1805 |
| top_sfc_only   | 12m       |     293 |    0.0501 |      0.7198 |     0.587  |                       0.4017 |

## Event-window overlay check

| subset          | horizon   |   pairs |   mean_ic |   nw_t_stat |
|:----------------|:----------|--------:|----------:|------------:|
| top_all_dates   | 3m        |     401 |    0.1368 |      2.4643 |
| top_all_dates   | 6m        |     365 |    0.147  |      2.0709 |
| top_all_dates   | 12m       |     293 |    0.0501 |      0.7198 |
| top_event_dates | 3m        |     374 |    0.1218 |      2.2115 |
| top_event_dates | 6m        |     338 |    0.1337 |      1.9554 |
| top_event_dates | 12m       |     266 |    0.0585 |      0.811  |

## Verdict

Verdict: **event-window drift overlay**
No live sizing is changed by this study.

