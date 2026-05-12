"use client"

import Link from "next/link"
import { Suspense, useEffect, useMemo, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { AlertTriangle, BookOpen, MoreHorizontal, Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { RetractableSavedSidebar } from "@/components/layout/retractable-saved-sidebar"
import { useStrategies, useStrategy, useStrategyBacktestRun, useStrategyBacktestRuns, useStrategyBacktestStockDetail } from "@/hooks/use-api"
import {
  cancelStrategyBacktestRun,
  createStrategyBacktestRun,
  deleteStrategyBacktestRun,
  fetchStrategyBacktest,
  type FamilyHistoryMode,
  type PlotlyFigure,
  type StrategyBacktestMetricRow,
  type StrategyBacktestResponse,
  renameStrategyBacktestRun,
} from "@/lib/api"
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from "@/lib/format"

const DEFAULT_START_DATE = "2020-01-01"

function todayIso() {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function asFigure(value: unknown): PlotlyFigure | null {
  if (!value || typeof value !== "object") return null
  const record = value as Record<string, unknown>
  if (!Array.isArray(record.data) || typeof record.layout !== "object") return null
  return {
    data: record.data as Array<Record<string, unknown>>,
    layout: record.layout as Record<string, unknown>,
    frames: Array.isArray(record.frames) ? (record.frames as Array<Record<string, unknown>>) : undefined,
  }
}

function hasWfoValues(value: unknown): boolean {
  if (!value || typeof value !== "object") return false
  if (Array.isArray(value)) return value.some(hasWfoValues)
  const record = value as Record<string, unknown>
  if (String(record.mode ?? "").toLowerCase() === "wfo") return true
  return Object.values(record).some(hasWfoValues)
}

function renderMetric(label: string, value: unknown) {
  const numeric = toNumber(value)
  if (numeric == null) return "--"
  const key = label.toLowerCase()
  if (key.includes("return") || key.includes("drawdown") || key.includes("win")) return formatPercent(numeric)
  if (key.includes("pnl") || key.includes("capital")) return formatCurrency(numeric)
  return formatNumber(numeric, 2)
}

function metricRowsFromValue(value: unknown): StrategyBacktestMetricRow[] {
  if (Array.isArray(value)) return value as StrategyBacktestMetricRow[]
  if (!isRecord(value)) return []
  return Object.entries(value).map(([metric, raw]) => ({ metric, value: raw }))
}

function sideTone(value: unknown) {
  const side = String(value ?? "").toUpperCase()
  if (side === "BUY") return "text-emerald-600"
  if (side === "SELL") return "text-red-600"
  return "text-muted-foreground"
}

function reasonLabel(value: unknown) {
  const reason = String(value ?? "").trim()
  if (!reason) return "--"
  return reason.replace(/_/g, " ")
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function variableLabel(value: unknown) {
  const key = String(value ?? "")
  if (key === "trend_score") return "Trend"
  if (key === "momentum_score") return "Momentum"
  if (key === "oscillation_score") return "Oscillation"
  if (key === "volume_score") return "Volume"
  if (key === "consensus_score") return "Consensus"
  return key || "--"
}

function formatRuleCondition(condition: unknown) {
  if (!isRecord(condition)) return "--"
  const threshold = isRecord(condition.threshold) ? toNumber(condition.threshold.value) : toNumber(condition.threshold)
  return `${variableLabel(condition.variable)} ${String(condition.operator ?? ">=")} ${formatNumber(threshold, 2)}`
}

function formatRule(rule: unknown) {
  if (!isRecord(rule)) return "--"
  const option = String(rule.config_option ?? "").trim().toUpperCase()
  const label = String(rule.label ?? "").trim()
  const conditions = Array.isArray(rule.conditions) ? rule.conditions.map(formatRuleCondition).filter(Boolean) : []
  const ruleName = [option, label].filter(Boolean).join(" - ") || "Rule"
  return conditions.length > 0 ? `${ruleName}: ${conditions.join(" AND ")}` : ruleName
}

function formatRiskExit(risk: Record<string, unknown> | undefined) {
  if (!risk) return []
  const lines: string[] = []
  const stopLoss = isRecord(risk.stop_loss) ? risk.stop_loss : null
  const takeProfit = isRecord(risk.take_profit) ? risk.take_profit : null
  const timeStop = isRecord(risk.time_stop) ? risk.time_stop : null

  if (stopLoss) {
    if (String(stopLoss.mode) === "manual_pct") lines.push(`SL: ${formatPercent(toNumber(stopLoss.manual_pct))}`)
    else if (String(stopLoss.mode) === "atr_based") {
      const atrMult = isRecord(stopLoss.atr_multiplier) ? toNumber(stopLoss.atr_multiplier.value) : toNumber(stopLoss.atr_multiplier)
      lines.push(`SL: ATR x ${formatNumber(atrMult, 2)}`)
    } else if (String(stopLoss.mode) === "wfo") lines.push("SL: WFO")
  }

  if (takeProfit) {
    if (String(takeProfit.mode) === "manual_pct") lines.push(`TP: ${formatPercent(toNumber(takeProfit.manual_pct))}`)
    else if (String(takeProfit.mode) === "rr_target") {
      const rr = isRecord(takeProfit.rr_ratio) ? toNumber(takeProfit.rr_ratio.value) : toNumber(takeProfit.rr_ratio)
      lines.push(`TP: RR ${formatNumber(rr, 2)}`)
    } else if (String(takeProfit.mode) === "wfo") lines.push("TP: WFO")
  }

  if (timeStop && Boolean(timeStop.enabled)) {
    const bars = isRecord(timeStop.bars) ? toNumber(timeStop.bars.value) : toNumber(timeStop.bars)
    lines.push(`TS: ${formatNumber(bars, 0)} bars`)
  }

  return lines
}

function formatRuleReference(rule: unknown) {
  if (!isRecord(rule)) return ""
  const option = String(rule.config_option ?? "").trim().toUpperCase()
  const label = String(rule.label ?? "").trim()
  if (option && label) return `${option} - ${label}`
  return option || label
}

function findRuleByReference(stockConfig: Record<string, unknown> | null | undefined, reference: string) {
  if (!stockConfig) return null
  const groups = [stockConfig.entry_rules, stockConfig.exit_rules]
  for (const group of groups) {
    if (!Array.isArray(group)) continue
    for (const rule of group) {
      if (!isRecord(rule)) continue
      const normalized = formatRuleReference(rule)
      const option = String(rule.config_option ?? "").trim().toUpperCase()
      if (reference === normalized || reference === option) return rule
    }
  }
  return null
}

function extractRuleLetter(reference: string) {
  const match = reference.trim().toUpperCase().match(/[A-E]/)
  return match?.[0] ?? reference.trim().toUpperCase()
}

function triggeredRuleDisplay(row: Record<string, unknown>, stockConfig: Record<string, unknown> | null | undefined) {
  const backendDisplay = String(row.trigger_display ?? "").trim()
  if (backendDisplay) return backendDisplay

  const side = String(row.side ?? "").trim().toUpperCase()
  const rulePrefix = side === "BUY" ? "Entry" : side === "SELL" ? "Exit" : "Rule"
  const triggered = String(row.exit_rule ?? row.entry_rule ?? "").trim()
  if (!triggered) {
    const reason = String(row.reason ?? "").trim()
    if (reason === "stop_loss") return "SL"
    if (reason === "take_profit") return "TP"
    if (reason === "time_stop") return "TS"
    if (reason.startsWith("entry_rule:") || reason.startsWith("exit_rule:")) {
      const ref = reason.split(":", 2)[1]?.trim() ?? ""
      const rule = findRuleByReference(stockConfig, ref)
      const letter = rule ? String(rule.config_option ?? "").trim().toUpperCase() || extractRuleLetter(ref) : extractRuleLetter(ref)
      const firstCondition = rule && Array.isArray(rule.conditions) ? rule.conditions.find((item) => isRecord(item)) : null
      const variable = firstCondition ? String(firstCondition.variable ?? "").trim() : ""
      const value = variable ? toNumber(row[variable]) : null
      return value == null ? `${rulePrefix} ${letter}` : `${rulePrefix} ${letter} (${formatNumber(value, 2)})`
    }
    return reason ? reasonLabel(reason) : "--"
  }
  if (["SL", "TP", "TS"].includes(triggered.toUpperCase())) return triggered.toUpperCase()

  const rule = findRuleByReference(stockConfig, triggered)
  const letter = rule ? String(rule.config_option ?? "").trim().toUpperCase() || extractRuleLetter(triggered) : extractRuleLetter(triggered)
  const firstCondition = rule && Array.isArray(rule.conditions) ? rule.conditions.find((item) => isRecord(item)) : null
  const variable = firstCondition ? String(firstCondition.variable ?? "").trim() : ""
  const value = variable ? toNumber(row[variable]) : null
  return value == null ? `${rulePrefix} ${letter}` : `${rulePrefix} ${letter} (${formatNumber(value, 2)})`
}

function compatibilityMessage(
  config: Record<string, unknown> | undefined,
  mode: "direct" | "wfo",
): { text: string; blocking: boolean } | null {
  if (!config || ![2, 3].includes(Number(config.schema_version))) return null
  const portfolio = (config.portfolio as Record<string, unknown> | undefined) ?? {}
  const universe = (portfolio.universe as Record<string, unknown> | undefined) ?? {}
  const basket = Array.isArray(universe.basket) ? universe.basket.map((item) => String(item).toUpperCase()) : []
  const stocks = ((config.stocks as Record<string, unknown> | undefined) ?? {})
  const stockConfigs = basket.map((symbol) => stocks[symbol] as Record<string, unknown> | undefined).filter(Boolean)
  if (stockConfigs.length === 0) return null

  const hasRules = stockConfigs.some((stock) => {
    const entries = Array.isArray(stock?.entry_rules) ? stock.entry_rules : []
    const exits = Array.isArray(stock?.exit_rules) ? stock.exit_rules : []
    return entries.length > 0 || exits.length > 0
  })
  const hasWfo = stockConfigs.some((stock) => hasWfoValues(stock))
  if (hasRules) {
    return {
      text:
        mode === "direct"
          ? "This saved strategy includes rules-based sections. Direct backtest executes the manual entry and exit rules with their current seed values."
          : "WFO mode uses the async clean-slice executor. Unsupported Option E and future-only indicator-type selection are blocked server-side before the run starts.",
      blocking: false,
    }
  }
  if (hasWfo && mode === "wfo") {
    return {
      text: "WFO mode will optimize the WFO-marked values per stock, then run the held-out test and final-OOS robustness checks asynchronously.",
      blocking: false,
    }
  }
  return null
}

function isActiveStrategyBacktestStatus(value: unknown) {
  const status = String(value ?? "").trim().toLowerCase()
  return status === "queued" || status === "running" || status === "cancel_requested"
}

function KeyValueList({
  value,
}: {
  value: Record<string, unknown> | null | undefined
}) {
  if (!value || Object.keys(value).length === 0) {
    return <p className="text-sm text-muted-foreground">No values available.</p>
  }
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {Object.entries(value).map(([key, raw]) => (
        <div key={key} className="claude-stat">
          <p className="lbl">{key.replace(/_/g, " ")}</p>
          <p className="val !text-xs break-all">
            {typeof raw === "number" ? formatNumber(raw, 4) : typeof raw === "string" ? raw : JSON.stringify(raw)}
          </p>
        </div>
      ))}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="claude-stat">
      <p className="lbl">{label}</p>
      <p className="val">{value}</p>
    </div>
  )
}

function EdgeSignalSummary({ signals }: { signals: unknown[] }) {
  const rows = signals.filter(isRecord)
  if (rows.length === 0) return null
  return (
    <Card className="claude-card">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Selected Edge Signals</CardTitle>
        <CardDescription>These dashboard signal references are frozen into the strategy snapshot for this backtest.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="claude-table min-w-[760px]">
            <thead>
              <tr><th>Ticker</th><th>Method</th><th>Triage</th><th>Direction</th><th className="r">Net ER</th><th className="r">Hit</th><th className="r">Proof</th></tr>
            </thead>
            <tbody>
              {rows.map((signal, index) => (
                <tr key={String(signal.candidate_id ?? index)}>
                  <td className="font-mono font-medium">{String(signal.symbol ?? "--")}</td>
                  <td>
                    <div className="max-w-[320px] truncate">{String(signal.label ?? "--")}</div>
                    <div className="text-xs text-muted-foreground">{String(signal.source ?? "--")} / {String(signal.variant ?? "--")}</div>
                  </td>
                  <td>{String(signal.triage ?? "watch")}</td>
                  <td>{String(signal.direction ?? "--")}</td>
                  <td className="r font-mono">{formatPercent(toNumber(signal.action_expected_return_net) ?? 0)}</td>
                  <td className="r font-mono">{formatPercent(toNumber(signal.hit_rate) ?? 0)}</td>
                  <td className="r font-mono">{String(signal.proof_n ?? signal.n ?? "--")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

function WindowSummaryTable({
  windows,
  runId,
  symbol,
}: {
  windows: Array<Record<string, unknown>>
  runId?: string | null
  symbol?: string | null
}) {
  const router = useRouter()

  if (windows.length === 0) {
    return <p className="text-sm text-muted-foreground">No persisted WFO windows yet.</p>
  }

  const isClickable = Boolean(runId && symbol)

  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="claude-table">
        <thead>
          <tr>
            {["#", "Train", "OOS", "IS Return", "OOS Return", "Profile"].map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {windows.map((window, index) => {
            const summary = (window.summary as Record<string, unknown> | undefined) ?? {}
            const windowIndex = Math.max(0, Math.trunc(toNumber(summary.window_index) ?? index))
            return (
              <tr
                key={String(summary.window_index ?? index)}
                className={isClickable ? "cursor-pointer" : ""}
                onClick={isClickable ? () => router.push(`/backtest/window/${runId}/${encodeURIComponent(symbol!)}/${windowIndex}`) : undefined}
              >
                <td className="font-mono text-xs">{formatNumber(toNumber(summary.window_index) ?? index, 0)}</td>
                <td className="text-xs">{String(summary.train_start ?? "--")} to {String(summary.train_end ?? "--")}</td>
                <td className="text-xs">{String(summary.oos_start ?? "--")} to {String(summary.oos_end ?? "--")}</td>
                <td className="font-mono text-xs">{formatPercent(toNumber(summary.is_total_return) ?? 0)}</td>
                <td className="font-mono text-xs">{formatPercent(toNumber(summary.oos_total_return) ?? 0)}</td>
                <td className="text-xs">{Boolean(summary.profile_passes) ? "pass" : "warn"}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ConfigComparisonTable({
  configs,
}: {
  configs: Array<Record<string, unknown>>
}) {
  if (!configs || configs.length === 0) return null
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="claude-table">
        <thead>
          <tr>
            {["Train", "OOS", "Windows", "WFE", "Robustness", "Profile", "Viable"].map(
              (h) => (
                <th key={h}>
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {configs.map((c, i) => {
            const wfe = toNumber(c.wfe ?? c.best_wfe) ?? 0
            const robustness = toNumber(c.robustness_ratio ?? c.best_robustness_ratio) ?? 0
            return (
              <tr
                key={i}
                className={Boolean(c.viable) ? "bg-green-500/5" : ""}
              >
                <td className="font-mono text-xs">{String(c.train_bars ?? "--")}</td>
                <td className="font-mono text-xs">{String(c.oos_bars ?? "--")}</td>
                <td className="font-mono text-xs">{String(c.window_count ?? "--")}</td>
                <td className={`font-mono text-xs ${wfe >= 0.5 ? "text-green-600" : "text-amber-600"}`}>
                  {formatPercent(wfe)}
                </td>
                <td className="font-mono text-xs">{formatPercent(robustness)}</td>
                <td className="text-xs">{Boolean(c.profile_passes) ? "pass" : "warn"}</td>
                <td className="text-xs font-semibold">{Boolean(c.viable) ? "Yes" : "No"}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function MetricTable({ rows }: { rows: StrategyBacktestMetricRow[] }) {
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No trade performance rows yet.</p>
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="claude-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th className="r">Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.metric}>
              <td>{row.metric}</td>
              <td className="r font-mono text-xs">{renderMetric(row.metric, row.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TradeLedgerTable({
  rows,
  stockConfig,
}: {
  rows: Array<Record<string, unknown>>
  stockConfig: Record<string, unknown> | null | undefined
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No trade ledger rows for this stock yet.</p>
  }

  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="claude-table whitespace-nowrap">
        <thead>
          <tr>
            {["Date", "Side", "Open", "CMP", "Close", "Qty", "Rule Triggered", "Realized", "Latent"].map((header) => (
              <th key={header}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const realized = toNumber(row.pnl_realise)
            const latent = toNumber(row.pnl_latent)
            return (
              <tr key={`${String(row.timestamp ?? "row")}-${index}`}>
                <td className="font-mono">{formatDateTime(String(row.timestamp ?? ""))}</td>
                <td className={`font-semibold uppercase ${sideTone(row.side)}`}>{String(row.side ?? "--")}</td>
                <td className="tabular-nums">{formatNumber(toNumber(row.prix_execution_open_jour), 4)}</td>
                <td className="tabular-nums">{formatNumber(toNumber(row.cmp), 4)}</td>
                <td className="tabular-nums">{formatNumber(toNumber(row.close_du_jour), 4)}</td>
                <td className="tabular-nums">{formatNumber(toNumber(row.quantite), 0)}</td>
                <td className={`font-semibold ${sideTone(row.side)}`}>{triggeredRuleDisplay(row, stockConfig)}</td>
                <td className={`tabular-nums font-semibold ${realized != null && realized > 0 ? "text-emerald-600" : realized != null && realized < 0 ? "text-red-600" : "text-muted-foreground"}`}>
                  {formatNumber(realized, 2)}
                </td>
                <td className={`tabular-nums font-semibold ${latent != null && latent > 0 ? "text-emerald-600" : latent != null && latent < 0 ? "text-red-600" : "text-muted-foreground"}`}>
                  {formatNumber(latent, 2)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function BacktestContentSaved() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const searchStrategyId = searchParams.get("strategyId")
  const searchRunId = searchParams.get("runId")
  const [setupStrategyId, setSetupStrategyId] = useState<string | null>(searchRunId ? null : searchStrategyId)
  const [startDate, setStartDate] = useState(DEFAULT_START_DATE)
  const [endDate, setEndDate] = useState(todayIso())
  const [activeStock, setActiveStock] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [directResult, setDirectResult] = useState<StrategyBacktestResponse | null>(null)
  const [wfoMinWalkForwards, setWfoMinWalkForwards] = useState(5)
  const [costModel, setCostModel] = useState({ brokerage_bps: 0.2, comm_bourse_bps: 0.1, reg_liv_bps: 0, slippage_bps: 0, tva_rate: 0.1 })
  const [volumeGateEnabled, setVolumeGateEnabled] = useState(false)
  const [volumeGateKind, setVolumeGateKind] = useState<"min_abs" | "min_ratio_adv">("min_ratio_adv")
  const [volumeGateMinAbs, setVolumeGateMinAbs] = useState(50_000)
  const [volumeGateMinRatioAdv, setVolumeGateMinRatioAdv] = useState(0.1)
  const [volumeGateAdvWindow, setVolumeGateAdvWindow] = useState(20)
  const [familyHistoryMode, setFamilyHistoryMode] = useState<FamilyHistoryMode>("dynamic_point_in_time")
  const [cooldownEnabled, setCooldownEnabled] = useState(false)
  const [cooldownBars, setCooldownBars] = useState(10)
  const [libraryStrategyFilter, setLibraryStrategyFilter] = useState("all")
  const [libraryModeFilter, setLibraryModeFilter] = useState("all")
  const [libraryStatusFilter, setLibraryStatusFilter] = useState("all")
  const [librarySearch, setLibrarySearch] = useState("")
  const [renameRunId, setRenameRunId] = useState<string | null>(null)
  const [renameTitle, setRenameTitle] = useState("")
  const [deleteRunId, setDeleteRunId] = useState<string | null>(null)
  const [cancelingRunId, setCancelingRunId] = useState<string | null>(null)
  const runId = searchRunId

  const { data: strategies, isLoading: strategiesLoading } = useStrategies()
  const { data: strategyRun, mutate: mutateStrategyRun } = useStrategyBacktestRun(runId, runId ? 2000 : 0)
  const selectedStrategyId = strategyRun?.strategy_id ?? (runId ? null : setupStrategyId)
  const { data: strategy } = useStrategy(selectedStrategyId)
  const { data: savedRuns, mutate: mutateSavedRuns } = useStrategyBacktestRuns({
    strategy_id: libraryStrategyFilter === "all" ? null : libraryStrategyFilter,
    status: libraryStatusFilter === "all" ? null : libraryStatusFilter,
    mode: libraryModeFilter === "all" ? null : libraryModeFilter,
    q: librarySearch.trim() || null,
    limit: 200,
  })
  const { data: activeRunStockDetail } = useStrategyBacktestStockDetail(strategyRun ? runId : null, activeStock)

  const runMode = useMemo<"direct" | "wfo">(() => {
    // When viewing a saved run, respect its stored mode
    // (strategy may have been edited since the run was created)
    if (strategyRun) return strategyRun.mode === "wfo" ? "wfo" : "direct"
    // For new runs, auto-detect from strategy config
    if (!strategy) return "direct"
    const config = strategy.config_json as Record<string, unknown> | undefined
    return config && hasWfoValues(config) ? "wfo" : "direct"
  }, [strategy, strategyRun])

  useEffect(() => {
    if (searchRunId) return
    setSetupStrategyId(searchStrategyId)
  }, [searchRunId, searchStrategyId])

  useEffect(() => {
    if (searchRunId) {
      setDirectResult(null)
    }
  }, [searchRunId])

  useEffect(() => {
    if (searchRunId) {
      const params = new URLSearchParams()
      params.set("runId", searchRunId)
      const next = `${pathname}?${params.toString()}`
      const current = searchParams.toString() ? `${pathname}?${searchParams.toString()}` : pathname
      if (next !== current) router.replace(next, { scroll: false })
      return
    }

    const params = new URLSearchParams()
    if (setupStrategyId) params.set("strategyId", setupStrategyId)
    const next = params.toString() ? `${pathname}?${params.toString()}` : pathname
    const current = searchParams.toString() ? `${pathname}?${searchParams.toString()}` : pathname
    if (next !== current) router.replace(next, { scroll: false })
  }, [pathname, router, searchParams, searchRunId, setupStrategyId])

  useEffect(() => {
    const symbols = searchRunId
      ? strategyRun?.stocks?.map((item) => item.symbol) ?? []
      : (directResult?.stocks ?? []).map((item) => item.symbol)
    const firstSymbol = symbols[0] ?? null
    setActiveStock((prev) => prev && symbols.includes(prev) ? prev : firstSymbol)
  }, [directResult, searchRunId, strategyRun])

  useEffect(() => {
    if (!strategyRun) return
    const request = isRecord(strategyRun.request) ? strategyRun.request : {}
    const wfoConfig = isRecord(request.wfo_config) ? request.wfo_config : {}
    const nextStart = strategyRun.mode === "wfo"
      ? (typeof wfoConfig.test_period_start === "string" ? wfoConfig.test_period_start : "")
      : (typeof request.start_date === "string" ? request.start_date : "")
    const nextEnd = strategyRun.mode === "wfo"
      ? (typeof wfoConfig.test_period_end === "string" ? wfoConfig.test_period_end : "")
      : (typeof request.end_date === "string" ? request.end_date : "")
    if (nextStart) setStartDate(nextStart)
    if (nextEnd) setEndDate(nextEnd)
    if (isRecord(request.cost_model)) {
      setCostModel({
        brokerage_bps: toNumber(request.cost_model.brokerage_bps) ?? 0.2,
        comm_bourse_bps: toNumber(request.cost_model.comm_bourse_bps) ?? 0.1,
        reg_liv_bps: toNumber(request.cost_model.reg_liv_bps) ?? 0,
        slippage_bps: toNumber(request.cost_model.slippage_bps) ?? 0,
        tva_rate: toNumber(request.cost_model.tva_rate) ?? 0.1,
      })
    }
    const gate = isRecord(request.volume_gate) ? request.volume_gate : {}
    setVolumeGateEnabled(Boolean(gate.enabled))
    setVolumeGateKind(String(gate.kind ?? "min_ratio_adv") === "min_abs" ? "min_abs" : "min_ratio_adv")
    setVolumeGateMinAbs(toNumber(gate.min_volume_abs) ?? 50_000)
    setVolumeGateMinRatioAdv(toNumber(gate.min_volume_ratio_adv) ?? 0.1)
    setVolumeGateAdvWindow(toNumber(gate.adv_window) ?? 20)
    const nextFamilyHistoryMode = String(request.family_history_mode ?? "").trim().toLowerCase()
    setFamilyHistoryMode(nextFamilyHistoryMode === "static_current_reps" ? "static_current_reps" : "dynamic_point_in_time")
    const nextCooldown = toNumber(request.cooldown_bars) ?? 0
    setCooldownEnabled(nextCooldown > 0)
    setCooldownBars(nextCooldown > 0 ? nextCooldown : 10)
    setWfoMinWalkForwards(toNumber(wfoConfig.min_walk_forwards) ?? 5)
  }, [strategyRun?.run_id])

  useEffect(() => {
    if (searchRunId || !setupStrategyId) return
    setDirectResult(null)
    setActiveStock(null)
  }, [searchRunId, setupStrategyId])

  const compatibility = useMemo(
    () => compatibilityMessage(strategy?.config_json as Record<string, unknown> | undefined, runMode),
    [runMode, strategy?.config_json],
  )

  const strategySummary = useMemo(() => {
    if (!strategy) return null
    const config = strategy.config_json as Record<string, unknown>
    if ([2, 3].includes(Number(config.schema_version))) {
      const portfolio = (config.portfolio as Record<string, unknown> | undefined) ?? {}
      const universe = (portfolio.universe as Record<string, unknown> | undefined) ?? {}
      return {
        capital: portfolio.total_capital_mad,
        basket: Array.isArray(universe.basket) ? universe.basket : [],
        edgeSignals: Array.isArray(universe.selected_signal_candidates) ? universe.selected_signal_candidates : [],
      }
    }
    const capital = (config.capital as Record<string, unknown> | undefined) ?? {}
    const universe = (config.universe as Record<string, unknown> | undefined) ?? {}
    return {
      capital: capital.total_capital_mad,
      basket: Array.isArray(universe.basket) ? universe.basket : [],
      edgeSignals: [],
    }
  }, [strategy])

  const runProgress = useMemo(() => (isRecord(strategyRun?.progress) ? strategyRun.progress : {}), [strategyRun?.progress])
  const runSummary = useMemo(() => (isRecord(strategyRun?.summary) ? strategyRun.summary : {}), [strategyRun?.summary])
  const activeStrategyStockConfig = useMemo(() => {
    const config = strategy?.config_json as Record<string, unknown> | undefined
    if (!config || ![2, 3].includes(Number(config.schema_version)) || !activeStock) return null
    const stocks = isRecord(config.stocks) ? config.stocks : {}
    const stock = stocks[activeStock]
    return isRecord(stock) ? stock : null
  }, [activeStock, strategy?.config_json])
  const viewingSavedRun = Boolean(searchRunId)
  const showingSavedWfo = Boolean(strategyRun && strategyRun.mode === "wfo")
  const showingSavedDirect = Boolean(strategyRun && strategyRun.mode === "direct")
  const showingLocalDirect = Boolean(!viewingSavedRun && runMode === "direct" && directResult)
  const localDirectStock = useMemo(
    () => (directResult?.stocks ?? []).find((stock) => stock.symbol === activeStock) ?? null,
    [activeStock, directResult],
  )
  const directGeneralResults = useMemo(() => {
    if (showingSavedDirect) {
      const result = isRecord(strategyRun?.result) ? strategyRun.result : {}
      return isRecord(result.general_results) ? result.general_results : {}
    }
    if (showingLocalDirect) {
      return isRecord(directResult?.general_results) ? directResult.general_results : {}
    }
    return {}
  }, [directResult, showingLocalDirect, showingSavedDirect, strategyRun?.result])
  const activeStockResult = useMemo(() => {
    if (showingSavedDirect) {
      return activeRunStockDetail?.symbol === activeStock && isRecord(activeRunStockDetail.result)
        ? activeRunStockDetail.result
        : null
    }
    if (showingLocalDirect) {
      return localDirectStock ? localDirectStock : null
    }
    return null
  }, [activeRunStockDetail, activeStock, localDirectStock, showingLocalDirect, showingSavedDirect])
  const equityFigure = asFigure((directGeneralResults.plots as Record<string, unknown> | undefined)?.cumreturn_vs_benchmark)
  const drawdownFigure = asFigure((directGeneralResults.plots as Record<string, unknown> | undefined)?.drawdown)
  const monthlyFigure = asFigure((directGeneralResults.plots as Record<string, unknown> | undefined)?.monthly_heatmap)
  const yearlyFigure = asFigure((directGeneralResults.plots as Record<string, unknown> | undefined)?.yearly_barplot)
  const priceFigure = asFigure((activeStockResult as Record<string, unknown> | undefined)?.price_chart)
  const stockEquityFigure = asFigure((activeStockResult as Record<string, unknown> | undefined)?.cumreturn_vs_benchmark)

  async function runBacktest() {
    if (!selectedStrategyId || compatibility?.blocking) return
    setIsRunning(true)
    setErrorMessage(null)
    try {
      const created = await createStrategyBacktestRun({
        strategy_id: selectedStrategyId,
        mode: runMode,
        start_date: startDate || null,
        end_date: endDate || null,
        timeframe: "1D",
        family_history_mode: familyHistoryMode,
        cost_model: costModel,
        volume_gate: {
          enabled: volumeGateEnabled,
          kind: volumeGateKind,
          min_volume_abs: volumeGateMinAbs,
          min_volume_ratio_adv: volumeGateMinRatioAdv,
          adv_window: volumeGateAdvWindow,
        },
        cooldown_bars: cooldownEnabled ? cooldownBars : 0,
        wfo_config: runMode === "wfo"
          ? {
              min_walk_forwards: wfoMinWalkForwards,
              test_period_start: startDate || null,
              test_period_end: endDate || null,
            }
          : undefined,
      })
      setDirectResult(null)
      router.replace(`${pathname}?runId=${created.run_id}`, { scroll: false })
      await mutateSavedRuns()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Backtest failed")
    } finally {
      setIsRunning(false)
    }
  }

  async function openSavedRun(nextRunId: string, _mode: string) {
    setDirectResult(null)
    setErrorMessage(null)
    router.replace(`${pathname}?runId=${nextRunId}`, { scroll: false })
  }

  async function cancelSavedRun(targetRunId: string) {
    if (!targetRunId) return
    setCancelingRunId(targetRunId)
    setErrorMessage(null)
    try {
      await cancelStrategyBacktestRun(targetRunId)
      await Promise.all([
        mutateSavedRuns(),
        runId === targetRunId ? mutateStrategyRun() : Promise.resolve(),
      ])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Cancel failed")
    } finally {
      setCancelingRunId((prev) => (prev === targetRunId ? null : prev))
    }
  }

  async function submitRename() {
    if (!renameRunId || !renameTitle.trim()) return
    try {
      await renameStrategyBacktestRun(renameRunId, renameTitle.trim())
      await Promise.all([mutateSavedRuns(), mutateStrategyRun()])
      setRenameRunId(null)
      setRenameTitle("")
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Rename failed")
    }
  }

  async function confirmDelete() {
    if (!deleteRunId) return
    try {
      await deleteStrategyBacktestRun(deleteRunId)
      if (deleteRunId === runId) {
        setActiveStock(null)
        setSetupStrategyId(selectedStrategyId)
        const next = selectedStrategyId ? `${pathname}?strategyId=${selectedStrategyId}` : pathname
        router.replace(next, { scroll: false })
      }
      await mutateSavedRuns()
      setDeleteRunId(null)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Delete failed")
    }
  }

  return (
    <>
      <div className="claude-backtest-shell">
        <aside className="runs-sidebar">
          <div className="rsh">
            <h4>Saved Backtests</h4>
            <Button asChild variant="ghost" size="icon" className="h-7 w-7">
              <Link href={selectedStrategyId ? `/strategy?strategyId=${selectedStrategyId}` : "/strategy"}>+</Link>
            </Button>
          </div>
          <div className="space-y-2 border-b border-line p-2">
            <Input value={librarySearch} onChange={(event) => setLibrarySearch(event.target.value)} placeholder="Search runs" className="h-8 text-xs" />
            <div className="grid grid-cols-2 gap-2">
              <Select value={libraryModeFilter} onValueChange={setLibraryModeFilter}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All modes</SelectItem>
                  <SelectItem value="direct">Direct</SelectItem>
                  <SelectItem value="wfo">WFO</SelectItem>
                </SelectContent>
              </Select>
              <Select value={libraryStatusFilter} onValueChange={setLibraryStatusFilter}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All status</SelectItem>
                  <SelectItem value="queued">Queued</SelectItem>
                  <SelectItem value="running">Running</SelectItem>
                  <SelectItem value="succeeded">Succeeded</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Select value={libraryStrategyFilter} onValueChange={setLibraryStrategyFilter}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All strategies</SelectItem>
                {(strategies ?? []).map((item) => (
                  <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="runs">
            {(savedRuns ?? []).length === 0 ? (
              <div className="rounded-md border border-dashed border-line px-3 py-6 text-xs text-muted-foreground">
                No saved backtests yet.
              </div>
            ) : (
              (savedRuns ?? []).map((item) => (
                <div key={item.run_id} className={`run-item ${item.run_id === runId ? "active" : ""}`}>
                  <div className="flex items-start gap-2">
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => openSavedRun(item.run_id, item.mode)}>
                      <div className="ri-name truncate">{item.title}</div>
                      <div className="ri-meta">{formatDateTime(item.created_at)}</div>
                      <div className="ri-stats">
                        <span className={item.status === "succeeded" ? "t-pos" : item.status === "failed" ? "t-neg" : "t-mut"}>{item.status}</span>
                        <span className="t-mut">-</span>
                        <span>{item.mode.toUpperCase()}</span>
                      </div>
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button type="button" variant="ghost" size="icon" className="h-7 w-7 shrink-0">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {isActiveStrategyBacktestStatus(item.status) ? (
                          <DropdownMenuItem disabled={item.status === "cancel_requested" || cancelingRunId === item.run_id} onClick={() => void cancelSavedRun(item.run_id)}>
                            {item.status === "cancel_requested" ? "Cancel requested" : cancelingRunId === item.run_id ? "Canceling..." : "Cancel"}
                          </DropdownMenuItem>
                        ) : null}
                        <DropdownMenuItem onClick={() => { setRenameRunId(item.run_id); setRenameTitle(item.title) }}>Rename</DropdownMenuItem>
                        <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setDeleteRunId(item.run_id)}>Delete</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              ))
            )}
          </div>
        </aside>

        <section className="bt-main">
          <div className="mode-bar">
            <h3>Configurer le backtest</h3>
            <span className="seg ml-auto">
              <button type="button" className={runMode === "direct" ? "active" : ""}>Direct</button>
              <button type="button" className={runMode === "wfo" ? "active" : ""}>WFO</button>
            </span>
            <Button type="button" size="sm" onClick={runBacktest} disabled={!selectedStrategyId || isRunning || Boolean(compatibility?.blocking)} className="gap-2">
              <Play className="h-4 w-4" />
              {isRunning ? "Launching" : "Lancer"}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href={selectedStrategyId ? `/strategy?strategyId=${selectedStrategyId}` : "/strategy"}>Open Strategy</Link>
            </Button>
            <Button asChild variant="ghost" size="sm" className="gap-2 text-muted-foreground">
              <Link href="/glossary#backtest">
                <BookOpen className="h-4 w-4" />
                Glossaire
              </Link>
            </Button>
          </div>

          <div className="cfg-panel">
            <div className="cfg-grid">
              <div className="cfg-field">
                <label>Strategie</label>
                {strategiesLoading ? <Skeleton className="h-[30px] rounded-md" /> : (
                  <Select value={selectedStrategyId ?? undefined} onValueChange={(value) => {
                    setSetupStrategyId(value)
                    setErrorMessage(null)
                    setDirectResult(null)
                    if (searchRunId) router.replace(`${pathname}?strategyId=${value}`, { scroll: false })
                  }}>
                    <SelectTrigger className="select"><SelectValue placeholder="Select strategy" /></SelectTrigger>
                    <SelectContent>
                      {(strategies ?? []).map((item) => (
                        <SelectItem key={item.id} value={item.id}>{item.name} - {item.horizon} - {item.basket_count} stocks</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
              <div className="cfg-field">
                <label>{runMode === "wfo" ? "Held-out start" : "Start date"}</label>
                <Input className="input" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
              </div>
              <div className="cfg-field">
                <label>{runMode === "wfo" ? "Held-out end" : "End date"}</label>
                <Input className="input" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
              </div>
              <div className="cfg-field">
                <label>Capital initial</label>
                <Input className="input" value={strategySummary ? formatCurrency(toNumber(strategySummary.capital) ?? 0) : "--"} readOnly />
              </div>
            </div>
            <div className="cfg-row">
              <div className="cfg-field">
                <label>Brokerage</label>
                <Input className="input" type="number" value={costModel.brokerage_bps} onChange={(event) => setCostModel((prev) => ({ ...prev, brokerage_bps: Number(event.target.value) }))} />
              </div>
              <div className="cfg-field">
                <label>Slippage</label>
                <Input className="input" type="number" value={costModel.slippage_bps} onChange={(event) => setCostModel((prev) => ({ ...prev, slippage_bps: Number(event.target.value) }))} />
              </div>
              <div className="cfg-field">
                <label>Volume gate</label>
                <Select value={volumeGateKind} onValueChange={(value) => setVolumeGateKind(value as "min_abs" | "min_ratio_adv")}>
                  <SelectTrigger className="select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="min_ratio_adv">Min ratio ADV</SelectItem>
                    <SelectItem value="min_abs">Min absolute volume</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="cfg-field">
                <label>Gate value</label>
                {volumeGateKind === "min_abs" ? (
                  <Input className="input" type="number" value={volumeGateMinAbs} onChange={(event) => setVolumeGateMinAbs(Number(event.target.value))} />
                ) : (
                  <Input className="input" type="number" step="0.01" value={volumeGateMinRatioAdv} onChange={(event) => setVolumeGateMinRatioAdv(Number(event.target.value))} />
                )}
              </div>
              <div className="cfg-field">
                <label>Family history</label>
                <Select value={familyHistoryMode} onValueChange={(value) => setFamilyHistoryMode(value as FamilyHistoryMode)}>
                  <SelectTrigger className="select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="static_current_reps">Fixed reps</SelectItem>
                    <SelectItem value="dynamic_point_in_time">Point-in-time</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {runMode === "wfo" ? (
                <div className="cfg-field">
                  <label>Min WFO</label>
                  <Input className="input" type="number" min={1} value={wfoMinWalkForwards} onChange={(event) => setWfoMinWalkForwards(Number(event.target.value))} />
                </div>
              ) : null}
              <div className="cfg-field">
                <label>Cooldown</label>
                <div className="flex h-[30px] items-center gap-2 rounded-md border border-line bg-card px-2">
                  <Switch checked={cooldownEnabled} onCheckedChange={setCooldownEnabled} />
                  <Input type="number" value={cooldownBars} onChange={(event) => setCooldownBars(Number(event.target.value))} disabled={!cooldownEnabled} className="h-6 w-16 border-0 p-0 text-xs shadow-none focus-visible:ring-0" />
                </div>
              </div>
              <div className="ml-auto flex items-end">
                <span className={`claude-chip ${volumeGateEnabled ? "amber" : ""}`}>
                  <span className="dot" />
                  {volumeGateEnabled ? "Volume gate actif" : "Volume gate off"}
                </span>
              </div>
            </div>
            {compatibility ? (
              <div className={`mt-3 rounded-md border px-3 py-2 text-sm ${compatibility.blocking ? "border-destructive/30 bg-destructive/10 text-destructive" : "border-amber-300 bg-amber-50 text-amber-900"}`}>
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4" />
                  <span>{compatibility.text}</span>
                </div>
              </div>
            ) : null}
            {errorMessage ? <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{errorMessage}</div> : null}
          </div>

          <div className="results">
            {strategySummary ? (
              <>
                <div className="kpi4">
                  <StatCard label="Capital" value={formatCurrency(toNumber(strategySummary?.capital) ?? 0)} />
                  <StatCard label="Basket" value={`${strategySummary?.basket.length ?? 0} stocks`} />
                  <StatCard label="Edge Signals" value={`${strategySummary?.edgeSignals.length ?? 0}`} />
                  <StatCard label="Mode" value={runMode === "wfo" ? "WFO" : "Direct"} />
                  <StatCard label="Timeframe" value="1D" />
                </div>
                <EdgeSignalSummary signals={strategySummary!.edgeSignals} />
              </>
            ) : null}

            {runId && !strategyRun ? <Skeleton className="h-72 rounded-xl" /> : null}

            {strategyRun ? (
              <Card>
                <CardHeader>
                  <div className="claude-section-h m-0">
                    <div>
                      <h2>{strategyRun.title}</h2>
                      <span className="meta">{strategyRun.strategy_name} - {strategyRun.status} - {formatDateTime(strategyRun.created_at)}</span>
                    </div>
                    {isActiveStrategyBacktestStatus(strategyRun.status) ? (
                      <Button type="button" variant="outline" size="sm" disabled={strategyRun.status === "cancel_requested" || cancelingRunId === strategyRun.run_id} onClick={() => void cancelSavedRun(strategyRun.run_id)}>
                        {strategyRun.status === "cancel_requested" ? "Cancel requested" : cancelingRunId === strategyRun.run_id ? "Canceling..." : "Cancel run"}
                      </Button>
                    ) : null}
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="kpi4">
                    <StatCard label="Status" value={strategyRun.status} />
                    <StatCard label="Mode" value={strategyRun.mode} />
                    <StatCard label="Completed" value={`${formatNumber(toNumber(runProgress.completed) ?? 0, 0)} / ${formatNumber(toNumber(runProgress.total) ?? strategyRun.stocks.length, 0)}`} />
                    <StatCard label="Message" value={String(runProgress.message ?? "--")} />
                  </div>
                  {strategyRun.error_text ? <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{strategyRun.error_text}</div> : null}
                </CardContent>
              </Card>
            ) : null}

            {showingSavedWfo ? (
              <>
                <Card>
                  <CardHeader><CardTitle>Portfolio Held-Out Summary</CardTitle></CardHeader>
                  <CardContent className="space-y-4">
                    <KeyValueList value={((runSummary.portfolio as Record<string, unknown> | undefined)?.test_period as Record<string, unknown> | undefined)?.metrics as Record<string, unknown> | undefined} />
                    <KeyValueList value={(runSummary.portfolio as Record<string, unknown> | undefined)?.robustness as Record<string, unknown> | undefined} />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle>Per Stock</CardTitle></CardHeader>
                  <CardContent>
                    <Tabs value={activeStock ?? undefined} onValueChange={setActiveStock}>
                      <TabsList className="h-auto flex-wrap justify-start">
                        {strategyRun?.stocks.map((stock) => <TabsTrigger key={stock.symbol} value={stock.symbol}>{stock.symbol}</TabsTrigger>)}
                      </TabsList>
                      {strategyRun?.stocks.map((stock) => {
                        const detail = activeRunStockDetail?.symbol === stock.symbol ? activeRunStockDetail : null
                        const stockResult = (detail?.result as Record<string, unknown> | undefined) ?? {}
                        const windows = Array.isArray(stockResult.windows) ? (stockResult.windows as Array<Record<string, unknown>>) : []
                        return (
                          <TabsContent key={stock.symbol} value={stock.symbol} className="space-y-4 pt-4">
                            <div className="kpi4">
                              <StatCard label="Status" value={stock.status} />
                              <StatCard label="WFE" value={formatNumber(toNumber(stock.summary.wfe ?? stock.summary.best_wfe) ?? 0, 3)} />
                              <StatCard label="Robustness" value={formatPercent(toNumber(stock.summary.robustness_ratio ?? stock.summary.best_robustness_ratio) ?? 0)} />
                              <StatCard label="Final Test Return" value={formatPercent(toNumber(stock.summary.final_test_return) ?? 0)} />
                            </div>
                            {detail ? (
                              <div className="grid gap-4 xl:grid-cols-2">
                                <Card><CardHeader><CardTitle>Winning Config</CardTitle></CardHeader><CardContent><KeyValueList value={stockResult.winning_config as Record<string, unknown> | undefined} /></CardContent></Card>
                                <Card><CardHeader><CardTitle>Held-Out Test</CardTitle></CardHeader><CardContent><KeyValueList value={(stockResult.test_period as Record<string, unknown> | undefined)?.metrics as Record<string, unknown> | undefined} /></CardContent></Card>
                                <Card className="xl:col-span-2"><CardHeader><CardTitle>Windows</CardTitle></CardHeader><CardContent><WindowSummaryTable windows={windows} runId={runId} symbol={stock.symbol} /></CardContent></Card>
                              </div>
                            ) : <p className="text-sm text-muted-foreground">Loading stock detail...</p>}
                          </TabsContent>
                        )
                      })}
                    </Tabs>
                  </CardContent>
                </Card>
              </>
            ) : null}

            {showingSavedDirect || showingLocalDirect ? (
              <>
                <Card>
                  <CardHeader>
                    <div className="claude-section-h m-0">
                      <div>
                        <h2>Resultats - {showingSavedDirect ? strategyRun?.strategy_name : strategy?.name ?? "Selected strategy"}</h2>
                        <span className="meta">{showingSavedDirect ? "saved direct run" : "direct backtest result"}</span>
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {(() => {
                      const m = isRecord((directGeneralResults as Record<string, unknown>).metrics)
                        ? (directGeneralResults as Record<string, unknown>).metrics as Record<string, unknown>
                        : null
                      if (!m) return null
                      return (
                        <>
                          <div className="kpi4">
                            <StatCard label="Rendement total" value={formatPercent(toNumber(m.total_return) ?? 0)} />
                            <StatCard label="Sharpe ratio" value={formatNumber(toNumber(m.sharpe) ?? 0, 2)} />
                            <StatCard label="Max drawdown" value={formatPercent(toNumber(m.max_drawdown) ?? 0)} />
                            <StatCard label="Win rate" value={formatPercent(toNumber(m.win_rate) ?? 0)} />
                          </div>
                          <div className="kpi8">
                            <StatCard label="Net PnL" value={formatCurrency(toNumber(m.net_pnl) ?? 0)} />
                            <StatCard label="CAGR" value={formatPercent(toNumber(m.cagr) ?? 0)} />
                            <StatCard label="Trades" value={formatNumber(toNumber(m.number_of_trades) ?? 0, 0)} />
                            <StatCard label="Fees" value={formatCurrency(toNumber(m.total_fees) ?? 0)} />
                            <StatCard label="Sortino" value={formatNumber(toNumber(m.sortino) ?? 0, 2)} />
                            <StatCard label="Calmar" value={formatNumber(toNumber(m.calmar) ?? 0, 2)} />
                            <StatCard label="Profit factor" value={formatNumber(toNumber(m.profit_factor) ?? 0, 2)} />
                            <StatCard label="Alpha" value={formatPercent(toNumber(m.alpha) ?? 0)} />
                          </div>
                        </>
                      )
                    })()}
                    <div className="grid gap-4 xl:grid-cols-2">
                      <Card><CardHeader><CardTitle>Courbe d'equite vs benchmark</CardTitle></CardHeader><CardContent className="bt-chart">{equityFigure ? <PlotlyChart figure={equityFigure} /> : <p className="p-4 text-sm text-muted-foreground">No cumulative plot available.</p>}</CardContent></Card>
                      <Card><CardHeader><CardTitle>Drawdown</CardTitle></CardHeader><CardContent className="bt-chart">{drawdownFigure ? <PlotlyChart figure={drawdownFigure} /> : <p className="p-4 text-sm text-muted-foreground">No drawdown plot available.</p>}</CardContent></Card>
                    </div>
                    <div className="grid gap-4 xl:grid-cols-2">
                      <Card><CardHeader><CardTitle>Monthly Returns</CardTitle></CardHeader><CardContent className="bt-chart">{monthlyFigure ? <PlotlyChart figure={monthlyFigure} /> : <p className="p-4 text-sm text-muted-foreground">No monthly heatmap available.</p>}</CardContent></Card>
                      <Card><CardHeader><CardTitle>Yearly Returns</CardTitle></CardHeader><CardContent className="bt-chart">{yearlyFigure ? <PlotlyChart figure={yearlyFigure} /> : <p className="p-4 text-sm text-muted-foreground">No yearly plot available.</p>}</CardContent></Card>
                    </div>
                    <MetricTable rows={metricRowsFromValue((directGeneralResults as Record<string, unknown>).trade_performance ?? (directGeneralResults as Record<string, unknown>).metrics)} />
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader><CardTitle>By Stock</CardTitle></CardHeader>
                  <CardContent>
                    <Tabs value={activeStock ?? undefined} onValueChange={setActiveStock}>
                      <TabsList className="h-auto flex-wrap justify-start">
                        {showingSavedDirect
                          ? strategyRun?.stocks.map((stock) => <TabsTrigger key={stock.symbol} value={stock.symbol}>{stock.symbol}</TabsTrigger>)
                          : (directResult?.stocks ?? []).map((stock) => <TabsTrigger key={stock.symbol} value={stock.symbol}>{stock.symbol}</TabsTrigger>)}
                      </TabsList>
                      {showingSavedDirect
                        ? strategyRun?.stocks.map((stock) => {
                            const detail = activeRunStockDetail?.symbol === stock.symbol ? activeRunStockDetail : null
                            const stockResult = (detail?.result as Record<string, unknown> | undefined) ?? {}
                            const stockSummary = isRecord(stock.summary) ? stock.summary : {}
                            const savedStockEquity = asFigure(stockResult.cumreturn_vs_benchmark)
                            return (
                              <TabsContent key={stock.symbol} value={stock.symbol} className="space-y-4 pt-4">
                                <div className="kpi8">
                                  <StatCard label="Allocation" value={formatCurrency(toNumber(stockSummary.capital_mad) ?? 0)} />
                                  <StatCard label="Weight" value={formatPercent((toNumber(stockSummary.weight_pct) ?? 0) / 100)} />
                                  <StatCard label="Net PnL" value={formatCurrency(toNumber(stockSummary.net_pnl) ?? 0)} />
                                  <StatCard label="Return" value={formatPercent(toNumber(stockSummary.total_return) ?? 0)} />
                                  <StatCard label="CAGR" value={formatPercent(toNumber(stockSummary.cagr) ?? 0)} />
                                  <StatCard label="Sharpe" value={formatNumber(toNumber(stockSummary.sharpe) ?? 0, 2)} />
                                  <StatCard label="Max DD" value={formatPercent(toNumber(stockSummary.max_drawdown) ?? 0)} />
                                  <StatCard label="Trades" value={formatNumber(toNumber(stockSummary.number_of_trades ?? stockSummary.n_trades) ?? 0, 0)} />
                                </div>
                                {detail ? (
                                  <>
                                    <div className="grid gap-4 xl:grid-cols-2">
                                      <Card><CardHeader><CardTitle>Price + Trades</CardTitle></CardHeader><CardContent className="bt-chart">{priceFigure ? <PlotlyChart figure={priceFigure} /> : <p className="p-4 text-sm text-muted-foreground">No price chart available.</p>}</CardContent></Card>
                                      <Card><CardHeader><CardTitle>Equity vs Benchmark</CardTitle></CardHeader><CardContent className="bt-chart">{savedStockEquity ? <PlotlyChart figure={savedStockEquity} /> : <p className="p-4 text-sm text-muted-foreground">No equity chart available.</p>}</CardContent></Card>
                                    </div>
                                    <Card><CardHeader><CardTitle>Trade Ledger</CardTitle></CardHeader><CardContent><TradeLedgerTable rows={(stockResult.trade_ledger as Array<Record<string, unknown>>) ?? []} stockConfig={activeStrategyStockConfig} /></CardContent></Card>
                                  </>
                                ) : <p className="text-sm text-muted-foreground">Loading stock detail...</p>}
                              </TabsContent>
                            )
                          })
                        : (directResult?.stocks ?? []).map((stock) => {
                            const summary = isRecord(stock.summary_metrics) ? stock.summary_metrics : {}
                            const allocation = isRecord(stock.allocation) ? stock.allocation : {}
                            const localStockEquity = asFigure((stock as Record<string, unknown>).cumreturn_vs_benchmark)
                            return (
                              <TabsContent key={stock.symbol} value={stock.symbol} className="space-y-4 pt-4">
                                <div className="kpi8">
                                  <StatCard label="Allocation" value={formatCurrency(toNumber(allocation.capital_mad) ?? 0)} />
                                  <StatCard label="Weight" value={formatPercent((toNumber(allocation.weight_pct) ?? 0) / 100)} />
                                  <StatCard label="Net PnL" value={formatCurrency(toNumber(summary.net_pnl) ?? 0)} />
                                  <StatCard label="Return" value={formatPercent(toNumber(summary.total_return) ?? 0)} />
                                  <StatCard label="CAGR" value={formatPercent(toNumber(summary.cagr) ?? 0)} />
                                  <StatCard label="Sharpe" value={formatNumber(toNumber(summary.sharpe) ?? 0, 2)} />
                                  <StatCard label="Max DD" value={formatPercent(toNumber(summary.max_drawdown) ?? 0)} />
                                  <StatCard label="Trades" value={formatNumber(toNumber(summary.n_trades) ?? 0, 0)} />
                                </div>
                                <div className="grid gap-4 xl:grid-cols-2">
                                  <Card><CardHeader><CardTitle>Price + Trades</CardTitle></CardHeader><CardContent className="bt-chart">{priceFigure ? <PlotlyChart figure={priceFigure} /> : <p className="p-4 text-sm text-muted-foreground">No price chart available.</p>}</CardContent></Card>
                                  <Card><CardHeader><CardTitle>Equity vs Benchmark</CardTitle></CardHeader><CardContent className="bt-chart">{localStockEquity ? <PlotlyChart figure={localStockEquity} /> : <p className="p-4 text-sm text-muted-foreground">No equity chart available.</p>}</CardContent></Card>
                                </div>
                                <Card><CardHeader><CardTitle>Trade Ledger</CardTitle></CardHeader><CardContent><TradeLedgerTable rows={(stock.trade_ledger as Array<Record<string, unknown>>) ?? []} stockConfig={activeStrategyStockConfig} /></CardContent></Card>
                              </TabsContent>
                            )
                          })}
                    </Tabs>
                  </CardContent>
                </Card>
              </>
            ) : null}

            {!runId && !showingLocalDirect ? (
              <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-line bg-card text-sm text-muted-foreground">
                Select a saved strategy and launch a direct or WFO backtest.
              </div>
            ) : null}
          </div>
        </section>
      </div>

      <Dialog open={Boolean(renameRunId)} onOpenChange={(open) => { if (!open) { setRenameRunId(null); setRenameTitle("") } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Backtest</DialogTitle>
            <DialogDescription>Update the saved title. The run contents stay immutable.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="rename-backtest-title">Title</Label>
            <Input id="rename-backtest-title" value={renameTitle} onChange={(event) => setRenameTitle(event.target.value)} maxLength={200} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setRenameRunId(null); setRenameTitle("") }}>Cancel</Button>
            <Button onClick={submitRename} disabled={!renameTitle.trim()}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(deleteRunId)} onOpenChange={(open) => { if (!open) setDeleteRunId(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Saved Backtest</AlertDialogTitle>
            <AlertDialogDescription>This permanently removes the run and its persisted stock and WFO window details.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )

  return (
    <div className="claude-page flex flex-col gap-6 xl:flex-row">
      <RetractableSavedSidebar storageKey="backtestSavedSidebar" label="Backtests" expandedWidth={320} className="xl:shrink-0">
        <Card className="claude-card h-fit">
        <CardHeader className="pb-3">
          <CardTitle>Saved Backtests</CardTitle>
          <CardDescription>Open any persisted direct or WFO run from the library.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input value={librarySearch} onChange={(event) => setLibrarySearch(event.target.value)} placeholder="Search title or strategy" />
          <Select value={libraryStrategyFilter} onValueChange={setLibraryStrategyFilter}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All strategies</SelectItem>
              {(strategies ?? []).map((item) => (
                <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="grid gap-3 sm:grid-cols-2">
            <Select value={libraryModeFilter} onValueChange={setLibraryModeFilter}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All modes</SelectItem>
                <SelectItem value="direct">Direct</SelectItem>
                <SelectItem value="wfo">WFO</SelectItem>
              </SelectContent>
            </Select>
            <Select value={libraryStatusFilter} onValueChange={setLibraryStatusFilter}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All status</SelectItem>
                <SelectItem value="queued">Queued</SelectItem>
                <SelectItem value="running">Running</SelectItem>
                <SelectItem value="succeeded">Succeeded</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            {(savedRuns ?? []).length === 0 ? (
              <div className="rounded-lg border border-dashed border-border/70 px-3 py-6 text-sm text-muted-foreground">
                No saved backtests yet.
              </div>
            ) : (
              (savedRuns ?? []).map((item) => (
                <div key={item.run_id} className={`rounded-md border ${item.run_id === runId ? "border-[oklch(0.82_0.06_260)] bg-[oklch(0.94_0.04_260_/_0.55)]" : "border-transparent hover:border-line hover:bg-bg3"}`}>
                  <div className="flex items-start gap-2 p-3">
                    <button type="button" className="min-w-0 flex-1 text-left" onClick={() => openSavedRun(item.run_id, item.mode)}>
                      <p className="truncate text-sm font-semibold text-foreground">{item.title}</p>
                      <p className="mt-1 text-xs text-muted-foreground">{item.strategy_name} - {item.mode} - {item.status}</p>
                      <p className="mt-1 text-[11px] text-muted-foreground">{formatDateTime(item.created_at)}</p>
                    </button>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0">
                          <MoreHorizontal className="h-4 w-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {isActiveStrategyBacktestStatus(item.status) ? (
                          <DropdownMenuItem
                            disabled={item.status === "cancel_requested" || cancelingRunId === item.run_id}
                            onClick={() => void cancelSavedRun(item.run_id)}
                          >
                            {item.status === "cancel_requested"
                              ? "Cancel requested"
                              : cancelingRunId === item.run_id
                                ? "Canceling..."
                                : "Cancel"}
                          </DropdownMenuItem>
                        ) : null}
                        <DropdownMenuItem onClick={() => { setRenameRunId(item.run_id); setRenameTitle(item.title) }}>Rename</DropdownMenuItem>
                        <DropdownMenuItem className="text-destructive focus:text-destructive" onClick={() => setDeleteRunId(item.run_id)}>Delete</DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
      </RetractableSavedSidebar>

      <div className="min-w-0 flex-1 space-y-6">
        <div className="claude-page-h">
          <div>
            <h1>Backtest</h1>
            <p className="sub">Configure direct or WFO execution, inspect saved runs, and review immutable result evidence.</p>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link href={selectedStrategyId ? `/strategy?strategyId=${selectedStrategyId}` : "/strategy"}>Open Strategy</Link>
          </Button>
        </div>

        <Card className="claude-card">
          <CardHeader className="pb-3">
            <CardTitle>Configure Backtest</CardTitle>
            <CardDescription>
              {runMode === "direct"
                ? "No WFO-marked parameters detected. Direct mode now launches as an async saved run."
                : "WFO-marked parameters detected \u2014 this run will optimize via async walk-forward."}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr_1fr]">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Label>Saved strategy</Label>
                  {strategy && (
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      runMode === "wfo"
                        ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400"
                        : "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400"
                    }`}>
                      {runMode === "wfo" ? "WFO (auto)" : "Direct"}
                    </span>
                  )}
                </div>
                {strategiesLoading ? <Skeleton className="h-10 rounded-md" /> : (
                  <Select value={selectedStrategyId ?? undefined} onValueChange={(value) => {
                    setSetupStrategyId(value)
                    setErrorMessage(null)
                    setDirectResult(null)
                    if (searchRunId) {
                      router.replace(`${pathname}?strategyId=${value}`, { scroll: false })
                    }
                  }}>
                    <SelectTrigger><SelectValue placeholder="Select a saved strategy" /></SelectTrigger>
                    <SelectContent>
                      {(strategies ?? []).map((item) => (
                        <SelectItem key={item.id} value={item.id}>{item.name} - {item.horizon} - {item.basket_count} stocks</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
              <div className="space-y-2">
                <Label>{runMode === "wfo" ? "Held-out test start" : "Start date"}</Label>
                <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{runMode === "wfo" ? "Held-out test end" : "End date"}</Label>
                <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
              </div>
            </div>
            {runMode === "wfo" ? (
              <div className="grid gap-4 xl:grid-cols-1">
                <div className="space-y-2">
                  <Label>Min walk-forwards</Label>
                  <Input type="number" min={1} value={wfoMinWalkForwards} onChange={(event) => setWfoMinWalkForwards(Number(event.target.value))} />
                </div>
              </div>
            ) : null}

            {strategySummary ? (
              <>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                  <StatCard label="Capital" value={formatCurrency(toNumber(strategySummary!.capital) ?? 0)} />
                  <StatCard label="Basket" value={`${strategySummary!.basket.length} stocks`} />
                  <StatCard label="Edge Signals" value={`${strategySummary!.edgeSignals.length}`} />
                  <StatCard label="Mode" value={runMode === "wfo" ? "WFO" : "Direct"} />
                  <StatCard label="Timeframe" value="1D" />
                </div>
                <EdgeSignalSummary signals={strategySummary!.edgeSignals} />
              </>
            ) : null}

            {compatibility ? (
              <div className={`rounded-lg border px-3 py-2 text-sm ${compatibility?.blocking ? "border-destructive/30 bg-destructive/10 text-destructive" : "border-amber-300 bg-amber-50 text-amber-900"}`}>
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4" />
                  <span>{compatibility?.text}</span>
                </div>
              </div>
            ) : null}

            <div className="grid gap-4 xl:grid-cols-3">
              <Card className="claude-card border-dashed">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Costs</CardTitle></CardHeader>
                <CardContent className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1.5"><Label>Brokerage</Label><Input type="number" value={costModel.brokerage_bps} onChange={(e) => setCostModel((prev) => ({ ...prev, brokerage_bps: Number(e.target.value) }))} /></div>
                  <div className="space-y-1.5"><Label>Comm. bourse</Label><Input type="number" value={costModel.comm_bourse_bps} onChange={(e) => setCostModel((prev) => ({ ...prev, comm_bourse_bps: Number(e.target.value) }))} /></div>
                  <div className="space-y-1.5"><Label>Reg/Liv</Label><Input type="number" value={costModel.reg_liv_bps} onChange={(e) => setCostModel((prev) => ({ ...prev, reg_liv_bps: Number(e.target.value) }))} /></div>
                  <div className="space-y-1.5"><Label>Slippage</Label><Input type="number" value={costModel.slippage_bps} onChange={(e) => setCostModel((prev) => ({ ...prev, slippage_bps: Number(e.target.value) }))} /></div>
                </CardContent>
              </Card>
              <Card className="claude-card border-dashed">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Volume Gate</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="flex items-center justify-between"><Label>Enable volume gate</Label><Switch checked={volumeGateEnabled} onCheckedChange={setVolumeGateEnabled} /></div>
                  <Select value={volumeGateKind} onValueChange={(value) => setVolumeGateKind(value as "min_abs" | "min_ratio_adv")}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="min_ratio_adv">Min ratio ADV</SelectItem><SelectItem value="min_abs">Min absolute volume</SelectItem></SelectContent>
                  </Select>
                  {volumeGateKind === "min_abs" ? <Input type="number" value={volumeGateMinAbs} onChange={(e) => setVolumeGateMinAbs(Number(e.target.value))} /> : <Input type="number" step="0.01" value={volumeGateMinRatioAdv} onChange={(e) => setVolumeGateMinRatioAdv(Number(e.target.value))} />}
                  <Input type="number" value={volumeGateAdvWindow} onChange={(e) => setVolumeGateAdvWindow(Number(e.target.value))} />
                </CardContent>
              </Card>
              <Card className="claude-card border-dashed">
                <CardHeader className="pb-2"><CardTitle className="text-sm">Run</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5">
                    <Label>Family history mode</Label>
                    <Select value={familyHistoryMode} onValueChange={(value) => setFamilyHistoryMode(value as FamilyHistoryMode)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="static_current_reps">Fixed reps (faster)</SelectItem>
                        <SelectItem value="dynamic_point_in_time">Recompute each bar (slower)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      {familyHistoryMode === "dynamic_point_in_time"
                        ? "Recomputes representative variants on every bar (point-in-time accurate, slower)."
                        : "Uses one representative set across the run (faster, less strict)."}
                    </p>
                  </div>
                  <div className="flex items-center justify-between"><Label>Enable cooldown</Label><Switch checked={cooldownEnabled} onCheckedChange={setCooldownEnabled} /></div>
                  <Input type="number" value={cooldownBars} onChange={(e) => setCooldownBars(Number(e.target.value))} disabled={!cooldownEnabled} />
                  <Button onClick={runBacktest} disabled={!selectedStrategyId || isRunning || Boolean(compatibility?.blocking)} className="w-full">
                    {isRunning ? (runMode === "direct" ? "Launching direct run..." : "Launching WFO run...") : runMode === "direct" ? "Run Direct Backtest" : "Launch WFO Run"}
                  </Button>
                </CardContent>
              </Card>
            </div>

            {errorMessage ? <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{errorMessage}</div> : null}
          </CardContent>
        </Card>

        {runId && !strategyRun ? <Skeleton className="h-72 rounded-xl" /> : null}

        {strategyRun ? (
          <Card className="claude-card">
            <CardHeader className="pb-3">
              <CardTitle>{strategyRun?.title}</CardTitle>
              <CardDescription>{strategyRun?.strategy_name} - {strategyRun?.status} - {formatDateTime(strategyRun?.created_at)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 md:grid-cols-4">
                <StatCard label="Status" value={strategyRun?.status ?? "--"} />
                <StatCard label="Mode" value={strategyRun?.mode ?? "--"} />
                <StatCard label="Completed" value={`${formatNumber(toNumber(runProgress.completed) ?? 0, 0)} / ${formatNumber(toNumber(runProgress.total) ?? strategyRun?.stocks.length ?? 0, 0)}`} />
                <StatCard label="Message" value={String(runProgress.message ?? "--")} />
              </div>
              {strategyRun && isActiveStrategyBacktestStatus(strategyRun!.status) ? (
                <div className="flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={strategyRun!.status === "cancel_requested" || cancelingRunId === strategyRun!.run_id}
                    onClick={() => void cancelSavedRun(strategyRun!.run_id)}
                  >
                    {strategyRun!.status === "cancel_requested"
                      ? "Cancel requested"
                      : cancelingRunId === strategyRun!.run_id
                        ? "Canceling..."
                        : "Cancel run"}
                  </Button>
                </div>
              ) : null}
              {strategyRun?.error_text ? <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{strategyRun?.error_text}</div> : null}
            </CardContent>
          </Card>
        ) : null}
        {showingSavedWfo ? (
          <>
            <Card className="claude-card">
              <CardHeader className="pb-3">
                <CardTitle>Portfolio Held-Out Summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <KeyValueList value={((runSummary.portfolio as Record<string, unknown> | undefined)?.test_period as Record<string, unknown> | undefined)?.metrics as Record<string, unknown> | undefined} />
                <KeyValueList value={(runSummary.portfolio as Record<string, unknown> | undefined)?.robustness as Record<string, unknown> | undefined} />
              </CardContent>
            </Card>
            <Card className="claude-card">
              <CardHeader className="pb-3">
                <CardTitle>Per Stock</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <Tabs value={activeStock ?? undefined} onValueChange={setActiveStock}>
                  <TabsList className="h-auto flex-wrap justify-start">
                    {strategyRun?.stocks.map((stock) => <TabsTrigger key={stock.symbol} value={stock.symbol}>{stock.symbol}</TabsTrigger>)}
                  </TabsList>
                  {strategyRun?.stocks.map((stock) => {
                    const detail = activeRunStockDetail?.symbol === stock.symbol ? activeRunStockDetail : null
                    const stockResult = (detail?.result as Record<string, unknown> | undefined) ?? {}
                    const windows = Array.isArray(stockResult.windows) ? (stockResult.windows as Array<Record<string, unknown>>) : []
                    return (
                      <TabsContent key={stock.symbol} value={stock.symbol} className="space-y-4">
                        <div className="grid gap-3 md:grid-cols-4">
                          <StatCard label="Status" value={stock.status} />
                          <StatCard label="WFE" value={formatNumber(toNumber(stock.summary.wfe ?? stock.summary.best_wfe) ?? 0, 3)} />
                          <StatCard label="Robustness" value={formatPercent(toNumber(stock.summary.robustness_ratio ?? stock.summary.best_robustness_ratio) ?? 0)} />
                          <StatCard label="Final Test Return" value={formatPercent(toNumber(stock.summary.final_test_return) ?? 0)} />
                        </div>
                        {stock.error_text ? <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{stock.error_text}</div> : null}
                        {(stock.status === "not_viable" || stockResult.status === "not_viable") &&
                          Array.isArray(stockResult.rejection_reasons) &&
                          stockResult.rejection_reasons.length > 0 && (
                          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 space-y-1">
                            <p className="text-sm font-semibold text-amber-700 dark:text-amber-400">
                              Strategy Not Viable
                            </p>
                            {(stockResult.rejection_reasons as string[]).map((reason: string, i: number) => (
                              <p key={i} className="text-sm text-amber-600 dark:text-amber-300">
                                - {reason}
                              </p>
                            ))}
                          </div>
                        )}
                        {detail ? (
                          <>
                            <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">{stockResult.status === "not_viable" ? "Best Config (Not Viable)" : "Winning Config"}</CardTitle></CardHeader><CardContent><KeyValueList value={stockResult.winning_config as Record<string, unknown> | undefined} /></CardContent></Card>
                            <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Final Params</CardTitle></CardHeader><CardContent><KeyValueList value={stockResult.final_params as Record<string, unknown> | undefined} /></CardContent></Card>
                            <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Windows</CardTitle></CardHeader><CardContent><WindowSummaryTable windows={windows} runId={runId} symbol={stock.symbol} /></CardContent></Card>
                            {Array.isArray(stockResult.all_configs_tested) &&
                              stockResult.all_configs_tested.length > 0 && (
                              <Card className="claude-card">
                                <CardHeader className="pb-2">
                                  <CardTitle className="text-sm">All Configs Tested</CardTitle>
                                </CardHeader>
                                <CardContent>
                                  <ConfigComparisonTable
                                    configs={stockResult.all_configs_tested as Array<Record<string, unknown>>}
                                  />
                                </CardContent>
                              </Card>
                            )}
                            <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Held-Out Test</CardTitle></CardHeader><CardContent><KeyValueList value={(stockResult.test_period as Record<string, unknown> | undefined)?.metrics as Record<string, unknown> | undefined} /></CardContent></Card>
                          </>
                        ) : <p className="text-sm text-muted-foreground">Loading stock detail...</p>}
                      </TabsContent>
                    )
                  })}
                </Tabs>
              </CardContent>
            </Card>
          </>
        ) : null}

        {showingSavedDirect || showingLocalDirect ? (
          <>
            <Card className="claude-card">
              <CardHeader className="pb-3">
                <CardTitle>General Results</CardTitle>
                <CardDescription>
                  {showingSavedDirect
                    ? `${strategyRun?.strategy_name} - saved direct run`
                    : `${strategy?.name ?? "Selected strategy"} - direct backtest result`}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {(() => {
                  const m = isRecord((directGeneralResults as Record<string, unknown>).metrics)
                    ? (directGeneralResults as Record<string, unknown>).metrics as Record<string, unknown>
                    : null
                  if (!m) return null
                  return (
                    <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
                      <StatCard label="Net PnL" value={formatCurrency(toNumber(m?.net_pnl) ?? 0)} />
                      <StatCard label="Return" value={formatPercent(toNumber(m?.total_return) ?? 0)} />
                      <StatCard label="CAGR" value={formatPercent(toNumber(m?.cagr) ?? 0)} />
                      <StatCard label="Sharpe" value={formatNumber(toNumber(m?.sharpe) ?? 0, 2)} />
                      <StatCard label="Max DD" value={formatPercent(toNumber(m?.max_drawdown) ?? 0)} />
                      <StatCard label="Win Rate" value={formatPercent(toNumber(m?.win_rate) ?? 0)} />
                      <StatCard label="Trades" value={formatNumber(toNumber(m?.number_of_trades) ?? 0, 0)} />
                      <StatCard label="Fees" value={formatCurrency(toNumber(m?.total_fees) ?? 0)} />
                    </div>
                  )
                })()}
                <div className="grid gap-4 xl:grid-cols-2">
                  <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Equity vs Benchmark</CardTitle></CardHeader><CardContent>{equityFigure ? <PlotlyChart figure={equityFigure ?? undefined} /> : <p className="text-sm text-muted-foreground">No cumulative plot available.</p>}</CardContent></Card>
                  <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Drawdown</CardTitle></CardHeader><CardContent>{drawdownFigure ? <PlotlyChart figure={drawdownFigure ?? undefined} /> : <p className="text-sm text-muted-foreground">No drawdown plot available.</p>}</CardContent></Card>
                </div>
                <div className="grid gap-4 xl:grid-cols-2">
                  <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Monthly Returns</CardTitle></CardHeader><CardContent>{monthlyFigure ? <PlotlyChart figure={monthlyFigure ?? undefined} /> : <p className="text-sm text-muted-foreground">No monthly heatmap available.</p>}</CardContent></Card>
                  <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Yearly Returns</CardTitle></CardHeader><CardContent>{yearlyFigure ? <PlotlyChart figure={yearlyFigure ?? undefined} /> : <p className="text-sm text-muted-foreground">No yearly plot available.</p>}</CardContent></Card>
                </div>
                <MetricTable rows={metricRowsFromValue((directGeneralResults as Record<string, unknown>).trade_performance ?? (directGeneralResults as Record<string, unknown>).metrics)} />
              </CardContent>
            </Card>
            <Card className="claude-card">
              <CardHeader className="pb-3">
                <CardTitle>By Stock</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <Tabs value={activeStock ?? undefined} onValueChange={setActiveStock}>
                  <TabsList className="h-auto flex-wrap justify-start">
                    {showingSavedDirect
                      ? strategyRun?.stocks.map((stock) => <TabsTrigger key={stock.symbol} value={stock.symbol}>{stock.symbol}</TabsTrigger>)
                      : (directResult?.stocks ?? []).map((stock) => <TabsTrigger key={stock.symbol} value={stock.symbol}>{stock.symbol}</TabsTrigger>)}
                  </TabsList>
                  {showingSavedDirect
                    ? strategyRun?.stocks.map((stock) => {
                        const detail = activeRunStockDetail?.symbol === stock.symbol ? activeRunStockDetail : null
                        const stockResult = (detail?.result as Record<string, unknown> | undefined) ?? {}
                        const stockSummary = isRecord(stock.summary) ? stock.summary : {}
                        const savedStockEquity = asFigure(stockResult.cumreturn_vs_benchmark)
                        return (
                          <TabsContent key={stock.symbol} value={stock.symbol} className="space-y-4">
                            <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
                              <StatCard label="Allocation" value={formatCurrency(toNumber(stockSummary.capital_mad) ?? 0)} />
                              <StatCard label="Weight" value={formatPercent((toNumber(stockSummary.weight_pct) ?? 0) / 100)} />
                              <StatCard label="Net PnL" value={formatCurrency(toNumber(stockSummary.net_pnl) ?? 0)} />
                              <StatCard label="Return" value={formatPercent(toNumber(stockSummary.total_return) ?? 0)} />
                              <StatCard label="CAGR" value={formatPercent(toNumber(stockSummary.cagr) ?? 0)} />
                              <StatCard label="Sharpe" value={formatNumber(toNumber(stockSummary.sharpe) ?? 0, 2)} />
                              <StatCard label="Max DD" value={formatPercent(toNumber(stockSummary.max_drawdown) ?? 0)} />
                              <StatCard label="Trades" value={formatNumber(toNumber(stockSummary.number_of_trades ?? stockSummary.n_trades) ?? 0, 0)} />
                            </div>
                            {stock.error_text ? <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{stock.error_text}</div> : null}
                            {detail ? (
                              <>
                                <div className="grid gap-4 xl:grid-cols-2">
                                  <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Price + Trades</CardTitle></CardHeader><CardContent>{priceFigure ? <PlotlyChart figure={priceFigure} /> : <p className="text-sm text-muted-foreground">No price chart available.</p>}</CardContent></Card>
                                  <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Equity vs Benchmark</CardTitle></CardHeader><CardContent>{savedStockEquity ? <PlotlyChart figure={savedStockEquity} /> : <p className="text-sm text-muted-foreground">No equity chart available.</p>}</CardContent></Card>
                                </div>
                                <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Trade Ledger</CardTitle></CardHeader><CardContent><TradeLedgerTable rows={(stockResult.trade_ledger as Array<Record<string, unknown>>) ?? []} stockConfig={activeStrategyStockConfig} /></CardContent></Card>
                                <MetricTable rows={metricRowsFromValue(stockResult.trade_performance ?? stockResult.summary_metrics)} />
                              </>
                            ) : <p className="text-sm text-muted-foreground">Loading stock detail...</p>}
                          </TabsContent>
                        )
                      })
                    : (directResult?.stocks ?? []).map((stock) => {
                        const summary = isRecord(stock.summary_metrics) ? stock.summary_metrics : {}
                        const allocation = isRecord(stock.allocation) ? stock.allocation : {}
                        const localStockEquity = asFigure((stock as Record<string, unknown>).cumreturn_vs_benchmark)
                        return (
                          <TabsContent key={stock.symbol} value={stock.symbol} className="space-y-4">
                            <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
                              <StatCard label="Allocation" value={formatCurrency(toNumber(allocation.capital_mad) ?? 0)} />
                              <StatCard label="Weight" value={formatPercent((toNumber(allocation.weight_pct) ?? 0) / 100)} />
                              <StatCard label="Net PnL" value={formatCurrency(toNumber(summary.net_pnl) ?? 0)} />
                              <StatCard label="Return" value={formatPercent(toNumber(summary.total_return) ?? 0)} />
                              <StatCard label="CAGR" value={formatPercent(toNumber(summary.cagr) ?? 0)} />
                              <StatCard label="Sharpe" value={formatNumber(toNumber(summary.sharpe) ?? 0, 2)} />
                              <StatCard label="Max DD" value={formatPercent(toNumber(summary.max_drawdown) ?? 0)} />
                              <StatCard label="Trades" value={formatNumber(toNumber(summary.n_trades) ?? 0, 0)} />
                            </div>
                            <div className="grid gap-4 xl:grid-cols-2">
                              <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Price + Trades</CardTitle></CardHeader><CardContent>{priceFigure ? <PlotlyChart figure={priceFigure} /> : <p className="text-sm text-muted-foreground">No price chart available.</p>}</CardContent></Card>
                              <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Equity vs Benchmark</CardTitle></CardHeader><CardContent>{localStockEquity ? <PlotlyChart figure={localStockEquity} /> : <p className="text-sm text-muted-foreground">No equity chart available.</p>}</CardContent></Card>
                            </div>
                            <Card className="claude-card"><CardHeader className="pb-2"><CardTitle className="text-sm">Trade Ledger</CardTitle></CardHeader><CardContent><TradeLedgerTable rows={(stock.trade_ledger as Array<Record<string, unknown>>) ?? []} stockConfig={activeStrategyStockConfig} /></CardContent></Card>
                            <MetricTable rows={metricRowsFromValue(stock.trade_performance ?? stock.summary_metrics)} />
                          </TabsContent>
                        )
                      })}
                </Tabs>
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>

      <Dialog open={Boolean(renameRunId)} onOpenChange={(open) => { if (!open) { setRenameRunId(null); setRenameTitle("") } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Backtest</DialogTitle>
            <DialogDescription>Update the saved title. The run contents stay immutable.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="rename-backtest-title">Title</Label>
            <Input id="rename-backtest-title" value={renameTitle} onChange={(event) => setRenameTitle(event.target.value)} maxLength={200} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setRenameRunId(null); setRenameTitle("") }}>Cancel</Button>
            <Button onClick={submitRename} disabled={!renameTitle.trim()}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog open={Boolean(deleteRunId)} onOpenChange={(open) => { if (!open) setDeleteRunId(null) }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Saved Backtest</AlertDialogTitle>
            <AlertDialogDescription>This permanently removes the run and its persisted stock and WFO window details.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={confirmDelete}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}


export default function BacktestPage() {
  return (
    <Suspense fallback={<div className="space-y-4"><Skeleton className="h-32 rounded-xl" /><Skeleton className="h-72 rounded-xl" /></div>}>
      <BacktestContentSaved />
    </Suspense>
  )
}

