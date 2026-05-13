"use client"

import { Star } from "lucide-react"
import type { DashboardBestSignal, DashboardBestTechnicalSignal, DashboardPortfolioEdge, DashboardStock } from "@/lib/dashboard-types"
import { formatPercent } from "@/lib/format"
import { SignalBadge } from "./signal-badge"

export type EdgeTriage = "proven" | "watch" | "insufficient" | "hold" | "missing"

function isActionableBestSignal(signal: DashboardBestSignal | null | undefined): signal is DashboardBestSignal {
  if (!signal) return false
  if (signal.direction === "none" || signal.bucket === "hold") return false
  if (signal.bucket === "buy" || signal.bucket === "strong_buy") return signal.direction === "long"
  if (signal.bucket === "sell" || signal.bucket === "strong_sell") return signal.direction === "short"
  return false
}

export function bestSignalForDisplay(stock: DashboardStock | null | undefined): DashboardBestSignal | null {
  const signal = stock?.best_signal ?? null
  if (signal?.source !== "wfo") return null
  if (!isActionableBestSignal(signal)) return null
  if (signal.action_expected_return_net == null || signal.hit_rate == null) return null
  return signal
}

export function technicalSignalForDisplay(stock: DashboardStock | null | undefined): DashboardBestTechnicalSignal | null {
  const signal = stock?.best_technical_signal ?? null
  if (!signal) return null
  if (signal.score_pct == null || !Number.isFinite(signal.score_pct)) return null
  return signal
}

export function bestSignalActionLabel(signal: DashboardBestSignal | null | undefined) {
  if (!signal) return "--"
  if (signal.direction === "long") return "Long"
  if (signal.direction === "short") return "Short"
  return "No trade"
}

export function bestSignalHoldingPeriodLabel(signal: DashboardBestSignal | null | undefined, fallbackDays?: number) {
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

export function bestSignalTriage(signal: DashboardBestSignal | null | undefined): EdgeTriage {
  if (!signal) return "missing"
  if (signal.direction === "none" || signal.bucket === "hold") return "hold"
  if ((signal.n ?? 0) < 30) return "insufficient"
  return signal.proven_edge_net ? "proven" : "watch"
}

function edgeTriageRank(signal: DashboardBestSignal | null | undefined) {
  const order: Record<EdgeTriage, number> = { proven: 4, watch: 3, insufficient: 2, hold: 1, missing: 0 }
  return order[bestSignalTriage(signal)]
}

export function bestSignalEdgeScore(signal: DashboardBestSignal | null | undefined) {
  return signal?.edge_score ?? null
}

function bestSignalSortScore(signal: DashboardBestSignal | null | undefined) {
  return signal?.edge_score ?? signal?.score ?? null
}

function formatEdgeScore(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  return value.toFixed(0)
}

function portfolioTriageRank(edge: DashboardPortfolioEdge | null | undefined) {
  const order: Record<EdgeTriage, number> = { proven: 4, watch: 3, insufficient: 2, hold: 1, missing: 0 }
  return order[portfolioEdgeTriage(edge)]
}

export function compareBestSignalStocks(left: DashboardStock, right: DashboardStock) {
  const leftSignal = bestSignalForDisplay(left)
  const rightSignal = bestSignalForDisplay(right)

  const triage = edgeTriageRank(rightSignal) - edgeTriageRank(leftSignal)
  if (triage !== 0) return triage

  const rightScore = bestSignalSortScore(rightSignal) ?? Number.NEGATIVE_INFINITY
  const leftScore = bestSignalSortScore(leftSignal) ?? Number.NEGATIVE_INFINITY
  if (rightScore !== leftScore) return rightScore - leftScore

  const rightEr = rightSignal?.action_expected_return_net ?? Number.NEGATIVE_INFINITY
  const leftEr = leftSignal?.action_expected_return_net ?? Number.NEGATIVE_INFINITY
  if (rightEr !== leftEr) return rightEr - leftEr

  return left.symbol.localeCompare(right.symbol)
}

export function compareTechnicalSignalStocks(left: DashboardStock, right: DashboardStock) {
  const leftSignal = technicalSignalForDisplay(left)
  const rightSignal = technicalSignalForDisplay(right)

  const rightScore = rightSignal?.abs_score_pct ?? Math.abs(rightSignal?.score_pct ?? Number.NEGATIVE_INFINITY)
  const leftScore = leftSignal?.abs_score_pct ?? Math.abs(leftSignal?.score_pct ?? Number.NEGATIVE_INFINITY)
  if (rightScore !== leftScore) return rightScore - leftScore

  const sourceRank = (rightSignal?.source === "wfo" ? 1 : 0) - (leftSignal?.source === "wfo" ? 1 : 0)
  if (sourceRank !== 0) return sourceRank

  return left.symbol.localeCompare(right.symbol)
}

function median(values: number[]) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[mid]
  return (sorted[mid - 1] + sorted[mid]) / 2
}

export function summarizeBestSignals(stocks: DashboardStock[]) {
  const ranked = [...stocks]
    .filter((stock) => bestSignalForDisplay(stock) !== null)
    .sort(compareBestSignalStocks)
  const topStock = ranked[0] ?? null
  const signals = ranked
    .map((stock) => bestSignalForDisplay(stock))
    .filter((signal): signal is DashboardBestSignal => signal !== null)

  return {
    topStock,
    topSignal: topStock ? bestSignalForDisplay(topStock) : null,
    actionableCount: signals.length,
    provenCount: signals.filter((signal) => signal.proven_edge_net).length,
    medianExpectedReturn: median(
      signals
        .map((signal) => signal.action_expected_return_net)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    ),
    medianHitRate: median(
      signals
        .map((signal) => signal.hit_rate)
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    ),
  }
}

export function summarizeTechnicalSignals(stocks: DashboardStock[]) {
  const ranked = [...stocks]
    .filter((stock) => technicalSignalForDisplay(stock) !== null)
    .sort(compareTechnicalSignalStocks)
  const topStock = ranked[0] ?? null
  const signals = ranked
    .map((stock) => technicalSignalForDisplay(stock))
    .filter((signal): signal is DashboardBestTechnicalSignal => signal !== null)

  return {
    topStock,
    topSignal: topStock ? technicalSignalForDisplay(topStock) : null,
    directionalCount: signals.filter((signal) => signal.direction === "long" || signal.direction === "short").length,
    bullishCount: signals.filter((signal) => signal.direction === "long").length,
    bearishCount: signals.filter((signal) => signal.direction === "short").length,
    medianAbsScore: median(
      signals
        .map((signal) => signal.abs_score_pct ?? Math.abs(signal.score_pct ?? NaN))
        .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
    ),
  }
}

export function portfolioEdgeTriage(edge: DashboardPortfolioEdge | null | undefined): EdgeTriage {
  if (!edge || (edge.active_count ?? 0) <= 0 || (edge.n ?? 0) <= 0) return "missing"
  if ((edge.n ?? 0) < 30) return "insufficient"
  return edge.proven_edge_net || edge.triage === "proven" ? "proven" : "watch"
}

export function comparePortfolioEdges(
  left: DashboardPortfolioEdge | null | undefined,
  right: DashboardPortfolioEdge | null | undefined,
) {
  const triage = portfolioTriageRank(right) - portfolioTriageRank(left)
  if (triage !== 0) return triage

  const rightScore = right?.score ?? right?.action_expected_return_net ?? Number.NEGATIVE_INFINITY
  const leftScore = left?.score ?? left?.action_expected_return_net ?? Number.NEGATIVE_INFINITY
  if (rightScore !== leftScore) return rightScore - leftScore

  const active = (right?.active_count ?? 0) - (left?.active_count ?? 0)
  if (active !== 0) return active

  return (right?.n ?? 0) - (left?.n ?? 0)
}

export function portfolioHoldingPeriodLabel(edge: DashboardPortfolioEdge | null | undefined, fallbackDays?: number) {
  if (edge?.exit_timing_label) return edge.exit_timing_label
  const days = edge?.exit_lag_bars ?? edge?.fwd_horizon_bars ?? fallbackDays
  if (edge?.return_calc_method === "open_to_exit_ladder" && days) {
    const exit = edge.exit_price_kind === "close" ? "Close" : "Open"
    return `J+${days} ${exit}`
  }
  const method = edge?.return_calc_method === "open_to_open" ? "O/O" : edge?.return_calc_method ?? null
  if (!days) return method ?? "--"
  return method ? `${days}j ${method}` : `${days}j`
}

function bucketSignalLabel(bucket: string | null | undefined) {
  if (bucket === "strong_buy") return "Achat fort"
  if (bucket === "buy") return "Achat"
  if (bucket === "sell") return "Vente"
  if (bucket === "strong_sell") return "Vente forte"
  if (bucket === "hold") return "Neutre"
  return "Indisponible"
}

export function bestSignalLabel(signal: DashboardBestSignal | null | undefined) {
  return signal?.signal_label ?? bucketSignalLabel(signal?.bucket)
}

export function shortMethodLabel(signal: DashboardBestSignal | null | undefined) {
  if (!signal) return "No eligible WFO edge"
  return signal.label
    .replace("Signal Engine - ", "Engine ")
    .replace("Factor x TA", "FX")
    .replace("Simple", "")
    .trim()
}

export function displayVariantLabel(variant: string | null | undefined) {
  const value = String(variant ?? "").trim()
  if (!value) return "--"
  return value.startsWith("sv_") ? "Selected indicator" : value
}

export function EdgeBadge({ triage }: { triage: EdgeTriage }) {
  if (triage === "insufficient") {
    return <span className="text-[11px] font-semibold text-muted-foreground">&lt;30 OOS</span>
  }
  if (triage === "hold") {
    return <span className="text-[11px] font-semibold text-muted-foreground">Hold</span>
  }
  if (triage === "missing") {
    return <span className="text-[11px] text-muted-foreground">No action.</span>
  }
  if (triage === "proven") {
    return (
      <span className="dashboard-chip-positive inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold">
        <Star className="h-2.5 w-2.5" />
        Prouve
      </span>
    )
  }
  return (
    <span className="dashboard-action-warning inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold">
      A surveiller
    </span>
  )
}

export function BestSignalBadgeCell({ signal }: { signal: DashboardBestSignal | null }) {
  if (!signal) return <SignalBadge label="Indisponible" />
  return <SignalBadge label={bestSignalLabel(signal)} />
}

export function BestSignalMethodCell({
  signal,
  stockSymbol,
}: {
  signal: DashboardBestSignal | null
  stockSymbol?: string | null
}) {
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
        <span className="dashboard-mono text-[10px] text-muted-foreground">
          {stockSymbol ? `${stockSymbol} - ` : ""}score {formatEdgeScore(bestSignalEdgeScore(signal))} - n={signal.n ?? "--"}
        </span>
      </div>
    </div>
  )
}

export function BestSignalExpectedReturnCell({
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

export function BestSignalHitRateCell({ signal }: { signal: DashboardBestSignal | null }) {
  if (!signal) {
    return <span className="dashboard-mono text-[10px] text-muted-foreground">No actionable</span>
  }
  return (
    <div className="space-y-0.5 text-right">
      <div className="dashboard-mono text-[11px]">{formatPercent(signal.hit_rate ?? null)}</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        [{signal.hit_ci_lower?.toFixed(2) ?? "--"}, {signal.hit_ci_upper?.toFixed(2) ?? "--"}]
      </div>
    </div>
  )
}

export function PortfolioEdgeBadgeCell({ edge }: { edge: DashboardPortfolioEdge | null | undefined }) {
  if (!edge || (edge.active_count ?? 0) <= 0) return <SignalBadge label="Indisponible" />
  const longCount = edge.long_count ?? 0
  const shortCount = edge.short_count ?? 0
  if (longCount > 0 && shortCount > 0) {
    return (
      <span className="inline-flex items-center rounded-[6px] bg-muted px-2 py-0.5 text-[11px] font-semibold leading-5 text-foreground">
        Long/Short
      </span>
    )
  }
  if (longCount > 0) return <SignalBadge label="Achat" />
  if (shortCount > 0) return <SignalBadge label="Vente" />
  return <SignalBadge label="Neutre" />
}

export function PortfolioEdgeMethodCell({ edge }: { edge: DashboardPortfolioEdge | null | undefined }) {
  if (!edge) {
    return <span className="text-[11px] text-muted-foreground">No portfolio edge</span>
  }
  return (
    <div className="space-y-1">
      <div className="max-w-[180px] truncate text-[11px] font-semibold" title={edge.label}>
        {edge.label}
      </div>
      <div className="flex items-center gap-1.5">
        <EdgeBadge triage={portfolioEdgeTriage(edge)} />
        <span className="dashboard-mono text-[10px] text-muted-foreground">
          n={edge.n ?? "--"} - {edge.active_count ?? 0}/{edge.total_count ?? 0}
        </span>
      </div>
    </div>
  )
}

export function PortfolioEdgeExpectedReturnCell({
  edge,
  fallbackDays,
}: {
  edge: DashboardPortfolioEdge | null | undefined
  fallbackDays: number
}) {
  if (!edge || edge.action_expected_return_net == null) {
    return (
      <div className="space-y-0.5 text-right text-muted-foreground">
        <div>No eligible</div>
        <div className="dashboard-mono text-[10px]">portfolio edge</div>
      </div>
    )
  }
  return (
    <div className="space-y-0.5 text-right">
      <div>{formatPercent(edge.action_expected_return_net ?? null)}</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        {portfolioHoldingPeriodLabel(edge, fallbackDays)} [{formatPercent(edge.action_expected_return_net_ci_lower ?? null)}, {formatPercent(edge.action_expected_return_net_ci_upper ?? null)}]
      </div>
    </div>
  )
}

export function PortfolioEdgeHitRateCell({ edge }: { edge: DashboardPortfolioEdge | null | undefined }) {
  if (!edge || edge.hit_rate == null) {
    return <span className="dashboard-mono text-[10px] text-muted-foreground">No portfolio obs</span>
  }
  return (
    <div className="space-y-0.5 text-right">
      <div className="dashboard-mono text-[11px]">{formatPercent(edge.hit_rate ?? null)}</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        [{edge.hit_ci_lower?.toFixed(2) ?? "--"}, {edge.hit_ci_upper?.toFixed(2) ?? "--"}]
      </div>
    </div>
  )
}
