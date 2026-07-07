"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { ArrowRight, ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react"
import type { FundamentalCrossSectionRow, ValueSignalRow } from "@/lib/api"
import type { DashboardFundamentals, DashboardStock } from "@/lib/dashboard-types"
import type { DashboardFundamentalColumn } from "@/lib/dashboard-preferences"
import { formatCurrency, formatNumber } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"

// Note: the legacy SFC composite panel/table columns and the DashboardFundamentals
// value/quality/coverage/confidence columns were removed here on 2026-07-07 per direct
// product feedback -- this table is now the canonical B/M + CF/P value-signal ranking only.
// The six-vintage strategy backtest panel moved to the Signal page's fundamental view
// ("Stratégie de valeur" tab, frontend/components/strategy/fundamental/tabs/strategie-tab.tsx)
// rather than living inside this stock-ranking table.

type SortDir = "asc" | "desc"
type SortKey = "symbol" | "bm_rank" | "cfp_rank" | "price" | "var1j"

interface FundamentalDirectionsTabProps {
  stocks: DashboardStock[]
  // Retained for call-site compatibility with v1/page.tsx (unused by this simplified table).
  columns?: DashboardFundamentalColumn[]
  onColumnsChange?: (columns: DashboardFundamentalColumn[]) => void
  sfcRowsBySymbol?: Record<string, FundamentalCrossSectionRow | undefined>
  sfcAsOf?: string | null
  sfcValidationLabel?: string | null
  valueSignalBySymbol?: Record<string, ValueSignalRow | undefined>
}

function finite(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function pctChange(endPrice: number | null | undefined, startPrice: number | null | undefined): number | null {
  if (endPrice == null || startPrice == null || !Number.isFinite(endPrice) || !Number.isFinite(startPrice) || startPrice === 0) return null
  return ((endPrice - startPrice) / startPrice) * 100
}

// Current price, preferring a fresh live quote, then the last official close.
function priceForDisplay(stock: DashboardStock): number | null {
  const quote = stock.live_quote
  const livePrice = quote?.is_fresh && quote.last_price != null ? quote.last_price : null
  return livePrice ?? stock.last_price ?? stock.scores.signal_engine.technical_levels?.close_used ?? null
}

// Daily variation in percentage points (not a fraction), live-quote aware.
function oneDayVarPct(stock: DashboardStock): number | null {
  const quote = stock.live_quote
  const livePrice = quote?.is_fresh && quote.last_price != null ? quote.last_price : null
  if (livePrice != null) return pctChange(livePrice, quote?.prev_close ?? stock.prev_close)
  return stock.performance?.one_day?.pct ?? stock.var1j_pct ?? null
}

function formatVarPct(value: number | null): string {
  if (value == null) return "--"
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`
}

function valueBadgeTone(eligible: boolean | undefined): string {
  if (eligible) return "border-emerald-400/40 bg-emerald-500/10 text-emerald-700"
  return "border-border bg-muted text-muted-foreground"
}

function formatPercentile(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${Math.round(value * 100)}e`
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

function asOfLabel(value: string | null | undefined) {
  if (!value) return "--"
  return value.slice(0, 10)
}

function fairValueHref(symbol: string): string {
  return `/signals?mode=fundamental&symbol=${encodeURIComponent(symbol)}&fund_tab=valuation`
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <ChevronsUpDown className="h-3 w-3" />
  return dir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
}

export function FundamentalDirectionsTab({
  stocks,
  valueSignalBySymbol = {},
}: FundamentalDirectionsTabProps) {
  const [sortKey, setSortKey] = useState<SortKey>("bm_rank")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const sorted = useMemo(() => {
    const sortValueFor = (stock: DashboardStock): number | string | null => {
      if (sortKey === "symbol") return stock.symbol
      if (sortKey === "price") return priceForDisplay(stock)
      if (sortKey === "var1j") return oneDayVarPct(stock)
      if (sortKey === "bm_rank") {
        const rank = valueSignalBySymbol[stock.symbol.toUpperCase()]?.bm_rank
        return rank == null ? null : -rank
      }
      if (sortKey === "cfp_rank") {
        const rank = valueSignalBySymbol[stock.symbol.toUpperCase()]?.cfp_rank
        return rank == null ? null : -rank
      }
      return null
    }
    return [...stocks].sort((left, right) => {
      const primary = compareValues(sortValueFor(left), sortValueFor(right), sortDir)
      return primary !== 0 ? primary : left.symbol.localeCompare(right.symbol)
    })
  }, [valueSignalBySymbol, stocks, sortDir, sortKey])

  function onSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortDir((current) => (current === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(nextKey)
    setSortDir("desc")
  }

  if (stocks.length === 0) {
    return <div className="dashboard-panel px-4 py-12 text-center text-sm text-muted-foreground">Aucune action ne correspond aux filtres.</div>
  }

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <div>
          <h3 className="dashboard-section-title">Classement par action — Valeur structurelle (B/M) &amp; Valeur cash-flow (CF/P)</h3>
          <div className="dashboard-meta">{sorted.length} lignes</div>
        </div>
      </div>

      <div className="grid gap-2 bg-background p-2 md:hidden">
        {sorted.map((stock) => {
          const valueRow = valueSignalBySymbol[stock.symbol.toUpperCase()]
          const var1j = oneDayVarPct(stock)
          return (
            <article key={`fund-mobile-${stock.symbol}`} className="rounded-lg border border-border bg-card px-3 py-3 shadow-xs">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link href={fairValueHref(stock.symbol)} className="dashboard-mono text-[14px] font-bold hover:underline">{stock.symbol}</Link>
                  <div className="truncate text-[12px] text-muted-foreground">{stock.display_name ?? "-"}</div>
                  <div className="mt-1 flex items-center gap-2 text-[12px]">
                    <span className="dashboard-mono font-semibold">{formatNumber(priceForDisplay(stock), 2)}</span>
                    <span className={cn("dashboard-mono", var1j != null ? (var1j >= 0 ? "dashboard-text-positive" : "dashboard-text-negative") : "text-muted-foreground")}>
                      {formatVarPct(var1j)}
                    </span>
                  </div>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-2">
                <div>
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Rang B/M</div>
                  <div className="mt-0.5">
                    {valueRow?.eligible_bm ? (
                      <Badge variant="outline" className={cn("dashboard-mono text-[10px]", valueBadgeTone(true))}>{formatPercentile(valueRow.bm_percentile)}</Badge>
                    ) : (
                      <span className="text-[10px] text-muted-foreground">Exclu</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Rang CF/P</div>
                  <div className="mt-0.5">
                    {valueRow == null ? "--" : !valueRow.cfp_applicable ? (
                      <span className="text-[10px] text-muted-foreground">N/A</span>
                    ) : valueRow.eligible_cfp ? (
                      <Badge variant="outline" className={cn("dashboard-mono text-[10px]", valueBadgeTone(true))}>{formatPercentile(valueRow.cfp_percentile)}</Badge>
                    ) : (
                      <span className="text-[10px] text-muted-foreground">Exclu</span>
                    )}
                  </div>
                </div>
              </div>
              <Link href={fairValueHref(stock.symbol)} className="mt-3 inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-border bg-bg2 text-[12px] font-semibold text-foreground">
                Voir la valorisation
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </article>
          )
        })}
      </div>

      <div className="hidden overflow-x-auto md:block">
        <Table className="text-[12px]">
          <TableHeader>
            <TableRow className="border-b border-border bg-bg2 hover:bg-bg2">
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("symbol")}>
                  Ticker
                  <SortIcon active={sortKey === "symbol"} dir={sortDir} />
                </button>
              </TableHead>
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Nom</TableHead>
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("price")}>
                  Prix
                  <SortIcon active={sortKey === "price"} dir={sortDir} />
                </button>
              </TableHead>
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("var1j")}>
                  Var. 1j
                  <SortIcon active={sortKey === "var1j"} dir={sortDir} />
                </button>
              </TableHead>
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("bm_rank")}>
                  Rang B/M (par action)
                  <SortIcon active={sortKey === "bm_rank"} dir={sortDir} />
                </button>
              </TableHead>
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("cfp_rank")}>
                  Rang CF/P (par action)
                  <SortIcon active={sortKey === "cfp_rank"} dir={sortDir} />
                </button>
              </TableHead>
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Valeur cible</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((stock) => {
              const valueRow = valueSignalBySymbol[stock.symbol.toUpperCase()]
              const var1j = oneDayVarPct(stock)
              const href = fairValueHref(stock.symbol)
              return (
                <TableRow key={stock.symbol} className="border-b border-border/70 hover:bg-bg2">
                  <TableCell className="px-3 py-2.5 align-middle">
                    <Link href={href} className="dashboard-mono text-[12px] font-semibold hover:underline">{stock.symbol}</Link>
                  </TableCell>
                  <TableCell className="max-w-[220px] px-3 py-2.5">
                    <Link href={href} className="block hover:underline">
                      <div className="truncate text-[12px] font-medium">{stock.display_name ?? "-"}</div>
                      <div className="truncate text-[10px] text-muted-foreground">{stock.sector ?? stock.market_region ?? "-"}</div>
                    </Link>
                  </TableCell>
                  <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px] font-semibold">
                    {formatNumber(priceForDisplay(stock), 2)}
                  </TableCell>
                  <TableCell
                    className={cn(
                      "dashboard-mono px-3 py-2.5 text-right text-[11px]",
                      var1j != null ? (var1j >= 0 ? "dashboard-text-positive" : "dashboard-text-negative") : undefined,
                    )}
                  >
                    {formatVarPct(var1j)}
                  </TableCell>
                  <TableCell className="px-3 py-2.5 text-right">
                    {valueRow?.eligible_bm ? (
                      <Badge variant="outline" className={cn("dashboard-mono text-[10px]", valueBadgeTone(true))}>
                        {formatPercentile(valueRow.bm_percentile)}
                      </Badge>
                    ) : (
                      <span className="text-[10px] text-muted-foreground" title={valueRow?.exclusion_reasons?.join(" ") ?? "Signal indisponible"}>
                        Exclu
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="px-3 py-2.5 text-right">
                    {valueRow == null ? (
                      "--"
                    ) : !valueRow.cfp_applicable ? (
                      <span className="text-[10px] text-muted-foreground" title="Non applicable : secteur bancaire/assurance exclu par la politique canonique CF/P.">
                        N/A
                      </span>
                    ) : valueRow.eligible_cfp ? (
                      <Badge variant="outline" className={cn("dashboard-mono text-[10px]", valueBadgeTone(true))}>
                        {formatPercentile(valueRow.cfp_percentile)}
                      </Badge>
                    ) : (
                      <span className="text-[10px] text-muted-foreground" title={valueRow.exclusion_reasons.join(" ")}>
                        Exclu
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="px-3 py-2.5 text-right">
                    <Link
                      href={href}
                      className="dashboard-mono inline-flex items-center gap-1 text-[11px] font-semibold text-primary hover:underline"
                      title="Cliquer pour voir comment cette valeur cible est construite (modèles, hypothèses)"
                    >
                      {formatCurrency(stock.fundamentals?.fair_value ?? null)}
                      <ArrowRight className="h-3 w-3" />
                    </Link>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
