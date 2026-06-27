"use client"

import { useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { usePredictiveAbilityLeaderboard } from "@/hooks/use-api"
import type { PredictiveLeaderboardRow } from "@/lib/api"
import { Skeleton } from "@/components/ui/skeleton"
import { signalEvidenceUrl } from "@/lib/signal-evidence-url"
import { horizonLabel } from "@/lib/horizon"
import { ArrowUpDown, ArrowDown, ArrowUp } from "lucide-react"

type EngineHorizon = "short" | "medium" | "long"

interface Props {
  onSelectSymbol: (
    symbol: string,
    source: string,
    engineHorizon: EngineHorizon,
  ) => void
  advBySymbol?: Map<string, number>
  liquidityFilter?: boolean
  advThreshold?: number
  lookback_days?: number
}

const HORIZONS: EngineHorizon[] = ["short", "medium", "long"]

const RETURN_METHODS = [
  { value: "open_to_open", label: "O to O" },
  { value: "open_to_close", label: "O to C" },
] as const

const SOURCE_LABEL: Record<string, string> = {
  engine_legacy: "Engine (legacy)",
  engine_expanded: "Engine (expanded)",
  factor_x_ta: "Engine (E FX)",
  wfo: "WFO",
}

const MODE_LABEL: Record<string, string> = {
  legacy_ta_simple: "L TA",
  expanded_ta_simple: "E TA",
  legacy_factor_x_ta_simple: "L FX",
  expanded_factor_x_ta_simple: "E FX",
  legacy_ta_combo: "L TA Combo",
  expanded_ta_combo: "E TA Combo",
  legacy_factor_x_ta_combo: "L FX Combo",
  expanded_factor_x_ta_combo: "E FX Combo",
}

function sourceLabel(source: string): string {
  if (SOURCE_LABEL[source]) return SOURCE_LABEL[source]
  const [axis, mode] = source.split(":", 2)
  if (!mode) return source
  const axisLabel = axis === "wfo" ? "WFO" : "Engine"
  return `${axisLabel} (${MODE_LABEL[mode] ?? mode})`
}

function evidenceSourceForLeaderboard(source: string): "signal_engine" | "wfo" {
  return source.startsWith("wfo") ? "wfo" : "signal_engine"
}

function evidenceViewForLeaderboard(source: string): string {
  const [_axis, mode] = source.split(":", 2)
  if (mode) return mode
  if (source === "engine_legacy") return "legacy_ta_simple"
  if (source === "factor_x_ta") return "expanded_factor_x_ta_simple"
  if (source.includes("legacy")) return "legacy_ta_simple"
  return "expanded_ta_simple"
}

function evidenceHrefForLeaderboard(row: PredictiveLeaderboardRow, horizon: EngineHorizon): string {
  const evidenceVariant = evidenceViewForLeaderboard(row.source)
  return signalEvidenceUrl({
    symbol: row.symbol,
    horizon,
    view: evidenceVariant,
    source: evidenceSourceForLeaderboard(row.source),
    evidenceVariant,
  })
}

function icColor(ic: number | null | undefined): string {
  if (ic === null || ic === undefined || Number.isNaN(ic)) return "text-muted-foreground"
  if (ic > 0) return `text-emerald-700 dark:text-emerald-400`
  if (ic < 0) return `text-red-700 dark:text-red-400`
  return "text-muted-foreground"
}

function icBg(ic: number | null | undefined): string {
  if (ic === null || ic === undefined || Number.isNaN(ic)) return ""
  const a = Math.min(0.6, Math.abs(ic) / 0.2)
  if (ic > 0) return `rgba(16,185,129,${a.toFixed(2)})`
  if (ic < 0) return `rgba(239,68,68,${a.toFixed(2)})`
  return ""
}

function fmtIC(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return (v >= 0 ? "+" : "") + v.toFixed(3)
}

export function TopSignauxLeaderboard({ onSelectSymbol, advBySymbol, liquidityFilter, advThreshold = 1_000_000, lookback_days }: Props) {
  const router = useRouter()
  const [engineHorizon, setEngineHorizon] = useState<EngineHorizon>("short")
  const [returnCalcMethod, setReturnCalcMethod] = useState<string>("open_to_open")
  const [sortKey, setSortKey] = useState<string>("mean_ic")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const { data, isLoading, error } = usePredictiveAbilityLeaderboard(engineHorizon, lookback_days ?? 0, returnCalcMethod)
  const fwdHorizons = data?.fwd_horizons ?? []

  const rows = useMemo(() => {
    let list = [...(data?.rows ?? [])]
    if (liquidityFilter && advBySymbol) {
      list = list.filter((r) => (advBySymbol.get(r.symbol) ?? 0) >= advThreshold)
    }
    list.sort((a, b) => {
      let av: number | null | undefined
      let bv: number | null | undefined
      if (sortKey === "mean_ic") {
        av = a.mean_ic
        bv = b.mean_ic
      } else if (sortKey === "mean_sharpe") {
        av = a.mean_sharpe
        bv = b.mean_sharpe
      } else if (sortKey === "mean_hit_rate") {
        av = a.mean_hit_rate
        bv = b.mean_hit_rate
      } else if (sortKey === "n") {
        av = a.n
        bv = b.n
      } else if (sortKey === "symbol") {
        return sortDir === "asc"
          ? a.symbol.localeCompare(b.symbol)
          : b.symbol.localeCompare(a.symbol)
      } else if (sortKey === "source") {
        return sortDir === "asc"
          ? a.source.localeCompare(b.source)
          : b.source.localeCompare(a.source)
      } else {
        av = a.ic_by_fwd_h[sortKey]
        bv = b.ic_by_fwd_h[sortKey]
      }
      const aN = av === null || av === undefined || Number.isNaN(av)
      const bN = bv === null || bv === undefined || Number.isNaN(bv)
      if (aN && bN) return 0
      if (aN) return 1
      if (bN) return -1
      return sortDir === "asc" ? (av as number) - (bv as number) : (bv as number) - (av as number)
    })
    return list
  }, [data, sortKey, sortDir, liquidityFilter, advBySymbol, advThreshold])

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc")
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const sortIcon = (key: string) => {
    if (sortKey !== key) return <ArrowUpDown className="h-3 w-3 opacity-40" />
    return sortDir === "desc" ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Horizon
        </span>
        <div className="inline-flex rounded-md border border-line bg-bg2 p-0.5">
          {HORIZONS.map((h) => (
            <button
              key={h}
              onClick={() => setEngineHorizon(h)}
              className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                engineHorizon === h
                  ? "bg-card text-foreground shadow-xs"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {horizonLabel(h)}
            </button>
          ))}
        </div>

        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Rendement
        </span>
        <div className="inline-flex rounded-md border border-line bg-bg2 p-0.5">
          {RETURN_METHODS.map((rm) => (
            <button
              key={rm.value}
              onClick={() => setReturnCalcMethod(rm.value)}
              className={`px-3 py-1 text-xs font-medium rounded transition-colors ${
                returnCalcMethod === rm.value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {rm.label}
            </button>
          ))}
        </div>

        <span className="text-xs text-muted-foreground">
          IC = Spearman(score, forward return). Color: green = predictive, red = inverted.
        </span>
      </div>

      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          Failed to load leaderboard: {String((error as Error).message ?? error)}
        </div>
      )}

      {isLoading && !data ? (
        <div className="space-y-1">
          {[...Array(8)].map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-32 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
          Aucune donnée — déclenchez « Recompute predictive history ».
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="claude-table">
            <thead>
              <tr>
                <Th onClick={() => toggleSort("symbol")}>
                  <span className="flex items-center gap-1">Symbole {sortIcon("symbol")}</span>
                </Th>
                <Th onClick={() => toggleSort("source")}>
                  <span className="flex items-center gap-1">Méthode {sortIcon("source")}</span>
                </Th>
                {fwdHorizons.map((h) => (
                  <Th key={h} onClick={() => toggleSort(String(h))} className="text-right">
                    <span className="flex items-center justify-end gap-1">
                      IC@{h}d {sortIcon(String(h))}
                    </span>
                  </Th>
                ))}
                <Th onClick={() => toggleSort("mean_ic")} className="text-right">
                  <span className="flex items-center justify-end gap-1">
                    Moy. IC {sortIcon("mean_ic")}
                  </span>
                </Th>
                <Th onClick={() => toggleSort("mean_sharpe")} className="text-right">
                  <span className="flex items-center justify-end gap-1">
                    Sharpe {sortIcon("mean_sharpe")}
                  </span>
                </Th>
                <Th onClick={() => toggleSort("mean_hit_rate")} className="text-right">
                  <span className="flex items-center justify-end gap-1">
                    Hit% {sortIcon("mean_hit_rate")}
                  </span>
                </Th>
                <Th onClick={() => toggleSort("n")} className="text-right">
                  <span className="flex items-center justify-end gap-1">n {sortIcon("n")}</span>
                </Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => {
                const evidenceHref = evidenceHrefForLeaderboard(row, engineHorizon)
                return (
                  <Row
                    key={`${row.symbol}-${row.source}-${idx}`}
                    row={row}
                    fwdHorizons={fwdHorizons}
                    evidenceHref={evidenceHref}
                    onClick={() => {
                      onSelectSymbol(row.symbol, row.source, engineHorizon)
                      router.push(evidenceHref)
                    }}
                  />
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Th({
  children,
  onClick,
  className = "",
}: {
  children: React.ReactNode
  onClick?: () => void
  className?: string
}) {
  return (
    <th
      onClick={onClick}
      className={`cursor-pointer select-none hover:bg-muted/60 ${className}`}
    >
      {children}
    </th>
  )
}

function fmtSharpe(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return (v >= 0 ? "+" : "") + v.toFixed(2)
}

function fmtHR(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return (v * 100).toFixed(1) + "%"
}

function sharpeColor(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "text-muted-foreground"
  if (v > 0.5) return "text-emerald-700 dark:text-emerald-400"
  if (v < -0.5) return "text-red-700 dark:text-red-400"
  return "text-muted-foreground"
}

function hrColor(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "text-muted-foreground"
  if (v > 0.55) return "text-emerald-700 dark:text-emerald-400"
  if (v < 0.45) return "text-red-700 dark:text-red-400"
  return "text-muted-foreground"
}

function Row({
  row,
  fwdHorizons,
  evidenceHref,
  onClick,
}: {
  row: PredictiveLeaderboardRow
  fwdHorizons: number[]
  evidenceHref: string
  onClick: () => void
}) {
  return (
    <tr
      onClick={onClick}
      role="link"
      tabIndex={0}
      title={`Voir la preuve OOS ${row.symbol}: ${evidenceHref}`}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault()
          onClick()
        }
      }}
      className="group cursor-pointer transition-colors hover:bg-muted/40"
    >
      <td className="font-mono font-semibold">
        <span className="underline-offset-2 group-hover:underline">{row.symbol}</span>
      </td>
      <td className="text-muted-foreground">
        {sourceLabel(row.source)}
      </td>
      {fwdHorizons.map((h) => {
        const ic = row.ic_by_fwd_h[h]
        const t = row.tstat_by_fwd_h[h]
        return (
          <td
            key={h}
            className={`r font-mono tabular-nums ${icColor(ic)}`}
            style={{ backgroundColor: icBg(ic) }}
            title={
              ic !== null && ic !== undefined
                ? `IC=${ic.toFixed(4)}, t=${t !== null && t !== undefined ? t.toFixed(2) : "—"}, n=${row.n}`
                : "no data"
            }
          >
            {fmtIC(ic)}
          </td>
        )
      })}
      <td
        className={`r font-mono tabular-nums font-semibold ${icColor(row.mean_ic)}`}
      >
        {fmtIC(row.mean_ic)}
      </td>
      <td className={`r font-mono tabular-nums font-semibold ${sharpeColor(row.mean_sharpe)}`}>
        {fmtSharpe(row.mean_sharpe)}
      </td>
      <td className={`r font-mono tabular-nums ${hrColor(row.mean_hit_rate)}`}>
        {fmtHR(row.mean_hit_rate)}
      </td>
      <td className="r text-muted-foreground tabular-nums">{row.n}</td>
    </tr>
  )
}
