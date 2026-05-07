# Tableau de Bord — Signaux MASI

## Purpose

Client-facing dashboard showing per-stock signal evaluations for the MASI equity universe.
Deployable as a static site on GitHub Pages — no backend dependency at runtime.

## Document index

| # | Document | What it covers |
|---|----------|---------------|
| 01 | [Export Script](./01-export-script.md) | Python script that generates static JSON from the signal engine |
| 02 | [Types and Constants](./02-types-and-constants.md) | TypeScript types, family labels, signal badge colors |
| 03 | [Components](./03-components.md) | ScoreBar, SignalBadge, FamilyCell, StockTable, SectorTable, IndexSummary |
| 04 | [Dashboard Page](./04-dashboard-page.md) | Main page assembly, horizon tabs, view tabs, loading/error states |
| 05 | [Navigation and Routing](./05-navigation-and-routing.md) | Header update, root redirect |
| 06 | [Static Export and GitHub Pages](./06-static-export.md) | next.config changes, dynamic route fixes, deploy workflow |
| 07 | [Gotchas and Verification](./07-gotchas-and-verification.md) | Common mistakes, verification checklists |

## Implementation order

Execute strictly in this order — each step builds on the previous:

1. **Doc 01** — Export script → produces test data for all subsequent frontend work
2. **Doc 02** — Types + constants → shared definitions used by all components
3. **Doc 03 (sections a-c)** — Atomic components: ScoreBar, SignalBadge, FamilyCell
4. **Doc 03 (sections d-f)** — Composite components: StockTable, SectorTable, IndexSummary
5. **Doc 04** — Dashboard page → assembles all components
6. **Doc 05** — Navigation update + root redirect
7. **Doc 06** — Static export config (do LAST)

## File summary

| File | Action | Approx lines |
|------|--------|-------------|
| `frontend/scripts/export-scores.py` | CREATE | ~150 |
| `frontend/public/data/.gitkeep` | CREATE | 0 |
| `frontend/lib/dashboard-types.ts` | CREATE | ~65 |
| `frontend/lib/dashboard-constants.ts` | CREATE | ~80 |
| `frontend/hooks/use-dashboard.ts` | CREATE | ~15 |
| `frontend/components/dashboard/score-bar.tsx` | CREATE | ~25 |
| `frontend/components/dashboard/signal-badge.tsx` | CREATE | ~15 |
| `frontend/components/dashboard/family-cell.tsx` | CREATE | ~20 |
| `frontend/components/dashboard/stock-table.tsx` | CREATE | ~150 |
| `frontend/components/dashboard/sector-table.tsx` | CREATE | ~120 |
| `frontend/components/dashboard/index-summary.tsx` | CREATE | ~80 |
| `frontend/app/dashboard/page.tsx` | CREATE | ~100 |
| `frontend/components/signals-header.tsx` | MODIFY | 3 lines |
| `frontend/app/page.tsx` | MODIFY | 1 line |
| `frontend/next.config.mjs` | MODIFY | ~5 lines |
| `frontend/.github/workflows/deploy-pages.yml` | CREATE | ~40 |

## Architecture

```
                              BUILD TIME                              RUNTIME

  ┌──────────────────────┐    ┌──────────────────────┐    ┌─────────────────────────────┐
  │ Python export script │───>│ public/data/          │───>│ /dashboard page              │
  │ (runs locally with   │    │   scores-short.json   │    │  - Reads static JSON         │
  │  DB + signal engine) │    │   scores-medium.json  │    │  - No API calls              │
  │                      │    │   scores-long.json    │    │  - Works on GitHub Pages     │
  └──────────────────────┘    └──────────────────────┘    └─────────────────────────────┘
```

The dashboard reads from static JSON files in `frontend/public/data/`, NOT from the API.
Data is updated by re-running the export script and committing the new JSON files.
