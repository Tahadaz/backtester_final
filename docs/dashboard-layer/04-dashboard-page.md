# 04 — Dashboard Page

## Overview

Create `frontend/app/dashboard/page.tsx` — the main page that assembles all dashboard components.

---

## File: `frontend/app/dashboard/page.tsx` (CREATE)

### Complete implementation

```tsx
"use client"

import { useState } from "react"
import { useDashboardData } from "@/hooks/use-dashboard"
import type { Horizon, DashboardView } from "@/lib/dashboard-types"
import { HORIZONS, VIEWS } from "@/lib/dashboard-constants"
import { StockTable } from "@/components/dashboard/stock-table"
import { SectorTable } from "@/components/dashboard/sector-table"
import { IndexSummary } from "@/components/dashboard/index-summary"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { AlertCircle } from "lucide-react"

export default function DashboardPage() {
  const [horizon, setHorizon] = useState<Horizon>("medium")
  const [view, setView] = useState<DashboardView>("stocks")

  const { data, error, isLoading } = useDashboardData(horizon)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Tableau de Bord</h1>
        <p className="text-sm text-muted-foreground">
          Signaux techniques — Marche MASI
          {data && (
            <span className="ml-2">
              · Mis a jour le {new Date(data.generated_at).toLocaleDateString("fr-FR")}
            </span>
          )}
        </p>
      </div>

      {/* Horizon tabs */}
      <Tabs value={horizon} onValueChange={(v) => setHorizon(v as Horizon)}>
        <TabsList>
          {HORIZONS.map((h) => (
            <TabsTrigger key={h.value} value={h.value} className="text-xs">
              {h.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* View toggle */}
      <div className="flex gap-1">
        {VIEWS.map((v) => (
          <button
            key={v.value}
            onClick={() => setView(v.value)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              view === v.value
                ? "bg-secondary text-secondary-foreground"
                : "text-muted-foreground hover:bg-muted"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* Loading state */}
      {isLoading && <LoadingSkeleton />}

      {/* Error state */}
      {error && <ErrorCard message={error.message} />}

      {/* Content */}
      {data && (
        <>
          {view === "stocks" && <StockTable stocks={data.stocks} />}
          {view === "sectors" && (
            <SectorTable sectors={data.sectors} stocks={data.stocks} />
          )}
          {view === "index" && <IndexSummary index={data.index} />}
        </>
      )}

      {/* Empty data state */}
      {data && data.stocks.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">
              Aucune donnee disponible. Chargez des donnees de marche depuis la page{" "}
              <a href="/data" className="underline">Data</a>.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-96 rounded-lg" />
    </div>
  )
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card className="border-destructive">
      <CardContent className="flex items-center gap-3 py-6">
        <AlertCircle className="h-5 w-5 text-destructive" />
        <div>
          <p className="font-medium text-destructive">Erreur de chargement</p>
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      </CardContent>
    </Card>
  )
}
```

### Key design decisions

1. **Horizon tabs use shadcn `Tabs`** — these affect which JSON file is loaded (triggers SWR refetch)
2. **View toggle uses plain buttons** — these only change which component renders (no data fetch)
3. **The two control groups are visually separate** — horizon tabs are styled as TabsList, view toggle is styled as plain buttons with active state
4. **Loading skeleton** matches the pattern used on the signals page
5. **Error card** uses destructive border color, same pattern as existing error states
6. **Empty state** directs user to the `/data` page to load market data
7. **Date formatting** uses `toLocaleDateString("fr-FR")` for French date format

### What NOT to do

- Do NOT use `"use client"` on any server component. This page needs it because of `useState` and SWR.
- Do NOT import from `@/lib/api` or `@/hooks/use-api`. The dashboard uses its own hook.
- Do NOT add a cooldown control. The dashboard always uses `cooldown_bars=0` (set in the export script).
