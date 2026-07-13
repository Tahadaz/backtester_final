# Value + Momentum CONFIRMATION Study v2 -- Verdict Report

Run timestamp (UTC): v2-20260712-173809
Panel: research-out\data-quality-forensic-repair\2026-07-06\characteristic-study-after-repair\20260706-194324\panel_characteristics.csv
Common invested window: 2022-03-31 .. 2026-05-31

## Config echo

- `timestamp_utc`: v2-20260712-173809
- `panel_path`: research-out\data-quality-forensic-repair\2026-07-06\characteristic-study-after-repair\20260706-194324\panel_characteristics.csv
- `common_invested_window`: ['2022-03-31', '2026-05-31']
- `sector_cap`: 0.3
- `max_name_weight`: None
- `cost_bps_primary`: 33.0
- `cost_bps_robust`: 75.0
- `dd_tolerance`: 0.02
- `p_threshold`: 0.1
- `primary_weights_value_momentum`: (0.7, 0.3)

## Headline metrics -- ALL cells (invested window)

| Cell | CAGR | Sharpe | MaxDD | HitRate | AvgTurnover | IR vs MASI |
|---|---|---|---|---|---|---|
| C0a | 0.3157 | 1.624 | -0.1390 | 0.588 | 0.0351 | 1.23 |
| VM2 | 0.2940 | 1.589 | -0.1653 | 0.667 | 0.0441 | 1.28 |
| VM2_uncapped | 0.2974 | 1.498 | -0.1653 | 0.608 | 0.0513 | 1.339 |
| VM2_5050 | 0.2942 | 1.605 | -0.1543 | 0.647 | 0.0564 | 1.47 |
| VM2_cost50 | 0.2917 | 1.578 | -0.1659 | 0.667 | 0.0441 | 1.27 |
| VM2_cost75 | 0.2883 | 1.563 | -0.1667 | 0.647 | 0.0441 | 1.256 |
| MASI | 0.1824 | 1.394 | -0.1443 | 0.571 | 0.0000 | None |

## PROMOTION BAR -- gates (a)-(g)

**OVERALL: NOT PROMOTED (value-only C0a stands)**

- `a_sharpe_ge_incumbent`: FAIL -- {'pass': False, 'primary': 1.5889754799379343, 'incumbent': 1.6235485625722093}
- `b_drawdown_tolerance`: FAIL -- {'pass': False, 'primary': -0.16533179302041334, 'incumbent': -0.13901244602814533, 'tolerance': 0.02}
- `c_difference_pvalue`: FAIL -- {'pass': False, 'pvalue': 0.2818, 'threshold': 0.1}
- `d_sharpe_ge_masi`: PASS -- {'pass': True, 'primary': 1.5889754799379343, 'masi': 1.3944068052022727}
- `e_split_half_consistency`: FAIL -- {'pass': False, 'half1': {'months': 26, 'vm2_cum_return': 0.629783691835939, 'c0a_cum_return': 0.8134402355445809, 'pass': False}, 'half2': {'months': 25, 'vm2_cum_return': 0.8346873692886092, 'c0a_cum_return': 0.7696164117546915, 'pass': True}}
- `f_cost_robustness_75bps`: FAIL -- {'pass': False, 'vm2_cost75_sharpe': 1.5630615192300854, 'c0a_cost33_sharpe': 1.6235485625722093}
- `g_drop_the_winner`: PASS -- {'pass': True, 'winner_symbol': 'JET', 'winner_total_return': 10.005, 'ex_common_invested_window': ['2022-03-31', '2026-05-31'], 'vm2_ex_sharpe': 1.447972335081671, 'c0a_ex_sharpe': 1.3961371779211813, 'candidate_returns_all_ever_held': {'ADH': 3.524137931034482, 'ADI': 5.407251132989529, 'ATW': 0.517391304347826, 'BCP': -0.101123595505618, 'CDM': 0.631899871630295, 'JET': 10.005}}

Difference test (VM2 - C0a): {'nobs': 51, 'mean_monthly_diff': -0.0015255288455166996, 'annualized_diff': -0.018306346146200393, 'observed_total_return_diff': -0.08149709556447238, 'pvalue': 0.2818, 'method': 'stationary_block_bootstrap_on_monthly_net_return_difference', 'block_mean': 6, 'n_iter': 5000}

Raw evaluate_acceptance verdict (a-d only, informational): C

## Active-return correlation (VM2-MASI vs C0a-MASI, common window)

correlation = 0.9643

## Momentum-real coverage of VM2 selected names

mean fraction of composite weight where momentum was REAL (not imputed): 0.7506535947712418

## Turnover by cell (invested window)

| cell         |   avg_turnover |
|:-------------|---------------:|
| C0a          |      0.0351413 |
| VM2          |      0.0441424 |
| VM2_uncapped |      0.0513319 |
| VM2_5050     |      0.0564412 |
| VM2_cost50   |      0.0441424 |
| VM2_cost75   |      0.0441424 |

## Cost sensitivity (VM2)

|   cost_bps |     cagr |   sharpe |   max_drawdown |   avg_turnover |
|-----------:|---------:|---------:|---------------:|---------------:|
|         33 | 0.29398  |  1.58898 |      -0.165332 |      0.0441424 |
|         50 | 0.291698 |  1.57849 |      -0.165872 |      0.0441424 |
|         75 | 0.288349 |  1.56306 |      -0.166666 |      0.0441424 |

## C0a sanity check (this run's full-frame C0a vs v1's C0a)

Result: PASS
- cumulative_return: this_run=2.2090936025559835 v1=2.2090936025559835 pass=True
- sharpe: this_run=1.0449603912315126 v1=1.0449603912315126 pass=True
- max_drawdown: this_run=-0.13901244602814533 v1=-0.13901244602814533 pass=True
- periods: this_run=111 v1=111 pass=True
- cagr: this_run=0.13434207596163295 v1=0.13434207596163295 pass=True

## Analysis (orchestrator)

**NOT PROMOTED — and this closes the value+momentum question on current-era
CSE data.** The single-shot confirmation, run with the structural fixes the
v1 diagnosis demanded (graceful integration over the full eligible_bm
universe with neutral 0.5 imputation; sector cap only), rejects the
combination on 4 of 7 pre-registered gates:

- With the full universe in play, the 0.7/0.3 tilt yields Sharpe 1.589 vs
  C0a's 1.624, a *negative* mean monthly difference (-0.15%/mo, p=0.28),
  more drawdown (-0.165 vs -0.139, breaching the 2pt tolerance), and fails
  the first split-half. The active-return correlation of 0.964 is the
  mechanism: over the real value universe, a 30% momentum rank-tilt barely
  reshapes the portfolio, and the reshaping it does is unhelpful.
- v1's spectacular exploratory cells (VM_int uncapped CAGR 49.5%, w73 55.2%)
  are hereby explained as artifacts of the thin 2022-23 intersection
  universe: 3-4 name portfolios that happened to ride multi-baggers (JET
  +1000% over the window). The drop-the-winner gate (g) passing here shows
  VM2 is not a one-stock story — but gates (a)(b)(c)(e)(f) show it is not an
  improvement either.
- Momentum's standalone result from v1 stands unrefuted (M12 beat MASI,
  Sharpe 1.42, IR 1.95) but carries -0.20 maxDD, double the turnover, a
  bull-flattered 51-month sample with no momentum-crash regime, and no
  incremental value over the value strategy. It is a possible future
  *satellite sleeve* candidate after a full market cycle of data — not a
  production component now.

**Cumulative research ledger on this data (all pre-registered): time-series
trend/WFO gating — rejected (C); value+momentum integration v1 — rejected
(C, malformed primary); v2 confirmation — NOT PROMOTED. The validated
production edge remains exactly one strategy: B/M six-vintage value
(Sharpe 1.62, IR 1.23 vs MASI, 51 months), with CF/P as the validated
secondary characteristic and sector/name caps available as a
~Sharpe-neutral risk-policy toggle.**
