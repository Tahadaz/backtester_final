"use client"

import Link from "next/link"
import { Fragment, useEffect, useMemo, useState } from "react"
import { ArrowRight, BarChart3, BookOpen, ChevronDown, ChevronUp, ChevronsUpDown, Star } from "lucide-react"
import type { EdgeMetrics } from "@/lib/api"
import type {
  DashboardBestSignal,
  DashboardBestTechnicalSignal,
  DashboardDisplayMode,
  DashboardScoreSource,
  DashboardStock,
  DashboardTechnicalDirectionMode,
  Horizon,
  WfoSupportResistanceSummary,
} from "@/lib/dashboard-types"
import { FAMILY_ORDER } from "@/lib/dashboard-constants"
import { formatPercent } from "@/lib/format"
import { FamilyCell } from "./family-cell"
import { DashboardSignalChartPanel } from "./signal-chart-panel"
import { SignalBadge } from "./signal-badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import { cn } from "@/lib/utils"

type SortDir = "asc" | "desc"
type SortKey =
  | "symbol"
  | "price"
  | "performance"
  | "adv"
  | "signal"
  | "best_signal"
  | "technical_signal"
  | "expected_return"
  | "hit_rate"
  | "edge"
  | (typeof FAMILY_ORDER)[number]
type FamilyKey = (typeof FAMILY_ORDER)[number]
type PerformancePeriod = "one_day" | "wtd" | "mtd" | "ytd" | "open_to_now"
const SR_WFO_COST_BPS = 33

interface StockTableProps {
  stocks: DashboardStock[]
  horizon: Horizon
  horizonDays: number
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  scoreSource?: DashboardScoreSource
  displayMode?: DashboardDisplayMode
  technicalDirectionMode?: DashboardTechnicalDirectionMode
  hideDetails?: boolean
  showTechnicalLevels?: boolean
  edgeEnabled?: boolean
  edgeMode?: "gross" | "net"
  edgeSource?: "signal_engine" | "wfo"
  edgeMap?: Record<string, EdgeMetrics | null | undefined>
  showSupportResistance?: boolean
  showSrConfidence?: boolean
  visibleFamilies?: Partial<Record<FamilyKey, boolean>>
  selectedSymbols?: ReadonlySet<string>
  onToggleSelected?: (symbol: string) => void
  onOpenEdge?: (stock: DashboardStock) => void
  performancePeriod?: PerformancePeriod
  onPerformancePeriodChange?: (value: PerformancePeriod) => void
}

function horizonLabel(horizon: Horizon) {
  if (horizon === "weekly") return "hebdomadaire"
  if (horizon === "monthly") return "mensuel"
  if (horizon === "quarterly") return "trimestriel"
  if (horizon === "medium") return "mensuel"
  if (horizon === "long") return "trimestriel"
  return "hebdomadaire"
}

function resolveSeFamily(stock: DashboardStock, family: string, signalView: "legacy" | "expanded" | "factor_x_ta") {
  const se = stock.scores.signal_engine
  const familyMap = signalView === "factor_x_ta"
    ? se.factor_x_ta_per_family
    : signalView === "expanded"
      ? (se.expanded_per_family ?? se.per_family)
      : se.per_family
  return familyMap?.[family] ?? null
}

function resolveFactorDependencies(stock: DashboardStock, family: string, signalView: "legacy" | "expanded" | "factor_x_ta") {
  if (signalView !== "factor_x_ta") return undefined
  return stock.scores.signal_engine.factor_dependencies?.[family]
}

function priceForDisplay(stock: DashboardStock): number | null {
  const quote = stock.live_quote
  return (quote?.is_fresh ? quote.last_price : null) ?? stock.last_price ?? stock.scores.signal_engine.technical_levels?.close_used ?? null
}

function quoteStatusLabel(stock: DashboardStock): string {
  const quote = stock.live_quote
  if (!quote) return "Close"
  if (quote.is_fresh) return "Live"
  const ageSeconds = quote.age_seconds
  if (ageSeconds == null) return "Live update unavailable"
  const ageMinutes = Math.max(1, Math.floor(ageSeconds / 60))
  return ageMinutes >= 60 ? `Stale • ${Math.floor(ageMinutes / 60)}h ago` : `Stale • ${ageMinutes}m ago`
}

function pctChange(endPrice: number | null | undefined, startPrice: number | null | undefined) {
  if (endPrice == null || startPrice == null || !Number.isFinite(endPrice) || !Number.isFinite(startPrice) || startPrice === 0) return null
  return ((endPrice - startPrice) / startPrice) * 100
}

function selectedPerformancePct(stock: DashboardStock, period: PerformancePeriod) {
  const quote = stock.live_quote
  const livePrice = quote?.is_fresh && quote.last_price != null ? quote.last_price : null
  if (period === "one_day") {
    return livePrice != null ? pctChange(livePrice, quote?.prev_close ?? stock.prev_close) : stock.performance?.one_day?.pct ?? stock.var1j_pct ?? null
  }
  if (period === "open_to_now") {
    return livePrice != null ? pctChange(livePrice, quote?.open_price) : stock.performance?.open_to_now?.pct ?? null
  }
  const official = stock.performance?.[period]
  return livePrice != null ? pctChange(livePrice, official?.start_price) : official?.pct ?? null
}

function performanceHeaderLabel(period: PerformancePeriod) {
  if (period === "one_day") return "Var. 1j"
  if (period === "wtd") return "WTD"
  if (period === "mtd") return "MTD"
  if (period === "ytd") return "YTD"
  return "Open->Now"
}

function isActionableBestSignal(signal: DashboardBestSignal | null | undefined): signal is DashboardBestSignal {
  if (!signal) return false
  if (signal.direction === "none" || signal.bucket === "hold") return false
  if (signal.bucket === "buy" || signal.bucket === "strong_buy") return signal.direction === "long"
  if (signal.bucket === "sell" || signal.bucket === "strong_sell") return signal.direction === "short"
  return false
}

function bestSignalForDisplay(stock: DashboardStock): DashboardBestSignal | null {
  const signal = stock.best_signal ?? null
  if (signal?.source !== "wfo") return null
  if (!isActionableBestSignal(signal)) return null
  if (signal.action_expected_return_net == null || signal.hit_rate == null) return null
  return signal
}

function technicalSignalForDisplay(
  stock: DashboardStock,
  mode: DashboardTechnicalDirectionMode = "best",
): DashboardBestTechnicalSignal | null {
  const signal = mode === "classic" ? stock.classic_technical_signal ?? null : stock.best_technical_signal ?? null
  if (!signal) return null
  if (signal.score_pct == null || !Number.isFinite(signal.score_pct)) return null
  return signal
}

function technicalFamilyForDisplay(stock: DashboardStock, family: string, mode: DashboardTechnicalDirectionMode) {
  return technicalSignalForDisplay(stock, mode)?.per_family?.[family] ?? null
}

function technicalFactorDependencies(stock: DashboardStock, family: string, mode: DashboardTechnicalDirectionMode) {
  return technicalSignalForDisplay(stock, mode)?.factor_dependencies?.[family]
}

function compareValues(left: number | string | null, right: number | string | null, dir: SortDir) {
  let comparison = 0
  if (typeof left === "string" && typeof right === "string") {
    comparison = left.localeCompare(right)
  } else {
    const l = typeof left === "number" ? left : Number.NEGATIVE_INFINITY
    const r = typeof right === "number" ? right : Number.NEGATIVE_INFINITY
    comparison = l - r
  }
  return dir === "asc" ? comparison : -comparison
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  return value.toLocaleString("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function formatVarPct(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}%`
}

function varToneClass(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value) || value === 0) return "dashboard-text-muted"
  return value > 0 ? "dashboard-text-positive" : "dashboard-text-negative"
}

function bestSignalActionLabel(signal: DashboardBestSignal | null | undefined) {
  if (!signal) return "--"
  if (signal.direction === "long") return "Long"
  if (signal.direction === "short") return "Short"
  return "No trade"
}

function bestSignalHoldingPeriodLabel(signal: DashboardBestSignal | null | undefined, fallbackDays?: number) {
  if (signal?.exit_timing_label) return signal.exit_timing_label
  const days = signal?.exit_lag_bars ?? signal?.fwd_horizon_bars ?? fallbackDays
  if (signal?.return_calc_method === "open_to_exit_ladder" && days) {
    const exit = signal.exit_price_kind === "close" ? "Close" : "Open"
    return `J+${days} ${exit}`
  }
  const method = signal?.return_calc_method === "open_to_open" ? "O/O" : signal?.return_calc_method ?? null
  if (!days) return method ?? "--"
  return method ? `${days}j ${method}` : `${days}j`
}

type EdgeTriage = "proven" | "watch" | "insufficient" | "hold" | "missing"

function bestSignalTriage(signal: DashboardBestSignal | null | undefined): EdgeTriage {
  if (!signal) return "missing"
  if (signal.direction === "none" || signal.bucket === "hold") return "hold"
  if ((signal.n ?? 0) < 30) return "insufficient"
  return signal.proven_edge_net ? "proven" : "watch"
}

function shortMethodLabel(signal: DashboardBestSignal | null | undefined) {
  if (!signal) return "No eligible WFO edge"
  return signal.label
    .replace("Signal Engine - ", "Engine ")
    .replace("Factor x TA", "FX")
    .replace("Simple", "")
    .trim()
}

function bucketSignalLabel(bucket: string | null | undefined) {
  if (bucket === "strong_buy") return "Achat fort"
  if (bucket === "buy") return "Achat"
  if (bucket === "sell") return "Vente"
  if (bucket === "strong_sell") return "Vente forte"
  if (bucket === "hold") return "Neutre"
  return "Indisponible"
}

function bestSignalLabel(signal: DashboardBestSignal | null | undefined) {
  return signal?.signal_label ?? bucketSignalLabel(signal?.bucket)
}

function signalViewForVariant(variant: string | null | undefined): "legacy" | "expanded" | "factor_x_ta" {
  const token = String(variant ?? "").toLowerCase()
  if (token.includes("factor_x_ta")) return "factor_x_ta"
  if (token.includes("legacy")) return "legacy"
  return "expanded"
}

function technicalEvidenceView(signal: DashboardBestTechnicalSignal | null, mode: DashboardTechnicalDirectionMode) {
  if (mode === "classic") return "legacy_ta_simple"
  return signal ? signalViewForVariant(signal.variant) : "expanded_ta_simple"
}

function technicalModeShortLabel(mode: DashboardTechnicalDirectionMode) {
  return mode === "classic" ? "classic" : "best"
}

function sourceLabel(source: "signal_engine" | "wfo" | string | null | undefined) {
  return source === "wfo" ? "WFO" : "Signal Engine"
}

function displayVariantLabel(variant: string | null | undefined) {
  const value = String(variant ?? "").trim()
  if (!value) return "--"
  return value.startsWith("sv_") ? "Selected indicator" : value
}

function formatScorePct(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(1)}`
}

function bestSignalEdgeScore(signal: DashboardBestSignal | null | undefined) {
  return signal?.edge_score ?? null
}

function bestSignalSortScore(signal: DashboardBestSignal | null | undefined) {
  return signal?.edge_score ?? signal?.score ?? null
}

function formatEdgeScore(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  return value.toFixed(0)
}

function srLevels(row: WfoSupportResistanceSummary | null | undefined): {
  support: number | null
  resistance: number | null
  supportMethod: string | null
  resistanceMethod: string | null
} {
  const empty = { support: null, resistance: null, supportMethod: null, resistanceMethod: null }
  const live = row?.live_recommendation
  if (!live) return empty
  return {
    support: live.support_level ?? null,
    resistance: live.resistance_level ?? null,
    supportMethod: live.support_method ?? null,
    resistanceMethod: live.resistance_method ?? null,
  }
}

function fmtSrPrice(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "--"
  return v.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function srWfoTitle(row: WfoSupportResistanceSummary | null | undefined) {
  if (!row) return "S/R WFO unavailable."
  const { support, resistance, supportMethod, resistanceMethod } = srLevels(row)
  const levels = `Support ${fmtSrPrice(support)}${supportMethod ? ` (${supportMethod})` : ""} · Résistance ${fmtSrPrice(resistance)}${resistanceMethod ? ` (${resistanceMethod})` : ""}`
  return `${levels}. S/R WFO status: ${row.status}.`
}

function SrWfoCell({
  row,
  loading,
  error,
  showConfidence,
}: {
  row: WfoSupportResistanceSummary | null | undefined
  loading: boolean
  error: unknown
  showConfidence: boolean
}) {
  if (loading && !row) {
    return <span className="dashboard-mono text-[10px] text-muted-foreground">S/R...</span>
  }
  if (error && !row) {
    return <span className="text-[10px] text-destructive" title={error instanceof Error ? error.message : String(error)}>Erreur S/R</span>
  }
  if (!row || row.status !== "succeeded") {
    return <span className="dashboard-mono text-[10px] text-muted-foreground" title="No S/R WFO signal available yet.">--</span>
  }
  const { support, resistance } = srLevels(row)
  return (
    <div className="space-y-0.5 text-right" title={srWfoTitle(row)}>
      <div className="dashboard-mono text-[11px] font-semibold leading-4">
        <span className="text-emerald-600 dark:text-emerald-400">S {fmtSrPrice(support)}</span>
        <span className="text-muted-foreground"> · </span>
        <span className="text-red-600 dark:text-red-400">R {fmtSrPrice(resistance)}</span>
      </div>
      {showConfidence ? (
        <div className="dashboard-mono text-[10px] text-muted-foreground">
          {row.label ?? "--"}
        </div>
      ) : null}
    </div>
  )
}

function EdgeBadge({ triage }: { triage: EdgeTriage }) {
  if (triage === "insufficient")
    return <span className="text-[11px] font-semibold text-muted-foreground">&lt;30 OOS</span>
  if (triage === "hold")
    return <span className="text-[11px] font-semibold text-muted-foreground">Hold</span>
  if (triage === "missing")
    return <span className="text-[11px] text-muted-foreground">No action.</span>
  if (triage === "proven")
    return (
      <span className="dashboard-chip-positive inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold">
        <Star className="h-2.5 w-2.5" />
        Prouvé
      </span>
    )
  if (triage === "watch")
    return (
      <span className="dashboard-action-warning inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold">
        À surveiller
      </span>
    )
  return <span className="text-[11px] text-muted-foreground">—</span>
}

function GlossaryHelpLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex h-4 w-4 items-center justify-center rounded text-muted-foreground/70 hover:bg-background hover:text-foreground"
      aria-label={label}
      title={label}
    >
      <BookOpen className="h-3 w-3" />
    </Link>
  )
}

function BestSignalMethodCell({ signal }: { signal: DashboardBestSignal | null }) {
  if (!signal) {
    return <span className="text-[11px] text-muted-foreground">No eligible WFO edge</span>
  }
  return (
    <div className="space-y-1">
      <div className="max-w-[180px] truncate text-[11px] font-semibold" title={signal.label}>
        {shortMethodLabel(signal)}
      </div>
      <div className="flex items-center gap-1.5">
        <EdgeBadge triage={bestSignalTriage(signal)} />
        {signal.live_adjusted ? (
          <span className="rounded border border-emerald-500/40 px-1 text-[9px] font-semibold uppercase text-emerald-600">
            Live
          </span>
        ) : null}
        <span className="dashboard-mono text-[10px] text-muted-foreground">
          n={signal.n ?? "--"}
        </span>
      </div>
    </div>
  )
}

function BestSignalBadgeCell({ signal }: { signal: DashboardBestSignal | null }) {
  if (!signal) return <SignalBadge label="Indisponible" />
  return <SignalBadge label={bestSignalLabel(signal)} />
}

function BestSignalExpectedReturnCell({
  signal,
  fallbackDays,
}: {
  signal: DashboardBestSignal | null
  fallbackDays: number
}) {
  if (!signal) {
    return (
      <div className="space-y-0.5 text-right text-muted-foreground">
        <div>No eligible</div>
        <div className="dashboard-mono text-[10px]">net edge</div>
      </div>
    )
  }
  return (
    <div className="space-y-0.5 text-right">
      <div>{formatPercent(signal.action_expected_return_net ?? null)}</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        {bestSignalActionLabel(signal)} {bestSignalHoldingPeriodLabel(signal, fallbackDays)} [{formatPercent(signal.action_expected_return_net_ci_lower ?? null)}, {formatPercent(signal.action_expected_return_net_ci_upper ?? null)}]
      </div>
    </div>
  )
}

export function StockTable({
  stocks,
  horizon,
  horizonDays,
  signalView = "expanded",
  scoreSource = "wfo",
  displayMode = "trade_opportunities",
  technicalDirectionMode = "best",
  hideDetails = false,
  edgeEnabled = true,
  visibleFamilies,
  showSupportResistance = false,
  showSrConfidence = true,
  selectedSymbols,
  onToggleSelected,
  performancePeriod = "one_day",
  onPerformancePeriodChange,
}: StockTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("expected_return")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const [expandedSymbol, setExpandedSymbol] = useState<string | null>(null)
  const isTechnicalMode = displayMode === "technical_directions"

  const shownFamilies = useMemo(
    () => FAMILY_ORDER.filter((family) => visibleFamilies?.[family] !== false),
    [visibleFamilies],
  )

  useEffect(() => {
    if (FAMILY_ORDER.includes(sortKey as FamilyKey) && !shownFamilies.includes(sortKey as FamilyKey)) {
      setSortKey(isTechnicalMode ? "technical_signal" : "expected_return")
      setSortDir("desc")
    }
  }, [isTechnicalMode, shownFamilies, sortKey])

  useEffect(() => {
    if (isTechnicalMode && ["best_signal", "expected_return", "hit_rate", "edge"].includes(sortKey)) {
      setSortKey("technical_signal")
      setSortDir("desc")
    }
    if (!isTechnicalMode && sortKey === "technical_signal") {
      setSortKey("expected_return")
      setSortDir("desc")
    }
  }, [isTechnicalMode, sortKey])

  useEffect(() => {
    if (expandedSymbol && !stocks.some((stock) => stock.symbol === expandedSymbol)) {
      setExpandedSymbol(null)
    }
  }, [expandedSymbol, stocks])

  const sorted = useMemo(() => {
    return [...stocks].sort((left, right) => {
      let leftValue: number | string | null = null
      let rightValue: number | string | null = null

      if (sortKey === "symbol") {
        leftValue = left.symbol
        rightValue = right.symbol
      } else if (sortKey === "price") {
        leftValue = priceForDisplay(left)
        rightValue = priceForDisplay(right)
      } else if (sortKey === "performance") {
        leftValue = selectedPerformancePct(left, performancePeriod)
        rightValue = selectedPerformancePct(right, performancePeriod)
      } else if (sortKey === "adv") {
        leftValue = left.adv ?? null
        rightValue = right.adv ?? null
      } else if (sortKey === "signal") {
        leftValue = isTechnicalMode ? technicalSignalForDisplay(left, technicalDirectionMode)?.score_pct ?? null : bestSignalSortScore(bestSignalForDisplay(left))
        rightValue = isTechnicalMode ? technicalSignalForDisplay(right, technicalDirectionMode)?.score_pct ?? null : bestSignalSortScore(bestSignalForDisplay(right))
      } else if (sortKey === "best_signal") {
        leftValue = bestSignalSortScore(bestSignalForDisplay(left))
        rightValue = bestSignalSortScore(bestSignalForDisplay(right))
      } else if (sortKey === "technical_signal") {
        leftValue = technicalSignalForDisplay(left, technicalDirectionMode)?.abs_score_pct ?? null
        rightValue = technicalSignalForDisplay(right, technicalDirectionMode)?.abs_score_pct ?? null
      } else if (sortKey === "expected_return") {
        leftValue = bestSignalForDisplay(left)?.action_expected_return_net ?? null
        rightValue = bestSignalForDisplay(right)?.action_expected_return_net ?? null
      } else if (sortKey === "hit_rate") {
        leftValue = bestSignalForDisplay(left)?.hit_rate ?? null
        rightValue = bestSignalForDisplay(right)?.hit_rate ?? null
      } else if (sortKey === "edge") {
        leftValue = bestSignalSortScore(bestSignalForDisplay(left))
        rightValue = bestSignalSortScore(bestSignalForDisplay(right))
      } else {
        leftValue = isTechnicalMode
          ? technicalFamilyForDisplay(left, sortKey, technicalDirectionMode)?.score_pct ?? null
          : scoreSource === "wfo"
            ? left.scores.wfo?.per_family[sortKey]?.score_pct ?? null
            : resolveSeFamily(left, sortKey, signalView)?.score_pct ?? null
        rightValue = isTechnicalMode
          ? technicalFamilyForDisplay(right, sortKey, technicalDirectionMode)?.score_pct ?? null
          : scoreSource === "wfo"
            ? right.scores.wfo?.per_family[sortKey]?.score_pct ?? null
            : resolveSeFamily(right, sortKey, signalView)?.score_pct ?? null
      }

      const primary = compareValues(leftValue, rightValue, sortDir)
      if (primary !== 0) return primary
      return left.symbol.localeCompare(right.symbol)
    })
  }, [stocks, sortKey, sortDir, scoreSource, signalView, isTechnicalMode, technicalDirectionMode, performancePeriod])

  function onSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(nextKey)
    setSortDir("desc")
  }

  function SortIcon({ columnKey }: { columnKey: SortKey }) {
    if (columnKey !== sortKey) return <ChevronsUpDown className="h-3 w-3" />
    return sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
  }

  if (sorted.length === 0) {
    return <div className="dashboard-panel px-4 py-12 text-center text-sm text-muted-foreground">Aucune action ne correspond aux filtres.</div>
  }

  const tableMinWidthClass = !isTechnicalMode
    ? showSupportResistance ? "min-w-[1080px]" : "min-w-[980px]"
    : shownFamilies.length === 0
      ? showSupportResistance ? "min-w-[1040px]" : "min-w-[940px]"
      : shownFamilies.length < FAMILY_ORDER.length
        ? showSupportResistance ? "min-w-[1140px]" : "min-w-[1040px]"
        : showSupportResistance ? "min-w-[1260px]" : "min-w-[1160px]"
  const tableColumnCount =
    (onToggleSelected ? 1 : 0)
    + 5
    + (showSupportResistance ? 1 : 0)
    + (isTechnicalMode && !hideDetails ? shownFamilies.length : 0)
    + 3
    + (!isTechnicalMode && edgeEnabled ? 2 : 0)
    + 1

  function toggleChart(symbol: string) {
    setExpandedSymbol((prev) => (prev === symbol ? null : symbol))
  }

  function evidenceHrefForStock(stock: DashboardStock) {
    const bestSignal = bestSignalForDisplay(stock)
    const technicalSignal = technicalSignalForDisplay(stock, technicalDirectionMode)
    const signalViewQuery = isTechnicalMode
      ? technicalEvidenceView(technicalSignal, technicalDirectionMode)
      : "expanded_ta_simple"
    const evidenceVariant = isTechnicalMode
      ? technicalDirectionMode !== "classic" ? technicalSignal?.variant : undefined
      : bestSignal?.variant

    return signalEvidenceUrl({
      symbol: stock.symbol,
      horizon,
      view: isTechnicalMode ? signalViewQuery : evidenceVariant ?? signalViewQuery,
      source: "wfo",
      evidenceVariant: undefined,
      scope: isTechnicalMode ? "global" : undefined,
      scopeKey: isTechnicalMode ? "global" : undefined,
      tab: isTechnicalMode ? "technique" : "evidence",
    })
  }

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <h3 className="dashboard-section-title">Signaux par titre · Horizon {horizonLabel(horizon)} ({horizonDays} j)</h3>
        <div className="dashboard-meta">{sorted.length} lignes · triées par retour attendu</div>
      </div>

      <div className="grid gap-2 bg-background p-2 md:hidden">
        {sorted.map((stock) => {
          const bestSignal = bestSignalForDisplay(stock)
          const technicalSignal = technicalSignalForDisplay(stock, technicalDirectionMode)
          const evidenceHref = evidenceHrefForStock(stock)
          const selected = selectedSymbols?.has(stock.symbol) ?? false
          const chartOpen = expandedSymbol === stock.symbol
          const srRow = stock.scores.wfo?.support_resistance ?? null

          return (
            <article key={`mobile-${stock.symbol}`} className="rounded-lg border border-border bg-card px-3 py-3 shadow-xs">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2">
                  {onToggleSelected ? (
                    <Checkbox
                      checked={selected}
                      onCheckedChange={() => onToggleSelected(stock.symbol)}
                      aria-label={`Select ${stock.symbol}`}
                      className="mt-0.5"
                    />
                  ) : null}
                  <div className="min-w-0">
                    <Link href={evidenceHref} className="dashboard-mono text-[14px] font-bold hover:underline">
                      {stock.symbol}
                    </Link>
                    <div className="truncate text-[12px] text-muted-foreground">{stock.display_name ?? "-"}</div>
                  </div>
                </div>
                <div className={cn("dashboard-mono shrink-0 text-right text-[12px] font-semibold", varToneClass(selectedPerformancePct(stock, performancePeriod)))}>
                  {formatVarPct(selectedPerformancePct(stock, performancePeriod))}
                </div>
              </div>

              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {isTechnicalMode ? (
                  <SignalBadge label={technicalSignal?.signal_label ?? "Indisponible"} />
                ) : (
                  <>
                    <BestSignalBadgeCell signal={bestSignal} />
                    <EdgeBadge triage={bestSignalTriage(bestSignal)} />
                  </>
                )}
              </div>

              {showSupportResistance ? (
                <div className="mt-3 border-t border-border pt-2">
                  <div className="mb-1 text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                    S/R
                  </div>
                  <SrWfoCell
                    row={srRow}
                    loading={false}
                    error={null}
                    showConfidence={showSrConfidence}
                  />
                </div>
              ) : null}

              <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-2">
                <div className="min-w-0">
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                    {isTechnicalMode ? "Score" : "E[R]"}
                  </div>
                  <div className="dashboard-mono mt-0.5 truncate text-[13px] font-semibold">
                    {isTechnicalMode
                      ? formatScorePct(technicalSignal?.score_pct)
                      : formatPercent(bestSignal?.action_expected_return_net ?? null)}
                  </div>
                </div>
                <div className="min-w-0 text-center">
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                    {isTechnicalMode ? "Direction" : "Hit"}
                  </div>
                  <div className="dashboard-mono mt-0.5 truncate text-[13px] font-semibold">
                    {isTechnicalMode
                      ? technicalSignal?.direction === "long" ? "Long" : technicalSignal?.direction === "short" ? "Short" : "Neutre"
                      : formatPercent(bestSignal?.hit_rate ?? null)}
                  </div>
                </div>
                <div className="min-w-0 text-right">
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                    {isTechnicalMode ? "Prix" : "Hold"}
                  </div>
                  <div className="dashboard-mono mt-0.5 truncate text-[13px] font-semibold">
                    {isTechnicalMode ? formatNumber(priceForDisplay(stock)) : bestSignalHoldingPeriodLabel(bestSignal, horizonDays)}
                  </div>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => toggleChart(stock.symbol)}
                  aria-expanded={chartOpen}
                  className={cn(
                    "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border text-[12px] font-semibold",
                    chartOpen
                      ? "border-foreground bg-foreground text-background"
                      : "border-border bg-bg2 text-foreground",
                  )}
                >
                  <BarChart3 className="h-3.5 w-3.5" />
                  Chart
                </button>
                <Link
                  href={evidenceHref}
                  className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-border bg-bg2 text-[12px] font-semibold text-foreground"
                >
                  Voir detail
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
              {chartOpen ? (
                <div className="-mx-3 mt-3">
                  <DashboardSignalChartPanel
                    stock={stock}
                    horizon={horizon}
                    horizonDays={horizonDays}
                    displayMode={displayMode}
                    technicalDirectionMode={technicalDirectionMode}
                    evidenceHref={evidenceHref}
                  />
                </div>
              ) : null}
            </article>
          )
        })}
      </div>

      <div className="hidden overflow-x-auto md:block">
      <Table className={cn(tableMinWidthClass, "text-[12px]")}>
        <TableHeader>
          <TableRow className="border-b border-border bg-bg2 hover:bg-bg2">
            {onToggleSelected ? (
              <TableHead className="h-auto w-9 px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground" />
            ) : null}
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("symbol")}>
                Ticker
                <SortIcon columnKey="symbol" />
              </button>
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Nom</TableHead>
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("price")}>
                Prix
                <SortIcon columnKey="price" />
              </button>
            </TableHead>
            {showSupportResistance ? (
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                S/R
              </TableHead>
            ) : null}
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <span className="inline-flex items-center justify-end gap-1">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("performance")}>
                  {performanceHeaderLabel(performancePeriod)}
                  <SortIcon columnKey="performance" />
                </button>
                {onPerformancePeriodChange ? (
                  <select
                    value={performancePeriod}
                    onChange={(event) => onPerformancePeriodChange(event.target.value as PerformancePeriod)}
                    className="h-6 rounded border border-border bg-background px-1 text-[10px] normal-case tracking-normal text-foreground"
                    aria-label="Performance period"
                  >
                    <option value="one_day">1D</option>
                    <option value="wtd">WTD</option>
                    <option value="mtd">MTD</option>
                    <option value="ytd">YTD</option>
                    <option value="open_to_now">O/N</option>
                  </select>
                ) : null}
              </span>
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <span className="inline-flex items-center justify-end gap-1">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("adv")}>
                  ADV20 MAD
                  <SortIcon columnKey="adv" />
                </button>
                <GlossaryHelpLink href="/glossary#adv20" label="Definition ADV20" />
              </span>
            </TableHead>
            {isTechnicalMode && !hideDetails && shownFamilies.includes("tendance") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Trend.
                  <GlossaryHelpLink href="/glossary#tendance" label="Definition Tendance" />
                </span>
              </TableHead>
            ) : null}
            {isTechnicalMode && !hideDetails && shownFamilies.includes("momentum") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Mom.
                  <GlossaryHelpLink href="/glossary#momentum" label="Definition Momentum" />
                </span>
              </TableHead>
            ) : null}
            {isTechnicalMode && !hideDetails && shownFamilies.includes("oscillation") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Osc.
                  <GlossaryHelpLink href="/glossary#oscillation" label="Definition Oscillation" />
                </span>
              </TableHead>
            ) : null}
            {isTechnicalMode && !hideDetails && shownFamilies.includes("volume") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Vol.
                  <GlossaryHelpLink href="/glossary#volume" label="Definition Volume" />
                </span>
              </TableHead>
            ) : null}
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort(isTechnicalMode ? "technical_signal" : "signal")}>
                  {isTechnicalMode ? `Direction ${technicalModeShortLabel(technicalDirectionMode)}` : "Signal"}
                  <SortIcon columnKey={isTechnicalMode ? "technical_signal" : "signal"} />
                </button>
                <GlossaryHelpLink href="/glossary#signal-badge" label="Definition Badge signal" />
              </span>
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort(isTechnicalMode ? "technical_signal" : "best_signal")}>
                  {isTechnicalMode ? "Methode technique" : "Methode auto"}
                  <SortIcon columnKey={isTechnicalMode ? "technical_signal" : "best_signal"} />
                </button>
                <GlossaryHelpLink href="/glossary#best-signal" label="Definition Meilleure methode auto" />
              </span>
            </TableHead>
            {isTechnicalMode ? (
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("technical_signal")}>
                  Score technique
                  <SortIcon columnKey="technical_signal" />
                </button>
              </TableHead>
            ) : (
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center justify-end gap-1">
                  <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("expected_return")}>
                    retour attendu
                    <SortIcon columnKey="expected_return" />
                  </button>
                  <GlossaryHelpLink href="/glossary#action-er" label="Definition Action E[R]" />
                </span>
              </TableHead>
            )}
            {!isTechnicalMode && edgeEnabled ? (
              <>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <span className="inline-flex items-center justify-end gap-1">
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("hit_rate")}>
                      %succés
                      <SortIcon columnKey="hit_rate" />
                    </button>
                    <GlossaryHelpLink href="/glossary#hit-rate" label="Definition Hit rate" />
                  </span>
                </TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("edge")}>
                      Edge
                      <SortIcon columnKey="edge" />
                    </button>
                    <GlossaryHelpLink href="/glossary#edge" label="Definition Edge" />
                  </span>
                </TableHead>
              </>
            ) : null}
            <TableHead className="h-auto w-10 px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((stock) => {
            const bestSignal = bestSignalForDisplay(stock)
            const technicalSignal = technicalSignalForDisplay(stock, technicalDirectionMode)
            const signalViewQuery = isTechnicalMode
              ? technicalEvidenceView(technicalSignal, technicalDirectionMode)
              : "expanded_ta_simple"
            const evidenceVariant = isTechnicalMode
              ? technicalDirectionMode !== "classic" ? technicalSignal?.variant : undefined
              : bestSignal?.variant
            const evidenceHref = signalEvidenceUrl({
              symbol: stock.symbol,
              horizon,
              view: isTechnicalMode ? signalViewQuery : evidenceVariant ?? signalViewQuery,
              source: "wfo",
              evidenceVariant: undefined,
              scope: isTechnicalMode ? "global" : undefined,
              scopeKey: isTechnicalMode ? "global" : undefined,
              tab: isTechnicalMode ? "technique" : "evidence",
            })
            const selected = selectedSymbols?.has(stock.symbol) ?? false
            const chartOpen = expandedSymbol === stock.symbol
            const srRow = stock.scores.wfo?.support_resistance ?? null

            return (
              <Fragment key={stock.symbol}>
                <TableRow className="border-b border-border/70 hover:bg-bg2">
                {onToggleSelected ? (
                  <TableCell className="px-2 py-2.5 align-middle">
                    <Checkbox
                      checked={selected}
                      onCheckedChange={() => onToggleSelected(stock.symbol)}
                      aria-label={`Select ${stock.symbol}`}
                    />
                  </TableCell>
                ) : null}
                <TableCell className="px-3 py-2.5 align-middle">
                  <Link href={evidenceHref} className="dashboard-mono text-[12px] font-semibold hover:underline">
                    {stock.symbol}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[220px] px-3 py-2.5">
                  <Link
                    href={evidenceHref}
                    className="block hover:underline"
                  >
                    <div className="text-[12px] font-medium">{stock.display_name ?? "-"}</div>
                  </Link>
                </TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                  <div>{formatNumber(priceForDisplay(stock))}</div>
                  <div className={cn("text-[9px]", stock.live_quote && !stock.live_quote.is_fresh ? "text-amber-600" : "text-muted-foreground")}>
                    {quoteStatusLabel(stock)}
                  </div>
                </TableCell>
                {showSupportResistance ? (
                  <TableCell className="px-3 py-2.5 text-right align-middle">
                    <SrWfoCell
                      row={srRow}
                      loading={false}
                      error={null}
                      showConfidence={showSrConfidence}
                    />
                  </TableCell>
                ) : null}
                <TableCell className={cn("dashboard-mono px-3 py-2.5 text-right text-[11px] font-semibold", varToneClass(selectedPerformancePct(stock, performancePeriod)))}>
                  {formatVarPct(selectedPerformancePct(stock, performancePeriod))}
                </TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px] text-muted-foreground">{formatNumber(stock.adv ?? null, 0)}</TableCell>
                {isTechnicalMode && !hideDetails && shownFamilies.includes("tendance") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "tendance", technicalDirectionMode)} factorDependencies={technicalFactorDependencies(stock, "tendance", technicalDirectionMode)} /></TableCell>
                ) : null}
                {isTechnicalMode && !hideDetails && shownFamilies.includes("momentum") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "momentum", technicalDirectionMode)} factorDependencies={technicalFactorDependencies(stock, "momentum", technicalDirectionMode)} /></TableCell>
                ) : null}
                {isTechnicalMode && !hideDetails && shownFamilies.includes("oscillation") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "oscillation", technicalDirectionMode)} factorDependencies={technicalFactorDependencies(stock, "oscillation", technicalDirectionMode)} /></TableCell>
                ) : null}
                {isTechnicalMode && !hideDetails && shownFamilies.includes("volume") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "volume", technicalDirectionMode)} factorDependencies={technicalFactorDependencies(stock, "volume", technicalDirectionMode)} /></TableCell>
                ) : null}
                <TableCell className="px-3 py-2.5">
                  {isTechnicalMode ? <SignalBadge label={technicalSignal?.signal_label ?? "Indisponible"} /> : <BestSignalBadgeCell signal={bestSignal} />}
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  {isTechnicalMode ? (
                    technicalSignal ? (
                      <div className="space-y-1">
                        <div className="max-w-[180px] truncate text-[11px] font-semibold" title={technicalSignal.label}>
                          {technicalSignal.label.replace("Signal Engine - ", "Engine ").replace("Factor x TA", "FX").trim()}
                        </div>
                        <div className="dashboard-mono text-[10px] text-muted-foreground">
                          {technicalDirectionMode === "classic"
                            ? "Fixed classic"
                            : `${sourceLabel(technicalSignal.source)} - ${displayVariantLabel(technicalSignal.variant)}`}
                          {technicalSignal.live_adjusted ? " - Live" : ""}
                        </div>
                      </div>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">No technical signal</span>
                    )
                  ) : <BestSignalMethodCell signal={bestSignal} />}
                </TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                  <Link href={evidenceHref} className="block hover:text-foreground hover:underline">
                    {isTechnicalMode ? (
                      <div className="space-y-0.5 text-right">
                        <div>{formatScorePct(technicalSignal?.score_pct)}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {technicalSignal?.direction === "long" ? "Long" : technicalSignal?.direction === "short" ? "Short" : "Neutre"}
                        </div>
                      </div>
                    ) : (
                      <BestSignalExpectedReturnCell signal={bestSignal} fallbackDays={horizonDays} />
                    )}
                  </Link>
                </TableCell>
                {!isTechnicalMode && edgeEnabled ? (
                  <>
                    <TableCell className="px-3 py-2.5 text-right">
                      {bestSignal ? (
                        <div className="space-y-0.5 text-right">
                          <div className="dashboard-mono text-[11px]">{formatPercent(bestSignal.hit_rate ?? null)}</div>
                          <div className="dashboard-mono text-[10px] text-muted-foreground">
                            [{bestSignal.hit_ci_lower?.toFixed(2) ?? "--"}, {bestSignal.hit_ci_upper?.toFixed(2) ?? "--"}]
                          </div>
                        </div>
                      ) : (
                        <span className="dashboard-mono text-[10px] text-muted-foreground">No actionable</span>
                      )}
                    </TableCell>
                    <TableCell className="px-3 py-2.5">
                      <div className="space-y-0.5">
                        <EdgeBadge triage={bestSignalTriage(bestSignal)} />
                        <div className="dashboard-mono text-[10px] text-muted-foreground">
                          Score {formatEdgeScore(bestSignalEdgeScore(bestSignal))}
                        </div>
                      </div>
                    </TableCell>
                  </>
                ) : null}
                <TableCell className="px-2 py-2.5 align-middle">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      type="button"
                      onClick={() => toggleChart(stock.symbol)}
                      aria-expanded={chartOpen}
                      className={cn(
                        "inline-flex h-7 w-7 items-center justify-center rounded-md border transition",
                        chartOpen
                          ? "border-foreground bg-foreground text-background"
                          : "border-transparent text-muted-foreground hover:border-border hover:bg-muted/30 hover:text-foreground",
                      )}
                      aria-label={`Afficher le graphique ${stock.symbol}`}
                      title={`Graphique ${stock.symbol}`}
                    >
                      <BarChart3 className="h-3.5 w-3.5" />
                    </button>
                    <Link
                      href={evidenceHref}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-muted-foreground transition hover:border-border hover:bg-muted/30 hover:text-foreground"
                      aria-label={`Voir la preuve OOS ${stock.symbol}`}
                    >
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </TableCell>
              </TableRow>
              {chartOpen ? (
                <TableRow className="border-b border-border/70 bg-background hover:bg-background">
                  <TableCell colSpan={tableColumnCount} className="p-0">
                    <DashboardSignalChartPanel
                      stock={stock}
                      horizon={horizon}
                      horizonDays={horizonDays}
                      displayMode={displayMode}
                      technicalDirectionMode={technicalDirectionMode}
                      evidenceHref={evidenceHref}
                    />
                  </TableCell>
                </TableRow>
              ) : null}
              </Fragment>
            )
          })}
        </TableBody>
      </Table>
      </div>
    </div>
  )
}
