"use client"

import { useMemo, useState } from "react"
import { CheckCircle2, Search, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import type { UniverseStock } from "@/lib/api"
import type { SortBy, SortDir } from "@/lib/strategy-v2"
import { cn } from "@/lib/utils"

type UniverseView = "all" | "selected"

type StockUniverseSelectorProps = {
  rows: UniverseStock[]
  selectedSymbols: string[]
  activeSymbol: string | null
  loading?: boolean
  errorMessage?: string | null
  isStaticFallback?: boolean
  sectorFilter: string[]
  sortBy: SortBy
  sortDir: SortDir
  title?: string
  description?: string
  className?: string
  onSectorFilterChange: (sectors: string[]) => void
  onSortChange: (patch: Partial<{ sort_by: SortBy; sort_dir: SortDir }>) => void
  onSelectedChange: (symbol: string, selected: boolean) => void
  onActiveSymbolChange: (symbol: string | null) => void
  onClearSelection: () => void
}

const fmtMoney = (value: number | null | undefined) =>
  value == null || Number.isNaN(value)
    ? "-"
    : value.toLocaleString("fr-FR", { maximumFractionDigits: 0 })

function normalizeText(value: string | null | undefined): string {
  return (value ?? "").normalize("NFC").trim().toLocaleLowerCase("fr-FR")
}

function normalizeSymbol(value: string): string {
  return value.trim().toUpperCase()
}

export function StockUniverseSelector({
  rows,
  selectedSymbols,
  activeSymbol,
  loading = false,
  errorMessage = null,
  isStaticFallback = false,
  sectorFilter,
  sortBy,
  sortDir,
  title = "Stock Universe",
  description = "Choose the stocks you want in this strategy basket.",
  className,
  onSectorFilterChange,
  onSortChange,
  onSelectedChange,
  onActiveSymbolChange,
  onClearSelection,
}: StockUniverseSelectorProps) {
  const [query, setQuery] = useState("")
  const [view, setView] = useState<UniverseView>("all")

  const selectedSet = useMemo(
    () => new Set(selectedSymbols.map((symbol) => normalizeSymbol(symbol))),
    [selectedSymbols],
  )
  const active = activeSymbol ? normalizeSymbol(activeSymbol) : null
  const sectors = useMemo(
    () => Array.from(new Set(rows.map((row) => row.sector?.trim()).filter(Boolean) as string[])).sort((a, b) => a.localeCompare(b, "fr")),
    [rows],
  )
  const selectedSectorKeys = useMemo(
    () => sectorFilter.map(normalizeText).filter(Boolean),
    [sectorFilter],
  )
  const selectedSectorSet = useMemo(() => new Set(selectedSectorKeys), [selectedSectorKeys])
  const normalizedQuery = normalizeText(query)
  const sectorFilterHasNoMatches = Boolean(
    rows.length > 0
    && selectedSectorSet.size > 0
    && !rows.some((stock) => selectedSectorSet.has(normalizeText(stock.sector))),
  )

  const visibleRows = useMemo(() => {
    const filtered = rows.filter((stock) => {
      const symbol = normalizeSymbol(stock.symbol)
      if (view === "selected" && !selectedSet.has(symbol)) return false
      if (!sectorFilterHasNoMatches && selectedSectorSet.size > 0 && !selectedSectorSet.has(normalizeText(stock.sector))) return false
      if (!normalizedQuery) return true
      const haystack = [
        stock.symbol,
        stock.display_name,
        stock.sector,
        stock.market_cap_class,
        stock.signal_label,
      ].map((item) => normalizeText(item)).join(" ")
      return haystack.includes(normalizedQuery)
    })
    const sign = sortDir === "asc" ? 1 : -1
    return [...filtered].sort((a, b) => {
      const left = sortBy === "signal_score" ? a.signal_score : a.adv20
      const right = sortBy === "signal_score" ? b.signal_score : b.adv20
      if (left == null && right == null) return normalizeSymbol(a.symbol).localeCompare(normalizeSymbol(b.symbol))
      if (left == null) return 1
      if (right == null) return -1
      return (left - right) * sign
    })
  }, [normalizedQuery, rows, sectorFilterHasNoMatches, selectedSectorSet, selectedSet, sortBy, sortDir, view])

  const toggleSector = (sector: string) => {
    const exists = sectorFilter.some((item) => normalizeText(item) === normalizeText(sector))
    onSectorFilterChange(exists ? sectorFilter.filter((item) => normalizeText(item) !== normalizeText(sector)) : [...sectorFilter, sector])
  }

  const selectStock = (symbol: string) => {
    const normalized = normalizeSymbol(symbol)
    onSelectedChange(normalized, true)
    onActiveSymbolChange(normalized)
  }

  const setStockChecked = (symbol: string, checked: boolean) => {
    const normalized = normalizeSymbol(symbol)
    onSelectedChange(normalized, checked)
    if (checked) onActiveSymbolChange(normalized)
  }

  const clearSelection = () => {
    onClearSelection()
    onActiveSymbolChange(null)
  }

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="outline">{rows.length} stocks</Badge>
            <Badge variant={selectedSymbols.length > 0 ? "default" : "secondary"}>{selectedSymbols.length} selected</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isStaticFallback ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Showing bundled universe data while the live API is unavailable or still loading. You can still select stocks and save a local draft.
          </div>
        ) : null}
        {errorMessage ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Universe API unavailable: {errorMessage}
          </div>
        ) : null}
        {sectorFilterHasNoMatches ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <span>No stocks match the saved sector filter. Showing all stocks.</span>
            <Button type="button" variant="outline" size="sm" onClick={() => onSectorFilterChange([])}>
              Clear sectors
            </Button>
          </div>
        ) : null}

        <div className="grid gap-3 lg:grid-cols-[minmax(220px,1fr)_auto_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search stocks, names, sectors"
              className="pl-9"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant={view === "all" ? "default" : "outline"} size="sm" onClick={() => setView("all")}>
              All
            </Button>
            <Button type="button" variant={view === "selected" ? "default" : "outline"} size="sm" onClick={() => setView("selected")}>
              Selected
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={clearSelection} disabled={selectedSymbols.length === 0}>
              Clear
            </Button>
          </div>
          <div className="flex flex-wrap gap-2">
            <Select value={sortBy} onValueChange={(value: SortBy) => onSortChange({ sort_by: value })}>
              <SelectTrigger className="h-8 w-[150px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="adv20">ADV20 MAD</SelectItem>
                <SelectItem value="signal_score">Signal strength</SelectItem>
              </SelectContent>
            </Select>
            <Select value={sortDir} onValueChange={(value: SortDir) => onSortChange({ sort_dir: value })}>
              <SelectTrigger className="h-8 w-[130px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="desc">Descending</SelectItem>
                <SelectItem value="asc">Ascending</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {sectors.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {sectors.map((sector) => {
              const activeSector = selectedSectorSet.has(normalizeText(sector))
              return (
                <button
                  key={sector}
                  type="button"
                  onClick={() => toggleSector(sector)}
                  className={cn("claude-chip", activeSector && "active")}
                >
                  {activeSector ? <CheckCircle2 className="h-3.5 w-3.5" /> : null}
                  <span>{sector}</span>
                </button>
              )
            })}
          </div>
        ) : null}

        {selectedSymbols.length > 0 ? (
          <div className="flex flex-wrap gap-2 rounded-md border border-line bg-bg2 p-3">
            {selectedSymbols.map((symbol) => {
              const normalized = normalizeSymbol(symbol)
              return (
                <div key={normalized} className={cn("claude-chip", normalized === active && "active")}>
                  <button type="button" onClick={() => onActiveSymbolChange(normalized)} className="border-0 bg-transparent p-0 font-mono text-inherit">
                    {normalized}
                  </button>
                  <span>{normalized === active ? "Editing" : "Open"}</span>
                  <button
                    type="button"
                    onClick={() => setStockChecked(normalized, false)}
                    className="border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground"
                    aria-label={`Remove ${normalized}`}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              )
            })}
          </div>
        ) : null}

        <div className="overflow-x-auto rounded-md border border-line">
          <table className="claude-table min-w-[820px]">
            <thead>
              <tr>
                <th className="w-8" />
                <th>Ticker</th>
                <th>Sector</th>
                <th className="r">ADV20 MAD</th>
                <th className="r">Signal</th>
                <th className="r">Status</th>
                <th className="r">Action</th>
              </tr>
            </thead>
            <tbody>
              {loading ? Array.from({ length: 8 }).map((_, index) => (
                <tr key={index}>
                  <td colSpan={7} className="px-3 py-2">
                    <Skeleton className="h-8 w-full" />
                  </td>
                </tr>
              )) : visibleRows.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-sm text-muted-foreground">
                    No stocks match the current list filters.
                  </td>
                </tr>
              ) : visibleRows.map((stock) => {
                const symbol = normalizeSymbol(stock.symbol)
                const selected = selectedSet.has(symbol)
                return (
                  <tr
                    key={symbol}
                    className={cn("cursor-pointer", selected && "bg-primary/5", symbol === active && "outline outline-1 outline-primary/30")}
                    title={stock.exclusion_reason ?? undefined}
                    onClick={() => selectStock(symbol)}
                  >
                    <td>
                      <Checkbox
                        checked={selected}
                        onClick={(event) => event.stopPropagation()}
                        onCheckedChange={(checked) => setStockChecked(symbol, checked === true)}
                      />
                    </td>
                    <td>
                      <div className="font-mono font-medium">{symbol}</div>
                      {stock.display_name ? <div className="text-xs text-muted-foreground">{stock.display_name}</div> : null}
                    </td>
                    <td className="text-muted-foreground">{stock.sector ?? "-"}</td>
                    <td className="r font-mono">{fmtMoney(stock.adv20)}</td>
                    <td className="r font-mono">{stock.signal_score != null ? stock.signal_score.toFixed(1) : "-"}</td>
                    <td className="r">
                      <Badge variant={stock.eligible ? "outline" : "secondary"}>
                        {stock.eligible ? "Available" : "Filtered"}
                      </Badge>
                    </td>
                    <td className="r">
                      <Button
                        type="button"
                        variant={selected ? "default" : "outline"}
                        size="sm"
                        onClick={(event) => {
                          event.stopPropagation()
                          setStockChecked(symbol, !selected)
                        }}
                      >
                        {selected ? "Remove" : "Add"}
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
