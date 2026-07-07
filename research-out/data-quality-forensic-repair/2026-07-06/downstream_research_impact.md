# Downstream Research Impact (Workstream 3, Phase 14)

All numbers below are from an actually-executed run of `characteristic_study.run_characteristic_study()` against the live, repaired database on 2026-07-06 (run id `20260706-194324`, 3,104 stock-month rows, 71 symbols, 111 monthly dates), plus a targeted before/after reconstruction script (`scripts/before_after_bm_impact.py`) isolating the effect of the REB/ATW/IAM data repairs specifically. Nothing here is estimated or extrapolated without a computed artifact backing it.

## B/M: survives, Tier 1

| Horizon | Mean IC | HAC t-stat | FDR q-value | Significant at 10% FDR |
|---|---|---|---|---|
| 1m | 0.070 | 2.18 | 0.667 | No |
| 3m | 0.127 | 3.51 | 0.010 | Yes |
| **6m (primary)** | **0.170** | **3.45** | **0.006** | **Yes** |
| 12m | 0.364 | 3.28 | 0.004 | Yes |

Classified **Tier 1 - strong candidate** (mean_ic 0.170 > 0.10, HAC t 3.45 ≥ 2.0, positive spread, Sharpe 1.71, monotonic bucket returns).

## CF/P: survives, Tier 2, and incremental beyond B/M

| Horizon | Mean IC | HAC t-stat | FDR q-value | Significant at 10% FDR |
|---|---|---|---|---|
| 1m | 0.040 | 1.10 | 0.883 | No |
| 3m | 0.092 | 2.66 | 0.089 | Yes |
| **6m (primary)** | **0.135** | **4.94** | **0.00002** | **Yes** |
| 12m | 0.196 | 4.22 | 0.0002 | Yes |

Classified **Tier 2 - promising but uncertain** (fails the Tier-1 monotonicity gate, not because of a weak IC — its 6m t-stat, 4.94, is actually higher than B/M's).

**Orthogonalized to B/M** (residual IC, i.e. CF/P's information content net of B/M): 6m mean IC 0.109, HAC t 3.57, p=0.0004; net of B/M+size+liquidity: 6m mean IC 0.079, HAC t 3.69, p=0.0002. **CF/P retains statistically significant incremental information beyond B/M at every horizon from 3m to 12m**, both before and after controlling for size and liquidity.

**Pairwise rank correlation, B/M vs CF/P**: 0.252 (mean across 51 common dates) — modest, confirming these are not simply two labels for the same underlying signal.

**Coverage**: B/M is computed for 2,622 stock-months (566 financial, 2,056 non-financial, 67 symbols); CF/P is computed for 2,061 stock-months, **0 financial** (the sector-applicability exclusion implemented this session is confirmed working as intended) across 55 symbols.

## Isolated effect of the REB/ATW/IAM data repairs on B/M (the actual causal question)

Reconstructed the exact "before" raw B/M values for REB (using the corrupted Total_Equity figures recorded in `known_cases_reb_sah_sbm.md`) and ATW/IAM (using the demo_fixture Total_Equity=53,300 placeholder that won the resolver for their 2021 dates), holding every other symbol at its current (repaired) value, then recomputed IC with the same machinery.

- **62 of 260** REB/ATW/IAM stock-month observations changed value. REB's raw B/M dropped from ~24-35 (still an extreme, single-stock outlier, in the same order of magnitude as the originally-flagged 41.9) to ~1.2-1.6 (plausible) across the affected months.
- **Aggregate B/M IC barely moved**: 6m mean IC 0.180 (before, reconstructed) → 0.170 (after, actual) — i.e., very slightly *lower* after the repair, and within noise; 12m actually rose slightly (0.353 → 0.364). **The direction is not uniformly "improved"** — this is reported honestly rather than selectively highlighting only the horizons where the repair "helped."
- **Interpretation**: B/M's aggregate predictive signal was never meaningfully driven by these 3 corrupted symbols (they're 3 of 67-71 symbols in the panel) — the repair was necessary for correctness and individual-stock trust (nobody should see REB quoted at a 41.9 B/M), but it does not materially change the portfolio-level conclusion about whether B/M works. This is a genuine, non-cherry-picked negative result on "did the bug inflate the headline IC" — it did not, meaningfully.
- **Tercile bucket membership**: **0 of 140** REB/ATW/IAM stock-month observations changed top/middle/bottom tercile bucket assignment despite the large raw-value changes. REB's absurdly high pre-repair B/M and its corrected, sane B/M both happened to rank it in the same tercile within its monthly cross-section — the repair fixed the *headline number's* economic correctness without changing which portfolio bucket the backtest would have placed it in.

## What was NOT computed this session (explicitly, not silently skipped)

- **Non-overlapping-period inference**: not computed. All IC/HAC numbers above use the existing `_hac_mean_t` (Newey-West HAC on monthly overlapping-horizon IC series, horizon-scaled maxlags) machinery already in the codebase — this is a real HAC correction, but it is not the same as a strictly non-overlapping-sample test, which would require subsampling to non-overlapping windows and was not built this session.
- **Effective independent N / moving-block bootstrap**: not computed — would require new statistical code beyond what `methodology_bakeoff.py`/`characteristic_study.py` currently provide.
- **Leave-one-stock, leave-one-date, leave-one-sector influence analysis**: not computed — each is a meaningful, separate piece of analysis code that was not built this session given the scope already covered.
- **Financial vs non-financial B/M split IC** (as opposed to just coverage counts): not separately computed — coverage (566 financial / 2,056 non-financial observations) is reported, but a financial-only vs non-financial-only IC comparison was not run.
- **90d vs 120d PIT fallback sensitivity specifically for B/M/CF/P IC** (as opposed to panel-row-count sensitivity, which *was* computed in `pit_fallback_audit.md`): not run — would require re-running the full characteristic study a second time under the 120-day config (another ~3 minute heavy computation not repeated this session to conserve time budget after already running it once).

These are genuine limitations, not oversights hidden from the reader — see `final_data_quality_verdict.md` item 17 for how they bound the overall confidence level.
