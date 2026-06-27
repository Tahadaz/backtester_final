"use client"

import { useMemo, useState } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import useSWR from "swr"
import {
  Activity,
  ArrowLeft,
  BarChart3,
  Database,
  GitCompareArrows,
  LineChart,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  type LucideIcon,
} from "lucide-react"
import {
  useFactorRelevance,
  useFactorSignalEval,
  useSignalEvaluation,
  useStatArbPairDetail,
} from "@/hooks/use-api"
import {
  fetchSignalBacktestResults,
  fetchSignalEvidence,
  type FactorSignalEval,
  type MacroBacktestReplay,
  type PlotlyFigure,
  type SignalBacktestResponse,
  type SignalBacktestResult,
  type SignalEvidence,
  type SignalEvaluationReport,
  type StatArbPairDetail,
} from "@/lib/api"
import { horizonLabel } from "@/lib/horizon"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { PlotlyChart } from "@/components/run/plotly-chart"

type QuantSourceType = "signal" | "macro" | "pair"
type QuantSleeve = "cross" | "trend" | "mean_reversion" | "volume" | "macro" | "pairs"
type QuantBias = "Long" | "Short" | "Neutral" | "Pair long/short" | "Pair continuation"
type QuantStatus = "Trade" | "Watch" | "Research" | "Reject"
type DetailTab = "overview" | "backtest" | "validation" | "rules"

type QuantStrategyCandidate = {
  id: string
  sourceType: QuantSourceType
  symbol: string
  sleeve: QuantSleeve
  sleeveLabel: string
  bias: QuantBias
  status: QuantStatus
  label: string
  category: string
  rawCategory: string | null
  factorId: string | null
  pairId: string | null
  horizon: string
  edge: number | null
  ic: number | null
  hitRate: number | null
  sharpe: number | null
  nObs: number | null
  fdrPass: boolean
  adv: number | null
  sector: string | null
  testStat: number | null
}

const SLEEVE_META: Record<QuantSleeve, { label: string; icon: LucideIcon; tone: string }> = {
  cross: { label: "Cross-sectional momentum", icon: BarChart3, tone: "border-blue-200 bg-blue-50 text-blue-700" },
  trend: { label: "Trend following", icon: TrendingUp, tone: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  mean_reversion: { label: "Mean reversion", icon: TrendingDown, tone: "border-amber-200 bg-amber-50 text-amber-800" },
  volume: { label: "Volume and flow", icon: Activity, tone: "border-sky-200 bg-sky-50 text-sky-700" },
  macro: { label: "Macro factor timing", icon: Database, tone: "border-violet-200 bg-violet-50 text-violet-700" },
  pairs: { label: "Pairs and stat-arb", icon: GitCompareArrows, tone: "border-slate-300 bg-slate-50 text-slate-700" },
}

const DEFAULT_HORIZON = "medium"
const DEFAULT_STATUS: QuantStatus = "Research"

function finite(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function boolParam(value: string | null): boolean {
  return value === "true" || value === "1" || value === "yes"
}

function param(searchParams: URLSearchParams, key: string): string | null {
  const value = searchParams.get(key)
  const trimmed = String(value ?? "").trim()
  return trimmed ? trimmed : null
}

function enumParam<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return allowed.includes(value as T) ? (value as T) : fallback
}

function fmt(value: unknown, digits = 2) {
  const numberValue = finite(value)
  if (numberValue == null) return "--"
  return numberValue.toFixed(digits)
}

function fmtSigned(value: unknown, digits = 2) {
  const numberValue = finite(value)
  if (numberValue == null) return "--"
  return `${numberValue >= 0 ? "+" : ""}${numberValue.toFixed(digits)}`
}

function fmtPct(value: unknown, digits = 1) {
  const numberValue = finite(value)
  if (numberValue == null) return "--"
  return `${(numberValue * 100).toFixed(digits)}%`
}

function fmtAdv(value: unknown) {
  const numberValue = finite(value)
  if (numberValue == null) return "--"
  if (numberValue >= 1_000_000) return `${(numberValue / 1_000_000).toFixed(1)}m`
  if (numberValue >= 1_000) return `${Math.round(numberValue / 1_000)}k`
  return Math.round(numberValue).toString()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function stringSeries(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === "string" && item.length > 0)
}

function alignedNumberSeries(value: unknown): Array<number | null> {
  if (!Array.isArray(value)) return []
  return value.map(finite)
}

function validNumberSeries(value: unknown): number[] {
  if (!Array.isArray(value)) return []
  return value.map(finite).filter((item): item is number => item != null)
}

function seriesHasValues(values: Array<number | null> | undefined): values is Array<number | null> {
  return Array.isArray(values) && values.some((value) => value != null)
}

function categoryText(value: string | null | undefined) {
  const token = String(value ?? "").trim()
  return token ? token.replace(/_/g, " ") : "signal"
}

function statusClass(status: QuantStatus) {
  if (status === "Trade") return "border-emerald-300 bg-emerald-50 text-emerald-700"
  if (status === "Watch") return "border-blue-300 bg-blue-50 text-blue-700"
  if (status === "Reject") return "border-red-300 bg-red-50 text-red-700"
  return "border-amber-300 bg-amber-50 text-amber-800"
}

function biasClass(bias: QuantBias) {
  if (bias === "Long" || bias === "Pair continuation") return "text-emerald-700"
  if (bias === "Short") return "text-red-700"
  if (bias === "Pair long/short") return "text-blue-700"
  return "text-muted-foreground"
}

function icTone(value: unknown): "positive" | "negative" | "neutral" | "blue" {
  const parsed = finite(value)
  if (parsed == null) return "neutral"
  return parsed >= 0 ? "positive" : "negative"
}

function makeFigure(data: Array<Record<string, unknown>>, layout: Record<string, unknown>): PlotlyFigure {
  return { data, layout }
}

function drawdownFromEquity(values: number[]) {
  let peak = Number.NEGATIVE_INFINITY
  return values.map((value) => {
    peak = Math.max(peak, value)
    if (!Number.isFinite(peak) || Math.abs(peak) < 1e-9) return 0
    return (value - peak) / Math.abs(peak)
  })
}

function selectedBacktestDirection(candidate: QuantStrategyCandidate): "long" | "short" | null {
  if (candidate.bias === "Long" || candidate.bias === "Pair continuation") return "long"
  if (candidate.bias === "Short") return "short"
  return null
}

function categoryMatchScore(row: SignalBacktestResult, candidate: QuantStrategyCandidate): number {
  const category = String(candidate.rawCategory ?? "").trim().toLowerCase()
  const scope = String(row.scope ?? "").trim().toLowerCase()
  const scopeKey = String(row.scope_key ?? "").trim().toLowerCase()
  if (category && scope === "per_category" && scopeKey === category) return 60
  if (category && scope === "combination" && scopeKey.split("+").map((item) => item.trim()).includes(category)) return 40
  if (scope === "global" && candidate.sleeve === "cross") return 35
  if (category && scopeKey.includes(category)) return 20
  return 0
}

function hasBacktestChartSeries(row: SignalBacktestResult) {
  return row.status === "succeeded" && Array.isArray(row.dates) && Array.isArray(row.close_series) && row.dates.length > 1 && row.close_series.length > 1
}

function selectSignalBacktestResult(response: SignalBacktestResponse | undefined, candidate: QuantStrategyCandidate): SignalBacktestResult | null {
  const rows = (response?.results ?? []).filter(hasBacktestChartSeries)
  if (rows.length === 0) return null
  return [...rows].sort((left, right) => {
    const score = (row: SignalBacktestResult) => {
      const sourceScore = row.source === "wfo" ? 80 : row.source === "engine" ? 45 : 0
      const policyScore = row.side_policy === "long_short" ? 20 : 0
      const matchScore = categoryMatchScore(row, candidate)
      const tradeScore = Math.min(15, finite(row.metrics.n_trades) ?? 0)
      const sharpeScore = Math.max(0, Math.min(20, (finite(row.metrics.sharpe) ?? 0) * 5))
      return sourceScore + policyScore + matchScore + tradeScore + sharpeScore
    }
    return score(right) - score(left)
  })[0] ?? null
}

function markerRows(row: SignalBacktestResult, sideToken: string) {
  const ledger = Array.isArray(row.trade_ledger) ? row.trade_ledger : []
  return ledger.filter((item) => {
    const side = String(isRecord(item) ? item.side ?? "" : "").toUpperCase()
    return side.includes(sideToken)
  })
}

function markerY(item: unknown): number | null {
  if (!isRecord(item)) return null
  return finite(item.prix_execution) ?? finite(item.open_t_plus_1) ?? finite(item.close_du_jour) ?? finite(item.open_price) ?? finite(item.close_price)
}

function markerDate(item: unknown): string {
  if (!isRecord(item)) return ""
  return String(item.date ?? item.open_date ?? item.close_date ?? "").slice(0, 10)
}

function makePriceTradesFigure(row: SignalBacktestResult, candidate: QuantStrategyCandidate): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const close = alignedNumberSeries(row.close_series)
  if (dates.length < 2 || close.length < 2) return null
  const score = alignedNumberSeries(row.score_series ?? row.global_score_series)
  const position = alignedNumberSeries(row.position_series)
  const buys = markerRows(row, "ACHAT")
  const sells = markerRows(row, "VENTE")
  const scoreLabel = candidate.rawCategory ? `${categoryText(candidate.rawCategory)} score` : "Signal score"
  const data: Array<Record<string, unknown>> = [
    {
      type: "scatter",
      mode: "lines",
      name: "Close",
      x: dates,
      y: close,
      line: { color: "#0f172a", width: 2 },
      hovertemplate: "%{x}<br>Close %{y:.2f}<extra></extra>",
    },
  ]
  if (seriesHasValues(score)) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: scoreLabel,
      x: dates,
      y: score,
      yaxis: "y2",
      line: { color: "#2563eb", width: 1.6, dash: "dot" },
      hovertemplate: "%{x}<br>Score %{y:.1f}<extra></extra>",
    })
  }
  if (seriesHasValues(position)) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: "Position",
      x: dates,
      y: position,
      yaxis: "y3",
      line: { color: "#7c3aed", width: 1.2, shape: "hv" },
      hovertemplate: "%{x}<br>Position %{y:.0f}<extra></extra>",
    })
  }
  if (buys.length > 0) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: "Buy",
      x: buys.map(markerDate),
      y: buys.map(markerY),
      marker: { color: "#059669", size: 10, symbol: "triangle-up", line: { color: "#ffffff", width: 1 } },
      hovertemplate: "%{x}<br>Buy %{y:.2f}<extra></extra>",
    })
  }
  if (sells.length > 0) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: "Sell",
      x: sells.map(markerDate),
      y: sells.map(markerY),
      marker: { color: "#dc2626", size: 10, symbol: "triangle-down", line: { color: "#ffffff", width: 1 } },
      hovertemplate: "%{x}<br>Sell %{y:.2f}<extra></extra>",
    })
  }
  return makeFigure(data, {
    title: { text: "Price, score and trades", font: { size: 13 } },
    margin: { l: 48, r: 56, t: 36, b: 42 },
    legend: { orientation: "h", y: 1.08, x: 0 },
    xaxis: { title: "", rangeslider: { visible: false } },
    yaxis: { title: "Price" },
    yaxis2: { title: "Score", overlaying: "y", side: "right", showgrid: false, zeroline: true },
    yaxis3: { title: "Position", overlaying: "y", side: "right", anchor: "free", position: 0.98, showgrid: false, visible: false },
  })
}

function makeEquityFigure(row: SignalBacktestResult): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const equity = alignedNumberSeries(row.equity)
  if (dates.length < 2 || equity.length < 2) return null
  const envelope = row.mc?.envelope
  const data: Array<Record<string, unknown>> = [
    { type: "scatter", mode: "lines", name: "Equity", x: dates, y: equity, line: { color: "#2563eb", width: 2 }, hovertemplate: "%{x}<br>Equity %{y:.3f}<extra></extra>" },
  ]
  if (envelope?.p05?.length && envelope?.p95?.length) {
    data.push(
      { type: "scatter", mode: "lines", name: "MC p05", x: dates, y: envelope.p05, line: { color: "rgba(37, 99, 235, 0.18)", width: 1 }, hoverinfo: "skip" },
      { type: "scatter", mode: "lines", name: "MC p95", x: dates, y: envelope.p95, fill: "tonexty", fillcolor: "rgba(37, 99, 235, 0.10)", line: { color: "rgba(37, 99, 235, 0.18)", width: 1 }, hoverinfo: "skip" },
    )
  }
  if (envelope?.p50?.length) {
    data.push({ type: "scatter", mode: "lines", name: "MC p50", x: dates, y: envelope.p50, line: { color: "#94a3b8", width: 1, dash: "dash" }, hovertemplate: "%{x}<br>MC p50 %{y:.3f}<extra></extra>" })
  }
  return makeFigure(data, {
    title: { text: "Equity curve", font: { size: 13 } },
    margin: { l: 48, r: 20, t: 36, b: 42 },
    legend: { orientation: "h", y: 1.08, x: 0 },
    xaxis: { title: "" },
    yaxis: { title: "Equity" },
  })
}

function makeDrawdownFigure(row: SignalBacktestResult): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const equity = validNumberSeries(row.equity)
  if (dates.length < 2 || equity.length < 2) return null
  const drawdown = drawdownFromEquity(equity)
  return makeFigure(
    [{ type: "scatter", mode: "lines", name: "Drawdown", x: dates.slice(0, drawdown.length), y: drawdown, fill: "tozeroy", line: { color: "#dc2626", width: 1.8 }, hovertemplate: "%{x}<br>Drawdown %{y:.2%}<extra></extra>" }],
    { title: { text: "Drawdown curve", font: { size: 13 } }, margin: { l: 48, r: 20, t: 36, b: 42 }, xaxis: { title: "" }, yaxis: { title: "Drawdown", tickformat: ".0%" } },
  )
}

function monthlyReturnGrid(dates: string[], equity: number[]) {
  const buckets = new Map<string, { year: number; month: number; start: number; end: number }>()
  for (let index = 0; index < Math.min(dates.length, equity.length); index += 1) {
    const value = equity[index]
    if (!Number.isFinite(value)) continue
    const date = new Date(dates[index])
    if (Number.isNaN(date.getTime())) continue
    const year = date.getUTCFullYear()
    const month = date.getUTCMonth()
    const key = `${year}-${month}`
    const existing = buckets.get(key)
    if (existing) existing.end = value
    else buckets.set(key, { year, month, start: value, end: value })
  }
  const years = Array.from(new Set(Array.from(buckets.values()).map((item) => item.year))).sort((a, b) => a - b)
  const z = years.map((year) =>
    Array.from({ length: 12 }, (_, month) => {
      const bucket = buckets.get(`${year}-${month}`)
      if (!bucket || bucket.start === 0) return null
      return bucket.end / bucket.start - 1
    }),
  )
  return { years, z }
}

function makeMonthlyHeatmapFigure(row: SignalBacktestResult): PlotlyFigure | null {
  const dates = stringSeries(row.dates)
  const equity = validNumberSeries(row.equity)
  if (dates.length < 2 || equity.length < 2) return null
  const { years, z } = monthlyReturnGrid(dates, equity)
  if (years.length === 0) return null
  return makeFigure(
    [{
      type: "heatmap",
      x: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
      y: years,
      z,
      colorscale: [[0, "#dc2626"], [0.5, "#f8fafc"], [1, "#059669"]],
      zmid: 0,
      hovertemplate: "%{y} %{x}<br>%{z:.2%}<extra></extra>",
      colorbar: { tickformat: ".0%" },
    }],
    { title: { text: "Monthly return heatmap", font: { size: 13 } }, margin: { l: 44, r: 16, t: 36, b: 42 }, xaxis: { title: "" }, yaxis: { title: "" } },
  )
}

function compactDateNumberSeries(dates: string[], values: unknown) {
  const y = alignedNumberSeries(values)
  const xOut: string[] = []
  const yOut: number[] = []
  for (let index = 0; index < Math.min(dates.length, y.length); index += 1) {
    const value = y[index]
    if (value == null) continue
    xOut.push(dates[index])
    yOut.push(value)
  }
  return { x: xOut, y: yOut }
}

function makeMacroPriceTradesFigure(replay: MacroBacktestReplay, report: FactorSignalEval, candidate: QuantStrategyCandidate): PlotlyFigure | null {
  const dates = stringSeries(replay.dates)
  const stock = compactDateNumberSeries(dates, replay.stock_close)
  const factor = compactDateNumberSeries(dates, replay.factor_close)
  const signal = compactDateNumberSeries(dates, replay.signal)
  const position = compactDateNumberSeries(dates, replay.position)
  if (stock.x.length < 2) return null
  const ledger = Array.isArray(replay.trade_ledger) ? replay.trade_ledger : []
  const buys = ledger.filter((item) => String(item.side ?? "").toUpperCase().includes("ACHAT"))
  const sells = ledger.filter((item) => String(item.side ?? "").toUpperCase().includes("VENTE"))
  const data: Array<Record<string, unknown>> = [
    {
      type: "scatter",
      mode: "lines",
      name: `${candidate.symbol} close`,
      x: stock.x,
      y: stock.y,
      line: { color: "#0f172a", width: 2 },
      hovertemplate: "%{x}<br>Stock %{y:.2f}<extra></extra>",
    },
  ]
  if (factor.x.length > 1) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: `${report.factor_id} close`,
      x: factor.x,
      y: factor.y,
      yaxis: "y2",
      line: { color: "#7c3aed", width: 1.7 },
      hovertemplate: `%{x}<br>${report.factor_id} %{y:.2f}<extra></extra>`,
    })
  }
  if (signal.x.length > 1) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: "Macro signal",
      x: signal.x,
      y: signal.y,
      yaxis: "y3",
      line: { color: "#2563eb", width: 1.4, dash: "dot", shape: "hv" },
      hovertemplate: "%{x}<br>Signal %{y:.0f}<extra></extra>",
    })
  }
  if (position.x.length > 1) {
    data.push({
      type: "scatter",
      mode: "lines",
      name: "Position",
      x: position.x,
      y: position.y,
      yaxis: "y3",
      line: { color: "#059669", width: 1.2, shape: "hv" },
      hovertemplate: "%{x}<br>Position %{y:.0f}<extra></extra>",
    })
  }
  if (buys.length > 0) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: "Buy / cover",
      x: buys.map(markerDate),
      y: buys.map(markerY),
      marker: { color: "#059669", size: 10, symbol: "triangle-up", line: { color: "#ffffff", width: 1 } },
      hovertemplate: "%{x}<br>Buy %{y:.2f}<extra></extra>",
    })
  }
  if (sells.length > 0) {
    data.push({
      type: "scatter",
      mode: "markers",
      name: "Sell / short",
      x: sells.map(markerDate),
      y: sells.map(markerY),
      marker: { color: "#dc2626", size: 10, symbol: "triangle-down", line: { color: "#ffffff", width: 1 } },
      hovertemplate: "%{x}<br>Sell %{y:.2f}<extra></extra>",
    })
  }
  return makeFigure(data, {
    title: { text: "Stock, macro factor, signal and trades", font: { size: 13 } },
    margin: { l: 48, r: 64, t: 36, b: 42 },
    legend: { orientation: "h", y: 1.1, x: 0 },
    xaxis: { title: "", rangeslider: { visible: false } },
    yaxis: { title: "Stock" },
    yaxis2: { title: report.factor_id, overlaying: "y", side: "right", showgrid: false },
    yaxis3: { title: "Signal", overlaying: "y", side: "right", anchor: "free", position: 0.98, range: [-1.25, 1.25], showgrid: false, zeroline: true },
  })
}

function makeMacroFactorVariationFigure(replay: MacroBacktestReplay, report: FactorSignalEval): PlotlyFigure | null {
  const dates = stringSeries(replay.dates)
  const factorReturn = compactDateNumberSeries(dates, replay.factor_return)
  if (factorReturn.x.length < 2) return null
  return makeFigure(
    [{
      type: "bar",
      name: `${report.factor_id} daily variation`,
      x: factorReturn.x,
      y: factorReturn.y,
      marker: { color: factorReturn.y.map((value) => (value >= 0 ? "#059669" : "#dc2626")) },
      hovertemplate: `%{x}<br>${report.factor_id} %{y:.2%}<extra></extra>`,
    }],
    { title: { text: `${report.factor_id} variation`, font: { size: 13 } }, margin: { l: 48, r: 18, t: 36, b: 42 }, xaxis: { title: "" }, yaxis: { title: "Variation", tickformat: ".1%" } },
  )
}

function makeMacroEquityFigure(replay: MacroBacktestReplay): PlotlyFigure | null {
  const dates = stringSeries(replay.dates)
  const equity = compactDateNumberSeries(dates, replay.equity)
  if (equity.x.length < 2) return null
  return makeFigure(
    [{ type: "scatter", mode: "lines", name: "Equity", x: equity.x, y: equity.y, line: { color: "#2563eb", width: 2 }, hovertemplate: "%{x}<br>Equity %{y:.3f}<extra></extra>" }],
    { title: { text: "Macro strategy equity", font: { size: 13 } }, margin: { l: 48, r: 20, t: 36, b: 42 }, xaxis: { title: "" }, yaxis: { title: "Equity" } },
  )
}

function makeMacroDrawdownFigure(replay: MacroBacktestReplay): PlotlyFigure | null {
  const dates = stringSeries(replay.dates)
  let drawdown = compactDateNumberSeries(dates, replay.drawdown)
  if (drawdown.x.length < 2) {
    const equity = compactDateNumberSeries(dates, replay.equity)
    drawdown = { x: equity.x, y: drawdownFromEquity(equity.y) }
  }
  if (drawdown.x.length < 2) return null
  return makeFigure(
    [{ type: "scatter", mode: "lines", name: "Drawdown", x: drawdown.x, y: drawdown.y, fill: "tozeroy", line: { color: "#dc2626", width: 1.8 }, hovertemplate: "%{x}<br>Drawdown %{y:.2%}<extra></extra>" }],
    { title: { text: "Macro strategy drawdown", font: { size: 13 } }, margin: { l: 48, r: 20, t: 36, b: 42 }, xaxis: { title: "" }, yaxis: { title: "Drawdown", tickformat: ".0%" } },
  )
}

function makeMacroMonthlyHeatmapFigure(replay: MacroBacktestReplay): PlotlyFigure | null {
  const dates = stringSeries(replay.dates)
  const equity = compactDateNumberSeries(dates, replay.equity)
  if (equity.x.length < 2) return null
  const { years, z } = monthlyReturnGrid(equity.x, equity.y)
  if (years.length === 0) return null
  return makeFigure(
    [{
      type: "heatmap",
      x: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
      y: years,
      z,
      colorscale: [[0, "#dc2626"], [0.5, "#f8fafc"], [1, "#059669"]],
      zmid: 0,
      hovertemplate: "%{y} %{x}<br>%{z:.2%}<extra></extra>",
      colorbar: { tickformat: ".0%" },
    }],
    { title: { text: "Macro monthly return heatmap", font: { size: 13 } }, margin: { l: 44, r: 16, t: 36, b: 42 }, xaxis: { title: "" }, yaxis: { title: "" } },
  )
}

function buildCandidate(searchParams: URLSearchParams, id: string): QuantStrategyCandidate {
  const sourceType = enumParam<QuantSourceType>(param(searchParams, "sourceType"), ["signal", "macro", "pair"], "signal")
  const sleeve = enumParam<QuantSleeve>(param(searchParams, "sleeve"), ["cross", "trend", "mean_reversion", "volume", "macro", "pairs"], sourceType === "macro" ? "macro" : sourceType === "pair" ? "pairs" : "cross")
  const bias = enumParam<QuantBias>(param(searchParams, "bias"), ["Long", "Short", "Neutral", "Pair long/short", "Pair continuation"], "Neutral")
  const status = enumParam<QuantStatus>(param(searchParams, "status"), ["Trade", "Watch", "Research", "Reject"], DEFAULT_STATUS)
  const rawCategory = param(searchParams, "rawCategory")
  return {
    id,
    sourceType,
    symbol: param(searchParams, "symbol") ?? "--",
    sleeve,
    sleeveLabel: param(searchParams, "sleeveLabel") ?? SLEEVE_META[sleeve].label,
    bias,
    status,
    label: param(searchParams, "label") ?? id,
    category: param(searchParams, "category") ?? categoryText(rawCategory),
    rawCategory,
    factorId: param(searchParams, "factorId"),
    pairId: param(searchParams, "pairId"),
    horizon: param(searchParams, "horizon") ?? DEFAULT_HORIZON,
    edge: finite(searchParams.get("edge")),
    ic: finite(searchParams.get("ic")),
    hitRate: finite(searchParams.get("hitRate")),
    sharpe: finite(searchParams.get("sharpe")),
    nObs: finite(searchParams.get("nObs")),
    fdrPass: boolParam(searchParams.get("fdrPass")),
    adv: finite(searchParams.get("adv")),
    sector: param(searchParams, "sector"),
    testStat: finite(searchParams.get("testStat")),
  }
}

function thesisSummary(candidate: QuantStrategyCandidate) {
  if (candidate.sleeve === "trend") return "Trend following keeps exposure only when persistent directional strength has historically ranked forward returns correctly."
  if (candidate.sleeve === "mean_reversion") return "Mean reversion fades stretched oscillator states only when the historical bucket return and hit-rate evidence justify the risk."
  if (candidate.sleeve === "volume") return "Volume and flow confirm whether price movement is supported by participation, accumulation or distribution."
  if (candidate.sleeve === "macro") return "Macro timing conditions the stock on external risk factors, then requires relevance and portfolio tests before promotion."
  if (candidate.sleeve === "pairs") return "Pairs and stat-arb trade relative dislocation or lead-lag continuation only after stationarity, FDR, OOS and drawdown gates."
  return "Cross-sectional momentum ranks securities against peers and promotes names whose score has predictive power after IC, FDR and execution gates."
}

function methodSummary(candidate: QuantStrategyCandidate) {
  if (candidate.sourceType === "macro") return "Inputs: factor relevance, IC/t-stat screen, FDR gate, after-cost portfolio evaluation, DSR/PSR robustness and cited macro rule."
  if (candidate.sourceType === "pair") return "Inputs: pair construction, hedge ratio, z-score state, ADF/FDR, OOS Sharpe, drawdown, fold profitability and explicit cost assumptions."
  return "Inputs: category score history, IC decay, conditional return t-stat, hit-rate interval, after-cost backtest, Monte Carlo envelope and representative indicator rules."
}

function MetricTile({ label, value, sub, tone = "neutral" }: { label: string; value: string; sub?: string; tone?: "positive" | "negative" | "neutral" | "blue" }) {
  return (
    <div className="rounded-lg border border-line bg-card px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className={cn("mt-1 truncate font-mono text-xl font-semibold tabular-nums", tone === "positive" && "text-emerald-700", tone === "negative" && "text-red-700", tone === "blue" && "text-blue-700")}>
        {value}
      </div>
      {sub ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

function EvidenceMetric({ label, value, sub, tone = "neutral" }: { label: string; value: string; sub?: string; tone?: "positive" | "negative" | "neutral" | "blue" }) {
  return (
    <div className="rounded-md border border-line bg-bg2 px-2.5 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">{label}</div>
      <div className={cn("mt-1 truncate font-mono text-sm font-semibold tabular-nums", tone === "positive" && "text-emerald-700", tone === "negative" && "text-red-700", tone === "blue" && "text-blue-700")}>{value}</div>
      {sub ? <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

function DecisionPipeline({
  candidate,
  backtestRow,
  backtestLoading,
  macroReport,
}: {
  candidate: QuantStrategyCandidate
  backtestRow: SignalBacktestResult | null
  backtestLoading?: boolean
  macroReport?: FactorSignalEval | null
}) {
  const backtestValue = candidate.sourceType === "macro"
    ? backtestLoading
      ? "Loading"
      : macroReport?.backtest
        ? fmtSigned(macroReport.after_cost_sharpe, 2)
        : "Unavailable"
    : backtestLoading
      ? "Loading"
      : backtestRow
        ? fmtSigned(backtestRow.metrics.sharpe, 2)
        : "Unavailable"
  const backtestPass = candidate.sourceType === "macro"
    ? Boolean(macroReport?.backtest && (macroReport.after_cost_sharpe ?? 0) > 0)
    : Boolean(backtestRow && (backtestRow.metrics.sharpe ?? 0) > 0)
  const steps = [
    { label: "Candidate", value: candidate.sleeveLabel, pass: true },
    { label: "IC", value: fmtSigned(candidate.ic, 3), pass: (candidate.ic ?? 0) > 0 },
    { label: "FDR", value: candidate.fdrPass ? "Pass" : "Not passed", pass: candidate.fdrPass },
    { label: "Backtest", value: backtestValue, pass: backtestPass },
    { label: "Decision", value: candidate.status, pass: candidate.status === "Trade" || candidate.status === "Watch" },
  ]
  return (
    <div className="grid gap-2 md:grid-cols-5">
      {steps.map((step, index) => (
        <div key={step.label} className="rounded-lg border border-line bg-card px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{index + 1}. {step.label}</div>
            <span className={cn("h-2.5 w-2.5 rounded-full", step.pass ? "bg-emerald-500" : "bg-amber-500")} />
          </div>
          <div className="mt-1 truncate text-sm font-semibold">{step.value}</div>
        </div>
      ))}
    </div>
  )
}

function ICDecayChart({ report }: { report: Pick<SignalEvaluationReport, "ic_curve"> | Pick<FactorSignalEval, "ic_curve"> | null }) {
  const horizons = report?.ic_curve.horizons ?? []
  const values = report?.ic_curve.ic_values ?? []
  const maxAbs = Math.max(...values.map((value) => Math.abs(value)).filter((value) => Number.isFinite(value)), 0.01)
  if (horizons.length === 0 || values.length === 0) {
    return <div className="rounded-md border border-dashed border-line px-3 py-8 text-center text-xs text-muted-foreground">IC curve unavailable.</div>
  }
  return (
    <div className="rounded-md border border-line bg-card px-3 py-3">
      <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.06em] text-muted-foreground">IC decay by forward horizon</div>
      <div className="flex h-28 items-end gap-2">
        {horizons.map((horizon, index) => {
          const ic = finite(values[index])
          const height = ic == null ? 4 : Math.max(5, (Math.abs(ic) / maxAbs) * 76)
          return (
            <div key={`${horizon}-${index}`} className="flex min-w-0 flex-1 flex-col items-center gap-1">
              <div className="font-mono text-[10px] tabular-nums">{ic == null ? "--" : fmtSigned(ic, 2)}</div>
              <div className={cn("w-full rounded-sm", ic == null ? "bg-muted" : ic >= 0 ? "bg-emerald-500" : "bg-red-400")} style={{ height: `${height}px` }} />
              <div className="text-[10px] text-muted-foreground">d{horizon}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SignalTradeLedgerTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) {
    return <div className="rounded-md border border-dashed border-line px-3 py-6 text-center text-xs text-muted-foreground">No realized fills in this selected backtest window.</div>
  }
  return (
    <div className="overflow-hidden rounded-md border border-line bg-card">
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <TableHead>Date</TableHead>
            <TableHead>Side</TableHead>
            <TableHead className="text-right">Score</TableHead>
            <TableHead className="text-right">Exec</TableHead>
            <TableHead className="text-right">Position</TableHead>
            <TableHead className="text-right">Return</TableHead>
            <TableHead className="text-right">Realized PnL</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 28).map((row, index) => {
            const side = String(row.side ?? "--")
            return (
              <TableRow key={`${String(row.date ?? "")}-${index}`} className="text-xs">
                <TableCell className="font-mono">{String(row.date ?? "--").slice(0, 10)}</TableCell>
                <TableCell className={side.toUpperCase().includes("ACHAT") ? "font-semibold text-emerald-700" : "font-semibold text-red-700"}>{side}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.global_score_pct), 1)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.prix_execution), 2)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.position), 0)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmtPct(finite(row.return_cumule), 1)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.pnl_realise), 2)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.cout), 2)}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function MacroTradeLedgerTable({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (rows.length === 0) {
    return <div className="rounded-md border border-dashed border-line px-3 py-6 text-center text-xs text-muted-foreground">No macro position changes in this replay window.</div>
  }
  return (
    <div className="overflow-hidden rounded-md border border-line bg-card">
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <TableHead>Date</TableHead>
            <TableHead>Side</TableHead>
            <TableHead className="text-right">Signal</TableHead>
            <TableHead className="text-right">Factor</TableHead>
            <TableHead className="text-right">Exec</TableHead>
            <TableHead className="text-right">Position</TableHead>
            <TableHead className="text-right">Ret.</TableHead>
            <TableHead className="text-right">Equity</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 40).map((row, index) => {
            const side = String(row.side ?? "--")
            return (
              <TableRow key={`${String(row.date ?? "")}-${index}`} className="text-xs">
                <TableCell className="font-mono">{String(row.execution_date ?? row.date ?? "--").slice(0, 10)}</TableCell>
                <TableCell className={side.toUpperCase().includes("ACHAT") ? "font-semibold text-emerald-700" : "font-semibold text-red-700"}>{side}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.signal_value), 0)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.factor_value), 2)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.prix_execution), 2)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.position), 0)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmtPct(finite(row.strategy_return), 2)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmt(finite(row.equity), 3)}</TableCell>
                <TableCell className="text-right font-mono tabular-nums">{fmtPct(finite(row.cout), 2)}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function representativeRows(row: SignalBacktestResult | null, evidence: SignalEvidence | undefined) {
  const diagnostics = isRecord(row?.signal_diagnostics) ? row.signal_diagnostics : null
  const rawDiagnostics = Array.isArray(diagnostics?.representatives) ? diagnostics.representatives : []
  const diagnosticRows = rawDiagnostics.filter(isRecord).map((rep, index) => ({
    id: String(rep.variant_id ?? rep.family ?? rep.description ?? `diagnostic-${index}`),
    title: String(rep.description ?? rep.variant_id ?? rep.family ?? "Indicator rule"),
    meta: [rep.family, rep.archetype].filter(Boolean).join(" / "),
    params: isRecord(rep.params) ? rep.params : {},
    current: finite(rep.indicator_value),
    label: String(rep.signal_label ?? ""),
  }))
  const evidenceRows = (evidence?.contributors ?? []).map((item) => ({
    id: String(item.variant_id || `${item.category}:${item.family}:${item.description}`),
    title: item.description || item.variant_id || item.family,
    meta: [categoryText(item.category), item.family, item.archetype].filter(Boolean).join(" / "),
    params: item.params,
    current: finite(item.indicator_value),
    label: item.signal_label,
  }))
  const seen = new Set<string>()
  return [...diagnosticRows, ...evidenceRows].filter((item) => {
    const key = item.id || `${item.title}:${item.meta}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function paramsText(params: Record<string, unknown>) {
  return Object.entries(params)
    .filter(([, value]) => value != null && typeof value !== "object")
    .slice(0, 8)
    .map(([key, value]) => `${key.replace(/_/g, " ")}=${String(value)}`)
    .join(", ")
}

function OverviewTab({ candidate, signalReport, macroReport, pairDetail, backtestRow, backtestLoading }: { candidate: QuantStrategyCandidate; signalReport?: SignalEvaluationReport; macroReport?: FactorSignalEval | null; pairDetail?: StatArbPairDetail; backtestRow: SignalBacktestResult | null; backtestLoading?: boolean }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Research thesis</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-foreground">{thesisSummary(candidate)}</p>
          <p className="text-sm text-muted-foreground">{methodSummary(candidate)}</p>
          <DecisionPipeline candidate={candidate} backtestRow={backtestRow} backtestLoading={backtestLoading} macroReport={macroReport} />
        </CardContent>
      </Card>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <MetricTile label="Screen score" value={fmt(candidate.edge, 0)} sub={`${candidate.sleeveLabel} rank`} tone="blue" />
        <MetricTile label="IC" value={fmtSigned(candidate.ic, 3)} sub={candidate.category} tone={icTone(candidate.ic)} />
        <MetricTile label="Hit / fold" value={fmtPct(candidate.hitRate, 1)} sub={`${candidate.nObs ?? "--"} observations`} tone={(candidate.hitRate ?? 0.5) >= 0.5 ? "positive" : "negative"} />
        <MetricTile label="Gate" value={candidate.status} sub={candidate.fdrPass ? "FDR pass" : "FDR not passed"} tone={candidate.status === "Reject" ? "negative" : candidate.status === "Trade" ? "positive" : "blue"} />
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <EvidenceMetric label="Signal Sharpe" value={fmtSigned(candidate.sharpe, 2)} sub={signalReport ? `Portfolio ${fmtSigned(signalReport.portfolio.after_cost_sharpe, 2)}` : "screen row"} tone={icTone(candidate.sharpe)} />
        <EvidenceMetric label="Macro test" value={fmtSigned(macroReport?.conditional_return_tstat ?? candidate.testStat, 2)} sub={macroReport?.factor_id ?? candidate.factorId ?? "not macro"} tone={icTone(macroReport?.conditional_return_tstat ?? candidate.testStat)} />
        <EvidenceMetric label="Pair OOS" value={fmtSigned(pairDetail?.oos_sharpe, 2)} sub={pairDetail ? `${pairDetail.n_folds} folds` : "not pair"} tone={icTone(pairDetail?.oos_sharpe)} />
      </div>
    </div>
  )
}

function MacroBacktestSurface({ candidate, macroReport, macroLoading }: { candidate: QuantStrategyCandidate; macroReport?: FactorSignalEval | null; macroLoading: boolean }) {
  if (macroLoading) {
    return (
      <div className="space-y-3">
        <div className="rounded-md border border-line bg-card px-3 py-2 text-xs text-muted-foreground">
          Loading the macro factor replay for this strategy.
        </div>
        <Skeleton className="h-64 rounded-lg" />
        <div className="grid gap-3 xl:grid-cols-3"><Skeleton className="h-52 rounded-lg" /><Skeleton className="h-52 rounded-lg" /><Skeleton className="h-52 rounded-lg" /></div>
      </div>
    )
  }

  const replay = macroReport?.backtest ?? null
  if (!macroReport || !replay) {
    return (
      <Card className="border-amber-300 bg-amber-50/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-amber-900">Macro replay unavailable</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-amber-900">
          The macro evaluation endpoint did not return a replay for {candidate.symbol}/{candidate.factorId ?? "factor"}. Check macro factor ingestion and the pre-registered factor signal configuration.
        </CardContent>
      </Card>
    )
  }

  const p = macroReport.portfolio
  const priceFigure = makeMacroPriceTradesFigure(replay, macroReport, candidate)
  const factorVariationFigure = makeMacroFactorVariationFigure(replay, macroReport)
  const equityFigure = makeMacroEquityFigure(replay)
  const drawdownFigure = makeMacroDrawdownFigure(replay)
  const monthlyFigure = makeMacroMonthlyHeatmapFigure(replay)
  const ledgerRows = Array.isArray(replay.trade_ledger) ? replay.trade_ledger : []

  return (
    <div className="space-y-4">
      <div className="grid gap-2 md:grid-cols-4">
        <EvidenceMetric label="Return" value={fmtPct(p.total_return, 1)} sub={replay.return_method.replace(/_/g, " ")} tone={icTone(p.total_return)} />
        <EvidenceMetric label="Net Sharpe" value={fmtSigned(macroReport.after_cost_sharpe, 2)} sub={`Gross ${fmtSigned(macroReport.sharpe, 2)}`} tone={icTone(macroReport.after_cost_sharpe)} />
        <EvidenceMetric label="Max DD" value={fmtPct(p.max_drawdown, 1)} sub={`Hit ${fmtPct(macroReport.hit_rate, 0)}`} tone="negative" />
        <EvidenceMetric label="Factor" value={macroReport.factor_id} sub={`${p.n_trades} trades, ${fmt(replay.cost_bps, 0)} bps`} tone="blue" />
      </div>
      <div className="rounded-lg border border-line bg-card p-2">
        {priceFigure ? <PlotlyChart figure={priceFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No macro price chart available.</div>}
      </div>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Macro trades ledger</CardTitle></CardHeader>
        <CardContent><MacroTradeLedgerTable rows={ledgerRows} /></CardContent>
      </Card>
      <div className="grid gap-3 xl:grid-cols-4">
        <div className="rounded-lg border border-line bg-card p-2">{factorVariationFigure ? <PlotlyChart figure={factorVariationFigure} /> : <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">No factor variation curve available.</div>}</div>
        <div className="rounded-lg border border-line bg-card p-2">{equityFigure ? <PlotlyChart figure={equityFigure} /> : <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">No equity curve available.</div>}</div>
        <div className="rounded-lg border border-line bg-card p-2">{drawdownFigure ? <PlotlyChart figure={drawdownFigure} /> : <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">No drawdown curve available.</div>}</div>
        <div className="rounded-lg border border-line bg-card p-2">{monthlyFigure ? <PlotlyChart figure={monthlyFigure} /> : <div className="flex h-72 items-center justify-center text-xs text-muted-foreground">No monthly heatmap available.</div>}</div>
      </div>
    </div>
  )
}

function BacktestTab({ candidate, backtest, backtestRow, macroReport, macroLoading }: { candidate: QuantStrategyCandidate; backtest: ReturnType<typeof useSignalBacktest>; backtestRow: SignalBacktestResult | null; macroReport?: FactorSignalEval | null; macroLoading: boolean }) {
  const priceFigure = backtestRow ? makePriceTradesFigure(backtestRow, candidate) : null
  const equityFigure = backtestRow ? makeEquityFigure(backtestRow) : null
  const drawdownFigure = backtestRow ? makeDrawdownFigure(backtestRow) : null
  const monthlyFigure = backtestRow ? makeMonthlyHeatmapFigure(backtestRow) : null
  const metrics = backtestRow?.metrics
  const ledgerRows = Array.isArray(backtestRow?.trade_ledger) ? backtestRow.trade_ledger : []

  if (candidate.sourceType === "macro") {
    return <MacroBacktestSurface candidate={candidate} macroReport={macroReport} macroLoading={macroLoading} />
  }

  if (candidate.sourceType !== "signal") {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">
          Pair replay charts are not promoted into this Backtest tab yet. The pair spread, z-score, OOS Sharpe and drawdown evidence are shown in Validation.
        </CardContent>
      </Card>
    )
  }

  if (backtest.isLoading) {
    return (
      <div className="space-y-3">
        <div className="rounded-md border border-line bg-card px-3 py-2 text-xs text-muted-foreground">
          Loading the stored signal backtest replay for this strategy.
        </div>
        <Skeleton className="h-64 rounded-lg" />
        <div className="grid gap-3 xl:grid-cols-3"><Skeleton className="h-52 rounded-lg" /><Skeleton className="h-52 rounded-lg" /><Skeleton className="h-52 rounded-lg" /></div>
      </div>
    )
  }

  if (!backtestRow) {
    return (
      <Card className="border-amber-300 bg-amber-50/60">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-amber-900">Stored backtest replay unavailable</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-amber-900">
          <p>
            The API did not return a successful stored replay for {candidate.symbol}/{candidate.horizon}. The detail page expects this evidence to be materialized server-side from the persisted signal engine representatives.
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-2 md:grid-cols-4">
        <EvidenceMetric label="Return" value={fmtPct(metrics?.total_return, 1)} sub={`${backtestRow.window_start ?? "--"} to ${backtestRow.window_end ?? "--"}`} tone={icTone(metrics?.total_return)} />
        <EvidenceMetric label="Sharpe" value={fmtSigned(metrics?.sharpe, 2)} sub={`${metrics?.n_trades ?? "--"} trades`} tone={icTone(metrics?.sharpe)} />
        <EvidenceMetric label="Max DD" value={fmtPct(metrics?.max_drawdown, 1)} sub={`Win ${fmtPct(metrics?.win_rate, 0)}`} tone="negative" />
        <EvidenceMetric label="MC positive" value={fmtPct(backtestRow.mc.stats?.prob_positive_terminal, 0)} sub={`${backtestRow.mc.n_paths} paths`} tone="blue" />
      </div>
      <div className="rounded-lg border border-line bg-card p-2">
        {priceFigure ? <PlotlyChart figure={priceFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No price chart available.</div>}
      </div>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Trades ledger</CardTitle></CardHeader>
        <CardContent><SignalTradeLedgerTable rows={ledgerRows} /></CardContent>
      </Card>
      <div className="grid gap-3 xl:grid-cols-3">
        <div className="rounded-lg border border-line bg-card p-2">{equityFigure ? <PlotlyChart figure={equityFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No equity curve available.</div>}</div>
        <div className="rounded-lg border border-line bg-card p-2">{drawdownFigure ? <PlotlyChart figure={drawdownFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No drawdown curve available.</div>}</div>
        <div className="rounded-lg border border-line bg-card p-2">{monthlyFigure ? <PlotlyChart figure={monthlyFigure} /> : <div className="flex h-80 items-center justify-center text-xs text-muted-foreground">No monthly heatmap available.</div>}</div>
      </div>
    </div>
  )
}

function ValidationTab({ candidate, signalReport, signalLoading, macroReport, pairDetail }: { candidate: QuantStrategyCandidate; signalReport?: SignalEvaluationReport; signalLoading: boolean; macroReport?: FactorSignalEval | null; pairDetail?: StatArbPairDetail }) {
  if (signalLoading) return <Skeleton className="h-72 rounded-lg" />
  if (candidate.sourceType === "pair" && pairDetail) {
    return (
      <div className="space-y-4">
        <div className="grid gap-2 md:grid-cols-4">
          <EvidenceMetric label="Z-score" value={fmtSigned(pairDetail.zscore, 2)} sub={`Half-life ${fmt(pairDetail.half_life, 1)}`} tone={Math.abs(pairDetail.zscore ?? 0) >= 2 ? "blue" : "neutral"} />
          <EvidenceMetric label="OOS Sharpe" value={fmtSigned(pairDetail.oos_sharpe, 2)} sub={`Return ${fmtPct(pairDetail.oos_return, 1)}`} tone={icTone(pairDetail.oos_sharpe)} />
          <EvidenceMetric label="ADF / FDR" value={`${fmt(pairDetail.adf_pvalue, 3)} / ${fmt(pairDetail.fdr_qvalue, 3)}`} sub={`Raw p ${fmt(pairDetail.raw_pvalue, 3)}`} tone={(pairDetail.fdr_qvalue ?? 1) <= 0.1 ? "positive" : "neutral"} />
          <EvidenceMetric label="Drawdown" value={fmtPct(pairDetail.max_drawdown, 1)} sub={`Profitable folds ${fmtPct(pairDetail.profitable_fold_ratio, 0)}`} tone="negative" />
        </div>
        <PairChart chart={pairDetail.chart} />
      </div>
    )
  }
  if (candidate.sourceType === "macro" && macroReport) {
    const p = macroReport.portfolio
    return (
      <div className="space-y-4">
        <div className="grid gap-2 md:grid-cols-4">
          <EvidenceMetric label="Factor" value={macroReport.factor_id} sub={macroReport.signal_name} />
          <EvidenceMetric label="IC d1 / d5" value={`${fmtSigned(macroReport.ic_h1, 3)} / ${fmtSigned(macroReport.ic_h5, 3)}`} sub={`${macroReport.n_obs} observations`} tone={icTone(macroReport.ic_h5)} />
          <EvidenceMetric label="Net Sharpe" value={fmtSigned(macroReport.after_cost_sharpe, 2)} sub={`Gross ${fmtSigned(macroReport.sharpe, 2)}`} tone={icTone(macroReport.after_cost_sharpe)} />
          <EvidenceMetric label="Drawdown" value={fmtPct(p.max_drawdown, 1)} sub={`Return ${fmtPct(p.total_return, 1)}`} tone="negative" />
        </div>
        <ICDecayChart report={macroReport} />
        <Card><CardContent className="py-3 text-sm text-muted-foreground">Citation: {macroReport.citation || "Pre-registered macro timing rule"}.</CardContent></Card>
      </div>
    )
  }
  if (!signalReport) {
    return <Card><CardContent className="py-8 text-sm text-muted-foreground">Validation report unavailable for this strategy.</CardContent></Card>
  }
  const p = signalReport.portfolio
  const r = signalReport.robustness
  return (
    <div className="space-y-4">
      <div className="grid gap-2 md:grid-cols-4">
        <EvidenceMetric label="Net Sharpe" value={fmtSigned(p.after_cost_sharpe, 2)} sub={`Gross ${fmtSigned(p.sharpe, 2)}`} tone={icTone(p.after_cost_sharpe)} />
        <EvidenceMetric label="Hit rate" value={fmtPct(signalReport.hit_rate_h1, 1)} sub={`CI ${fmtPct(signalReport.hit_rate_ci[0], 0)} to ${fmtPct(signalReport.hit_rate_ci[1], 0)}`} tone={(signalReport.hit_rate_h1 ?? 0.5) >= 0.5 ? "positive" : "negative"} />
        <EvidenceMetric label="Cond. t-stat" value={fmtSigned(signalReport.conditional_return_tstat, 2)} sub={`${signalReport.n_obs} observations`} tone={icTone(signalReport.conditional_return_tstat)} />
        <EvidenceMetric label="DSR / PSR" value={`${fmtPct(r.dsr, 0)} / ${fmtPct(r.psr, 0)}`} sub={`${r.n_variants} variants`} tone={(r.dsr ?? 0) >= 0.7 ? "positive" : "neutral"} />
      </div>
      <ICDecayChart report={signalReport} />
      <div className="grid gap-2 md:grid-cols-2">
        <EvidenceMetric label="IC bootstrap CI" value={`${fmtSigned(r.ic_bootstrap_ci[0], 3)} to ${fmtSigned(r.ic_bootstrap_ci[1], 3)}`} sub={`IC CV ${fmt(r.ic_cv, 2)}`} />
        <EvidenceMetric label="Sharpe bootstrap CI" value={`${fmtSigned(r.sharpe_bootstrap_ci[0], 2)} to ${fmtSigned(r.sharpe_bootstrap_ci[1], 2)}`} sub={`Sharpe CV ${fmt(r.sharpe_cv, 2)}`} />
      </div>
    </div>
  )
}

function RulesTab({ candidate, evidence, backtestRow }: { candidate: QuantStrategyCandidate; evidence?: SignalEvidence; backtestRow: SignalBacktestResult | null }) {
  const rows = representativeRows(backtestRow, evidence)
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Decision memo</CardTitle></CardHeader>
        <CardContent className="grid gap-2 md:grid-cols-2">
          <EvidenceMetric label="Rule" value={candidate.bias} sub={candidate.label} tone={candidate.bias === "Long" || candidate.bias === "Pair continuation" ? "positive" : candidate.bias === "Short" ? "negative" : "neutral"} />
          <EvidenceMetric label="Multiple testing" value={candidate.fdrPass ? "Passed" : "Not passed"} sub={candidate.sourceType === "macro" ? "Relevance screen" : "Signal screen"} tone={candidate.fdrPass ? "positive" : "neutral"} />
          <EvidenceMetric label="Liquidity" value={fmtAdv(candidate.adv)} sub={candidate.sector ?? "Sector missing"} tone={candidate.adv == null || candidate.adv >= 1_000_000 ? "blue" : "negative"} />
          <EvidenceMetric label="Execution gate" value={candidate.status} sub={candidate.status === "Trade" ? "Eligible" : "Needs validation"} tone={candidate.status === "Trade" ? "positive" : candidate.status === "Reject" ? "negative" : "blue"} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">Indicator and rule contributors</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {rows.length === 0 ? (
            <div className="rounded-md border border-dashed border-line px-3 py-6 text-sm text-muted-foreground">No representative rule payload was returned for this strategy.</div>
          ) : (
            rows.map((row) => (
              <div key={row.id} className="rounded-md border border-line px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-semibold">{row.title}</div>
                    <div className="mt-0.5 truncate text-[10px] text-muted-foreground">{row.meta || "technical rule"}</div>
                  </div>
                  <div className="shrink-0 text-right font-mono tabular-nums">
                    <div>{fmt(row.current, 2)}</div>
                    <div className="text-[10px] text-muted-foreground">{row.label || "latest"}</div>
                  </div>
                </div>
                {paramsText(row.params) ? <div className="mt-1 truncate text-[10px] text-muted-foreground">{paramsText(row.params)}</div> : null}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function PairChart({ chart }: { chart: Record<string, unknown> | undefined }) {
  const zscore = validNumberSeries(chart?.zscore)
  const targetReturn = validNumberSeries(chart?.target_return)
  const values = zscore.length > 0 ? zscore : targetReturn
  const label = zscore.length > 0 ? "Z-score history" : "Target-return history"
  if (values.length < 2) return <div className="rounded-md border border-dashed border-line px-3 py-8 text-center text-xs text-muted-foreground">Pair chart unavailable.</div>
  const x = Array.from({ length: values.length }, (_, index) => index)
  const figure = makeFigure(
    [{ type: "scatter", mode: "lines", name: label, x, y: values, line: { color: "#2563eb", width: 2 }, hovertemplate: "%{x}<br>%{y:.3f}<extra></extra>" }],
    { title: { text: label, font: { size: 13 } }, margin: { l: 48, r: 20, t: 36, b: 42 }, xaxis: { title: "Observation" }, yaxis: { title: label } },
  )
  return <div className="rounded-lg border border-line bg-card p-2"><PlotlyChart figure={figure} /></div>
}

function useSignalBacktest(candidate: QuantStrategyCandidate) {
  const selectedDirection = selectedBacktestDirection(candidate)
  return useSWR<SignalBacktestResponse>(
    candidate.sourceType === "signal" && candidate.symbol !== "--"
      ? ["quant-strategy-backtest", candidate.symbol, candidate.horizon, candidate.rawCategory, selectedDirection]
      : null,
    () =>
      fetchSignalBacktestResults(candidate.symbol, candidate.horizon, {
        variant: "expanded",
        selectedDirection,
        cooldownBars: 0,
      }),
    { revalidateOnFocus: false, shouldRetryOnError: false },
  )
}

export default function QuantStrategyDetailPage() {
  const params = useParams()
  const searchParams = useSearchParams()
  const router = useRouter()
  const [tab, setTab] = useState<DetailTab>("overview")
  const id = decodeURIComponent(String(params.id ?? "quant-strategy"))
  const candidate = useMemo(() => buildCandidate(searchParams, id), [searchParams, id])
  const meta = SLEEVE_META[candidate.sleeve] ?? SLEEVE_META.cross
  const Icon = meta.icon

  const signalReport = useSignalEvaluation(
    candidate.sourceType === "signal" ? candidate.symbol : null,
    candidate.sourceType === "signal" ? candidate.rawCategory : null,
    candidate.sourceType === "signal" ? candidate.horizon : null,
  )
  const signalEvidence = useSWR<SignalEvidence>(
    candidate.sourceType === "signal" && candidate.symbol !== "--" ? ["quant-strategy-evidence", candidate.symbol, candidate.horizon] : null,
    () => fetchSignalEvidence({ symbol: candidate.symbol, horizon: candidate.horizon, source: "wfo", costBps: 33, proofLimit: "100" }),
    { revalidateOnFocus: false },
  )
  const backtest = useSignalBacktest(candidate)
  const backtestRow = selectSignalBacktestResult(backtest.data, candidate)

  const forwardHorizon = candidate.horizon === "short" ? 5 : candidate.horizon === "long" ? 63 : 21
  const factorRelevance = useFactorRelevance(candidate.sourceType === "macro" ? candidate.symbol : null, {
    returnMethod: "close_to_close",
    lookbackDays: 252,
    forwardHorizon,
  })
  const factorEval = useFactorSignalEval(candidate.sourceType === "macro" ? candidate.symbol : null, {
    returnMethod: "close_to_close",
    lookbackDays: 252,
  })
  const macroReport = useMemo(() => {
    const rows = factorEval.data ?? []
    return rows.find((row) => row.factor_id.toUpperCase() === String(candidate.factorId ?? "").toUpperCase()) ?? rows[0] ?? null
  }, [candidate.factorId, factorEval.data])
  const pairDetail = useStatArbPairDetail(candidate.sourceType === "pair" ? candidate.pairId : null)
  const detailBacktestLoading = candidate.sourceType === "macro" ? factorEval.isLoading : backtest.isLoading

  const tabs: Array<{ key: DetailTab; label: string }> = [
    { key: "overview", label: "Overview" },
    { key: "backtest", label: "Backtest" },
    { key: "validation", label: "Validation" },
    { key: "rules", label: "Rules" },
  ]

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-6xl space-y-5 p-5">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => router.back()} className="gap-1">
            <ArrowLeft className="h-3.5 w-3.5" />
            Back
          </Button>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("grid h-8 w-8 place-items-center rounded-md border", meta.tone)}>
                <Icon className="h-4 w-4" />
              </span>
              <h1 className="truncate text-lg font-bold">
                {meta.label} - <span className="font-mono">{candidate.symbol}</span>
              </h1>
              <Badge variant="outline" className="text-xs">{horizonLabel(candidate.horizon)}</Badge>
              <Badge variant="outline" className={cn("text-xs", statusClass(candidate.status))}>{candidate.status}</Badge>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>{candidate.label}</span>
              <span>/</span>
              <span>{candidate.category}</span>
              <span>/</span>
              <span className={cn("font-semibold", biasClass(candidate.bias))}>{candidate.bias}</span>
            </div>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-5">
          <MetricTile label="Edge" value={fmt(candidate.edge, 0)} sub="rank score" tone="blue" />
          <MetricTile label="IC" value={fmtSigned(candidate.ic, 3)} sub={candidate.category} tone={icTone(candidate.ic)} />
          <MetricTile label="Sharpe" value={fmtSigned(candidate.sharpe, 2)} sub="screen backtest" tone={icTone(candidate.sharpe)} />
          <MetricTile label="Sample" value={candidate.nObs == null ? "--" : String(candidate.nObs)} sub={candidate.fdrPass ? "FDR pass" : "FDR not passed"} />
          <MetricTile label="Liquidity" value={fmtAdv(candidate.adv)} sub={candidate.sector ?? "sector missing"} tone="blue" />
        </div>

        <Tabs value={tab} onValueChange={(value) => setTab(value as DetailTab)}>
          <TabsList className="h-auto flex-wrap justify-start">
            {tabs.map((item) => <TabsTrigger key={item.key} value={item.key}>{item.label}</TabsTrigger>)}
          </TabsList>
          <TabsContent value="overview" className="mt-4">
            <OverviewTab
              candidate={candidate}
              signalReport={signalReport.data}
              macroReport={macroReport}
              pairDetail={pairDetail.data}
              backtestRow={backtestRow}
              backtestLoading={detailBacktestLoading}
            />
          </TabsContent>
          <TabsContent value="backtest" className="mt-4">
            <BacktestTab candidate={candidate} backtest={backtest} backtestRow={backtestRow} macroReport={macroReport} macroLoading={factorEval.isLoading} />
          </TabsContent>
          <TabsContent value="validation" className="mt-4">
            <ValidationTab
              candidate={candidate}
              signalReport={signalReport.data}
              signalLoading={signalReport.isLoading || factorEval.isLoading || factorRelevance.isLoading || pairDetail.isLoading}
              macroReport={macroReport}
              pairDetail={pairDetail.data}
            />
          </TabsContent>
          <TabsContent value="rules" className="mt-4">
            <RulesTab candidate={candidate} evidence={signalEvidence.data} backtestRow={backtestRow} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
