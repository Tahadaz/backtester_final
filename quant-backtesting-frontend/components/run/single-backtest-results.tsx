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
  if (!ledgerRows.length) return figure

  const hasBuy = hasNamedTrace(figure, "BUY")
  const hasSell = hasNamedTrace(figure, "SELL")
  if (hasBuy && hasSell) return figure

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

  const nextData = [...figure.data]
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

  if (nextData.length === figure.data.length) return figure
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

  const decisionWeekFigure = useMemo(
    () => sliceFigureToLastDays(decisionBaseFigure, 7),
    [decisionBaseFigure]
  )

  const decisionSignalExplanation = useMemo(
    () => buildSignalExplanation(strategy, runStrategyParams, decisionBaseFigure),
    [decisionBaseFigure, runStrategyParams, strategy]
  )

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
          {showDecisionTab && (
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
        </TabsContent>

        {showDecisionTab && (
          <TabsContent value="decision">
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Decision Chart (Last Available Week)</CardTitle>
                </CardHeader>
                <CardContent>
                  {plotLoading || materializeLoading ? (
                    <Skeleton className="h-96 rounded-lg" />
                  ) : decisionWeekFigure ? (
                    <PlotlyChart figure={decisionWeekFigure} />
                  ) : (
                    <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
                      Decision chart not available for this run.
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">Why The Signal Is {decisionSignalExplanation.summary}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <SignalBadge value={decisionSignalExplanation.signalValue} size="md" />
                    <span className="text-xs text-muted-foreground">
                      {decisionSignalExplanation.asOf
                        ? `As of ${formatDateTime(decisionSignalExplanation.asOf)}`
                        : "As-of timestamp unavailable"}
                    </span>
                  </div>
                  <p className="text-sm text-foreground">{decisionSignalExplanation.explanation}</p>
                  <p className="text-xs text-muted-foreground">
                    This explanation is computed from the latest plotted indicator values (strategy signal
                    logic). Execution controls like cooldown/gates can still affect fills.
                  </p>
                  {decisionSignalExplanation.checks.length > 0 && (
                    <div className="overflow-x-auto rounded-lg border border-border/70">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b border-border bg-secondary/20">
                            <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                              Rule Check
                            </th>
                            <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                              Result
                            </th>
                            <th className="px-3 py-2 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                              Details
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {decisionSignalExplanation.checks.map((check, idx) => (
                            <tr key={`${check.label}-${idx}`} className="border-b border-border/50 last:border-0">
                              <td className="px-3 py-2 text-xs text-foreground">{check.label}</td>
                              <td className="px-3 py-2 text-xs">
                                <span
                                  className={`inline-flex rounded-md px-2 py-0.5 font-semibold ${
                                    check.passed
                                      ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
                                      : "bg-muted text-muted-foreground"
                                  }`}
                                >
                                  {check.passed ? "TRUE" : "FALSE"}
                                </span>
                              </td>
                              <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{check.detail}</td>
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
        )}
      </Tabs>
    </div>
  )
}
