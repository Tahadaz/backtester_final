"use client"

import { useMemo, useState } from "react"
import { Search, SlidersHorizontal } from "lucide-react"
import {
  type FundamentalUniverseRow,
} from "@/lib/api"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import { FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD } from "./lib/constants"
import { fmtCompactMad, fmtPct } from "./lib/formatters"
import type { IpoProfileMeta } from "./lib/ipo-store"
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
  ratingAssumptions,
  ipoProfiles,
  activeIpoId,
  onSelectIpo,
  onAddIpo,
}: {
  rows: FundamentalUniverseRow[]
  totalRows: number
  liquidityFilter: boolean
  selectedSymbol: string | null
  isLoading: boolean
  onSelect: (symbol: string) => void
  onLiquidityFilterChange: (enabled: boolean) => void
  ratingAssumptions?: Record<string, unknown> | null
  ipoProfiles?: IpoProfileMeta[]
  activeIpoId?: string | null
  onSelectIpo?: (id: string) => void
  onAddIpo?: () => void
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
              ["BUY", "Acheter"],
              ["HOLD", "Conserver"],
              ["SELL", "Vendre"],
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

      {ipoProfiles && ipoProfiles.length > 0 ? (
        <div className="mx-2 mb-2 flex flex-col gap-1">
          {ipoProfiles.map((profile) => (
            <button
              key={profile.id}
              type="button"
              onClick={() => onSelectIpo?.(profile.id)}
              className={cn(
                "flex flex-col gap-0.5 rounded-md border border-line px-2.5 py-2 text-left transition-colors hover:bg-accent",
                profile.id === activeIpoId && "signal-fund-row-active border-primary",
              )}
            >
              <span className={cn("flex items-center gap-1.5 text-xs font-bold", profile.id === activeIpoId && "text-primary")}>
                {profile.ticker} · IPO — Marché primaire
                {!profile.isBuiltin ? (
                  <span className="rounded bg-muted px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">perso</span>
                ) : null}
              </span>
              <span className="text-[10px] text-muted-foreground">Première cotation {profile.firstQuote}</span>
            </button>
          ))}
          {onAddIpo ? (
            <button
              type="button"
              onClick={onAddIpo}
              className="rounded-md border border-dashed border-line px-2.5 py-1.5 text-left text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
            >
              + Ajouter une IPO
            </button>
          ) : null}
        </div>
      ) : null}

      <ScrollArea className="min-h-0 flex-1 signals-scrollbar">
        <div className="space-y-1 p-1.5">
          {isLoading ? (
            <div className="space-y-1">
              {[...Array(12)].map((_, index) => (
                <div key={index} className="h-[45px] w-full rounded-md animate-pulse bg-muted" />
              ))}
            </div>
          ) : filteredRows.length === 0 ? (
            <div className="p-4 text-center text-xs text-muted-foreground">
              {liquidityFilter ? `Aucun titre avec ADV20 >= ${thresholdLabel}.` : "No fundamental rows."}
            </div>
          ) : (
            filteredRows.map((row) => {
              const active = row.symbol === selectedSymbol
              return (
                <button
                  key={row.symbol}
                  type="button"
                  onClick={() => onSelect(row.symbol)}
                  className={cn(
                    "grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-2 rounded-md border border-transparent px-2.5 py-2 text-left transition-colors hover:border-line hover:bg-bg3",
                    active && "border-primary/30 bg-primary/10 text-foreground",
                  )}
                >
                  <span className="min-w-0">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className={cn("font-mono text-xs font-bold", active && "text-primary")}>{row.symbol}</span>
                      <span className="text-[10px]">{revisionArrow(row.revision_direction)}</span>
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                      {row.sector ?? row.display_name ?? "-"}
                    </span>
                  </span>
                  <span className="flex min-w-0 flex-col items-end gap-1">
                    <span className="flex items-center gap-1.5">
                      <RecChip value={row.recommendation} assumptions={ratingAssumptions} />
                      <span className={cn("font-mono text-[11px] font-bold min-w-[32px] text-right", (rowUpside(row) ?? 0) >= 0 ? "t-pos" : "t-neg")}>
                        {fmtPct(rowUpside(row))}
                      </span>
                    </span>
                    <ScorePair valueScore={row.value_score} qualityScore={row.quality_score} />
                  </span>
                </button>
              )
            })
          )}
        </div>
      </ScrollArea>

      <div className="fund-univ-footer">
        <span>
          <span className="t-pos font-bold">{summary.buys} Acheter</span> - {summary.holds} Conserver - <span className="t-neg font-bold">{summary.sells} Vendre</span> - {summary.notRated} NR
        </span>
        <span>
          Upside moy. <span className={cn("font-mono font-bold", (summary.averageUpside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(summary.averageUpside)}</span>
        </span>
      </div>
    </aside>
  )
}
