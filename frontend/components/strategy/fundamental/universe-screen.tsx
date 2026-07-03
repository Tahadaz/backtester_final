"use client"

import { useMemo, useState } from "react"
import { Search, SlidersHorizontal } from "lucide-react"
import {
  type FundamentalUniverseRow,
} from "@/lib/api"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD } from "./lib/constants"
import { fmtCompactMad, fmtPct } from "./lib/formatters"
import { LoadingRows, RecChip, ScorePair, revisionArrow } from "./shared/cards"
import { Recommendation, RecommendationFilter, SortKey } from "./lib/types"
import { rowUpside, sortValue } from "./lib/view-models"

export function UniverseScreen({
  rows,
  totalRows,
  liquidityFilter,
  selectedSymbol,
  isLoading,
  onSelect,
  onLiquidityFilterChange,
}: {
  rows: FundamentalUniverseRow[]
  totalRows: number
  liquidityFilter: boolean
  selectedSymbol: string | null
  isLoading: boolean
  onSelect: (symbol: string) => void
  onLiquidityFilterChange: (enabled: boolean) => void
}) {
  const [query, setQuery] = useState("")
  const [sortKey, setSortKey] = useState<SortKey>("upside")
  const [filter, setFilter] = useState<RecommendationFilter>("all")

  const filteredRows = useMemo(() => {
    const q = query.trim().toUpperCase()
    return [...rows]
      .filter((row) => {
        if (filter !== "all" && row.recommendation !== filter) return false
        if (!q) return true
        return `${row.symbol} ${row.company_name} ${row.display_name ?? ""} ${row.sector ?? ""}`.toUpperCase().includes(q)
      })
      .sort((a, b) => sortValue(b, sortKey) - sortValue(a, sortKey) || a.symbol.localeCompare(b.symbol))
  }, [filter, query, rows, sortKey])

  const summary = useMemo(() => {
    const count = (rec: Recommendation) => filteredRows.filter((row) => row.recommendation === rec).length
    const upsides = filteredRows.map(rowUpside).filter((value): value is number => value != null)
    return {
      buys: count("BUY"),
      holds: count("HOLD"),
      sells: count("SELL"),
      notRated: filteredRows.filter((row) => !row.recommendation).length,
      averageUpside: upsides.length ? upsides.reduce((sum, value) => sum + value, 0) / upsides.length : null,
    }
  }, [filteredRows])

  const latestYear = rows.reduce<number | null>((latest, row) => {
    if (row.latest_statement_year == null) return latest
    return latest == null ? row.latest_statement_year : Math.max(latest, row.latest_statement_year)
  }, null)
  const coverageLabel = liquidityFilter ? `${rows.length}/${totalRows} titres` : `${rows.length} titres`
  const thresholdLabel = `${fmtCompactMad(FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD)} MAD`
  const liquidityScopeLabel = liquidityFilter ? "Eligibles" : "Univers"
  const liquidityScopeValue = liquidityFilter ? `${rows.length}/${totalRows}` : `${totalRows}`

  return (
    <aside className="signal-fund-universe">
      <div className="signal-fund-universe-header">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-bold">Couverture - {coverageLabel}</span>
          <span className="text-[10px] text-muted-foreground">FY {latestYear ?? "-"}</span>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-7 rounded-md pl-7 text-xs" placeholder="Rechercher un titre..." value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <div className={cn("fund-liquidity-filter", liquidityFilter && "active")}>
          <div className="fund-liquidity-head">
            <div className="fund-liquidity-icon">
              <SlidersHorizontal className="h-3.5 w-3.5" />
            </div>
            <div className="fund-liquidity-copy">
              <span className="fund-liquidity-kicker">Filtre institutionnel</span>
              <div className="fund-liquidity-title-row">
                <span className="fund-liquidity-title">Liquidité ADV20</span>
                <span className="fund-liquidity-status">{liquidityFilter ? "Actif" : "Inactif"}</span>
              </div>
            </div>
            <Switch
              checked={liquidityFilter}
              onCheckedChange={onLiquidityFilterChange}
              aria-label={liquidityFilter ? "Désactiver le filtre de liquidité" : "Activer le filtre de liquidité"}
            />
          </div>
          <div className="fund-liquidity-metrics">
            <div className="fund-liquidity-metric">
              <span className="fund-liquidity-metric-label">Seuil</span>
              <span className="fund-liquidity-metric-value">{`>= ${thresholdLabel}`}</span>
            </div>
            <div className="fund-liquidity-metric">
              <span className="fund-liquidity-metric-label">{liquidityScopeLabel}</span>
              <span className="fund-liquidity-metric-value">{liquidityScopeValue}</span>
            </div>
          </div>
        </div>
        <div className="flex gap-1.5">
          <div className="seg min-w-0 flex-1">
            {[
              ["all", "Tous"],
              ["BUY", "Buy"],
              ["HOLD", "Hold"],
              ["SELL", "Sell"],
            ].map(([key, label]) => (
              <button key={key} type="button" className={filter === key ? "active" : ""} onClick={() => setFilter(key as RecommendationFilter)}>
                {label}
              </button>
            ))}
          </div>
          <select className="h-[32px] rounded-md border border-line bg-card px-2 text-[11px] outline-none" value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
            <option value="upside">Upside</option>
            <option value="value">Value</option>
            <option value="quality">Quality</option>
            <option value="conviction">Conviction</option>
            <option value="market_cap">Mkt Cap</option>
            <option value="magic">Magic</option>
            <option value="peg">PEG</option>
            <option value="altman">Altman</option>
            <option value="eva">EVA</option>
            <option value="regression">Regression</option>
          </select>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="claude-table signal-fund-universe-table">
          <thead>
            <tr>
              <th>Titre</th>
              <th className="r">Rec.</th>
              <th className="r">V/Q</th>
              <th className="r">Upside</th>
              <th>Rev</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <LoadingRows />
            ) : filteredRows.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                  {liquidityFilter ? `Aucun titre avec ADV20 >= ${thresholdLabel}.` : "No fundamental rows."}
                </td>
              </tr>
            ) : (
              filteredRows.map((row) => {
                const active = row.symbol === selectedSymbol
                return (
                  <tr key={row.symbol} className={cn("cursor-pointer", active && "signal-fund-row-active")} onClick={() => onSelect(row.symbol)}>
                    <td>
                      <div className="fund-symbol-cell">
                        <div className="min-w-0">
                          <div className={cn("font-mono text-[11px] font-bold", active && "text-primary")}>{row.symbol}</div>
                          <div className="truncate text-[9px] text-muted-foreground">{row.sector ?? row.display_name ?? "-"}</div>
                        </div>
                      </div>
                    </td>
                    <td className="r">
                      <RecChip value={row.recommendation} />
                    </td>
                    <td className="r">
                      <ScorePair valueScore={row.value_score} qualityScore={row.quality_score} />
                    </td>
                    <td className={cn("r font-mono text-[11px] font-bold", (rowUpside(row) ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(rowUpside(row))}</td>
                    <td className="text-center text-[10px]">{revisionArrow(row.revision_direction)}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="fund-univ-footer">
        <span>
          <span className="t-pos font-bold">{summary.buys} Buy</span> - {summary.holds} Hold - <span className="t-neg font-bold">{summary.sells} Sell</span> - {summary.notRated} N/R
        </span>
        <span>
          Upside moy. <span className={cn("font-mono font-bold", (summary.averageUpside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(summary.averageUpside)}</span>
        </span>
      </div>
    </aside>
  )
}

