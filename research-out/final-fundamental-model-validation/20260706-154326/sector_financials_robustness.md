# Sector And Financial-Firm Robustness

Generated: 2026-07-06T15:49:27.963209+00:00

## Financial/Nonfinancial Filters

| sample       | signal         | definition   | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue |   top_bottom_spread |   net_sharpe |   max_drawdown |   turnover |   avg_names_per_date |   dates |   symbols |
|:-------------|:---------------|:-------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|--------------------:|-------------:|---------------:|-----------:|---------------------:|--------:|----------:|
| full         | book_to_market | B/M          | 6m        |        56 |    2254 |    0.1638 |      0.1743 |   0.2419 |     0.7679 |       2.8134 |   0.0049 |              0.1034 |       0.7591 |        -0.8644 |     0.0685 |              43.6349 |      63 |        70 |
| full         | cashflow_price | CF/P         | 6m        |        44 |    2139 |    0.1467 |      0.1329 |   0.1379 |     0.8864 |       5.8144 |   0      |              0.1035 |       1.0634 |        -0.6233 |     0.0988 |              51.5098 |      51 |        69 |
| nonfinancial | book_to_market | B/M          | 6m        |        56 |    1791 |    0.177  |      0.1617 |   0.2661 |     0.7679 |       2.8597 |   0.0042 |              0.1608 |       0.8735 |        -0.8676 |     0.0661 |              34.6508 |      63 |        59 |
| nonfinancial | cashflow_price | CF/P         | 6m        |        44 |    1676 |    0.1351 |      0.1521 |   0.1344 |     0.8182 |       4.8894 |   0      |              0.1262 |       0.9958 |        -0.7133 |     0.1169 |              40.4118 |      51 |        55 |
| financial    | book_to_market | B/M          | 6m        |        31 |     424 |    0.0228 |      0.0462 |   0.4307 |     0.5806 |       0.1404 |   0.8883 |              0.018  |       0.2193 |        -0.7089 |     0.0796 |              11.098  |      51 |        15 |
| financial    | cashflow_price | CF/P         | 6m        |        31 |     424 |    0.1762 |      0.1826 |   0.1968 |     0.7742 |       4.728  |   0      |              0.0686 |       1.7232 |        -0.0393 |     0.0581 |              11.098  |      51 |        15 |

## Leave-One-Sector

| sample                        | signal         | definition   | horizon   |   periods |   pairs |   mean_ic |   median_ic |   ic_std |   hit_rate |   hac_t_stat |   pvalue | excluded_sector         |
|:------------------------------|:---------------|:-------------|:----------|----------:|--------:|----------:|------------:|---------:|-----------:|-------------:|---------:|:------------------------|
| minus_Agroalimentaire         | book_to_market | B/M          | 6m        |        56 |    2087 |    0.158  |      0.1579 |   0.2468 |     0.7679 |       2.6456 |   0.0082 | Agroalimentaire         |
| minus_Agroalimentaire         | cashflow_price | CF/P         | 6m        |        44 |    1972 |    0.1729 |      0.1686 |   0.1568 |     0.8409 |       6.3006 |   0      | Agroalimentaire         |
| minus_Assurances              | book_to_market | B/M          | 6m        |        56 |    2101 |    0.1517 |      0.1565 |   0.2454 |     0.75   |       2.5502 |   0.0108 | Assurances              |
| minus_Assurances              | cashflow_price | CF/P         | 6m        |        44 |    1986 |    0.1419 |      0.1325 |   0.1403 |     0.9091 |       5.5392 |   0      | Assurances              |
| minus_Autre                   | book_to_market | B/M          | 6m        |        56 |    2161 |    0.1665 |      0.1499 |   0.2439 |     0.7679 |       2.8077 |   0.005  | Autre                   |
| minus_Autre                   | cashflow_price | CF/P         | 6m        |        44 |    2046 |    0.1547 |      0.1478 |   0.1435 |     0.8864 |       5.4032 |   0      | Autre                   |
| minus_BTP                     | book_to_market | B/M          | 6m        |        56 |    1956 |    0.2736 |      0.2144 |   0.3296 |     0.8214 |       3.0438 |   0.0023 | BTP                     |
| minus_BTP                     | cashflow_price | CF/P         | 6m        |        44 |    1896 |    0.1819 |      0.1465 |   0.1798 |     0.9318 |       5.296  |   0      | BTP                     |
| minus_Banques                 | book_to_market | B/M          | 6m        |        44 |    1922 |    0.2035 |      0.1848 |   0.2666 |     0.7727 |       2.7153 |   0.0066 | Banques                 |
| minus_Banques                 | cashflow_price | CF/P         | 6m        |        44 |    1891 |    0.1533 |      0.1455 |   0.1151 |     0.8636 |       6.6414 |   0      | Banques                 |
| minus_Boissons                | book_to_market | B/M          | 6m        |        56 |    2223 |    0.1603 |      0.167  |   0.2444 |     0.7679 |       2.717  |   0.0066 | Boissons                |
| minus_Boissons                | cashflow_price | CF/P         | 6m        |        44 |    2108 |    0.1513 |      0.1363 |   0.1394 |     0.8864 |       5.9875 |   0      | Boissons                |
| minus_Chimie                  | book_to_market | B/M          | 6m        |        56 |    2223 |    0.1647 |      0.1578 |   0.2452 |     0.7857 |       2.7586 |   0.0058 | Chimie                  |
| minus_Chimie                  | cashflow_price | CF/P         | 6m        |        44 |    2108 |    0.1477 |      0.143  |   0.1386 |     0.8636 |       5.7108 |   0      | Chimie                  |
| minus_Distribution            | book_to_market | B/M          | 6m        |        56 |    2109 |    0.1722 |      0.1793 |   0.2287 |     0.8036 |       3.2941 |   0.001  | Distribution            |
| minus_Distribution            | cashflow_price | CF/P         | 6m        |        44 |    1994 |    0.1591 |      0.1523 |   0.18   |     0.8864 |       4.1021 |   0      | Distribution            |
| minus_Immobilier              | book_to_market | B/M          | 6m        |        56 |    2043 |    0.1375 |      0.1278 |   0.247  |     0.7321 |       2.5647 |   0.0103 | Immobilier              |
| minus_Immobilier              | cashflow_price | CF/P         | 6m        |        44 |    1928 |    0.1102 |      0.1249 |   0.1708 |     0.75   |       4.2477 |   0      | Immobilier              |
| minus_Industrie               | book_to_market | B/M          | 6m        |        56 |    2212 |    0.17   |      0.2091 |   0.2381 |     0.8036 |       3.036  |   0.0024 | Industrie               |
| minus_Industrie               | cashflow_price | CF/P         | 6m        |        44 |    2097 |    0.1414 |      0.1279 |   0.1406 |     0.8409 |       5.6313 |   0      | Industrie               |
| minus_Informatique            | book_to_market | B/M          | 6m        |        56 |    2037 |    0.1675 |      0.1999 |   0.2494 |     0.7679 |       2.7133 |   0.0067 | Informatique            |
| minus_Informatique            | cashflow_price | CF/P         | 6m        |        44 |    1922 |    0.1487 |      0.1449 |   0.1261 |     0.9318 |       7.3385 |   0      | Informatique            |
| minus_Loisirs & Hôtels        | book_to_market | B/M          | 6m        |        56 |    2223 |    0.1625 |      0.1769 |   0.2418 |     0.7679 |       2.8094 |   0.005  | Loisirs & Hôtels        |
| minus_Loisirs & Hôtels        | cashflow_price | CF/P         | 6m        |        44 |    2108 |    0.1442 |      0.1384 |   0.1369 |     0.8636 |       5.8554 |   0      | Loisirs & Hôtels        |
| minus_Mines                   | book_to_market | B/M          | 6m        |        56 |    2100 |    0.1672 |      0.1485 |   0.2547 |     0.75   |       2.6061 |   0.0092 | Mines                   |
| minus_Mines                   | cashflow_price | CF/P         | 6m        |        44 |    1985 |    0.1468 |      0.1267 |   0.1382 |     0.9091 |       5.7016 |   0      | Mines                   |
| minus_Santé                   | book_to_market | B/M          | 6m        |        56 |    2215 |    0.1706 |      0.1872 |   0.2523 |     0.7679 |       2.7223 |   0.0065 | Santé                   |
| minus_Santé                   | cashflow_price | CF/P         | 6m        |        44 |    2100 |    0.1379 |      0.1307 |   0.1389 |     0.8864 |       5.5796 |   0      | Santé                   |
| minus_Sociétés de financement | book_to_market | B/M          | 6m        |        56 |    2132 |    0.1743 |      0.1996 |   0.2377 |     0.8036 |       3.102  |   0.0019 | Sociétés de financement |
| minus_Sociétés de financement | cashflow_price | CF/P         | 6m        |        44 |    2017 |    0.1379 |      0.1278 |   0.1472 |     0.8636 |       4.8037 |   0      | Sociétés de financement |
| minus_Transport               | book_to_market | B/M          | 6m        |        56 |    2167 |    0.1854 |      0.192  |   0.2711 |     0.75   |       2.8696 |   0.0041 | Transport               |
| minus_Transport               | cashflow_price | CF/P         | 6m        |        44 |    2064 |    0.1489 |      0.1424 |   0.1599 |     0.9091 |       4.8972 |   0      | Transport               |
| minus_Télécommunications      | book_to_market | B/M          | 6m        |        56 |    2198 |    0.1031 |      0.1256 |   0.2545 |     0.6607 |       1.6753 |   0.0939 | Télécommunications      |
| minus_Télécommunications      | cashflow_price | CF/P         | 6m        |        44 |    2095 |    0.1117 |      0.1214 |   0.1451 |     0.8182 |       3.8402 |   0.0001 | Télécommunications      |
| minus_Électricité             | book_to_market | B/M          | 6m        |        56 |    2223 |    0.1654 |      0.1723 |   0.2412 |     0.7679 |       2.8377 |   0.0045 | Électricité             |
| minus_Électricité             | cashflow_price | CF/P         | 6m        |        44 |    2108 |    0.1412 |      0.1253 |   0.1393 |     0.8636 |       5.3717 |   0      | Électricité             |
| minus_Énergie                 | book_to_market | B/M          | 6m        |        56 |    2192 |    0.1611 |      0.1711 |   0.244  |     0.7679 |       2.7228 |   0.0065 | Énergie                 |
| minus_Énergie                 | cashflow_price | CF/P         | 6m        |        44 |    2077 |    0.1501 |      0.1427 |   0.1378 |     0.8864 |       5.9349 |   0      | Énergie                 |
