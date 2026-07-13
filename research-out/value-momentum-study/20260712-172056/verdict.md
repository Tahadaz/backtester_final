# Value + Momentum Study -- Verdict Report

Run timestamp (UTC): 20260712-172056
Panel: research-out\data-quality-forensic-repair\2026-07-06\characteristic-study-after-repair\20260706-194324\panel_characteristics.csv
Common invested window: 2022-03-31 .. 2026-05-31

## Config echo

- `momentum_coverage`: {'momentum_12_1_raw_notna': 2284, 'momentum_6_1_raw_notna': 2632, 'total_rows': 3104}
- `timestamp_utc`: 20260712-172056
- `panel_path`: research-out\data-quality-forensic-repair\2026-07-06\characteristic-study-after-repair\20260706-194324\panel_characteristics.csv
- `common_invested_window`: ['2022-03-31', '2026-05-31']
- `sector_cap`: 0.3
- `max_name_weight`: 0.1
- `cost_bps_primary`: 33.0
- `dd_tolerance`: 0.02
- `p_threshold`: 0.1

## Headline metrics -- ALL cells (invested window)

| Cell | CAGR | Sharpe | MaxDD | HitRate | AvgTurnover | IR vs MASI |
|---|---|---|---|---|---|---|
| C0a | 0.3157 | 1.624 | -0.1390 | 0.588 | 0.0351 | 1.23 |
| M12 | 0.4257 | 1.418 | -0.1968 | 0.667 | 0.0845 | 1.951 |
| M6 | 0.3036 | 1.337 | -0.2164 | 0.647 | 0.1115 | 2.026 |
| VM_int | 0.4953 | 1.603 | -0.1592 | 0.667 | 0.0725 | 1.667 |
| VM_int_capped | 0.2380 | 1.477 | -0.1592 | 0.667 | 0.0401 | 1.22 |
| VM_int_capped_cost50 | 0.2360 | 1.467 | -0.1599 | 0.647 | 0.0401 | 1.205 |
| VM_int_capped_cost75 | 0.2331 | 1.452 | -0.1611 | 0.647 | 0.0401 | 1.182 |
| VM_int_w37 | 0.4583 | 1.574 | -0.1703 | 0.627 | 0.0793 | 1.702 |
| VM_int_w73 | 0.5517 | 1.664 | -0.1697 | 0.608 | 0.0537 | 1.598 |
| VM_mix | 0.3749 | 1.590 | -0.1648 | 0.627 | 0.0598 | 1.796 |
| MASI | 0.1824 | 1.394 | -0.1443 | 0.571 | 0.0000 | None |

## STAGE-A mechanism gate (M12 vs MASI, common window)

**Stage A: PASS**

- `i_m12_sharpe_ge_masi_sharpe`: PASS -- {'pass': True, 'm12_sharpe': 1.4180675372883853, 'masi_sharpe': 1.3944068052022727}
- `ii_m12_information_ratio_gt_0`: PASS -- {'pass': True, 'm12_information_ratio': 1.9508222408317628}

## STAGE-B acceptance (primary = VM_int_capped vs incumbent C0a)

Status: **CONFIRMED (Stage A passed)**
Raw Stage-B verdict: C

- `a_sharpe_ge_incumbent`: FAIL -- {'pass': False, 'primary': 1.4774476874787237, 'incumbent': 1.6235485625722093}
- `b_drawdown_tolerance`: FAIL -- {'pass': False, 'primary': -0.15918753624178428, 'incumbent': -0.13901244602814533, 'tolerance': 0.02}
- `c_difference_pvalue`: FAIL -- {'pass': False, 'pvalue': 0.189, 'threshold': 0.1}
- `d_sharpe_ge_masi`: PASS -- {'pass': True, 'primary': 1.4774476874787237, 'masi': 1.3944068052022727}

Difference test (VM_int_capped - C0a): {'nobs': 51, 'mean_monthly_diff': -0.00553453463489803, 'annualized_diff': -0.06641441561877635, 'observed_total_return_diff': -0.26658719007358755, 'pvalue': 0.189, 'method': 'stationary_block_bootstrap_on_monthly_net_return_difference', 'block_mean': 6, 'n_iter': 5000}

## OVERALL VERDICT: C

## Monthly return correlation, M12 vs C0a (common window)

correlation = 0.7655

## Momentum candidate coverage

- `mean_n_eligible_bm`: 24.144144144144143
- `mean_n_momentum_12_1_notna`: 19.855855855855857
- `mean_pct_momentum_12_1_of_eligible_bm`: 1.3216063819894466
- `n_formation_dates`: 111

## Turnover by cell (invested window)

| cell                 |   avg_turnover |
|:---------------------|---------------:|
| C0a                  |      0.0351413 |
| M12                  |      0.0845231 |
| M6                   |      0.111528  |
| VM_int               |      0.0725466 |
| VM_int_capped        |      0.0401272 |
| VM_int_capped_cost50 |      0.0401272 |
| VM_int_capped_cost75 |      0.0401272 |
| VM_int_w37           |      0.0792537 |
| VM_int_w73           |      0.0536546 |

## Cost sensitivity (VM_int_capped)

|   cost_bps |     cagr |   sharpe |   max_drawdown |   avg_turnover |   breakeven_bps_analytic |
|-----------:|---------:|---------:|---------------:|---------------:|-------------------------:|
|         33 | 0.237974 |  1.47745 |      -0.159188 |      0.0401272 |                 -5517.17 |
|         50 | 0.235987 |  1.46704 |      -0.159949 |      0.0401272 |                 -5517.17 |
|         75 | 0.23307  |  1.45172 |      -0.161068 |      0.0401272 |                 -5517.17 |

Analytic breakeven cost (bps), VM_int_capped vs C0a: -5517.165876519631

## C0a sanity check (this run's full-frame C0a vs the prior combined-portfolio-strategy study's C0a)

Result: PASS
- cumulative_return: this_run=2.2090936025559835 prior_study=2.2090936025559835 pass=True
- sharpe: this_run=1.0449603912315126 prior_study=1.0449603912315126 pass=True
- max_drawdown: this_run=-0.13901244602814533 prior_study=-0.13901244602814533 pass=True
- periods: this_run=111 prior_study=111 pass=True
- cagr: this_run=0.13434207596163295 prior_study=0.13434207596163295 pass=True

## Anomalies / deviations

- Analytic breakeven cost for VM_int_capped vs C0a is negative (-5517.2 bps) -- VM_int_capped's mean GROSS return is already below C0a's (mean_gross_diff_monthly=-0.00550), so the underperformance is not a cost/turnover artifact; the breakeven figure is degenerate (no positive cost level makes VM_int_capped competitive on this metric).
- mean_pct_momentum_12_1_of_eligible_bm > 1.0: momentum_12_1_raw notna is counted within eligible_universe (the broader momentum-cell universe), which is larger than eligible_bm (requires book_to_market_raw notna too) on many dates -- not a data bug, just two different eligibility denominators.

## Analysis (orchestrator)

**Verdict C for the pre-registered primary stands, but the study's real findings
are (1) the momentum mechanism EXISTS on current-era CSE data (Stage A passed:
M12 Sharpe 1.42 >= MASI 1.39, IR 1.95, CAGR 42.6% -- reconciling the external
literature with the noisy in-house IC), and (2) the primary cell was
structurally malformed by a cap x coverage interaction, diagnosed post-hoc:**

- Most symbols' price bars start 2023-04, so 12-1 momentum exists for only
  ~10 names before 2024. The dual-signal (B/M AND momentum) intersection
  universe produced 3-4 name terciles in 2022-23 at 25-33% weight each; the
  10% name cap therefore forced the capped cell to **77.5% cash in 2022 and
  70.0% in 2023** (verified from cash_weight), fully explaining its CAGR
  collapse (49.5% -> 23.8%). From 2025 the caps never bind (identical
  drawdown paths to machine precision, verified).
- Consequently the early backtest years test a *different, thinner* strategy
  than the recent years -- the intersection-universe design was the mistake,
  not the integration concept.
- Exploratory cells (NOT promotable, single-look): uncapped VM_int Sharpe
  1.603 / CAGR 49.5%; value-tilted VM_int_w73 (0.7 B/M + 0.3 momentum)
  **Sharpe 1.664 > C0a's 1.624, CAGR 55.2%, maxDD -0.17, turnover 0.054** --
  the best cell seen in any study on this data. Momentum-only cells carry the
  classic crash-risk signature (maxDD -0.20/-0.22) and the 51-month window
  contains no momentum-crash regime; treat all momentum results as
  bull-sample-flattered.
- M12-C0a total-return correlation 0.77 is high because both are long-only in
  the same market; the combination benefit shows in the return lift, not in
  correlation reduction.

**Decision: verdict C recorded; a single pre-registered CONFIRMATION study
(v2) is authorized with the structural fixes (graceful missing-momentum
integration over the full eligible_bm universe with neutral 0.5 rank
imputation; sector cap only, no name cap) and a strictly harder, A-grade-only
promotion bar with split-half, cost-75bps, and drop-the-winner robustness
gates -- explicitly acknowledging that the 0.7/0.3 tilt was observed in this
study's sensitivity table (selection-bias disclosure).**
