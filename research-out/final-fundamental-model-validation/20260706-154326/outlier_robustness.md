# Outlier Robustness

Generated: 2026-07-06T15:49:27.956021+00:00

## Transform Specifications

| sample          | signal                         | definition                     | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue |   cost_bps |   top_bottom_spread |   gross_top_bottom_spread |   net_sharpe |   max_drawdown |   turnover | monotonic   | base_signal    | method          |
|:----------------|:-------------------------------|:-------------------------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|-----------:|--------------------:|--------------------------:|-------------:|---------------:|-----------:|:------------|:---------------|:----------------|
| raw             | book_to_market_raw             | book_to_market raw             | 6m        |        44 |    2254 |    0.1638 |      0.1743 |   0.2419 |     0.7679 |       2.8134 |   0.0049 |         33 |              0.1034 |                    0.1039 |       0.7591 |        -0.8644 |     0.0685 | True        | book_to_market | raw             |
| rank            | book_to_market_rank            | book_to_market rank            | 6m        |        44 |    2254 |    0.1653 |      0.1678 |   0.2429 |     0.7679 |       2.786  |   0.0053 |         33 |              0.1034 |                    0.1039 |       0.7591 |        -0.8644 |     0.0685 | True        | book_to_market | rank            |
| winsor_1_99     | book_to_market_winsor_1_99     | book_to_market winsor_1_99     | 6m        |        44 |    2254 |    0.1638 |      0.1743 |   0.2419 |     0.7679 |       2.8134 |   0.0049 |         33 |              0.1034 |                    0.1039 |       0.7591 |        -0.8644 |     0.0685 | True        | book_to_market | winsor_1_99     |
| winsor_2_5_97_5 | book_to_market_winsor_2_5_97_5 | book_to_market winsor_2_5_97_5 | 6m        |        44 |    2254 |    0.1638 |      0.1743 |   0.2419 |     0.7679 |       2.8134 |   0.0049 |         33 |              0.1034 |                    0.1039 |       0.7591 |        -0.8644 |     0.0685 | True        | book_to_market | winsor_2_5_97_5 |
| mad             | book_to_market_mad             | book_to_market mad             | 6m        |        44 |    2254 |    0.1638 |      0.1743 |   0.2419 |     0.7679 |       2.8134 |   0.0049 |         33 |              0.1034 |                    0.1039 |       0.7591 |        -0.8644 |     0.0685 | True        | book_to_market | mad             |
| raw             | cashflow_price_raw             | cashflow_price raw             | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |         33 |              0.1035 |                    0.1042 |       1.0634 |        -0.6233 |     0.0988 | False       | cashflow_price | raw             |
| rank            | cashflow_price_rank            | cashflow_price rank            | 6m        |        44 |    2139 |    0.1463 |      0.1304 |   0.1381 |     0.8864 |       5.7608 |   0      |         33 |              0.1035 |                    0.1042 |       1.0634 |        -0.6233 |     0.0988 | False       | cashflow_price | rank            |
| winsor_1_99     | cashflow_price_winsor_1_99     | cashflow_price winsor_1_99     | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |         33 |              0.1035 |                    0.1042 |       1.0634 |        -0.6233 |     0.0988 | False       | cashflow_price | winsor_1_99     |
| winsor_2_5_97_5 | cashflow_price_winsor_2_5_97_5 | cashflow_price winsor_2_5_97_5 | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |         33 |              0.1035 |                    0.1042 |       1.0634 |        -0.6233 |     0.0988 | False       | cashflow_price | winsor_2_5_97_5 |
| mad             | cashflow_price_mad             | cashflow_price mad             | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |         33 |              0.1035 |                    0.1042 |       1.0634 |        -0.6233 |     0.0988 | False       | cashflow_price | mad             |

## Leave-One-Stock

| signal         | excluded   | by     |   mean_ic |   delta_vs_base |   hac_t_stat |
|:---------------|:-----------|:-------|----------:|----------------:|-------------:|
| book_to_market | IAM        | symbol |    0.1031 |         -0.0607 |       1.6753 |
| book_to_market | CDM        | symbol |    0.1296 |         -0.0342 |       1.7629 |
| book_to_market | ADI        | symbol |    0.1417 |         -0.0222 |       2.8326 |
| book_to_market | ATW        | symbol |    0.1453 |         -0.0185 |       2.3248 |
| book_to_market | RDS        | symbol |    0.1521 |         -0.0117 |       2.564  |
| book_to_market | HPS        | symbol |    0.1566 |         -0.0072 |       2.6627 |
| book_to_market | OUL        | symbol |    0.1588 |         -0.005  |       2.6818 |
| book_to_market | AFM        | symbol |    0.1593 |         -0.0045 |       2.7264 |
| book_to_market | SAH        | symbol |    0.1597 |         -0.0041 |       2.8289 |
| book_to_market | CSR        | symbol |    0.1598 |         -0.004  |       2.7393 |
| book_to_market | GAZ        | symbol |    0.1598 |         -0.004  |       2.7287 |
| book_to_market | SBM        | symbol |    0.1603 |         -0.0036 |       2.717  |
| book_to_market | LBV        | symbol |    0.1604 |         -0.0035 |       2.7462 |
| book_to_market | SID        | symbol |    0.1605 |         -0.0033 |       2.7544 |
| book_to_market | DHO        | symbol |    0.1607 |         -0.0031 |       2.783  |
| book_to_market | ZDJ        | symbol |    0.1607 |         -0.0031 |       2.5881 |
| book_to_market | MDP        | symbol |    0.1615 |         -0.0023 |       2.8311 |
| book_to_market | AGM        | symbol |    0.1617 |         -0.0022 |       2.6829 |
| book_to_market | RIS        | symbol |    0.1625 |         -0.0013 |       2.8094 |
| book_to_market | ATL        | symbol |    0.1626 |         -0.0012 |       2.7679 |
| book_to_market | DYT        | symbol |    0.1627 |         -0.0011 |       2.7616 |
| book_to_market | FBR        | symbol |    0.1631 |         -0.0007 |       2.6999 |
| book_to_market | LES        | symbol |    0.1634 |         -0.0004 |       2.76   |
| book_to_market | VCN        | symbol |    0.1634 |         -0.0004 |       2.805  |
| book_to_market | BAL        | symbol |    0.1635 |         -0.0003 |       2.7859 |
| book_to_market | CTM        | symbol |    0.1637 |         -0.0001 |       2.7972 |
| book_to_market | M2M        | symbol |    0.1637 |         -0.0001 |       2.8234 |
| book_to_market | CMT        | symbol |    0.1638 |         -0.0001 |       2.8409 |
| book_to_market | CMG        | symbol |    0.1638 |         -0      |       2.8099 |
| book_to_market | CAP        | symbol |    0.1638 |          0      |       2.8134 |
| book_to_market | GTM        | symbol |    0.1638 |          0      |       2.8134 |
| book_to_market | SNP        | symbol |    0.1638 |          0      |       2.8134 |
| book_to_market | AFI        | symbol |    0.1639 |          0      |       2.8023 |
| book_to_market | WAA        | symbol |    0.164  |          0.0002 |       2.8054 |
| book_to_market | ALM        | symbol |    0.1643 |          0.0004 |       2.8056 |
| book_to_market | S2M        | symbol |    0.1645 |          0.0007 |       2.8204 |
| book_to_market | BCI        | symbol |    0.1647 |          0.0009 |       2.9093 |
| book_to_market | MOX        | symbol |    0.1647 |          0.0009 |       2.7586 |
| book_to_market | EQD        | symbol |    0.1648 |          0.0009 |       2.8538 |
| book_to_market | TMA        | symbol |    0.165  |          0.0012 |       2.8054 |
| book_to_market | SLF        | symbol |    0.165  |          0.0012 |       2.8289 |
| book_to_market | COL        | symbol |    0.1651 |          0.0013 |       2.8284 |
| book_to_market | ATH        | symbol |    0.1651 |          0.0013 |       2.8249 |
| book_to_market | SMI        | symbol |    0.1652 |          0.0014 |       2.8324 |
| book_to_market | CIH        | symbol |    0.1653 |          0.0015 |       2.8449 |
| book_to_market | DWY        | symbol |    0.1653 |          0.0015 |       2.8324 |
| book_to_market | MIC        | symbol |    0.1653 |          0.0015 |       2.806  |
| book_to_market | TQM        | symbol |    0.1654 |          0.0016 |       2.8377 |
| book_to_market | CFG        | symbol |    0.1654 |          0.0016 |       2.8269 |
| book_to_market | MUT        | symbol |    0.1654 |          0.0016 |       2.8651 |
| book_to_market | BOA        | symbol |    0.1656 |          0.0018 |       2.8492 |
| book_to_market | NKL        | symbol |    0.166  |          0.0022 |       2.8818 |
| book_to_market | CRS        | symbol |    0.1663 |          0.0024 |       2.8753 |
| book_to_market | REB        | symbol |    0.1663 |          0.0025 |       2.7687 |
| book_to_market | MNG        | symbol |    0.1663 |          0.0025 |       2.8597 |
| book_to_market | ADH        | symbol |    0.1668 |          0.0029 |       2.7591 |
| book_to_market | MAB        | symbol |    0.1668 |          0.003  |       2.8919 |
| book_to_market | INV        | symbol |    0.1675 |          0.0036 |       2.7597 |
| book_to_market | ARD        | symbol |    0.1679 |          0.0041 |       2.9419 |
| book_to_market | SRM        | symbol |    0.168  |          0.0042 |       2.7769 |
| book_to_market | IMO        | symbol |    0.1681 |          0.0043 |       2.9097 |
| book_to_market | LHM        | symbol |    0.1684 |          0.0046 |       2.7592 |
| book_to_market | MLE        | symbol |    0.1685 |          0.0047 |       2.954  |
| book_to_market | IBC        | symbol |    0.1687 |          0.0049 |       2.9451 |
| book_to_market | STR        | symbol |    0.17   |          0.0062 |       3.0366 |
| book_to_market | TGC        | symbol |    0.1709 |          0.0071 |       2.9684 |
| book_to_market | AKT        | symbol |    0.171  |          0.0072 |       2.7326 |
| book_to_market | BCP        | symbol |    0.1713 |          0.0075 |       2.7105 |
| book_to_market | SNA        | symbol |    0.1725 |          0.0087 |       3.4049 |
| book_to_market | MSA        | symbol |    0.1855 |          0.0217 |       2.8826 |
| book_to_market | JET        | symbol |    0.2405 |          0.0767 |       3.2709 |
| cashflow_price | ADI        | symbol |    0.1052 |         -0.0414 |       5.5728 |
| cashflow_price | IAM        | symbol |    0.1117 |         -0.0349 |       3.8402 |
| cashflow_price | RDS        | symbol |    0.1329 |         -0.0137 |       5.2585 |
| cashflow_price | AKT        | symbol |    0.1385 |         -0.0081 |       5.6487 |
| cashflow_price | SMI        | symbol |    0.1395 |         -0.0071 |       5.1828 |
| cashflow_price | STR        | symbol |    0.1402 |         -0.0065 |       5.5013 |
| cashflow_price | BCI        | symbol |    0.1404 |         -0.0062 |       5.6153 |
| cashflow_price | TQM        | symbol |    0.1412 |         -0.0054 |       5.3717 |
| cashflow_price | SAH        | symbol |    0.1415 |         -0.0051 |       5.5279 |

## Leave-One-Date

| signal         | excluded   | by         |   mean_ic |   delta_vs_base |   hac_t_stat |
|:---------------|:-----------|:-----------|----------:|----------------:|-------------:|
| book_to_market | 2022-03-31 | as_of_date |    0.151  |         -0.0128 |       2.4632 |
| book_to_market | 2022-12-31 | as_of_date |    0.1557 |         -0.0082 |       2.7827 |
| book_to_market | 2022-11-30 | as_of_date |    0.1572 |         -0.0066 |       2.7708 |
| book_to_market | 2021-04-30 | as_of_date |    0.1577 |         -0.0061 |       2.675  |
| book_to_market | 2022-10-31 | as_of_date |    0.1583 |         -0.0056 |       2.764  |
| book_to_market | 2023-03-31 | as_of_date |    0.1583 |         -0.0055 |       2.7564 |
| book_to_market | 2022-09-30 | as_of_date |    0.1584 |         -0.0054 |       2.7632 |
| book_to_market | 2023-07-31 | as_of_date |    0.1594 |         -0.0045 |       2.7347 |
| book_to_market | 2022-08-31 | as_of_date |    0.1595 |         -0.0043 |       2.7614 |
| book_to_market | 2023-02-28 | as_of_date |    0.1599 |         -0.004  |       2.7449 |
| book_to_market | 2023-01-31 | as_of_date |    0.1601 |         -0.0037 |       2.7425 |
| book_to_market | 2021-03-31 | as_of_date |    0.161  |         -0.0029 |       2.7268 |
| book_to_market | 2023-08-31 | as_of_date |    0.161  |         -0.0028 |       2.7389 |
| book_to_market | 2023-09-30 | as_of_date |    0.1611 |         -0.0027 |       2.7392 |
| book_to_market | 2023-06-30 | as_of_date |    0.1613 |         -0.0025 |       2.7365 |
| book_to_market | 2023-05-31 | as_of_date |    0.1616 |         -0.0023 |       2.7362 |
| book_to_market | 2024-02-29 | as_of_date |    0.1617 |         -0.0021 |       2.739  |
| book_to_market | 2024-01-31 | as_of_date |    0.1618 |         -0.002  |       2.7396 |
| book_to_market | 2023-12-31 | as_of_date |    0.1619 |         -0.002  |       2.7403 |
| book_to_market | 2022-07-31 | as_of_date |    0.1619 |         -0.0019 |       2.7673 |
| book_to_market | 2021-05-31 | as_of_date |    0.1622 |         -0.0016 |       2.7567 |
| book_to_market | 2023-04-30 | as_of_date |    0.1626 |         -0.0012 |       2.7322 |
| book_to_market | 2023-11-30 | as_of_date |    0.1627 |         -0.0011 |       2.7465 |
| book_to_market | 2022-04-30 | as_of_date |    0.1629 |         -0.0009 |       2.7337 |
| book_to_market | 2022-05-31 | as_of_date |    0.1629 |         -0.0009 |       2.7337 |
| book_to_market | 2023-10-31 | as_of_date |    0.163  |         -0.0008 |       2.7479 |
| book_to_market | 2024-04-30 | as_of_date |    0.1636 |         -0.0002 |       2.7612 |
| book_to_market | 2024-07-31 | as_of_date |    0.1636 |         -0.0002 |       2.7596 |
| book_to_market | 2024-05-31 | as_of_date |    0.1636 |         -0.0002 |       2.7622 |
| book_to_market | 2025-10-31 | as_of_date |    0.1638 |         -0      |       2.7626 |
| book_to_market | 2017-03-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-04-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-10-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-09-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-08-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-07-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-06-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-05-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-11-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-12-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-11-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-12-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-05-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-06-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-07-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-08-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-09-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2017-10-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-07-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-08-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-09-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-10-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-11-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-12-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-01-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-02-28 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-03-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2019-04-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-01-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-02-28 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-03-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-04-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-05-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2018-06-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-06-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-05-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-04-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-03-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-02-29 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-01-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-08-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-07-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2025-11-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2025-12-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-09-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-10-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-11-30 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2020-12-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2021-01-31 | as_of_date |    0.1638 |          0      |       2.8134 |
| book_to_market | 2021-02-28 | as_of_date |    0.1638 |          0      |       2.8134 |
