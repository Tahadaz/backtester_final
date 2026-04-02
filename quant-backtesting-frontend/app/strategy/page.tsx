"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { CoreStrategyHeader } from "@/components/strategy/core-strategy-header"
import { StrategyRail } from "@/components/strategy-plan/strategy-rail"
import { SignalScoreBar } from "@/components/strategy/signal-score-bar"
import { SignalZoneChart } from "@/components/strategy/signal-zone-chart"
import {
  useExecution,
  useSignalConsensus,
  useSignalZoneChart,
  useStrategies,
  useStrategyAllocation,
  useUniverse,
} from "@/hooks/use-api"
import {
  archiveStrategy,
  createStrategy,
  duplicateStrategy,
  updateStrategy,
  type StrategyAllocationRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import {
  ChartColumnIncreasing,
  CircleDollarSign,
  Globe,
  Info,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
} from "lucide-react"

type SortBy = "adv20" | "signal_score"
type SortDir = "asc" | "desc"

interface ManualOverrideConfig {
  enabled: boolean
  capital_mad: number
}

interface LegacyBetSizingConfig {
  starter_threshold: number
  starter_target_pct: number
  medium_threshold: number
  medium_target_pct: number
  large_threshold: number
  large_target_pct: number
  max_threshold: number
  max_target_pct: number
  reduce_to_large_below: number
  reduce_to_medium_below: number
  reduce_to_starter_below: number
  exit_below: number
}

interface CalibrationBucketRow {
  score_low: number
  score_high: number
  n_observations: number
  avg_r_multiple: number
  avg_net_return: number
  win_rate: number
  target_exposure_pct: number
}

interface CalibrationSnapshot {
  status: "ok" | "provisional" | "fallback"
  lookback_bars: number
  window_start?: string | null
  window_end?: string | null
  n_observations: number
  primary_metric: string
  bucket_rows: CalibrationBucketRow[]
  ladder: Array<Record<string, unknown>>
  reason?: string | null
}

interface BetSizingConfig {
  mode: "auto_calibrated"
  calibration_lookback_bars: number
  min_observations: number
  min_bucket_observations: number
  primary_metric: "avg_r_multiple"
  bucket_count: number
  exposure_levels: number[]
  sample_method: "event_deduped"
  legacy_manual_ladder?: LegacyBetSizingConfig | null
  last_calibration?: CalibrationSnapshot | null
}

interface StrategyConfig {
  capital: {
    total_capital_mad: number
  }
  universe: {
    basket: string[]
    sector_filter: string[]
    min_abs_signal: number
    min_adv20: number
    sort_by: SortBy
    sort_dir: SortDir
  }
  allocation: {
    method: "hrp"
    hrp_lookback_bars: number
    manual_overrides_by_symbol: Record<string, ManualOverrideConfig>
  }
  signal: {
    signal_policy: "consensus"
    enabled_families: string[]
  }
  bet_sizing: BetSizingConfig
  risk: {
    max_holding_bars: number
    stop_atr_multiplier: number
    stop_buffer_pct: number
    take_profit_rr: number
    time_stop_enabled: boolean
    trailing_stop_enabled: boolean
  }
}

function defaultHoldingBars(horizon: string): number {
  if (horizon === "short") return 10
  if (horizon === "long") return 60
  return 30
}

const DEFAULT_LEGACY_BET_SIZING: LegacyBetSizingConfig = {
  starter_threshold: 20,
  starter_target_pct: 25,
  medium_threshold: 40,
  medium_target_pct: 50,
  large_threshold: 60,
  large_target_pct: 75,
  max_threshold: 80,
  max_target_pct: 100,
  reduce_to_large_below: 70,
  reduce_to_medium_below: 50,
  reduce_to_starter_below: 30,
  exit_below: 15,
}

const FALLBACK_LADDER = [
  { score_low: 0, score_high: 29.9999, target_exposure_pct: 0 },
  { score_low: 30, score_high: 49.9999, target_exposure_pct: 25 },
  { score_low: 50, score_high: 69.9999, target_exposure_pct: 50 },
  { score_low: 70, score_high: 84.9999, target_exposure_pct: 75 },
  { score_low: 85, score_high: 100, target_exposure_pct: 100 },
]

const DEFAULT_BET_SIZING: BetSizingConfig = {
  mode: "auto_calibrated",
  calibration_lookback_bars: 756,
  min_observations: 200,
  min_bucket_observations: 25,
  primary_metric: "avg_r_multiple",
  bucket_count: 10,
  exposure_levels: [0, 25, 50, 75, 100],
  sample_method: "event_deduped",
  legacy_manual_ladder: DEFAULT_LEGACY_BET_SIZING,
  last_calibration: null,
}

const DEFAULT_CONFIG: StrategyConfig = {
  capital: {
    total_capital_mad: 1_000_000,
  },
  universe: {
    basket: [],
    sector_filter: [],
    min_abs_signal: 0,
    min_adv20: 0,
    sort_by: "adv20",
    sort_dir: "desc",
  },
  allocation: {
    method: "hrp",
    hrp_lookback_bars: 252,
    manual_overrides_by_symbol: {},
  },
  signal: {
    signal_policy: "consensus",
    enabled_families: ["sma", "rsi", "macd", "obv"],
  },
  bet_sizing: DEFAULT_BET_SIZING,
  risk: {
    max_holding_bars: 30,
    stop_atr_multiplier: 1.5,
    stop_buffer_pct: 0.005,
    take_profit_rr: 1.5,
    time_stop_enabled: true,
    trailing_stop_enabled: false,
  },
}

const FAMILY_VISUAL_TOOLTIPS: Record<string, string[]> = {
  sma: [
    "Representee par des courbes de moyennes mobiles vertes sur le graphique de prix.",
    "Chaque variante representative peut tracer sa propre courbe ; les variantes les plus fortes sont plus visibles.",
  ],
  macd: [
    "Representee par de petites fleches sur les bougies aux croisements MACD / signal.",
    "Fleche verte = croisement haussier. Fleche rouge = croisement baissier.",
  ],
  rsi: [
    "Representee par des bandes temporelles rouge / vert sur le graphique principal.",
    "Bande rouge = zone de surachat. Bande verte = zone de survente.",
    "Il n'y a pas de courbe RSI visible ni d'axe RSI separe sur le graphique.",
  ],
  obv: [
    "Representee par des barres de volume colorees en bas du graphique.",
    "Vert = accumulation, rouge = distribution, gris = neutre.",
  ],
}

const SIGNAL_FAMILY_OPTIONS = [
  { id: "sma", label: "SMA", summary: "Trend structure" },
  { id: "rsi", label: "RSI", summary: "Stretch and mean-reversion context" },
  { id: "macd", label: "MACD", summary: "Momentum confirmation" },
  { id: "obv", label: "OBV", summary: "Volume-backed accumulation" },
] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function toNumber(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function toStringArray(value: unknown, fallback: string[] = []): string[] {
  if (!Array.isArray(value)) return fallback
  return value.map((item) => String(item)).filter(Boolean)
}

function isLegacyBetSizing(value: unknown): value is LegacyBetSizingConfig {
  return isRecord(value) && "starter_threshold" in value && "starter_target_pct" in value
}

function normalizeStrategyConfig(raw: unknown, horizon: string): StrategyConfig {
  const next = structuredClone(DEFAULT_CONFIG)
  next.risk.max_holding_bars = defaultHoldingBars(horizon)

  if (!isRecord(raw)) return next

  const capital = isRecord(raw.capital) ? raw.capital : {}
  const universe = isRecord(raw.universe) ? raw.universe : {}
  const allocation = isRecord(raw.allocation) ? raw.allocation : {}
  const logic = isRecord(raw.logic) ? raw.logic : {}
  const risk = isRecord(raw.risk) ? raw.risk : {}

  const legacySignal = isRecord(raw.signal) ? raw.signal : {}
  const legacyExecution = isRecord(raw.execution) ? raw.execution : {}
  const legacySizing = isRecord(raw.sizing) ? raw.sizing : {}

  next.capital.total_capital_mad = toNumber(
    capital.total_capital_mad ?? legacySizing.account_equity,
    DEFAULT_CONFIG.capital.total_capital_mad,
  )

  next.universe = {
    basket: toStringArray(universe.basket, DEFAULT_CONFIG.universe.basket),
    sector_filter: toStringArray(universe.sector_filter, DEFAULT_CONFIG.universe.sector_filter),
    min_abs_signal: toNumber(universe.min_abs_signal, DEFAULT_CONFIG.universe.min_abs_signal),
    min_adv20: toNumber(universe.min_adv20, DEFAULT_CONFIG.universe.min_adv20),
    sort_by: universe.sort_by === "signal_score" ? "signal_score" : "adv20",
    sort_dir: universe.sort_dir === "asc" ? "asc" : "desc",
  }

  const manualRaw = isRecord(allocation.manual_overrides_by_symbol)
    ? allocation.manual_overrides_by_symbol
    : {}
  const manual: Record<string, ManualOverrideConfig> = {}
  for (const [symbol, value] of Object.entries(manualRaw)) {
    if (!isRecord(value)) continue
    manual[symbol] = {
      enabled: Boolean(value.enabled),
      capital_mad: toNumber(value.capital_mad, 0),
    }
  }
  next.allocation = {
    method: "hrp",
    hrp_lookback_bars: toNumber(allocation.hrp_lookback_bars, DEFAULT_CONFIG.allocation.hrp_lookback_bars),
    manual_overrides_by_symbol: manual,
  }

  const signal = isRecord(raw.signal) ? raw.signal : {}
  const rawBetSizing = isRecord(raw.bet_sizing) ? raw.bet_sizing : {}
  const legacyBetSizing = isLegacyBetSizing(rawBetSizing)
    ? rawBetSizing
    : isLegacyBetSizing(logic.bet_sizing)
      ? logic.bet_sizing
      : DEFAULT_LEGACY_BET_SIZING
  next.signal = {
    signal_policy:
      signal.signal_policy === "consensus" || logic.signal_policy === "consensus"
        ? "consensus"
        : DEFAULT_CONFIG.signal.signal_policy,
    enabled_families: toStringArray(
      signal.enabled_families ?? logic.enabled_families ?? legacySignal.enabled_families,
      DEFAULT_CONFIG.signal.enabled_families,
    ),
  }
  next.bet_sizing = {
    mode: "auto_calibrated",
    calibration_lookback_bars: toNumber(rawBetSizing.calibration_lookback_bars, DEFAULT_BET_SIZING.calibration_lookback_bars),
    min_observations: toNumber(rawBetSizing.min_observations, DEFAULT_BET_SIZING.min_observations),
    min_bucket_observations: toNumber(rawBetSizing.min_bucket_observations, DEFAULT_BET_SIZING.min_bucket_observations),
    primary_metric: "avg_r_multiple",
    bucket_count: toNumber(rawBetSizing.bucket_count, DEFAULT_BET_SIZING.bucket_count),
    exposure_levels: Array.isArray(rawBetSizing.exposure_levels)
      ? rawBetSizing.exposure_levels.map((item) => Number(item)).filter((item) => Number.isFinite(item))
      : DEFAULT_BET_SIZING.exposure_levels,
    sample_method: "event_deduped",
    legacy_manual_ladder: {
      starter_threshold: toNumber(legacyBetSizing.starter_threshold, DEFAULT_LEGACY_BET_SIZING.starter_threshold),
      starter_target_pct: toNumber(legacyBetSizing.starter_target_pct, DEFAULT_LEGACY_BET_SIZING.starter_target_pct),
      medium_threshold: toNumber(legacyBetSizing.medium_threshold, DEFAULT_LEGACY_BET_SIZING.medium_threshold),
      medium_target_pct: toNumber(legacyBetSizing.medium_target_pct, DEFAULT_LEGACY_BET_SIZING.medium_target_pct),
      large_threshold: toNumber(legacyBetSizing.large_threshold, DEFAULT_LEGACY_BET_SIZING.large_threshold),
      large_target_pct: toNumber(legacyBetSizing.large_target_pct, DEFAULT_LEGACY_BET_SIZING.large_target_pct),
      max_threshold: toNumber(legacyBetSizing.max_threshold, DEFAULT_LEGACY_BET_SIZING.max_threshold),
      max_target_pct: toNumber(legacyBetSizing.max_target_pct, DEFAULT_LEGACY_BET_SIZING.max_target_pct),
      reduce_to_large_below: toNumber(legacyBetSizing.reduce_to_large_below, DEFAULT_LEGACY_BET_SIZING.reduce_to_large_below),
      reduce_to_medium_below: toNumber(legacyBetSizing.reduce_to_medium_below, DEFAULT_LEGACY_BET_SIZING.reduce_to_medium_below),
      reduce_to_starter_below: toNumber(legacyBetSizing.reduce_to_starter_below, DEFAULT_LEGACY_BET_SIZING.reduce_to_starter_below),
      exit_below: toNumber(legacyBetSizing.exit_below, DEFAULT_LEGACY_BET_SIZING.exit_below),
    },
    last_calibration: isRecord(rawBetSizing.last_calibration)
      ? {
          status: String(rawBetSizing.last_calibration.status ?? "fallback") as CalibrationSnapshot["status"],
          lookback_bars: toNumber(rawBetSizing.last_calibration.lookback_bars, 0),
          window_start: rawBetSizing.last_calibration.window_start == null ? null : String(rawBetSizing.last_calibration.window_start),
          window_end: rawBetSizing.last_calibration.window_end == null ? null : String(rawBetSizing.last_calibration.window_end),
          n_observations: toNumber(rawBetSizing.last_calibration.n_observations, 0),
          primary_metric: String(rawBetSizing.last_calibration.primary_metric ?? "avg_r_multiple"),
          bucket_rows: Array.isArray(rawBetSizing.last_calibration.bucket_rows)
            ? rawBetSizing.last_calibration.bucket_rows
                .filter(isRecord)
                .map((row) => ({
                  score_low: toNumber(row.score_low, 0),
                  score_high: toNumber(row.score_high, 0),
                  n_observations: toNumber(row.n_observations, 0),
                  avg_r_multiple: toNumber(row.avg_r_multiple, 0),
                  avg_net_return: toNumber(row.avg_net_return, 0),
                  win_rate: toNumber(row.win_rate, 0),
                  target_exposure_pct: toNumber(row.target_exposure_pct, 0),
                }))
            : [],
          ladder: Array.isArray(rawBetSizing.last_calibration.ladder)
            ? rawBetSizing.last_calibration.ladder.filter(isRecord)
            : [],
          reason: rawBetSizing.last_calibration.reason == null ? null : String(rawBetSizing.last_calibration.reason),
        }
      : null,
  }

  next.risk = {
    max_holding_bars: toNumber(risk.max_holding_bars ?? legacyExecution.holding_bars, defaultHoldingBars(horizon)),
    stop_atr_multiplier: toNumber(risk.stop_atr_multiplier ?? legacyExecution.atr_multiplier, DEFAULT_CONFIG.risk.stop_atr_multiplier),
    stop_buffer_pct: toNumber(risk.stop_buffer_pct ?? legacyExecution.buffer_pct, DEFAULT_CONFIG.risk.stop_buffer_pct),
    take_profit_rr: toNumber(risk.take_profit_rr ?? legacyExecution.min_rr, DEFAULT_CONFIG.risk.take_profit_rr),
    time_stop_enabled: risk.time_stop_enabled == null ? DEFAULT_CONFIG.risk.time_stop_enabled : Boolean(risk.time_stop_enabled),
    trailing_stop_enabled: Boolean(risk.trailing_stop_enabled),
  }

  return next
}

function fmtMoney(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { maximumFractionDigits: 0 })
}

function parseFormattedInteger(value: string): number {
  const raw = String(value)
    .replace(/\s/g, "")
    .replace(/,/g, "")
    .replace(/\./g, "")

  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : 0
}

function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "-"
  return `${value.toFixed(digits)}%`
}

function fmtNum(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

function buildManualOverridesForApi(overrides: Record<string, ManualOverrideConfig>, symbols: string[]): Record<string, number> {
  const out: Record<string, number> = {}
  for (const symbol of symbols) {
    const current = overrides[symbol]
    if (current?.enabled && current.capital_mad > 0) {
      out[symbol] = current.capital_mad
    }
  }
  return out
}

function resolveExposureLadder(config: BetSizingConfig) {
  if (config.last_calibration?.ladder && config.last_calibration.ladder.length > 0) {
    return config.last_calibration.ladder
  }
  return FALLBACK_LADDER
}

function computeBetSizingPreview(score: number | null | undefined, stockCapital: number, config: BetSizingConfig) {
  const absScore = Math.abs(score ?? 0)
  const ladder = resolveExposureLadder(config)
  let label = config.last_calibration ? "Calibrated" : "Fallback reference"
  let targetPct = 0

  for (const row of ladder) {
    const low = toNumber((row as Record<string, unknown>).score_low, 0)
    const high = toNumber((row as Record<string, unknown>).score_high, 100)
    if (absScore >= low && absScore <= high) {
      targetPct = toNumber((row as Record<string, unknown>).target_exposure_pct, 0)
      break
    }
  }

  if (targetPct >= 100) {
    label = "Max size"
  } else if (targetPct >= 75) {
    label = "Large size"
  } else if (targetPct >= 50) {
    label = "Medium size"
  } else if (targetPct >= 25) {
    label = "Starter size"
  } else {
    label = "Flat"
  }

  return {
    label,
    targetPct,
    capital: stockCapital * (targetPct / 100),
  }
}

function MetricTile({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <div className="rounded-lg border bg-background p-3">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-sm font-semibold">{value}</p>
      {hint ? <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

function StockStrategyTab({
  symbol,
  horizon,
  sidePolicy,
  totalStrategyCapital,
  signalConfig,
  sizingConfig,
  riskConfig,
  allocationRow,
  manualOverride,
  onManualToggle,
  onManualCapitalChange,
  onSignalChange,
  onRiskChange,
}: {
  symbol: string
  horizon: string
  sidePolicy: string
  totalStrategyCapital: number
  signalConfig: StrategyConfig["signal"]
  sizingConfig: StrategyConfig["bet_sizing"]
  riskConfig: StrategyConfig["risk"]
  allocationRow: StrategyAllocationRow | null
  manualOverride: ManualOverrideConfig
  onManualToggle: (enabled: boolean) => void
  onManualCapitalChange: (capital: number) => void
  onSignalChange: (patch: Partial<StrategyConfig["signal"]>) => void
  onRiskChange: (patch: Partial<StrategyConfig["risk"]>) => void
}) {
  const referenceLadder = resolveExposureLadder(sizingConfig)
  const firstRiskOnBucket = referenceLadder.find((row) => toNumber((row as Record<string, unknown>).target_exposure_pct, 0) > 0)
  const previewEntryThreshold = toNumber(firstRiskOnBucket ? (firstRiskOnBucket as Record<string, unknown>).score_low : 30, 30)

  const { data: consensus, isLoading: consensusLoading } = useSignalConsensus(
    symbol,
    horizon,
    signalConfig.enabled_families,
  )
  const { data: zoneChart, isLoading: chartLoading } = useSignalZoneChart(
    symbol,
    horizon,
    signalConfig.enabled_families,
  )
  const { data: executionPlan, isLoading: executionLoading } = useExecution(symbol, horizon, {
    enabled_families: signalConfig.enabled_families,
    execution_holding_bars: riskConfig.max_holding_bars,
    side_policy: sidePolicy,
    entry_threshold: previewEntryThreshold,
    atr_multiplier: riskConfig.stop_atr_multiplier,
    buffer_pct: riskConfig.stop_buffer_pct,
    min_rr: riskConfig.take_profit_rr,
    consensus_override: consensus?.final_consensus,
  })

  const sizingPreview = computeBetSizingPreview(
    consensus?.final_consensus,
    allocationRow?.capital_mad ?? 0,
    sizingConfig,
  )
  const hrpSuggestedCapital = totalStrategyCapital * ((allocationRow?.hrp_weight_pct ?? 0) / 100)

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Allocation</CardTitle>
          <CardDescription>Assign stock capital with HRP by default and manual override when needed.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <MetricTile
              label="Source"
              value={allocationRow?.source === "manual" ? "Manual override" : "HRP baseline"}
              hint={allocationRow?.source === "manual" ? "This stock is using a manual capital amount." : "Weight comes from the HRP allocation preview."}
            />
            <MetricTile
              label="HRP suggested"
              value={`${fmtPct(allocationRow?.hrp_weight_pct ?? 0, 2)} / ${fmtMoney(hrpSuggestedCapital)} MAD`}
              hint="Suggested baseline before any manual override."
            />
            <MetricTile
              label="Allocated"
              value={`${fmtPct(allocationRow?.weight_pct ?? 0, 2)} / ${fmtMoney(allocationRow?.capital_mad ?? 0)} MAD`}
              hint="Final capital assigned to this stock."
            />
          </div>

          <div className="rounded-lg border bg-muted/20 p-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Manual override</p>
                <p className="text-xs text-muted-foreground">Enable this only when you want to override the HRP baseline.</p>
              </div>
              <Switch checked={manualOverride.enabled} onCheckedChange={onManualToggle} />
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs">Manual capital (MAD)</Label>
                <Input
                  type="number"
                  className="h-8 text-sm"
                  value={manualOverride.capital_mad}
                  onChange={(e) => onManualCapitalChange(Number(e.target.value))}
                  disabled={!manualOverride.enabled}
                  min={0}
                  step={1000}
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Current mode</Label>
                <div className="flex h-8 items-center rounded-md border bg-background px-3 text-sm">
                  {manualOverride.enabled ? "Manual" : "HRP"}
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Signal</CardTitle>
          <CardDescription>Shared signal configuration applied to every selected stock, with this tab showing the stock-specific preview.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {consensusLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <SignalScoreBar
              value={consensus?.final_consensus ?? null}
              size="lg"
              label={`Policy: ${signalConfig.signal_policy}`}
            />
          )}

          <SignalZoneChart
            data={zoneChart}
            enabledFamilies={signalConfig.enabled_families}
            isLoading={chartLoading}
            height={360}
          />

          <div className="space-y-3">
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Signal families</p>
                <p className="mt-1 text-xs text-muted-foreground">Toggle the four building blocks used in the consensus and preview how much each family is contributing.</p>
              </div>
              <Badge variant="secondary" className="shrink-0">
                {signalConfig.enabled_families.length} / {SIGNAL_FAMILY_OPTIONS.length} active
              </Badge>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {SIGNAL_FAMILY_OPTIONS.map((family) => {
                const enabled = signalConfig.enabled_families.includes(family.id)
                const familyScore = consensus?.per_family?.[family.id]
                const representativeCount = zoneChart?.families?.[family.id]?.representatives?.length
                const tooltipLines = FAMILY_VISUAL_TOOLTIPS[family.id] ?? []
                return (
                  <div
                    key={family.id}
                    className={cn(
                      "rounded-lg border p-3 transition-colors",
                      enabled ? "bg-background" : "bg-muted/20 text-muted-foreground",
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex min-w-0 items-start gap-3">
                        <Checkbox
                          checked={enabled}
                          onCheckedChange={() => {
                            const current = signalConfig.enabled_families
                            const next = enabled
                              ? current.filter((item) => item !== family.id)
                              : [...current, family.id]
                            onSignalChange({ enabled_families: next })
                          }}
                          className="mt-0.5"
                        />
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <p className="text-sm font-medium">{family.label}</p>
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <button
                                  type="button"
                                  className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground"
                                  aria-label={`Explication visuelle ${family.label}`}
                                >
                                  <Info className="h-3.5 w-3.5" />
                                </button>
                              </TooltipTrigger>
                              <TooltipContent side="right" sideOffset={6} className="max-w-[260px]">
                                <div className="space-y-1">
                                  {tooltipLines.map((line) => (
                                    <p key={line} className="text-xs leading-relaxed">
                                      {line}
                                    </p>
                                  ))}
                                </div>
                              </TooltipContent>
                            </Tooltip>
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">{family.summary}</p>
                        </div>
                      </div>
                      <Badge variant={enabled ? "default" : "outline"}>{enabled ? "On" : "Off"}</Badge>
                    </div>

                    <div className="mt-3 flex flex-wrap gap-2">
                      <Badge variant="secondary" className="font-mono text-[11px]">
                        Score {familyScore ? familyScore.score_pct.toFixed(1) : "--"}
                      </Badge>
                      <Badge variant="secondary" className="font-mono text-[11px]">
                        Weight {familyScore ? fmtPct(familyScore.weight * 100, 0) : "--"}
                      </Badge>
                      <Badge variant="secondary" className="font-mono text-[11px]">
                        Reps {representativeCount ?? "--"}
                      </Badge>
                    </div>
                  </div>
                )
              })}
            </div>

            {signalConfig.enabled_families.length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                At least one family needs to stay active for the consensus and chart preview to remain meaningful.
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Bet Sizing</CardTitle>
          <CardDescription>Auto-calibrated target exposure derived from historical consensus-score outcomes for this strategy.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <MetricTile label="Mode" value="Auto-calibrated" hint="Sizing is derived from historical evidence, not hand-set score brackets." />
            <MetricTile label="Lookback" value={`${sizingConfig.calibration_lookback_bars} bars`} hint="Trailing pre-start history used for calibration in backtest." />
            <MetricTile label="Metric" value="Avg R-multiple" hint="Primary ranking metric for calibrated score buckets." />
            <MetricTile label="Levels" value={sizingConfig.exposure_levels.join(" / ")} hint="Discrete exposure states allowed by the strategy." />
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <MetricTile label="Target state" value={sizingPreview.label} hint="Current score mapped to the target deployed state." />
            <MetricTile label="Target deployment" value={fmtPct(sizingPreview.targetPct, 0)} hint="Fraction of this stock allocation to deploy." />
            <MetricTile label="Target capital" value={`${fmtMoney(sizingPreview.capital)} MAD`} hint="Capital implied by the current score and stock allocation." />
          </div>

          <div className="rounded-lg border bg-muted/20 p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Calibration policy</p>
                <p className="text-xs text-muted-foreground">
                  The authoritative ladder is computed on the Backtest page using only history before the selected start date.
                </p>
              </div>
              <Badge variant={sizingConfig.last_calibration?.status === "ok" ? "default" : "secondary"}>
                {sizingConfig.last_calibration?.status ?? "Awaiting run"}
              </Badge>
            </div>
            {sizingConfig.last_calibration?.reason ? (
              <p className="mt-3 text-xs text-muted-foreground">Latest calibration note: {sizingConfig.last_calibration.reason}</p>
            ) : null}
          </div>

          <div className="space-y-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Reference ladder</p>
            <div className="overflow-x-auto rounded-lg border border-border/70">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-secondary/20">
                    {["Abs score range", "Target exposure", "Obs", "Avg R"].map((label) => (
                      <th key={label} className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(sizingConfig.last_calibration?.bucket_rows ?? FALLBACK_LADDER).map((row, index) => {
                    const record = row as unknown as Record<string, unknown>
                    return (
                      <tr key={`${symbol}-sizing-${index}`} className="border-b border-border/50 last:border-0">
                        <td className="px-3 py-2 font-mono text-xs">
                          {fmtNum(toNumber(record.score_low, 0), 1)} - {fmtNum(toNumber(record.score_high, 0), 1)}
                        </td>
                        <td className="px-3 py-2 font-mono text-xs">{fmtPct(toNumber(record.target_exposure_pct, 0), 0)}</td>
                        <td className="px-3 py-2 font-mono text-xs">{record.n_observations == null ? "--" : fmtNum(toNumber(record.n_observations, 0), 0)}</td>
                        <td className="px-3 py-2 font-mono text-xs">{record.avg_r_multiple == null ? "--" : fmtNum(toNumber(record.avg_r_multiple, 0), 2)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Risk</CardTitle>
          <CardDescription>Classic labels backed by a simple barrier framework: stop loss, take profit, and max holding period.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <MetricTile label="Stop loss" value={executionLoading ? "..." : executionPlan?.stop_loss?.toFixed(2) ?? "-"} hint="ATR and structural buffer combined." />
            <MetricTile label="Take profit" value={executionLoading ? "..." : executionPlan?.target_1?.toFixed(2) ?? "-"} hint="Primary structural target." />
            <MetricTile label="Reward / risk" value={executionLoading ? "..." : executionPlan?.rr_ratio?.toFixed(2) ?? "-"} hint="Current geometry using the selected risk settings." />
            <MetricTile label="Max holding" value={`${riskConfig.max_holding_bars} bars`} hint="Time barrier used as a classic max holding rule." />
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <div className="space-y-1">
              <Label className="text-xs">Max holding bars</Label>
              <Input type="number" className="h-8 text-sm" value={riskConfig.max_holding_bars} onChange={(e) => onRiskChange({ max_holding_bars: Number(e.target.value) })} min={2} max={252} step={1} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Stop ATR multiple</Label>
              <Input type="number" className="h-8 text-sm" value={riskConfig.stop_atr_multiplier} onChange={(e) => onRiskChange({ stop_atr_multiplier: Number(e.target.value) })} min={0.1} max={10} step={0.1} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Stop buffer (%)</Label>
              <Input type="number" className="h-8 text-sm" value={(riskConfig.stop_buffer_pct * 100).toFixed(1)} onChange={(e) => onRiskChange({ stop_buffer_pct: Number(e.target.value) / 100 })} min={0} max={10} step={0.1} />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Minimum take-profit R:R</Label>
              <Input type="number" className="h-8 text-sm" value={riskConfig.take_profit_rr} onChange={(e) => onRiskChange({ take_profit_rr: Number(e.target.value) })} min={0.5} max={10} step={0.1} />
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div className="flex items-center justify-between rounded-md border p-3">
              <div>
                <p className="text-sm font-medium">Time stop</p>
                <p className="text-xs text-muted-foreground">Use the max holding period as an active time barrier.</p>
              </div>
              <Switch checked={riskConfig.time_stop_enabled} onCheckedChange={(checked) => onRiskChange({ time_stop_enabled: checked })} />
            </div>
            <div className="flex items-center justify-between rounded-md border p-3">
              <div>
                <p className="text-sm font-medium">Trailing stop</p>
                <p className="text-xs text-muted-foreground">Stored in the strategy config for future extension.</p>
              </div>
              <Switch checked={riskConfig.trailing_stop_enabled} onCheckedChange={(checked) => onRiskChange({ trailing_stop_enabled: checked })} />
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function StrategyPageContent() {
  const searchParams = useSearchParams()
  const searchStrategyId = searchParams.get("strategyId")
  const [railOpen, setRailOpen] = useState(true)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [activeSymbol, setActiveSymbol] = useState<string | null>(null)

  const [name, setName] = useState("New strategy")
  const [sidePolicy, setSidePolicy] = useState("long_only")
  const [horizon, setHorizon] = useState("short")
  const [status, setStatus] = useState("draft")
  const [config, setConfig] = useState<StrategyConfig>(() => {
    const initial = structuredClone(DEFAULT_CONFIG)
    initial.risk.max_holding_bars = defaultHoldingBars("short")
    return initial
  })
  const [isSaving, setIsSaving] = useState(false)

  const { data: strategies, isLoading: strategiesLoading, mutate: mutateStrategies } = useStrategies()
  const { data: universe, isLoading: universeLoading } = useUniverse(horizon, {
    min_abs_signal: config.universe.min_abs_signal,
    min_adv20: config.universe.min_adv20,
    sector_filter: config.universe.sector_filter.length > 0 ? config.universe.sector_filter : undefined,
    sort_by: config.universe.sort_by,
    sort_dir: config.universe.sort_dir,
  })

  const basket = config.universe.basket
  const manualOverridesForApi = useMemo(
    () => buildManualOverridesForApi(config.allocation.manual_overrides_by_symbol, basket),
    [config.allocation.manual_overrides_by_symbol, basket],
  )
  const { data: allocationPreview } = useStrategyAllocation(basket, {
    total_capital_mad: config.capital.total_capital_mad,
    method: config.allocation.method,
    lookback_bars: config.allocation.hrp_lookback_bars,
    manual_overrides_by_symbol: manualOverridesForApi,
  })

  const allocationRowsBySymbol = useMemo(() => {
    const out = new Map<string, StrategyAllocationRow>()
    for (const row of allocationPreview?.rows ?? []) out.set(row.symbol, row)
    return out
  }, [allocationPreview?.rows])

  useEffect(() => {
    if (basket.length === 0) {
      setActiveSymbol(null)
      return
    }
    if (!activeSymbol || !basket.includes(activeSymbol)) {
      setActiveSymbol(basket[0])
    }
  }, [activeSymbol, basket])

  const availableSectors = useMemo(() => {
    const sectors = new Set<string>()
    for (const stock of universe ?? []) {
      if (stock.sector?.trim()) sectors.add(stock.sector.trim())
    }
    return Array.from(sectors).sort((a, b) => a.localeCompare(b, "fr"))
  }, [universe])

  const visibleUniverse = useMemo(() => {
    return (universe ?? []).filter((stock) => {
      if (
        config.universe.sector_filter.length > 0 &&
        !config.universe.sector_filter.includes(stock.sector ?? "")
      ) {
        return false
      }
      if (config.universe.min_adv20 > 0 && (stock.adv20 == null || stock.adv20 < config.universe.min_adv20)) {
        return false
      }
      return true
    })
  }, [config.universe.min_adv20, config.universe.sector_filter, universe])

  const hiddenSelectedSymbols = useMemo(() => {
    const visibleSymbols = new Set(visibleUniverse.map((stock) => stock.symbol))
    return basket.filter((symbol) => !visibleSymbols.has(symbol))
  }, [basket, visibleUniverse])

  const updateConfig = useCallback(
    <K extends keyof StrategyConfig>(section: K, patch: Partial<StrategyConfig[K]>) => {
      setConfig((prev) => ({
        ...prev,
        [section]: { ...prev[section], ...patch },
      }))
      if (status === "saved") setStatus("modified")
    },
    [status],
  )

  const handleHorizonChange = useCallback((nextHorizon: string) => {
    setHorizon(nextHorizon)
    setConfig((prev) => ({
      ...prev,
      risk: {
        ...prev.risk,
        max_holding_bars: defaultHoldingBars(nextHorizon),
      },
    }))
    if (status === "saved") setStatus("modified")
  }, [status])

  const handleCreate = useCallback(async () => {
    try {
      const strategy = await createStrategy({ name: "New strategy", side_policy: "long_only", horizon: "short" })
      const fresh = structuredClone(DEFAULT_CONFIG)
      fresh.risk.max_holding_bars = defaultHoldingBars(strategy.horizon)
      setActiveId(strategy.id)
      setName(strategy.name)
      setSidePolicy(strategy.side_policy)
      setHorizon(strategy.horizon)
      setStatus(strategy.status)
      setConfig(fresh)
      setActiveSymbol(null)
      mutateStrategies()
    } catch (error) {
      console.error("Failed to create strategy", error)
    }
  }, [mutateStrategies])

  const loadStrategy = useCallback(async (id: string) => {
    setActiveId(id)
    try {
      const { fetchStrategy } = await import("@/lib/api")
      const strategy = await fetchStrategy(id)
      const normalized = normalizeStrategyConfig(strategy.config_json, strategy.horizon)
      setName(strategy.name)
      setSidePolicy(strategy.side_policy)
      setHorizon(strategy.horizon)
      setStatus(strategy.status)
      setConfig(normalized)
      setActiveSymbol(normalized.universe.basket[0] ?? null)
    } catch (error) {
      console.error("Failed to load strategy", error)
    }
  }, [])

  useEffect(() => {
    if (!searchStrategyId || !strategies || strategies.length === 0) return
    if (activeId === searchStrategyId) return
    const match = strategies.find((item) => item.id === searchStrategyId)
    if (match) {
      void loadStrategy(match.id)
    }
  }, [activeId, loadStrategy, searchStrategyId, strategies])

  const handleSave = useCallback(async () => {
    const payload = {
      name,
      side_policy: sidePolicy,
      horizon,
      config_json: config as unknown as Record<string, unknown>,
      status: "saved",
    }

    if (!activeId) {
      try {
        const strategy = await createStrategy({ name, side_policy: sidePolicy, horizon })
        setActiveId(strategy.id)
        await updateStrategy(strategy.id, payload)
        setStatus("saved")
        mutateStrategies()
      } catch (error) {
        console.error("Failed to create+save strategy", error)
      }
      return
    }

    setIsSaving(true)
    try {
      await updateStrategy(activeId, payload)
      setStatus("saved")
      mutateStrategies()
    } catch (error) {
      console.error("Failed to save strategy", error)
    } finally {
      setIsSaving(false)
    }
  }, [activeId, config, horizon, mutateStrategies, name, sidePolicy])

  const handleDuplicate = useCallback(async () => {
    if (!activeId) return
    try {
      const copy = await duplicateStrategy(activeId)
      mutateStrategies()
      await loadStrategy(copy.id)
    } catch (error) {
      console.error("Failed to duplicate strategy", error)
    }
  }, [activeId, loadStrategy, mutateStrategies])

  const handleArchive = useCallback(async () => {
    if (!activeId) return
    try {
      await archiveStrategy(activeId)
      const fresh = structuredClone(DEFAULT_CONFIG)
      fresh.risk.max_holding_bars = defaultHoldingBars("short")
      setActiveId(null)
      setName("New strategy")
      setSidePolicy("long_only")
      setHorizon("short")
      setStatus("draft")
      setConfig(fresh)
      setActiveSymbol(null)
      mutateStrategies()
    } catch (error) {
      console.error("Failed to archive strategy", error)
    }
  }, [activeId, mutateStrategies])

  const toggleBasketSymbol = useCallback((symbol: string) => {
    setConfig((prev) => {
      const current = prev.universe.basket
      const next = current.includes(symbol) ? current.filter((item) => item !== symbol) : [...current, symbol]
      return {
        ...prev,
        universe: { ...prev.universe, basket: next },
      }
    })
    if (!basket.includes(symbol)) setActiveSymbol(symbol)
    if (status === "saved") setStatus("modified")
  }, [basket, status])

  const toggleSectorFilter = useCallback((sector: string) => {
    setConfig((prev) => {
      const current = prev.universe.sector_filter
      const next = current.includes(sector) ? current.filter((item) => item !== sector) : [...current, sector]
      return {
        ...prev,
        universe: { ...prev.universe, sector_filter: next },
      }
    })
    if (status === "saved") setStatus("modified")
  }, [status])

  const updateManualOverride = useCallback((symbol: string, patch: Partial<ManualOverrideConfig>) => {
    setConfig((prev) => ({
      ...prev,
      allocation: {
        ...prev.allocation,
        manual_overrides_by_symbol: {
          ...prev.allocation.manual_overrides_by_symbol,
          [symbol]: {
            enabled: prev.allocation.manual_overrides_by_symbol[symbol]?.enabled ?? false,
            capital_mad: prev.allocation.manual_overrides_by_symbol[symbol]?.capital_mad ?? 0,
            ...patch,
          },
        },
      },
    }))
    if (status === "saved") setStatus("modified")
  }, [status])

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] overflow-hidden">
      <div className={cn("shrink-0 overflow-hidden transition-[width] duration-200 ease-in-out", railOpen ? "w-[260px]" : "w-0")}>
        <StrategyRail strategies={strategies} isLoading={strategiesLoading} activeId={activeId} onSelect={loadStrategy} onCreate={handleCreate} className="h-full w-[260px]" />
      </div>

      <div className="flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-7xl space-y-4">
          <div className="flex items-center gap-2">
            <button onClick={() => setRailOpen((value) => !value)} className="rounded-md p-1 transition-colors hover:bg-muted" title={railOpen ? "Hide strategies" : "Show strategies"}>
              {railOpen ? <PanelLeftClose className="h-4 w-4 text-muted-foreground" /> : <PanelLeftOpen className="h-4 w-4 text-muted-foreground" />}
            </button>
          </div>

          <CoreStrategyHeader
            name={name}
            onNameChange={(value) => { setName(value); if (status === "saved") setStatus("modified") }}
            sidePolicy={sidePolicy}
            onSidePolicyChange={(value) => { setSidePolicy(value); if (status === "saved") setStatus("modified") }}
            horizon={horizon}
            onHorizonChange={handleHorizonChange}
            status={status}
            focusedStock={activeSymbol}
            basket={basket}
            onFocusedStockChange={setActiveSymbol}
            onSave={handleSave}
            onDuplicate={handleDuplicate}
            onArchive={handleArchive}
            backtestHref={activeId ? `/backtest?strategyId=${activeId}` : null}
            isSaving={isSaving}
          />

          <div className="grid gap-4 xl:grid-cols-[1.1fr_1.3fr]">
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2"><CircleDollarSign className="h-4 w-4 text-muted-foreground" /><CardTitle className="text-base">Capital</CardTitle></div>
                <CardDescription>Define the total deployable capital for this strategy before assigning anything to individual stocks.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-1">
                  <Label className="text-xs">Total strategy capital (MAD)</Label>
                  <Input
                    type="text"
                    inputMode="numeric"
                    className="h-9 text-sm"
                    value={fmtMoney(config.capital.total_capital_mad)}
                    onChange={(e) => updateConfig("capital", { total_capital_mad: parseFormattedInteger(e.target.value) })}
                  />
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <MetricTile label="Allocated" value={`${fmtMoney(allocationPreview?.allocated_capital_mad ?? 0)} MAD`} hint="Capital currently assigned to selected stocks." />
                  <MetricTile label="Remaining" value={`${fmtMoney(allocationPreview?.remaining_capital_mad ?? config.capital.total_capital_mad)} MAD`} hint="Still unassigned after HRP and manual overrides." />
                  <MetricTile label="Method" value="HRP + manual" hint="HRP baseline with optional stock-level manual overrides." />
                </div>
                <p className="text-xs text-muted-foreground">{allocationPreview?.explain ?? "Pick stocks in the universe first to preview HRP allocation."}</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center gap-2"><Globe className="h-4 w-4 text-muted-foreground" /><CardTitle className="text-base">Universe</CardTitle></div>
                <CardDescription>Filter by sector, rank by liquidity, and select the stocks that deserve a dedicated strategy tab.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 lg:grid-cols-4">
                  <div className="space-y-1">
                    <Label className="text-xs">Minimum ADV20</Label>
                    <Input type="number" className="h-8 text-sm" value={config.universe.min_adv20} onChange={(e) => updateConfig("universe", { min_adv20: Number(e.target.value) })} min={0} step={1000} />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Sort by</Label>
                    <Select value={config.universe.sort_by} onValueChange={(value: SortBy) => updateConfig("universe", { sort_by: value })}>
                      <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="adv20">ADV20</SelectItem><SelectItem value="signal_score">Signal strength</SelectItem></SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Direction</Label>
                    <Select value={config.universe.sort_dir} onValueChange={(value: SortDir) => updateConfig("universe", { sort_dir: value })}>
                      <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                      <SelectContent><SelectItem value="desc">Descending</SelectItem><SelectItem value="asc">Ascending</SelectItem></SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">HRP lookback</Label>
                    <Input type="number" className="h-8 text-sm" value={config.allocation.hrp_lookback_bars} onChange={(e) => updateConfig("allocation", { hrp_lookback_bars: Number(e.target.value) })} min={20} max={2000} step={5} />
                  </div>
                </div>

                {availableSectors.length > 0 && (
                  <div className="rounded-lg border bg-muted/20 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs font-medium text-muted-foreground">Sector filter</span>
                      {availableSectors.map((sector) => {
                        const active = config.universe.sector_filter.includes(sector)
                        return (
                          <button key={sector} type="button" onClick={() => toggleSectorFilter(sector)} className={cn("rounded-full border px-2.5 py-1 text-[11px] transition-colors", active ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background text-muted-foreground hover:text-foreground")}>
                            {sector}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}

                <div className="overflow-hidden rounded-lg border">
                  <table className="w-full text-xs">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="w-8 px-2 py-2" />
                        <th className="px-2 py-2 text-left font-medium">Ticker</th>
                        <th className="px-2 py-2 text-left font-medium">Sector</th>
                        <th className="px-2 py-2 text-right font-medium">ADV20</th>
                        <th className="px-2 py-2 text-right font-medium">Signal</th>
                        <th className="px-2 py-2 text-right font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {universeLoading ? Array.from({ length: 6 }).map((_, index) => (
                        <tr key={index} className="border-t"><td colSpan={6} className="px-3 py-2"><Skeleton className="h-8 w-full" /></td></tr>
                      )) : visibleUniverse.map((stock) => {
                        const selected = basket.includes(stock.symbol)
                        return (
                          <tr key={stock.symbol} className={cn("border-t transition-colors", selected ? "bg-primary/5" : "hover:bg-muted/40")}>
                            <td className="px-2 py-2"><Checkbox checked={selected} onCheckedChange={() => toggleBasketSymbol(stock.symbol)} /></td>
                            <td className="px-2 py-2 font-mono font-medium">{stock.symbol}</td>
                            <td className="px-2 py-2 text-muted-foreground">{stock.sector ?? "-"}</td>
                            <td className="px-2 py-2 text-right font-mono">{stock.adv20 != null ? fmtMoney(stock.adv20) : "-"}</td>
                            <td className="px-2 py-2 text-right font-mono">{stock.signal_score != null ? stock.signal_score.toFixed(1) : "-"}</td>
                            <td className="px-2 py-2 text-right"><Badge variant={stock.eligible ? "outline" : "secondary"}>{stock.eligible ? "Eligible" : "Filtered"}</Badge></td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <div className="space-y-1 text-xs text-muted-foreground">
                  <p>Selected stocks become tabs below. Universe filters change what is visible without silently deleting saved basket choices.</p>
                  {hiddenSelectedSymbols.length > 0 ? (
                    <p>{hiddenSelectedSymbols.length} selected stock{hiddenSelectedSymbols.length === 1 ? "" : "s"} hidden by the current universe filters still remain available in the stock tabs.</p>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2"><ChartColumnIncreasing className="h-4 w-4 text-muted-foreground" /><CardTitle className="text-base">Stock Tabs</CardTitle></div>
              <CardDescription>One tab per selected stock. Logic is shared; allocation is stock-specific; risk is presented with classic labels.</CardDescription>
            </CardHeader>
            <CardContent>
              {basket.length === 0 ? (
                <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">Select stocks in the universe to open dedicated strategy tabs.</div>
              ) : (
                <Tabs value={activeSymbol ?? basket[0]} onValueChange={setActiveSymbol} className="gap-4">
                  <TabsList className="h-auto w-full flex-wrap justify-start">
                    {basket.map((symbol) => {
                      const row = allocationRowsBySymbol.get(symbol)
                      return (
                        <TabsTrigger key={symbol} value={symbol} className="flex-none">
                          <span>{symbol}</span>
                          <Badge variant="secondary" className="ml-1 text-[10px]">{row?.source === "manual" ? "Manual" : "HRP"}</Badge>
                        </TabsTrigger>
                      )
                    })}
                  </TabsList>

                  {basket.map((symbol) => {
                    const row = allocationRowsBySymbol.get(symbol) ?? null
                    const manualOverride = config.allocation.manual_overrides_by_symbol[symbol] ?? { enabled: false, capital_mad: 0 }
                    return (
                      <TabsContent key={symbol} value={symbol} className="pt-2">
                        <StockStrategyTab
                          symbol={symbol}
                          horizon={horizon}
                          sidePolicy={sidePolicy}
                          totalStrategyCapital={config.capital.total_capital_mad}
                          signalConfig={config.signal}
                          sizingConfig={config.bet_sizing}
                          riskConfig={config.risk}
                          allocationRow={row}
                          manualOverride={manualOverride}
                          onManualToggle={(enabled) => updateManualOverride(symbol, { enabled })}
                          onManualCapitalChange={(capital) => updateManualOverride(symbol, { capital_mad: capital })}
                          onSignalChange={(patch) => updateConfig("signal", patch)}
                          onRiskChange={(patch) => updateConfig("risk", patch)}
                        />
                      </TabsContent>
                    )
                  })}
                </Tabs>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-muted-foreground" /><CardTitle className="text-base">Design Summary</CardTitle></div>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-3">
              <MetricTile label="Capital" value={`${fmtMoney(config.capital.total_capital_mad)} MAD`} hint="Single strategy-level capital budget." />
              <MetricTile label="Universe" value={`${basket.length} selected stock${basket.length === 1 ? "" : "s"}`} hint="Sector filter + ADV20 sorting + min ADV20 filter." />
              <MetricTile label="Signal" value="Shared across tabs" hint="Signal, bet sizing, and risk parameters remain coherent for the whole strategy." />
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default function StrategyPage() {
  return (
    <Suspense fallback={<div className="space-y-4"><Skeleton className="h-24 rounded-xl" /><Skeleton className="h-72 rounded-xl" /></div>}>
      <StrategyPageContent />
    </Suspense>
  )
}
