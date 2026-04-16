"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Progress } from "@/components/ui/progress"
import { RefreshCw, TrendingUp, Activity, BarChart3, AlertCircle, CheckCircle2, Info, ExternalLink } from "lucide-react"
import { formatNumber } from "@/lib/format"
import { triggerWfoComputation, type WfoSummaryResponse, type WfoCategorySummary } from "@/lib/api"
import { SignalScoreBar } from "./signal-score-bar"
import { useState } from "react"
import { useRouter } from "next/navigation"
import { cn } from "@/lib/utils"

type WfoSignalColumnProps = {
  data: WfoSummaryResponse | null
  isLoading: boolean
  error: string | null
  symbol: string
  horizon: string
  onRefresh?: () => void
}

const GRADE_COLORS: Record<string, string> = {
  A: "bg-green-600 text-white hover:bg-green-700",
  B: "bg-green-500 text-white hover:bg-green-600",
  C: "bg-yellow-500 text-black hover:bg-yellow-600",
  D: "bg-orange-500 text-white hover:bg-orange-600",
  F: "bg-red-500 text-white hover:bg-red-600",
}

const CATEGORY_ICONS: Record<string, any> = {
  tendance: TrendingUp,
  momentum: Activity,
  oscillation: Activity,
  volume: BarChart3,
}

const CATEGORY_LABELS: Record<string, string> = {
  tendance: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}

export function WfoSignalColumn({
  data,
  isLoading,
  error,
  symbol,
  horizon,
  onRefresh,
}: WfoSignalColumnProps) {
  const router = useRouter()
  const [isRefreshing, setIsRefreshing] = useState(false)

  const navigateToDetail = (category: string) => {
    router.push(`/signals/wfo-detail?symbol=${encodeURIComponent(symbol)}&horizon=${encodeURIComponent(horizon)}&category=${encodeURIComponent(category)}`)
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    try {
      await triggerWfoComputation({ symbol, horizon })
      onRefresh?.()
    } catch (err) {
      console.error("Failed to trigger WFO:", err)
    } finally {
      setIsRefreshing(false)
    }
  }

  if (isLoading && !data) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-32 w-full" />
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <Card className="border-destructive/50 bg-destructive/5">
        <CardContent className="py-8 text-center">
          <AlertCircle className="h-8 w-8 text-destructive mx-auto mb-2" />
          <p className="text-sm font-medium text-destructive">Erreur de chargement WFO</p>
          <p className="text-xs text-muted-foreground mt-1">{error}</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={handleRefresh}>
            Réessayer
          </Button>
        </CardContent>
      </Card>
    )
  }

  const global = data?.global_signal
  const categories = data?.categories || {}

  return (
    <div className="space-y-5">
      {/* Global WFO Card */}
      <Card className="border-primary/20 bg-primary/5">
        <CardHeader className="pb-2 pt-4 px-4">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-primary" />
              Consensus WFO Optimisé
            </CardTitle>
            <div className="flex items-center gap-2">
              {data?.global_signal?.data_as_of && (
                <span className="text-[10px] text-muted-foreground">
                  Dernier calcul: {data.global_signal.data_as_of}
                </span>
              )}
              <Button
                variant="ghost"
                size="icon"
                className={cn("h-6 w-6", isRefreshing && "animate-spin")}
                onClick={handleRefresh}
                disabled={isRefreshing}
              >
                <RefreshCw className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="pb-4 px-4">
          {global && global.status === "succeeded" ? (
            <div className="space-y-3">
              <div className="flex flex-col items-center gap-1">
                <SignalScoreBar
                  value={global.global_score_pct ?? null}
                  size="lg"
                  className="w-full max-w-xs"
                />
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="outline" className="capitalize text-[10px] font-bold">
                    {global.recommendation?.replace("_", " ")}
                  </Badge>
                  {global.sr_modifier != null && global.sr_modifier !== 1 && (
                    <Badge variant="outline" className="text-[10px] bg-blue-50 text-blue-700 border-blue-200">
                      Modif S/R: x{global.sr_modifier?.toFixed(2)}
                    </Badge>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-[10px]">
                <div className="flex flex-col border rounded p-1.5 bg-background/50">
                  <span className="text-muted-foreground font-medium uppercase tracking-tight">Support</span>
                  <span className="font-mono font-bold text-green-700">
                    {global.sr_support_level ? formatNumber(global.sr_support_level) : "N/A"}
                  </span>
                  <span className="text-[9px] truncate opacity-70">{global.sr_support_method}</span>
                </div>
                <div className="flex flex-col border rounded p-1.5 bg-background/50">
                  <span className="text-muted-foreground font-medium uppercase tracking-tight">Résistance</span>
                  <span className="font-mono font-bold text-red-700">
                    {global.sr_resistance_level ? formatNumber(global.sr_resistance_level) : "N/A"}
                  </span>
                  <span className="text-[9px] truncate opacity-70">{global.sr_resistance_method}</span>
                </div>
              </div>
            </div>
          ) : global?.status === "running" ? (
            <div className="py-4 text-center space-y-2">
              <p className="text-xs text-muted-foreground animate-pulse">Calcul WFO en cours...</p>
              <Progress value={45} className="h-1" />
            </div>
          ) : (
            <div className="py-4 text-center">
              <p className="text-xs text-muted-foreground italic">Aucun consensus WFO disponible.</p>
              <Button variant="link" size="sm" onClick={handleRefresh} className="text-[10px]">
                Lancer le calcul hebdomadaire
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Category WFO Cards */}
      <div className="space-y-4">
        {["tendance", "momentum", "oscillation", "volume"].map((catKey) => {
          const cat = categories[catKey] as WfoCategorySummary | undefined
          const Icon = CATEGORY_ICONS[catKey] || Activity
          const label = CATEGORY_LABELS[catKey] || catKey

          return (
            <Card
              key={catKey}
              className={cn(
                !cat || cat.status === "pending" ? "opacity-60" : "",
                cat?.status === "succeeded" && "cursor-pointer transition-colors hover:border-primary/50",
              )}
              onClick={cat?.status === "succeeded" ? () => navigateToDetail(catKey) : undefined}
            >
              <CardHeader className="pb-2 pt-3 px-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs font-bold">{label}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {cat?.status === "succeeded" && (
                      <>
                        <Badge className={cn("text-[9px] h-4 font-bold px-1.5", GRADE_COLORS[cat.robustness_grade || "F"])}>
                          Grade {cat.robustness_grade}
                        </Badge>
                        <span className="text-xs font-mono font-bold">
                          {cat.score_pct && cat.score_pct >= 0 ? "+" : ""}
                          {cat.score_pct?.toFixed(1)}%
                        </span>
                      </>
                    )}
                  </div>
                </div>
                {cat?.status === "succeeded" && (
                  <SignalScoreBar value={cat.score_pct ?? null} size="sm" className="w-full mt-1" />
                )}
              </CardHeader>
              <CardContent className="pb-3 px-4 pt-0">
                {cat?.status === "succeeded" ? (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-[10px] text-muted-foreground bg-muted/30 p-1 rounded">
                      <div className="flex gap-3">
                        <span>WFE: <span className="text-foreground font-bold">{cat.wfe_pct?.toFixed(0)}%</span></span>
                        <span>Rob: <span className="text-foreground font-bold">{cat.robustness_ratio?.toFixed(2)}</span></span>
                      </div>
                      <span className="flex items-center gap-1">
                        <Info className="h-2.5 w-2.5" />
                        PROM: {cat.composite_score?.toFixed(1)}
                      </span>
                    </div>
                    
                    {/* Representatives simplified */}
                    <div className="space-y-1">
                      {cat.representatives?.slice(0, 3).map((rep, idx) => (
                        <div key={idx} className="flex items-center justify-between text-[10px]">
                          <span className="text-muted-foreground truncate max-w-[140px]">{rep.description}</span>
                          <div className="flex items-center gap-2">
                            <span className={cn(
                              "font-bold",
                              rep.signal > 0 ? "text-green-600" : rep.signal < 0 ? "text-red-600" : "text-muted-foreground"
                            )}>
                              {rep.signal_label}
                            </span>
                            <span className="text-muted-foreground opacity-60">{(rep.normalized_weight * 100).toFixed(0)}%</span>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center justify-end gap-1 mt-1.5">
                      <span className="text-[9px] text-muted-foreground">Voir details</span>
                      <ExternalLink className="h-2.5 w-2.5 text-muted-foreground" />
                    </div>
                  </div>
                ) : cat?.status === "running" ? (
                  <div className="py-2 space-y-1">
                    <Skeleton className="h-2 w-full" />
                    <Skeleton className="h-2 w-3/4" />
                  </div>
                ) : (
                  <div className="py-2 text-center">
                    <span className="text-[10px] text-muted-foreground italic">
                      {cat?.status === "failed" ? "Calcul échoué" : "En attente de calcul"}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}
