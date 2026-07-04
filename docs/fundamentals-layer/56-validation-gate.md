# Doc 56 — Validation gate: one command, PASS/FAIL, exit code

**Status:** SHIPPED (brief 54 Phase 5).
**Script:** `services/api/scripts/validation_gate.py`.
**Predecessors:** brief 48 (`ic_ensemble_weights.json`, `pit_ic_backtest.py`), brief 54 §3
(coverage audit, BKGR fixture), doc 55 (perfect-foresight IC verdict).

## 1. What it answers

"Is the fundamentals layer still healthy after this engine change?" — a single rerunnable
command that bundles three existing checks, imports their internal functions directly (no
subprocess drift), and reduces them to one `VALIDATION GATE: PASS|FAIL` line + exit code
(0 = pass, 1 = fail; WARNs never fail the gate).

## 2. The three checks and their gates

### 2.1 Coverage audit (`audit_fundamental_coverage.py`)
Classifies every active MASI equity into one resolved state (OK / BELOW_QUORUM /
HEADLINE_REVIEW / NR_UNVERIFIED / NR_NO_MODELS / NO_ENSEMBLE / NO_FUNDAMENTALS) and a
weight mode (real IC spread vs. relative-multiples fallback).
- **FAIL** if any symbol is `NO_ENSEMBLE`, `NO_FUNDAMENTALS`, or `NR_NO_MODELS` — these mean
  the ingest/valuation pipeline silently produced nothing, which coverage regressions must
  never do.
- **FAIL** if `NR_UNVERIFIED` contains a symbol outside `--allow-unverified` (default `AFM`
  — a known, tracked tie-out failure; see the stale-data-verification-cache note). Any other
  symbol dropping into `NR_UNVERIFIED` is a new data problem, not a known one.
- `BELOW_QUORUM` / `HEADLINE_REVIEW` / whitelisted `NR_UNVERIFIED` are reported, not gated —
  they're expected steady-state noise (thin comps, brief-44 governance holds).

### 2.2 BKGR broker validation (`validate_vs_bkgr.py`)
Compares the latest base ensembles against the BKGR Jun-2026 fixture.
- **FAIL** if `floor_count > 0` or `tail_count > 0` — a valuation pinned at the −95% floor or
  past the +150% tail cap signals a broken model input, not a legitimate extreme view.
- **FAIL** if `overlap_count < 30` — below that the fixture no longer exercises enough of the
  universe to mean anything.
- `mean_diff_vs_bkgr_pct`, `spearman`, `directional_agreement` are printed as context only.
  Per brief 48: BKGR is a single-broker sanity reference, never a target to fit — gating on
  agreement-with-BKGR would reintroduce the circularity brief 48 removed.

### 2.3 IC-weight provenance (`ic_ensemble_weights.json`)
Reports each model's weight and the `estimated_date` the weights were last (re-)estimated.
- **FAIL** if the weights file is missing or fails to parse — the ensemble cannot run
  meaningfully blind.
- **WARN** (not fail) if `valuation.py`, `projection.py`, or `pit_ic_backtest.py` has a
  filesystem mtime newer than the weights file — a stale-weights signal, not proof the
  weights are wrong (re-estimating is expensive; the WARN just flags "go check doc 55's
  decision rule before trusting these numbers blindly").
- Always prints the doc-55 verdict: *"ddm structural zero; residual_income watch-list
  (re-estimate after ≥2 FY of real consensus history); fcff_dcf seeding validated."*

## 3. How to run it

```
.venv/Scripts/python.exe services/api/scripts/validation_gate.py
.venv/Scripts/python.exe services/api/scripts/validation_gate.py --allow-unverified AFM XYZ
.venv/Scripts/python.exe services/api/scripts/validation_gate.py --json out/gate_result.json
```

Read-only against `postgresql+psycopg2://app:app@127.0.0.1:5555/quant`; no writes anywhere.

## 4. When it MUST be run

- After any change to `core/quant_core/fundamentals/valuation.py` or `projection.py`.
- After any change to scoring / ensemble weighting logic.
- After re-running a fundamentals re-import (worker `refresh_*` tasks) against a DB you care
  about.
- Before any demo or deploy that shows fundamentals data.

## 5. Baseline (2026-07-02, live DB)

Coverage: `OK=60 BELOW_QUORUM=9 HEADLINE_REVIEW=3 NR_UNVERIFIED=1(AFM)`, universe=73. BKGR:
`overlap=33 floor=0 tail=0 mean_diff_vs_bkgr_pct≈-30`. IC provenance: WARN (valuation.py /
projection.py modified after the 2026-06-20 weights run). Overall: **PASS with warnings**.
