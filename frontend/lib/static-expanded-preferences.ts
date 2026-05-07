"use client"

import { useEffect, useMemo, useState } from "react"
import {
  INDICATOR_FAMILY_ORDER,
  INDICATOR_META_BY_KEY,
  type IndicatorFamilyKey,
} from "@/components/strategy/indicator-config"
import {
  FAMILY_LABELS,
  FAMILY_ORDER,
  aggregateScoreLabel,
  familyScoreLabel,
} from "@/lib/dashboard-constants"
import type {
  DashboardBreadth,
  DashboardIndex,
  DashboardSector,
  DashboardStock,
  FamilyScore,
  SignalEngineScores,
  WfoScores,
} from "@/lib/dashboard-types"
import type { PublicFamilySignalDetail, PublicSignalsStock } from "@/lib/public-signals-types"

export type ExpandedCategoryKey = (typeof FAMILY_ORDER)[number]
export type ExpandedFamilyKey = IndicatorFamilyKey
export type ExpandedFamilySelection = Record<ExpandedFamilyKey, boolean>
export type ExpandedStockOverrideMap = Record<string, ExpandedFamilySelection>

type ScoredFamilyValue =
  | FamilyScore
  | PublicFamilySignalDetail
  | null
  | undefined

const STORAGE_VERSION = "v1"
export const GLOBAL_EXPANDED_SELECTION_STORAGE_KEY = `public-expanded-family-selection:${STORAGE_VERSION}`
export const STOCK_EXPANDED_OVERRIDES_STORAGE_KEY = `public-expanded-family-overrides:${STORAGE_VERSION}`

const INDICATOR_CATEGORY_TO_EXPANDED: Record<
  "tendance" | "momentum" | "oscillation" | "volume",
  ExpandedCategoryKey
> = {
  tendance: "tendance",
  momentum: "momentum",
  oscillation: "oscillation",
  volume: "volume",
}

export const EXPANDED_FAMILY_ORDER = INDICATOR_FAMILY_ORDER

export const EXPANDED_FAMILY_LABELS: Record<ExpandedFamilyKey, string> = Object.fromEntries(
  INDICATOR_FAMILY_ORDER.map((family) => [family, INDICATOR_META_BY_KEY[family].shortLabel]),
) as Record<ExpandedFamilyKey, string>

export const EXPANDED_CATEGORY_FAMILIES = FAMILY_ORDER.reduce(
  (acc, category) => {
    acc[category] = INDICATOR_FAMILY_ORDER.filter(
      (family) => INDICATOR_CATEGORY_TO_EXPANDED[INDICATOR_META_BY_KEY[family].category] === category,
    )
    return acc
  },
  {} as Record<ExpandedCategoryKey, ExpandedFamilyKey[]>,
)

export function createAllExpandedFamilySelection(): ExpandedFamilySelection {
  return Object.fromEntries(
    INDICATOR_FAMILY_ORDER.map((family) => [family, true]),
  ) as ExpandedFamilySelection
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  const total = values.reduce((sum, value) => sum + value, 0)
  return total / values.length
}

function getNumericFamilyScore(value: ScoredFamilyValue): number | null {
  if (!value) return null
  if ("score_pct" in value) {
    return typeof value.score_pct === "number" ? value.score_pct : null
  }
  return typeof value.family_score_pct === "number" ? value.family_score_pct : null
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

export function normalizeExpandedFamilySelection(raw: unknown): ExpandedFamilySelection {
  const selection = createAllExpandedFamilySelection()
  if (!isPlainObject(raw)) return selection
  for (const family of INDICATOR_FAMILY_ORDER) {
    if (typeof raw[family] === "boolean") {
      selection[family] = raw[family]
    }
  }
  return selection
}

export function selectionsEqual(
  left: ExpandedFamilySelection,
  right: ExpandedFamilySelection,
): boolean {
  return INDICATOR_FAMILY_ORDER.every((family) => left[family] === right[family])
}

function sanitizeStockOverrideMap(raw: unknown): ExpandedStockOverrideMap {
  if (!isPlainObject(raw)) return {}
  const next: ExpandedStockOverrideMap = {}
  for (const [symbol, value] of Object.entries(raw)) {
    const normalizedSymbol = symbol.trim().toUpperCase()
    if (!normalizedSymbol) continue
    next[normalizedSymbol] = normalizeExpandedFamilySelection(value)
  }
  return next
}

function safeReadStorage<T>(key: string, fallback: T, parse: (raw: unknown) => T): T {
  if (typeof window === "undefined") return fallback
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return fallback
    return parse(JSON.parse(raw))
  } catch {
    return fallback
  }
}

function safeWriteStorage(key: string, value: unknown) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // ignore storage write failures
  }
}

export function readGlobalExpandedSelection(): ExpandedFamilySelection {
  return safeReadStorage(
    GLOBAL_EXPANDED_SELECTION_STORAGE_KEY,
    createAllExpandedFamilySelection(),
    normalizeExpandedFamilySelection,
  )
}

export function readStockExpandedOverrides(): ExpandedStockOverrideMap {
  return safeReadStorage(
    STOCK_EXPANDED_OVERRIDES_STORAGE_KEY,
    {},
    sanitizeStockOverrideMap,
  )
}

export function resolveExpandedFamilySelection(
  globalSelection: ExpandedFamilySelection | null | undefined,
  stockOverrides: ExpandedStockOverrideMap | null | undefined,
  symbol?: string | null,
): ExpandedFamilySelection {
  const normalizedGlobal = globalSelection ?? createAllExpandedFamilySelection()
  const normalizedSymbol = symbol?.trim().toUpperCase()
  if (!normalizedSymbol) {
    return normalizedGlobal
  }
  return stockOverrides?.[normalizedSymbol] ?? normalizedGlobal
}

export function countEnabledFamilies(
  selection: ExpandedFamilySelection,
  category?: ExpandedCategoryKey,
): number {
  const families = category ? EXPANDED_CATEGORY_FAMILIES[category] : INDICATOR_FAMILY_ORDER
  return families.filter((family) => selection[family]).length
}

export function computeSelectedFamilyScore(
  familyMap: Partial<Record<ExpandedFamilyKey, ScoredFamilyValue>> | undefined,
  selection: ExpandedFamilySelection,
  families: readonly ExpandedFamilyKey[],
): number | null {
  const values = families
    .filter((family) => selection[family])
    .map((family) => getNumericFamilyScore(familyMap?.[family]))
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value))

  return average(values)
}

export function computeSelectedAggregateScore(
  familyMap: Partial<Record<ExpandedFamilyKey, ScoredFamilyValue>> | undefined,
  selection: ExpandedFamilySelection,
): number | null {
  return computeSelectedFamilyScore(familyMap, selection, INDICATOR_FAMILY_ORDER)
}

export function computeSelectedCategoryScores(
  familyMap: Partial<Record<ExpandedFamilyKey, ScoredFamilyValue>> | undefined,
  selection: ExpandedFamilySelection,
): Record<ExpandedCategoryKey, FamilyScore | undefined> {
  return FAMILY_ORDER.reduce(
    (acc, category) => {
      const score = computeSelectedFamilyScore(
        familyMap,
        selection,
        EXPANDED_CATEGORY_FAMILIES[category],
      )
      if (score == null) {
        acc[category] = undefined
        return acc
      }
      acc[category] = {
        score_pct: round2(score),
        label: familyScoreLabel(category, score),
      }
      return acc
    },
    {} as Record<ExpandedCategoryKey, FamilyScore | undefined>,
  )
}

export function countAvailableActiveFamilies(
  familyMap: Partial<Record<ExpandedFamilyKey, ScoredFamilyValue>> | undefined,
  selection: ExpandedFamilySelection,
  category: ExpandedCategoryKey,
): number {
  return EXPANDED_CATEGORY_FAMILIES[category].filter((family) => {
    if (!selection[family]) return false
    return getNumericFamilyScore(familyMap?.[family]) != null
  }).length
}

export function transformDashboardStockForExpandedSelection(
  stock: DashboardStock,
  publicStock: PublicSignalsStock | null | undefined,
  selection: ExpandedFamilySelection,
): DashboardStock {
  if (!publicStock) return stock

  const aggregateScore = computeSelectedAggregateScore(publicStock.families, selection)
  const perCategory = computeSelectedCategoryScores(publicStock.families, selection)

  const newAggregatePct = aggregateScore == null ? null : round2(aggregateScore)
  const newAggregateLabel = aggregateScore == null ? null : aggregateScoreLabel(aggregateScore)
  const newPerFamily = FAMILY_ORDER.reduce(
    (acc, category) => {
      const score = perCategory[category]
      if (score) acc[category] = score
      return acc
    },
    {} as Record<string, FamilyScore>,
  )

  const updatedSignalEngine: SignalEngineScores = {
    ...stock.scores.signal_engine,
    aggregate_score_pct: newAggregatePct,
    aggregate_signal_label: newAggregateLabel,
    expanded_aggregate_score_pct: newAggregatePct,
    expanded_aggregate_signal_label: newAggregateLabel,
    per_family: newPerFamily,
    expanded_per_family: newPerFamily,
  }

  return {
    ...stock,
    scores: { ...stock.scores, signal_engine: updatedSignalEngine },
  }
}

function breadthFromStocks(
  stocks: DashboardStock[],
  source: "signal_engine" | "wfo" = "signal_engine",
): DashboardBreadth {
  let achat = 0
  let neutre = 0
  let vente = 0
  let indisponible = 0

  for (const stock of stocks) {
    const label = stock.scores[source]?.aggregate_signal_label
    if (!label) {
      indisponible += 1
      continue
    }
    if (label.includes("Achat")) {
      achat += 1
      continue
    }
    if (label.includes("Vente")) {
      vente += 1
      continue
    }
    neutre += 1
  }

  return { achat, neutre, vente, indisponible }
}

function emptySignalEngineScores(): SignalEngineScores {
  return {
    variant: "expanded",
    aggregate_score_pct: null,
    aggregate_signal_label: null,
    expanded_aggregate_score_pct: null,
    expanded_aggregate_signal_label: null,
    per_family: {},
    expanded_per_family: {},
  }
}

export function recomputeDashboardSectors(
  stocks: DashboardStock[],
  source: "signal_engine" | "wfo" | "both" = "signal_engine",
): DashboardSector[] {
  const grouped = new Map<string, DashboardStock[]>()

  for (const stock of stocks) {
    const sector = stock.sector ?? "Autre"
    if (!grouped.has(sector)) {
      grouped.set(sector, [])
    }
    grouped.get(sector)!.push(stock)
  }

  return Array.from(grouped.entries()).map(([sector, members]) => {
    const computeSourceScores = (activeSource: "signal_engine" | "wfo") => {
      const sourceMembers = members.filter((member) => member.scores[activeSource] != null)
      const aggregateScore = average(
        sourceMembers
          .map((member) => member.scores[activeSource]?.aggregate_score_pct)
          .filter((value): value is number => typeof value === "number"),
      )

      const perFamily = FAMILY_ORDER.reduce(
        (acc, category) => {
          const score = average(
            sourceMembers
              .map((member) => member.scores[activeSource]?.per_family[category]?.score_pct)
              .filter((value): value is number => typeof value === "number"),
          )
          if (score == null) return acc
          acc[category] = {
            score_pct: round2(score),
            label: familyScoreLabel(category, score),
          }
          return acc
        },
        {} as Record<string, FamilyScore>,
      )

      return {
        aggregateScore,
        aggregateScoreRounded: aggregateScore == null ? null : round2(aggregateScore),
        aggregateLabel: aggregateScore == null ? null : aggregateScoreLabel(aggregateScore),
        perFamily,
      }
    }

    const seSummary = source === "wfo" ? null : computeSourceScores("signal_engine")
    const wfoSummary = source === "signal_engine" ? null : computeSourceScores("wfo")

    const seScores: SignalEngineScores =
      seSummary == null
        ? emptySignalEngineScores()
        : {
            variant: "expanded",
            aggregate_score_pct: seSummary.aggregateScoreRounded,
            aggregate_signal_label: seSummary.aggregateLabel,
            expanded_aggregate_score_pct: seSummary.aggregateScoreRounded,
            expanded_aggregate_signal_label: seSummary.aggregateLabel,
            per_family: seSummary.perFamily,
            expanded_per_family: seSummary.perFamily,
          }

    const wfoScores: WfoScores | null =
      wfoSummary == null
        ? null
        : {
            variant: "expanded",
            aggregate_score_pct: wfoSummary.aggregateScoreRounded,
            aggregate_signal_label: wfoSummary.aggregateLabel,
            per_family: wfoSummary.perFamily,
            status: "succeeded",
          }

    return {
      sector,
      stock_count: members.length,
      scores: { signal_engine: seScores, wfo: wfoScores },
    }
  })
}

export function recomputeDashboardIndex(
  name: string,
  stocks: DashboardStock[],
  source: "signal_engine" | "wfo" | "both" = "signal_engine",
): DashboardIndex {
  const computeSourceScores = (activeSource: "signal_engine" | "wfo") => {
    const sourceStocks = stocks.filter((stock) => stock.scores[activeSource] != null)
    const aggregateScore = average(
      sourceStocks
        .map((stock) => stock.scores[activeSource]?.aggregate_score_pct)
        .filter((value): value is number => typeof value === "number"),
    )

    const perFamily = FAMILY_ORDER.reduce(
      (acc, category) => {
        const score = average(
          sourceStocks
            .map((stock) => stock.scores[activeSource]?.per_family[category]?.score_pct)
            .filter((value): value is number => typeof value === "number"),
        )
        if (score == null) return acc
        acc[category] = {
          score_pct: round2(score),
          label: familyScoreLabel(category, score),
        }
        return acc
      },
      {} as Record<string, FamilyScore>,
    )

    return {
      aggregateScoreRounded: aggregateScore == null ? null : round2(aggregateScore),
      aggregateLabel: aggregateScore == null ? null : aggregateScoreLabel(aggregateScore),
      perFamily,
      breadth: breadthFromStocks(stocks, activeSource),
    }
  }

  const seSummary = source === "wfo" ? null : computeSourceScores("signal_engine")
  const wfoSummary = source === "signal_engine" ? null : computeSourceScores("wfo")

  const seScores: SignalEngineScores =
    seSummary == null
      ? emptySignalEngineScores()
      : {
          variant: "expanded",
          aggregate_score_pct: seSummary.aggregateScoreRounded,
          aggregate_signal_label: seSummary.aggregateLabel,
          expanded_aggregate_score_pct: seSummary.aggregateScoreRounded,
          expanded_aggregate_signal_label: seSummary.aggregateLabel,
          per_family: seSummary.perFamily,
          expanded_per_family: seSummary.perFamily,
          breadth: seSummary.breadth,
        }

  const wfoScores: WfoScores | null =
    wfoSummary == null
      ? null
      : {
          variant: "expanded",
          aggregate_score_pct: wfoSummary.aggregateScoreRounded,
          aggregate_signal_label: wfoSummary.aggregateLabel,
          per_family: wfoSummary.perFamily,
          status: "succeeded",
          breadth: wfoSummary.breadth,
        }

  return {
    name,
    stock_count: stocks.length,
    scores: { signal_engine: seScores, wfo: wfoScores },
  }
}

export function useExpandedFamilyPreferences() {
  const [globalSelection, setGlobalSelection] = useState<ExpandedFamilySelection>(() =>
    createAllExpandedFamilySelection(),
  )
  const [stockOverrides, setStockOverrides] = useState<ExpandedStockOverrideMap>({})
  const [hydrated, setHydrated] = useState(false)

  useEffect(() => {
    setGlobalSelection(readGlobalExpandedSelection())
    setStockOverrides(readStockExpandedOverrides())
    setHydrated(true)
  }, [])

  useEffect(() => {
    if (!hydrated) return
    safeWriteStorage(GLOBAL_EXPANDED_SELECTION_STORAGE_KEY, globalSelection)
  }, [globalSelection, hydrated])

  useEffect(() => {
    if (!hydrated) return
    safeWriteStorage(STOCK_EXPANDED_OVERRIDES_STORAGE_KEY, stockOverrides)
  }, [hydrated, stockOverrides])

  const helpers = useMemo(
    () => ({
      getEffectiveSelection(symbol?: string | null) {
        return resolveExpandedFamilySelection(globalSelection, stockOverrides, symbol)
      },
      hasStockOverride(symbol?: string | null) {
        const normalizedSymbol = symbol?.trim().toUpperCase()
        return normalizedSymbol ? Boolean(stockOverrides[normalizedSymbol]) : false
      },
      setGlobalFamilyEnabled(family: ExpandedFamilyKey, enabled: boolean) {
        setGlobalSelection((prev) => ({
          ...prev,
          [family]: enabled,
        }))
      },
      resetGlobalSelection() {
        setGlobalSelection(createAllExpandedFamilySelection())
      },
      setStockFamilyEnabled(symbol: string, family: ExpandedFamilyKey, enabled: boolean) {
        const normalizedSymbol = symbol.trim().toUpperCase()
        if (!normalizedSymbol) return
        setStockOverrides((prev) => {
          const base = resolveExpandedFamilySelection(globalSelection, prev, normalizedSymbol)
          const nextSelection = {
            ...base,
            [family]: enabled,
          }
          if (selectionsEqual(nextSelection, globalSelection)) {
            const { [normalizedSymbol]: _ignored, ...rest } = prev
            return rest
          }
          return {
            ...prev,
            [normalizedSymbol]: nextSelection,
          }
        })
      },
      resetStockOverride(symbol: string) {
        const normalizedSymbol = symbol.trim().toUpperCase()
        if (!normalizedSymbol) return
        setStockOverrides((prev) => {
          const { [normalizedSymbol]: _ignored, ...rest } = prev
          return rest
        })
      },
    }),
    [globalSelection, stockOverrides],
  )

  return {
    hydrated,
    globalSelection,
    stockOverrides,
    categoryLabels: FAMILY_LABELS,
    categoryOrder: FAMILY_ORDER,
    familyOrder: EXPANDED_FAMILY_ORDER,
    familyLabels: EXPANDED_FAMILY_LABELS,
    categoryFamilies: EXPANDED_CATEGORY_FAMILIES,
    ...helpers,
  }
}
