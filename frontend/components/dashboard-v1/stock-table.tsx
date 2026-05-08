"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { ArrowRight, ChevronDown, ChevronUp, ChevronsUpDown, Star } from "lucide-react"
import type { EdgeMetrics } from "@/lib/api"
import type { DashboardScoreSource, DashboardStock, Horizon } from "@/lib/dashboard-types"
import { FAMILY_ORDER } from "@/lib/dashboard-constants"
import { formatPercent } from "@/lib/format"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

type SortDir = "asc" | "desc"
type SortKey =
  | "symbol"
  | "price"
  | "adv"
  | "signal"
  | "score"
  | "expected_return"
  | "hit_rate"
  | "edge"
  | (typeof FAMILY_ORDER)[number]

interface StockTableProps {
  stocks: DashboardStock[]
  horizon: Horizon
  horizonDays: number
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  scoreSource?: DashboardScoreSource
  hideDetails?: boolean
  showTechnicalLevels?: boolean
  edgeEnabled?: boolean
  edgeMode?: "gross" | "net"
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
  if (horizon === "weekly") return "court"
  if (horizon === "monthly") return "moyen"
  if (horizon === "quarterly") return "long"
  if (horizon === "medium") return "moyen"
  if (horizon === "long") return "long"
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

function resolveSeFamily(stock: DashboardStock, family: string, signalView: "legacy" | "expanded" | "factor_x_ta") {
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

function signalLabel(
  stock: DashboardStock,
  scoreSource: DashboardScoreSource,
  signalView: "legacy" | "expanded" | "factor_x_ta",
): string | null {
  if (scoreSource === "wfo") return stock.scores.wfo?.aggregate_signal_label ?? null
  if (scoreSource === "both") return stock.scores.wfo?.aggregate_signal_label ?? resolveSeAggregateLabel(stock, signalView)
  return resolveSeAggregateLabel(stock, signalView)
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

function formatSigned(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}`
}

type EdgeTriage = "proven" | "watch" | "none"

function edgeTriage(edge: EdgeMetrics | null | undefined, mode: "gross" | "net"): EdgeTriage {
  if (!edge || !edge.gates.n) return "none"
  const proven = mode === "net" ? edge.proven_edge_net : edge.proven_edge_gross
  return proven ? "proven" : "watch"
}

function EdgeBadge({ triage }: { triage: EdgeTriage }) {
  if (triage === "proven")
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold bg-emerald-500/15 text-emerald-700">
        <Star className="h-2.5 w-2.5" />
        Prouvé
      </span>
    )
  if (triage === "watch")
    return (
      <span className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold bg-amber-500/20 text-amber-700">
        À surveiller
      </span>
    )
  return <span className="text-[11px] text-muted-foreground">—</span>
}

function HitRateCell({ edge }: { edge: EdgeMetrics | null | undefined }) {
  if (!edge || edge.hit_rate == null) return <span className="dashboard-mono text-[10px] text-muted-foreground">--</span>
  return (
    <div className="space-y-0.5 text-right">
      <div className="dashboard-mono text-[11px]">{formatPercent(edge.hit_rate)}</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        [{edge.hit_ci_lower?.toFixed(2) ?? "--"}, {edge.hit_ci_upper?.toFixed(2) ?? "--"}]
      </div>
    </div>
  )
}

export function StockTable({
  stocks,
  horizon,
  horizonDays,
  signalView = "expanded",
  scoreSource = "signal_engine",
  hideDetails = false,
  edgeEnabled = true,
  edgeMode = "net",
  edgeMap = {},
  onOpenEdge,
}: StockTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("score")
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
      } else if (sortKey === "signal" || sortKey === "score") {
        leftValue = sourceScore(left, scoreSource, signalView)
        rightValue = sourceScore(right, scoreSource, signalView)
      } else if (sortKey === "expected_return") {
        leftValue = edgeMode === "net" ? edgeMap[left.symbol]?.expected_return_net ?? null : edgeMap[left.symbol]?.expected_return_gross ?? null
        rightValue = edgeMode === "net" ? edgeMap[right.symbol]?.expected_return_net ?? null : edgeMap[right.symbol]?.expected_return_gross ?? null
      } else if (sortKey === "hit_rate") {
        leftValue = edgeMap[left.symbol]?.hit_rate ?? null
        rightValue = edgeMap[right.symbol]?.hit_rate ?? null
      } else if (sortKey === "edge") {
        const order: Record<EdgeTriage, number> = { proven: 2, watch: 1, none: 0 }
        leftValue = order[edgeTriage(edgeMap[left.symbol], edgeMode)]
        rightValue = order[edgeTriage(edgeMap[right.symbol], edgeMode)]
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
  }, [stocks, sortKey, sortDir, scoreSource, signalView, edgeMap, edgeMode])

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

  const linkHorizon = toLegacyHorizon(horizon)

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-background px-4 py-3">
        <h3 className="text-[13px] font-semibold">Signaux par titre · Horizon {horizonLabel(horizon)} ({horizonDays} j)</h3>
        <div className="dashboard-meta">{sorted.length} lignes · triées par score composite</div>
      </div>

      <Table className="min-w-[1160px] text-[12px]">
        <TableHeader>
          <TableRow className="border-b border-border bg-muted/25 hover:bg-muted/25">
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
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Var. 1j</TableHead>
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("adv")}>
                ADV20
                <SortIcon columnKey="adv" />
              </button>
            </TableHead>
            {!hideDetails && (
              <>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Trend.</TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Mom.</TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Osc.</TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Vol.</TableHead>
              </>
            )}
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("score")}>
                Score
                <SortIcon columnKey="score" />
              </button>
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("signal")}>
                Signal
                <SortIcon columnKey="signal" />
              </button>
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("expected_return")}>
                E[R] <span className="normal-case font-normal text-muted-foreground/70">{horizonDays}j</span>
                <SortIcon columnKey="expected_return" />
              </button>
            </TableHead>
            {edgeEnabled ? (
              <>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("hit_rate")}>
                    Hit%
                    <SortIcon columnKey="hit_rate" />
                  </button>
                </TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("edge")}>
                    Edge
                    <SortIcon columnKey="edge" />
                  </button>
                </TableHead>
              </>
            ) : null}
            <TableHead className="h-auto w-10 px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((stock) => {
            const edge = edgeMap[stock.symbol]
            const expectedReturn = edgeMode === "net" ? edge?.expected_return_net : edge?.expected_return_gross
            const score = sourceScore(stock, scoreSource, signalView)
            const label = signalLabel(stock, scoreSource, signalView)
            const signalViewQuery = scoreSource === "wfo" ? "expanded" : signalView

            return (
              <TableRow key={stock.symbol} className="border-b border-border/70 hover:bg-background">
                <TableCell className="px-3 py-2.5 align-middle">
                  <span className="dashboard-mono text-[12px] font-semibold">{stock.symbol}</span>
                </TableCell>
                <TableCell className="max-w-[220px] px-3 py-2.5">
                  <Link
                    href={`/signals?symbol=${encodeURIComponent(stock.symbol)}&horizon=${linkHorizon}&view=${signalViewQuery}`}
                    className="block hover:underline"
                  >
                    <div className="text-[12px] font-medium">{stock.display_name ?? "-"}</div>
                  </Link>
                </TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">{formatNumber(priceForDisplay(stock))}</TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px] text-muted-foreground">--</TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px] text-muted-foreground">{formatNumber(stock.adv ?? null, 0)}</TableCell>
                {!hideDetails && (
                  <>
                    <TableCell className="px-3 py-2.5"><FamilyCell score={resolveSeFamily(stock, "trend", signalView)} /></TableCell>
                    <TableCell className="px-3 py-2.5"><FamilyCell score={resolveSeFamily(stock, "momentum", signalView)} /></TableCell>
                    <TableCell className="px-3 py-2.5"><FamilyCell score={resolveSeFamily(stock, "oscillation", signalView)} /></TableCell>
                    <TableCell className="px-3 py-2.5"><FamilyCell score={resolveSeFamily(stock, "volume", signalView)} /></TableCell>
                  </>
                )}
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px] font-semibold">{formatSigned(score)}</TableCell>
                <TableCell className="px-3 py-2.5"><SignalBadge label={label} /></TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                  <button type="button" onClick={() => onOpenEdge?.(stock)} className="hover:text-foreground">
                    {formatPercent(expectedReturn)}
                  </button>
                </TableCell>
                {edgeEnabled ? (
                  <>
                    <TableCell className="px-3 py-2.5 text-right">
                      <HitRateCell edge={edge} />
                    </TableCell>
                    <TableCell className="px-3 py-2.5">
                      <EdgeBadge triage={edgeTriage(edge, edgeMode)} />
                    </TableCell>
                  </>
                ) : null}
                <TableCell className="px-2 py-2.5 align-middle">
                  <button
                    type="button"
                    onClick={() => onOpenEdge?.(stock)}
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-muted-foreground transition hover:border-border hover:bg-muted/30 hover:text-foreground"
                    aria-label={`Ouvrir ${stock.symbol}`}
                  >
                    <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}
