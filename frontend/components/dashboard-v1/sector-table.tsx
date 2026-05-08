"use client"

import Link from "next/link"
import { Fragment, useMemo, useState } from "react"
import type {
  DashboardScoreSource,
  DashboardSector,
  DashboardStock,
  Horizon,
  SignalEngineScores,
  WfoScores,
} from "@/lib/dashboard-types"
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
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  scoreSource?: DashboardScoreSource
  showTechnicalLevels?: boolean
}

function toLegacyHorizon(horizon: Horizon): "short" | "medium" | "long" {
  if (horizon === "weekly") return "short"
  if (horizon === "monthly") return "medium"
  if (horizon === "quarterly") return "long"
  if (horizon === "medium") return "medium"
  if (horizon === "long") return "long"
  return "short"
}

function formatLevelPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return value.toFixed(2)
}

function resolveSeAggregateScore(item: SignalEngineScores, signalView: "legacy" | "expanded" | "factor_x_ta"): number | null {
  return signalView === "expanded"
    ? (item.expanded_aggregate_score_pct ?? item.aggregate_score_pct)
    : item.aggregate_score_pct
}

function resolveSeAggregateLabel(item: SignalEngineScores, signalView: "legacy" | "expanded" | "factor_x_ta"): string | null {
  return signalView === "expanded"
    ? (item.expanded_aggregate_signal_label ?? item.aggregate_signal_label)
    : item.aggregate_signal_label
}

function resolveSeFamily(
  stockOrSector: DashboardStock | DashboardSector,
  family: string,
  signalView: "legacy" | "expanded" | "factor_x_ta",
) {
  const se = stockOrSector.scores.signal_engine
  const familyMap = signalView === "expanded" ? (se.expanded_per_family ?? se.per_family) : se.per_family
  return familyMap[family] ?? null
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

function scoreForSort(
  sector: DashboardSector,
  scoreSource: DashboardScoreSource,
  signalView: "legacy" | "expanded" | "factor_x_ta",
): number | null {
  if (scoreSource === "wfo") {
    return sector.scores.wfo?.aggregate_score_pct ?? null
  }
  return resolveSeAggregateScore(sector.scores.signal_engine, signalView)
}

function compareScores(left: number | null, right: number | null): number {
  if (left == null && right == null) return 0
  if (left == null) return 1
  if (right == null) return -1
  return right - left
}

function AggregateCell({
  signalView,
  scoreSource,
  signalEngine,
  wfo,
}: {
  signalView: "legacy" | "expanded" | "factor_x_ta"
  scoreSource: DashboardScoreSource
  signalEngine: SignalEngineScores
  wfo: WfoScores | null
}) {
  if (scoreSource === "both") {
    const seScore = resolveSeAggregateScore(signalEngine, signalView)
    const seLabel = resolveSeAggregateLabel(signalEngine, signalView)
    const wfoScore = wfo?.aggregate_score_pct ?? null
    const wfoLabel = wfo?.aggregate_signal_label ?? null

    return (
      <div className="space-y-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
          <div className="flex items-center justify-between gap-2">
            <SignalBadge label={seLabel} />
            <span className="font-mono text-sm font-semibold text-foreground">{formatScore(seScore)}</span>
          </div>
          <ScoreBar score={seScore} />
        </div>
        <div className="border-t pt-1">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
          <div className="flex items-center justify-between gap-2">
            <SignalBadge label={wfoLabel} />
            <span className="font-mono text-sm font-semibold text-foreground">{formatScore(wfoScore)}</span>
          </div>
          <ScoreBar score={wfoScore} />
        </div>
      </div>
    )
  }

  if (scoreSource === "wfo") {
    const wfoScore = wfo?.aggregate_score_pct ?? null
    return (
      <div className="space-y-1">
        <div className="flex items-center justify-between gap-2">
          <SignalBadge label={wfo?.aggregate_signal_label ?? null} />
          <span className="font-mono text-sm font-semibold text-foreground">{formatScore(wfoScore)}</span>
        </div>
        <ScoreBar score={wfoScore} />
      </div>
    )
  }

  const seScore = resolveSeAggregateScore(signalEngine, signalView)
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between gap-2">
        <SignalBadge label={resolveSeAggregateLabel(signalEngine, signalView)} />
        <span className="font-mono text-sm font-semibold text-foreground">{formatScore(seScore)}</span>
      </div>
      <ScoreBar score={seScore} />
    </div>
  )
}

export function SectorTable({
  sectors,
  stocks,
  horizon,
  signalView = "legacy",
  scoreSource = "both",
  showTechnicalLevels = true,
}: SectorTableProps) {
  const [expandedSector, setExpandedSector] = useState<string | null>(null)
  const linkHorizon = toLegacyHorizon(horizon)

  const sortedSectors = useMemo(
    () =>
      [...sectors].sort((left, right) =>
        compareScores(
          scoreForSort(left, scoreSource, signalView),
          scoreForSort(right, scoreSource, signalView),
        ),
      ),
    [scoreSource, sectors, signalView],
  )

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Secteur</TableHead>
          {FAMILY_ORDER.map((family) => (
            <TableHead key={family}>{FAMILY_SHORT_LABELS[family]}</TableHead>
          ))}
          <TableHead className={`sticky right-0 z-20 border-l bg-primary/10 text-primary ${showTechnicalLevels ? "min-w-[220px]" : "min-w-[180px]"}`}>
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
                    {scoreSource === "both" ? (
                      <div className="space-y-1">
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                          <FamilyCell score={resolveSeFamily(sector, family, signalView)} />
                        </div>
                        <div className="border-t pt-1">
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                          <FamilyCell score={sector.scores.wfo?.per_family[family] ?? null} />
                        </div>
                      </div>
                    ) : scoreSource === "wfo" ? (
                      <FamilyCell score={sector.scores.wfo?.per_family[family] ?? null} />
                    ) : (
                      <FamilyCell score={resolveSeFamily(sector, family, signalView)} />
                    )}
                  </TableCell>
                ))}

                <TableCell className={`sticky right-0 z-10 border-l bg-background/95 backdrop-blur ${showTechnicalLevels ? "min-w-[220px]" : "min-w-[180px]"}`}>
                  <AggregateCell
                    signalView={signalView}
                    scoreSource={scoreSource}
                    signalEngine={sector.scores.signal_engine}
                    wfo={sector.scores.wfo}
                  />
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
                                  <TableHead className={`sticky right-0 z-20 border-l bg-primary/10 text-primary ${showTechnicalLevels ? "min-w-[220px]" : "min-w-[180px]"}`}>
                                    <span className="font-semibold">Signal Technique Global</span>
                                  </TableHead>
                                </TableRow>
                              </TableHeader>
                              <TableBody>
                                {sectorStocks.map((stock) => {
                                  const signalViewQuery = scoreSource === "wfo" ? "expanded" : signalView

                                  return (
                                    <TableRow key={`${sector.sector}-${stock.symbol}`}>
                                      <TableCell className="pl-8">
                                        <Link
                                          href={`/signals?symbol=${encodeURIComponent(stock.symbol)}&horizon=${linkHorizon}&view=${signalViewQuery}`}
                                          className="block hover:underline"
                                        >
                                          <p className="font-semibold">{stock.symbol}</p>
                                          <p className="text-xs text-muted-foreground">{stock.display_name ?? "-"}</p>
                                        </Link>
                                      </TableCell>

                                      {FAMILY_ORDER.map((family) => (
                                        <TableCell key={`${stock.symbol}-nested-${family}`}>
                                          {scoreSource === "both" ? (
                                            <div className="space-y-1">
                                              <div>
                                                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                                                <FamilyCell score={resolveSeFamily(stock, family, signalView)} />
                                              </div>
                                              <div className="border-t pt-1">
                                                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
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

                                      <TableCell className={`sticky right-0 z-10 border-l bg-background/95 backdrop-blur ${showTechnicalLevels ? "min-w-[220px]" : "min-w-[180px]"}`}>
                                        {scoreSource === "both" ? (
                                          <div className="space-y-2">
                                            <div>
                                              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                                              {showTechnicalLevels ? (
                                                <>
                                                  <SignalBadge label={resolveSeAggregateLabel(stock.scores.signal_engine, signalView)} />
                                                  <TechnicalLevels
                                                    support={seSupportForDisplay(stock)}
                                                    center={stock.scores.signal_engine.technical_levels?.close_used}
                                                    resistance={stock.scores.signal_engine.technical_levels?.resistance_sell_trigger}
                                                  />
                                                </>
                                              ) : (
                                                <AggregateSummary
                                                  label={resolveSeAggregateLabel(stock.scores.signal_engine, signalView)}
                                                  score={resolveSeAggregateScore(stock.scores.signal_engine, signalView)}
                                                />
                                              )}
                                            </div>
                                            <div className="border-t pt-1">
                                              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                                              {showTechnicalLevels ? (
                                                <>
                                                  <SignalBadge label={stock.scores.wfo?.aggregate_signal_label ?? null} />
                                                  <TechnicalLevels
                                                    support={wfoSupportForDisplay(stock)}
                                                    center={stock.scores.wfo?.technical_levels?.support_reference}
                                                    resistance={stock.scores.wfo?.technical_levels?.resistance_sell_trigger}
                                                  />
                                                </>
                                              ) : (
                                                <AggregateSummary
                                                  label={stock.scores.wfo?.aggregate_signal_label ?? null}
                                                  score={stock.scores.wfo?.aggregate_score_pct ?? null}
                                                />
                                              )}
                                            </div>
                                          </div>
                                        ) : scoreSource === "wfo" ? (
                                          <div className="space-y-1.5">
                                            {showTechnicalLevels ? (
                                              <>
                                                <SignalBadge label={stock.scores.wfo?.aggregate_signal_label ?? null} />
                                                <TechnicalLevels
                                                  support={wfoSupportForDisplay(stock)}
                                                  center={stock.scores.wfo?.technical_levels?.support_reference}
                                                  resistance={stock.scores.wfo?.technical_levels?.resistance_sell_trigger}
                                                />
                                              </>
                                            ) : (
                                              <AggregateSummary
                                                label={stock.scores.wfo?.aggregate_signal_label ?? null}
                                                score={stock.scores.wfo?.aggregate_score_pct ?? null}
                                              />
                                            )}
                                          </div>
                                        ) : (
                                          <div className="space-y-1.5">
                                            {showTechnicalLevels ? (
                                              <>
                                                <SignalBadge label={resolveSeAggregateLabel(stock.scores.signal_engine, signalView)} />
                                                <TechnicalLevels
                                                  support={seSupportForDisplay(stock)}
                                                  center={stock.scores.signal_engine.technical_levels?.close_used}
                                                  resistance={stock.scores.signal_engine.technical_levels?.resistance_sell_trigger}
                                                />
                                              </>
                                            ) : (
                                              <AggregateSummary
                                                label={resolveSeAggregateLabel(stock.scores.signal_engine, signalView)}
                                                score={resolveSeAggregateScore(stock.scores.signal_engine, signalView)}
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
