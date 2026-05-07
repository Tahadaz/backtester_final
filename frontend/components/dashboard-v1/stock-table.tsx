"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import type { DashboardScoreSource, DashboardStock, Horizon } from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_SHORT_LABELS } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { ScoreBar } from "@/components/dashboard/score-bar"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Input } from "@/components/ui/input"
import { ChevronDown, ChevronUp, ChevronsUpDown, Search } from "lucide-react"

interface StockTableProps {
  stocks: DashboardStock[]
  horizon: Horizon
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  scoreSource?: DashboardScoreSource
  showTechnicalLevels?: boolean
}

type SortDir = "asc" | "desc"

type SortMetric =
  | { kind: "string"; value: string }
  | { kind: "number"; value: number | null }

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

function resolveSeFamilyScore(
  stock: DashboardStock,
  family: string,
  signalView: "legacy" | "expanded" | "factor_x_ta",
): number | null {
  const se = stock.scores.signal_engine
  const familyMap = signalView === "expanded" ? (se.expanded_per_family ?? se.per_family) : se.per_family
  return familyMap[family]?.score_pct ?? null
}

function resolveSeFamilyLabel(
  stock: DashboardStock,
  family: string,
  signalView: "legacy" | "expanded" | "factor_x_ta",
): { score_pct: number; label: string } | null {
  const se = stock.scores.signal_engine
  const familyMap = signalView === "expanded" ? (se.expanded_per_family ?? se.per_family) : se.per_family
  return familyMap[family] ?? null
}

function getSortMetric(
  stock: DashboardStock,
  key: string,
  signalView: "legacy" | "expanded" | "factor_x_ta",
  scoreSource: DashboardScoreSource,
): SortMetric {
  if (key === "symbol") return { kind: "string", value: stock.symbol }
  if (key === "sector") return { kind: "string", value: stock.sector ?? "" }

  if (key === "aggregate_score_pct") {
    if (scoreSource === "wfo") {
      return { kind: "number", value: stock.scores.wfo?.aggregate_score_pct ?? null }
    }
    return { kind: "number", value: resolveSeAggregate(stock, signalView) }
  }

  if (scoreSource === "wfo") {
    return { kind: "number", value: stock.scores.wfo?.per_family[key]?.score_pct ?? null }
  }

  return { kind: "number", value: resolveSeFamilyScore(stock, key, signalView) }
}

function compareMetrics(left: SortMetric, right: SortMetric, sortDir: SortDir): number {
  if (left.kind === "string" && right.kind === "string") {
    const comparison = left.value.localeCompare(right.value)
    return sortDir === "asc" ? comparison : -comparison
  }

  const leftValue = left.kind === "number" ? left.value : null
  const rightValue = right.kind === "number" ? right.value : null

  if (leftValue == null && rightValue == null) return 0
  if (leftValue == null) return 1
  if (rightValue == null) return -1

  const comparison = leftValue - rightValue
  return sortDir === "asc" ? comparison : -comparison
}

function formatLevelPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return value.toFixed(2)
}

function seSupportForDisplay(stock: DashboardStock): number | null | undefined {
  const se = stock.scores.signal_engine
  const isBuy = (se.aggregate_signal_label ?? "").includes("Achat")
  if (isBuy) {
    return se.technical_levels?.support_reference ?? se.technical_levels?.support_buy_trigger
  }
  return se.technical_levels?.support_buy_trigger ?? se.technical_levels?.support_reference
}

function wfoSupportForDisplay(stock: DashboardStock): number | null | undefined {
  const levels = stock.scores.wfo?.technical_levels
  return levels?.support_reference ?? levels?.support_buy_trigger
}

function TechnicalLevels({
  support,
  center,
  resistance,
}: {
  support: number | null | undefined
  center: number | null | undefined
  resistance: number | null | undefined
}) {
  return (
    <div className="grid grid-cols-3 items-center gap-1 rounded-md border bg-muted/20 px-2 py-1">
      <div className="text-left">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">S</p>
        <p className="font-mono text-xs font-semibold text-emerald-600">{formatLevelPrice(support)}</p>
      </div>
      <div className="text-center">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">C</p>
        <p className="font-mono text-xs font-semibold text-foreground">{formatLevelPrice(center)}</p>
      </div>
      <div className="text-right">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">R</p>
        <p className="font-mono text-xs font-semibold text-red-600">{formatLevelPrice(resistance)}</p>
      </div>
    </div>
  )
}

function AggregateSummary({
  label,
  score,
}: {
  label: string | null
  score: number | null
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <SignalBadge label={label} />
        <span className="font-mono text-sm font-semibold text-foreground">
          {score == null ? "-" : score > 0 ? `+${score.toFixed(1)}` : score.toFixed(1)}
        </span>
      </div>
      <ScoreBar score={score} />
    </div>
  )
}

export function StockTable({
  stocks,
  horizon,
  signalView = "legacy",
  scoreSource = "both",
  showTechnicalLevels = true,
}: StockTableProps) {
  const [search, setSearch] = useState("")
  const [sectorFilter, setSectorFilter] = useState<string>("all")
  const [hideUnavailable, setHideUnavailable] = useState(false)
  const [sortKey, setSortKey] = useState<string>("aggregate_score_pct")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const sectors = useMemo(() => {
    const set = new Set(
      stocks.map((stock) => stock.sector).filter((sector): sector is string => Boolean(sector)),
    )
    return ["all", ...Array.from(set).sort()]
  }, [stocks])

  const filtered = useMemo(() => {
    let result = stocks

    if (hideUnavailable) {
      if (scoreSource === "wfo") {
        result = result.filter((stock) => stock.scores.wfo?.aggregate_score_pct != null)
      } else {
        result = result.filter((stock) => resolveSeAggregate(stock, signalView) != null)
      }
    }

    if (search) {
      const query = search.toLowerCase()
      result = result.filter(
        (stock) =>
          stock.symbol.toLowerCase().includes(query) ||
          (stock.display_name ?? "").toLowerCase().includes(query),
      )
    }

    if (sectorFilter !== "all") {
      result = result.filter((stock) => stock.sector === sectorFilter)
    }

    return result
  }, [hideUnavailable, scoreSource, search, sectorFilter, signalView, stocks])

  const sorted = useMemo(() => {
    return filtered
      .map((stock, index) => ({ stock, index }))
      .sort((left, right) => {
        const leftMetric = getSortMetric(left.stock, sortKey, signalView, scoreSource)
        const rightMetric = getSortMetric(right.stock, sortKey, signalView, scoreSource)

        const comparison = compareMetrics(leftMetric, rightMetric, sortDir)
        if (comparison !== 0) return comparison
        return left.index - right.index
      })
      .map((row) => row.stock)
  }, [filtered, scoreSource, signalView, sortDir, sortKey])

  function onSort(nextKey: string) {
    if (nextKey === sortKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(nextKey)
    setSortDir("desc")
  }

  function SortIcon({ columnKey }: { columnKey: string }) {
    if (columnKey !== sortKey) return <ChevronsUpDown className="h-3.5 w-3.5" />
    return sortDir === "asc" ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />
  }

  return (
    <div>
      <div className="mb-5 grid gap-3 rounded-xl border bg-card/70 p-3 shadow-sm sm:grid-cols-[minmax(0,1fr)_260px]">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Rechercher une action..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-10 rounded-lg border-border/70 bg-background pl-9 text-sm"
          />
        </div>

        <div className="relative">
          <select
            value={sectorFilter}
            onChange={(event) => setSectorFilter(event.target.value)}
            className="h-10 w-full appearance-none rounded-lg border border-border/70 bg-background px-3 pr-9 text-sm font-medium text-foreground outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"
          >
            <option value="all">Tous les secteurs</option>
            {sectors
              .filter((sector) => sector !== "all")
              .map((sector) => (
                <option key={sector} value={sector}>
                  {sector}
                </option>
              ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="py-12 text-center text-muted-foreground">Aucune action ne correspond aux filtres.</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <button className="inline-flex items-center gap-1" onClick={() => onSort("symbol")}>
                  Action
                  <SortIcon columnKey="symbol" />
                </button>
              </TableHead>
              {FAMILY_ORDER.map((family) => (
                <TableHead key={family}>
                  <button className="inline-flex items-center gap-1" onClick={() => onSort(family)}>
                    {FAMILY_SHORT_LABELS[family]}
                    <SortIcon columnKey={family} />
                  </button>
                </TableHead>
              ))}
              <TableHead className={`sticky right-0 z-20 border-l bg-primary/10 text-primary ${showTechnicalLevels ? "min-w-[220px]" : "min-w-[180px]"}`}>
                <button
                  className="inline-flex w-full items-center justify-between gap-2 font-semibold"
                  onClick={() => onSort("aggregate_score_pct")}
                >
                  <span>Signal Technique Global</span>
                  <SortIcon columnKey="aggregate_score_pct" />
                </button>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((stock) => {
              const seFamily = (family: string) => resolveSeFamilyLabel(stock, family, signalView)
              const wfoFamily = (family: string) => stock.scores.wfo?.per_family[family] ?? null
              const seLabel = resolveSeAggregateLabel(stock, signalView)
              const wfoLabel = stock.scores.wfo?.aggregate_signal_label ?? null
              const signalViewQuery = scoreSource === "wfo" ? "expanded" : signalView

              return (
                <TableRow key={stock.symbol}>
                  <TableCell className="max-w-[220px]">
                    <Link
                      href={`/signals?symbol=${encodeURIComponent(stock.symbol)}&horizon=${horizon}&view=${signalViewQuery}`}
                      className="block hover:underline"
                    >
                      <p className="font-semibold">{stock.symbol}</p>
                      <p className="truncate text-xs text-muted-foreground">{stock.display_name ?? "-"}</p>
                    </Link>
                  </TableCell>

                  {FAMILY_ORDER.map((family) => (
                    <TableCell key={`${stock.symbol}-${family}`}>
                      {scoreSource === "both" ? (
                        <div className="space-y-1">
                          <div>
                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                            <FamilyCell score={seFamily(family)} />
                          </div>
                          <div className="border-t pt-1">
                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                            <FamilyCell score={wfoFamily(family)} />
                          </div>
                        </div>
                      ) : scoreSource === "wfo" ? (
                        <FamilyCell score={wfoFamily(family)} />
                      ) : (
                        <FamilyCell score={seFamily(family)} />
                      )}
                    </TableCell>
                  ))}

                  <TableCell className={`sticky right-0 z-10 border-l bg-background/95 backdrop-blur ${showTechnicalLevels ? "min-w-[220px]" : "min-w-[180px]"}`}>
                    {scoreSource === "both" ? (
                      <div className="space-y-2">
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                          {showTechnicalLevels ? (
                            <>
                              <SignalBadge label={seLabel} />
                              <TechnicalLevels
                                support={seSupportForDisplay(stock)}
                                center={stock.scores.signal_engine.technical_levels?.close_used}
                                resistance={stock.scores.signal_engine.technical_levels?.resistance_sell_trigger}
                              />
                            </>
                          ) : (
                            <AggregateSummary
                              label={seLabel}
                              score={resolveSeAggregate(stock, signalView)}
                            />
                          )}
                        </div>
                        <div className="border-t pt-1">
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                          {showTechnicalLevels ? (
                            <>
                              <SignalBadge label={wfoLabel} />
                              <TechnicalLevels
                                support={wfoSupportForDisplay(stock)}
                                center={stock.scores.wfo?.technical_levels?.support_reference}
                                resistance={stock.scores.wfo?.technical_levels?.resistance_sell_trigger}
                              />
                            </>
                          ) : (
                            <AggregateSummary
                              label={wfoLabel}
                              score={stock.scores.wfo?.aggregate_score_pct ?? null}
                            />
                          )}
                        </div>
                      </div>
                    ) : scoreSource === "wfo" ? (
                      <div className="space-y-1.5">
                        {showTechnicalLevels ? (
                          <>
                            <SignalBadge label={wfoLabel} />
                            <TechnicalLevels
                              support={wfoSupportForDisplay(stock)}
                              center={stock.scores.wfo?.technical_levels?.support_reference}
                              resistance={stock.scores.wfo?.technical_levels?.resistance_sell_trigger}
                            />
                          </>
                        ) : (
                          <AggregateSummary
                            label={wfoLabel}
                            score={stock.scores.wfo?.aggregate_score_pct ?? null}
                          />
                        )}
                      </div>
                    ) : (
                      <div className="space-y-1.5">
                        {showTechnicalLevels ? (
                          <>
                            <SignalBadge label={seLabel} />
                            <TechnicalLevels
                              support={seSupportForDisplay(stock)}
                              center={stock.scores.signal_engine.technical_levels?.close_used}
                              resistance={stock.scores.signal_engine.technical_levels?.resistance_sell_trigger}
                            />
                          </>
                        ) : (
                          <AggregateSummary
                            label={seLabel}
                            score={resolveSeAggregate(stock, signalView)}
                          />
                        )}
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
