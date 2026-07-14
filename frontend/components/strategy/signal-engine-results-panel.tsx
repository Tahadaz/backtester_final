"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useRouter } from "next/navigation"
import { Activity, BarChart3, ExternalLink, Layers3, TrendingUp } from "lucide-react"
import {
  FamilyCombinedSignalSchema,
  fetchSignalEngineResultWithBootstrap,
  type FamilyCombinedSignal,
  type SignalEngineResult,
  type SignalRepresentative,
  type SupportResistanceVariantsResponse,
  type VariantSummary,
} from "@/lib/api"
import { useSupportResistanceVariants } from "@/hooks/use-api"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import { signalVariantLabel } from "@/lib/signal-variant-label"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalBadge } from "@/components/signal-badge"
import {
  INDICATOR_FAMILY_META,
  INDICATOR_FAMILY_ORDER,
  type IndicatorFamilyKey,
  type IndicatorFamilyMeta,
} from "./indicator-config"

type CategoryId = "tendance" | "momentum" | "oscillation" | "volume"

type CategoryMeta = {
  id: CategoryId
  label: string
  description: string
  icon: typeof TrendingUp
  families: IndicatorFamilyMeta[]
}

type FamilyResultRow = {
  key: string
  label: string
  description: string
  isCombo: boolean
  data: FamilyCombinedSignal | null
}

type ResultsState = {
  result: SignalEngineResult | null
  rows: Record<CategoryId, FamilyResultRow[]>
}

const EMPTY_ROWS: Record<CategoryId, FamilyResultRow[]> = {
  tendance: [],
  momentum: [],
  oscillation: [],
  volume: [],
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

const META_BY_KEY = Object.fromEntries(
  INDICATOR_FAMILY_META.map((meta) => [meta.key, meta]),
) as Record<IndicatorFamilyKey, IndicatorFamilyMeta>

const FACTOR_TICKER_LABELS: Record<string, string> = {
  "^VIX": "VIX",
  "^GSPC": "SP500",
  "^NDX": "NDX",
  "^N225": "N225",
  "^FCHI": "CAC",
  "^FTSE": "FTSE",
  "BZ=F": "BRENT",
  "GC=F": "GOLD",
  "SI=F": "SILVER",
  "DX-Y.NYB": "DXY",
  "EURUSD=X": "EURUSD",
  "AED=X": "AED",
  "^TNX": "US10Y",
  "BTC-USD": "BTC",
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
    latest_close: typeof detail.latest_close === "number" ? detail.latest_close : null,
    best_variant_id: asString(detail.best_variant_id, ""),
  }

  const parsed = FamilyCombinedSignalSchema.safeParse(candidate)
  return parsed.success ? parsed.data : null
}

function comboFamilyKey(variant: string, category: CategoryId): string {
  if (variant.startsWith("legacy_factor_x_ta")) return `legacy_fx_combo_${category}`
  if (variant.startsWith("expanded_factor_x_ta")) return `expanded_fx_combo_${category}`
  if (variant.startsWith("legacy_ta")) return `legacy_ta_combo_${category}`
  return `expanded_ta_combo_${category}`
}

function representativeLabel(rep: SignalRepresentative): string {
  return signalVariantLabel(rep)
}

function factorConditionRule(condition: Record<string, unknown>): string {
  const direction = asString(condition.direction)
  const sym = direction === "below" ? "<" : ">"
  const form = asString(condition.form)
  const lookback = condition.lookback
  const threshold = typeof condition.threshold === "number" ? condition.threshold : Number(condition.threshold ?? 0)
  if (form === "zscore") return `z${lookback} ${sym} ${threshold}`
  if (form === "momentum") return `mom${lookback} ${sym} ${(threshold * 100).toFixed(1)}%`
  if (form === "change") return `change(${lookback}) ${sym} ${threshold}`
  if (form === "level") return `level ${sym} ${threshold}`
  if (form === "direction") return `dir ${sym} 0`
  return `${form}(${lookback}) ${sym} ${threshold}`
}

function collectFactorConditions(rep: SignalRepresentative): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = []
  const seen = new Set<string>()
  const add = (value: unknown) => {
    const condition = asRecord(value)
    if (!condition) return
    const ticker = asString(condition.factor_ticker)
    const id = asString(condition.condition_id)
    if (!ticker || !id) return
    const key = `${ticker}:${id}`
    if (seen.has(key)) return
    seen.add(key)
    out.push(condition)
  }
  add(rep.factor_condition)
  const params = asRecord(rep.params)
  for (const component of asArray(params?.components)) {
    const componentRecord = asRecord(component)
    add(componentRecord?.factor_condition)
  }
  return out
}

function FactorDependencyChips({ reps }: { reps: SignalRepresentative[] }) {
  const seen = new Set<string>()
  const conditions = reps.flatMap(collectFactorConditions).filter((condition) => {
    const key = `${asString(condition.factor_ticker)}:${asString(condition.condition_id)}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
  if (conditions.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1">
      {conditions.slice(0, 4).map((condition) => {
        const ticker = asString(condition.factor_ticker)
        const id = asString(condition.condition_id)
        const label = FACTOR_TICKER_LABELS[ticker] ?? ticker
        return (
          <span
            key={`${ticker}:${id}`}
            className="inline-flex max-w-full items-center rounded border border-border bg-muted/35 px-1.5 py-0.5 text-[9px] font-semibold text-muted-foreground"
            title={`${label} ${factorConditionRule(condition)}`}
          >
            <span>{label}</span>
            <span className="ml-1 font-mono font-normal">{factorConditionRule(condition)}</span>
          </span>
        )
      })}
      {conditions.length > 4 ? <span className="text-[9px] text-muted-foreground">+{conditions.length - 4}</span> : null}
    </div>
  )
}

function scoreTone(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground"
  if (score > 15) return "text-[oklch(0.50_0.13_165)]"
  if (score < -15) return "text-[oklch(0.52_0.20_25)]"
  return "text-muted-foreground"
}

function formatSignedScore(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "--"
  return `${score >= 0 ? "+" : ""}${score.toFixed(1)}%`
}

function normalizeResults(
  result: SignalEngineResult,
  symbol: string,
  horizon: string,
  variant: string,
): Record<CategoryId, FamilyResultRow[]> {
  const payload = asRecord(result.families) ?? {}
  const rows: Record<CategoryId, FamilyResultRow[]> = {
    tendance: [],
    momentum: [],
    oscillation: [],
    volume: [],
  }

  if (variant.endsWith("_combo")) {
    for (const category of CATEGORY_META) {
      const family = comboFamilyKey(variant, category.id)
      const data = persistedFamilyToSignal(family, symbol, horizon, payload[family])
      rows[category.id].push({
        key: family,
        label: "Strict AND combo",
        description: category.description,
        isCombo: true,
        data,
      })
    }
    return rows
  }

  const availableKeys = new Set(Object.keys(payload))
  const familyKeys = INDICATOR_FAMILY_ORDER.filter((family) => availableKeys.has(family))

  for (const family of familyKeys) {
    const meta = META_BY_KEY[family]
    const data = persistedFamilyToSignal(family, symbol, horizon, payload[family])
    rows[meta.category].push({
      key: family,
      label: meta.shortLabel,
      description: meta.description,
      isCombo: false,
      data,
    })
  }

  return rows
}

function averageScore(rows: FamilyResultRow[]): number | null {
  const scores = rows
    .map((row) => row.data?.family_score_pct)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
  if (scores.length === 0) return null
  return scores.reduce((sum, value) => sum + value, 0) / scores.length
}

function VariantRows({
  variants,
  symbol,
  horizon,
  variant,
  cooldownBars,
  provisional,
}: {
  variants: SignalRepresentative[]
  symbol: string
  horizon: string
  variant: string
  cooldownBars: number
  provisional?: boolean
}) {
  const router = useRouter()

  if (variants.length === 0) return null

  return (
    <div className="space-y-1">
      {variants.map((rep) => (
        <button
          key={`${rep.variant_id}-${provisional ? "fallback" : "rep"}`}
          type="button"
          onClick={() =>
            router.push(
              `/signals/variant/${encodeURIComponent(rep.variant_id)}?symbol=${encodeURIComponent(symbol)}&horizon=${horizon}&cooldown=${cooldownBars}&variant=${variant}`,
            )
          }
          className="flex w-full items-center justify-between gap-3 rounded-md border border-transparent px-2 py-1.5 text-left transition-colors hover:border-primary/40 hover:bg-muted/30"
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate font-mono text-[11px] font-semibold">
                {representativeLabel(rep)}
              </span>
              {provisional ? (
                <Badge variant="outline" className="h-5 text-[9px] border-amber-300 text-amber-800">
                  Provisoire
                </Badge>
              ) : null}
            </div>
            <div className="truncate text-[10px] text-muted-foreground">
              {(rep.archetype || rep.variant_id).replace(/_/g, " ")}
            </div>
            <div className="mt-1">
              <FactorDependencyChips reps={[rep]} />
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <SignalBadge value={rep.signal} label={rep.signal_label} size="sm" />
            <span className="font-mono text-[10px] text-muted-foreground">
              w={formatNumber(rep.normalized_weight, 2)}
            </span>
            <ExternalLink className="h-3 w-3 text-muted-foreground" />
          </div>
        </button>
      ))}
    </div>
  )
}

function FamilyResultCard({
  row,
  symbol,
  horizon,
  variant,
  cooldownBars,
}: {
  row: FamilyResultRow
  symbol: string
  horizon: string
  variant: string
  cooldownBars: number
}) {
  const router = useRouter()
  const data = row.data

  return (
    <div className="rounded-md border border-border bg-card p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{row.label}</span>
            {row.isCombo ? (
              <Badge variant="outline" className="h-5 text-[10px]">
                Combo
              </Badge>
            ) : null}
            {data?.is_provisional ? (
              <Badge variant="outline" className="h-5 text-[10px] border-amber-300 text-amber-800">
                Provisoire
              </Badge>
            ) : null}
          </div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">{row.description}</p>
          {data ? (
            <div className="mt-1">
              <FactorDependencyChips reps={[...data.representatives, ...data.fallback_variants]} />
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {data ? <SignalBadge value={data.family_score_pct / 100} label={data.family_signal_label} size="sm" /> : null}
          <span className={cn("font-mono text-xs font-semibold", scoreTone(data?.family_score_pct))}>
            {formatSignedScore(data?.family_score_pct)}
          </span>
        </div>
      </div>

      {data ? (
        <>
          <div className="mt-3 grid grid-cols-4 gap-2 text-center">
            {[
              ["Testees", data.tested_count],
              ["Viables", data.viable_count],
              ["Competitives", data.competitive_count],
              ["Reps", data.representative_count],
            ].map(([label, value]) => (
              <div key={label} className="rounded border bg-muted/20 px-2 py-1.5">
                <div className="font-mono text-sm font-semibold">{value}</div>
                <div className="text-[9px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
              </div>
            ))}
          </div>

          {data.score_explanation ? (
            <p className="mt-3 text-[11px] text-muted-foreground">{data.score_explanation}</p>
          ) : null}

          <div className="mt-3 space-y-3">
            <VariantRows
              variants={data.representatives}
              symbol={symbol}
              horizon={horizon}
              variant={variant}
              cooldownBars={cooldownBars}
            />
            <VariantRows
              variants={data.fallback_variants}
              symbol={symbol}
              horizon={horizon}
              variant={variant}
              cooldownBars={cooldownBars}
              provisional
            />
          </div>

          {data.representative_count === 0 && data.fallback_variants.length === 0 ? (
            <div className="mt-3 rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
              Aucun representant robuste pour cette famille.
              {data.best_variant_id ? (
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="ml-1 h-auto p-0 text-xs"
                  onClick={() =>
                    router.push(
                      `/signals/variant/${encodeURIComponent(data.best_variant_id)}?symbol=${encodeURIComponent(symbol)}&horizon=${horizon}&cooldown=${cooldownBars}&variant=${variant}`,
                    )
                  }
                >
                  Voir la meilleure variante
                </Button>
              ) : null}
            </div>
          ) : null}
        </>
      ) : (
        <div className="mt-3 rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
          Aucun resultat persiste pour cette famille dans le mode actif.
        </div>
      )}
    </div>
  )
}

function srVariantHref({
  variantId,
  symbol,
  horizon,
  cooldownBars,
  variant,
}: {
  variantId: string
  symbol: string
  horizon: string
  cooldownBars: number
  variant: string
}) {
  return `/signals/sr-variant/${encodeURIComponent(variantId)}?symbol=${encodeURIComponent(symbol)}&horizon=${encodeURIComponent(horizon)}&cooldown=${cooldownBars}&variant=${encodeURIComponent(variant)}`
}

function srFamilyHref({
  symbol,
  horizon,
  cooldownBars,
  variant,
}: {
  symbol: string
  horizon: string
  cooldownBars: number
  variant: string
}) {
  return `/signals/sr-variants?symbol=${encodeURIComponent(symbol)}&horizon=${encodeURIComponent(horizon)}&cooldown=${cooldownBars}&variant=${encodeURIComponent(variant)}`
}

function SupportResistanceVariantRow({
  item,
  symbol,
  horizon,
  variant,
  cooldownBars,
  fallback,
}: {
  item: VariantSummary
  symbol: string
  horizon: string
  variant: string
  cooldownBars: number
  fallback?: boolean
}) {
  const router = useRouter()
  const objective = item.sr_objective_score ?? item.reliability_score

  return (
    <button
      type="button"
      onClick={() => router.push(srVariantHref({ variantId: item.variant_id, symbol, horizon, cooldownBars, variant }))}
      className="flex w-full items-center justify-between gap-3 rounded-md border border-transparent px-2 py-1.5 text-left transition-colors hover:border-primary/40 hover:bg-muted/30"
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-[11px] font-semibold">{item.description}</span>
          {fallback ? (
            <Badge variant="outline" className="h-5 shrink-0 border-amber-300 text-[9px] text-amber-800">
              Meilleure disponible
            </Badge>
          ) : null}
        </div>
        <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{item.variant_id}</div>
        <div className="mt-1 flex flex-wrap gap-1.5 text-[9px] text-muted-foreground">
          <span>S {item.support_level == null ? "--" : formatNumber(item.support_level, 2)}</span>
          <span>R {item.resistance_level == null ? "--" : formatNumber(item.resistance_level, 2)}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <SignalBadge value={item.signal_value} label={item.signal_label} size="sm" />
        <span className="font-mono text-[10px] text-muted-foreground">
          SR {(objective * 100).toFixed(1)}%
        </span>
        <ExternalLink className="h-3 w-3 text-muted-foreground" />
      </div>
    </button>
  )
}

function SupportResistanceResultCard({
  data,
  isLoading,
  error,
  symbol,
  horizon,
  variant,
  cooldownBars,
}: {
  data: SupportResistanceVariantsResponse | undefined
  isLoading: boolean
  error: unknown
  symbol: string
  horizon: string
  variant: string
  cooldownBars: number
}) {
  const router = useRouter()
  const representatives = data?.representatives ?? []
  const bestAvailable = data?.all_variants.find((item) => item.variant_id === data.best_variant_id)
    ?? data?.all_variants[0]
    ?? null
  const displayed = representatives.length > 0 ? representatives : bestAvailable ? [bestAvailable] : []

  return (
    <Card>
      <CardHeader className="px-4 pb-2 pt-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm font-bold">
              <Layers3 className="h-4 w-4 text-muted-foreground" />
              Support / Resistance
            </CardTitle>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Niveaux structurels et couples S/R robustes
            </p>
          </div>
          {data ? (
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {data.optimal_status === "ready" ? "Pret" : data.optimal_status}
            </Badge>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 px-4 pb-4">
        {isLoading && !data ? (
          <Skeleton className="h-40 w-full rounded-md" />
        ) : error || !data ? (
          <div className="rounded-md border border-dashed bg-muted/20 p-4 text-center text-xs text-muted-foreground">
            Variantes S/R indisponibles.
          </div>
        ) : (
          <>
            <div className="rounded-md border border-border bg-card p-3">
              <div className="grid grid-cols-4 gap-2 text-center">
                {[
                  ["Testees", data.tested_count],
                  ["Viables", data.viable_count],
                  ["Competitives", data.competitive_count],
                  ["Reps", data.representative_count],
                ].map(([label, value]) => (
                  <div key={label} className="rounded border bg-muted/20 px-2 py-1.5">
                    <div className="font-mono text-sm font-semibold">{value}</div>
                    <div className="text-[9px] uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
                  </div>
                ))}
              </div>

              <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                <div className="rounded border border-emerald-200 bg-emerald-50/40 px-2 py-1.5 dark:bg-emerald-950/20">
                  <div className="text-[9px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">Support</div>
                  <div className="font-mono font-semibold">{data.final_support == null ? "--" : formatNumber(data.final_support, 2)}</div>
                </div>
                <div className="rounded border border-red-200 bg-red-50/40 px-2 py-1.5 dark:bg-red-950/20">
                  <div className="text-[9px] font-semibold uppercase tracking-wide text-red-700 dark:text-red-400">Resistance</div>
                  <div className="font-mono font-semibold">{data.final_resistance == null ? "--" : formatNumber(data.final_resistance, 2)}</div>
                </div>
              </div>

              {data.score_explanation ? (
                <p className="mt-3 text-[11px] text-muted-foreground">{data.score_explanation}</p>
              ) : null}

              <div className="mt-3 space-y-1">
                {displayed.map((item) => (
                  <SupportResistanceVariantRow
                    key={item.variant_id}
                    item={item}
                    symbol={symbol}
                    horizon={horizon}
                    variant={variant}
                    cooldownBars={cooldownBars}
                    fallback={representatives.length === 0}
                  />
                ))}
                {displayed.length === 0 ? (
                  <div className="rounded-md border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground">
                    Aucun couple S/R disponible.
                  </div>
                ) : null}
              </div>
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              className="w-full gap-2 text-xs"
              onClick={() => router.push(srFamilyHref({ symbol, horizon, cooldownBars, variant }))}
            >
              Voir toutes les variantes S/R
              <ExternalLink className="h-3 w-3" />
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  )
}

export function SignalEngineResultsPanel({
  symbol,
  horizon,
  variant,
  cooldownBars,
}: {
  symbol: string
  horizon: string
  variant: string
  cooldownBars: number
}) {
  const [state, setState] = useState<ResultsState>({ result: null, rows: EMPTY_ROWS })
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestTokenRef = useRef(0)
  const supportResistance = useSupportResistanceVariants(
    symbol,
    horizon,
    33,
    cooldownBars,
    variant,
    Boolean(symbol),
  )

  useEffect(() => {
    const token = ++requestTokenRef.current
    setIsLoading(true)
    setError(null)

    fetchSignalEngineResultWithBootstrap(symbol, horizon, variant)
      .then((result) => {
        if (requestTokenRef.current !== token) return
        setState({
          result,
          rows: normalizeResults(result, symbol, horizon, variant),
        })
      })
      .catch((err) => {
        if (requestTokenRef.current !== token) return
        setState({ result: null, rows: EMPTY_ROWS })
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (requestTokenRef.current === token) setIsLoading(false)
      })

    return () => {
      requestTokenRef.current += 1
    }
  }, [horizon, symbol, variant])

  const categoriesWithRows = useMemo(
    () => CATEGORY_META.map((category) => ({ ...category, rows: state.rows[category.id] })),
    [state.rows],
  )

  if (isLoading && !state.result) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24 w-full rounded-md" />
        <div className="grid gap-3 xl:grid-cols-2">
          {[...Array(4)].map((_, index) => (
            <Skeleton key={index} className="h-52 w-full rounded-md" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="py-8 text-center">
          <p className="text-sm font-semibold text-destructive">Erreur Signal Engine</p>
          <p className="mt-1 text-xs text-muted-foreground">{error}</p>
        </CardContent>
      </Card>
    )
  }

  const result = state.result
  const stale = result?.resolution_mode === "stale_cache" || result?.is_stale

  return (
    <div className="space-y-3.5">
      <Card className="border-primary/20 bg-primary/5">
        <CardHeader className="pb-2 pt-3 px-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-sm font-bold">
                <Layers3 className="h-4 w-4 text-primary" />
                Resultats Signal Engine
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Categories, familles et variantes representatives du mode actif.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {stale ? (
                <Badge variant="outline" className="border-amber-300 text-amber-800">
                  Donnees provisoires
                </Badge>
              ) : null}
              <Badge variant="outline" className="font-mono text-[10px]">
                {variant}
              </Badge>
            </div>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 px-4 pb-4 sm:grid-cols-3">
          <div className="rounded-md border bg-background p-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Score global
            </div>
            <div className={cn("mt-1 font-mono text-lg font-bold", scoreTone(result?.aggregate_score_pct))}>
              {formatSignedScore(result?.aggregate_score_pct)}
            </div>
          </div>
          <div className="rounded-md border bg-background p-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Signal
            </div>
            <div className="mt-1">
              <SignalBadge
                value={(result?.aggregate_score_pct ?? 0) / 100}
                label={result?.signal_label ?? undefined}
                size="sm"
              />
            </div>
          </div>
          <div className="rounded-md border bg-background p-3">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              As of
            </div>
            <div className="mt-1 font-mono text-sm font-semibold">
              {result?.data_as_of ?? result?.computed_at ?? "--"}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 xl:grid-cols-2">
        {categoriesWithRows.map((category) => {
          const Icon = category.icon
          const categoryScore = averageScore(category.rows)
          return (
            <Card key={category.id}>
              <CardHeader className="pb-2 pt-3 px-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-sm font-bold">
                      <Icon className="h-4 w-4 text-muted-foreground" />
                      {category.label}
                    </CardTitle>
                    <p className="mt-1 text-[11px] text-muted-foreground">{category.description}</p>
                  </div>
                  <span className={cn("shrink-0 font-mono text-xs font-semibold", scoreTone(categoryScore))}>
                    {formatSignedScore(categoryScore)}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="space-y-3 px-4 pb-4">
                {category.rows.length > 0 ? (
                  category.rows.map((row) => (
                    <FamilyResultCard
                      key={row.key}
                      row={row}
                      symbol={symbol}
                      horizon={horizon}
                      variant={variant}
                      cooldownBars={cooldownBars}
                    />
                  ))
                ) : (
                  <div className="rounded-md border border-dashed bg-muted/20 p-4 text-center text-xs text-muted-foreground">
                    Aucun resultat pour cette categorie dans le mode actif.
                  </div>
                )}
              </CardContent>
            </Card>
          )
        })}
        <SupportResistanceResultCard
          data={supportResistance.data}
          isLoading={supportResistance.isLoading}
          error={supportResistance.error}
          symbol={symbol}
          horizon={horizon}
          variant={variant}
          cooldownBars={cooldownBars}
        />
      </div>
    </div>
  )
}
