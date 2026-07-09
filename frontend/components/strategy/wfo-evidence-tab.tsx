"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Activity, AlertCircle, BarChart3, CheckCircle2, ExternalLink, Gauge, Layers, RefreshCw, Settings, TrendingUp } from "lucide-react"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import {
  fetchSignalEvidence,
  fetchSrWfo,
  fetchWfoDetail,
  triggerWfoComputation,
  type SrOverlay,
  type SrWfoPairMeta,
  type SrWfoResponse,
  type WfoCategoryDetail,
  type WfoCategorySummary,
  type WfoRepresentative,
} from "@/lib/api"
import { formatWfoFoldRange } from "@/lib/wfo-fold-display"
import { formatNumber, formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalBadge } from "@/components/ui/signal-badge"
import { SignalScoreBar } from "./signal-score-bar"

const EDGE_COST_BPS = 33

type BaseCategoryId = "tendance" | "momentum" | "oscillation" | "volume"
type SyntheticCategoryId = "sr_execution" | "sr_wfo"
type CategoryId = BaseCategoryId | SyntheticCategoryId

type CategoryMeta = {
  id: CategoryId
  label: string
  icon: typeof TrendingUp
  synthetic?: boolean
}

const CATEGORY_META: CategoryMeta[] = [
  { id: "tendance", label: "Tendance", icon: TrendingUp },
  { id: "momentum", label: "Momentum", icon: Activity },
  { id: "oscillation", label: "Oscillation", icon: Activity },
  { id: "volume", label: "Volume", icon: BarChart3 },
  { id: "sr_execution", label: "S/R Execution", icon: Gauge, synthetic: true },
  { id: "sr_wfo", label: "S/R Walk-Forward", icon: Layers, synthetic: true },
]

const SYNTHETIC_CATEGORY_IDS: SyntheticCategoryId[] = ["sr_execution", "sr_wfo"]

function isSyntheticCategory(id: CategoryId): id is SyntheticCategoryId {
  return (SYNTHETIC_CATEGORY_IDS as CategoryId[]).includes(id)
}

const BASE_CATEGORY_META = CATEGORY_META.filter((meta): meta is CategoryMeta & { id: BaseCategoryId } => !meta.synthetic)

const GRADE_COLORS: Record<string, string> = {
  A: "bg-green-600 text-white",
  B: "bg-green-500 text-white",
  C: "bg-yellow-500 text-black",
  D: "bg-orange-500 text-white",
  F: "bg-red-500 text-white",
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function compactDate(value: string | null | undefined): string {
  if (!value) return "--"
  const normalized = value.includes("T") ? value : `${value}T00:00:00`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, {
    month: "2-digit",
    day: "2-digit",
    year: "2-digit",
  })
}

function pct(value: number | null | undefined, decimals = 1): string {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${value.toFixed(decimals)}%`
}

function decimalPct(value: unknown, decimals = 2): string {
  const n = asNumber(value)
  if (n == null) return "--"
  return `${(n * 100).toFixed(decimals)}%`
}

function scoreTone(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground"
  if (score > 15) return "text-[oklch(0.50_0.13_165)]"
  if (score < -15) return "text-[oklch(0.52_0.20_25)]"
  return "text-muted-foreground"
}

function scoreText(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "--"
  return `${score >= 0 ? "+" : ""}${score.toFixed(1)}%`
}

function ConfigItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background p-2">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-xs font-semibold">{value}</div>
    </div>
  )
}

function MetricBox({
  label,
  value,
  sub,
  valueClassName,
}: {
  label: string
  value: string
  sub?: string
  valueClassName?: string
}) {
  return (
    <div className="rounded-md border bg-background p-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div className={cn("mt-1 font-mono text-sm font-semibold", valueClassName)}>{value}</div>
      {sub ? <div className="mt-0.5 text-[10px] text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

type CategoryButtonSummary = Pick<
  WfoCategorySummary,
  "status" | "score_pct" | "signal_label" | "representatives" | "wfe_pct" | "robustness_grade"
> & {
  badges?: string[]
}

function CategoryButton({
  meta,
  summary,
  selected,
  onSelect,
}: {
  meta: CategoryMeta
  summary: CategoryButtonSummary | undefined
  selected: boolean
  onSelect: () => void
}) {
  const Icon = meta.icon
  const succeeded = summary?.status === "succeeded"
  const extraBadges = summary?.badges ?? []
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-left transition-colors",
        selected ? "border-primary bg-primary/5" : "border-border bg-card hover:border-primary/40",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="truncate text-xs font-semibold">{meta.label}</span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {summary?.robustness_grade ? (
            <Badge className={cn("h-5 px-1.5 text-[9px] font-bold", GRADE_COLORS[summary.robustness_grade] ?? "")}>
              {summary.robustness_grade}
            </Badge>
          ) : null}
          <span className={cn("font-mono text-xs font-semibold", scoreTone(summary?.score_pct))}>
            {scoreText(summary?.score_pct)}
          </span>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant="outline" className="h-5 text-[9px]">
          {summary?.status ?? "pending"}
        </Badge>
        {extraBadges.length ? (
          extraBadges.map((badge) => (
            <Badge key={badge} variant="outline" className="h-5 text-[9px]">
              {badge}
            </Badge>
          ))
        ) : succeeded ? (
          <>
            <Badge variant="outline" className="h-5 text-[9px]">
              WFE {pct(summary?.wfe_pct, 0)}
            </Badge>
            <Badge variant="outline" className="h-5 text-[9px]">
              Reps {summary?.representatives.length ?? 0}
            </Badge>
          </>
        ) : null}
      </div>
    </button>
  )
}

function RepresentativesTable({
  reps,
  symbol,
  horizon,
  variant,
}: {
  reps: WfoRepresentative[]
  symbol: string
  horizon: string
  variant: string
}) {
  const router = useRouter()

  if (reps.length === 0) {
    return (
      <div className="rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
        Aucun representant WFO selectionne.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b bg-muted/30 text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Variante</th>
            <th className="px-3 py-2 text-left font-medium">Famille</th>
            <th className="px-3 py-2 text-center font-medium">Signal</th>
            <th className="px-3 py-2 text-right font-medium">Poids</th>
            <th className="px-3 py-2 text-right font-medium">Contribution</th>
            <th className="px-3 py-2 text-right font-medium">PROM</th>
          </tr>
        </thead>
        <tbody>
          {reps.map((rep) => (
            <tr
              key={rep.variant_id}
              className="cursor-pointer border-b border-border/50 hover:bg-muted/30"
              onClick={() =>
                router.push(
                  `/signals/variant/${encodeURIComponent(rep.variant_id)}?symbol=${encodeURIComponent(symbol)}&horizon=${horizon}&variant=${variant}`,
                )
              }
            >
              <td className="px-3 py-2">
                <div className="flex items-center gap-1.5">
                  <span className="font-medium">{rep.description || rep.variant_id}</span>
                  <ExternalLink className="h-3 w-3 text-muted-foreground" />
                </div>
                <div className="font-mono text-[9px] text-muted-foreground">{rep.variant_id}</div>
              </td>
              <td className="px-3 py-2">
                <Badge variant="outline" className="text-[9px]">{rep.family}</Badge>
              </td>
              <td className="px-3 py-2 text-center">
                <SignalBadge label={rep.signal_label} />
              </td>
              <td className="px-3 py-2 text-right font-mono">{pct(rep.normalized_weight * 100, 1)}</td>
              <td className="px-3 py-2 text-right font-mono">
                <span className={scoreTone(rep.contribution * 100)}>{formatNumber(rep.contribution, 4)}</span>
              </td>
              <td className="px-3 py-2 text-right font-mono">
                {rep.wfo_prom != null ? decimalPct(rep.wfo_prom, 3) : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function FoldTable({ folds }: { folds: Array<Record<string, unknown>> }) {
  if (folds.length === 0) {
    return (
      <div className="rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
        Aucun detail de fold disponible.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b bg-muted/30 text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Fold</th>
            <th className="px-3 py-2 text-left font-medium">Train</th>
            <th className="px-3 py-2 text-left font-medium">OOS</th>
            <th className="px-3 py-2 text-right font-medium">IS return</th>
            <th className="px-3 py-2 text-right font-medium">OOS return</th>
            <th className="px-3 py-2 text-right font-medium">Sharpe</th>
            <th className="px-3 py-2 text-left font-medium">Gagnant</th>
            <th className="px-3 py-2 text-right font-medium">PROM</th>
          </tr>
        </thead>
        <tbody>
          {folds.map((fold, index) => {
            const profitable = Boolean(fold.oos_profitable)
            return (
              <tr
                key={`${asString(fold.index) || index}`}
                className={cn("border-b border-border/50", profitable ? "bg-green-50/30" : "bg-red-50/20")}
              >
                <td className="px-3 py-2 font-medium">#{asNumber(fold.index) != null ? Number(fold.index) + 1 : index + 1}</td>
                <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                  {formatWfoFoldRange(fold, "train")}
                </td>
                <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                  {formatWfoFoldRange(fold, "oos")}
                </td>
                <td className="px-3 py-2 text-right font-mono">{decimalPct(fold.is_return)}</td>
                <td className="px-3 py-2 text-right font-mono">{decimalPct(fold.oos_return)}</td>
                <td className="px-3 py-2 text-right font-mono">{formatNumber(asNumber(fold.oos_sharpe), 2)}</td>
                <td className="max-w-[220px] truncate px-3 py-2" title={asString(fold.winner_variant_id)}>
                  {asString(fold.winner_description) || asString(fold.winner_variant_id) || "--"}
                </td>
                <td className="px-3 py-2 text-right font-mono">{decimalPct(fold.winner_prom, 3)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

type SrOverlayVariant = SrOverlay["top_variants"][number]

function returnTone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "text-foreground"
  return value >= 0 ? "text-[oklch(0.50_0.13_165)]" : "text-[oklch(0.52_0.20_25)]"
}

function formatSrReason(reason: string): string {
  if (reason === "baseline_has_no_positions") return "Sans positions directionnelles"
  if (reason === "source_not_wfo") return "Source non WFO"
  if (reason === "not_requested") return "Non demande"
  return reason
}

function SrOverlayStatusCard({
  overlay,
  error,
}: {
  overlay: SrOverlay | null
  error: string | null
}) {
  const rawReason = error ?? overlay?.reason ?? overlay?.status ?? "unavailable"
  const reason = formatSrReason(rawReason)
  return (
    <Card>
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="flex items-center gap-2 text-sm font-bold">
          <Gauge className="h-4 w-4 text-muted-foreground" />
          S/R Execution Overlay
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4">
        <p className="rounded-md border border-dashed bg-muted/20 p-3 text-sm text-muted-foreground">
          {reason}
        </p>
        {overlay ? (
          <div className="grid gap-2 sm:grid-cols-4">
            <MetricBox label="Tested" value={formatNumber(overlay.tested_count, 0)} />
            <MetricBox label="Viable" value={formatNumber(overlay.viable_count, 0)} />
            <MetricBox label="Invalid pairs" value={formatNumber(overlay.invalid_pair_count, 0)} />
            <MetricBox label="Unavailable" value={formatNumber(overlay.unavailable_count, 0)} />
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function SrOverlayVariantsTable({ variants }: { variants: SrOverlayVariant[] }) {
  if (!variants.length) {
    return (
      <div className="rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
        Aucun couple S/R viable disponible.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-[860px] text-xs">
        <thead>
          <tr className="border-b bg-muted/30 text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Couple</th>
            <th className="px-3 py-2 text-right font-medium">Support</th>
            <th className="px-3 py-2 text-right font-medium">Resistance</th>
            <th className="px-3 py-2 text-right font-medium">S/R return</th>
            <th className="px-3 py-2 text-right font-medium">Return uplift</th>
            <th className="px-3 py-2 text-right font-medium">DD uplift</th>
            <th className="px-3 py-2 text-right font-medium">Trades</th>
            <th className="px-3 py-2 text-right font-medium">Rank</th>
          </tr>
        </thead>
        <tbody>
          {variants.map((row) => (
            <tr key={row.variant_id} className="border-b border-border/50 hover:bg-muted/30">
              <td className="px-3 py-2">
                <div className="font-medium">{row.support_method ?? "--"} / {row.resistance_method ?? "--"}</div>
                <div className="font-mono text-[9px] text-muted-foreground">{row.variant_id}</div>
              </td>
              <td className="px-3 py-2 text-right">
                <div className="font-mono">{formatNumber(row.support_level, 2)}</div>
                <div className="text-[9px] text-muted-foreground">{row.support_line ?? "--"}</div>
              </td>
              <td className="px-3 py-2 text-right">
                <div className="font-mono">{formatNumber(row.resistance_level, 2)}</div>
                <div className="text-[9px] text-muted-foreground">{row.resistance_line ?? "--"}</div>
              </td>
              <td className={cn("px-3 py-2 text-right font-mono font-semibold", returnTone(row.metrics?.total_return))}>
                {formatPercent(row.metrics?.total_return)}
              </td>
              <td className={cn("px-3 py-2 text-right font-mono font-semibold", returnTone(row.uplift?.total_return))}>
                {formatPercent(row.uplift?.total_return)}
              </td>
              <td className={cn("px-3 py-2 text-right font-mono font-semibold", returnTone(row.uplift?.max_drawdown))}>
                {formatPercent(row.uplift?.max_drawdown)}
              </td>
              <td className="px-3 py-2 text-right font-mono">{formatNumber(row.trade_count, 0)}</td>
              <td className="px-3 py-2 text-right font-mono">{formatNumber(row.rank_score, 4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SrOverlayTradesTable({ trades }: { trades: Array<Record<string, unknown>> }) {
  if (!trades.length) {
    return (
      <div className="rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
        Aucun trade S/R recent pour le meilleur couple.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-[720px] text-xs">
        <thead>
          <tr className="border-b bg-muted/30 text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Entry</th>
            <th className="px-3 py-2 text-left font-medium">Exit</th>
            <th className="px-3 py-2 text-right font-medium">Open</th>
            <th className="px-3 py-2 text-right font-medium">Close</th>
            <th className="px-3 py-2 text-right font-medium">Bars</th>
            <th className="px-3 py-2 text-right font-medium">P&L</th>
            <th className="px-3 py-2 text-left font-medium">Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, index) => {
            const pnl = asNumber(trade.pnl_return)
            return (
              <tr key={`${asString(trade.open_date)}-${asString(trade.close_date)}-${index}`} className="border-b border-border/50">
                <td className="px-3 py-2 font-mono">{compactDate(asString(trade.open_date))}</td>
                <td className="px-3 py-2 font-mono">{compactDate(asString(trade.close_date))}</td>
                <td className="px-3 py-2 text-right font-mono">{formatNumber(asNumber(trade.open_price), 2)}</td>
                <td className="px-3 py-2 text-right font-mono">{formatNumber(asNumber(trade.close_price), 2)}</td>
                <td className="px-3 py-2 text-right font-mono">{formatNumber(asNumber(trade.bars_held), 0)}</td>
                <td className={cn("px-3 py-2 text-right font-mono font-semibold", returnTone(pnl))}>{formatPercent(pnl)}</td>
                <td className="px-3 py-2">
                  {asString(trade.entry_reason) || "--"} {"->"} {asString(trade.exit_reason) || "--"}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SrOverlayDetailPanel({
  overlay,
  isLoading,
  error,
}: {
  overlay: SrOverlay | null
  isLoading: boolean
  error: string | null
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-md" />
        <Skeleton className="h-56 w-full rounded-md" />
      </div>
    )
  }

  const ready = (overlay?.status === "actionable" || overlay?.status === "research_only") && overlay.overlay_metrics
  if (!ready) return <SrOverlayStatusCard overlay={overlay} error={error} />

  const bestVariant =
    overlay.top_variants.find((row) => row.variant_id === overlay.best_variant_id) ??
    overlay.top_variants[0] ??
    null
  const bestTrades = bestVariant?.trades ?? []

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm font-bold">
                <Gauge className="h-4 w-4 text-primary" />
                S/R Execution Overlay
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                WFO signal replayed with support-entry / resistance-exit execution.
              </p>
            </div>
            <Badge variant="outline" className="h-6 text-[10px]">
              {overlay.viable_count} viable / {overlay.tested_count} tested
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 px-4 pb-4 sm:grid-cols-4">
          <MetricBox
            label="Baseline return"
            value={formatPercent(overlay.baseline_metrics.total_return)}
            sub={`trades ${formatNumber(overlay.baseline_metrics.n_trades, 0)}`}
            valueClassName={returnTone(overlay.baseline_metrics.total_return)}
          />
          <MetricBox
            label="S/R return"
            value={formatPercent(overlay.overlay_metrics?.total_return)}
            sub={overlay.best_variant_id ?? "best pair"}
            valueClassName={returnTone(overlay.overlay_metrics?.total_return)}
          />
          <MetricBox
            label="Return uplift"
            value={formatPercent(overlay.uplift.total_return)}
            sub={`${overlay.best_support_method ?? "--"} ${overlay.best_support_line ?? ""} / ${overlay.best_resistance_method ?? "--"} ${overlay.best_resistance_line ?? ""}`}
            valueClassName={returnTone(overlay.uplift.total_return)}
          />
          <MetricBox
            label="Drawdown uplift"
            value={formatPercent(overlay.uplift.max_drawdown)}
            sub="positive means lower drawdown"
            valueClassName={returnTone(overlay.uplift.max_drawdown)}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Execution candidates</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 px-4 pb-4">
          <div className="grid gap-2 sm:grid-cols-4">
            <MetricBox label="Invalid pairs" value={formatNumber(overlay.invalid_pair_count, 0)} />
            <MetricBox label="Unavailable" value={formatNumber(overlay.unavailable_count, 0)} />
            <MetricBox label="Best support" value={`${overlay.best_support_method ?? "--"} ${overlay.best_support_line ?? ""}`} />
            <MetricBox label="Best resistance" value={`${overlay.best_resistance_method ?? "--"} ${overlay.best_resistance_line ?? ""}`} />
          </div>
          <SrOverlayVariantsTable variants={overlay.top_variants} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Recent best-pair trades</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <SrOverlayTradesTable trades={bestTrades} />
        </CardContent>
      </Card>
    </div>
  )
}

function srWfoDecisionLabel(decision: string | null | undefined): string {
  if (decision === "actionable") return "Edge valide"
  if (decision === "weak") return "Signal faible"
  if (decision === "no_edge") return "Pas d'edge"
  return decision || "--"
}

function srWfoDecisionBadgeClass(decision: string | null | undefined): string {
  if (decision === "actionable") return "bg-green-600 text-white"
  if (decision === "weak") return "bg-amber-500 text-black"
  if (decision === "no_edge") return "bg-red-500/80 text-white"
  return "bg-muted text-muted-foreground"
}

function srWfoPairMetaLabel(meta: SrWfoPairMeta | null | undefined): string {
  if (!meta) return "--"
  const support = meta.support_label || meta.support_method_id || "--"
  const supportLine = meta.support_line_label || meta.support_line_id || ""
  const resistance = meta.resistance_label || meta.resistance_method_id || "--"
  const resistanceLine = meta.resistance_line_label || meta.resistance_line_id || ""
  return `${support}${supportLine ? ` ${supportLine}` : ""} / ${resistance}${resistanceLine ? ` ${resistanceLine}` : ""}`
}

function sortedWinCounts(counts: Record<string, number>, limit = 5): Array<[string, number]> {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
}

function SrWfoStatusCard({ wfo, error }: { wfo: SrWfoResponse["wfo"] | null; error: string | null }) {
  const reason = error ?? wfo?.explanation ?? "Historique insuffisant pour la procedure walk-forward S/R."
  return (
    <Card>
      <CardHeader className="pb-2 pt-3 px-4">
        <CardTitle className="flex items-center gap-2 text-sm font-bold">
          <Layers className="h-4 w-4 text-muted-foreground" />
          Lignes S/R pertinentes (walk-forward)
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-4">
        <p className="rounded-md border border-dashed bg-muted/20 p-3 text-sm text-muted-foreground">{reason}</p>
      </CardContent>
    </Card>
  )
}

function SrWfoProcedureTable({ wfo }: { wfo: SrWfoResponse["wfo"] }) {
  const proc = wfo.procedure_oos
  const buyHold = wfo.baselines?.buy_hold
  const isBest = wfo.baselines?.in_sample_best

  const rows: Array<{
    label: string
    sub?: string
    total_return?: number | null
    cagr?: number | null
    sharpe?: number | null
    max_drawdown?: number | null
    n_trades?: number | null
    highlight?: boolean
  }> = [
    {
      label: "Procedure walk-forward",
      total_return: proc?.total_return,
      cagr: proc?.cagr,
      sharpe: proc?.sharpe,
      max_drawdown: proc?.max_drawdown,
      n_trades: proc?.n_trades,
      highlight: true,
    },
    {
      label: "Buy & hold",
      total_return: buyHold?.total_return,
      cagr: buyHold?.cagr,
      sharpe: buyHold?.sharpe,
      max_drawdown: buyHold?.max_drawdown,
      n_trades: null,
    },
    {
      label: "Meilleur in-sample",
      sub: "biais de selection (reference optimiste)",
      total_return: isBest?.total_return,
      cagr: isBest?.cagr,
      sharpe: isBest?.sharpe,
      max_drawdown: isBest?.max_drawdown,
      n_trades: isBest?.n_trades,
    },
  ]

  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[640px] text-xs">
          <thead>
            <tr className="border-b bg-muted/30 text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">Reference</th>
              <th className="px-3 py-2 text-right font-medium">Rendement total</th>
              <th className="px-3 py-2 text-right font-medium">CAGR</th>
              <th className="px-3 py-2 text-right font-medium">Sharpe</th>
              <th className="px-3 py-2 text-right font-medium">Max DD</th>
              <th className="px-3 py-2 text-right font-medium">N trades</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.label}
                className={cn("border-b border-border/50", row.highlight && "bg-primary/5 font-semibold")}
              >
                <td className="px-3 py-2">
                  <div>{row.label}</div>
                  {row.sub ? <div className="text-[9px] font-normal text-muted-foreground">{row.sub}</div> : null}
                </td>
                <td className={cn("px-3 py-2 text-right font-mono", returnTone(row.total_return))}>
                  {pct(row.total_return != null ? row.total_return * 100 : null)}
                </td>
                <td className={cn("px-3 py-2 text-right font-mono", returnTone(row.cagr))}>
                  {pct(row.cagr != null ? row.cagr * 100 : null)}
                </td>
                <td className="px-3 py-2 text-right font-mono">{formatNumber(row.sharpe, 2)}</td>
                <td className={cn("px-3 py-2 text-right font-mono", returnTone(row.max_drawdown != null ? -Math.abs(row.max_drawdown) : null))}>
                  {pct(row.max_drawdown != null ? row.max_drawdown * 100 : null)}
                </td>
                <td className="px-3 py-2 text-right font-mono">
                  {row.n_trades != null ? formatNumber(row.n_trades, 0) : "--"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <span>
          Hit rate {pct(proc?.hit_rate != null ? proc.hit_rate * 100 : null)}
          {proc?.wilson_lb != null && proc?.wilson_ub != null
            ? ` [${pct(proc.wilson_lb * 100)} - ${pct(proc.wilson_ub * 100)}]`
            : ""}
        </span>
        <span>&middot;</span>
        <span>p-value bootstrap {proc?.bootstrap_pvalue != null ? formatNumber(proc.bootstrap_pvalue, 3) : "n/a"}</span>
      </div>
      <p className="text-[10px] italic text-muted-foreground">
        La procedure re-selectionne la meilleure paire a chaque fenetre a partir des seules donnees passees ; c&apos;est
        le seul bilan reellement obtenable.
      </p>
    </div>
  )
}

function SrWfoWindowsTable({ windows }: { windows: SrWfoResponse["wfo"]["windows"] }) {
  if (!windows.length) {
    return (
      <div className="rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
        Aucune fenetre walk-forward disponible.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-[780px] text-xs">
        <thead>
          <tr className="border-b bg-muted/30 text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">Fenetre</th>
            <th className="px-3 py-2 text-left font-medium">Periode test</th>
            <th className="px-3 py-2 text-left font-medium">Paire selectionnee</th>
            <th className="px-3 py-2 text-right font-medium">Objectif train</th>
            <th className="px-3 py-2 text-right font-medium">Sharpe test</th>
            <th className="px-3 py-2 text-right font-medium">Rendement test</th>
            <th className="px-3 py-2 text-right font-medium">N trades</th>
          </tr>
        </thead>
        <tbody>
          {windows.map((win) => (
            <tr key={win.window_index} className="border-b border-border/50">
              <td className="px-3 py-2 font-medium">#{win.window_index + 1}</td>
              <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                {compactDate(win.test_start_date)} - {compactDate(win.test_end_date)}
              </td>
              <td className="max-w-[240px] truncate px-3 py-2" title={srWfoPairMetaLabel(win.selected_pair_meta)}>
                {win.selected_pair_meta ? srWfoPairMetaLabel(win.selected_pair_meta) : "--"}
              </td>
              <td className="px-3 py-2 text-right font-mono">{formatNumber(win.train_objective, 3)}</td>
              <td className="px-3 py-2 text-right font-mono">{formatNumber(win.test_metrics?.sharpe, 2)}</td>
              <td className={cn("px-3 py-2 text-right font-mono", returnTone(win.test_metrics?.total_return))}>
                {pct(win.test_metrics?.total_return != null ? win.test_metrics.total_return * 100 : null)}
              </td>
              <td className="px-3 py-2 text-right font-mono">{formatNumber(win.test_metrics?.n_trades, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SrWfoTouchStatsTable({
  title,
  stats,
}: {
  title: string
  stats: Record<string, { n_touches: number; n_bounces: number; bounce_rate?: number | null; wilson_ci_lower?: number | null; wilson_ci_upper?: number | null }>
}) {
  const rows = Object.entries(stats)
    .sort((a, b) => (b[1].n_touches ?? 0) - (a[1].n_touches ?? 0))
    .slice(0, 8)
  if (!rows.length) {
    return (
      <div className="rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
        Aucune donnee de touche pour {title.toLowerCase()}.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full min-w-[520px] text-xs">
        <thead>
          <tr className="border-b bg-muted/30 text-muted-foreground">
            <th className="px-3 py-2 text-left font-medium">{title}</th>
            <th className="px-3 py-2 text-right font-medium">Touches</th>
            <th className="px-3 py-2 text-right font-medium">Taux rebond</th>
            <th className="px-3 py-2 text-right font-medium">Wilson</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([id, stat]) => (
            <tr key={id} className="border-b border-border/50">
              <td className="px-3 py-2 font-mono text-[10px]">{id}</td>
              <td className="px-3 py-2 text-right font-mono">{formatNumber(stat.n_touches, 0)}</td>
              <td className="px-3 py-2 text-right font-mono">
                {pct(stat.bounce_rate != null ? stat.bounce_rate * 100 : null)}
              </td>
              <td className="px-3 py-2 text-right font-mono text-[10px] text-muted-foreground">
                {stat.wilson_ci_lower != null && stat.wilson_ci_upper != null
                  ? `[${pct(stat.wilson_ci_lower * 100)} - ${pct(stat.wilson_ci_upper * 100)}]`
                  : "--"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SrWfoDetailPanel({
  wfo,
  touchStats,
  isLoading,
  error,
}: {
  wfo: SrWfoResponse | null
  touchStats: SrWfoResponse["line_touch_stats"] | undefined
  isLoading: boolean
  error: string | null
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-md" />
        <Skeleton className="h-56 w-full rounded-md" />
      </div>
    )
  }

  if (error) {
    return <SrWfoStatusCard wfo={wfo?.wfo ?? null} error={error} />
  }

  if (!wfo || wfo.wfo.status === "insufficient_history") {
    return <SrWfoStatusCard wfo={wfo?.wfo ?? null} error={null} />
  }

  const { wfo: result } = wfo
  const rec = result.live_recommendation
  const stability = result.stability
  const supportWins = stability ? sortedWinCounts(stability.support_win_counts) : []
  const resistanceWins = stability ? sortedWinCounts(stability.resistance_win_counts) : []
  const hasTouchStats =
    touchStats != null &&
    (Object.keys(touchStats.support ?? {}).length > 0 || Object.keys(touchStats.resistance ?? {}).length > 0)

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm font-bold">
                <Layers className="h-4 w-4 text-primary" />
                Lignes S/R pertinentes (walk-forward)
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">{result.explanation}</p>
            </div>
            <Badge className={cn("h-6 px-2 text-[10px] font-bold", srWfoDecisionBadgeClass(result.decision))}>
              {srWfoDecisionLabel(result.decision)}
            </Badge>
          </div>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Procedure OOS vs references</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <SrWfoProcedureTable wfo={result} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Recommandation actuelle</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 px-4 pb-4">
          {rec?.pair_id ? (
            <div className="text-sm font-medium">
              Support: {rec.pair_meta?.support_label ?? "--"} {rec.pair_meta?.support_line_label ?? ""}
              {"  /  "}
              Resistance: {rec.pair_meta?.resistance_label ?? "--"} {rec.pair_meta?.resistance_line_label ?? ""}
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">Aucune paire eligible actuellement.</div>
          )}
          {rec?.note ? <p className="text-[10px] italic text-muted-foreground">{rec.note}</p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Stabilite de la selection</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 px-4 pb-4">
          <div className="grid gap-2 sm:grid-cols-2">
            <MetricBox
              label="Paire modale"
              value={`${stability?.modal_pair_wins ?? 0}/${stability?.n_selectable_windows ?? 0}`}
              sub={stability?.modal_pair_id ?? "--"}
            />
            <MetricBox label="Stabilite de selection" value={pct(stability?.selection_stability != null ? stability.selection_stability * 100 : null)} />
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Support</div>
              <ul className="space-y-1 text-xs">
                {supportWins.length ? (
                  supportWins.map(([id, count]) => (
                    <li key={id} className="flex justify-between rounded border border-border/50 px-2 py-1 font-mono text-[10px]">
                      <span className="truncate">{id}</span>
                      <span className="text-muted-foreground">{count} fenetres</span>
                    </li>
                  ))
                ) : (
                  <li className="text-muted-foreground">--</li>
                )}
              </ul>
            </div>
            <div>
              <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Resistance</div>
              <ul className="space-y-1 text-xs">
                {resistanceWins.length ? (
                  resistanceWins.map(([id, count]) => (
                    <li key={id} className="flex justify-between rounded border border-border/50 px-2 py-1 font-mono text-[10px]">
                      <span className="truncate">{id}</span>
                      <span className="text-muted-foreground">{count} fenetres</span>
                    </li>
                  ))
                ) : (
                  <li className="text-muted-foreground">--</li>
                )}
              </ul>
            </div>
          </div>
          <p className="text-[10px] italic text-muted-foreground">
            Une stabilite faible signifie qu&apos;aucune paire unique ne domine ; lire au niveau methode/ligne.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Fenetres walk-forward</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <SrWfoWindowsTable windows={result.windows} />
        </CardContent>
      </Card>

      {hasTouchStats ? (
        <details className="group rounded-md border bg-card">
          <summary className="cursor-pointer list-none px-4 py-3 text-xs font-semibold">
            Diagnostic touches / rebonds
          </summary>
          <div className="space-y-3 px-4 pb-4">
            <SrWfoTouchStatsTable title="Support" stats={touchStats?.support ?? {}} />
            <SrWfoTouchStatsTable title="Resistance" stats={touchStats?.resistance ?? {}} />
            <p className="text-[10px] italic text-muted-foreground">
              Les lignes tres proches du prix (ex. pivots serres) sont touchees presque chaque barre : leur taux de
              rebond reflete surtout la derive du marche, pas la qualite de la ligne. A comparer au taux de base.
            </p>
          </div>
        </details>
      ) : null}
    </div>
  )
}

function WfoDetailPanel({
  detail,
  isLoading,
  error,
  symbol,
  horizon,
  variant,
}: {
  detail: WfoCategoryDetail | null
  isLoading: boolean
  error: string | null
  symbol: string
  horizon: string
  variant: string
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-md" />
        <Skeleton className="h-56 w-full rounded-md" />
      </div>
    )
  }

  if (error) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="py-8 text-center">
          <AlertCircle className="mx-auto mb-2 h-7 w-7 text-destructive" />
          <p className="text-sm font-semibold text-destructive">Erreur WFO detail</p>
          <p className="mt-1 text-xs text-muted-foreground">{error}</p>
        </CardContent>
      </Card>
    )
  }

  if (!detail) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Selectionnez une categorie pour voir le detail WFO.
        </CardContent>
      </Card>
    )
  }

  const config = asRecord(detail.config)
  const folds = Array.isArray(detail.folds) ? detail.folds : []
  const dataAsOf = (typeof detail.data_as_of === "string" ? detail.data_as_of : "") || (config ? asString(config.data_as_of) : "")
  const lastOosEnd = config ? asString(config.last_oos_end_date) : ""
  const unusedTailBars = config ? asNumber(config.unused_tail_bars) : null

  return (
    <div className="space-y-3">
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-sm font-bold">
                Detail WFO - {CATEGORY_META.find((meta) => meta.id === detail.category)?.label ?? detail.category}
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {detail.computed_at ? `Calcule le ${detail.computed_at}` : "Aucun calcul date disponible"}
                {detail.compute_seconds != null ? ` (${detail.compute_seconds.toFixed(1)}s)` : ""}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="h-6 text-[10px]">{detail.status}</Badge>
              {detail.robustness_grade ? (
                <Badge className={cn("h-6 px-2 text-[10px] font-bold", GRADE_COLORS[detail.robustness_grade] ?? "")}>
                  Grade {detail.robustness_grade}
                </Badge>
              ) : null}
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-2 px-4 pb-4 sm:grid-cols-4">
          <MetricBox label="Score" value={scoreText(detail.score_pct)} />
          <MetricBox label="WFE" value={pct(detail.wfe_pct, 1)} />
          <MetricBox label="Robustesse" value={formatNumber(detail.robustness_ratio, 2)} />
          <MetricBox label="Folds rentables" value={`${detail.profitable_folds ?? 0}/${detail.total_folds ?? 0}`} />
        </CardContent>
      </Card>

      {config ? (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="flex items-center gap-2 text-xs font-semibold">
              <Settings className="h-3.5 w-3.5 text-muted-foreground" />
              Configuration utilisee
            </CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 px-4 pb-4 sm:grid-cols-4">
            <ConfigItem label="Train" value={`${config.train_bars ?? "--"} barres`} />
            <ConfigItem label="Test" value={`${config.oos_bars ?? "--"} barres`} />
            <ConfigItem label="Step" value={`${config.step_bars ?? "--"} barres`} />
            <ConfigItem label="Grille" value={`${config.grid_size ?? "--"} variantes`} />
            <ConfigItem label="Cout" value={`${config.cost_bps ?? "--"} bps`} />
            <ConfigItem label="Max reps" value={String(config.max_reps ?? "--")} />
            <ConfigItem label="Donnees" value={`${config.data_bars ?? "--"} barres`} />
            <ConfigItem label="Min requis" value={`${config.min_bars_needed ?? "--"} barres`} />
            <ConfigItem label="Dernier OOS" value={lastOosEnd || "--"} />
            <ConfigItem label="Data as of" value={dataAsOf || "--"} />
            <ConfigItem label="Tail inutilisee" value={`${unusedTailBars ?? "--"} barres`} />
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Representants selectionnes</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <RepresentativesTable reps={detail.representatives} symbol={symbol} horizon={horizon} variant={variant} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Folds walk-forward</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <FoldTable folds={folds} />
        </CardContent>
      </Card>
    </div>
  )
}

export function WfoEvidenceTab({
  symbol,
  horizon,
  variant,
  cooldownBars = 0,
}: {
  symbol: string
  horizon: string
  variant: string
  cooldownBars?: number
}) {
  const { data, isLoading, error, refresh } = useWfoSummary(symbol, horizon, variant)
  const [selectedCategory, setSelectedCategory] = useState<CategoryId>("tendance")
  const [detail, setDetail] = useState<WfoCategoryDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState<"selected" | "all" | null>(null)
  const [srOverlay, setSrOverlay] = useState<SrOverlay | null>(null)
  const [srOverlayLoading, setSrOverlayLoading] = useState(false)
  const [srOverlayError, setSrOverlayError] = useState<string | null>(null)
  const [srWfo, setSrWfo] = useState<SrWfoResponse | null>(null)
  const [srWfoLoading, setSrWfoLoading] = useState(false)
  const [srWfoError, setSrWfoError] = useState<string | null>(null)
  const srWfoCacheKeyRef = useRef<string | null>(null)

  const categories = data?.categories ?? {}
  const bestCategory = data?.global_signal?.best_category as CategoryId | null | undefined
  const normalizedCooldownBars = Math.max(0, Math.floor(cooldownBars || 0))

  useEffect(() => {
    const firstSucceeded = BASE_CATEGORY_META.find((meta) => categories[meta.id]?.status === "succeeded")?.id
    setSelectedCategory(bestCategory ?? firstSucceeded ?? "tendance")
  }, [bestCategory, horizon, symbol, variant])

  useEffect(() => {
    let cancelled = false
    if (isSyntheticCategory(selectedCategory)) {
      setDetail(null)
      setDetailLoading(false)
      setDetailError(null)
      return () => {
        cancelled = true
      }
    }

    setDetail(null)
    setDetailLoading(true)
    setDetailError(null)

    fetchWfoDetail(symbol, horizon, selectedCategory, variant)
      .then((res) => {
        if (!cancelled) setDetail(res)
      })
      .catch((err) => {
        if (!cancelled) setDetailError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [horizon, selectedCategory, symbol, variant])

  useEffect(() => {
    let cancelled = false
    setSrOverlay(null)
    setSrOverlayLoading(true)
    setSrOverlayError(null)

    fetchSignalEvidence({
      symbol,
      horizon,
      source: "wfo",
      variant,
      costBps: EDGE_COST_BPS,
      cooldownBars: normalizedCooldownBars,
    })
      .then((res) => {
        if (cancelled) return
        setSrOverlay(res.stitched_oos_backtest?.sr_overlay ?? res.sr_overlay ?? null)
      })
      .catch((err) => {
        if (!cancelled) setSrOverlayError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setSrOverlayLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [horizon, normalizedCooldownBars, symbol, variant])

  useEffect(() => {
    const key = `${symbol}|${horizon}`

    if (srWfoCacheKeyRef.current === key) {
      // Already fetched (or in flight) for this symbol/horizon combination.
      return
    }

    let cancelled = false
    srWfoCacheKeyRef.current = key
    setSrWfo(null)
    setSrWfoLoading(true)
    setSrWfoError(null)

    fetchSrWfo({ symbol, horizon, timeframe: "1D" })
      .then((res) => {
        if (!cancelled) setSrWfo(res)
      })
      .catch((err) => {
        if (!cancelled) {
          setSrWfoError(err instanceof Error ? err.message : String(err))
          srWfoCacheKeyRef.current = null
        }
      })
      .finally(() => {
        if (!cancelled) setSrWfoLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [horizon, symbol])

  const handleTrigger = async (scope: "selected" | "all") => {
    if (scope === "selected" && isSyntheticCategory(selectedCategory)) return
    setTriggering(scope)
    try {
      await triggerWfoComputation({
        symbol,
        horizon,
        variant,
        categories: scope === "selected" ? [selectedCategory] : undefined,
      })
      window.setTimeout(() => {
        void refresh()
      }, 1500)
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err))
    } finally {
      setTriggering(null)
    }
  }

  const global = data?.global_signal ?? null
  const srReturnPct = srOverlay?.overlay_metrics?.total_return
  const srReady = (srOverlay?.status === "actionable" || srOverlay?.status === "research_only") && srOverlay.overlay_metrics
  const rawStatus = srOverlayLoading ? "loading" : srOverlayError ? "error" : srReady ? "ready" : srOverlay?.reason ?? srOverlay?.status ?? "unavailable"
  const srCategorySummary: CategoryButtonSummary = {
    status: formatSrReason(rawStatus),
    score_pct: srReturnPct == null ? null : srReturnPct * 100,
    signal_label: srReady ? "Overlay ready" : srOverlayError ?? srOverlay?.reason ?? "Unavailable",
    representatives: [],
    badges: srOverlay
      ? [
          `${formatNumber(srOverlay.viable_count, 0)} viable`,
          `${formatNumber(srOverlay.tested_count, 0)} tested`,
        ]
      : [],
  }
  const srWfoResult = srWfo?.wfo ?? null
  const srWfoRawStatus = srWfoLoading
    ? "loading"
    : srWfoError
      ? "error"
      : srWfoResult
        ? srWfoResult.decision ?? srWfoResult.status
        : "unavailable"
  const srWfoCategorySummary: CategoryButtonSummary = {
    status: srWfoRawStatus,
    score_pct:
      srWfoResult?.procedure_oos?.total_return != null ? srWfoResult.procedure_oos.total_return * 100 : null,
    signal_label: srWfoError ?? (srWfoResult ? srWfoDecisionLabel(srWfoResult.decision) : "Unavailable"),
    representatives: [],
    badges: srWfoResult
      ? [
          `${srWfoResult.windows.length} fenetres`,
          srWfoResult.stability?.selection_stability != null
            ? `${Math.round(srWfoResult.stability.selection_stability * 100)}% stable`
            : "-- stable",
        ]
      : [],
  }
  const categoryCount = useMemo(
    () => BASE_CATEGORY_META.filter((meta) => categories[meta.id]?.status === "succeeded").length,
    [categories],
  )

  if (isLoading && !data) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-32 w-full rounded-md" />
        <div className="grid gap-3 xl:grid-cols-[320px_minmax(0,1fr)]">
          <Skeleton className="h-96 w-full rounded-md" />
          <Skeleton className="h-96 w-full rounded-md" />
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="py-8 text-center">
          <AlertCircle className="mx-auto mb-2 h-7 w-7 text-destructive" />
          <p className="text-sm font-semibold text-destructive">Erreur WFO</p>
          <p className="mt-1 text-xs text-muted-foreground">{error}</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3.5">
      <Card className="border-primary/20 bg-primary/5">
        <CardHeader className="pb-2 pt-3 px-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm font-bold">
                <CheckCircle2 className="h-4 w-4 text-primary" />
                Evidence WFO
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Consensus, categories et details fold-by-fold du mode actif.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                disabled={isLoading}
                onClick={refresh}
              >
                <RefreshCw className={cn("h-3.5 w-3.5", isLoading && "animate-spin")} />
                Rafraichir
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 text-xs"
                disabled={triggering != null || isSyntheticCategory(selectedCategory)}
                onClick={() => handleTrigger("selected")}
                title={isSyntheticCategory(selectedCategory) ? "S/R a la demande - calcule depuis signal evidence, non recalculable ici." : undefined}
              >
                {isSyntheticCategory(selectedCategory) ? "S/R a la demande" : triggering === "selected" ? "Envoi..." : "Recalculer categorie"}
              </Button>
              <Button
                type="button"
                size="sm"
                className="h-7 text-xs"
                disabled={triggering != null}
                onClick={() => handleTrigger("all")}
              >
                {triggering === "all" ? "Envoi..." : "Recalculer tout"}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 px-4 pb-4 lg:grid-cols-[220px_minmax(0,1fr)]">
          <div className="flex items-center justify-center rounded-md border bg-background p-3">
            <SignalScoreBar value={global?.global_score_pct ?? null} size="lg" className="w-full max-w-[180px]" />
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
            <MetricBox label="Signal" value={global?.signal_label ?? global?.recommendation ?? "--"} />
            <MetricBox label="Categories" value={`${categoryCount}/4`} sub={`${global?.categories_viable ?? categoryCount} viable`} />
            <MetricBox label="WFE consensus" value={pct(global?.consensus_wfe_pct, 1)} />
            <MetricBox label="Robustesse" value={formatNumber(global?.consensus_robustness, 2)} />
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 xl:grid-cols-[320px_minmax(0,1fr)]">
        <div className="space-y-2">
          {CATEGORY_META.map((meta) => (
            <CategoryButton
              key={meta.id}
              meta={meta}
              summary={
                meta.id === "sr_wfo"
                  ? srWfoCategorySummary
                  : meta.id === "sr_execution"
                    ? srCategorySummary
                    : categories[meta.id]
              }
              selected={selectedCategory === meta.id}
              onSelect={() => setSelectedCategory(meta.id)}
            />
          ))}
        </div>

        {selectedCategory === "sr_wfo" ? (
          <SrWfoDetailPanel
            wfo={srWfo}
            touchStats={srWfo?.line_touch_stats}
            isLoading={srWfoLoading}
            error={srWfoError}
          />
        ) : selectedCategory === "sr_execution" ? (
          <SrOverlayDetailPanel
            overlay={srOverlay}
            isLoading={srOverlayLoading}
            error={srOverlayError}
          />
        ) : (
          <WfoDetailPanel
            detail={detail}
            isLoading={detailLoading}
            error={detailError}
            symbol={symbol}
            horizon={horizon}
            variant={variant}
          />
        )}
      </div>
    </div>
  )
}
