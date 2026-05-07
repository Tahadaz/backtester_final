# 13 - Signal Page Implementation Status

## Shipped Surface

- `/signals` keeps the A-G family ensemble flow as the canonical experience.
- The consensus tab and existing family drill-down remain the primary UX.
- The regime-aware detail flow is now wired into the supported page as `v0.1 experimental`.
- Equal-weight consensus remains the baseline and fallback whenever regime weighting does not produce a positive OOS improvement.

## Implemented

- Backend family ensemble endpoints and variant detail
- Signal-page consensus drill-down
- Regime-aware consensus endpoint
- Regime-aware detail panel on the signal page

## Deferred

- Indicator explorer tab
- Any expansion of regime detection beyond the documented v0.1 detector set
- Any redesign of the A-G methodology, candidate counts, robustness weights, survivor logic, or ensemble math

## Product Rule

The shipped four-page signal layer must stay honest about status:

- A-G pipeline: implemented
- Regime-aware conditioning: implemented, experimental
- Indicator explorer: documented but not wired into the shipped surface
