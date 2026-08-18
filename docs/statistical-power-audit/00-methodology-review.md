# Statistical Power Audit — Methodology Review (Discussion Draft)

Status: DISCUSSION DRAFT for user review — no code changes derive from this until approved.
Date: 2026-07-18
Locked calibration so far (user decisions): economic anchor = net annualized Sharpe SR* = 0.5;
test spec = one-sided alpha = 5%, 80% power primary (90% sensitivity); scope = all signal
families; delivery = report only.

This document critically reviews the initially proposed "replace N>=30 with power analysis"
plan, point by point, with derivations. Sections marked **[DECISION]** need the user's
judgment; everything else has a determinate statistical answer. A summary decision list is at
the end (Section 13).

---

## 0. Vocabulary used throughout (precise definitions)

- **Statistical significance**: the observed effect is unlikely (p <= alpha) under the null
  of no effect. Says nothing about size or reliability of the estimate.
- **Statistical power**: probability of *detecting* an effect of size delta if it truly
  exists, with the given test and sample. A property of the design, not the data.
- **Minimum detectable effect (MDE)**: the smallest true effect the current sample could
  detect with the target power. MDE = (z_a + z_b) * sigma_LR / sqrt(N).
- **Economic relevance**: the point estimate exceeds delta, the pre-set smallest effect worth
  trading. Independent of significance.
- **Multiple-testing control**: adjustment for the fact that many candidates were searched.
- **OOS confirmation**: a test on data untouched by the search that produced the candidate.
- **Robustness**: stability of the conclusion across subperiods, estimator settings
  (bandwidths, block lengths), and specification perturbations.

A validated signal must clear ALL of these; the current gates test only the first (and a
zero-hurdle version of economic relevance).

---

## 1. The correct observation unit

### 1.1 Principle

Every gate tests a mean. For independent observations Var(mean) = sigma^2/N. For dependent
observations:

    Var(mean) = (sigma^2 / N) * VIF,
    VIF = 1 + 2 * sum_{k>=1} (1 - k/N) * rho_k        (variance inflation factor)

Two special cases dominate this repo:

- **Overlapping windows**: an h-bar forward return sampled every bar is a moving sum, an
  MA(h-1) process with rho_k ~= 1 - k/h. Then VIF ~= h exactly: daily-sampled h-bar returns
  carry 1/h of the information their count suggests. 30 bucket-days at the monthly horizon
  (h=21) can be worth ~1.4 independent observations.
- **Clustered observations** (many stocks, one date): Moulton factor
  VIF = 1 + (m_bar - 1) * rho_within. With 73 stocks and intra-date correlation 0.2-0.4,
  pooled stock-dates overstate information by a factor of ~15-30.

**Governing rule**: the unit is the largest block such that blocks are approximately
exchangeable under the null. Smaller units = pseudo-replication; larger = conservative.

### 1.2 Repo finding (the central defect)

`core/quant_core/research/edge.py` counts one observation per OOS *bucket-day* (every day the
score sits in today's bucket contributes an h-bar forward return; `_sample_frames`, capped at
`EDGE_MAX_OBSERVATIONS = 100`). Consecutive signal days produce near-duplicate windows, yet
each counts toward `gate_n = n >= 30`. At quarterly horizon (h = 63, N <= 100) the overlap
ratio h/N reaches 0.63, which is inside the zone where even HAC-corrected t-statistics are
severely size-distorted (Valkanov 2003). The n >= 30 gate can be satisfied by fewer than two
statistically independent windows.

### 1.3 Literature resolution

- Fama (1998), Mitchell & Stafford (2000): per-event buy-and-hold returns with overlapping
  windows produce invalid t-stats (cross-correlation); the accepted fix is the
  **calendar-time portfolio**: one observation per calendar period over the portfolio of all
  active positions. Double counting becomes impossible by construction.
- Hansen & Hodrick (1980), Richardson & Smith (1991): overlapping observations may be kept
  with corrected (HAC) standard errors — valid only while h/N is small; Valkanov (2003)
  shows breakdown otherwise. Usable here only at the weekly horizon (h/N ~= 0.05).
- Lo (2002), Bailey & Lopez de Prado (2012): Sharpe inference (PSR, MinTRL) is defined on
  calendar-period returns; a "Sharpe over 30 trades" has no valid inference.
- Petersen (2009): panel inference must cluster on the dimension with common shocks (time);
  per-date statistics (Fama-MacBeth, per-date IC) are the correct cross-sectional unit.
- Per-trade statistics (expectancy, profit factor, win rate): practitioner diagnostics; no
  inferential literature supports them as primary validation units (variable holding periods,
  overlap, shared capital, exit-date bunching).

### 1.4 Resolution per family **[DECISION D1 — recommended defaults below]**

| Family | Primary gate unit | Supporting / diagnostic units | Basis |
|---|---|---|---|
| Edge engine (symbol x horizon x bucket) | Calendar-time MTM return series of "hold while in bucket" (active periods) | Non-overlapping trade episodes (cost hurdle); bucket-day stats HAC-deflated (weekly cross-check only) | Fama 98 / M-S 00; Valkanov 03 |
| S/R WFO | Calendar-time daily series (consistent with its Sharpe-vs-buy-hold gate) | Completed trades (valid unit here: single position + cooldown, `sr_wfo.py:180`) | Lo 02 |
| Historical portfolio backtest | Weekly MTM portfolio return (requires the already-briefed MTM fix; booked-at-exit returns bunch P&L) | Per-trade attribution | Fama 98 |
| MASI condition discovery | Decision-date cluster of triggered trades (code already tests this via `_one_sided_cluster_pvalue`; the `min_outer_trades=15` gate must count clusters, not trades) | Per-trade ledger | Petersen 09 |
| Stat-arb pairs | Daily spread P&L per pair | Pair-formation stats | standard TS |
| Cross-sectional IC | One IC per evaluation date | Pooled per-date breadth (reported, drives hurdle translation) | FM 73; Petersen 09 |
| Fama-MacBeth | One per-date coefficient | Median cross-section n per date | FM 73 |
| Long-short / tercile | One portfolio return per rebalance period | Leg-level stats | standard |
| Event studies | One event (BMP + block bootstrap as designed in docs/event-backtest-layer) | Per-day CARs display-only | BMP 91; M-S 00 |

Note: the per-date IC / FM / L-S series at 3m/6m/12m horizons sampled monthly are themselves
overlapping (VIF ~= 3 / 6 / 12); the *date series* gets the HAC treatment of Section 4.

### 1.5 Why the companion episode check is mandatory

Costs accrue per round trip. A calendar-time series nets out turnover invisibly. So the
economic test has two legs: (i) calendar-time net Sharpe >= SR*; (ii) mean net return per
episode >= cost-based hurdle (Section 5). Both must pass. Hit rate, profit factor, per-trade
quantiles remain diagnostics.

---

## 2. What N_req means

### 2.1 Derivation

For a stationary weakly dependent unit series x_1..x_N with true mean mu, the CLT gives
sqrt(N)*(xbar - mu) -> Normal(0, sigma_LR^2), sigma_LR^2 = sigma^2 * VIF. A one-sided
level-alpha test rejects when xbar > z_{1-a} * sigma_LR / sqrt(N). Under the alternative
mu = delta:

    Power = Phi( delta * sqrt(N) / sigma_LR  -  z_{1-a} )

Solving Power >= 1-b:

    N_req = ( (z_{1-a} + z_{1-b}) * sigma_LR / delta )^2

### 2.2 The convention **[DECISION D2 — recommended: Convention R]**

N_req counts **raw observations of the unit series at its own sampling frequency**, with all
dependence absorbed in sigma_LR ("Convention R"). The algebraically identical alternative
("Convention E") deflates N to N_eff = N/VIF and uses iid sigma. Proof of equivalence:
substitute and the VIF cancels. The conventions must never be mixed (double-counts or
zero-counts the dependence penalty). Convention R is operationally safer: Newey-West outputs
sigma_LR directly; the block bootstrap natively reproduces it; N stays an integer count of
real things. N_eff is kept as a display-only transform.

### 2.3 Calendar translation

- Calendar series: years_needed = (N_req - N) / periods_per_year.
- Date series (IC/FM): additional evaluation dates; at monthly cadence, /12 for years.
- Episode series: additional episodes / historical episode arrival rate (rate itself
  estimated -> gets an uncertainty band).

---

## 3. VIF vs N_eff; negative autocorrelation

- N_eff = N/VIF **can exceed N** under negative autocorrelation (VIF < 1). This is genuine
  information (mean-reverting errors cancel), so "N_eff <= N" is NOT a valid invariant.
  Valid invariants: VIF > 0; N_eff > 0; N_eff <= N *after* the gating floor below.
- **[DECISION D3 — recommended: floor VIF at 1 for gating, show uncapped in diagnostics.]**
  Rationale: Newey-West sigma_LR is biased downward in short samples (Andrews 1991); rho_k
  estimates have SE ~ 1/sqrt(N); and the loss is asymmetric (over-validation trades real
  money; under-validation waits for data). Alternatives considered: uncapped everywhere
  (systematically over-validates short series); adaptive floor with a robustness battery
  (more accurate for true mean-reverters, adds a new judgment boundary — revisit only if the
  uncapped diagnostic ever shows the floor binding on a real family).
- Presentation: VIF = sigma_LR^2/sigma^2 is the primary estimated quantity; N_eff = N/VIF the
  display transform; N_req always stated in raw units (Convention R).

---

## 4. Long-run variance estimation and HAC bandwidth

### 4.1 Status of the overlap floor L >= ceil(h/Delta) - 1

Exact only for the pure moving-sum component of dependence. It is a **floor, not a choice**:
volatility clustering and regime persistence extend correlation beyond the overlap length.

### 4.2 Recommended default

    L_default = max( ceil(h/Delta) - 1 ,  L_auto )

with L_auto = Newey-West automatic bandwidth floor(4*(N/100)^(2/9)) (already implemented in
`research/stats/ic.py:_newey_west_var`) or the Andrews (1991) AR(1) plug-in. Bartlett kernel
(as implemented) guarantees a positive semi-definite estimate.

### 4.3 Sensitivity and small samples

- Report sigma_LR at L in { overlap floor, L_default, 2*L_default }. Instability across this
  grid feeds the reliability score (Section 11), not an arbitrary N cutoff.
- Small-sample size distortion of HAC t-tests is real (Kiefer-Vogelsang fixed-b asymptotics
  document it). Rather than fixed-b critical values, the **block bootstrap is the primary
  small-sample device** (Section 8); the analytic HAC number is the cross-check.
- Estimability precondition: the number of effectively independent blocks N/L must be large
  enough to estimate a variance at all (Section 11.2). When violated -> state
  `insufficient_to_estimate`, never a numeric verdict.

### 4.4 Per-family defaults

| Series | Sampling Delta | h (overlap) | Floor | Default L |
|---|---|---|---|---|
| Edge calendar series (active daily) | 1 bar | none (MTM) | 0 | L_auto |
| Edge episodes | per episode | none | 0 | 1-2 (residual clustering) |
| IC / FM / L-S date series, 3m/6m/12m | monthly | 3/6/12 months | 2 / 5 / 11 | max(floor, L_auto) |
| Weekly portfolio MTM | weekly | none | 0 | L_auto |
| S/R WFO trades | per trade | none (sequential) | 0 | L_auto over trade sequence |
| Stat-arb daily P&L | daily | none | 0 | L_auto |

---

## 5. The economic hurdle

### 5.1 What SR* = 0.5 means (chosen by user; application details below)

Annualized net Sharpe 0.5 <=> annual mean = 0.5 * annual sigma. Implications: a truly-SR-0.5
strategy has P(losing year) = Phi(-0.5) ~= 31%; P(losing 5-year stretch) ~= 13%; its 5-year
t-stat averages 0.5*sqrt(5) ~= 1.12 — i.e., even a genuinely economic strategy rarely "proves"
itself quickly. This is the honest cost of the hurdle, not an argument against it.

### 5.2 Sensitivity of required history to the hurdle (the brutal arithmetic)

To detect SR = SR* against H0: SR <= 0 (one-sided 5%, 80% power), required track length in
years ~= ((1.645+0.842)/SR*)^2:

| SR* | Years required |
|---|---|
| 0.3 | ~69 |
| 0.5 | ~25 |
| 0.75 | ~11 |
| 1.0 | ~6.2 |

Equivalently, the MDE with T years of history is MDE_SR ~= 2.487/sqrt(T): 5 years of data can
only detect true Sharpe ~1.1; 10 years ~0.79. **Consequence: with Moroccan history depths,
signals whose true edge is merely "borderline economic" (SR ~= 0.5) are formally
unvalidatable; only strong edges (SR >~ 1) are within reach.** The framework must say this
plainly (the `underpowered` state) rather than pretend otherwise. This is the single most
important output of the audit.

### 5.3 Application details

- Applied **net of costs** (repo cost conventions: 25-33 bps per side, already modeled).
- **[DECISION D4]** Test design at the hurdle. Two coherent designs:
  (i) *Standard*: test H0: effect <= 0; require significance AND point estimate >= delta AND
      power-at-delta >= 0.8. Detects existence; economic size checked on the estimate.
  (ii) *Proof-of-hurdle*: test H0: SR <= SR* (PSR against SR* as benchmark). Demands the data
      prove the strategy exceeds the hurdle — far more demanding (required T explodes as
      observed SR -> SR*).
  Recommended: (i) for gating; report the PSR against SR* from (ii) as a diagnostic
  ("probability the strategy beats the hurdle").
- Configurability: SR* is a config constant with per-family overrides, not a hardcode.
- Per-episode hurdle (companion check): mean net return per episode >= 1x round-trip cost
  (i.e., gross >= 2x costs), the cost-multiple translation of the anchor.

---

## 6. The IC / Fama-MacBeth hurdle

### 6.1 Critique of IC_min = SR* / sqrt(B * rebalances_per_year)

The fundamental law (Grinold-Kahn) assumes B *independent* bets. The raw stock count
overstates independent bets because of: the common MASI factor and sector blocks (cross-
sectional correlation); the same stocks repeating across consecutive rebalances with
autocorrelated signal values (turnover < 100% means consecutive bets are partly the same
bet); portfolio constraints (long-only tilts, size limits) reducing transfer; and correlation
among the signals themselves. Effective breadth corrections exist
(B_eff ~= B / (1 + (B-1)*rho_bar) from the Moulton logic, or eigenvalue-based diversification
counts), but rho_bar and the turnover adjustment are themselves estimated — the "corrected
fundamental law" stacks estimated corrections on an idealized formula.

### 6.2 Recommended definition **[DECISION D5]**

Make the **net long-short portfolio the primary economic test** for cross-sectional signals
(alternative 3 in the objection list), and demote IC/FM to *mechanism evidence*:

- Economic gate: net tercile/quintile L-S Sharpe >= SR* on the per-rebalance return series
  (this is exactly the machinery of `ic_study.tercile_backtest` /
  `cross_sectional.backtest_long_short`, evaluated under Section 2's power framework).
  The L-S portfolio automatically embodies the *actual* breadth, correlations, constraints,
  and turnover — no effective-breadth estimation needed.
- Statistical gate on IC/FM: HAC-significant mean per-date IC (and FM coefficient) with
  correct bandwidth — existence of predictive information, no standalone magnitude hurdle.
- Reporting only: the empirical IC <-> realized L-S Sharpe mapping measured in the panel
  (regression of realized per-period L-S return on lagged IC regime), giving an *empirical*
  IC_min for intuition. No look-ahead: the mapping is structural (how much Sharpe a unit of
  IC converts to in this universe), not a signal-selection device.
- Rejected alternatives: raw fundamental-law inversion (Section 6.1); pure historical
  simulation to set IC_min (selection-contaminated unless run on a frozen spec).

### 6.3 Fama-MacBeth units

Rank-standardize predictors to [-0.5, 0.5] (the repo already does this:
`sfc_diagnostics._rank_standardize`). The per-date coefficient is then "return spread from
worst-to-best rank exposure," directly comparable across predictors, robust to outliers in
9-70-name cross-sections (z-scoring is not). Hurdle: the coefficient magnitude whose implied
top-minus-bottom spread, net of costs, clears the L-S economic gate — i.e., derived from the
same single anchor, not set independently.

---

## 7. Sharpe-ratio methodology: which tool is primary

| Tool | What it does | Role here |
|---|---|---|
| HAC mean-return power (Sec. 2) | Power/N_req for the mean with dependence | **Primary analytic** |
| Stationary-bootstrap power (Sec. 8) | Same, with the actual distribution (skew, kurtosis, dependence) | **Primary simulation** |
| Lo (2002) SE(SR) | SR standard errors incl. autocorrelation-correct annualization | Reporting: CI on annualized SR |
| PSR (Bailey-Prado) | P(true SR > SR*) with skew/kurtosis correction | Diagnostic vs the hurdle (D4 design ii) |
| MinTRL | Required T given the **observed** SR-hat | Diagnostic ONLY — it conditions on the sample estimate, so it is not a power calculation (power uses delta, fixed a priori). Report it, never gate on it. |
| Deflated Sharpe (already in `robustness.py:94`) | Corrects the max-SR over m tried variants | Discovery-stage reporting (Sec. 9) |

Note on mean-vs-Sharpe testing: at per-period Sharpes this small (SR_ann 0.5 -> monthly
0.144, daily 0.031), the extra variance term in SR inference ((1 + SR^2/2)) is a <= 1%
correction, so the mean-return power analysis and the Sharpe power analysis coincide to first
order; the bootstrap captures the difference exactly anyway.

---

## 8. Bootstrap power design

Procedure (per unit series):
1. Demean the observed series; add delta (location-shift alternative — valid for mean-type
   hypotheses; preserves higher moments and dependence; the standard construction).
2. Resample with the **stationary bootstrap** (Politis-Romano geometric blocks), expected
   block length L_b = max( ceil(h/Delta), Politis-White (2004) automatic selection ).
   Sensitivity at 0.5x and 2x L_b feeds the reliability score. (Moving-block and circular
   variants are acceptable; stationary is least sensitive to block misspecification.
   Dependent-wild reserved for strongly heteroskedastic short series if needed.)
3. What is resampled preserves the cross-section by construction: calendar series -> blocks
   of periods; IC/FM -> blocks of *dates* (never resample stocks within a date); episodes ->
   blocks of consecutive episodes; portfolio -> blocks of weekly returns.
4. Apply the complete test (the same statistic + HAC as the analytic path) to each replicate;
   power(T) = rejection frequency at alpha; N_req = smallest T on a grid with power >= 0.8
   (0.9), with monotone smoothing of the power curve.
5. B = 2000 replicates (repo convention): MC error of a power estimate at 0.8 is
   sqrt(0.8*0.2/2000) ~= 0.9pp.
6. Uncertainty on N_req: the envelope over the (bandwidth x block length) sensitivity grid
   (a nested double bootstrap is disproportionate); reported as a range.
7. **Extrapolation cap [DECISION D6]**: simulating T beyond the observed history length
   fabricates regime coverage. Recommended cap: simulate up to 2x observed length; if
   N_req exceeds the cap, report "requirement beyond simulable range (> X)" — a warning
   state, not a number invented by extrapolation.

---

## 9. Multiple testing: discovery vs confirmatory

Clarification of what each procedure controls:
- Sidak/Bonferroni control **FWER** = P(any false positive among m tests).
- Benjamini-Hochberg controls **FDR** = expected fraction of false positives among
  *discoveries*. Its rejection threshold is data-dependent, so "power at the BH threshold"
  is not an a-priori quantity.
- Deflated Sharpe corrects the *point estimate* of the best of m variants (selection bias),
  not the error rate of a test.

### Recommended coherent policy **[DECISION D7]**

- **Discovery stage** (any signal produced by searching modes/horizons/thresholds/rules):
  BH-FDR at q = 0.10 within the pre-registered family (as the repo already does), Deflated
  Sharpe reported for best-of-family picks. **No validation claim is available at this
  stage, regardless of q-values.** Output = candidate list.
- **Confirmatory stage**: one frozen specification, tested on data that postdates (or was
  held out from) the search, at full alpha = 5% one-sided with power planned per Section 2.
  Only this stage can set `validated`.
- Power planning: discovery-stage power is reported as a bracket [power at Bonferroni
  alpha/m, power at raw alpha] — the truth lies between; full simulation of the selection
  process is reserved for the two families whose search is codified end-to-end (edge exit-
  ladder selection in `select_optimal_holding_period`; MASI rule search).
- m comes from the code, not from what is displayed: edge = |EDGE_SIGNAL_MODES| x exit
  candidates x horizons per symbol; events = 60 registered cells; MASI = atomic rules x
  combinations actually enumerated; factor screen = factors x horizons tested. The
  measurement phase counts these exactly.

This also matches the Harvey-Liu-Zhu (2016) diagnosis: grid-searched factors need a far
higher evidence bar (their t >= 3.0 heuristic) than pre-registered confirmations.

---

## 10. Hit rates and expectancy

- The proposed binomial power against p1 "implied by the observed win/loss asymmetry" is
  **partly circular**: the payoff ratio is estimated from the same sample, so the alternative
  hypothesis moves with the data.
- A binomial hit-rate test is meaningful only when the payoff structure is **pre-specified**
  (e.g., fixed take-profit/stop-loss symmetric brackets: then p > 0.5 <=> positive edge).
  None of the repo's strategies have fixed brackets; payoffs are market-determined.
- Therefore: primary evidence = mean net P&L on the Section-1 units (calendar / episode);
  hit rate with Wilson CI is retained as a **diagnostic** (and the current Wilson gate's
  independence assumption is invalid on overlapping bucket-days anyway — on episodes it is
  approximately valid); profit factor likewise diagnostic. Bootstrap of full trade outcomes
  (Section 8) is the inferential tool that uses the whole P&L distribution without
  circularity.

---

## 11. Small-sample reliability: no new arbitrary thresholds

### 11.1 Data-driven reliability battery (replaces "warn if N < 40")

A row's requirement estimate (N_req, MDE, power) is flagged unreliable in proportion to:
1. **N_req envelope width**: ratio of upper/lower N_req across the (HAC bandwidth x block
   length) sensitivity grid; flag if > 2.
2. **sigma_LR instability**: relative range across the bandwidth grid.
3. **Independent-block count**: N / L_b (see 11.2).
4. **Bootstrap MC error**: reported alongside power (0.9pp at B=2000).
5. **Subperiod stability**: sigma and mean sign across chronological halves.
6. **Moment estimability**: skew/kurtosis SEs (needed for PSR/MinTRL corrections) are
   O(sqrt(6/N)) and O(sqrt(24/N)); corrections are suppressed (not fabricated) when their
   SEs exceed the estimates.

### 11.2 Unavoidable computational floors (justified, not arbitrary)

- N >= 3 to compute a variance at all (undefined otherwise).
- N / L_b >= ~8 independent blocks to estimate a *long-run* variance: the variance of a
  variance estimate from k blocks scales as 1/k; below ~8 blocks the sigma_LR estimate's own
  CI spans a factor of >2, which makes every downstream number decorative. This is a
  precondition for estimation, not an evidence threshold — the state is
  `insufficient_to_estimate`, which claims nothing about the signal.

---

## 12. Validation state machine

Five orthogonal booleans, each defined on the primary unit series:
- `estimable`: preconditions 11.2 met.
- `significant`: one-sided HAC/bootstrap p <= alpha (confirmatory alpha, or FDR-q at
  discovery — but discovery cannot reach `validated` regardless, per Section 9).
- `powered`: power at delta >= 0.8.
- `economic`: point estimate >= delta (both legs where applicable: Sharpe >= SR* and episode
  expectancy >= cost hurdle).
- `robust`: reliability battery (11.1) passes and the non-overlapping / subperiod checks
  agree in sign.

States (precedence top to bottom):
1. `insufficient_to_estimate` — not estimable. No claim of any kind.
2. `underpowered` — estimable, not powered, not significant. **Explicitly not "no edge":**
   an underpowered non-rejection is absence of evidence. (Also entered when N_req is beyond
   the simulable range, D6.)
3. `underpowered_but_promising` — not powered, but significant and economic. Small-sample
   flag: significant results from underpowered designs overstate effects (winner's curse);
   promote to confirmatory tracking, do not validate.
4. `adequately_powered_no_edge` — powered and not significant. The only state entitled to
   say the edge is absent (at detectable size delta).
5. `statistically_supported_not_economic` — significant (powered or not) with point estimate
   < delta. Real but too small to trade.
6. `unstable` — passes 2-5's criteria for validation except `robust`.
7. `validated` — estimable AND significant AND powered AND economic AND robust AND
   confirmatory-stage (never straight from discovery).

---

## 13. Decisions requiring user judgment (with recommended defaults)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Primary observation unit for trade-based strategies | Calendar-time MTM series primary + mandatory episode cost-check; clusters where already correct (MASI); days+HAC demoted to weekly cross-check |
| D2 | N_req bookkeeping convention | Convention R (raw N + sigma_LR); N_eff display-only |
| D3 | Estimated VIF < 1 | Floor at 1 for gating; uncapped shown in diagnostics |
| D4 | Test design at the hurdle | Standard design (significance vs 0 + estimate >= delta + power at delta); PSR-vs-SR* reported as diagnostic |
| D5 | Cross-sectional economic test | Net L-S Sharpe primary; IC/FM significance as mechanism evidence; empirical IC<->Sharpe map reported, fundamental-law inversion dropped as a gate |
| D6 | Bootstrap extrapolation cap | 2x observed history; beyond -> warning state, no number |
| D7 | Discovery vs confirmatory | Discovery can never validate; confirmatory = frozen spec on untouched data at full alpha |

Already locked by user: SR* = 0.5 net; one-sided alpha = 5%; 80% power primary; all families;
report-only delivery.

---

## 14. Next step after methodology approval

Measurement phase (read-only against the live DB): per family x horizon, construct the
primary unit series, estimate sigma, VIF (bandwidth grid), N, N_eff, MDE, power at delta,
N_req (analytic + bootstrap with envelope), calendar translation, reliability battery, and
the multiple-testing family sizes m counted from code. Output: results table + per-row state
under Section 12. Then the threshold-replacement design doc (no code changes until separately
approved).
