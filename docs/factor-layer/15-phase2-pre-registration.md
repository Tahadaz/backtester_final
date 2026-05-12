# 15 — Phase 2 Pre-Registration Protocol

> Pre-registration is the single most important integrity control in this research layer. It is what makes the Phase 2 results defensible against "we tuned until it looked good."

## What is pre-registered

`services/worker/research/phase2_pre_registration.yaml` contains, frozen before the first Phase 2 backtest run:

- The exact universe of stocks and auto-expand rule.
- The exact list of factor conditions (condition_id, form, parameters, direction, channel_gate).
- The evaluation horizons, cost assumptions, FDR threshold, bootstrap method.
- The alignment lag rule.
- The incremental value criterion (bootstrap CI lower bound on incremental Sharpe > 0).

## Why this matters

Without pre-registration, a researcher could run 100 factor conditions, observe which ones look good, and report only those — a classic multiple-testing inflation. With a frozen spec committed before any backtest, the FDR correction is applied to a known, bounded set and the results are honest.

## Protocol

1. **Before any Phase 2 backtest**: commit `phase2_pre_registration.yaml` with `freeze_date` and the git commit hash of the current HEAD.
2. **Tag the commit**: `git tag phase2-preregistration` immediately after.
3. **Never modify** the freeze file after tagging. If a parameter must change, create a new file (`phase2b_pre_registration.yaml`) and tag again — treating it as a separate trial.
4. **CI check** (planned): a CI step fails any Phase 2 backtest task if `phase2_pre_registration.yaml` has been modified since the last `phase2-*` tag.

## What is NOT pre-registered

- The expected direction of results (null hypothesis: no factor condition adds value; pre-registration does not mean we expect it to).
- The exact number of surviving variants (FDR outcome is a result, not an input).
- Phase 3 or later extensions.

## Honest reporting obligation

`docs/factor-layer/16-phase2-results.md` must include:
- Stocks for which **no** factor-conditioned variant beats its TA baseline (these are results, not failures).
- The FDR-rejected variants alongside the FDR-accepted ones.
- Any surprises that conflict with the channel-tag economic hypothesis (statistical-only discoveries flagged for manual review).
