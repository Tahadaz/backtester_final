"use client"

import { useState } from "react"
import { useFactorLeaderboard } from "@/hooks/use-api"
import type { FactorLeaderboardRow } from "@/lib/api"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ChevronUp, ChevronDown } from "lucide-react"

type SortKey = keyof Pick<FactorLeaderboardRow, "symbol" | "n_significant" | "best_factor" | "max_t_stat" | "max_ic" | "n_obs">

function tStatColor(v: number) {
  const abs = Math.abs(v)
  if (abs > 2.58) return "text-emerald-700"
  if (abs > 1.96) return "text-yellow-700"
  return "text-muted-foreground"
}

function icColor(v: number) {
  if (v > 0.05) return "text-emerald-700"
  if (v < -0.05) return "text-red-600"
  return "text-muted-foreground"
}

interface Props {
  lookbackDays?: number
  returnMethod?: string
  onSelectSymbol?: (symbol: string) => void
}

export function FactorLeaderboardPanel({ lookbackDays, returnMethod, onSelectSymbol }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("n_significant")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const { data, isLoading, error } = useFactorLeaderboard({ lookbackDays, returnMethod })

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  function SortIcon({ col }: { col: SortKey }) {
    if (col !== sortKey) return <span className="ml-0.5 opacity-20">↕</span>
    return sortDir === "desc" ? <ChevronDown className="inline h-3 w-3 ml-0.5" /> : <ChevronUp className="inline h-3 w-3 ml-0.5" />
  }

  function SortTh({ col, label, className }: { col: SortKey; label: string; className?: string }) {
    return (
      <TableHead
        className={`cursor-pointer select-none hover:text-foreground transition-colors ${className ?? ""}`}
        onClick={() => toggleSort(col)}
      >
        {label}<SortIcon col={col} />
      </TableHead>
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-1.5">
        {[...Array(10)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-sm text-destructive py-4 text-center">
        Erreur chargement classement macro.
      </div>
    )
  }

  if (!data || data.length === 0) {
    return (
      <div className="text-sm text-muted-foreground py-4 text-center">
        Aucune donnée — ingérez les séries macro dans l&apos;onglet{" "}
        <strong>Données Macro</strong> puis relancez.
      </div>
    )
  }

  const sorted = [...data].sort((a, b) => {
    let av = a[sortKey]
    let bv = b[sortKey]
    if (av == null) return 1
    if (bv == null) return -1
    if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv as string) : (bv as string).localeCompare(av)
    return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number)
  })

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Classement par nombre de facteurs macro significatifs (|t-stat| &gt; 1.96) sur l&apos;ensemble des 6 facteurs.
      </p>
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <SortTh col="symbol" label="Symbole" className="w-24" />
            <SortTh col="n_significant" label="Sig. / 6" className="w-20 text-right" />
            <SortTh col="best_factor" label="Meilleur facteur" />
            <SortTh col="max_t_stat" label="t-stat max" className="w-24 text-right" />
            <SortTh col="max_ic" label="IC max" className="w-20 text-right" />
            <SortTh col="n_obs" label="Obs" className="w-16 text-right" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow
              key={row.symbol}
              className="text-xs cursor-pointer hover:bg-muted/60"
              onClick={() => onSelectSymbol?.(row.symbol)}
            >
              <TableCell className="font-mono font-semibold">{row.symbol}</TableCell>
              <TableCell className="text-right tabular-nums">
                <span className={row.n_significant >= 3 ? "text-emerald-700 font-semibold" : row.n_significant >= 1 ? "text-yellow-700" : "text-muted-foreground"}>
                  {row.n_significant}/6
                </span>
              </TableCell>
              <TableCell className="font-mono text-[11px]">{row.best_factor}</TableCell>
              <TableCell className={`text-right tabular-nums font-mono ${tStatColor(row.max_t_stat)}`}>
                {row.max_t_stat > 0 ? "+" : ""}{row.max_t_stat.toFixed(2)}
              </TableCell>
              <TableCell className={`text-right tabular-nums font-mono ${icColor(row.max_ic)}`}>
                {(row.max_ic * 100).toFixed(1)}%
              </TableCell>
              <TableCell className="text-right tabular-nums text-muted-foreground">
                {row.n_obs}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-[10px] text-muted-foreground">
        Cliquez sur une ligne pour voir le détail par action. Vert ≥ 3 facteurs sig., jaune ≥ 1.
      </p>
    </div>
  )
}
