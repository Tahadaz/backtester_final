# ChatGPT Change Request Template

Copy/paste this into ChatGPT and fill every section.

## Project Context

- Repository: `backtester_final`
- Primary target area: `core/quant_core`
- Architecture reference: `docs/CHATGPT_CONTEXT_PACK.md`

## Objective

Describe the exact functional change:

-

## Why This Change Is Needed

-

## Exact Scope (Allowed Files)

List only files ChatGPT is allowed to edit:

-

## Out Of Scope (Do Not Edit)

-

## Current Behavior

Include concrete examples (inputs/outputs, API response, figure behavior, ledger row behavior, etc.):

-

## Desired Behavior

Define expected result precisely, including edge cases:

-

## Data/Contract Constraints (Must Stay Compatible)

- Keep `run_pipeline` output contract unless explicitly approved:
  - `leaderboard`
  - `plot_artifacts`
  - `strategy_results`
  - `artifacts`
- Keep API route contracts unless explicitly approved:
  - `/runs`, `/runs/{id}/leaderboard`, `/runs/{id}/artifacts`, etc.
- Keep artifact naming conventions unless explicitly approved.

Add any additional constraints:

-

## Acceptance Tests

Define what must pass after the change:

1.
2.
3.

## Required Verification Commands

Ask ChatGPT to run and report relevant commands (customize):

```powershell
python -m pytest core/tests/test_synthetic_data_smoke.py
python services/ui_streamlit/smoke_test.py --api-url http://127.0.0.1:8000 --symbol IAM
```

## Output Format You Want From ChatGPT

Tell ChatGPT to respond with:

1. Files changed
2. Exact behavioral diffs
3. Risk/regression notes
4. Test evidence (command + key output)

## If Ambiguous

When uncertain, instruct ChatGPT to:

- stop and ask 1-3 focused questions before editing, and
- avoid silent assumptions about strategy IDs, indicator names, artifact schema, or API payload shape.
