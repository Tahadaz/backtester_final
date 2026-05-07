"use client"

import { useParams, usePathname, useSearchParams, useRouter } from "next/navigation"
import { useState, useMemo } from "react"
import {
  useSupportResistanceVariantBacktest,
  useSupportResistanceVariantDetail,
  useVariantBacktest,
  useVariantDetail,
} from "@/hooks/use-api"
import { SignalScoreBar } from "@/components/strategy/signal-score-bar"
import { SignalBadge } from "@/components/signal-badge"
import { PipelineStepper } from "@/components/strategy/pipeline-stepper"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip"
import { ArrowLeft, ChevronDown, ChevronRight, Loader2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { signalVariantLabel } from "@/lib/signal-variant-label"
import { ICStatsChip } from "@/components/signals/ic-stats-chip"
import type { VariantDetail, VariantSummary, VariantBacktest, PlotlyFigure } from "@/lib/api"

type Tab = "comparaison" | "oos" | "fiabilite"
type SortKey = "reliability_score" | "cagr" | "mean_sharpe" | "total_pnl"

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  selected: { label: "Selectionne", cls: "text-green-700 border-green-300 bg-green-50" },
  redundancy_filtered: { label: "Redondant", cls: "text-amber-700 border-amber-300 bg-amber-50" },
  percentile_cutoff: { label: "Elimine", cls: "text-gray-600 border-gray-300 bg-gray-50" },
  not_viable: { label: "Non-viable", cls: "text-red-700 border-red-300 bg-red-50" },
  adaptive_fallback: { label: "Fallback adaptatif", cls: "text-amber-800 border-amber-300 bg-amber-50" },
  live_only_fallback: { label: "Signal live", cls: "text-orange-800 border-orange-300 bg-orange-50" },
}

function variantLabel(v: VariantSummary): string {
  return signalVariantLabel(v)
}

function formatNumber(n: number): string {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}k`
  if (Number.isInteger(n)) return n.toLocaleString()
  return n.toFixed(2)
}

function formatTradePrice(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  })
}

function formatHoldPeriodDays(n: number): string {
  return `${Number.isInteger(n) ? n : n.toFixed(1)} j`
}

function formatPercent(n: number): string {
  return `${(n * 100).toFixed(2)}%`
}

function formatBacktestMetricLabel(metric: string): string {
  if (metric === "total_pnl") return "PnL simule (100k)"
  if (metric === "total_pnl_100k") return "PnL simule (100k)"
  if (metric === "total_pnl_realise_1u") return "PnL realise total (1 unite)"
  if (metric === "mean_hold_period_between_trades_days") return "Mean Hold Period (jours)"
  return metric.replace(/_/g, " ")
}

function formatTradeMetricLabel(metric: string): string {
  if (metric === "total_pnl_realise") return "PnL realise (registre, 1 unite)"
  return metric.replace(/_/g, " ")
}

function normalizeMetricKey(metric: string): string {
  return metric.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")
}

function shouldHideTradePerformanceMetric(metric: string): boolean {
  const key = normalizeMetricKey(metric)
  return key === "n_oos_windows" || key === "total_pnl" || key === "total_pnl_100k"
}

function meanHoldPeriodBetweenTradesDays(trades: Record<string, unknown>[]): number | null {
  const timestamps = trades
    .map((trade) => {
      const rawDate = trade.date
      if (typeof rawDate !== "string" || !rawDate) return null
      const timestamp = new Date(rawDate).getTime()
      return Number.isFinite(timestamp) ? timestamp : null
    })
    .filter((timestamp): timestamp is number => timestamp != null)
    .sort((a, b) => a - b)

  if (timestamps.length < 2) return null

  const dayDiffs: number[] = []
  for (let i = 1; i < timestamps.length; i += 1) {
    dayDiffs.push((timestamps[i] - timestamps[i - 1]) / (1000 * 60 * 60 * 24))
  }

  if (dayDiffs.length === 0) return null
  return dayDiffs.reduce((sum, value) => sum + value, 0) / dayDiffs.length
}

export default function VariantDetailPage() {
  const params = useParams()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const router = useRouter()
  const [tab, setTab] = useState<Tab>("comparaison")
  const costBps = 33
  const cooldownBars = Number(searchParams.get("cooldown") ?? 0)

  const variantId = decodeURIComponent(params.id as string)
  const symbol = searchParams.get("symbol")
  const horizon = searchParams.get("horizon") ?? "medium"
  const variant = searchParams.get("variant") ?? "expanded"
  const srMode = pathname.includes("/signals/sr-variant/")

  const standardDetail = useVariantDetail(srMode ? null : variantId, symbol, horizon, costBps, cooldownBars, variant)
  const srDetail = useSupportResistanceVariantDetail(
    srMode ? variantId : null,
    symbol,
    horizon,
    costBps,
    cooldownBars,
    variant,
    srMode,
  )
  const data = srMode ? srDetail.data : standardDetail.data
  const isLoading = srMode ? srDetail.isLoading : standardDetail.isLoading
  const error = srMode ? srDetail.error : standardDetail.error

  if (!symbol) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        Parametre &quot;symbol&quot; manquant dans l&apos;URL.
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="p-6 space-y-4 max-w-5xl mx-auto">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="p-6 max-w-5xl mx-auto">
        <Card className="border-destructive/50">
          <CardContent className="py-8 text-center">
            <p className="text-sm text-destructive font-medium">
              Erreur lors du chargement du detail
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {error instanceof Error ? error.message : "Variante introuvable"}
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: "comparaison", label: "Comparaison" },
    { key: "oos", label: "Fenetres OOS" },
    { key: "fiabilite", label: "Fiabilite" },
  ]

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour
        </Button>
        <div className="flex items-center gap-3 flex-1">
          {!srMode && (
            <div className="w-40">
              <SignalScoreBar value={data.signal * 100} size="md" />
            </div>
          )}
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold">{srMode ? "Couple S/R" : symbol}</h1>
              <Badge variant="outline" className="text-xs font-medium px-2 py-0.5">
                {horizon === "short" ? "Court terme" : horizon === "medium" ? "Moyen terme" : "Long terme"}
              </Badge>
            </div>
            <p className="text-sm font-medium text-muted-foreground mt-0.5">{data.description}</p>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="outline" className="text-[10px]">
                {data.archetype}
              </Badge>
              {!srMode && <SignalBadge value={data.signal} label={data.signal_label} size="sm" />}
              {!srMode && data.selection_status && (
                <Badge variant="outline" className={`text-[10px] ${STATUS_BADGE[data.selection_status]?.cls ?? ""}`}>
                  {STATUS_BADGE[data.selection_status]?.label ?? data.selection_status}
                </Badge>
              )}
              {!srMode && symbol && (
                <ICStatsChip symbol={symbol} horizon={horizon} archetype={data.archetype} />
              )}
            </div>
          </div>
        </div>
      </div>

      {data.methodology_context.is_provisional && data.methodology_context.warning_message && (
        <Card className="border-amber-300 bg-amber-50/60">
          <CardContent className="py-3 text-xs text-amber-900">
            <div className="font-semibold mb-1">Signal provisoire</div>
            <p>{data.methodology_context.warning_message}</p>
          </CardContent>
        </Card>
      )}

      {/* Pipeline stepper — will be made clickable inside ComparisonTab */}
      {!srMode && tab !== "comparaison" && (
        <PipelineStepper
          tested={data.funnel.tested}
          viable={data.funnel.viable}
          competitive={data.funnel.competitive}
          representative={data.funnel.representative}
        />
      )}

      {/* Cooldown display */}
      {cooldownBars > 0 && (
        <div className="flex items-center gap-1.5 text-xs">
          <span className="text-muted-foreground">Cooldown:</span>
          <Badge variant="outline" className="text-[10px] font-mono">{cooldownBars} bars</Badge>
        </div>
      )}

      {/* Tab switcher */}
      <div className="flex gap-1 border-b">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
              tab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "comparaison" && (
        <ComparisonTab
          data={data}
          currentId={variantId}
          symbol={symbol}
          horizon={horizon}
          costBps={costBps}
          cooldownBars={cooldownBars}
          srMode={srMode}
          variant={variant}
        />
      )}
      {tab === "oos" && <OOSTab data={data} />}
      {tab === "fiabilite" && <ReliabilityTab data={data} />}
    </div>
  )
}

/* -- Tab 1: Comparaison -------------------------------------------------- */

function ComparisonTab({
  data,
  currentId,
  symbol,
  horizon,
  costBps,
  cooldownBars,
  srMode,
  variant,
}: {
  data: VariantDetail
  currentId: string
  symbol: string
  horizon: string
  costBps: number
  cooldownBars: number
  srMode: boolean
  variant: string
}) {
  const [sortBy, setSortBy] = useState<SortKey>("reliability_score")
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [stageFilter, setStageFilter] = useState<string | null>(null)

  const filtered = useMemo(() => {
    if (srMode) return data.all_variants
    if (!stageFilter) return data.all_variants
    return data.all_variants.filter((v) => {
      switch (stageFilter) {
        case "tested":
          return true
        case "viable":
          return v.is_viable
        case "competitive":
          return v.is_survivor
        case "representative":
          return v.is_representative
        default:
          return true
      }
    })
  }, [data.all_variants, stageFilter, srMode])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      switch (sortBy) {
        case "cagr":
          return b.cagr - a.cagr
        case "mean_sharpe":
          return b.mean_sharpe - a.mean_sharpe
        case "total_pnl":
          return b.total_pnl - a.total_pnl
        default:
          return b.reliability_score - a.reliability_score
      }
    })
  }, [filtered, sortBy])

  return (
    <div className="space-y-4">
      {!srMode && (
        <PipelineStepper
          tested={data.funnel.tested}
          viable={data.funnel.viable}
          competitive={data.funnel.competitive}
          representative={data.funnel.representative}
          activeStage={stageFilter}
          onStageClick={setStageFilter}
        />
      )}

      <Card>
        <CardHeader className="pb-2 pt-3 px-4 flex flex-row items-center justify-between">
          <CardTitle className="text-xs font-semibold">
            {srMode
              ? `Couples S/R compares (${sorted.length})`
              : stageFilter
              ? `Variantes — ${stageFilter} (${sorted.length})`
              : `Toutes les variantes (${sorted.length})`}
          </CardTitle>
          <select
            className="text-[10px] border rounded px-1.5 py-0.5 bg-background"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortKey)}
          >
            <option value="reliability_score">Score</option>
            <option value="cagr">CAGR</option>
            <option value="mean_sharpe">Sharpe</option>
            <option value="total_pnl">PnL (100k)</option>
          </select>
        </CardHeader>
        <CardContent className="px-0 pb-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-secondary/30">
                  <th className="text-left px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">#</th>
                  <th className="text-left px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Variante</th>
                  {!srMode && (
                    <th className="text-center px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Signal</th>
                  )}
                  <th className="text-right px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">CAGR</th>
                  <th className="text-right px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Sharpe</th>
                  <th className="text-right px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Max DD</th>
                  <th className="text-right px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">PnL (100k)</th>
                  <th className="text-right px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Fen+</th>
                  <th className="text-right px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Score</th>
                  {!srMode && (
                    <th className="text-center px-2.5 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Statut</th>
                  )}
                  <th className="px-2.5 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((v, i) => {
                  const isExpanded = expandedId === v.variant_id
                  return (
                    <VariantRow
                      key={v.variant_id}
                      v={v}
                      idx={i}
                      isCurrent={v.variant_id === currentId}
                      isExpanded={isExpanded}
                      symbol={symbol}
                      horizon={horizon}
                      costBps={costBps}
                      cooldownBars={cooldownBars}
                      srMode={srMode}
                      variant={variant}
                      onToggle={() => setExpandedId(isExpanded ? null : v.variant_id)}
                    />
                  )
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function RankCircle({ idx }: { idx: number }) {
  const cls =
    idx === 0
      ? "bg-amber-100 text-amber-700 border-amber-300"
      : idx === 1
        ? "bg-slate-100 text-slate-600 border-slate-300"
        : idx === 2
          ? "bg-orange-100 text-orange-700 border-orange-300"
          : "bg-secondary text-muted-foreground"
  return (
    <span
      className={cn(
        "inline-flex h-5 w-5 items-center justify-center rounded-full border text-[10px] font-bold",
        cls,
      )}
    >
      {idx + 1}
    </span>
  )
}

function StatusBadgeWithTooltip({ v }: { v: VariantSummary }) {
  const statusKey = v.selection_status ?? v.elimination_reason
  const badge = STATUS_BADGE[statusKey] ?? STATUS_BADGE.not_viable

  let tooltipText = ""
  if (statusKey === "adaptive_fallback") {
    tooltipText = "Variante affichee en fallback adaptatif faute de representant strict."
  } else if (statusKey === "live_only_fallback") {
    tooltipText = "Variante affichee a partir du signal courant uniquement, sans validation OOS complete."
  } else if (v.elimination_reason === "redundancy_filtered" && v.correlated_with_label && v.correlation != null) {
    tooltipText = `r=${v.correlation.toFixed(2)} avec ${v.correlated_with_label}`
  } else if (v.elimination_reason === "percentile_cutoff" && v.threshold_score != null) {
    tooltipText = `Score ${(v.reliability_score * 100).toFixed(1)}% (seuil ${(v.threshold_score * 100).toFixed(1)}%)`
  } else if (v.elimination_reason === "not_viable" && v.viability_detail) {
    tooltipText = v.viability_detail
  } else if (v.elimination_reason === "selected") {
    tooltipText = `Selectionne comme representatif (score ${(v.reliability_score * 100).toFixed(1)}%)`
  }

  const badgeEl = (
    <Badge variant="outline" className={`text-[9px] ${badge.cls}`}>
      {badge.label}
    </Badge>
  )

  if (!tooltipText) return badgeEl

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help">{badgeEl}</span>
      </TooltipTrigger>
      <TooltipContent side="left" className="max-w-[200px]">
        <p className="text-xs">{tooltipText}</p>
      </TooltipContent>
    </Tooltip>
  )
}

function VariantRow({
  v,
  idx,
  isCurrent,
  isExpanded,
  symbol,
  horizon,
  costBps,
  cooldownBars,
  srMode,
  variant,
  onToggle,
}: {
  v: VariantSummary
  idx: number
  isCurrent: boolean
  isExpanded: boolean
  symbol: string
  horizon: string
  costBps: number
  cooldownBars: number
  srMode: boolean
  variant: string
  onToggle: () => void
}) {
  return (
    <>
      <tr
        className={cn(
          "border-b border-border/50 transition-colors cursor-pointer",
          isExpanded ? "bg-primary/5" : "hover:bg-secondary/40",
          isCurrent ? "font-semibold" : "",
          idx < 3 ? "font-medium" : "",
        )}
        onClick={onToggle}
      >
        <td className="px-2.5 py-2.5">
          <RankCircle idx={idx} />
        </td>
        <td className="px-2.5 py-2.5" title={v.variant_id}>
          <div className="font-mono font-bold text-sm">{variantLabel(v)}</div>
          <div className="text-[10px] text-muted-foreground capitalize">{v.archetype.replace(/_/g, " ")}</div>
        </td>
        {!srMode && (
          <td className="px-2.5 py-2.5 text-center">
            <SignalBadge value={v.signal_value} label={v.signal_label} size="sm" />
          </td>
        )}
        <td
          className={cn(
            "px-2.5 py-2.5 text-right font-mono",
            v.cagr > 0 ? "text-green-700" : v.cagr < 0 ? "text-red-700" : "",
          )}
        >
          {(v.cagr * 100).toFixed(1)}%
        </td>
        <td
          className={cn(
            "px-2.5 py-2.5 text-right font-mono",
            v.mean_sharpe > 0 ? "text-green-700" : "text-red-700",
          )}
        >
          {v.mean_sharpe.toFixed(2)}
        </td>
        <td className="px-2.5 py-2.5 text-right font-mono text-red-700">
          {(v.mean_max_drawdown * 100).toFixed(1)}%
        </td>
        <td
          className={cn(
            "px-2.5 py-2.5 text-right font-mono",
            v.total_pnl > 0 ? "text-green-700" : v.total_pnl < 0 ? "text-red-700" : "",
          )}
        >
          {formatNumber(v.total_pnl)}
        </td>
        <td className="px-2.5 py-2.5 text-right font-mono">
          {(v.fraction_positive_windows * 100).toFixed(1)}%
        </td>
        <td className="px-2.5 py-2.5 text-right">
          <span className="tabular-nums text-xs font-mono">
            {(v.reliability_score * 100).toFixed(1)}%
          </span>
        </td>
        {!srMode && (
          <td className="px-2.5 py-2.5 text-center">
            <StatusBadgeWithTooltip v={v} />
          </td>
        )}
        <td className="px-2.5 py-2.5 text-right">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground ml-auto" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground ml-auto" />
          )}
        </td>
      </tr>
      {isExpanded && (
        <tr>
          <td colSpan={srMode ? 9 : 11} className="p-0">
            <VariantDetailPanel
              variantId={v.variant_id}
              symbol={symbol}
              horizon={horizon}
              costBps={costBps}
              cooldownBars={cooldownBars}
              srMode={srMode}
              variant={variant}
            />
          </td>
        </tr>
      )}
    </>
  )
}

/* -- Variant Detail Panel (expanded row) --------------------------------- */

function VariantDetailPanel({
  variantId,
  symbol,
  horizon,
  costBps,
  cooldownBars,
  srMode,
  variant,
}: {
  variantId: string
  symbol: string
  horizon: string
  costBps: number
  cooldownBars: number
  srMode: boolean
  variant: string
}) {
  const standardBacktest = useVariantBacktest(srMode ? null : variantId, symbol, horizon, costBps, cooldownBars, variant)
  const srBacktest = useSupportResistanceVariantBacktest(
    srMode ? variantId : null,
    symbol,
    horizon,
    costBps,
    cooldownBars,
    variant,
    srMode,
  )
  const data = srMode ? srBacktest.data : standardBacktest.data
  const isLoading = srMode ? srBacktest.isLoading : standardBacktest.isLoading
  const error = srMode ? srBacktest.error : standardBacktest.error
  const [selectedWindow, setSelectedWindow] = useState<number | null>(null)
  const plotKeys = Object.keys(data?.plots ?? {})
  const hasPerWindow = (data?.per_window?.length ?? 0) > 0
  const activeWindow = selectedWindow != null ? data?.per_window.find((pw) => pw.window_index === selectedWindow) ?? null : null
  const filteredTradePerformance = useMemo(
    () => (data?.trade_performance ?? []).filter((row) => !shouldHideTradePerformanceMetric(String(row.metric ?? ""))),
    [data?.trade_performance],
  )
  const meanHoldPeriod = useMemo(
    () => meanHoldPeriodBetweenTradesDays(data?.trade_ledger ?? []),
    [data?.trade_ledger],
  )
  const activeWindowMeanHoldPeriod = useMemo(
    () => (activeWindow ? meanHoldPeriodBetweenTradesDays(activeWindow.trades) : null),
    [activeWindow],
  )
  const metricsEntries = useMemo(() => {
    const entries = Object.entries(data?.metrics ?? {})
    if (meanHoldPeriod == null) return entries
    return [...entries, ["mean_hold_period_between_trades_days", meanHoldPeriod] as [string, unknown]]
  }, [data?.metrics, meanHoldPeriod])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 border-t border-border bg-background">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="px-4 py-6 text-sm text-red-600 border-t border-border bg-background">
        Echec du chargement du backtest: {error instanceof Error ? error.message : "Erreur inconnue"}
      </div>
    )
  }

  return (
    <div className="border-t border-border bg-background p-4">
      {data.methodology_context?.is_provisional && data.warning_message && (
        <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {data.warning_message}
        </div>
      )}

      {/* OOS period selector */}
      {hasPerWindow && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          <button
            onClick={() => setSelectedWindow(null)}
            className={cn("px-2 py-1 rounded-md text-[10px] font-medium border transition-colors",
              selectedWindow === null ? "bg-primary text-primary-foreground border-primary" : "bg-secondary/50 text-muted-foreground border-border hover:bg-secondary"
            )}
          >
            Toutes
          </button>
          {data.per_window.map((pw) => (
            <button
              key={pw.window_index}
              onClick={() => setSelectedWindow(pw.window_index)}
              className={cn("px-2 py-1 rounded-md text-[10px] font-medium border transition-colors",
                selectedWindow === pw.window_index ? "bg-primary text-primary-foreground border-primary" :
                pw.sharpe > 0 ? "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100" :
                "bg-red-50 text-red-700 border-red-200 hover:bg-red-100"
              )}
            >
              #{pw.window_index + 1} ({pw.start_date} &rarr; {pw.end_date})
            </button>
          ))}
        </div>
      )}

      {/* Per-window metrics summary */}
      {activeWindow && (
        <div className="flex gap-4 mb-3 text-xs">
          <div>
            <span className="text-muted-foreground">Sharpe: </span>
            <span className={cn("font-mono font-semibold", activeWindow.sharpe > 0 ? "text-green-700" : "text-red-700")}>
              {activeWindow.sharpe.toFixed(2)}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">PnL (100k): </span>
            <span className={cn("font-mono font-semibold", activeWindow.pnl > 0 ? "text-green-700" : "text-red-700")}>
              {formatNumber(activeWindow.pnl)}
            </span>
          </div>
          <div>
            <span className="text-muted-foreground">Trades: </span>
            <span className="font-mono font-semibold">{activeWindow.n_trades}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Valide: </span>
            <span className={activeWindow.is_valid ? "text-green-600 font-semibold" : "text-red-600 font-semibold"}>
              {activeWindow.is_valid ? "Oui" : "Non"}
            </span>
          </div>
        </div>
      )}

      <Tabs defaultValue={plotKeys.length > 0 || activeWindow ? "graphiques" : "metriques"}>
        <TabsList className="mb-4">
          {(plotKeys.length > 0 || activeWindow) && <TabsTrigger value="graphiques">Graphiques</TabsTrigger>}
          <TabsTrigger value="metriques">Metriques</TabsTrigger>
          {((activeWindow ? activeWindow.trades.length : filteredTradePerformance.length) > 0) && (
            <TabsTrigger value="performance">Performance Trades</TabsTrigger>
          )}
          {((activeWindow ? activeWindow.trades.length : data.trade_ledger.length) > 0) && (
            <TabsTrigger value="ledger">Registre Trades</TabsTrigger>
          )}
        </TabsList>

        {/* Graphiques tab */}
        {(plotKeys.length > 0 || activeWindow) && (
          <TabsContent value="graphiques" className="space-y-4">
            {activeWindow && activeWindow.plot ? (
              <>
                <Card>
                  <CardHeader className="pb-2 pt-3 px-4">
                    <CardTitle className="text-sm">
                      Prix + Signal — Fenetre #{activeWindow.window_index + 1} ({activeWindow.start_date} &rarr; {activeWindow.end_date})
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-2 pb-2">
                    <PlotlyChart figure={activeWindow.plot as PlotlyFigure} />
                  </CardContent>
                </Card>
                {activeWindow.equity_plot && (
                  <Card>
                    <CardHeader className="pb-2 pt-3 px-4">
                      <CardTitle className="text-sm">Courbe Equity</CardTitle>
                    </CardHeader>
                    <CardContent className="px-2 pb-2">
                      <PlotlyChart figure={activeWindow.equity_plot as PlotlyFigure} />
                    </CardContent>
                  </Card>
                )}
                {activeWindow.drawdown_plot && (
                  <Card>
                    <CardHeader className="pb-2 pt-3 px-4">
                      <CardTitle className="text-sm">Drawdown</CardTitle>
                    </CardHeader>
                    <CardContent className="px-2 pb-2">
                      <PlotlyChart figure={activeWindow.drawdown_plot as PlotlyFigure} />
                    </CardContent>
                  </Card>
                )}
              </>
            ) : (
              plotKeys.map((key) => (
                <Card key={key}>
                  <CardHeader className="pb-2 pt-3 px-4">
                    <CardTitle className="text-sm capitalize">
                      {key.replace(/_/g, " ")}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="px-2 pb-2">
                    <PlotlyChart figure={data.plots[key] as PlotlyFigure} />
                  </CardContent>
                </Card>
              ))
            )}
          </TabsContent>
        )}

        <TabsContent value="metriques">
          {activeWindow ? (
            <Card>
              <CardContent className="p-4">
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-xs">
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Sharpe</p>
                    <p className="font-mono text-sm font-semibold mt-0.5">{activeWindow.sharpe.toFixed(3)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">PnL (100k)</p>
                    <p className="font-mono text-sm font-semibold mt-0.5">{formatNumber(activeWindow.pnl)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Trades</p>
                    <p className="font-mono text-sm font-semibold mt-0.5">{activeWindow.n_trades}</p>
                  </div>
                  {activeWindowMeanHoldPeriod != null && (
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Mean Hold Period</p>
                      <p className="font-mono text-sm font-semibold mt-0.5">
                        {formatHoldPeriodDays(activeWindowMeanHoldPeriod)}
                      </p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-px bg-border">
                  {metricsEntries.map(([k, v]) => (
                    <div key={k} className="bg-background p-3">
                      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">
                        {formatBacktestMetricLabel(k)}
                      </p>
                      <p className="font-mono text-sm font-semibold mt-0.5">
                        {k === "mean_hold_period_between_trades_days" && typeof v === "number"
                          ? formatHoldPeriodDays(v)
                          : typeof v === "number"
                            ? formatNumber(v)
                            : String(v ?? "\u2014")}
                      </p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Performance trades */}
        <TabsContent value="performance">
          {activeWindow ? (
            <TradesTable trades={activeWindow.trades} />
          ) : (
            filteredTradePerformance.length > 0 && (
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-secondary/30">
                        <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Metrique
                        </th>
                        <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Valeur
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTradePerformance.map((row, i) => (
                        <tr key={i} className="border-b border-border/50 hover:bg-secondary/20">
                          <td className="px-4 py-2 font-medium capitalize">
                            {formatTradeMetricLabel(String(row.metric ?? ""))}
                          </td>
                          <td className="px-4 py-2 text-right tabular-nums font-mono text-xs">
                            {typeof row.value === "number"
                              ? formatNumber(row.value as number)
                              : String(row.value ?? "\u2014")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )
          )}
        </TabsContent>

        {/* Ledger */}
        <TabsContent value="ledger">
          {activeWindow ? (
            <TradesTable trades={activeWindow.trades} />
          ) : (
            data.trade_ledger.length > 0 && <TradeLedgerTable trades={data.trade_ledger} />
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

function TradesTable({ trades }: { trades: Record<string, unknown>[] }) {
  if (trades.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-xs text-muted-foreground">
          Aucun trade pour cette fenetre.
        </CardContent>
      </Card>
    )
  }
  return <TradeLedgerTable trades={trades} />
}

function TradeLedgerTable({ trades }: { trades: Record<string, unknown>[] }) {
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <div className="border-b bg-secondary/20 px-3 py-2 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground">Audit:</span>{" "}
          <span>`PnL (100k) = 100000 × Return cumule`.</span>{" "}
          <span>`PnL realise cumule (1 unite)` suit separement le ledger des trades unitaires.</span>
        </div>
        <table className="w-full text-xs whitespace-nowrap">
          <thead>
            <tr className="border-b bg-secondary/30">
              {[
                "Date",
                "Sens",
                "Open (t+1)",
                "CMP",
                "Position",
                "Return Cumule (%)",
                "PnL Realise Cumule (1 unite)",
              ].map((h) => (
                <th
                  key={h}
                  className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((row, i) => {
              const hasReturnCumule = row.return_cumule != null
              const returnCumule = hasReturnCumule ? Number(row.return_cumule) : NaN
              const hasPnlCumule = row.pnl_realise_cumule != null
              const pnlRealiseCumule = hasPnlCumule ? Number(row.pnl_realise_cumule) : NaN
              const side = String(row.side ?? "")
              return (
                <tr
                  key={i}
                  className="border-b border-border/40 hover:bg-secondary/20"
                >
                  <td className="px-3 py-1.5 font-mono">
                    {String(row.date ?? "").slice(0, 10)}
                  </td>
                  <td className="px-3 py-1.5">
                    <span
                      className={cn(
                        "font-semibold",
                        side === "ACHAT"
                          ? "text-emerald-600"
                          : "text-red-600",
                      )}
                    >
                      {side || "\u2014"}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {row.open_t_plus_1 != null || row.prix_execution != null
                      ? formatTradePrice(Number(row.open_t_plus_1 ?? row.prix_execution))
                      : "\u2014"}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {row.cmp != null || row.close_du_jour != null
                      ? formatTradePrice(Number(row.cmp ?? row.close_du_jour))
                      : "\u2014"}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 tabular-nums font-semibold text-center",
                      Number(row.position ?? 0) > 0
                        ? "text-emerald-600"
                        : Number(row.position ?? 0) < 0
                          ? "text-red-600"
                          : "text-muted-foreground",
                    )}
                  >
                    {row.position != null
                      ? Number(row.position) > 0
                        ? "+1"
                        : Number(row.position) < 0
                          ? "-1"
                          : "0"
                      : "\u2014"}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 tabular-nums font-semibold",
                      returnCumule > 0
                        ? "text-emerald-600"
                        : returnCumule < 0
                          ? "text-red-600"
                          : "text-muted-foreground",
                    )}
                  >
                    {Number.isFinite(returnCumule) ? formatPercent(returnCumule) : "\u2014"}
                  </td>
                  <td
                    className={cn(
                      "px-3 py-1.5 tabular-nums font-semibold",
                      pnlRealiseCumule > 0
                        ? "text-emerald-600"
                        : pnlRealiseCumule < 0
                          ? "text-red-600"
                          : "text-muted-foreground",
                    )}
                  >
                    {Number.isFinite(pnlRealiseCumule) ? formatNumber(pnlRealiseCumule) : "\u2014"}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

/* -- Tab 2: Fenetres OOS ------------------------------------------------- */

function OOSTab({ data }: { data: VariantDetail }) {
  if (data.oos_windows.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-xs text-muted-foreground">
          {data.methodology_context.methodology_mode === "live_signal_only"
            ? "Aucune fenetre OOS disponible: cette variante est affichee en signal live uniquement."
            : "Aucune fenetre OOS disponible."}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="text-xs font-semibold">
          Fenetres OOS ({data.oos_windows.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left px-4 py-1.5 font-medium">#</th>
                <th className="text-left px-2 py-1.5 font-medium">Periode</th>
                <th className="text-right px-2 py-1.5 font-medium">Bars</th>
                <th className="text-right px-2 py-1.5 font-medium">Trades</th>
                <th className="text-right px-2 py-1.5 font-medium">Return moy.</th>
                <th className="text-right px-2 py-1.5 font-medium">Sharpe</th>
                <th className="text-right px-2 py-1.5 font-medium">Max DD</th>
                <th className="text-right px-2 py-1.5 font-medium">Win%</th>
                <th className="text-center px-2 py-1.5 font-medium">Valide</th>
              </tr>
            </thead>
            <tbody>
              {data.oos_windows.map((w) => (
                <tr key={w.window_index} className="border-b last:border-0">
                  <td className="px-4 py-1.5 text-muted-foreground">{w.window_index + 1}</td>
                  <td className="px-2 py-1.5 font-mono text-[10px]">
                    {w.test_start_date && w.test_end_date
                      ? `${w.test_start_date} \u2192 ${w.test_end_date}`
                      : "\u2014"}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">{w.n_bars}</td>
                  <td className="px-2 py-1.5 text-right font-mono">{w.n_trades}</td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {(w.mean_return_net * 100).toFixed(3)}%
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right font-mono ${
                      w.sharpe > 0 ? "text-green-700" : "text-red-700"
                    }`}
                  >
                    {w.sharpe.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {(w.max_drawdown * 100).toFixed(1)}%
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono">
                    {(w.fraction_positive_bars * 100).toFixed(1)}%
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {w.is_valid ? (
                      <span className="text-green-600">OK</span>
                    ) : (
                      <span className="text-red-600">--</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

/* -- Tab 3: Fiabilite ---------------------------------------------------- */

function ReliabilityTab({ data }: { data: VariantDetail }) {
  const r = data.robustness
  const components = [
    {
      label: "Sharpe",
      weight: 35,
      score: r.sharpe_score,
      brief: `base sur le Sharpe moyen (${r.mean_sharpe.toFixed(3)})`,
    },
    {
      label: "Stabilite",
      weight: 30,
      score: r.stability_score,
      brief: `basee sur ${(r.fraction_positive_windows * 100).toFixed(1)}% de fenetres positives`,
    },
    {
      label: "Consistance",
      weight: 20,
      score: r.consistency_score,
      brief: `basee sur la regularite du Sharpe (ecart-type ${r.std_sharpe.toFixed(3)})`,
    },
    {
      label: "Drawdown",
      weight: 15,
      score: r.drawdown_score,
      brief: `base sur un max DD moyen de ${(r.mean_max_drawdown * 100).toFixed(1)}%`,
    },
  ]

  return (
    <div className="space-y-4">
      {/* Final score */}
      <Card>
        <CardContent className="py-6 flex flex-col items-center gap-2">
          <div className="text-3xl font-bold">
            {(r.reliability_score * 100).toFixed(1)}%
          </div>
          <div className="text-xs text-muted-foreground">Score de fiabilite</div>
          <Badge
            variant="outline"
            className={`text-[10px] ${r.is_viable ? "text-green-700 border-green-300" : "text-red-700 border-red-300"}`}
          >
            {r.is_viable ? "Viable" : "Non-viable"}
          </Badge>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Decomposition</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 px-4 pb-4">
          {components.map((c) => (
            <div key={c.label} className="rounded-lg border border-border/60 bg-background p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{c.label}</span>
                    <span className="text-[10px] text-muted-foreground">({c.weight}%)</span>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{c.brief}</p>
                </div>
                <span className="font-mono text-sm font-semibold">
                  {(c.score * 100).toFixed(1)}%
                </span>
              </div>
              <div className="mt-3 h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all"
                  style={{ width: `${Math.max(0, Math.min(100, c.score * 100))}%` }}
                />
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Raw metrics */}
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Metriques OOS</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Sharpe moyen</span>
              <span className="font-mono">{r.mean_sharpe.toFixed(3)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Sharpe median</span>
              <span className="font-mono">{r.median_sharpe.toFixed(3)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Ecart-type Sharpe</span>
              <span className="font-mono">{r.std_sharpe.toFixed(3)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Fenetres positives</span>
              <span className="font-mono">{(r.fraction_positive_windows * 100).toFixed(1)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Max DD moyen</span>
              <span className="font-mono">{(r.mean_max_drawdown * 100).toFixed(1)}%</span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
