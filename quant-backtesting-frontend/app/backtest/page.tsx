"use client"

import Link from "next/link"
import { Suspense, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
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
import { useStrategies, useStrategy } from "@/hooks/use-api"
import {
  fetchStrategyBacktest,
  type PlotlyFigure,
  type StrategyBacktestMetricRow,
  type StrategyBacktestResponse,
} from "@/lib/api"
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format"

function formatDateInput(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, "0")
  const day = String(date.getDate()).padStart(2, "0")
  return `${year}-${month}-${day}`
}

function todayIso() {
  return formatDateInput(new Date())
}

const DEFAULT_START_DATE = "2026-01-01"

function formatSidePolicy(value: string) {
  return value === "long_short" ? "Long/Short" : "Long Only"
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

function renderMetric(label: string, value: unknown) {
  const numeric = toNumber(value)
  if (numeric == null) return "--"
  const key = label.toLowerCase()
  if (key.includes("return") || key.includes("drawdown") || key.includes("win")) {
    return formatPercent(numeric)
  }
  if (key.includes("pnl") || key.includes("fee") || key.includes("capital")) {
    return formatCurrency(numeric)
  }
  return formatNumber(numeric, 2)
}

function MetricTable({ rows }: { rows: StrategyBacktestMetricRow[] }) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">No trade performance rows yet.</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border/70">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-secondary/20">
            <th className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Metric</th>
            <th className="px-3 py-2 text-right text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.metric} className="border-b border-border/50 last:border-0">
              <td className="px-3 py-2 text-foreground">{row.metric}</td>
              <td className="px-3 py-2 text-right font-mono text-xs">{renderMetric(row.metric, row.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StrategySummary({ strategy }: { strategy: Record<string, unknown> }) {
  const basket = Array.isArray(strategy.basket) ? strategy.basket.map((item) => String(item)) : []
  const enabledFamilies = Array.isArray(strategy.enabled_families)
    ? strategy.enabled_families.map((item) => String(item).toUpperCase())
    : []

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Capital</p>
        <p className="mt-1 text-lg font-semibold text-foreground">
          {formatCurrency(toNumber(strategy.capital_mad) ?? 0)}
        </p>
      </div>
      <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Basket</p>
        <p className="mt-1 text-lg font-semibold text-foreground">{basket.length} stocks</p>
        <p className="mt-1 text-xs text-muted-foreground">{basket.slice(0, 4).join(", ") || "--"}</p>
      </div>
      <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Signal Families</p>
        <p className="mt-1 text-lg font-semibold text-foreground">{enabledFamilies.length}</p>
        <p className="mt-1 text-xs text-muted-foreground">{enabledFamilies.join(" / ") || "--"}</p>
      </div>
      <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
        <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Risk</p>
        <p className="mt-1 text-lg font-semibold text-foreground">
          {formatNumber(toNumber((strategy.risk as Record<string, unknown> | undefined)?.max_holding_bars) ?? 0, 0)} bars
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          stop ATR x {formatNumber(toNumber((strategy.risk as Record<string, unknown> | undefined)?.stop_atr_multiplier) ?? 0, 2)}
        </p>
      </div>
    </div>
  )
}

function BacktestContent() {
  const searchParams = useSearchParams()
  const searchStrategyId = searchParams.get("strategyId")

  const [selectedStrategyId, setSelectedStrategyId] = useState<string | null>(searchStrategyId)
  const [startDate, setStartDate] = useState(DEFAULT_START_DATE)
  const [endDate, setEndDate] = useState(todayIso())
  const [running, setRunning] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [result, setResult] = useState<StrategyBacktestResponse | null>(null)
  const [activeStock, setActiveStock] = useState<string | null>(null)

  const [costModel, setCostModel] = useState({
    brokerage_bps: 0.2,
    comm_bourse_bps: 0.1,
    reg_liv_bps: 0,
    slippage_bps: 0,
    tva_rate: 0.1,
  })
  const [volumeGateEnabled, setVolumeGateEnabled] = useState(false)
  const [volumeGateKind, setVolumeGateKind] = useState<"min_abs" | "min_ratio_adv">("min_ratio_adv")
  const [volumeGateMinAbs, setVolumeGateMinAbs] = useState(50_000)
  const [volumeGateMinRatioAdv, setVolumeGateMinRatioAdv] = useState(0.1)
  const [volumeGateAdvWindow, setVolumeGateAdvWindow] = useState(20)
  const [cooldownEnabled, setCooldownEnabled] = useState(false)
  const [cooldownBars, setCooldownBars] = useState(10)

  const { data: strategies, isLoading: strategiesLoading } = useStrategies()
  const { data: strategy } = useStrategy(selectedStrategyId)

  useEffect(() => {
    if (searchStrategyId) {
      setSelectedStrategyId(searchStrategyId)
    }
  }, [searchStrategyId])

  useEffect(() => {
    if (!result?.stocks?.length) {
      setActiveStock(null)
      return
    }
    if (!activeStock || !result.stocks.some((stock) => stock.symbol === activeStock)) {
      setActiveStock(result.stocks[0].symbol)
    }
  }, [activeStock, result?.stocks])

  const selectedListItem = useMemo(
    () => (strategies ?? []).find((item) => item.id === selectedStrategyId) ?? null,
    [selectedStrategyId, strategies],
  )

  const strategySummaryData = useMemo(() => {
    if (result?.strategy && Object.keys(result.strategy).length > 0) {
      return result.strategy as Record<string, unknown>
    }
    if (!strategy) return null
    const config = strategy.config_json as Record<string, unknown>
    const capital = (config.capital as Record<string, unknown> | undefined) ?? {}
    const universe = (config.universe as Record<string, unknown> | undefined) ?? {}
    const signal = (config.signal as Record<string, unknown> | undefined) ?? {}
    const logic = (config.logic as Record<string, unknown> | undefined) ?? {}
    const risk = (config.risk as Record<string, unknown> | undefined) ?? {}
    return {
      capital_mad: capital.total_capital_mad,
      basket: Array.isArray(universe.basket) ? universe.basket : [],
      enabled_families: Array.isArray(signal.enabled_families)
        ? signal.enabled_families
        : Array.isArray(logic.enabled_families)
          ? logic.enabled_families
          : [],
      risk,
    } satisfies Record<string, unknown>
  }, [result?.strategy, strategy])

  async function runBacktest() {
    if (!selectedStrategyId) return
    setRunning(true)
    setErrorMessage(null)
    try {
      const next = await fetchStrategyBacktest({
        strategy_id: selectedStrategyId,
        start_date: startDate,
        end_date: endDate,
        family_history_mode: "dynamic_point_in_time",
        cost_model: costModel,
        volume_gate: {
          enabled: volumeGateEnabled,
          kind: volumeGateKind,
          min_volume_abs: volumeGateMinAbs,
          min_volume_ratio_adv: volumeGateMinRatioAdv,
          adv_window: volumeGateAdvWindow,
        },
        cooldown_bars: cooldownEnabled ? cooldownBars : 0,
      })
      setResult(next)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Backtest failed")
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  const generalCumFigure = asFigure(result?.general_results?.plots?.cumreturn_vs_benchmark)
  const generalDdFigure = asFigure(result?.general_results?.plots?.drawdown)
  const generalMonthlyFigure = asFigure(result?.general_results?.plots?.monthly_heatmap)
  const calibrationFigure = asFigure(result?.general_results?.calibration?.plot)
  const activeStockResult = useMemo(
    () => result?.stocks.find((stock) => stock.symbol === activeStock) ?? result?.stocks[0] ?? null,
    [activeStock, result?.stocks],
  )

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">Backtest</h1>
          <p className="text-sm text-muted-foreground">
            Pick a saved strategy, set the historical window, and inspect strategy-level results before drilling into each stock.
          </p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={selectedStrategyId ? `/strategy?strategyId=${selectedStrategyId}` : "/strategy"}>
            Open Strategy
          </Link>
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Setup</CardTitle>
          <CardDescription>
            Strategy definition comes from the saved strategy. This page only adds direct backtest assumptions.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr_1fr]">
            <div className="space-y-2">
              <Label>Saved strategy</Label>
              {strategiesLoading ? (
                <Skeleton className="h-10 rounded-md" />
              ) : (
                <Select
                  value={selectedStrategyId ?? undefined}
                  onValueChange={(value) => {
                    setSelectedStrategyId(value)
                    setResult(null)
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a saved strategy" />
                  </SelectTrigger>
                  <SelectContent>
                    {(strategies ?? []).map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.name} • {formatSidePolicy(item.side_policy)} • {item.horizon} • {item.basket_count} stocks • {item.updated_at.slice(0, 10)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
            <div className="space-y-2">
              <Label>Start date</Label>
              <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label>End date</Label>
              <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
            </div>
          </div>

          {strategySummaryData ? <StrategySummary strategy={strategySummaryData} /> : null}

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="border-dashed">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Costs</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>Brokerage (bps)</Label>
                  <Input type="number" value={costModel.brokerage_bps} onChange={(event) => setCostModel((prev) => ({ ...prev, brokerage_bps: Number(event.target.value) }))} />
                </div>
                <div className="space-y-1.5">
                  <Label>Comm. bourse (bps)</Label>
                  <Input type="number" value={costModel.comm_bourse_bps} onChange={(event) => setCostModel((prev) => ({ ...prev, comm_bourse_bps: Number(event.target.value) }))} />
                </div>
                <div className="space-y-1.5">
                  <Label>Reg/Liv (bps)</Label>
                  <Input type="number" value={costModel.reg_liv_bps} onChange={(event) => setCostModel((prev) => ({ ...prev, reg_liv_bps: Number(event.target.value) }))} />
                </div>
                <div className="space-y-1.5">
                  <Label>Slippage (bps)</Label>
                  <Input type="number" value={costModel.slippage_bps} onChange={(event) => setCostModel((prev) => ({ ...prev, slippage_bps: Number(event.target.value) }))} />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label>TVA rate</Label>
                  <Input type="number" step="0.01" value={costModel.tva_rate} onChange={(event) => setCostModel((prev) => ({ ...prev, tva_rate: Number(event.target.value) }))} />
                </div>
              </CardContent>
            </Card>

            <Card className="border-dashed">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Volume constraints</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>Enable volume gate</Label>
                  <Switch checked={volumeGateEnabled} onCheckedChange={setVolumeGateEnabled} />
                </div>
                <div className="space-y-1.5">
                  <Label>Mode</Label>
                  <Select value={volumeGateKind} onValueChange={(value) => setVolumeGateKind(value as "min_abs" | "min_ratio_adv")}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="min_ratio_adv">Min ratio ADV</SelectItem>
                      <SelectItem value="min_abs">Min absolute volume</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {volumeGateKind === "min_abs" ? (
                  <div className="space-y-1.5">
                    <Label>Minimum volume</Label>
                    <Input type="number" value={volumeGateMinAbs} onChange={(event) => setVolumeGateMinAbs(Number(event.target.value))} />
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <Label>Minimum ratio ADV</Label>
                    <Input type="number" step="0.01" value={volumeGateMinRatioAdv} onChange={(event) => setVolumeGateMinRatioAdv(Number(event.target.value))} />
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label>ADV window</Label>
                  <Input type="number" value={volumeGateAdvWindow} onChange={(event) => setVolumeGateAdvWindow(Number(event.target.value))} />
                </div>
              </CardContent>
            </Card>

            <Card className="border-dashed">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Cooldown</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>Enable cooldown</Label>
                  <Switch checked={cooldownEnabled} onCheckedChange={setCooldownEnabled} />
                </div>
                <div className="space-y-1.5">
                  <Label>Cooldown bars</Label>
                  <Input type="number" value={cooldownBars} onChange={(event) => setCooldownBars(Number(event.target.value))} disabled={!cooldownEnabled} />
                </div>
                <Button onClick={runBacktest} disabled={!selectedStrategyId || running} className="w-full">
                  {running ? "Running..." : "Run Backtest"}
                </Button>
                {selectedListItem ? (
                  <p className="text-xs text-muted-foreground">
                    {selectedListItem.name} • {formatSidePolicy(selectedListItem.side_policy)} • {selectedListItem.horizon} • updated {selectedListItem.updated_at.slice(0, 10)}
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </div>

          {errorMessage ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {errorMessage}
            </div>
          ) : null}
        </CardContent>
      </Card>

      {running ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-72 rounded-xl" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      ) : null}

      {result ? (
        <>
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">General Results</CardTitle>
              <CardDescription>
                Strategy-level view first. Benchmark is initial allocated basket buy-and-hold.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {([
                  ["Net PnL", result.general_results.metrics.net_pnl],
                  ["Total Return", result.general_results.metrics.total_return],
                  ["CAGR", result.general_results.metrics.cagr],
                  ["Sharpe", result.general_results.metrics.sharpe],
                  ["Max Drawdown", result.general_results.metrics.max_drawdown],
                  ["Win Rate", result.general_results.metrics.win_rate],
                  ["Trades", result.general_results.metrics.number_of_trades],
                  ["Total Fees", result.general_results.metrics.total_fees],
                ] as Array<[string, unknown]>).map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                    <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{label}</p>
                    <p className="mt-1 text-lg font-semibold text-foreground">{renderMetric(label, value)}</p>
                  </div>
                ))}
              </div>

              <div className="grid gap-4 xl:grid-cols-2">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Cumulative Return vs Benchmark</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {generalCumFigure ? <PlotlyChart figure={generalCumFigure} /> : <p className="text-sm text-muted-foreground">No cumulative plot available.</p>}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Drawdown</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {generalDdFigure ? <PlotlyChart figure={generalDdFigure} /> : <p className="text-sm text-muted-foreground">No drawdown plot available.</p>}
                  </CardContent>
                </Card>
              </div>

              <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Monthly Heatmap</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {generalMonthlyFigure ? <PlotlyChart figure={generalMonthlyFigure} /> : <p className="text-sm text-muted-foreground">No monthly heatmap available.</p>}
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm">Trade Performance</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <MetricTable rows={result.general_results.trade_performance} />
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Sizing Calibration</CardTitle>
                  <CardDescription>
                    Ladder frozen for this run using only history before the selected start date.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                    <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Status</p>
                      <p className="mt-1 text-lg font-semibold text-foreground">{String(result.general_results.calibration.status ?? "--")}</p>
                    </div>
                    <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Lookback</p>
                      <p className="mt-1 text-lg font-semibold text-foreground">{formatNumber(toNumber(result.general_results.calibration.lookback_bars) ?? 0, 0)} bars</p>
                    </div>
                    <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Observations</p>
                      <p className="mt-1 text-lg font-semibold text-foreground">{formatNumber(toNumber(result.general_results.calibration.n_observations) ?? 0, 0)}</p>
                    </div>
                    <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Metric</p>
                      <p className="mt-1 text-lg font-semibold text-foreground">{String(result.general_results.calibration.primary_metric ?? "--")}</p>
                    </div>
                    <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Window Start</p>
                      <p className="mt-1 text-lg font-semibold text-foreground">{String(result.general_results.calibration.window_start ?? "--")}</p>
                    </div>
                    <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                      <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Window End</p>
                      <p className="mt-1 text-lg font-semibold text-foreground">{String(result.general_results.calibration.window_end ?? "--")}</p>
                    </div>
                  </div>

                  {result.general_results.calibration.reason ? (
                    <div className="rounded-lg border border-border/70 bg-secondary/20 px-3 py-2 text-sm text-muted-foreground">
                      {String(result.general_results.calibration.reason)}
                    </div>
                  ) : null}

                  <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">Calibration Plot</CardTitle>
                      </CardHeader>
                      <CardContent>
                        {calibrationFigure ? <PlotlyChart figure={calibrationFigure} /> : <p className="text-sm text-muted-foreground">No calibration plot available.</p>}
                      </CardContent>
                    </Card>
                    <Card>
                      <CardHeader className="pb-2">
                        <CardTitle className="text-sm">Exposure Ladder</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="overflow-x-auto rounded-lg border border-border/70">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="border-b border-border bg-secondary/20">
                                {["Abs score range", "Target exposure", "Obs", "Avg R", "Avg return", "Win rate"].map((label) => (
                                  <th key={label} className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                                    {label}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {result.general_results.calibration.bucket_rows.length === 0 ? (
                                <tr>
                                  <td colSpan={6} className="px-3 py-4 text-sm text-muted-foreground">
                                    No calibrated bucket rows available for this run.
                                  </td>
                                </tr>
                              ) : (
                                result.general_results.calibration.bucket_rows.map((row, index) => (
                                  <tr key={`cal-row-${index}`} className="border-b border-border/50 last:border-0">
                                    <td className="px-3 py-2 font-mono text-xs">{formatNumber(row.score_low, 1)} - {formatNumber(row.score_high, 1)}</td>
                                    <td className="px-3 py-2 font-mono text-xs">{formatPercent(row.target_exposure_pct / 100)}</td>
                                    <td className="px-3 py-2 font-mono text-xs">{formatNumber(row.n_observations, 0)}</td>
                                    <td className="px-3 py-2 font-mono text-xs">{formatNumber(row.avg_r_multiple, 2)}</td>
                                    <td className="px-3 py-2 font-mono text-xs">{formatPercent(row.avg_net_return)}</td>
                                    <td className="px-3 py-2 font-mono text-xs">{formatPercent(row.win_rate)}</td>
                                  </tr>
                                ))
                              )}
                            </tbody>
                          </table>
                        </div>
                      </CardContent>
                    </Card>
                  </div>
                </CardContent>
              </Card>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">By Stock</CardTitle>
              <CardDescription>
                Stock tabs contain the detailed diagnostics: price chart, execution markers, trade ledger, and trade performance.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Tabs value={activeStock ?? undefined} onValueChange={setActiveStock}>
                <TabsList className="h-auto flex-wrap justify-start">
                  {result.stocks.map((stock) => (
                    <TabsTrigger key={stock.symbol} value={stock.symbol}>
                      {stock.symbol}
                    </TabsTrigger>
                  ))}
                </TabsList>

                {activeStockResult ? (() => {
                  const stock = activeStockResult
                  const figure = asFigure(stock.price_chart)
                  const allocation = stock.allocation as Record<string, unknown>
                  const summaryMetrics = stock.summary_metrics as Record<string, unknown>
                  return (
                    <TabsContent key={stock.symbol} value={stock.symbol} className="space-y-4">
                      <div className="grid gap-3 md:grid-cols-4">
                        <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Allocation</p>
                          <p className="mt-1 text-lg font-semibold text-foreground">{formatCurrency(toNumber(allocation.capital_mad) ?? 0)}</p>
                        </div>
                        <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Weight</p>
                          <p className="mt-1 text-lg font-semibold text-foreground">{formatPercent((toNumber(allocation.weight_pct) ?? 0) / 100)}</p>
                        </div>
                        <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Net PnL</p>
                          <p className="mt-1 text-lg font-semibold text-foreground">{formatCurrency(toNumber(summaryMetrics.net_pnl) ?? 0)}</p>
                        </div>
                        <div className="rounded-lg border border-border/70 bg-secondary/20 p-3">
                          <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Trades</p>
                          <p className="mt-1 text-lg font-semibold text-foreground">{formatNumber(toNumber(summaryMetrics.n_trades) ?? 0, 0)}</p>
                        </div>
                      </div>

                      <Card>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">Price + Trades</CardTitle>
                        </CardHeader>
                        <CardContent>
                          {figure ? <PlotlyChart figure={figure} /> : <p className="text-sm text-muted-foreground">No price chart available.</p>}
                        </CardContent>
                      </Card>

                      <div className="grid gap-4 xl:grid-cols-[0.7fr_1.3fr]">
                        <Card>
                          <CardHeader className="pb-2">
                            <CardTitle className="text-sm">Trade Performance</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <MetricTable rows={stock.trade_performance} />
                          </CardContent>
                        </Card>

                        <Card>
                          <CardHeader className="pb-2">
                            <CardTitle className="text-sm">Trade Ledger</CardTitle>
                          </CardHeader>
                          <CardContent>
                            {stock.trade_ledger.length === 0 ? (
                              <p className="text-sm text-muted-foreground">No executed trades for this stock in the selected period.</p>
                            ) : (
                              <div className="overflow-x-auto rounded-lg border border-border/70">
                                <table className="w-full text-sm">
                                  <thead>
                                    <tr className="border-b border-border bg-secondary/20">
                                      {["Date", "Side", "Qty", "Price", "Signal", "CMP", "PnL realised", "PnL latent", "Cost"].map((label) => (
                                        <th key={label} className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                                          {label}
                                        </th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {stock.trade_ledger.map((row, index) => {
                                      const record = row as Record<string, unknown>
                                      return (
                                        <tr key={`${stock.symbol}-${index}`} className="border-b border-border/50 last:border-0">
                                          <td className="px-3 py-2 text-xs">{String(record.timestamp ?? "").slice(0, 10)}</td>
                                          <td className="px-3 py-2 text-xs">{String(record.side ?? "--")}</td>
                                          <td className="px-3 py-2 text-right font-mono text-xs">{formatNumber(toNumber(record.quantite) ?? 0, 0)}</td>
                                          <td className="px-3 py-2 text-right font-mono text-xs">{formatNumber(toNumber(record.prix_execution_open_jour) ?? 0, 2)}</td>
                                          <td className="px-3 py-2 text-right font-mono text-xs">{formatNumber(toNumber(record.signal_score) ?? 0, 1)}</td>
                                          <td className="px-3 py-2 text-right font-mono text-xs">{formatNumber(toNumber(record.cmp) ?? 0, 2)}</td>
                                          <td className="px-3 py-2 text-right font-mono text-xs">{formatNumber(toNumber(record.pnl_realise) ?? 0, 2)}</td>
                                          <td className="px-3 py-2 text-right font-mono text-xs">{formatNumber(toNumber(record.pnl_latent) ?? 0, 2)}</td>
                                          <td className="px-3 py-2 text-right font-mono text-xs">{formatNumber(toNumber(record.cost) ?? 0, 2)}</td>
                                        </tr>
                                      )
                                    })}
                                  </tbody>
                                </table>
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      </div>
                    </TabsContent>
                  )
                })() : null}
              </Tabs>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  )
}

export default function BacktestPage() {
  return (
    <Suspense
      fallback={
        <div className="space-y-4">
          <Skeleton className="h-40 rounded-xl" />
          <Skeleton className="h-72 rounded-xl" />
        </div>
      }
    >
      <BacktestContent />
    </Suspense>
  )
}
