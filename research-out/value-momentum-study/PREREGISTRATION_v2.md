Pre-registered 2026-07-12T17:34:52Z

Confirmation study v2: value-tilted graceful value+momentum integration.
Selection-bias disclosure: the 0.7/0.3 value/momentum weighting was the best-performing SENSITIVITY cell in study v1 (research-out/value-momentum-study/20260712-172056). Because it has been seen once on this data, v2 promotes ONLY on a strictly harder, A-grade-only bar with three additional robustness gates. No further weight/parameter tuning is permitted in v2; one shot.
Structural fixes vs v1 (diagnosed in v1 analysis, not performance-tuned): (1) graceful integration — universe = eligible_bm (B/M required), momentum_12_1 pct-rank imputed at neutral 0.5 when missing, so the strategy is defined over the full value universe in every year and degrades to pure value where momentum data does not exist; (2) sector cap 0.30 retained, name cap REMOVED (redundant for equal-weight terciles; in v1 it interacted with thin early-coverage terciles to force up to 77% cash).
Cells: C0a (S1_bm raw anchor); VM2 (PRIMARY) = graceful composite 0.7*rank(B/M) + 0.3*rank(mom_12_1, imputed 0.5), sector_cap 0.30, no name cap, cost 33; VM2_uncapped; VM2_5050 (0.5/0.5 weights, robustness); VM2 at cost 50 and 75.
PROMOTION BAR (ALL must hold for the primary on the common invested window; otherwise NOT PROMOTED and value-only stands):
(a) net Sharpe(VM2) >= net Sharpe(C0a);
(b) maxDD(VM2) >= maxDD(C0a) - 0.02;
(c) block-bootstrap p < 0.10 WITH positive mean monthly difference (VM2 - C0a);
(d) net Sharpe(VM2) >= net Sharpe(MASI);
(e) split-half consistency: split the common window into two equal halves; VM2 cumulative net return >= C0a's in BOTH halves;
(f) cost robustness: VM2 at 75 bps still satisfies (a) against C0a at 33 bps;
(g) drop-the-winner: identify the ever-held name (union of VM2 holdings) with the highest total close-price return over the common window; rerun BOTH VM2 and C0a with that symbol excluded from the panel before holdings construction; require Sharpe(VM2_ex) >= Sharpe(C0a_ex).
Also reported (informational): correlation of active returns (cell minus MASI) between VM2 and C0a; subperiod table; turnover; average effective momentum coverage (share of composite weight where momentum was real vs imputed).
Common invested window: first date where BOTH C0a and VM2 have n_holdings > 0 (expected to equal C0a's own start since the universes now coincide), through the last panel date.
