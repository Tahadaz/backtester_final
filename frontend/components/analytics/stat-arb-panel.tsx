"use client"

import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, GitCompareArrows, LineChart, RefreshCw, ShieldCheck } from "lucide-react"
import { useStatArbLeaderboard, useStatArbPairDetail, useStatArbStatus } from "@/hooks/use-api"
import { triggerStatArbRecompute } from "@/lib/api"
import type { StatArbPairRow } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

type Horizon = "short" | "medium" | "long"

const HORIZONS: Horizon[] = ["short", "medium", "long"]
const ARCHETYPES = [
  ["", "Tous"],
  ["same_bar_cointegration", "Coint. meme barre"],
  ["lagged_cointegration", "Coint. laggee"],
  ["lead_lag_continuation", "Lead-lag buy-buy"],
] as const
const STATUSES = [
  ["", "Tous"],
  ["actionable", "Actionable"],
  ["watch", "Watch"],
  ["rejected", "Rejetes"],
  ["failed", "Failed"],
] as const
const ACTIONS = [
  ["", "Tous"],
  ["long_y_short_x", "Long Y / Short X"],
  ["short_y_long_x", "Short Y / Long X"],
  ["buy_buy", "Buy-buy"],
  ["none", "None"],
] as const

function fmt(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  return value.toFixed(digits)
}

function fmtPct(value: number | null | undefined, digits = 1) {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${(value * 100).toFixed(digits)}%`
}

function labelFor(options: readonly (readonly [string, string])[], value: string) {
  return options.find(([key]) => key === value)?.[1] ?? value
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "actionable"
      ? "border-emerald-300 bg-emerald-50 text-emerald-700"
      : status === "watch"
        ? "border-blue-300 bg-blue-50 text-blue-700"
        : status === "failed"
          ? "border-red-300 bg-red-50 text-red-700"
          : "text-muted-foreground"
  return <Badge variant="outline" className={`h-5 px-1.5 text-[10px] ${cls}`}>{status}</Badge>
}

function numericSeries(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is number => typeof item === "number" && Number.isFinite(item))
}

function MiniChart({ chart }: { chart: Record<string, unknown> | undefined }) {
  const values = numericSeries(chart?.zscore).length > 0
    ? numericSeries(chart?.zscore)
    : numericSeries(chart?.target_return)
  const points = values.slice(-120)
  if (points.length < 2) {
    return <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-line text-xs text-muted-foreground">No chart data</div>
  }
  const min = Math.min(...points)
  const max = Math.max(...points)
  const span = max - min || 1
  const path = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * 100
      const y = 100 - ((v - min) / span) * 100
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(" ")
  const zeroY = 100 - ((0 - min) / span) * 100

  return (
    <div className="h-40 rounded-md border border-line bg-card p-2">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full">
        {zeroY >= 0 && zeroY <= 100 ? <line x1="0" x2="100" y1={zeroY} y2={zeroY} className="stroke-muted-foreground/30" strokeWidth="0.8" /> : null}
        <path d={path} fill="none" className="stroke-primary" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}

function PairName({ row }: { row: StatArbPairRow }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono font-semibold">
      <span>{row.symbol_y}</span>
      <span className="text-muted-foreground">/</span>
      <span>{row.symbol_x}</span>
    </span>
  )
}

export function StatArbPanel() {
  const [horizon, setHorizon] = useState<Horizon>("short")
  const [archetype, setArchetype] = useState("")
  const [status, setStatus] = useState("")
  const [actionType, setActionType] = useState("")
  const [selectedPairId, setSelectedPairId] = useState<string | null>(null)
  const [isTriggering, setIsTriggering] = useState(false)
  const [triggerError, setTriggerError] = useState<string | null>(null)

  const leaderboard = useStatArbLeaderboard({
    horizon,
    archetype: archetype || undefined,
    status: status || undefined,
    actionType: actionType || undefined,
    limit: 250,
  })
  const statusState = useStatArbStatus()
  const detail = useStatArbPairDetail(selectedPairId)
  const rows = leaderboard.data?.rows ?? []

  useEffect(() => {
    if (!selectedPairId && rows[0]) setSelectedPairId(rows[0].pair_id)
    if (selectedPairId && rows.length > 0 && !rows.some((row) => row.pair_id === selectedPairId)) {
      setSelectedPairId(rows[0].pair_id)
    }
  }, [rows, selectedPairId])

  const counts = useMemo(() => {
    return rows.reduce(
      (acc, row) => {
        acc.total += 1
        if (row.status === "actionable") acc.actionable += 1
        if (row.status === "watch") acc.watch += 1
        return acc
      },
      { total: 0, actionable: 0, watch: 0 },
    )
  }, [rows])

  const latest = statusState.data?.latest ?? {}
  const latestStatus = typeof latest.status === "string" ? latest.status : "idle"
  const latestPairs = typeof latest.total_pairs === "number" ? latest.total_pairs : 0

  async function handleRecompute() {
    setIsTriggering(true)
    setTriggerError(null)
    try {
      await triggerStatArbRecompute({ horizon })
      await Promise.all([statusState.mutate(), leaderboard.mutate()])
    } catch (error) {
      setTriggerError(error instanceof Error ? error.message : "stat-arb recompute failed")
    } finally {
      setIsTriggering(false)
    }
  }

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="px-5 pb-2 pt-4">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold">
            <GitCompareArrows className="h-4 w-4 text-primary" />
            Statistical arbitrage
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="seg">
              {HORIZONS.map((item) => (
                <button
                  key={item}
                  type="button"
                  className={horizon === item ? "active" : ""}
                  onClick={() => setHorizon(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <select className="select" value={archetype} onChange={(event) => setArchetype(event.target.value)}>
              {ARCHETYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <select className="select" value={actionType} onChange={(event) => setActionType(event.target.value)}>
              {ACTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <select className="select" value={status} onChange={(event) => setStatus(event.target.value)}>
              {STATUSES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <Button type="button" size="sm" variant="outline" className="ml-auto" onClick={handleRecompute} disabled={isTriggering}>
              <RefreshCw className={`h-3.5 w-3.5 ${isTriggering ? "animate-spin" : ""}`} />
              Recompute
            </Button>
          </div>

          <div className="grid gap-2 sm:grid-cols-4">
            <div className="rounded-md border border-line bg-bg2 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">Rows</div>
              <div className="font-mono text-lg font-semibold">{counts.total}</div>
            </div>
            <div className="rounded-md border border-line bg-bg2 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">Actionable</div>
              <div className="font-mono text-lg font-semibold text-emerald-700">{counts.actionable}</div>
            </div>
            <div className="rounded-md border border-line bg-bg2 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">Watch</div>
              <div className="font-mono text-lg font-semibold text-blue-700">{counts.watch}</div>
            </div>
            <div className="rounded-md border border-line bg-bg2 px-3 py-2">
              <div className="text-[11px] text-muted-foreground">Latest job</div>
              <div className="truncate font-mono text-sm font-semibold">{latestStatus} - {latestPairs}</div>
            </div>
          </div>
          {triggerError ? (
            <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              <AlertTriangle className="h-3.5 w-3.5" />
              {triggerError}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.45fr)_minmax(340px,0.75fr)]">
        <Card>
          <CardHeader className="px-5 pb-2 pt-4">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <ShieldCheck className="h-4 w-4 text-primary" />
              Pair leaderboard
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {leaderboard.isLoading ? (
              <div className="space-y-1.5 p-4">
                {Array.from({ length: 10 }).map((_, index) => <Skeleton key={index} className="h-9 w-full" />)}
              </div>
            ) : leaderboard.error ? (
              <div className="px-4 py-8 text-center text-sm text-destructive">Erreur chargement stat-arb.</div>
            ) : rows.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">No statistical arbitrage rows yet.</div>
            ) : (
              <div className="max-h-[620px] overflow-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="text-xs">
                      <TableHead>Pair</TableHead>
                      <TableHead>Mode</TableHead>
                      <TableHead>Signal</TableHead>
                      <TableHead className="text-right">Z</TableHead>
                      <TableHead className="text-right">Sharpe</TableHead>
                      <TableHead className="text-right">FDR q</TableHead>
                      <TableHead className="text-right">OOS ret</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.map((row) => (
                      <TableRow
                        key={row.pair_id}
                        className={`cursor-pointer text-xs hover:bg-muted/60 ${selectedPairId === row.pair_id ? "bg-muted/60" : ""}`}
                        onClick={() => setSelectedPairId(row.pair_id)}
                      >
                        <TableCell><PairName row={row} /></TableCell>
                        <TableCell className="text-muted-foreground">{labelFor(ARCHETYPES, row.archetype)}</TableCell>
                        <TableCell className="font-mono">{row.current_signal}</TableCell>
                        <TableCell className="text-right font-mono tabular-nums">{fmt(row.zscore)}</TableCell>
                        <TableCell className="text-right font-mono tabular-nums">{fmt(row.oos_sharpe)}</TableCell>
                        <TableCell className="text-right font-mono tabular-nums">{fmt(row.fdr_qvalue, 3)}</TableCell>
                        <TableCell className="text-right font-mono tabular-nums">{fmtPct(row.oos_return)}</TableCell>
                        <TableCell><StatusBadge status={row.status} /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="px-5 pb-2 pt-4">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <LineChart className="h-4 w-4 text-primary" />
              Pair detail
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 p-4">
            {detail.isLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-8 w-40" />
                <Skeleton className="h-40 w-full" />
                <Skeleton className="h-20 w-full" />
              </div>
            ) : !detail.data ? (
              <div className="flex h-48 items-center justify-center rounded-md border border-dashed border-line text-sm text-muted-foreground">Select a pair</div>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <PairName row={detail.data} />
                  <StatusBadge status={detail.data.status} />
                </div>
                <MiniChart chart={detail.data.chart} />
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-md border border-line px-2 py-1.5">
                    <div className="text-muted-foreground">Direction</div>
                    <div className="font-mono font-semibold">{detail.data.direction}</div>
                  </div>
                  <div className="rounded-md border border-line px-2 py-1.5">
                    <div className="text-muted-foreground">Action type</div>
                    <div className="font-mono font-semibold">{detail.data.action_type}</div>
                  </div>
                  <div className="rounded-md border border-line px-2 py-1.5">
                    <div className="text-muted-foreground">Half-life</div>
                    <div className="font-mono font-semibold">{fmt(detail.data.half_life)}</div>
                  </div>
                  <div className="rounded-md border border-line px-2 py-1.5">
                    <div className="text-muted-foreground">Drawdown</div>
                    <div className="font-mono font-semibold">{fmtPct(detail.data.max_drawdown)}</div>
                  </div>
                  <div className="rounded-md border border-line px-2 py-1.5">
                    <div className="text-muted-foreground">Profitable folds</div>
                    <div className="font-mono font-semibold">{fmtPct(detail.data.profitable_fold_ratio)}</div>
                  </div>
                  <div className="rounded-md border border-line px-2 py-1.5">
                    <div className="text-muted-foreground">Data as of</div>
                    <div className="font-mono font-semibold">{detail.data.data_as_of ?? "--"}</div>
                  </div>
                </div>
                {detail.data.warnings.length > 0 ? (
                  <div className="flex flex-wrap gap-1">
                    {detail.data.warnings.slice(0, 8).map((warning) => (
                      <Badge key={warning} variant="outline" className="text-[10px] text-muted-foreground">{warning}</Badge>
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
