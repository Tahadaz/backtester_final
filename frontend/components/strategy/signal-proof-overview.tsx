"use client"

import useSWR from "swr"
import { AlertTriangle, CheckCircle2, CircleDashed, ShieldCheck } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalBadge } from "@/components/ui/signal-badge"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import { fetchEdge, type EdgeMetrics } from "@/lib/api"
import { formatNumber, formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"

type EdgeHorizon = "weekly" | "monthly" | "quarterly"
type EdgeSource = "signal_engine" | "wfo"

const EDGE_COST_BPS = 33

function edgeHorizon(horizon: string): EdgeHorizon {
  if (horizon === "short" || horizon === "weekly") return "weekly"
  if (horizon === "long" || horizon === "quarterly") return "quarterly"
  return "monthly"
}

function sourceLabel(source: EdgeSource) {
  return source === "signal_engine" ? "Signal Engine" : "WFO"
}

function actionLabel(edge: EdgeMetrics) {
  if (edge.direction === "long") return "Long"
  if (edge.direction === "short") return "Short"
  return "No trade"
}

function actionExpectedReturn(edge: EdgeMetrics) {
  return edge.action_expected_return_net ?? edge.expected_return_net ?? null
}

function actionExpectedReturnCi(edge: EdgeMetrics) {
  return {
    lower: edge.action_expected_return_net_ci_lower ?? edge.expected_return_net_ci_lower ?? null,
    upper: edge.action_expected_return_net_ci_upper ?? edge.expected_return_net_ci_upper ?? null,
  }
}

function GatePill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10px] font-semibold",
        ok
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-border bg-muted/30 text-muted-foreground",
      )}
    >
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <CircleDashed className="h-3 w-3" />}
      {label}
    </span>
  )
}

function MetricBox({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="rounded-md border border-border bg-background px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold">{value}</div>
      {sub ? <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

function EdgeProofCard({
  edge,
  loading,
  source,
}: {
  edge: EdgeMetrics | null | undefined
  loading: boolean
  source: EdgeSource
}) {
  if (loading && edge === undefined) {
    return <Skeleton className="h-[156px] rounded-md" />
  }

  if (!edge) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-semibold">{sourceLabel(source)}</div>
            <div className="mt-1 text-xs text-muted-foreground">Edge cache unavailable.</div>
          </div>
          <AlertTriangle className="h-4 w-4 text-muted-foreground" />
        </div>
      </div>
    )
  }

  const proven = edge.proven_edge_net
  const actionCi = actionExpectedReturnCi(edge)
  const stockCi = {
    lower: edge.stock_expected_return_ci_lower ?? null,
    upper: edge.stock_expected_return_ci_upper ?? null,
  }

  return (
    <div
      className={cn(
        "rounded-md border px-3 py-3",
        proven ? "border-emerald-200 bg-emerald-50/40" : "border-border bg-card",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{sourceLabel(source)}</span>
            <SignalBadge label={edge.bucket.replaceAll("_", " ")} />
          </div>
          <div className="mt-1 flex flex-wrap gap-1.5 text-[11px] text-muted-foreground">
            <Badge variant="outline" className="h-5 text-[10px]">
              {actionLabel(edge)}
            </Badge>
            <Badge variant="outline" className="h-5 text-[10px]">
              {edge.side_policy}
            </Badge>
            <Badge variant="outline" className="h-5 text-[10px]">
              n={edge.n}
            </Badge>
          </div>
        </div>
        <Badge
          variant={proven ? "default" : "outline"}
          className={cn("h-6 text-[10px]", !proven && "text-muted-foreground")}
        >
          {proven ? "Proven edge" : edge.n < 30 ? "Insufficient" : "Watch"}
        </Badge>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <MetricBox
          label="Action E[R] net"
          value={formatPercent(actionExpectedReturn(edge))}
          sub={`CI ${formatPercent(actionCi.lower)} to ${formatPercent(actionCi.upper)}`}
        />
        <MetricBox
          label="Holding"
          value={edge.fwd_horizon_bars != null ? `${edge.fwd_horizon_bars}d` : "--"}
          sub={edge.return_calc_method === "open_to_open" ? "open T+1 to open T+1+d" : edge.return_calc_method}
        />
        <MetricBox
          label="Stock E[R]"
          value={formatPercent(edge.stock_expected_return)}
          sub={`CI ${formatPercent(stockCi.lower)} to ${formatPercent(stockCi.upper)}`}
        />
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <GatePill ok={edge.gates.mc_net} label="MC" />
        <GatePill ok={edge.gates.label_shuffle_net} label="Shuffle" />
        <GatePill ok={edge.gates.wilson} label="Wilson" />
        <GatePill ok={edge.gates.n} label="N" />
      </div>
    </div>
  )
}

function WfoEvidenceCard({
  symbol,
  horizon,
  variant,
}: {
  symbol: string
  horizon: string
  variant: string
}) {
  const { data, isLoading, error } = useWfoSummary(symbol, horizon, variant)

  if (isLoading && !data) {
    return <Skeleton className="h-[156px] rounded-md" />
  }

  if (error) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-3">
        <div className="text-sm font-semibold">WFO evidence</div>
        <div className="mt-1 text-xs text-muted-foreground">{error}</div>
      </div>
    )
  }

  const global = data?.global_signal ?? null
  const categories = Object.values(data?.categories ?? {})
  const succeeded = categories.filter((category) => category.status === "succeeded").length
  const representativeCount = categories.reduce(
    (total, category) => total + category.representatives.length,
    0,
  )
  const bestCategory = global?.best_category ?? categories.find((category) => category.status === "succeeded")?.category
  const ready = global?.status === "succeeded"

  return (
    <div className="rounded-md border border-border bg-card px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">WFO evidence</span>
            {ready ? <SignalBadge label={global?.signal_label ?? global?.recommendation ?? null} /> : null}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            {ready ? "Consensus optimized out-of-sample." : "No WFO consensus ready."}
          </div>
        </div>
        <Badge variant="outline" className="h-6 text-[10px]">
          {succeeded}/{categories.length || 4} categories
        </Badge>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <MetricBox
          label="WFE"
          value={global?.consensus_wfe_pct != null ? `${formatNumber(global.consensus_wfe_pct, 1)}%` : "--"}
        />
        <MetricBox label="Robustness" value={formatNumber(global?.consensus_robustness, 2)} />
        <MetricBox label="Reps" value={String(representativeCount)} sub={bestCategory ?? "--"} />
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {categories.slice(0, 4).map((category) => (
          <Badge key={category.category} variant="outline" className="h-5 text-[10px]">
            {category.category}: {category.robustness_grade ?? category.status}
          </Badge>
        ))}
      </div>
    </div>
  )
}

export function SignalProofOverview({
  symbol,
  horizon,
  variant,
}: {
  symbol: string
  horizon: string
  variant: string
}) {
  const normalizedHorizon = edgeHorizon(horizon)
  const edgeKeyBase = `${symbol}-${normalizedHorizon}`
  const { data: signalEngineEdge, isLoading: signalEngineLoading } = useSWR(
    ["signal-proof-edge", edgeKeyBase, "signal_engine"],
    () => fetchEdge(symbol, normalizedHorizon, "signal_engine", EDGE_COST_BPS).catch(() => null),
    { revalidateOnFocus: false },
  )
  const { data: wfoEdge, isLoading: wfoLoading } = useSWR(
    ["signal-proof-edge", edgeKeyBase, "wfo"],
    () => fetchEdge(symbol, normalizedHorizon, "wfo", EDGE_COST_BPS).catch(() => null),
    { revalidateOnFocus: false },
  )

  return (
    <section className="rounded-lg border border-border bg-muted/20 p-3">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold">Proof overview</h2>
        </div>
        <Badge variant="outline" className="text-[10px]">
          {normalizedHorizon} - cost {EDGE_COST_BPS} bps/side
        </Badge>
      </div>
      <div className="grid gap-3 xl:grid-cols-3">
        <EdgeProofCard edge={signalEngineEdge} loading={signalEngineLoading} source="signal_engine" />
        <EdgeProofCard edge={wfoEdge} loading={wfoLoading} source="wfo" />
        <WfoEvidenceCard symbol={symbol} horizon={horizon} variant={variant} />
      </div>
    </section>
  )
}
