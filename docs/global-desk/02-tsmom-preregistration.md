# Pre-Registration — Cross-Asset Time-Series Momentum

**Written 2026-08-17, BEFORE any global backtest was run.** Committed first so the
acceptance criteria cannot be adjusted to fit the result.

**Study question:** does a diversified cross-asset time-series momentum sleeve
survive honest costs and out-of-sample testing well enough to be considered for
desk deployment?

**This is a replication, not a discovery.** TSMOM is one of the most documented
premia in finance (Moskowitz, Ooi & Pedersen 2012; the managed-futures industry
is built on it). The purpose is to find out whether *this pipeline* reproduces it
faithfully on clean data. A result far *above* published values is evidence of a
bug, not of skill.

---

## 1. Hypothesis

The sign of an instrument's trailing 12-month excess return predicts the sign of
its next-period excess return, and a vol-targeted portfolio of such positions
across asset classes earns a positive risk-adjusted return after costs.

**Published benchmark:** gross Sharpe ~0.8-1.2 for a diversified managed-futures
TSMOM portfolio over long samples, degrading materially post-2010 (widely
documented; the 2010-2019 decade was poor for trend). **Expected realistic net
Sharpe for this study: 0.3-0.7.**

---

## 2. Universe and data (declared in advance)

Free-data proxies from the W1 security master. **Bloomberg is not used** — the
entitlement discovery run has not happened, so this study is deliberately
scoped to what is reproducible without a terminal.

| Class | N | Instrument | Return construction |
|---|---|---|---|
| FX | 9 | yfinance spot | Spot log return. **Carry excluded** — free policy rates are not tradable forward points. |
| Rates | 4 | FRED `DGS2/5/10/30` | Duration-approximated total return: `y[t-1]/252 - D·Δy[t]`. |
| Commodities | 14 | yfinance `=F` continuous | Back-adjusted continuous return. |
| Equity index | 8 | yfinance index/future | Price return. |
| Credit | 4 | `LQD/HYG/IEAC/IHYG` | ETF total return; mixed duration+spread exposure. |

**Sample:** 2000-01-01 to present, subject to per-instrument `history_start` from
the registry. Includes 2008 and the 2022 rates shock, per decision G11.

**Instruments failing data-quality checks are dropped and named in the report.**

---

## 3. Method (fixed in advance)

- **Signal:** `sign(trailing 12-month excess return)`, lagged one bar.
- **Vol scaling:** per-instrument, target 10% annualized, EWMA halflife 60 days, lagged one bar.
- **Portfolio:** equal-weight across instruments, then scaled to 10% annualized portfolio vol using a trailing estimate. No optimization, no instrument selection.
- **Rebalance:** weekly, with a no-trade band (decision G2).
- **Execution lag:** one full bar between signal and fill.
- **Costs (pessimistic, per side, on `|Δposition|`):** FX 1.5bps, rates 2bps, equity index 2bps, commodities 5bps, credit ETFs 10bps. Roughly 2-4× typical institutional fills, deliberately.

**No parameter tuning.** 12 months and 10% vol are the published defaults. The
lookback grid (1/3/6/12) is run **only** for the deflated-Sharpe variant count
and reported in full, not to select a winner.

---

## 4. Acceptance gates — pre-registered

| # | Gate | Threshold |
|---|---|---|
| **G-1** | Net Sharpe, full sample, after pessimistic costs | **> 0.30** |
| **G-2** | Deflated Sharpe Ratio with honest variant count | **> 0.95** (amended — see below) |
| **G-3** | Walk-forward OOS net return | **> 0**, and OOS Sharpe > 0 in **≥ 60%** of windows |
| **G-4** | Cost robustness | Net Sharpe stays **> 0** at **3× declared costs** |
| **G-5** | Not one-instrument-driven | Leave-one-instrument-out: net Sharpe stays **> 0.20** for every exclusion |
| **G-6** | Not one-regime-driven | Positive net return in **≥ 55%** of calendar years |
| **G-7** | Bootstrap CI on mean net return | 95% stationary-bootstrap lower bound **> 0** |
| **G-8** | Sanity ceiling | Net Sharpe **< 1.5**. Above this, presume a bug and investigate before believing it. |

**Verdict rule, fixed now:**

- **All 8 gates pass** → *Provisionally validated.* Proceed to Bloomberg-grade data and paper tracking. **Not** cleared for capital on free-proxy data alone.
- **6-7 pass** → *Promising, not deployable.* Report which failed; investigate.
- **≤ 5 pass** → *Rejected* for desk use in this form.

No gate may be revised after seeing results. If a gate proves badly specified,
that is recorded as a limitation and the study is re-run as a *new*
pre-registration.

### Amendment 1 — 2026-08-17, before any backtest was run

**G-2 was mis-specified as "DSR > 0".** On reading the implementation
(`core/quant_core/research/stats/robustness.py:94`), `deflated_sharpe_ratio`
returns a *probability* in [0,1] (a PSR against the Harvey-Liu-Zhu expected
maximum Sharpe), not a z-score. "> 0" is therefore satisfied by any input and
tests nothing.

Corrected to the conventional significance bar, **DSR > 0.95** — i.e. ≥95%
probability the observed Sharpe exceeds what the best of `n_variants` random
trials would produce. This amendment is made **before running the study**; no
result has been observed. It makes the gate materially *harder*, not easier.

### Amendment 2 — 2026-08-17, AFTER G-2 failed. Read this critically.

**Timing disclosed up front: this change was made after the first run scored
G-2 as DSR = 0.0000 and failed.** Adjusting a computation after seeing a gate
fail is precisely the behaviour pre-registration exists to prevent, so the
justification has to stand on its own, independent of whether it helps.

**The defect.** `deflated_sharpe_ratio` passed the Harvey-Liu-Zhu expected-maximum
term (~1.05 for N=4) directly into `probabilistic_sharpe_ratio` as the benchmark.
But that term is the expected maximum of N *standard normal* draws — a
dimensionless multiplier — while `probabilistic_sharpe_ratio` operates on
**per-period** Sharpes, where a daily Sharpe of 0.044 corresponds to an
annualized 0.70. The function was therefore asking whether a daily Sharpe
exceeded 1.05, which nothing can.

**Independent proof it was broken, not merely unhelpful:** a synthetic strategy
with an annualized Sharpe of **4.71** also scored exactly 0.0. The function
returned 0.0 for every input it has ever been given, in this study and
everywhere else in the repo that calls it.

**The correction** applies the Bailey & López de Prado definition properly:
`SR* = sigma_SR × E[max of N standard normals]`, where `sigma_SR` is the
dispersion of the trial Sharpes (here the four lookback variants), with both
sides in per-period units. Fixed in
`core/quant_core/research/stats/robustness.py`, with regression tests in
`core/tests/test_ca_tsmom_study.py` asserting it discriminates between a good
and a worthless strategy and penalizes larger variant counts. The full core
suite (1867 tests) passes unchanged — nothing depended on the broken value.

**Effect on this study:** G-2 moves from FAIL (0.0000) to PASS (0.9666), taking
the verdict from 6/8 to 7/8. The verdict band is unchanged: both land in
"PROMISING, NOT DEPLOYABLE". **A gate that passes only on a post-hoc corrected
statistic is reported as a qualified pass, not a clean one.**

---

## 5. Known limitations, stated in advance

1. **Back-adjusted continuous commodity series are not tradable P&L.** They approximate a rolled position but rewrite history at each roll. This is the single largest data defect and is exactly what Bloomberg per-contract chains (G7) would fix.
2. **FX excludes carry**, so this is trend only, not the full FX premium.
3. **Rates use duration-approximated returns from revised FRED yields** — FRED restates series, so this is not strictly point-in-time.
4. **Instrument selection has hindsight.** The universe is instruments liquid *today*. Genuinely dead contracts are absent. For major futures this bias is small but non-zero.
5. **No capacity modelling in v1.** Reported qualitatively.
6. **A passing result is not permission to trade.** It means the pipeline reproduces a known premium and deserves better data.
