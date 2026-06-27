"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { Activity, AlertCircle, BarChart3, CheckCircle2, ExternalLink, Gauge, RefreshCw, Settings, TrendingUp } from "lucide-react"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import {
  fetchSignalEvidence,
  fetchWfoDetail,
  triggerWfoComputation,
  type SrOverlay,
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
type CategoryId = BaseCategoryId | "sr_execution"

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
]

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

function SrOverlayStatusCard({
  overlay,
  error,
}: {
  overlay: SrOverlay | null
  error: string | null
}) {
  const reason = error ?? overlay?.reason ?? overlay?.status ?? "unavailable"
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

  const ready = overlay?.status === "ready" && overlay.overlay_metrics
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

  const categories = data?.categories ?? {}
  const bestCategory = data?.global_signal?.best_category as CategoryId | null | undefined
  const normalizedCooldownBars = Math.max(0, Math.floor(cooldownBars || 0))

  useEffect(() => {
    const firstSucceeded = BASE_CATEGORY_META.find((meta) => categories[meta.id]?.status === "succeeded")?.id
    setSelectedCategory(bestCategory ?? firstSucceeded ?? "tendance")
  }, [bestCategory, horizon, symbol, variant])

  useEffect(() => {
    let cancelled = false
    if (selectedCategory === "sr_execution") {
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

  const handleTrigger = async (scope: "selected" | "all") => {
    if (scope === "selected" && selectedCategory === "sr_execution") return
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
  const srReady = srOverlay?.status === "ready" && srOverlay.overlay_metrics
  const srCategorySummary: CategoryButtonSummary = {
    status: srOverlayLoading ? "loading" : srOverlayError ? "error" : srReady ? "ready" : srOverlay?.reason ?? srOverlay?.status ?? "unavailable",
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
                disabled={triggering != null || selectedCategory === "sr_execution"}
                onClick={() => handleTrigger("selected")}
                title={selectedCategory === "sr_execution" ? "S/R execution is computed from signal evidence on demand." : undefined}
              >
                {selectedCategory === "sr_execution" ? "S/R on demand" : triggering === "selected" ? "Envoi..." : "Recalculer categorie"}
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
              summary={meta.id === "sr_execution" ? srCategorySummary : categories[meta.id]}
              selected={selectedCategory === meta.id}
              onSelect={() => setSelectedCategory(meta.id)}
            />
          ))}
        </div>

        {selectedCategory === "sr_execution" ? (
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
