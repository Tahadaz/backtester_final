# Full Duplicate / Conflict Catalogue (Workstream 1, post-repair)

Scanned live `fundamental_annual_metric` (113,009 non-null rows, post REB/EV/demo_fixture repairs) grouped by `(symbol, statement_year, metric_name)`. A group is a "conflict" only if it contains **more than one distinct value** (rows with identical values across duplicate imports are not conflicts — they're redundant, not disagreeing).

## Headline numbers

- **10,439** conflicting `(symbol, statement_year, metric_name)` groups across the full universe.
- **1,591** of those involve a factor-critical metric (book equity variants, market cap, EBITDA, EV, CFO, cash, debt, shares, net income, revenue) — see `duplicate_conflicts_factor_critical.csv`.
- Classification breakdown (all metrics): `E_source_disagreement` 6,256, `B_harmless_equivalent` 3,475, `E_source_disagreement_sign_flip` 636, `G_scale_mismatch` 72.

## Classification scheme actually used

| Code | Meaning | Threshold |
|---|---|---|
| B_harmless_equivalent | values agree to within 0.1% | `\|max-min\| < 0.001 * max(\|max\|,1)` |
| G_scale_mismatch | ratio between max/min is within 2% of a clean power-of-10 (10x/100x/1000x/1,000,000x) | classic unit error signature |
| E_source_disagreement_sign_flip | competing values disagree in sign | e.g. a net-debt vs net-cash flip — often a real accounting-basis difference (group vs standalone), not necessarily a bug |
| E_source_disagreement | values disagree, same sign, no clean scale relationship | most common — typically restatement, vintage, or source methodology difference |

**Caveat on scope**: this pass classifies by numeric pattern only, not by re-deriving the correct economic value for each of the 10,439 groups — that would require the same manual/external-verification depth as the REB/SAH/SBM forensics, multiplied ~3,000x, which is out of scope for this session. What *was* done: the 72 `G_scale_mismatch` and 636 sign-flip rows were spot-checked against the metric list already known to be bug-prone (EnterpriseValue, MarketCap_Calc, Total_Equity) — none of the remaining scale-mismatch rows after repair match the REB/EV/demo_fixture patterns (those are now fixed), so the residual scale-mismatches are presumed to be genuine consolidated-vs-standalone or restatement differences (Category C/D in the original schema) unless someone flags a specific symbol for the same depth of forensic work done on REB/SAH/SBM.

## Severe factor-critical conflicts by symbol (scale-mismatch or sign-flip, factor-critical metric)

Top offenders (from `duplicate_conflicts_factor_critical.csv`, filtered to `G_scale_mismatch`/`E_source_disagreement_sign_flip`): RIS (5), M2M (4), MDP (3), SRM (3), CAP/IMO/LES/SBM/SMI/SNP/WAA (2 each), plus 10 more symbols with 1 each. **These are flagged as unresolved (Category I) and not repaired** — each would need the same document-level forensic tracing done for REB/SAH/SBM before a value can be trusted, which was not performed for these ~20 symbols this session.

## What this catalogue is NOT

It does not attempt restatement/consolidated-vs-standalone semantic classification per row (Categories C and D from the original schema) — that requires reading each `fundamental_source_document`'s actual statement type, which is tracked in the schema (`period_type`, `document_kind`) but was not cross-joined into this scan. This is flagged as follow-on work, not fabricated here.

Machine-readable outputs: `duplicate_conflicts.csv` (all 10,439), `duplicate_conflicts_factor_critical.csv` (1,591 factor-relevant subset).
