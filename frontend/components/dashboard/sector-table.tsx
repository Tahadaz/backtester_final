"use client"

import Link from "next/link"
import { Fragment, useMemo, useState } from "react"
import type { DashboardSector, DashboardStock, Horizon } from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_SHORT_LABELS } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import { ChevronDown, ChevronRight } from "lucide-react"

interface SectorTableProps {
  sectors: DashboardSector[]
  stocks: DashboardStock[]
  horizon: Horizon
}

export function SectorTable({ sectors, stocks, horizon }: SectorTableProps) {
  const [expandedSector, setExpandedSector] = useState<string | null>(null)

  const sortedSectors = useMemo(
    () =>
      [...sectors].sort(
        (left, right) =>
          (right.scores.signal_engine.aggregate_score_pct ?? -999) -
          (left.scores.signal_engine.aggregate_score_pct ?? -999),
      ),
    [sectors],
  )

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
      <Table className="[&_thead]:sticky [&_thead]:top-0 [&_thead]:z-30 [&_thead]:bg-slate-900 dark:[&_thead]:bg-slate-950">
        <TableHeader>
          <TableRow className="border-b border-slate-200 dark:border-slate-700">
            <TableHead className="text-left text-xs font-bold uppercase tracking-wider text-white">Secteur</TableHead>
            {FAMILY_ORDER.map((family) => (
              <TableHead key={family} className="text-left text-xs font-bold uppercase tracking-wider text-white">{FAMILY_SHORT_LABELS[family]}</TableHead>
            ))}
            <TableHead className="sticky right-0 z-40 min-w-[240px] border-l border-slate-300 bg-blue-600 text-left text-xs font-bold uppercase tracking-wider text-white dark:border-slate-600 dark:bg-blue-700">
              <span>Signal Technique Global</span>
            </TableHead>
          </TableRow>
        </TableHeader>
      <TableBody className="divide-y divide-slate-200 dark:divide-slate-700">
        {sortedSectors.map((sector) => {
          const isOpen = expandedSector === sector.sector
          const sectorStocks = stocks.filter((stock) => stock.sector === sector.sector)

          return (
            <Fragment key={sector.sector}>
              <TableRow className="cursor-pointer border-none transition-colors hover:bg-slate-50 dark:hover:bg-slate-800" onClick={() => setExpandedSector(isOpen ? null : sector.sector)}>
                <TableCell className="py-4">
                  <button className="flex items-center gap-3 text-left">
                    {isOpen ? <ChevronDown className="h-4 w-4 text-slate-700 dark:text-slate-300" /> : <ChevronRight className="h-4 w-4 text-slate-700 dark:text-slate-300" />}
                    <div>
                      <p className="font-semibold text-slate-900 dark:text-white">{sector.sector}</p>
                      <p className="text-xs text-slate-500 dark:text-slate-400">({sector.stock_count} actions)</p>
                    </div>
                  </button>
                </TableCell>

                {FAMILY_ORDER.map((family) => (
                  <TableCell key={`${sector.sector}-${family}`} className="py-4">
                    <FamilyCell score={sector.scores.signal_engine.per_family[family]} />
                  </TableCell>
                ))}

                <TableCell className="sticky right-0 z-20 min-w-[240px] border-l border-slate-200 bg-blue-50 py-4 dark:border-slate-700 dark:bg-blue-950/30">
                  {sector.scores.signal_engine.aggregate_score_pct == null ? (
                    <span className="text-xs text-slate-500 dark:text-slate-400">-</span>
                  ) : (
                    <SignalBadge label={sector.scores.signal_engine.aggregate_signal_label} />
                  )}
                </TableCell>
              </TableRow>

              {isOpen && (
                <TableRow key={`${sector.sector}-expanded`}>
                  <TableCell colSpan={6} className="bg-slate-50 p-0 dark:bg-slate-900/50">
                    <Collapsible open={isOpen}>
                      <CollapsibleContent forceMount>
                        <div className="px-4 py-4">
                          {sectorStocks.length === 0 ? (
                            <p className="text-sm text-slate-500 dark:text-slate-400">Aucune action disponible pour ce secteur.</p>
                          ) : (
                            <Table>
                              <TableHeader>
                                <TableRow className="border-b border-slate-200 dark:border-slate-700">
                                  <TableHead className="pl-8 text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-400">Action</TableHead>
                                  {FAMILY_ORDER.map((family) => (
                                    <TableHead key={`${sector.sector}-nested-${family}`} className="text-xs font-semibold uppercase tracking-wider text-slate-700 dark:text-slate-400">
                                      {FAMILY_SHORT_LABELS[family]}
                                    </TableHead>
                                  ))}
                                  <TableHead className="sticky right-0 z-20 min-w-[240px] border-l border-slate-200 bg-blue-50 text-xs font-semibold uppercase tracking-wider text-blue-900 dark:border-slate-700 dark:bg-blue-950/50 dark:text-blue-200">
                                    <span>Signal Technique Global</span>
                                  </TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody className="divide-y divide-slate-100 dark:divide-slate-800">
                                {sectorStocks.map((stock) => (
                                  <TableRow key={`${sector.sector}-${stock.symbol}`} className="border-none hover:bg-slate-50 dark:hover:bg-slate-800">
                                    <TableCell className="pl-8 py-3">
                                        <Link
                                        href={signalEvidenceUrl({ symbol: stock.symbol, horizon })}
                                        className="block hover:text-blue-600 dark:hover:text-blue-400"
                                      >
                                        <p className="font-semibold text-slate-900 dark:text-white">{stock.symbol}</p>
                                        <p className="text-xs text-slate-500 dark:text-slate-400">{stock.display_name ?? "-"}</p>
                                      </Link>
                                    </TableCell>
                                    {FAMILY_ORDER.map((family) => (
                                      <TableCell key={`${stock.symbol}-nested-${family}`} className="py-3">
                                        <FamilyCell score={stock.scores.signal_engine.per_family[family]} />
                                      </TableCell>
                                    ))}
                                    <TableCell className="sticky right-0 z-20 min-w-[240px] border-l border-slate-200 bg-blue-50/80 py-3 dark:border-slate-700 dark:bg-blue-950/20">
                                      {stock.scores.signal_engine.aggregate_score_pct == null ? (
                                        <span className="text-xs text-slate-500 dark:text-slate-400">-</span>
                                      ) : (
                                        <SignalBadge label={stock.scores.signal_engine.aggregate_signal_label} />
                                      )}
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
    </div>
  )
}
