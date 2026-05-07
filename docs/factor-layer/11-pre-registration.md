# Pre-Registration Protocol

## Why Pre-Registration Matters

Pre-registration is the scientific bulwark against **p-hacking** and **data snooping**. Before evaluating six novel factor-only trading signals against historical data, we freeze the rule definitions, parameters, and evaluation costs in a git-timestamped YAML file. This ensures that:

1. **Rule definitions are locked** — no post-hoc tweaks to thresholds or signal logic after peeking at results.
2. **The universe is fixed** — we commit to which stocks (seed + auto-expand criteria) are in scope before running any analysis.
3. **Costs are predetermined** — spread, commission, and trading friction are locked so we cannot cherry-pick friendly numbers after seeing P&L.
4. **Evaluation methodology is frozen** — the alignment lag rule, FDR threshold, and statistical test battery are decided in advance.

The git commit timestamp on `phase1_pre_registration.yaml` serves as **irrevocable proof** that these choices predate the first evaluation run.

## What Counts as a Protocol Violation

- **Post-hoc rule changes**: e.g., "the z-score threshold for VIX should be -1.5 instead of -1.0 because the results look better" — violation.
- **Parameter tuning on live results**: e.g., adjusting the Brent momentum window from 5 to 10 days after seeing the first stock's Sharpe ratio — violation.
- **Universe cherry-picking**: e.g., adding or removing stocks from the seed list after initial evaluation — violation.
- **Cost revision downward**: e.g., "actually, commission is only 20 bps, let me rerun" — violation. The pre-registered 33 bps stands.
- **Threshold shopping**: e.g., trying FDR q=0.15 instead of 0.10 to get more signals to pass — violation.

**Null results are deliverables.** If a signal shows `fdr_pass=false` or `sharpe < 0`, that is an honest finding and will be documented in the final report. We do not re-run "because the answer doesn't look right."

## Evidence of Integrity

The file `docs/research/phase1_pre_registration.yaml` contains:

- **freeze_date**: 2026-04-29
- **commit_hash**: populated at commit time via `git rev-parse HEAD`
- All six signal rule definitions with exact parameters (thresholds, windows, z-scores)
- Universe definition (seed symbols + auto-expand criteria)
- Evaluation costs (spread and commission in basis points)
- Alignment rule (lag logic and max staleness)
- FDR and bootstrap configuration
- Academic citations for each rule

Any divergence from this file constitutes a post-hoc change and must be re-registered in a new YAML version with a new commit timestamp.

## Evaluation Workflow

1. **Commit pre-registration YAML** — this is the integrity anchor.
2. **Run all six signals through `evaluate_signal()`** — no tweaking during or between runs.
3. **Collect raw results** — p-values, test statistics, per-signal and per-stock metrics.
4. **Apply BH-FDR** — once, across all (signal, stock, horizon) combinations at q=0.10.
5. **Document verdicts** — including null findings, in `docs/research/phase1_results.md`.
6. **Report honestly** — cite this pre-registration protocol in the final report.

## Extensions (Phase 2+)

If Phase 1 results justify moving factor signals into the trading pipeline (conditional composition with TA signals), that work is **Phase 2** and requires a separate pre-registration document. The integrity boundary is clear: Phase 1 is research-panel-only evaluation; Phase 2 is operational integration and will have its own locked specifications.
