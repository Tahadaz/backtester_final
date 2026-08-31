"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import { AlertCircle, ArrowLeft, BookOpen, Download, ExternalLink, Eye, EyeOff, Filter, LayoutDashboard, Plus, RefreshCw, Save, Search, X, Zap } from "lucide-react"
import { useDashboardData } from "@/hooks/use-dashboard"
import { useDashboardIndices } from "@/hooks/use-dashboard-indices"
import { useDashboardPreferences } from "@/hooks/use-dashboard-preferences"
import { useMarketCatalog } from "@/hooks/use-api"
import {
  createDashboardIndex,
  deleteDashboardIndex,
  createDashboardPortfolio,
  createDashboardPortfolioFromHistory,
  fetchBourseLiveQuotes,
  fetchBourseSessionStatus,
  fetchDashboardDailyBlotter,
  fetchDashboardLiveRefresh,
  fetchValueSignal,
  type ValueSignalResponse,
  type ValueSignalRow,
  fetchDashboardNamedPortfolioSummary,
  fetchDashboardPortfolioLoadState,
  fetchDashboardPortfolioPositions,
  fetchEdge,
  generateDashboardPortfolioHistory,
  recordDashboardNamedPortfolioTrade,
  runDashboardPortfolioBacktest,
  saveDashboardPortfolioPositions,
  updateDashboardPortfolio,
  updateDashboardIndex,
  type BourseLiveQuote,
  type BourseSessionStatus,
  type DashboardLiveRefreshOverlay,
  type DashboardDailyBlotterResponse,
  type DashboardCustomIndexComponent,
  type DashboardManualPosition,
  type DashboardPortfolio,
  type DashboardPortfolioComponent,
  type DashboardPortfolioLoadState,
  type DashboardPortfolioSummary,
  type DashboardPortfolioTicketResponse,
  type DashboardPortfolioTradeInput,
  type EdgeMetrics,
  type FundamentalCrossSectionRow,
} from "@/lib/api"
import type {
  DashboardDisplayMode,
  DashboardCustomIndexDefinition,
  DashboardScoreSource,
  DashboardStock,
  DashboardTechnicalDirectionMode,
  DashboardView,
  Horizon,
} from "@/lib/dashboard-types"
import {
  DEFAULT_DASHBOARD_PREFERENCES,
  DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS,
  DEFAULT_DASHBOARD_VISIBLE_FAMILIES,
  type DashboardAssetTab as AssetTab,
  type DashboardEdgeMode as EdgeMode,
  type DashboardFamilyColumn as FamilyColumn,
  type DashboardFundamentalColumn as FundamentalColumn,
  type DashboardPreferences,
  type DashboardRegionTab as RegionTab,
  type DashboardViewMode as ViewMode,
} from "@/lib/dashboard-preferences"
import { resolveHorizonPreset } from "@/lib/horizon"
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import {
  BUILTIN_CUSTOM_DASHBOARD_INDICES,
  BUILTIN_WEIGHTED_MASI_INDEX,
} from "@/lib/builtin-dashboard-indices"
import { IndexTab } from "@/components/dashboard-v1/index-tab"
import { SectorTable } from "@/components/dashboard-v1/sector-table"
import { StockTable } from "@/components/dashboard-v1/stock-table"
import { FundamentalDirectionsTab } from "@/components/dashboard-v1/fundamental-directions-tab"
import { applyDashboardLiveOverlays } from "@/components/dashboard-v1/live-overlay-utils.mjs"
import { displayVariantLabel, technicalSignalForDisplay } from "@/components/dashboard-v1/best-signal-cells"
import { buildPortfolioWeightRows, summarizeWeightRows } from "@/components/dashboard-v1/sector-portfolio-utils.mjs"
import { SetupStep } from "@/components/dashboard/setup-step"
import { KpiTile } from "@/components/dashboard/kpi-tile"
import { EdgePanel } from "@/components/dashboard/edge-panel"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const edgeEnabled = process.env.NEXT_PUBLIC_EDGE_ENABLED !== "false"
const EDGE_COST_BPS = 33
const ADV_THRESHOLD = 1_000_000
const EMPTY_DASHBOARD_POSITIONS: DashboardManualPosition[] = []

const DASHBOARD_HORIZONS = [
  { value: "weekly" as const, label: "Hebdomadaire" },
  { value: "monthly" as const, label: "Mensuel" },
  { value: "quarterly" as const, label: "Trimestriel" },
]

const STOCK_VIEW_OPTIONS = [
  { value: "stocks" as const, label: "Stocks" },
  { value: "sectors" as const, label: "Sectors" },
  { value: "index" as const, label: "Indices" },
  { value: "portfolio" as const, label: "Portfolio" },
]

type PerformancePeriod = "one_day" | "wtd" | "mtd" | "ytd" | "open_to_now"

const DASHBOARD_MODE_OPTIONS = [
  { value: "trade_opportunities" as const, label: "Trade opportunities" },
  { value: "technical_directions" as const, label: "Technical directions" },
  { value: "fundamental_directions" as const, label: "Fondamental" },
]

const TECHNICAL_DIRECTION_MODE_OPTIONS = [
  { value: "best" as const, label: "Best" },
  { value: "classic" as const, label: "Classic" },
]

function evidenceProofHref(raw: string): string {
  try {
    const url = new URL(raw, "http://local")
    url.searchParams.set("tab", "evidence")
    return `${url.pathname}${url.search}${url.hash}`
  } catch {
    const joiner = raw.includes("?") ? "&" : "?"
    return raw.includes("tab=evidence") ? raw : `${raw}${joiner}tab=evidence`
  }
}

const FAMILY_COLUMN_OPTIONS: { value: FamilyColumn; label: string }[] = [
  { value: "tendance", label: "Trend." },
  { value: "momentum", label: "Mom." },
  { value: "oscillation", label: "Osc." },
  { value: "volume", label: "Vol." },
]

function median(values: number[]) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[mid]
  return (sorted[mid - 1] + sorted[mid]) / 2
}

function formatInteger(value: number | null) {
  if (value == null || !Number.isFinite(value)) return "--"
  return Math.round(value).toLocaleString("fr-FR")
}

function formatMoney(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${Math.round(value).toLocaleString("fr-FR")} MAD`
}

function formatDecimal(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  return value.toLocaleString("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function technicalModeShortLabel(mode: DashboardTechnicalDirectionMode) {
  return mode === "classic" ? "classic" : "best"
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  return Math.min(max, Math.max(min, value))
}

function isMasiEquity(stock: DashboardStock) {
  return (stock.asset_class ?? "equity") === "equity"
    && (stock.asset_type ?? "equity") === "equity"
    && stock.market_region === "masi"
}

function hasAvailableWfoSignal(stock: DashboardStock) {
  const wfo = stock.scores.wfo
  const label = wfo?.aggregate_signal_label?.trim().toLowerCase()
  return Boolean(
    wfo
    && wfo.aggregate_score_pct != null
    && Number.isFinite(wfo.aggregate_score_pct)
    && label
    && label !== "indisponible"
    && label !== "unavailable",
  )
}

function bestActionableSignal(stock: DashboardStock, opts?: { excludeMasiShorts?: boolean }) {
  const signal = stock.best_signal ?? null
  if (!signal) return null
  if (signal.source !== "wfo") return null
  if (!hasAvailableWfoSignal(stock)) return null
  if (signal.direction === "none" || signal.bucket === "hold") return null
  if (opts?.excludeMasiShorts && isMasiEquity(stock) && signal.direction === "short") return null
  if ((signal.bucket === "buy" || signal.bucket === "strong_buy") && signal.direction !== "long") return null
  if ((signal.bucket === "sell" || signal.bucket === "strong_sell") && signal.direction !== "short") return null
  if (!["buy", "strong_buy", "sell", "strong_sell"].includes(String(signal.bucket))) return null
  if (signal.action_expected_return_net == null || signal.hit_rate == null) return null
  return signal
}

function hasProvenEdgeForMode(
  stock: DashboardStock,
  edge: EdgeMetrics | null | undefined,
  mode: EdgeMode,
) {
  const best = bestActionableSignal(stock)
  if (best && Number(best.proof_n ?? best.n ?? 0) >= 30) {
    const bestProven = mode === "net" ? Boolean(best.proven_edge_net) : Boolean(best.proven_edge_gross)
    if (bestProven) return true
  }
  if (!edge?.gates.n) return false
  return mode === "net" ? edge.proven_edge_net : edge.proven_edge_gross
}

function TopActionableSignals({
  stocks,
  horizon,
}: {
  stocks: DashboardStock[]
  horizon: Horizon
}) {
  const rows = useMemo(
    () =>
      stocks
        .map((stock) => ({ stock, signal: bestActionableSignal(stock, { excludeMasiShorts: true }) }))
        .filter((row): row is { stock: DashboardStock; signal: NonNullable<ReturnType<typeof bestActionableSignal>> } => Boolean(row.signal))
        .sort((left, right) => {
          const proven = Number(Boolean(right.signal.proven_edge_net)) - Number(Boolean(left.signal.proven_edge_net))
          if (proven !== 0) return proven
          const rightScore = right.signal.score ?? Number.NEGATIVE_INFINITY
          const leftScore = left.signal.score ?? Number.NEGATIVE_INFINITY
          if (rightScore !== leftScore) return rightScore - leftScore
          const rightEr = right.signal.action_expected_return_net ?? Number.NEGATIVE_INFINITY
          const leftEr = left.signal.action_expected_return_net ?? Number.NEGATIVE_INFINITY
          if (rightEr !== leftEr) return rightEr - leftEr
          return left.stock.symbol.localeCompare(right.stock.symbol)
        })
        .slice(0, 6),
    [stocks],
  )

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <div>
          <h2 className="dashboard-section-title">Top signaux actionnables</h2>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Classement par edge validé (OOS), score puis retour attendu net.
          </p>
        </div>
        <div className="dashboard-meta">{rows.length} setups prêts à justifier</div>
      </div>

      {rows.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          Aucun signal actionnable dans les filtres actuels. Élargissez l'univers ou retirez le filtre Edge.
        </div>
      ) : (
        <div className="grid divide-y divide-border">
          {rows.map(({ stock, signal }) => {
            const evidenceHref = signalEvidenceUrl({
              symbol: stock.symbol,
              horizon,
              view: signal.variant ?? "expanded_ta_simple",
              source: "wfo",
              tab: "evidence",
            })

            return (
              <Link
                key={`${stock.symbol}-${signal.source}-${signal.variant}`}
                href={evidenceHref}
                title={`Voir la preuve OOS ${stock.symbol}: ${signal.label}`}
                aria-label={`Voir la preuve OOS ${stock.symbol}: ${signal.label}`}
                className="grid gap-3 px-4 py-3 text-left transition hover:bg-bg2 md:grid-cols-[0.8fr_1.4fr_0.8fr_0.8fr_0.8fr]"
              >
              <div>
                <div className="dashboard-mono text-[13px] font-semibold">{stock.symbol}</div>
                <div className="truncate text-[11px] text-muted-foreground">{stock.display_name ?? stock.sector ?? "-"}</div>
              </div>
              <div>
                <div className="text-[12px] font-semibold">{signal.label}</div>
                <div className="dashboard-mono mt-0.5 text-[10px] text-muted-foreground">
                  WFO · {displayVariantLabel(signal.variant)}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Action</div>
                <div className={cn("mt-0.5 text-[12px] font-semibold", signal.direction === "long" ? "dashboard-text-positive" : "dashboard-text-negative")}>
                  {signal.direction === "long" ? "Long" : signal.direction === "short" ? "Short" : "No trade"}
                </div>
              </div>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">retour attendu</div>
                <div className="dashboard-mono mt-0.5 text-[12px] font-semibold">{formatPercent(signal.action_expected_return_net)}</div>
              </div>
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Preuve</div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px]">
                  <span className={cn("rounded px-2 py-0.5 font-semibold", signal.proven_edge_net ? "dashboard-chip-positive" : "dashboard-action-warning")}>
                    {signal.proven_edge_net ? "Validé OOS" : "Watch"}
                  </span>
                  <span className="dashboard-mono text-muted-foreground">
                    %succès {formatPercent(signal.hit_rate)} · {signal.fwd_horizon_bars ?? "--"}j
                  </span>
                  <span className="dashboard-mono text-muted-foreground">
                    n={signal.proof_n ?? signal.n ?? "--"}
                  </span>
                  <ExternalLink className="h-3 w-3 text-muted-foreground" />
                </div>
              </div>
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}

function downloadStocksCsv(stocks: DashboardStock[]) {
  const lines = [
    ["symbol", "display_name", "sector", "asset_class", "asset_type", "market_region", "adv20_mad", "actionable", "actionable_side"].join(","),
    ...stocks.map((stock) => {
      const signal = bestActionableSignal(stock, { excludeMasiShorts: true })
      return [
        stock.symbol,
        stock.display_name ?? "",
        stock.sector ?? "",
        stock.asset_class ?? "",
        stock.asset_type ?? "",
        stock.market_region ?? "",
        stock.adv ?? "",
        signal ? "true" : "false",
        signal?.direction ?? "",
      ]
        .map((value) => {
          const raw = String(value)
          const escaped = raw.replaceAll("\"", "\"\"")
          return /[",\n\r]/.test(raw) ? `"${escaped}"` : escaped
        })
        .join(",")
    }),
  ]
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = "dashboard.csv"
  link.click()
  URL.revokeObjectURL(url)
}

function csvCell(value: unknown) {
  const raw = value == null ? "" : String(value)
  const escaped = raw.replaceAll("\"", "\"\"")
  return /[",\n\r]/.test(raw) ? `"${escaped}"` : escaped
}

function formatPositionsText(positions: DashboardManualPosition[]) {
  return positions
    .map((position) =>
      [
        position.symbol,
        position.quantity,
        position.average_price_mad ?? "",
        position.side ?? "long",
        position.opened_at ?? "",
      ].join(","),
    )
    .join("\n")
}

function parsePositionsText(text: string): { positions: DashboardManualPosition[]; error: string | null } {
  const positions: DashboardManualPosition[] = []
  for (const [idx, rawLine] of text.split(/\r?\n/).entries()) {
    const line = rawLine.trim()
    if (!line) continue
    const [symbolRaw, qtyRaw, avgRaw, sideRaw, openedAtRaw] = line.split(",").map((part) => part.trim())
    const symbol = (symbolRaw ?? "").toUpperCase()
    const quantity = Number(qtyRaw)
    const average = avgRaw ? Number(avgRaw) : null
    const side = sideRaw === "short" ? "short" : "long"
    if (!symbol || !Number.isFinite(quantity) || quantity <= 0) {
      return { positions: [], error: `Position line ${idx + 1} is invalid.` }
    }
    if (average != null && (!Number.isFinite(average) || average <= 0)) {
      return { positions: [], error: `Average price line ${idx + 1} is invalid.` }
    }
    positions.push({
      symbol,
      side,
      quantity,
      average_price_mad: average,
      opened_at: openedAtRaw || null,
    })
  }
  return { positions, error: null }
}

function shareMapFromPositions(positions: DashboardManualPosition[]) {
  const out: Record<string, string> = {}
  for (const position of positions) {
    const symbol = String(position.symbol ?? "").trim().toUpperCase()
    if (!symbol || position.side === "short" || position.quantity <= 0) continue
    out[symbol] = String(position.quantity)
  }
  return out
}

function equalStringRecords(left: Record<string, string>, right: Record<string, string>) {
  const leftKeys = Object.keys(left)
  const rightKeys = Object.keys(right)
  if (leftKeys.length !== rightKeys.length) return false
  return leftKeys.every((key) => left[key] === right[key])
}

function parseShareQuantity(value: string | number | null | undefined) {
  const parsed = Number(String(value ?? "").replace(",", "."))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function positionsFromShareMap(
  sharesBySymbol: Record<string, string | number | null | undefined>,
  savedPositions: DashboardManualPosition[],
) {
  const existingLongPositions = new Map(
    savedPositions
      .filter((position) => position.side !== "short")
      .map((position) => [String(position.symbol ?? "").trim().toUpperCase(), position]),
  )
  const nextPositions: DashboardManualPosition[] = savedPositions
    .filter((position) => position.side === "short" && position.quantity > 0)
    .map((position) => ({ ...position, symbol: String(position.symbol ?? "").trim().toUpperCase() }))
    .filter((position) => position.symbol)

  for (const [rawSymbol, rawQuantity] of Object.entries(sharesBySymbol)) {
    const symbol = rawSymbol.trim().toUpperCase()
    const quantity = parseShareQuantity(rawQuantity)
    if (!symbol || quantity == null) continue
    const existing = existingLongPositions.get(symbol)
    nextPositions.push({
      ...(existing ?? {}),
      symbol,
      side: "long",
      quantity,
    })
  }

  return nextPositions.sort((left, right) => left.symbol.localeCompare(right.symbol))
}

function downloadBlotterCsv(blotter: DashboardDailyBlotterResponse | null) {
  if (!blotter) return
  const header = [
    "symbol",
    "action",
    "current_qty",
    "planned_qty",
    "planned_notional_mad",
    "planned_weight_pct",
    "target_qty",
    "delta_qty",
    "delta_notional_mad",
    "entry",
    "stop",
    "target",
    "hold_days",
    "action_er_net",
    "status",
    "reasons",
  ]
  const lines = [
    header.join(","),
    ...blotter.rows.map((row) =>
      [
        row.symbol,
        row.blotter_action,
        row.current_quantity,
        row.shares,
        row.size_mad,
        row.final_weight_pct,
        row.target_quantity,
        row.delta_quantity,
        row.delta_notional_mad,
        row.entry_reference_price,
        row.stop_loss,
        row.target_1,
        row.holding_period_bars,
        row.action_expected_return_net,
        row.status,
        row.no_trade_reasons.join(";"),
      ].map(csvCell).join(","),
    ),
  ]
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = "daily-blotter.csv"
  link.click()
  URL.revokeObjectURL(url)
}

export default function DashboardV1Page() {
  const [viewMode, setViewMode] = useState<ViewMode>(DEFAULT_DASHBOARD_PREFERENCES.viewMode)
  const [assetTab, setAssetTab] = useState<AssetTab>(DEFAULT_DASHBOARD_PREFERENCES.assetTab)
  const [regionTab, setRegionTab] = useState<RegionTab>(DEFAULT_DASHBOARD_PREFERENCES.regionTab)
  const [horizon, setHorizon] = useState<Horizon>(DEFAULT_DASHBOARD_PREFERENCES.horizon)
  const [view, setView] = useState<DashboardView>(DEFAULT_DASHBOARD_PREFERENCES.view)
  const [showFilters, setShowFilters] = useState(DEFAULT_DASHBOARD_PREFERENCES.showFilters)
  const [showTopActionableSignals, setShowTopActionableSignals] = useState(DEFAULT_DASHBOARD_PREFERENCES.showTopActionableSignals)
  const [showSupportResistance, setShowSupportResistance] = useState(DEFAULT_DASHBOARD_PREFERENCES.showSupportResistance)
  const [showSrConfidence, setShowSrConfidence] = useState(DEFAULT_DASHBOARD_PREFERENCES.showSrConfidence)
  const [liquidityFilter, setLiquidityFilter] = useState(DEFAULT_DASHBOARD_PREFERENCES.liquidityFilter)
  const [dashboardMode, setDashboardMode] = useState<DashboardDisplayMode>(DEFAULT_DASHBOARD_PREFERENCES.dashboardMode)
  const [technicalDirectionMode, setTechnicalDirectionMode] = useState<DashboardTechnicalDirectionMode>(DEFAULT_DASHBOARD_PREFERENCES.technicalDirectionMode)
  const signalView: "expanded" = "expanded"
  const scoreSource: DashboardScoreSource = dashboardMode === "trade_opportunities" ? "wfo" : "signal_engine"
  const [visibleFamilies, setVisibleFamilies] = useState<Record<FamilyColumn, boolean>>({
    ...DEFAULT_DASHBOARD_VISIBLE_FAMILIES,
  })
  const [fundamentalColumns, setFundamentalColumns] = useState<FundamentalColumn[]>([
    ...DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS,
  ])
  const [edgeOnly, setEdgeOnly] = useState(DEFAULT_DASHBOARD_PREFERENCES.edgeOnly)
  const [edgeMode, setEdgeMode] = useState<EdgeMode>(DEFAULT_DASHBOARD_PREFERENCES.edgeMode)
  const [performancePeriod, setPerformancePeriod] = useState<PerformancePeriod>("one_day")
  const [search, setSearch] = useState("")
  const [sectorFilter, setSectorFilter] = useState<string>("all")
  const [basketOnly, setBasketOnly] = useState(false)
  const [selectedBasketSymbols, setSelectedBasketSymbols] = useState<string[]>([])
  const [selectedStock, setSelectedStock] = useState<DashboardStock | null>(null)
  const [ticketCapital, setTicketCapital] = useState(1_000_000)
  const [ticketCashBufferPct, setTicketCashBufferPct] = useState(10)
  const [ticketMaxPositionPct, setTicketMaxPositionPct] = useState(20)
  const [ticketMaxSectorPct, setTicketMaxSectorPct] = useState(40)
  const [ticketKellyPct, setTicketKellyPct] = useState(25)
  const [ticketSidePolicy, setTicketSidePolicy] = useState<"long_only" | "long_short">("long_only")
  const [ticketRequireProvenEdge, setTicketRequireProvenEdge] = useState(false)
  const [positionText, setPositionText] = useState("")
  const [positionsDirty, setPositionsDirty] = useState(false)
  const [positionsSaving, setPositionsSaving] = useState(false)
  const [positionsSaveError, setPositionsSaveError] = useState<string | null>(null)
  const [sectorShareQuantities, setSectorShareQuantities] = useState<Record<string, string>>({})
  const [sectorSharesDirty, setSectorSharesDirty] = useState(false)
  const [sectorSharesSaving, setSectorSharesSaving] = useState(false)
  const [sectorSharesError, setSectorSharesError] = useState<string | null>(null)
  const [dashboardIndexActionError, setDashboardIndexActionError] = useState<string | null>(null)

  const dashboardPreferences = useMemo<DashboardPreferences>(
    () => ({
      showTopActionableSignals,
      showFilters,
      showSupportResistance,
      showSrConfidence,
      viewMode,
      assetTab,
      regionTab,
      horizon,
      view,
      liquidityFilter,
      dashboardMode,
      technicalDirectionMode,
      visibleFamilies,
      fundamentalColumns,
      edgeOnly,
      edgeMode,
    }),
    [
      showTopActionableSignals,
      showFilters,
      showSupportResistance,
      showSrConfidence,
      viewMode,
      assetTab,
      regionTab,
      horizon,
      view,
      liquidityFilter,
      dashboardMode,
      technicalDirectionMode,
      visibleFamilies,
      fundamentalColumns,
      edgeOnly,
      edgeMode,
    ],
  )

  const applyDashboardPreferences = useCallback((next: DashboardPreferences) => {
    setShowTopActionableSignals(next.showTopActionableSignals)
    setShowFilters(next.showFilters)
    setShowSupportResistance(next.showSupportResistance)
    setShowSrConfidence(next.showSrConfidence)
    setViewMode(next.viewMode)
    setAssetTab(next.assetTab)
    setRegionTab(next.regionTab)
    setHorizon(next.horizon)
    setView(next.view)
    setLiquidityFilter(next.liquidityFilter)
    setDashboardMode(next.dashboardMode)
    setTechnicalDirectionMode(next.technicalDirectionMode)
    setVisibleFamilies({ ...next.visibleFamilies })
    setFundamentalColumns([...next.fundamentalColumns])
    setEdgeOnly(next.edgeOnly)
    setEdgeMode(next.edgeMode)
  }, [])

  useDashboardPreferences(!isPublicDashboardOnly, dashboardPreferences, applyDashboardPreferences)

  useEffect(() => {
    if (dashboardMode === "fundamental_directions" && view !== "stocks") {
      setView("stocks")
    }
  }, [dashboardMode, view])

  const { data, error, isLoading, mutate } = useDashboardData(horizon)
  const {
    data: dashboardIndices,
    error: dashboardIndicesError,
    mutate: mutateDashboardIndices,
  } = useDashboardIndices(!isPublicDashboardOnly && viewMode === "masi" && view === "index", horizon)
  const { data: catalogData } = useMarketCatalog()
  const {
    data: savedPositionsData,
    mutate: mutatePortfolioPositions,
  } = useSWR<DashboardManualPosition[]>(
    isPublicDashboardOnly ? null : "dashboard-portfolio-positions",
    fetchDashboardPortfolioPositions,
    {
      revalidateOnFocus: false,
    },
  )
  const savedPositions = savedPositionsData ?? EMPTY_DASHBOARD_POSITIONS

  useEffect(() => {
    if (positionsDirty) return
    const nextText = formatPositionsText(savedPositions)
    setPositionText((current) => (current === nextText ? current : nextText))
  }, [positionsDirty, savedPositions])

  useEffect(() => {
    if (sectorSharesDirty) return
    const nextShares = shareMapFromPositions(savedPositions)
    setSectorShareQuantities((current) => (equalStringRecords(current, nextShares) ? current : nextShares))
  }, [savedPositions, sectorSharesDirty])

  const parsedPositions = useMemo(() => parsePositionsText(positionText), [positionText])
  const activeManualPositions = parsedPositions.error ? savedPositions : parsedPositions.positions

  const saveManualPositions = async () => {
    if (parsedPositions.error) {
      setPositionsSaveError(parsedPositions.error)
      return
    }
    setPositionsSaving(true)
    setPositionsSaveError(null)
    try {
      const saved = await saveDashboardPortfolioPositions(parsedPositions.positions)
      await mutatePortfolioPositions(saved, false)
      setPositionsDirty(false)
      setPositionText(formatPositionsText(saved))
    } catch (err) {
      setPositionsSaveError(err instanceof Error ? err.message : "Position save failed")
    } finally {
      setPositionsSaving(false)
    }
  }

  const updateSectorPortfolioShare = (symbol: string, value: string) => {
    const normalizedSymbol = symbol.trim().toUpperCase()
    if (!normalizedSymbol) return
    setSectorSharesDirty(true)
    setSectorSharesError(null)
    setSectorShareQuantities((previous) => {
      const next = { ...previous }
      const quantity = parseShareQuantity(value)
      if (quantity == null) {
        delete next[normalizedSymbol]
      } else {
        next[normalizedSymbol] = value.trim()
      }
      return next
    })
  }

  const resetSectorPortfolioShares = () => {
    setSectorShareQuantities(shareMapFromPositions(savedPositions))
    setSectorSharesDirty(false)
    setSectorSharesError(null)
  }

  const saveSectorPortfolioShares = async () => {
    setSectorSharesSaving(true)
    setSectorSharesError(null)
    try {
      const nextPositions = positionsFromShareMap(sectorShareQuantities, savedPositions)
      const saved = await saveDashboardPortfolioPositions(nextPositions)
      await mutatePortfolioPositions(saved, false)
      setSectorSharesDirty(false)
      setSectorShareQuantities(shareMapFromPositions(saved))
      if (!positionsDirty) {
        setPositionText(formatPositionsText(saved))
      }
    } catch (err) {
      setSectorSharesError(err instanceof Error ? err.message : "Position save failed")
    } finally {
      setSectorSharesSaving(false)
    }
  }

  const runDashboardIndexAction = async (action: () => Promise<unknown>) => {
    setDashboardIndexActionError(null)
    try {
      await action()
      await mutateDashboardIndices()
    } catch (err) {
      const message = err instanceof Error ? err.message : "Dashboard index action failed"
      setDashboardIndexActionError(message)
      throw err
    }
  }

  const createCustomDashboardIndex = (payload: { name: string; components: DashboardCustomIndexComponent[] }) =>
    runDashboardIndexAction(() => createDashboardIndex(payload))

  const updateCustomDashboardIndex = (id: string, payload: { name: string; components: DashboardCustomIndexComponent[] }) =>
    runDashboardIndexAction(() => updateDashboardIndex(id, payload))

  const deleteCustomDashboardIndex = (id: string) =>
    runDashboardIndexAction(() => deleteDashboardIndex(id))

  const taxonomyMap = useMemo(() => {
    const out: Record<string, { asset_class: string | null; asset_type: string; market_region: string | null }> = {}
    for (const row of catalogData ?? []) {
      out[row.symbol] = {
        asset_class: row.asset_class ?? "equity",
        asset_type: row.asset_type ?? "equity",
        market_region: row.market_region ?? null,
      }
    }
    return out
  }, [catalogData])

  const availableIndexShares = useMemo(() => {
    const out: Record<string, number> = {}
    for (const row of catalogData ?? []) {
      if ((row.asset_class ?? "equity") !== "equity") continue
      if ((row.asset_type ?? "equity") !== "equity") continue
      if (row.market_region !== "masi") continue
      const shares = Number(row.shares_outstanding)
      if (!Number.isInteger(shares) || shares <= 0) continue
      out[row.symbol.toUpperCase()] = shares
    }
    return out
  }, [catalogData])

  const {
    data: bourseSession,
    mutate: mutateBourseSession,
  } = useSWR<BourseSessionStatus>(
    "bourse-session-status",
    fetchBourseSessionStatus,
    { refreshInterval: 60_000, revalidateOnFocus: true },
  )
  const [liveRefreshOverlays, setLiveRefreshOverlays] = useState<Record<string, DashboardLiveRefreshOverlay>>({})
  const [liveRefreshRunning, setLiveRefreshRunning] = useState(false)
  const [liveRefreshError, setLiveRefreshError] = useState<string | null>(null)
  const [liveRefreshMessage, setLiveRefreshMessage] = useState<string | null>(null)

  useEffect(() => {
    setLiveRefreshOverlays({})
    setLiveRefreshError(null)
    setLiveRefreshMessage(null)
  }, [horizon])

  const liveQuoteSymbols = useMemo(
    () =>
      (data?.stocks ?? [])
        .filter((stock) => {
          const taxonomy = taxonomyMap[stock.symbol]
          const assetClass = stock.asset_class ?? taxonomy?.asset_class ?? "equity"
          const assetType = stock.asset_type ?? taxonomy?.asset_type ?? "equity"
          const region = stock.market_region ?? taxonomy?.market_region ?? null
          return assetClass === "equity" && assetType === "equity" && region === "masi"
        })
        .map((stock) => stock.symbol),
    [data?.stocks, taxonomyMap],
  )
  const liveQuotePollingEnabled = Boolean(bourseSession?.is_live_session && liveQuoteSymbols.length)
  const { data: liveQuotesData, mutate: mutateLiveQuotes } = useSWR(
    liveQuotePollingEnabled ? `bourse-live-${liveQuoteSymbols.join(",")}` : null,
    () => fetchBourseLiveQuotes(liveQuoteSymbols, { maxAgeSeconds: 60, persistHistory: false }),
    { refreshInterval: 60_000, revalidateOnFocus: false },
  )
  const liveQuoteMap = useMemo<Record<string, BourseLiveQuote>>(() => {
    const entries = (liveQuotesData?.quotes ?? []).map((quote) => [quote.symbol.toUpperCase(), quote] as const)
    return Object.fromEntries(entries)
  }, [liveQuotesData])
  const liveOverlayMap = useMemo<Record<string, DashboardLiveRefreshOverlay>>(() => liveRefreshOverlays, [liveRefreshOverlays])

  const allStocks = useMemo(
    () => applyDashboardLiveOverlays(data?.stocks ?? [], liveOverlayMap, liveQuoteMap, taxonomyMap) as DashboardStock[],
    [data?.stocks, liveOverlayMap, liveQuoteMap, taxonomyMap],
  )

  const masiStocks = useMemo(
    () =>
      allStocks.filter(
        (stock) =>
          (stock.asset_class ?? "equity") === "equity" &&
          (stock.asset_type ?? "equity") === "equity" &&
          stock.market_region === "masi",
      ),
    [allStocks],
  )

  const edgeSource = scoreSource === "signal_engine" ? "signal_engine" : "wfo"
  const ticketSource = dashboardMode === "fundamental_directions" ? "sfc" : dashboardMode === "trade_opportunities" ? "wfo" : edgeSource
  const edgeHorizon = resolveHorizonPreset(horizon).value
  const horizonDays = horizon === "weekly" ? 5 : horizon === "monthly" ? 21 : 63
  const edgeLookupEnabled = edgeEnabled && dashboardMode === "trade_opportunities"

  const stocksBeforeEdge = useMemo(() => {
    const query = search.trim().toLowerCase()
    return masiStocks
      .filter((stock) => !liquidityFilter || (stock.adv ?? ADV_THRESHOLD) >= ADV_THRESHOLD)
      .filter((stock) => sectorFilter === "all" || stock.sector === sectorFilter)
      .filter((stock) => {
        if (!query) return true
        return stock.symbol.toLowerCase().includes(query) || (stock.display_name ?? "").toLowerCase().includes(query)
      })
  }, [masiStocks, liquidityFilter, sectorFilter, search])

  const { data: edgeEntries = [] } = useSWR<[string, EdgeMetrics | null][]>(
    edgeLookupEnabled && view === "stocks" && stocksBeforeEdge.length
      ? `dashboard-edge-${edgeHorizon}-${edgeSource}-${edgeMode}-${stocksBeforeEdge.map((stock) => stock.symbol).join(",")}`
      : null,
    async () =>
      Promise.all(
        stocksBeforeEdge.map(async (stock) => {
          const embeddedEdge = stock.edge?.[edgeSource]
          return [
            stock.symbol,
            embeddedEdge !== undefined
              ? embeddedEdge
              : await fetchEdge(stock.symbol, edgeHorizon, edgeSource, EDGE_COST_BPS).catch(() => null),
          ] as [string, EdgeMetrics | null]
        }),
      ),
    { revalidateOnFocus: false },
  )

  const edgeMap = useMemo(() => Object.fromEntries(edgeEntries), [edgeEntries]) as Record<string, EdgeMetrics | null | undefined>

  // The legacy SFC snapshot is withdrawn. Keep the compatibility prop empty
  // while all visible fundamental rankings and coverage come from v2 B/M.
  const sfcRowsBySymbol = useMemo<Record<string, FundamentalCrossSectionRow | undefined>>(() => ({}), [])

  const { data: valueSignalData } = useSWR<ValueSignalResponse>(
    dashboardMode === "fundamental_directions" ? "value-signal" : null,
    () => fetchValueSignal(),
    { revalidateOnFocus: false, dedupingInterval: 300_000 },
  )
  const valueSignalBySymbol = useMemo<Record<string, ValueSignalRow | undefined>>(() => {
    const entries = (valueSignalData?.rows ?? []).map((row) => [row.symbol.toUpperCase(), row] as const)
    return Object.fromEntries(entries)
  }, [valueSignalData])

  const filteredStocks = useMemo(() => {
    const modeFiltered = dashboardMode === "trade_opportunities"
      ? stocksBeforeEdge.filter((stock) => bestActionableSignal(stock) !== null)
      : stocksBeforeEdge
    if (dashboardMode !== "trade_opportunities" || !edgeEnabled || !edgeOnly) {
      return modeFiltered
    }
    return modeFiltered.filter((stock) => {
      const edge = edgeMap[stock.symbol]
      return hasProvenEdgeForMode(stock, edge, edgeMode)
    })
  }, [dashboardMode, stocksBeforeEdge, edgeEnabled, edgeOnly, edgeMap, edgeMode])

  const selectedBasketSet = useMemo(() => new Set(selectedBasketSymbols), [selectedBasketSymbols])

  useEffect(() => {
    if (basketOnly && selectedBasketSymbols.length === 0) {
      setBasketOnly(false)
    }
  }, [basketOnly, selectedBasketSymbols.length])

  const toggleBasketSymbol = (symbol: string) => {
    setSelectedBasketSymbols((prev) => {
      return prev.includes(symbol)
        ? prev.filter((item) => item !== symbol)
        : [...prev, symbol]
    })
  }

  const clearBasket = () => {
    setSelectedBasketSymbols([])
    setBasketOnly(false)
  }

  const toggleFamilyColumn = (family: FamilyColumn) => {
    setVisibleFamilies((prev) => {
      return { ...prev, [family]: !prev[family] }
    })
  }

  const setAllFamilyColumns = (visible: boolean) => {
    setVisibleFamilies({
      tendance: visible,
      momentum: visible,
      oscillation: visible,
      volume: visible,
    })
  }

  const toggleAllFamilyColumns = () => {
    setVisibleFamilies((prev) => {
      const nextVisible = !Object.values(prev).every(Boolean)
      return {
        tendance: nextVisible,
        momentum: nextVisible,
        oscillation: nextVisible,
        volume: nextVisible,
      }
    })
  }

  const visibleMasiStocks = useMemo(
    () =>
      basketOnly
        ? filteredStocks.filter((stock) => selectedBasketSet.has(stock.symbol))
        : filteredStocks,
    [basketOnly, filteredStocks, selectedBasketSet],
  )

  const liveRefreshDisabled = liveRefreshRunning || !bourseSession?.is_live_session || visibleMasiStocks.length === 0
  const bourseSessionLabel = bourseSession?.is_live_session
    ? bourseSession.phase === "closing_auction"
      ? "Closing"
      : "Ouverte"
    : bourseSession?.phase === "pre_open"
      ? "Pre-open"
      : "Fermee"
  const runLiveDashboardRefresh = useCallback(async () => {
    const symbols = Array.from(new Set(visibleMasiStocks.map((stock) => stock.symbol.toUpperCase()).filter(Boolean))).slice(0, 80)
    if (!symbols.length) return
    setLiveRefreshRunning(true)
    setLiveRefreshError(null)
    setLiveRefreshMessage(null)
    try {
      await mutateBourseSession()
      const response = await fetchDashboardLiveRefresh({
        symbols,
        horizon,
        maxAgeSeconds: 60,
        persistHistory: true,
      })
      if (response.skipped) {
        setLiveRefreshMessage("Bourse fermee")
        return
      }
      const next: Record<string, DashboardLiveRefreshOverlay> = {}
      for (const overlay of response.overlays) {
        next[overlay.symbol.toUpperCase()] = overlay
      }
      setLiveRefreshOverlays((current) => ({ ...current, ...next }))
      setLiveRefreshMessage(`${response.overlays.length} live`)
      await mutateLiveQuotes()
    } catch (err) {
      setLiveRefreshError(err instanceof Error ? err.message : "Live refresh failed")
    } finally {
      setLiveRefreshRunning(false)
    }
  }, [horizon, mutateBourseSession, mutateLiveQuotes, visibleMasiStocks])

  const visibleSectorCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const stock of visibleMasiStocks) {
      const sector = stock.sector ?? "Autre"
      counts.set(sector, (counts.get(sector) ?? 0) + 1)
    }
    return counts
  }, [visibleMasiStocks])

  const visibleSectors = useMemo(
    () =>
      (data?.sectors ?? [])
        .filter((sector) => visibleSectorCounts.has(sector.sector))
        .map((sector) => ({
          ...sector,
          stock_count: visibleSectorCounts.get(sector.sector) ?? sector.stock_count,
        })),
    [data?.sectors, visibleSectorCounts],
  )

  const customIndexDefinitions = useMemo<DashboardCustomIndexDefinition[]>(() => {
    const sourceDefinitions = dashboardIndices ?? data?.custom_index_definitions ?? []
    const builtIns = BUILTIN_CUSTOM_DASHBOARD_INDICES.filter((builtIn) => {
      const builtInName = builtIn.name.trim().toLowerCase()
      return !sourceDefinitions.some(
        (definition) =>
          definition.id === builtIn.id ||
          definition.name.trim().toLowerCase() === builtInName,
      )
    })
    return [...builtIns, ...sourceDefinitions]
  }, [dashboardIndices, data?.custom_index_definitions])
  const dashboardIndexErrorMessage =
    dashboardIndexActionError ??
    (dashboardIndicesError instanceof Error ? dashboardIndicesError.message : null)

  const sectorOptions = useMemo(() => {
    const set = new Set(filteredStocks.map((stock) => stock.sector).filter((sector): sector is string => Boolean(sector)))
    return ["all", ...Array.from(set).sort()]
  }, [filteredStocks])

  const completStocks = useMemo(() => {
    return allStocks
      .filter((stock) => assetTab === "all" || (stock.asset_type ?? "equity") === assetTab)
      .filter((stock) => regionTab === "all" || stock.market_region === regionTab)
  }, [allStocks, assetTab, regionTab])

  const completeBullishCount = completStocks.filter((stock) =>
    dashboardMode === "fundamental_directions"
      ? valueSignalBySymbol[stock.symbol.toUpperCase()]?.eligible_bm === true
      : dashboardMode === "technical_directions"
      ? technicalSignalForDisplay(stock, technicalDirectionMode)?.direction === "long"
      : bestActionableSignal(stock)?.direction === "long",
  ).length
  const completeBearishCount = completStocks.filter((stock) =>
    dashboardMode === "fundamental_directions"
      ? valueSignalBySymbol[stock.symbol.toUpperCase()]?.eligible_cfp === true
      : dashboardMode === "technical_directions"
      ? technicalSignalForDisplay(stock, technicalDirectionMode)?.direction === "short"
      : bestActionableSignal(stock)?.direction === "short",
  ).length
  const completeTechnicalScoreValues = useMemo(
    () =>
      completStocks
        .map((stock) => technicalSignalForDisplay(stock, technicalDirectionMode)?.abs_score_pct ?? null)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    [completStocks, technicalDirectionMode],
  )
  const medianCompleteTechnicalScore = median(completeTechnicalScoreValues)
  const completeFundamentalUpsideValues = useMemo(
    () =>
      completStocks
        .map((stock) => {
          const row = valueSignalBySymbol[stock.symbol.toUpperCase()]
          return row?.eligible_bm ? row.bm_raw ?? null : null
        })
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    [completStocks, valueSignalBySymbol],
  )
  const medianCompleteFundamentalUpside = median(completeFundamentalUpsideValues)
  const completeProvenEdgeCount = useMemo(() => {
    return completStocks.filter((stock) => hasProvenEdgeForMode(stock, edgeMap[stock.symbol], edgeMode)).length
  }, [completStocks, edgeMap, edgeMode])

  const bullishCount = visibleMasiStocks.filter((stock) =>
    dashboardMode === "fundamental_directions"
      ? valueSignalBySymbol[stock.symbol.toUpperCase()]?.eligible_bm === true
      : dashboardMode === "technical_directions"
      ? technicalSignalForDisplay(stock, technicalDirectionMode)?.direction === "long"
      : bestActionableSignal(stock)?.direction === "long",
  ).length
  const bearishCount = visibleMasiStocks.filter((stock) =>
    dashboardMode === "fundamental_directions"
      ? valueSignalBySymbol[stock.symbol.toUpperCase()]?.eligible_cfp === true
      : dashboardMode === "technical_directions"
      ? technicalSignalForDisplay(stock, technicalDirectionMode)?.direction === "short"
      : bestActionableSignal(stock)?.direction === "short",
  ).length

  const erValues = useMemo(() => {
    return visibleMasiStocks
      .map((stock) => {
        const v = bestActionableSignal(stock)?.action_expected_return_net ?? null
        return typeof v === "number" && Number.isFinite(v) ? v : null
      })
      .filter((v): v is number => v !== null)
  }, [visibleMasiStocks])

  const medianEr = median(erValues)
  const technicalScoreValues = useMemo(
    () =>
      visibleMasiStocks
        .map((stock) => technicalSignalForDisplay(stock, technicalDirectionMode)?.abs_score_pct ?? null)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    [visibleMasiStocks, technicalDirectionMode],
  )
  const medianTechnicalScore = median(technicalScoreValues)
  const fundamentalUpsideValues = useMemo(
    () =>
      visibleMasiStocks
        .map((stock) => {
          const row = valueSignalBySymbol[stock.symbol.toUpperCase()]
          return row?.eligible_bm ? row.bm_raw ?? null : null
        })
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    [valueSignalBySymbol, visibleMasiStocks],
  )
  const medianFundamentalUpside = median(fundamentalUpsideValues)
  const optimizedHoldValues = useMemo(
    () =>
      visibleMasiStocks
        .map((stock) => bestActionableSignal(stock)?.fwd_horizon_bars ?? null)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    [visibleMasiStocks],
  )
  const medianOptimizedHold = median(optimizedHoldValues)

  const selectedManualPositions = useMemo(
    () => activeManualPositions.filter((position) => selectedBasketSet.has(position.symbol)),
    [activeManualPositions, selectedBasketSet],
  )

  const blotterSymbols = selectedBasketSymbols

  const positionsFingerprint = useMemo(
    () =>
      selectedManualPositions
        .map((position) => `${position.symbol}:${position.side}:${position.quantity}:${position.average_price_mad ?? ""}:${position.opened_at ?? ""}`)
        .join("|"),
    [selectedManualPositions],
  )

  const ticketKey = selectedBasketSymbols.length
    ? [
        "dashboard-daily-blotter",
        blotterSymbols.join(","),
        positionsFingerprint,
        edgeHorizon,
        ticketSource,
        ticketSidePolicy,
        ticketCapital,
        ticketCashBufferPct,
        ticketMaxPositionPct,
        ticketMaxSectorPct,
        ticketKellyPct,
        ticketRequireProvenEdge,
      ]
    : null

  const {
    data: basketBlotter,
    error: basketTicketError,
    isLoading: basketTicketLoading,
    mutate: refreshBasketTicket,
  } = useSWR<DashboardDailyBlotterResponse | null>(
    ticketKey,
    () =>
      fetchDashboardDailyBlotter({
        symbols: blotterSymbols,
        positions: selectedManualPositions,
        horizon: edgeHorizon,
        source: ticketSource,
        side_policy: ticketSidePolicy,
        total_capital_mad: ticketCapital,
        cash_buffer_pct: ticketCashBufferPct,
        max_position_pct: ticketMaxPositionPct,
        max_sector_pct: ticketMaxSectorPct,
        kelly_fraction: ticketKellyPct / 100,
        require_proven_edge: ticketRequireProvenEdge,
        price_source: "live_if_fresh",
        max_live_quote_age_seconds: 60,
      }),
    { revalidateOnFocus: false },
  )

  const basketTicket = basketBlotter?.ticket ?? null

  const provenEdgeCount = useMemo(() => {
    return stocksBeforeEdge.filter((stock) => hasProvenEdgeForMode(stock, edgeMap[stock.symbol], edgeMode)).length
  }, [stocksBeforeEdge, edgeMap, edgeMode])

  const visibleFamilyCount = Object.values(visibleFamilies).filter(Boolean).length
  const familyColumnsHidden = visibleFamilyCount === 0
  const isTechnicalDashboardMode = dashboardMode === "technical_directions"
  const isFundamentalDashboardMode = dashboardMode === "fundamental_directions"

  return (
    <div className="dashboard-claude space-y-4 px-0.5">
      <div className="flex flex-col gap-4 border-b border-border pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <h1 className="text-[18px] font-semibold tracking-tight sm:text-[22px]">
            Tableau de Bord
          </h1>
          <p className="text-[12px] text-muted-foreground">
            Signaux techniques · <span className="font-medium text-foreground">Univers multi-actifs</span>
            {data ? <span className="dashboard-meta ml-2">Mis à jour le {new Date(data.generated_at).toLocaleDateString("fr-FR")}</span> : null}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 max-md:w-full max-md:flex-nowrap max-md:overflow-x-auto max-md:pb-1">
          <div className="inline-flex shrink-0 rounded-md border border-border bg-muted/40 p-0.5">
            <button
              type="button"
              onClick={() => setViewMode("complet")}
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-[5px] px-3 text-[12px] font-medium transition",
                viewMode === "complet" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
              )}
            >
              <LayoutDashboard className="h-3.5 w-3.5" />
              Complet
            </button>
            <button
              type="button"
              onClick={() => setViewMode("masi")}
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-[5px] px-3 text-[12px] font-medium transition",
                viewMode === "masi" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
              )}
            >
              <Zap className="h-3.5 w-3.5" />
              MASI Actions
            </button>
          </div>
          <Button variant="outline" size="sm" className="h-8 rounded-md px-4 text-[13px]" onClick={() => setShowFilters((value) => !value)}>
            <Filter className="h-3.5 w-3.5" />
            Filtres
          </Button>
          {dashboardMode === "trade_opportunities" ? (
            <Button
              variant="outline"
              size="sm"
              className="h-8 rounded-md px-4 text-[13px]"
              onClick={() => setShowTopActionableSignals((value) => !value)}
              aria-pressed={showTopActionableSignals}
              title={showTopActionableSignals ? "Masquer Top signaux actionnables" : "Afficher Top signaux actionnables"}
            >
              {showTopActionableSignals ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {showTopActionableSignals ? "Masquer top signaux" : "Afficher top signaux"}
            </Button>
          ) : null}
          {isTechnicalDashboardMode ? (
            <Button
              variant="outline"
              size="sm"
              className="h-8 rounded-md px-4 text-[13px]"
              onClick={toggleAllFamilyColumns}
              aria-pressed={!familyColumnsHidden}
              title={familyColumnsHidden ? "Afficher les colonnes Trend, Momentum, Oscillation et Volume" : "Masquer les colonnes Trend, Momentum, Oscillation et Volume"}
            >
              {familyColumnsHidden ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
              {familyColumnsHidden ? "Afficher familles" : "Masquer familles"}
            </Button>
          ) : null}
          <Button variant="outline" size="sm" className="h-8 rounded-md px-4 text-[13px]" onClick={() => downloadStocksCsv(viewMode === "masi" ? visibleMasiStocks : completStocks)}>
            <Download className="h-3.5 w-3.5" />
            Exporter
          </Button>
          <Button variant="default" size="sm" className="h-8 rounded-md px-4 text-[13px]" onClick={() => void mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Recalculer
          </Button>
        </div>
      </div>

      {data && dashboardMode === "trade_opportunities" && showTopActionableSignals ? (
        <TopActionableSignals
          stocks={viewMode === "masi" ? visibleMasiStocks : completStocks}
          horizon={horizon}
        />
      ) : null}

      {viewMode === "masi" ? (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-2 xl:grid-cols-4">
          <KpiTile
            label="Univers actif"
            value={visibleMasiStocks.length.toLocaleString("fr-FR")}
            sub={basketOnly ? "titres du panier" : "titres après filtres"}
          />
          <KpiTile label={isFundamentalDashboardMode ? "Éligibles B/M" : isTechnicalDashboardMode ? "Directions haussières" : "Opportunités long"} value={bullishCount.toLocaleString("fr-FR")} tone="positive" sub={isFundamentalDashboardMode ? "date et actions PIT vérifiées" : isTechnicalDashboardMode ? `${technicalModeShortLabel(technicalDirectionMode)} technique > +15` : "edge eligible"} />
          <KpiTile label={isFundamentalDashboardMode ? "Éligibles CF/P" : isTechnicalDashboardMode ? "Directions baissières" : "À éviter / alléger"} value={bearishCount.toLocaleString("fr-FR")} sub={isFundamentalDashboardMode ? "couverture secondaire" : isTechnicalDashboardMode ? `${technicalModeShortLabel(technicalDirectionMode)} technique < -15` : "signal de sortie"} />
          <KpiTile
            label={isFundamentalDashboardMode ? "B/M médian" : isTechnicalDashboardMode ? "Score technique médian" : "Action E[R] opt. médian"}
            value={isFundamentalDashboardMode ? (medianFundamentalUpside != null ? formatDecimal(medianFundamentalUpside, 2) : "--") : isTechnicalDashboardMode ? (medianTechnicalScore != null ? formatDecimal(medianTechnicalScore, 1) : "--") : (medianEr != null ? formatPercent(medianEr) : "--")}
            tone={isFundamentalDashboardMode || isTechnicalDashboardMode ? undefined : medianEr != null && medianEr > 0 ? "positive" : medianEr != null && medianEr < 0 ? "negative" : undefined}
            sub={
              isFundamentalDashboardMode
                ? `${fundamentalUpsideValues.length} observations éligibles · v2 PIT strict`
                : isTechnicalDashboardMode
                ? `${technicalScoreValues.length} directions techniques`
                : erValues.length > 0
                ? `${erValues.length} titres · O/O · hold ${medianOptimizedHold != null ? `${Math.round(medianOptimizedHold)}j` : "opt."}`
                : "en attente données Edge"
            }
          />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-2 xl:grid-cols-4">
          <KpiTile label="Univers total" value={completStocks.length.toLocaleString("fr-FR")} sub={isFundamentalDashboardMode ? "scores SFC" : isTechnicalDashboardMode ? "directions techniques" : "instruments disponibles"} />
          <KpiTile label={isFundamentalDashboardMode ? "Éligibles B/M" : isTechnicalDashboardMode ? "Directions haussières" : "Opportunités long"} value={completeBullishCount.toLocaleString("fr-FR")} tone="positive" sub={isFundamentalDashboardMode ? "date et actions PIT vérifiées" : isTechnicalDashboardMode ? `${technicalModeShortLabel(technicalDirectionMode)} technique > +15` : "edge eligible"} />
          <KpiTile label={isFundamentalDashboardMode ? "Éligibles CF/P" : isTechnicalDashboardMode ? "Directions baissières" : "Opportunités short"} value={completeBearishCount.toLocaleString("fr-FR")} tone="negative" sub={isFundamentalDashboardMode ? "couverture secondaire" : isTechnicalDashboardMode ? `${technicalModeShortLabel(technicalDirectionMode)} technique < -15` : "edge eligible"} />
          <KpiTile
            label={isFundamentalDashboardMode ? "B/M médian" : isTechnicalDashboardMode ? "Score technique médian" : "Edge validé (OOS)"}
            value={isFundamentalDashboardMode ? (medianCompleteFundamentalUpside != null ? formatDecimal(medianCompleteFundamentalUpside, 2) : "--") : isTechnicalDashboardMode ? (medianCompleteTechnicalScore != null ? formatDecimal(medianCompleteTechnicalScore, 1) : "--") : completeProvenEdgeCount.toLocaleString("fr-FR")}
            tone={isFundamentalDashboardMode || isTechnicalDashboardMode ? undefined : "positive"}
            sub={isFundamentalDashboardMode ? `${completeFundamentalUpsideValues.length} observations éligibles · v2 PIT strict` : isTechnicalDashboardMode ? `${completeTechnicalScoreValues.length} directions techniques` : `sur ${completStocks.length} instruments`}
          />
        </div>
      )}

      {showFilters ? (
        <div className="space-y-3">
          <div className="flex items-end justify-between gap-3">
            <h2 className="text-[14px] font-semibold">Configurez l'analyse</h2>
            <p className="text-[12px] text-muted-foreground">3 paramètres · valeurs par défaut MASI</p>
          </div>

          <div className="grid gap-2 xl:grid-cols-3">
            <SetupStep index={1} title="Horizon de temps" value={horizon} onChange={setHorizon} options={DASHBOARD_HORIZONS} hint="5 j · 21 j · 63 j" />
            <SetupStep index={2} title="Univers d'analyse" value={view} onChange={setView} options={STOCK_VIEW_OPTIONS} hint={`${masiStocks.length} titres MASI`} />
            <SetupStep
              index={3}
              title="Mode dashboard"
              value={dashboardMode}
              onChange={setDashboardMode}
              options={DASHBOARD_MODE_OPTIONS}
              hint="Edge tradable, technique ou fondamental"
              inlineAfter={
                isTechnicalDashboardMode ? (
                  <div className="inline-flex rounded-md border border-border bg-bg2 p-0.5">
                    {TECHNICAL_DIRECTION_MODE_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setTechnicalDirectionMode(option.value)}
                        className={cn(
                          "min-w-0 rounded-[5px] px-2 py-1 text-[11px] font-medium transition",
                          technicalDirectionMode === option.value
                            ? "bg-card text-foreground shadow-sm"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                ) : null
              }
            />
          </div>

          <div className="dashboard-panel flex flex-col gap-3 px-3 py-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex flex-1 flex-wrap items-center gap-2">
              {liquidityFilter ? (
                <span className="dashboard-chip dashboard-chip-amber">
                  <span className="dashboard-chip-dot bg-[var(--warning)]" />
                  Liquidité ≥ {ADV_THRESHOLD.toLocaleString("fr-FR")} MAD (actif)
                </span>
              ) : null}
              <span className={cn("dashboard-chip", sectorFilter !== "all" && "dashboard-chip-active")}>
                <span className="dashboard-chip-dot" />
                Secteur · {sectorFilter === "all" ? "Tous" : sectorFilter}
              </span>
              <div className="flex h-8 min-w-[220px] flex-1 items-center gap-2 rounded-md border border-input bg-background px-2.5">
                <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <Input
                  className="h-auto border-0 bg-transparent px-0 text-[12px] shadow-none focus-visible:ring-0"
                  placeholder="Rechercher ticker ou nom..."
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
              <select value={sectorFilter} onChange={(event) => setSectorFilter(event.target.value)} className="hidden">
                <option value="all">Tous les secteurs</option>
                {sectorOptions.filter((option) => option !== "all").map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <span className={cn("dashboard-chip h-7", bourseSession?.is_live_session && "dashboard-chip-active")}>
                  <span className={cn("dashboard-chip-dot", bourseSession?.is_live_session ? "bg-[var(--success)]" : "bg-muted-foreground")} />
                  Bourse {bourseSessionLabel}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 rounded-md px-2 text-[12px]"
                  onClick={runLiveDashboardRefresh}
                  disabled={liveRefreshDisabled}
                  title={liveRefreshError ?? liveRefreshMessage ?? undefined}
                >
                  <RefreshCw className={cn("h-3.5 w-3.5", liveRefreshRunning && "animate-spin")} />
                  Live
                </Button>
                <Button variant="ghost" size="sm" className="h-7 rounded-md px-2 text-[12px] text-muted-foreground" asChild>
                  <Link href="/glossary#dashboard">
                    <BookOpen className="h-3.5 w-3.5" />
                    Glossaire
                  </Link>
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                <Switch checked={liquidityFilter} onCheckedChange={setLiquidityFilter} />
                <span>Liquidité</span>
              </div>
              <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                <Switch checked={showSupportResistance} onCheckedChange={setShowSupportResistance} />
                <span>Support / Resistance</span>
              </div>
              <div className={cn("flex items-center gap-2 text-[12px] text-muted-foreground", !showSupportResistance && "opacity-50")}>
                <Switch
                  checked={showSrConfidence}
                  onCheckedChange={setShowSrConfidence}
                  disabled={!showSupportResistance}
                />
                <span>Confidence</span>
              </div>
              {isTechnicalDashboardMode ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">Colonnes</span>
                <label className="dashboard-chip h-7 cursor-pointer bg-background">
                  <Switch
                    checked={!familyColumnsHidden}
                    onCheckedChange={setAllFamilyColumns}
                    aria-label="Afficher ou masquer les colonnes familles"
                  />
                  Familles TA
                  <span className="dashboard-mono text-[10px] text-muted-foreground">{visibleFamilyCount}/4</span>
                </label>
                {FAMILY_COLUMN_OPTIONS.map((option) => {
                  const active = visibleFamilies[option.value]
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => toggleFamilyColumn(option.value)}
                      aria-pressed={active}
                      className={cn("dashboard-chip h-7", active && "dashboard-chip-active")}
                    >
                      <span
                        className={cn(
                          "h-3.5 w-3.5 rounded-[3px] border",
                          active ? "border-primary bg-primary" : "border-border bg-card",
                        )}
                      />
                      {option.label}
                    </button>
                  )
                })}
              </div>
              ) : null}
              {dashboardMode === "trade_opportunities" && edgeEnabled ? (
                <>
                  <div className="inline-flex rounded-md border border-border bg-muted/40 p-0.5">
                    <button
                      type="button"
                      onClick={() => setEdgeMode("net")}
                      className={cn(
                        "rounded-[6px] px-2 py-1 text-[11px] font-medium",
                        edgeMode === "net" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
                      )}
                    >
                      Coûts inclus
                    </button>
                    <button
                      type="button"
                      onClick={() => setEdgeMode("gross")}
                      className={cn(
                        "rounded-[6px] px-2 py-1 text-[11px] font-medium",
                        edgeMode === "gross" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
                      )}
                    >
                      Coûts exclus
                    </button>
                  </div>
                  <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
                    <Checkbox checked={edgeOnly} onCheckedChange={(checked) => setEdgeOnly(checked === true)} />
                    Edge validé (OOS) seulement
                  </label>
                </>
              ) : null}
            </div>
          </div>

          {dashboardMode === "trade_opportunities" && viewMode === "masi" && selectedBasketSymbols.length > 0 ? (
            <BasketCockpit
              selectedSymbols={selectedBasketSymbols}
              basketOnly={basketOnly}
              onBasketOnlyChange={setBasketOnly}
              onClear={clearBasket}
              onRemoveSymbol={toggleBasketSymbol}
              ticket={basketTicket ?? null}
              blotter={basketBlotter ?? null}
              ticketLoading={basketTicketLoading}
              ticketError={basketTicketError instanceof Error ? basketTicketError.message : positionsSaveError}
              capital={ticketCapital}
              cashBufferPct={ticketCashBufferPct}
              maxPositionPct={ticketMaxPositionPct}
              maxSectorPct={ticketMaxSectorPct}
              kellyPct={ticketKellyPct}
              sidePolicy={ticketSidePolicy}
              requireProvenEdge={ticketRequireProvenEdge}
              onCapitalChange={setTicketCapital}
              onCashBufferPctChange={setTicketCashBufferPct}
              onMaxPositionPctChange={setTicketMaxPositionPct}
              onMaxSectorPctChange={setTicketMaxSectorPct}
              onKellyPctChange={setTicketKellyPct}
              onSidePolicyChange={setTicketSidePolicy}
              onRequireProvenEdgeChange={setTicketRequireProvenEdge}
              onRefreshTicket={() => void refreshBasketTicket()}
              positionText={positionText}
              positionError={parsedPositions.error}
              positionsSaving={positionsSaving}
              onPositionTextChange={(value) => {
                setPositionsDirty(true)
                setPositionText(value)
              }}
              onSavePositions={() => void saveManualPositions()}
            />
          ) : null}
        </div>
      ) : null}

      {isLoading && <LoadingSkeleton />}
      {error && <ErrorCard message={error.message} />}

      {data ? (
        isFundamentalDashboardMode && viewMode === "masi" ? (
          <FundamentalDirectionsTab
            stocks={visibleMasiStocks}
            columns={fundamentalColumns}
            onColumnsChange={setFundamentalColumns}
            sfcRowsBySymbol={sfcRowsBySymbol}
            sfcAsOf={valueSignalData?.as_of_date ?? null}
            sfcValidationLabel="v2 PIT strict — recherche non validée"
            valueSignalBySymbol={valueSignalBySymbol}
          />
        ) : viewMode === "masi" ? (
          view === "portfolio" ? (
            <PortfolioTab
              readOnly={isPublicDashboardOnly}
              stocks={masiStocks}
              horizon={horizon}
              displayMode={dashboardMode}
              technicalDirectionMode={technicalDirectionMode}
            />
          ) : view === "sectors" ? (
            <SectorTable
              sectors={visibleSectors}
              stocks={visibleMasiStocks}
              horizon={horizon}
              horizonDays={horizonDays}
              signalView={signalView}
              scoreSource={scoreSource}
              displayMode={dashboardMode}
              technicalDirectionMode={technicalDirectionMode}
              edgeEnabled={edgeEnabled}
              showTechnicalLevels={false}
              visibleFamilies={visibleFamilies}
              portfolioShares={sectorShareQuantities}
              portfolioSharesDirty={sectorSharesDirty}
              portfolioSharesSaving={sectorSharesSaving}
              portfolioSharesError={sectorSharesError}
              onPortfolioShareChange={updateSectorPortfolioShare}
              onSavePortfolioShares={isPublicDashboardOnly ? undefined : () => void saveSectorPortfolioShares()}
              onResetPortfolioShares={resetSectorPortfolioShares}
            />
          ) : view === "index" ? (
            <IndexTab
              baseIndex={data.index}
              baseDefinition={BUILTIN_WEIGHTED_MASI_INDEX}
              stocks={masiStocks}
              customDefinitions={customIndexDefinitions}
              readOnly={isPublicDashboardOnly}
              actionError={dashboardIndexErrorMessage}
              scoreSource={scoreSource}
              signalView={signalView}
              displayMode={dashboardMode}
              technicalDirectionMode={technicalDirectionMode}
              horizon={horizon}
              horizonDays={horizonDays}
              edgeEnabled={edgeEnabled}
              visibleFamilies={visibleFamilies}
              availableShares={availableIndexShares}
              onCreate={isPublicDashboardOnly ? undefined : createCustomDashboardIndex}
              onUpdate={isPublicDashboardOnly ? undefined : updateCustomDashboardIndex}
              onDelete={isPublicDashboardOnly ? undefined : deleteCustomDashboardIndex}
            />
          ) : (
            <StockTable
              stocks={visibleMasiStocks}
              horizon={horizon}
              horizonDays={horizonDays}
              signalView={signalView}
              scoreSource={scoreSource}
              displayMode={dashboardMode}
              technicalDirectionMode={technicalDirectionMode}
              hideDetails={false}
              visibleFamilies={visibleFamilies}
              edgeEnabled={edgeEnabled}
              edgeMode={edgeMode}
              edgeSource={edgeSource}
              edgeMap={edgeMap}
              showSupportResistance={showSupportResistance}
              showSrConfidence={showSrConfidence}
              selectedSymbols={dashboardMode === "trade_opportunities" ? selectedBasketSet : undefined}
              onToggleSelected={dashboardMode === "trade_opportunities" ? toggleBasketSymbol : undefined}
              onOpenEdge={setSelectedStock}
              performancePeriod={performancePeriod}
              onPerformancePeriodChange={setPerformancePeriod}
            />
          )
        ) : (
          <CompletView
            stocks={completStocks}
            assetTab={assetTab}
            setAssetTab={setAssetTab}
            regionTab={regionTab}
            setRegionTab={setRegionTab}
            horizon={horizon}
            horizonDays={horizonDays}
            signalView={signalView}
            scoreSource={scoreSource}
            displayMode={dashboardMode}
            technicalDirectionMode={technicalDirectionMode}
            edgeEnabled={edgeEnabled}
            edgeMode={edgeMode}
            edgeSource={edgeSource}
            edgeMap={edgeMap}
            showSupportResistance={showSupportResistance}
            showSrConfidence={showSrConfidence}
            visibleFamilies={visibleFamilies}
            fundamentalColumns={fundamentalColumns}
            onFundamentalColumnsChange={setFundamentalColumns}
            sfcRowsBySymbol={sfcRowsBySymbol}
            sfcAsOf={valueSignalData?.as_of_date ?? null}
            sfcValidationLabel="v2 PIT strict — recherche non validée"
            valueSignalBySymbol={valueSignalBySymbol}
            onOpenEdge={setSelectedStock}
            performancePeriod={performancePeriod}
            onPerformancePeriodChange={setPerformancePeriod}
          />
        )
      ) : null}

      {data && data.stocks.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            {isPublicDashboardOnly ? (
              <p className="text-muted-foreground">Aucune donnée disponible.</p>
            ) : (
              <p className="text-muted-foreground">
                Aucune donnée disponible. Chargez des données de marché depuis la page <Link href="/data" className="underline">Data</Link>.
              </p>
            )}
          </CardContent>
        </Card>
      ) : null}

      <p className="text-[11px] text-muted-foreground">
        Trade Opportunities sélectionne automatiquement le meilleur edge exploitable. Technical Directions affiche Best ou Classic par titre. Fondamental classe les titres par score, upside et couverture. Liquidité = ADV20 (valeur moyenne échangée 20 j).
      </p>

      {edgeEnabled ? (
        <EdgePanel
          open={Boolean(selectedStock)}
          onOpenChange={(open) => {
            if (!open) setSelectedStock(null)
          }}
          symbol={selectedStock?.symbol ?? null}
          horizon={edgeHorizon}
          initialSource={(selectedStock ? bestActionableSignal(selectedStock)?.source : null) ?? edgeSource}
          initialVariant={(selectedStock ? bestActionableSignal(selectedStock)?.variant : null) ?? null}
          mode={edgeMode}
          onModeChange={setEdgeMode}
          costBps={EDGE_COST_BPS}
          initialEdge={null}
        />
      ) : null}
    </div>
  )
}

function BasketCockpit({
  selectedSymbols,
  basketOnly,
  onBasketOnlyChange,
  onClear,
  onRemoveSymbol,
  ticket,
  blotter,
  ticketLoading,
  ticketError,
  capital,
  cashBufferPct,
  maxPositionPct,
  maxSectorPct,
  kellyPct,
  sidePolicy,
  requireProvenEdge,
  onCapitalChange,
  onCashBufferPctChange,
  onMaxPositionPctChange,
  onMaxSectorPctChange,
  onKellyPctChange,
  onSidePolicyChange,
  onRequireProvenEdgeChange,
  onRefreshTicket,
  positionText,
  positionError,
  positionsSaving,
  onPositionTextChange,
  onSavePositions,
}: {
  selectedSymbols: string[]
  basketOnly: boolean
  onBasketOnlyChange: (checked: boolean) => void
  onClear: () => void
  onRemoveSymbol: (symbol: string) => void
  ticket: DashboardPortfolioTicketResponse | null
  blotter: DashboardDailyBlotterResponse | null
  ticketLoading: boolean
  ticketError: string | null
  capital: number
  cashBufferPct: number
  maxPositionPct: number
  maxSectorPct: number
  kellyPct: number
  sidePolicy: "long_only" | "long_short"
  requireProvenEdge: boolean
  onCapitalChange: (value: number) => void
  onCashBufferPctChange: (value: number) => void
  onMaxPositionPctChange: (value: number) => void
  onMaxSectorPctChange: (value: number) => void
  onKellyPctChange: (value: number) => void
  onSidePolicyChange: (value: "long_only" | "long_short") => void
  onRequireProvenEdgeChange: (checked: boolean) => void
  onRefreshTicket: () => void
  positionText: string
  positionError: string | null
  positionsSaving: boolean
  onPositionTextChange: (value: string) => void
  onSavePositions: () => void
}) {
  const summary = ticket?.summary ?? null
  const plannedRows = ticket?.rows.filter((row) => row.shares > 0) ?? []
  const blotterSummary = blotter?.summary ?? null
  const hasBlotterScope = selectedSymbols.length > 0 || positionText.trim().length > 0
  const selectedCountLabel = `${selectedSymbols.length} titre${selectedSymbols.length > 1 ? "s" : ""}`
  const actionRows = blotter?.rows ?? []

  return (
    <div className="dashboard-panel">
      <div className="flex flex-col gap-3 border-b border-border bg-bg2 px-4 py-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="dashboard-section-title">Portefeuille & blotter</h3>
            <span className="dashboard-meta">{selectedCountLabel}</span>
            {blotterSummary ? (
              <span className="dashboard-chip dashboard-chip-active">
                <span className="dashboard-chip-dot" />
                {blotterSummary.actionable_count} actions
              </span>
            ) : null}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {selectedSymbols.length > 0 ? (
              selectedSymbols.map((symbol) => (
                <button
                  key={symbol}
                  type="button"
                  onClick={() => onRemoveSymbol(symbol)}
                  className="dashboard-chip h-7 bg-card font-semibold"
                >
                  <span className="dashboard-mono">{symbol}</span>
                  <X className="h-3 w-3 text-muted-foreground" />
                </button>
              ))
            ) : (
              <span className="dashboard-meta">Aucun titre</span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <Switch
              checked={basketOnly}
              onCheckedChange={onBasketOnlyChange}
              disabled={!hasBlotterScope}
            />
            Afficher panier
          </label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-md px-3 text-[12px]"
            onClick={onRefreshTicket}
            disabled={!hasBlotterScope || ticketLoading}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", ticketLoading && "animate-spin")} />
            Ticket
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-md px-3 text-[12px]"
            onClick={onClear}
            disabled={selectedSymbols.length === 0}
          >
            Vider
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 rounded-md px-3 text-[12px]"
            onClick={() => downloadBlotterCsv(blotter)}
            disabled={!blotter?.rows.length}
          >
            <Download className="h-3.5 w-3.5" />
            CSV blotter
          </Button>
        </div>
      </div>

      <div className="space-y-3 p-3">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-end">
        <label className="dashboard-field space-y-1.5 p-3">
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Positions actuelles
          </span>
          <Textarea
            value={positionText}
            onChange={(event) => onPositionTextChange(event.currentTarget.value)}
            placeholder="IAM,100,450,long,2026-05-01"
            className="min-h-[66px] resize-y rounded-md border-border bg-card text-[12px]"
          />
          <span className="text-[11px] text-muted-foreground">
            Optionnel. Une ligne par position détenue: ticker, quantité, prix moyen, long/short, date.
          </span>
        </label>
        <div className="dashboard-field flex h-full flex-col justify-between gap-3 p-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Scope blotter</div>
            <div className="mt-1 text-[12px] text-foreground">
              {selectedSymbols.length > 0 ? selectedCountLabel : "Aucun titre sélectionné"}
            </div>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {positionText.trim().length > 0 ? "Positions détenues prises en compte pour les titres sélectionnés" : "Sélectionnez des titres; les positions détenues sont optionnelles"}
            </div>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 w-full rounded-md px-3 text-[12px]"
            onClick={onSavePositions}
            disabled={positionsSaving || Boolean(positionError)}
          >
            <Save className={cn("h-3.5 w-3.5", positionsSaving && "animate-pulse")} />
            Sauver positions
          </Button>
        </div>
      </div>
      {positionError ? <div className="text-[11px] text-destructive">{positionError}</div> : null}

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
        <TicketNumberInput
          label="Capital"
          value={capital}
          min={1}
          max={1_000_000_000}
          step={10_000}
          onChange={onCapitalChange}
        />
        <TicketNumberInput
          label="Cash %"
          value={cashBufferPct}
          min={0}
          max={95}
          step={1}
          onChange={onCashBufferPctChange}
        />
        <TicketNumberInput
          label="Max titre %"
          value={maxPositionPct}
          min={1}
          max={100}
          step={1}
          onChange={onMaxPositionPctChange}
        />
        <TicketNumberInput
          label="Max secteur %"
          value={maxSectorPct}
          min={1}
          max={100}
          step={1}
          onChange={onMaxSectorPctChange}
        />
        <TicketNumberInput
          label="Kelly %"
          value={kellyPct}
          min={0}
          max={100}
          step={5}
          onChange={onKellyPctChange}
        />
        <div className="dashboard-field px-2.5 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Mode</div>
          <div className="mt-2 inline-flex w-full rounded-md border border-border bg-muted/40 p-0.5">
            <button
              type="button"
              onClick={() => onSidePolicyChange("long_only")}
              className={cn(
                "h-7 flex-1 rounded-[5px] px-2 text-[11px] font-medium",
                sidePolicy === "long_only" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
              )}
            >
              Long
            </button>
            <button
              type="button"
              onClick={() => onSidePolicyChange("long_short")}
              className={cn(
                "h-7 flex-1 rounded-[5px] px-2 text-[11px] font-medium",
                sidePolicy === "long_short" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
              )}
            >
              L/S
            </button>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Checkbox
            checked={requireProvenEdge}
            onCheckedChange={(checked) => onRequireProvenEdgeChange(checked === true)}
          />
          Bloquer les edges non prouvés
        </label>
        {ticketError ? (
          <span className="text-[11px] text-destructive">{ticketError}</span>
        ) : null}
      </div>

      <div className="grid gap-2 md:grid-cols-3">
        <TicketMethodNote label="Allocation" value="HRP sur le panier sélectionné, puis plafonds titre, secteur, liquidité et Kelly." />
        <TicketMethodNote label="Entrée" value="Ordre au prochain open uniquement si le prix reste dans la zone support/résistance ± ATR(14)." />
        <TicketMethodNote label="Sortie" value="Stop volatilité/structurel, objectif sur niveau opposé, et révision par durée de détention." />
      </div>

      {summary ? (
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
          <TicketMetric label="Déployable" value={formatMoney(summary.deployable_capital_mad)} />
          <TicketMetric label="Plan alloc." value={`${summary.allocated_count ?? plannedRows.length}/${summary.selected_count}`} sub={formatMoney(summary.allocated_capital_mad)} />
          <TicketMetric label="Delta ordre" value={formatMoney(blotterSummary?.total_delta_notional_mad ?? 0)} />
          <TicketMetric label="Positions" value={formatInteger(blotterSummary?.position_count ?? 0)} />
          <TicketMetric
            label="Action E[R]"
            value={formatMoney(summary.expected_action_return_mad)}
            sub={formatPercent(summary.expected_action_return_pct)}
          />
          <TicketMetric label="Blotter" value={`${blotterSummary?.actionable_count ?? summary.tradable_count}/${summary.selected_count}`} sub={summary.entry_timing} />
        </div>
      ) : ticketLoading ? (
        <div className="dashboard-field px-3 py-3 text-[12px] text-muted-foreground">
          Calcul du ticket et des actions blotter...
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-border bg-bg2 px-3 py-4 text-[12px] text-muted-foreground">
          Sélectionnez des titres dans la table ou ajoutez des positions manuelles pour générer le ticket.
        </div>
      )}

      {actionRows.length ? (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="dashboard-table min-w-[1200px] w-full text-[11px]">
            <thead className="bg-bg2 text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-2 py-2 text-left font-semibold uppercase tracking-[0.08em]">Ticker</th>
                <th className="px-2 py-2 text-left font-semibold uppercase tracking-[0.08em]">Action</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Position</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Plan</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Cible ordre</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Delta</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Notional</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Hold</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Entrée</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Stop</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Objectif prix</th>
                <th className="px-2 py-2 text-right font-semibold uppercase tracking-[0.08em]">Edge</th>
                <th className="px-2 py-2 text-left font-semibold uppercase tracking-[0.08em]">Raisons</th>
                <th className="px-2 py-2 text-left font-semibold uppercase tracking-[0.08em]">Proof</th>
              </tr>
            </thead>
            <tbody>
              {actionRows.map((row) => {
                const proofHref = evidenceProofHref(row.proof_url)
                return (
                <tr
                  key={row.symbol}
                  role="link"
                  tabIndex={0}
                  title={`Voir la preuve OOS ${row.symbol}`}
                  onClick={() => {
                    window.location.href = proofHref
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault()
                      window.location.href = proofHref
                    }
                  }}
                  className="group cursor-pointer border-b border-border/70 bg-background last:border-0 hover:bg-bg2"
                >
                  <td className="dashboard-mono px-2 py-2 font-semibold underline-offset-2 group-hover:underline">{row.symbol}</td>
                  <td className="px-2 py-2">
                    <span
                      className={cn(
                        "inline-flex rounded px-2 py-0.5 font-semibold",
                        blotterActionTone(row.blotter_action),
                      )}
                    >
                      {blotterActionLabel(row.blotter_action)}
                    </span>
                  </td>
                  <td className="dashboard-mono px-2 py-2 text-right">{formatDecimal(row.current_quantity, 0)}</td>
                  <td className="dashboard-mono px-2 py-2 text-right">
                    <div>{formatInteger(row.shares)}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {formatMoney(row.size_mad)} · {formatDecimal(row.final_weight_pct, 2)}%
                    </div>
                  </td>
                  <td className="dashboard-mono px-2 py-2 text-right">{formatInteger(row.target_quantity)}</td>
                  <td className="dashboard-mono px-2 py-2 text-right">{formatInteger(row.delta_quantity)}</td>
                  <td className="dashboard-mono px-2 py-2 text-right">{formatMoney(row.delta_notional_mad)}</td>
                  <td className="dashboard-mono px-2 py-2 text-right">
                    {row.holding_period_bars != null ? `${row.holding_period_bars}j` : "--"}
                    <div className="text-[10px] text-muted-foreground">
                      {row.return_calc_method === "open_to_open" ? "O/O" : row.return_calc_method ?? "--"}
                    </div>
                  </td>
                  <td className="dashboard-mono px-2 py-2 text-right" title={row.execution_explain ?? undefined}>
                    <div>{formatDecimal(row.entry_reference_price, 2)}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {formatDecimal(row.entry_zone_low, 2)} / {formatDecimal(row.entry_zone_high, 2)}
                    </div>
                  </td>
                  <td className="dashboard-mono px-2 py-2 text-right">{formatDecimal(row.stop_loss, 2)}</td>
                  <td className="dashboard-mono px-2 py-2 text-right">{formatDecimal(row.target_1, 2)}</td>
                  <td className="dashboard-mono px-2 py-2 text-right">
                    {formatPercent(row.action_expected_return_net)}
                    <div className="text-[10px] text-muted-foreground">{ticketStatusLabel(row.status)}</div>
                  </td>
                  <td className="px-2 py-2">
                    <div
                      className="max-w-[260px] truncate text-[10px] text-muted-foreground"
                      title={(row.no_trade_reasons.length ? row.no_trade_reasons : [row.allocation_reason ?? row.execution_notes]).map(ticketReasonLabel).join(", ")}
                    >
                      {(row.no_trade_reasons.length ? row.no_trade_reasons : [row.allocation_reason ?? row.execution_notes]).map(ticketReasonLabel).join(", ")}
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <Button variant="ghost" size="sm" className="h-7 rounded-md px-2 text-[11px]" asChild>
                      <Link href={proofHref} onClick={(event) => event.stopPropagation()}>
                        Voir
                        <ExternalLink className="h-3 w-3" />
                      </Link>
                    </Button>
                  </td>
                </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-md border border-dashed border-border bg-bg2 px-3 py-4 text-[12px] text-muted-foreground">
          Aucun ordre blotter pour ce scope.
        </div>
      )}
      </div>
    </div>
  )
}

function TicketNumberInput({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}) {
  return (
    <label className="dashboard-field px-2.5 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</span>
      <Input
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(clampNumber(event.currentTarget.valueAsNumber, min, max))}
        className="mt-1 h-7 border-0 bg-transparent px-0 text-[12px] font-semibold shadow-none focus-visible:ring-0"
      />
    </label>
  )
}

function TicketMetric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="dashboard-field px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className="mt-1 dashboard-mono text-[13px] font-semibold">{value}</div>
      {sub ? <div className="mt-0.5 dashboard-mono text-[10px] text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

function TicketMethodNote({ label, value }: { label: string; value: string }) {
  return (
    <div className="dashboard-field px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className="mt-1 text-[11px] leading-snug text-muted-foreground">{value}</div>
    </div>
  )
}

function blotterActionLabel(action: string) {
  if (action === "BUY") return "Buy"
  if (action === "SELL_SHORT") return "Short"
  if (action === "HOLD") return "Hold"
  if (action === "REDUCE") return "Reduce"
  if (action === "COVER") return "Cover"
  if (action === "EXIT") return "Exit"
  if (action === "WATCH") return "Watch"
  if (action === "REVIEW") return "Review"
  return "Avoid"
}

function blotterActionTone(action: string) {
  if (action === "BUY") return "dashboard-action-buy"
  if (action === "SELL_SHORT") return "dashboard-action-sell"
  if (["EXIT", "COVER", "REDUCE"].includes(action)) return "dashboard-action-warning"
  return "dashboard-action-muted"
}

function ticketStatusLabel(status: string) {
  if (status === "entry_zone") return "Entry zone"
  if (status === "watching") return "En attente"
  if (status === "wait_for_breakout") return "Wait breakout"
  if (status === "wait_for_pullback") return "Wait pullback"
  if (status === "no_setup") return "No setup"
  return status.replaceAll("_", " ")
}

function ticketReasonLabel(reason: string) {
  const labels: Record<string, string> = {
    adv_unavailable: "ADV indisponible",
    direction_geometry_mismatch: "géométrie prix incohérente",
    edge_not_proven: "edge non prouvé",
    edge_unavailable: "edge indisponible",
    entry_price_unavailable: "prix d'entrée indisponible",
    execution_entry_zone: "en zone d'entrée",
    execution_no_setup: "pas de setup",
    execution_unfavorable_rr: "R:R insuffisant",
    execution_watching: "hors zone d'entrée",
    no_directional_signal: "pas de signal directionnel",
    no_executable_signal: "pas de signal exécutable",
    not_in_entry_zone: "hors zone d'entrée",
    position_without_current_edge: "position sans edge courant",
    score_edge_direction_mismatch: "score et edge divergents",
    short_blocked_by_long_only: "short bloqué en long-only",
    strict_edge_gate: "edge prouvé requis",
    waiting_for_entry_zone: "allocation planifiée, entrée à attendre",
    zero_target_size: "taille cible zéro",
  }
  return labels[reason] ?? reason.replaceAll("_", " ")
}

const ASSET_TABS: { value: AssetTab; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "equity", label: "Actions" },
  { value: "commodity", label: "Matières prem." },
  { value: "forex", label: "Forex" },
  { value: "bond", label: "Obligations" },
  { value: "crypto", label: "Crypto" },
]

const REGION_TABS: { value: RegionTab; label: string }[] = [
  { value: "all", label: "Tous" },
  { value: "masi", label: "MASI (Maroc)" },
  { value: "us", label: "US" },
  { value: "european", label: "Europe" },
  { value: "asian", label: "Asie" },
]

function isoDateOffset(days: number) {
  const date = new Date()
  date.setDate(date.getDate() + days)
  return date.toISOString().slice(0, 10)
}

function portfolioDirectionLabel(direction: string) {
  if (direction === "long") return "Buy"
  if (direction === "short") return "Sell"
  return "Neutral"
}

function portfolioDirectionTone(direction: string) {
  if (direction === "long") return "dashboard-text-positive"
  if (direction === "short") return "dashboard-text-negative"
  return "text-muted-foreground"
}

function portfolioComponentsFromState(symbols: string[], shares: Record<string, number>): DashboardPortfolioComponent[] {
  return symbols
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean)
    .filter((symbol, index, arr) => arr.indexOf(symbol) === index)
    .map((symbol) => ({ symbol, shares: Math.max(1, Math.floor(Number(shares[symbol] ?? 1))), enabled: true }))
}

function PortfolioTab({
  readOnly,
  stocks,
  horizon,
  displayMode,
  technicalDirectionMode,
}: {
  readOnly: boolean
  stocks: DashboardStock[]
  horizon: Horizon
  displayMode: DashboardDisplayMode
  technicalDirectionMode: DashboardTechnicalDirectionMode
}) {
  const router = useRouter()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [createMode, setCreateMode] = useState<"manual" | "history">("manual")
  const [name, setName] = useState("")
  const [componentSearch, setComponentSearch] = useState("")
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [shareDraft, setShareDraft] = useState<Record<string, number>>({})
  const [allocationMethod, setAllocationMethod] = useState<"share_quantities" | "hrp">("share_quantities")
  const [sidePolicy, setSidePolicy] = useState<"long_only" | "long_short">("long_only")
  const [stopLossPct, setStopLossPct] = useState("")
  const [takeProfitPct, setTakeProfitPct] = useState("")
  const [startDate, setStartDate] = useState(isoDateOffset(-7))
  const [endDate, setEndDate] = useState(isoDateOffset(-1))
  const [symbol, setSymbol] = useState("")
  const [action, setAction] = useState<DashboardPortfolioTradeInput["action"]>("BUY")
  const [quantity, setQuantity] = useState("")
  const [price, setPrice] = useState("")
  const [fees, setFees] = useState("0")
  const [errorText, setErrorText] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const { data: portfolioState, error, isLoading, mutate } = useSWR<DashboardPortfolioLoadState>(
    readOnly ? null : "dashboard-portfolios",
    fetchDashboardPortfolioLoadState,
    { refreshInterval: 60_000, revalidateOnFocus: false },
  )
  const portfolios = portfolioState?.portfolios ?? []
  const legacyFallback = portfolioState?.legacyFallback === true
  const authRequired = portfolioState?.authRequired === true
  const selected = portfolios.find((portfolio) => portfolio.id === selectedId) ?? null
  const { data: liveSummary, mutate: mutateSummary } = useSWR<DashboardPortfolioSummary>(
    selected && !readOnly && !legacyFallback ? `dashboard-portfolio-summary-${selected.id}` : null,
    () => fetchDashboardNamedPortfolioSummary(selected!.id, { priceSource: "live_if_fresh", maxLiveQuoteAgeSeconds: 60 }),
    { refreshInterval: 60_000, revalidateOnFocus: false },
  )
  const summary = liveSummary ?? selected?.summary ?? null
  const positions = summary?.positions ?? []
  const trades = summary?.trades ?? []
  const visibleStockChoices = useMemo(() => {
    const query = componentSearch.trim().toUpperCase()
    return stocks
      .filter((stock) => !query || stock.symbol.toUpperCase().includes(query) || String(stock.display_name ?? "").toUpperCase().includes(query))
      .slice(0, 80)
  }, [componentSearch, stocks])

  useEffect(() => {
    if (!selected) return
    setName(selected.name)
    setSelectedSymbols(selected.symbols)
    setShareDraft(selected.component_shares)
    setAllocationMethod(selected.allocation_method)
    setSidePolicy(selected.side_policy)
    setStopLossPct(selected.stop_loss_pct == null ? "" : String(selected.stop_loss_pct))
    setTakeProfitPct(selected.take_profit_pct == null ? "" : String(selected.take_profit_pct))
    setStartDate(selected.replay_start_date ?? isoDateOffset(-7))
    setEndDate(selected.replay_end_date ?? isoDateOffset(-1))
  }, [selected])

  if (readOnly) {
    return <div className="dashboard-panel px-4 py-8 text-sm text-muted-foreground">Portfolio management is disabled in public dashboard mode.</div>
  }

  const portfolioDisplayMode = displayMode === "fundamental_directions" ? "trade_opportunities" : displayMode

  const resetCreateForm = () => {
    setName("")
    setSelectedSymbols([])
    setShareDraft({})
    setAllocationMethod("share_quantities")
    setSidePolicy("long_only")
    setStopLossPct("")
    setTakeProfitPct("")
    setStartDate(isoDateOffset(-7))
    setEndDate(isoDateOffset(-1))
    setCreateMode("manual")
    setComponentSearch("")
  }

  const toggleSymbol = (rawSymbol: string) => {
    const nextSymbol = rawSymbol.trim().toUpperCase()
    if (!nextSymbol) return
    setSelectedSymbols((current) => (
      current.includes(nextSymbol)
        ? current.filter((item) => item !== nextSymbol)
        : [...current, nextSymbol]
    ))
    setShareDraft((current) => ({ ...current, [nextSymbol]: current[nextSymbol] ?? 1 }))
  }

  const payloadFromForm = () => {
    const components = portfolioComponentsFromState(selectedSymbols, shareDraft)
    return {
      name: name.trim(),
      components,
      allocation_method: allocationMethod,
      side_policy: sidePolicy,
      total_capital_mad: 1_000_000,
      cash_buffer_pct: 0,
      stop_loss_pct: stopLossPct.trim() ? Number(stopLossPct) : null,
      take_profit_pct: takeProfitPct.trim() ? Number(takeProfitPct) : null,
      display_mode: portfolioDisplayMode,
      technical_direction_mode: technicalDirectionMode,
      horizon,
    }
  }

  const submitPortfolio = async () => {
    setErrorText(null)
    if (legacyFallback) {
      setErrorText("The deployed API is still on the legacy portfolio endpoint. Deploy the portfolio API to edit portfolios.")
      return
    }
    const payload = payloadFromForm()
    if (!payload.name || payload.components.length === 0) {
      setErrorText("Nom et composants requis.")
      return
    }
    setSaving(true)
    try {
      if (selected) {
        await updateDashboardPortfolio(selected.id, payload)
        await mutate()
        await mutateSummary()
      } else if (createMode === "history") {
        const created = await createDashboardPortfolioFromHistory({ ...payload, start_date: startDate, end_date: endDate })
        await mutate()
        setSelectedId(created.portfolio.id)
        setShowCreate(false)
      } else {
        const created = await createDashboardPortfolio(payload)
        await mutate()
        setSelectedId(created.id)
        setShowCreate(false)
      }
      if (!selected) resetCreateForm()
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : "Portfolio save failed")
    } finally {
      setSaving(false)
    }
  }

  const submitReplay = async () => {
    if (!selected) return
    setErrorText(null)
    if (legacyFallback) {
      setErrorText("Historical portfolio generation requires the new portfolio API.")
      return
    }
    setSaving(true)
    try {
      await generateDashboardPortfolioHistory(selected.id, {
        ...payloadFromForm(),
        start_date: startDate,
        end_date: endDate,
        persist: true,
      })
      await mutate()
      await mutateSummary()
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : "Replay failed")
    } finally {
      setSaving(false)
    }
  }

  const submitTrade = async () => {
    if (!selected) return
    setErrorText(null)
    if (legacyFallback) {
      setErrorText("Trade recording is disabled until the deployed API has the new portfolio routes.")
      return
    }
    const normalized = symbol.trim().toUpperCase()
    const qty = Number(quantity)
    const px = Number(price)
    const feeValue = Number(fees || 0)
    if (!normalized || !Number.isFinite(qty) || qty <= 0 || !Number.isFinite(px) || px <= 0 || !Number.isFinite(feeValue) || feeValue < 0) {
      setErrorText("Trade invalide: ticker, quantite, prix et frais doivent etre numeriques.")
      return
    }
    setSaving(true)
    try {
      await recordDashboardNamedPortfolioTrade(selected.id, {
        symbol: normalized,
        action,
        quantity: qty,
        price_mad: px,
        fees_mad: feeValue,
      })
      setSymbol("")
      setQuantity("")
      setPrice("")
      setFees("0")
      await mutateSummary()
      await mutate()
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : "Trade save failed")
    } finally {
      setSaving(false)
    }
  }

  const launchBacktest = async () => {
    if (!selected) return
    setErrorText(null)
    if (legacyFallback) {
      setErrorText("Portfolio replay backtests require the new portfolio API.")
      return
    }
    setSaving(true)
    try {
      const run = await runDashboardPortfolioBacktest(selected.id)
      router.push(`/backtest?runId=${encodeURIComponent(run.run_id)}`)
    } catch (err) {
      setErrorText(err instanceof Error ? err.message : "Backtest launch failed")
    } finally {
      setSaving(false)
    }
  }

  const portfolioCard = (portfolio: DashboardPortfolio) => {
    const weights = buildPortfolioWeightRows(stocks, portfolio.component_shares, { displayMode: portfolioDisplayMode, technicalDirectionMode })
    const signalSummary = summarizeWeightRows(weights.rows)
    const previewRows = weights.rows.slice(0, 5)
    return (
      <button
        key={portfolio.id}
        type="button"
        onClick={() => setSelectedId(portfolio.id)}
        className="dashboard-panel w-full p-4 text-left transition hover:border-primary/40"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="dashboard-section-title">{portfolio.name}</h3>
              {portfolio.is_default ? <span className="dashboard-chip h-6 text-[10px]">Default</span> : null}
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {portfolio.symbols.length} composants · {portfolio.allocation_method === "hrp" ? "HRP" : "Shares"} · {portfolio.side_policy === "long_short" ? "Long/short" : "Long only"}
            </p>
          </div>
          <div className="text-right">
            <div className="dashboard-mono text-[13px] font-semibold">{formatMoney(portfolio.summary?.total_market_value_mad ?? null)}</div>
            <div className={cn("dashboard-mono text-[11px] font-semibold", (portfolio.summary?.total_unrealized_pnl_mad ?? 0) > 0 ? "dashboard-text-positive" : (portfolio.summary?.total_unrealized_pnl_mad ?? 0) < 0 ? "dashboard-text-negative" : "text-muted-foreground")}>
              {formatMoney(portfolio.summary?.total_unrealized_pnl_mad ?? null)}
            </div>
          </div>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <TicketMetric label="Signal net" value={signalSummary.signalLabel} sub={`${formatDecimal(signalSummary.netSignalPct, 1)}% net`} />
          <TicketMetric label="Long / Sell" value={`${formatDecimal(signalSummary.longWeightPct, 0)}% / ${formatDecimal(signalSummary.shortWeightPct, 0)}%`} />
          <TicketMetric label="Replay" value={portfolio.replay_generated_at ? "Generated" : "Manual"} sub={portfolio.replay_end_date ?? "no history"} />
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {previewRows.length ? previewRows.map((row) => (
            <span key={row.symbol} className="dashboard-chip h-7 gap-1.5 text-[11px]">
              <span className="dashboard-mono font-semibold">{row.symbol}</span>
              <span className={cn("font-semibold", portfolioDirectionTone(row.direction))}>{portfolioDirectionLabel(row.direction)}</span>
            </span>
          )) : <span className="text-[11px] text-muted-foreground">No component signals available.</span>}
        </div>
      </button>
    )
  }

  const componentEditor = (
    <div className="dashboard-panel p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="dashboard-section-title">Composants</h3>
          <p className="mt-0.5 text-[11px] text-muted-foreground">Selectionnez les titres et les quantites cible par titre.</p>
        </div>
        <Input className="h-9 max-w-[260px]" placeholder="Search symbol" value={componentSearch} onChange={(event) => setComponentSearch(event.target.value)} />
      </div>
      <div className="grid max-h-[320px] gap-2 overflow-y-auto md:grid-cols-2 xl:grid-cols-3">
        {visibleStockChoices.map((stock) => {
          const stockSymbol = stock.symbol.toUpperCase()
          const checked = selectedSymbols.includes(stockSymbol)
          return (
            <label key={stockSymbol} className={cn("flex items-center gap-2 rounded-md border border-border bg-card p-2 text-[12px]", checked && "border-primary/30 bg-[var(--dashboard-primary-bg)]")}>
              <Checkbox checked={checked} onCheckedChange={() => toggleSymbol(stockSymbol)} />
              <span className="dashboard-mono w-14 font-semibold">{stockSymbol}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground">{stock.display_name ?? stock.sector}</span>
              <Input
                className="h-7 w-20 text-right"
                inputMode="numeric"
                value={String(shareDraft[stockSymbol] ?? 1)}
                disabled={!checked}
                onChange={(event) => setShareDraft((current) => ({ ...current, [stockSymbol]: Math.max(1, Number(event.target.value) || 1) }))}
              />
            </label>
          )
        })}
      </div>
    </div>
  )

  if (!selected) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">Portfolios</h2>
            <p className="text-[12px] text-muted-foreground">List view shows current component directions for the selected dashboard mode.</p>
          </div>
          <Button
            onClick={() => { resetCreateForm(); setShowCreate((value) => !value) }}
            disabled={legacyFallback || authRequired}
          >
            <Plus className="h-3.5 w-3.5" />
            New portfolio
          </Button>
        </div>
        {authRequired ? (
          <div className="dashboard-panel px-4 py-6 text-sm text-muted-foreground">
            Sign in to load and manage portfolios.
          </div>
        ) : null}
        {legacyFallback ? (
          <div className="dashboard-panel border-amber-500/30 bg-amber-500/5 px-4 py-3 text-[12px] text-muted-foreground">
            This deployment is using the legacy portfolio API. The default portfolio is available in read-only compatibility mode; deploy the portfolio API migration/routes to enable multiple portfolios, history generation, and backtest handoff.
          </div>
        ) : null}
        {showCreate && !legacyFallback && !authRequired ? (
          <div className="space-y-3">
            <div className="dashboard-panel p-3">
              <div className="grid gap-2 md:grid-cols-[1fr_auto_auto_auto_auto]">
                <Input placeholder="Portfolio name" value={name} onChange={(event) => setName(event.target.value)} />
                <select value={createMode} onChange={(event) => setCreateMode(event.target.value as "manual" | "history")} className="h-10 rounded-md border border-input bg-background px-3 text-sm">
                  <option value="manual">Manual</option>
                  <option value="history">From history</option>
                </select>
                <select value={allocationMethod} onChange={(event) => setAllocationMethod(event.target.value as "share_quantities" | "hrp")} className="h-10 rounded-md border border-input bg-background px-3 text-sm">
                  <option value="share_quantities">Share quantities</option>
                  <option value="hrp">HRP</option>
                </select>
                <label className="flex h-10 items-center gap-2 rounded-md border border-input px-3 text-[12px]">
                  <Checkbox checked={sidePolicy === "long_short"} onCheckedChange={(checked) => setSidePolicy(checked ? "long_short" : "long_only")} />
                  Long/short
                </label>
                <Button onClick={() => void submitPortfolio()} disabled={saving}>
                  <Save className={cn("h-3.5 w-3.5", saving && "animate-pulse")} />
                  Save
                </Button>
              </div>
              {createMode === "history" ? (
                <div className="mt-2 grid gap-2 md:grid-cols-4">
                  <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
                  <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
                  <Input placeholder="Stop loss %" inputMode="decimal" value={stopLossPct} onChange={(event) => setStopLossPct(event.target.value)} />
                  <Input placeholder="Take profit %" inputMode="decimal" value={takeProfitPct} onChange={(event) => setTakeProfitPct(event.target.value)} />
                </div>
              ) : null}
              {errorText ? <div className="mt-2 text-[11px] text-destructive">{errorText}</div> : null}
            </div>
            {componentEditor}
          </div>
        ) : null}
        {error ? <ErrorCard message={error instanceof Error ? error.message : "Portfolio load failed"} /> : null}
        {isLoading ? <Skeleton className="h-40 rounded-md" /> : null}
        <div className="grid gap-3 xl:grid-cols-2">
          {portfolios.length ? portfolios.map(portfolioCard) : (
            !authRequired && !isLoading ? (
              <div className="dashboard-panel px-4 py-8 text-center text-sm text-muted-foreground">No portfolios yet.</div>
            ) : null
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setSelectedId(null)}>
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
          <div>
            <h2 className="text-base font-semibold">{selected.name}</h2>
            <p className="text-[12px] text-muted-foreground">{selected.symbols.length} composants · {selected.replay_generated_at ? `Replay ${selected.replay_start_date} to ${selected.replay_end_date}` : "Manual portfolio"}</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={() => legacyFallback ? void mutate() : void mutateSummary()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={() => void launchBacktest()} disabled={legacyFallback || saving || !selected.replay_start_date}>
            <ExternalLink className="h-3.5 w-3.5" />
            Run Backtest
          </Button>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-3">
        <KpiTile label="Valeur marche" value={formatMoney(summary?.total_market_value_mad ?? null)} sub="mark live si disponible" />
        <KpiTile
          label="PnL latent"
          value={formatMoney(summary?.total_unrealized_pnl_mad ?? null)}
          tone={(summary?.total_unrealized_pnl_mad ?? 0) > 0 ? "positive" : (summary?.total_unrealized_pnl_mad ?? 0) < 0 ? "negative" : undefined}
          sub={`${positions.length} positions`}
        />
        <KpiTile
          label="PnL realise"
          value={formatMoney(summary?.total_realized_pnl_mad ?? null)}
          tone={(summary?.total_realized_pnl_mad ?? 0) > 0 ? "positive" : (summary?.total_realized_pnl_mad ?? 0) < 0 ? "negative" : undefined}
          sub={`${trades.length} trades recents`}
        />
      </div>

      {legacyFallback ? (
        <div className="dashboard-panel border-amber-500/30 bg-amber-500/5 px-4 py-3 text-[12px] text-muted-foreground">
          Read-only compatibility mode: the deployed API does not expose the new portfolio routes yet. Positions and recent trades are shown from the legacy summary endpoint.
        </div>
      ) : (
        <>
      <div className="dashboard-panel p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h3 className="dashboard-section-title">Nouveau trade</h3>
            <p className="mt-0.5 text-[11px] text-muted-foreground">BUY/SELL pour long, SELL SHORT/COVER pour short. Le CMP est pondere par quantite.</p>
          </div>
        </div>
        <div className="grid gap-2 md:grid-cols-[1fr_1fr_1fr_1fr_1fr_auto]">
          <Input placeholder="Ticker" value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} />
          <select value={action} onChange={(event) => setAction(event.target.value as DashboardPortfolioTradeInput["action"])} className="h-10 rounded-md border border-input bg-background px-3 text-sm">
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
            <option value="SELL_SHORT">SELL SHORT</option>
            <option value="COVER">COVER</option>
          </select>
          <Input placeholder="Quantite" inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
          <Input placeholder="Prix" inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} />
          <Input placeholder="Frais" inputMode="decimal" value={fees} onChange={(event) => setFees(event.target.value)} />
          <Button onClick={() => void submitTrade()} disabled={saving}>
            <Save className={cn("h-3.5 w-3.5", saving && "animate-pulse")} />
            Save
          </Button>
        </div>
      </div>

      <div className="dashboard-panel p-3">
        <div className="grid gap-2 md:grid-cols-[1fr_auto_auto_auto_auto_auto]">
          <Input placeholder="Portfolio name" value={name} onChange={(event) => setName(event.target.value)} />
          <select value={allocationMethod} onChange={(event) => setAllocationMethod(event.target.value as "share_quantities" | "hrp")} className="h-10 rounded-md border border-input bg-background px-3 text-sm">
            <option value="share_quantities">Share quantities</option>
            <option value="hrp">HRP</option>
          </select>
          <label className="flex h-10 items-center gap-2 rounded-md border border-input px-3 text-[12px]">
            <Checkbox checked={sidePolicy === "long_short"} onCheckedChange={(checked) => setSidePolicy(checked ? "long_short" : "long_only")} />
            Long/short
          </label>
          <Input className="w-28" placeholder="SL %" inputMode="decimal" value={stopLossPct} onChange={(event) => setStopLossPct(event.target.value)} />
          <Input className="w-28" placeholder="TP %" inputMode="decimal" value={takeProfitPct} onChange={(event) => setTakeProfitPct(event.target.value)} />
          <Button variant="outline" onClick={() => void submitPortfolio()} disabled={saving}>
            <Save className="h-3.5 w-3.5" />
            Settings
          </Button>
        </div>
        <div className="mt-2 grid gap-2 md:grid-cols-[1fr_1fr_auto]">
          <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
          <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
          <Button variant="outline" onClick={() => void submitReplay()} disabled={saving}>
            <RefreshCw className={cn("h-3.5 w-3.5", saving && "animate-spin")} />
            Generate history
          </Button>
        </div>
        {errorText ? <div className="mt-2 text-[11px] text-destructive">{errorText}</div> : null}
      </div>

      {componentEditor}
        </>
      )}

      <div className="dashboard-panel overflow-hidden">
        <div className="border-b border-border bg-bg2 px-4 py-3">
          <h3 className="dashboard-section-title">Positions</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="dashboard-table min-w-[980px] w-full text-[11px]">
            <thead className="bg-bg2 text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-3 py-2 text-left">Ticker</th>
                <th className="px-3 py-2 text-left">Side</th>
                <th className="px-3 py-2 text-right">Quantite</th>
                <th className="px-3 py-2 text-right">CMP</th>
                <th className="px-3 py-2 text-right">Mark</th>
                <th className="px-3 py-2 text-right">Valeur</th>
                <th className="px-3 py-2 text-right">PnL latent</th>
                <th className="px-3 py-2 text-right">PnL realise</th>
              </tr>
            </thead>
            <tbody>
              {positions.length ? positions.map((position) => (
                <tr key={`${position.symbol}-${position.side}`} className="border-b border-border/70 hover:bg-bg2">
                  <td className="dashboard-mono px-3 py-2 font-semibold">{position.symbol}</td>
                  <td className="px-3 py-2">{position.side === "short" ? "Short" : "Long"}</td>
                  <td className="dashboard-mono px-3 py-2 text-right">{formatDecimal(position.quantity, 0)}</td>
                  <td className="dashboard-mono px-3 py-2 text-right">{formatDecimal(position.cmp_mad, 2)}</td>
                  <td className="dashboard-mono px-3 py-2 text-right">
                    <div>{formatDecimal(position.mark_price_mad, 2)}</div>
                    <div className="text-[9px] text-muted-foreground">{position.mark_source === "live" ? "Live" : position.mark_source === "replay_close" ? "Replay" : "Close"}</div>
                  </td>
                  <td className="dashboard-mono px-3 py-2 text-right">{formatMoney(position.market_value_mad)}</td>
                  <td className={cn("dashboard-mono px-3 py-2 text-right font-semibold", (position.unrealized_pnl_mad ?? 0) > 0 ? "dashboard-text-positive" : (position.unrealized_pnl_mad ?? 0) < 0 ? "dashboard-text-negative" : "text-muted-foreground")}>{formatMoney(position.unrealized_pnl_mad)}</td>
                  <td className={cn("dashboard-mono px-3 py-2 text-right font-semibold", position.realized_pnl_mad > 0 ? "dashboard-text-positive" : position.realized_pnl_mad < 0 ? "dashboard-text-negative" : "text-muted-foreground")}>{formatMoney(position.realized_pnl_mad)}</td>
                </tr>
              )) : (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-muted-foreground">Aucune position active.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="dashboard-panel overflow-hidden">
        <div className="border-b border-border bg-bg2 px-4 py-3">
          <h3 className="dashboard-section-title">Trades recents</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="dashboard-table min-w-[760px] w-full text-[11px]">
            <thead className="bg-bg2 text-muted-foreground">
              <tr className="border-b border-border">
                <th className="px-3 py-2 text-left">Date</th>
                <th className="px-3 py-2 text-left">Ticker</th>
                <th className="px-3 py-2 text-left">Action</th>
                <th className="px-3 py-2 text-right">Quantite</th>
                <th className="px-3 py-2 text-right">Prix</th>
                <th className="px-3 py-2 text-right">PnL realise</th>
              </tr>
            </thead>
            <tbody>
              {trades.length ? trades.slice(0, 25).map((trade) => (
                <tr key={trade.id} className="border-b border-border/70 hover:bg-bg2">
                  <td className="dashboard-mono px-3 py-2">{trade.timestamp ?? "--"}</td>
                  <td className="dashboard-mono px-3 py-2 font-semibold">{trade.symbol}</td>
                  <td className="px-3 py-2">{trade.action}</td>
                  <td className="dashboard-mono px-3 py-2 text-right">{formatDecimal(trade.quantity, 0)}</td>
                  <td className="dashboard-mono px-3 py-2 text-right">{formatDecimal(trade.price_mad, 2)}</td>
                  <td className={cn("dashboard-mono px-3 py-2 text-right font-semibold", trade.realized_pnl_mad > 0 ? "dashboard-text-positive" : trade.realized_pnl_mad < 0 ? "dashboard-text-negative" : "text-muted-foreground")}>{formatMoney(trade.realized_pnl_mad)}</td>
                </tr>
              )) : (
                <tr><td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">Aucun trade enregistre.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function CompletView({
  stocks,
  assetTab,
  setAssetTab,
  regionTab,
  setRegionTab,
  horizon,
  horizonDays,
  signalView,
  scoreSource,
  displayMode,
  technicalDirectionMode,
  edgeEnabled,
  edgeMode,
  edgeSource,
  edgeMap,
  showSupportResistance,
  showSrConfidence,
  visibleFamilies,
  fundamentalColumns,
  onFundamentalColumnsChange,
  sfcRowsBySymbol,
  sfcAsOf,
  sfcValidationLabel,
  valueSignalBySymbol,
  onOpenEdge,
  performancePeriod,
  onPerformancePeriodChange,
}: {
  stocks: DashboardStock[]
  assetTab: AssetTab
  setAssetTab: (v: AssetTab) => void
  regionTab: RegionTab
  setRegionTab: (v: RegionTab) => void
  horizon: Horizon
  horizonDays: number
  signalView: "legacy" | "expanded" | "factor_x_ta"
  scoreSource: DashboardScoreSource
  displayMode: DashboardDisplayMode
  technicalDirectionMode: DashboardTechnicalDirectionMode
  edgeEnabled: boolean
  edgeMode: "gross" | "net"
  edgeSource: "signal_engine" | "wfo"
  edgeMap: Record<string, import("@/lib/api").EdgeMetrics | null | undefined>
  showSupportResistance: boolean
  showSrConfidence: boolean
  visibleFamilies: Partial<Record<FamilyColumn, boolean>>
  fundamentalColumns: FundamentalColumn[]
  onFundamentalColumnsChange: (columns: FundamentalColumn[]) => void
  sfcRowsBySymbol: Record<string, FundamentalCrossSectionRow | undefined>
  sfcAsOf: string | null
  sfcValidationLabel: string | null
  valueSignalBySymbol: Record<string, ValueSignalRow | undefined>
  onOpenEdge: (stock: DashboardStock) => void
  performancePeriod: PerformancePeriod
  onPerformancePeriodChange: (value: PerformancePeriod) => void
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {ASSET_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setAssetTab(tab.value)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-[12px] font-medium transition",
              assetTab === tab.value
                ? "border-primary/25 bg-[var(--dashboard-primary-bg)] font-semibold text-primary"
                : "border-border bg-card text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        ))}
        <div className="ml-2 flex gap-1">
          {REGION_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setRegionTab(tab.value)}
              className={cn(
                "inline-flex h-8 items-center rounded-md border px-3 text-[12px] transition",
                regionTab === tab.value
                  ? "border-border bg-background font-semibold text-foreground shadow-sm"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {displayMode === "fundamental_directions" ? (
        <FundamentalDirectionsTab
          stocks={stocks}
          columns={fundamentalColumns}
          onColumnsChange={onFundamentalColumnsChange}
          sfcRowsBySymbol={sfcRowsBySymbol}
          sfcAsOf={sfcAsOf}
          sfcValidationLabel={sfcValidationLabel}
          valueSignalBySymbol={valueSignalBySymbol}
        />
      ) : (
        <StockTable
          stocks={stocks}
          horizon={horizon}
          horizonDays={horizonDays}
          signalView={signalView}
          scoreSource={scoreSource}
          displayMode={displayMode}
          technicalDirectionMode={technicalDirectionMode}
          edgeEnabled={edgeEnabled}
          edgeMode={edgeMode}
          edgeSource={edgeSource}
          edgeMap={edgeMap}
          showSupportResistance={showSupportResistance}
          showSrConfidence={showSrConfidence}
          visibleFamilies={visibleFamilies}
          onOpenEdge={onOpenEdge}
          performancePeriod={performancePeriod}
          onPerformancePeriodChange={onPerformancePeriodChange}
        />
      )}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20 rounded-md" />
        ))}
      </div>
      <Skeleton className="h-28 rounded-md" />
      <Skeleton className="h-[480px] rounded-md" />
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
