"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { ArrowRight, ChevronDown, ChevronRight, Database, Pencil, Plus, Trash2 } from "lucide-react"
import type {
  DashboardBreadth,
  DashboardCustomIndexComponent,
  DashboardCustomIndexDefinition,
  DashboardDisplayMode,
  DashboardPortfolioEdge,
  DashboardScoreSource,
  DashboardIndex,
  DashboardStock,
  DashboardTechnicalDirectionMode,
  FamilyScore,
  Horizon,
  SignalEngineScores,
} from "@/lib/dashboard-types"
import { FAMILY_LABELS, FAMILY_ORDER, FAMILY_SHORT_LABELS, aggregateScoreLabel, familyScoreLabel } from "@/lib/dashboard-constants"
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
  compareTechnicalSignalStocks,
  displayVariantLabel,
  portfolioEdgeTriage,
  summarizeBestSignals,
  summarizeTechnicalSignals,
  technicalSignalForDisplay,
} from "./best-signal-cells"
import { SignalBadge } from "./signal-badge"
import { buildDashboardIndexPayload, normalizeDashboardIndexName } from "./index-tab-utils.mjs"
import {
  buildPortfolioWeightRows,
  portfolioRowsBySymbol,
  stockPriceForWeight,
  summarizeWeightRows,
} from "./sector-portfolio-utils.mjs"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible"
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import { cn } from "@/lib/utils"

interface IndexTabProps {
  baseIndex: DashboardIndex
  baseDefinition?: DashboardCustomIndexDefinition
  stocks: DashboardStock[]
  customDefinitions: DashboardCustomIndexDefinition[]
  readOnly: boolean
  actionError?: string | null
  scoreSource?: DashboardScoreSource
  displayMode?: DashboardDisplayMode
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  horizon: Horizon
  horizonDays: number
  edgeEnabled?: boolean
  technicalDirectionMode?: DashboardTechnicalDirectionMode
  visibleFamilies?: Partial<Record<FamilyKey, boolean>>
  availableShares?: Record<string, number>
  onCreate?: (payload: { name: string; components: DashboardCustomIndexComponent[] }) => Promise<void>
  onUpdate?: (id: string, payload: { name: string; components: DashboardCustomIndexComponent[] }) => Promise<void>
  onDelete?: (id: string) => Promise<void>
}

type FamilyKey = (typeof FAMILY_ORDER)[number]

interface IndexMemberSourceScore {
  signal_label: string | null
  aggregate_score_pct: number | null
  per_family: Record<string, FamilyScore>
}

interface IndexMember {
  symbol: string
  display_name: string | null
  stock: DashboardStock | null
  shares: number | null
  price: number | null
  marketValue: number
  weightFraction: number
  weightPct: number
  scores: {
    signal_engine: IndexMemberSourceScore
    wfo: IndexMemberSourceScore | null
  }
}

interface IndexScoreBlock {
  aggregate_signal_label: string | null
  aggregate_score_pct: number | null
  per_family: Record<string, FamilyScore>
  breadth: DashboardBreadth
}

interface ComputedIndex {
  id: string
  name: string
  stock_count: number
  scores: {
    signal_engine: IndexScoreBlock
    wfo: IndexScoreBlock | null
  }
  bestStats: ReturnType<typeof summarizeBestSignals>
  technicalStats: ReturnType<typeof summarizeTechnicalSignals>
  weightSummary: ReturnType<typeof summarizeWeightRows> | null
  portfolioEdge: DashboardPortfolioEdge | null
  members: IndexMember[]
  totalMarketValue: number
  isWeightedComplete: boolean
  hasComponentWeights: boolean
  editable: boolean
}

type PortfolioWeightRow = ReturnType<typeof buildPortfolioWeightRows>["rows"][number]

const MASI_KEY = "__masi__"
type SignalView = NonNullable<IndexTabProps["signalView"]>

function normalizeSymbols(symbols: string[]): string[] {
  const seen = new Set<string>()
  const normalized: string[] = []
  for (const raw of symbols) {
    const token = String(raw ?? "").trim().toUpperCase()
    if (!token || seen.has(token)) continue
    seen.add(token)
    normalized.push(token)
  }
  return normalized
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  const sum = values.reduce((acc, value) => acc + value, 0)
  return sum / values.length
}

function round2(value: number): number {
  return Math.round(value * 100) / 100
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

function shareInputMessage(symbols: string[], shareInputs: Record<string, string>, missingPrices: string[]) {
  if (symbols.length === 0) return "Selectionnez au moins un composant."
  const missingShares = symbols.filter((symbol) => {
    const value = Number(String(shareInputs[symbol] ?? "").replace(",", "."))
    return !Number.isInteger(value) || value <= 0
  })
  if (missingShares.length > 0) return `Actions entieres requises: ${missingShares.join(", ")}.`
  if (missingPrices.length > 0) return `Prix indisponible: ${missingPrices.join(", ")}.`
  return null
}

function normalizeComponentShares(definition: DashboardCustomIndexDefinition): Record<string, number> {
  const out: Record<string, number> = {}
  const raw = definition.component_shares ?? {}
  for (const [symbolRaw, sharesRaw] of Object.entries(raw)) {
    const symbol = String(symbolRaw ?? "").trim().toUpperCase()
    const shares = Number(sharesRaw)
    if (!symbol || !Number.isInteger(shares) || shares <= 0) continue
    out[symbol] = shares
  }
  for (const component of definition.components ?? []) {
    const symbol = String(component.symbol ?? "").trim().toUpperCase()
    const shares = Number(component.shares)
    if (!symbol || !Number.isInteger(shares) || shares <= 0) continue
    out[symbol] = shares
  }
  return out
}

function weightedAverageMemberValue(
  members: IndexMember[],
  getValue: (member: IndexMember) => number | null | undefined,
  useWeights: boolean,
): number | null {
  if (!useWeights) {
    return average(
      members
        .map((member) => getValue(member))
        .filter((value): value is number => typeof value === "number"),
    )
  }

  let weightedSum = 0
  let totalWeight = 0
  for (const member of members) {
    const value = getValue(member)
    if (typeof value !== "number" || !Number.isFinite(value) || member.weightFraction <= 0) continue
    weightedSum += value * member.weightFraction
    totalWeight += member.weightFraction
  }
  return totalWeight > 0 ? weightedSum / totalWeight : null
}

function breadthFromLabels(labels: Array<string | null>): DashboardBreadth {
  let achat = 0
  let neutre = 0
  let vente = 0
  let indisponible = 0

  for (const label of labels) {
    if (!label) {
      indisponible += 1
      continue
    }
    if (label.includes("Achat")) {
      achat += 1
      continue
    }
    if (label.includes("Vente")) {
      vente += 1
      continue
    }
    neutre += 1
  }

  return { achat, neutre, vente, indisponible }
}

function computeScoreBlock(
  members: IndexMember[],
  source: "signal_engine" | "wfo",
  useWeights = false,
): IndexScoreBlock | null {
  const aggregateScore = weightedAverageMemberValue(
    members,
    (member) => member.scores[source]?.aggregate_score_pct,
    useWeights,
  )
  const perFamily: Record<string, FamilyScore> = {}

  for (const family of FAMILY_ORDER) {
    const familyAvg = weightedAverageMemberValue(
      members,
      (member) => member.scores[source]?.per_family[family]?.score_pct,
      useWeights,
    )
    if (familyAvg == null) continue

    perFamily[family] = {
      score_pct: round2(familyAvg),
      label: familyScoreLabel(family, familyAvg),
    }
  }

  const labels = members.map((member) => member.scores[source]?.signal_label ?? null)

  return {
    aggregate_signal_label: aggregateScore == null ? null : aggregateScoreLabel(aggregateScore),
    aggregate_score_pct: aggregateScore == null ? null : round2(aggregateScore),
    per_family: perFamily,
    breadth: breadthFromLabels(labels),
  }
}

function emptyIndexScoreBlock(total: number): IndexScoreBlock {
  return {
    aggregate_signal_label: null,
    aggregate_score_pct: null,
    per_family: {},
    breadth: { achat: 0, neutre: 0, vente: 0, indisponible: total },
  }
}

function resolveSeAggregateScore(item: SignalEngineScores, signalView: SignalView): number | null {
  if (signalView === "factor_x_ta") return item.factor_x_ta_aggregate_score_pct ?? null
  if (signalView === "expanded") return item.expanded_aggregate_score_pct ?? item.aggregate_score_pct
  return item.aggregate_score_pct
}

function resolveSeAggregateLabel(item: SignalEngineScores, signalView: SignalView): string | null {
  if (signalView === "factor_x_ta") return item.factor_x_ta_aggregate_signal_label ?? null
  if (signalView === "expanded") return item.expanded_aggregate_signal_label ?? item.aggregate_signal_label
  return item.aggregate_signal_label
}

function resolveSePerFamily(item: SignalEngineScores, signalView: SignalView): Record<string, FamilyScore> {
  if (signalView === "factor_x_ta") return item.factor_x_ta_per_family ?? {}
  if (signalView === "expanded") return item.expanded_per_family ?? item.per_family
  return item.per_family
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

function technicalHref(stock: DashboardStock, horizon: Horizon, mode: DashboardTechnicalDirectionMode) {
  const signal = technicalSignalForDisplay(stock, mode)
  const variant = mode === "classic" ? "legacy_ta_simple" : signal?.variant ?? "expanded_ta_simple"
  return signalEvidenceUrl({
    symbol: stock.symbol,
    horizon,
    view: variant,
    source: signal?.source ?? "auto",
    evidenceVariant: mode === "classic" ? undefined : signal?.variant,
    scope: signal?.scope,
    scopeKey: signal?.scope_key,
    tab: "technique",
  })
}

function technicalModeShortLabel(mode: DashboardTechnicalDirectionMode) {
  return mode === "classic" ? "classic" : "best"
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

function compareIndexMembers(left: IndexMember, right: IndexMember) {
  if (left.stock && right.stock) return compareBestSignalStocks(left.stock, right.stock)
  if (left.stock) return -1
  if (right.stock) return 1
  return left.symbol.localeCompare(right.symbol)
}

function BreadthBar({
  breadth,
  total,
}: {
  breadth: DashboardBreadth
  total: number
}) {
  const pctAchat = total > 0 ? (breadth.achat / total) * 100 : 0
  const pctNeutre = total > 0 ? (breadth.neutre / total) * 100 : 0
  const pctVente = total > 0 ? (breadth.vente / total) * 100 : 0
  const pctIndisponible = total > 0 ? (breadth.indisponible / total) * 100 : 0

  return (
    <div className="space-y-1">
      <div className="flex h-3 w-full overflow-hidden rounded-full">
        {pctAchat > 0 && <div className="bg-emerald-500" style={{ width: `${pctAchat}%` }} />}
        {pctNeutre > 0 && <div className="bg-zinc-400" style={{ width: `${pctNeutre}%` }} />}
        {pctVente > 0 && <div className="bg-red-500" style={{ width: `${pctVente}%` }} />}
        {pctIndisponible > 0 && <div className="bg-slate-300" style={{ width: `${pctIndisponible}%` }} />}
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span>{breadth.achat} Achat</span>
        <span>{breadth.neutre} Neutre</span>
        <span>{breadth.vente} Vente</span>
        {breadth.indisponible > 0 && <span>{breadth.indisponible} Indisponible</span>}
      </div>
    </div>
  )
}

function renderIndexHeaderSignal(index: ComputedIndex, displayMode: DashboardDisplayMode) {
  if ((index.editable || index.hasComponentWeights) && !index.isWeightedComplete) {
    return (
      <div className="space-y-1 text-right">
        <div className="text-[11px] font-semibold text-amber-700">Poids incomplets</div>
        <div className="dashboard-mono text-[10px] text-muted-foreground">actions/prix requis</div>
      </div>
    )
  }

  if (displayMode === "technical_directions") {
    return (
      <div className="space-y-1 text-right">
        <SignalBadge label={index.technicalStats.topSignal?.signal_label ?? "Indisponible"} />
        <div className="dashboard-mono text-[10px] text-muted-foreground">
          {index.technicalStats.topStock?.symbol ?? "--"} - {index.technicalStats.directionalCount}/{index.stock_count} directions
        </div>
      </div>
    )
  }
  return (
    <div className="space-y-1 text-right">
      <PortfolioEdgeBadgeCell edge={index.portfolioEdge} />
      <div className="dashboard-mono text-[10px] text-muted-foreground">
        {index.portfolioEdge?.active_count ?? index.bestStats.actionableCount}/{index.stock_count} actives
      </div>
    </div>
  )
}

function IndexSignalOverview({
  index,
  horizonDays,
  edgeEnabled,
  displayMode,
  technicalDirectionMode,
}: {
  index: ComputedIndex
  horizonDays: number
  edgeEnabled: boolean
  displayMode: DashboardDisplayMode
  technicalDirectionMode: DashboardTechnicalDirectionMode
}) {
  const portfolioEdge = index.portfolioEdge
  const technicalSignal = index.technicalStats.topSignal
  const isTechnicalMode = displayMode === "technical_directions"

  if ((index.editable || index.hasComponentWeights) && !index.isWeightedComplete) {
    return (
      <div className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950">
        Renseignez un nombre entier d'actions et un prix disponible pour chaque composant afin de calculer les poids et les scores ponderes.
      </div>
    )
  }

  return (
    <div className={cn("grid gap-2", !isTechnicalMode && edgeEnabled ? "md:grid-cols-5" : "md:grid-cols-3")}>
      <div className="dashboard-field px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{isTechnicalMode ? `Direction ${technicalModeShortLabel(technicalDirectionMode)}` : "Portefeuille"}</div>
        <div className="mt-1">
          {isTechnicalMode ? <SignalBadge label={technicalSignal?.signal_label ?? "Indisponible"} /> : <PortfolioEdgeBadgeCell edge={portfolioEdge} />}
          <div className="dashboard-mono mt-1 text-[10px] text-muted-foreground">
            {isTechnicalMode
              ? `${index.technicalStats.bullishCount}L/${index.technicalStats.bearishCount}S - ${index.technicalStats.directionalCount}/${index.stock_count}`
              : `${portfolioEdge?.long_count ?? 0}L/${portfolioEdge?.short_count ?? 0}S - ${portfolioEdge?.active_count ?? index.bestStats.actionableCount}/${index.stock_count}`}
          </div>
        </div>
      </div>
      <div className="dashboard-field px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{isTechnicalMode ? "Methode technique" : "Methode auto"}</div>
        <div className="mt-1">
          {isTechnicalMode ? (
            <div className="space-y-1">
              <div className="max-w-[180px] truncate text-[11px] font-semibold" title={technicalSignal?.label ?? ""}>
                {technicalSignal?.label?.replace("Signal Engine - ", "Engine ").replace("Factor x TA", "FX") ?? "No technical signal"}
              </div>
              <div className="dashboard-mono text-[10px] text-muted-foreground">
                {technicalDirectionMode === "classic" ? "Fixed classic" : index.technicalStats.topStock?.symbol ?? "--"}
              </div>
            </div>
          ) : <PortfolioEdgeMethodCell edge={portfolioEdge} />}
        </div>
      </div>
      <div className="dashboard-field px-3 py-2">
        <div className="text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{isTechnicalMode ? "Score technique" : "retour attendu"}</div>
        <div className="mt-1">
          {isTechnicalMode ? (
            <div className="space-y-0.5 text-right">
              <div>{formatScorePct(technicalSignal?.score_pct)}</div>
              <div className="text-[10px] text-muted-foreground">{technicalDirectionLabel(technicalSignal?.direction)}</div>
            </div>
          ) : <PortfolioEdgeExpectedReturnCell edge={portfolioEdge} fallbackDays={horizonDays} />}
        </div>
      </div>
      {!isTechnicalMode && edgeEnabled ? (
        <>
          <div className="dashboard-field px-3 py-2">
            <div className="text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">%succés port.</div>
            <div className="mt-1">
              <PortfolioEdgeHitRateCell edge={portfolioEdge} />
            </div>
          </div>
          <div className="dashboard-field px-3 py-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Edge</div>
            <div className="mt-1 space-y-1">
              <EdgeBadge triage={portfolioEdgeTriage(portfolioEdge)} />
              <div className="dashboard-mono text-[10px] text-muted-foreground">n={portfolioEdge?.n ?? 0}</div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

export function IndexTab({
  baseIndex,
  baseDefinition,
  stocks,
  customDefinitions,
  readOnly,
  actionError,
  scoreSource = "both",
  onCreate,
  onUpdate,
  onDelete,
  signalView = "expanded",
  displayMode = "trade_opportunities",
  horizon,
  horizonDays,
  edgeEnabled = true,
  technicalDirectionMode = "best",
  visibleFamilies,
  availableShares,
}: IndexTabProps) {
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [createName, setCreateName] = useState("")
  const [createSearch, setCreateSearch] = useState("")
  const [createSymbols, setCreateSymbols] = useState<string[]>([])
  const [createShareInputs, setCreateShareInputs] = useState<Record<string, string>>({})
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState("")
  const [editSearch, setEditSearch] = useState("")
  const [editSymbols, setEditSymbols] = useState<string[]>([])
  const [editShareInputs, setEditShareInputs] = useState<Record<string, string>>({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const isTechnicalMode = displayMode === "technical_directions"

  const createNameTrimmed = normalizeDashboardIndexName(createName)
  const editNameTrimmed = normalizeDashboardIndexName(editName)
  const createNameInvalid = showCreate && createNameTrimmed.length === 0
  const editNameInvalid = Boolean(editingId) && editNameTrimmed.length === 0
  const createPayload = buildDashboardIndexPayload(
    createName,
    createSymbols.map((symbol) => ({ symbol, shares: createShareInputs[symbol] })),
  )
  const editPayload = buildDashboardIndexPayload(
    editName,
    editSymbols.map((symbol) => ({ symbol, shares: editShareInputs[symbol] })),
  )
  const shownFamilies = useMemo(
    () => isTechnicalMode ? FAMILY_ORDER.filter((family) => visibleFamilies?.[family] !== false) : [],
    [isTechnicalMode, visibleFamilies],
  )

  const stockCatalog = useMemo(
    () =>
      [...stocks]
        .map((stock) => ({
          symbol: stock.symbol,
          display_name: stock.display_name,
        }))
        .sort((left, right) => left.symbol.localeCompare(right.symbol)),
    [stocks],
  )

  const stockBySymbol = useMemo(
    () =>
      new Map(
        stocks.map((stock) => [
          stock.symbol.toUpperCase(),
          stock,
        ]),
      ),
    [stocks],
  )

  const availableShareSymbols = useMemo(
    () =>
      stockCatalog
        .map((stock) => stock.symbol)
        .filter((symbol) => {
          const shares = Number(availableShares?.[symbol])
          return Number.isInteger(shares) && shares > 0
        }),
    [availableShares, stockCatalog],
  )

  const createMissingPriceSymbols = useMemo(
    () => createSymbols.filter((symbol) => {
      const stock = stockBySymbol.get(symbol)
      const price = stock ? stockPriceForWeight(stock) : null
      return price == null || price <= 0
    }),
    [createSymbols, stockBySymbol],
  )
  const editMissingPriceSymbols = useMemo(
    () => editSymbols.filter((symbol) => {
      const stock = stockBySymbol.get(symbol)
      const price = stock ? stockPriceForWeight(stock) : null
      return price == null || price <= 0
    }),
    [editSymbols, stockBySymbol],
  )
  const createShareMessage = shareInputMessage(createSymbols, createShareInputs, createMissingPriceSymbols)
  const editShareMessage = shareInputMessage(editSymbols, editShareInputs, editMissingPriceSymbols)
  const canSubmitCreate = Boolean(onCreate) && !isSubmitting && createPayload !== null && createShareMessage === null
  const canSubmitEdit = Boolean(editingId) && Boolean(onUpdate) && !isSubmitting && editPayload !== null && editShareMessage === null

  const computedIndices = useMemo<ComputedIndex[]>(() => {
    const makeMember = (
      stock: DashboardStock | undefined,
      symbolFallback?: string,
      shares: number | null = null,
    ): IndexMember => {
      const price = stock ? stockPriceForWeight(stock) : null
      const marketValue = shares != null && shares > 0 && price != null && price > 0 ? shares * price : 0
      return {
        symbol: stock?.symbol ?? symbolFallback ?? "",
        display_name: stock?.display_name ?? null,
        stock: stock ?? null,
        shares,
        price,
        marketValue,
        weightFraction: 0,
        weightPct: 0,
        scores: {
          signal_engine: {
            signal_label: stock ? resolveSeAggregateLabel(stock.scores.signal_engine, signalView) : null,
            aggregate_score_pct: stock ? resolveSeAggregateScore(stock.scores.signal_engine, signalView) : null,
            per_family: stock ? resolveSePerFamily(stock.scores.signal_engine, signalView) : {},
          },
          wfo: stock?.scores.wfo
            ? {
                signal_label: stock.scores.wfo.aggregate_signal_label,
                aggregate_score_pct: stock.scores.wfo.aggregate_score_pct,
                per_family: stock.scores.wfo.per_family,
              }
            : null,
        },
      }
    }

    const makeWeightedIndex = (
      definition: DashboardCustomIndexDefinition,
      portfolioEdge: DashboardPortfolioEdge | null,
    ): ComputedIndex => {
      const symbols = normalizeSymbols(definition.symbols)
      const componentShares = normalizeComponentShares(definition)
      const hasComponentWeights = Object.keys(componentShares).length > 0
      const rawMembers = symbols.map((symbol) => makeMember(stockBySymbol.get(symbol), symbol, componentShares[symbol] ?? null))
      const totalMarketValue = rawMembers.reduce((sum, member) => sum + member.marketValue, 0)
      const hasCompleteWeights =
        Boolean(definition.is_weighted_complete) &&
        symbols.length > 0 &&
        rawMembers.every((member) => member.shares != null && member.shares > 0 && member.price != null && member.price > 0) &&
        totalMarketValue > 0
      const hasUsableWeights =
        Boolean(definition.is_weighted_complete) &&
        symbols.length > 0 &&
        totalMarketValue > 0 &&
        rawMembers.some((member) => member.shares != null && member.shares > 0 && member.price != null && member.price > 0)
      const requireCompleteWeights = definition.editable !== false
      const isWeightedComplete = requireCompleteWeights ? hasCompleteWeights : hasUsableWeights
      const members = rawMembers.map((member) => {
        const weightFraction = isWeightedComplete && totalMarketValue > 0 ? member.marketValue / totalMarketValue : 0
        return {
          ...member,
          weightFraction,
          weightPct: weightFraction * 100,
        }
      })
      const memberStocks = members
        .map((member) => member.stock)
        .filter((stock): stock is DashboardStock => Boolean(stock))
      const weightRows = isWeightedComplete
        ? buildPortfolioWeightRows(memberStocks, componentShares, { displayMode, technicalDirectionMode }).rows
        : []

      return {
        id: definition.id,
        name: definition.name,
        stock_count: symbols.length,
        scores: {
          signal_engine:
            isWeightedComplete
              ? computeScoreBlock(members, "signal_engine", true) ?? emptyIndexScoreBlock(symbols.length)
              : emptyIndexScoreBlock(symbols.length),
          wfo: isWeightedComplete ? computeScoreBlock(members, "wfo", true) : null,
        },
        bestStats: summarizeBestSignals(memberStocks),
        technicalStats: summarizeTechnicalSignals(memberStocks, technicalDirectionMode),
        weightSummary: isWeightedComplete ? summarizeWeightRows(weightRows) : null,
        portfolioEdge: isWeightedComplete ? portfolioEdge : null,
        members,
        totalMarketValue,
        isWeightedComplete,
        hasComponentWeights,
        editable: definition.editable ?? true,
      }
    }

    const base: ComputedIndex = baseDefinition
      ? {
          ...makeWeightedIndex(
            {
              ...baseDefinition,
              id: MASI_KEY,
              name: baseDefinition.name || baseIndex.name || "MASI",
              editable: false,
            },
            baseDefinition.portfolio_edge ?? baseIndex.portfolio_edge ?? null,
          ),
          id: MASI_KEY,
          editable: false,
        }
      : (() => {
          const masiMembers = stocks.map((stock) => makeMember(stock))

          return {
            id: MASI_KEY,
            name: baseIndex.name || "MASI",
            stock_count: stocks.length,
            scores: {
              signal_engine:
                computeScoreBlock(masiMembers, "signal_engine") ?? emptyIndexScoreBlock(stocks.length),
              wfo: computeScoreBlock(masiMembers, "wfo"),
            },
            bestStats: summarizeBestSignals(stocks),
            technicalStats: summarizeTechnicalSignals(stocks, technicalDirectionMode),
            weightSummary: null,
            portfolioEdge: baseIndex.portfolio_edge ?? null,
            members: masiMembers,
            totalMarketValue: 0,
            isWeightedComplete: true,
            hasComponentWeights: false,
            editable: false,
          }
        })()

    const custom = customDefinitions.map((definition) => {
      return makeWeightedIndex(definition, definition.portfolio_edge ?? null)
    })

    return [base, ...custom]
  }, [baseDefinition, baseIndex.name, baseIndex.portfolio_edge, customDefinitions, displayMode, signalView, stockBySymbol, stocks, technicalDirectionMode])

  function symbolOptions(query: string) {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return stockCatalog
    return stockCatalog.filter(
      (stock) =>
        stock.symbol.toLowerCase().includes(normalized) ||
        (stock.display_name ?? "").toLowerCase().includes(normalized),
    )
  }

  function toggleSymbol(
    symbols: string[],
    symbol: string,
    setSymbols: (next: string[]) => void,
    setShareInputs: (updater: (previous: Record<string, string>) => Record<string, string>) => void,
  ) {
    if (symbols.includes(symbol)) {
      setSymbols(symbols.filter((item) => item !== symbol))
      setShareInputs((previous) => {
        const next = { ...previous }
        delete next[symbol]
        return next
      })
      return
    }
    setSymbols([...symbols, symbol].sort())
    setShareInputs((previous) => ({ ...previous, [symbol]: previous[symbol] ?? "" }))
  }

  function applyAvailableShares(
    symbols: string[],
    setSymbols: (next: string[]) => void,
    setShareInputs: (updater: (previous: Record<string, string>) => Record<string, string>) => void,
  ) {
    const nextSymbols = symbols.length > 0
      ? normalizeSymbols(symbols.filter((symbol) => Number(availableShares?.[symbol]) > 0))
      : availableShareSymbols
    if (nextSymbols.length === 0) return
    setSymbols(nextSymbols)
    setShareInputs((previous) => {
      const next: Record<string, string> = {}
      for (const symbol of nextSymbols) {
        const shares = Number(availableShares?.[symbol])
        next[symbol] = Number.isInteger(shares) && shares > 0 ? String(shares) : previous[symbol] ?? ""
      }
      return next
    })
  }

  function componentPreviewRows(symbols: string[], shareInputs: Record<string, string>): Record<string, PortfolioWeightRow> {
    const selectedStocks = symbols
      .map((symbol) => stockBySymbol.get(symbol))
      .filter((stock): stock is DashboardStock => Boolean(stock))
    return portfolioRowsBySymbol(
      buildPortfolioWeightRows(selectedStocks, shareInputs, { displayMode, technicalDirectionMode }).rows,
    ) as Record<string, PortfolioWeightRow>
  }

  function renderComponentShareEditor({
    symbols,
    shareInputs,
    validationMessage,
    onShareChange,
  }: {
    symbols: string[]
    shareInputs: Record<string, string>
    validationMessage: string | null
    onShareChange: (symbol: string, value: string) => void
  }) {
    if (symbols.length === 0) {
      return (
        <div className="rounded-md border border-dashed px-3 py-3 text-sm text-muted-foreground">
          Aucun composant selectionne.
        </div>
      )
    }

    const previewRows = componentPreviewRows(symbols, shareInputs)
    const totalMarketValue = Object.values(previewRows).reduce((sum, row) => sum + (Number(row.marketValue) || 0), 0)

    return (
      <div className="space-y-2">
        <div className="overflow-x-auto rounded-md border">
          <Table className="min-w-[680px] text-[12px]">
            <TableHeader>
              <TableRow className="border-b border-border bg-bg2 hover:bg-bg2">
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Ticker</TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Nom</TableHead>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Actions</TableHead>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Prix</TableHead>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Poids</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...symbols].sort().map((symbol) => {
                const stock = stockBySymbol.get(symbol)
                const preview = previewRows[symbol]
                const price = stock ? stockPriceForWeight(stock) : null
                return (
                  <TableRow key={`component-share-${symbol}`} className="border-b border-border/70 hover:bg-bg2">
                    <TableCell className="dashboard-mono px-3 py-2.5 font-semibold">{symbol}</TableCell>
                    <TableCell className="max-w-[220px] px-3 py-2.5">
                      <div className="truncate text-[12px] font-medium">{stock?.display_name ?? "-"}</div>
                    </TableCell>
                    <TableCell className="px-3 py-2.5 text-right">
                      <Input
                        className="ml-auto h-8 w-24 text-right"
                        inputMode="numeric"
                        min={1}
                        step={1}
                        type="number"
                        value={shareInputs[symbol] ?? ""}
                        onChange={(event) => onShareChange(symbol, event.target.value)}
                      />
                    </TableCell>
                    <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">{formatMoneyCompact(price)}</TableCell>
                    <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                      <div>{formatWeightPct(preview?.weightPct)}</div>
                      <div className="text-[10px] text-muted-foreground">{formatMoneyCompact(preview?.marketValue)}</div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className={validationMessage ? "text-destructive" : "text-muted-foreground"}>
            {validationMessage ?? "Composants prets pour le calcul des poids."}
          </span>
          <span className="dashboard-mono text-muted-foreground">Valeur totale {formatMoneyCompact(totalMarketValue)}</span>
        </div>
      </div>
    )
  }

  async function submitCreate() {
    if (!onCreate || isSubmitting || createPayload == null) return
    setIsSubmitting(true)
    try {
      await onCreate(createPayload)
      setCreateName("")
      setCreateSearch("")
      setCreateSymbols([])
      setCreateShareInputs({})
      setShowCreate(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  function startEdit(index: ComputedIndex) {
    setEditingId(index.id)
    setEditName(index.name)
    setEditSearch("")
    setEditSymbols(index.members.map((member) => member.symbol))
    setEditShareInputs(
      Object.fromEntries(
        index.members.map((member) => [member.symbol, member.shares != null ? String(member.shares) : ""]),
      ),
    )
  }

  async function submitEdit() {
    if (!editingId || !onUpdate || isSubmitting || editPayload == null) return
    setIsSubmitting(true)
    try {
      await onUpdate(editingId, editPayload)
      setEditingId(null)
      setEditName("")
      setEditSearch("")
      setEditSymbols([])
      setEditShareInputs({})
    } finally {
      setIsSubmitting(false)
    }
  }

  async function submitDelete(index: ComputedIndex) {
    if (!onDelete || isSubmitting) return
    const confirmed = window.confirm(`Supprimer l'indice "${index.name}" ?`)
    if (!confirmed) return
    setIsSubmitting(true)
    try {
      await onDelete(index.id)
      if (openKey === index.id) {
        setOpenKey(null)
      }
      if (editingId === index.id) {
        setEditingId(null)
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-4">
      {!readOnly && (
        <Card className="dashboard-panel">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <CardTitle className="text-base">Indices personnalises</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Creez des indices a partir d'une liste manuelle d'actions et de quantites.
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                variant={showCreate ? "secondary" : "default"}
                onClick={() => setShowCreate((prev) => !prev)}
              >
                <Plus className="h-4 w-4" />
                Nouvel indice
              </Button>
            </div>
          </CardHeader>
          {showCreate && (
            <CardContent className="space-y-3">
              <Input
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                placeholder="Nom de l'indice"
                aria-invalid={createNameInvalid}
              />
              {createNameInvalid && (
                <p className="text-xs text-destructive">Le nom de l'indice ne peut pas etre vide.</p>
              )}
              <Input
                value={createSearch}
                onChange={(event) => setCreateSearch(event.target.value)}
                placeholder="Rechercher un symbole"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={availableShareSymbols.length === 0}
                  onClick={() => applyAvailableShares([], setCreateSymbols, setCreateShareInputs)}
                >
                  <Database className="h-4 w-4" />
                  Toutes les actions disponibles
                </Button>
                <span className="text-xs text-muted-foreground">{availableShareSymbols.length} quantite(s) disponible(s)</span>
              </div>
              <div className="max-h-52 space-y-2 overflow-y-auto rounded-md border p-3">
                {symbolOptions(createSearch).map((stock) => (
                  <label key={`create-${stock.symbol}`} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={createSymbols.includes(stock.symbol)}
                      onChange={() => toggleSymbol(createSymbols, stock.symbol, setCreateSymbols, setCreateShareInputs)}
                    />
                    <span className="font-mono">{stock.symbol}</span>
                    <span className="text-muted-foreground">{stock.display_name ?? "-"}</span>
                  </label>
                ))}
              </div>
              {renderComponentShareEditor({
                symbols: createSymbols,
                shareInputs: createShareInputs,
                validationMessage: createShareMessage,
                onShareChange: (symbol, value) => {
                  setCreateShareInputs((previous) => ({ ...previous, [symbol]: value }))
                },
              })}
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={submitCreate}
                  disabled={!canSubmitCreate}
                >
                  Enregistrer
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setShowCreate(false)
                    setCreateName("")
                    setCreateSearch("")
                    setCreateSymbols([])
                    setCreateShareInputs({})
                  }}
                >
                  Annuler
                </Button>
                <span className="text-xs text-muted-foreground">{createSymbols.length} symbole(s) selectionne(s)</span>
              </div>
            </CardContent>
          )}
        </Card>
      )}

      {actionError && (
        <Card className="border-destructive">
          <CardContent className="py-3 text-sm text-destructive">{actionError}</CardContent>
        </Card>
      )}

      {computedIndices.map((index) => {
        const isOpen = openKey === index.id
        const isEditing = editingId === index.id
        const sortedMembers = [...index.members].sort((left, right) => {
          if (isTechnicalMode && left.stock && right.stock) {
            return compareTechnicalSignalStocks(left.stock, right.stock, technicalDirectionMode)
          }
          return compareIndexMembers(left, right)
        })
        const showComponentWeights = index.editable || index.hasComponentWeights
        const memberColumnCount = 2 + (showComponentWeights ? 3 : 0) + shownFamilies.length + 3 + (!isTechnicalMode && edgeEnabled ? 2 : 0) + 1
        return (
          <Collapsible key={index.id} open={isOpen}>
            <Card className="dashboard-panel">
              <CardHeader
                className="cursor-pointer pb-3"
                onClick={() => setOpenKey(isOpen ? null : index.id)}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-2">
                    {isOpen ? <ChevronDown className="mt-0.5 h-4 w-4" /> : <ChevronRight className="mt-0.5 h-4 w-4" />}
                    <div>
                      <CardTitle className="text-base">{index.name}</CardTitle>
                      <p className="text-sm text-muted-foreground">{index.stock_count} action(s)</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {renderIndexHeaderSignal(index, displayMode)}
                    {!readOnly && index.editable && !isEditing && (
                      <>
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="outline"
                          onClick={(event) => {
                            event.stopPropagation()
                            startEdit(index)
                          }}
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="destructive"
                          onClick={(event) => {
                            event.stopPropagation()
                            void submitDelete(index)
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              </CardHeader>

              <CardContent className="space-y-4">
                <IndexSignalOverview
                  index={index}
                  horizonDays={horizonDays}
                  edgeEnabled={edgeEnabled}
                  displayMode={displayMode}
                  technicalDirectionMode={technicalDirectionMode}
                />

                {isEditing && !readOnly && index.editable && (
                  <div className="space-y-3 rounded-md border p-3">
                    <Input
                      value={editName}
                      onChange={(event) => setEditName(event.target.value)}
                      placeholder="Nom de l'indice"
                      aria-invalid={editNameInvalid}
                    />
                    {editNameInvalid && (
                      <p className="text-xs text-destructive">Le nom de l'indice ne peut pas etre vide.</p>
                    )}
                    <Input
                      value={editSearch}
                      onChange={(event) => setEditSearch(event.target.value)}
                      placeholder="Rechercher un symbole"
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={availableShareSymbols.length === 0}
                        onClick={() => applyAvailableShares([], setEditSymbols, setEditShareInputs)}
                      >
                        <Database className="h-4 w-4" />
                        Toutes les actions disponibles
                      </Button>
                      <span className="text-xs text-muted-foreground">{availableShareSymbols.length} quantite(s) disponible(s)</span>
                    </div>
                    <div className="max-h-52 space-y-2 overflow-y-auto rounded-md border p-3">
                      {symbolOptions(editSearch).map((stock) => (
                        <label key={`edit-${index.id}-${stock.symbol}`} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={editSymbols.includes(stock.symbol)}
                            onChange={() => toggleSymbol(editSymbols, stock.symbol, setEditSymbols, setEditShareInputs)}
                          />
                          <span className="font-mono">{stock.symbol}</span>
                          <span className="text-muted-foreground">{stock.display_name ?? "-"}</span>
                        </label>
                      ))}
                    </div>
                    {renderComponentShareEditor({
                      symbols: editSymbols,
                      shareInputs: editShareInputs,
                      validationMessage: editShareMessage,
                      onShareChange: (symbol, value) => {
                        setEditShareInputs((previous) => ({ ...previous, [symbol]: value }))
                      },
                    })}
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        size="sm"
                        onClick={submitEdit}
                        disabled={!canSubmitEdit}
                      >
                        Enregistrer
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setEditingId(null)
                          setEditName("")
                          setEditSearch("")
                          setEditSymbols([])
                          setEditShareInputs({})
                        }}
                      >
                        Annuler
                      </Button>
                      <span className="text-xs text-muted-foreground">{editSymbols.length} symbole(s) selectionne(s)</span>
                    </div>
                  </div>
                )}

                {shownFamilies.length > 0 ? (
                  <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                    {shownFamilies.map((family) => (
                      <div key={`${index.id}-${family}`} className="space-y-1">
                        <p className="text-sm font-medium">{FAMILY_LABELS[family]}</p>

                        {isTechnicalMode ? (
                          <FamilyCell score={index.technicalStats.topSignal?.per_family?.[family] ?? null} factorDependencies={index.technicalStats.topSignal?.factor_dependencies?.[family]} />
                        ) : scoreSource === "both" ? (
                          <div className="space-y-1">
                            <div>
                              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                              <FamilyCell score={index.scores.signal_engine.per_family[family]} />
                            </div>
                            <div className="border-t pt-1">
                              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                              <FamilyCell score={index.scores.wfo?.per_family[family] ?? null} />
                            </div>
                          </div>
                        ) : scoreSource === "wfo" ? (
                          <FamilyCell score={index.scores.wfo?.per_family[family] ?? null} />
                        ) : (
                          <FamilyCell score={index.scores.signal_engine.per_family[family]} />
                        )}
                      </div>
                    ))}
                  </div>
                ) : null}

                <div className="space-y-2">
                  <p className="text-sm font-medium">Largeur de marche</p>
                  {scoreSource === "both" ? (
                    <div className="space-y-2">
                      <div>
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                        <BreadthBar breadth={index.scores.signal_engine.breadth} total={index.stock_count} />
                      </div>
                      <div className="border-t pt-1">
                        <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                        <BreadthBar
                          breadth={index.scores.wfo?.breadth ?? { achat: 0, neutre: 0, vente: 0, indisponible: index.stock_count }}
                          total={index.stock_count}
                        />
                      </div>
                    </div>
                  ) : scoreSource === "wfo" ? (
                    <BreadthBar
                      breadth={index.scores.wfo?.breadth ?? { achat: 0, neutre: 0, vente: 0, indisponible: index.stock_count }}
                      total={index.stock_count}
                    />
                  ) : (
                    <BreadthBar breadth={index.scores.signal_engine.breadth} total={index.stock_count} />
                  )}
                </div>
              </CardContent>

              <CollapsibleContent forceMount>
                {isOpen && (
                  <CardContent className="pt-0">
                    <div className="rounded-md border">
                      <Table className={cn(showComponentWeights ? "min-w-[1280px]" : "min-w-[1080px]", "text-[12px]")}>
                        <TableHeader>
                          <TableRow className="border-b border-border bg-bg2 hover:bg-bg2">
                            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Ticker</TableHead>
                            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Nom</TableHead>
                            {showComponentWeights ? (
                              <>
                                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Actions</TableHead>
                                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Prix</TableHead>
                                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Poids</TableHead>
                              </>
                            ) : null}
                            {shownFamilies.map((family) => (
                              <TableHead key={`${index.id}-member-${family}`} className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                                {FAMILY_SHORT_LABELS[family]}
                              </TableHead>
                            ))}
                            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                              {isTechnicalMode ? `Direction ${technicalModeShortLabel(technicalDirectionMode)}` : "Signal"}
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
                          {index.members.length === 0 ? (
                            <TableRow>
                              <TableCell colSpan={memberColumnCount} className="text-center text-sm text-muted-foreground">
                                Aucune action dans cet indice.
                              </TableCell>
                            </TableRow>
                          ) : (
                            sortedMembers.map((member) => {
                              const signal = bestSignalForDisplay(member.stock)
                              const technicalSignal = technicalSignalForDisplay(member.stock, technicalDirectionMode)
                              const href = member.stock
                                ? isTechnicalMode
                                  ? technicalHref(member.stock, horizon, technicalDirectionMode)
                                  : evidenceHref(member.stock, horizon)
                                : null

                              return (
                                <TableRow key={`${index.id}-${member.symbol}`} className="border-b border-border/70 hover:bg-bg2">
                                  <TableCell className="px-3 py-2.5">
                                    {href ? (
                                      <Link href={href} className="dashboard-mono text-[12px] font-semibold hover:underline">
                                        {member.symbol}
                                      </Link>
                                    ) : (
                                      <span className="dashboard-mono text-[12px] font-semibold">{member.symbol}</span>
                                    )}
                                  </TableCell>
                                  <TableCell className="max-w-[220px] px-3 py-2.5">
                                    {href ? (
                                      <Link href={href} className="block hover:underline">
                                        <div className="text-[12px] font-medium">{member.display_name ?? "-"}</div>
                                      </Link>
                                    ) : (
                                      <div className="text-[12px] font-medium text-muted-foreground">{member.display_name ?? "-"}</div>
                                    )}
                                  </TableCell>
                                  {showComponentWeights ? (
                                    <>
                                      <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">{member.shares ?? "--"}</TableCell>
                                      <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">{formatMoneyCompact(member.price)}</TableCell>
                                      <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                                        <div>{formatWeightPct(index.isWeightedComplete ? member.weightPct : null)}</div>
                                        <div className="text-[10px] text-muted-foreground">{formatMoneyCompact(member.marketValue)}</div>
                                      </TableCell>
                                    </>
                                  ) : null}
                                  {shownFamilies.map((family) => (
                                    <TableCell key={`${index.id}-${member.symbol}-${family}`} className="px-3 py-2.5">
                                      {isTechnicalMode ? (
                                        <FamilyCell score={technicalSignal?.per_family?.[family] ?? null} factorDependencies={technicalSignal?.factor_dependencies?.[family]} />
                                      ) : scoreSource === "both" ? (
                                        <div className="space-y-1">
                                          <div>
                                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">SE</p>
                                            <FamilyCell score={member.scores.signal_engine.per_family[family]} />
                                          </div>
                                          <div className="border-t pt-1">
                                            <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">WFO</p>
                                            <FamilyCell score={member.scores.wfo?.per_family[family] ?? null} />
                                          </div>
                                        </div>
                                      ) : scoreSource === "wfo" ? (
                                        <FamilyCell score={member.scores.wfo?.per_family[family] ?? null} />
                                      ) : (
                                        <FamilyCell score={member.scores.signal_engine.per_family[family]} />
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
                                        <div className="dashboard-mono text-[10px] text-muted-foreground">
                                          {technicalDirectionMode === "classic" ? "Fixed classic" : displayVariantLabel(technicalSignal?.variant)}
                                        </div>
                                      </div>
                                    ) : <BestSignalMethodCell signal={signal} />}
                                  </TableCell>
                                  <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                                    {href ? (
                                      <Link href={href} className="block hover:text-foreground hover:underline">
                                        {isTechnicalMode ? (
                                          <div className="space-y-0.5 text-right">
                                            <div>{formatScorePct(technicalSignal?.score_pct)}</div>
                                            <div className="text-[10px] text-muted-foreground">{technicalDirectionLabel(technicalSignal?.direction)}</div>
                                          </div>
                                        ) : <BestSignalExpectedReturnCell signal={signal} fallbackDays={horizonDays} />}
                                      </Link>
                                    ) : (
                                      isTechnicalMode ? (
                                        <div className="space-y-0.5 text-right">
                                          <div>{formatScorePct(technicalSignal?.score_pct)}</div>
                                          <div className="text-[10px] text-muted-foreground">{technicalDirectionLabel(technicalSignal?.direction)}</div>
                                        </div>
                                      ) : <BestSignalExpectedReturnCell signal={signal} fallbackDays={horizonDays} />
                                    )}
                                  </TableCell>
                                  {!isTechnicalMode && edgeEnabled ? (
                                    <>
                                      <TableCell className="px-3 py-2.5 text-right"><BestSignalHitRateCell signal={signal} /></TableCell>
                                      <TableCell className="px-3 py-2.5"><EdgeBadge triage={bestSignalTriage(signal)} /></TableCell>
                                    </>
                                  ) : null}
                                  <TableCell className="px-2 py-2.5 align-middle">
                                    {href ? (
                                      <Link
                                        href={href}
                                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-transparent text-muted-foreground transition hover:border-border hover:bg-muted/30 hover:text-foreground"
                                        aria-label={`Voir la preuve OOS ${member.symbol}`}
                                      >
                                        <ArrowRight className="h-3.5 w-3.5" />
                                      </Link>
                                    ) : null}
                                  </TableCell>
                                </TableRow>
                              )
                            })
                          )}
                        </TableBody>
                      </Table>
                    </div>
                  </CardContent>
                )}
              </CollapsibleContent>
            </Card>
          </Collapsible>
        )
      })}
    </div>
  )
}
