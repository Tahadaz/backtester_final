# Cross-Asset Time-Series Momentum — Study Result

**Run date:** 2026-08-17 · **Pre-registration:** `docs/global-desk/02-tsmom-preregistration.md`
**Sample:** 2000-01-03 → 2026-08-17, 39 instruments, 6,945 bars, 27.6 years
**Data:** free proxies only. **No Bloomberg** — entitlement discovery has not run.

## Verdict: PROMISING, NOT DEPLOYABLE (7 of 8 gates)

Per the verdict rule fixed in advance: 6-7 gates passing = *promising, not
deployable*. Report what failed and investigate.

| Gate | Criterion | Result | |
|---|---|---|---|
| G-1 | Net Sharpe > 0.30 | **0.699** | PASS |
| G-2 | DSR > 0.95 | **0.967** | PASS (qualified — see below) |
| G-3 | OOS return > 0 **and** ≥60% of windows positive | +96.1%, but **59%** (13/22) | **FAIL** |
| G-4 | Net Sharpe > 0 at 3× costs | **0.555** | PASS |
| G-5 | Leave-one-out net Sharpe > 0.20 | worst 0.616 (excl. TU) | PASS |
| G-6 | ≥55% of years positive | **70%** (19/27) | PASS |
| G-7 | Bootstrap 95% lower bound > 0 | [+0.000094, +0.000395] | PASS |
| G-8 | Net Sharpe < 1.5 (sanity ceiling) | 0.699 | PASS |

**G-3 missed by a single window.** 13 of 22 is 59.1% against a 60% threshold —
one more positive window would have passed it. The gate was fixed in advance and
has not been moved. The failure is real but marginal, and the direction of the
evidence (+96% cumulative OOS) is favourable.

**G-2 is a qualified pass.** It passes only after a bug fix made *after* it
first failed. Full disclosure in the pre-registration, Amendment 2.

## Headline numbers

| | |
|---|---|
| Net Sharpe (after pessimistic costs) | **0.699** |
| Gross Sharpe | 0.771 |
| Net CAGR | 6.03% |
| Realized vol | 8.94% (target 10%) |
| **Max drawdown** | **−30.4%** |
| **Longest drawdown** | **1,637 days (~6.5 years)** |
| Annual turnover | 16.5× |
| Cost drag | 0.64%/yr |

This sits squarely inside the 0.3-0.7 net Sharpe band pre-registered as the
realistic expectation, and below the published gross benchmark of 0.8-1.2 — the
right side of the sanity ceiling. **The pipeline reproduces the known premium
rather than inventing a new one, which was the point.**

The lookback ordering also reproduces the literature without being fitted to it:

| Lookback | 1m | 3m | 6m | 12m |
|---|---|---|---|---|
| Net Sharpe | −0.031 | 0.223 | 0.564 | **0.699** |

## Where the return comes from

| Sleeve | Net Sharpe |
|---|---|
| Rates | 0.574 |
| Equity index | 0.552 |
| Commodity | 0.483 |
| FX | 0.183 |
| **Credit** | **−0.398** |

**Credit is a detractor and should probably be cut.** The four credit names are
ETF proxies (LQD/HYG/IEAC/IHYG) carrying mixed duration *and* spread exposure —
the registry flags this. Trend on a mixed-exposure proxy is not trend on credit.
This is the sleeve most likely to change under real Bloomberg CDX/iTraxx data,
and it should not be traded on the current evidence.

No single instrument carries the result: the worst leave-one-out exclusion (TU)
still yields 0.616 against 0.699 for the full set.

## Trade statistics — read these before the Sharpe

Full tables per variant, per sleeve and per instrument: **`strategy_results.md`**.

| Variant | Exp. return p.a. | Sharpe | Win rate | Payoff | Profit factor | Trades | Avg bars held |
|---|---|---|---|---|---|---|---|
| TSMOM 1m | −0.29% | −0.031 | 37.5% | 1.76 | 1.06 | 10,764 | 23 |
| TSMOM 3m | 2.02% | 0.223 | 36.9% | 1.98 | 1.16 | 6,292 | 39 |
| TSMOM 6m | 5.07% | 0.564 | 36.1% | 2.50 | 1.41 | 4,056 | 60 |
| **TSMOM 12m** | **6.25%** | **0.699** | **37.2%** | **2.86** | **1.70** | **2,718** | **88** |

**You lose roughly two trades in three and still make money.** A 37% win rate
with a 2.86 payoff ratio is the textbook trend-following signature — many small
losses cut quickly, a few large winners held. It is also the reason these
programs are psychologically hard to run: the modal outcome of any single trade
is a small loss.

Note what improves as the lookback lengthens: the win rate is flat (~37%) across
all four variants, while the **payoff ratio climbs from 1.76 to 2.86**. The edge
is not in being right more often — it is entirely in the asymmetry of the
winners. Any change that truncates large winners destroys this strategy.

| Sleeve | Exp. return p.a. | Sharpe | Win rate | Payoff | Profit factor |
|---|---|---|---|---|---|
| Rates (4) | 5.83% | 0.574 | 37.6% | 4.51 | 2.71 |
| Equity index (8) | 5.60% | 0.552 | 39.7% | 3.69 | 2.43 |
| Commodity (14) | 4.82% | 0.483 | 35.9% | 2.75 | 1.54 |
| FX (9) | 1.90% | 0.183 | 38.1% | 2.13 | 1.31 |
| **Credit (4)** | **−4.17%** | **−0.398** | **34.1%** | **1.64** | **0.85** |

Credit's profit factor below 1.0 means it lost more than it made, gross of
everything — and its −70.8% drawdown is by far the worst of any sleeve. Three of
the four credit names are individually negative (`CDX_HY`, `ITRAXX_XOVER`,
`CDX_IG`). **Cut it, or rebuild it on real CDX/iTraxx rather than duration-
contaminated ETFs.**

Eight of 39 instruments lost money; per-instrument P&L reconciles exactly to the
portfolio total (1.9008 in risk units).

## The drawdown is the real obstacle to deployment

−30.4% peak-to-trough with **6.5 years underwater** is the number that decides
whether this is desk-viable, not the Sharpe. The losing years cluster exactly
where the literature says they should — 2009, 2011-2012, 2016-2019, 2023 — the
well-documented post-crisis trend drought. Consistency with the known failure
mode is evidence the replication is faithful; it is also a warning that a desk
running this must be prepared to sit through years of underperformance without
switching it off, which is where most systematic programs actually die.

Signature years behaved correctly: **2008 +11.9%**, **2022 +23.2%** — trend's two
famous years. An earlier version of this study showed 2008 at −6.5%, which is
what exposed the bug described below.

## Two bugs found and fixed (both would have invalidated the result)

**1. Calendar misalignment silently zeroed 30 of 39 instruments.** Instruments
trade on different holiday calendars, so a union index leaves a NaN in every
column wherever some other market was open. `rolling(252, min_periods=252)` then
never fills, and the signal is NaN forever. Thirty instruments contributed
nothing while still appearing in the panel — and the study reported a Sharpe
anyway. Fixed by aligning on a common business-day calendar with disclosed
forward-fill counts, bounded to each instrument's own life. The study runner now
**aborts** if any instrument fails to produce a live signal.

**2. `deflated_sharpe_ratio` returned 0.0 for every input, repo-wide.** A units
mismatch: the Harvey-Liu-Zhu expected-maximum term (dimensionless, ~1.05) was
used directly as a *per-period* Sharpe benchmark. A synthetic strategy with an
annualized Sharpe of 4.71 also scored 0.0. Fixed in
`core/quant_core/research/stats/robustness.py`. **This affects any past result in
this repo that reported a DSR** — including the cross-asset `validation.py`
path. Those numbers were not conservative; they were empty.

Also fixed: `price_returns` produced −306% then +127% across WTI's −$37.63
settlement on 2020-04-20, corrupting CL's vol estimate and its 12-month signal
for a year afterward. Non-positive price transitions are now marked missing and
disclosed.

## Limitations — why this is not a deployment decision

Pre-registered, and all still true:

1. **Commodity series are unadjusted front-month prices**, so every roll injects a spurious return. This is the single largest data defect and is exactly what Bloomberg per-contract chains would fix.
2. **FX excludes carry** — trend only, not the full premium. FX's weak 0.183 partly reflects this.
3. **Rates use duration-approximated returns from revised FRED yields**, so not strictly point-in-time.
4. **Eight instruments are missing entirely** — Bund, Bobl, Schatz, Buxl, Gilt, JGB, BTP, OAT have no free source. The rates sleeve is US-only, which is a material gap for a global desk given rates was the strongest sleeve.
5. **Instrument selection has hindsight** — these are instruments liquid today.
6. **No capacity modelling.** Not yet answered.
7. **A passing result is not permission to trade.** It means the pipeline reproduces a known premium and deserves better data.

## What would change the verdict

| Action | Why it matters |
|---|---|
| Run Bloomberg entitlement discovery | Unblocks per-contract commodity chains, real credit indices, and the 8 missing sovereigns |
| Re-run on real chains + FX forwards | Removes defects 1, 2 and 4 — the three largest |
| Drop or rebuild the credit sleeve | It is currently a detractor built on mixed-exposure proxies |
| Add capacity analysis | Required by invariant 9 before any sizing conversation |
| Paper-track live vs backtest | Invariant 10; the only real defence against a subtly broken backtest |

Reproduce with:

```bash
python tools/global_desk/ingest_free_panel.py
python tools/global_desk/run_tsmom_study.py
```
