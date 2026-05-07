# 02 — Types and Constants

## Overview

Create two files:
1. `frontend/lib/dashboard-types.ts` — TypeScript interfaces matching the JSON shape exactly
2. `frontend/lib/dashboard-constants.ts` — Family labels, signal colors, helper functions
3. `frontend/hooks/use-dashboard.ts` — SWR hook that loads the static JSON

---

## File: `frontend/lib/dashboard-types.ts` (CREATE)

```typescript
// Dashboard data types — mirrors the JSON shape from export-scores.py exactly.

export interface FamilyScore {
  score_pct: number
  label: string
}

export interface CategoryScore {
  score_pct: number
  label: string
  families: string[]
}

export interface DashboardStock {
  symbol: string
  display_name: string | null
  sector: string | null
  aggregate_score_pct: number | null
  aggregate_signal_label: string | null
  per_family: Record<string, FamilyScore>
  categories: Record<string, CategoryScore>
}

export interface DashboardSector {
  sector: string
  stock_count: number
  aggregate_score_pct: number
  aggregate_signal_label: string
  per_family: Record<string, FamilyScore>
}

export interface DashboardBreadth {
  achat: number
  neutre: number
  vente: number
  indisponible: number
}

export interface DashboardIndex {
  name: string
  stock_count: number
  aggregate_score_pct: number
  aggregate_signal_label: string
  per_family: Record<string, FamilyScore>
  breadth: DashboardBreadth
}

export interface DashboardData {
  generated_at: string
  horizon: string
  horizon_label: string
  stocks: DashboardStock[]
  sectors: DashboardSector[]
  index: DashboardIndex
}

export type DashboardView = "stocks" | "sectors" | "index"
export type Horizon = "short" | "medium" | "long"
```

---

## File: `frontend/lib/dashboard-constants.ts` (CREATE)

```typescript
// Dashboard constants — labels, colors, and helpers shared by all dashboard components.

/** Horizon tab configuration */
export const HORIZONS = [
  { value: "short" as const, label: "Court terme" },
  { value: "medium" as const, label: "Moyen terme" },
  { value: "long" as const, label: "Long terme" },
] as const

/** View tab configuration */
export const VIEWS = [
  { value: "stocks" as const, label: "Actions" },
  { value: "sectors" as const, label: "Secteurs" },
  { value: "index" as const, label: "Indice MASI" },
] as const

/** Internal family key -> French UI label (long form) */
export const FAMILY_LABELS: Record<string, string> = {
  sma: "Tendance (SMA)",
  macd: "Momentum (MACD)",
  rsi: "Mean Reversion (RSI)",
  obv: "Volume (OBV)",
}

/** Short family labels for table column headers */
export const FAMILY_SHORT_LABELS: Record<string, string> = {
  sma: "Tendance",
  macd: "Momentum",
  rsi: "Oscillation",
  obv: "Volume",
}

/** Family display order — always render families in this order */
export const FAMILY_ORDER = ["sma", "macd", "rsi", "obv"] as const

/**
 * Signal label -> Tailwind badge classes.
 *
 * These labels come directly from signal_type_label() in
 * core/quant_core/signal_engine/domain.py:38-84.
 * They have NO accents (e.g. "Tres" not "Tres", "Surachete" not "Surachete").
 * Do NOT add accents here.
 */
export const SIGNAL_BADGE_COLORS: Record<string, string> = {
  // Trend family (SMA, MACD)
  "Tres haussier":      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  "Haussier":           "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  "Neutre":             "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400",
  "Baissier":           "bg-red-500/10 text-red-600 dark:text-red-400",
  "Tres baissier":      "bg-red-500/15 text-red-700 dark:text-red-400",

  // Oscillator family (RSI)
  "Tres survendu":      "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  "Survendu":           "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  "Normal":             "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400",
  "Surachete":          "bg-red-500/10 text-red-600 dark:text-red-400",
  "Tres surachete":     "bg-red-500/15 text-red-700 dark:text-red-400",

  // Volume family (OBV)
  "Forte accumulation": "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  "Accumulation":       "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  // "Neutre" already covered above
  "Distribution":       "bg-red-500/10 text-red-600 dark:text-red-400",
  "Forte distribution": "bg-red-500/15 text-red-700 dark:text-red-400",

  // Aggregate labels
  "Achat fort":         "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  "Achat":              "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  "Vente":              "bg-red-500/10 text-red-600 dark:text-red-400",
  "Vente forte":        "bg-red-500/15 text-red-700 dark:text-red-400",
}

/** Default fallback color when a label is not found in SIGNAL_BADGE_COLORS */
export const SIGNAL_BADGE_FALLBACK = "bg-zinc-500/10 text-zinc-600 dark:text-zinc-400"

/** Return Tailwind bg class for a score bar segment */
export function scoreBarColor(score: number): string {
  if (score > 15) return "bg-emerald-500"
  if (score < -15) return "bg-red-500"
  return "bg-zinc-400"
}

/** Format a score with explicit sign: "+45.2" or "-12.0" */
export function formatScore(score: number): string {
  const sign = score > 0 ? "+" : ""
  return `${sign}${score.toFixed(1)}`
}
```

---

## File: `frontend/hooks/use-dashboard.ts` (CREATE)

```typescript
"use client"

import useSWR from "swr"
import type { DashboardData, Horizon } from "@/lib/dashboard-types"

async function fetchDashboardData(horizon: Horizon): Promise<DashboardData> {
  const base = process.env.NEXT_PUBLIC_BASE_PATH || ""
  const res = await fetch(`${base}/data/scores-${horizon}.json`)
  if (!res.ok) throw new Error(`Failed to load dashboard data: ${res.status}`)
  return res.json()
}

export function useDashboardData(horizon: Horizon) {
  return useSWR<DashboardData>(
    `dashboard-${horizon}`,
    () => fetchDashboardData(horizon),
    { revalidateOnFocus: false }
  )
}
```

### Why `NEXT_PUBLIC_BASE_PATH`?

When deployed to GitHub Pages, the app lives at `https://<user>.github.io/<repo-name>/`.
Next.js automatically handles `basePath` for `<Link>` components, but raw `fetch()` calls
need the base path prepended manually. This env variable is empty in local dev and set to
`/<repo-name>` during the GitHub Pages build (see doc 06).

### Why `revalidateOnFocus: false`?

The data is static JSON — it doesn't change between tab focuses. Matches the existing
pattern used by `useBatchScores` in `hooks/use-api.ts:466-476`.
