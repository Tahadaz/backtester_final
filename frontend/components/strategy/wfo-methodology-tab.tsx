"use client"

import { useState } from "react"
import { ChevronDown, ChevronRight, Play, RefreshCw, Settings } from "lucide-react"
import { useWfoConfig } from "@/hooks/use-wfo-config"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import { fetchWfoBatchStatus, triggerAllWfo, triggerWfoComputation } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type WfoMethodologyTabProps = {
  symbol: string
  horizon: string
  variant: string
}

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

function asRecord(value: unknown): Record<string, any> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, any>)
    : null
}

function formatTriplet(config: Record<string, any> | null): string {
  if (!config) return "Auto"
  const train = config.train_bars
  const oos = config.oos_bars
  const step = config.step_bars
  if (train == null || oos == null || step == null) return "Auto"
  return `${train}/${oos}/${step}`
}

export function WfoMethodologyTab({ symbol, horizon, variant }: WfoMethodologyTabProps) {
  const { data: config, isLoading: configLoading } = useWfoConfig()
  const { data: wfoData, isLoading: wfoLoading, refresh: wfoRefresh } = useWfoSummary(symbol, horizon, variant)
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())
  const [isTriggering, setIsTriggering] = useState(false)
  const [isTriggeringAll, setIsTriggeringAll] = useState(false)
  const [batchStatus, setBatchStatus] = useState<{
    total: number; succeeded: number; running: number; failed: number; pending: number
  } | null>(null)

  // Editable overrides
  const horizonConfig = config?.horizons?.[horizon]
  const [trainBars, setTrainBars] = useState<number | null>(null)
  const [oosBars, setOosBars] = useState<number | null>(null)
  const [stepBars, setStepBars] = useState<number | null>(null)
  const [costBps, setCostBps] = useState<number | null>(null)
  const [maxReps, setMaxReps] = useState<number | null>(null)
  const [maxCorr, setMaxCorr] = useState<number | null>(null)
  const policyDefaults = config?.window_policy_defaults
  const scoringDefaults = config?.scoring
  const maxRepresentativesDefault = scoringDefaults?.max_representatives
  const maxCorrelationDefault = scoringDefaults?.max_correlation
  const trainBand = policyDefaults?.train_bands?.[horizon]
  const manualWindowOverride = trainBars != null || oosBars != null || stepBars != null

  const toggleStep = (id: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleCategory = (cat: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const handleTrigger = async (categories?: string[]) => {
    setIsTriggering(true)
    try {
      await triggerWfoComputation({
        symbol,
        horizon,
        variant,
        categories,
        train_bars: trainBars ?? undefined,
        oos_bars: oosBars ?? undefined,
        step_bars: stepBars ?? undefined,
        window_policy: manualWindowOverride ? "manual_override" : policyDefaults?.default_policy,
        top_k_folds: policyDefaults?.top_k_folds,
        min_walk_forwards: policyDefaults?.min_walk_forwards,
        strict_fallback_enabled: policyDefaults?.strict_fallback_enabled,
        strict_fallback_floor: policyDefaults?.strict_fallback_floor,
        cost_bps: costBps ?? undefined,
        max_reps: maxReps ?? undefined,
        max_corr: maxCorr ?? undefined,
      })
      // Poll after a short delay
      setTimeout(() => wfoRefresh(), 2000)
    } catch (err) {
      console.error("WFO trigger failed:", err)
    } finally {
      setIsTriggering(false)
    }
  }

  const handleTriggerAll = async () => {
    setIsTriggeringAll(true)
    try {
      await triggerAllWfo({
        variants: [variant],
        train_bars: trainBars ?? undefined,
        oos_bars: oosBars ?? undefined,
        step_bars: stepBars ?? undefined,
        window_policy: manualWindowOverride ? "manual_override" : policyDefaults?.default_policy,
        top_k_folds: policyDefaults?.top_k_folds,
        min_walk_forwards: policyDefaults?.min_walk_forwards,
        strict_fallback_enabled: policyDefaults?.strict_fallback_enabled,
        strict_fallback_floor: policyDefaults?.strict_fallback_floor,
        cost_bps: costBps ?? undefined,
        max_reps: maxReps ?? undefined,
        max_corr: maxCorr ?? undefined,
      })
      // Start polling batch status every 5s
      const poll = setInterval(async () => {
        try {
          const status = await fetchWfoBatchStatus()
          setBatchStatus(status)
          if (status.running === 0 && status.pending === 0) {
            clearInterval(poll)
            setIsTriggeringAll(false)
          }
        } catch {
          // ignore transient errors
        }
      }, 5000)
      const initial = await fetchWfoBatchStatus()
      setBatchStatus(initial)
    } catch (err) {
      console.error("WFO trigger-all failed:", err)
      setIsTriggeringAll(false)
    }
  }

  if (configLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-60 w-full" />
      </div>
    )
  }

  if (!config) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          Impossible de charger la configuration WFO.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Section 1: Pipeline Overview */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-bold">Pipeline WFO — Methodologie</CardTitle>
          <p className="text-xs text-muted-foreground">
            Le Walk-Forward Optimization (WFO) evalue systematiquement chaque indicateur technique
            sur des fenetres glissantes train/test pour produire un signal robuste et valide hors echantillon.
          </p>
          <p className="text-[11px] text-amber-700">
            Les representants restent figes pendant la semaine. Les mises a jour quotidiennes
            rafraichissent seulement leur signal courant, leur valeur courante et leur contribution.
          </p>
        </CardHeader>
        <CardContent className="space-y-1 pb-4">
          {config.pipeline_steps.map((step, idx) => {
            const isExpanded = expandedSteps.has(step.id)
            // Check if this step has completed based on WFO data
            const catStatuses = Object.values(wfoData?.categories || {})
            const anySucceeded = catStatuses.some((c) => c.status === "succeeded")
            const anyRunning = catStatuses.some((c) => c.status === "running")
            const globalReady = wfoData?.global_signal?.status === "succeeded"

            let stepStatus: "pending" | "running" | "done" = "pending"
            if (step.id === "consensus" && globalReady) stepStatus = "done"
            else if (step.id !== "consensus" && anySucceeded) stepStatus = "done"
            else if (anyRunning) stepStatus = idx <= 1 ? "running" : "pending"

            return (
              <div key={step.id}>
                <button
                  className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left transition-colors hover:bg-muted/50"
                  onClick={() => toggleStep(step.id)}
                >
                  <div className={cn(
                    "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold border",
                    stepStatus === "done"
                      ? "bg-green-100 border-green-400 text-green-700"
                      : stepStatus === "running"
                        ? "bg-blue-100 border-blue-400 text-blue-700 animate-pulse"
                        : "bg-muted border-border text-muted-foreground"
                  )}>
                    {idx + 1}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold">{step.label}</p>
                    <p className="text-[10px] text-muted-foreground truncate">{step.description}</p>
                  </div>
                  {isExpanded ? (
                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  )}
                </button>
                {isExpanded && step.detail && (
                  <div className="ml-12 mr-3 mb-2 rounded-md bg-muted/30 p-3">
                    <p className="text-[11px] text-muted-foreground leading-relaxed whitespace-pre-line">
                      {step.detail}
                    </p>
                  </div>
                )}
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* Section 2: Horizon Configuration */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-bold flex items-center gap-2">
              <Settings className="h-4 w-4 text-muted-foreground" />
              Configuration de l&apos;horizon
            </CardTitle>
            <Badge variant="outline" className="text-[10px] capitalize">{horizon}</Badge>
          </div>
        </CardHeader>
        <CardContent className="pb-4">
          <div className="mb-3 flex flex-wrap gap-2">
            <Badge variant={manualWindowOverride ? "secondary" : "outline"} className="text-[10px]">
              {manualWindowOverride ? "Override manuel" : "Auto strict"}
            </Badge>
            {trainBand && (
              <Badge variant="outline" className="text-[10px]">
                Bande train: {trainBand.min}-{trainBand.max}
              </Badge>
            )}
            {policyDefaults?.ratio_anchors && (
              <Badge variant="outline" className="text-[10px]">
                Ratio OOS/IS: {policyDefaults.ratio_anchors.map((v) => v.toFixed(2)).join(" / ")}
              </Badge>
            )}
            {policyDefaults && (
              <Badge variant="outline" className="text-[10px]">
                Min folds: {policyDefaults.min_walk_forwards} | Top K: {policyDefaults.top_k_folds}
              </Badge>
            )}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <div>
              <Label className="text-[10px] text-muted-foreground">Train (barres IS)</Label>
              <Input
                type="number"
                className="h-7 text-xs mt-1"
                placeholder={String(horizonConfig?.train ?? "")}
                value={trainBars ?? ""}
                onChange={(e) => setTrainBars(e.target.value ? Number(e.target.value) : null)}
              />
              <p className="text-[9px] text-muted-foreground mt-0.5">
                Defaut: {horizonConfig?.train}
              </p>
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Test (barres OOS)</Label>
              <Input
                type="number"
                className="h-7 text-xs mt-1"
                placeholder={String(horizonConfig?.test ?? "")}
                value={oosBars ?? ""}
                onChange={(e) => setOosBars(e.target.value ? Number(e.target.value) : null)}
              />
              <p className="text-[9px] text-muted-foreground mt-0.5">
                Defaut: {horizonConfig?.test}
              </p>
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Step (barres)</Label>
              <Input
                type="number"
                className="h-7 text-xs mt-1"
                placeholder={String(horizonConfig?.step ?? "")}
                value={stepBars ?? ""}
                onChange={(e) => setStepBars(e.target.value ? Number(e.target.value) : null)}
              />
              <p className="text-[9px] text-muted-foreground mt-0.5">
                Defaut: {horizonConfig?.step}
              </p>
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Cout (bps)</Label>
              <Input
                type="number"
                className="h-7 text-xs mt-1"
                placeholder="10"
                step={1}
                value={costBps ?? ""}
                onChange={(e) => setCostBps(e.target.value ? Number(e.target.value) : null)}
              />
              <p className="text-[9px] text-muted-foreground mt-0.5">Defaut: 10</p>
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Max representants</Label>
              <Input
                type="number"
                className="h-7 text-xs mt-1"
                placeholder={String(maxRepresentativesDefault ?? 1)}
                min={1}
                max={20}
                value={maxReps ?? ""}
                onChange={(e) => setMaxReps(e.target.value ? Number(e.target.value) : null)}
              />
              <p className="text-[9px] text-muted-foreground mt-0.5">
                Defaut: {maxRepresentativesDefault ?? 1}
              </p>
            </div>
            <div>
              <Label className="text-[10px] text-muted-foreground">Max correlation</Label>
              <Input
                type="number"
                className="h-7 text-xs mt-1"
                placeholder={String(maxCorrelationDefault ?? 0.85)}
                step={0.05}
                min={0}
                max={1}
                value={maxCorr ?? ""}
                onChange={(e) => setMaxCorr(e.target.value ? Number(e.target.value) : null)}
              />
              <p className="text-[9px] text-muted-foreground mt-0.5">
                Defaut: {maxCorrelationDefault ?? 0.85}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Section 3: Family Strategies by Category */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-bold">Strategies par categorie</CardTitle>
          <p className="text-xs text-muted-foreground">
            Chaque categorie regroupe des familles d&apos;indicateurs evalues par le WFO.
          </p>
        </CardHeader>
        <CardContent className="space-y-1 pb-4">
          {Object.entries(config.categories).map(([catKey, families]) => {
            const isExpanded = expandedCategories.has(catKey)
            const catData = wfoData?.categories?.[catKey]
            return (
              <div key={catKey}>
                <button
                  className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left transition-colors hover:bg-muted/50"
                  onClick={() => toggleCategory(catKey)}
                >
                  <div className="flex items-center gap-2">
                    {isExpanded ? (
                      <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                    )}
                    <span className="text-xs font-semibold">
                      {CATEGORY_LABELS[catKey] || catKey}
                    </span>
                    <Badge variant="outline" className="text-[9px]">
                      {families.length} familles
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    {catData?.status === "succeeded" && (
                      <>
                        <Badge className={cn("text-[9px] h-4 px-1.5 font-bold", GRADE_COLORS[catData.robustness_grade || "F"])}>
                          {catData.robustness_grade}
                        </Badge>
                        <span className="text-[10px] font-mono">
                          {(catData.score_pct ?? 0) >= 0 ? "+" : ""}
                          {catData.score_pct?.toFixed(1)}%
                        </span>
                      </>
                    )}
                    {catData?.status === "running" && (
                      <Badge variant="outline" className="text-[9px] animate-pulse border-blue-300 text-blue-600">
                        En cours...
                      </Badge>
                    )}
                    {(!catData || catData.status === "pending") && (
                      <Badge variant="outline" className="text-[9px] text-muted-foreground">
                        En attente
                      </Badge>
                    )}
                    {catData?.status === "failed" && (
                      <Badge variant="outline" className="text-[9px] border-red-300 text-red-600">
                        Echoue
                      </Badge>
                    )}
                  </div>
                </button>
                {isExpanded && (
                  <div className="ml-6 mr-3 mb-2 space-y-1.5">
                    {families.map((family) => {
                      const desc = config.family_descriptions[family]
                      return (
                        <div key={family} className="flex items-start gap-2 rounded bg-muted/20 px-3 py-2">
                          <Badge variant="outline" className="text-[9px] mt-0.5 shrink-0">
                            {desc?.label || family}
                          </Badge>
                          <p className="text-[10px] text-muted-foreground">
                            {desc?.description || family}
                          </p>
                        </div>
                      )
                    })}
                    {catData?.config && (() => {
                      const configUsed = asRecord(catData.config)
                      const selectedConfig = asRecord(configUsed?.selected_config) ?? configUsed
                      return (
                        <div className="rounded bg-muted/30 px-3 py-2 text-[10px] text-muted-foreground">
                          <div className="flex flex-wrap gap-2">
                            <Badge variant="outline" className="text-[9px]">
                              {String(configUsed?.window_policy_used ?? "strict_fold_driven")}
                            </Badge>
                            <Badge variant="outline" className="text-[9px]">
                              Config: {formatTriplet(selectedConfig)}
                            </Badge>
                            {configUsed?.fallback_applied ? (
                              <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-700">
                                Fallback min folds: {String(configUsed?.effective_min_walk_forwards ?? "--")}
                              </Badge>
                            ) : null}
                          </div>
                        </div>
                      )
                    })()}
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-[10px] h-6 mt-1"
                      disabled={isTriggering}
                      onClick={() => handleTrigger([catKey])}
                    >
                      <Play className="h-3 w-3 mr-1" />
                      Lancer WFO {CATEGORY_LABELS[catKey]}
                    </Button>
                  </div>
                )}
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* Section 4: Scoring Reference */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-bold">Reference de scoring</CardTitle>
        </CardHeader>
        <CardContent className="pb-4 space-y-4">
          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Seuils de grade
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th className="px-2 py-1 text-left font-medium">Grade</th>
                    <th className="px-2 py-1 text-right font-medium">WFE min</th>
                    <th className="px-2 py-1 text-right font-medium">Robustesse min</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(config.scoring.grade_thresholds).map(([grade, thresholds]) => (
                    <tr key={grade} className="border-b border-border/30">
                      <td className="px-2 py-1">
                        <Badge className={cn("text-[9px] h-4 px-1.5 font-bold", GRADE_COLORS[grade])}>
                          {grade}
                        </Badge>
                      </td>
                      <td className="px-2 py-1 text-right font-mono">{(thresholds.wfe * 100).toFixed(0)}%</td>
                      <td className="px-2 py-1 text-right font-mono">{(thresholds.robustness * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              Score composite
            </p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(config.scoring.composite_weights).map(([key, weight]) => (
                <Badge key={key} variant="outline" className="text-[10px]">
                  {key}: {(weight * 100).toFixed(0)}%
                </Badge>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              Formule: {Object.entries(config.scoring.composite_weights)
                .map(([k, w]) => `${(w * 100).toFixed(0)}% ${k}`)
                .join(" + ")}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Section 5: Trigger */}
      <Card className="border-primary/20 bg-primary/5">
        <CardContent className="py-4 space-y-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-bold">Lancer le calcul WFO</p>
              <p className="text-[10px] text-muted-foreground">
                {symbol} / {horizon}
                {manualWindowOverride || costBps || maxReps || maxCorr
                  ? " (parametres personnalises)"
                  : " (auto strict par defaut)"}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="text-xs"
                disabled={wfoLoading}
                onClick={wfoRefresh}
              >
                <RefreshCw className={cn("h-3 w-3 mr-1", wfoLoading && "animate-spin")} />
                Rafraichir
              </Button>
              <Button
                size="sm"
                className="text-xs"
                disabled={isTriggering}
                onClick={() => handleTrigger()}
              >
                <Play className="h-3 w-3 mr-1" />
                Lancer tout
              </Button>
              <Button
                size="sm"
                variant="secondary"
                className="text-xs"
                disabled={isTriggeringAll}
                onClick={handleTriggerAll}
              >
                <Play className="h-3 w-3 mr-1" />
                Lancer WFO global (tous les titres)
              </Button>
            </div>
          </div>
          {batchStatus && (
            <div className="space-y-1">
              <p className="text-[10px] text-muted-foreground">
                {batchStatus.succeeded}/{batchStatus.total} terminés
                {batchStatus.running > 0 && ` · ${batchStatus.running} en cours`}
                {batchStatus.failed > 0 && ` · ${batchStatus.failed} échoués`}
              </p>
              <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-primary transition-all"
                  style={{ width: batchStatus.total > 0 ? `${(batchStatus.succeeded / batchStatus.total) * 100}%` : "0%" }}
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
