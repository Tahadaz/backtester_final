"use client"

import { useMemo, useState } from "react"
import type { ReactNode } from "react"
import useSWR from "swr"
import { Activity, BarChart3, CheckCircle2, Eye, EyeOff, Layers3, ListChecks } from "lucide-react"
import {
  fetchBestSignalBacktestChart,
  fetchBestSignalEvidence,
  fetchSignalBacktestResults,
  fetchSignalEvidence,
  type SignalEvidence,
  type SignalEvidenceContributor,
  type SignalEvidenceOosPeriod,
  type SignalBacktestResponse,
  type SignalEvidenceTrade,
  type SrOverlay,
} from "@/lib/api"
import { formatNumber, formatPercent } from "@/lib/format"
import { buildSignalEvidenceRangeView } from "@/lib/signal-evidence-range"
import { signalVariantLabel } from "@/lib/signal-variant-label"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { AccountingTradeLedgerTable } from "@/components/signals/trade-ledger-table"
import { PriceSignalsChart } from "@/components/signals/price-signals-chart"
import { GlobalFanChart } from "@/components/signals/fan-chart"

const EDGE_COST_BPS = 33

type EvidenceSource = "auto" | "signal_engine" | "wfo"
type EvidenceRangeKey = "all" | "5y" | "3y" | "1y" | "6m" | "3m"
type ProofLimitKey = "100" | "250" | "500" | "all"
type McVarStats = {
  var95?: number | null
  cvar95?: number | null
}

const EVIDENCE_RANGE_OPTIONS: Array<{ key: EvidenceRangeKey; label: string; days: number | null }> = [
  { key: "all", label: "All", days: null },
  { key: "5y", label: "5Y", days: 365 * 5 },
  { key: "3y", label: "3Y", days: 365 * 3 },
  { key: "1y", label: "1Y", days: 365 },
  { key: "6m", label: "6M", days: 183 },
  { key: "3m", label: "3M", days: 92 },
]

const PROOF_LIMIT_OPTIONS: Array<{ key: ProofLimitKey; label: string }> = [
  { key: "100", label: "100" },
  { key: "250", label: "250" },
  { key: "500", label: "500" },
  { key: "all", label: "All" },
]

interface SignalEvidenceTabProps {
  symbol: string
  horizon: string
  variant?: string | null
  source?: EvidenceSource
  selectedVariantId?: string | null
  cooldownBars?: number
}

function fmtDate(value: string | null | undefined) {
  if (!value) return "--"
  const normalized = value.includes("T") ? value : `${value}T00:00:00`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  })
}

function sourceLabel(source: string) {
  return source === "wfo" ? "WFO" : "Signal Engine"
}

function directionLabel(direction: string | null | undefined) {
  if (direction === "long") return "Long"
  if (direction === "short") return "Short"
  return "No trade"
}

function isActionableDirection(direction: string | null | undefined) {
  return direction === "long" || direction === "short"
}

function isOpaqueVariantId(value: string | null | undefined) {
  return /^sv_[0-9a-f]{8,}$/i.test(String(value ?? "").trim())
}

function readableContributorLabel(contributor: SignalEvidenceContributor) {
  const label = signalVariantLabel(contributor).trim()
  if (label && !isOpaqueVariantId(label)) return label
  const archetype = contributor.archetype ? contributor.archetype.replaceAll("_", " ") : ""
  const family = contributor.family ? contributor.family.replaceAll("_", " ") : ""
  return archetype || family || "Selected indicator"
}

function readableContributorDetail(contributor: SignalEvidenceContributor) {
  const archetype = contributor.archetype ? contributor.archetype.replaceAll("_", " ") : ""
  const family = contributor.family ? contributor.family.replaceAll("_", " ") : ""
  if (archetype && family && archetype !== family) return `${family} / ${archetype}`
  return archetype || family || "indicator"
}

function holdingLabel(edge: SignalEvidence["edge"]) {
  if (edge.exit_timing_label) return edge.exit_timing_label
  if (edge.fwd_horizon_bars != null) return `${edge.fwd_horizon_bars} bars`
  return "--"
}

function metricTone(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "text-foreground"
  return value >= 0 ? "text-[oklch(0.48_0.14_160)]" : "text-[oklch(0.52_0.20_25)]"
}

function dateKey(value: unknown): string | null {
  if (typeof value !== "string") return null
  const key = value.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(key) ? key : null
}

function evidenceRangeStart(dates: string[], range: EvidenceRangeKey): string | null {
  if (range === "all" || dates.length === 0) return null
  const option = EVIDENCE_RANGE_OPTIONS.find((item) => item.key === range)
  if (!option?.days) return null
  const lastDate = dateKey(dates[dates.length - 1])
  if (!lastDate) return null
  const [year, month, day] = lastDate.split("-").map(Number)
  if (!year || !month || !day) return null
  const cutoff = new Date(Date.UTC(year, month - 1, day))
  cutoff.setUTCDate(cutoff.getUTCDate() - option.days)
  return cutoff.toISOString().slice(0, 10)
}

function formatPvalue(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  if (value > 0 && value < 0.001) return "<0.001"
  return value.toFixed(3)
}

function signalBacktestMcStats(response: SignalBacktestResponse | null | undefined): McVarStats | null {
  if (!response?.results?.length) return null
  const result = response.results.find((row) => row.mc?.stats?.var95 != null || row.mc?.stats?.cvar95 != null)
  return result?.mc?.stats ?? null
}

function formatFiniteNumber(value: number | null | undefined, decimals = 2) {
  if (value === Number.POSITIVE_INFINITY) return "Inf"
  return formatNumber(value, decimals)
}

function formatMetricBasis(value: string | null | undefined) {
  const token = String(value ?? "").trim()
  if (!token) return "same-sample WFO"
  return token.replaceAll("_", " ")
}

function dateWindowLabel(start: string | null | undefined, end: string | null | undefined) {
  if (!start && !end) return "--"
  return `${fmtDate(start)} -> ${fmtDate(end)}`
}

function SrOverlaySummary({ overlay }: { overlay?: SrOverlay | null }) {
  if (!overlay) return null
  const decision = overlay.decision ?? overlay.status
  const ready = (overlay.status === "ready" || decision === "actionable") && overlay.overlay_metrics
  const bestLabel = overlay.best_variant_id?.replace(/^sr:/, "").replaceAll("__", " / ").replaceAll(":", " ")
  const rejected = !ready && overlay.decision && overlay.decision !== "actionable"
  return (
    <div className="rounded-md border border-line bg-muted/20 px-3 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">S/R execution overlay</h4>
          <p className="mt-1 text-xs text-muted-foreground">
            Baseline WFO signal replayed with support entry and resistance exit.
          </p>
        </div>
        <Badge variant={ready ? "default" : "outline"} className="h-6 rounded-md text-[11px]">
          {ready
            ? `${overlay.viable_count} viable / ${overlay.tested_count} tested`
            : rejected
              ? overlay.reason ?? decision
              : overlay.reason ?? "unavailable"}
        </Badge>
      </div>
      {ready ? (
        <div className="grid gap-3 md:grid-cols-4">
          <StatCard
            label="Baseline return"
            value={formatPercent(overlay.baseline_metrics.total_return)}
            detail={`trades ${formatNumber(overlay.baseline_metrics.n_trades, 0)}`}
          />
          <StatCard
            label="S/R return"
            value={formatPercent(overlay.overlay_metrics?.total_return)}
            detail={bestLabel ?? "best pair"}
            tone={metricTone(overlay.overlay_metrics?.total_return)}
          />
          <StatCard
            label="Return uplift"
            value={formatPercent(overlay.uplift.total_return)}
            detail={`${overlay.best_support_method ?? "--"} ${overlay.best_support_line ?? ""} / ${overlay.best_resistance_method ?? "--"} ${overlay.best_resistance_line ?? ""}`}
            tone={metricTone(overlay.uplift.total_return)}
          />
          <StatCard
            label="Drawdown uplift"
            value={formatPercent(overlay.uplift.max_drawdown)}
            detail="positive means lower drawdown"
            tone={metricTone(overlay.uplift.max_drawdown)}
          />
        </div>
      ) : null}
    </div>
  )
}

function DiagnosticMetric({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string
  detail?: string
  tone?: string
}) {
  return (
    <div className="min-w-0 rounded-md border border-line bg-background px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className={`mt-1 truncate font-mono text-sm font-semibold ${tone ?? ""}`}>{value}</div>
      {detail ? <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{detail}</div> : null}
    </div>
  )
}

function DiagnosticSection({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <div className="rounded-md border border-line bg-muted/10 px-3 py-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{children}</div>
    </div>
  )
}

function ToggleSectionButton({
  visible,
  onToggle,
  label,
}: {
  visible: boolean
  onToggle: () => void
  label: string
}) {
  const Icon = visible ? EyeOff : Eye
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={visible}
      className={`inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[11px] font-medium transition-colors ${
        visible
          ? "border-primary/60 bg-primary/10 text-primary"
          : "border-line bg-background text-muted-foreground hover:bg-muted/40"
      }`}
    >
      <Icon className="h-3.5 w-3.5" />
      {label}
    </button>
  )
}

function SectionTogglesBar({
  showSrOverlay,
  onToggleSrOverlay,
  showRiskDistribution,
  onToggleRiskDistribution,
}: {
  showSrOverlay: boolean
  onToggleSrOverlay: () => void
  showRiskDistribution: boolean
  onToggleRiskDistribution: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border border-dashed border-line bg-muted/10 px-3 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Optional sections
      </span>
      <ToggleSectionButton visible={showSrOverlay} onToggle={onToggleSrOverlay} label="S/R execution overlay" />
      <ToggleSectionButton
        visible={showRiskDistribution}
        onToggle={onToggleRiskDistribution}
        label="Risk & Distribution"
      />
    </div>
  )
}

function StitchedWfoEvidenceBacktest({ data, mcStats }: { data: SignalEvidence; mcStats?: McVarStats | null }) {
  const [range, setRange] = useState<EvidenceRangeKey>("all")
  const [showSrOverlay, setShowSrOverlay] = useState(false)
  const [showRiskDistribution, setShowRiskDistribution] = useState(false)
  const stitched = data.stitched_oos_backtest
  const visible = useMemo(() => {
    return buildSignalEvidenceRangeView(stitched, stitched ? evidenceRangeStart(stitched.dates, range) : null)
  }, [range, stitched])

  if (!stitched || stitched.dates.length < 2 || stitched.close_series.length < 2) {
    return (
      <Card className="rounded-md py-0">
        <CardHeader className="border-b border-line px-4 py-3">
          <CardTitle className="text-sm">WFO Stitched OOS Backtest</CardTitle>
        </CardHeader>
        <CardContent className="px-4 py-4">
          <p className="rounded-md border border-line bg-muted/20 p-3 text-sm text-muted-foreground">
            WFO stitched evidence is unavailable for this signal. Run WFO and score history for this stock/horizon first.
          </p>
        </CardContent>
      </Card>
    )
  }

  const metrics = visible.metrics
  const hasAction = isActionableDirection(stitched.direction)
  const cooldownBars = Math.max(0, Math.floor(stitched.cooldown_bars ?? stitched.metrics.cooldown_bars ?? 0))
  const cooldownFilteredTrades = Math.max(0, Math.floor(stitched.metrics.cooldown_filtered_trades ?? 0))
  const stockSampleCount = Array.isArray(visible.sampleTrades)
    ? visible.sampleTrades.length
    : Array.isArray(stitched.trades)
      ? stitched.trades.length
      : 0
  return (
    <Card className="overflow-hidden rounded-md py-0">
      <CardHeader className="border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="text-sm">WFO Stitched OOS Backtest</CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Fold winners applied to their own OOS periods / exact {bucketLabel(stitched.bucket)} bucket
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {EVIDENCE_RANGE_OPTIONS.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setRange(option.key)}
                className={`h-6 rounded-md border px-2 text-[11px] font-medium ${
                  range === option.key
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-line bg-background text-muted-foreground hover:bg-muted/40"
                }`}
              >
                {option.label}
              </button>
            ))}
            <Badge variant="outline" className="h-6 rounded-md text-[11px]">
              {stitched.score_mode.replaceAll("_", " ")}
            </Badge>
            <Badge variant="outline" className="h-6 rounded-md text-[11px]">
              {formatNumber(visible.ledger.length, 0)} movements
            </Badge>
            {cooldownBars > 0 ? (
              <Badge variant="outline" className="h-6 rounded-md text-[11px]">
                cooldown {cooldownBars} bars
                {cooldownFilteredTrades > 0 ? ` / ${cooldownFilteredTrades} filtered` : ""}
              </Badge>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 px-4 py-4">
        {stitched.warnings.length ? (
          <div className="rounded-md border border-amber-300 bg-amber-50/80 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/70 dark:bg-amber-950/30 dark:text-amber-200">
            {stitched.warnings.join(" ")}
          </div>
        ) : null}

        <SectionTogglesBar
          showSrOverlay={showSrOverlay}
          onToggleSrOverlay={() => setShowSrOverlay((prev) => !prev)}
          showRiskDistribution={showRiskDistribution}
          onToggleRiskDistribution={() => setShowRiskDistribution((prev) => !prev)}
        />
        {showSrOverlay ? <SrOverlaySummary overlay={stitched.sr_overlay ?? data.sr_overlay} /> : null}

        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Action E[R] net"
            value={hasAction ? formatPercent(metrics.expected_return_net) : "--"}
            detail={hasAction ? "Opened trades in range" : "Current signal is Hold / no trade"}
            tone={hasAction ? metricTone(metrics.expected_return_net) : undefined}
          />
          <StatCard
            label="Hit rate"
            value={hasAction ? formatPercent(metrics.hit_rate ?? metrics.win_rate) : "--"}
            detail={hasAction ? `n=${formatNumber(metrics.n_trades, 0)}` : "No directional trades"}
          />
          <StatCard
            label={hasAction ? "Return / notional" : "Stock E[R]"}
            value={formatPercent(hasAction ? metrics.total_return : (metrics.stock_expected_return ?? data.edge.stock_expected_return))}
            detail={hasAction ? "Realized PnL / opened notional" : `n=${formatNumber(stockSampleCount, 0)} neutral OOS samples`}
            tone={metricTone(hasAction ? metrics.total_return : (metrics.stock_expected_return ?? data.edge.stock_expected_return))}
          />
          <StatCard
            label="Trade Sharpe"
            value={hasAction ? formatNumber(metrics.sharpe, 2) : "--"}
            detail={hasAction ? "per-trade, freq-annualized" : "No action return stream"}
          />
        </div>

        {hasAction ? (
          <>
            {showRiskDistribution ? (
              <DiagnosticSection title="Risk & Distribution">
                <DiagnosticMetric
                  label="Max drawdown"
                  value={formatPercent(metrics.max_drawdown)}
                  detail="visible equity path"
                  tone="text-[oklch(0.52_0.20_25)]"
                />
                <DiagnosticMetric
                  label="Profit factor"
                  value={formatFiniteNumber(metrics.profit_factor_net, 2)}
                  detail="net wins / net losses"
                />
                <DiagnosticMetric
                  label="Avg win / loss"
                  value={`${formatPercent(metrics.avg_win_net)} / ${formatPercent(metrics.avg_loss_net)}`}
                  detail={`payoff ${formatFiniteNumber(metrics.payoff_ratio_net, 2)}`}
                />
                <DiagnosticMetric
                  label="Expectancy"
                  value={formatPercent(metrics.expected_return_net)}
                  detail={`median ${formatPercent(metrics.median_return_net)}`}
                  tone={metricTone(metrics.expected_return_net)}
                />
                {metrics.min_sample_pass ? (
                  <>
                    <DiagnosticMetric
                      label="Sortino"
                      value={formatFiniteNumber(metrics.sortino, 2)}
                      detail="daily path basis"
                      tone={metricTone(metrics.sortino)}
                    />
                    <DiagnosticMetric
                      label="Path Sharpe"
                      value={formatFiniteNumber(metrics.sharpe_path, 2)}
                      detail="daily path basis"
                      tone={metricTone(metrics.sharpe_path)}
                    />
                    <DiagnosticMetric
                      label="Tail returns"
                      value={`${formatPercent(metrics.p05_return_net)} / ${formatPercent(metrics.p95_return_net)}`}
                      detail="p05 / p95 net trade"
                    />
                    <DiagnosticMetric
                      label="Ann. volatility"
                      value={formatPercent(metrics.annualized_volatility)}
                      detail={`downside ${formatPercent(metrics.downside_volatility)}`}
                    />
                    <DiagnosticMetric
                      label="Hist VaR 95%"
                      value={formatPercent(metrics.var95)}
                      detail={metrics.var95 == null ? "minimum n=5 trades" : "5th pct net trade return"}
                      tone={metricTone(metrics.var95)}
                    />
                    <DiagnosticMetric
                      label="Hist CVaR 95%"
                      value={formatPercent(metrics.cvar95)}
                      detail={metrics.cvar95 == null ? "minimum n=5 trades" : "mean below VaR"}
                      tone={metricTone(metrics.cvar95)}
                    />
                    <DiagnosticMetric
                      label="MC VaR 95%"
                      value={formatPercent(mcStats?.var95)}
                      detail={mcStats?.var95 == null ? "MC unavailable" : "terminal return p05"}
                      tone={metricTone(mcStats?.var95)}
                    />
                    <DiagnosticMetric
                      label="MC CVaR 95%"
                      value={formatPercent(mcStats?.cvar95)}
                      detail={mcStats?.cvar95 == null ? "MC unavailable" : "terminal tail mean"}
                      tone={metricTone(mcStats?.cvar95)}
                    />
                    <DiagnosticMetric
                      label="Calmar"
                      value={formatFiniteNumber(metrics.calmar, 2)}
                      detail="daily path basis"
                      tone={metricTone(metrics.calmar)}
                    />
                  </>
                ) : (
                  <div className="min-w-0 rounded-md border border-dashed border-line bg-background px-3 py-2 text-xs text-muted-foreground sm:col-span-2 xl:col-span-4">
                    Distribution & tail metrics hidden - n&lt;30 (audit only)
                  </div>
                )}
              </DiagnosticSection>
            ) : null}

          </>
        ) : null}

        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {hasAction ? "Price + WFO OOS transactions" : "Price + WFO neutral sample"}
            </h4>
            <Badge variant="outline" className="h-6 rounded-md text-[11px]">
              {hasAction ? "Ledger markers" : "No action markers"}
            </Badge>
          </div>
          <PriceSignalsChart
            open={visible.open}
            high={visible.high}
            low={visible.low}
            close={visible.close}
            position={visible.position}
            dates={visible.dates}
            tradeMarkers={visible.chartMarkers}
            height={520}
            maxHeight={560}
          />
        </div>

        {hasAction ? (
          <DiagnosticSection title="Sample Quality">
            <DiagnosticMetric
              label="OOS trades"
              value={formatNumber(metrics.n_trades, 0)}
              detail={metrics.min_sample_pass ? "minimum sample passed" : "below n=30 evidence floor"}
              tone={metrics.min_sample_pass ? "text-[oklch(0.48_0.14_160)]" : "text-[oklch(0.52_0.20_25)]"}
            />
            <DiagnosticMetric
              label="Date window"
              value={dateWindowLabel(metrics.sample_start, metrics.sample_end)}
              detail={`${formatNumber(metrics.sample_days, 0)} bars in visible range`}
            />
            <DiagnosticMetric
              label="Cooldown filter"
              value={formatNumber(cooldownFilteredTrades, 0)}
              detail={`cooldown ${formatNumber(cooldownBars, 0)} bars`}
            />
            <div className="min-w-0 rounded-md border border-line bg-background px-3 py-2">
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Metric basis</div>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                <Badge variant="outline" className="h-5 rounded text-[10px]">
                  {formatMetricBasis(metrics.metric_basis)}
                </Badge>
                <Badge variant={metrics.min_sample_pass ? "default" : "outline"} className="h-5 rounded text-[10px]">
                  {metrics.min_sample_pass ? "n OK" : "audit only"}
                </Badge>
              </div>
            </div>
          </DiagnosticSection>
        ) : null}

        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Trades ledger
          </h4>
          {hasAction ? (
            <AccountingTradeLedgerTable trades={visible.ledger} />
          ) : (
            <p className="rounded-md border border-line bg-muted/20 p-3 text-sm text-muted-foreground">
              No action ledger is generated for a neutral Hold signal.
            </p>
          )}
        </div>

        {hasAction ? (
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Evidence PnL curve
            </h4>
            <GlobalFanChart
              equity={visible.equity}
              dates={visible.dates}
              envelope={null}
              stats={null}
              title="WFO stitched OOS realized PnL / notional"
            />
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function StatCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string
  value: string
  detail?: string
  tone?: string
}) {
  return (
    <div className="rounded-md border border-line bg-card px-3 py-3">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
      <div className={`mt-1 font-mono text-lg font-semibold ${tone ?? ""}`}>{value}</div>
      {detail ? <div className="mt-0.5 text-[11px] text-muted-foreground">{detail}</div> : null}
    </div>
  )
}

function ProofGateCard({
  ok,
  label,
  primaryLabel,
  primaryValue,
  secondary,
  detail,
}: {
  ok: boolean
  label: string
  primaryLabel: string
  primaryValue: string
  secondary: string
  detail?: string
}) {
  return (
    <div className={`rounded-md border px-3 py-3 ${ok ? "border-emerald-300 bg-emerald-50/40 dark:border-emerald-900/70 dark:bg-emerald-950/20" : "border-line bg-card"}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
          <div className="mt-1 font-mono text-lg font-semibold">{primaryValue}</div>
        </div>
        <Badge variant={ok ? "default" : "outline"} className="h-6 rounded-md text-[11px]">
          {ok ? <CheckCircle2 className="h-3 w-3" /> : null}
          {ok ? "OK" : "KO"}
        </Badge>
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">{primaryLabel}</div>
      <div className="mt-2 font-mono text-[11px] text-muted-foreground">{secondary}</div>
      {detail ? <div className="mt-1 text-[11px] text-muted-foreground">{detail}</div> : null}
    </div>
  )
}

function ProofGatesGrid({ edge }: { edge: SignalEvidence["edge"] }) {
  const gates = edge.gates
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Proof gates</h4>
          <p className="mt-1 text-xs text-muted-foreground">
            P-values come from edge proof tests. The path bootstrap below is a separate robustness view.
          </p>
        </div>
        <Badge variant={edge.proven_edge_net ? "default" : "outline"} className="h-6 rounded-md text-[11px]">
          Net proof {edge.proven_edge_net ? "passed" : "not passed"}
        </Badge>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        <ProofGateCard
          ok={Boolean(gates.mc_net)}
          label="MC luck p-value"
          primaryLabel="net, costs included"
          primaryValue={`p=${formatPvalue(edge.mc_luck_pvalue_net)}`}
          secondary={`gross p=${formatPvalue(edge.mc_luck_pvalue_gross)}`}
          detail={
            edge.mc_luck_pvalue_net_adj != null
              ? `adjusted net p=${formatPvalue(edge.mc_luck_pvalue_net_adj)}`
              : undefined
          }
        />
        <ProofGateCard
          ok={Boolean(gates.label_shuffle_net)}
          label="Label shuffle p-value"
          primaryLabel="net, costs included"
          primaryValue={`p=${formatPvalue(edge.label_shuffle_pvalue_net)}`}
          secondary={`gross p=${formatPvalue(edge.label_shuffle_pvalue_gross)}`}
          detail={
            edge.label_shuffle_pvalue_net_adj != null
              ? `adjusted net p=${formatPvalue(edge.label_shuffle_pvalue_net_adj)}`
              : undefined
          }
        />
        <ProofGateCard
          ok={Boolean(gates.wilson)}
          label="Wilson lower bound"
          primaryLabel="hit-rate confidence floor"
          primaryValue={formatNumber(edge.hit_ci_lower, 2)}
          secondary={`threshold > 0.50; hit ${formatPercent(edge.hit_rate)}`}
        />
        <ProofGateCard
          ok={Boolean(gates.n)}
          label="Sample size"
          primaryLabel="proof observations"
          primaryValue={formatNumber(edge.n, 0)}
          secondary="minimum n=30"
        />
        <ProofGateCard
          ok={Boolean(gates.freshness_net)}
          label="Freshness"
          primaryLabel="latest regime confirmation"
          primaryValue={formatNumber(edge.freshness_n, 0)}
          secondary={`minimum n=${formatNumber(edge.freshness_min_n, 0)}; net ${formatPercent(edge.freshness_action_expected_return_net)}`}
          detail={`${edge.freshness_window_start ?? "--"} -> ${edge.freshness_window_end ?? "--"}`}
        />
      </div>
    </div>
  )
}

function FactorConditionList({ contributor }: { contributor: SignalEvidenceContributor }) {
  if (!contributor.factor_conditions.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {contributor.factor_conditions.map((condition, index) => (
        <span
          key={`${condition.condition_id}-${condition.factor_ticker}-${index}`}
          className="inline-flex rounded border border-sky-300/60 bg-sky-50 px-2 py-1 text-[10px] text-sky-900 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-200"
        >
          {condition.factor_ticker || "factor"} / {condition.form || condition.condition_id}
          {condition.lookback != null ? ` L${formatNumber(condition.lookback, 0)}` : ""}
          {condition.threshold != null ? ` @ ${formatNumber(condition.threshold, 2)}` : ""}
          {condition.direction ? ` ${condition.direction}` : ""}
        </span>
      ))}
    </div>
  )
}

function ContributorRow({ contributor }: { contributor: SignalEvidenceContributor }) {
  const weight = contributor.normalized_weight ?? contributor.reliability_weight ?? null
  return (
    <div className="rounded-md border border-line bg-card px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="h-5 rounded text-[10px]">
              {contributor.category || "global"}
            </Badge>
            <Badge variant="outline" className="h-5 rounded text-[10px]">
              {contributor.family || "--"}
            </Badge>
            {contributor.is_factor_conditioned ? (
              <Badge variant="secondary" className="h-5 rounded text-[10px]">Factor x TA</Badge>
            ) : null}
          </div>
          <div className="mt-2 text-sm font-semibold">{readableContributorLabel(contributor)}</div>
          <div className="mt-1 max-w-3xl truncate font-mono text-[10px] text-muted-foreground">
            {readableContributorDetail(contributor)}
          </div>
        </div>
        <div className="grid min-w-[220px] grid-cols-3 gap-2 text-right">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Signal</div>
            <div className="text-xs font-semibold">{contributor.signal_label || "--"}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Weight</div>
            <div className="font-mono text-xs font-semibold">{formatNumber(weight, 3)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Value</div>
            <div className="font-mono text-xs font-semibold">{formatNumber(contributor.indicator_value, 3)}</div>
          </div>
        </div>
      </div>
      <FactorConditionList contributor={contributor} />
    </div>
  )
}

function bucketLabel(bucket: string | null | undefined) {
  const token = String(bucket ?? "").toLowerCase()
  if (token === "strong_sell") return "Vente forte"
  if (token === "sell") return "Vente"
  if (token === "strong_buy") return "Achat fort"
  if (token === "buy") return "Achat"
  if (token === "hold") return "Neutre"
  return token ? token.replaceAll("_", " ") : "--"
}

function priceKindLabel(value: string | null | undefined) {
  const token = String(value ?? "").toLowerCase()
  if (token === "open") return "Open"
  if (token === "close") return "Close"
  return token || "--"
}

function hitBadge(trade: SignalEvidenceTrade) {
  return trade.is_hit ? (
    <Badge variant="default" className="h-5 rounded text-[10px]">Hit</Badge>
  ) : (
    <Badge variant="outline" className="h-5 rounded text-[10px]">Miss</Badge>
  )
}

function CompactContributorList({ contributors }: { contributors: SignalEvidenceContributor[] }) {
  if (!contributors.length) {
    return <p className="text-xs text-muted-foreground">No persisted indicator detail for this OOS period.</p>
  }
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
      {contributors.map((contributor, index) => {
        const weight = contributor.normalized_weight ?? contributor.reliability_weight ?? null
        return (
          <div
            key={`${contributor.category}-${contributor.family}-${contributor.variant_id}-${index}`}
            className="min-w-0 rounded-md border border-line bg-card px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className="h-5 rounded text-[10px]">
                {contributor.category || "global"}
              </Badge>
              {contributor.family ? (
                <Badge variant="outline" className="h-5 rounded text-[10px]">
                  {contributor.family}
                </Badge>
              ) : null}
            </div>
            <div className="mt-1 truncate text-xs font-semibold">{readableContributorLabel(contributor)}</div>
            <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
              <span className="truncate">{readableContributorDetail(contributor)}</span>
              <span className="font-mono">{weight == null ? "" : formatNumber(weight, 3)}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function EvidenceTradeTable({ trades }: { trades: SignalEvidenceTrade[] }) {
  if (!trades.length) {
    return (
      <div className="rounded-md border border-dashed border-line px-4 py-6 text-center text-sm text-muted-foreground">
        No sampled trades in this period matched the selected signal bucket.
      </div>
    )
  }
  return (
    <div className="max-h-[360px] overflow-auto rounded-md border border-line">
      <table className="w-full min-w-[940px] text-xs">
        <thead className="sticky top-0 bg-muted/70">
          <tr>
            <th className="px-2 py-2 text-left font-medium">Signal</th>
            <th className="px-2 py-2 text-left font-medium">Entry</th>
            <th className="px-2 py-2 text-left font-medium">Exit</th>
            <th className="px-2 py-2 text-right font-medium">Global score</th>
            <th className="px-2 py-2 text-right font-medium">Stock return</th>
            <th className="px-2 py-2 text-right font-medium">Action net</th>
            <th className="px-2 py-2 text-center font-medium">Result</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {trades.map((trade, index) => (
            <tr key={`${trade.signal_date}-${trade.entry_date}-${index}`} className="hover:bg-muted/20">
              <td className="px-2 py-2">
                <div className="font-mono">{fmtDate(trade.signal_date)}</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">
                  {bucketLabel(trade.bucket)} / {directionLabel(trade.direction)}
                </div>
              </td>
              <td className="px-2 py-2">
                <div className="font-mono">{fmtDate(trade.entry_date)}</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">
                  {priceKindLabel(trade.entry_price_kind)} @ {formatNumber(trade.entry_price, 2)}
                </div>
              </td>
              <td className="px-2 py-2">
                <div className="font-mono">{fmtDate(trade.exit_date)}</div>
                <div className="mt-0.5 text-[10px] text-muted-foreground">
                  {trade.exit_timing_label || priceKindLabel(trade.exit_price_kind)} @ {formatNumber(trade.exit_price, 2)}
                </div>
              </td>
              <td className="px-2 py-2 text-right font-mono">{formatNumber(trade.score_pct, 2)}</td>
              <td className={`px-2 py-2 text-right font-mono font-semibold ${metricTone(trade.stock_return)}`}>
                {formatPercent(trade.stock_return)}
              </td>
              <td className={`px-2 py-2 text-right font-mono font-semibold ${metricTone(trade.action_return_net)}`}>
                {formatPercent(trade.action_return_net)}
              </td>
              <td className="px-2 py-2 text-center">{hitBadge(trade)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function EvidenceOosPeriodCard({ period }: { period: SignalEvidenceOosPeriod }) {
  return (
    <div className="rounded-md border border-line bg-muted/10">
      <div className="border-b border-line px-3 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="h-6 rounded-md text-[11px]">
                OOS #{period.window_index + 1}
              </Badge>
              {period.fold_id != null ? (
                <Badge variant="outline" className="h-6 rounded-md text-[11px]">
                  Fold {String(period.fold_id)}
                </Badge>
              ) : null}
              <span className="font-mono text-xs text-muted-foreground">
                {fmtDate(period.start_date)} {"->"} {fmtDate(period.end_date)}
              </span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {period.indicator_count} indicators / {period.sample_n} sampled trades
            </p>
          </div>
          <div className="grid min-w-[250px] grid-cols-3 gap-2 text-right">
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">E[R] net</div>
              <div className={`font-mono text-xs font-semibold ${metricTone(period.action_expected_return_net)}`}>
                {formatPercent(period.action_expected_return_net)}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Hit rate</div>
              <div className="font-mono text-xs font-semibold">{formatPercent(period.hit_rate)}</div>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Stock E[R]</div>
              <div className={`font-mono text-xs font-semibold ${metricTone(period.stock_expected_return)}`}>
                {formatPercent(period.stock_expected_return)}
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="space-y-3 px-3 py-3">
        <CompactContributorList contributors={period.contributors} />
        <EvidenceTradeTable trades={period.trades} />
      </div>
    </div>
  )
}

function EvidenceOosPeriods({ data, selectedVariantId }: { data: SignalEvidence; selectedVariantId?: string | null }) {
  const periods = data.oos_periods ?? []
  const edge = data.edge
  const stitched = data.stitched_oos_backtest
  const selectedContributor = selectedVariantId
    ? data.contributors.find((item) => item.variant_id === selectedVariantId)
    : null

  return (
    <Card className="rounded-md py-0">
      <CardHeader className="border-b border-line px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm">
              <ListChecks className="h-4 w-4" />
              OOS Trade Evidence
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              WFO / {bucketLabel(edge.bucket)} / {holdingLabel(edge)} / exact bucket
              {selectedContributor ? ` / selected indicator: ${readableContributorLabel(selectedContributor)}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="h-6 rounded-md text-[11px]">
              {formatNumber(stitched?.metrics.n_trades ?? data.evidence_trade_count ?? edge.n, 0)} sampled trades
            </Badge>
            <Badge variant="outline" className="h-6 rounded-md text-[11px]">
              {periods.length} OOS periods
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 px-4 py-4">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Action E[R] net"
            value={formatPercent(stitched?.metrics.expected_return_net ?? edge.action_expected_return_net ?? edge.expected_return_net)}
            detail="Mean of all WFO OOS trades"
            tone={metricTone(stitched?.metrics.expected_return_net ?? edge.action_expected_return_net ?? edge.expected_return_net)}
          />
          <StatCard
            label="Hit rate"
            value={formatPercent(stitched?.metrics.hit_rate ?? edge.hit_rate)}
            detail={`n=${formatNumber(stitched?.metrics.n_trades ?? edge.n, 0)}`}
          />
          <StatCard
            label="Signal bucket"
            value={bucketLabel(edge.bucket)}
            detail={directionLabel(edge.direction)}
          />
          <StatCard
            label="Holding"
            value={holdingLabel(edge)}
            detail={`${edge.return_calc_method} / costs ${edge.cost_bps_per_side} bps`}
          />
        </div>

        {periods.length ? (
          <div className="space-y-3">
            {periods.map((period) => (
              <EvidenceOosPeriodCard key={`${period.window_index}-${period.start_date}-${period.end_date}`} period={period} />
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed border-line px-4 py-8 text-center text-sm text-muted-foreground">
            OOS trade evidence is unavailable for this signal. The aggregate proof metrics above are still shown from the edge payload.
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SignalEvidenceContent({
  data,
  mcStats,
  selectedVariantId,
  proofLimit,
  onProofLimitChange,
}: {
  data: SignalEvidence
  mcStats?: McVarStats | null
  selectedVariantId?: string | null
  proofLimit: ProofLimitKey
  onProofLimitChange: (value: ProofLimitKey) => void
}) {
  const edge = data.edge

  return (
    <div className="space-y-4">
      <StitchedWfoEvidenceBacktest data={data} mcStats={mcStats} />

      <Card className="rounded-md py-0">
        <CardHeader className="border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="text-sm">Selected Signal Proof</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {data.method_label} / {edge.bucket?.replaceAll("_", " ") ?? "--"} / {directionLabel(edge.direction)}
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex overflow-hidden rounded-md border border-line">
                {PROOF_LIMIT_OPTIONS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => onProofLimitChange(option.key)}
                    className={`h-6 border-r border-line px-2 text-[11px] font-medium last:border-r-0 ${
                      proofLimit === option.key
                        ? "bg-primary text-primary-foreground"
                        : "bg-background text-muted-foreground hover:bg-muted/40"
                    }`}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <Badge variant={edge.proven_edge_net ? "default" : "outline"} className="h-6 rounded-md text-[11px]">
                {edge.proven_edge_net ? "Proven edge" : edge.n < 30 ? "Insufficient n" : "Watch"}
              </Badge>
              <Badge variant="outline" className="h-6 rounded-md text-[11px]">
                {sourceLabel(data.source)}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 px-4 py-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatCard
              label="Action E[R] net"
              value={formatPercent(edge.action_expected_return_net ?? edge.expected_return_net)}
              detail={`CI ${formatPercent(edge.action_expected_return_net_ci_lower ?? edge.expected_return_net_ci_lower)} -> ${formatPercent(edge.action_expected_return_net_ci_upper ?? edge.expected_return_net_ci_upper)}`}
              tone={metricTone(edge.action_expected_return_net ?? edge.expected_return_net)}
            />
            <StatCard
              label="Hit rate"
              value={formatPercent(edge.hit_rate)}
              detail={`Wilson ${formatNumber(edge.hit_ci_lower, 2)} -> ${formatNumber(edge.hit_ci_upper, 2)}`}
            />
            <StatCard
              label="OOS proof"
              value={`${fmtDate(data.oos.proof_window_start)} -> ${fmtDate(data.oos.proof_window_end)}`}
              detail={`n=${data.oos.proof_n ?? edge.n} / ${data.oos.proof_limit === "all" ? "all" : `latest ${data.oos.proof_limit ?? proofLimit}`} / ${data.oos.proof_method ?? "same_oos_sample"}`}
            />
            <StatCard
              label="Holding"
              value={holdingLabel(edge)}
              detail={`${edge.return_calc_method} / costs ${edge.cost_bps_per_side} bps per side`}
            />
          </div>

          <ProofGatesGrid edge={edge} />

          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-md border border-line bg-muted/20 px-3 py-3">
              <div className="flex items-center gap-2 text-xs font-semibold">
                <Activity className="h-3.5 w-3.5" />
                Current signal
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div>
                  <div className="text-muted-foreground">Score</div>
                  <div className="font-mono font-semibold">{formatNumber(data.current_signal.score_pct, 2)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Label</div>
                  <div className="font-semibold">{data.current_signal.signal_label ?? "--"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">As of</div>
                  <div className="font-mono font-semibold">{fmtDate(data.current_signal.data_as_of)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Best category</div>
                  <div className="font-semibold">{data.current_signal.best_category ?? "--"}</div>
                </div>
              </div>
            </div>
            <div className="rounded-md border border-line bg-muted/20 px-3 py-3">
              <div className="flex items-center gap-2 text-xs font-semibold">
                <BarChart3 className="h-3.5 w-3.5" />
                Selection window
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                <div>
                  <div className="text-muted-foreground">Period</div>
                  <div className="font-mono font-semibold">
                    {fmtDate(data.oos.selection_window_start)} {"->"} {fmtDate(data.oos.selection_window_end)}
                  </div>
                </div>
                <div>
                  <div className="text-muted-foreground">Selection n</div>
                  <div className="font-mono font-semibold">{data.oos.selection_n ?? "--"}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Selection Action E[R]</div>
                  <div className="font-mono font-semibold">{formatPercent(data.oos.selection_action_expected_return_net)}</div>
                </div>
                <div>
                  <div className="text-muted-foreground">Selection Hit</div>
                  <div className="font-mono font-semibold">{formatPercent(data.oos.selection_hit_rate)}</div>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-md py-0">
        <CardHeader className="border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Layers3 className="h-4 w-4" />
              WFO Signal Components
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="h-6 rounded-md text-[11px]">{data.contributor_count} components</Badge>
              <Badge variant="outline" className="h-6 rounded-md text-[11px]">{data.factor_condition_count} factor rules</Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-2 px-4 py-4">
          {data.contributors.length ? (
            data.contributors.map((contributor, index) => (
              <ContributorRow
                key={`${contributor.category}-${contributor.family}-${contributor.variant_id}-${index}`}
                contributor={contributor}
              />
            ))
          ) : (
            <div className="rounded-md border border-dashed border-line px-4 py-8 text-center text-sm text-muted-foreground">
              No representative indicator was persisted for this signal.
            </div>
          )}
        </CardContent>
      </Card>

      <EvidenceOosPeriods data={data} selectedVariantId={selectedVariantId} />
    </div>
  )
}

export function SignalEvidenceTab({
  symbol,
  horizon,
  variant,
  source = "auto",
  selectedVariantId = null,
  cooldownBars = 0,
}: SignalEvidenceTabProps) {
  const requestedVariant = variant || undefined
  const normalizedCooldownBars = Math.max(0, Math.floor(cooldownBars || 0))
  const useStoredBest = source === "auto" || (source === "wfo" && !requestedVariant)
  const [proofLimit, setProofLimit] = useState<ProofLimitKey>("100")
  const { data, error, isLoading } = useSWR(
    ["signal-evidence", useStoredBest ? "best" : "live", symbol, horizon, source, requestedVariant, normalizedCooldownBars, proofLimit],
    () =>
      useStoredBest
        ? fetchBestSignalEvidence({
            symbol,
            horizon,
            cooldownBars: normalizedCooldownBars,
          })
        : fetchSignalEvidence({
            symbol,
            horizon,
            source,
            variant: requestedVariant,
            costBps: EDGE_COST_BPS,
            cooldownBars: normalizedCooldownBars,
            proofLimit,
          }),
    { revalidateOnFocus: false },
  )
  const selectedDirection = data?.stitched_oos_backtest?.direction ?? data?.current_signal.direction ?? data?.edge.direction ?? null
  const { data: mcStats } = useSWR(
    data?.stitched_oos_backtest && isActionableDirection(selectedDirection)
      ? [
          "signal-evidence-mc-var",
          useStoredBest ? "best" : "live",
          symbol,
          horizon,
          data.source,
          data.variant,
          selectedDirection,
          normalizedCooldownBars,
        ]
      : null,
    async () => {
      try {
        const response = useStoredBest
          ? await fetchBestSignalBacktestChart(symbol, horizon, { cooldownBars: normalizedCooldownBars })
          : await fetchSignalBacktestResults(symbol, horizon, {
              source: data?.source,
              variant: data?.variant,
              selectedDirection,
              cooldownBars: normalizedCooldownBars,
            })
        return signalBacktestMcStats(response)
      } catch {
        return null
      }
    },
    { revalidateOnFocus: false },
  )

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-36 w-full rounded-md" />
        <Skeleton className="h-56 w-full rounded-md" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <Card className="rounded-md">
        <CardContent className="px-4 py-8 text-sm text-muted-foreground">
          {error instanceof Error ? error.message : "Signal evidence unavailable."}
        </CardContent>
      </Card>
    )
  }

  return (
    <SignalEvidenceContent
      data={data}
      mcStats={mcStats}
      selectedVariantId={selectedVariantId}
      proofLimit={proofLimit}
      onProofLimitChange={setProofLimit}
    />
  )
}
