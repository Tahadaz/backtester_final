"use client"

import Link from "next/link"
import { Fragment, useMemo, useState } from "react"
import type { DashboardSector, DashboardStock, Horizon } from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_SHORT_LABELS, formatScore } from "@/lib/dashboard-constants"
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
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { ChevronDown, ChevronRight } from "lucide-react"

interface SectorTableProps {
  sectors: DashboardSector[]
  stocks: DashboardStock[]
  horizon: Horizon
  signalView?: "legacy" | "expanded"
}

function formatLevelPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return value.toFixed(2)
}

function supportForDisplay(stock: DashboardStock): number | null | undefined {
  const isBuy = (stock.aggregate_signal_label ?? "").includes("Achat")
  if (isBuy) {
    return stock.technical_levels?.support_reference ?? stock.technical_levels?.support_buy_trigger
  }
  return stock.technical_levels?.support_buy_trigger ?? stock.technical_levels?.support_reference
}

export function SectorTable({ sectors, stocks, horizon, signalView = "legacy" }: SectorTableProps) {
  function resolveAggregateLabel(item: { aggregate_signal_label: string | null; expanded_aggregate_signal_label?: string | null }): string | null {
    return signalView === "expanded" ? (item.expanded_aggregate_signal_label ?? item.aggregate_signal_label) : item.aggregate_signal_label
  }
  function resolveAggregateScore(item: { aggregate_score_pct: number | null; expanded_aggregate_score_pct?: number | null }): number | null {
    return signalView === "expanded" ? (item.expanded_aggregate_score_pct ?? item.aggregate_score_pct) : item.aggregate_score_pct
  }
  const [expandedSector, setExpandedSector] = useState<string | null>(null)

  const sortedSectors = useMemo(
    () =>
      [...sectors].sort(
        (left, right) => (right.aggregate_score_pct ?? -999) - (left.aggregate_score_pct ?? -999),
      ),
    [sectors],
  )

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Secteur</TableHead>
          {FAMILY_ORDER.map((family) => (
            <TableHead key={family}>{FAMILY_SHORT_LABELS[family]}</TableHead>
          ))}
          <TableHead className="sticky right-0 z-20 min-w-[220px] border-l bg-primary/10 text-primary">
            <span className="font-semibold">Signal Technique Global</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sortedSectors.map((sector) => {
          const isOpen = expandedSector === sector.sector
          const sectorStocks = stocks.filter((stock) => stock.sector === sector.sector)

          return (
            <Fragment key={sector.sector}>
              <TableRow className="cursor-pointer hover:bg-muted/40" onClick={() => setExpandedSector(isOpen ? null : sector.sector)}>
                <TableCell>
                  <button className="flex items-center gap-2 text-left">
                    {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    <div>
                      <p className="font-medium">{sector.sector}</p>
                      <p className="text-xs text-muted-foreground">({sector.stock_count} actions)</p>
                    </div>
                  </button>
                </TableCell>

                {FAMILY_ORDER.map((family) => (
                  <TableCell key={`${sector.sector}-${family}`}>
                    <FamilyCell score={signalView === "expanded" ? (sector.expanded_per_family?.[family] || sector.per_family[family]) : sector.per_family[family]} />
                  </TableCell>
                ))}

                <TableCell className="sticky right-0 z-10 min-w-[220px] border-l bg-background/95 backdrop-blur">
                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <SignalBadge label={resolveAggregateLabel(sector)} />
                      <span className="font-mono text-sm font-semibold text-foreground">
                        {formatScore(resolveAggregateScore(sector))}
                      </span>
                    </div>
                    <ScoreBar score={resolveAggregateScore(sector)} />
                  </div>
                </TableCell>
              </TableRow>

              {isOpen && (
                <TableRow key={`${sector.sector}-expanded`}>
                  <TableCell colSpan={6} className="bg-muted/30 p-0">
                    <Collapsible open={isOpen}>
                      <CollapsibleContent forceMount>
                        <div className="px-4 py-3">
                          {sectorStocks.length === 0 ? (
                            <p className="text-sm text-muted-foreground">Aucune action disponible pour ce secteur.</p>
                          ) : (
                            <Table>
                              <TableHeader>
                                <TableRow>
                                  <TableHead className="pl-8">Action</TableHead>
                                  {FAMILY_ORDER.map((family) => (
                                    <TableHead key={`${sector.sector}-nested-${family}`}>
                                      {FAMILY_SHORT_LABELS[family]}
                                    </TableHead>
                                  ))}
                                  <TableHead className="sticky right-0 z-20 min-w-[220px] border-l bg-primary/10 text-primary">
                                    <span className="font-semibold">Signal Technique Global</span>
                                  </TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {sectorStocks.map((stock) => (
                                  <TableRow key={`${sector.sector}-${stock.symbol}`}>
                                    <TableCell className="pl-8">
                                      <Link
                                        href={`/signals?symbol=${encodeURIComponent(stock.symbol)}&horizon=${horizon}&view=${signalView}`}
                                        className="block hover:underline"
                                      >
                                        <p className="font-semibold">{stock.symbol}</p>
                                        <p className="text-xs text-muted-foreground">{stock.display_name ?? "-"}</p>
                                      </Link>
                                    </TableCell>
                                    {FAMILY_ORDER.map((family) => (
                                      <TableCell key={`${stock.symbol}-nested-${family}`}>
                                        <FamilyCell score={signalView === "expanded" ? (stock.expanded_per_family?.[family] || stock.per_family[family]) : stock.per_family[family]} />
                                      </TableCell>
                                    ))}
                                    <TableCell className="sticky right-0 z-10 min-w-[220px] border-l bg-background/95 backdrop-blur">
                                      <div className="space-y-1">
                                        <div className="flex items-center justify-between gap-2">
                                          <SignalBadge label={resolveAggregateLabel(stock)} />
                                        </div>
                                        <div className="grid grid-cols-3 items-center gap-1 rounded-md border bg-muted/20 px-2 py-1">
                                          <div className="text-left">
                                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">S</p>
                                            <p className="font-mono text-xs font-semibold text-emerald-600">
                                              {formatLevelPrice(supportForDisplay(stock))}
                                            </p>
                                          </div>
                                          <div className="text-center">
                                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">C</p>
                                            <p className="font-mono text-xs font-semibold text-foreground">
                                              {formatLevelPrice(stock.technical_levels?.close_used)}
                                            </p>
                                          </div>
                                          <div className="text-right">
                                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">R</p>
                                            <p className="font-mono text-xs font-semibold text-red-600">
                                              {formatLevelPrice(stock.technical_levels?.resistance_sell_trigger)}
                                            </p>
                                          </div>
                                        </div>
                                      </div>
                                    </TableCell>
                                  </TableRow>
                                ))}
                              </TableBody>
                            </Table>
                          )}
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  </TableCell>
                </TableRow>
              )}
            </Fragment>
          )
        })}
      </TableBody>
    </Table>
  )
}
