# Phase 1 Results: Factor-Only Signal Evaluation

**Evaluation Date**: [TO BE FILLED]  
**Evaluation Completed By**: [TO BE FILLED]  
**Pre-Registration Hash**: [link to phase1_pre_registration.yaml commit]

---

## Executive Summary

[TO BE FILLED: 2–3 sentence verdict. Example: "Of six pre-registered factor signals, three passed Benjamini-Hochberg FDR filtering at q=0.10 on the MASI universe. Two signals (vix_zscore, sp500_vix_confirmation) exhibited DSR > 0 and PSR > 0.80, justifying Phase 2 exploratory work. One signal (brent_direction) showed honest null (fdr_pass=false) across all stocks."]

---

## Methodology Recap

- **Pre-registration file**: `docs/research/phase1_pre_registration.yaml`
- **Signal definitions**: `docs/factor-layer/07-phase1-factor-strategies.md`
- **Statistical methods**: `docs/factor-layer/05-statistical-battery.md`
- **Evaluation harness**: `core/quant_core/research/evaluate.py:evaluate_signal()`
- **Multiple-testing correction**: Benjamini-Hochberg FDR at q=0.10

---

## Per-Signal Verdicts

### 1. VIX Z-Score

**Applicable stocks**: All 8 seed + expanded universe  
**FDR pass**: [YES/NO]  
**Median DSR**: [value]  
**Median PSR**: [value]  
**Median Sharpe (net)**: [value]  
**IC (Spearman, NW t-stat)**: [value]

**Verdict**: [2–3 sentences describing results, economic interpretation, and confidence level.]

**Key findings per horizon**:
- h=1d: [summary]
- h=2d: [summary]
- h=5d: [summary]
- h=10d: [summary]

---

### 2. DXY Momentum

**Applicable stocks**: All sectors  
**FDR pass**: [YES/NO]  
**Median DSR**: [value]  
**Median PSR**: [value]  
**Median Sharpe (net)**: [value]  
**IC**: [value]

**Verdict**: [2–3 sentences.]

**Key findings per horizon**:
- h=1d: [summary]
- h=2d: [summary]
- h=5d: [summary]
- h=10d: [summary]

---

### 3. Brent Direction

**Applicable stocks**: Materials, mining, chemicals sectors only (channel-filtered)  
**FDR pass**: [YES/NO]  
**Median DSR**: [value]  
**Median PSR**: [value]  
**Median Sharpe (net)**: [value]  
**IC**: [value]

**Verdict**: [2–3 sentences. Note if channel filtering reduced applicability.]

**Key findings per horizon**:
- h=1d: [summary]
- h=2d: [summary]
- h=5d: [summary]
- h=10d: [summary]

---

### 4. SP500 + VIX Confirmation

**Applicable stocks**: All sectors  
**FDR pass**: [YES/NO]  
**Median DSR**: [value]  
**Median PSR**: [value]  
**Median Sharpe (net)**: [value]  
**IC**: [value]

**Verdict**: [2–3 sentences.]

**Key findings per horizon**:
- h=1d: [summary]
- h=2d: [summary]
- h=5d: [summary]
- h=10d: [summary]

---

### 5. US 10Y Shock

**Applicable stocks**: Banks, insurance, real_estate sectors only (channel-filtered)  
**FDR pass**: [YES/NO]  
**Median DSR**: [value]  
**Median PSR**: [value]  
**Median Sharpe (net)**: [value]  
**IC**: [value]

**Verdict**: [2–3 sentences.]

**Key findings per horizon**:
- h=1d: [summary]
- h=2d: [summary]
- h=5d: [summary]
- h=10d: [summary]

---

### 6. EUR/USD Momentum

**Applicable stocks**: All sectors  
**FDR pass**: [YES/NO]  
**Median DSR**: [value]  
**Median PSR**: [value]  
**Median Sharpe (net)**: [value]  
**IC**: [value]

**Verdict**: [2–3 sentences.]

**Key findings per horizon**:
- h=1d: [summary]
- h=2d: [summary]
- h=5d: [summary]
- h=10d: [summary]

---

## Cross-Signal Summary Table

| Signal | FDR Pass | DSR | PSR | Sharpe (net) | IC (NW t-stat) | Applicable Sectors |
|--------|----------|-----|-----|--------------|-----------------|-------------------|
| vix_zscore | [Y/N] | [#] | [#] | [#] | [#] ([#]) | All |
| dxy_momentum | [Y/N] | [#] | [#] | [#] | [#] ([#]) | All |
| brent_direction | [Y/N] | [#] | [#] | [#] | [#] ([#]) | Mat/Min/Chem |
| sp500_vix_confirmation | [Y/N] | [#] | [#] | [#] | [#] ([#]) | All |
| us10y_shock | [Y/N] | [#] | [#] | [#] | [#] ([#]) | Banks/Ins/RE |
| eurusd_momentum | [Y/N] | [#] | [#] | [#] | [#] ([#]) | All |

---

## Honest Nulls

**Signals marked fdr_pass=false** (brief narratives):

- [Signal name]: [1–2 sentences explaining why it did not survive FDR filtering and what the metrics show.]
- [Signal name]: [...]

---

## Universe Generalizability

For each FDR-passing signal, report:

- **Seed stocks** (stock, h, Sharpe net): [list]
- **Auto-expanded stocks** (min 10 examples): [list]
- **Sector coverage**: [list sectors with ≥1 passing signal]

---

## Economic Interpretation

[2–3 paragraphs synthesizing results]:

- What is the dominant theme? (e.g., "risk-sentiment gates are profitable; carry signals are not.")
- Which academic hypotheses held? (e.g., "Ilmanen's VIX risk-on/off gate replicates, but at smaller magnitude than developed markets.")
- What is surprising? (e.g., "DXY momentum outperforms on long only; short signals fail.")
- Caveats: (e.g., "Results rely on pre-1990 volatility data with potential survivorship bias," or "Forward returns are in-sample; realistic slippage may reduce returns by 20–30%.")

---

## Phase 2 Recommendation

**Recommendation**: [APPROVED / CONDITIONAL / NOT RECOMMENDED]

**Rationale**:
- If APPROVED: Which signals exhibit DSR > 0, PSR > 0.80, and FDR pass? How many stocks generalize?
- If CONDITIONAL: Which conditions must be satisfied before Phase 2 pre-registration (e.g., "sector-specific tuning of Brent channel," "out-of-sample validation on 2024 data")?
- If NOT RECOMMENDED: Why? (e.g., "All signals show honest nulls; no DSR > 0," or "High variance across stocks suggests overfitting; recommend alternative factor research.")

---

## Appendix: Per-Stock Summary

[Optional: For each seed stock + top 10 auto-expanded]:

```
Symbol: ATW
---
Signal          | h=1d | h=2d | h=5d | h=10d | Applicable
vix_zscore      | [Sharpe] | ... | ... | ... | Yes
dxy_momentum    | [Sharpe] | ... | ... | ... | Yes
brent_direction | N/A | N/A | N/A | N/A | No (sector=banks)
...
```

---

## Appendix: Robustness Checks

[Optional: If time permits, include]:

- **Bootstrap CI**: For each signal, 90% CI on Sharpe across 500 block-resamples.
- **Rolling IC stability**: IC by 63-day rolling window; any signal with IC decay > 0.3 flagged.
- **Parameter sensitivity**: Quick scan (e.g., "VIX z-score window 15 vs 20 vs 25 — results stable") to check if rules are brittle.

---

## References

- Pre-registration: `docs/research/phase1_pre_registration.yaml`
- Signal definitions: `docs/factor-layer/07-phase1-factor-strategies.md`
- Methodology: `docs/factor-layer/10-methodology-and-sources.md`
- Phase 2 scoping: `docs/factor-layer/12-phase2-scoping-note.md`
- Code: `core/quant_core/research/factors/signals.py`, `core/quant_core/research/evaluate.py`
