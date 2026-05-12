"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  FamilyCombinedSignalSchema,
  fetchSignalEngineResultWithBootstrap,
  type FamilyCombinedSignal,
  type WfoSummaryResponse,
} from "@/lib/api"
import { useFactorSelectionActive, useRegimeConsensus } from "@/hooks/use-api"
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
  family: string,
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
  const fallbackVariants = asArray(detail.fallback_variants)

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
    fallback_variants: fallbackVariants,
    score_explanation: asString(detail.score_explanation, ""),
    methodology_status: asString(detail.methodology_status, "robust_oos_ensemble"),
    methodology_mode: asString(detail.methodology_mode, asString(detail.methodology_status, "robust_oos_ensemble")),
    available_bars: asNumber(detail.available_bars, 0),
    nominal_window: asRecord(detail.nominal_window) ?? { train: 0, test: 0, step: 0, target_windows: 0 },
    effective_window: asRecord(detail.effective_window) ?? { train: 0, test: 0, step: 0, target_windows: 0 },
    warning_message: asString(detail.warning_message, asString(payload.warning_message, "")),
    is_provisional: asBoolean(detail.is_provisional, asBoolean(payload.is_provisional, false)),
    as_of: asString(detail.as_of, asString(payload.data_as_of, "")),
    latest_close:
      typeof detail.latest_close === "number"
        ? detail.latest_close
        : null,
    best_variant_id: asString(detail.best_variant_id, ""),
  }

  const parsed = FamilyCombinedSignalSchema.safeParse(candidate)
  return parsed.success ? parsed.data : null
}

function comboFamilyKey(variant: string | undefined, category: CategoryId): string | null {
  const value = variant ?? ""
  if (!value.endsWith("_combo")) return null
  if (value.startsWith("legacy_factor_x_ta")) return `legacy_fx_combo_${category}`
  if (value.startsWith("expanded_factor_x_ta")) return `expanded_fx_combo_${category}`
  if (value.startsWith("legacy_ta")) return `legacy_ta_combo_${category}`
  return `expanded_ta_combo_${category}`
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

function fmtLevel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return formatNumber(value)
}

function resolveSupportResistanceLevels(data: Record<string, unknown> | null | undefined) {
  const record = data ?? {}
  const hasOptimal = record.optimal_status === "ready"
  const supportValue = hasOptimal
    ? (typeof record.optimal_support === "number" ? record.optimal_support : null)
    : (typeof record.preview_support === "number"
        ? record.preview_support
        : (typeof record.final_support === "number" ? record.final_support : null))
  const resistanceValue = hasOptimal
    ? (typeof record.optimal_resistance === "number" ? record.optimal_resistance : null)
    : (typeof record.preview_resistance === "number"
        ? record.preview_resistance
        : (typeof record.final_resistance === "number" ? record.final_resistance : null))
  const supportSource = hasOptimal
    ? (typeof record.selected_support_method_id === "string" ? record.selected_support_method_id : null)
    : (typeof record.preview_support_method_id === "string"
        ? record.preview_support_method_id
        : (typeof record.selected_support_method_id === "string" ? record.selected_support_method_id : null))
  const resistanceSource = hasOptimal
    ? (typeof record.selected_resistance_method_id === "string" ? record.selected_resistance_method_id : null)
    : (typeof record.preview_resistance_method_id === "string"
        ? record.preview_resistance_method_id
        : (typeof record.selected_resistance_method_id === "string" ? record.selected_resistance_method_id : null))
  const closeValue = typeof record.current_close === "number" ? record.current_close : null

  return {
    close: closeValue,
    supportValue,
    resistanceValue,
    supportSource,
    resistanceSource,
  }
}

function SignalEngineConsensusCard({
  aggregateScore,
  aggregateIsProvisional,
  aggregateMeta,
  supportResistance,
  loadedFamilyCount,
  enabledFamilyCount,
}: {
  aggregateScore: number | null
  aggregateIsProvisional: boolean
  aggregateMeta: FamilyCombinedSignal | null
  supportResistance: Record<string, unknown> | null | undefined
  loadedFamilyCount?: number
  enabledFamilyCount?: number
}) {
  const levels = resolveSupportResistanceLevels(supportResistance)

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardHeader className="pb-2 pt-4 px-4">
        <CardTitle className="text-sm font-bold">Consensus Signal Engine (A&rarr;G)</CardTitle>
      </CardHeader>
      <CardContent className="pb-4 px-4 space-y-3">
        <div className="flex flex-col items-center gap-1">
          <SignalScoreBar value={aggregateScore} size="lg" className="w-full max-w-xs" />
        </div>

        <div className="flex items-center gap-2 flex-wrap justify-center">
          {typeof loadedFamilyCount === "number" && typeof enabledFamilyCount === "number" && (
            <Badge variant="outline" className="text-[10px]">
              {loadedFamilyCount}/{enabledFamilyCount} familles actives
            </Badge>
          )}
          {levels.close != null && (
            <Badge variant="outline" className="text-[10px] text-muted-foreground">
              Cloture {fmtLevel(levels.close)}
            </Badge>
          )}
          {aggregateIsProvisional && (
            <Badge variant="outline" className="text-[10px] border-amber-300 text-amber-800">
              Provisoire
            </Badge>
          )}
          {aggregateMeta?.as_of && (
            <Badge variant="outline" className="text-[10px] text-muted-foreground">
              {aggregateMeta.as_of}
            </Badge>
          )}
        </div>

        <div className="grid grid-cols-2 gap-2 text-[10px]">
          <div className="flex flex-col border rounded p-1.5 bg-emerald-50/60">
            <span className="text-emerald-700 font-medium uppercase tracking-tight">Support</span>
            <span className="font-mono font-bold text-emerald-700">{fmtLevel(levels.supportValue)}</span>
            <span className="text-[9px] truncate text-emerald-700/80">{levels.supportSource ?? "--"}</span>
          </div>
          <div className="flex flex-col border rounded p-1.5 bg-red-50/60">
            <span className="text-red-700 font-medium uppercase tracking-tight">Resistance</span>
            <span className="font-mono font-bold text-red-700">{fmtLevel(levels.resistanceValue)}</span>
            <span className="text-[9px] truncate text-red-700/80">{levels.resistanceSource ?? "--"}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function WfoConsensusCard({
  data,
  isLoading,
  error,
}: {
  data: WfoSummaryResponse | null
  isLoading: boolean
  error: string | null
}) {
  if (isLoading && !data) {
    return (
      <Card className="border-primary/20 bg-primary/5">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-bold">Consensus WFO optimise</CardTitle>
        </CardHeader>
        <CardContent className="pb-4 px-4 space-y-2">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-10 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className="border-destructive/50 bg-destructive/5">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-bold">Consensus WFO optimise</CardTitle>
        </CardHeader>
        <CardContent className="pb-4 px-4">
          <p className="text-xs text-destructive">Erreur WFO: {error}</p>
        </CardContent>
      </Card>
    )
  }

  const global = data?.global_signal
  const isReady = global?.status === "succeeded"

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardHeader className="pb-2 pt-4 px-4">
        <CardTitle className="text-sm font-bold">Consensus WFO optimise</CardTitle>
      </CardHeader>
      <CardContent className="pb-4 px-4 space-y-3">
        {isReady ? (
          <>
            <div className="flex flex-col items-center gap-1">
              <SignalScoreBar value={global?.global_score_pct ?? null} size="lg" className="w-full max-w-xs" />
            </div>

            <div className="flex items-center gap-2 flex-wrap justify-center">
              {global?.recommendation && (
                <Badge variant="outline" className="capitalize text-[10px] font-bold">
                  {global.recommendation.replace("_", " ")}
                </Badge>
              )}
              {global?.data_as_of && (
                <Badge variant="outline" className="text-[10px] text-muted-foreground">
                  {global.data_as_of}
                </Badge>
              )}
            </div>

            <div className="grid grid-cols-2 gap-2 text-[10px]">
              <div className="flex flex-col border rounded p-1.5 bg-emerald-50/60">
                <span className="text-emerald-700 font-medium uppercase tracking-tight">Support</span>
                <span className="font-mono font-bold text-emerald-700">{fmtLevel(global?.sr_support_level)}</span>
                <span className="text-[9px] truncate text-emerald-700/80">{global?.sr_support_method ?? "--"}</span>
              </div>
              <div className="flex flex-col border rounded p-1.5 bg-red-50/60">
                <span className="text-red-700 font-medium uppercase tracking-tight">Resistance</span>
                <span className="font-mono font-bold text-red-700">{fmtLevel(global?.sr_resistance_level)}</span>
                <span className="text-[9px] truncate text-red-700/80">{global?.sr_resistance_method ?? "--"}</span>
              </div>
            </div>
          </>
        ) : (
          <p className="text-xs text-muted-foreground italic">Aucun consensus WFO disponible.</p>
        )}
      </CardContent>
    </Card>
  )
}

export function TechnicalAnalysisPanel({
  symbol,
  horizon,
  cooldownBars,
  variant,
}: {
  symbol: string
  horizon: string
  cooldownBars?: number
  variant?: string
}) {
  const regime = useRegimeConsensus(symbol, horizon, cooldownBars, variant)
  const { data: wfoData, isLoading: wfoLoading, error: wfoError, refresh: wfoRefresh } = useWfoSummary(symbol, horizon, variant ?? "expanded")
  const [familyData, setFamilyData] = useState<Record<IndicatorFamilyKey, FamilyState>>(() =>
    createFamilyState(),
  )
  const [supportResistanceSnapshot, setSupportResistanceSnapshot] = useState<Record<string, unknown> | null>(null)
  const [enabledFamilies, setEnabledFamilies] = useState<Record<IndicatorFamilyKey, boolean>>(() =>
    createEnabledState(),
  )
  const [level, setLevel] = useState(0)
  const [selectedFamily, setSelectedFamily] = useState<IndicatorFamilyKey | null>(null)
  const [methodologyOpen, setMethodologyOpen] = useState(false)
  const [persistedFallbackNotice, setPersistedFallbackNotice] = useState<string | null>(null)
  const requestTokenRef = useRef(0)
  const isFactorXTa = (variant ?? "").includes("factor_x_ta")
  const { data: factorSelectionActive } = useFactorSelectionActive(isFactorXTa ? symbol : null, horizon)

  useEffect(() => {
    setLevel(0)
    setSelectedFamily(null)
  }, [symbol, horizon, variant])

  useEffect(() => {
    const token = ++requestTokenRef.current
    let pollTimer: ReturnType<typeof setTimeout> | null = null
    const markLoading = () => {
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
    }

    const loadAutoResolved = async (isInitial: boolean) => {
      if (isInitial) markLoading()
      try {
        const result = await fetchSignalEngineResultWithBootstrap(symbol, horizon, variant ?? "expanded")
        if (requestTokenRef.current !== token) return
        const familiesPayload = asRecord(result.families) ?? {}
        const next = createFamilyState()

        if ((variant ?? "").endsWith("_combo")) {
          CATEGORY_META.forEach((category) => {
            const displayFamily = category.families[0]?.key
            const persistedKey = comboFamilyKey(variant, category.id)
            if (!displayFamily || !persistedKey) return
            const persisted = persistedFamilyToSignal(
              persistedKey,
              symbol,
              horizon,
              familiesPayload[persistedKey],
            )
            next[displayFamily] = {
              data: persisted,
              isLoading: false,
              error: null,
            }
          })
        } else {
          INDICATOR_FAMILY_ORDER.forEach((family) => {
            const persisted = persistedFamilyToSignal(
              family,
              symbol,
              horizon,
              familiesPayload[family],
            )
            next[family] = {
              data: persisted,
              isLoading: false,
              error: null,
            }
          })
        }

        const isStale = result.resolution_mode === "stale_cache" || result.is_stale
        const notice: string | null = isStale
          ? "Données provisoires : recalcul en cours, mise à jour automatique dans quelques instants."
          : null

        setSupportResistanceSnapshot(asRecord(result.support_resistance))
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
        setSupportResistanceSnapshot(null)
        setFamilyData((prev) => {
          const next = { ...prev }
          for (const family of INDICATOR_FAMILY_ORDER) {
            next[family] = {
              data: null,
              isLoading: false,
              error: message,
            }
          }
          return next
        })
      }
    }

    void loadAutoResolved(true)
    return () => {
      if (pollTimer) clearTimeout(pollTimer)
    }
  }, [horizon, symbol, variant])

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
  const factorXTaEmptyNotice = useMemo(() => {
    if (!isFactorXTa || anyEnabledLoading || enabledLoadedFamilies.length > 0) return null
    const activeRows = factorSelectionActive ?? []
    if (activeRows.length === 0) {
      return "Aucun facteur macro utilisable n'a franchi le score IC composite pour ce titre et cet horizon."
    }
    if (activeRows.some((row) => row.low_confidence || row.selected_reason === "low_confidence")) {
      const factors = activeRows.map((row) => row.factor_canonical_id).join(", ")
      return `Facteur(s) retenu(s) en basse confiance (${factors}), mais aucun representant Factor×TA robuste n'a survecu.`
    }
    const factors = activeRows.map((row) => row.factor_canonical_id).join(", ")
    return `Facteur(s) retenu(s) (${factors}), mais les conditions macro × TA n'ont produit aucun representant robuste.`
  }, [anyEnabledLoading, enabledLoadedFamilies.length, factorSelectionActive, isFactorXTa])

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
        variant={variant}
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
      {factorXTaEmptyNotice && (
        <Card className="border-sky-200 bg-sky-50/70">
          <CardContent className="py-3 text-xs text-sky-900">
            {factorXTaEmptyNotice}
          </CardContent>
        </Card>
      )}
      {level === 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <button type="button" className="text-left" onClick={() => setLevel(1)}>
              <SignalEngineConsensusCard
                aggregateScore={aggregateScore}
                aggregateIsProvisional={aggregateIsProvisional}
                aggregateMeta={aggregateMeta}
                supportResistance={supportResistanceSnapshot}
                loadedFamilyCount={enabledLoadedFamilies.length}
                enabledFamilyCount={enabledFamiliesCount}
              />
            </button>
            <button type="button" className="text-left" onClick={() => setLevel(1)}>
              <WfoConsensusCard
                data={wfoData}
                isLoading={wfoLoading}
                error={wfoError}
              />
            </button>
          </div>

          <div className="flex items-center justify-center">
            <SignalAgreementBadge
              engineScore={aggregateScore}
              wfoScore={wfoData?.global_signal?.global_score_pct ?? null}
              wfoGrade={wfoData?.global_signal?.best_category ? wfoData.categories[wfoData.global_signal.best_category]?.robustness_grade ?? null : null}
            />
          </div>

          <p className="text-[10px] text-muted-foreground text-center">
            Cliquez pour voir le detail par categorie
          </p>
        </div>
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

          <SupportResistanceDrilldown symbol={symbol} horizon={horizon} cooldownBars={cooldownBars} variant={variant} />

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
              <SignalEngineConsensusCard
                aggregateScore={aggregateScore}
                aggregateIsProvisional={aggregateIsProvisional}
                aggregateMeta={aggregateMeta}
                supportResistance={supportResistanceSnapshot}
                loadedFamilyCount={enabledLoadedFamilies.length}
                enabledFamilyCount={enabledFamiliesCount}
              />

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
                          const shortLabel =
                            (variant ?? "").endsWith("_combo") && data?.family?.includes("_combo_")
                              ? "Combo"
                              : family.meta.shortLabel
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
                                  {shortLabel}
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
                variant={variant ?? "expanded"}
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
