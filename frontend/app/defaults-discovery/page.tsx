"use client"

import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { BarChart3, Download, Loader2, Play, Save, Search, Settings2, Trash2 } from "lucide-react"

import { PlotlyChart } from "@/components/run/plotly-chart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  applyDefaultsRun,
  deleteDefaultsRun,
  getDefaultsRun,
  launchSmaDefaultsDiscovery,
  listDatasets,
  listDefaultsRuns,
  listMarketSymbols,
  type Dataset,
  type SmaDefaultsDiscoveryRun,
} from "@/lib/api"
import { HORIZON_OPTIONS, resolveHorizonPreset, type TradingHorizon } from "@/lib/horizon"

type BucketRange = { bucket_id: string; low: number; high: number }

const DEFAULT_BUCKETS: BucketRange[] = [
  { bucket_id: "B1", low: 3, high: 7 },
  { bucket_id: "B2", low: 8, high: 12 },
  { bucket_id: "B3", low: 13, high: 20 },
  { bucket_id: "B4", low: 21, high: 30 },
  { bucket_id: "B5", low: 31, high: 45 },
  { bucket_id: "B6", low: 46, high: 70 },
  { bucket_id: "B7", low: 71, high: 110 },
  { bucket_id: "B8", low: 111, high: 170 },
  { bucket_id: "B9", low: 171, high: 250 },
]

function validateBuckets(buckets: BucketRange[]): string | null {
  let prevHigh = 0
  for (const bucket of buckets) {
    if (!Number.isFinite(bucket.low) || !Number.isFinite(bucket.high)) return `${bucket.bucket_id}: bounds must be numeric`
    if (bucket.low <= 0 || bucket.high <= 0) return `${bucket.bucket_id}: bounds must be positive`
    if (bucket.low > bucket.high) return `${bucket.bucket_id}: low must be <= high`
    if (bucket.low <= prevHigh) return "Buckets must be increasing and non-overlapping"
    prevHigh = bucket.high
  }
  if (buckets.length !== 9) return "Exactly 9 buckets are required"
  return null
}

function csvFromRows(rows: Array<Record<string, unknown>>): string {
  if (!rows.length) return ""
  const headers = Array.from(new Set(rows.flatMap((r) => Object.keys(r))))
  const esc = (value: unknown) => {
    const raw = value === null || value === undefined ? "" : String(value)
    if (!raw.includes(",") && !raw.includes("\"") && !raw.includes("\n")) return raw
    return `"${raw.replaceAll("\"", "\"\"")}"`
  }
  const lines = [headers.join(",")]
  for (const row of rows) lines.push(headers.map((h) => esc(row[h])).join(","))
  return lines.join("\n")
}

function downloadFile(filename: string, body: string, mime: string) {
  const blob = new Blob([body], { type: mime })
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

type SortKey = "bucket_id" | "chosen_default_n" | "win_rate" | "stability_std" | "avg_score"
const ORDERED_HORIZONS: TradingHorizon[] = ["weekly", "monthly", "quarterly"]

function normalizeSymbol(raw: string): string {
  let symbol = String(raw ?? "").trim().toUpperCase()
  if (!symbol) return ""
  symbol = symbol.replace(/\s*\([^)]+\)\s*$/, "").trim()
  return symbol
}

function normalizeSymbols(raw: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const symbol = normalizeSymbol(item)
    if (!symbol || seen.has(symbol)) continue
    seen.add(symbol)
    out.push(symbol)
  }
  return out
}

function isPlaceholderSheetTicker(raw: string): boolean {
  const sym = normalizeSymbol(raw)
  if (!sym) return true
  if (sym === "UPLOAD" || sym === "DATASET") return true
  if (/^FEUIL(?:LE)?\d*$/.test(sym)) return true
  if (/^SHEET\d*$/.test(sym)) return true
  return false
}

function getDatasetSymbols(dataset: Dataset): string[] {
  const direct = Array.isArray(dataset.detected_symbols) ? dataset.detected_symbols : []
  const fromMeta =
    dataset.meta && typeof dataset.meta === "object" && !Array.isArray(dataset.meta)
      ? (dataset.meta as { detected_symbols?: unknown }).detected_symbols
      : undefined
  const fallback = Array.isArray(fromMeta) ? fromMeta.map((x) => String(x)) : []
  const source = direct.length > 0 ? direct : fallback
  return normalizeSymbols(source).filter((sym) => !isPlaceholderSheetTicker(sym))
}

function isRecentIsoDate(raw: string | null | undefined, maxMinutes: number): boolean {
  if (!raw) return false
  const ts = Date.parse(raw)
  if (!Number.isFinite(ts)) return false
  return Date.now() - ts <= maxMinutes * 60 * 1000
}

// ── Labelled field helper ──────────────────────────────────────────────────
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs font-medium">{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

export default function DefaultsDiscoveryPage() {
  // ── Data source ───────────────────────────────────────────────────────────
  const [ticker, setTicker] = useState("IAM")
  const [symbols, setSymbols] = useState<string[]>([])
  const [tickerSearch, setTickerSearch] = useState("")
  const [startDate, setStartDate] = useState("2015-01-01")
  const [endDate, setEndDate] = useState("")

  // ── Signal parameters (new) ────────────────────────────────────────────────
  const [buyThresholdPerc, setBuyThresholdPerc] = useState(0)
  const [sellThresholdPerc, setSellThresholdPerc] = useState(0)
  const [cooldownDays, setCooldownDays] = useState(0)
  const [minVolume, setMinVolume] = useState(0)

  // ── Cost model ────────────────────────────────────────────────────────────
  const [brokerageBps, setBrokerageBps] = useState(0)
  const [commBps, setCommBps] = useState(0)
  const [slippageBps, setSlippageBps] = useState(0)
  const [tvaRate, setTvaRate] = useState(0)
  const [useNetAfterCosts, setUseNetAfterCosts] = useState(false)

  // ── Score weights ─────────────────────────────────────────────────────────
  const [drawdownWeight, setDrawdownWeight] = useState(0.5)
  const [turnoverWeight, setTurnoverWeight] = useState(0.1)
  const [snapToNice, setSnapToNice] = useState(true)

  // ── Buckets ───────────────────────────────────────────────────────────────
  const [buckets, setBuckets] = useState<BucketRange[]>(DEFAULT_BUCKETS)

  // ── Walk-forward settings ─────────────────────────────────────────────────
  const [horizon, setHorizon] = useState<TradingHorizon>("monthly")
  const [trainWindow, setTrainWindow] = useState(504)
  const [stepSize, setStepSize] = useState(21)
  const [useTestWindow, setUseTestWindow] = useState(true)
  const [testWindow, setTestWindow] = useState(63)
  const [enforceHalfTrain, setEnforceHalfTrain] = useState(true)

  // ── Run state ─────────────────────────────────────────────────────────────
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [currentRun, setCurrentRun] = useState<SmaDefaultsDiscoveryRun | null>(null)
  const [resultsHorizon, setResultsHorizon] = useState<TradingHorizon>("monthly")
  const [recentRuns, setRecentRuns] = useState<SmaDefaultsDiscoveryRun[]>([])
  const [loadingRun, setLoadingRun] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [applying, setApplying] = useState(false)
  const [showQueuedRuns, setShowQueuedRuns] = useState(false)
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null)
  const [bulkDeleteMode, setBulkDeleteMode] = useState<"queued" | "past" | null>(null)

  // ── Table sort ────────────────────────────────────────────────────────────
  const [sortKey, setSortKey] = useState<SortKey>("bucket_id")
  const [sortAsc, setSortAsc] = useState(true)

  const bucketError = useMemo(() => validateBuckets(buckets), [buckets])
  const feasibleMaxN = useMemo(() => Math.floor(trainWindow / 2), [trainWindow])
  const horizonPreset = useMemo(() => resolveHorizonPreset(horizon), [horizon])

  // ── Load initial data ─────────────────────────────────────────────────────
  useEffect(() => {
    ;(async () => {
      try {
        const [marketSymbols, datasets, runs] = await Promise.all([
          listMarketSymbols({ timeframe: "1D" }).catch(() => []),
          listDatasets().catch(() => []),
          listDefaultsRuns({ limit: 20, strategy_name: "sma_price" }).catch(() => []),
        ])
        const symbolsOut = normalizeSymbols([
          ...marketSymbols.map((row) => row.symbol),
          ...datasets.flatMap(getDatasetSymbols),
        ]).sort((a, b) => a.localeCompare(b))
        setSymbols(symbolsOut)
        setTicker((prev) => {
          const normalizedPrev = normalizeSymbol(prev)
          if (normalizedPrev && symbolsOut.includes(normalizedPrev)) return normalizedPrev
          return symbolsOut[0] ?? normalizedPrev ?? "IAM"
        })
        setRecentRuns(runs)
      } catch (err) {
        toast.error(`Failed to load data: ${err instanceof Error ? err.message : "Unknown error"}`)
      }
    })()
  }, [])

  // ── Background refresh of run list ────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    const timer = setInterval(async () => {
      try {
        const runs = await listDefaultsRuns({ limit: 20, strategy_name: "sma_price" })
        if (!cancelled) setRecentRuns(runs)
      } catch { /* best-effort */ }
    }, 5000)
    return () => { cancelled = true; clearInterval(timer) }
  }, [])

  // ── Poll active run ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!currentRunId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const poll = async () => {
      try {
        const run = await getDefaultsRun(currentRunId)
        if (cancelled) return
        setCurrentRun(run)
        if (run.status === "queued" || run.status === "running") {
          timer = setTimeout(poll, 2000)
          return
        }
        const runs = await listDefaultsRuns({ limit: 20, strategy_name: "sma_price" }).catch(() => [])
        if (!cancelled) setRecentRuns(runs)
      } catch (err) {
        if (!cancelled) toast.error(`Polling failed: ${err instanceof Error ? err.message : "Unknown error"}`)
      }
    }
    poll()
    return () => { cancelled = true; if (timer) clearTimeout(timer) }
  }, [currentRunId])

  // ── Sync horizon preset to walk-forward fields ────────────────────────────
  useEffect(() => {
    const preset = resolveHorizonPreset(horizon)
    setTrainWindow(preset.trainWindow)
    setTestWindow(preset.testWindow)
    setStepSize(preset.stepSize)
    setUseTestWindow(preset.useTestWindow)
  }, [horizon])

  // ── Results derived state ─────────────────────────────────────────────────
  const resultsJson = useMemo(() => {
    const raw = currentRun?.results_json
    return raw && typeof raw === "object" ? raw : null
  }, [currentRun?.results_json])

  const horizonResultsMap = useMemo(() => {
    const out: Partial<Record<TradingHorizon, Record<string, unknown>>> = {}
    const nestedRaw = (resultsJson?.horizons ?? resultsJson?.results_by_horizon) as unknown
    if (nestedRaw && typeof nestedRaw === "object" && !Array.isArray(nestedRaw)) {
      const nested = nestedRaw as Record<string, unknown>
      for (const [rawHorizon, payload] of Object.entries(nested)) {
        const hz = resolveHorizonPreset(rawHorizon).value
        if (payload && typeof payload === "object" && !Array.isArray(payload)) {
          out[hz] = payload as Record<string, unknown>
        }
      }
    }
    if (Object.keys(out).length === 0 && resultsJson) {
      const fallbackMeta = resultsJson.meta
      const fallbackHorizon =
        fallbackMeta && typeof fallbackMeta === "object" && !Array.isArray(fallbackMeta)
          ? String((fallbackMeta as Record<string, unknown>).horizon ?? "monthly").trim().toLowerCase()
          : "monthly"
      const token = resolveHorizonPreset(fallbackHorizon).value
      out[token] = resultsJson as Record<string, unknown>
    }
    return out
  }, [resultsJson])

  const availableResultHorizons = useMemo(
    () => ORDERED_HORIZONS.filter((h) => Boolean(horizonResultsMap[h])),
    [horizonResultsMap]
  )

  useEffect(() => {
    if (!availableResultHorizons.length) return
    const rootMeta =
      resultsJson?.meta && typeof resultsJson.meta === "object" && !Array.isArray(resultsJson.meta)
        ? (resultsJson.meta as Record<string, unknown>)
        : {}
    const activeRaw = String(
      resultsJson?.active_horizon ?? rootMeta.active_horizon ?? rootMeta.horizon ?? availableResultHorizons[0]
    ).trim().toLowerCase()
    const active = ORDERED_HORIZONS.includes(activeRaw as TradingHorizon) ? (activeRaw as TradingHorizon) : availableResultHorizons[0]
    setResultsHorizon((prev) => (availableResultHorizons.includes(prev) ? prev : active))
  }, [availableResultHorizons, resultsJson])

  const activeResultsJson = useMemo(() => {
    if (!resultsJson) return null
    if (horizonResultsMap[resultsHorizon]) return horizonResultsMap[resultsHorizon] ?? null
    const first = availableResultHorizons[0]
    return first ? (horizonResultsMap[first] ?? null) : resultsJson
  }, [availableResultHorizons, horizonResultsMap, resultsHorizon, resultsJson])

  const resultsMeta = useMemo(() => {
    const raw = activeResultsJson?.meta
    return raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {}
  }, [activeResultsJson])

  const defaults = useMemo(() => {
    const values = Array.isArray(activeResultsJson?.defaults) ? activeResultsJson.defaults : []
    return values.map((v) => Number(v)).filter((v) => Number.isFinite(v))
  }, [activeResultsJson])

  const bucketReports = useMemo(() => {
    const rows = Array.isArray(activeResultsJson?.bucket_reports) ? activeResultsJson.bucket_reports : []
    return rows.filter((r): r is Record<string, unknown> => Boolean(r && typeof r === "object"))
  }, [activeResultsJson])

  const sortedBucketReports = useMemo(() => {
    const rows = [...bucketReports]
    rows.sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey]
      const aNum = typeof av === "number" ? av : Number(av)
      const bNum = typeof bv === "number" ? bv : Number(bv)
      if (Number.isFinite(aNum) && Number.isFinite(bNum)) return sortAsc ? aNum - bNum : bNum - aNum
      return sortAsc ? String(av ?? "").localeCompare(String(bv ?? "")) : String(bv ?? "").localeCompare(String(av ?? ""))
    })
    return rows
  }, [bucketReports, sortAsc, sortKey])

  const filteredRecentRuns = useMemo(
    () => (showQueuedRuns ? recentRuns : recentRuns.filter((r) => r.status !== "queued")),
    [recentRuns, showQueuedRuns]
  )
  const hiddenQueuedCount = useMemo(() => (showQueuedRuns ? 0 : recentRuns.filter((r) => r.status === "queued").length), [recentRuns, showQueuedRuns])
  const queuedRunsCount = useMemo(() => recentRuns.filter((r) => r.status === "queued").length, [recentRuns])
  const pastRunsCount = useMemo(() => recentRuns.filter((r) => r.status !== "queued" && r.status !== "running").length, [recentRuns])

  const winners = useMemo(() => {
    const rows = Array.isArray(activeResultsJson?.walk_forward_winners) ? activeResultsJson.walk_forward_winners : []
    return rows.filter((r): r is Record<string, unknown> => Boolean(r && typeof r === "object"))
  }, [activeResultsJson])

  // ── Plotly figures ────────────────────────────────────────────────────────
  const histogramFigure = useMemo(() => {
    if (!winners.length) return undefined
    const byBucket = new Map<string, number[]>()
    for (const row of winners) {
      const bucket = String(row.bucket_id ?? "")
      const n = Number(row.best_n)
      if (!bucket || !Number.isFinite(n)) continue
      const cur = byBucket.get(bucket) ?? []
      cur.push(n)
      byBucket.set(bucket, cur)
    }
    return {
      data: Array.from(byBucket.entries()).map(([bucketId, xs]) => ({
        type: "histogram", x: xs, name: bucketId, opacity: 0.65,
      })),
      layout: {
        title: "Best n Distribution by Bucket", barmode: "overlay",
        xaxis: { title: "SMA window (n)" }, yaxis: { title: "Count" },
      },
    }
  }, [winners])

  const heatmapFigure = useMemo(() => {
    const matrix = Array.isArray(activeResultsJson?.selection_matrix) ? activeResultsJson.selection_matrix : []
    if (!matrix.length) return undefined
    const bucketIds = buckets.map((b) => b.bucket_id)
    const z = bucketIds.map((bucketId) =>
      matrix.map((entry) => {
        const sel = entry && typeof entry === "object" ? (entry as Record<string, unknown>).selections : null
        const value = sel && typeof sel === "object" ? (sel as Record<string, unknown>)[bucketId] : null
        const out = Number(value)
        return Number.isFinite(out) ? out : null
      })
    )
    const x = matrix.map((entry) => Number((entry as Record<string, unknown>).window_index ?? 0))
    return {
      data: [{ type: "heatmap", x, y: bucketIds, z, colorscale: "Blues" }],
      layout: {
        title: "Selected n per Walk-Forward Window",
        xaxis: { title: "Window index" }, yaxis: { title: "Bucket" },
      },
    }
  }, [activeResultsJson?.selection_matrix, buckets])

  const stabilityFigure = useMemo(() => {
    if (!bucketReports.length) return undefined
    const labels = bucketReports.map((r) => String(r.bucket_id ?? ""))
    return {
      data: [
        { type: "bar", x: labels, y: bucketReports.map((r) => Number(r.win_rate ?? 0)), name: "Win rate", yaxis: "y" },
        { type: "scatter", mode: "lines+markers", x: labels, y: bucketReports.map((r) => Number(r.stability_std ?? 0)), name: "Stability std", yaxis: "y2" },
      ],
      layout: {
        title: "Win Rate & Stability by Bucket",
        xaxis: { title: "Bucket" },
        yaxis: { title: "Win rate" },
        yaxis2: { title: "Std dev", overlaying: "y", side: "right" },
      },
    }
  }, [bucketReports])

  // ── Handlers ──────────────────────────────────────────────────────────────
  async function handleRunDiscovery() {
    if (bucketError) { toast.error(bucketError); return }
    const normalizedTicker = normalizeSymbol(ticker)
    if (!normalizedTicker) { toast.error("Ticker is required"); return }

    const activeRun = recentRuns.find(
      (r) => (r.status === "queued" || r.status === "running") && isRecentIsoDate(r.created_at, 120)
    )
    if (activeRun) {
      setCurrentRunId(activeRun.run_id)
      setCurrentRun(activeRun)
      toast.info("A discovery run is already active.")
      return
    }

    setSubmitting(true)
    try {
      const launched = await launchSmaDefaultsDiscovery({
        strategy_name: "sma_price",
        ticker: normalizedTicker,
        timeframe: "1D",
        start_date: startDate || null,
        end_date: endDate || null,
        horizon,
        compute_all_horizons: true,
        walk_forward: {
          train_window: Number(trainWindow),
          step_size: Number(stepSize),
          use_test_window: Boolean(useTestWindow),
          test_window: Number(testWindow),
          enforce_feasible_train_half: Boolean(enforceHalfTrain),
        },
        buckets: buckets.map((b) => ({ bucket_id: b.bucket_id, low: Number(b.low), high: Number(b.high) })),
        score_settings: {
          drawdown_weight: Number(drawdownWeight),
          turnover_weight: Number(turnoverWeight),
          mode_threshold: 0.20,
        },
        signal_params: {
          buy_threshold_perc: Number(buyThresholdPerc),
          sell_threshold_perc: Number(sellThresholdPerc),
          cooldown_days: Number(cooldownDays),
          min_volume: Number(minVolume),
        },
        cost_model: {
          brokerage_bps: Number(brokerageBps),
          comm_bourse_bps: Number(commBps),
          slippage_bps: Number(slippageBps),
          tva_rate: Number(tvaRate) / 100,
        },
        use_net_after_costs: Boolean(useNetAfterCosts),
        snap_to_nice: Boolean(snapToNice),
        allow_short: false,
        signal_mode: "level",
      })
      setCurrentRunId(launched.run_id)
      setCurrentRun(null)
      toast.success(`Discovery started: ${launched.run_id.slice(0, 8)}…`)
    } catch (err) {
      toast.error(`Launch failed: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleOpenRun(runId: string) {
    setLoadingRun(true)
    try {
      const run = await getDefaultsRun(runId)
      setCurrentRunId(run.run_id)
      setCurrentRun(run)
    } catch (err) {
      toast.error(`Failed to open run: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setLoadingRun(false)
    }
  }

  async function handleDeleteRun(runId: string) {
    if (!window.confirm(`Delete run ${runId.slice(0, 8)}…?`)) return
    setDeletingRunId(runId)
    try {
      await deleteDefaultsRun(runId)
      if (currentRunId === runId) { setCurrentRunId(null); setCurrentRun(null) }
      setRecentRuns((prev) => prev.filter((r) => r.run_id !== runId))
      const runs = await listDefaultsRuns({ limit: 20, strategy_name: "sma_price" }).catch(() => [])
      setRecentRuns(runs)
      toast.success(`Run ${runId.slice(0, 8)} deleted`)
    } catch (err) {
      toast.error(`Delete failed: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setDeletingRunId(null)
    }
  }

  async function handleBulkDelete(mode: "queued" | "past") {
    setBulkDeleteMode(mode)
    try {
      const runs = await listDefaultsRuns({ limit: 200, strategy_name: "sma_price" })
      const targets = runs.filter((r) =>
        mode === "queued" ? r.status === "queued" : r.status !== "queued" && r.status !== "running"
      )
      if (!targets.length) { toast.message(`No ${mode} runs to delete`); return }
      if (!window.confirm(`Delete ${targets.length} ${mode} run(s)?`)) return

      const results = await Promise.allSettled(targets.map((r) => deleteDefaultsRun(r.run_id)))
      const deletedIds = results.map((res, idx) => (res.status === "fulfilled" ? targets[idx]?.run_id ?? null : null)).filter((id): id is string => Boolean(id))
      const failed = results.length - deletedIds.length

      if (currentRunId && deletedIds.includes(currentRunId)) { setCurrentRunId(null); setCurrentRun(null) }
      setRecentRuns((prev) => prev.filter((r) => !deletedIds.includes(r.run_id)))
      const refreshed = await listDefaultsRuns({ limit: 20, strategy_name: "sma_price" }).catch(() => [])
      setRecentRuns(refreshed)

      if (failed > 0) toast.warning(`${deletedIds.length} deleted, ${failed} failed`)
      else toast.success(`${deletedIds.length} run(s) deleted`)
    } catch (err) {
      toast.error(`Bulk delete failed: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setBulkDeleteMode(null)
    }
  }

  async function handleApplyDefaults() {
    if (!currentRunId) return
    setApplying(true)
    try {
      await applyDefaultsRun(currentRunId, { horizon: resultsHorizon })
      toast.success("SMA defaults saved")
    } catch (err) {
      toast.error(`Apply failed: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setApplying(false)
    }
  }

  function toggleSort(nextKey: SortKey) {
    if (sortKey === nextKey) { setSortAsc((v) => !v); return }
    setSortKey(nextKey); setSortAsc(true)
  }

  function exportJson() {
    if (!resultsJson) return
    downloadFile(`sma-defaults-${currentRunId ?? "run"}.json`, JSON.stringify(resultsJson, null, 2), "application/json")
  }

  function exportCsvs() {
    if (!activeResultsJson) return
    const hz = resultsHorizon || "medium"
    downloadFile(`sma-defaults-${currentRunId ?? "run"}-${hz}-defaults.csv`, csvFromRows(defaults.map((v, i) => ({ bucket_id: `B${i + 1}`, default_n: v }))), "text/csv")
    downloadFile(`sma-defaults-${currentRunId ?? "run"}-${hz}-buckets.csv`, csvFromRows(bucketReports as Array<Record<string, unknown>>), "text/csv")
    downloadFile(`sma-defaults-${currentRunId ?? "run"}-${hz}-winners.csv`, csvFromRows(winners as Array<Record<string, unknown>>), "text/csv")
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold tracking-tight">SMA Defaults Discovery</h1>
        <p className="text-sm text-muted-foreground">
          Grid-search optimal SMA windows per bucket using configurable signal parameters and costs.
        </p>
      </div>

      <div className="grid gap-6 xl:grid-cols-[400px_minmax(0,1fr)]">
        {/* ── LEFT: Configuration panel ──────────────────────────────────── */}
        <div className="space-y-4">

          {/* Data Source */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Data Source</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2 rounded-xl border border-border p-3">
                <div className="flex items-center justify-between gap-2">
                  <Label className="text-sm font-semibold">Ticker</Label>
                  {ticker && (
                    <span className="rounded-full bg-primary/10 border border-primary/30 px-2.5 py-0.5 font-mono text-xs font-semibold text-primary">
                      {ticker}
                    </span>
                  )}
                </div>
                {symbols.length > 0 ? (
                  <>
                    <div className="relative">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                      <input
                        type="text"
                        placeholder="Filter tickers…"
                        value={tickerSearch}
                        onChange={(e) => setTickerSearch(e.target.value)}
                        className="w-full rounded-md border border-border bg-background py-1.5 pl-8 pr-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                      />
                    </div>
                    <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto pr-0.5">
                      {symbols
                        .filter((s) => !tickerSearch || s.toUpperCase().includes(tickerSearch.toUpperCase()))
                        .map((symbol) => (
                          <button
                            key={symbol}
                            type="button"
                            onClick={() => setTicker(symbol)}
                            className={
                              ticker === symbol
                                ? "rounded-md border border-primary bg-primary/10 px-2.5 py-1 font-mono text-xs font-semibold text-primary"
                                : "rounded-md border border-border px-2.5 py-1 font-mono text-xs text-foreground hover:border-primary/40 hover:bg-secondary/50"
                            }
                          >
                            {symbol}
                          </button>
                        ))}
                    </div>
                  </>
                ) : (
                  <input
                    type="text"
                    placeholder="e.g. IAM"
                    value={ticker}
                    onChange={(e) => setTicker(e.target.value.toUpperCase())}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 font-mono text-sm uppercase placeholder:normal-case placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Start Date">
                  <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                </Field>
                <Field label="End Date">
                  <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
                </Field>
              </div>
            </CardContent>
          </Card>

          {/* Signal Parameters */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Signal Parameters</CardTitle>
              <CardDescription>How buy/sell decisions are made during the grid search.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Buy Threshold %" hint="Buy when price is this % above SMA">
                  <Input
                    type="number"
                    step="0.1"
                    min={0}
                    value={buyThresholdPerc}
                    onChange={(e) => setBuyThresholdPerc(Number(e.target.value))}
                  />
                </Field>
                <Field label="Sell Threshold %" hint="Sell when price is this % below SMA">
                  <Input
                    type="number"
                    step="0.1"
                    min={0}
                    value={sellThresholdPerc}
                    onChange={(e) => setSellThresholdPerc(Number(e.target.value))}
                  />
                </Field>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Cooldown (bars)" hint="Min bars between position changes">
                  <Input
                    type="number"
                    min={0}
                    value={cooldownDays}
                    onChange={(e) => setCooldownDays(Number(e.target.value))}
                  />
                </Field>
                <Field label="Min Volume" hint="Skip trade if volume below this">
                  <Input
                    type="number"
                    min={0}
                    value={minVolume}
                    onChange={(e) => setMinVolume(Number(e.target.value))}
                  />
                </Field>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Zero thresholds = classic SMA price-level strategy (price {">"}= SMA → long).
              </p>
            </CardContent>
          </Card>

          {/* Cost Model */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Cost Model</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Brokerage (bps)">
                  <Input type="number" min={0} step={0.1} value={brokerageBps} onChange={(e) => setBrokerageBps(Number(e.target.value))} />
                </Field>
                <Field label="Commission (bps)">
                  <Input type="number" min={0} step={0.1} value={commBps} onChange={(e) => setCommBps(Number(e.target.value))} />
                </Field>
                <Field label="Slippage (bps)">
                  <Input type="number" min={0} step={0.1} value={slippageBps} onChange={(e) => setSlippageBps(Number(e.target.value))} />
                </Field>
                <Field label="VAT (%)">
                  <Input type="number" min={0} step={0.1} value={tvaRate} onChange={(e) => setTvaRate(Number(e.target.value))} />
                </Field>
              </div>
              <label className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2 text-sm">
                <span>Score on net-after-costs returns</span>
                <Switch checked={useNetAfterCosts} onCheckedChange={setUseNetAfterCosts} />
              </label>
            </CardContent>
          </Card>

          {/* Score Weights */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Score Weights</CardTitle>
              <CardDescription>score = Sharpe − w_dd·MaxDD − w_to·Turnover</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="Drawdown Weight">
                  <Input type="number" step="0.05" min={0} value={drawdownWeight} onChange={(e) => setDrawdownWeight(Number(e.target.value))} />
                </Field>
                <Field label="Turnover Weight">
                  <Input type="number" step="0.05" min={0} value={turnoverWeight} onChange={(e) => setTurnoverWeight(Number(e.target.value))} />
                </Field>
              </div>
              <label className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2 text-sm">
                <span>Snap results to nice numbers</span>
                <Switch checked={snapToNice} onCheckedChange={setSnapToNice} />
              </label>
            </CardContent>
          </Card>

          {/* Advanced: Buckets + Walk-Forward */}
          <Accordion type="multiple">
            <AccordionItem value="buckets" className="rounded-lg border border-border px-3">
              <AccordionTrigger className="py-3 text-sm font-semibold">
                <span className="inline-flex items-center gap-2">
                  <Settings2 className="h-4 w-4" />
                  SMA Bucket Ranges
                </span>
              </AccordionTrigger>
              <AccordionContent className="space-y-2 pb-3">
                <p className="text-[11px] text-muted-foreground">
                  Each bucket defines a range of SMA windows to grid-search. Must be strictly increasing.
                </p>
                <div className="grid grid-cols-[48px_1fr_1fr] gap-2 text-[11px] font-semibold text-muted-foreground px-1">
                  <span>ID</span><span>Low</span><span>High</span>
                </div>
                {buckets.map((bucket, idx) => (
                  <div key={bucket.bucket_id} className="grid grid-cols-[48px_1fr_1fr] gap-2">
                    <div className="rounded-md border border-border bg-secondary px-2 py-2 text-xs font-semibold text-center">
                      {bucket.bucket_id}
                    </div>
                    <Input
                      type="number"
                      value={bucket.low}
                      min={1}
                      onChange={(e) => {
                        const next = [...buckets]
                        next[idx] = { ...next[idx], low: Number(e.target.value) }
                        setBuckets(next)
                      }}
                    />
                    <Input
                      type="number"
                      value={bucket.high}
                      min={1}
                      onChange={(e) => {
                        const next = [...buckets]
                        next[idx] = { ...next[idx], high: Number(e.target.value) }
                        setBuckets(next)
                      }}
                    />
                  </div>
                ))}
                {bucketError && <p className="text-xs font-medium text-destructive">{bucketError}</p>}
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="walkforward" className="rounded-lg border border-border px-3 mt-2">
              <AccordionTrigger className="py-3 text-sm font-semibold">
                <span className="inline-flex items-center gap-2">
                  <Settings2 className="h-4 w-4" />
                  Walk-Forward Settings
                </span>
              </AccordionTrigger>
              <AccordionContent className="space-y-3 pb-3">
                <Field label="Horizon">
                  <select
                    value={horizon}
                    onChange={(e) => setHorizon(e.target.value as TradingHorizon)}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
                  >
                    {HORIZON_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                  <p className="text-[11px] text-muted-foreground mt-1">
                    Preset: train {horizonPreset.trainWindow}d · step {horizonPreset.stepSize}d · test {horizonPreset.testWindow}d · feasibility cap {feasibleMaxN}
                  </p>
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Train Window (days)">
                    <Input type="number" min={20} value={trainWindow} onChange={(e) => setTrainWindow(Number(e.target.value))} />
                  </Field>
                  <Field label="Step Size (days)">
                    <Input type="number" min={1} value={stepSize} onChange={(e) => setStepSize(Number(e.target.value))} />
                  </Field>
                </div>
                <label className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2 text-sm">
                  <span>Out-of-sample test window</span>
                  <Switch checked={useTestWindow} onCheckedChange={setUseTestWindow} />
                </label>
                {useTestWindow && (
                  <Field label="Test Window (days)">
                    <Input type="number" min={1} value={testWindow} onChange={(e) => setTestWindow(Number(e.target.value))} />
                  </Field>
                )}
                <label className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2 text-sm">
                  <span>Enforce n ≤ floor(train/2)</span>
                  <Switch checked={enforceHalfTrain} onCheckedChange={setEnforceHalfTrain} />
                </label>
              </AccordionContent>
            </AccordionItem>
          </Accordion>

          <Button
            className="w-full gap-2"
            onClick={handleRunDiscovery}
            disabled={submitting || Boolean(bucketError)}
          >
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Run Grid Search
          </Button>

          {/* Recent Runs */}
          <Card>
            <CardHeader className="space-y-3 pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Recent Runs</CardTitle>
                {hiddenQueuedCount > 0 && <Badge variant="outline">{hiddenQueuedCount} queued hidden</Badge>}
              </div>
              <label className="flex items-center justify-between rounded-lg border border-border/70 px-3 py-2 text-sm">
                <span>Show queued</span>
                <Switch checked={showQueuedRuns} onCheckedChange={setShowQueuedRuns} />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <Button type="button" variant="outline" size="sm" className="gap-1.5"
                  onClick={() => handleBulkDelete("queued")}
                  disabled={Boolean(bulkDeleteMode) || Boolean(deletingRunId) || queuedRunsCount === 0}
                >
                  {bulkDeleteMode === "queued" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  Clear queued ({queuedRunsCount})
                </Button>
                <Button type="button" variant="outline" size="sm" className="gap-1.5"
                  onClick={() => handleBulkDelete("past")}
                  disabled={Boolean(bulkDeleteMode) || Boolean(deletingRunId) || pastRunsCount === 0}
                >
                  {bulkDeleteMode === "past" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  Clear past ({pastRunsCount})
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              {filteredRecentRuns.map((run) => (
                <div key={run.run_id} className="flex items-center gap-2">
                  <button
                    className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-2 text-left hover:bg-secondary/60"
                    onClick={() => handleOpenRun(run.run_id)}
                    disabled={loadingRun || Boolean(bulkDeleteMode) || deletingRunId === run.run_id}
                  >
                    <div>
                      <p className="font-mono text-xs">{run.run_id.slice(0, 12)}…</p>
                      <p className="text-xs text-muted-foreground">{run.ticker ?? "--"} · {run.created_at.slice(0, 10)}</p>
                    </div>
                    <Badge variant={run.status === "succeeded" ? "secondary" : "outline"}>{run.status}</Badge>
                  </button>
                  <Button
                    type="button" variant="ghost" size="icon" className="shrink-0"
                    onClick={() => void handleDeleteRun(run.run_id)}
                    disabled={Boolean(bulkDeleteMode) || loadingRun || deletingRunId === run.run_id}
                  >
                    {deletingRunId === run.run_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                  </Button>
                </div>
              ))}
              {!filteredRecentRuns.length && (
                <p className="text-sm text-muted-foreground">
                  {hiddenQueuedCount > 0 ? "Queued runs hidden — toggle the switch above." : "No discovery runs yet."}
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ── RIGHT: Results panel ────────────────────────────────────────── */}
        <div className="space-y-4">

          {/* Progress */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center justify-between text-base">
                <span>Run Status</span>
                <Badge variant="outline">{currentRun?.status ?? "idle"}</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <Progress value={Number(currentRun?.progress_pct ?? 0)} />
              <div className="grid gap-1.5 text-sm text-muted-foreground sm:grid-cols-2">
                <p>Stage: <span className="font-medium text-foreground">{currentRun?.progress_stage ?? "--"}</span></p>
                <p>Progress: <span className="font-medium text-foreground">{Math.round(Number(currentRun?.progress_pct ?? 0))}%</span></p>
                <p className="sm:col-span-2">Message: <span className="font-medium text-foreground">{currentRun?.progress_message ?? "--"}</span></p>
              </div>
              {currentRun?.error_message && (
                <pre className="max-h-40 overflow-auto rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                  {currentRun.error_message}
                </pre>
              )}
            </CardContent>
          </Card>

          {/* Defaults summary */}
          {defaults.length > 0 && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Best SMA Windows per Bucket</CardTitle>
                <CardDescription>Strictly increasing defaults from fastest to slowest moving average.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Horizon switcher */}
                {availableResultHorizons.length > 1 && (
                  <div className="flex flex-wrap gap-2">
                    {availableResultHorizons.map((hz) => {
                      const preset = resolveHorizonPreset(hz)
                      return (
                        <Button
                          key={hz}
                          type="button"
                          size="sm"
                          variant={resultsHorizon === hz ? "default" : "outline"}
                          onClick={() => setResultsHorizon(hz)}
                        >
                          {preset.label}
                        </Button>
                      )
                    })}
                  </div>
                )}

                <div className="flex flex-wrap gap-1.5">
                  <Badge variant="outline" className="text-xs">
                    {String(resultsMeta.horizon_label ?? resultsMeta.horizon ?? resolveHorizonPreset(resultsHorizon).label)}
                  </Badge>
                  <Badge variant="outline" className="text-xs">
                    Train {Number(resultsMeta.train_window ?? trainWindow)}d
                  </Badge>
                  {resultsMeta.buy_threshold_perc !== undefined && Number(resultsMeta.buy_threshold_perc) > 0 && (
                    <Badge variant="outline" className="text-xs">Buy +{Number(resultsMeta.buy_threshold_perc)}%</Badge>
                  )}
                  {resultsMeta.sell_threshold_perc !== undefined && Number(resultsMeta.sell_threshold_perc) > 0 && (
                    <Badge variant="outline" className="text-xs">Sell -{Number(resultsMeta.sell_threshold_perc)}%</Badge>
                  )}
                  {resultsMeta.cooldown_days !== undefined && Number(resultsMeta.cooldown_days) > 0 && (
                    <Badge variant="outline" className="text-xs">Cooldown {Number(resultsMeta.cooldown_days)}d</Badge>
                  )}
                </div>

                <div className="flex flex-wrap gap-2">
                  {defaults.map((value, i) => (
                    <div key={`${value}-${i}`} className="flex flex-col items-center rounded-lg border border-border px-3 py-2 min-w-[56px]">
                      <span className="text-[10px] text-muted-foreground">B{i + 1}</span>
                      <span className="text-lg font-bold">{value}</span>
                    </div>
                  ))}
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" className="gap-1.5" onClick={exportJson}>
                    <Download className="h-3.5 w-3.5" />Export JSON
                  </Button>
                  <Button variant="outline" size="sm" className="gap-1.5" onClick={exportCsvs}>
                    <Download className="h-3.5 w-3.5" />Export CSV
                  </Button>
                  <Button size="sm" className="gap-1.5" onClick={handleApplyDefaults} disabled={applying || !currentRunId}>
                    {applying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                    Apply as SMA Defaults
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Bucket Summary Table */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Bucket Summary</CardTitle>
              <CardDescription>Click column headers to sort.</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="cursor-pointer" onClick={() => toggleSort("bucket_id")}>Bucket</TableHead>
                    <TableHead className="cursor-pointer text-right" onClick={() => toggleSort("chosen_default_n")}>Best n</TableHead>
                    <TableHead className="cursor-pointer text-right" onClick={() => toggleSort("win_rate")}>Win Rate</TableHead>
                    <TableHead className="cursor-pointer text-right" onClick={() => toggleSort("stability_std")}>Stability</TableHead>
                    <TableHead className="cursor-pointer text-right" onClick={() => toggleSort("avg_score")}>Avg Score</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedBucketReports.map((row) => (
                    <TableRow key={String(row.bucket_id)}>
                      <TableCell className="font-medium">
                        {String(row.bucket_id)} <span className="text-muted-foreground text-xs">({String(row.bucket_label ?? "")})</span>
                      </TableCell>
                      <TableCell className="text-right font-mono font-semibold">{Number(row.chosen_default_n ?? 0)}</TableCell>
                      <TableCell className="text-right">{(Number(row.win_rate ?? 0) * 100).toFixed(1)}%</TableCell>
                      <TableCell className="text-right">{Number(row.stability_std ?? 0).toFixed(3)}</TableCell>
                      <TableCell className="text-right">{Number(row.avg_score ?? 0).toFixed(3)}</TableCell>
                    </TableRow>
                  ))}
                  {!sortedBucketReports.length && (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground py-6">
                        No results yet. Run a grid search to see results.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Charts */}
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Best n Distribution</CardTitle>
              </CardHeader>
              <CardContent>
                {histogramFigure
                  ? <PlotlyChart figure={histogramFigure as any} />
                  : <p className="text-sm text-muted-foreground py-8 text-center">Run discovery to see chart.</p>
                }
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Selection Heatmap</CardTitle>
              </CardHeader>
              <CardContent>
                {heatmapFigure
                  ? <PlotlyChart figure={heatmapFigure as any} />
                  : <p className="text-sm text-muted-foreground py-8 text-center">Run discovery to see chart.</p>
                }
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm inline-flex items-center gap-2">
                <BarChart3 className="h-4 w-4" />
                Win Rate &amp; Stability
              </CardTitle>
            </CardHeader>
            <CardContent>
              {stabilityFigure
                ? <PlotlyChart figure={stabilityFigure as any} />
                : <p className="text-sm text-muted-foreground py-8 text-center">Run discovery to see chart.</p>
              }
            </CardContent>
          </Card>

          {/* Warnings */}
          {!!(activeResultsJson && Array.isArray(activeResultsJson.warnings) && (activeResultsJson.warnings as unknown[]).length) && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Warnings</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1">
                {(activeResultsJson.warnings as unknown[]).map((w, i) => (
                  <p key={i} className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-900">
                    {String(w)}
                  </p>
                ))}
              </CardContent>
            </Card>
          )}

          {/* Separator */}
          {!currentRun && (
            <div className="flex flex-col items-center gap-2 py-12 text-center text-muted-foreground">
              <Play className="h-8 w-8 opacity-20" />
              <p className="text-sm">Configure parameters on the left and run the grid search.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
