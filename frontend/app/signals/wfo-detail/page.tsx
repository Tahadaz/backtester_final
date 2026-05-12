"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft, AlertCircle, CheckCircle2, Clock, Info } from "lucide-react"
import { fetchWfoDetail, type WfoCategoryDetail } from "@/lib/api"
import { formatWfoFoldRange } from "@/lib/wfo-fold-display"
import { formatNumber } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

const CATEGORY_LABELS: Record<string, string> = {
  tendance: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}

const GRADE_COLORS: Record<string, string> = {
  A: "bg-green-600 text-white",
  B: "bg-green-500 text-white",
  C: "bg-yellow-500 text-black",
  D: "bg-orange-500 text-white",
  F: "bg-red-500 text-white",
}

function WfoDetailContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const symbol = searchParams.get("symbol") ?? ""
  const horizon = searchParams.get("horizon") ?? "medium"
  const category = searchParams.get("category") ?? ""
  const variant = searchParams.get("variant") ?? "expanded"

  const [data, setData] = useState<WfoCategoryDetail | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!symbol || !category) return
    let cancelled = false
    setIsLoading(true)
    setError(null)

    fetchWfoDetail(symbol, horizon, category, variant)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => { cancelled = true }
  }, [symbol, horizon, category, variant])

  if (!symbol || !category) {
    return (
      <div className="p-6 text-center text-sm text-muted-foreground">
        Parametres manquants dans l&apos;URL (symbol, category).
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-6">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-52 w-full" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <Card className="border-destructive/50">
          <CardContent className="py-8 text-center">
            <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-2" />
            <p className="text-sm font-medium text-destructive">Erreur de chargement</p>
            <p className="mt-1 text-xs text-muted-foreground">{error || "Donnees non disponibles"}</p>
            <Button variant="outline" size="sm" className="mt-4" onClick={() => router.back()}>
              Retour
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  const config = data.config as Record<string, any> | null
  const folds = data.folds as Array<Record<string, any>> | null
  const dataAsOf = data.data_as_of || config?.data_as_of || ""
  const lastOosEnd = config?.last_oos_end_date || ""
  const unusedTailBars = typeof config?.unused_tail_bars === "number" ? config.unused_tail_bars : null

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour
        </Button>
        <div>
          <h1 className="text-base font-bold">
            WFO Detail — {CATEGORY_LABELS[category] || category}
          </h1>
          <p className="text-xs text-muted-foreground">
            {symbol} / {horizon} / {variant}
            {data.computed_at && ` — Calcule le ${data.computed_at}`}
            {data.compute_seconds != null && ` (${data.compute_seconds.toFixed(1)}s)`}
          </p>
        </div>
      </div>

      {/* Status Banner */}
      {data.status === "succeeded" ? (
        <Card className="border-green-200 bg-green-50/50">
          <CardContent className="py-3 flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-600 shrink-0" />
            <div>
              <p className="text-xs font-bold text-green-800">Calcul reussi</p>
              <p className="text-[10px] text-green-700">
                Score: {data.score_pct?.toFixed(1)}% — {data.signal_label}
              </p>
            </div>
            {data.robustness_grade && (
              <Badge className={cn("ml-auto text-xs font-bold px-2", GRADE_COLORS[data.robustness_grade])}>
                Grade {data.robustness_grade}
              </Badge>
            )}
          </CardContent>
        </Card>
      ) : data.status === "failed" ? (
        <Card className="border-red-200 bg-red-50/50">
          <CardContent className="py-3 flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-red-600 shrink-0" />
            <div>
              <p className="text-xs font-bold text-red-800">Calcul echoue</p>
              <p className="text-[10px] text-red-700">{data.error_message || "Erreur inconnue"}</p>
            </div>
          </CardContent>
        </Card>
      ) : data.status === "insufficient_data" ? (
        <Card className="border-amber-200 bg-amber-50/50">
          <CardContent className="py-3 flex items-center gap-3">
            <Info className="h-5 w-5 text-amber-600 shrink-0" />
            <div>
              <p className="text-xs font-bold text-amber-800">Donnees insuffisantes</p>
              <p className="text-[10px] text-amber-700">{data.error_message || "Pas assez de barres de donnees"}</p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card className="border-blue-200 bg-blue-50/50">
          <CardContent className="py-3 flex items-center gap-3">
            <Clock className="h-5 w-5 text-blue-600 shrink-0 animate-pulse" />
            <div>
              <p className="text-xs font-bold text-blue-800">
                {data.status === "running" ? "Calcul en cours..." : "En attente"}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Config Used */}
      {config && (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold">Configuration utilisee</CardTitle>
          </CardHeader>
          <CardContent className="pb-3 px-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <ConfigItem label="Train (IS)" value={`${config.train_bars} barres`} />
              <ConfigItem label="Test (OOS)" value={`${config.oos_bars} barres`} />
              <ConfigItem label="Step" value={`${config.step_bars} barres`} />
              <ConfigItem label="Donnees" value={`${config.data_bars} barres`} />
              <ConfigItem label="Min requis" value={`${config.min_bars_needed} barres`} />
              <ConfigItem label="Grille" value={`${config.grid_size} variantes`} />
              <ConfigItem label="Cout" value={`${config.cost_bps} bps`} />
              <ConfigItem label="Max reps" value={String(config.max_reps)} />
              <ConfigItem label="Dernier OOS" value={lastOosEnd || "--"} />
              <ConfigItem label="Data as of" value={dataAsOf || "--"} />
              <ConfigItem label="Tail inutilisee" value={`${unusedTailBars ?? "--"} barres`} />
            </div>
            {config.families && (
              <div className="mt-2 flex flex-wrap gap-1">
                {(config.families as string[]).map((f) => (
                  <Badge key={f} variant="outline" className="text-[9px]">{f}</Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Fold Details Table */}
      {folds && folds.length > 0 && (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold">
              Detail des folds ({folds.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-secondary/30 text-muted-foreground">
                    <th className="px-3 py-2 text-left font-medium">Fold</th>
                    <th className="px-3 py-2 text-left font-medium">Train</th>
                    <th className="px-3 py-2 text-left font-medium">OOS</th>
                    <th className="px-3 py-2 text-right font-medium">IS Return</th>
                    <th className="px-3 py-2 text-right font-medium">OOS Return</th>
                    <th className="px-3 py-2 text-right font-medium">OOS Sharpe</th>
                    <th className="px-3 py-2 text-left font-medium">Gagnant</th>
                    <th className="px-3 py-2 text-right font-medium">PROM</th>
                    <th className="px-3 py-2 text-center font-medium">Profil</th>
                  </tr>
                </thead>
                <tbody>
                  {folds.map((fold: any) => (
                    <tr
                      key={fold.index}
                      className={cn(
                        "border-b border-border/50",
                        fold.oos_profitable ? "bg-green-50/30" : "bg-red-50/30",
                      )}
                    >
                      <td className="px-3 py-2 font-medium">#{fold.index + 1}</td>
                      <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                        {formatWfoFoldRange(fold, "train")}
                      </td>
                      <td className="px-3 py-2 font-mono text-[10px] text-muted-foreground">
                        {formatWfoFoldRange(fold, "oos")}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        <span className={fold.is_return > 0 ? "text-green-700" : "text-red-700"}>
                          {(fold.is_return * 100).toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        <span className={fold.oos_return > 0 ? "text-green-700" : "text-red-700"}>
                          {(fold.oos_return * 100).toFixed(2)}%
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {fold.oos_sharpe != null ? fold.oos_sharpe.toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span className="font-mono text-[10px] text-muted-foreground truncate max-w-[150px] block" title={fold.winner_variant_id}>
                          {fold.winner_description || fold.winner_variant_id || "—"}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {(fold.winner_prom * 100).toFixed(3)}%
                      </td>
                      <td className="px-3 py-2 text-center">
                        {fold.profile_passes ? (
                          <Badge variant="outline" className="text-[9px] border-green-300 text-green-700">
                            OK
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-[9px] border-red-300 text-red-700">
                            {fold.profile_reason}
                          </Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t-2 bg-secondary/20 font-medium">
                    <td colSpan={3} className="px-3 py-2">Resume</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2">
                      <span className="text-[10px] text-muted-foreground">
                        {data.profitable_folds}/{data.total_folds} rentables
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-[10px]">—</td>
                    <td className="px-3 py-2 text-center">
                      <span className="text-[10px] text-muted-foreground">
                        {folds.filter((f: any) => f.profile_passes).length}/{folds.length} OK
                      </span>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Scoring Breakdown */}
      {data.status === "succeeded" && (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold">Decomposition du scoring</CardTitle>
          </CardHeader>
          <CardContent className="pb-3 px-4">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <ScoreCard
                label="WFE"
                value={data.wfe_pct != null ? `${data.wfe_pct.toFixed(1)}%` : "—"}
                detail="Walk-Forward Efficiency"
              />
              <ScoreCard
                label="Robustesse"
                value={data.robustness_ratio != null ? `${(data.robustness_ratio * 100).toFixed(0)}%` : "—"}
                detail="% folds OOS rentables"
              />
              <ScoreCard
                label="Sharpe OOS moy."
                value={data.mean_oos_sharpe != null ? data.mean_oos_sharpe.toFixed(4) : "—"}
                detail="Sharpe moyen des folds"
              />
              <ScoreCard
                label="Pire drawdown"
                value={data.worst_fold_drawdown != null ? `${(data.worst_fold_drawdown * 100).toFixed(2)}%` : "—"}
                detail="Pire fold OOS"
              />
            </div>
            <div className="mt-3 flex items-center gap-3 bg-muted/30 rounded p-2">
              <span className="text-[10px] text-muted-foreground">Score composite:</span>
              <span className="text-sm font-bold font-mono">{data.composite_score?.toFixed(1)}</span>
              <span className="text-[10px] text-muted-foreground">/ 100</span>
              {data.robustness_grade && (
                <Badge className={cn("ml-auto text-xs font-bold px-2", GRADE_COLORS[data.robustness_grade])}>
                  Grade {data.robustness_grade}
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Selected Representatives */}
      {data.representatives && data.representatives.length > 0 && (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold">
              Representants selectionnes ({data.representatives.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-secondary/30 text-muted-foreground">
                    <th className="px-3 py-2 text-left font-medium">Variante</th>
                    <th className="px-3 py-2 text-left font-medium">Famille</th>
                    <th className="px-3 py-2 text-center font-medium">Signal</th>
                    <th className="px-3 py-2 text-right font-medium">Poids</th>
                    <th className="px-3 py-2 text-right font-medium">Contribution</th>
                    <th className="px-3 py-2 text-right font-medium">PROM</th>
                  </tr>
                </thead>
                <tbody>
                  {data.representatives.map((rep, idx) => (
                    <tr key={idx} className="border-b border-border/50">
                      <td className="px-3 py-2">
                        <div className="font-medium">{rep.description}</div>
                        <div className="font-mono text-[9px] text-muted-foreground">{rep.variant_id}</div>
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant="outline" className="text-[9px]">{rep.family}</Badge>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-[9px]",
                            rep.signal > 0 ? "border-green-300 text-green-700"
                              : rep.signal < 0 ? "border-red-300 text-red-700"
                                : "",
                          )}
                        >
                          {rep.signal_label}
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {(rep.normalized_weight * 100).toFixed(1)}%
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        <span className={rep.contribution > 0 ? "text-green-700" : rep.contribution < 0 ? "text-red-700" : ""}>
                          {rep.contribution.toFixed(4)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {rep.wfo_prom != null ? (rep.wfo_prom * 100).toFixed(3) + "%" : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function ConfigItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border bg-muted/20 p-2">
      <p className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono font-semibold">{value}</p>
    </div>
  )
}

function ScoreCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded border p-2.5 text-center">
      <p className="text-[9px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="font-mono text-lg font-bold">{value}</p>
      <p className="text-[9px] text-muted-foreground">{detail}</p>
    </div>
  )
}

export default function WfoDetailPage() {
  return (
    <Suspense>
      <WfoDetailContent />
    </Suspense>
  )
}
