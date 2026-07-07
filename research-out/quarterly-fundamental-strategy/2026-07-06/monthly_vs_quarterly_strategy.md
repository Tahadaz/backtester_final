# Monthly Six-Vintage vs. Quarterly Fixed-Stride Strategy (Phase 8-9)

Both use the **exact same underlying panel, same eligibility rules, same B/M signal, same price data, same 33bps cost assumption** — the only difference is rebalance cadence: six overlapping monthly vintages (existing engine) vs. a single portfolio replaced wholesale every 3rd monthly formation date, held until the next rebalance (`run_fixed_stride_backtest(..., stride_months=3)`, a direct generalization of the existing `run_semiannual_backtest`, now `stride_months`-parameterized and covered by a new passing test).

## Results (S1 B/M, invested period only, i.e. from 2022-03 onward)

| | Monthly six-vintage | Quarterly fixed-stride |
|---|---|---|
| Periods | 51 (monthly) | 17 (quarterly) |
| Cumulative return | +220% | +217% |
| CAGR | 31.5% | 31.1% |
| Annualized vol | 18.0% | **25.5%** |
| **Sharpe** | **1.62** | **1.21** |
| Max drawdown | -13.9% | -10.5% |
| Avg turnover (per rebalance) | 3.5% | 13.4% |

## Interpretation

**Cumulative return and CAGR are essentially identical** — expected, since (per `quarterly_bm_comparison.md`/`information_refresh_analysis.md`) both designs are drawing on materially the same fundamental information. **Sharpe is meaningfully worse under the quarterly design (1.21 vs 1.62)**, driven by higher realized volatility (25.5% vs 18.0%) — the monthly six-vintage structure smooths returns by staggering six overlapping entry cohorts, which diversifies away idiosyncratic single-rebalance-date timing risk that a single-portfolio quarterly rebalance is fully exposed to. Turnover per rebalance is also nearly 4x higher for the quarterly design (13.4% vs 3.5%), though since it rebalances 1/3 as often, annualized turnover is roughly comparable.

**Given the underlying fundamental information content is nearly identical between the two designs (Phase 4/6), quarterly rebalancing does not unlock new information — it only removes the monthly vintage-smoothing diversification benefit, at the cost of higher realized volatility and a materially lower Sharpe ratio, for no offsetting return improvement.**
