"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { ArrowRight, BookOpen, ChevronDown, ChevronUp, ChevronsUpDown, Star } from "lucide-react"
import type { EdgeMetrics } from "@/lib/api"
import type {
  DashboardBestSignal,
  DashboardBestTechnicalSignal,
  DashboardDisplayMode,
  DashboardScoreSource,
  DashboardStock,
  Horizon,
} from "@/lib/dashboard-types"
import { FAMILY_ORDER } from "@/lib/dashboard-constants"
import { formatPercent } from "@/lib/format"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import { cn } from "@/lib/utils"

type SortDir = "asc" | "desc"
type SortKey =
  | "symbol"
  | "price"
  | "adv"
  | "signal"
  | "best_signal"
  | "technical_signal"
  | "expected_return"
  | "hit_rate"
  | "edge"
  | (typeof FAMILY_ORDER)[number]
type FamilyKey = (typeof FAMILY_ORDER)[number]

interface StockTableProps {
  stocks: DashboardStock[]
  horizon: Horizon
  horizonDays: number
  signalView?: "legacy" | "expanded" | "factor_x_ta"
  scoreSource?: DashboardScoreSource
  displayMode?: DashboardDisplayMode
  hideDetails?: boolean
  showTechnicalLevels?: boolean
  edgeEnabled?: boolean
  edgeMode?: "gross" | "net"
  edgeSource?: "signal_engine" | "wfo"
  edgeMap?: Record<string, EdgeMetrics | null | undefined>
  visibleFamilies?: Partial<Record<FamilyKey, boolean>>
  selectedSymbols?: ReadonlySet<string>
  onToggleSelected?: (symbol: string) => void
  onOpenEdge?: (stock: DashboardStock) => void
}

function horizonLabel(horizon: Horizon) {
  if (horizon === "weekly") return "court"
  if (horizon === "monthly") return "moyen"
  if (horizon === "quarterly") return "long"
  if (horizon === "medium") return "moyen"
  if (horizon === "long") return "long"
  return "court"
}

function resolveSeFamily(stock: DashboardStock, family: string, signalView: "legacy" | "expanded" | "factor_x_ta") {
  const se = stock.scores.signal_engine
  const familyMap = signalView === "factor_x_ta"
    ? se.factor_x_ta_per_family
    : signalView === "expanded"
      ? (se.expanded_per_family ?? se.per_family)
      : se.per_family
  return familyMap?.[family] ?? null
}

function resolveFactorDependencies(stock: DashboardStock, family: string, signalView: "legacy" | "expanded" | "factor_x_ta") {
  if (signalView !== "factor_x_ta") return undefined
  return stock.scores.signal_engine.factor_dependencies?.[family]
}

function priceForDisplay(stock: DashboardStock): number | null {
  return stock.last_price ?? stock.scores.signal_engine.technical_levels?.close_used ?? null
}

function isActionableBestSignal(signal: DashboardBestSignal | null | undefined): signal is DashboardBestSignal {
  if (!signal) return false
  if (signal.direction === "none" || signal.bucket === "hold") return false
  if (signal.bucket === "buy" || signal.bucket === "strong_buy") return signal.direction === "long"
  if (signal.bucket === "sell" || signal.bucket === "strong_sell") return signal.direction === "short"
  return false
}

function bestSignalForDisplay(stock: DashboardStock): DashboardBestSignal | null {
  const signal = stock.best_signal ?? null
  if (signal?.source !== "wfo") return null
  if (!isActionableBestSignal(signal)) return null
  if (signal.action_expected_return_net == null || signal.hit_rate == null) return null
  return signal
}

function technicalSignalForDisplay(stock: DashboardStock): DashboardBestTechnicalSignal | null {
  const signal = stock.best_technical_signal ?? null
  if (!signal) return null
  if (signal.score_pct == null || !Number.isFinite(signal.score_pct)) return null
  return signal
}

function technicalFamilyForDisplay(stock: DashboardStock, family: string) {
  return technicalSignalForDisplay(stock)?.per_family?.[family] ?? null
}

function technicalFactorDependencies(stock: DashboardStock, family: string) {
  return technicalSignalForDisplay(stock)?.factor_dependencies?.[family]
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

function formatVarPct(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(2)}%`
}

function varToneClass(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value) || value === 0) return "dashboard-text-muted"
  return value > 0 ? "dashboard-text-positive" : "dashboard-text-negative"
}

function bestSignalActionLabel(signal: DashboardBestSignal | null | undefined) {
  if (!signal) return "--"
  if (signal.direction === "long") return "Long"
  if (signal.direction === "short") return "Short"
  return "No trade"
}

function bestSignalHoldingPeriodLabel(signal: DashboardBestSignal | null | undefined, fallbackDays?: number) {
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

type EdgeTriage = "proven" | "watch" | "insufficient" | "hold" | "missing"

function bestSignalTriage(signal: DashboardBestSignal | null | undefined): EdgeTriage {
  if (!signal) return "missing"
  if (signal.direction === "none" || signal.bucket === "hold") return "hold"
  if ((signal.n ?? 0) < 30) return "insufficient"
  return signal.proven_edge_net ? "proven" : "watch"
}

function shortMethodLabel(signal: DashboardBestSignal | null | undefined) {
  if (!signal) return "No eligible WFO edge"
  return signal.label
    .replace("Signal Engine - ", "Engine ")
    .replace("Factor x TA", "FX")
    .replace("Simple", "")
    .trim()
}

function bucketSignalLabel(bucket: string | null | undefined) {
  if (bucket === "strong_buy") return "Achat fort"
  if (bucket === "buy") return "Achat"
  if (bucket === "sell") return "Vente"
  if (bucket === "strong_sell") return "Vente forte"
  if (bucket === "hold") return "Neutre"
  return "Indisponible"
}

function bestSignalLabel(signal: DashboardBestSignal | null | undefined) {
  return signal?.signal_label ?? bucketSignalLabel(signal?.bucket)
}

function signalViewForVariant(variant: string | null | undefined): "legacy" | "expanded" | "factor_x_ta" {
  const token = String(variant ?? "").toLowerCase()
  if (token.includes("factor_x_ta")) return "factor_x_ta"
  if (token.includes("legacy")) return "legacy"
  return "expanded"
}

function sourceLabel(source: "signal_engine" | "wfo" | string | null | undefined) {
  return source === "wfo" ? "WFO" : "Signal Engine"
}

function displayVariantLabel(variant: string | null | undefined) {
  const value = String(variant ?? "").trim()
  if (!value) return "--"
  return value.startsWith("sv_") ? "Selected indicator" : value
}

function formatScorePct(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(1)}`
}

function EdgeBadge({ triage }: { triage: EdgeTriage }) {
  if (triage === "insufficient")
    return <span className="text-[11px] font-semibold text-muted-foreground">&lt;30 OOS</span>
  if (triage === "hold")
    return <span className="text-[11px] font-semibold text-muted-foreground">Hold</span>
  if (triage === "missing")
    return <span className="text-[11px] text-muted-foreground">No action.</span>
  if (triage === "proven")
    return (
      <span className="dashboard-chip-positive inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold">
        <Star className="h-2.5 w-2.5" />
        Prouvé
      </span>
    )
  if (triage === "watch")
    return (
      <span className="dashboard-action-warning inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-semibold">
        À surveiller
      </span>
    )
  return <span className="text-[11px] text-muted-foreground">—</span>
}

function GlossaryHelpLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="inline-flex h-4 w-4 items-center justify-center rounded text-muted-foreground/70 hover:bg-background hover:text-foreground"
      aria-label={label}
      title={label}
    >
      <BookOpen className="h-3 w-3" />
    </Link>
  )
}

function BestSignalMethodCell({ signal }: { signal: DashboardBestSignal | null }) {
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
          n={signal.n ?? "--"}
        </span>
      </div>
    </div>
  )
}

function BestSignalBadgeCell({ signal }: { signal: DashboardBestSignal | null }) {
  if (!signal) return <SignalBadge label="Indisponible" />
  return <SignalBadge label={bestSignalLabel(signal)} />
}

function BestSignalExpectedReturnCell({
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

export function StockTable({
  stocks,
  horizon,
  horizonDays,
  signalView = "expanded",
  scoreSource = "wfo",
  displayMode = "trade_opportunities",
  hideDetails = false,
  edgeEnabled = true,
  visibleFamilies,
  selectedSymbols,
  onToggleSelected,
}: StockTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("expected_return")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const isTechnicalMode = displayMode === "technical_directions"

  const shownFamilies = useMemo(
    () => FAMILY_ORDER.filter((family) => visibleFamilies?.[family] !== false),
    [visibleFamilies],
  )

  useEffect(() => {
    if (FAMILY_ORDER.includes(sortKey as FamilyKey) && !shownFamilies.includes(sortKey as FamilyKey)) {
      setSortKey(isTechnicalMode ? "technical_signal" : "expected_return")
      setSortDir("desc")
    }
  }, [isTechnicalMode, shownFamilies, sortKey])

  useEffect(() => {
    if (isTechnicalMode && ["best_signal", "expected_return", "hit_rate", "edge"].includes(sortKey)) {
      setSortKey("technical_signal")
      setSortDir("desc")
    }
    if (!isTechnicalMode && sortKey === "technical_signal") {
      setSortKey("expected_return")
      setSortDir("desc")
    }
  }, [isTechnicalMode, sortKey])

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
        leftValue = isTechnicalMode ? technicalSignalForDisplay(left)?.score_pct ?? null : bestSignalForDisplay(left)?.score ?? null
        rightValue = isTechnicalMode ? technicalSignalForDisplay(right)?.score_pct ?? null : bestSignalForDisplay(right)?.score ?? null
      } else if (sortKey === "best_signal") {
        leftValue = bestSignalForDisplay(left)?.score ?? null
        rightValue = bestSignalForDisplay(right)?.score ?? null
      } else if (sortKey === "technical_signal") {
        leftValue = technicalSignalForDisplay(left)?.abs_score_pct ?? null
        rightValue = technicalSignalForDisplay(right)?.abs_score_pct ?? null
      } else if (sortKey === "expected_return") {
        leftValue = bestSignalForDisplay(left)?.action_expected_return_net ?? null
        rightValue = bestSignalForDisplay(right)?.action_expected_return_net ?? null
      } else if (sortKey === "hit_rate") {
        leftValue = bestSignalForDisplay(left)?.hit_rate ?? null
        rightValue = bestSignalForDisplay(right)?.hit_rate ?? null
      } else if (sortKey === "edge") {
        const order: Record<EdgeTriage, number> = { proven: 4, watch: 3, insufficient: 2, hold: 1, missing: 0 }
        leftValue = order[bestSignalTriage(bestSignalForDisplay(left))]
        rightValue = order[bestSignalTriage(bestSignalForDisplay(right))]
      } else {
        leftValue = isTechnicalMode
          ? technicalFamilyForDisplay(left, sortKey)?.score_pct ?? null
          : scoreSource === "wfo"
            ? left.scores.wfo?.per_family[sortKey]?.score_pct ?? null
            : resolveSeFamily(left, sortKey, signalView)?.score_pct ?? null
        rightValue = isTechnicalMode
          ? technicalFamilyForDisplay(right, sortKey)?.score_pct ?? null
          : scoreSource === "wfo"
            ? right.scores.wfo?.per_family[sortKey]?.score_pct ?? null
            : resolveSeFamily(right, sortKey, signalView)?.score_pct ?? null
      }

      const primary = compareValues(leftValue, rightValue, sortDir)
      if (primary !== 0) return primary
      return left.symbol.localeCompare(right.symbol)
    })
  }, [stocks, sortKey, sortDir, scoreSource, signalView, isTechnicalMode])

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

  const tableMinWidthClass = !isTechnicalMode
    ? "min-w-[980px]"
    : shownFamilies.length === 0
      ? "min-w-[940px]"
      : shownFamilies.length < FAMILY_ORDER.length
        ? "min-w-[1040px]"
        : "min-w-[1160px]"

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <h3 className="dashboard-section-title">Signaux par titre · Horizon {horizonLabel(horizon)} ({horizonDays} j)</h3>
        <div className="dashboard-meta">{sorted.length} lignes · triées par retour attendu</div>
      </div>

      <Table className={cn(tableMinWidthClass, "text-[12px]")}>
        <TableHeader>
          <TableRow className="border-b border-border bg-bg2 hover:bg-bg2">
            {onToggleSelected ? (
              <TableHead className="h-auto w-9 px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground" />
            ) : null}
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
              <span className="inline-flex items-center justify-end gap-1">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("adv")}>
                  ADV20 MAD
                  <SortIcon columnKey="adv" />
                </button>
                <GlossaryHelpLink href="/glossary#adv20" label="Definition ADV20" />
              </span>
            </TableHead>
            {isTechnicalMode && !hideDetails && shownFamilies.includes("tendance") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Trend.
                  <GlossaryHelpLink href="/glossary#tendance" label="Definition Tendance" />
                </span>
              </TableHead>
            ) : null}
            {isTechnicalMode && !hideDetails && shownFamilies.includes("momentum") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Mom.
                  <GlossaryHelpLink href="/glossary#momentum" label="Definition Momentum" />
                </span>
              </TableHead>
            ) : null}
            {isTechnicalMode && !hideDetails && shownFamilies.includes("oscillation") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Osc.
                  <GlossaryHelpLink href="/glossary#oscillation" label="Definition Oscillation" />
                </span>
              </TableHead>
            ) : null}
            {isTechnicalMode && !hideDetails && shownFamilies.includes("volume") ? (
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center gap-1">
                  Vol.
                  <GlossaryHelpLink href="/glossary#volume" label="Definition Volume" />
                </span>
              </TableHead>
            ) : null}
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort(isTechnicalMode ? "technical_signal" : "signal")}>
                  {isTechnicalMode ? "Direction best" : "Signal"}
                  <SortIcon columnKey={isTechnicalMode ? "technical_signal" : "signal"} />
                </button>
                <GlossaryHelpLink href="/glossary#signal-badge" label="Definition Badge signal" />
              </span>
            </TableHead>
            <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort(isTechnicalMode ? "technical_signal" : "best_signal")}>
                  {isTechnicalMode ? "Methode technique" : "Methode auto"}
                  <SortIcon columnKey={isTechnicalMode ? "technical_signal" : "best_signal"} />
                </button>
                <GlossaryHelpLink href="/glossary#best-signal" label="Definition Meilleure methode auto" />
              </span>
            </TableHead>
            {isTechnicalMode ? (
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("technical_signal")}>
                  Score technique
                  <SortIcon columnKey="technical_signal" />
                </button>
              </TableHead>
            ) : (
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <span className="inline-flex items-center justify-end gap-1">
                  <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("expected_return")}>
                    retour attendu
                    <SortIcon columnKey="expected_return" />
                  </button>
                  <GlossaryHelpLink href="/glossary#action-er" label="Definition Action E[R]" />
                </span>
              </TableHead>
            )}
            {!isTechnicalMode && edgeEnabled ? (
              <>
                <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <span className="inline-flex items-center justify-end gap-1">
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("hit_rate")}>
                      %succés
                      <SortIcon columnKey="hit_rate" />
                    </button>
                    <GlossaryHelpLink href="/glossary#hit-rate" label="Definition Hit rate" />
                  </span>
                </TableHead>
                <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <span className="inline-flex items-center gap-1">
                    <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("edge")}>
                      Edge
                      <SortIcon columnKey="edge" />
                    </button>
                    <GlossaryHelpLink href="/glossary#edge" label="Definition Edge" />
                  </span>
                </TableHead>
              </>
            ) : null}
            <TableHead className="h-auto w-10 px-2 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((stock) => {
            const bestSignal = bestSignalForDisplay(stock)
            const technicalSignal = technicalSignalForDisplay(stock)
            const signalViewQuery = isTechnicalMode
              ? signalViewForVariant(technicalSignal?.variant)
              : scoreSource === "wfo"
                ? "expanded"
                : signalView
            const evidenceVariant = isTechnicalMode ? technicalSignal?.variant : bestSignal?.variant
            const evidenceSource = isTechnicalMode
              ? technicalSignal?.source ?? "auto"
              : bestSignal?.source ?? "auto"
            const evidenceHref = signalEvidenceUrl({
              symbol: stock.symbol,
              horizon,
              view: evidenceVariant ?? signalViewQuery,
              source: evidenceSource,
              evidenceVariant,
              tab: isTechnicalMode ? "technique" : "evidence",
            })
            const selected = selectedSymbols?.has(stock.symbol) ?? false

            return (
              <TableRow key={stock.symbol} className="border-b border-border/70 hover:bg-bg2">
                {onToggleSelected ? (
                  <TableCell className="px-2 py-2.5 align-middle">
                    <Checkbox
                      checked={selected}
                      onCheckedChange={() => onToggleSelected(stock.symbol)}
                      aria-label={`Select ${stock.symbol}`}
                    />
                  </TableCell>
                ) : null}
                <TableCell className="px-3 py-2.5 align-middle">
                  <Link href={evidenceHref} className="dashboard-mono text-[12px] font-semibold hover:underline">
                    {stock.symbol}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[220px] px-3 py-2.5">
                  <Link
                    href={evidenceHref}
                    className="block hover:underline"
                  >
                    <div className="text-[12px] font-medium">{stock.display_name ?? "-"}</div>
                  </Link>
                </TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">{formatNumber(priceForDisplay(stock))}</TableCell>
                <TableCell className={cn("dashboard-mono px-3 py-2.5 text-right text-[11px] font-semibold", varToneClass(stock.var1j_pct))}>
                  {formatVarPct(stock.var1j_pct)}
                </TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px] text-muted-foreground">{formatNumber(stock.adv ?? null, 0)}</TableCell>
                {isTechnicalMode && !hideDetails && shownFamilies.includes("tendance") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "tendance")} factorDependencies={technicalFactorDependencies(stock, "tendance")} /></TableCell>
                ) : null}
                {isTechnicalMode && !hideDetails && shownFamilies.includes("momentum") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "momentum")} factorDependencies={technicalFactorDependencies(stock, "momentum")} /></TableCell>
                ) : null}
                {isTechnicalMode && !hideDetails && shownFamilies.includes("oscillation") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "oscillation")} factorDependencies={technicalFactorDependencies(stock, "oscillation")} /></TableCell>
                ) : null}
                {isTechnicalMode && !hideDetails && shownFamilies.includes("volume") ? (
                  <TableCell className="px-3 py-2.5"><FamilyCell score={technicalFamilyForDisplay(stock, "volume")} factorDependencies={technicalFactorDependencies(stock, "volume")} /></TableCell>
                ) : null}
                <TableCell className="px-3 py-2.5">
                  {isTechnicalMode ? <SignalBadge label={technicalSignal?.signal_label ?? "Indisponible"} /> : <BestSignalBadgeCell signal={bestSignal} />}
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  {isTechnicalMode ? (
                    technicalSignal ? (
                      <div className="space-y-1">
                        <div className="max-w-[180px] truncate text-[11px] font-semibold" title={technicalSignal.label}>
                          {technicalSignal.label.replace("Signal Engine - ", "Engine ").replace("Factor x TA", "FX").trim()}
                        </div>
                        <div className="dashboard-mono text-[10px] text-muted-foreground">
                          {sourceLabel(technicalSignal.source)} - {displayVariantLabel(technicalSignal.variant)}
                        </div>
                      </div>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">No technical signal</span>
                    )
                  ) : <BestSignalMethodCell signal={bestSignal} />}
                </TableCell>
                <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px]">
                  <Link href={evidenceHref} className="block hover:text-foreground hover:underline">
                    {isTechnicalMode ? (
                      <div className="space-y-0.5 text-right">
                        <div>{formatScorePct(technicalSignal?.score_pct)}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {technicalSignal?.direction === "long" ? "Long" : technicalSignal?.direction === "short" ? "Short" : "Neutre"}
                        </div>
                      </div>
                    ) : (
                      <BestSignalExpectedReturnCell signal={bestSignal} fallbackDays={horizonDays} />
                    )}
                  </Link>
                </TableCell>
                {!isTechnicalMode && edgeEnabled ? (
                  <>
                    <TableCell className="px-3 py-2.5 text-right">
                      {bestSignal ? (
                        <div className="space-y-0.5 text-right">
                          <div className="dashboard-mono text-[11px]">{formatPercent(bestSignal.hit_rate ?? null)}</div>
                          <div className="dashboard-mono text-[10px] text-muted-foreground">
                            [{bestSignal.hit_ci_lower?.toFixed(2) ?? "--"}, {bestSignal.hit_ci_upper?.toFixed(2) ?? "--"}]
                          </div>
                        </div>
                      ) : (
                        <span className="dashboard-mono text-[10px] text-muted-foreground">No actionable</span>
                      )}
                    </TableCell>
                    <TableCell className="px-3 py-2.5">
                      <EdgeBadge triage={bestSignalTriage(bestSignal)} />
                    </TableCell>
                  </>
                ) : null}
                <TableCell className="px-2 py-2.5 align-middle">
                  <Link
                    href={evidenceHref}
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
    </div>
  )
}
