import type { DashboardDisplayMode, DashboardTechnicalDirectionMode, DashboardView, Horizon } from "@/lib/dashboard-types"

export type DashboardViewMode = "masi" | "complet"
export type DashboardAssetTab = "all" | "equity" | "commodity" | "forex" | "bond" | "crypto"
export type DashboardRegionTab = "all" | "masi" | "us" | "european" | "asian"
export type DashboardFamilyColumn = "tendance" | "momentum" | "oscillation" | "volume"
export type DashboardFundamentalColumn =
  | "value"
  | "quality"
  | "upside"
  | "fair_value"
  | "pe"
  | "dividend_yield"
  | "coverage"
  | "source"
export type DashboardEdgeMode = "gross" | "net"

export type DashboardVisibleFamilies = Record<DashboardFamilyColumn, boolean>

export interface DashboardPreferences {
  showTopActionableSignals: boolean
  showFilters: boolean
  viewMode: DashboardViewMode
  assetTab: DashboardAssetTab
  regionTab: DashboardRegionTab
  horizon: Horizon
  view: DashboardView
  liquidityFilter: boolean
  dashboardMode: DashboardDisplayMode
  technicalDirectionMode: DashboardTechnicalDirectionMode
  visibleFamilies: DashboardVisibleFamilies
  fundamentalColumns: DashboardFundamentalColumn[]
  edgeOnly: boolean
  edgeMode: DashboardEdgeMode
}

export const DEFAULT_DASHBOARD_VISIBLE_FAMILIES: DashboardVisibleFamilies = {
  tendance: true,
  momentum: true,
  oscillation: true,
  volume: true,
}

export const DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS: DashboardFundamentalColumn[] = [
  "upside",
  "fair_value",
  "value",
  "quality",
  "coverage",
]

export const DEFAULT_DASHBOARD_PREFERENCES: DashboardPreferences = {
  showTopActionableSignals: true,
  showFilters: true,
  viewMode: "masi",
  assetTab: "all",
  regionTab: "all",
  horizon: "monthly",
  view: "stocks",
  liquidityFilter: false,
  dashboardMode: "trade_opportunities",
  technicalDirectionMode: "best",
  visibleFamilies: DEFAULT_DASHBOARD_VISIBLE_FAMILIES,
  fundamentalColumns: DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS,
  edgeOnly: false,
  edgeMode: "net",
}

const VIEW_MODES: DashboardViewMode[] = ["masi", "complet"]
const ASSET_TABS: DashboardAssetTab[] = ["all", "equity", "commodity", "forex", "bond", "crypto"]
const REGION_TABS: DashboardRegionTab[] = ["all", "masi", "us", "european", "asian"]
const HORIZONS: Horizon[] = ["weekly", "monthly", "quarterly"]
const VIEWS: DashboardView[] = ["stocks", "sectors", "index", "portfolio"]
const DASHBOARD_MODES: DashboardDisplayMode[] = ["trade_opportunities", "technical_directions", "fundamental_directions"]
const TECHNICAL_DIRECTION_MODES: DashboardTechnicalDirectionMode[] = ["best", "classic"]
const FAMILY_COLUMNS: DashboardFamilyColumn[] = ["tendance", "momentum", "oscillation", "volume"]
export const FUNDAMENTAL_COLUMNS: DashboardFundamentalColumn[] = [
  "upside",
  "fair_value",
  "value",
  "quality",
  "pe",
  "dividend_yield",
  "coverage",
  "source",
]
const EDGE_MODES: DashboardEdgeMode[] = ["gross", "net"]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === "string" && allowed.includes(value as T) ? (value as T) : fallback
}

function sanitizeVisibleFamilies(value: unknown): DashboardVisibleFamilies {
  const raw = isRecord(value) ? value : {}
  return Object.fromEntries(
    FAMILY_COLUMNS.map((family) => [
      family,
      booleanValue(raw[family], DEFAULT_DASHBOARD_VISIBLE_FAMILIES[family]),
    ]),
  ) as DashboardVisibleFamilies
}

export function sanitizeFundamentalColumns(value: unknown): DashboardFundamentalColumn[] {
  if (!Array.isArray(value)) return DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS
  const seen = new Set<DashboardFundamentalColumn>()
  for (const item of value) {
    if (typeof item === "string" && FUNDAMENTAL_COLUMNS.includes(item as DashboardFundamentalColumn)) {
      seen.add(item as DashboardFundamentalColumn)
    }
  }
  return seen.size ? Array.from(seen) : DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS
}

export function sanitizeDashboardPreferences(raw: unknown): DashboardPreferences {
  const value = isRecord(raw) ? raw : {}
  return {
    showTopActionableSignals: booleanValue(
      value.showTopActionableSignals,
      DEFAULT_DASHBOARD_PREFERENCES.showTopActionableSignals,
    ),
    showFilters: booleanValue(value.showFilters, DEFAULT_DASHBOARD_PREFERENCES.showFilters),
    viewMode: enumValue(value.viewMode, VIEW_MODES, DEFAULT_DASHBOARD_PREFERENCES.viewMode),
    assetTab: enumValue(value.assetTab, ASSET_TABS, DEFAULT_DASHBOARD_PREFERENCES.assetTab),
    regionTab: enumValue(value.regionTab, REGION_TABS, DEFAULT_DASHBOARD_PREFERENCES.regionTab),
    horizon: enumValue(value.horizon, HORIZONS, DEFAULT_DASHBOARD_PREFERENCES.horizon),
    view: enumValue(value.view, VIEWS, DEFAULT_DASHBOARD_PREFERENCES.view),
    liquidityFilter: booleanValue(value.liquidityFilter, DEFAULT_DASHBOARD_PREFERENCES.liquidityFilter),
    dashboardMode: enumValue(value.dashboardMode, DASHBOARD_MODES, DEFAULT_DASHBOARD_PREFERENCES.dashboardMode),
    technicalDirectionMode: enumValue(
      value.technicalDirectionMode,
      TECHNICAL_DIRECTION_MODES,
      DEFAULT_DASHBOARD_PREFERENCES.technicalDirectionMode,
    ),
    visibleFamilies: sanitizeVisibleFamilies(value.visibleFamilies),
    fundamentalColumns: sanitizeFundamentalColumns(value.fundamentalColumns),
    edgeOnly: booleanValue(value.edgeOnly, DEFAULT_DASHBOARD_PREFERENCES.edgeOnly),
    edgeMode: enumValue(value.edgeMode, EDGE_MODES, DEFAULT_DASHBOARD_PREFERENCES.edgeMode),
  }
}
