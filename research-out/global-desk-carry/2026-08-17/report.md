# Cross-Asset Carry — Study Result

**Run date:** 2026-08-17 · **Pre-registration:** `docs/global-desk/03-carry-preregistration.md`
**Sample:** 2000-2026, **13 instruments** (9 G10 FX + 4 US rates), 6,946 bars
**Data:** free only. No commodity carry (needs a term structure), no Bloomberg.

## Verdict: REJECTED (3 of 9 gates)

| Gate | Criterion | Result | |
|---|---|---|---|
| C-1 | Net Sharpe > 0.20 | **−0.128** | FAIL |
| C-2 | DSR > 0.95 | 0.179 | FAIL |
| C-3 | OOS > 0 and ≥55% windows | −57.2%, 32% of 22 | FAIL |
| C-4 | Sharpe > 0 at 3× costs | −0.176 | FAIL |
| C-5 | Leave-one-out > 0.10 | worst −0.196 (US) | FAIL |
| C-6 | ≥50% years positive | 56% | PASS |
| C-7 | Bootstrap lower bound > 0 | [−0.000212, +0.000105] | FAIL |
| C-8 | Sharpe < 1.5 (sanity) | −0.128 | PASS |
| C-9 | **Corr with TSMOM < 0.50** | **0.098** | **PASS** |

Net Sharpe −0.128 · CAGR −1.79% · vol 10.1% · **max drawdown −62.3%**

All three signal variants are negative (sign −0.128, smoothed −0.124, ranked
−0.221). Gross Sharpe is **−0.104**, so this is not a cost problem — the signal
itself is negative before a single basis point is charged.

## Do not yet read this as "carry does not work"

Published diversified carry Sharpes are ~0.7-1.0 gross. **This study is roughly
0.8 Sharpe below the literature, which is the same magnitude of divergence that
turned out to be a bug in the TSMOM study** — where an implausible result was
traced to calendar misalignment silently zeroing 30 of 39 instruments, not to an
absent premium. The discipline that applied there applies here: a result far
outside published values is evidence about the implementation until proven
otherwise.

Specific things that warrant checking before this verdict is treated as a
finding about markets:

1. **A −62% drawdown on a 10% vol target is structurally implausible** for a diversified carry book and is the loudest signal that something is wrong.
2. **FX carry sign convention.** Long `EURUSD` earns `r_EUR − r_USD`; long `USDJPY` earns `r_USD − r_JPY`. The registry's `base_ccy`/`quote_ccy` drive this and the unit tests cover the arithmetic, but the mapping from *quoted pair* to *long position* is worth re-deriving against the actual yfinance quote convention for the inverted pairs (`JPY=X`, `CHF=X`, `CAD=X`, `NOK=X`, `SEK=X`).
3. **Rates curve carry was positive nearly throughout** 2000-2026 (an upward-sloping curve most of the sample), which means the sleeve was near-permanently long duration — a position that *made* money over that period. A negative result there specifically does not reconcile.
4. **The two-month publication lag** on monthly rates is conservative but may be misaligning the carry step against the month boundary.

## What did work

**C-9 passed convincingly: correlation with TSMOM is 0.098.** Whatever this
sleeve is measuring, it is close to orthogonal to trend — which is the property
that would make carry worth having in the book. That is the one result here
worth keeping.

## Data defect found in shipped code

`services/api/app/services/cross_asset/datasources.py:23` (`FRED_RATE_SERIES`,
used by the **shipped** FX vertical) points at dead or stale series:

| Currency | Wired series | Status probed 2026-08-17 |
|---|---|---|
| GBP | `IUDERB6` | **404 — does not exist** |
| SEK | `IRSTCI01SEM156N` | ends **2020-10** (~6 years stale) |
| NZD | `IRSTCI01NZM156N` | ends 2024-12 |
| CHF | `IRSTCI01CHM156N` | ends 2024-03 |

This study used `IR3TIB01*` 3-month interbank rates instead (monthly, all ten
currencies, current to 2026). **The shipped FX carry vertical is still on the
broken map** and should be repointed independently of this study's outcome.

## Limitations (pre-registered, unchanged)

1. **No commodity carry** — the largest and most-cited carry sleeve is absent, because free sources serve only the front contract. This is the single biggest Bloomberg unlock for this strategy.
2. Monthly, revised interbank rates stand in for tradable forward points; cross-currency basis is not captured, and it moved violently in 2008/2011/2020.
3. US-only rates curve — one country, one curve shape.
4. 13 instruments is a small cross-section; confidence intervals are wide throughout.

Reproduce with:

```bash
python tools/global_desk/ingest_free_panel.py
python tools/global_desk/ingest_rates.py
python tools/global_desk/run_carry_study.py
```
