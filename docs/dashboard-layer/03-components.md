# 03 — Dashboard Components

## Overview

Create 6 components in `frontend/components/dashboard/`:

| Component | File | Purpose |
|-----------|------|---------|
| ScoreBar | `score-bar.tsx` | Horizontal bar -100 to +100 |
| SignalBadge | `signal-badge.tsx` | Colored label badge |
| FamilyCell | `family-cell.tsx` | Table cell with badge + score |
| StockTable | `stock-table.tsx` | Main stocks view (sortable, filterable) |
| SectorTable | `sector-table.tsx` | Sector aggregates with expandable rows |
| IndexSummary | `index-summary.tsx` | MASI overview card with breadth |

All imports from `@/lib/dashboard-types` and `@/lib/dashboard-constants`.
All use `cn()` from `@/lib/utils` for conditional classnames (already exists).

---

## 3a. Score Bar — `frontend/components/dashboard/score-bar.tsx` (CREATE)

A horizontal bar from -100 to +100, centered at zero.

```tsx
import { cn } from "@/lib/utils"
import { scoreBarColor } from "@/lib/dashboard-constants"

interface ScoreBarProps {
  score: number | null
  className?: string
}

export function ScoreBar({ score, className }: ScoreBarProps) {
  if (score == null) {
    return <div className={cn("h-2 w-full rounded-full bg-muted", className)} />
  }

  // Clamp to [-100, 100]
  const clamped = Math.max(-100, Math.min(100, score))
  // Bar width as percentage of half the container (since center is at 50%)
  const widthPct = (Math.abs(clamped) / 100) * 50
  // Position: negative scores extend left from center, positive extend right
  const isPositive = clamped >= 0

  return (
    <div className={cn("relative h-2 w-full rounded-full bg-muted", className)}>
      {/* Center line */}
      <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      {/* Score bar */}
      <div
        className={cn("absolute top-0 h-full rounded-full", scoreBarColor(clamped))}
        style={{
          left: isPositive ? "50%" : `${50 - widthPct}%`,
          width: `${widthPct}%`,
        }}
      />
    </div>
  )
}
```

### Behavior
- `score = null` → show empty grey bar (muted background, no fill)
- `score = +75` → green bar extending 37.5% to the right of center
- `score = -30` → red bar extending 15% to the left of center
- `score = 0` → tiny grey dot at center (width = 0%)
- Center line always visible as a 1px border

---

## 3b. Signal Badge — `frontend/components/dashboard/signal-badge.tsx` (CREATE)

A colored badge that displays a signal label like "Haussier", "Surachete", "Accumulation".

```tsx
import { cn } from "@/lib/utils"
import { SIGNAL_BADGE_COLORS, SIGNAL_BADGE_FALLBACK } from "@/lib/dashboard-constants"

interface SignalBadgeProps {
  label: string | null
  className?: string
}

export function SignalBadge({ label, className }: SignalBadgeProps) {
  if (!label) {
    return (
      <span className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        SIGNAL_BADGE_FALLBACK,
        className,
      )}>
        —
      </span>
    )
  }

  const colorClass = SIGNAL_BADGE_COLORS[label] ?? SIGNAL_BADGE_FALLBACK

  return (
    <span className={cn(
      "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
      colorClass,
      className,
    )}>
      {label}
    </span>
  )
}
```

### Behavior
- `label = "Haussier"` → green-tinted badge
- `label = "Surachete"` → red-tinted badge
- `label = null` → grey badge showing "—"
- Unknown labels → grey fallback (same as "Neutre")

---

## 3c. Family Cell — `frontend/components/dashboard/family-cell.tsx` (CREATE)

A compact cell for table use: shows a family's signal badge and numeric score.

```tsx
import type { FamilyScore } from "@/lib/dashboard-types"
import { formatScore } from "@/lib/dashboard-constants"
import { SignalBadge } from "./signal-badge"

interface FamilyCellProps {
  score: FamilyScore | undefined | null
}

export function FamilyCell({ score }: FamilyCellProps) {
  if (!score) {
    return <span className="text-xs text-muted-foreground">—</span>
  }

  return (
    <div className="flex flex-col items-start gap-0.5">
      <SignalBadge label={score.label} />
      <span className="text-xs text-muted-foreground font-mono">
        {formatScore(score.score_pct)}
      </span>
    </div>
  )
}
```

### Behavior
- Score exists → badge on top, formatted score below (e.g. "+45.2")
- Score is null/undefined → show "—" in muted text
- Always show sign: "+45.2" or "-12.0"

---

## 3d. Stock Table — `frontend/components/dashboard/stock-table.tsx` (CREATE)

The main stocks view. A sortable, filterable table.

**Props**: `{ stocks: DashboardStock[] }`

### Imports

```tsx
"use client"

import { useState, useMemo } from "react"
import type { DashboardStock } from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_SHORT_LABELS } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { ScoreBar } from "./score-bar"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { Input } from "@/components/ui/input"
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react"
```

### State

```typescript
const [search, setSearch] = useState("")
const [sectorFilter, setSectorFilter] = useState<string>("all")
const [sortKey, setSortKey] = useState<string>("aggregate_score_pct")
const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
```

### Columns

| # | Header text | Key for sort | Cell content |
|---|-------------|-------------|-------------|
| 1 | "Action" | `"symbol"` | `symbol` in bold + `display_name` below in muted-foreground text-xs |
| 2 | "Secteur" | `"sector"` | `sector` as text badge or plain text |
| 3 | "Tendance" | `"sma"` | `<FamilyCell score={stock.per_family.sma} />` |
| 4 | "Momentum" | `"macd"` | `<FamilyCell score={stock.per_family.macd} />` |
| 5 | "Oscillation" | `"rsi"` | `<FamilyCell score={stock.per_family.rsi} />` |
| 6 | "Volume" | `"obv"` | `<FamilyCell score={stock.per_family.obv} />` |
| 7 | "Signal Global" | `"aggregate_score_pct"` | `<SignalBadge>` + `<ScoreBar>` stacked vertically |

### Sorting logic

```typescript
function getSortValue(stock: DashboardStock, key: string): number | string {
  if (key === "symbol") return stock.symbol
  if (key === "sector") return stock.sector ?? ""
  if (key === "aggregate_score_pct") return stock.aggregate_score_pct ?? -999
  // Family keys: "sma", "macd", "rsi", "obv"
  const fam = stock.per_family[key]
  return fam ? fam.score_pct : -999
}
```

When clicking a column header:
- If clicking the already-active sort column, toggle direction (asc/desc)
- If clicking a different column, set that column as active with "desc" direction
- Show sort arrow: `<ChevronUp>` for asc, `<ChevronDown>` for desc, `<ChevronsUpDown>` for inactive

### Filtering logic

```typescript
const sectors = useMemo(() => {
  const s = new Set(stocks.map(st => st.sector).filter(Boolean))
  return ["all", ...Array.from(s).sort()]
}, [stocks])

const filtered = useMemo(() => {
  let result = stocks
  if (search) {
    const q = search.toLowerCase()
    result = result.filter(s =>
      s.symbol.toLowerCase().includes(q) ||
      (s.display_name ?? "").toLowerCase().includes(q)
    )
  }
  if (sectorFilter !== "all") {
    result = result.filter(s => s.sector === sectorFilter)
  }
  return result
}, [stocks, search, sectorFilter])
```

### Layout

```
┌─────────────────────────────────────────────────────┐
│  [Search input...............] [Sector dropdown ▾]  │
├────────┬─────────┬────┬────┬────┬────┬──────────────┤
│ Action │ Secteur │ T  │ M  │ O  │ V  │ Signal Global│
├────────┼─────────┼────┼────┼────┼────┼──────────────┤
│ ATW    │ Banques │ .. │ .. │ .. │ .. │ Achat  ████  │
│ Attija │         │    │    │    │    │ +34.5        │
├────────┼─────────┼────┼────┼────┼────┼──────────────┤
│ ...    │         │    │    │    │    │              │
└────────┴─────────┴────┴────┴────┴────┴──────────────┘
```

### Empty state

If no stocks match the search/filter, show:
```tsx
<div className="py-12 text-center text-muted-foreground">
  Aucune action ne correspond aux filtres.
</div>
```

### Search and filter controls

Place above the table in a flex row:
```tsx
<div className="flex items-center gap-3 mb-4">
  <Input
    placeholder="Rechercher une action..."
    value={search}
    onChange={(e) => setSearch(e.target.value)}
    className="max-w-xs"
  />
  <select
    value={sectorFilter}
    onChange={(e) => setSectorFilter(e.target.value)}
    className="rounded-md border border-border bg-background px-3 py-2 text-sm"
  >
    <option value="all">Tous les secteurs</option>
    {sectors.filter(s => s !== "all").map(s => (
      <option key={s} value={s}>{s}</option>
    ))}
  </select>
</div>
```

**Use the shadcn `Input` component** from `@/components/ui/input` for the search field.
**Use a plain `<select>`** for the sector filter (shadcn Select is complex; a plain select is fine for V1).

---

## 3e. Sector Table — `frontend/components/dashboard/sector-table.tsx` (CREATE)

Sector aggregates view with expandable rows.

**Props**: `{ sectors: DashboardSector[], stocks: DashboardStock[] }`

### Imports

```tsx
"use client"

import { useState } from "react"
import type { DashboardSector, DashboardStock } from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_SHORT_LABELS } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { ScoreBar } from "./score-bar"
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table"
import { ChevronRight, ChevronDown } from "lucide-react"
```

### State

```typescript
const [expandedSector, setExpandedSector] = useState<string | null>(null)
```

### Columns (same family columns as stock table)

| # | Header | Cell content |
|---|--------|-------------|
| 1 | "Secteur" | Sector name + `(N actions)` in muted text. Chevron icon for expand. |
| 2 | "Tendance" | `<FamilyCell score={sector.per_family.sma} />` |
| 3 | "Momentum" | `<FamilyCell score={sector.per_family.macd} />` |
| 4 | "Oscillation" | `<FamilyCell score={sector.per_family.rsi} />` |
| 5 | "Volume" | `<FamilyCell score={sector.per_family.obv} />` |
| 6 | "Signal Global" | `<SignalBadge>` + `<ScoreBar>` |

### Expandable rows

When a sector row is clicked:
- Toggle `expandedSector` state
- If expanded, render a nested section below the sector row showing all stocks in that sector
- Filter stocks: `stocks.filter(s => s.sector === sector.sector)`
- Render the filtered stocks as a simple table (same columns as stock table, minus the Secteur column)
- Use `<ChevronRight>` when collapsed, `<ChevronDown>` when expanded

### Sorting

Default sort by `aggregate_score_pct` descending. Sort the sectors array before rendering.

### Layout

```
┌──────────────┬────┬────┬────┬────┬──────────────┐
│ Secteur      │ T  │ M  │ O  │ V  │ Signal Global│
├──────────────┼────┼────┼────┼────┼──────────────┤
│ ▶ Banques (7)│ .. │ .. │ .. │ .. │ Neutre ░░██  │
├──────────────┼────┼────┼────┼────┼──────────────┤
│ ▼ BTP (8)    │ .. │ .. │ .. │ .. │ Achat  ████  │
│  ┌───────────┼────┼────┼────┼────┼──────────────┤
│  │ CMA       │ .. │ .. │ .. │ .. │ Achat  ████  │
│  │ LHM       │ .. │ .. │ .. │ .. │ Neutre ░░░░  │
│  └───────────┼────┼────┼────┼────┼──────────────┤
├──────────────┼────┼────┼────┼────┼──────────────┤
│ ▶ Mines (6)  │ .. │ .. │ .. │ .. │ Vente  ████  │
└──────────────┴────┴────┴────┴────┴──────────────┘
```

The expanded stocks section should be visually indented (e.g., `pl-8` on the first cell) and have a slightly different background (`bg-muted/30`).

---

## 3f. Index Summary — `frontend/components/dashboard/index-summary.tsx` (CREATE)

MASI index overview card.

**Props**: `{ index: DashboardIndex }`

### Imports

```tsx
import type { DashboardIndex } from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_LABELS } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { ScoreBar } from "./score-bar"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
```

### Layout

```tsx
<Card>
  <CardHeader>
    <div className="flex items-center justify-between">
      <div>
        <CardTitle className="text-lg">MASI — Indice Global</CardTitle>
        <p className="text-sm text-muted-foreground">
          {index.stock_count} actions analysees
        </p>
      </div>
      <div className="flex items-center gap-3">
        <SignalBadge label={index.aggregate_signal_label} />
        <span className="text-lg font-mono font-bold">
          {formatScore(index.aggregate_score_pct)}
        </span>
      </div>
    </div>
  </CardHeader>
  <CardContent className="space-y-6">
    {/* 1. Family grid */}
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
      {FAMILY_ORDER.map(fam => (
        <div key={fam} className="space-y-2">
          <p className="text-sm font-medium">{FAMILY_LABELS[fam]}</p>
          <ScoreBar score={index.per_family[fam]?.score_pct ?? null} />
          <FamilyCell score={index.per_family[fam]} />
        </div>
      ))}
    </div>

    {/* 2. Breadth bar */}
    <div className="space-y-2">
      <p className="text-sm font-medium">Largeur de marche</p>
      <BreadthBar breadth={index.breadth} total={index.stock_count} />
    </div>
  </CardContent>
</Card>
```

### Breadth bar sub-component (inline in the same file)

```tsx
function BreadthBar({ breadth, total }: { breadth: DashboardBreadth; total: number }) {
  const pctAchat = total > 0 ? (breadth.achat / total) * 100 : 0
  const pctNeutre = total > 0 ? (breadth.neutre / total) * 100 : 0
  const pctVente = total > 0 ? (breadth.vente / total) * 100 : 0

  return (
    <div className="space-y-1">
      {/* Stacked horizontal bar */}
      <div className="flex h-3 w-full overflow-hidden rounded-full">
        {pctAchat > 0 && (
          <div className="bg-emerald-500" style={{ width: `${pctAchat}%` }} />
        )}
        {pctNeutre > 0 && (
          <div className="bg-zinc-400" style={{ width: `${pctNeutre}%` }} />
        )}
        {pctVente > 0 && (
          <div className="bg-red-500" style={{ width: `${pctVente}%` }} />
        )}
      </div>
      {/* Legend */}
      <div className="flex gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          {breadth.achat} Achat ({pctAchat.toFixed(0)}%)
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-zinc-400" />
          {breadth.neutre} Neutre ({pctNeutre.toFixed(0)}%)
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-red-500" />
          {breadth.vente} Vente ({pctVente.toFixed(0)}%)
        </span>
      </div>
    </div>
  )
}
```

### Import `formatScore`

```typescript
import { FAMILY_ORDER, FAMILY_LABELS, formatScore } from "@/lib/dashboard-constants"
```

Also import `DashboardBreadth` from types:
```typescript
import type { DashboardIndex, DashboardBreadth } from "@/lib/dashboard-types"
```
