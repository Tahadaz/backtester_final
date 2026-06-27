"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { ArrowRight, ChevronDown, ChevronUp, ChevronsUpDown, Columns3 } from "lucide-react"
import type { DashboardFundamentals, DashboardStock } from "@/lib/dashboard-types"
import {
  DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS,
  FUNDAMENTAL_COLUMNS,
  type DashboardFundamentalColumn,
} from "@/lib/dashboard-preferences"
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format"
import { SignalBadge } from "./signal-badge"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { cn } from "@/lib/utils"

type SortDir = "asc" | "desc"
type SortKey =
  | "symbol"
  | "price"
  | "var1j"
  | "direction"
  | "value"
  | "quality"
  | "upside"
  | "fair_value"
  | "pe"
  | "dividend_yield"
  | "coverage"
  | "source"

interface FundamentalDirectionsTabProps {
  stocks: DashboardStock[]
  columns?: DashboardFundamentalColumn[]
  onColumnsChange?: (columns: DashboardFundamentalColumn[]) => void
}

const COLUMN_LABELS: Record<DashboardFundamentalColumn, string> = {
  value: "Value",
  quality: "Quality",
  upside: "Upside",
  fair_value: "Fair value",
  pe: "P/E",
  dividend_yield: "Div. yield",
  coverage: "Coverage",
  source: "Source",
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

function upsideToSignalScore(value: number | null | undefined): number | null {
  const upside = finite(value)
  return upside == null ? null : Math.max(-100, Math.min(100, upside * 250))
}

export function fundamentalSignalScore(fundamentals: DashboardFundamentals | null | undefined): number | null {
  if (!fundamentals) return null
  return upsideToSignalScore(fundamentals.upside_pct)
}

export function fundamentalDirectionForStock(stock: DashboardStock): "long" | "short" | "none" | "missing" {
  const score = fundamentalSignalScore(stock.fundamentals)
  if (score == null) return "missing"
  if (score > 15) return "long"
  if (score < -15) return "short"
  return "none"
}

function fundamentalSignalLabel(fundamentals: DashboardFundamentals | null | undefined): string {
  const score = fundamentalSignalScore(fundamentals)
  if (score == null) return "Indisponible"
  if (score > 50) return "Achat fort"
  if (score > 15) return "Achat"
  if (score >= -15) return "Neutre"
  if (score >= -50) return "Vente"
  return "Vente forte"
}

function confidenceTone(value: string | null | undefined) {
  if (value === "high") return "border-emerald-400/40 bg-emerald-500/10 text-emerald-700"
  if (value === "medium") return "border-sky-400/40 bg-sky-500/10 text-sky-700"
  if (value === "low") return "border-amber-400/40 bg-amber-500/10 text-amber-800"
  return "text-muted-foreground"
}

function sourceLabel(value: string | null | undefined) {
  if (value === "yfinance") return "yfinance"
  if (value === "workbook") return "Workbook"
  return "--"
}

function columnValue(fundamentals: DashboardFundamentals | null | undefined, key: SortKey): number | string | null {
  if (key === "symbol") return null
  if (!fundamentals) return null
  if (key === "direction") return fundamentalSignalScore(fundamentals)
  if (key === "value") return finite(fundamentals.value_score)
  if (key === "quality") return finite(fundamentals.quality_score)
  if (key === "upside") return finite(fundamentals.upside_pct)
  if (key === "fair_value") return finite(fundamentals.fair_value)
  if (key === "pe") return finite(fundamentals.pe)
  if (key === "dividend_yield") return finite(fundamentals.dividend_yield)
  if (key === "coverage") return finite(fundamentals.coverage_pct)
  if (key === "source") return sourceLabel(fundamentals.data_source)
  return null
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

function formatColumnValue(fundamentals: DashboardFundamentals | null | undefined, key: DashboardFundamentalColumn) {
  if (!fundamentals) return "--"
  if (key === "upside" || key === "dividend_yield") return formatPercent(columnValue(fundamentals, key) as number | null)
  if (key === "fair_value") return formatCurrency(fundamentals.fair_value)
  if (key === "coverage") {
    const value = finite(fundamentals.coverage_pct)
    return value == null ? "--" : `${value.toFixed(0)}%`
  }
  if (key === "source") return sourceLabel(fundamentals.data_source)
  return formatNumber(columnValue(fundamentals, key) as number | null, key === "pe" ? 2 : 1)
}

function asOfLabel(value: string | null | undefined) {
  if (!value) return "--"
  return value.slice(0, 10)
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active) return <ChevronsUpDown className="h-3 w-3" />
  return dir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
}

export function FundamentalDirectionsTab({
  stocks,
  columns = DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS,
  onColumnsChange,
}: FundamentalDirectionsTabProps) {
  const [sortKey, setSortKey] = useState<SortKey>("upside")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const visibleColumns = useMemo(
    () => columns.filter((column) => FUNDAMENTAL_COLUMNS.includes(column)),
    [columns],
  )

  const sorted = useMemo(() => {
    const sortValueFor = (stock: DashboardStock): number | string | null => {
      if (sortKey === "symbol") return stock.symbol
      if (sortKey === "price") return priceForDisplay(stock)
      if (sortKey === "var1j") return oneDayVarPct(stock)
      return columnValue(stock.fundamentals, sortKey)
    }
    return [...stocks].sort((left, right) => {
      const primary = compareValues(sortValueFor(left), sortValueFor(right), sortDir)
      return primary !== 0 ? primary : left.symbol.localeCompare(right.symbol)
    })
  }, [stocks, sortDir, sortKey])

  const covered = useMemo(
    () => stocks.filter((stock) => stock.fundamentals?.upside_pct != null).length,
    [stocks],
  )

  function onSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortDir((current) => (current === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(nextKey)
    setSortDir("desc")
  }

  function toggleColumn(column: DashboardFundamentalColumn, checked: boolean) {
    if (!onColumnsChange) return
    const next = checked
      ? [...visibleColumns, column]
      : visibleColumns.filter((item) => item !== column)
    onColumnsChange(next.length ? next : DEFAULT_DASHBOARD_FUNDAMENTAL_COLUMNS)
  }

  if (stocks.length === 0) {
    return <div className="dashboard-panel px-4 py-12 text-center text-sm text-muted-foreground">Aucune action ne correspond aux filtres.</div>
  }

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <div>
          <h3 className="dashboard-section-title">Directions fondamentales</h3>
          <div className="dashboard-meta">{sorted.length} lignes - {covered} couvertes</div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-8 gap-1.5 rounded-md text-[12px]">
              <Columns3 className="h-3.5 w-3.5" />
              Colonnes
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52">
            <DropdownMenuLabel>Fondamental</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {FUNDAMENTAL_COLUMNS.map((column) => (
              <DropdownMenuCheckboxItem
                key={column}
                checked={visibleColumns.includes(column)}
                onCheckedChange={(checked) => toggleColumn(column, checked === true)}
              >
                {COLUMN_LABELS[column]}
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <div className="grid gap-2 bg-background p-2 md:hidden">
        {sorted.map((stock) => {
          const fundamentals = stock.fundamentals ?? null
          const href = `/signals?mode=fundamental&symbol=${encodeURIComponent(stock.symbol)}`
          return (
            <article key={`fund-mobile-${stock.symbol}`} className="rounded-lg border border-border bg-card px-3 py-3 shadow-xs">
              <div className="flex min-w-0 items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link href={href} className="dashboard-mono text-[14px] font-bold hover:underline">{stock.symbol}</Link>
                  <div className="truncate text-[12px] text-muted-foreground">{stock.display_name ?? "-"}</div>
                  {(() => {
                    const var1j = oneDayVarPct(stock)
                    return (
                      <div className="mt-1 flex items-center gap-2 text-[12px]">
                        <span className="dashboard-mono font-semibold">{formatNumber(priceForDisplay(stock), 2)}</span>
                        <span className={cn("dashboard-mono", var1j != null ? (var1j >= 0 ? "dashboard-text-positive" : "dashboard-text-negative") : "text-muted-foreground")}>
                          {formatVarPct(var1j)}
                        </span>
                      </div>
                    )
                  })()}
                </div>
                <SignalBadge label={fundamentalSignalLabel(fundamentals)} />
              </div>
              <div className="mt-3 grid grid-cols-3 gap-2 border-t border-border pt-2">
                <div>
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Upside</div>
                  <div className={cn("dashboard-mono mt-0.5 text-[13px] font-semibold", (fundamentals?.upside_pct ?? 0) > 0 ? "dashboard-text-positive" : (fundamentals?.upside_pct ?? 0) < 0 ? "dashboard-text-negative" : undefined)}>
                    {formatPercent(fundamentals?.upside_pct)}
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Value</div>
                  <div className="dashboard-mono mt-0.5 text-[13px] font-semibold">{formatNumber(fundamentals?.value_score, 1)}</div>
                </div>
                <div className="text-right">
                  <div className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Quality</div>
                  <div className="dashboard-mono mt-0.5 text-[13px] font-semibold">{formatNumber(fundamentals?.quality_score, 1)}</div>
                </div>
              </div>
              <Link href={href} className="mt-3 inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md border border-border bg-bg2 text-[12px] font-semibold text-foreground">
                Voir detail
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </article>
          )
        })}
      </div>

      <div className="hidden overflow-x-auto md:block">
        <Table className="min-w-[1120px] text-[12px]">
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
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort("direction")}>
                  Direction
                  <SortIcon active={sortKey === "direction"} dir={sortDir} />
                </button>
              </TableHead>
              {visibleColumns.map((column) => (
                <TableHead key={column} className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  <button type="button" className="inline-flex items-center gap-1" onClick={() => onSort(column)}>
                    {COLUMN_LABELS[column]}
                    <SortIcon active={sortKey === column} dir={sortDir} />
                  </button>
                </TableHead>
              ))}
              <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Confidence</TableHead>
              <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">As of</TableHead>
              <TableHead className="h-auto w-10 px-2 py-2" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((stock) => {
              const fundamentals = stock.fundamentals ?? null
              const href = `/signals?mode=fundamental&symbol=${encodeURIComponent(stock.symbol)}`
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
                  {(() => {
                    const var1j = oneDayVarPct(stock)
                    return (
                      <TableCell
                        className={cn(
                          "dashboard-mono px-3 py-2.5 text-right text-[11px]",
                          var1j != null ? (var1j >= 0 ? "dashboard-text-positive" : "dashboard-text-negative") : undefined,
                        )}
                      >
                        {formatVarPct(var1j)}
                      </TableCell>
                    )
                  })()}
                  <TableCell className="px-3 py-2.5">
                    <SignalBadge label={fundamentalSignalLabel(fundamentals)} />
                  </TableCell>
                  {visibleColumns.map((column) => (
                    <TableCell
                      key={`${stock.symbol}-${column}`}
                      className={cn(
                        "dashboard-mono px-3 py-2.5 text-right text-[11px]",
                        (column === "upside" || column === "dividend_yield") && (columnValue(fundamentals, column) as number | null) != null
                          ? ((columnValue(fundamentals, column) as number) >= 0 ? "dashboard-text-positive" : "dashboard-text-negative")
                          : undefined,
                      )}
                    >
                      {formatColumnValue(fundamentals, column)}
                    </TableCell>
                  ))}
                  <TableCell className="px-3 py-2.5">
                    <Badge variant="outline" className={cn("text-[10px]", confidenceTone(fundamentals?.confidence))}>
                      {fundamentals?.confidence ?? "--"}
                    </Badge>
                  </TableCell>
                  <TableCell className="dashboard-mono px-3 py-2.5 text-right text-[11px] text-muted-foreground">
                    {asOfLabel(fundamentals?.as_of)}
                  </TableCell>
                  <TableCell className="px-2 py-2.5 align-middle">
                    <Button asChild variant="ghost" size="icon" className="h-7 w-7 rounded-md">
                      <Link href={href} aria-label={`Voir fundamentals ${stock.symbol}`}>
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Link>
                    </Button>
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
