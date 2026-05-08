"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { ArrowRight, ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react"
import type { EdgeMetrics } from "@/lib/api"
import type { DashboardScoreSource, DashboardStock, Horizon } from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_SHORT_LABELS } from "@/lib/dashboard-constants"
import { formatPercent } from "@/lib/format"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { EdgeTile, type EdgeMode } from "@/components/dashboard/edge-tile"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

type SortDir = "asc" | "desc"
type SortKey =
  | "symbol"
  | "price"
  | "adv"
  | "signal"
  | "expected_return"
  | "hit_rate"
  | "edge_ratio"
  | (typeof FAMILY_ORDER)[number]

interface StockTableProps {
  stocks: DashboardStock[]
  horizon: Horizon
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  scoreSource?: DashboardScoreSource
  hideDetails?: boolean
  showTechnicalLevels?: boolean
  edgeEnabled?: boolean
  edgeMode?: EdgeMode
  edgeSource?: "signal_engine" | "wfo"
  edgeMap?: Record<string, EdgeMetrics | null | undefined>
  onOpenEdge?: (stock: DashboardStock) => void
}

function toLegacyHorizon(horizon: Horizon): "short" | "medium" | "long" {
  if (horizon === "weekly") return "short"
  if (horizon === "monthly") return "medium"
  if (horizon === "quarterly") return "long"
  if (horizon === "medium") return "medium"
  if (horizon === "long") return "long"
  return "short"
}

function horizonLabel(horizon: Horizon) {
  if (horizon === "weekly") return "hebdo"
  if (horizon === "monthly") return "mensuel"
  if (horizon === "quarterly") return "trimestriel"
  if (horizon === "long") return "long"
  if (horizon === "medium") return "moyen"
  return "court"
}

function resolveSeAggregate(stock: DashboardStock, signalView: "legacy" | "expanded" | "factor_x_ta"): number | null {
  const se = stock.scores.signal_engine
  return signalView === "expanded"
    ? (se.expanded_aggregate_score_pct ?? se.aggregate_score_pct)
    : se.aggregate_score_pct
}

function resolveSeAggregateLabel(stock: DashboardStock, signalView: "legacy" | "expanded" | "factor_x_ta"): string | null {
  const se = stock.scores.signal_engine
  return signalView === "expanded"
    ? (se.expanded_aggregate_signal_label ?? se.aggregate_signal_label)
    : se.aggregate_signal_label
}

function resolveSeFamily(
  stock: DashboardStock,
  family: string,
  signalView: "legacy" | "expanded" | "factor_x_ta",
) {
  const se = stock.scores.signal_engine
  const familyMap = signalView === "expanded" ? (se.expanded_per_family ?? se.per_family) : se.per_family
  return familyMap[family] ?? null
}

function priceForDisplay(stock: DashboardStock): number | null {
  return stock.scores.signal_engine.technical_levels?.close_used ?? null
}

function sourceScore(
  stock: DashboardStock,
  scoreSource: DashboardScoreSource,
  signalView: "legacy" | "expanded" | "factor_x_ta",
): number | null {
  if (scoreSource === "wfo") return stock.scores.wfo?.aggregate_score_pct ?? null
  if (scoreSource === "both") return stock.scores.wfo?.aggregate_score_pct ?? resolveSeAggregate(stock, signalView)
  return resolveSeAggregate(stock, signalView)
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

function formatSigned(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}`
}

function HitRateCell({ edge }: { edge: EdgeMetrics | null | undefined }) {
  if (!edge || edge.hit_rate == null) return <span className="text-[11px] text-muted-foreground">--</span>
  return (
    <div className="space-y-0.5 text-right">
      <div className="dashboard-mono text-xs">{formatPercent(edge.hit_rate)}</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        [{edge.hit_ci_lower?.toFixed(2) ?? "--"}, {edge.hit_ci_upper?.toFixed(2) ?? "--"}]
      </div>
    </div>
  )
}

function SignalSummary({
  stock,
  scoreSource,
  signalView,
  showTechnicalLevels,
}: {
  stock: DashboardStock
  scoreSource: DashboardScoreSource
  signalView: "legacy" | "expanded" | "factor_x_ta"
  showTechnicalLevels: boolean
}) {
  const seLabel = resolveSeAggregateLabel(stock, signalView)
  const seScore = resolveSeAggregate(stock, signalView)
  const wfoLabel = stock.scores.wfo?.aggregate_signal_label ?? null
  const wfoScore = stock.scores.wfo?.aggregate_score_pct ?? null

  if (scoreSource === "both") {
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">SE</span>
          <SignalBadge label={seLabel} />
          <span className="dashboard-mono text-[11px]">{formatSigned(seScore, 1)}</span>
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-border/70 pt-1">
          <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">WFO</span>
          <SignalBadge label={wfoLabel} />
          <span className="dashboard-mono text-[11px]">{formatSigned(wfoScore, 1)}</span>
        </div>
        {showTechnicalLevels ? (
          <div className="dashboard-mono border-t border-border/70 pt-1 text-[10px] text-muted-foreground">
            S {formatNumber(stock.scores.signal_engine.technical_levels?.support_reference ?? stock.scores.signal_engine.technical_levels?.support_buy_trigger)} - R {formatNumber(stock.scores.signal_engine.technical_levels?.resistance_sell_trigger)}
          </div>
        ) : null}
      </div>
    )
  }

  if (scoreSource === "wfo") {
    return (
      <div className="space-y-1">
        <SignalBadge label={wfoLabel} />
        <div className="dashboard-mono text-[11px] text-muted-foreground">{formatSigned(wfoScore, 1)}</div>
        {showTechnicalLevels ? (
          <div className="dashboard-mono text-[10px] text-muted-foreground">
            S {formatNumber(stock.scores.wfo?.technical_levels?.support_reference ?? stock.scores.wfo?.technical_levels?.support_buy_trigger)} - R {formatNumber(stock.scores.wfo?.technical_levels?.resistance_sell_trigger)}
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="space-y-1">
      <SignalBadge label={seLabel} />
      <div className="dashboard-mono text-[11px] text-muted-foreground">{formatSigned(seScore, 1)}</div>
      {showTechnicalLevels ? (
        <div className="dashboard-mono text-[10px] text-muted-foreground">
          S {formatNumber(stock.scores.signal_engine.technical_levels?.support_reference ?? stock.scores.signal_engine.technical_levels?.support_buy_trigger)} - R {formatNumber(stock.scores.signal_engine.technical_levels?.resistance_sell_trigger)}
        </div>
      ) : null}
    </div>
  )
}

export function StockTable({
  stocks,
  horizon,
  signalView = "expanded",
  scoreSource = "wfo",
  hideDetails = true,
  showTechnicalLevels = false,
  edgeEnabled = true,
  edgeMode = "net",
  edgeSource = "wfo",
  edgeMap = {},
  onOpenEdge,
}: StockTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>(edgeEnabled ? "edge_ratio" : "signal")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

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
      } else if (sortKey === "adv") {
        leftValue = left.adv ?? null
        rightValue = right.adv ?? null
      } else if (sortKey === "signal") {
        leftValue = sourceScore(left, scoreSource, signalView)
        rightValue = sourceScore(right, scoreSource, signalView)
      } else if (sortKey === "expected_return") {
        leftValue = edgeMode === "net" ? edgeMap[left.symbol]?.expected_return_net ?? null : edgeMap[left.symbol]?.expected_return_gross ?? null
        rightValue = edgeMode === "net" ? edgeMap[right.symbol]?.expected_return_net ?? null : edgeMap[right.symbol]?.expected_return_gross ?? null
      } else if (sortKey === "hit_rate") {
        leftValue = edgeMap[left.symbol]?.hit_rate ?? null
        rightValue = edgeMap[right.symbol]?.hit_rate ?? null
      } else if (sortKey === "edge_ratio") {
        const leftEdge = edgeMap[left.symbol]
        const rightEdge = edgeMap[right.symbol]
        const leftProven = edgeMode === "net" ? leftEdge?.proven_edge_net : leftEdge?.proven_edge_gross
        const rightProven = edgeMode === "net" ? rightEdge?.proven_edge_net : rightEdge?.proven_edge_gross
        if (leftProven !== rightProven) {
          return leftProven ? -1 : 1
        }
        leftValue = edgeMode === "net" ? leftEdge?.edge_ratio_net ?? null : leftEdge?.edge_ratio_gross ?? null
        rightValue = edgeMode === "net" ? rightEdge?.edge_ratio_net ?? null : rightEdge?.edge_ratio_gross ?? null
      } else {
        leftValue = scoreSource === "wfo"
          ? left.scores.wfo?.per_family[sortKey]?.score_pct ?? null
          : resolveSeFamily(left, sortKey, signalView)?.score_pct ?? null
        rightValue = scoreSource === "wfo"
          ? right.scores.wfo?.per_family[sortKey]?.score_pct ?? null
          : resolveSeFamily(right, sortKey, signalView)?.score_pct ?? null
      }

      const primary = compareValues(leftValue, rightValue, sortDir)
      if (primary !== 0) return primary
      return left.symbol.localeCompare(right.symbol)
    })
  }, [stocks, sortKey, sortDir, scoreSource, signalView, edgeMap, edgeMode, edgeEnabled])

  function onSort(nextKey: SortKey) {
    if (nextKey === sortKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(nextKey)
    setSortDir("desc")
  }

  function SortIcon({ columnKey }: { columnKey: SortKey }) {
    if (columnKey !== sortKey) return <ChevronsUpDown className="h-3.5 w-3.5" />
    return sortDir === "asc" ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />
  }

  if (sorted.length === 0) {
    return <div className="dashboard-panel px-4 py-12 text-center text-sm text-muted-foreground">Aucune action ne correspond aux filtres.</div>
  }

  const linkHorizon = toLegacyHorizon(horizon)

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-muted/30 px-4 py-3">
        <div>
          <h3 className="text-[13px] font-semibold">Signaux par titre - Horizon {horizonLabel(horizon)}</h3>
          <p className="text-[11px] text-muted-foreground">Actions visibles</p>
        </div>
        <div className="dashboard-meta">
          {sorted.length} lignes - triees par {sortKey}
          {edgeEnabled ? <span className="ml-1 rounded-sm bg-primary/10 px-1.5 py-0.5 text-primary">Edge</span> : null}
        </div>
      </div>

      <Table className="min-w-[1100px] text-[13px]">
        <TableHeader>
          <TableRow className="border-b border-border bg-muted/50 hover:bg-muted/50">
            <TableHead className="h-auto px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("symbol")}>
                Ticker
                <SortIcon columnKey="symbol" />
              </button>
            </TableHead>
            <TableHead className="h-auto px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Nom</TableHead>
            <TableHead className="h-auto px-2.5 py-2 text-right text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("price")}>
                Prix
                <SortIcon columnKey="price" />
              </button>
            </TableHead>
            <TableHead className="h-auto px-2.5 py-2 text-right text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("adv")}>
                ADV20
                <SortIcon columnKey="adv" />
              </button>
            </TableHead>
            {!hideDetails && FAMILY_ORDER.map((family) => (
              <TableHead key={family} className="h-auto px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort(family)}>
                  {FAMILY_SHORT_LABELS[family]}
                  <SortIcon columnKey={family} />
                </button>
              </TableHead>
            ))}
            <TableHead className="h-auto px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("signal")}>
                Signal
                <SortIcon columnKey="signal" />
              </button>
            </TableHead>
            <TableHead className="h-auto px-2.5 py-2 text-right text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("expected_return")}>
                E[R]
                <SortIcon columnKey="expected_return" />
              </button>
            </TableHead>
            <TableHead className="h-auto px-2.5 py-2 text-right text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("hit_rate")}>
                Hit% [IC 95%]
                <SortIcon columnKey="hit_rate" />
              </button>
            </TableHead>
            {edgeEnabled ? (
              <TableHead className="h-auto min-w-[238px] px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("edge_ratio")}>
                  Edge
                  <SortIcon columnKey="edge_ratio" />
                </button>
              </TableHead>
            ) : null}
            <TableHead className="h-auto w-10 px-2.5 py-2 text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((stock) => {
            const edge = edgeMap[stock.symbol]
            const expectedReturn = edgeMode === "net" ? edge?.expected_return_net : edge?.expected_return_gross
            const signalViewQuery = scoreSource === "wfo" ? "expanded" : signalView

            return (
              <TableRow key={stock.symbol} className="border-b border-border/80 align-top hover:bg-background">
                <TableCell className="px-2.5 py-2.5 align-middle">
                  <span className="dashboard-mono text-[13px] font-semibold">{stock.symbol}</span>
                </TableCell>
                <TableCell className="max-w-[260px] px-2.5 py-2.5">
                  <Link
                    href={`/signals?symbol=${encodeURIComponent(stock.symbol)}&horizon=${linkHorizon}&view=${signalViewQuery}`}
                    className="block hover:underline"
                  >
                    <div className="text-[12px] font-medium">{stock.display_name ?? "-"}</div>
                    <div className="text-[11px] text-muted-foreground">{stock.sector ?? "-"}</div>
                  </Link>
                </TableCell>
                <TableCell className="dashboard-mono px-2.5 py-2.5 text-right text-[12px]">{formatNumber(priceForDisplay(stock))}</TableCell>
                <TableCell className="dashboard-mono px-2.5 py-2.5 text-right text-[12px] text-muted-foreground">{formatNumber(stock.adv ?? null, 0)}</TableCell>
                {!hideDetails && FAMILY_ORDER.map((family) => (
                  <TableCell key={`${stock.symbol}-${family}`} className="px-2.5 py-2.5">
                    {scoreSource === "both" ? (
                      <div className="space-y-1">
                        <div>
                          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">SE</div>
                          <FamilyCell score={resolveSeFamily(stock, family, signalView)} />
                        </div>
                        <div className="border-t border-border/70 pt-1">
                          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">WFO</div>
                          <FamilyCell score={stock.scores.wfo?.per_family[family] ?? null} />
                        </div>
                      </div>
                    ) : scoreSource === "wfo" ? (
                      <FamilyCell score={stock.scores.wfo?.per_family[family] ?? null} />
                    ) : (
                      <FamilyCell score={resolveSeFamily(stock, family, signalView)} />
                    )}
                  </TableCell>
                ))}
                <TableCell className="px-2.5 py-2.5"><SignalSummary stock={stock} scoreSource={scoreSource} signalView={signalView} showTechnicalLevels={showTechnicalLevels} /></TableCell>
                <TableCell className="dashboard-mono px-2.5 py-2.5 text-right text-[12px]">{formatPercent(expectedReturn)}</TableCell>
                <TableCell className="px-2.5 py-2.5"><HitRateCell edge={edge} /></TableCell>
                {edgeEnabled ? (
                  <TableCell className="px-2.5 py-2.5">
                    <EdgeTile
                      edge={edge}
                      mode={edgeMode}
                      sourceLabel={edgeSource === "wfo" ? "WFO" : "SE"}
                      onOpen={() => onOpenEdge?.(stock)}
                    />
                  </TableCell>
                ) : null}
                <TableCell className="px-2 py-2.5 align-middle">
                  <Link
                    href={`/signals?symbol=${encodeURIComponent(stock.symbol)}&horizon=${linkHorizon}&view=${signalViewQuery}`}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-muted-foreground transition hover:border-border hover:bg-muted/30 hover:text-foreground"
                    aria-label={`Ouvrir ${stock.symbol}`}
                  >
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
