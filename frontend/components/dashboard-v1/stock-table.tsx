"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import type { DashboardStock, Horizon } from "@/lib/dashboard-types"
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
import { Input } from "@/components/ui/input"
import { ChevronDown, ChevronUp, ChevronsUpDown, Eye, EyeOff, Search } from "lucide-react"

interface StockTableProps {
  stocks: DashboardStock[]
  horizon: Horizon
  signalView?: "legacy" | "expanded"
}

type SortDir = "asc" | "desc"

function getSortValue(stock: DashboardStock, key: string, signalView: "legacy" | "expanded"): number | string {
  if (key === "symbol") return stock.symbol
  if (key === "sector") return stock.sector ?? ""
  if (key === "aggregate_score_pct") {
    return signalView === "expanded"
      ? (stock.expanded_aggregate_score_pct ?? -999)
      : (stock.aggregate_score_pct ?? -999)
  }
  const familyMap = signalView === "expanded" ? (stock.expanded_per_family || stock.per_family) : stock.per_family
  const family = familyMap[key]
  return family ? family.score_pct : -999
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

export function StockTable({ stocks, horizon, signalView = "legacy" }: StockTableProps) {
  const [search, setSearch] = useState("")
  const [sectorFilter, setSectorFilter] = useState<string>("all")
  const [hideUnavailable, setHideUnavailable] = useState(false)
  const [sortKey, setSortKey] = useState<string>("aggregate_score_pct")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const sectors = useMemo(() => {
    const set = new Set(
      stocks.map((stock) => stock.sector).filter((sector): sector is string => Boolean(sector)),
    )
    return ["all", ...Array.from(set).sort()]
  }, [stocks])

  const filtered = useMemo(() => {
    let result = stocks

    if (hideUnavailable) {
      result = result.filter((stock) => stock.aggregate_score_pct != null)
    }

    if (search) {
      const query = search.toLowerCase()
      result = result.filter(
        (stock) =>
          stock.symbol.toLowerCase().includes(query) ||
          (stock.display_name ?? "").toLowerCase().includes(query),
      )
    }

    if (sectorFilter !== "all") {
      result = result.filter((stock) => stock.sector === sectorFilter)
    }

    return result
  }, [stocks, search, sectorFilter, hideUnavailable])

  const sorted = useMemo(() => {
    return filtered
      .map((stock, index) => ({ stock, index }))
      .sort((left, right) => {
        const leftValue = getSortValue(left.stock, sortKey, signalView)
        const rightValue = getSortValue(right.stock, sortKey, signalView)

        let comparison = 0
        if (typeof leftValue === "string" && typeof rightValue === "string") {
          comparison = leftValue.localeCompare(rightValue)
        } else {
          comparison = Number(leftValue) - Number(rightValue)
        }

        if (comparison !== 0) {
          return sortDir === "asc" ? comparison : -comparison
        }

        return left.index - right.index
      })
      .map((row) => row.stock)
  }, [filtered, sortDir, sortKey, signalView])

  function onSort(nextKey: string) {
    if (nextKey === sortKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"))
      return
    }
    setSortKey(nextKey)
    setSortDir("desc")
  }

  function SortIcon({ columnKey }: { columnKey: string }) {
    if (columnKey !== sortKey) return <ChevronsUpDown className="h-3.5 w-3.5" />
    return sortDir === "asc" ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />
  }

  return (
    <div>
      <div className="mb-5 grid gap-3 rounded-xl border bg-card/70 p-3 shadow-sm sm:grid-cols-[minmax(0,1fr)_260px]">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Rechercher une action..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-10 rounded-lg border-border/70 bg-background pl-9 text-sm"
          />
        </div>

        <div className="relative">
          <select
            value={sectorFilter}
            onChange={(event) => setSectorFilter(event.target.value)}
            className="h-10 w-full appearance-none rounded-lg border border-border/70 bg-background px-3 pr-9 text-sm font-medium text-foreground outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]"
          >
            <option value="all">Tous les secteurs</option>
            {sectors
              .filter((sector) => sector !== "all")
              .map((sector) => (
                <option key={sector} value={sector}>
                  {sector}
                </option>
              ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        </div>
      </div>

      {sorted.length === 0 ? (
        <div className="py-12 text-center text-muted-foreground">Aucune action ne correspond aux filtres.</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>
                <button className="inline-flex items-center gap-1" onClick={() => onSort("symbol")}>
                  Action
                  <SortIcon columnKey="symbol" />
                </button>
              </TableHead>
              {FAMILY_ORDER.map((family) => (
                <TableHead key={family}>
                  <button className="inline-flex items-center gap-1" onClick={() => onSort(family)}>
                    {FAMILY_SHORT_LABELS[family]}
                    <SortIcon columnKey={family} />
                  </button>
                </TableHead>
              ))}
              <TableHead className="sticky right-0 z-20 min-w-[220px] border-l bg-primary/10 text-primary">
                <button
                  className="inline-flex w-full items-center justify-between gap-2 font-semibold"
                  onClick={() => onSort("aggregate_score_pct")}
                >
                  <span>Signal Technique Global</span>
                  <SortIcon columnKey="aggregate_score_pct" />
                </button>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.map((stock) => (
              <TableRow key={stock.symbol}>
                <TableCell className="max-w-[220px]">
                  <Link
                    href={`/signals?symbol=${encodeURIComponent(stock.symbol)}&horizon=${horizon}&view=${signalView}`}
                    className="block hover:underline"
                  >
                    <p className="font-semibold">{stock.symbol}</p>
                    <p className="truncate text-xs text-muted-foreground">{stock.display_name ?? "-"}</p>
                  </Link>
                </TableCell>
                {FAMILY_ORDER.map((family) => (
                  <TableCell key={`${stock.symbol}-${family}`}>
                    <FamilyCell score={signalView === "expanded" ? (stock.expanded_per_family?.[family] || stock.per_family[family]) : stock.per_family[family]} />
                  </TableCell>
                ))}
                <TableCell className="sticky right-0 z-10 min-w-[220px] border-l bg-background/95 backdrop-blur">
                  <div className="space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <SignalBadge label={signalView === "expanded" ? (stock.expanded_aggregate_signal_label ?? stock.aggregate_signal_label) : stock.aggregate_signal_label} />
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
  )
}
