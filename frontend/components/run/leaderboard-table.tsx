"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { SignalBadge } from "@/components/signal-badge"
import { Skeleton } from "@/components/ui/skeleton"
import { formatDate, formatNumber, formatPercent } from "@/lib/format"
import { ArrowUpDown, BookOpen, Download, Search } from "lucide-react"
import type { LeaderboardRow } from "@/lib/api"

type SortField = "cagr" | "pnl" | "efficiency" | "n_fills" | "signal_today"
type SortDir = "asc" | "desc"

const RANK_OPTIONS: { value: SortField; label: string }[] = [
  { value: "cagr", label: "CAGR" },
  { value: "pnl", label: "PnL" },
  { value: "efficiency", label: "Efficiency" },
  { value: "n_fills", label: "# Fills" },
  { value: "signal_today", label: "Signal Value" },
]

function parseBestParams(raw: unknown): Record<string, unknown> {
  if (!raw) return {}
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
      return {}
    } catch {
      return {}
    }
  }
  if (typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Record<string, unknown>
  }
  return {}
}

function bestParamsPreview(raw: unknown): string {
  const obj = parseBestParams(raw)
  const entries = Object.entries(obj)
  if (!entries.length) return "--"
  return entries
    .slice(0, 3)
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(", ")
}

function escapeCsvCell(value: unknown): string {
  if (value === null || value === undefined) return ""
  const raw = typeof value === "object" ? (JSON.stringify(value) ?? "") : String(value)
  const escaped = raw.replaceAll("\"", "\"\"")
  return /[",\n\r]/.test(raw) ? `"${escaped}"` : escaped
}

export function LeaderboardTable({
  rows,
  isLoading,
  bestOnly,
  onBestOnlyChange,
  symbolFilter,
  onSymbolFilterChange,
  onRowClick,
  showSymbolColumn = true,
}: {
  rows: LeaderboardRow[] | undefined
  isLoading: boolean
  bestOnly: boolean
  onBestOnlyChange: (v: boolean) => void
  symbolFilter: string
  onSymbolFilterChange: (v: string) => void
  onRowClick?: (row: LeaderboardRow) => void
  showSymbolColumn?: boolean
}) {
  const [sortField, setSortField] = useState<SortField>("cagr")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const sortedRows = useMemo(() => {
    if (!rows) return []
    return [...rows].sort((a, b) => {
      const aVal = Number(a[sortField] ?? 0)
      const bVal = Number(b[sortField] ?? 0)
      return sortDir === "desc" ? bVal - aVal : aVal - bVal
    })
  }, [rows, sortField, sortDir])

  function toggleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))
      return
    }
    setSortField(field)
    setSortDir("desc")
  }

  function downloadCSV() {
    if (!sortedRows.length) return
    const headers = [
      "symbol",
      "strategy_kind",
      "rank",
      "pnl",
      "cagr",
      "efficiency",
      "n_fills",
      "signal_label",
      "signal_today",
      "signal_date",
      "best_params_json",
      "plot_url",
      "ledger_url",
    ]
    const csv = [
      headers.join(","),
      ...sortedRows.map((row) =>
        headers
          .map((header) => escapeCsvCell(row[header as keyof LeaderboardRow]))
          .join(",")
      ),
    ].join("\n")
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const link = document.createElement("a")
    link.href = url
    link.download = "leaderboard.csv"
    link.click()
    URL.revokeObjectURL(url)
  }

  const SortHeader = ({ field, label }: { field: SortField; label: string }) => (
    <button
      type="button"
      onClick={() => toggleSort(field)}
      className="flex items-center gap-0.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
    >
      {label}
      <ArrowUpDown className="h-3 w-3 opacity-40" />
    </button>
  )

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Strategy Leaderboard</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 5 }).map((_, idx) => (
            <Skeleton key={idx} className="h-10 rounded-lg" />
          ))}
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <CardTitle className="text-base">Strategy Leaderboard</CardTitle>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <Label className="whitespace-nowrap text-xs text-muted-foreground">Rank by</Label>
              <Select
                value={sortField}
                onValueChange={(value) => {
                  setSortField(value as SortField)
                  setSortDir("desc")
                }}
              >
                <SelectTrigger className="h-8 w-36 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RANK_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value} className="text-xs">
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Filter symbol..."
                value={symbolFilter}
                onChange={(event) => onSymbolFilterChange(event.target.value)}
                className="h-8 w-40 pl-8 text-xs"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <Switch id="bestOnly" checked={bestOnly} onCheckedChange={onBestOnlyChange} />
              <Label htmlFor="bestOnly" className="text-xs text-muted-foreground">
                Best only
              </Label>
            </div>
            <Button variant="outline" size="sm" asChild className="h-8 gap-1 text-xs">
              <Link href="/glossary#backtest" target="_blank">
                <BookOpen className="h-3 w-3" />
                Definitions
              </Link>
            </Button>
            <Button variant="outline" size="sm" onClick={downloadCSV} className="h-8 gap-1 text-xs">
              <Download className="h-3 w-3" />
              CSV
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        {!sortedRows.length ? (
          <div className="py-12 text-center text-sm text-muted-foreground">
            No leaderboard data available
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  {showSymbolColumn && (
                    <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                      Symbol
                    </th>
                  )}
                  <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Strategy
                  </th>
                  <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Rank
                  </th>
                  <th className="px-3 py-2.5 text-right">
                    <SortHeader field="pnl" label="PnL" />
                  </th>
                  <th className="px-3 py-2.5 text-right">
                    <SortHeader field="cagr" label="CAGR" />
                  </th>
                  <th className="px-3 py-2.5 text-right">
                    <SortHeader field="efficiency" label="Eff." />
                  </th>
                  <th className="px-3 py-2.5 text-right">
                    <SortHeader field="n_fills" label="Fills" />
                  </th>
                  <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Best Params
                  </th>
                  <th className="px-3 py-2.5 text-center text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Signal
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((row, idx) => (
                  <tr
                    key={`${row.symbol}-${row.strategy_kind}-${idx}`}
                    className="cursor-pointer border-b border-border/50 transition-colors hover:bg-secondary/50"
                    onClick={() => onRowClick?.(row)}
                  >
                    {showSymbolColumn && (
                      <td className="px-3 py-2.5 font-mono text-xs font-semibold text-foreground">
                        {row.symbol}
                      </td>
                    )}
                    <td className="px-3 py-2.5">
                      <div className="text-xs font-semibold text-foreground">{row.strategy_kind}</div>
                      {row.signal_date && (
                        <div className="text-[10px] text-muted-foreground">
                          {formatDate(row.signal_date)}
                        </div>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs">{row.rank ?? "--"}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs">{formatNumber(row.pnl)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs">
                      <span className={(row.cagr ?? 0) >= 0 ? "text-[oklch(0.45_0.15_165)]" : "text-destructive"}>
                        {formatPercent(row.cagr)}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs">{formatNumber(row.efficiency)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-xs">{row.n_fills ?? "--"}</td>
                    <td className="max-w-[280px] px-3 py-2.5 font-mono text-[11px] text-muted-foreground">
                      <span className="line-clamp-2">{bestParamsPreview(row.best_params_json)}</span>
                    </td>
                    <td className="px-3 py-2.5 text-center">
                      <SignalBadge value={row.signal_today} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="border-t border-border px-3 py-2.5 text-xs text-muted-foreground">
          {sortedRows.length} {sortedRows.length === 1 ? "strategy" : "strategies"}
          {symbolFilter && ` matching "${symbolFilter}"`} .
          <span className="ml-1">
            Backend leaderboard currently provides: `pnl`, `cagr`, `efficiency`, `n_fills`, signals.
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
