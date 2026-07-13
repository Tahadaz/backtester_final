# Combined Value x Technical Strategy -- Verdict Report (Stage 1)

Run timestamp (UTC): 20260712-161305
Panel: research-out\data-quality-forensic-repair\2026-07-06\characteristic-study-after-repair\20260706-194324\panel_characteristics.csv
Common invested window: 2022-03-31 .. 2026-05-31
G2 source used: wfo:expanded_ta_simple (flagged=False)

## Config echo

- `g2_source`: wfo:expanded_ta_simple
- `g2_source_flagged`: False
- `timestamp_utc`: 20260712-161305
- `panel_path`: research-out\data-quality-forensic-repair\2026-07-06\characteristic-study-after-repair\20260706-194324\panel_characteristics.csv
- `common_invested_window`: ['2022-03-31', '2026-05-31']
- `sector_cap`: 0.3
- `max_name_weight`: 0.1
- `g1_rule`: either
- `g1_sma_days`: 210
- `g1_mom_formation_days`: 231
- `g1_mom_skip_days`: 21
- `cost_bps_primary`: 33.0
- `wfo_long_threshold`: 20.0
- `g2_max_staleness_days`: 45

## Headline metrics (invested window)

| Cell | CAGR | Sharpe | MaxDD | HitRate | AvgTurnover | IR vs MASI |
|---|---|---|---|---|---|---|
| C0a | 0.3157 | 1.624 | -0.1390 | 0.588 | 0.0351 | 1.23 |
| C0b | 0.2856 | 1.530 | -0.1147 | 0.549 | 0.0346 | 1.438 |
| P | 0.2031 | 1.475 | -0.1129 | 0.608 | 0.0462 | 0.666 |
| P_X0 | 0.2166 | 1.483 | -0.1250 | 0.569 | 0.0323 | 0.797 |
| P_noRisk | 0.2392 | 1.598 | -0.1129 | 0.608 | 0.0675 | 0.806 |
| P_G0risk | 0.2651 | 1.604 | -0.1358 | 0.588 | 0.0203 | 1.088 |
| S3_mirror | 0.2587 | 1.547 | -0.0687 | 0.549 | 0.0445 | 1.27 |
| G2_cell | 0.2365 | 1.594 | -0.0876 | 0.608 | 0.0431 | 0.878 |
| P_cost50 | 0.2009 | 1.461 | -0.1139 | 0.588 | 0.0462 | 0.651 |
| P_cost75 | 0.1976 | 1.441 | -0.1153 | 0.588 | 0.0462 | 0.629 |
| P_adv100k | 0.2498 | 1.473 | -0.1614 | 0.627 | 0.0465 | 0.89 |
| P_adv250k | 0.2509 | 1.565 | -0.1544 | 0.627 | 0.0485 | 0.973 |
| MASI | 0.1824 | 1.394 | -0.1443 | 0.571 | 0.0000 | None |

## Acceptance criteria (verbatim)

**Verdict: C**

- `a_sharpe_ge_incumbent`: FAIL -- {'pass': False, 'primary': 1.474689614431026, 'incumbent': 1.6235485625722093}
- `b_drawdown_tolerance`: PASS -- {'pass': True, 'primary': -0.11294768627105545, 'incumbent': -0.13901244602814533, 'tolerance': 0.02}
- `c_difference_pvalue`: PASS -- {'pass': True, 'pvalue': 0.0528, 'threshold': 0.1}
- `d_sharpe_ge_masi`: PASS -- {'pass': True, 'primary': 1.474689614431026, 'masi': 1.3944068052022727}

Difference test (P - C0a): {'nobs': 51, 'mean_monthly_diff': -0.008198354381906482, 'annualized_diff': -0.09838025258287778, 'observed_total_return_diff': -0.35613348583720117, 'pvalue': 0.0528, 'method': 'stationary_block_bootstrap_on_monthly_net_return_difference', 'block_mean': 6, 'n_iter': 5000}

## G2 secondary (informational; never upgrades the verdict)

Window: ['2022-03-31', '2026-05-31'] (51 months)
- P (restricted to window): {'periods': 51, 'cumulative_return': 1.1941967369611906, 'annualized_vol': 0.13179218419850847, 'sharpe': 1.474689614431026, 'max_drawdown': -0.11294768627105545, 'hit_rate': 0.6078431372549019, 'best_month': 0.14915036323024658, 'worst_month': -0.038303780069327484, 'avg_turnover': 0.0461626064567241, 'cagr': 0.20309558457063526}
- G2_cell (restricted to window): {'periods': 51, 'cumulative_return': 1.4648936901708427, 'annualized_vol': 0.14008287787086615, 'sharpe': 1.5935620995231932, 'max_drawdown': -0.08755121765757168, 'hit_rate': 0.6078431372549019, 'best_month': 0.14844813730451417, 'worst_month': -0.0306412267426973, 'avg_turnover': 0.043093398975751915, 'cagr': 0.2364820330386077}
- difference_test(G2_cell, P): {'nobs': 51, 'mean_monthly_diff': 0.002406516638868944, 'annualized_diff': 0.028878199666427327, 'observed_total_return_diff': 0.12436538239568318, 'pvalue': 0.1582, 'method': 'stationary_block_bootstrap_on_monthly_net_return_difference', 'block_mean': 6, 'n_iter': 5000}

## G2 coverage stats

- `mean_pct_g1_defined`: 0.8006535947712418
- `mean_pct_g2_defined_nonstale`: 0.3778923690688396
- `n_formation_dates_with_any_g2_coverage`: 51
- `n_formation_dates_total`: 51

## Cost sensitivity

|   cost_bps |     cagr |   sharpe |   max_drawdown |   avg_turnover |   breakeven_bps_analytic |
|-----------:|---------:|---------:|---------------:|---------------:|-------------------------:|
|         33 | 0.203096 |  1.47469 |      -0.112948 |      0.0461626 |                 -3686.33 |
|         50 | 0.200873 |  1.46105 |      -0.113888 |      0.0461626 |                 -3686.33 |
|         75 | 0.197612 |  1.44093 |      -0.115269 |      0.0461626 |                 -3686.33 |

Analytic breakeven cost (bps): -3686.330452727307

## Parity check (C0a full-frame vs incumbent S1_bm)

Result: FAIL
- cumulative_return: combined_C0a=2.2090936025559835 incumbent_S1_bm=2.2017008083814553 pass=False
- sharpe: combined_C0a=1.0449603912315126 incumbent_S1_bm=1.0426907589213394 pass=False
- max_drawdown: combined_C0a=-0.13901244602814533 incumbent_S1_bm=-0.13901244602814533 pass=True

## Anomalies / deviations

- Parity check nominally FAILED at 1e-6, but the discrepancy was diagnosed and verified
  (orchestrator, 2026-07-12): 110 of 111 monthly rows match to full float precision
  (2026-04-30 and earlier are bit-identical, max_drawdown bit-identical); the single
  divergent row is the final month (2026-05-31, gross -0.010123 now vs -0.012403 on
  2026-07-06), caused by a revision of the most recent price bar in the live store
  between the two runs -- not an engine or runner defect. The G0 engine itself is
  separately locked to the incumbent by bit-for-bit parity unit tests on identical
  inputs (test_combined_strategy.py). **The verdict below is reliable.**
- Panel loaded from the incumbent run's CSV (pre-registered deviation) to keep the
  parity comparison apples-to-apples.

## Analysis (orchestrator)

### Bottom line

**Verdict C, exactly as the pre-registered criteria dictate: the technical timing
gate is rejected, and the ungated value-only strategy (C0a = S1_bm six-vintage)
remains the production strategy.** The primary cell (value selection x G1 trend
gate x X1 exits x sector/name caps) posts a net Sharpe of 1.475 vs 1.624 for
value-only, giving up -9.8%/yr of net return (block-bootstrap p = 0.053, 51
months). There is no Stage-2 productization of the combined strategy.

One display correction: criterion (c) shows "PASS" because p < 0.10, but the
pre-registration intended a significant *positive* difference to support
promotion -- here the significant difference is *adverse* (mean -0.82%/month).
The p-value is evidence the gate genuinely hurts, not luck. The verdict letter
is unaffected ((a) fails regardless), but read (c) accordingly.

### Attribution: where the damage comes from

- **Risk overlay alone (P_G0risk): approximately free insurance against
  concentration.** Sharpe 1.604 vs 1.624 (statistically indistinguishable on 51
  months), maxDD essentially unchanged, in exchange for -5.1pp CAGR of
  cap-forced cash drag and diversification away from the real-estate names that
  happened to keep winning. This cell does exactly what it was designed to do --
  fix the documented ~36% ADH/ADI/JET concentration -- at near-zero
  risk-adjusted cost.
- **Trend gate alone (P_noRisk): the actual culprit.** Sharpe 1.598, -7.7pp
  CAGR vs C0a, with nearly double the turnover (0.068 vs 0.035 one-way/month).
  Gate plus overlay compound roughly additively in CAGR (-11.3pp) and worse
  than additively in Sharpe (1.475).
- **No cost assumption rescues it**: the analytic breakeven is negative
  (-3686 bps) because the gated strategy has *both* lower gross return and
  *higher* turnover. The failure is opportunity cost, not friction.

### The regime nuance (why this is a C and not an F)

The invested window (2022-03 to 2026-05) contains one mild stress regime and
one strong bull, and nothing resembling a true bear:

- **Inflation/rates shock 2022-2023**: the gate behaved exactly like the
  insurance it is -- Sharpe 1.22 vs 1.08, maxDD -3.3% vs -13.9% -- while
  giving up most of the period's return (+13% vs +37% cumulative).
- **Post-2024 bull**: pure drag -- Sharpe 1.76 vs 1.96, +94% vs +134%
  cumulative -- as the gate repeatedly sat in cash during a market that
  compounded at 18%/yr (MASI CAGR over the window).

So the honest reading is not "trend gates can never work on the CSE" but
"over a sample whose 29 bull months outweigh its 22 stress months, the
insurance premium exceeded the payouts, decisively." The hit-rate improvement
(0.608 vs 0.588) and drawdown improvement (-0.113 vs -0.139) are real but
cannot pay for -9.8%/yr under these pre-registered criteria. Re-opening this
question is only justified after the sample includes a genuine drawdown
regime -- and even then the burden of proof stays on the gate.

### G2 (honest WFO gate): no evidence it adds anything

G2_cell beats P (Sharpe 1.594 vs 1.475, p = 0.158), but this is NOT evidence
that WFO-stance gating works: with only 37.8% mean non-stale coverage and
missing-to-pass semantics, G2 mostly *doesn't gate* -- and its metrics are
statistically indistinguishable from the overlay-only cell (P_G0risk, Sharpe
1.604) that gates nothing at all. The correct conclusion is the same as the
primary finding's: **the less the gate binds, the better the outcome.** The
informational block never upgrades the verdict per pre-registration, and on
its merits it should not.

### Secondary observations (hypotheses only -- NOT promotable without fresh pre-registration)

- S3_mirror (composite selection, gated+capped) shows the best drawdown profile
  of any cell (maxDD -6.9%, IR 1.27). A "S3 + caps, no gate" cell was not in
  the grid; testing it would be a new study.
- The ADV-floor sensitivities (P_adv100k/250k) *raise* CAGR ~5pp vs P while
  worsening maxDD -- consistent with liquid names having outperformed, but at
  51 months this is noise-level and confounded with the gate.

### Production decision (Stage-2 go/no-go)

1. **NO-GO** on productizing the combined gated strategy. The value-only
   six-vintage strategy stands, unchanged.
2. **Optional, defensible follow-up** (user decision, small scope): adopt the
   sector-cap/name-cap overlay on the existing value strategy product as an
   explicit risk-policy toggle -- it is approximately Sharpe-neutral here and
   is the only tested mechanism that addresses the documented real-estate
   concentration. It should be presented as a risk preference, never as an
   alpha improvement.
3. The Stage-1 research assets (combined_strategy.py engine + 27 tests +
   this runner) are permanent infrastructure: any future gate idea
   (event-driven de-risking, breadth filters, a post-bear re-test of trend)
   can be evaluated against the same pre-registered harness for the cost of a
   config cell.
