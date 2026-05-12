"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { Activity, AlertCircle, BarChart3, CheckCircle2, ExternalLink, RefreshCw, Settings, TrendingUp } from "lucide-react"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import {
  fetchWfoDetail,
  triggerWfoComputation,
  type WfoCategoryDetail,
  type WfoCategorySummary,
  type WfoRepresentative,
} from "@/lib/api"
import { formatWfoFoldRange } from "@/lib/wfo-fold-display"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalBadge } from "@/components/ui/signal-badge"
import { SignalScoreBar } from "./signal-score-bar"

type CategoryId = "tendance" | "momentum" | "oscillation" | "volume"

type CategoryMeta = {
  id: CategoryId
  label: string
  icon: typeof TrendingUp
}

const CATEGORY_META: CategoryMeta[] = [
  { id: "tendance", label: "Tendance", icon: TrendingUp },
  { id: "momentum", label: "Momentum", icon: Activity },
  { id: "oscillation", label: "Oscillation", icon: Activity },
  { id: "volume", label: "Volume", icon: BarChart3 },
]

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

function MetricBox({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-md border bg-background p-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold">{value}</div>
      {sub ? <div className="mt-0.5 text-[10px] text-muted-foreground">{sub}</div> : null}
    </div>
  )
}

function CategoryButton({
  meta,
  summary,
  selected,
  onSelect,
}: {
  meta: CategoryMeta
  summary: WfoCategorySummary | undefined
  selected: boolean
  onSelect: () => void
}) {
  const Icon = meta.icon
  const succeeded = summary?.status === "succeeded"
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
        {succeeded ? (
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
}: {
  symbol: string
  horizon: string
  variant: string
}) {
  const { data, isLoading, error, refresh } = useWfoSummary(symbol, horizon, variant)
  const [selectedCategory, setSelectedCategory] = useState<CategoryId>("tendance")
  const [detail, setDetail] = useState<WfoCategoryDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [triggering, setTriggering] = useState<"selected" | "all" | null>(null)

  const categories = data?.categories ?? {}
  const bestCategory = data?.global_signal?.best_category as CategoryId | null | undefined

  useEffect(() => {
    const firstSucceeded = CATEGORY_META.find((meta) => categories[meta.id]?.status === "succeeded")?.id
    setSelectedCategory(bestCategory ?? firstSucceeded ?? "tendance")
  }, [bestCategory, horizon, symbol, variant])

  useEffect(() => {
    let cancelled = false
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

  const handleTrigger = async (scope: "selected" | "all") => {
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
  const categoryCount = useMemo(
    () => CATEGORY_META.filter((meta) => categories[meta.id]?.status === "succeeded").length,
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
                disabled={triggering != null}
                onClick={() => handleTrigger("selected")}
              >
                {triggering === "selected" ? "Envoi..." : "Recalculer categorie"}
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
              summary={categories[meta.id]}
              selected={selectedCategory === meta.id}
              onSelect={() => setSelectedCategory(meta.id)}
            />
          ))}
        </div>

        <WfoDetailPanel
          detail={detail}
          isLoading={detailLoading}
          error={detailError}
          symbol={symbol}
          horizon={horizon}
          variant={variant}
        />
      </div>
    </div>
  )
}
