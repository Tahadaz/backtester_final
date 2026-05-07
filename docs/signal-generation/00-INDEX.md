# Signal Generation Layer - Architecture Documentation

> Station mandate: transform raw market data into informative signals with measurable predictive power using a strict out-of-sample research pipeline. This layer produces evaluated, filtered, ensembled signals, not executable strategies.

## Status

- A-G signal pipeline: `Implemented (4 families), expanding to 20 families`
- Variant detail and signal-page drill-down: `Implemented`
- Regime-aware conditioning: `Implemented (v0.1 experimental)`
- Indicator explorer: `Partial / deferred`
- **Indicator expansion**: `Planned — 4 → 20 indicators (5 per category)`. See [10-indicator-expansion-plan.md](./10-indicator-expansion-plan.md)

## Documents

| # | File | Scope |
|---|------|-------|
| 01 | [philosophy.md](./01-philosophy.md) | Why signals are not strategies, multiple testing, and why OOS validation is mandatory |
| 02 | [candidate-universe.md](./02-candidate-universe.md) | Layer A: structured candidate generation |
| 03 | [oos-evaluation.md](./03-oos-evaluation.md) | Layer B: walk-forward OOS evaluation and cost-adjusted scoring |
| 04 | [robustness-scoring.md](./04-robustness-scoring.md) | Layer C: reliability scoring |
| 05 | [survivor-filtering.md](./05-survivor-filtering.md) | Layer D: survivor filtering |
| 06 | [redundancy-reduction.md](./06-redundancy-reduction.md) | Layer E: redundancy reduction |
| 07 | [current-signal-and-ensemble.md](./07-current-signal-and-ensemble.md) | Layers F-G: current signal and ensemble output |
| 08 | [variant-detail.md](./08-variant-detail.md) | Variant detail, trade register, plots, and metrics |
| 09 | [api-and-frontend.md](./09-api-and-frontend.md) | API endpoints and signal-page UX |
| 10 | [methodology-and-sources.md](./10-methodology-and-sources.md) | Sources and justification |
| 11 | [regime-aware-conditioning.md](./11-regime-aware-conditioning.md) | Experimental regime-aware family weighting, now wired on the signal page with equal-weight fallback |
| 12 | [indicator-explorer.md](./12-indicator-explorer.md) | Planned indicator explorer, still deferred from the shipped four-page surface |
| 13 | [13-implementation.md](./13-implementation.md) | Page implementation status and deferred work |

### Expansion Plan

| # | File | Scope |
|---|------|-------|
| 10 | [indicator-expansion-plan.md](./10-indicator-expansion-plan.md) | Full implementation plan for expanding from 4 to 20 indicators (Codex-ready) |

## The A-G Pipeline

```text
Layer A  Candidate generation
Layer B  OOS evaluation
Layer C  Robustness scoring
Layer D  Survivor filtering
Layer E  Redundancy reduction
Layer F  Current signal
Layer G  Ensemble
```

The product surface uses this A-G path as the canonical signal engine. With the indicator expansion, 20 families (5 per category) go through the same pipeline — Layers C through G are family-agnostic and require no changes. Regime-aware conditioning is an experimental overlay on top of the family ensemble rather than a replacement for the baseline equal-weight consensus.
