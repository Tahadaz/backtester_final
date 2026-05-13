"use client"

import Link from "next/link"
import { Fragment, useMemo, useState } from "react"
import { ArrowRight, ChevronDown, ChevronRight, RotateCcw, Save } from "lucide-react"
import type {
  DashboardDisplayMode,
  DashboardScoreSource,
  DashboardSector,
  DashboardStock,
  Horizon,
  SignalEngineScores,
} from "@/lib/dashboard-types"
import { FAMILY_ORDER, FAMILY_SHORT_LABELS } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import {
  BestSignalBadgeCell,
  BestSignalExpectedReturnCell,
  BestSignalHitRateCell,
  BestSignalMethodCell,
  EdgeBadge,
  PortfolioEdgeBadgeCell,
  PortfolioEdgeExpectedReturnCell,
  PortfolioEdgeHitRateCell,
  PortfolioEdgeMethodCell,
  bestSignalForDisplay,
  bestSignalTriage,
  compareBestSignalStocks,
  comparePortfolioEdges,
  compareTechnicalSignalStocks,
  displayVariantLabel,
  portfolioEdgeTriage,
  summarizeBestSignals,
  summarizeTechnicalSignals,
  technicalSignalForDisplay,
} from "./best-signal-cells"
import { SignalBadge } from "./signal-badge"
import { formatPercent } from "@/lib/format"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import { cn } from "@/lib/utils"
import {
  buildPortfolioWeightRows,
  portfolioRowsBySymbol,
  summarizeWeightRows,
} from "./sector-portfolio-utils.mjs"

type FamilyKey = (typeof FAMILY_ORDER)[number]
type PortfolioWeightRow = {
  shares: number
  price: number | null
  marketValue: number
  weightPct: number
}

interface SectorTableProps {
  sectors: DashboardSector[]
  stocks: DashboardStock[]
  horizon: Horizon
  horizonDays: number
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  scoreSource?: DashboardScoreSource
  displayMode?: DashboardDisplayMode
  edgeEnabled?: boolean
  showTechnicalLevels?: boolean
  visibleFamilies?: Partial<Record<FamilyKey, boolean>>
  portfolioShares?: Record<string, string | number | null | undefined>
  portfolioSharesDirty?: boolean
  portfolioSharesSaving?: boolean
  portfolioSharesError?: string | null
  onPortfolioShareChange?: (symbol: string, shares: string) => void
  onSavePortfolioShares?: () => void
  onResetPortfolioShares?: () => void
}

function resolveSeAggregateScore(item: SignalEngineScores, signalView: "legacy" | "expanded" | "factor_x_ta"): number | null {
  if (signalView === "factor_x_ta") return item.factor_x_ta_aggregate_score_pct ?? null
  if (signalView === "expanded") return item.expanded_aggregate_score_pct ?? item.aggregate_score_pct
  return item.aggregate_score_pct
}

function resolveSeFamily(
  stockOrSector: DashboardStock | DashboardSector,
  family: string,
  signalView: "legacy" | "expanded" | "factor_x_ta",
) {
  const se = stockOrSector.scores.signal_engine
  const familyMap = signalView === "factor_x_ta"
    ? se.factor_x_ta_per_family
    : signalView === "expanded"
      ? (se.expanded_per_family ?? se.per_family)
      : se.per_family
  return familyMap?.[family] ?? null
}

function resolveFactorDependencies(
  stockOrSector: DashboardStock | DashboardSector,
  family: string,
  signalView: "legacy" | "expanded" | "factor_x_ta",
) {
  if (signalView !== "factor_x_ta") return undefined
  return stockOrSector.scores.signal_engine.factor_dependencies?.[family]
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

function horizonLabel(horizon: Horizon) {
  if (horizon === "weekly") return "court"
  if (horizon === "monthly") return "moyen"
  if (horizon === "quarterly") return "long"
  if (horizon === "medium") return "moyen"
  if (horizon === "long") return "long"
  return "court"
}

function evidenceHref(
  stock: DashboardStock,
  horizon: Horizon,
) {
  const signal = bestSignalForDisplay(stock)
  return signalEvidenceUrl({
    symbol: stock.symbol,
    horizon,
    view: signal?.variant ?? "expanded_ta_simple",
    source: "wfo",
  })
}

function technicalHref(stock: DashboardStock, horizon: Horizon) {
  const signal = technicalSignalForDisplay(stock)
  const variant = signal?.variant ?? "expanded_ta_simple"
  return signalEvidenceUrl({
    symbol: stock.symbol,
    horizon,
    view: variant,
    source: signal?.source ?? "auto",
    evidenceVariant: signal?.variant,
    tab: "technique",
  })
}

function technicalDirectionLabel(direction: string | null | undefined) {
  if (direction === "long") return "Long"
  if (direction === "short") return "Short"
  return "Neutre"
}

function formatScorePct(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(1)}`
}

function formatWeightPct(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${value.toLocaleString("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`
}

function formatMoneyCompact(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${Math.round(value).toLocaleString("fr-FR")} MAD`
}

function WeightedSignalCell({ summary }: { summary: ReturnType<typeof summarizeWeightRows> }) {
  if (!summary || summary.totalWeightPct <= 0) {
    return <SignalBadge label="Indisponible" />
  }
  return (
    <div className="space-y-1">
      <SignalBadge label={summary.signalLabel} />
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        {formatWeightPct(summary.longWeightPct)}L/{formatWeightPct(summary.shortWeightPct)}S
      </div>
    </div>
  )
}

function WeightedMethodCell({ summary }: { summary: ReturnType<typeof summarizeWeightRows> }) {
  if (!summary || summary.totalWeightPct <= 0) {
    return <span className="text-[11px] text-muted-foreground">No portfolio weight</span>
  }
  return (
    <div className="space-y-1">
      <div className="max-w-[180px] truncate text-[11px] font-semibold">Poids manuels</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        {summary.investedCount} lignes - {formatWeightPct(summary.totalWeightPct)}
      </div>
    </div>
  )
}

function WeightedExpectedReturnCell({ summary }: { summary: ReturnType<typeof summarizeWeightRows> }) {
  if (!summary || summary.weightedAverageExpectedReturnNet == null) {
    return (
      <div className="space-y-0.5 text-right text-muted-foreground">
        <div>No eligible</div>
        <div className="dashboard-mono text-[10px]">weighted E[R]</div>
      </div>
    )
  }
  return (
    <div className="space-y-0.5 text-right">
      <div>{formatPercent(summary.weightedAverageExpectedReturnNet)}</div>
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        contribution {formatPercent(summary.weightedExpectedReturnNet)}
      </div>
    </div>
  )
}

export function SectorTable({
  sectors,
  stocks,
  horizon,
  horizonDays,
  signalView = "legacy",
  scoreSource = "both",
  displayMode = "trade_opportunities",
  edgeEnabled = true,
  visibleFamilies,
  portfolioShares,
  portfolioSharesDirty = false,
  portfolioSharesSaving = false,
  portfolioSharesError,
  onPortfolioShareChange,
  onSavePortfolioShares,
  onResetPortfolioShares,
}: SectorTableProps) {
  const [expandedSector, setExpandedSector] = useState<string | null>(null)
  const isTechnicalMode = displayMode === "technical_directions"
  const showPortfolioWeights = Boolean(portfolioShares && onPortfolioShareChange)

  const shownFamilies = useMemo(
    () => isTechnicalMode ? FAMILY_ORDER.filter((family) => visibleFamilies?.[family] !== false) : [],
    [isTechnicalMode, visibleFamilies],
  )

  const portfolioWeights = useMemo(
    () => buildPortfolioWeightRows(stocks, portfolioShares ?? {}, { displayMode }),
    [displayMode, portfolioShares, stocks],
  )
  const portfolioRowBySymbol = useMemo<Record<string, PortfolioWeightRow>>(
    () => portfolioRowsBySymbol(portfolioWeights.rows) as Record<string, PortfolioWeightRow>,
    [portfolioWeights.rows],
  )
  const portfolioSummary = useMemo(
    () => summarizeWeightRows(portfolioWeights.rows),
    [portfolioWeights.rows],
  )
  const hasWeightedPortfolio = showPortfolioWeights && portfolioSummary.totalWeightPct > 0

  const sectorRows = useMemo(
    () =>
      sectors
        .map((sector) => {
          const sectorStocks = stocks.filter((stock) => stock.sector === sector.sector)
          const weightSummary = summarizeWeightRows(
            portfolioWeights.rows.filter((row) => row.sector === sector.sector),
          )
          return {
            sector,
            sectorStocks,
            sortedStocks: [...sectorStocks].sort(isTechnicalMode ? compareTechnicalSignalStocks : compareBestSignalStocks),
            stats: summarizeBestSignals(sectorStocks),
            technicalStats: summarizeTechnicalSignals(sectorStocks),
            weightSummary,
          }
        })
        .sort((left, right) => {
          if (hasWeightedPortfolio) {
            const weight = right.weightSummary.totalWeightPct - left.weightSummary.totalWeightPct
            if (weight !== 0) return weight
          }
          if (isTechnicalMode) {
            const rightScore = right.technicalStats.topSignal?.abs_score_pct ?? Number.NEGATIVE_INFINITY
            const leftScore = left.technicalStats.topSignal?.abs_score_pct ?? Number.NEGATIVE_INFINITY
            if (rightScore !== leftScore) return rightScore - leftScore
          }
          const portfolio = comparePortfolioEdges(left.sector.portfolio_edge, right.sector.portfolio_edge)
          if (portfolio !== 0) return portfolio
          return compareScores(
            scoreForSort(left.sector, scoreSource, signalView),
            scoreForSort(right.sector, scoreSource, signalView),
          )
        }),
    [hasWeightedPortfolio, isTechnicalMode, portfolioWeights.rows, scoreSource, sectors, signalView, stocks],
  )

  const columnCount = 1 + (showPortfolioWeights ? 1 : 0) + shownFamilies.length + 3 + (!isTechnicalMode && edgeEnabled ? 2 : 0) + 1
  const tableMinWidthClass = showPortfolioWeights
    ? shownFamilies.length === 0
      ? "min-w-[1160px]"
      : shownFamilies.length < FAMILY_ORDER.length
        ? "min-w-[1300px]"
        : "min-w-[1420px]"
    : shownFamilies.length === 0
      ? "min-w-[880px]"
      : shownFamilies.length < FAMILY_ORDER.length
        ? "min-w-[1020px]"
        : "min-w-[1140px]"

  if (sectorRows.length === 0) {
    return <div className="dashboard-panel px-4 py-12 text-center text-sm text-muted-foreground">Aucun secteur ne correspond aux filtres.</div>
  }

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <h3 className="dashboard-section-title">Signaux par secteur - Horizon {horizonLabel(horizon)} ({horizonDays} j)</h3>
        <div className="dashboard-meta">
          {sectorRows.length} secteurs - {hasWeightedPortfolio ? "poids manuels" : "edge portefeuille"}
        </div>
      </div>

      {showPortfolioWeights ? (
        <div className="grid gap-2 border-b border-border bg-background px-4 py-3 md:grid-cols-5">
          <div className="dashboard-field px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Portefeuille</div>
            <div className="mt-1">
              <WeightedSignalCell summary={portfolioSummary} />
            </div>
          </div>
          <div className="dashboard-field px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Valeur</div>
            <div className="dashboard-mono mt-1 text-[13px] font-semibold">{formatMoneyCompact(portfolioWeights.totalMarketValue)}</div>
            <div className="dashboard-mono mt-0.5 text-[10px] text-muted-foreground">
              {portfolioWeights.investedCount} lignes valorisees
            </div>
          </div>
          <div className="dashboard-field px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Long / Short</div>
            <div className="dashboard-mono mt-1 text-[13px] font-semibold">
              {formatWeightPct(portfolioSummary.longWeightPct)} / {formatWeightPct(portfolioSummary.shortWeightPct)}
            </div>
            <div className="dashboard-mono mt-0.5 text-[10px] text-muted-foreground">
              net {formatScorePct(portfolioSummary.netSignalPct)}
            </div>
          </div>
          <div className="dashboard-field px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">E[R] pondere</div>
            <div className="dashboard-mono mt-1 text-[13px] font-semibold">
              {formatPercent(portfolioSummary.weightedExpectedReturnNet)}
            </div>
            <div className="dashboard-mono mt-0.5 text-[10px] text-muted-foreground">
              moyenne {formatPercent(portfolioSummary.weightedAverageExpectedReturnNet)}
            </div>
          </div>
          <div className="dashboard-field flex flex-col justify-between gap-2 px-3 py-2">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Positions</div>
              <div className="mt-1 text-[11px] text-muted-foreground">
                {portfolioSharesError ?? (portfolioSharesDirty ? "Modifications non sauvegardees" : "Synchronise")}
              </div>
              {portfolioWeights.missingPriceCount > 0 ? (
                <div className="mt-0.5 text-[10px] text-destructive">
                  {portfolioWeights.missingPriceCount} prix absent(s)
                </div>
              ) : null}
            </div>
            <div className="flex gap-2">
              {onResetPortfolioShares ? (
                <button
                  type="button"
                  onClick={onResetPortfolioShares}
                  className="inline-flex h-7 flex-1 items-center justify-center gap-1 rounded-md border border-border px-2 text-[11px] text-muted-foreground transition hover:bg-muted/30 hover:text-foreground"
                >
                  <RotateCcw className="h-3 w-3" />
                  Reset
                </button>
              ) : null}
              {onSavePortfolioShares ? (
                <button
                  type="button"
                  onClick={onSavePortfolioShares}
                  disabled={!portfolioSharesDirty || portfolioSharesSaving}
                  className="inline-flex h-7 flex-1 items-center justify-center gap-1 rounded-md border border-border px-2 text-[11px] font-semibold transition hover:bg-muted/30 disabled:pointer-events-none disabled:opacity-50"
                >
                  <Save className={cn("h-3 w-3", portfolioSharesSaving && "animate-pulse")} />
                  Save
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <Table className={cn(tableMinWidthClass, "text-[12px]")}>
        <TableHeader>
          <TableRow className="border-b border-border bg-bg2 hover:bg-bg2">
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Secteur</TableHead>
            {showPortfolioWeights ? (
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Poids</TableHead>
            ) : null}
            {shownFamilies.map((family) => (
              <TableHead key={family} className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {FAMILY_SHORT_LABELS[family]}
              </TableHead>
            ))}
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {isTechnicalMode ? "Direction best" : "Portefeuille"}
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {isTechnicalMode ? "Methode technique" : "Methode auto"}
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {isTechnicalMode ? "Score technique" : "retour attendu"}
            </TableHead>
            {!isTechnicalMode && edgeEnabled && showPortfolioWeights ? (
              <>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Actif poids</TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Net poids</TableHead>
              </>
            ) : null}
            {!isTechnicalMode && edgeEnabled && !showPortfolioWeights ? (
              <>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">%succés port.</TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Edge</TableHead>
              </>
            ) : null}
            <TableHead className="h-auto w-10 px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sectorRows.map(({ sector, sectorStocks, sortedStocks, stats, technicalStats, weightSummary }) => {
            const isOpen = expandedSector === sector.sector
            const portfolioEdge = sector.portfolio_edge ?? null
            const topTechnicalSignal = technicalStats.topSignal

            return (
              <Fragment key={sector.sector}>
                <TableRow className="cursor-pointer border-b border-border/70 hover:bg-bg2" onClick={() => setExpandedSector(isOpen ? null : sector.sector)}>
                  <TableCell className="px-3 py-2.5 align-middle">
                    <button className="flex items-center gap-2 text-left">
                      {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      <div>
                        <p className="font-medium">{sector.sector}</p>
                        <p className="text-xs text-muted-foreground">
                          {sector.stock_count} actions - {hasWeightedPortfolio ? formatWeightPct(weightSummary.totalWeightPct) : isTechnicalMode ? technicalStats.directionalCount : portfolioEdge?.active_count ?? stats.actionableCount} actives
                        </p>
                      </div>
                    </button>
                  </TableCell>

                  {showPortfolioWeights ? (
                    <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                      <div>{formatWeightPct(weightSummary.totalWeightPct)}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {formatWeightPct(weightSummary.longWeightPct)}L/{formatWeightPct(weightSummary.shortWeightPct)}S
                      </div>
                    </TableCell>
                  ) : null}

                  {shownFamilies.map((family) => (
                    <TableCell key={`${sector.sector}-${family}`} className="px-3 py-2.5">
                      {isTechnicalMode ? (
                        <FamilyCell score={topTechnicalSignal?.per_family?.[family] ?? null} factorDependencies={topTechnicalSignal?.factor_dependencies?.[family]} />
                      ) : scoreSource === "both" ? (
                        <div className="space-y-1">
                          <div>
                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                            <FamilyCell score={resolveSeFamily(sector, family, signalView)} factorDependencies={resolveFactorDependencies(sector, family, signalView)} />
                          </div>
                          <div className="border-t pt-1">
                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                            <FamilyCell score={sector.scores.wfo?.per_family[family] ?? null} />
                          </div>
                        </div>
                      ) : scoreSource === "wfo" ? (
                        <FamilyCell score={sector.scores.wfo?.per_family[family] ?? null} />
                      ) : (
                        <FamilyCell score={resolveSeFamily(sector, family, signalView)} factorDependencies={resolveFactorDependencies(sector, family, signalView)} />
                      )}
                    </TableCell>
                  ))}

                  <TableCell className="px-3 py-2.5">
                    <div className="space-y-1">
                      {hasWeightedPortfolio ? (
                        <WeightedSignalCell summary={weightSummary} />
                      ) : isTechnicalMode ? (
                        <SignalBadge label={topTechnicalSignal?.signal_label ?? "Indisponible"} />
                      ) : (
                        <PortfolioEdgeBadgeCell edge={portfolioEdge} />
                      )}
                      <div className="dashboard-mono text-[10px] text-muted-foreground">
                        {hasWeightedPortfolio
                          ? `${formatScorePct(weightSummary.netSignalPct)} net - ${weightSummary.investedCount}/${sectorStocks.length}`
                          : isTechnicalMode
                          ? `${technicalStats.bullishCount}L/${technicalStats.bearishCount}S - ${technicalStats.directionalCount}/${sectorStocks.length}`
                          : `${portfolioEdge?.long_count ?? 0}L/${portfolioEdge?.short_count ?? 0}S - ${portfolioEdge?.active_count ?? stats.actionableCount}/${sectorStocks.length}`}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="px-3 py-2.5">
                    {hasWeightedPortfolio ? (
                      <WeightedMethodCell summary={weightSummary} />
                    ) : isTechnicalMode ? (
                      <div className="space-y-1">
                        <div className="max-w-[180px] truncate text-[11px] font-semibold" title={topTechnicalSignal?.label ?? ""}>
                          {topTechnicalSignal?.label?.replace("Signal Engine - ", "Engine ").replace("Factor x TA", "FX") ?? "No technical signal"}
                        </div>
                        <div className="dashboard-mono text-[10px] text-muted-foreground">{technicalStats.topStock?.symbol ?? "--"}</div>
                      </div>
                    ) : <PortfolioEdgeMethodCell edge={portfolioEdge} />}
                  </TableCell>
                  <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                    {hasWeightedPortfolio ? (
                      <WeightedExpectedReturnCell summary={weightSummary} />
                    ) : isTechnicalMode ? (
                      <div className="space-y-0.5 text-right">
                        <div>{formatScorePct(topTechnicalSignal?.score_pct)}</div>
                        <div className="text-[10px] text-muted-foreground">{technicalDirectionLabel(topTechnicalSignal?.direction)}</div>
                      </div>
                    ) : <PortfolioEdgeExpectedReturnCell edge={portfolioEdge} fallbackDays={horizonDays} />}
                  </TableCell>
                  {!isTechnicalMode && edgeEnabled ? (
                    <>
                      <TableCell className="px-3 py-2.5 text-right">
                        {hasWeightedPortfolio ? (
                          <div className="dashboard-mono text-[11px]">{formatWeightPct(weightSummary.activeWeightPct)}</div>
                        ) : (
                          <PortfolioEdgeHitRateCell edge={portfolioEdge} />
                        )}
                      </TableCell>
                      <TableCell className="px-3 py-2.5">
                        {hasWeightedPortfolio ? (
                          <div className="dashboard-mono text-[11px] font-semibold">{formatScorePct(weightSummary.netSignalPct)}</div>
                        ) : (
                          <div className="space-y-1">
                            <EdgeBadge triage={portfolioEdgeTriage(portfolioEdge)} />
                            <div className="dashboard-mono text-[10px] text-muted-foreground">n={portfolioEdge?.n ?? 0}</div>
                          </div>
                        )}
                      </TableCell>
                    </>
                  ) : null}
                  <TableCell className="px-2 py-2.5 align-middle" />
                </TableRow>

                {isOpen && (
                  <TableRow key={`${sector.sector}-expanded`}>
                    <TableCell colSpan={columnCount} className="bg-muted/30 p-0">
                      <Collapsible open={isOpen}>
                        <CollapsibleContent forceMount>
                          <div className="px-4 py-3">
                            {sortedStocks.length === 0 ? (
                              <p className="text-sm text-muted-foreground">Aucune action disponible pour ce secteur.</p>
                            ) : (
                              <Table className={cn(tableMinWidthClass, "text-[12px]")}>
                                <TableHeader>
                                  <TableRow className="border-b border-border bg-bg2 hover:bg-bg2">
                                    <TableHead className="h-auto pl-8 pr-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Ticker</TableHead>
                                    <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Nom</TableHead>
                                    {showPortfolioWeights ? (
                                      <>
                                        <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Actions</TableHead>
                                        <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Poids</TableHead>
                                      </>
                                    ) : null}
                                    {shownFamilies.map((family) => (
                                      <TableHead key={`${sector.sector}-nested-${family}`} className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                                        {FAMILY_SHORT_LABELS[family]}
                                      </TableHead>
                                    ))}
                                    <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                                      {isTechnicalMode ? "Direction best" : "Signal"}
                                    </TableHead>
                                    <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                                      {isTechnicalMode ? "Methode technique" : "Methode auto"}
                                    </TableHead>
                                    <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                                      {isTechnicalMode ? "Score technique" : "retour attendu"}
                                    </TableHead>
                                    {!isTechnicalMode && edgeEnabled ? (
                                      <>
                                        <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">%succés</TableHead>
                                        <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Edge</TableHead>
                                      </>
                                    ) : null}
                                    <TableHead className="h-auto w-10 px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground" />
                                  </TableRow>
                                </TableHeader>
                                <TableBody>
                                  {sortedStocks.map((stock) => {
                                    const href = isTechnicalMode ? technicalHref(stock, horizon) : evidenceHref(stock, horizon)
                                    const signal = bestSignalForDisplay(stock)
                                    const technicalSignal = technicalSignalForDisplay(stock)
                                    const shareSymbol = String(stock.symbol ?? "").trim().toUpperCase()
                                    const weightRow = portfolioRowBySymbol[shareSymbol]
                                    const shareValue = portfolioShares?.[shareSymbol] ?? ""

                                    return (
                                      <TableRow key={`${sector.sector}-${stock.symbol}`} className="border-b border-border/70 hover:bg-bg2">
                                        <TableCell className="pl-8 pr-3 py-2.5">
                                          <Link href={href} className="dashboard-mono text-[12px] font-semibold hover:underline">
                                            {stock.symbol}
                                          </Link>
                                        </TableCell>
                                        <TableCell className="max-w-[220px] px-3 py-2.5">
                                          <Link href={href} className="block hover:underline">
                                            <div className="text-[12px] font-medium">{stock.display_name ?? "-"}</div>
                                          </Link>
                                        </TableCell>
                                        {showPortfolioWeights ? (
                                          <>
                                            <TableCell className="px-3 py-2.5 text-right">
                                              <Input
                                                type="number"
                                                min={0}
                                                step={1}
                                                value={String(shareValue)}
                                                onClick={(event) => event.stopPropagation()}
                                                onChange={(event) => onPortfolioShareChange?.(shareSymbol, event.currentTarget.value)}
                                                className="ml-auto h-7 w-24 border-border bg-background px-2 text-right dashboard-mono text-[12px]"
                                                aria-label={`Actions ${stock.symbol}`}
                                              />
                                            </TableCell>
                                            <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                                              <div>{weightRow ? formatWeightPct(weightRow.weightPct) : "--"}</div>
                                              <div className="text-[10px] text-muted-foreground">
                                                {weightRow?.price == null && weightRow?.shares > 0
                                                  ? "Prix absent"
                                                  : formatMoneyCompact(weightRow?.marketValue)}
                                              </div>
                                            </TableCell>
                                          </>
                                        ) : null}
                                        {shownFamilies.map((family) => (
                                          <TableCell key={`${stock.symbol}-nested-${family}`} className="px-3 py-2.5">
                                            {isTechnicalMode ? (
                                              <FamilyCell score={technicalSignal?.per_family?.[family] ?? null} factorDependencies={technicalSignal?.factor_dependencies?.[family]} />
                                            ) : scoreSource === "both" ? (
                                              <div className="space-y-1">
                                                <div>
                                                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                                                  <FamilyCell score={resolveSeFamily(stock, family, signalView)} factorDependencies={resolveFactorDependencies(stock, family, signalView)} />
                                                </div>
                                                <div className="border-t pt-1">
                                                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                                                  <FamilyCell score={stock.scores.wfo?.per_family[family] ?? null} />
                                                </div>
                                              </div>
                                            ) : scoreSource === "wfo" ? (
                                              <FamilyCell score={stock.scores.wfo?.per_family[family] ?? null} />
                                            ) : (
                                              <FamilyCell score={resolveSeFamily(stock, family, signalView)} factorDependencies={resolveFactorDependencies(stock, family, signalView)} />
                                            )}
                                          </TableCell>
                                        ))}
                                        <TableCell className="px-3 py-2.5">
                                          {isTechnicalMode ? <SignalBadge label={technicalSignal?.signal_label ?? "Indisponible"} /> : <BestSignalBadgeCell signal={signal} />}
                                        </TableCell>
                                        <TableCell className="px-3 py-2.5">
                                          {isTechnicalMode ? (
                                            <div className="space-y-1">
                                              <div className="max-w-[180px] truncate text-[11px] font-semibold" title={technicalSignal?.label ?? ""}>
                                                {technicalSignal?.label?.replace("Signal Engine - ", "Engine ").replace("Factor x TA", "FX") ?? "No technical signal"}
                                              </div>
                                              <div className="dashboard-mono text-[10px] text-muted-foreground">{displayVariantLabel(technicalSignal?.variant)}</div>
                                            </div>
                                          ) : <BestSignalMethodCell signal={signal} />}
                                        </TableCell>
                                        <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                                          <Link href={href} className="block hover:text-foreground hover:underline">
                                            {isTechnicalMode ? (
                                              <div className="space-y-0.5 text-right">
                                                <div>{formatScorePct(technicalSignal?.score_pct)}</div>
                                                <div className="text-[10px] text-muted-foreground">{technicalDirectionLabel(technicalSignal?.direction)}</div>
                                              </div>
                                            ) : <BestSignalExpectedReturnCell signal={signal} fallbackDays={horizonDays} />}
                                          </Link>
                                        </TableCell>
                                        {!isTechnicalMode && edgeEnabled ? (
                                          <>
                                            <TableCell className="px-3 py-2.5 text-right"><BestSignalHitRateCell signal={signal} /></TableCell>
                                            <TableCell className="px-3 py-2.5"><EdgeBadge triage={bestSignalTriage(signal)} /></TableCell>
                                          </>
                                        ) : null}
                                        <TableCell className="px-2 py-2.5 align-middle">
                                          <Link
                                            href={href}
                                            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-muted-foreground transition hover:border-border hover:bg-muted/30 hover:text-foreground"
                                            aria-label={`Voir la preuve OOS ${stock.symbol}`}
                                          >
                                            <ArrowRight className="h-3.5 w-3.5" />
                                          </Link>
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
    </div>
  )
}
