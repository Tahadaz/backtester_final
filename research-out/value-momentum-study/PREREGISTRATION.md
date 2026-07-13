Pre-registered: 2026-07-12 17:15:33 UTC

---
Study: Cross-sectional momentum on the CSE — mechanism test and gated value+momentum combination.
Motivation: External literature (de Groot-Pang-Swinkels JEF 2012 frontier markets; Moroccan studies 2008-2020) finds strong cross-sectional momentum; the in-house PIT panel finds insignificant momentum IC (12-1: t=0.66-0.97 across horizons, hit rate ~51%). This study resolves the conflict with a tradeable live-like test. Cross-sectional momentum stays fully invested (no cash drag) — the failure mode of the rejected time-series gate study (research-out/combined-portfolio-strategy/20260712-161305) does not apply.
Signals (all PIT, from the repaired panel CSV): book_to_market_raw; momentum_12_1_raw (prior 252 trading-day return skipping 21); momentum_6_1_raw (robustness).
Engine: six-vintage monthly overlapping (J/K = 12-1/6 Jegadeesh-Titman for momentum cells), G0 mode of the parity-locked combined engine, cost 33 bps two-way, long-only, top tercile equal weight, min 9 names.
Cells: C0a value-only anchor (S1_bm raw); M12 momentum_12_1-only raw; M6 momentum_6_1-only raw (robustness); VM_int integrated 0.5*rank(B/M)+0.5*rank(mom_12_1) raw; VM_int_capped = VM_int + sector_cap 0.30 + max_name_weight 0.10 (PRIMARY); VM_mix = 50/50 sleeve combination of C0a and M12 monthly returns (combine_sleeves). Sensitivities (reported only): VM_int_capped at cost 50/75 bps; integrated weights 0.3/0.7 and 0.7/0.3.
STAGE-A MECHANISM GATE (decided before Stage-B is interpreted): on the common invested window, M12 must have (i) net Sharpe >= MASI net Sharpe and (ii) information ratio vs MASI > 0. If the gate FAILS, the study verdict is automatically C ("momentum mechanism absent on current-era CSE data"), Stage-B cells are reported as exploratory-only and are NOT promotable regardless of their numbers.
STAGE-B ACCEPTANCE (only if Stage A passes; primary = VM_int_capped vs incumbent C0a): (a) net Sharpe >= incumbent; (b) maxDD no worse than incumbent - 2pts; (c) block-bootstrap p < 0.10 WITH positive mean monthly difference; (d) net Sharpe >= MASI. Verdict A = a,b,c,d; B = a,b; C otherwise.
Also reported: monthly return correlation (M12 vs C0a) on the common window; turnover and breakeven cost for every cell; subperiod table; momentum candidate coverage per formation date.
Common invested window: first date where BOTH C0a and M12 have n_holdings > 0, through the last panel date; all cross-cell stats on this window.
---
