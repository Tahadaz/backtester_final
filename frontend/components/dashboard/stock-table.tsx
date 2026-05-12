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
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react"

interface StockTableProps {
  stocks: DashboardStock[]
  horizon: Horizon
}

type SortDir = "asc" | "desc"

function getSortValue(stock: DashboardStock, key: string): number | string {
  if (key === "symbol") return stock.symbol
  if (key === "sector") return stock.sector ?? ""
  if (key === "aggregate_score_pct") return stock.scores.signal_engine.aggregate_score_pct ?? -999
  const family = stock.scores.signal_engine.per_family[key]
  return family ? family.score_pct : -999
}

export function StockTable({ stocks, horizon }: StockTableProps) {
  const [search, setSearch] = useState("")
  const [sectorFilter, setSectorFilter] = useState<string>("all")
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
  }, [stocks, search, sectorFilter])

  const sorted = useMemo(() => {
    return filtered
      .map((stock, index) => ({ stock, index }))
      .sort((left, right) => {
        const leftValue = getSortValue(left.stock, sortKey)
        const rightValue = getSortValue(right.stock, sortKey)

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
  }, [filtered, sortDir, sortKey])

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
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <Input
          placeholder="Rechercher une action..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="max-w-sm border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-950"
        />
        <select
          value={sectorFilter}
          onChange={(event) => setSectorFilter(event.target.value)}
          className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:border-slate-300 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300"
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
      </div>

      {sorted.length === 0 ? (
        <div className="rounded-lg border border-slate-200 bg-white py-12 text-center text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400">Aucune action ne correspond aux filtres.</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 dark:border-slate-700">
          <Table className="[&_thead]:sticky [&_thead]:top-0 [&_thead]:z-30 [&_thead]:bg-slate-900 dark:[&_thead]:bg-slate-950">
            <TableHeader>
              <TableRow className="border-b border-slate-200 dark:border-slate-700">
                <TableHead className="text-left text-xs font-bold uppercase tracking-wider text-white">
                  <button className="inline-flex items-center gap-2" onClick={() => onSort("symbol")}>
                    Action
                    <SortIcon columnKey="symbol" />
                  </button>
                </TableHead>
                {FAMILY_ORDER.map((family) => (
                  <TableHead key={family} className="text-left text-xs font-bold uppercase tracking-wider text-white">
                    <button className="inline-flex items-center gap-2" onClick={() => onSort(family)}>
                      {FAMILY_SHORT_LABELS[family]}
                      <SortIcon columnKey={family} />
                    </button>
                  </TableHead>
                ))}
                <TableHead className="sticky right-0 z-40 min-w-[240px] border-l border-slate-300 bg-blue-600 text-left text-xs font-bold uppercase tracking-wider text-white dark:border-slate-600 dark:bg-blue-700">
                  <button
                    className="inline-flex w-full items-center justify-between gap-2"
                    onClick={() => onSort("aggregate_score_pct")}
                  >
                    <span>Signal Technique Global</span>
                    <SortIcon columnKey="aggregate_score_pct" />
                  </button>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className="divide-y divide-slate-200 dark:divide-slate-700">
              {sorted.map((stock) => (
                <TableRow key={stock.symbol} className="border-none hover:bg-slate-50 dark:hover:bg-slate-800">
                  <TableCell className="max-w-xs py-4">
                    <Link
                      href={signalEvidenceUrl({ symbol: stock.symbol, horizon })}
                      className="block hover:text-blue-600 dark:hover:text-blue-400"
                    >
                      <p className="font-semibold text-slate-900 dark:text-white">{stock.symbol}</p>
                      <p className="truncate text-xs text-slate-500 dark:text-slate-400">{stock.display_name ?? "-"}</p>
                    </Link>
                  </TableCell>
                    {FAMILY_ORDER.map((family) => (
                      <TableCell key={`${stock.symbol}-${family}`} className="py-4">
                        <FamilyCell score={stock.scores.signal_engine.per_family[family]} />
                      </TableCell>
                    ))}
                  <TableCell className="sticky right-0 z-20 min-w-[240px] border-l border-slate-200 bg-blue-50 py-4 dark:border-slate-700 dark:bg-blue-950/30">
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
        </div>
      )}
    </div>
  )
}
