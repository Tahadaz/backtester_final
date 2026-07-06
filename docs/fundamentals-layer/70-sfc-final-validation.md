# 70 - SFC final validation

Generated: 2026-07-06T10:45:14.713666+00:00
Methodology version: `sfc_core_v2_2026_07_06`
Evaluation / held-out-by-original-design period start: `2023-07-31`

## Formulas

- `sfc = mean(pillar_val, pillar_qual, pillar_fmom)` over available core pillars, requiring >=2 of 3.
- `sfc_legacy = mean(pillar_val, pillar_qual, pillar_fmom, pillar_pmom)` over available legacy pillars, requiring >=2 of 4.
- ICs are per-date Spearman correlations; HAC t-stats use the existing Newey-West helper over the date-level IC series.
- D2 incremental PMOM IC uses per-date rank residualization of `pillar_pmom` on `technical_score` before the same IC calculation.
- D4 uses Fama-MacBeth: cross-sectional regressions estimated per date, then HAC t-stats over the coefficient time series. No pooled OLS is used.

## D1 Attribution

| variant_id             | split      | signal      | horizon   |   periods |   pairs |   mean_ic |   nw_t_stat |   pooled_hac_t_stat |   pvalue |   n_dates |   median_cross_section_n |   bh_qvalue |
|:-----------------------|:-----------|:------------|:----------|----------:|--------:|----------:|------------:|--------------------:|---------:|----------:|-------------------------:|------------:|
| sfc_core_v2_2026_07_06 | evaluation | pillar_val  | 3m        |        31 |    2046 |    0.0808 |      2.4228 |              5.2387 |   0.0154 |        31 |                       65 |      0.0418 |
| sfc_core_v2_2026_07_06 | evaluation | pillar_val  | 6m        |        28 |    1836 |    0.1275 |      3.5391 |              6.7624 |   0.0004 |        28 |                       65 |      0.0015 |
| sfc_core_v2_2026_07_06 | evaluation | pillar_val  | 12m       |        22 |    1427 |    0.2283 |      7.6325 |              8.1201 |   0      |        22 |                       65 |      0      |
| sfc_core_v2_2026_07_06 | evaluation | pillar_qual | 3m        |        31 |    2092 |    0.0014 |      0.049  |              0.0936 |   0.9609 |        31 |                       67 |      0.9857 |
| sfc_core_v2_2026_07_06 | evaluation | pillar_qual | 6m        |        28 |    1879 |    0.0089 |      0.2763 |              1.0042 |   0.7823 |        28 |                       67 |      0.9027 |
| sfc_core_v2_2026_07_06 | evaluation | pillar_qual | 12m       |        22 |    1464 |    0.0301 |      1.381  |              3.3478 |   0.1673 |        22 |                       67 |      0.2509 |
| sfc_core_v2_2026_07_06 | evaluation | pillar_fmom | 3m        |        31 |    2084 |    0.0112 |      0.4402 |             -0.5754 |   0.6598 |        31 |                       67 |      0.8248 |
| sfc_core_v2_2026_07_06 | evaluation | pillar_fmom | 6m        |        28 |    1871 |    0.0005 |      0.0179 |              1.3361 |   0.9857 |        28 |                       67 |      0.9857 |
| sfc_core_v2_2026_07_06 | evaluation | pillar_fmom | 12m       |        22 |    1456 |   -0.0257 |     -0.7285 |              2.8362 |   0.4663 |        22 |                       67 |      0.6358 |
| sfc_core_v2_2026_07_06 | evaluation | sfc         | 3m        |        31 |    2092 |    0.0425 |      1.6199 |              2.5155 |   0.1053 |        31 |                       67 |      0.1754 |
| sfc_core_v2_2026_07_06 | evaluation | sfc         | 6m        |        28 |    1879 |    0.0647 |      2.2557 |              4.0655 |   0.0241 |        28 |                       67 |      0.0516 |
| sfc_core_v2_2026_07_06 | evaluation | sfc         | 12m       |        22 |    1464 |    0.1254 |      6.3584 |              6.253  |   0      |        22 |                       67 |      0      |
| sfc_core_v2_2026_07_06 | evaluation | sfc_legacy  | 3m        |        31 |    2092 |    0.0654 |      1.8002 |              3.1344 |   0.0718 |        31 |                       67 |      0.1347 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_legacy  | 6m        |        28 |    1879 |    0.0919 |      2.3926 |              4.8611 |   0.0167 |        28 |                       67 |      0.0418 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_legacy  | 12m       |        22 |    1464 |    0.1719 |      5.79   |              7.2565 |   0      |        22 |                       67 |      0      |

### Leave-one-pillar-out

| variant_id             | split      | signal      | horizon   |   periods |   pairs |   mean_ic |   nw_t_stat |   pooled_hac_t_stat |   pvalue |   n_dates |   median_cross_section_n | excluded_pillar   |   base_sfc_ic |   IC with pillar excluded |   Δ associated with exclusion |
|:-----------------------|:-----------|:------------|:----------|----------:|--------:|----------:|------------:|--------------------:|---------:|----------:|-------------------------:|:------------------|--------------:|--------------------------:|------------------------------:|
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_val  | 3m        |        31 |    2084 |    0.0173 |      0.5599 |             -0.2473 |   0.5755 |        31 |                       67 | VAL               |        0.0425 |                    0.0173 |                       -0.0252 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_val  | 6m        |        28 |    1871 |    0.0198 |      0.531  |              1.4763 |   0.5954 |        28 |                       67 | VAL               |        0.0647 |                    0.0198 |                       -0.0449 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_val  | 12m       |        22 |    1456 |    0.0266 |      0.8127 |              3.6702 |   0.4164 |        22 |                       67 | VAL               |        0.1254 |                    0.0266 |                       -0.0988 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_qual | 3m        |        31 |    2038 |    0.0569 |      2.7398 |              4.2675 |   0.0061 |        31 |                       65 | QUAL              |        0.0425 |                    0.0569 |                        0.0144 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_qual | 6m        |        28 |    1828 |    0.0859 |      4.0425 |              5.6362 |   0.0001 |        28 |                       65 | QUAL              |        0.0647 |                    0.0859 |                        0.0212 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_qual | 12m       |        22 |    1419 |    0.1495 |     11.1012 |              7.581  |   0      |        22 |                       65 | QUAL              |        0.1254 |                    0.1495 |                        0.024  |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_fmom | 3m        |        31 |    2046 |    0.0381 |      1.1616 |              3.9481 |   0.2454 |        31 |                       65 | FMOM              |        0.0425 |                    0.0381 |                       -0.0044 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_fmom | 6m        |        28 |    1836 |    0.0788 |      2.3011 |              5.494  |   0.0214 |        28 |                       65 | FMOM              |        0.0647 |                    0.0788 |                        0.0141 |
| sfc_core_v2_2026_07_06 | evaluation | sfc_ex_fmom | 12m       |        22 |    1427 |    0.1742 |     10.0776 |              7.619  |   0      |        22 |                       65 | FMOM              |        0.1254 |                    0.1742 |                        0.0487 |

### Per-date-averaged pillar rank-correlation matrix

| pillar_left   | pillar_right   |   mean_rank_corr |   n_dates |   median_cross_section_n |
|:--------------|:---------------|-----------------:|----------:|-------------------------:|
| pillar_val    | pillar_val     |           1      |        35 |                       66 |
| pillar_val    | pillar_qual    |           0.1068 |        35 |                       66 |
| pillar_val    | pillar_fmom    |           0.0804 |        35 |                       66 |
| pillar_val    | pillar_pmom    |           0.1346 |        35 |                       65 |
| pillar_qual   | pillar_val     |           0.1068 |        35 |                       66 |
| pillar_qual   | pillar_qual    |           1      |        35 |                       68 |
| pillar_qual   | pillar_fmom    |           0.235  |        35 |                       68 |
| pillar_qual   | pillar_pmom    |           0.1075 |        35 |                       67 |
| pillar_fmom   | pillar_val     |           0.0804 |        35 |                       66 |
| pillar_fmom   | pillar_qual    |           0.235  |        35 |                       68 |
| pillar_fmom   | pillar_fmom    |           1      |        35 |                       68 |
| pillar_fmom   | pillar_pmom    |           0.0725 |        35 |                       67 |
| pillar_pmom   | pillar_val     |           0.1346 |        35 |                       65 |
| pillar_pmom   | pillar_qual    |           0.1075 |        35 |                       67 |
| pillar_pmom   | pillar_fmom    |           0.0725 |        35 |                       67 |
| pillar_pmom   | pillar_pmom    |           1      |        35 |                       67 |

### Per-pillar coverage counts

| pillar      |   covered_rows |   covered_dates |   n_dates |   median_cross_section_n |
|:------------|---------------:|----------------:|----------:|-------------------------:|
| pillar_val  |           2331 |              35 |        35 |                       66 |
| pillar_qual |           2381 |              35 |        35 |                       68 |
| pillar_fmom |           2373 |              35 |        35 |                       68 |
| pillar_pmom |           2179 |              35 |        35 |                       67 |

## D2 PMOM overlap

| metric                             |   mean_corr |   iqr_corr |   n_dates |   median_cross_section_n |
|:-----------------------------------|------------:|-----------:|----------:|-------------------------:|
| corr(pillar_pmom, technical_score) |      0.2668 |     0.2523 |        35 |                       36 |

### PMOM incremental IC after per-date rank residualization on technical_score

| variant_id             | split      | signal                     | horizon   |   periods |   pairs |   mean_ic |   nw_t_stat |   pooled_hac_t_stat |   pvalue |   n_dates |   median_cross_section_n |
|:-----------------------|:-----------|:---------------------------|:----------|----------:|--------:|----------:|------------:|--------------------:|---------:|----------:|-------------------------:|
| sfc_core_v2_2026_07_06 | evaluation | pmom_residual_vs_technical | 3m        |        31 |    1034 |    0.1089 |      1.5169 |              3.5755 |   0.1293 |        31 |                       36 |
| sfc_core_v2_2026_07_06 | evaluation | pmom_residual_vs_technical | 6m        |        28 |     926 |    0.1783 |      2.4271 |              5.7073 |   0.0152 |        28 |                       36 |
| sfc_core_v2_2026_07_06 | evaluation | pmom_residual_vs_technical | 12m       |        22 |     710 |    0.2385 |      3.9184 |              5.1951 |   0.0001 |        22 |                       36 |

## D3 Robustness

| signal     | horizon   | scenario                     |   mean_ic |   nw_t_stat |   pvalue |   n_dates |   median_cross_section_n |
|:-----------|:----------|:-----------------------------|----------:|------------:|---------:|----------:|-------------------------:|
| pillar_val | 6m        | baseline                     |    0.1275 |      3.5391 |   0.0004 |        28 |                       65 |
| pillar_val | 6m        | date_jackknife_min           |    0.1176 |      3.7614 |   0.0002 |        27 |                       65 |
| pillar_val | 6m        | date_jackknife_max           |    0.1344 |      4.0974 |   0      |        27 |                       65 |
| pillar_val | 6m        | block3_jackknife_min         |    0.1033 |      3.432  |   0.0006 |        25 |                       65 |
| pillar_val | 6m        | block3_jackknife_max         |    0.1484 |      4.8198 |   0      |        25 |                       65 |
| pillar_val | 6m        | drop_top_1_influential_names |    0.153  |      4.5809 |   0      |        28 |                       64 |
| pillar_val | 6m        | drop_top_3_influential_names |    0.1511 |      4.6082 |   0      |        28 |                       62 |
| pillar_val | 6m        | drop_top_5_influential_names |    0.1262 |      3.8188 |   0.0001 |        28 |                       60 |
| pillar_val | 6m        | financials_removed           |    0.1638 |      4.6041 |   0      |        28 |                       52 |
| pillar_val | 6m        | size_bucket_small            |    0.1926 |      5.236  |   0      |        28 |                       32 |
| pillar_val | 6m        | size_bucket_large            |    0.0747 |      1.0648 |   0.2869 |        28 |                       32 |
| pillar_val | 12m       | baseline                     |    0.2283 |      7.6325 |   0      |        22 |                       65 |
| pillar_val | 12m       | date_jackknife_min           |    0.2222 |      7.4691 |   0      |        21 |                       65 |
| pillar_val | 12m       | date_jackknife_max           |    0.2366 |      8.4426 |   0      |        21 |                       65 |
| pillar_val | 12m       | block3_jackknife_min         |    0.213  |      6.7442 |   0      |        19 |                       65 |
| pillar_val | 12m       | block3_jackknife_max         |    0.2523 |     10.1288 |   0      |        19 |                       65 |
| pillar_val | 12m       | drop_top_1_influential_names |    0.2634 |      9.3011 |   0      |        22 |                       64 |
| pillar_val | 12m       | drop_top_3_influential_names |    0.2697 |      9.616  |   0      |        22 |                       62 |
| pillar_val | 12m       | drop_top_5_influential_names |    0.2245 |      6.1216 |   0      |        22 |                       60 |
| pillar_val | 12m       | financials_removed           |    0.3031 |     25.3685 |   0      |        22 |                       52 |
| pillar_val | 12m       | size_bucket_small            |    0.3567 |     21.996  |   0      |        22 |                       32 |
| pillar_val | 12m       | size_bucket_large            |    0.062  |      0.9525 |   0.3408 |        22 |                       32 |
| sfc        | 6m        | baseline                     |    0.0647 |      2.2557 |   0.0241 |        28 |                       67 |
| sfc        | 6m        | date_jackknife_min           |    0.0573 |      2.0125 |   0.0442 |        27 |                       67 |
| sfc        | 6m        | date_jackknife_max           |    0.0752 |      2.9313 |   0.0034 |        27 |                       67 |
| sfc        | 6m        | block3_jackknife_min         |    0.0475 |      1.6577 |   0.0974 |        25 |                       67 |
| sfc        | 6m        | block3_jackknife_max         |    0.0888 |      3.4908 |   0.0005 |        25 |                       67 |
| sfc        | 6m        | drop_top_1_influential_names |    0.0881 |      2.9448 |   0.0032 |        28 |                       66 |
| sfc        | 6m        | drop_top_3_influential_names |    0.0487 |      1.4433 |   0.1489 |        28 |                       64 |
| sfc        | 6m        | drop_top_5_influential_names |    0.0466 |      1.2347 |   0.2169 |        28 |                       62 |
| sfc        | 6m        | financials_removed           |    0.0803 |      2.069  |   0.0385 |        28 |                       53 |
| sfc        | 6m        | size_bucket_small            |    0.1063 |      2.2963 |   0.0217 |        28 |                       32 |
| sfc        | 6m        | size_bucket_large            |    0.0412 |      1.3759 |   0.1688 |        28 |                       32 |
| sfc        | 12m       | baseline                     |    0.1254 |      6.3584 |   0      |        22 |                       67 |
| sfc        | 12m       | date_jackknife_min           |    0.1201 |      6.3353 |   0      |        21 |                       67 |
| sfc        | 12m       | date_jackknife_max           |    0.1342 |      8.1698 |   0      |        21 |                       67 |
| sfc        | 12m       | block3_jackknife_min         |    0.1142 |      5.7447 |   0      |        19 |                       67 |
| sfc        | 12m       | block3_jackknife_max         |    0.1429 |      8.9264 |   0      |        19 |                       67 |
| sfc        | 12m       | drop_top_1_influential_names |    0.1588 |      7.2513 |   0      |        22 |                       66 |
| sfc        | 12m       | drop_top_3_influential_names |    0.1664 |      8.396  |   0      |        22 |                       64 |
| sfc        | 12m       | drop_top_5_influential_names |    0.1228 |      6.4586 |   0      |        22 |                       62 |
| sfc        | 12m       | financials_removed           |    0.1585 |      6.1138 |   0      |        22 |                       53 |
| sfc        | 12m       | size_bucket_small            |    0.2325 |      7.5274 |   0      |        22 |                       32 |
| sfc        | 12m       | size_bucket_large            |    0.0533 |      2.6034 |   0.0092 |        22 |                       32 |

## D4 Secondary integration

| factor     | horizon   | model               | term      |   mean_coef |   hac_t_stat |   pvalue |   n_dates |   median_cross_section_n | label                 |
|:-----------|:----------|:--------------------|:----------|------------:|-------------:|---------:|----------:|-------------------------:|:----------------------|
| pillar_val | 3m        | r ~ 1 + T + F       | Intercept |      0.0778 |       2.7177 |   0.0066 |        31 |                       36 |                       |
| pillar_val | 3m        | r ~ 1 + T + F       | T         |      0.1056 |       5.2308 |   0      |        31 |                       36 |                       |
| pillar_val | 3m        | r ~ 1 + T + F       | F         |      0.129  |       3.164  |   0.0016 |        31 |                       36 |                       |
| pillar_val | 3m        | r ~ 1 + T + F + T*F | Intercept |      0.0767 |       2.7194 |   0.0065 |        31 |                       36 |                       |
| pillar_val | 3m        | r ~ 1 + T + F + T*F | T         |      0.0986 |       4.5682 |   0      |        31 |                       36 |                       |
| pillar_val | 3m        | r ~ 1 + T + F + T*F | F         |      0.1125 |       2.631  |   0.0085 |        31 |                       36 |                       |
| pillar_val | 3m        | r ~ 1 + T + F + T*F | T*F       |      0.2351 |       1.9826 |   0.0474 |        31 |                       36 | EXPLORATORY_LOW_POWER |
| pillar_val | 6m        | r ~ 1 + T + F       | Intercept |      0.2052 |       3.6446 |   0.0003 |        28 |                       36 |                       |
| pillar_val | 6m        | r ~ 1 + T + F       | T         |      0.2041 |       4.1299 |   0      |        28 |                       36 |                       |
| pillar_val | 6m        | r ~ 1 + T + F       | F         |      0.3168 |       4.2502 |   0      |        28 |                       36 |                       |
| pillar_val | 6m        | r ~ 1 + T + F + T*F | Intercept |      0.2001 |       3.5741 |   0.0004 |        28 |                       36 |                       |
| pillar_val | 6m        | r ~ 1 + T + F + T*F | T         |      0.1979 |       3.911  |   0.0001 |        28 |                       36 |                       |
| pillar_val | 6m        | r ~ 1 + T + F + T*F | F         |      0.2959 |       4.0586 |   0      |        28 |                       36 |                       |
| pillar_val | 6m        | r ~ 1 + T + F + T*F | T*F       |      0.3562 |       1.89   |   0.0588 |        28 |                       36 | EXPLORATORY_LOW_POWER |
| pillar_val | 12m       | r ~ 1 + T + F       | Intercept |      0.5628 |       6.9188 |   0      |        22 |                       35 |                       |
| pillar_val | 12m       | r ~ 1 + T + F       | T         |      0.3018 |       2.0922 |   0.0364 |        22 |                       35 |                       |
| pillar_val | 12m       | r ~ 1 + T + F       | F         |      0.9949 |       7.1862 |   0      |        22 |                       35 |                       |
| pillar_val | 12m       | r ~ 1 + T + F + T*F | Intercept |      0.5641 |       6.4281 |   0      |        22 |                       35 |                       |
| pillar_val | 12m       | r ~ 1 + T + F + T*F | T         |      0.3185 |       2.3412 |   0.0192 |        22 |                       35 |                       |
| pillar_val | 12m       | r ~ 1 + T + F + T*F | F         |      0.9088 |       6.8155 |   0      |        22 |                       35 |                       |
| pillar_val | 12m       | r ~ 1 + T + F + T*F | T*F       |     -0.2107 |      -0.2914 |   0.7707 |        22 |                       35 | EXPLORATORY_LOW_POWER |
| sfc        | 3m        | r ~ 1 + T + F       | Intercept |      0.0764 |       2.7068 |   0.0068 |        31 |                       36 |                       |
| sfc        | 3m        | r ~ 1 + T + F       | T         |      0.1056 |       4.7776 |   0      |        31 |                       36 |                       |
| sfc        | 3m        | r ~ 1 + T + F       | F         |      0.0562 |       1.1325 |   0.2574 |        31 |                       36 |                       |
| sfc        | 3m        | r ~ 1 + T + F + T*F | Intercept |      0.0759 |       2.6912 |   0.0071 |        31 |                       36 |                       |
| sfc        | 3m        | r ~ 1 + T + F + T*F | T         |      0.0993 |       4.5819 |   0      |        31 |                       36 |                       |
| sfc        | 3m        | r ~ 1 + T + F + T*F | F         |      0.0552 |       1.1387 |   0.2548 |        31 |                       36 |                       |
| sfc        | 3m        | r ~ 1 + T + F + T*F | T*F       |      0.142  |       1.3647 |   0.1723 |        31 |                       36 | EXPLORATORY_LOW_POWER |
| sfc        | 6m        | r ~ 1 + T + F       | Intercept |      0.2018 |       3.6531 |   0.0003 |        28 |                       36 |                       |
| sfc        | 6m        | r ~ 1 + T + F       | T         |      0.2242 |       4.1905 |   0      |        28 |                       36 |                       |
| sfc        | 6m        | r ~ 1 + T + F       | F         |      0.1692 |       1.8179 |   0.0691 |        28 |                       36 |                       |
| sfc        | 6m        | r ~ 1 + T + F + T*F | Intercept |      0.2018 |       3.6113 |   0.0003 |        28 |                       36 |                       |
| sfc        | 6m        | r ~ 1 + T + F + T*F | T         |      0.2272 |       3.9374 |   0.0001 |        28 |                       36 |                       |
| sfc        | 6m        | r ~ 1 + T + F + T*F | F         |      0.1589 |       1.769  |   0.0769 |        28 |                       36 |                       |
| sfc        | 6m        | r ~ 1 + T + F + T*F | T*F       |      0.1989 |       0.8835 |   0.3769 |        28 |                       36 | EXPLORATORY_LOW_POWER |
| sfc        | 12m       | r ~ 1 + T + F       | Intercept |      0.5588 |       7.0427 |   0      |        22 |                       36 |                       |
| sfc        | 12m       | r ~ 1 + T + F       | T         |      0.3671 |       2.8177 |   0.0048 |        22 |                       36 |                       |
| sfc        | 12m       | r ~ 1 + T + F       | F         |      0.6867 |       3.2796 |   0.001  |        22 |                       36 |                       |
| sfc        | 12m       | r ~ 1 + T + F + T*F | Intercept |      0.5749 |       6.9141 |   0      |        22 |                       36 |                       |
| sfc        | 12m       | r ~ 1 + T + F + T*F | T         |      0.4111 |       3.772  |   0.0002 |        22 |                       36 |                       |
| sfc        | 12m       | r ~ 1 + T + F + T*F | F         |      0.6663 |       3.4116 |   0.0006 |        22 |                       36 |                       |
| sfc        | 12m       | r ~ 1 + T + F + T*F | T*F       |     -0.1489 |      -0.1944 |   0.8459 |        22 |                       36 | EXPLORATORY_LOW_POWER |
| sfc_legacy | 3m        | r ~ 1 + T + F       | Intercept |      0.0764 |       2.7068 |   0.0068 |        31 |                       36 |                       |
| sfc_legacy | 3m        | r ~ 1 + T + F       | T         |      0.0908 |       4.4157 |   0      |        31 |                       36 |                       |
| sfc_legacy | 3m        | r ~ 1 + T + F       | F         |      0.0919 |       1.6145 |   0.1064 |        31 |                       36 |                       |
| sfc_legacy | 3m        | r ~ 1 + T + F + T*F | Intercept |      0.0737 |       2.683  |   0.0073 |        31 |                       36 |                       |
| sfc_legacy | 3m        | r ~ 1 + T + F + T*F | T         |      0.0818 |       4.1423 |   0      |        31 |                       36 |                       |
| sfc_legacy | 3m        | r ~ 1 + T + F + T*F | F         |      0.0843 |       1.4912 |   0.1359 |        31 |                       36 |                       |
| sfc_legacy | 3m        | r ~ 1 + T + F + T*F | T*F       |      0.1549 |       1.251  |   0.2109 |        31 |                       36 | EXPLORATORY_LOW_POWER |
| sfc_legacy | 6m        | r ~ 1 + T + F       | Intercept |      0.2018 |       3.6531 |   0.0003 |        28 |                       36 |                       |
| sfc_legacy | 6m        | r ~ 1 + T + F       | T         |      0.1853 |       3.8192 |   0.0001 |        28 |                       36 |                       |
| sfc_legacy | 6m        | r ~ 1 + T + F       | F         |      0.2671 |       2.447  |   0.0144 |        28 |                       36 |                       |
| sfc_legacy | 6m        | r ~ 1 + T + F + T*F | Intercept |      0.2002 |       3.5104 |   0.0004 |        28 |                       36 |                       |
| sfc_legacy | 6m        | r ~ 1 + T + F + T*F | T         |      0.1887 |       3.4582 |   0.0005 |        28 |                       36 |                       |
| sfc_legacy | 6m        | r ~ 1 + T + F + T*F | F         |      0.2575 |       2.5349 |   0.0112 |        28 |                       36 |                       |
| sfc_legacy | 6m        | r ~ 1 + T + F + T*F | T*F       |      0.2092 |       0.7438 |   0.457  |        28 |                       36 | EXPLORATORY_LOW_POWER |
| sfc_legacy | 12m       | r ~ 1 + T + F       | Intercept |      0.5588 |       7.0427 |   0      |        22 |                       36 |                       |
| sfc_legacy | 12m       | r ~ 1 + T + F       | T         |      0.2891 |       2.322  |   0.0202 |        22 |                       36 |                       |
| sfc_legacy | 12m       | r ~ 1 + T + F       | F         |      0.8449 |       3.4567 |   0.0005 |        22 |                       36 |                       |
| sfc_legacy | 12m       | r ~ 1 + T + F + T*F | Intercept |      0.5672 |       6.8059 |   0      |        22 |                       36 |                       |
| sfc_legacy | 12m       | r ~ 1 + T + F + T*F | T         |      0.3285 |       3.4623 |   0.0005 |        22 |                       36 |                       |
| sfc_legacy | 12m       | r ~ 1 + T + F + T*F | F         |      0.8139 |       3.6449 |   0.0003 |        22 |                       36 |                       |
| sfc_legacy | 12m       | r ~ 1 + T + F + T*F | T*F       |      0.0977 |       0.1111 |   0.9115 |        22 |                       36 | EXPLORATORY_LOW_POWER |

## Harvestability (construction ladder — not a causal decomposition)

| construction              |   active_return |   tracking_error |   information_ratio |   n_dates |   median_cross_section_n |
|:--------------------------|----------------:|-----------------:|--------------------:|----------:|-------------------------:|
| equal_top_tercile         |          0.0086 |           0.0408 |              0.8427 |        32 |                       68 |
| benchmark_active_uncapped |         -0.0051 |           0.0546 |             -0.3728 |        32 |                       68 |
| benchmark_active_pm3pct   |         -0.0034 |           0.0551 |             -0.2462 |        32 |                       68 |

## Sample sizes and limitations

- The effective evidence window remains one regime: the evaluation / held-out-by-original-design period begins on 2023-07-31.
- The panel still relies heavily on fallback PIT availability lags; interpret the diagnostics with the same fallback-coverage caveat used in brief 61.
- Leave-one-out confirms value-domination: core `sfc` 6m IC falls from 0.0647 to 0.0198 and becomes insignificant when `pillar_val` is excluded.
- Financials remain a thin bucket, so financials-removed and size-split robustness rows are descriptive rather than decisive.
- IC is not alpha; the construction ladder is included to show harvestability under long-only constraints, not to claim causal decomposition.

