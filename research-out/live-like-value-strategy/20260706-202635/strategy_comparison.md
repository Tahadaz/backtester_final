# S1-S4 Fair Comparison (Phase 15)

All four strategies share identical trusted-universe logic, rebalance schedule (monthly formation, 6-month vintage life), price data, cost assumption (33bps), and benchmark. No architecture was optimized separately from the others.

1. **Strongest raw (gross) return**: S2 (CF/P), +309% cumulative, though over the shortest window (42 months) — CAGR 49.6% is the highest of the four.
2. **Strongest net return**: same — S2.
3. **Strongest Sharpe**: **S4 (separate sleeves)**, 2.13 — combining independently-run B/M and CF/P sleeves diversifies away some idiosyncratic risk relative to either alone.
4. **Lowest drawdown**: S3 (composite), -11.5%.
5. **Lowest turnover**: S1 (B/M), 3.5% avg monthly.
6. **Best benchmark-relative (information ratio)**: S1, IR 1.22 — but note S4 (1.58) and S2 (1.65) both have higher IR; S1 is only lowest here, not best. Re-ranking by IR: S2 (1.65) > S4 (1.58) > S3 (1.44) > S1 (1.22).
7. **Most stable by subperiod**: S1 — first/second half Sharpes (1.46 / 1.74) are closest together and both trend the same direction (improving); S2 and S3 weaken more from first to second half.
8. **Least dependent on a few names**: not separately computed for S2/S3/S4 this session (only S1's attribution was run, see `holdings_attribution.md`) — flagged as incomplete, not claimed.
9. **Simplest to defend**: **S1 (B/M alone)** — single signal, canonical definition, lowest turnover, most stable subperiod behavior, and B/M is the more theoretically well-established value characteristic (Fama-French HML) versus CF/P's greater sensitivity to the CFO field-mapping ambiguities already flagged as unresolved in the prior session (`field_mapping_audit.md`'s net_income mapping issue also touches CFO-adjacent fields).

## Overall read

S4 (separate sleeves) has the best risk-adjusted profile (Sharpe, IR) and the most balanced beta (≈1.0), consistent with a real diversification benefit from combining two only-modestly-correlated signals (B/M/CF/P pairwise rank correlation was 0.25 in the predictive-research phase). But S1 alone is the most defensible from a "can I explain and trust this" standpoint given the shorter, thinner samples underlying S2/S3/S4 and CF/P's additional field-mapping uncertainty.
