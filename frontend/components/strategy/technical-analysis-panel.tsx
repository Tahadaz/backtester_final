"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { fetchFamilyEnsemble, type FamilyCombinedSignal } from "@/lib/api"
import { useRegimeConsensus } from "@/hooks/use-api"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import { SignalScoreBar } from "./signal-score-bar"
import { WfoSignalColumn } from "./wfo-signal-column"
import { SignalAgreementBadge } from "./signal-agreement-badge"
import { SmaFamilyDrilldown } from "./sma-family-drilldown"
import { MethodologyModal } from "./methodology-modal"
import { RegimeDetailPanel } from "./regime-detail-panel"
import { SupportResistanceDrilldown } from "./support-resistance-drilldown"
import {
  INDICATOR_FAMILY_META,
  INDICATOR_FAMILY_ORDER,
  type IndicatorFamilyKey,
} from "./indicator-config"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { formatNumber } from "@/lib/format"
import { Activity, BarChart3, Info, TrendingUp } from "lucide-react"

type FamilyState = {
  data: FamilyCombinedSignal | null
  isLoading: boolean
  error: string | null
}

type CategoryId = "tendance" | "momentum" | "oscillation" | "volume"

type CategoryMeta = {
  id: CategoryId
  label: string
  description: string
  icon: typeof TrendingUp
  families: Array<(typeof INDICATOR_FAMILY_META)[number]>
}

const CATEGORY_META: CategoryMeta[] = [
  {
    id: "tendance",
    label: "Tendance",
    description: "Direction et structure du marche",
    icon: TrendingUp,
    families: INDICATOR_FAMILY_META.filter((meta) => meta.category === "tendance"),
  },
  {
    id: "momentum",
    label: "Momentum",
    description: "Acceleration et force du mouvement",
    icon: Activity,
    families: INDICATOR_FAMILY_META.filter((meta) => meta.category === "momentum"),
  },
  {
    id: "oscillation",
    label: "Oscillation",
    description: "Surachat, survendu et extremes",
    icon: Activity,
    families: INDICATOR_FAMILY_META.filter((meta) => meta.category === "oscillation"),
  },
  {
    id: "volume",
    label: "Volume",
    description: "Confirmation et pression des flux",
    icon: BarChart3,
    families: INDICATOR_FAMILY_META.filter((meta) => meta.category === "volume"),
  },
]

function createFamilyState(): Record<IndicatorFamilyKey, FamilyState> {
  return Object.fromEntries(
    INDICATOR_FAMILY_ORDER.map((family) => [
      family,
      { data: null, isLoading: false, error: null },
    ]),
  ) as Record<IndicatorFamilyKey, FamilyState>
}

function createEnabledState(): Record<IndicatorFamilyKey, boolean> {
  return Object.fromEntries(
    INDICATOR_FAMILY_ORDER.map((family) => [family, true]),
  ) as Record<IndicatorFamilyKey, boolean>
}

function labelBadgeClass(label: string): string {
  const l = label.toLowerCase()
  if (l.includes("disponible")) {
    return "text-muted-foreground border-muted-foreground/30"
  }
  if (
    l.includes("haussier") ||
    l.includes("survendu") ||
    l.includes("accumulation") ||
    l.includes("achat")
  ) {
    return "text-green-700 border-green-300"
  }
  if (
    l.includes("baissier") ||
    l.includes("surachet") ||
    l.includes("distribution") ||
    l.includes("vente")
  ) {
    return "text-red-700 border-red-300"
  }
  return "text-muted-foreground"
}

function isFamilyAvailable(data: FamilyCombinedSignal | null | undefined): data is FamilyCombinedSignal {
  return Boolean(data && data.representative_count > 0)
}

export function TechnicalAnalysisPanel({
  symbol,
  horizon,
  cooldownBars,
}: {
  symbol: string
  horizon: string
  cooldownBars?: number
}) {
  const regime = useRegimeConsensus(symbol, horizon, cooldownBars)
  const { data: wfoData, isLoading: wfoLoading, error: wfoError, refresh: wfoRefresh } = useWfoSummary(symbol, horizon)
  const [familyData, setFamilyData] = useState<Record<IndicatorFamilyKey, FamilyState>>(() =>
    createFamilyState(),
  )
  const [enabledFamilies, setEnabledFamilies] = useState<Record<IndicatorFamilyKey, boolean>>(() =>
    createEnabledState(),
  )
  const [level, setLevel] = useState(0)
  const [selectedFamily, setSelectedFamily] = useState<IndicatorFamilyKey | null>(null)
  const [methodologyOpen, setMethodologyOpen] = useState(false)
  const requestTokenRef = useRef(0)

  useEffect(() => {
    setLevel(0)
    setSelectedFamily(null)
  }, [symbol, horizon])

  useEffect(() => {
    const token = ++requestTokenRef.current
    setFamilyData((prev) => {
      const next = { ...prev }
      for (const family of INDICATOR_FAMILY_ORDER) {
        next[family] = {
          ...next[family],
          isLoading: true,
          error: null,
        }
      }
      return next
    })

    void Promise.allSettled(
      INDICATOR_FAMILY_ORDER.map((family) =>
        fetchFamilyEnsemble({
          family,
          symbol,
          horizon,
          cooldown_bars: cooldownBars,
          timeframe: "1D",
        }),
      ),
    ).then((results) => {
      if (requestTokenRef.current !== token) return
      setFamilyData((prev) => {
        const next = { ...prev }
        INDICATOR_FAMILY_ORDER.forEach((family, index) => {
          const result = results[index]
          if (result.status === "fulfilled") {
            next[family] = {
              data: result.value,
              isLoading: false,
              error: null,
            }
          } else {
            const message =
              result.reason instanceof Error && result.reason.message
                ? result.reason.message
                : "Erreur lors du chargement du signal"
            next[family] = {
              data: null,
              isLoading: false,
              error: message,
            }
          }
        })
        return next
      })
    })
  }, [cooldownBars, horizon, symbol])

  const enabledLoadedFamilies = useMemo(
    () =>
      INDICATOR_FAMILY_ORDER.filter(
        (family) => enabledFamilies[family] && isFamilyAvailable(familyData[family].data),
      ),
    [enabledFamilies, familyData],
  )
  const enabledFamiliesCount = useMemo(
    () => INDICATOR_FAMILY_ORDER.filter((family) => enabledFamilies[family]).length,
    [enabledFamilies],
  )
  const anyEnabledLoading = useMemo(
    () => INDICATOR_FAMILY_ORDER.some((family) => enabledFamilies[family] && familyData[family].isLoading),
    [enabledFamilies, familyData],
  )
  const allEnabledError = useMemo(
    () =>
      enabledFamiliesCount > 0 &&
      INDICATOR_FAMILY_ORDER.every(
        (family) => !enabledFamilies[family] || Boolean(familyData[family].error),
      ),
    [enabledFamilies, enabledFamiliesCount, familyData],
  )
  const firstError = useMemo(
    () =>
      INDICATOR_FAMILY_ORDER.map((family) => familyData[family].error).find(
        (value): value is string => Boolean(value),
      ) ?? "Erreur inconnue",
    [familyData],
  )
  const aggregateScore =
    enabledLoadedFamilies.length > 0
      ? enabledLoadedFamilies.reduce(
          (sum, family) => sum + (familyData[family].data?.family_score_pct ?? 0),
          0,
        ) / enabledLoadedFamilies.length
      : null
  const aggregateIsProvisional = enabledLoadedFamilies.some(
    (family) => familyData[family].data?.is_provisional,
  )
  const aggregateMeta =
    enabledLoadedFamilies
      .map((family) => familyData[family].data)
      .find((value): value is FamilyCombinedSignal => Boolean(value)) ??
    INDICATOR_FAMILY_ORDER.map((family) => familyData[family].data).find(
      (value): value is FamilyCombinedSignal => Boolean(value),
    ) ??
    null

  if (anyEnabledLoading && enabledLoadedFamilies.length === 0) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <div className="space-y-3">
          {[...Array(4)].map((_, index) => (
            <Skeleton key={index} className="h-36 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (allEnabledError) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="py-8 text-center">
          <p className="text-sm text-destructive font-medium">
            Erreur lors du chargement des signaux
          </p>
          <p className="text-xs text-muted-foreground mt-1">{firstError}</p>
        </CardContent>
      </Card>
    )
  }

  if (level === 2 && selectedFamily && familyData[selectedFamily]?.data) {
    return (
      <SmaFamilyDrilldown
        data={familyData[selectedFamily].data!}
        family={selectedFamily}
        cooldownBars={cooldownBars}
        onBack={() => setLevel(1)}
      />
    )
  }

  if (level === 3 && regime.data) {
    return <RegimeDetailPanel data={regime.data} onBack={() => setLevel(1)} />
  }

  return (
    <div className="space-y-5">
      {level === 0 && (
        <Card
          className="cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => setLevel(1)}
        >
          <CardContent className="flex flex-col items-center py-6 gap-2">
            <SignalScoreBar
              value={aggregateScore}
              size="lg"
              label="Consensus des signaux - Analyse Technique"
              className="w-full max-w-xs"
            />
            <div className="mt-1">
              <SignalAgreementBadge
                engineScore={aggregateScore}
                wfoScore={wfoData?.global_signal?.global_score_pct ?? null}
                wfoGrade={wfoData?.global_signal?.best_category ? wfoData.categories[wfoData.global_signal.best_category]?.robustness_grade ?? null : null}
              />
            </div>
            <div className="flex items-center gap-2 mt-2 flex-wrap justify-center">
              <Badge variant="outline" className="text-[10px]">
                {enabledLoadedFamilies.length}/{enabledFamiliesCount} familles actives
              </Badge>
              {aggregateIsProvisional && (
                <Badge variant="outline" className="text-[10px] border-amber-300 text-amber-800">
                  Provisoire
                </Badge>
              )}
              {aggregateMeta?.latest_close != null && (
                <Badge variant="outline" className="text-[10px] text-muted-foreground">
                  Cloture {formatNumber(aggregateMeta.latest_close)}
                </Badge>
              )}
              {aggregateMeta && (
                <Badge variant="outline" className="text-[10px] text-muted-foreground">
                  {aggregateMeta.as_of}
                </Badge>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              Cliquez pour voir le detail par categorie
            </p>
          </CardContent>
        </Card>
      )}

      {level === 1 && (
        <>
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLevel(0)}
              className="text-xs"
            >
              &larr; Vue d&apos;ensemble
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMethodologyOpen(true)}
              className="gap-1 text-xs"
            >
              <Info className="h-3 w-3" />
              Methodologie
            </Button>
          </div>

          <SupportResistanceDrilldown symbol={symbol} horizon={horizon} cooldownBars={cooldownBars} />

          {regime.data ? (
            <Card className="border-dashed">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3">
                <div>
                  <p className="text-xs font-semibold text-foreground">Regime-aware conditioning</p>
                  <p className="text-[11px] text-muted-foreground">
                    Experimental v0.1. Equal-weight remains the fallback if regime weighting does not improve OOS validation.
                  </p>
                </div>
                <Button variant="outline" size="sm" onClick={() => setLevel(3)}>
                  Open Regime Detail
                </Button>
              </CardContent>
            </Card>
          ) : null}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3 px-1">
                Signal Engine (A&rarr;G)
              </h3>
              {CATEGORY_META.map((category) => {
                const Icon = category.icon
                const categoryFamilies = category.families.map((family) => ({
                  meta: family,
                  enabled: enabledFamilies[family.key],
                  state: familyData[family.key],
                }))
                const enabledCategoryFamilies = categoryFamilies.filter((family) => family.enabled)
                const loadedEnabledCategoryFamilies = enabledCategoryFamilies.filter(
                  (family) => isFamilyAvailable(family.state.data),
                )
                const categoryScore =
                  loadedEnabledCategoryFamilies.length > 0
                    ? loadedEnabledCategoryFamilies.reduce(
                        (sum, family) => sum + (family.state.data?.family_score_pct ?? 0),
                        0,
                      ) / loadedEnabledCategoryFamilies.length
                    : null
                const categoryIsProvisional = loadedEnabledCategoryFamilies.some(
                  (family) => family.state.data?.is_provisional,
                )
                const anyCategoryLoading = enabledCategoryFamilies.some(
                  (family) => family.state.isLoading,
                )

                return (
                  <Card key={category.id}>
                    <CardHeader className="pb-2 pt-3 px-4">
                      <div className="flex items-center justify-between gap-3">
                        <CardTitle className="text-xs font-semibold flex items-center gap-1.5">
                          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                          {category.label}
                          <span className="text-[10px] font-normal text-muted-foreground ml-1">
                            {category.description}
                          </span>
                        </CardTitle>
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-[9px]">
                            {enabledCategoryFamilies.length}/{categoryFamilies.length} actives
                          </Badge>
                          {categoryIsProvisional && (
                            <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-800">
                              Provisoire
                            </Badge>
                          )}
                          {categoryScore !== null && (
                            <span className="text-xs font-mono font-medium">
                              {categoryScore >= 0 ? "+" : ""}
                              {categoryScore.toFixed(1)}%
                            </span>
                          )}
                        </div>
                      </div>
                      {categoryScore !== null && (
                        <SignalScoreBar value={categoryScore} size="sm" className="w-full mt-1" />
                      )}
                      {categoryScore === null && anyCategoryLoading && (
                        <Skeleton className="h-6 w-full mt-1" />
                      )}
                    </CardHeader>
                    <CardContent className="pb-3 px-4 pt-0">
                      <div className="space-y-1.5">
                        {categoryFamilies.map((family) => {
                          const data = family.state.data
                          const available = isFamilyAvailable(data)
                          const clickable = family.enabled && Boolean(data)
                          return (
                            <div
                              key={family.meta.key}
                              className={`flex items-center justify-between gap-3 rounded px-2 py-2 transition-colors ${
                                clickable
                                  ? "cursor-pointer hover:bg-muted/50"
                                  : family.enabled
                                    ? ""
                                    : "opacity-55"
                              }`}
                              onClick={() => {
                                if (!clickable) return
                                setSelectedFamily(family.meta.key)
                                setLevel(2)
                              }}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                <span className="text-xs font-medium w-16">
                                  {family.meta.shortLabel}
                                </span>
                                {data ? (
                                  <Badge
                                    variant="outline"
                                    className={`text-[9px] ${labelBadgeClass(
                                      data.family_signal_label,
                                    )}`}
                                  >
                                    {data.family_signal_label}
                                  </Badge>
                                ) : family.state.isLoading ? (
                                  <Skeleton className="h-4 w-24" />
                                ) : (
                                  <span className="text-[10px] text-muted-foreground">N/A</span>
                                )}
                                {data?.is_provisional && (
                                  <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-800">
                                    Provisoire
                                  </Badge>
                                )}
                              </div>
                              <div className="flex items-center gap-3 shrink-0">
                                {available ? (
                                  <span className="text-xs font-mono text-muted-foreground">
                                    {data.family_score_pct >= 0 ? "+" : ""}
                                    {data.family_score_pct.toFixed(1)}%
                                  </span>
                                ) : data ? (
                                  <span className="text-xs text-muted-foreground">-</span>
                                ) : null}
                                <div
                                  className="flex items-center gap-2"
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  <span className="text-[10px] text-muted-foreground">Actif</span>
                                  <Switch
                                    checked={family.enabled}
                                    onCheckedChange={(checked) =>
                                      setEnabledFamilies((prev) => ({
                                        ...prev,
                                        [family.meta.key]: checked,
                                      }))
                                    }
                                  />
                                </div>
                                {clickable ? (
                                  <span className="text-[10px] text-muted-foreground">&rarr;</span>
                                ) : null}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>

            <div className="space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-3 px-1">
                WFO Optimis&eacute; (Hebdomadaire)
              </h3>
              <WfoSignalColumn
                data={wfoData}
                isLoading={wfoLoading}
                error={wfoError}
                symbol={symbol}
                horizon={horizon}
                onRefresh={wfoRefresh}
              />
            </div>
          </div>
        </>
      )}

      <MethodologyModal
        open={methodologyOpen}
        onClose={() => setMethodologyOpen(false)}
      />
    </div>
  )
}
