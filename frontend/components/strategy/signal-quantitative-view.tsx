"use client"

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import useSWR from "swr"
import {
  Activity,
  BarChart3,
  CheckCircle2,
  Database,
  GitCompareArrows,
  LineChart,
  Search,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from "lucide-react"
import {
  useAnalyticsSignalsOverview,
  useFactorSignalEval,
  useFactorLeaderboard,
  useFactorRelevance,
  useSignalEvaluation,
  useStatArbPairDetail,
  useStatArbLeaderboard,
  useStatArbStatus,
} from "@/hooks/use-api"
import { useDashboardData } from "@/hooks/use-dashboard"
import {
  fetchSignalBacktestResultsWithBootstrap,
  fetchSignalEvidence,
  type FactorLeaderboardRow,
  type FactorRelevanceRow,
  type FactorSignalEval,
  type PlotlyFigure,
  type SignalBacktestResponse,
  type SignalBacktestResult,
  type SignalEvaluationReport,
  type SignalEvidence,
  type SignalOverviewRow,
  type StatArbPairDetail,
  type StatArbPairRow,
} from "@/lib/api"
import { horizonLabel } from "@/lib/horizon"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { PlotlyChart } from "@/components/run/plotly-chart"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

type EngineHorizon = "short" | "medium" | "long"
type UniverseFilter = "all" | "liquid"
type DirectionFilter = "all" | "long" | "short"
type QuantSleeve = "cross" | "trend" | "mean_reversion" | "volume" | "macro" | "pairs"
type CandidateBias = "Long" | "Short" | "Neutral" | "Pair long/short" | "Pair continuation"
type GateStatus = "Trade" | "Watch" | "Research" | "Reject"

type QuantCandidate = {
  id: string
  sourceType: "signal" | "macro" | "pair"
  symbol: string
  sleeve: QuantSleeve
  sleeveLabel: string
  bias: CandidateBias
  label: string
  rawCategory: string | null
  factorId: string | null
  pairId: string | null
  testStat: number | null
  category: string
  edge: number
  ic: number | null
  hitRate: number | null
  sharpe: number | null
  nObs: number | null
  fdrPass: boolean
  adv: number | null
  sector: string | null
  status: GateStatus
  notes: string[]
}

const LIQUID_ADV = 1_000_000

const HORIZONS: Array<{ value: EngineHorizon; label: string; fwd: number }> = [
  { value: "short", label: "Hebdomadaire", fwd: 5 },
  { value: "medium", label: "Mensuel", fwd: 21 },
  { value: "long", label: "Trimestriel", fwd: 63 },
]

const SLEEVE_META: Record<QuantSleeve, { label: string; shortLabel: string; icon: LucideIcon; tone: string }> = {
  cross: {
    label: "Cross-sectional momentum",
    shortLabel: "X-sec momentum",
    icon: BarChart3,
    tone: "border-blue-200 bg-blue-50 text-blue-700",
  },
  trend: {
    label: "Trend following",
    shortLabel: "Trend",
    icon: TrendingUp,
    tone: "border-emerald-200 bg-emerald-50 text-emerald-700",
  },
  mean_reversion: {
    label: "Mean reversion",
    shortLabel: "Reversion",
    icon: TrendingDown,
    tone: "border-amber-200 bg-amber-50 text-amber-800",
  },
  volume: {
    label: "Volume and flow",
    shortLabel: "Flow",
    icon: Activity,
    tone: "border-sky-200 bg-sky-50 text-sky-700",
  },
  macro: {
    label: "Macro factor timing",
    shortLabel: "Macro",
    icon: Database,
    tone: "border-violet-200 bg-violet-50 text-violet-700",
  },
  pairs: {
    label: "Pairs and stat-arb",
    shortLabel: "Pairs",
    icon: GitCompareArrows,
    tone: "border-slate-300 bg-slate-50 text-slate-700",
  },
}

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function finiteUnknown(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function firstNumber(...values: Array<number | null | undefined>): number | null {
  for (const value of values) {
    const parsed = finiteNumber(value)
    if (parsed != null) return parsed
  }
  return null
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function fmt(value: number | null | undefined, digits = 2) {
  const numberValue = finiteNumber(value)
  if (numberValue == null) return "--"
  return numberValue.toFixed(digits)
}

function fmtSigned(value: number | null | undefined, digits = 2) {
  const numberValue = finiteNumber(value)
  if (numberValue == null) return "--"
  return `${numberValue >= 0 ? "+" : ""}${numberValue.toFixed(digits)}`
}

function fmtPct(value: number | null | undefined, digits = 1) {
  const numberValue = finiteNumber(value)
  if (numberValue == null) return "--"
  return `${(numberValue * 100).toFixed(digits)}%`
}

function fmtAdv(value: number | null | undefined) {
  const numberValue = finiteNumber(value)
  if (numberValue == null) return "--"
  if (numberValue >= 1_000_000) return `${(numberValue / 1_000_000).toFixed(1)}m`
  if (numberValue >= 1_000) return `${Math.round(numberValue / 1_000)}k`
  return Math.round(numberValue).toString()
}

function categoryText(value: string | null | undefined) {
  const token = String(value ?? "").trim()
  if (!token) return "signal"
  return token.replace(/_/g, " ")
}

function categoryMatches(row: SignalOverviewRow, tokens: string[]) {
  const category = `${row.category} ${row.signal_id}`.toLowerCase()
  return tokens.some((token) => category.includes(token))
}

function rowBias(row: SignalOverviewRow): CandidateBias {
  const label = String(row.engine_label ?? "").toLowerCase()
  const score = finiteNumber(row.engine_score_pct)
  if (label.includes("achat") || label.includes("buy") || label.includes("long") || label.includes("hauss") || label.includes("survendu")) {
    return "Long"
  }
  if (label.includes("vente") || label.includes("sell") || label.includes("short") || label.includes("baiss") || label.includes("surachet")) {
    return "Short"
  }
  if (score != null && score >= 8) return "Long"
  if (score != null && score <= -8) return "Short"
  return "Neutral"
}

function rowEdgeScore(row: SignalOverviewRow) {
  const ic = firstNumber(row.ic_h5, row.ic_h1) ?? 0
  const sharpe = firstNumber(row.after_cost_sharpe, row.sharpe) ?? 0
  const hitRate = firstNumber(row.hit_rate) ?? 0.5
  const engine = finiteNumber(row.engine_score_pct) ?? 0
  const nObs = finiteNumber(row.n_obs) ?? 0
  const fdr = row.fdr_pass ? 12 : 0
  const evidence =
    Math.abs(engine) * 0.22 +
    Math.abs(ic) * 260 +
    Math.abs(sharpe) * 16 +
    Math.abs(hitRate - 0.5) * 120 +
    Math.min(10, Math.log10(nObs + 1) * 4) +
    fdr
  return clamp(evidence, 0, 100)
}

function gateStatus(params: {
  edge: number
  fdrPass: boolean
  nObs: number | null
  sharpe: number | null
  adv: number | null
  pairStatus?: string
}): GateStatus {
  if (params.pairStatus) {
    if (params.pairStatus === "actionable") return "Trade"
    if (params.pairStatus === "watch") return "Watch"
    if (params.pairStatus === "rejected" || params.pairStatus === "failed") return "Reject"
  }
  const enoughObs = (params.nObs ?? 0) >= 50
  const costOk = (params.sharpe ?? 0) > 0
  const liquid = params.adv == null || params.adv >= LIQUID_ADV
  if (params.edge >= 65 && params.fdrPass && enoughObs && costOk && liquid) return "Trade"
  if (params.edge >= 45 && enoughObs && costOk) return "Watch"
  if (params.edge < 22 || (!liquid && params.adv != null)) return "Reject"
  return "Research"
}

function statusClass(status: GateStatus) {
  if (status === "Trade") return "border-emerald-300 bg-emerald-50 text-emerald-700"
  if (status === "Watch") return "border-blue-300 bg-blue-50 text-blue-700"
  if (status === "Reject") return "border-red-300 bg-red-50 text-red-700"
  return "border-amber-300 bg-amber-50 text-amber-800"
}

function biasClass(bias: CandidateBias) {
  if (bias === "Long" || bias === "Pair continuation") return "text-emerald-700"
  if (bias === "Short") return "text-red-700"
  if (bias === "Pair long/short") return "text-blue-700"
  return "text-muted-foreground"
}

function labelPairAction(row: StatArbPairRow): CandidateBias {
  if (row.action_type === "buy_buy") return "Pair continuation"
  if (row.action_type === "long_y_short_x" || row.action_type === "short_y_long_x") return "Pair long/short"
  return "Neutral"
}

function actionText(row: StatArbPairRow) {
  if (row.action_type === "long_y_short_x") return `Long ${row.symbol_y} / Short ${row.symbol_x}`
  if (row.action_type === "short_y_long_x") return `Short ${row.symbol_y} / Long ${row.symbol_x}`
  if (row.action_type === "buy_buy") return `Long ${row.symbol_y} + ${row.symbol_x}`
  return row.current_signal || "No action"
}

function pairEdgeScore(row: StatArbPairRow) {
  const sharpe = Math.max(0, finiteNumber(row.oos_sharpe) ?? 0)
  const profitable = finiteNumber(row.profitable_fold_ratio) ?? 0
  const qValue = finiteNumber(row.fdr_qvalue)
  const zscore = Math.abs(finiteNumber(row.zscore) ?? 0)
  const drawdown = Math.abs(finiteNumber(row.max_drawdown) ?? 0)
  const qScore = qValue == null ? 0 : clamp((0.15 - qValue) * 180, 0, 18)
  return clamp(sharpe * 18 + profitable * 24 + zscore * 6 + qScore - drawdown * 35, 0, 100)
}

function avg(values: Array<number | null | undefined>) {
  const nums = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value))
  if (nums.length === 0) return null
  return nums.reduce((sum, value) => sum + value, 0) / nums.length
}

function sortByEdge<T extends { edge: number }>(rows: T[]) {
  return [...rows].sort((left, right) => right.edge - left.edge)
}

function bestBySymbol(rows: QuantCandidate[]) {
  const map = new Map<string, QuantCandidate>()
  for (const row of rows) {
    const existing = map.get(row.symbol)
    if (!existing || row.edge > existing.edge) map.set(row.symbol, row)
  }
  return sortByEdge(Array.from(map.values()))
}

function candidateFromRow(
  row: SignalOverviewRow,
  sleeve: QuantSleeve,
  advBySymbol: Map<string, number>,
  sectorBySymbol: Map<string, string | null>,
): QuantCandidate {
  const edge = rowEdgeScore(row)
  const ic = firstNumber(row.ic_h5, row.ic_h1)
  const sharpe = firstNumber(row.after_cost_sharpe, row.sharpe)
  const hitRate = firstNumber(row.hit_rate)
  const adv = advBySymbol.get(row.symbol) ?? null
  const nObs = finiteNumber(row.n_obs)
  const status = gateStatus({ edge, fdrPass: row.fdr_pass, nObs, sharpe, adv })
  const notes = [
    row.fdr_pass ? "FDR pass" : "FDR pending",
    nObs != null ? `n=${nObs}` : "n missing",
    adv != null ? `ADV ${fmtAdv(adv)}` : "ADV missing",
  ]
  return {
    id: `${sleeve}:${row.symbol}:${row.signal_id}:${row.category}`,
    sourceType: "signal",
    symbol: row.symbol,
    sleeve,
    sleeveLabel: SLEEVE_META[sleeve].shortLabel,
    bias: rowBias(row),
    label: row.signal_id,
    rawCategory: row.category,
    factorId: null,
    pairId: null,
    testStat: null,
    category: categoryText(row.category),
    edge,
    ic,
    hitRate,
    sharpe,
    nObs,
    fdrPass: row.fdr_pass,
    adv,
    sector: sectorBySymbol.get(row.symbol) ?? null,
    status,
    notes,
  }
}

function macroCandidateFromRow(
  row: FactorLeaderboardRow,
  advBySymbol: Map<string, number>,
  sectorBySymbol: Map<string, string | null>,
): QuantCandidate {
  const edge = clamp(Math.abs(row.max_t_stat) * 2.2 + Math.abs(row.max_ic) * 160 + Math.min(18, row.n_significant * 2), 0, 100)
  const status: GateStatus = edge >= 65 && row.n_significant > 0 && row.n_obs >= 50 ? "Watch" : "Research"
  const adv = advBySymbol.get(row.symbol) ?? null
  return {
    id: `macro:${row.symbol}:${row.best_factor}`,
    sourceType: "macro",
    symbol: row.symbol,
    sleeve: "macro",
    sleeveLabel: SLEEVE_META.macro.shortLabel,
    bias: row.max_ic >= 0 ? "Long" : "Short",
    label: row.best_factor,
    rawCategory: null,
    factorId: row.best_factor,
    pairId: null,
    testStat: row.max_t_stat,
    category: `${row.n_significant} significant factors`,
    edge,
    ic: row.max_ic,
    hitRate: null,
    sharpe: null,
    nObs: row.n_obs,
    fdrPass: row.n_significant > 0,
    adv,
    sector: sectorBySymbol.get(row.symbol) ?? null,
    status,
    notes: [`t=${fmtSigned(row.max_t_stat)}`, `n=${row.n_obs}`],
  }
}

function pairCandidateFromRow(row: StatArbPairRow, advBySymbol: Map<string, number>): QuantCandidate {
  const edge = pairEdgeScore(row)
  const advY = advBySymbol.get(row.symbol_y) ?? null
  const advX = advBySymbol.get(row.symbol_x) ?? null
  const minAdv = advY != null && advX != null ? Math.min(advY, advX) : advY ?? advX ?? null
  const status = gateStatus({
    edge,
    fdrPass: (row.fdr_qvalue ?? 1) <= 0.1,
    nObs: row.n_obs,
    sharpe: row.oos_sharpe ?? null,
    adv: minAdv,
    pairStatus: row.status,
  })
  return {
    id: `pairs:${row.pair_id}`,
    sourceType: "pair",
    symbol: `${row.symbol_y}/${row.symbol_x}`,
    sleeve: "pairs",
    sleeveLabel: SLEEVE_META.pairs.shortLabel,
    bias: labelPairAction(row),
    label: actionText(row),
    rawCategory: null,
    factorId: null,
    pairId: row.pair_id,
    testStat: row.zscore ?? null,
    category: row.archetype.replace(/_/g, " "),
    edge,
    ic: null,
    hitRate: row.profitable_fold_ratio ?? null,
    sharpe: row.oos_sharpe ?? null,
    nObs: row.n_obs,
    fdrPass: (row.fdr_qvalue ?? 1) <= 0.1,
    adv: minAdv,
    sector: null,
    status,
    notes: [`z=${fmtSigned(row.zscore)}`, `q=${fmt(row.fdr_qvalue, 3)}`],
  }
}

function directionMatches(row: QuantCandidate, direction: DirectionFilter) {
  if (direction === "all") return true
  if (direction === "long") return row.bias === "Long" || row.bias === "Pair continuation"
  return row.bias === "Short"
}

function filterCandidates(rows: QuantCandidate[], query: string, universe: UniverseFilter, direction: DirectionFilter) {
  const q = query.trim().toLowerCase()
  return rows.filter((row) => {
    if (universe === "liquid" && row.adv != null && row.adv < LIQUID_ADV) return false
    if (!directionMatches(row, direction)) return false
    if (!q) return true
    return `${row.symbol} ${row.label} ${row.sleeveLabel} ${row.category} ${row.sector ?? ""}`.toLowerCase().includes(q)
  })
}

function quantStrategyDetailHref(row: QuantCandidate, horizon: EngineHorizon) {
  const params = new URLSearchParams({
    sourceType: row.sourceType,
    symbol: row.symbol,
    sleeve: row.sleeve,
    sleeveLabel: row.sleeveLabel,
    bias: row.bias,
    status: row.status,
    label: row.label,
    category: row.category,
    horizon,
    fdrPass: String(row.fdrPass),
  })
  if (row.rawCategory) params.set("rawCategory", row.rawCategory)
  if (row.factorId) params.set("factorId", row.factorId)
  if (row.pairId) params.set("pairId", row.pairId)
  if (row.ic != null) params.set("ic", String(row.ic))
  if (row.hitRate != null) params.set("hitRate", String(row.hitRate))
  if (row.sharpe != null) params.set("sharpe", String(row.sharpe))
  if (row.nObs != null) params.set("nObs", String(row.nObs))
  if (row.adv != null) params.set("adv", String(row.adv))
  if (row.sector) params.set("sector", row.sector)
  if (row.testStat != null) params.set("testStat", String(row.testStat))
  params.set("edge", String(row.edge))
  return `/signals/quant-strategy/${encodeURIComponent(row.id)}?${params.toString()}`
}

function MetricTile({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string
  value: string
  sub: string
  tone?: "positive" | "negative" | "neutral" | "blue"
}) {
  return (
    <div className="rounded-lg border border-line bg-card px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 truncate font-mono text-xl font-semibold tabular-nums",
          tone === "positive" && "text-emerald-700",
          tone === "negative" && "text-red-700",
          tone === "blue" && "text-blue-700",
        )}
      >
        {value}
      </div>
      <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{sub}</div>
    </div>
  )
}

function CandidateBadge({ row }: { row: QuantCandidate }) {
  return (
    <Badge variant="outline" className={cn("h-5 px-1.5 text-[10px]", statusClass(row.status))}>
      {row.status}
    </Badge>
  )
}

function validationText(row: QuantCandidate) {
  if (row.sourceType === "macro") return `t ${fmtSigned(row.testStat, 1)}`
  if (row.sourceType === "pair") return row.hitRate == null ? `z ${fmtSigned(row.testStat, 2)}` : `fold ${fmtPct(row.hitRate, 0)}`
  return row.hitRate == null ? `n ${row.nObs ?? "--"}` : fmtPct(row.hitRate, 0)
}

function backtestText(row: QuantCandidate) {
  if (row.sourceType === "macro") return "relevance first"
  if (row.sharpe == null) return "pending"
  return fmtSigned(row.sharpe, 2)
}

function screenValidationMetric(row: QuantCandidate): {
  label: string
  value: string
  sub: string
  tone: "positive" | "negative" | "neutral" | "blue"
} {
  if (row.sourceType === "macro") {
    return {
      label: "Relevance t-stat",
      value: fmtSigned(row.testStat, 1),
      sub: `${row.factorId ?? "Factor"} - ${row.nObs ?? "--"} obs`,
      tone: icTone(row.testStat),
    }
  }
  if (row.sourceType === "pair") {
    return {
      label: "OOS validation",
      value: row.hitRate == null ? `z ${fmtSigned(row.testStat, 2)}` : fmtPct(row.hitRate, 0),
      sub: `Sharpe ${fmtSigned(row.sharpe, 2)}`,
      tone: icTone(row.sharpe),
    }
  }
  if (row.hitRate == null) {
    return {
      label: "Sample size",
      value: `${row.nObs ?? "--"} obs`,
      sub: `Sharpe ${fmtSigned(row.sharpe, 2)}`,
      tone: icTone(row.sharpe),
    }
  }
  return {
    label: "Screen hit",
    value: fmtPct(row.hitRate, 1),
    sub: `Sharpe ${fmtSigned(row.sharpe, 2)}`,
    tone: row.hitRate >= 0.5 ? "positive" : "negative",
  }
}

function SleeveCard({
  sleeve,
  rows,
  selectedCandidateId,
  onSelectCandidate,
}: {
  sleeve: QuantSleeve
  rows: QuantCandidate[]
  selectedCandidateId: string | null
  onSelectCandidate: (candidate: QuantCandidate) => void
}) {
  const meta = SLEEVE_META[sleeve]
  const Icon = meta.icon
  const top = rows[0] ?? null
  const tradeCount = rows.filter((row) => row.status === "Trade").length
  const avgEdge = avg(rows.map((row) => row.edge))
  return (
    <Card className="rounded-lg py-4">
      <CardHeader className="px-4 pb-0">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-md border", meta.tone)}>
                <Icon className="h-3.5 w-3.5" />
              </span>
              <span className="truncate">{meta.label}</span>
            </CardTitle>
            <div className="mt-1 text-[11px] text-muted-foreground">
              {tradeCount} trade gate - avg edge {fmt(avgEdge, 1)}
            </div>
          </div>
          {top ? <CandidateBadge row={top} /> : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-2 px-4 pt-3">
        {rows.length === 0 ? (
          <div className="rounded-md border border-dashed border-line px-3 py-5 text-center text-xs text-muted-foreground">
            No qualified names.
          </div>
        ) : (
          rows.slice(0, 4).map((row) => (
            <button
              key={row.id}
              type="button"
              onClick={() => onSelectCandidate(row)}
              className={cn(
                "grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-line px-3 py-2 text-left hover:bg-muted/50",
                selectedCandidateId === row.id && "border-primary/40 bg-primary/5",
              )}
            >
              <span className="min-w-0">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="truncate font-mono text-xs font-semibold">{row.symbol}</span>
                  <span className={cn("shrink-0 text-[11px] font-semibold", biasClass(row.bias))}>{row.bias}</span>
                </span>
                <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                  {row.category} - {row.label}
                </span>
              </span>
              <span className="text-right">
                <span className="block font-mono text-sm font-semibold tabular-nums">{fmt(row.edge, 0)}</span>
                <span className="block text-[10px] text-muted-foreground">IC {fmtSigned(row.ic, 3)}</span>
              </span>
            </button>
          ))
        )}
      </CardContent>
    </Card>
  )
}

function FocusPanel({
  symbol,
  rows,
  factorRows,
  pairRows,
}: {
  symbol: string | null
  rows: QuantCandidate[]
  factorRows: FactorLeaderboardRow[]
  pairRows: StatArbPairRow[]
}) {
  if (!symbol) {
    return (
      <div className="flex h-full min-h-[220px] items-center justify-center rounded-lg border border-dashed border-line bg-card px-4 text-center text-sm text-muted-foreground">
        Select a symbol from the blotter to review its quant signals.
      </div>
    )
  }
  const symbolRows = sortByEdge(rows.filter((row) => row.symbol === symbol)).slice(0, 5)
  const factor = factorRows.find((row) => row.symbol === symbol)
  const pairs = pairRows.filter((row) => row.symbol_x === symbol || row.symbol_y === symbol).slice(0, 4)
  return (
    <Card className="rounded-lg py-4">
      <CardHeader className="px-4 pb-0">
        <CardTitle className="flex items-center gap-2 text-sm">
          <LineChart className="h-4 w-4 text-primary" />
          Symbol quant stack - <span className="font-mono">{symbol}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pt-3">
        <div className="grid gap-2 sm:grid-cols-3">
          <MetricTile
            label="Best edge"
            value={symbolRows[0] ? fmt(symbolRows[0].edge, 0) : "--"}
            sub={symbolRows[0]?.sleeveLabel ?? "No signal rows"}
            tone={symbolRows[0]?.status === "Trade" ? "positive" : "neutral"}
          />
          <MetricTile
            label="Best factor"
            value={factor?.best_factor ?? "--"}
            sub={factor ? `${factor.n_significant}/6 significant` : "No macro row"}
            tone={factor && factor.n_significant > 0 ? "blue" : "neutral"}
          />
          <MetricTile
            label="Pair links"
            value={String(pairs.length)}
            sub={pairs[0] ? `${pairs[0].symbol_y}/${pairs[0].symbol_x}` : "No active pair row"}
          />
        </div>
        <div className="space-y-1.5">
          {symbolRows.length === 0 ? (
            <div className="rounded-md border border-dashed border-line px-3 py-4 text-xs text-muted-foreground">
              No signal candidates for this horizon.
            </div>
          ) : (
            symbolRows.map((row) => (
              <div key={row.id} className="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2 text-xs">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px]">{row.sleeveLabel}</Badge>
                    <span className={cn("font-semibold", biasClass(row.bias))}>{row.bias}</span>
                    <span className="truncate text-muted-foreground">{row.label}</span>
                  </div>
                  <div className="mt-1 truncate text-[11px] text-muted-foreground">{row.notes.join(" - ")}</div>
                </div>
                <div className="shrink-0 text-right font-mono tabular-nums">
                  <div>{fmt(row.edge, 0)}</div>
                  <div className="text-[10px] text-muted-foreground">IC {fmtSigned(row.ic, 3)}</div>
                </div>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  )
}

function BlotterTable({
  rows,
  selectedCandidateId,
  onSelectCandidate,
}: {
  rows: QuantCandidate[]
  selectedCandidateId: string | null
  onSelectCandidate: (candidate: QuantCandidate) => void
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-card">
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <TableHead>Signal</TableHead>
            <TableHead>Sleeve</TableHead>
            <TableHead>Bias</TableHead>
            <TableHead className="text-right">Edge</TableHead>
            <TableHead className="text-right">IC</TableHead>
            <TableHead className="text-right">Validation</TableHead>
            <TableHead className="text-right">Backtest</TableHead>
            <TableHead className="text-right">ADV</TableHead>
            <TableHead>Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={9} className="py-8 text-center text-sm text-muted-foreground">
                No rows match the current filters.
              </TableCell>
            </TableRow>
          ) : (
            rows.slice(0, 18).map((row) => (
              <TableRow
                key={row.id}
                className={cn(
                  "cursor-pointer text-xs hover:bg-muted/50",
                  selectedCandidateId === row.id && "bg-primary/5",
                )}
                onClick={() => onSelectCandidate(row)}
              >
                <TableCell>
                  <div className="min-w-0">
                    <div className="font-mono font-semibold">{row.symbol}</div>
                    <div className="max-w-[240px] truncate text-[11px] text-muted-foreground">{row.label}</div>
                  </div>
                </TableCell>
                <TableCell>
                  <Badge variant="outline" className="text-[10px]">{row.sleeveLabel}</Badge>
                </TableCell>
                <TableCell className={cn("font-semibold", biasClass(row.bias))}>{row.bias}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(row.edge, 0)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmtSigned(row.ic, 3)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{validationText(row)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{backtestText(row)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmtAdv(row.adv)}</TableCell>
                <TableCell><CandidateBadge row={row} /></TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}

function EvidenceMetric({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string
  value: string
  sub?: string
  tone?: "positive" | "negative" | "neutral" | "blue"
}) {
  return (
    <div className="rounded-md border border-line bg-bg2 px-2.5 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1 truncate font-mono text-sm font-semibold tabular-nums",
          tone === "positive" && "text-emerald-700",
          tone === "negative" && "text-red-700",
          tone === "blue" && "text-blue-700",
        )}
      >
        {value}
      </div>
      {sub ? <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

function icTone(value: number | null | undefined): "positive" | "negative" | "neutral" {
  const parsed = finiteNumber(value)
  if (parsed == null) return "neutral"
  return parsed >= 0 ? "positive" : "negative"
}

function ICDecayMiniChart({
  report,
}: {
  report: Pick<SignalEvaluationReport, "ic_curve"> | Pick<FactorSignalEval, "ic_curve">
}) {
  const horizons = report.ic_curve.horizons ?? []
  const values = report.ic_curve.ic_values ?? []
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)).filter((value) => Number.isFinite(value)), 0.01)
  if (horizons.length === 0 || values.length === 0) {
    return <div className="rounded-md border border-dashed border-line px-3 py-5 text-center text-xs text-muted-foreground">IC curve unavailable.</div>
  }
  return (
    <div className="rounded-md border border-line bg-card px-3 py-2">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">IC decay by forward horizon</div>
      <div className="flex h-20 items-end gap-1.5">
        {horizons.map((horizon, index) => {
          const ic = finiteNumber(values[index])
          const height = ic == null ? 4 : Math.max(5, (Math.abs(ic) / maxAbs) * 58)
          return (
            <div key={`${horizon}-${index}`} className="flex min-w-0 flex-1 flex-col items-center gap-1">
              <div className="font-mono text-[9px] tabular-nums">{ic == null ? "--" : fmtSigned(ic, 2)}</div>
              <div
                className={cn("w-full rounded-sm", ic == null ? "bg-muted" : ic >= 0 ? "bg-emerald-500" : "bg-red-400")}
                style={{ height: `${height}px` }}
              />
              <div className="text-[9px] text-muted-foreground">d{horizon}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function numericSeries(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is number => typeof item === "number" && Number.isFinite(item))
}

function stringSeries(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === "string" && item.length > 0)
}

function sampleIndexes(length: number, maxPoints = 180) {
  if (length <= 0) return []
  if (length <= maxPoints) return Array.from({ length }, (_, index) => index)
  const step = (length - 1) / (maxPoints - 1)
  return Array.from({ length: maxPoints }, (_, index) => Math.min(length - 1, Math.round(index * step)))
}

function linePath(values: number[], indexes: number[], min: number, max: number) {
  const span = max - min || 1
  return indexes
    .map((sourceIndex, plotIndex) => {
      const value = values[Math.min(sourceIndex, values.length - 1)]
      const x = indexes.length === 1 ? 0 : (plotIndex / (indexes.length - 1)) * 100
      const y = 100 - ((value - min) / span) * 100
      return `${plotIndex === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(" ")
}

function drawdownFromEquity(values: number[]) {
  let peak = Number.NEGATIVE_INFINITY
  return values.map((value) => {
    peak = Math.max(peak, value)
    if (!Number.isFinite(peak) || Math.abs(peak) < 1e-9) return 0
    return (value - peak) / Math.abs(peak)
  })
}

function normalizedReturnPath(values: number[]) {
  const first = values.find((value) => Number.isFinite(value) && Math.abs(value) > 1e-9)
  if (first == null) return values
  return values.map((value) => value / first - 1)
}

function compactDate(value: string | undefined) {
  if (!value) return "--"
  const parts = value.split("-")
  if (parts.length >= 2) return `${parts[1]}/${parts[0].slice(2)}`
  return value
}

function MiniLineChart({
  title,
  subtitle,
  series,
  height = 180,
  zeroLine = true,
}: {
  title: string
  subtitle?: string
  series: Array<{ label: string; values: number[]; color: string }>
  height?: number
  zeroLine?: boolean
}) {
  const cleanSeries = series
    .map((item) => ({ ...item, values: item.values.filter((value) => Number.isFinite(value)) }))
    .filter((item) => item.values.length >= 2)
  const maxLength = Math.max(...cleanSeries.map((item) => item.values.length), 0)
  if (cleanSeries.length === 0 || maxLength < 2) {
    return <div className="flex h-44 items-center justify-center rounded-md border border-dashed border-line text-xs text-muted-foreground">No chart series available.</div>
  }
  const indexes = sampleIndexes(maxLength)
  const sampledValues = cleanSeries.flatMap((item) => indexes.map((index) => item.values[Math.min(index, item.values.length - 1)]))
  const min = Math.min(...sampledValues)
  const max = Math.max(...sampledValues)
  const span = max - min || 1
  const zeroY = 100 - ((0 - min) / span) * 100
  return (
    <div className="rounded-md border border-line bg-card px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{title}</div>
          {subtitle ? <div className="mt-0.5 text-[10px] text-muted-foreground">{subtitle}</div> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {cleanSeries.map((item) => (
            <span key={item.label} className="flex items-center gap-1 text-[10px] text-muted-foreground">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      </div>
      <div className="mt-2" style={{ height }}>
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full">
          {zeroLine && zeroY >= 0 && zeroY <= 100 ? <line x1="0" x2="100" y1={zeroY} y2={zeroY} stroke="currentColor" className="text-muted-foreground/30" strokeWidth="0.8" vectorEffect="non-scaling-stroke" /> : null}
          {cleanSeries.map((item) => (
            <path
              key={item.label}
              d={linePath(item.values, indexes, min, max)}
              fill="none"
              stroke={item.color}
              strokeWidth="1.8"
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </svg>
      </div>
    </div>
  )
}

function MetricBarPanel({
  title,
  subtitle,
  items,
}: {
  title: string
  subtitle?: string
  items: Array<{ label: string; value: number | null | undefined; display: string; tone?: "positive" | "negative" | "neutral" | "blue" }>
}) {
  const validItems = items.map((item) => ({ ...item, parsed: finiteNumber(item.value) }))
  const maxAbs = Math.max(...validItems.map((item) => Math.abs(item.parsed ?? 0)), 0.01)
  return (
    <div className="rounded-md border border-line bg-card px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{title}</div>
          {subtitle ? <div className="mt-0.5 text-[10px] text-muted-foreground">{subtitle}</div> : null}
        </div>
      </div>
      <div className="mt-3 space-y-2">
        {validItems.map((item) => {
          const parsed = item.parsed
          const width = parsed == null ? 0 : Math.max(4, (Math.abs(parsed) / maxAbs) * 100)
          return (
            <div key={item.label} className="grid grid-cols-[96px_minmax(0,1fr)_64px] items-center gap-2 text-xs">
              <div className="truncate text-muted-foreground">{item.label}</div>
              <div className="h-2 rounded-full bg-muted">
                <div
                  className={cn(
                    "h-2 rounded-full",
                    item.tone === "positive" && "bg-emerald-500",
                    item.tone === "negative" && "bg-red-500",
                    item.tone === "blue" && "bg-blue-500",
                    (!item.tone || item.tone === "neutral") && "bg-muted-foreground/50",
                  )}
                  style={{ width: `${width}%` }}
                />
              </div>
              <div className="text-right font-mono tabular-nums">{item.display}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function selectedBacktestDirection(candidate: QuantCandidate): "long" | "short" | null {
  if (candidate.bias === "Long" || candidate.bias === "Pair continuation") return "long"
  if (candidate.bias === "Short") return "short"
  return null
}

function alignedNumberSeries(value: unknown): Array<number | null> {
  if (!Array.isArray(value)) return []
  return value.map(finiteUnknown)
}

function validNumberSeries(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  return value.map(finiteUnknown).filter((item): item is number => item != null)
}

function seriesHasValues(values: Array<number | null> | undefined): values is Array<number | null> {
  return Array.isArray(values) && values.some((value) => value != null)
}

function makeFigure(data: Array<Record<string, unknown>>, layout: Record<string, unknown>): PlotlyFigure {
  return { data, layout }
}

function categoryMatchScore(row: SignalBacktestResult, candidate: QuantCandidate): number {
  const category = String(candidate.rawCategory ?? "").trim().toLowerCase()
  const scope = String(row.scope ?? "").trim().toLowerCase()
  const scopeKey = String(row.scope_key ?? "").trim().toLowerCase()
  if (category && scope === "per_category" && scopeKey === category) return 60
  if (category && scope === "combination" && scopeKey.split("+").map((item) => item.trim()).includes(category)) return 40
  if (!category && scope === "global") return 35
  if (scope === "global" && candidate.sleeve === "cross") return 30
  if (category && scopeKey.includes(category)) return 20
  return 0
}

function hasBacktestChartSeries(row: SignalBacktestResult) {
  return (
    row.status === "succeeded" &&
    Array.isArray(row.dates) &&
    Array.isArray(row.close_series) &&
    row.dates.length > 1 &&
    row.close_series.length > 1
  )
}

function selectSignalBacktestResult(
  response: SignalBacktestResponse | undefined,
  candidate: QuantCandidate,
): SignalBacktestResult | null {
  const rows = (response?.results ?? []).filter(hasBacktestChartSeries)
  if (rows.length === 0) return null
  return [...rows].sort((left, right) => {
    const score = (row: SignalBacktestResult) => {
      const sourceScore = row.source === "wfo" ? 80 : row.source === "engine" ? 45 : 0
      const policyScore = row.side_policy === "long_short" ? 20 : 0
      const matchScore = categoryMatchScore(row, candidate)
      const tradeScore = Math.min(15, finiteNumber(row.metrics.n_trades) ?? 0)
      const sharpeScore = Math.max(0, Math.min(20, (finiteNumber(row.metrics.sharpe) ?? 0) * 5))
      return sourceScore + policyScore + matchScore + tradeScore + sharpeScore
    }
    return score(right) - score(left)
  })[0] ?? null
}

function markerRows(row: SignalBacktestResult, sideToken: string) {
  const ledger = Array.isArray(row.trade_ledger) ? row.trade_ledger : []
  return ledger.filter((item) => {
    const side = String(isRecord(item) ? item.side ?? "" : "").toUpperCase()
    return side.includes(sideToken)
  })
}

function markerY(item: unknown): number | null {
  if (!isRecord(item)) return null
  return (
    finiteUnknown(item.prix_execution) ??
    finiteUnknown(item.open_t_plus_1) ??
    finiteUnknown(item.close_du_jour) ??
    finiteUnknown(item.open_price) ??
    finiteUnknown(item.close_price)
  )
}

function markerDate(item: unknown): string {
  if (!isRecord(item)) return ""
  return String(item.date ?? item.open_date ?? item.close_date ?? "").slice(0, 10)
}

function makePriceTradesFigure(row: SignalBacktestResult, candidate: QuantCandidate): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const close = alignedNumberSeries(row.close_series)
  if (dates.length < 2 || close.length < 2) return null
  const score = alignedNumberSeries(row.score_series ?? row.global_score_series)
  const position = alignedNumberSeries(row.position_series)
  const buys = markerRows(row, "ACHAT")
  const sells = markerRows(row, "VENTE")
  const scoreLabel = candidate.rawCategory ? `${categoryText(candidate.rawCategory)} score` : "Signal score"
  const data: Array<Record<string, unknown>> = [
    {
      type: "scatter",
      mode: "lines",
      name: "Close",
      x: dates,
      y: close,
      line: { color: "#0f172a", width: 2 },
      hovertemplate: "%{x}<br>Close %{y:.2f}<extra></extra>",
    },
  ]
  if (seriesHasValues(score)) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: scoreLabel,
      x: dates,
      y: score,
      yaxis: "y2",
      line: { color: "#2563eb", width: 1.6, dash: "dot" },
      hovertemplate: "%{x}<br>Score %{y:.1f}<extra></extra>",
    })
  }
  if (seriesHasValues(position)) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: "Position",
      x: dates,
      y: position,
      yaxis: "y3",
      line: { color: "#7c3aed", width: 1.2, shape: "hv" },
      hovertemplate: "%{x}<br>Position %{y:.0f}<extra></extra>",
    })
  }
  if (buys.length > 0) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: "Buy",
      x: buys.map(markerDate),
      y: buys.map(markerY),
      marker: { color: "#059669", size: 10, symbol: "triangle-up", line: { color: "#ffffff", width: 1 } },
      hovertemplate: "%{x}<br>Buy %{y:.2f}<extra></extra>",
    })
  }
  if (sells.length > 0) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: "Sell",
      x: sells.map(markerDate),
      y: sells.map(markerY),
      marker: { color: "#dc2626", size: 10, symbol: "triangle-down", line: { color: "#ffffff", width: 1 } },
      hovertemplate: "%{x}<br>Sell %{y:.2f}<extra></extra>",
    })
  }
  return makeFigure(data, {
    title: { text: "Price, strategy score and trades", font: { size: 13 } },
    margin: { l: 48, r: 56, t: 36, b: 42 },
    legend: { orientation: "h", y: 1.08, x: 0 },
    xaxis: { title: "", rangeslider: { visible: false } },
    yaxis: { title: "Price" },
    yaxis2: {
      title: "Score",
      overlaying: "y",
      side: "right",
      showgrid: false,
      zeroline: true,
    },
    yaxis3: {
      title: "Position",
      overlaying: "y",
      side: "right",
      anchor: "free",
      position: 0.98,
      showgrid: false,
      visible: false,
    },
  })
}

function makeEquityFigure(row: SignalBacktestResult): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const equity = alignedNumberSeries(row.equity)
  if (dates.length < 2 || equity.length < 2) return null
  const envelope = row.mc?.envelope
  const data: Array<Record<string, unknown>> = [
    {
      type: "scatter",
      mode: "lines",
      name: "Equity",
      x: dates,
      y: equity,
      line: { color: "#2563eb", width: 2 },
      hovertemplate: "%{x}<br>Equity %{y:.3f}<extra></extra>",
    },
  ]
  if (envelope?.p05?.length && envelope?.p95?.length) {
    data.push(
      {
        type: "scatter",
        mode: "lines",
        name: "MC p05",
        x: dates,
        y: envelope.p05,
        line: { color: "rgba(37, 99, 235, 0.18)", width: 1 },
        hoverinfo: "skip",
      },
      {
        type: "scatter",
        mode: "lines",
        name: "MC p95",
        x: dates,
        y: envelope.p95,
        fill: "tonexty",
        fillcolor: "rgba(37, 99, 235, 0.10)",
        line: { color: "rgba(37, 99, 235, 0.18)", width: 1 },
        hoverinfo: "skip",
      },
    )
  }
  if (envelope?.p50?.length) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: "MC p50",
      x: dates,
      y: envelope.p50,
      line: { color: "#94a3b8", width: 1, dash: "dash" },
      hovertemplate: "%{x}<br>MC p50 %{y:.3f}<extra></extra>",
    })
  }
  return makeFigure(data, {
    title: { text: "Equity curve", font: { size: 13 } },
    margin: { l: 48, r: 20, t: 36, b: 42 },
    legend: { orientation: "h", y: 1.08, x: 0 },
    xaxis: { title: "" },
    yaxis: { title: "Equity" },
  })
}

function makeDrawdownFigure(row: SignalBacktestResult): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const equity = validNumberSeries(row.equity)
  if (dates.length < 2 || equity.length < 2) return null
  const drawdown = drawdownFromEquity(equity)
  return makeFigure(
    [
      {
        type: "scatter",
        mode: "lines",
        name: "Drawdown",
        x: dates.slice(0, drawdown.length),
        y: drawdown,
        fill: "tozeroy",
        line: { color: "#dc2626", width: 1.8 },
        hovertemplate: "%{x}<br>Drawdown %{y:.2%}<extra></extra>",
      },
    ],
    {
      title: { text: "Drawdown curve", font: { size: 13 } },
      margin: { l: 48, r: 20, t: 36, b: 42 },
      xaxis: { title: "" },
      yaxis: { title: "Drawdown", tickformat: ".0%" },
    },
  )
}

function monthlyReturnGrid(dates: string[], equity: number[]) {
  const buckets = new Map<string, { year: number; month: number; start: number; end: number }>()
  for (let index = 0; index < Math.min(dates.length, equity.length); index += 1) {
    const value = equity[index]
    if (!Number.isFinite(value)) continue
    const date = new Date(dates[index])
    if (Number.isNaN(date.getTime())) continue
    const year = date.getUTCFullYear()
    const month = date.getUTCMonth()
    const key = `${year}-${month}`
    const existing = buckets.get(key)
    if (existing) {
      existing.end = value
    } else {
      buckets.set(key, { year, month, start: value, end: value })
    }
  }
  const years = Array.from(new Set(Array.from(buckets.values()).map((item) => item.year))).sort((a, b) => a - b)
  const z = years.map((year) =>
    Array.from({ length: 12 }, (_, month) => {
      const bucket = buckets.get(`${year}-${month}`)
      if (!bucket || bucket.start === 0) return null
      return bucket.end / bucket.start - 1
    }),
  )
  return { years, z }
}

function makeMonthlyHeatmapFigure(row: SignalBacktestResult): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const equity = validNumberSeries(row.equity)
  if (dates.length < 2 || equity.length < 2) return null
  const { years, z } = monthlyReturnGrid(dates, equity)
  if (years.length === 0) return null
  return makeFigure(
    [
      {
        type: "heatmap",
        x: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        y: years,
        z,
        colorscale: [
          [0, "#dc2626"],
          [0.5, "#f8fafc"],
          [1, "#059669"],
        ],
        zmid: 0,
        hovertemplate: "%{y} %{x}<br>%{z:.2%}<extra></extra>",
        colorbar: { tickformat: ".0%" },
      },
    ],
    {
      title: { text: "Monthly return heatmap", font: { size: 13 } },
      margin: { l: 44, r: 16, t: 36, b: 42 },
      xaxis: { title: "" },
      yaxis: { title: "" },
    },
  )
}

function strategyParamSummary(params: unknown) {
  if (!isRecord(params)) return ""
  return Object.entries(params)
    .filter(([, value]) => value != null && typeof value !== "object")
    .slice(0, 5)
    .map(([key, value]) => `${key.replace(/_/g, " ")}=${String(value)}`)
    .join(", ")
}

function strategyRepresentatives(row: SignalBacktestResult | null, evidence: SignalEvidence | undefined) {
  const diagnostics = isRecord(row?.signal_diagnostics) ? row?.signal_diagnostics : null
  const rawDiagnostics = Array.isArray(diagnostics?.representatives) ? diagnostics.representatives : []
  const diagnosticRows = rawDiagnostics.filter(isRecord).map((rep, index) => ({
    id: String(rep.variant_id ?? rep.family ?? rep.description ?? `diagnostic-${index}`),
    title: String(rep.description ?? rep.variant_id ?? rep.family ?? "Indicator rule"),
    meta: [rep.family, rep.archetype].filter(Boolean).join(" / "),
    params: strategyParamSummary(rep.params),
    current: finiteUnknown(rep.indicator_value),
    label: String(rep.signal_label ?? ""),
  }))
  const evidenceRows = (evidence?.contributors ?? []).map((item) => ({
    id: String(item.variant_id || `${item.category}:${item.family}:${item.description}`),
    title: item.description || item.variant_id || item.family,
    meta: [categoryText(item.category), item.family, item.archetype].filter(Boolean).join(" / "),
    params: strategyParamSummary(item.params),
    current: finiteNumber(item.indicator_value),
    label: item.signal_label,
  }))
  const seen = new Set<string>()
  return [...diagnosticRows, ...evidenceRows].filter((item) => {
    const key = item.id || `${item.title}:${item.meta}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function decisionReasons(candidate: QuantCandidate, row: SignalBacktestResult | null) {
  const metrics = row?.metrics
  const reasons = [
    candidate.fdrPass ? "FDR gate passed" : "FDR gate did not pass",
    candidate.nObs != null ? `${candidate.nObs} validation observations` : "Validation sample missing",
    candidate.adv == null || candidate.adv >= LIQUID_ADV ? "Liquidity gate acceptable" : `ADV below ${fmtAdv(LIQUID_ADV)}`,
  ]
  if (metrics) {
    reasons.push(`Backtest Sharpe ${fmtSigned(metrics.sharpe, 2)}`)
    reasons.push(`Max drawdown ${fmtPct(metrics.max_drawdown, 1)}`)
    reasons.push(`${metrics.n_trades ?? 0} realized trades`)
  } else {
    reasons.push(`Screen Sharpe ${fmtSigned(candidate.sharpe, 2)}`)
  }
  return reasons
}

function StrategyJustificationPanel({
  candidate,
  row,
  evidence,
}: {
  candidate: QuantCandidate
  row: SignalBacktestResult | null
  evidence: SignalEvidence | undefined
}) {
  const reps = strategyRepresentatives(row, evidence)
  return (
    <div className="rounded-md border border-line bg-card px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">Strategy justification</div>
          <div className="mt-1 text-sm font-semibold">{candidate.status} - IC {fmtSigned(candidate.ic, 3)}</div>
        </div>
        <Badge variant="outline" className={cn("text-[10px]", statusClass(candidate.status))}>{candidate.status}</Badge>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {decisionReasons(candidate, row).map((reason) => (
          <div key={reason} className="rounded-md border border-line bg-bg2 px-2.5 py-2 text-xs text-muted-foreground">
            {reason}
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">Indicator rules used</div>
        {reps.length === 0 ? (
          <div className="rounded-md border border-dashed border-line px-3 py-4 text-xs text-muted-foreground">
            Representative indicator details were not returned for this row.
          </div>
        ) : (
          reps.slice(0, 6).map((item) => (
            <div key={item.id} className="rounded-md border border-line px-3 py-2 text-xs">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-semibold">{item.title}</div>
                  <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{item.meta || "technical rule"}</div>
                </div>
                <div className="shrink-0 text-right font-mono tabular-nums">
                  <div>{fmt(item.current, 2)}</div>
                  <div className="text-[10px] text-muted-foreground">{item.label || "latest"}</div>
                </div>
              </div>
              {item.params ? <div className="mt-1 truncate text-[10px] text-muted-foreground">{item.params}</div> : null}
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function SignalTradeLedgerTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-5 text-center text-xs text-muted-foreground">
        No realized fills in this selected backtest window.
      </div>
    )
  }
  return (
    <div className="overflow-hidden rounded-md border border-line bg-card">
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <TableHead>Date</TableHead>
            <TableHead>Side</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead className="text-right">Exec</TableHead>
            <TableHead className="text-right">Position</TableHead>
            <TableHead className="text-right">Return</TableHead>
            <TableHead className="text-right">Realized PnL</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 14).map((row, index) => {
            const side = String(row.side ?? "--")
            return (
              <TableRow key={`${String(row.date ?? "")}-${index}`} className="text-xs">
                <TableCell className="font-mono">{String(row.date ?? "--").slice(0, 10)}</TableCell>
                <TableCell className={side.toUpperCase().includes("ACHAT") ? "font-semibold text-emerald-700" : "font-semibold text-red-700"}>{side}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finiteUnknown(row.global_score_pct), 1)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finiteUnknown(row.prix_execution), 2)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finiteUnknown(row.position), 0)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmtPct(finiteUnknown(row.return_cumule), 1)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finiteUnknown(row.pnl_realise), 2)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finiteUnknown(row.cout), 2)}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      {rows.length > 14 ? (
        <div className="border-t border-line px-3 py-2 text-[10px] text-muted-foreground">
          Showing first 14 of {rows.length} fills.
        </div>
      ) : null}
    </div>
  )
}

function SignalBacktestSurface({
  candidate,
  horizon,
  evidence,
  evidenceLoading,
  evidenceError,
}: {
  candidate: QuantCandidate
  horizon: EngineHorizon
  evidence: SignalEvidence | undefined
  evidenceLoading: boolean
  evidenceError: unknown
}) {
  const direction = selectedBacktestDirection(candidate)
  const backtest = useSWR<SignalBacktestResponse>(
    candidate.sourceType === "signal" ? ["quant-signal-backtest-surface", candidate.symbol, horizon, candidate.rawCategory, direction] : null,
    () =>
      fetchSignalBacktestResultsWithBootstrap(candidate.symbol, horizon, "expanded", {
        timeoutMs: 140_000,
        pollMs: 3_000,
        requireChartPayload: true,
        sidePolicy: "long_short",
        selectedDirection: direction,
        cooldownBars: 0,
        minPaths: 2000,
      }),
    { revalidateOnFocus: false },
  )

  if (backtest.isLoading || evidenceLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-56 rounded-lg" />
        <div className="grid gap-3 xl:grid-cols-3">
          <Skeleton className="h-52 rounded-lg" />
          <Skeleton className="h-52 rounded-lg" />
          <Skeleton className="h-52 rounded-lg" />
        </div>
      </div>
    )
  }

  const row = selectSignalBacktestResult(backtest.data, candidate)
  if (backtest.error || !row) {
    return (
      <div className="space-y-3">
        <WfoHistoricalPerformance evidence={evidence} isLoading={false} error={evidenceError || backtest.error} />
        <StrategyJustificationPanel candidate={candidate} row={null} evidence={evidence} />
      </div>
    )
  }

  const priceFigure = makePriceTradesFigure(row, candidate)
  const equityFigure = makeEquityFigure(row)
  const drawdownFigure = makeDrawdownFigure(row)
  const monthlyFigure = makeMonthlyHeatmapFigure(row)
  const metrics = row.metrics
  const ledgerRows = Array.isArray(row.trade_ledger) ? row.trade_ledger : []
  const windowLabel = `${row.window_start ?? "--"} to ${row.window_end ?? "--"}`

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <EvidenceMetric label="Backtest return" value={fmtPct(metrics.total_return, 1)} sub={windowLabel} tone={icTone(metrics.total_return)} />
        <EvidenceMetric label="Backtest Sharpe" value={fmtSigned(metrics.sharpe, 2)} sub={`${metrics.n_trades ?? "--"} trades`} tone={icTone(metrics.sharpe)} />
        <EvidenceMetric label="Max drawdown" value={fmtPct(metrics.max_drawdown, 1)} sub={`Win ${fmtPct(metrics.win_rate, 0)}`} tone="negative" />
        <EvidenceMetric label="Monte Carlo" value={fmtPct(row.mc.stats?.prob_positive_terminal, 0)} sub={`${row.mc.n_paths} paths`} tone="blue" />
      </div>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
        <div className="rounded-md border border-line bg-card p-2">
          {priceFigure ? <PlotlyChart figure={priceFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No price chart available.</div>}
        </div>
        <StrategyJustificationPanel candidate={candidate} row={row} evidence={evidence} />
      </div>
      <div className="rounded-md border border-line bg-card px-3 py-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">Trades ledger</div>
          <Badge variant="outline" className="text-[10px]">{row.source} / {row.scope_key}</Badge>
        </div>
        <SignalTradeLedgerTable rows={ledgerRows} />
      </div>
      <div className="grid gap-3 xl:grid-cols-3">
        <div className="rounded-md border border-line bg-card p-2">
          {equityFigure ? <PlotlyChart figure={equityFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No equity curve available.</div>}
        </div>
        <div className="rounded-md border border-line bg-card p-2">
          {drawdownFigure ? <PlotlyChart figure={drawdownFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No drawdown curve available.</div>}
        </div>
        <div className="rounded-md border border-line bg-card p-2">
          {monthlyFigure ? <PlotlyChart figure={monthlyFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No monthly heatmap available.</div>}
        </div>
      </div>
    </div>
  )
}

function WfoHistoricalPerformance({
  evidence,
  isLoading,
  error,
}: {
  evidence: SignalEvidence | undefined
  isLoading: boolean
  error: unknown
}) {
  if (isLoading) {
    return (
      <div className="rounded-md border border-line bg-card px-3 py-4">
        <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">Loading WFO historical performance</div>
        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Skeleton className="h-48 rounded-md" />
          <Skeleton className="h-48 rounded-md" />
        </div>
      </div>
    )
  }
  const stitched = evidence?.stitched_oos_backtest
  if (error || !stitched) {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-5 text-xs text-muted-foreground">
        WFO historical equity is unavailable for this selected signal. The aggregate analytics backtest below still shows IC, hit-rate, Sharpe and robustness.
      </div>
    )
  }
  const equity = numericSeries(stitched.equity)
  const close = numericSeries(stitched.close_series)
  const position = numericSeries(stitched.position_series)
  const dates = stringSeries(stitched.dates)
  if (equity.length < 2 && close.length < 2) {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-5 text-xs text-muted-foreground">
        WFO evidence loaded, but no dated equity or close series was returned.
      </div>
    )
  }
  const drawdown = drawdownFromEquity(equity)
  const normalizedClose = normalizedReturnPath(close)
  const periodLabel = `${compactDate(dates[0])} to ${compactDate(dates[dates.length - 1])}`
  const metrics = stitched.metrics
  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-4">
        <EvidenceMetric label="WFO return" value={fmtPct(metrics.total_return, 1)} sub={periodLabel} tone={icTone(metrics.total_return)} />
        <EvidenceMetric label="WFO Sharpe" value={fmtSigned(metrics.sharpe, 2)} sub={`${metrics.n_trades ?? "--"} trades`} tone={icTone(metrics.sharpe)} />
        <EvidenceMetric label="WFO max DD" value={fmtPct(metrics.max_drawdown, 1)} sub={`Win ${fmtPct(metrics.win_rate, 0)}`} tone="negative" />
        <EvidenceMetric label="Exposure" value={position.length ? fmt(avg(position.map((value) => Math.abs(value))), 2) : "--"} sub={stitched.direction || "direction missing"} />
      </div>
      <div className="grid gap-3 xl:grid-cols-2">
        <MiniLineChart
          title="Historical OOS equity and drawdown"
          subtitle="Dated stitched WFO path, net of configured costs"
          series={[
            { label: "Equity", values: equity, color: "#2563eb" },
            { label: "Drawdown", values: drawdown, color: "#dc2626" },
          ]}
        />
        <MiniLineChart
          title="Price path and exposure"
          subtitle="Close normalized to start; position shows when the rule was active"
          series={[
            { label: "Close ret", values: normalizedClose, color: "#0f766e" },
            { label: "Position", values: position, color: "#7c3aed" },
          ]}
        />
      </div>
    </div>
  )
}

function EvidenceSparkline({ chart }: { chart: Record<string, unknown> | undefined }) {
  const zscore = numericSeries(chart?.zscore)
  const targetReturn = numericSeries(chart?.target_return)
  const values = zscore.length > 0 ? zscore : targetReturn
  const label = zscore.length > 0 ? "Z-score history" : "Target-return history"
  const points = values.slice(-120)
  if (points.length < 2) {
    return <div className="flex h-28 items-center justify-center rounded-md border border-dashed border-line text-xs text-muted-foreground">No pair chart data.</div>
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const path = points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * 100
      const y = 100 - ((value - min) / span) * 100
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(" ")
  const zeroY = 100 - ((0 - min) / span) * 100
  return (
    <div className="rounded-md border border-line bg-card px-3 py-2">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{label}</div>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-28 w-full">
        {zeroY >= 0 && zeroY <= 100 ? <line x1="0" x2="100" y1={zeroY} y2={zeroY} className="stroke-muted-foreground/30" strokeWidth="0.8" vectorEffect="non-scaling-stroke" /> : null}
        <path d={path} fill="none" className="stroke-primary" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}

function methodSummary(candidate: QuantCandidate, horizon: EngineHorizon) {
  if (candidate.sourceType === "pair") {
    return "Validated with the stat-arb engine: pair construction, cointegration or lead-lag archetype, z-score state, FDR-adjusted p-value, OOS Sharpe, drawdown, fold profitability and explicit cost assumptions."
  }
  if (candidate.sourceType === "macro") {
    return "Validated with pre-registered macro factor rules: factor IC, t-stat, BH-FDR control, after-cost portfolio backtest, DSR/PSR robustness and bootstrap confidence intervals."
  }
  return `Validated through the category signal evaluation endpoint for the ${horizonLabel(horizon)} horizon: IC decay, conditional return t-stat, hit-rate confidence interval, after-cost portfolio stats and DSR/PSR bootstrap robustness.`
}

function thesisSummary(candidate: QuantCandidate) {
  if (candidate.sleeve === "trend") {
    return "The idea is to buy persistent strength or avoid persistent weakness when trend indicators have historically ranked forward returns correctly."
  }
  if (candidate.sleeve === "mean_reversion") {
    return "The idea is to fade statistically stretched oscillator states only when the historical bucket return and hit-rate evidence are strong enough."
  }
  if (candidate.sleeve === "volume") {
    return "The idea is to use volume and flow confirmation as an execution-quality filter, not as a standalone recommendation without validation."
  }
  if (candidate.sleeve === "macro") {
    return "The idea is to condition the stock on external risk factors such as VIX, Brent, DXY, rates or global equity indices, then trade only if the factor timing rule survives multiple-test control."
  }
  if (candidate.sleeve === "pairs") {
    return "The idea is to trade relative mispricing or lead-lag continuation only when the pair survives stationarity, FDR, OOS and drawdown gates."
  }
  return "The idea is to rank securities cross-sectionally and only trade names where the score has shown predictive power after statistical and liquidity gates."
}

function SignalBacktestEvidence({
  candidate,
  horizon,
}: {
  candidate: QuantCandidate
  horizon: EngineHorizon
}) {
  const history = useSWR<SignalEvidence>(
    candidate.sourceType === "signal" ? ["quant-signal-history", candidate.symbol, horizon] : null,
    () =>
      fetchSignalEvidence({
        symbol: candidate.symbol,
        horizon,
        source: "wfo",
        costBps: 33,
        proofLimit: "100",
      }),
    { revalidateOnFocus: false },
  )
  const evaluation = useSignalEvaluation(
    candidate.sourceType === "signal" ? candidate.symbol : null,
    candidate.sourceType === "signal" ? candidate.rawCategory : null,
    candidate.sourceType === "signal" ? horizon : null,
  )
  const report = evaluation.data

  if (evaluation.isLoading) {
    return <Skeleton className="h-56 w-full rounded-lg" />
  }
  if (evaluation.error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-3 text-xs text-red-700">
        Backtest unavailable for this category. Run or refresh the signal evaluation job for {candidate.symbol}.
      </div>
    )
  }
  if (!report) {
    return <div className="rounded-md border border-dashed border-line px-3 py-5 text-xs text-muted-foreground">Select a technical signal row to load its backtest.</div>
  }

  const p = report.portfolio
  const r = report.robustness
  return (
    <div className="space-y-3">
      <SignalBacktestSurface
        candidate={candidate}
        horizon={horizon}
        evidence={history.data}
        evidenceLoading={history.isLoading}
        evidenceError={history.error}
      />
      <div className="grid gap-2 sm:grid-cols-3">
        <EvidenceMetric label="Net Sharpe" value={fmtSigned(p.after_cost_sharpe, 2)} sub={`Gross ${fmtSigned(p.sharpe, 2)}`} tone={icTone(p.after_cost_sharpe)} />
        <EvidenceMetric label="Hit rate" value={fmtPct(report.hit_rate_h1, 1)} sub={`CI ${fmtPct(report.hit_rate_ci[0], 0)} to ${fmtPct(report.hit_rate_ci[1], 0)}`} tone={report.hit_rate_h1 >= 0.5 ? "positive" : "negative"} />
        <EvidenceMetric label="DSR / PSR" value={`${fmtPct(r.dsr, 0)} / ${fmtPct(r.psr, 0)}`} sub={`${r.n_variants} variants`} tone={r.dsr >= 0.7 ? "positive" : "neutral"} />
        <EvidenceMetric label="Cond. t-stat" value={fmtSigned(report.conditional_return_tstat, 2)} sub={`${report.n_obs} observations`} tone={icTone(report.conditional_return_tstat)} />
        <EvidenceMetric label="Drawdown" value={fmtPct(p.max_drawdown, 1)} sub={`Calmar ${fmtSigned(p.calmar, 2)}`} tone="negative" />
        <EvidenceMetric label="Trade stats" value={`${p.n_trades}`} sub={`PF ${fmt(p.profit_factor, 2)} - Turnover ${fmt(p.turnover, 2)}`} />
      </div>
      <ICDecayMiniChart report={report} />
      <div className="grid gap-2 sm:grid-cols-2">
        <EvidenceMetric
          label="IC bootstrap CI"
          value={`${fmtSigned(r.ic_bootstrap_ci[0], 3)} to ${fmtSigned(r.ic_bootstrap_ci[1], 3)}`}
          sub={`IC CV ${fmt(r.ic_cv, 2)}`}
        />
        <EvidenceMetric
          label="Sharpe bootstrap CI"
          value={`${fmtSigned(r.sharpe_bootstrap_ci[0], 2)} to ${fmtSigned(r.sharpe_bootstrap_ci[1], 2)}`}
          sub={`Sharpe CV ${fmt(r.sharpe_cv, 2)}`}
        />
      </div>
    </div>
  )
}

function FactorRelevanceEvidence({
  row,
  factorId,
}: {
  row: FactorRelevanceRow | null
  factorId: string | null
}) {
  if (!row) {
    return (
      <div className="rounded-md border border-dashed border-line px-3 py-4 text-xs text-muted-foreground">
        No direct factor relevance row for {factorId ?? "this factor"}.
      </div>
    )
  }
  return (
    <div className="grid gap-2 sm:grid-cols-5">
      <EvidenceMetric label="Factor" value={row.factor_id} sub="Relevance screen" />
      <EvidenceMetric label="IC" value={fmtSigned(row.ic, 3)} sub={`CV ${fmt(row.ic_cv, 2)}`} tone={icTone(row.ic)} />
      <EvidenceMetric label="t-stat" value={fmtSigned(row.t_stat, 2)} sub={`${row.n_obs} obs`} tone={icTone(row.t_stat)} />
      <EvidenceMetric label="p-value" value={fmt(row.p_value, 4)} sub={row.significant ? "Significant" : "Not significant"} tone={row.significant ? "positive" : "neutral"} />
      <EvidenceMetric label="Desk use" value={row.significant ? "Candidate" : "Reject"} sub="Needs portfolio test" tone={row.significant ? "blue" : "negative"} />
    </div>
  )
}

function MacroBacktestEvidence({ candidate, horizon }: { candidate: QuantCandidate; horizon: EngineHorizon }) {
  const forwardHorizon = HORIZONS.find((item) => item.value === horizon)?.fwd ?? 21
  const relevance = useFactorRelevance(candidate.sourceType === "macro" ? candidate.symbol : null, {
    returnMethod: "close_to_close",
    lookbackDays: 252,
    forwardHorizon,
  })
  const evaluation = useFactorSignalEval(candidate.sourceType === "macro" ? candidate.symbol : null, {
    returnMethod: "close_to_close",
    lookbackDays: 252,
  })
  const relevanceRows = relevance.data?.pairs ?? []
  const relevanceRow =
    relevanceRows.find((row) => row.factor_id.toUpperCase() === String(candidate.factorId ?? "").toUpperCase()) ??
    null
  const rows = evaluation.data ?? []
  const exactBacktest = rows.find((row) => row.factor_id.toUpperCase() === String(candidate.factorId ?? "").toUpperCase()) ?? null
  const rankedBacktests = [...rows].sort((left, right) => {
    const leftScore = Math.abs(finiteNumber(left.after_cost_sharpe) ?? 0) + Math.abs(finiteNumber(left.ic_h5) ?? 0)
    const rightScore = Math.abs(finiteNumber(right.after_cost_sharpe) ?? 0) + Math.abs(finiteNumber(right.ic_h5) ?? 0)
    return rightScore - leftScore
  })
  const preferred = exactBacktest ?? rankedBacktests[0]

  if (evaluation.isLoading || relevance.isLoading) {
    return <Skeleton className="h-56 w-full rounded-lg" />
  }
  if (evaluation.error && relevance.error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-3 text-xs text-red-700">
        Macro evidence unavailable. Check macro ingestion, factor relevance and factor evaluation jobs.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="rounded-md border border-line bg-bg2 px-3 py-2">
        <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">Factor relevance screen</div>
        <div className="mt-2">
          <FactorRelevanceEvidence row={relevanceRow} factorId={candidate.factorId} />
        </div>
      </div>
      {!exactBacktest ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          No direct portfolio backtest is registered for {candidate.factorId}. Treat this as a relevance signal only until a portfolio rule is added and tested.
        </div>
      ) : null}
      {!preferred ? (
        <div className="rounded-md border border-dashed border-line px-3 py-5 text-xs text-muted-foreground">
          No pre-registered macro portfolio backtest is available for this symbol.
        </div>
      ) : (
        <MacroBacktestSummary row={preferred} exact={Boolean(exactBacktest)} />
      )}
      {!exactBacktest && rankedBacktests.length > 0 ? (
        <div className="rounded-md border border-line bg-card">
          <div className="border-b border-line px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">
            Available pre-registered macro backtests for {candidate.symbol}
          </div>
          <div className="divide-y divide-line">
            {rankedBacktests.slice(0, 4).map((row) => (
              <div key={row.signal_name} className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] gap-2 px-3 py-2 text-xs">
                <div className="min-w-0">
                  <div className="font-mono font-semibold">{row.factor_id}</div>
                  <div className="truncate text-[10px] text-muted-foreground">{row.signal_name}</div>
                </div>
                <div className="font-mono tabular-nums">IC {fmtSigned(row.ic_h5, 3)}</div>
                <div className="font-mono tabular-nums">SR {fmtSigned(row.after_cost_sharpe, 2)}</div>
                <Badge variant="outline" className={cn("h-5 text-[10px]", row.fdr_pass && "border-emerald-300 bg-emerald-50 text-emerald-700")}>
                  {row.fdr_pass ? "FDR" : "screen"}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function MacroBacktestSummary({ row, exact }: { row: FactorSignalEval; exact: boolean }) {
  const p = row.portfolio
  const r = row.robustness
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <Badge variant="outline" className="text-[10px]">{row.factor_id}</Badge>
        <Badge variant="outline" className={cn("text-[10px]", exact ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-amber-300 bg-amber-50 text-amber-800")}>
          {exact ? "direct backtest match" : "nearest registered backtest"}
        </Badge>
        <Badge variant="outline" className={cn("text-[10px]", row.fdr_pass && "border-emerald-300 bg-emerald-50 text-emerald-700")}>
          {row.fdr_pass ? "BH-FDR pass" : "FDR not passed"}
        </Badge>
        <Badge variant="outline" className="text-[10px]">{row.signal_name}</Badge>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <EvidenceMetric label="IC d1 / d5" value={`${fmtSigned(row.ic_h1, 3)} / ${fmtSigned(row.ic_h5, 3)}`} sub={`n=${row.n_obs}`} tone={icTone(row.ic_h5)} />
        <EvidenceMetric label="Net Sharpe" value={fmtSigned(row.after_cost_sharpe, 2)} sub={`Gross ${fmtSigned(row.sharpe, 2)}`} tone={icTone(row.after_cost_sharpe)} />
        <EvidenceMetric label="DSR / PSR" value={`${fmtPct(row.dsr, 0)} / ${fmtPct(row.psr, 0)}`} sub="Multiple-test aware" tone={(finiteNumber(row.dsr) ?? 0) >= 0.7 ? "positive" : "neutral"} />
        <EvidenceMetric label="Hit rate" value={fmtPct(row.hit_rate, 1)} sub={`Cond t ${fmtSigned(row.conditional_return_tstat, 2)}`} tone={(finiteNumber(row.hit_rate) ?? 0.5) >= 0.5 ? "positive" : "negative"} />
        <EvidenceMetric label="Drawdown" value={fmtPct(p.max_drawdown, 1)} sub={`Return ${fmtPct(p.total_return, 1)}`} tone="negative" />
        <EvidenceMetric label="Profit factor" value={fmt(p.profit_factor, 2)} sub={`${p.n_trades} trades`} />
      </div>
      <MetricBarPanel
        title="Registered backtest profile"
        subtitle="Returned by the macro factor evaluation job"
        items={[
          { label: "Total ret", value: p.total_return, display: fmtPct(p.total_return, 1), tone: icTone(p.total_return) },
          { label: "Max DD", value: p.max_drawdown, display: fmtPct(p.max_drawdown, 1), tone: "negative" },
          { label: "Net Sharpe", value: row.after_cost_sharpe, display: fmtSigned(row.after_cost_sharpe, 2), tone: icTone(row.after_cost_sharpe) },
          { label: "Hit rate", value: row.hit_rate - 0.5, display: fmtPct(row.hit_rate, 1), tone: (finiteNumber(row.hit_rate) ?? 0.5) >= 0.5 ? "positive" : "negative" },
          { label: "DSR", value: row.dsr, display: fmtPct(row.dsr, 0), tone: (finiteNumber(row.dsr) ?? 0) >= 0.7 ? "positive" : "neutral" },
          { label: "PSR", value: row.psr, display: fmtPct(row.psr, 0), tone: (finiteNumber(row.psr) ?? 0) >= 0.7 ? "positive" : "neutral" },
        ]}
      />
      <ICDecayMiniChart report={row} />
      <div className="rounded-md border border-line bg-bg2 px-3 py-2 text-xs text-muted-foreground">
        Citation: {row.citation || "Pre-registered macro timing rule"}.
      </div>
    </div>
  )
}

function PairBacktestEvidence({ candidate }: { candidate: QuantCandidate }) {
  const detailState = useStatArbPairDetail(candidate.sourceType === "pair" ? candidate.pairId : null)
  const detail = detailState.data as StatArbPairDetail | undefined

  if (detailState.isLoading) {
    return <Skeleton className="h-56 w-full rounded-lg" />
  }
  if (detailState.error) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 px-3 py-3 text-xs text-red-700">
        Pair detail unavailable. Recompute stat-arb for this horizon.
      </div>
    )
  }
  if (!detail) {
    return <div className="rounded-md border border-dashed border-line px-3 py-5 text-xs text-muted-foreground">Select a pair row to load stat-arb evidence.</div>
  }

  return (
    <div className="space-y-3">
      <EvidenceSparkline chart={detail.chart} />
      <div className="grid gap-2 sm:grid-cols-3">
        <EvidenceMetric label="Signal state" value={detail.current_signal} sub={detail.action_type} />
        <EvidenceMetric label="Z-score" value={fmtSigned(detail.zscore, 2)} sub={`Half-life ${fmt(detail.half_life, 1)}`} tone={Math.abs(detail.zscore ?? 0) >= 2 ? "blue" : "neutral"} />
        <EvidenceMetric label="OOS Sharpe" value={fmtSigned(detail.oos_sharpe, 2)} sub={`Return ${fmtPct(detail.oos_return, 1)}`} tone={icTone(detail.oos_sharpe)} />
        <EvidenceMetric label="ADF / FDR" value={`${fmt(detail.adf_pvalue, 3)} / ${fmt(detail.fdr_qvalue, 3)}`} sub={`Raw p ${fmt(detail.raw_pvalue, 3)}`} tone={(detail.fdr_qvalue ?? 1) <= 0.1 ? "positive" : "neutral"} />
        <EvidenceMetric label="Drawdown" value={fmtPct(detail.max_drawdown, 1)} sub={`Profitable folds ${fmtPct(detail.profitable_fold_ratio, 0)}`} tone="negative" />
        <EvidenceMetric label="Costs" value={`${fmt(detail.cost_bps_per_side, 0)}+${fmt(detail.slippage_bps_per_side, 0)} bps`} sub={`Borrow ${fmt(detail.borrow_bps_annual, 0)} bps`} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <EvidenceMetric label="Hedge ratio" value={fmtSigned(detail.hedge_ratio, 3)} sub={`Intercept ${fmtSigned(detail.intercept, 3)}`} />
        <EvidenceMetric label="Coverage" value={`${detail.n_obs} obs`} sub={`${detail.n_folds} OOS folds - ${detail.data_as_of ?? "date missing"}`} />
      </div>
      {detail.warnings.length > 0 ? (
        <div className="flex flex-wrap gap-1">
          {detail.warnings.slice(0, 8).map((warning) => (
            <Badge key={warning} variant="outline" className="text-[10px] text-muted-foreground">{warning}</Badge>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function EvidencePanel({
  candidate,
  horizon,
}: {
  candidate: QuantCandidate | null
  horizon: EngineHorizon
}) {
  if (!candidate) {
    return (
      <div className="flex h-full min-h-[300px] items-center justify-center rounded-lg border border-dashed border-line bg-card px-4 text-center text-sm text-muted-foreground">
        Select a signal, macro factor, or pair to load the validation pack.
      </div>
    )
  }

  const validationMetric = screenValidationMetric(candidate)
  const evidenceBlock =
    candidate.sourceType === "signal" ? (
      <SignalBacktestEvidence candidate={candidate} horizon={horizon} />
    ) : candidate.sourceType === "macro" ? (
      <MacroBacktestEvidence candidate={candidate} horizon={horizon} />
    ) : (
      <PairBacktestEvidence candidate={candidate} />
    )

  return (
    <Card className="rounded-lg py-4">
      <CardHeader className="px-4 pb-0">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <CardTitle className="flex items-center gap-2 text-sm">
              <LineChart className="h-4 w-4 text-primary" />
              Quant backtest lab - <span className="truncate font-mono">{candidate.symbol}</span>
            </CardTitle>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <Badge variant="outline" className="text-[10px]">{candidate.sleeveLabel}</Badge>
              <Badge variant="outline" className={cn("text-[10px]", statusClass(candidate.status))}>{candidate.status}</Badge>
              <Badge variant="outline" className={cn("text-[10px]", biasClass(candidate.bias))}>{candidate.bias}</Badge>
            </div>
          </div>
          <div className="text-right">
            <div className="font-mono text-lg font-semibold tabular-nums">{fmt(candidate.edge, 0)}</div>
            <div className="text-[10px] uppercase tracking-[0.06em] text-muted-foreground">Screen score</div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pt-3">
        <div className="rounded-md border border-line bg-bg2 px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">Signal thesis</div>
          <p className="mt-1 text-xs text-foreground">{thesisSummary(candidate)}</p>
          <p className="mt-1 text-xs text-muted-foreground">{methodSummary(candidate, horizon)}</p>
        </div>
        {evidenceBlock}
        <div className="grid gap-2 md:grid-cols-4">
          <EvidenceMetric label="Rule" value={candidate.bias} sub={candidate.label} tone={candidate.bias === "Long" || candidate.bias === "Pair continuation" ? "positive" : candidate.bias === "Short" ? "negative" : "neutral"} />
          <EvidenceMetric label="Test window" value={horizon.toUpperCase()} sub={`${candidate.nObs ?? "--"} observations`} />
          <EvidenceMetric label="Multiple testing" value={candidate.fdrPass ? "Passed" : "Not passed"} sub={candidate.sourceType === "macro" ? "Relevance screen" : "Signal screen"} tone={candidate.fdrPass ? "positive" : "neutral"} />
          <EvidenceMetric label="Execution gate" value={candidate.status} sub={candidate.status === "Trade" ? "Eligible" : "Needs validation"} tone={candidate.status === "Trade" ? "positive" : candidate.status === "Reject" ? "negative" : "blue"} />
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <EvidenceMetric label="Screen IC" value={fmtSigned(candidate.ic, 3)} sub={candidate.category} tone={icTone(candidate.ic)} />
          <EvidenceMetric label={validationMetric.label} value={validationMetric.value} sub={validationMetric.sub} tone={validationMetric.tone} />
          <EvidenceMetric label="Liquidity" value={fmtAdv(candidate.adv)} sub={candidate.sector ?? "Sector missing"} tone={candidate.adv == null || candidate.adv >= LIQUID_ADV ? "blue" : "negative"} />
        </div>
      </CardContent>
    </Card>
  )
}

export function SignalQuantitativeView({
  selectedSymbol,
  onSelectSymbol,
}: {
  selectedSymbol: string | null
  onSelectSymbol?: (symbol: string) => void
}) {
  const router = useRouter()
  const [horizon, setHorizon] = useState<EngineHorizon>("medium")
  const [universe, setUniverse] = useState<UniverseFilter>("liquid")
  const [directionFilter, setDirectionFilter] = useState<DirectionFilter>("all")
  const [query, setQuery] = useState("")
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null)
  const horizonMeta = HORIZONS.find((item) => item.value === horizon) ?? HORIZONS[1]

  const signals = useAnalyticsSignalsOverview(null, horizon)
  const dashboard = useDashboardData(horizon)
  const factors = useFactorLeaderboard({
    forwardHorizon: horizonMeta.fwd,
    lookbackDays: 252,
    returnMethod: "close_to_close",
  })
  const statArb = useStatArbLeaderboard({ horizon, limit: 80 })
  const statArbStatus = useStatArbStatus()

  const advBySymbol = useMemo(() => {
    const map = new Map<string, number>()
    for (const stock of dashboard.data?.stocks ?? []) {
      const adv = finiteNumber(stock.adv)
      if (adv != null) map.set(stock.symbol, adv)
    }
    return map
  }, [dashboard.data])

  const sectorBySymbol = useMemo(() => {
    const map = new Map<string, string | null>()
    for (const stock of dashboard.data?.stocks ?? []) {
      map.set(stock.symbol, stock.sector)
    }
    return map
  }, [dashboard.data])

  const signalRows = signals.data ?? []
  const factorRows = factors.data ?? []
  const pairRows = statArb.data?.rows ?? []

  const signalCandidates = useMemo(() => {
    const baseRows = signalRows
    const all = baseRows.map((row) => candidateFromRow(row, "cross", advBySymbol, sectorBySymbol))
    const trend = baseRows
      .filter((row) => categoryMatches(row, ["tendance", "trend", "sma", "ema", "macd", "adx", "ichimoku", "psar"]))
      .map((row) => candidateFromRow(row, "trend", advBySymbol, sectorBySymbol))
    const meanReversion = baseRows
      .filter((row) => categoryMatches(row, ["oscillation", "oscillator", "rsi", "stochastic", "cci", "mfi", "uo"]))
      .map((row) => candidateFromRow(row, "mean_reversion", advBySymbol, sectorBySymbol))
    const volume = baseRows
      .filter((row) => categoryMatches(row, ["volume", "obv", "cmf", "vwap", "force", "accumulation", "distribution"]))
      .map((row) => candidateFromRow(row, "volume", advBySymbol, sectorBySymbol))

    return {
      cross: bestBySymbol(all),
      trend: bestBySymbol(trend),
      meanReversion: bestBySymbol(meanReversion),
      volume: bestBySymbol(volume),
    }
  }, [advBySymbol, sectorBySymbol, signalRows])

  const macroCandidates = useMemo(
    () => sortByEdge(factorRows.map((row) => macroCandidateFromRow(row, advBySymbol, sectorBySymbol))),
    [advBySymbol, factorRows, sectorBySymbol],
  )
  const pairCandidates = useMemo(() => sortByEdge(pairRows.map((row) => pairCandidateFromRow(row, advBySymbol))), [advBySymbol, pairRows])

  const allCandidates = useMemo(
    () =>
      sortByEdge([
        ...signalCandidates.cross,
        ...signalCandidates.trend,
        ...signalCandidates.meanReversion,
        ...signalCandidates.volume,
        ...macroCandidates,
        ...pairCandidates,
      ]),
    [macroCandidates, pairCandidates, signalCandidates],
  )

  const filteredCandidates = useMemo(
    () => filterCandidates(allCandidates, query, universe, directionFilter),
    [allCandidates, directionFilter, query, universe],
  )

  const selectedCandidate = useMemo(
    () => {
      const selectedById = allCandidates.find((candidate) => candidate.id === selectedCandidateId)
      if (selectedById && filterCandidates([selectedById], query, universe, directionFilter).length > 0) return selectedById
      const selectedBySymbol = selectedSymbol ? allCandidates.find((candidate) => candidate.symbol === selectedSymbol) : null
      if (selectedBySymbol && filterCandidates([selectedBySymbol], query, universe, directionFilter).length > 0) return selectedBySymbol
      return filteredCandidates[0] ?? null
    },
    [allCandidates, directionFilter, filteredCandidates, query, selectedCandidateId, selectedSymbol, universe],
  )

  function handleSelectCandidate(candidate: QuantCandidate) {
    setSelectedCandidateId(candidate.id)
    if (candidate.sourceType !== "pair" && !candidate.symbol.includes("/")) {
      onSelectSymbol?.(candidate.symbol)
    }
    router.push(quantStrategyDetailHref(candidate, horizon))
  }

  const summary = useMemo(() => {
    const icRows = signalRows.map((row) => firstNumber(row.ic_h5, row.ic_h1)).filter((value): value is number => value != null)
    const fdrPct = signalRows.length > 0 ? signalRows.filter((row) => row.fdr_pass).length / signalRows.length : null
    const tradeRows = filteredCandidates.filter((row) => row.status === "Trade")
    const longRows = filteredCandidates.filter((row) => row.bias === "Long" || row.bias === "Pair continuation")
    const shortRows = filteredCandidates.filter((row) => row.bias === "Short")
    return {
      avgIc: avg(icRows),
      fdrPct,
      tradeCount: tradeRows.length,
      longCount: longRows.length,
      shortCount: shortRows.length,
      best: filteredCandidates[0] ?? null,
      pairTradeCount: pairCandidates.filter((row) => row.status === "Trade").length,
    }
  }, [filteredCandidates, pairCandidates, signalRows])

  const latestStatArb = statArbStatus.data?.latest ?? null
  const latestStatArbStatus = latestStatArb && typeof latestStatArb.status === "string" ? latestStatArb.status : "idle"
  const loading = signals.isLoading || dashboard.isLoading

  return (
    <div className="h-full overflow-auto bg-background">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="grid h-9 w-9 place-items-center rounded-lg border border-line bg-card">
                <ShieldCheck className="h-4 w-4 text-primary" />
              </span>
              <div>
                <h1 className="text-lg font-semibold tracking-tight">Quantitative signal desk</h1>
                <p className="text-xs text-muted-foreground">
                  Classic signal families from IC, factor relevance, liquidity and pairs evidence.
                </p>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-md border border-line bg-card p-0.5">
              {HORIZONS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setHorizon(item.value)}
                  className={cn(
                    "h-8 rounded px-3 text-xs font-medium text-muted-foreground hover:bg-muted",
                    horizon === item.value && "bg-primary text-primary-foreground hover:bg-primary",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <select
              value={universe}
              onChange={(event) => setUniverse(event.target.value as UniverseFilter)}
              className="h-9 rounded-md border border-line bg-card px-3 text-xs"
            >
              <option value="liquid">Liquid ADV gate</option>
              <option value="all">All symbols</option>
            </select>
            <div className="flex rounded-md border border-line bg-card p-0.5">
              {[
                { value: "all", label: "All sides" },
                { value: "long", label: "Long only" },
                { value: "short", label: "Short only" },
              ].map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setDirectionFilter(item.value as DirectionFilter)}
                  className={cn(
                    "h-8 rounded px-3 text-xs font-medium text-muted-foreground hover:bg-muted",
                    directionFilter === item.value && "bg-primary text-primary-foreground hover:bg-primary",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <div className="relative w-56">
              <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search symbol or signal"
                className="h-9 pl-7 text-xs"
              />
            </div>
          </div>
        </div>

        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-5">
          <MetricTile
            label="Universe IC"
            value={fmtSigned(summary.avgIc, 3)}
            sub={`${signalRows.length} signal rows - ${horizonMeta.label}`}
            tone={(summary.avgIc ?? 0) >= 0 ? "positive" : "negative"}
          />
          <MetricTile
            label="FDR discipline"
            value={summary.fdrPct == null ? "--" : `${(summary.fdrPct * 100).toFixed(1)}%`}
            sub="Rows passing multiple-test gate"
            tone="blue"
          />
          <MetricTile
            label="Actionable"
            value={String(summary.tradeCount)}
            sub={`${summary.longCount} long-biased - ${summary.shortCount} short-biased`}
            tone="positive"
          />
          <MetricTile
            label="Pairs book"
            value={String(summary.pairTradeCount)}
            sub={`Stat-arb job ${latestStatArbStatus}`}
            tone="blue"
          />
          <MetricTile
            label="Best idea"
            value={summary.best?.symbol ?? "--"}
            sub={summary.best ? `${summary.best.sleeveLabel} - ${fmt(summary.best.edge, 0)} edge` : "No candidate"}
          />
        </div>

        {loading ? (
          <div className="grid gap-3 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-48 rounded-lg" />
            ))}
          </div>
        ) : (
          <div className="grid gap-3 xl:grid-cols-3">
            <SleeveCard sleeve="cross" rows={filterCandidates(signalCandidates.cross, query, universe, directionFilter)} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={handleSelectCandidate} />
            <SleeveCard sleeve="trend" rows={filterCandidates(signalCandidates.trend, query, universe, directionFilter)} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={handleSelectCandidate} />
            <SleeveCard sleeve="mean_reversion" rows={filterCandidates(signalCandidates.meanReversion, query, universe, directionFilter)} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={handleSelectCandidate} />
            <SleeveCard sleeve="volume" rows={filterCandidates(signalCandidates.volume, query, universe, directionFilter)} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={handleSelectCandidate} />
            <SleeveCard sleeve="macro" rows={filterCandidates(macroCandidates, query, universe, directionFilter)} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={handleSelectCandidate} />
            <SleeveCard sleeve="pairs" rows={filterCandidates(pairCandidates, query, universe, directionFilter)} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={handleSelectCandidate} />
          </div>
        )}

        <div className="grid gap-3">
          <Card className="rounded-lg py-4">
            <CardHeader className="px-4 pb-0">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-primary" />
                  Actionable quant blotter
                </CardTitle>
                <div className="text-xs text-muted-foreground">
                  Ranked by evidence strength, cost-adjusted quality and validation gates.
                </div>
              </div>
            </CardHeader>
            <CardContent className="px-4 pt-3">
              <BlotterTable rows={filteredCandidates} selectedCandidateId={selectedCandidate?.id ?? null} onSelectCandidate={handleSelectCandidate} />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
