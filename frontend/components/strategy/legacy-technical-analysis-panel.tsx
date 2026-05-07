"use client"

import { useEffect, useRef, useState } from "react"
import { Activity, BarChart3, Info, TrendingUp } from "lucide-react"
import { useRegimeConsensus } from "@/hooks/use-api"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import {
  FamilyCombinedSignalSchema,
  fetchSignalEngineResultWithBootstrap,
  type FamilyCombinedSignal,
} from "@/lib/api"
import { formatNumber } from "@/lib/format"
import { MethodologyModal } from "@/components/strategy/methodology-modal"
import { RegimeDetailPanel } from "@/components/strategy/regime-detail-panel"
import { SignalScoreBar } from "@/components/strategy/signal-score-bar"
import { WfoSignalColumn } from "@/components/strategy/wfo-signal-column"
import { SignalAgreementBadge } from "@/components/strategy/signal-agreement-badge"
import { SmaFamilyDrilldown } from "@/components/strategy/sma-family-drilldown"
import { SupportResistanceDrilldown } from "@/components/strategy/support-resistance-drilldown"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

type LegacyFamilyId = "sma" | "macd" | "rsi" | "obv"

type LegacyCategory = {
  id: "tendance" | "momentum" | "oscillation" | "volume"
  label: string
  description: string
  icon: typeof TrendingUp
  families: Array<{ id: LegacyFamilyId; label: string }>
}

const CATEGORIES: LegacyCategory[] = [
  {
    id: "tendance",
    label: "Tendance",
    description: "Direction du marche",
    icon: TrendingUp,
    families: [{ id: "sma", label: "SMA" }],
  },
  {
    id: "momentum",
    label: "Momentum",
    description: "Dynamique du marche",
    icon: Activity,
    families: [{ id: "macd", label: "MACD" }],
  },
  {
    id: "oscillation",
    label: "Oscillation",
    description: "Conditions de marche",
    icon: Activity,
    families: [{ id: "rsi", label: "RSI" }],
  },
  {
    id: "volume",
    label: "Volume",
    description: "Confirmation par le volume",
    icon: BarChart3,
    families: [{ id: "obv", label: "OBV" }],
  },
]

const ALL_FAMILIES = CATEGORIES.flatMap((category) => category.families)
const LEGACY_FAMILIES: LegacyFamilyId[] = ["sma", "rsi", "macd", "obv"]

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback
}

function asBoolean(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback
}

function persistedFamilyToSignal(
  family: LegacyFamilyId,
  symbol: string,
  horizon: string,
  raw: unknown,
): FamilyCombinedSignal | null {
  const payload = asRecord(raw)
  if (!payload) return null
  const detail = asRecord(payload.family_detail) ?? {}
  const representatives = asArray(detail.representatives).length > 0
    ? asArray(detail.representatives)
    : asArray(payload.representatives)

  const candidate = {
    family: asString(detail.family, family),
    symbol: asString(detail.symbol, symbol),
    horizon: asString(detail.horizon, horizon),
    timeframe: asString(detail.timeframe, "1D"),
    family_score_pct: asNumber(detail.family_score_pct, asNumber(payload.family_score_pct, 0)),
    family_signal_label: asString(detail.family_signal_label, asString(payload.signal_label, "Pas disponible")),
    tested_count: asNumber(detail.tested_count, asNumber(payload.tested_count, 0)),
    viable_count: asNumber(detail.viable_count, asNumber(payload.viable_count, 0)),
    competitive_count: asNumber(detail.competitive_count, asNumber(payload.competitive_count, 0)),
    representative_count: asNumber(detail.representative_count, asNumber(payload.representative_count, representatives.length)),
    representatives,
    fallback_variants: asArray(detail.fallback_variants),
    score_explanation: asString(detail.score_explanation, ""),
    methodology_status: asString(detail.methodology_status, "robust_oos_ensemble"),
    methodology_mode: asString(detail.methodology_mode, asString(detail.methodology_status, "robust_oos_ensemble")),
    available_bars: asNumber(detail.available_bars, 0),
    nominal_window: asRecord(detail.nominal_window) ?? { train: 0, test: 0, step: 0, target_windows: 0 },
    effective_window: asRecord(detail.effective_window) ?? { train: 0, test: 0, step: 0, target_windows: 0 },
    warning_message: asString(detail.warning_message, asString(payload.warning_message, "")),
    is_provisional: asBoolean(detail.is_provisional, asBoolean(payload.is_provisional, false)),
    as_of: asString(detail.as_of, asString(payload.data_as_of, "")),
    latest_close: typeof detail.latest_close === "number" ? detail.latest_close : null,
    best_variant_id: asString(detail.best_variant_id, ""),
  }
  const parsed = FamilyCombinedSignalSchema.safeParse(candidate)
  return parsed.success ? parsed.data : null
}

function labelBadgeClass(label: string): string {
  const lower = label.toLowerCase()
  if (
    lower.includes("haussier") ||
    lower.includes("survendu") ||
    lower.includes("accumulation") ||
    lower.includes("achat")
  ) {
    return "text-green-700 border-green-300"
  }
  if (
    lower.includes("baissier") ||
    lower.includes("surachet") ||
    lower.includes("distribution") ||
    lower.includes("vente")
  ) {
    return "text-red-700 border-red-300"
  }
  return "text-muted-foreground"
}

export function LegacyTechnicalAnalysisPanel({
  symbol,
  horizon,
  cooldownBars,
}: {
  symbol: string
  horizon: string
  cooldownBars?: number
}) {
  const regime = useRegimeConsensus(symbol, horizon, cooldownBars)
  const { data: wfoData, isLoading: wfoLoading, error: wfoError, refresh: wfoRefresh } = useWfoSummary(symbol, horizon, "legacy")

  const [familyData, setFamilyData] = useState<Record<LegacyFamilyId, { data?: FamilyCombinedSignal; isLoading: boolean; error: unknown }>>({
    sma: { data: undefined, isLoading: true, error: null },
    rsi: { data: undefined, isLoading: true, error: null },
    macd: { data: undefined, isLoading: true, error: null },
    obv: { data: undefined, isLoading: true, error: null },
  })
  const requestTokenRef = useRef(0)

  const [level, setLevel] = useState(0)
  const [selectedFamily, setSelectedFamily] = useState<LegacyFamilyId | null>(null)
  const [methodologyOpen, setMethodologyOpen] = useState(false)
  const [persistedFallbackNotice, setPersistedFallbackNotice] = useState<string | null>(null)

  useEffect(() => {
    setLevel(0)
    setSelectedFamily(null)
  }, [symbol, horizon])

  useEffect(() => {
    const token = ++requestTokenRef.current
    let pollTimer: ReturnType<typeof setTimeout> | null = null
    const markLoading = () => {
      setFamilyData((prev) => ({
        sma: { ...prev.sma, isLoading: true, error: null },
        rsi: { ...prev.rsi, isLoading: true, error: null },
        macd: { ...prev.macd, isLoading: true, error: null },
        obv: { ...prev.obv, isLoading: true, error: null },
      }))
    }

    const loadAutoResolved = async (isInitial: boolean) => {
      if (isInitial) markLoading()
      try {
        const result = await fetchSignalEngineResultWithBootstrap(symbol, horizon, "legacy")
        if (requestTokenRef.current !== token) return
        const payload = asRecord(result.families) ?? {}
        const next: Record<LegacyFamilyId, { data?: FamilyCombinedSignal; isLoading: boolean; error: unknown }> = {
          sma: { data: persistedFamilyToSignal("sma", symbol, horizon, payload.sma) ?? undefined, isLoading: false, error: null as unknown },
          rsi: { data: persistedFamilyToSignal("rsi", symbol, horizon, payload.rsi) ?? undefined, isLoading: false, error: null as unknown },
          macd: { data: persistedFamilyToSignal("macd", symbol, horizon, payload.macd) ?? undefined, isLoading: false, error: null as unknown },
          obv: { data: persistedFamilyToSignal("obv", symbol, horizon, payload.obv) ?? undefined, isLoading: false, error: null as unknown },
        }

        const isStale = result.resolution_mode === "stale_cache" || result.is_stale
        const notice: string | null = isStale
          ? "Données provisoires : recalcul en cours, mise à jour automatique dans quelques instants."
          : null
        setPersistedFallbackNotice(notice)
        setFamilyData(next)

        if (isStale) {
          pollTimer = setTimeout(() => {
            if (requestTokenRef.current === token) void loadAutoResolved(false)
          }, 15000)
        }
      } catch (error) {
        if (requestTokenRef.current !== token) return
        const message =
          error instanceof Error && error.message
            ? error.message
            : "Erreur lors du chargement des signaux persistes"
        setPersistedFallbackNotice(null)
        setFamilyData({
          sma: { data: undefined, isLoading: false, error: message },
          rsi: { data: undefined, isLoading: false, error: message },
          macd: { data: undefined, isLoading: false, error: message },
          obv: { data: undefined, isLoading: false, error: message },
        })
      }
    }

    void loadAutoResolved(true)
    return () => {
      if (pollTimer) clearTimeout(pollTimer)
    }
  }, [horizon, symbol])

  const loadedFamilies = ALL_FAMILIES.filter((family) => familyData[family.id].data)
  const anyLoading = ALL_FAMILIES.some((family) => familyData[family.id].isLoading)
  const allError = ALL_FAMILIES.every((family) => familyData[family.id].error)

  if (anyLoading && loadedFamilies.length === 0) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <div className="space-y-3">
          {[...Array(3)].map((_, index) => (
            <Skeleton key={index} className="h-28 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (allError) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="py-8 text-center">
          <p className="text-sm font-medium text-destructive">
            Erreur lors du chargement du signal
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {typeof familyData.sma.error === "string" ? familyData.sma.error : "Erreur inconnue"}
          </p>
        </CardContent>
      </Card>
    )
  }

  const aggregateScore =
    loadedFamilies.length > 0
      ? loadedFamilies.reduce(
          (sum, family) => sum + (familyData[family.id].data?.family_score_pct ?? 0),
          0,
        ) / loadedFamilies.length
      : null
  const aggregateIsProvisional = loadedFamilies.some(
    (family) => familyData[family.id].data?.is_provisional,
  )
  const aggregateMeta = familyData.sma.data ?? familyData.rsi.data ?? familyData.macd.data ?? familyData.obv.data

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
      {persistedFallbackNotice && (
        <Card className="border-amber-300 bg-amber-50/70">
          <CardContent className="py-3 text-xs text-amber-900">
            {persistedFallbackNotice}
          </CardContent>
        </Card>
      )}
      {level === 0 && (
        <Card
          className="cursor-pointer transition-colors hover:border-primary/50"
          onClick={() => setLevel(1)}
        >
          <CardContent className="flex flex-col items-center gap-2 py-6">
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
            <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
              <Badge variant="outline" className="text-[10px]">
                {loadedFamilies.length}/{ALL_FAMILIES.length} familles
              </Badge>
              {aggregateIsProvisional && (
                <Badge variant="outline" className="border-amber-300 text-[10px] text-amber-800">
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
            <p className="mt-1 text-[10px] text-muted-foreground">
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
              {CATEGORIES.map((category) => {
                const Icon = category.icon
                const categoryFamilyData = category.families.map((family) => ({
                  ...family,
                  data: familyData[family.id],
                }))
                const loadedCategoryFamilies = categoryFamilyData.filter((family) => family.data.data)
                const categoryScore =
                  loadedCategoryFamilies.length > 0
                    ? loadedCategoryFamilies.reduce(
                        (sum, family) => sum + (family.data.data?.family_score_pct ?? 0),
                        0,
                      ) / loadedCategoryFamilies.length
                    : null
                const anyCategoryLoading = categoryFamilyData.some((family) => family.data.isLoading)
                const categoryIsProvisional = loadedCategoryFamilies.some(
                  (family) => family.data.data?.is_provisional,
                )

                return (
                  <Card key={category.id}>
                    <CardHeader className="px-4 pb-2 pt-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="flex items-center gap-1.5 text-xs font-semibold">
                          <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                          {category.label}
                          <span className="ml-1 text-[10px] font-normal text-muted-foreground">
                            {category.description}
                          </span>
                        </CardTitle>
                        {categoryScore !== null && (
                          <div className="flex items-center gap-2">
                            {categoryIsProvisional && (
                              <Badge variant="outline" className="border-amber-300 text-[9px] text-amber-800">
                                Provisoire
                              </Badge>
                            )}
                            <span className="text-xs font-medium font-mono">
                              {categoryScore >= 0 ? "+" : ""}
                              {categoryScore.toFixed(1)}%
                            </span>
                          </div>
                        )}
                      </div>
                      {categoryScore !== null && (
                        <SignalScoreBar value={categoryScore} size="sm" className="mt-1 w-full" />
                      )}
                      {categoryScore === null && anyCategoryLoading && (
                        <Skeleton className="mt-1 h-6 w-full" />
                      )}
                    </CardHeader>
                    <CardContent className="px-4 pb-3 pt-0">
                      <div className="space-y-1.5">
                        {categoryFamilyData.map((family) => {
                          if (family.data.data) {
                            return (
                              <div
                                key={family.id}
                                className="flex cursor-pointer items-center justify-between rounded px-2 py-1.5 transition-colors hover:bg-muted/50"
                                onClick={() => {
                                  setSelectedFamily(family.id)
                                  setLevel(2)
                                }}
                              >
                                <div className="flex items-center gap-2">
                                  <span className="w-12 text-xs font-medium">{family.label}</span>
                                  <Badge
                                    variant="outline"
                                    className={`text-[9px] ${labelBadgeClass(
                                      family.data.data.family_signal_label,
                                    )}`}
                                  >
                                    {family.data.data.family_signal_label}
                                  </Badge>
                                  {family.data.data.is_provisional && (
                                    <Badge variant="outline" className="border-amber-300 text-[9px] text-amber-800">
                                      Provisoire
                                    </Badge>
                                  )}
                                </div>
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-mono text-muted-foreground">
                                    {family.data.data.family_score_pct >= 0 ? "+" : ""}
                                    {family.data.data.family_score_pct.toFixed(1)}%
                                  </span>
                                  <span className="text-[10px] text-muted-foreground">&rarr;</span>
                                </div>
                              </div>
                            )
                          }

                          return (
                            <div
                              key={family.id}
                              className="flex items-center justify-between px-2 py-1.5 opacity-50"
                            >
                              <span className="w-12 text-xs font-medium">{family.label}</span>
                              {family.data.isLoading ? (
                                <Skeleton className="h-4 w-20" />
                              ) : (
                                <span className="text-[10px] text-muted-foreground">N/A</span>
                              )}
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
                variant="legacy"
                onRefresh={wfoRefresh}
              />
            </div>
          </div>
        </>
      )}

      <MethodologyModal open={methodologyOpen} onClose={() => setMethodologyOpen(false)} />
    </div>
  )
}
