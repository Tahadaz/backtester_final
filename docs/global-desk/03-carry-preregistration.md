# Pre-Registration — Cross-Asset Carry

**Written 2026-08-17, BEFORE any carry backtest was run.** Committed first so the
gates cannot be adjusted to fit the result.

**Study question:** does a carry sleeve — long high-yielding, short low-yielding
— survive honest costs and out-of-sample testing, and does it diversify the
already-tested TSMOM sleeve?

**This is a replication.** Carry is as documented as trend (Koijen, Moskowitz,
Pedersen & Vrugt, *Carry*, JFE 2018). Published diversified carry Sharpes run
~0.7-1.0 gross over long samples. **Expected realistic net Sharpe here: 0.2-0.6**,
lower than the literature because the universe is smaller and the rate data is
coarse (below).

---

## 1. What can and cannot be built on free data

| Sleeve | Free? | Carry definition |
|---|---|---|
| **FX carry** (9 G10 pairs) | ✅ | `r_base − r_quote`, 3-month interbank rates |
| **Rates curve carry** (4 US tenors) | ✅ | `(y_T − financing) + roll-down along the curve` |
| **Commodity curve carry** | ❌ **blocked** | Needs the futures term structure (front vs deferred). yfinance serves only the front contract. |
| **Equity index carry** | ❌ skipped | Dividend yield minus financing; no reliable free index dividend series. |

**Commodity curve carry is the single largest thing Bloomberg unlocks for this
strategy**, and it is deliberately absent rather than approximated. There is no
honest free proxy for a term structure.

Universe is therefore **13 instruments** versus TSMOM's 39. Statistical power is
correspondingly lower and the gates below account for that.

## 2. Rate data — and a defect found in shipped code

`services/api/app/services/cross_asset/datasources.py:23` (`FRED_RATE_SERIES`,
used by the shipped FX vertical) points at series that are dead or stale:

| Currency | Wired series | Status (probed 2026-08-17) |
|---|---|---|
| GBP | `IUDERB6` | **404 — does not exist** |
| SEK | `IRSTCI01SEM156N` | ends **2020-10** (~6 years stale) |
| NZD | `IRSTCI01NZM156N` | ends 2024-12 |
| CHF | `IRSTCI01CHM156N` | ends 2024-03 |

This study uses `IR3TIB01*` 3-month interbank rates instead — monthly, all ten
currencies, current through 2026. Fixing the shipped map is tracked separately;
this document only records that the two paths now differ and why.

**PIT treatment of monthly rates.** OECD/FRED monthly series are published with a
lag and are subsequently revised. Using the observation dated month *M* during
month *M* is look-ahead. Rates are therefore **lagged two months** before use, and
forward-filled to daily. This is deliberately conservative; carry moves slowly
enough that the cost is small.

## 3. Method (fixed in advance)

Identical portfolio machinery to the TSMOM study, so the two are comparable:
vol-scaled to 10% per instrument, equal risk weight, portfolio scaled to 10%
annualized, weekly rebalance with a 10% no-trade band, one-bar execution lag,
same pessimistic costs (FX 1.5bps, rates 2bps per side on `|Δposition|`).

**Only the signal differs:**

- **FX:** `carry_i = r_base − r_quote` (annualized decimals), signal = `sign(carry)`, lagged one bar.
- **Rates:** `expected_carry_T = (y_T − financing) + D_T × (y_T − y_{T−1y}) `, where `y_{T−1y}` is linearly interpolated on the curve {3m, 1y, 2y, 5y, 10y, 30y} and financing is `DGS3MO`. Signal = `sign(expected_carry)`, lagged one bar.

**No parameter tuning.** Carry has no lookback to fit. The only variant axis is
the signal form, and exactly **three** are run for the deflated-Sharpe variant
count, all reported: `sign(carry)`, `sign(carry)` with a 21-day smoothing of the
carry input, and rank-demeaned carry (cross-sectional within sleeve).

## 4. Acceptance gates — pre-registered

Thresholds are **lower than the TSMOM study's** where power is the binding
constraint (13 instruments, and FX carry is known to be crisis-fragile), and
unchanged where they encode correctness rather than performance.

| # | Gate | Threshold |
|---|---|---|
| **C-1** | Net Sharpe, full sample, after pessimistic costs | **> 0.20** |
| **C-2** | Deflated Sharpe Ratio, honest variant count (3) | **> 0.95** |
| **C-3** | Walk-forward OOS net return **> 0** and OOS Sharpe > 0 in **≥ 55%** of windows | |
| **C-4** | Net Sharpe > 0 at **3×** declared costs | |
| **C-5** | Leave-one-instrument-out: net Sharpe stays **> 0.10** for every exclusion | |
| **C-6** | Positive net return in **≥ 50%** of calendar years | |
| **C-7** | 95% stationary-bootstrap lower bound on mean net return **> 0** | |
| **C-8** | Sanity ceiling: net Sharpe **< 1.5** | |
| **C-9** | **Diversification:** correlation of daily net returns with the TSMOM sleeve **< 0.50** | |

**C-9 is the gate that matters most.** A carry sleeve that merely tracks trend
adds nothing to a book that already has trend. Carry and trend are documented as
weakly correlated — if that does not reproduce here, the sleeve fails its actual
purpose regardless of standalone Sharpe.

**Verdict rule, fixed now:**

- **All 9 pass** → *Provisionally validated*, pending Bloomberg-grade data.
- **7-8 pass** → *Promising, not deployable.*
- **≤ 6 pass** → *Rejected* in this form.

No gate may be revised after seeing results. Any correction found necessary
mid-study is disclosed as a dated amendment stating whether it was made before or
after a gate outcome was observed.

## 5. Known limitations, stated in advance

1. **No commodity carry** — the largest and most-cited carry sleeve is absent entirely.
2. **Monthly, revised interbank rates** stand in for tradable forward points. Real FX carry is earned through forwards, whose points embed cross-currency basis that interbank rates do not capture. In stressed periods (2008, 2011, 2020) basis moved violently and this proxy will understate the true cost.
3. **US-only rates curve** — no Bund, Gilt, JGB or BTP, so the curve sleeve is one country and one curve shape.
4. **Carry's known failure mode is crash risk.** The strategy earns steadily and loses violently (2008). Sharpe systematically flatters it; C-8 and the drawdown reporting exist to keep that visible.
5. **13 instruments is a small cross-section.** Expect wider confidence intervals than the TSMOM study throughout.
