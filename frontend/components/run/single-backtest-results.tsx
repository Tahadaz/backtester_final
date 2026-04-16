"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useArtifacts } from "@/hooks/use-api"
import {
  fetchArtifactJson,
  fetchArtifactText,
  materializeStrategyDetails,
  type Artifact,
  type LeaderboardRow,
  type MetricRow,
  type PlotlyFigure,
} from "@/lib/api"
import { parseCsvRecords } from "@/lib/csv"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { SignalBadge } from "@/components/signal-badge"
import {
  formatCurrency,
  formatDateTime,
  formatNumber,
  formatPercent,
  signalLabel,
} from "@/lib/format"

type PlotKey =
  | "price_indicators_trades"
  | "drawdown"
  | "cumreturn_vs_benchmark"
  | "monthly_heatmap"
  | "yearly_return_barplot"

type PlotSpec = {
  key: PlotKey
  label: string
}

type TradePerformanceRow = {
  metric: string
  value: number | null
}

type TradesLedgerRow = {
  timestamp: string
  entry_time: string
  exit_time: string
  symbol: string
  side: string
  prix_execution_open_jour: number | null
  entry_price: number | null
  exit_price: number | null
  quantite: number | null
  cmp: number | null
  pnl_realise: number | null
  pnl_latent: number | null
  close_du_jour: number | null
  available_quantity: number | null
  position_value_cost: number | null
  notional: number | null
  cost: number | null
  requested_sell_qty: number | null
  executed_sell_qty: number | null
  sell_clamp_reason: string
}

type SeriesPoint = {
  ts: number
  value: number
}

type SignalExplanationCheck = {
  label: string
  passed: boolean
  detail: string
}

type SignalExplanation = {
  signalValue: number
  asOf: string | null
  summary: string
  explanation: string
  checks: SignalExplanationCheck[]
}

type DecisionObjective = "pnl" | "cagr" | "sharpe"

type DecisionFoldMeta = {
  key: string
  label: string
  index: number
  start: string | null
  end: string | null
}

type DecisionVariantAggregate = {
  key: string
  label: string
  params: Record<string, unknown>
  foldValues: Map<string, number>
  mean: number | null
  std: number | null
  cv: number | null
}

type DecisionNeighborRow = {
  label: string
  paramsText: string
  metric: number | null
  deltaPct: number | null
}

const DECISION_CV_MAX = 1.0
const DECISION_DROP_MAX = 0.35
const DECISION_SLOPE_LOOKBACK = 20
const DECISION_VOL_WINDOW = 20
const DECISION_CROSS_FRESH_DAYS = 10
const DECISION_EPS = 1e-9

const PLOT_SPECS: PlotSpec[] = [
  { key: "price_indicators_trades", label: "Price + Indicators + Trades" },
  { key: "drawdown", label: "Drawdown" },
  { key: "cumreturn_vs_benchmark", label: "CumReturn vs Benchmark" },
  { key: "monthly_heatmap", label: "Monthly Heatmap" },
  { key: "yearly_return_barplot", label: "Yearly Return Barplot" },
]

const TRADE_PERF_ORDER = [
  "Trades",
  "Win Rate",
  "Avg Net PnL",
  "Total Net PnL",
  "Avg Return %",
  "Profit Factor",
  "Avg Hold Days",
]

const STRATEGY_PARAM_EXCLUDE_KEYS = new Set([
  "kind",
  "allow_short",
  "buy_pct_cash",
  "sell_pct_shares",
  "initial_cash",
  "cooldown_bars",
  "min_return_before_sell",
])

type ParamDisplayRow = {
  label: string
  value: string
}

type PortfolioControlTile = {
  label: string
  value: string
}

type GateConfigDisplay = {
  enabled: boolean
  rows: ParamDisplayRow[]
}

function splitArtifactName(name: string): { strategy: string; base: string } {
  const lowered = name.trim().toLowerCase()
  const idx = lowered.indexOf(".")
  if (idx < 0) return { strategy: "", base: lowered }
  return {
    strategy: lowered.slice(0, idx).trim(),
    base: lowered.slice(idx + 1).trim(),
  }
}

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "")
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value !== "string") return null
  const trimmed = value.trim()
  if (!trimmed) return null
  const lowered = trimmed.toLowerCase()
  if (lowered === "inf" || lowered === "+inf" || lowered === "infinity" || lowered === "+infinity") {
    return Number.POSITIVE_INFINITY
  }
  if (lowered === "-inf" || lowered === "-infinity") {
    return Number.NEGATIVE_INFINITY
  }
  const n = Number(trimmed)
  if (Number.isFinite(n)) return n
  if (n === Number.POSITIVE_INFINITY || n === Number.NEGATIVE_INFINITY) return n
  return null
}

function toBoolean(value: unknown, fallback = false): boolean {
  if (typeof value === "boolean") return value
  if (typeof value === "number") return value !== 0
  if (typeof value === "string") {
    const lowered = value.trim().toLowerCase()
    if (["true", "1", "yes", "y", "on", "enabled"].includes(lowered)) return true
    if (["false", "0", "no", "n", "off", "disabled"].includes(lowered)) return false
  }
  return fallback
}

function formatParamLabel(key: string): string {
  return key
    .replace(/^strategy\./i, "")
    .replace(/^portfolio\./i, "")
    .replace(/_/g, " ")
    .replace(/\./g, " ")
    .replace(/\s+/g, " ")
    .trim()
}

function toDisplayValue(value: unknown): string {
  if (value === null || value === undefined) return "--"
  if (typeof value === "boolean") return value ? "true" : "false"
  return String(value)
}

function findArtifactByBase(
  artifacts: Artifact[],
  strategy: string | null,
  baseName: string,
  artifactType?: string
): Artifact | null {
  if (!strategy) return null
  const targetStrategy = strategy.trim().toLowerCase()
  const targetBase = baseName.trim().toLowerCase()
  const row = artifacts.find((item) => {
    if (artifactType && item.artifact_type !== artifactType) return false
    const parsed = splitArtifactName(item.name)
    return parsed.strategy === targetStrategy && parsed.base === targetBase
  })
  return row ?? null
}

function normalizeLedgerRow(record: Record<string, string>): TradesLedgerRow {
  const normalized: Record<string, string> = {}
  for (const [key, val] of Object.entries(record)) {
    normalized[normalizeKey(key)] = val
  }

  const pick = (...keys: string[]) => {
    for (const key of keys) {
      const value = normalized[key]
      if (value !== undefined) return value
    }
    return ""
  }

  return {
    symbol: pick("symbol"),
    timestamp: pick("timestamp"),
    entry_time: pick("entry_time", "entry_ts"),
    exit_time: pick("exit_time", "exit_ts"),
    side: pick("side", "trade_side", "direction", "position_side"),
    prix_execution_open_jour: toNumber(
      pick("prix_execution_open_jour", "prix_d_execution_open_du_jour", "price")
    ),
    entry_price: toNumber(pick("entry_price", "entry_px")),
    exit_price: toNumber(pick("exit_price", "exit_px")),
    quantite: toNumber(pick("quantite", "qty", "quantity")),
    cmp: toNumber(pick("cmp")),
    pnl_realise: toNumber(pick("pnl_realise", "pnl_realized", "pnl_realise_")),
    pnl_latent: toNumber(pick("pnl_latent")),
    close_du_jour: toNumber(pick("close_du_jour", "mark_price", "_mark")),
    available_quantity: toNumber(pick("available_quantity", "available_qty")),
    position_value_cost: toNumber(pick("position_value_cost")),
    notional: toNumber(pick("notional")),
    cost: toNumber(pick("cost", "fees")),
    requested_sell_qty: toNumber(pick("requested_sell_qty")),
    executed_sell_qty: toNumber(pick("executed_sell_qty")),
    sell_clamp_reason: pick("sell_clamp_reason"),
  }
}

function normalizeLedgerRowAny(record: Record<string, unknown>): TradesLedgerRow {
  const asStrings: Record<string, string> = {}
  for (const [key, value] of Object.entries(record)) {
    asStrings[key] = value === null || value === undefined ? "" : String(value)
  }
  return normalizeLedgerRow(asStrings)
}

function normalizeTradePerformanceRows(raw: Array<Record<string, unknown>>): TradePerformanceRow[] {
  const parsed = raw.map((row) => {
    const metricRaw = row.metric ?? row.Metric ?? row.name ?? row.label ?? ""
    const metric = String(metricRaw || "")
    const value = toNumber(row.value ?? row.Value ?? null)
    return { metric, value }
  })
  return TRADE_PERF_ORDER.map((name) => {
    const match = parsed.find((row) => normalizeKey(row.metric) === normalizeKey(name))
    return match ?? { metric: name, value: null }
  })
}

function formatTradePerfValue(metric: string, value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "--"
  if (metric === "Trades") return formatNumber(value, 0)
  if (metric === "Win Rate") return formatPercent(value)
  if (metric === "Avg Return %") return formatPercent(value)
  if (metric === "Avg Hold Days") return formatNumber(value, 2)
  if (metric === "Avg Net PnL" || metric === "Total Net PnL") return formatCurrency(value)
  if (metric === "Profit Factor") return value === Number.POSITIVE_INFINITY ? "inf" : formatNumber(value, 2)
  return formatNumber(value)
}

function toMetricMap(rows: MetricRow[] | undefined): Map<string, number> {
  const map = new Map<string, number>()
  for (const row of rows ?? []) {
    const value =
      typeof row.metric_value === "number"
        ? row.metric_value
        : toNumber(String(row.metric_value))
    if (value === null) continue
    map.set(normalizeKey(row.metric_name), value)
  }
  return map
}

function getMetric(metricMap: Map<string, number>, keys: string[]): number | null {
  for (const key of keys) {
    const val = metricMap.get(normalizeKey(key))
    if (val !== undefined) return val
  }
  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function flattenParams(
  value: Record<string, unknown>,
  prefix = "",
  out: Record<string, unknown> = {}
): Record<string, unknown> {
  for (const [key, raw] of Object.entries(value)) {
    const nextKey = prefix ? `${prefix}.${key}` : key
    if (isRecord(raw)) {
      flattenParams(raw, nextKey, out)
      continue
    }
    out[nextKey] = raw
  }
  return out
}

function normalizeStrategyKind(value: string | null | undefined): string {
  return String(value ?? "").trim().toLowerCase()
}

function getParamNumber(params: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = toNumber(params[key])
    if (value !== null) return value
  }
  return null
}

function getParamText(params: Record<string, unknown>, keys: string[], fallback = "--"): string {
  for (const key of keys) {
    const value = params[key]
    if (value === null || value === undefined) continue
    const text = String(value).trim()
    if (text) return text
  }
  return fallback
}

function toTimestamp(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? null : d.getTime()
  }
  if (typeof value === "string") {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? null : d.getTime()
  }
  if (value instanceof Date) {
    const ts = value.getTime()
    return Number.isNaN(ts) ? null : ts
  }
  return null
}

function traceName(trace: Record<string, unknown>): string {
  const name = trace.name
  return typeof name === "string" ? name : ""
}

function traceType(trace: Record<string, unknown>): string {
  const raw = trace.type
  return typeof raw === "string" ? raw.trim().toLowerCase() : ""
}

function decodeBase64Bytes(input: string): Uint8Array | null {
  if (typeof atob !== "function") return null
  try {
    const raw = atob(input)
    const out = new Uint8Array(raw.length)
    for (let i = 0; i < raw.length; i += 1) {
      out[i] = raw.charCodeAt(i)
    }
    return out
  } catch {
    return null
  }
}

function decodePlotlyTypedArray(value: unknown): unknown[] | null {
  if (!isRecord(value)) return null
  const dtypeRaw = value.dtype
  const bdataRaw = value.bdata
  if (typeof dtypeRaw !== "string" || typeof bdataRaw !== "string") return null

  // Plotly may serialize numpy arrays as { dtype, bdata } payloads.
  const bytes = decodeBase64Bytes(bdataRaw)
  if (!bytes) return null

  const dtype = dtypeRaw.trim().toLowerCase()
  const littleEndian = !dtype.startsWith(">")
  const base = dtype.replace(/^[<>|=]/, "")
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)

  const readNumberArray = (step: number, read: (offset: number) => number): number[] => {
    const out: number[] = []
    for (let offset = 0; offset + step <= view.byteLength; offset += step) {
      out.push(read(offset))
    }
    return out
  }

  switch (base) {
    case "f8":
      return readNumberArray(8, (offset) => view.getFloat64(offset, littleEndian))
    case "f4":
      return readNumberArray(4, (offset) => view.getFloat32(offset, littleEndian))
    case "i8":
      return readNumberArray(8, (offset) => Number(view.getBigInt64(offset, littleEndian)))
    case "u8":
      return readNumberArray(8, (offset) => Number(view.getBigUint64(offset, littleEndian)))
    case "i4":
      return readNumberArray(4, (offset) => view.getInt32(offset, littleEndian))
    case "u4":
      return readNumberArray(4, (offset) => view.getUint32(offset, littleEndian))
    case "i2":
      return readNumberArray(2, (offset) => view.getInt16(offset, littleEndian))
    case "u2":
      return readNumberArray(2, (offset) => view.getUint16(offset, littleEndian))
    case "i1":
      return readNumberArray(1, (offset) => view.getInt8(offset))
    case "u1":
      return readNumberArray(1, (offset) => view.getUint8(offset))
    case "b1":
      return readNumberArray(1, (offset) => (view.getUint8(offset) ? 1 : 0))
    default:
      return null
  }
}

function toArrayData(value: unknown): unknown[] {
  if (Array.isArray(value)) return value
  return decodePlotlyTypedArray(value) ?? []
}

function extractSeriesFromTrace(trace: Record<string, unknown>, valueKey: string): SeriesPoint[] {
  const x = toArrayData(trace.x)
  const y = toArrayData(trace[valueKey])
  const n = Math.min(x.length, y.length)
  if (n <= 0) return []

  const out: SeriesPoint[] = []
  for (let i = 0; i < n; i += 1) {
    const ts = toTimestamp(x[i])
    const value = toNumber(y[i])
    if (ts === null || value === null || !Number.isFinite(value)) continue
    out.push({ ts, value })
  }
  out.sort((a, b) => a.ts - b.ts)
  return out
}

function toCloseLineDecisionFigure(
  figure: PlotlyFigure | null | undefined
): PlotlyFigure | null {
  if (!figure || !Array.isArray(figure.data)) return null

  const nextData: Record<string, unknown>[] = []
  for (const raw of figure.data) {
    if (!isRecord(raw)) continue

    if (traceType(raw) !== "candlestick") {
      nextData.push({ ...raw })
      continue
    }

    const x = toArrayData(raw.x)
    const close = toArrayData(raw.close)
    const n = Math.min(x.length, close.length)
    if (n <= 0) continue

    const xOut: unknown[] = []
    const yOut: number[] = []
    for (let i = 0; i < n; i += 1) {
      const ts = toTimestamp(x[i])
      const y = toNumber(close[i])
      if (ts === null || y === null || !Number.isFinite(y)) continue
      xOut.push(x[i])
      yOut.push(y)
    }
    if (!xOut.length) continue

    const lineTrace: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(raw)) {
      if (
        key === "open" ||
        key === "high" ||
        key === "low" ||
        key === "close" ||
        key === "increasing" ||
        key === "decreasing" ||
        key === "whiskerwidth" ||
        key === "x" ||
        key === "type" ||
        key === "mode"
      ) {
        continue
      }
      lineTrace[key] = value
    }
    lineTrace.type = "scatter"
    lineTrace.mode = "lines"
    lineTrace.x = xOut
    lineTrace.y = yOut
    lineTrace.name = traceName(raw) || "Close"
    const baseLine = isRecord(raw.line) ? { ...raw.line } : {}
    if (toNumber(baseLine.width) === null) baseLine.width = 1.8
    lineTrace.line = baseLine
    lineTrace.hovertemplate = "%{x}<br>Close=%{y:.2f}<extra></extra>"
    nextData.push(lineTrace)
  }

  return {
    ...figure,
    data: nextData,
    layout: isRecord(figure.layout) ? { ...figure.layout } : {},
  }
}

function normalizeTradeSide(value: unknown): "BUY" | "SELL" | null {
  const raw = String(value ?? "").trim().toUpperCase()
  if (!raw) return null
  if (raw === "BUY" || raw === "B" || raw === "LONG" || raw.includes("BUY")) return "BUY"
  if (raw === "SELL" || raw === "S" || raw === "SHORT" || raw.includes("SELL")) return "SELL"
  if (raw === "ACHAT") return "BUY"
  if (raw === "VENTE") return "SELL"
  return null
}

function hasNamedTrace(
  figure: PlotlyFigure | null | undefined,
  target: "BUY" | "SELL"
): boolean {
  const traces = Array.isArray(figure?.data) ? figure.data : []
  return traces.some((raw) => {
    if (!isRecord(raw)) return false
    return traceName(raw).trim().toUpperCase() === target
  })
}

function withLedgerTradeMarkers(
  figure: PlotlyFigure | null | undefined,
  ledgerRows: TradesLedgerRow[]
): PlotlyFigure | null {
  if (!figure) return null
  if (!Array.isArray(figure.data) || !figure.data.length) return figure

  const hasBuy = hasNamedTrace(figure, "BUY")
  const hasSell = hasNamedTrace(figure, "SELL")
  let styledExistingMarkers = false
  const nextData = figure.data.map((raw) => {
    if (!isRecord(raw)) return raw
    const target = traceName(raw).trim().toUpperCase()
    if (target !== "BUY" && target !== "SELL") return raw

    styledExistingMarkers = true
    const side = target as "BUY" | "SELL"
    const xValues = toArrayData(raw.x)
    const marker = isRecord(raw.marker) ? { ...raw.marker } : {}

    return {
      ...raw,
      mode: "markers+text",
      marker: {
        ...marker,
        size: 14,
        symbol: side === "BUY" ? "triangle-up" : "triangle-down",
        color: side === "BUY" ? "#00B050" : "#C00000",
        line: {
          color: side === "BUY" ? "#004D1A" : "#4D0000",
          width: 1.5,
        },
      },
      text: xValues.map(() => side),
      textposition: side === "BUY" ? "top center" : "bottom center",
      textfont: {
        size: 12,
        color: side === "BUY" ? "#004D1A" : "#4D0000",
      },
    }
  })
  if (!ledgerRows.length) {
    return styledExistingMarkers ? { ...figure, data: nextData } : figure
  }

  const buyX: string[] = []
  const buyY: number[] = []
  const sellX: string[] = []
  const sellY: number[] = []
  const pushMarker = (side: "BUY" | "SELL", ts: string, y: number | null) => {
    if (!ts || toTimestamp(ts) === null) return
    if (y === null || !Number.isFinite(y)) return
    if (side === "BUY") {
      buyX.push(ts)
      buyY.push(y)
      return
    }
    sellX.push(ts)
    sellY.push(y)
  }

  for (const row of ledgerRows) {
    const side = normalizeTradeSide(row.side)
    const defaultY =
      row.prix_execution_open_jour ??
      row.close_du_jour ??
      row.entry_price ??
      row.exit_price ??
      row.cmp

    if (row.timestamp && toTimestamp(row.timestamp) !== null && side) {
      pushMarker(side, row.timestamp, defaultY)
      continue
    }

    if (!side) continue

    const entrySide: "BUY" | "SELL" = side === "BUY" ? "BUY" : "SELL"
    const exitSide: "BUY" | "SELL" = side === "BUY" ? "SELL" : "BUY"
    const entryY = row.entry_price ?? defaultY
    const exitY = row.exit_price ?? row.close_du_jour ?? row.cmp ?? defaultY

    if (row.entry_time) {
      pushMarker(entrySide, row.entry_time, entryY)
    }
    if (row.exit_time) {
      pushMarker(exitSide, row.exit_time, exitY)
    }
  }

  if (!hasBuy && buyX.length) {
    nextData.push({
      type: "scatter",
      mode: "markers+text",
      x: buyX,
      y: buyY,
      marker: {
        size: 14,
        symbol: "triangle-up",
        color: "#00B050",
        line: { color: "#004D1A", width: 1.5 },
      },
      text: buyX.map(() => "BUY"),
      textposition: "top center",
      textfont: { size: 12, color: "#004D1A" },
      name: "BUY",
    })
  }
  if (!hasSell && sellX.length) {
    nextData.push({
      type: "scatter",
      mode: "markers+text",
      x: sellX,
      y: sellY,
      marker: {
        size: 14,
        symbol: "triangle-down",
        color: "#C00000",
        line: { color: "#4D0000", width: 1.5 },
      },
      text: sellX.map(() => "SELL"),
      textposition: "bottom center",
      textfont: { size: 12, color: "#4D0000" },
      name: "SELL",
    })
  }

  if (!styledExistingMarkers && nextData.length === figure.data.length) return figure
  return { ...figure, data: nextData }
}

function findSeriesByPredicate(
  figure: PlotlyFigure | null | undefined,
  predicate: (trace: Record<string, unknown>, name: string) => boolean,
  valueKey = "y"
): SeriesPoint[] {
  const traces = Array.isArray(figure?.data) ? figure?.data : []
  for (const raw of traces) {
    if (!isRecord(raw)) continue
    const name = traceName(raw)
    if (!predicate(raw, name)) continue
    const series = extractSeriesFromTrace(raw, valueKey)
    if (series.length > 0) return series
  }
  return []
}

function findCloseSeries(figure: PlotlyFigure | null | undefined): SeriesPoint[] {
  const candle = findSeriesByPredicate(
    figure,
    (trace) => traceType(trace) === "candlestick",
    "close"
  )
  if (candle.length > 0) return candle

  return findSeriesByPredicate(
    figure,
    (_, name) => {
      const lowered = name.trim().toLowerCase()
      return lowered === "close" || lowered === "price"
    },
    "y"
  )
}

function latestValue(series: SeriesPoint[]): { current: number | null; previous: number | null; ts: number | null } {
  if (!series.length) return { current: null, previous: null, ts: null }
  const last = series[series.length - 1]
  const prev = series.length > 1 ? series[series.length - 2] : null
  return {
    current: last.value,
    previous: prev ? prev.value : null,
    ts: last.ts,
  }
}

function toIsoTimestamp(ts: number | null): string | null {
  if (ts === null) return null
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return null
  return d.toISOString()
}

function sliceFigureToLastDays(
  figure: PlotlyFigure | null | undefined,
  days = 7
): PlotlyFigure | null {
  if (!figure || !Array.isArray(figure.data)) return null
  let maxTs: number | null = null

  for (const raw of figure.data) {
    if (!isRecord(raw)) continue
    const x = toArrayData(raw.x)
    if (!x.length) continue
    for (const xv of x) {
      const ts = toTimestamp(xv)
      if (ts === null) continue
      if (maxTs === null || ts > maxTs) maxTs = ts
    }
  }

  if (maxTs === null) return figure

  const cutoff = maxTs - days * 24 * 60 * 60 * 1000
  const nextData: Record<string, unknown>[] = []

  for (const raw of figure.data) {
    if (!isRecord(raw)) continue
    const x = toArrayData(raw.x)
    if (!x.length) {
      nextData.push({ ...raw })
      continue
    }

    const mask = x.map((v) => {
      const ts = toTimestamp(v)
      return ts !== null && ts >= cutoff
    })
    if (!mask.some(Boolean)) continue

    const nextTrace: Record<string, unknown> = { ...raw }
    for (const [key, value] of Object.entries(raw)) {
      const values = toArrayData(value)
      if (!values.length || values.length !== mask.length) continue
      nextTrace[key] = values.filter((_, idx) => mask[idx])
    }
    nextData.push(nextTrace)
  }

  return {
    ...figure,
    data: nextData,
  }
}

function buildSignalExplanation(
  strategy: string | null,
  params: Record<string, unknown>,
  figure: PlotlyFigure | null | undefined
): SignalExplanation {
  const kind = normalizeStrategyKind(strategy)
  const checks: SignalExplanationCheck[] = []
  const close = latestValue(findCloseSeries(figure))
  let asOfTs = close.ts
  const updateAsOf = (ts: number | null) => {
    if (ts === null) return
    if (asOfTs === null || ts > asOfTs) asOfTs = ts
  }
  const fmt = (n: number | null, d = 4) => (n === null ? "--" : formatNumber(n, d))

  if (!figure || !Array.isArray(figure.data) || figure.data.length === 0) {
    return {
      signalValue: 0,
      asOf: null,
      summary: "HOLD signal",
      explanation: "Price/indicator figure is not available, so signal reason cannot be computed.",
      checks: [{ label: "Data availability", passed: false, detail: "Missing decision chart data." }],
    }
  }

  if (kind === "buy_hold") {
    const hasClose = close.current !== null
    checks.push({
      label: "Has valid price bar",
      passed: hasClose,
      detail: hasClose ? `Close=${fmt(close.current, 2)}` : "No close value found.",
    })
    const signal = hasClose ? 1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: hasClose
        ? "Buy & Hold keeps long exposure once valid data exists."
        : "No valid bar is available; signal defaults to HOLD.",
      checks,
    }
  }

  if (kind === "ma_cross") {
    const fast = getParamNumber(params, ["sma_fast_window", "fast_window"]) ?? 15
    const slow = getParamNumber(params, ["sma_slow_window", "slow_window"]) ?? 50
    const fastV = latestValue(
      findSeriesByPredicate(figure, (_, name) => normalizeStrategyKind(name) === `sma_${fast}`)
    )
    const slowV = latestValue(
      findSeriesByPredicate(figure, (_, name) => normalizeStrategyKind(name) === `sma_${slow}`)
    )
    updateAsOf(fastV.ts)
    updateAsOf(slowV.ts)
    const has = fastV.current !== null && slowV.current !== null
    const buy = has && fastV.current! > slowV.current!
    const sell = has && fastV.current! < slowV.current!
    checks.push({
      label: `SMA(${fast}) > SMA(${slow})`,
      passed: buy,
      detail: `${fmt(fastV.current)} vs ${fmt(slowV.current)}`,
    })
    checks.push({
      label: `SMA(${fast}) < SMA(${slow})`,
      passed: sell,
      detail: `${fmt(fastV.current)} vs ${fmt(slowV.current)}`,
    })
    const signal = !has ? 0 : buy ? 1 : sell ? -1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: has
        ? `Fast/slow moving-average comparison determines the signal at the latest bar.`
        : "Missing moving-average values; defaulting to HOLD.",
      checks,
    }
  }

  if (kind === "sma_price" || kind === "price_sma" || kind === "price_above_sma") {
    const window = getParamNumber(params, ["sma_window", "window"]) ?? 50
    const sma = latestValue(
      findSeriesByPredicate(figure, (_, name) => normalizeStrategyKind(name) === `sma_${window}`)
    )
    updateAsOf(sma.ts)
    const has = close.current !== null && sma.current !== null
    const buy = has && close.current! > sma.current!
    const sell = has && close.current! < sma.current!
    checks.push({
      label: `Close > SMA(${window})`,
      passed: buy,
      detail: `${fmt(close.current, 2)} vs ${fmt(sma.current)}`,
    })
    checks.push({
      label: `Close < SMA(${window})`,
      passed: sell,
      detail: `${fmt(close.current, 2)} vs ${fmt(sma.current)}`,
    })
    const signal = !has ? 0 : buy ? 1 : sell ? -1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: has
        ? "Signal comes from close price position relative to SMA."
        : "Close/SMA values are incomplete; defaulting to HOLD.",
      checks,
    }
  }

  if (kind === "rsi") {
    const window = getParamNumber(params, ["rsi_window", "period"]) ?? 14
    const low = getParamNumber(params, ["rsi_oversold", "low"]) ?? 30
    const high = getParamNumber(params, ["rsi_overbought", "high"]) ?? 70
    const mode = normalizeStrategyKind(getParamText(params, ["mode"], "reversal"))
    const rsi = latestValue(
      findSeriesByPredicate(
        figure,
        (_, name) =>
          name.toLowerCase().includes(`rsi_${window}`) ||
          name.toLowerCase().startsWith("rsi (") ||
          name.toLowerCase().startsWith(`rsi_${window}`)
      )
    )
    updateAsOf(rsi.ts)
    const has = rsi.current !== null
    let buy = false
    let sell = false
    if (has) {
      if (mode === "momentum") {
        buy = rsi.current! > high
        sell = rsi.current! < low
      } else {
        buy = rsi.current! < low
        sell = rsi.current! > high
      }
    }
    checks.push({
      label: `RSI value`,
      passed: has,
      detail: `RSI=${fmt(rsi.current, 2)}, low=${fmt(low, 0)}, high=${fmt(high, 0)}, mode=${mode}`,
    })
    checks.push({
      label: "BUY condition",
      passed: buy,
      detail:
        mode === "momentum"
          ? `RSI > high -> ${fmt(rsi.current, 2)} > ${fmt(high, 0)}`
          : `RSI < low -> ${fmt(rsi.current, 2)} < ${fmt(low, 0)}`,
    })
    checks.push({
      label: "SELL condition",
      passed: sell,
      detail:
        mode === "momentum"
          ? `RSI < low -> ${fmt(rsi.current, 2)} < ${fmt(low, 0)}`
          : `RSI > high -> ${fmt(rsi.current, 2)} > ${fmt(high, 0)}`,
    })
    const signal = !has ? 0 : buy ? 1 : sell ? -1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: has
        ? "RSI threshold logic determines buy/sell/hold."
        : "RSI value is unavailable; defaulting to HOLD.",
      checks,
    }
  }

  if (kind === "macd") {
    const fast = getParamNumber(params, ["macd_fast_window", "fast"]) ?? 12
    const slow = getParamNumber(params, ["macd_slow_window", "slow"]) ?? 26
    const sigW = getParamNumber(params, ["macd_signal_window", "signal"]) ?? 9
    const trigger = normalizeStrategyKind(getParamText(params, ["trigger"], "zero"))
    const base = `macd_${fast}_${slow}_${sigW}`
    const macdLine = latestValue(
      findSeriesByPredicate(
        figure,
        (_, name) => name.toLowerCase().includes(`${base} line`) || name.toLowerCase().includes("__line")
      )
    )
    const macdSignal = latestValue(
      findSeriesByPredicate(
        figure,
        (_, name) => name.toLowerCase().includes(`${base} signal`) || name.toLowerCase().includes("__signal")
      )
    )
    updateAsOf(macdLine.ts)
    updateAsOf(macdSignal.ts)
    const hasCurrent = macdLine.current !== null && macdSignal.current !== null
    const hasPrev = macdLine.previous !== null && macdSignal.previous !== null
    let buy = false
    let sell = false

    if (hasCurrent && trigger === "cross" && hasPrev) {
      buy = macdLine.previous! <= macdSignal.previous! && macdLine.current! > macdSignal.current!
      sell = macdLine.previous! >= macdSignal.previous! && macdLine.current! < macdSignal.current!
    } else if (hasCurrent && trigger !== "cross" && macdLine.previous !== null) {
      buy = macdLine.previous <= 0 && macdLine.current! > 0
      sell = macdLine.previous >= 0 && macdLine.current! < 0
    }

    checks.push({
      label: "MACD current values",
      passed: hasCurrent,
      detail: `line=${fmt(macdLine.current)} signal=${fmt(macdSignal.current)} trigger=${trigger}`,
    })
    checks.push({
      label: "BUY crossover",
      passed: buy,
      detail:
        trigger === "cross"
          ? `prev(line<=sig) and now(line>sig): ${fmt(macdLine.previous)}<=${fmt(macdSignal.previous)} -> ${fmt(macdLine.current)}>${fmt(macdSignal.current)}`
          : `prev(line<=0) and now(line>0): ${fmt(macdLine.previous)} -> ${fmt(macdLine.current)}`,
    })
    checks.push({
      label: "SELL crossover",
      passed: sell,
      detail:
        trigger === "cross"
          ? `prev(line>=sig) and now(line<sig): ${fmt(macdLine.previous)}>=${fmt(macdSignal.previous)} -> ${fmt(macdLine.current)}<${fmt(macdSignal.current)}`
          : `prev(line>=0) and now(line<0): ${fmt(macdLine.previous)} -> ${fmt(macdLine.current)}`,
    })

    const signal = !hasCurrent || !hasPrev ? 0 : buy ? 1 : sell ? -1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation:
        hasCurrent && hasPrev
          ? "MACD trigger logic is evaluated using current and previous bars."
          : "MACD values are insufficient for crossover detection; defaulting to HOLD.",
      checks,
    }
  }

  if (kind === "bollinger") {
    const upper = latestValue(
      findSeriesByPredicate(figure, (_, name) => name.toLowerCase().includes("bb upper"))
    )
    const lower = latestValue(
      findSeriesByPredicate(figure, (_, name) => name.toLowerCase().includes("bb lower"))
    )
    updateAsOf(upper.ts)
    updateAsOf(lower.ts)
    const has = close.current !== null && upper.current !== null && lower.current !== null
    const buy = has && close.current! < lower.current!
    const sell = has && close.current! > upper.current!
    checks.push({
      label: "Close below lower band",
      passed: buy,
      detail: `${fmt(close.current, 2)} < ${fmt(lower.current, 2)}`,
    })
    checks.push({
      label: "Close above upper band",
      passed: sell,
      detail: `${fmt(close.current, 2)} > ${fmt(upper.current, 2)}`,
    })
    const signal = !has ? 0 : buy ? 1 : sell ? -1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: has
        ? "Bollinger signal is based on close relative to upper/lower bands."
        : "Band values are missing; defaulting to HOLD.",
      checks,
    }
  }

  if (kind === "obv") {
    const span = getParamNumber(params, ["obv_span", "span"]) ?? 20
    const obv = latestValue(findSeriesByPredicate(figure, (_, name) => name.trim().toLowerCase() === "obv"))
    const ema = latestValue(
      findSeriesByPredicate(figure, (_, name) => name.toLowerCase().includes(`obv_ema_${span}`))
    )
    const emaFallback =
      ema.current === null
        ? latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase().startsWith("obv_ema_")))
        : ema
    updateAsOf(obv.ts)
    updateAsOf(emaFallback.ts)
    const has = obv.current !== null && emaFallback.current !== null
    const buy = has && obv.current! > emaFallback.current!
    const sell = has && obv.current! < emaFallback.current!
    checks.push({
      label: "OBV above EMA",
      passed: buy,
      detail: `${fmt(obv.current, 2)} > ${fmt(emaFallback.current, 2)}`,
    })
    checks.push({
      label: "OBV below EMA",
      passed: sell,
      detail: `${fmt(obv.current, 2)} < ${fmt(emaFallback.current, 2)}`,
    })
    const signal = !has ? 0 : buy ? 1 : sell ? -1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: has
        ? "OBV trend versus EMA determines signal direction."
        : "OBV/EMA values are missing; defaulting to HOLD.",
      checks,
    }
  }

  if (kind === "stoch_vwap" || kind === "stoch" || kind === "stochastic") {
    const kVal = latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase().includes("stoch %k")))
    const dVal = latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase().includes("stoch %d")))
    const vwap = latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase().startsWith("vwap_")))
    updateAsOf(kVal.ts)
    updateAsOf(dVal.ts)
    updateAsOf(vwap.ts)

    const hasCurrent =
      close.current !== null &&
      close.previous !== null &&
      kVal.current !== null &&
      kVal.previous !== null &&
      dVal.current !== null &&
      dVal.previous !== null &&
      vwap.current !== null &&
      vwap.previous !== null

    let buy = false
    let sell = false
    if (hasCurrent) {
      const kxUp = kVal.previous! <= dVal.previous! && kVal.current! > dVal.current!
      const kxDn = kVal.previous! >= dVal.previous! && kVal.current! < dVal.current!
      const cxUp = close.previous! <= vwap.previous! && close.current! > vwap.current!
      const cxDn = close.previous! >= vwap.previous! && close.current! < vwap.current!

      const buy1 = kxUp && kVal.current! < 20 && dVal.current! < 20 && close.current! > vwap.current!
      const buy2 =
        kVal.current! > 50 &&
        kVal.current! < 80 &&
        dVal.current! > 50 &&
        dVal.current! < 80 &&
        cxUp
      const buy3 = kxUp && kVal.current! < 80 && dVal.current! < 80 && close.current! > vwap.current!

      const sell1 = kxDn && kVal.current! > 80 && dVal.current! > 80 && close.current! < vwap.current!
      const sell2 =
        kVal.current! > 20 &&
        kVal.current! < 50 &&
        dVal.current! > 20 &&
        dVal.current! < 50 &&
        cxDn
      const sell3 = kxDn && kVal.current! > 20 && dVal.current! > 20 && close.current! < vwap.current!

      buy = buy1 || buy2 || buy3
      sell = sell1 || sell2 || sell3
      checks.push({ label: "BUY condition group", passed: buy, detail: `buy1=${buy1} buy2=${buy2} buy3=${buy3}` })
      checks.push({
        label: "SELL condition group (sell precedence)",
        passed: sell,
        detail: `sell1=${sell1} sell2=${sell2} sell3=${sell3}`,
      })
    } else {
      checks.push({
        label: "Data completeness",
        passed: false,
        detail: "Need current+previous K, D, Close, and VWAP values.",
      })
    }

    const signal = !hasCurrent ? 0 : sell ? -1 : buy ? 1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: hasCurrent
        ? "Stoch/VWAP multi-condition logic was evaluated on the latest bar (sell has precedence)."
        : "Inputs are incomplete for Stoch/VWAP conditions; defaulting to HOLD.",
      checks,
    }
  }

  if (kind === "ichimoku") {
    const tenkan = latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase() === "tenkan"))
    const kijun = latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase() === "kijun"))
    const spanA = latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase() === "span a"))
    const spanB = latestValue(findSeriesByPredicate(figure, (_, name) => name.toLowerCase() === "span b"))
    updateAsOf(tenkan.ts)
    updateAsOf(kijun.ts)
    updateAsOf(spanA.ts)
    updateAsOf(spanB.ts)
    const has =
      close.current !== null &&
      tenkan.current !== null &&
      kijun.current !== null &&
      spanA.current !== null &&
      spanB.current !== null
    const cloudTop = has ? Math.max(spanA.current!, spanB.current!) : null
    const cloudBottom = has ? Math.min(spanA.current!, spanB.current!) : null
    const buy = has && close.current! > cloudTop! && tenkan.current! > kijun.current!
    const sell = has && close.current! < cloudBottom! && tenkan.current! < kijun.current!
    checks.push({
      label: "BUY: close above cloud and tenkan>kijun",
      passed: buy,
      detail: `close=${fmt(close.current, 2)} cloudTop=${fmt(cloudTop, 2)} tenkan=${fmt(tenkan.current, 2)} kijun=${fmt(kijun.current, 2)}`,
    })
    checks.push({
      label: "SELL: close below cloud and tenkan<kijun",
      passed: sell,
      detail: `close=${fmt(close.current, 2)} cloudBottom=${fmt(cloudBottom, 2)} tenkan=${fmt(tenkan.current, 2)} kijun=${fmt(kijun.current, 2)}`,
    })
    const signal = !has ? 0 : buy ? 1 : sell ? -1 : 0
    return {
      signalValue: signal,
      asOf: toIsoTimestamp(asOfTs),
      summary: `${signalLabel(signal)} signal`,
      explanation: has
        ? "Ichimoku cloud and Tenkan/Kijun confirmation determine the signal."
        : "Ichimoku inputs are missing; defaulting to HOLD.",
      checks,
    }
  }

  return {
    signalValue: 0,
    asOf: toIsoTimestamp(asOfTs),
    summary: "HOLD signal",
    explanation: `No signal evaluator implemented for strategy '${strategy ?? "--"}'.`,
    checks: [],
  }
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

function stdPop(values: number[]): number | null {
  if (!values.length) return null
  const mean = values.reduce((acc, v) => acc + v, 0) / values.length
  const variance =
    values.reduce((acc, v) => acc + (v - mean) ** 2, 0) / values.length
  return Math.sqrt(variance)
}

function normalizeObjective(
  raw: unknown,
  fallback: DecisionObjective = "pnl"
): DecisionObjective {
  const token = String(raw ?? "").trim().toLowerCase()
  if (token === "pnl") return "pnl"
  if (token === "cagr") return "cagr"
  if (token === "sharpe") return "sharpe"
  return fallback
}

function objectiveFromRunSpec(runSpec: Record<string, unknown> | undefined): DecisionObjective {
  if (!isRecord(runSpec)) return "pnl"
  const optimization = isRecord(runSpec.optimization) ? runSpec.optimization : {}
  const walkForward = isRecord(optimization.walk_forward) ? optimization.walk_forward : {}
  return normalizeObjective(walkForward.objective, "pnl")
}

function parseUnknownObject(raw: unknown): Record<string, unknown> {
  if (!raw) return {}
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown
      return isRecord(parsed) ? parsed : {}
    } catch {
      return {}
    }
  }
  return isRecord(raw) ? raw : {}
}

function normalizeSignalMode(value: unknown): string {
  const token = String(value ?? "").trim().toLowerCase()
  if (token === "cross" || token === "level") return token
  return "level"
}

function extractSmaParams(params: Record<string, unknown>): {
  window: number | null
  signalMode: string
} {
  const window = getParamNumber(params, [
    "sma_window",
    "window",
    "strategy.sma_window",
    "param.strategy.sma_window",
  ])
  const signalMode = normalizeSignalMode(
    getParamText(
      params,
      ["signal_mode", "strategy.signal_mode", "param.strategy.signal_mode"],
      "level"
    )
  )
  return { window, signalMode }
}

function decisionVariantKey(window: number | null, signalMode: string): string {
  return `w:${window ?? "na"}|m:${normalizeSignalMode(signalMode)}`
}

function decisionVariantLabel(window: number | null, signalMode: string): string {
  const wText = window === null ? "SMA ?" : `SMA ${formatNumber(window, 0)}`
  return `${wText} | ${normalizeSignalMode(signalMode)}`
}

function parseBatchMetric(
  row: Record<string, unknown>,
  objective: DecisionObjective
): number | null {
  const keys =
    objective === "pnl"
      ? ["stat.pnl", "pnl", "objective_value"]
      : objective === "cagr"
        ? ["stat.cagr", "cagr", "objective_value"]
        : ["stat.sharpe", "sharpe", "objective_value"]
  for (const key of keys) {
    const value = toNumber(row[key])
    if (value !== null && Number.isFinite(value)) return value
  }
  return null
}

function parseBatchFoldMeta(row: Record<string, unknown>): DecisionFoldMeta {
  const foldIndexRaw = toNumber(row.fold_index)
  const foldIndex =
    foldIndexRaw !== null && Number.isFinite(foldIndexRaw)
      ? Math.max(0, Math.round(foldIndexRaw))
      : 0
  const periodRaw = String(row.period ?? row.label ?? "").trim()
  const label = periodRaw || `Fold ${foldIndex + 1}`
  const start = String(
    row.test_start ?? row.start ?? row.fold_test_start ?? ""
  ).trim()
  const end = String(row.test_end ?? row.end ?? row.fold_test_end ?? "").trim()
  const key = `${foldIndex}|${label}|${start}|${end}`
  return {
    key,
    label,
    index: foldIndex,
    start: start || null,
    end: end || null,
  }
}

function rowHorizonToken(row: Record<string, unknown>): string {
  return String(
    row.horizon ??
      row["simple_wfo.horizon"] ??
      row["walk_forward.horizon"] ??
      ""
  )
    .trim()
    .toLowerCase()
}

function parseBatchDecisionRows(
  rows: Array<Record<string, string>>,
  objective: DecisionObjective,
  selectedHorizon: string | null
): {
  folds: DecisionFoldMeta[]
  variants: Array<{
    key: string
    label: string
    params: Record<string, unknown>
    foldValues: Map<string, number>
  }>
} {
  const horizonToken = String(selectedHorizon ?? "").trim().toLowerCase()
  const foldsByKey = new Map<string, DecisionFoldMeta>()
  const variantsByKey = new Map<
    string,
    {
      key: string
      label: string
      params: Record<string, unknown>
      foldValues: Map<string, { metric: number; trialRank: number }>
    }
  >()

  for (const rowRaw of rows) {
    const row: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(rowRaw)) row[k] = v

    const strategyKind = normalizeStrategyKind(String(row.strategy_kind ?? ""))
    if (strategyKind !== "sma_price") continue

    if (horizonToken) {
      const rowHorizon = rowHorizonToken(row)
      if (rowHorizon && rowHorizon !== horizonToken) continue
    }

    const fold = parseBatchFoldMeta(row)
    foldsByKey.set(fold.key, fold)

    const params: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(row)) {
      if (key.startsWith("param.strategy.")) {
        params[key.slice("param.".length)] = value
      } else if (key.startsWith("strategy.")) {
        params[key] = value
      }
    }
    const sma = extractSmaParams(params)
    const variantKey = decisionVariantKey(sma.window, sma.signalMode)
    const variantLabel = decisionVariantLabel(sma.window, sma.signalMode)
    const metric = parseBatchMetric(row, objective)
    if (metric === null) continue

    const trialRank = Math.max(
      1,
      Math.round(toNumber(row.trial_rank) ?? Number.POSITIVE_INFINITY)
    )
    if (!variantsByKey.has(variantKey)) {
      variantsByKey.set(variantKey, {
        key: variantKey,
        label: variantLabel,
        params,
        foldValues: new Map(),
      })
    }
    const target = variantsByKey.get(variantKey)!
    const prev = target.foldValues.get(fold.key)
    if (!prev || trialRank < prev.trialRank) {
      target.foldValues.set(fold.key, { metric, trialRank })
    }
  }

  const folds = Array.from(foldsByKey.values()).sort((a, b) => a.index - b.index)
  const variants = Array.from(variantsByKey.values()).map((item) => ({
    key: item.key,
    label: item.label,
    params: item.params,
    foldValues: new Map(
      Array.from(item.foldValues.entries()).map(([k, payload]) => [k, payload.metric])
    ),
  }))

  return { folds, variants }
}

function computeVariantAggregates(
  variants: Array<{
    key: string
    label: string
    params: Record<string, unknown>
    foldValues: Map<string, number>
  }>,
  selectedFoldKeys: string[]
): DecisionVariantAggregate[] {
  const out: DecisionVariantAggregate[] = []
  for (const variant of variants) {
    const values = selectedFoldKeys
      .map((foldKey) => variant.foldValues.get(foldKey))
      .filter((value): value is number => value !== undefined && Number.isFinite(value))
    const mean =
      values.length > 0 ? values.reduce((acc, value) => acc + value, 0) / values.length : null
    const std = values.length > 0 ? stdPop(values) : null
    const cv =
      mean !== null && std !== null
        ? std / (Math.abs(mean) + DECISION_EPS)
        : null

    out.push({
      key: variant.key,
      label: variant.label,
      params: variant.params,
      foldValues: variant.foldValues,
      mean,
      std,
      cv,
    })
  }

  out.sort((a, b) => {
    const left = a.mean ?? Number.NEGATIVE_INFINITY
    const right = b.mean ?? Number.NEGATIVE_INFINITY
    return right - left
  })
  return out
}

function rollingSmaFromSeries(series: SeriesPoint[], window: number): SeriesPoint[] {
  const w = Math.max(1, Math.round(window))
  if (!series.length || w <= 1) return [...series]
  const out: SeriesPoint[] = []
  let sum = 0
  const buffer: number[] = []
  for (const point of series) {
    buffer.push(point.value)
    sum += point.value
    if (buffer.length > w) {
      sum -= buffer.shift() ?? 0
    }
    if (buffer.length >= w) {
      out.push({ ts: point.ts, value: sum / w })
    }
  }
  return out
}

function findSmaSeries(
  figure: PlotlyFigure | null | undefined,
  closeSeries: SeriesPoint[],
  window: number
): SeriesPoint[] {
  const named = findSeriesByPredicate(
    figure,
    (_, name) => normalizeStrategyKind(name) === `sma_${Math.max(1, Math.round(window))}`
  )
  if (named.length > 0) return named
  return rollingSmaFromSeries(closeSeries, window)
}

function slopePct(series: SeriesPoint[], lookback = DECISION_SLOPE_LOOKBACK): number | null {
  if (series.length <= lookback) return null
  const last = series[series.length - 1]?.value
  const prev = series[series.length - 1 - lookback]?.value
  if (last === undefined || prev === undefined) return null
  return (last - prev) / (Math.abs(prev) + DECISION_EPS)
}

function trailingVolatility(closeSeries: SeriesPoint[], window = DECISION_VOL_WINDOW): number | null {
  if (closeSeries.length < window + 1) return null
  const returns: number[] = []
  for (let i = closeSeries.length - window; i < closeSeries.length; i += 1) {
    const prev = closeSeries[i - 1]?.value
    const curr = closeSeries[i]?.value
    if (prev === undefined || curr === undefined) continue
    if (!Number.isFinite(prev) || !Number.isFinite(curr) || prev === 0) continue
    returns.push(curr / prev - 1)
  }
  return stdPop(returns)
}

function daysSinceLastCrossover(fast: SeriesPoint[], slow: SeriesPoint[]): number | null {
  if (!fast.length || !slow.length) return null
  const fastMap = new Map<number, number>()
  for (const p of fast) fastMap.set(p.ts, p.value)
  const slowMap = new Map<number, number>()
  for (const p of slow) slowMap.set(p.ts, p.value)
  const commonTs = Array.from(fastMap.keys())
    .filter((ts) => slowMap.has(ts))
    .sort((a, b) => a - b)
  if (commonTs.length < 2) return null

  let prevSign = 0
  let crossTs: number | null = null
  for (const ts of commonTs) {
    const diff = (fastMap.get(ts) ?? 0) - (slowMap.get(ts) ?? 0)
    const sign = diff > 0 ? 1 : diff < 0 ? -1 : 0
    if (sign !== 0 && prevSign !== 0 && sign !== prevSign) {
      crossTs = ts
    }
    if (sign !== 0) prevSign = sign
  }

  if (crossTs === null) return null
  const lastTs = commonTs[commonTs.length - 1]
  const deltaMs = Math.max(0, lastTs - crossTs)
  return deltaMs / (24 * 60 * 60 * 1000)
}

function formatDecisionValue(value: number | null, objective: DecisionObjective): string {
  if (value === null || !Number.isFinite(value)) return "--"
  if (objective === "cagr") return formatPercent(value)
  if (objective === "pnl") return formatCurrency(value)
  return formatNumber(value, 3)
}

export function SingleBacktestResults({
  runId,
  symbol,
  runSpec,
  metrics,
  metricsLoading,
  showDecisionTab = true,
  forcedStrategy,
  strategyParamsOverride,
  portfolioConfigOverride,
  metricOverrides,
  decisionBatchRows,
  decisionSelectedHorizon,
  decisionSelectedBestParamsRaw,
  decisionSameStrategyRows,
}: {
  runId: string
  symbol?: string
  runSpec?: Record<string, unknown>
  metrics: MetricRow[] | undefined
  metricsLoading: boolean
  showDecisionTab?: boolean
  forcedStrategy?: string
  strategyParamsOverride?: Record<string, unknown>
  portfolioConfigOverride?: Record<string, unknown>
  metricOverrides?: {
    cagr?: number | null
    pnl?: number | null
    total_return?: number | null
    sharpe?: number | null
    max_drawdown?: number | null
    n_fills?: number | null
    win_pct?: number | null
  }
  decisionBatchRows?: Array<Record<string, string>>
  decisionSelectedHorizon?: string | null
  decisionSelectedBestParamsRaw?: unknown
  decisionSameStrategyRows?: LeaderboardRow[]
}) {
  const { data: artifacts, isLoading: artifactsLoading } = useArtifacts(
    runId,
    symbol ? { symbol } : undefined
  )

  const strategies = useMemo(() => {
    const out = new Set<string>()
    for (const artifact of artifacts ?? []) {
      if (!artifact.name.includes(".")) continue
      const parsed = splitArtifactName(artifact.name)
      if (parsed.strategy) out.add(parsed.strategy)
    }
    const forced = normalizeStrategyKind(forcedStrategy)
    if (forced) out.add(forced)
    return Array.from(out).sort()
  }, [artifacts, forcedStrategy])

  const baseRunStrategyParams = useMemo<Record<string, unknown>>(() => {
    if (!isRecord(runSpec)) return {}
    const strategy = isRecord(runSpec.strategy) ? runSpec.strategy : {}
    const params = isRecord(strategy.params) ? strategy.params : {}
    return flattenParams(params)
  }, [runSpec])

  const overrideStrategyParams = useMemo<Record<string, unknown>>(() => {
    if (!isRecord(strategyParamsOverride)) return {}
    return flattenParams(strategyParamsOverride)
  }, [strategyParamsOverride])

  const runStrategyParams = useMemo<Record<string, unknown>>(
    () => ({ ...baseRunStrategyParams, ...overrideStrategyParams }),
    [baseRunStrategyParams, overrideStrategyParams]
  )

  const baseRunPortfolioConfig = useMemo<Record<string, unknown>>(() => {
    if (!isRecord(runSpec)) return {}
    return isRecord(runSpec.portfolio) ? runSpec.portfolio : {}
  }, [runSpec])

  const runPortfolioConfig = useMemo<Record<string, unknown>>(
    () => ({
      ...baseRunPortfolioConfig,
      ...(isRecord(portfolioConfigOverride) ? portfolioConfigOverride : {}),
    }),
    [baseRunPortfolioConfig, portfolioConfigOverride]
  )

  const [strategy, setStrategy] = useState<string | null>(null)
  const [plotFigures, setPlotFigures] = useState<Partial<Record<PlotKey, PlotlyFigure>>>({})
  const [plotLoading, setPlotLoading] = useState(false)
  const [tradePerformance, setTradePerformance] = useState<TradePerformanceRow[]>([])
  const [ledgerRows, setLedgerRows] = useState<TradesLedgerRow[]>([])
  const [tableLoading, setTableLoading] = useState(false)
  const [materializeLoading, setMaterializeLoading] = useState(false)
  const [materializedMetrics, setMaterializedMetrics] = useState<Record<string, number>>({})
  const materializeAttemptedRef = useRef<Set<string>>(new Set())
  const [decisionObjective, setDecisionObjective] = useState<DecisionObjective>(
    objectiveFromRunSpec(runSpec)
  )
  const [selectedDecisionFoldKeys, setSelectedDecisionFoldKeys] = useState<string[]>([])

  useEffect(() => {
    setDecisionObjective(objectiveFromRunSpec(runSpec))
  }, [runSpec])

  const displayedStrategyParams = useMemo(() => {
    return Object.fromEntries(
      Object.entries(runStrategyParams).filter(([key]) => {
        const normalized = normalizeKey(key)
        if (STRATEGY_PARAM_EXCLUDE_KEYS.has(normalized)) return false
        return !normalized.startsWith("cost")
      })
    )
  }, [runStrategyParams])

  const strategyParamEntries = useMemo(
    () =>
      Object.entries(displayedStrategyParams).sort(([left], [right]) =>
        left.localeCompare(right)
      ),
    [displayedStrategyParams]
  )

  const controlTiles = useMemo<PortfolioControlTile[]>(() => {
    const initialCash = toNumber(runPortfolioConfig.initial_cash)
    const buyPct = toNumber(runPortfolioConfig.buy_pct_cash)
    const sellPct = toNumber(runPortfolioConfig.sell_pct_shares)
    const cooldownBars = toNumber(runPortfolioConfig.cooldown_bars)
    const minReturn = toNumber(runPortfolioConfig.min_return_before_sell)
    return [
      {
        label: "Initial Cash",
        value: initialCash === null ? "--" : formatCurrency(initialCash),
      },
      {
        label: "Buy %",
        value: buyPct === null ? "--" : formatPercent(buyPct),
      },
      {
        label: "Sell %",
        value: sellPct === null ? "--" : formatPercent(sellPct),
      },
      {
        label: "Cooldown Bars",
        value: cooldownBars === null ? "--" : formatNumber(cooldownBars, 0),
      },
      {
        label: "Min Return Before Sell",
        value: minReturn === null ? "--" : formatPercent(minReturn),
      },
    ]
  }, [runPortfolioConfig])

  const volumeGateDisplay = useMemo<GateConfigDisplay>(() => {
    const volumeGate = isRecord(runPortfolioConfig.volume_gate)
      ? runPortfolioConfig.volume_gate
      : {}
    const enabled = toBoolean(
      volumeGate.enabled ?? runPortfolioConfig.use_volume_gate ?? runPortfolioConfig.volume_gate_enabled,
      false
    )
    if (!enabled) return { enabled: false, rows: [] }

    const kindRaw =
      typeof volumeGate.kind === "string"
        ? volumeGate.kind
        : typeof runPortfolioConfig.volume_gate_kind === "string"
          ? runPortfolioConfig.volume_gate_kind
          : ""
    const kind = kindRaw.trim().toLowerCase()
    const rows: ParamDisplayRow[] = [{ label: "Kind", value: kind || "--" }]

    if (kind === "min_abs") {
      const minAbs = toNumber(volumeGate.min_volume_abs ?? runPortfolioConfig.min_volume_abs)
      rows.push({
        label: "Min Volume Abs",
        value: minAbs === null ? "--" : formatNumber(minAbs, 0),
      })
    } else {
      const minRatio = toNumber(
        volumeGate.min_volume_ratio_adv ?? runPortfolioConfig.min_volume_ratio_adv
      )
      const advWindow = toNumber(volumeGate.adv_window ?? runPortfolioConfig.volume_gate_adv_window)
      rows.push({
        label: "Min Volume / ADV",
        value: minRatio === null ? "--" : formatPercent(minRatio),
      })
      rows.push({
        label: "ADV Window",
        value: advWindow === null ? "--" : formatNumber(advWindow, 0),
      })
    }

    return { enabled: true, rows }
  }, [runPortfolioConfig])

  const participationCapDisplay = useMemo<GateConfigDisplay>(() => {
    const participationCap = isRecord(runPortfolioConfig.participation_cap)
      ? runPortfolioConfig.participation_cap
      : {}
    const enabled = toBoolean(
      participationCap.enabled ??
        runPortfolioConfig.use_participation_cap ??
        runPortfolioConfig.participation_cap_enabled,
      false
    )
    if (!enabled) return { enabled: false, rows: [] }

    const rate = toNumber(participationCap.rate ?? runPortfolioConfig.participation_rate)
    const basis =
      typeof participationCap.basis === "string"
        ? participationCap.basis
        : typeof runPortfolioConfig.participation_basis === "string"
          ? runPortfolioConfig.participation_basis
          : ""
    const advWindow = toNumber(participationCap.adv_window ?? runPortfolioConfig.adv_window)

    const rows: ParamDisplayRow[] = [
      { label: "Rate", value: rate === null ? "--" : formatPercent(rate) },
      { label: "Basis", value: basis || "--" },
    ]
    if (basis.trim().toLowerCase() === "adv") {
      rows.push({
        label: "ADV Window",
        value: advWindow === null ? "--" : formatNumber(advWindow, 0),
      })
    }
    return { enabled: true, rows }
  }, [runPortfolioConfig])

  useEffect(() => {
    const forced = normalizeStrategyKind(forcedStrategy)
    if (forced) {
      if (strategies.includes(forced)) {
        if (strategy !== forced) setStrategy(forced)
        return
      }
      setStrategy(strategies.length ? strategies[0] : null)
      return
    }
    if (!strategies.length) {
      setStrategy(null)
      return
    }
    if (!strategy || !strategies.includes(strategy)) {
      setStrategy(strategies[0])
    }
  }, [forcedStrategy, strategies, strategy])

  useEffect(() => {
    if (artifactsLoading) return

    if (!strategy) {
      setPlotFigures({})
      setTradePerformance([])
      setLedgerRows([])
      setMaterializedMetrics({})
      setMaterializeLoading(false)
      return
    }

    let cancelled = false
    const artifactRows = artifacts ?? []
    const activeStrategy = strategy
    async function load() {
      setPlotLoading(true)
      setTableLoading(true)
      setMaterializeLoading(false)

      try {
        const nextPlots: Partial<Record<PlotKey, PlotlyFigure>> = {}
        let nextTradePerformance: TradePerformanceRow[] = []
        let nextLedgerRows: TradesLedgerRow[] = []

        await Promise.all(
          PLOT_SPECS.map(async ({ key }) => {
            const artifact = findArtifactByBase(
              artifactRows,
              activeStrategy,
              key,
              "strategy_plotly_json"
            )
            if (!artifact) return
            try {
              const fig = await fetchArtifactJson(artifact.url, artifact.object_key)
              nextPlots[key] = fig
            } catch {
              // plot stays unavailable if artifact content fails
            }
          })
        )

        const perfArtifact = findArtifactByBase(
          artifactRows,
          activeStrategy,
          "trade_performance",
          "strategy_trade_performance_csv"
        )
        if (perfArtifact) {
          const csv = await fetchArtifactText(
            perfArtifact.url,
            perfArtifact.object_key
          )
          const rows = parseCsvRecords(csv)
          const parsed = rows.map((row) => {
            const metric = row.metric ?? row.Metric ?? ""
            const value = toNumber(row.value ?? row.Value ?? "")
            return { metric, value }
          })
          nextTradePerformance = TRADE_PERF_ORDER.map((name) => {
            const match = parsed.find(
              (row) => normalizeKey(row.metric) === normalizeKey(name)
            )
            return match ?? { metric: name, value: null }
          })
        }

        const ledgerArtifact = findArtifactByBase(
          artifactRows,
          activeStrategy,
          "trade_ledger",
          "strategy_trade_ledger_csv"
        )
        if (ledgerArtifact) {
          const csv = await fetchArtifactText(
            ledgerArtifact.url,
            ledgerArtifact.object_key
          )
          nextLedgerRows = parseCsvRecords(csv).map(normalizeLedgerRow)
        }

        // When strategyParamsOverride is active, each variant must be materialized
        // independently so its specific plots/ledger/performance are shown.
        const hasParamOverrides = Object.keys(overrideStrategyParams).length > 0
        const missingPricePlot = !nextPlots.price_indicators_trades
        const missingTradePerf = nextTradePerformance.length === 0
        const missingLedger = nextLedgerRows.length === 0
        // Include a params signature in the key so different variants of the same
        // strategy kind each get their own materialization slot.
        const paramsSignature = hasParamOverrides
          ? JSON.stringify(Object.fromEntries(Object.entries(runStrategyParams).sort()))
          : ""
        const materializeKey = `${runId}::${symbol ?? "__ALL__"}::${activeStrategy}::${paramsSignature}`

        const canMaterialize =
          Boolean(runId) &&
          Boolean(symbol) &&
          !materializeAttemptedRef.current.has(materializeKey) &&
          (missingPricePlot || missingTradePerf || missingLedger || hasParamOverrides)

        if (canMaterialize) {
          setMaterializeLoading(true)
          try {
            const details = await materializeStrategyDetails(runId, {
              symbol: symbol ?? "",
              strategy_kind: activeStrategy,
              strategy_params: runStrategyParams,
              portfolio_overrides: runPortfolioConfig,
            })
            if (cancelled) return

            materializeAttemptedRef.current.add(materializeKey)

            const materializedPlots = details.plots ?? {}
            for (const { key } of PLOT_SPECS) {
              const maybeFigure = materializedPlots[key]
              if (!maybeFigure) continue
              // When param overrides are active, always replace artifact-loaded plots
              // with freshly materialized ones for the specific parameter set.
              if (!hasParamOverrides && nextPlots[key]) continue
              if (Array.isArray(maybeFigure.data) && typeof maybeFigure.layout === "object") {
                nextPlots[key] = maybeFigure as PlotlyFigure
              }
            }

            if ((missingTradePerf || hasParamOverrides) && Array.isArray(details.trade_performance)) {
              const rows = details.trade_performance.filter(
                (row): row is Record<string, unknown> =>
                  Boolean(row) && typeof row === "object" && !Array.isArray(row)
              )
              nextTradePerformance = normalizeTradePerformanceRows(rows)
            }

            if ((missingLedger || hasParamOverrides) && Array.isArray(details.trade_ledger)) {
              const rows = details.trade_ledger.filter(
                (row): row is Record<string, unknown> =>
                  Boolean(row) && typeof row === "object" && !Array.isArray(row)
              )
              nextLedgerRows = rows.map(normalizeLedgerRowAny)
            }

            const nextMetrics: Record<string, number> = {}
            const rawMetrics = details.metrics ?? {}
            for (const [key, value] of Object.entries(rawMetrics)) {
              const n = toNumber(value)
              if (n !== null && Number.isFinite(n)) {
                nextMetrics[normalizeKey(key)] = n
              }
            }
            setMaterializedMetrics(nextMetrics)
          } catch {
            // Keep artifact-backed values if on-demand materialization fails.
          } finally {
            if (!cancelled) setMaterializeLoading(false)
          }
        } else {
          setMaterializedMetrics({})
        }

        if (!cancelled) {
          setPlotFigures(nextPlots)
          setTradePerformance(nextTradePerformance)
          setLedgerRows(nextLedgerRows)
        }
      } finally {
        if (!cancelled) {
          setPlotLoading(false)
          setTableLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [artifacts, artifactsLoading, overrideStrategyParams, runId, runPortfolioConfig, runStrategyParams, strategy, symbol])

  const metricMap = useMemo(() => {
    const map = toMetricMap(metrics)
    for (const [key, value] of Object.entries(materializedMetrics)) {
      if (Number.isFinite(value)) {
        map.set(normalizeKey(key), value)
      }
    }
    const overrideRows: Array<[string, number | null | undefined]> = [
      ["CAGR", metricOverrides?.cagr],
      ["Net PnL", metricOverrides?.pnl],
      ["Total return", metricOverrides?.total_return],
      ["Sharpe", metricOverrides?.sharpe],
      ["Max drawdown", metricOverrides?.max_drawdown],
      ["Trades", metricOverrides?.n_fills],
      ["Win Rate", metricOverrides?.win_pct],
    ]
    for (const [key, value] of overrideRows) {
      if (typeof value === "number" && Number.isFinite(value)) {
        map.set(normalizeKey(key), value)
      }
    }
    return map
  }, [materializedMetrics, metricOverrides, metrics])
  const tradePerfMap = useMemo(() => {
    const map = new Map<string, number>()
    for (const row of tradePerformance) {
      if (row.value === null) continue
      map.set(normalizeKey(row.metric), row.value)
    }
    return map
  }, [tradePerformance])

  const metricCards = useMemo(
    () => [
      {
        label: "CAGR",
        value: getMetric(metricMap, ["CAGR"]),
        fmt: "percent" as const,
      },
      {
        label: "PnL",
        value: getMetric(metricMap, ["Net PnL", "PnL"]),
        fmt: "currency" as const,
      },
      {
        label: "Total Return",
        value: getMetric(metricMap, ["Total return"]),
        fmt: "percent" as const,
      },
      {
        label: "Trades",
        value:
          getMetric(metricMap, ["Trades"]) ??
          tradePerfMap.get(normalizeKey("Trades")) ??
          null,
        fmt: "int" as const,
      },
      {
        label: "Win%",
        value:
          getMetric(metricMap, ["Win Rate"]) ??
          tradePerfMap.get(normalizeKey("Win Rate")) ??
          null,
        fmt: "percent" as const,
      },
      {
        label: "Max Drawdown",
        value: getMetric(metricMap, ["Max drawdown"]),
        fmt: "percent" as const,
      },
      {
        label: "Sharpe",
        value: getMetric(metricMap, ["Sharpe", "Sharpe Ratio"]),
        fmt: "number" as const,
      },
    ],
    [metricMap, tradePerfMap]
  )

  const priceFigureWithFallbackMarkers = useMemo(
    () => withLedgerTradeMarkers(plotFigures.price_indicators_trades ?? null, ledgerRows),
    [plotFigures.price_indicators_trades, ledgerRows]
  )

  const decisionBaseFigure = useMemo(
    () => toCloseLineDecisionFigure(priceFigureWithFallbackMarkers),
    [priceFigureWithFallbackMarkers]
  )

  const decisionSignalExplanation = useMemo(
    () => buildSignalExplanation(strategy, runStrategyParams, decisionBaseFigure),
    [decisionBaseFigure, runStrategyParams, strategy]
  )

  const isSmaPriceDecision = useMemo(() => {
    const kind = normalizeStrategyKind(strategy)
    return kind === "sma_price" || kind === "price_sma" || kind === "price_above_sma"
  }, [strategy])

  const selectedDecisionHorizon = useMemo(() => {
    const flat = flattenParams(parseUnknownObject(decisionSelectedBestParamsRaw))
    const fromBest = String(
      flat["simple_wfo.horizon"] ?? flat["walk_forward.horizon"] ?? ""
    )
      .trim()
      .toLowerCase()
    const fromProp = String(decisionSelectedHorizon ?? "")
      .trim()
      .toLowerCase()
    return fromBest || fromProp || null
  }, [decisionSelectedBestParamsRaw, decisionSelectedHorizon])

  const decisionBatchParsed = useMemo(
    () =>
      parseBatchDecisionRows(
        decisionBatchRows ?? [],
        decisionObjective,
        selectedDecisionHorizon
      ),
    [decisionBatchRows, decisionObjective, selectedDecisionHorizon]
  )

  useEffect(() => {
    const available = decisionBatchParsed.folds.map((fold) => fold.key)
    setSelectedDecisionFoldKeys((prev) => {
      if (!available.length) return []
      const kept = prev.filter((key) => available.includes(key))
      return kept.length ? kept : available
    })
  }, [decisionBatchParsed.folds])

  const decisionEffectiveFoldKeys = useMemo(() => {
    if (!decisionBatchParsed.folds.length) return [] as string[]
    if (!selectedDecisionFoldKeys.length) {
      return decisionBatchParsed.folds.map((fold) => fold.key)
    }
    return selectedDecisionFoldKeys.filter((key) =>
      decisionBatchParsed.folds.some((fold) => fold.key === key)
    )
  }, [decisionBatchParsed.folds, selectedDecisionFoldKeys])

  const decisionVariantAggregates = useMemo(
    () =>
      computeVariantAggregates(
        decisionBatchParsed.variants,
        decisionEffectiveFoldKeys
      ),
    [decisionBatchParsed.variants, decisionEffectiveFoldKeys]
  )
  const decisionStrategyRowCount = decisionSameStrategyRows?.length ?? 0

  const decisionVariantMinMax = useMemo(() => {
    const values = decisionVariantAggregates
      .flatMap((variant) =>
        decisionEffectiveFoldKeys
          .map((foldKey) => variant.foldValues.get(foldKey))
          .filter(
            (value): value is number => value !== undefined && Number.isFinite(value)
          )
      )
    if (!values.length) return { min: 0, max: 1 }
    return { min: Math.min(...values), max: Math.max(...values) }
  }, [decisionEffectiveFoldKeys, decisionVariantAggregates])

  const selectedDecisionVariantKey = useMemo(() => {
    const raw = {
      ...flattenParams(parseUnknownObject(decisionSelectedBestParamsRaw)),
      ...runStrategyParams,
    }
    const sma = extractSmaParams(raw)
    return decisionVariantKey(sma.window, sma.signalMode)
  }, [decisionSelectedBestParamsRaw, runStrategyParams])

  const selectedDecisionVariant = useMemo(() => {
    const exact = decisionVariantAggregates.find(
      (variant) => variant.key === selectedDecisionVariantKey
    )
    if (exact) return exact
    return decisionVariantAggregates[0] ?? null
  }, [decisionVariantAggregates, selectedDecisionVariantKey])

  const decisionPerformanceScore = useMemo(() => {
    const currentMean = selectedDecisionVariant?.mean
    if (currentMean === null || currentMean === undefined) return 0
    const means = decisionVariantAggregates
      .map((variant) => variant.mean)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    if (!means.length) return 0
    const min = Math.min(...means)
    const max = Math.max(...means)
    if (max - min <= DECISION_EPS) return 50
    return 100 * clamp01((currentMean - min) / (max - min))
  }, [decisionVariantAggregates, selectedDecisionVariant])

  const decisionStabilityScore = useMemo(() => {
    const cv = selectedDecisionVariant?.cv
    if (cv === null || cv === undefined || !Number.isFinite(cv)) return 0
    return 100 * (1 - clamp01(cv / DECISION_CV_MAX))
  }, [selectedDecisionVariant])

  const decisionConfidenceTime = useMemo(
    () => 0.6 * decisionPerformanceScore + 0.4 * decisionStabilityScore,
    [decisionPerformanceScore, decisionStabilityScore]
  )

  const decisionVariantByKey = useMemo(() => {
    const out = new Map<string, DecisionVariantAggregate>()
    for (const variant of decisionVariantAggregates) out.set(variant.key, variant)
    return out
  }, [decisionVariantAggregates])

  const decisionNeighborRows = useMemo<DecisionNeighborRow[]>(() => {
    if (!selectedDecisionVariant) return []
    const base = extractSmaParams(selectedDecisionVariant.params)
    const neighbors: Array<{ window: number | null; signalMode: string; label: string }> = []

    if (base.window !== null) {
      if (base.window > 10) {
        neighbors.push({
          window: base.window - 1,
          signalMode: base.signalMode,
          label: "sma_window - 1",
        })
      }
      if (base.window < 250) {
        neighbors.push({
          window: base.window + 1,
          signalMode: base.signalMode,
          label: "sma_window + 1",
        })
      }
    }

    const altSignalMode = base.signalMode === "cross" ? "level" : "cross"
    neighbors.push({
      window: base.window,
      signalMode: altSignalMode,
      label: "signal_mode swap",
    })

    const out: DecisionNeighborRow[] = []
    const seen = new Set<string>()
    const bestMean = selectedDecisionVariant.mean
    for (const neighbor of neighbors) {
      const key = decisionVariantKey(neighbor.window, neighbor.signalMode)
      if (seen.has(key) || key === selectedDecisionVariant.key) continue
      seen.add(key)
      const match = decisionVariantByKey.get(key)
      const metric = match?.mean ?? null
      const deltaPct =
        metric !== null &&
        bestMean !== null &&
        Number.isFinite(metric) &&
        Number.isFinite(bestMean)
          ? (bestMean - metric) / (Math.abs(bestMean) + DECISION_EPS)
          : null
      out.push({
        label: neighbor.label,
        paramsText: decisionVariantLabel(neighbor.window, neighbor.signalMode),
        metric,
        deltaPct,
      })
    }
    return out
  }, [decisionVariantByKey, selectedDecisionVariant])

  const decisionParamRobustnessScore = useMemo(() => {
    const bestMean = selectedDecisionVariant?.mean
    if (bestMean === null || bestMean === undefined) return 0
    const neighborMetrics = decisionNeighborRows
      .map((row) => row.metric)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    if (!neighborMetrics.length) return 50
    const neighborMean =
      neighborMetrics.reduce((acc, value) => acc + value, 0) / neighborMetrics.length
    const drop =
      (bestMean - neighborMean) / (Math.abs(bestMean) + DECISION_EPS)
    return 100 * (1 - clamp01(Math.max(0, drop) / DECISION_DROP_MAX))
  }, [decisionNeighborRows, selectedDecisionVariant])

  const decisionNeighborMean = useMemo(() => {
    const neighborMetrics = decisionNeighborRows
      .map((row) => row.metric)
      .filter((value): value is number => value !== null && Number.isFinite(value))
    if (!neighborMetrics.length) return null
    return neighborMetrics.reduce((acc, value) => acc + value, 0) / neighborMetrics.length
  }, [decisionNeighborRows])

  const decisionDropPct = useMemo(() => {
    const bestMean = selectedDecisionVariant?.mean
    if (bestMean === null || bestMean === undefined || decisionNeighborMean === null) return null
    return (bestMean - decisionNeighborMean) / (Math.abs(bestMean) + DECISION_EPS)
  }, [decisionNeighborMean, selectedDecisionVariant])

  const decisionConfidenceFinal = useMemo(
    () => 0.65 * decisionConfidenceTime + 0.35 * decisionParamRobustnessScore,
    [decisionConfidenceTime, decisionParamRobustnessScore]
  )

  const decisionOpportunity = useMemo(() => {
    const closeSeries = findCloseSeries(decisionBaseFigure)
    if (!closeSeries.length) {
      return {
        total: 0,
        regime: 0,
        direction: 0,
        confirmation: 0,
        timing: 0,
        risk: 0,
        fastWindow: null as number | null,
        slowWindow: null as number | null,
        inputs: {
          distanceToSma200: null as number | null,
          slope200: null as number | null,
          slopeSlow: null as number | null,
          vol20: null as number | null,
          distFastSlow: null as number | null,
          daysSinceCross: null as number | null,
          bull: null as boolean | null,
          trendLike: null as boolean | null,
        },
        closeSeries: [] as SeriesPoint[],
        fastSeries: [] as SeriesPoint[],
        slowSeries: [] as SeriesPoint[],
        sma200Series: [] as SeriesPoint[],
      }
    }

    const selectedParams = {
      ...flattenParams(parseUnknownObject(decisionSelectedBestParamsRaw)),
      ...runStrategyParams,
    }
    const sma = extractSmaParams(selectedParams)
    const fastWindow = Math.max(10, Math.round(sma.window ?? 50))
    const slowWindow = Math.min(200, Math.max(fastWindow + 20, fastWindow * 2))

    const fastSeries = findSmaSeries(decisionBaseFigure, closeSeries, fastWindow)
    const slowSeries = findSmaSeries(decisionBaseFigure, closeSeries, slowWindow)
    const sma200Series = findSmaSeries(decisionBaseFigure, closeSeries, 200)

    const closeNow = latestValue(closeSeries).current
    const fastNow = latestValue(fastSeries).current
    const slowNow = latestValue(slowSeries).current
    const sma200Now = latestValue(sma200Series).current
    const slope200 = slopePct(sma200Series, DECISION_SLOPE_LOOKBACK)
    const slopeSlow = slopePct(slowSeries, DECISION_SLOPE_LOOKBACK)
    const vol20 = trailingVolatility(closeSeries, DECISION_VOL_WINDOW)

    const distanceToSma200 =
      closeNow !== null && sma200Now !== null
        ? (closeNow - sma200Now) / (Math.abs(sma200Now) + DECISION_EPS)
        : null
    const distFastSlow =
      closeNow !== null && fastNow !== null && slowNow !== null
        ? Math.abs(fastNow - slowNow) / (Math.abs(closeNow) + DECISION_EPS)
        : null
    const daysSinceCross = daysSinceLastCrossover(fastSeries, slowSeries)

    const bull =
      closeNow !== null && sma200Now !== null ? closeNow > sma200Now : null
    const trendLike = slope200 !== null ? Math.abs(slope200) > 0.01 : null

    const distNorm = distanceToSma200 === null ? 0 : clamp01(Math.abs(distanceToSma200) / 0.12)
    const slopeNorm = slope200 === null ? 0 : clamp01(Math.abs(slope200) / 0.08)
    const scoreRegime = 100 * ((distNorm + slopeNorm) / 2)

    let scoreDirection = 40
    if (
      closeNow !== null &&
      sma200Now !== null &&
      fastNow !== null &&
      slowNow !== null
    ) {
      if (closeNow > sma200Now && fastNow > slowNow) scoreDirection = 92
      else if (closeNow > sma200Now || fastNow > slowNow) scoreDirection = 62
      else scoreDirection = 20
    }

    const confirmationChecks = [
      closeNow !== null && sma200Now !== null ? closeNow > sma200Now : null,
      fastNow !== null && slowNow !== null ? fastNow > slowNow : null,
      slopeSlow !== null ? slopeSlow > 0 : slope200 !== null ? slope200 > 0 : null,
    ].filter((value): value is boolean => value !== null)
    const scoreConfirmation = confirmationChecks.length
      ? (confirmationChecks.filter(Boolean).length / confirmationChecks.length) * 100
      : 0

    const freshScore =
      daysSinceCross === null
        ? 40
        : daysSinceCross <= DECISION_CROSS_FRESH_DAYS
          ? 100
          : Math.max(
              20,
              100 -
                ((daysSinceCross - DECISION_CROSS_FRESH_DAYS) /
                  DECISION_CROSS_FRESH_DAYS) *
                  60
            )
    const distPenalty = distFastSlow === null ? 0 : clamp01(distFastSlow / 0.08)
    const scoreTiming = Math.max(0, Math.min(100, freshScore * (1 - 0.5 * distPenalty)))

    const volNorm = vol20 === null ? 0 : clamp01(vol20 / 0.05)
    const riskIndex = (volNorm + distNorm) / 2
    const scoreRisk = 100 * (1 - riskIndex)

    const total =
      0.2 * (scoreRegime + scoreDirection + scoreConfirmation + scoreTiming + scoreRisk)

    return {
      total,
      regime: scoreRegime,
      direction: scoreDirection,
      confirmation: scoreConfirmation,
      timing: scoreTiming,
      risk: scoreRisk,
      fastWindow,
      slowWindow,
      inputs: {
        distanceToSma200,
        slope200,
        slopeSlow,
        vol20,
        distFastSlow,
        daysSinceCross,
        bull,
        trendLike,
      },
      closeSeries,
      fastSeries,
      slowSeries,
      sma200Series,
    }
  }, [decisionBaseFigure, decisionSelectedBestParamsRaw, runStrategyParams])

  const decisionPriceFigure = useMemo<PlotlyFigure | null>(() => {
    const closeSeries = decisionOpportunity.closeSeries
    if (!Array.isArray(closeSeries) || closeSeries.length === 0) return null

    const sliceTail = (series: SeriesPoint[], n = 180) => series.slice(Math.max(0, series.length - n))
    const closeTail = sliceTail(closeSeries)
    const fastTail = sliceTail(Array.isArray(decisionOpportunity.fastSeries) ? decisionOpportunity.fastSeries : [])
    const slowTail = sliceTail(Array.isArray(decisionOpportunity.slowSeries) ? decisionOpportunity.slowSeries : [])
    const sma200Tail = sliceTail(Array.isArray(decisionOpportunity.sma200Series) ? decisionOpportunity.sma200Series : [])

    const toXY = (series: SeriesPoint[]) => ({
      x: series.map((p) => new Date(p.ts).toISOString().slice(0, 10)),
      y: series.map((p) => p.value),
    })

    const closeXY = toXY(closeTail)
    const fastXY = toXY(fastTail)
    const slowXY = toXY(slowTail)
    const sma200XY = toXY(sma200Tail)
    const bullLabel =
      decisionOpportunity.inputs.bull === null
        ? "Unknown"
        : decisionOpportunity.inputs.bull
          ? "Bull"
          : "Bear"
    const trendLabel =
      decisionOpportunity.inputs.trendLike === null
        ? "n/a"
        : decisionOpportunity.inputs.trendLike
          ? "Trend-like"
          : "Range-like"

    return {
      data: [
        { type: "scatter", mode: "lines", name: "Close", x: closeXY.x, y: closeXY.y, line: { color: "#2563eb", width: 2 } },
        { type: "scatter", mode: "lines", name: `MA fast (${decisionOpportunity.fastWindow ?? "?"})`, x: fastXY.x, y: fastXY.y, line: { color: "#16a34a", width: 1.6 } },
        { type: "scatter", mode: "lines", name: `MA slow (${decisionOpportunity.slowWindow ?? "?"})`, x: slowXY.x, y: slowXY.y, line: { color: "#f59e0b", width: 1.6 } },
        { type: "scatter", mode: "lines", name: "SMA200", x: sma200XY.x, y: sma200XY.y, line: { color: "#dc2626", width: 1.8, dash: "dot" } },
      ],
      layout: {
        title: "Price + MA Fast + MA Slow + SMA200 (recent bars)",
        template: "plotly_white",
        legend: { orientation: "h" },
        margin: { t: 48, l: 40, r: 20, b: 34 },
        annotations: [
          {
            xref: "paper",
            yref: "paper",
            x: 0,
            y: 1.14,
            text: `Regime: ${bullLabel} | Structure: ${trendLabel}`,
            showarrow: false,
            font: { size: 11 },
          },
        ],
      },
    }
  }, [decisionOpportunity])

  const decisionOpportunityBreakdownFigure = useMemo<PlotlyFigure>(() => {
    const x = ["Regime", "Direction", "Confirmation", "Timing", "Risk"]
    const y = [
      decisionOpportunity.regime,
      decisionOpportunity.direction,
      decisionOpportunity.confirmation,
      decisionOpportunity.timing,
      decisionOpportunity.risk,
    ]
    return {
      data: [
        {
          type: "bar",
          x,
          y,
          marker: { color: ["#1d4ed8", "#0f766e", "#f59e0b", "#7c3aed", "#dc2626"] },
          text: y.map((value) => formatNumber(value, 1)),
          textposition: "outside",
        },
      ],
      layout: {
        title: "Opportunity Breakdown (0-100)",
        template: "plotly_white",
        margin: { t: 48, l: 40, r: 20, b: 36 },
        yaxis: { range: [0, 100] },
      },
    }
  }, [decisionOpportunity])

  const decisionShowTab = showDecisionTab && isSmaPriceDecision

  function renderMetricValue(
    kind: "percent" | "currency" | "number" | "int",
    value: number | null
  ) {
    if (value === null || !Number.isFinite(value)) return "--"
    if (kind === "percent") return formatPercent(value)
    if (kind === "currency") return formatCurrency(value)
    if (kind === "int") return formatNumber(value, 0)
    return formatNumber(value, 2)
  }

  if (artifactsLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Backtest Results</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 6 }).map((_, idx) => (
            <Skeleton key={idx} className="h-10 rounded-lg" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (!strategies.length) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Backtest Results</CardTitle>
        </CardHeader>
        <CardContent className="py-8 text-sm text-muted-foreground">
          Strategy artifacts are not available for this run/symbol yet.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card className="border-border/80 bg-gradient-to-br from-background via-background to-muted/30 shadow-sm">
        <CardHeader className="space-y-1 pb-3">
          <CardTitle className="text-base">Strategy Setup</CardTitle>
          <p className="text-xs text-muted-foreground">
            Parameter snapshot for this single backtest execution.
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          {!forcedStrategy ? (
            <div className="flex flex-wrap gap-2">
              {strategies.map((item) => {
                const active = item === strategy
                return (
                  <button
                    key={item}
                    type="button"
                    onClick={() => setStrategy(item)}
                    className={`rounded-md border px-3 py-1.5 text-xs font-semibold tracking-wide transition-all ${
                      active
                        ? "border-primary/50 bg-primary/10 text-primary shadow-sm"
                        : "border-border/70 bg-background text-muted-foreground hover:border-primary/30 hover:text-foreground"
                    }`}
                  >
                    {item}
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <span className="rounded-md border border-primary/40 bg-primary/10 px-3 py-1.5 text-xs font-semibold tracking-wide text-primary">
                {strategy ?? normalizeStrategyKind(forcedStrategy)}
              </span>
            </div>
          )}

          {strategyParamEntries.length > 0 && (
            <div className="rounded-xl border border-border/70 bg-background/80 p-4">
              <p className="mb-3 text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">
                Strategy Parameters
              </p>
              <div className="grid gap-x-5 gap-y-2 sm:grid-cols-2">
                {strategyParamEntries.map(([key, val]) => (
                  <div
                    key={key}
                    className="flex items-center justify-between border-b border-border/50 py-1.5 last:border-0"
                  >
                    <span className="text-xs text-muted-foreground">{formatParamLabel(key)}</span>
                    <span className="font-mono text-xs font-semibold text-foreground">
                      {toDisplayValue(val)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="rounded-xl border border-border/70 bg-background/70 p-4">
            <p className="mb-3 text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">
              Execution Controls
            </p>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              {controlTiles.map((tile) => (
                <div
                  key={tile.label}
                  className="rounded-lg border border-border/60 bg-gradient-to-b from-background to-muted/20 p-3"
                >
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    {tile.label}
                  </p>
                  <p className="mt-1 font-mono text-sm font-semibold text-foreground">{tile.value}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div className="rounded-xl border border-border/70 bg-background/70 p-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">
                  Volume Gate
                </p>
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                    volumeGateDisplay.enabled
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                      : "border-border bg-muted text-muted-foreground"
                  }`}
                >
                  {volumeGateDisplay.enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              {volumeGateDisplay.enabled ? (
                <div className="space-y-1.5">
                  {volumeGateDisplay.rows.map((row) => (
                    <div
                      key={row.label}
                      className="flex items-center justify-between border-b border-border/50 py-1.5 last:border-0"
                    >
                      <span className="text-xs text-muted-foreground">{row.label}</span>
                      <span className="font-mono text-xs font-semibold text-foreground">{row.value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Related parameters appear only when `volume_gate.enabled` is true.
                </p>
              )}
            </div>

            <div className="rounded-xl border border-border/70 bg-background/70 p-4">
              <div className="mb-3 flex items-center justify-between">
                <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-muted-foreground">
                  Participation Cap
                </p>
                <span
                  className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
                    participationCapDisplay.enabled
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
                      : "border-border bg-muted text-muted-foreground"
                  }`}
                >
                  {participationCapDisplay.enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              {participationCapDisplay.enabled ? (
                <div className="space-y-1.5">
                  {participationCapDisplay.rows.map((row) => (
                    <div
                      key={row.label}
                      className="flex items-center justify-between border-b border-border/50 py-1.5 last:border-0"
                    >
                      <span className="text-xs text-muted-foreground">{row.label}</span>
                      <span className="font-mono text-xs font-semibold text-foreground">{row.value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">
                  Related parameters appear only when `participation_cap.enabled` is true.
                </p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="trade-performance" className="space-y-4">
        <TabsList>
          <TabsTrigger value="trade-performance" className="text-xs">
            Trade Performance
          </TabsTrigger>
          <TabsTrigger value="plots" className="text-xs">
            Plots
          </TabsTrigger>
          <TabsTrigger value="metrics" className="text-xs">
            Metrics
          </TabsTrigger>
          <TabsTrigger value="trades-ledger" className="text-xs">
            Trades Ledger
          </TabsTrigger>
          {decisionShowTab && (
            <TabsTrigger value="decision" className="text-xs">
              Decision
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="trade-performance">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Trade Performance</CardTitle>
            </CardHeader>
            <CardContent className="px-0 pb-0">
              {tableLoading ? (
                <div className="space-y-2 px-4 pb-4">
                  {Array.from({ length: 6 }).map((_, idx) => (
                    <Skeleton key={idx} className="h-8 rounded-lg" />
                  ))}
                </div>
              ) : !tradePerformance.length ? (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  No trade performance data available.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border">
                        <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                          Metric
                        </th>
                        <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                          Value
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {tradePerformance.map((row) => (
                        <tr key={row.metric} className="border-b border-border/50">
                          <td className="px-3 py-2.5 text-xs text-foreground">{row.metric}</td>
                          <td className="px-3 py-2.5 text-right font-mono text-xs">
                            {formatTradePerfValue(row.metric, row.value)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="plots">
          <div className="space-y-4">
            {PLOT_SPECS.map((plot) => (
              <Card key={plot.key}>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">{plot.label}</CardTitle>
                </CardHeader>
                <CardContent>
                  {plotLoading || materializeLoading ? (
                    <Skeleton className="h-96 rounded-lg" />
                  ) : (plot.key === "price_indicators_trades"
                      ? priceFigureWithFallbackMarkers
                      : plotFigures[plot.key]) ? (
                    <PlotlyChart
                      figure={
                        plot.key === "price_indicators_trades"
                          ? priceFigureWithFallbackMarkers ?? undefined
                          : plotFigures[plot.key]
                      }
                    />
                  ) : (
                    <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
                      Detail plot could not be computed.
                    </div>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </TabsContent>

        <TabsContent value="metrics">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Strategy Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              {metricsLoading ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                  {Array.from({ length: 7 }).map((_, idx) => (
                    <Skeleton key={idx} className="h-16 rounded-lg" />
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                  {metricCards.map((item) => (
                    <div
                      key={item.label}
                      className="rounded-lg border border-border bg-secondary/20 p-3"
                    >
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                        {item.label}
                      </p>
                      <p className="mt-1 font-mono text-sm font-semibold text-foreground">
                        {renderMetricValue(item.fmt, item.value)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="trades-ledger">
          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Price + Indicators + Trades</CardTitle>
              </CardHeader>
              <CardContent>
                {plotLoading || materializeLoading ? (
                  <Skeleton className="h-96 rounded-lg" />
                ) : priceFigureWithFallbackMarkers ? (
                  <PlotlyChart figure={priceFigureWithFallbackMarkers ?? undefined} />
                ) : (
                  <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
                    Detail plot could not be computed.
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Trades Ledger</CardTitle>
              </CardHeader>
              <CardContent className="px-0 pb-0">
                {tableLoading || materializeLoading ? (
                  <div className="space-y-2 px-4 pb-4">
                    {Array.from({ length: 8 }).map((_, idx) => (
                      <Skeleton key={idx} className="h-8 rounded-lg" />
                    ))}
                  </div>
                ) : !ledgerRows.length ? (
                  <div className="py-8 text-center text-sm text-muted-foreground">
                    Trades ledger could not be computed.
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border">
                          <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            Timestamp
                          </th>
                          <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            Side
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            Prix d&apos;execution (open du jour)
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            Quantite
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            CMP
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            PnL realise
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            PnL latent
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            Close du jour
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            Available Quantity
                          </th>
                          <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            Position Value Cost
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {ledgerRows.map((row, idx) => (
                          <tr key={`${row.timestamp}-${idx}`} className="border-b border-border/50">
                            <td className="px-3 py-2.5 text-xs">{formatDateTime(row.timestamp)}</td>
                            <td className="px-3 py-2.5 text-xs">{row.side || "--"}</td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.prix_execution_open_jour)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.quantite)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.cmp)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.pnl_realise)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.pnl_latent)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.close_du_jour)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.available_quantity)}
                            </td>
                            <td className="px-3 py-2.5 text-right font-mono text-xs">
                              {formatNumber(row.position_value_cost)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {decisionShowTab && (
          <TabsContent value="decision">
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Decision Scores (sma_price)</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-lg border border-border bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                        Confidence
                      </p>
                      <p className="mt-1 font-mono text-2xl font-bold text-foreground">
                        {formatNumber(decisionConfidenceFinal, 1)} / 100
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        0.65 * confidence_time + 0.35 * score_param
                      </p>
                    </div>
                    <div className="rounded-lg border border-border bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                        Opportunity
                      </p>
                      <p className="mt-1 font-mono text-2xl font-bold text-foreground">
                        {formatNumber(decisionOpportunity.total, 1)} / 100
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        0.20 * (regime + direction + confirmation + timing + risk)
                      </p>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Trader view: Confidence mesure la robustesse (temps + params), Opportunity mesure la qualité du setup actuel.
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <CardTitle className="text-base">Confidence A1 - WFO Heatmap Table</CardTitle>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-muted-foreground">Objective</label>
                      <select
                        className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                        value={decisionObjective}
                        onChange={(event) =>
                          setDecisionObjective(
                            normalizeObjective(event.target.value, "pnl")
                          )
                        }
                      >
                        <option value="pnl">PnL</option>
                        <option value="cagr">CAGR</option>
                        <option value="sharpe">Sharpe</option>
                      </select>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {decisionBatchParsed.folds.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {decisionBatchParsed.folds.map((fold) => {
                        const active = decisionEffectiveFoldKeys.includes(fold.key)
                        return (
                          <button
                            key={fold.key}
                            type="button"
                            className={`rounded-md border px-2 py-1 text-[11px] ${
                              active
                                ? "border-primary/50 bg-primary/10 text-primary"
                                : "border-border text-muted-foreground"
                            }`}
                            title={`test: ${fold.start ?? "--"} -> ${fold.end ?? "--"}`}
                            onClick={() => {
                              setSelectedDecisionFoldKeys((prev) => {
                                if (prev.includes(fold.key)) {
                                  const next = prev.filter((key) => key !== fold.key)
                                  return next.length ? next : [fold.key]
                                }
                                return [...prev, fold.key]
                              })
                            }}
                          >
                            {fold.label}
                          </button>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Fold rows not available from `batch_period.results` for this symbol/horizon.
                      Known strategy rows: {decisionStrategyRowCount}.
                    </p>
                  )}

                  {decisionVariantAggregates.length > 0 && decisionEffectiveFoldKeys.length > 0 ? (
                    <div className="overflow-x-auto rounded-lg border border-border/70">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-border bg-secondary/20">
                            <th className="px-2 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              Variant
                            </th>
                            {decisionBatchParsed.folds
                              .filter((fold) => decisionEffectiveFoldKeys.includes(fold.key))
                              .map((fold) => (
                                <th
                                  key={fold.key}
                                  title={`test: ${fold.start ?? "--"} -> ${fold.end ?? "--"}`}
                                  className="px-2 py-2 text-right text-[11px] font-bold uppercase tracking-wider text-muted-foreground"
                                >
                                  {fold.label}
                                </th>
                              ))}
                            <th className="px-2 py-2 text-right text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              MEAN
                            </th>
                            <th className="px-2 py-2 text-right text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              DISPERSION
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {decisionVariantAggregates.map((variant) => (
                            <tr key={variant.key} className="border-b border-border/50 last:border-0">
                              <td className="px-2 py-2 font-mono text-[11px] text-foreground">
                                {variant.label}
                              </td>
                              {decisionBatchParsed.folds
                                .filter((fold) => decisionEffectiveFoldKeys.includes(fold.key))
                                .map((fold) => {
                                  const value = variant.foldValues.get(fold.key)
                                  const hasValue =
                                    value !== undefined && Number.isFinite(value)
                                  const ratio =
                                    hasValue &&
                                    decisionVariantMinMax.max > decisionVariantMinMax.min
                                      ? clamp01(
                                          (value! - decisionVariantMinMax.min) /
                                            (decisionVariantMinMax.max - decisionVariantMinMax.min)
                                        )
                                      : 0
                                  const bgAlpha = hasValue ? 0.08 + ratio * 0.28 : 0.02
                                  const bgColor = hasValue
                                    ? `rgba(34, 197, 94, ${bgAlpha.toFixed(3)})`
                                    : "rgba(148, 163, 184, 0.06)"
                                  return (
                                    <td
                                      key={`${variant.key}-${fold.key}`}
                                      className="px-2 py-2 text-right font-mono text-[11px]"
                                      style={{ backgroundColor: bgColor }}
                                    >
                                      {hasValue
                                        ? formatDecisionValue(value ?? null, decisionObjective)
                                        : "--"}
                                    </td>
                                  )
                                })}
                              <td className="px-2 py-2 text-right font-mono text-[11px] font-semibold text-foreground">
                                {formatDecisionValue(variant.mean, decisionObjective)}
                              </td>
                              <td className="px-2 py-2 text-right font-mono text-[11px] text-muted-foreground">
                                std={formatNumber(variant.std, 4)} | cv={formatNumber(variant.cv, 3)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Not enough fold/variant rows to build the WFO heatmap table.
                    </p>
                  )}

                  <div className="rounded-md border border-border/70 bg-secondary/20 p-3 text-xs text-muted-foreground">
                    <p className="font-semibold text-foreground">Formula</p>
                    <p>
                      score_perf = normalized(mean across selected folds), cv = std/(|mean|+eps),
                      score_stability = 100*(1-clip(cv,0,cv_max)/cv_max), confidence_time = 0.60*score_perf + 0.40*score_stability.
                    </p>
                    <p className="mt-1">
                      Inputs: mean={formatDecisionValue(selectedDecisionVariant?.mean ?? null, decisionObjective)},
                      std={formatNumber(selectedDecisionVariant?.std, 4)},
                      cv={formatNumber(selectedDecisionVariant?.cv, 4)},
                      cv_max={DECISION_CV_MAX}, folds={decisionEffectiveFoldKeys.length}.
                    </p>
                    <p className="mt-1">
                      Trader view: on privilégie des performances OOS élevées et régulières d’un fold à l’autre.
                    </p>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Confidence A2 - Parameter Robustness</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-md border border-border/70 bg-secondary/20 p-3">
                    <p className="text-[11px] font-semibold text-foreground">
                      score_param: {formatNumber(decisionParamRobustnessScore, 1)} / 100
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      drop = (metric_best - mean(metric_neighbors)) / (|metric_best|+eps)
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Inputs: metric_best={formatDecisionValue(selectedDecisionVariant?.mean ?? null, decisionObjective)},
                      metric_neighbors={formatDecisionValue(decisionNeighborMean, decisionObjective)},
                      drop={formatPercent(decisionDropPct)},
                      drop_max={formatPercent(DECISION_DROP_MAX)}.
                    </p>
                  </div>

                  {decisionNeighborRows.length > 0 ? (
                    <div className="overflow-x-auto rounded-lg border border-border/70">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-border bg-secondary/20">
                            <th className="px-2 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              Neighbor
                            </th>
                            <th className="px-2 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              Params
                            </th>
                            <th className="px-2 py-2 text-right text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              Metric
                            </th>
                            <th className="px-2 py-2 text-right text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              Drop %
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {decisionNeighborRows.map((row) => (
                            <tr key={`${row.label}-${row.paramsText}`} className="border-b border-border/50 last:border-0">
                              <td className="px-2 py-2 text-xs text-foreground">{row.label}</td>
                              <td className="px-2 py-2 font-mono text-[11px] text-muted-foreground">{row.paramsText}</td>
                              <td className="px-2 py-2 text-right font-mono text-[11px]">
                                {formatDecisionValue(row.metric, decisionObjective)}
                              </td>
                              <td className="px-2 py-2 text-right font-mono text-[11px]">
                                {formatPercent(row.deltaPct)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No local neighbor metrics found (score_param defaults to neutral).
                    </p>
                  )}

                  <p className="text-xs text-muted-foreground">
                    Trader view: si de petits changements de paramètres dégradent fortement la perf, la confiance baisse.
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Opportunity - Price + MAs</CardTitle>
                </CardHeader>
                <CardContent>
                  {decisionPriceFigure ? (
                    <PlotlyChart figure={decisionPriceFigure} />
                  ) : (
                    <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
                      Price/MA data not available for opportunity view.
                    </div>
                  )}
                  <p className="mt-2 text-xs text-muted-foreground">
                    Signal snapshot: {decisionSignalExplanation.summary}
                    {decisionSignalExplanation.asOf
                      ? ` (as of ${formatDateTime(decisionSignalExplanation.asOf)})`
                      : ""}
                    .
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Opportunity Breakdown</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <PlotlyChart figure={decisionOpportunityBreakdownFigure} />
                  <div className="rounded-md border border-border/70 bg-secondary/20 p-3 text-xs text-muted-foreground">
                    <p className="font-semibold text-foreground">Formula</p>
                    <p>
                      regime from |price-SMA200| and |slope200|, direction from price&gt;SMA200 and MAfast&gt;MAslow,
                      confirmation from boolean MA checks, timing from crossover recency (K={DECISION_CROSS_FRESH_DAYS})
                      and MA distance penalty, risk from vol20 + distance to SMA200.
                    </p>
                    <p className="mt-1">
                      Inputs: distance_to_SMA200={formatPercent(decisionOpportunity.inputs.distanceToSma200)},
                      slope200={formatPercent(decisionOpportunity.inputs.slope200)},
                      vol20={formatNumber(decisionOpportunity.inputs.vol20, 4)},
                      dist_fast_slow={formatPercent(decisionOpportunity.inputs.distFastSlow)},
                      days_since_cross={formatNumber(decisionOpportunity.inputs.daysSinceCross, 1)}.
                    </p>
                    <p className="mt-1">
                      Trader view: on favorise un contexte de tendance confirmé, pas trop étiré, et avec un risque court-terme contenu.
                    </p>
                  </div>
                </CardContent>
              </Card>
            </div>
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
