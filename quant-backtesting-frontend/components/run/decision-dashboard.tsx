"use client"

import { useMemo } from "react"
import { Badge } from "@/components/ui/badge"
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
import type { DecisionDashboard, StrategyDecision } from "@/lib/api"
import { formatNumber } from "@/lib/format"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function formatValue(value: unknown, digits = 2): string {
  const num = toNumber(value)
  if (num !== null) return formatNumber(num, digits)
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE"
  if (value === null || value === undefined) return "n/a"
  if (typeof value === "string") return value || "n/a"
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function formatPct(value: unknown): string {
  const num = toNumber(value)
  if (num === null) return "n/a"
  return `${formatNumber(num * 100, 2)}%`
}

function decisionBadgeClass(direction: string): string {
  const d = direction.toLowerCase()
  if (d === "long") return "bg-emerald-100 text-emerald-800"
  if (d === "short") return "bg-rose-100 text-rose-800"
  return "bg-slate-200 text-slate-700"
}

function statusBadgeClass(status: string): string {
  const s = status.toLowerCase()
  if (s === "trade") return "bg-emerald-100 text-emerald-800"
  if (s === "watch") return "bg-amber-100 text-amber-800"
  return "bg-slate-200 text-slate-700"
}

type DecisionDashboardProps = {
  decision: StrategyDecision
  dashboard: DecisionDashboard | null
  loading: boolean
}

export function DecisionDashboardView({
  decision,
  dashboard,
  loading,
}: DecisionDashboardProps) {
  const chartData = useMemo(() => {
    if (!dashboard) return []
    const ts = dashboard.timeseries
    return ts.t.map((t, i) => ({
      t: t.slice(0, 10),
      close: toNumber(ts.close[i]),
      smaRef: toNumber(ts.sma_ref[i]),
      sma200: toNumber(ts.sma200[i]),
      rsi14: toNumber(ts.rsi14[i]),
      adx: toNumber(ts.adx[i]),
      atr: toNumber(ts.atr[i]),
      signal: toNumber(ts.signal_markers.find((m) => m.t === ts.t[i])?.direction),
    }))
  }, [dashboard])

  const zoomData = chartData.slice(-120)
  const regimeChecks = (dashboard?.regime?.rule_checks as Array<Record<string, unknown>>) ?? []
  const signalChecks = dashboard?.signal_debug?.checks ?? []
  const reasons = (dashboard?.decision_summary?.reasons as Array<Record<string, unknown>>) ?? []
  const levels = (dashboard?.levels ?? {}) as Record<string, unknown>
  const confidenceLayers = (dashboard?.confidence_layers ?? []) as Array<Record<string, unknown>>
  const frameworks = ((dashboard?.framework_comparison?.frameworks as Array<Record<string, unknown>>) ?? [])
  const allIdentical = Boolean((dashboard?.framework_comparison?.all_identical as boolean | undefined) ?? false)

  if (loading && !dashboard) {
    return (
      <Card className="border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Decision Dashboard</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-80 w-full" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (!dashboard) {
    return (
      <Card className="border-border">
        <CardContent className="py-8 text-sm text-muted-foreground">
          Decision dashboard data is not available.
        </CardContent>
      </Card>
    )
  }

  const direction = String(dashboard.decision_summary.direction ?? decision.decision_page.direction ?? "neutral")
  const status = String(dashboard.decision_summary.status ?? decision.status ?? "watch")
  const rr = toNumber(dashboard.decision_summary.rr)

  return (
    <Card className="border-border">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">
          {decision.symbol} - {decision.strategy_kind}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Tabs defaultValue="decision" className="w-full">
          <TabsList className="mb-2 h-auto w-full flex-wrap justify-start gap-1">
            <TabsTrigger value="decision">A. Decision</TabsTrigger>
            <TabsTrigger value="params">B. Strategy Parameters</TabsTrigger>
            <TabsTrigger value="regime">C. Regime & Context</TabsTrigger>
            <TabsTrigger value="signal">D. Signal & Triggers</TabsTrigger>
            <TabsTrigger value="risk">E. Risk & Levels</TabsTrigger>
            <TabsTrigger value="confidence">F. Confidence Layers</TabsTrigger>
            <TabsTrigger value="frameworks">G. Framework Comparison</TabsTrigger>
          </TabsList>

          <TabsContent value="decision" className="space-y-3">
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
              <div className="rounded-md bg-secondary/30 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Direction</p>
                <Badge className={decisionBadgeClass(direction)}>{direction.toUpperCase()}</Badge>
              </div>
              <div className="rounded-md bg-secondary/30 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Status</p>
                <Badge className={statusBadgeClass(status)}>{status.toUpperCase()}</Badge>
              </div>
              <div className="rounded-md bg-secondary/30 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Opportunity</p>
                <p className="font-mono text-sm">{formatValue(dashboard.decision_summary.opportunity, 1)}</p>
              </div>
              <div className="rounded-md bg-secondary/30 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Confidence</p>
                <p className="font-mono text-sm">{formatValue(dashboard.decision_summary.confidence, 1)}</p>
              </div>
              <div className="rounded-md bg-secondary/30 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">RR</p>
                <p className="font-mono text-sm">{rr === null ? "n/a" : formatNumber(rr, 2)}</p>
              </div>
              <div className="rounded-md bg-secondary/30 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Regime</p>
                <p className="text-sm font-semibold">{String(dashboard.regime.label ?? "n/a")}</p>
              </div>
            </div>

            <div className="rounded-md border border-border p-2">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Levels
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
                <p>Entry: <span className="font-mono">{formatValue(levels.entry, 2)}</span></p>
                <p>Stop: <span className="font-mono">{formatValue(levels.stop, 2)}</span></p>
                <p>Target: <span className="font-mono">{formatValue(levels.target, 2)}</span></p>
                <p>Support: <span className="font-mono">{formatValue(levels.support, 2)}</span></p>
                <p>Resistance: <span className="font-mono">{formatValue(levels.resistance, 2)}</span></p>
              </div>
            </div>

            <div className="h-56 rounded-md border border-border p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="t" />
                  <YAxis domain={["auto", "auto"]} />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="close" stroke="#0f172a" dot={false} name="Close" />
                  <Line type="monotone" dataKey="smaRef" stroke="#2563eb" dot={false} name="SMA Ref" />
                  <Line type="monotone" dataKey="sma200" stroke="#16a34a" dot={false} name="SMA200" />
                  {toNumber(levels.entry) !== null ? <ReferenceLine y={toNumber(levels.entry)!} stroke="#f59e0b" strokeDasharray="5 5" label="Entry" /> : null}
                  {toNumber(levels.stop) !== null ? <ReferenceLine y={toNumber(levels.stop)!} stroke="#dc2626" strokeDasharray="5 5" label="Stop" /> : null}
                  {toNumber(levels.target) !== null ? <ReferenceLine y={toNumber(levels.target)!} stroke="#16a34a" strokeDasharray="5 5" label="Target" /> : null}
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div className="rounded-md border border-border p-2">
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Top 3 Reasons
              </p>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Reason</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead>Detail</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reasons.map((r, idx) => (
                    <TableRow key={`reason-${idx}`}>
                      <TableCell>{formatValue(r.name, 0)}</TableCell>
                      <TableCell className="text-right font-mono">{formatValue(r.score, 1)}</TableCell>
                      <TableCell>{formatValue(r.detail, 0)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </TabsContent>

          <TabsContent value="params" className="space-y-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Key</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Impact</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dashboard.strategy_params.map((row) => (
                  <TableRow key={row.key}>
                    <TableCell className="font-mono">{row.key}</TableCell>
                    <TableCell className="font-mono">{formatValue(row.value)}</TableCell>
                    <TableCell>{row.description}</TableCell>
                    <TableCell>{row.impact}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="grid gap-2 sm:grid-cols-3">
              {Object.entries(dashboard.derived_metrics).map(([k, v]) => (
                <div key={k} className="rounded-md border border-border bg-secondary/20 p-2">
                  <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{k}</p>
                  <p className="font-mono text-sm">
                    {k.includes("ratio") || k.includes("distance") || k.includes("slope") ? formatPct(v) : formatValue(v)}
                  </p>
                </div>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="regime" className="space-y-2">
            <div className="h-64 rounded-md border border-border p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="t" />
                  <YAxis yAxisId="price" domain={["auto", "auto"]} />
                  <YAxis yAxisId="osc" orientation="right" domain={[0, 100]} />
                  <Tooltip />
                  <Legend />
                  <Line yAxisId="price" type="monotone" dataKey="close" stroke="#0f172a" dot={false} name="Close" />
                  <Line yAxisId="price" type="monotone" dataKey="sma200" stroke="#16a34a" dot={false} name="SMA200" />
                  <Line yAxisId="osc" type="monotone" dataKey="rsi14" stroke="#f59e0b" dot={false} name="RSI14" />
                  <Line yAxisId="osc" type="monotone" dataKey="adx" stroke="#9333ea" dot={false} name="ADX" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Rule</TableHead>
                  <TableHead>Expr</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Threshold</TableHead>
                  <TableHead className="text-center">Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {regimeChecks.map((check, idx) => (
                  <TableRow key={`regime-${idx}`}>
                    <TableCell>{formatValue(check.name, 0)}</TableCell>
                    <TableCell>{formatValue(check.expr, 0)}</TableCell>
                    <TableCell className="font-mono">{formatValue(check.value)}</TableCell>
                    <TableCell className="font-mono">{formatValue(check.threshold)}</TableCell>
                    <TableCell className="text-center">{check.pass ? "✅" : "❌"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TabsContent>

          <TabsContent value="signal" className="space-y-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Condition</TableHead>
                  <TableHead>Expr</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead>Threshold</TableHead>
                  <TableHead className="text-center">Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {signalChecks.map((check) => (
                  <TableRow key={check.name}>
                    <TableCell>{check.name}</TableCell>
                    <TableCell>{check.expr}</TableCell>
                    <TableCell className="font-mono">{formatValue(check.value)}</TableCell>
                    <TableCell className="font-mono">{formatValue(check.threshold)}</TableCell>
                    <TableCell className="text-center">{check.pass ? "✅" : "❌"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="rounded-md border border-border p-2 text-xs">
              Final direction:{" "}
              <span className="font-mono">
                {dashboard.signal_debug.final_direction_label.toUpperCase()} ({dashboard.signal_debug.final_direction})
              </span>
            </div>
            <div className="h-64 rounded-md border border-border p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={zoomData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="t" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="close" stroke="#0f172a" dot={false} name="Close" />
                  <Line type="monotone" dataKey="smaRef" stroke="#2563eb" dot={false} name="SMA Ref" />
                  <Scatter
                    name="Signal"
                    data={zoomData.filter((row) => row.signal !== null && row.signal !== 0)}
                    dataKey="close"
                    fill="#dc2626"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </TabsContent>

          <TabsContent value="risk" className="space-y-2">
            <div className="grid gap-2 sm:grid-cols-3">
              <div className="rounded-md border border-border bg-secondary/20 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">RR</p>
                <p className="font-mono text-sm">{formatValue(dashboard.levels.rr ?? dashboard.decision_summary.rr, 2)}</p>
              </div>
              <div className="rounded-md border border-border bg-secondary/20 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Risk / Share</p>
                <p className="font-mono text-sm">{formatValue((dashboard.levels as Record<string, unknown>).risk_per_share, 2)}</p>
              </div>
              <div className="rounded-md border border-border bg-secondary/20 p-2">
                <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Reward / Share</p>
                <p className="font-mono text-sm">{formatValue((dashboard.levels as Record<string, unknown>).reward_per_share, 2)}</p>
              </div>
            </div>
            <div className="h-64 rounded-md border border-border p-2">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="t" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="close" stroke="#0f172a" dot={false} name="Close" />
                  {toNumber(levels.support) !== null ? <ReferenceLine y={toNumber(levels.support)!} stroke="#38bdf8" label="Support" /> : null}
                  {toNumber(levels.resistance) !== null ? <ReferenceLine y={toNumber(levels.resistance)!} stroke="#f97316" label="Resistance" /> : null}
                  {toNumber(levels.entry) !== null ? <ReferenceLine y={toNumber(levels.entry)!} stroke="#f59e0b" strokeDasharray="5 5" label="Entry" /> : null}
                  {toNumber(levels.stop) !== null ? <ReferenceLine y={toNumber(levels.stop)!} stroke="#dc2626" strokeDasharray="5 5" label="Stop" /> : null}
                  {toNumber(levels.target) !== null ? <ReferenceLine y={toNumber(levels.target)!} stroke="#16a34a" strokeDasharray="5 5" label="Target" /> : null}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </TabsContent>

          <TabsContent value="confidence" className="space-y-2">
            <div className="h-60 rounded-md border border-border p-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={confidenceLayers.map((layer) => ({
                    name: String(layer.name ?? "layer"),
                    score: toNumber(layer.score),
                  }))}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Bar dataKey="score" fill="#0ea5e9" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Layer</TableHead>
                  <TableHead className="text-right">Score</TableHead>
                  <TableHead>Metrics</TableHead>
                  <TableHead>Impact</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {confidenceLayers.map((layer, idx) => (
                  <TableRow key={`conf-${idx}`}>
                    <TableCell>{formatValue(layer.name, 0)}</TableCell>
                    <TableCell className="text-right font-mono">{formatValue(layer.score, 1)}</TableCell>
                    <TableCell className="font-mono">{formatValue(layer.metrics)}</TableCell>
                    <TableCell>{formatValue(layer.impact, 0)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TabsContent>

          <TabsContent value="frameworks" className="space-y-2">
            {allIdentical ? (
              <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
                {String(dashboard.framework_comparison.note ?? "All frameworks identical.")}
              </div>
            ) : null}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Opportunity</TableHead>
                  <TableHead className="text-right">Confidence</TableHead>
                  <TableHead className="text-right">RR</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {frameworks.map((row, idx) => (
                  <TableRow key={`fw-${idx}`}>
                    <TableCell>{formatValue(row.strategy_kind, 0)}</TableCell>
                    <TableCell>{formatValue(row.direction, 0)}</TableCell>
                    <TableCell>{formatValue(row.status, 0)}</TableCell>
                    <TableCell className="text-right font-mono">{formatValue(row.opportunity, 1)}</TableCell>
                    <TableCell className="text-right font-mono">{formatValue(row.confidence, 1)}</TableCell>
                    <TableCell className="text-right font-mono">{formatValue(row.rr, 2)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  )
}

