"use client"

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Archive, BookOpen, Check, ChevronLeft, ChevronRight, CircleDollarSign, CopyPlus, Eye, Gauge, Plus, Save } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { EntryRulesTab } from "@/components/strategy/entry-rules-tab"
import { ExitRulesTab } from "@/components/strategy/exit-rules-tab"
import { ReviewTab } from "@/components/strategy/review-tab"
import { RiskTab } from "@/components/strategy/risk-tab"
import { SignalConstructionTab } from "@/components/strategy/signal-construction-tab"
import { StockUniverseSelector } from "@/components/strategy/stock-universe-selector"
import { INDICATOR_FAMILY_META, normalizeIndicatorParams } from "@/components/strategy/indicator-config"
import {
  useSignalConstructionPreview,
  useEntryRulesPreview,
  useExitRulesPreview,
  useRiskPreview,
  useStrategies,
  useStrategy,
  useStrategyAllocation,
  useStrategyReview,
  useUniverse,
} from "@/hooks/use-api"
import { archiveStrategy, createStrategy, duplicateStrategy, updateStrategy, type StrategyAllocationRow } from "@/lib/api"
import { applyStarterPresetToStock, cloneStockStrategyConfig, defaultEntryRule, defaultExitRule, defaultIndicatorRowConfig, defaultRuleCondition, defaultStrategyConfigV2, ensureBasketStocks, manualParam, migrateStrategyConfigV2, scoreVariableOptions, type EntryRuleV2, type ExitRuleV2, type FamilyId, type HorizonKey, type RiskConfigV2, type RuleConditionV2, type StrategyConfigV2 } from "@/lib/strategy-v2"
import { STRATEGY_TEMPLATE_REGISTRY, materializeStrategyTemplate } from "@/lib/strategy-template-registry"
import { cn } from "@/lib/utils"

const fmtMoney = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "-" : v.toLocaleString("fr-FR", { maximumFractionDigits: 0 }))
const fmtPct = (v: number | null | undefined, d = 1) => (v == null || Number.isNaN(v) ? "-" : `${v.toFixed(d)}%`)
const parseIntSafe = (v: string) => { const n = Number(String(v).replace(/\s/g, "").replace(/,/g, "")); return Number.isFinite(n) ? n : 0 }
const LOCAL_STRATEGY_DRAFT_KEY = "strategy.simple.localDraft.v1"
type StrategyStep = "capital" | "type" | "signal" | "entry" | "exit" | "risk" | "review"
type WorkflowMode = "simple" | "advanced"
const SIMPLE_STRATEGY_STEPS: Array<{ id: StrategyStep; label: string }> = [
  { id: "capital", label: "Stock Universe" },
  { id: "signal", label: "Indicators" },
  { id: "entry", label: "Entries" },
  { id: "exit", label: "Exits" },
  { id: "risk", label: "Risk" },
  { id: "review", label: "Review" },
]
const ADVANCED_STRATEGY_STEPS: Array<{ id: StrategyStep; label: string }> = [
  { id: "capital", label: "Stock Universe" },
  { id: "type", label: "Basket Setup" },
  { id: "signal", label: "Signal Rules" },
  { id: "entry", label: "Entries" },
  { id: "exit", label: "Exits" },
  { id: "risk", label: "Risk" },
  { id: "review", label: "Review" },
]

function manualOverridesForApi(config: StrategyConfigV2) {
  const out: Record<string, number> = {}
  for (const symbol of config.portfolio.universe.basket) {
    const value = config.portfolio.allocation.manual_overrides_by_symbol[symbol]
    if (value?.enabled && value.capital_mad > 0) out[symbol] = value.capital_mad
  }
  return out
}


function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function buildSignalPreviewStockConfig(
  stock: StrategyConfigV2["stocks"][string] | null,
): Record<string, unknown> | null {
  if (!stock) return null
  return {
    strategy_type: stock.strategy_type,
    signal_construction: structuredClone(stock.signal_construction),
  }
}

function buildSignalConstructionShapeSignature(stockConfig: Record<string, unknown> | null): string {
  if (!stockConfig) return ""
  const signalConstruction = isRecord(stockConfig.signal_construction) ? stockConfig.signal_construction : {}
  const families = isRecord(signalConstruction.families) ? signalConstruction.families : {}
  const familyShape = Object.keys(families)
    .sort()
    .map((familyId) => {
      const family = isRecord(families[familyId]) ? families[familyId] : {}
      const rows = Array.isArray(family.rows) ? family.rows : []
      return {
        family_id: familyId,
        enabled: Boolean(family.enabled),
        source_mode: String(family.source_mode ?? "indicator_rows"),
        rows: rows.map((row) => {
          const rowRecord = isRecord(row) ? row : {}
          const params = isRecord(rowRecord.params) ? rowRecord.params : {}
          return {
            id: String(rowRecord.id ?? ""),
            enabled: rowRecord.enabled == null ? true : Boolean(rowRecord.enabled),
            score_key: String(rowRecord.score_key ?? ""),
            label: String(rowRecord.label ?? ""),
            param_modes: Object.keys(params)
              .sort()
              .map((paramName) => {
                const param = isRecord(params[paramName]) ? params[paramName] : {}
                return {
                  name: paramName,
                  mode: String(param.mode ?? "manual"),
                  value: param.value ?? null,
                  scan_min: param.scan_min ?? null,
                  scan_max: param.scan_max ?? null,
                  scan_step: param.scan_step ?? null,
                }
              }),
          }
        }),
      }
    })
  return JSON.stringify({
    strategy_type: String(stockConfig.strategy_type ?? ""),
    families: familyShape,
  })
}

function AllocationCard({ symbol, totalCapital, row, override, onChange }: { symbol: string; totalCapital: number; row: StrategyAllocationRow | null; override: { enabled: boolean; capital_mad: number }; onChange: (next: { enabled: boolean; capital_mad: number }) => void }) {
  const hrpCapital = totalCapital * ((row?.hrp_weight_pct ?? 0) / 100)
  return (
    <Card className="claude-card"><CardHeader><CardTitle>Allocation</CardTitle><CardDescription>Allocation stays stock-specific even when copying the logic template to the full basket.</CardDescription></CardHeader><CardContent className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <SummaryStat label="Source" value={row?.source === "manual" ? "Manual" : "HRP"} sub={row?.source === "manual" ? "Override active" : "Baseline"} />
        <SummaryStat label="HRP suggested" value={fmtPct(row?.hrp_weight_pct ?? 0, 2)} sub={`${fmtMoney(hrpCapital)} MAD`} />
        <SummaryStat label="Allocated" value={fmtPct(row?.weight_pct ?? 0, 2)} sub={`${fmtMoney(row?.capital_mad ?? 0)} MAD`} primary={row?.source === "manual"} />
      </div>
      <div className="rounded-lg border border-line bg-bg2 p-4"><div className="flex items-center justify-between gap-4"><div><p className="text-sm font-medium">Manual override</p><p className="text-xs text-muted-foreground">Override the HRP baseline only for {symbol}.</p></div><Switch checked={override.enabled} onCheckedChange={(checked) => onChange({ ...override, enabled: checked })} /></div><div className="mt-4 space-y-1"><Label className="text-xs">Manual capital (MAD)</Label><Input type="number" className="h-8 text-sm" value={override.capital_mad} min={0} step={1000} disabled={!override.enabled} onChange={(e) => onChange({ ...override, capital_mad: Number(e.target.value) })} /></div></div>
    </CardContent></Card>
  )
}

function SummaryStat({ label, value, sub, primary, tone }: { label: string; value: string | number; sub?: string; primary?: boolean; tone?: "pos" | "neg" | "mut" }) {
  return (
    <div className={cn("claude-stat", primary && "primary")}>
      <div className="lbl">{label}</div>
      <div className={cn("val", tone === "pos" && "t-pos", tone === "neg" && "t-neg", tone === "mut" && "t-mut")}>{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  )
}

const SIMPLE_RULE_OPERATOR_OPTIONS: RuleConditionV2["operator"][] = [">=", ">", "<=", "<"]

function firstRuleCondition(rule: EntryRuleV2 | ExitRuleV2 | undefined): RuleConditionV2 {
  return rule?.conditions[0] ?? defaultRuleCondition(0)
}

function familyIdForRuleVariable(stock: StrategyConfigV2["stocks"][string], variable: string): FamilyId {
  for (const meta of INDICATOR_FAMILY_META) {
    const familyId = meta.key as FamilyId
    const family = stock.signal_construction.families[familyId]
    if (family?.rows.some((row) => row.score_key === variable)) return familyId
    if (defaultIndicatorRowConfig(familyId, 0).score_key === variable) return familyId
  }
  const enabledMeta = INDICATOR_FAMILY_META.find((meta) => stock.signal_construction.families[meta.key as FamilyId]?.enabled)
  return (enabledMeta?.key ?? "rsi") as FamilyId
}

function SimpleIndicatorRuleCard({
  kind,
  horizon,
  stock,
  rules,
  preview,
  errorMessage,
  onIndicatorChange,
  onParamChange,
  onConditionChange,
}: {
  kind: "entry" | "exit"
  horizon: HorizonKey
  stock: StrategyConfigV2["stocks"][string]
  rules: EntryRuleV2[] | ExitRuleV2[]
  preview?: { score_snapshot: Record<string, number | null>; rules: Array<{ id: string; label: string; triggered: boolean; conditions: string[] }> }
  errorMessage?: string | null
  onIndicatorChange: (familyId: FamilyId) => void
  onParamChange: (familyId: FamilyId, paramKey: string, value: number) => void
  onConditionChange: (patch: Partial<RuleConditionV2>) => void
}) {
  const rule = rules[0]
  const condition = firstRuleCondition(rule)
  const familyId = familyIdForRuleVariable(stock, condition.variable)
  const meta = INDICATOR_FAMILY_META.find((item) => item.key === familyId) ?? INDICATOR_FAMILY_META[0]
  const family = stock.signal_construction.families[familyId]
  const row = family?.rows[0] ?? defaultIndicatorRowConfig(familyId, 0)
  const previewValue = preview?.score_snapshot?.[condition.variable]
  const previewRule = preview?.rules?.[0]
  const title = kind === "entry" ? "Entry Rule" : "Exit Rule"
  const description = kind === "entry"
    ? "Choose the indicator that opens the position and tune its parameters."
    : "Choose the indicator that closes or reduces the position and tune its parameters."

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title} - {activeRuleSymbolLabel(stock, rule?.label)}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-3">
          <div className="space-y-1 lg:col-span-1">
            <Label className="text-xs">Indicator</Label>
            <Select value={familyId} onValueChange={(value) => onIndicatorChange(value as FamilyId)}>
              <SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {INDICATOR_FAMILY_META.map((option) => (
                  <SelectItem key={option.key} value={option.key}>{option.shortLabel}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:col-span-2">
            <div className="space-y-1">
              <Label className="text-xs">Trigger</Label>
              <Select value={condition.operator} onValueChange={(value) => onConditionChange({ operator: value as RuleConditionV2["operator"] })}>
                <SelectTrigger className="h-9 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {SIMPLE_RULE_OPERATOR_OPTIONS.map((option) => (
                    <SelectItem key={option} value={option}>{option}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Threshold</Label>
              <Input
                type="number"
                className="h-9"
                step={0.1}
                value={condition.threshold.value}
                onChange={(event) => onConditionChange({ threshold: manualParam(Number(event.target.value)) })}
              />
            </div>
          </div>
        </div>

        <div className="rounded-lg border bg-muted/20 p-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-semibold">{meta.shortLabel}</p>
              <p className="text-xs text-muted-foreground">{meta.description}</p>
            </div>
            <Badge variant={family?.enabled ? "default" : "secondary"}>{family?.enabled ? "Active" : "Will activate"}</Badge>
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {meta.params.map((param) => {
              const rowKey = familyId === "sma" && param.key === "period" ? "window" : param.key
              const value = row.params[rowKey]?.value ?? meta.defaults[param.key] ?? 0
              return (
                <Label key={`${kind}-${familyId}-${param.key}`} className="space-y-1 text-xs">
                  <span>{param.label}</span>
                  <Input
                    type="number"
                    min={param.min}
                    max={param.max}
                    step={param.step}
                    value={value}
                    onChange={(event) => onParamChange(familyId, param.key, Number(event.target.value))}
                    className="h-8"
                  />
                </Label>
              )
            })}
          </div>
        </div>

        <div className="rounded-lg border bg-background px-3 py-2 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-muted-foreground">
              {meta.shortLabel} score {condition.operator} {condition.threshold.value}
            </span>
            <span className={previewRule?.triggered ? "font-medium text-green-700" : "text-muted-foreground"}>
              {previewRule?.triggered ? "Triggered" : "Idle"}
            </span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            Current score: {previewValue == null ? "--" : previewValue.toFixed(1)}
          </div>
        </div>

        {errorMessage ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Preview unavailable: {errorMessage}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

function activeRuleSymbolLabel(_stock: StrategyConfigV2["stocks"][string], label: string | undefined): string {
  return label?.trim() || "Simple trigger"
}

function StrategyPageContent() {
  const searchParams = useSearchParams()
  const [activeId, setActiveId] = useState<string | null>(null)
  const [activeSymbol, setActiveSymbol] = useState<string | null>(null)
  const [name, setName] = useState("New strategy")
  const [sidePolicy, setSidePolicy] = useState("long_only")
  const [horizon, setHorizon] = useState("short")
  const [status, setStatus] = useState("draft")
  const [config, setConfig] = useState<StrategyConfigV2>(() => defaultStrategyConfigV2("short"))
  const [isSaving, setIsSaving] = useState(false)
  const [activeStep, setActiveStep] = useState<StrategyStep>("capital")
  const [workflowMode, setWorkflowMode] = useState<WorkflowMode>("simple")
  const searchStrategyId = searchParams.get("strategyId")

  const { data: strategies, isLoading: strategiesLoading, mutate: mutateStrategies } = useStrategies()
  const { data: loadedStrategy } = useStrategy(activeId)
  const { data: universe, isLoading: universeLoading, error: universeError } = useUniverse(horizon)
  const { data: allocationPreview } = useStrategyAllocation(config.portfolio.universe.basket, { total_capital_mad: config.portfolio.total_capital_mad, method: config.portfolio.allocation.method, lookback_bars: config.portfolio.allocation.hrp_lookback_bars, manual_overrides_by_symbol: manualOverridesForApi(config) })
  const { data: reviewPreview } = useStrategyReview(config as unknown as Record<string, unknown>, horizon)
  const stockConfig = activeSymbol ? config.stocks[activeSymbol] : null
  const signalPreviewRawConfig = useMemo(() => buildSignalPreviewStockConfig(stockConfig), [stockConfig])
  const signalPreviewRawSerialized = useMemo(
    () => signalPreviewRawConfig ? JSON.stringify(signalPreviewRawConfig) : null,
    [signalPreviewRawConfig],
  )
  const signalPreviewShapeSignature = useMemo(
    () => buildSignalConstructionShapeSignature(signalPreviewRawConfig),
    [signalPreviewRawConfig],
  )
  const [familyHistoryMode, setFamilyHistoryMode] = useState<"static_current_reps" | "dynamic_point_in_time">("dynamic_point_in_time")
  const signalPreviewImmediateSignature = `${activeSymbol ?? ""}:${horizon}:${familyHistoryMode}:${signalPreviewShapeSignature}`
  const [signalPreviewConfig, setSignalPreviewConfig] = useState<Record<string, unknown> | null>(signalPreviewRawConfig)
  const [signalPreviewPending, setSignalPreviewPending] = useState(false)
  const signalPreviewShapeRef = useRef("")
  const localDraftLoadedRef = useRef(false)

  useEffect(() => {
    if (!signalPreviewRawConfig) {
      signalPreviewShapeRef.current = ""
      setSignalPreviewConfig(null)
      setSignalPreviewPending(false)
      return
    }

    const previousShape = signalPreviewShapeRef.current
    signalPreviewShapeRef.current = signalPreviewImmediateSignature
    const shouldRefreshImmediately = previousShape.length === 0 || previousShape !== signalPreviewImmediateSignature

    if (shouldRefreshImmediately) {
      setSignalPreviewConfig(signalPreviewRawConfig)
      setSignalPreviewPending(false)
      return
    }

    setSignalPreviewPending(true)
    const timer = window.setTimeout(() => {
      setSignalPreviewConfig(signalPreviewRawConfig)
      setSignalPreviewPending(false)
    }, 220)

    return () => window.clearTimeout(timer)
  }, [signalPreviewImmediateSignature, signalPreviewRawConfig, signalPreviewRawSerialized])

  const signalPreviewSerialized = useMemo(
    () => signalPreviewConfig ? JSON.stringify(signalPreviewConfig) : null,
    [signalPreviewConfig],
  )
  const signalPreviewRenderKey = signalPreviewSerialized
    ? `${activeSymbol ?? "preview"}:${horizon}:${signalPreviewSerialized}`
    : `${activeSymbol ?? "preview"}:${horizon}:empty`

  const activeStockConfig = stockConfig as unknown as Record<string, unknown> | null
  const { data: signalPreview, isLoading: signalPreviewLoading, isValidating: signalPreviewValidating, error: signalPreviewError } = useSignalConstructionPreview(
    activeSymbol,
    horizon,
    signalPreviewConfig,
    { familyHistoryMode },
  )
  const { data: entryPreview, error: entryPreviewError } = useEntryRulesPreview(activeSymbol, horizon, activeStockConfig)
  const { data: exitPreview, error: exitPreviewError } = useExitRulesPreview(activeSymbol, horizon, activeStockConfig)
  const { data: riskPreview, error: riskPreviewError } = useRiskPreview(activeSymbol, horizon, activeStockConfig)
  const rowBySymbol = useMemo(() => new Map((allocationPreview?.rows ?? []).map((row) => [row.symbol, row])), [allocationPreview?.rows])
  const universeIsStaticFallback = Boolean((universe ?? []).some((stock) => stock.is_static_fallback))

  useEffect(() => { if (searchStrategyId && strategies?.some((s) => s.id === searchStrategyId) && searchStrategyId !== activeId) setActiveId(searchStrategyId) }, [activeId, searchStrategyId, strategies])
  useEffect(() => { if (!loadedStrategy) return; const next = ensureBasketStocks(migrateStrategyConfigV2(loadedStrategy.config_json, loadedStrategy.horizon), loadedStrategy.horizon); setName(loadedStrategy.name); setSidePolicy(loadedStrategy.side_policy); setHorizon(loadedStrategy.horizon); setStatus(loadedStrategy.status); setConfig(next); setActiveSymbol(next.portfolio.universe.basket[0] ?? null); setActiveStep(next.portfolio.universe.basket.length > 0 ? "type" : "capital") }, [loadedStrategy])
  useEffect(() => {
    if (!universeIsStaticFallback || localDraftLoadedRef.current || loadedStrategy || activeId || typeof window === "undefined") return
    localDraftLoadedRef.current = true
    const raw = window.localStorage.getItem(LOCAL_STRATEGY_DRAFT_KEY)
    if (!raw) return
    try {
      const draft = JSON.parse(raw) as { name?: string; side_policy?: string; horizon?: string; status?: string; config_json?: unknown }
      const draftHorizon = draft.horizon || horizon
      const next = ensureBasketStocks(migrateStrategyConfigV2(draft.config_json, draftHorizon), draftHorizon)
      setName(draft.name || "Local simple strategy")
      setSidePolicy(draft.side_policy || "long_only")
      setHorizon(draftHorizon)
      setStatus(draft.status || "local")
      setConfig(next)
      setActiveSymbol(next.portfolio.universe.basket[0] ?? null)
      setWorkflowMode("simple")
    } catch {
      window.localStorage.removeItem(LOCAL_STRATEGY_DRAFT_KEY)
    }
  }, [activeId, horizon, loadedStrategy, universeIsStaticFallback])
  useEffect(() => { const basket = config.portfolio.universe.basket; if (basket.length === 0) setActiveSymbol(null); else if (!activeSymbol || !basket.includes(activeSymbol)) setActiveSymbol(basket[0]) }, [activeSymbol, config.portfolio.universe.basket])
  useEffect(() => {
    const steps = workflowMode === "simple" ? SIMPLE_STRATEGY_STEPS : ADVANCED_STRATEGY_STEPS
    if (!steps.some((step) => step.id === activeStep)) setActiveStep("capital")
  }, [activeStep, workflowMode])

  const markModified = useCallback(() => setStatus((prev) => prev === "saved" ? "modified" : prev), [])
  const updatePortfolioUniverse = useCallback((patch: Partial<StrategyConfigV2["portfolio"]["universe"]>) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, universe: { ...prev.portfolio.universe, ...patch } } })); markModified() }, [markModified])
  const updateStock = useCallback((symbol: string, updater: (stock: StrategyConfigV2["stocks"][string]) => StrategyConfigV2["stocks"][string]) => { setConfig((prev) => ({ ...prev, stocks: { ...prev.stocks, [symbol]: updater(cloneStockStrategyConfig(prev.stocks[symbol], horizon)) } })); markModified() }, [horizon, markModified])

  const setBasketSymbolSelected = useCallback((symbol: string, selected: boolean) => {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized) return
    setConfig((prev) => {
      const currentBasket = prev.portfolio.universe.basket.map((item) => item.trim().toUpperCase()).filter(Boolean)
      const exists = currentBasket.includes(normalized)
      const basket = selected
        ? exists ? currentBasket : [...currentBasket, normalized]
        : currentBasket.filter((item) => item !== normalized)
      const stocks = { ...prev.stocks }
      if (selected && stocks[normalized]) {
        stocks[normalized] = {
          ...stocks[normalized],
          signal_construction: {
            ...stocks[normalized].signal_construction,
            source_mode: "manual",
            selected_signal_candidate: null,
          },
        }
      }
      return ensureBasketStocks({
        ...prev,
        portfolio: {
          ...prev.portfolio,
          universe: {
            ...prev.portfolio.universe,
            basket,
            selection_mode: "manual",
            selected_signal_candidates: [],
          },
        },
        stocks,
      }, horizon)
    })
    setActiveSymbol((prev) => selected ? normalized : prev === normalized ? null : prev)
    markModified()
  }, [horizon, markModified])

  const clearBasket = useCallback(() => {
    setConfig((prev) => ensureBasketStocks({
      ...prev,
      portfolio: {
        ...prev.portfolio,
        universe: {
          ...prev.portfolio.universe,
          basket: [],
          selection_mode: "manual",
          selected_signal_candidates: [],
        },
      },
    }, horizon))
    setActiveSymbol(null)
    markModified()
  }, [horizon, markModified])
  const applyToAll = useCallback(() => { if (!activeSymbol || !stockConfig) return; setConfig((prev) => ({ ...prev, stocks: Object.fromEntries(prev.portfolio.universe.basket.map((symbol) => { const current = cloneStockStrategyConfig(prev.stocks[symbol], horizon); const source = cloneStockStrategyConfig(stockConfig, horizon); source.risk.max_position_pct = current.risk.max_position_pct; source.risk.max_sector_pct = current.risk.max_sector_pct; return [symbol, source] })) })); markModified() }, [activeSymbol, horizon, markModified, stockConfig])
  const applyTemplateToActive = useCallback((templateId: string) => {
    if (!activeSymbol) return
    updateStock(activeSymbol, (stock) => materializeStrategyTemplate(templateId, horizon as HorizonKey, stock) ?? stock)
    setWorkflowMode("advanced")
    setActiveStep("entry")
  }, [activeSymbol, horizon, updateStock])
  const applyTemplateToAll = useCallback((templateId: string) => {
    setConfig((prev) => {
      if (prev.portfolio.universe.basket.length === 0) return prev
      return {
        ...prev,
        stocks: Object.fromEntries(
          prev.portfolio.universe.basket.map((symbol) => {
            const current = cloneStockStrategyConfig(prev.stocks[symbol], horizon)
            return [symbol, materializeStrategyTemplate(templateId, horizon as HorizonKey, current) ?? current]
          }),
        ),
      }
    })
    markModified()
    setWorkflowMode("advanced")
    setActiveStep("entry")
  }, [horizon, markModified])
  const setSimpleIndicatorEnabled = useCallback((familyId: FamilyId, enabled: boolean) => {
    if (!activeSymbol) return
    updateStock(activeSymbol, (stock) => {
      const existingFamily = stock.signal_construction.families[familyId] ?? {
        enabled: false,
        source_mode: "indicator_rows" as const,
        rows: [defaultIndicatorRowConfig(familyId, 0)],
      }
      return {
        ...stock,
        signal_construction: {
          ...stock.signal_construction,
          source_mode: "manual",
          families: {
            ...stock.signal_construction.families,
            [familyId]: {
              ...existingFamily,
              enabled,
              source_mode: "indicator_rows",
              rows: existingFamily.rows.length > 0 ? existingFamily.rows : [defaultIndicatorRowConfig(familyId, 0)],
            },
          },
        },
      }
    })
  }, [activeSymbol, updateStock])
  const setSimpleIndicatorParam = useCallback((familyId: FamilyId, paramKey: string, rawValue: number) => {
    if (!activeSymbol) return
    updateStock(activeSymbol, (stock) => {
      const meta = INDICATOR_FAMILY_META.find((item) => item.key === familyId)
      if (!meta) return stock
      const family = stock.signal_construction.families[familyId] ?? {
        enabled: true,
        source_mode: "indicator_rows" as const,
        rows: [defaultIndicatorRowConfig(familyId, 0)],
      }
      const row = family.rows[0] ?? defaultIndicatorRowConfig(familyId, 0)
      const currentParams = Object.fromEntries(
        meta.params.map((param) => {
          const rowKey = familyId === "sma" && param.key === "period" ? "window" : param.key
          return [param.key, row.params[rowKey]?.value ?? meta.defaults[param.key] ?? 0]
        }),
      )
      const normalized = normalizeIndicatorParams(familyId, paramKey, rawValue, currentParams)
      const nextParams = { ...row.params }
      for (const param of meta.params) {
        const rowKey = familyId === "sma" && param.key === "period" ? "window" : param.key
        nextParams[rowKey] = manualParam(normalized[param.key] ?? currentParams[param.key] ?? meta.defaults[param.key] ?? 0)
      }
      return {
        ...stock,
        signal_construction: {
          ...stock.signal_construction,
          source_mode: "manual",
          families: {
            ...stock.signal_construction.families,
            [familyId]: {
              ...family,
              enabled: true,
              source_mode: "indicator_rows",
              rows: [{ ...row, enabled: true, params: nextParams }, ...family.rows.slice(1)],
            },
          },
        },
      }
    })
  }, [activeSymbol, updateStock])
  const setSimpleRuleIndicator = useCallback((kind: "entry" | "exit", familyId: FamilyId) => {
    if (!activeSymbol) return
    updateStock(activeSymbol, (stock) => {
      const meta = INDICATOR_FAMILY_META.find((item) => item.key === familyId)
      const existingFamily = stock.signal_construction.families[familyId] ?? {
        enabled: false,
        source_mode: "indicator_rows" as const,
        rows: [defaultIndicatorRowConfig(familyId, 0)],
      }
      const row = existingFamily.rows[0] ?? defaultIndicatorRowConfig(familyId, 0)
      const existingRule = kind === "entry" ? stock.entry_rules[0] ?? defaultEntryRule(0) : stock.exit_rules[0] ?? defaultExitRule(0)
      const existingCondition = firstRuleCondition(existingRule)
      const usesDefaultConsensus = existingCondition.variable === "consensus_score"
      const nextCondition: RuleConditionV2 = {
        ...existingCondition,
        variable: row.score_key,
        operator: usesDefaultConsensus ? (kind === "entry" ? ">=" : "<=") : existingCondition.operator,
        threshold: usesDefaultConsensus ? manualParam(kind === "entry" ? 20 : 0) : existingCondition.threshold,
      }
      const nextRule = {
        ...existingRule,
        label: `${kind === "entry" ? "Entry" : "Exit"} with ${meta?.shortLabel ?? familyId}`,
        conditions: [nextCondition],
      }
      const nextStock = {
        ...stock,
        signal_construction: {
          ...stock.signal_construction,
          source_mode: "manual" as const,
          families: {
            ...stock.signal_construction.families,
            [familyId]: {
              ...existingFamily,
              enabled: true,
              source_mode: "indicator_rows" as const,
              rows: existingFamily.rows.length > 0 ? existingFamily.rows : [row],
            },
          },
        },
      }
      return kind === "entry"
        ? { ...nextStock, entry_rules: [nextRule as EntryRuleV2] }
        : { ...nextStock, exit_rules: [nextRule as ExitRuleV2] }
    })
  }, [activeSymbol, updateStock])
  const setSimpleRuleCondition = useCallback((kind: "entry" | "exit", patch: Partial<RuleConditionV2>) => {
    if (!activeSymbol) return
    updateStock(activeSymbol, (stock) => {
      const existingRule = kind === "entry" ? stock.entry_rules[0] ?? defaultEntryRule(0) : stock.exit_rules[0] ?? defaultExitRule(0)
      const nextRule = {
        ...existingRule,
        conditions: [{ ...firstRuleCondition(existingRule), ...patch }],
      }
      return kind === "entry"
        ? { ...stock, entry_rules: [nextRule as EntryRuleV2] }
        : { ...stock, exit_rules: [nextRule as ExitRuleV2] }
    })
  }, [activeSymbol, updateStock])

  const save = useCallback(async () => {
    const canonicalConfig = ensureBasketStocks(config, horizon)
    const payload = { name, side_policy: sidePolicy, horizon, config_json: canonicalConfig as unknown as Record<string, unknown>, status: "saved" }
    setIsSaving(true)
    try {
      if (universeIsStaticFallback && typeof window !== "undefined") {
        window.localStorage.setItem(
          LOCAL_STRATEGY_DRAFT_KEY,
          JSON.stringify({ ...payload, status: "local", saved_at: new Date().toISOString() }),
        )
        setActiveId(null)
        setStatus("local")
        return
      }
      if (!activeId) {
        const created = await createStrategy({ name, side_policy: sidePolicy, horizon })
        setActiveId(created.id)
        await updateStrategy(created.id, payload)
      } else await updateStrategy(activeId, payload)
      setStatus("saved")
      mutateStrategies()
    } finally {
      setIsSaving(false)
    }
  }, [activeId, config, horizon, mutateStrategies, name, sidePolicy, universeIsStaticFallback])
  const create = useCallback(async () => {
    if (universeIsStaticFallback) {
      setActiveId(null)
      setName("New local strategy")
      setSidePolicy("long_only")
      setHorizon("short")
      setStatus("draft")
      setConfig(defaultStrategyConfigV2("short"))
      setActiveSymbol(null)
      setActiveStep("capital")
      setWorkflowMode("simple")
      return
    }
    const created = await createStrategy({ name: "New strategy", side_policy: "long_only", horizon: "short" })
    setActiveId(created.id)
    setName(created.name)
    setSidePolicy(created.side_policy)
    setHorizon(created.horizon)
    setStatus(created.status)
    setConfig(defaultStrategyConfigV2(created.horizon))
    setActiveSymbol(null)
    setActiveStep("capital")
    mutateStrategies()
  }, [mutateStrategies, universeIsStaticFallback])
  const duplicate = useCallback(async () => { if (!activeId) return; const copy = await duplicateStrategy(activeId); mutateStrategies(); setActiveId(copy.id) }, [activeId, mutateStrategies])
  const archive = useCallback(async () => { if (!activeId) return; await archiveStrategy(activeId); setActiveId(null); setName("New strategy"); setSidePolicy("long_only"); setHorizon("short"); setStatus("draft"); setConfig(defaultStrategyConfigV2("short")); setActiveSymbol(null); setActiveStep("capital"); mutateStrategies() }, [activeId, mutateStrategies])
  const activeSteps = workflowMode === "simple" ? SIMPLE_STRATEGY_STEPS : ADVANCED_STRATEGY_STEPS
  const activeStepIndex = Math.max(0, activeSteps.findIndex((step) => step.id === activeStep))
  const currentStock = activeSymbol ? config.stocks[activeSymbol] : null
  const noBasketSelected = config.portfolio.universe.basket.length === 0
  const currentAllocationRow = activeSymbol ? rowBySymbol.get(activeSymbol) ?? null : null
  const currentOverride = activeSymbol
    ? config.portfolio.allocation.manual_overrides_by_symbol[activeSymbol] ?? { enabled: false, capital_mad: 0 }
    : { enabled: false, capital_mad: 0 }
  const currentScoreOptions = currentStock
    ? scoreVariableOptions(currentStock, [
        ...currentStock.entry_rules.flatMap((rule) => rule.conditions.map((condition) => condition.variable)),
        ...currentStock.exit_rules.flatMap((rule) => rule.conditions.map((condition) => condition.variable)),
      ])
    : []
  const backtestHref = !universeIsStaticFallback && activeId && status === "saved" && reviewPreview?.ready ? `/backtest?strategyId=${activeId}` : null
  const backtestBlockedReason = backtestHref
    ? null
    : universeIsStaticFallback
      ? "The API is offline, so this draft is local only. Start the API and save again before backtesting."
      : !activeId
      ? "Save the strategy before opening Backtest."
      : status !== "saved"
        ? "Save the latest changes before opening Backtest."
        : (reviewPreview?.blocking_issues?.[0] ?? (reviewPreview?.ready === false ? "Resolve the review blockers before opening Backtest." : "Complete the strategy review before opening Backtest."))
  const nextStepBlockedReason = noBasketSelected
    ? "Select at least one stock before continuing."
    : null
  const goToStepOffset = (offset: number) => {
    const next = activeSteps[activeStepIndex + offset]
    if (next) setActiveStep(next.id)
  }

  return (
    <div className="claude-strategy claude-page space-y-4">
      <div className="claude-page-h">
        <div className="min-w-0">
          <h1>Strategy</h1>
          <div className="sub flex flex-wrap items-center gap-2">
            <span>Constructeur</span>
            <span>-</span>
            <Input
              value={name}
              onChange={(event) => {
                setName(event.target.value)
                markModified()
              }}
              className="h-7 w-[min(420px,70vw)] border-0 bg-transparent px-1 text-sm font-semibold shadow-none focus-visible:ring-0"
            />
            <span>-</span>
            <Badge variant={status === "saved" ? "default" : "secondary"}>{status}</Badge>
          </div>
        </div>
        <div className="actions">
          <Select value={sidePolicy} onValueChange={(value) => { setSidePolicy(value); markModified() }}>
            <SelectTrigger className="h-8 w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="long_only">Long only</SelectItem>
              <SelectItem value="long_short">Long/short</SelectItem>
            </SelectContent>
          </Select>
          <Button type="button" variant="outline" size="sm" onClick={duplicate} disabled={!activeId} className="gap-2">
            <CopyPlus className="h-4 w-4" />
            Dupliquer
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => setActiveStep("review")} className="gap-2">
            <Eye className="h-4 w-4" />
            Apercu
          </Button>
          <Button asChild variant="outline" size="sm" className="gap-2">
            <Link href="/glossary#strategy">
              <BookOpen className="h-4 w-4" />
              Glossaire
            </Link>
          </Button>
          {backtestHref ? (
            <Button asChild size="sm" className="gap-2">
              <Link href={backtestHref}>
                <Gauge className="h-4 w-4" />
                Lancer un backtest
              </Link>
            </Button>
          ) : (
            <Button type="button" size="sm" disabled className="gap-2" title={backtestBlockedReason ?? undefined}>
              <Gauge className="h-4 w-4" />
              Lancer un backtest
            </Button>
          )}
        </div>
      </div>

      <div className="alloc-row">
        <div className="alloc primary">
          <div className="lbl">Capital</div>
          <div className="val">{fmtMoney(config.portfolio.total_capital_mad)}</div>
          <div className="sub">MAD - disponible</div>
        </div>
        <div className="alloc">
          <div className="lbl">Basket</div>
          <div className="val">{config.portfolio.universe.basket.length} / {universe?.length ?? "-"}</div>
          <div className="sub">titres selectionnes</div>
        </div>
        <div className="alloc">
          <div className="lbl">Active stock</div>
          <div className="val">{activeSymbol ?? "-"}</div>
          <div className="sub">current setup</div>
        </div>
        <div className="alloc">
          <div className="lbl">Allocated</div>
          <div className="val">{fmtMoney(allocationPreview?.allocated_capital_mad ?? 0)}</div>
          <div className="sub">{fmtPct(config.portfolio.total_capital_mad > 0 ? ((allocationPreview?.allocated_capital_mad ?? 0) / config.portfolio.total_capital_mad) * 100 : 0)} du capital</div>
        </div>
        <div className="alloc">
          <div className="lbl">Remaining</div>
          <div className="val">{fmtMoney(allocationPreview?.remaining_capital_mad ?? config.portfolio.total_capital_mad)}</div>
          <div className="sub">cash buffer</div>
        </div>
      </div>

      <div className="layout">
        <aside className="sidebar space-y-3">
          <div className="savd">
            <div className="ch flex items-center justify-between">
              <h4>Saved Strategies</h4>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" onClick={create}>
                <Plus className="h-4 w-4" />
              </Button>
            </div>
            <ul>
              {strategiesLoading ? (
                Array.from({ length: 5 }).map((_, index) => (
                  <li key={index}><Skeleton className="h-5 w-full" /></li>
                ))
              ) : (strategies ?? []).length === 0 ? (
                <li><span>No saved strategies</span></li>
              ) : (
                (strategies ?? []).map((item) => (
                  <li
                    key={item.id}
                    className={cn(item.id === activeId && "active")}
                    onClick={() => setActiveId(item.id)}
                  >
                    <span className="min-w-0 truncate">{item.name}</span>
                    <span className="ts">{item.horizon}</span>
                  </li>
                ))
              )}
            </ul>
          </div>

          <div className="savd">
            <div className="ch flex items-center justify-between">
              <h4>Template Library</h4>
              <BookOpen className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="space-y-2">
              {STRATEGY_TEMPLATE_REGISTRY.map((template) => (
                <div key={template.id} className="rounded-lg border border-line bg-bg2 p-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold">{template.name}</div>
                      <div className="truncate text-[11px] text-muted-foreground">{template.author}</div>
                    </div>
                    <Badge variant="outline" className="shrink-0 text-[10px] capitalize">{template.category.replace("_", " ")}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">{template.summary}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {template.tags.slice(0, 3).map((tag) => (
                      <span key={tag} className="rounded-full border bg-background px-2 py-0.5 text-[10px] text-muted-foreground">{tag}</span>
                    ))}
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-1.5">
                    <Button type="button" variant="outline" size="sm" onClick={() => applyTemplateToActive(template.id)} disabled={!activeSymbol || !template.isExecutable}>
                      Active
                    </Button>
                    <Button type="button" variant="outline" size="sm" onClick={() => applyTemplateToAll(template.id)} disabled={config.portfolio.universe.basket.length === 0 || !template.isExecutable}>
                      All
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" onClick={save} disabled={isSaving} className="flex-1 gap-2">
              <Save className="h-4 w-4" />
              {isSaving ? "Saving" : "Save"}
            </Button>
            <Button type="button" variant="outline" size="icon" className="h-8 w-8" onClick={archive} disabled={!activeId}>
              <Archive className="h-4 w-4" />
            </Button>
          </div>
        </aside>

        <div className="min-w-0">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-bg2 p-2">
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant={workflowMode === "simple" ? "default" : "outline"} onClick={() => setWorkflowMode("simple")}>
                Simple strategy
              </Button>
              <Button type="button" size="sm" variant={workflowMode === "advanced" ? "default" : "outline"} onClick={() => setWorkflowMode("advanced")}>
                Advanced wizard
              </Button>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">Horizon</span>
              <Select value={horizon} onValueChange={(value) => { setHorizon(value); setConfig((prev) => ensureBasketStocks(prev, value)); markModified() }}>
                <SelectTrigger className="h-8 w-[130px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="short">Hebdomadaire</SelectItem>
                  <SelectItem value="medium">Mensuel</SelectItem>
                  <SelectItem value="long">Trimestriel</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {workflowMode === "simple" ? (
            <>
              <div className="wizard">
                {activeSteps.map((step, index) => (
                  <button
                    key={step.id}
                    type="button"
                    className={cn("step", index < activeStepIndex && "done", step.id === activeStep && "active")}
                    disabled={step.id !== "capital" && noBasketSelected}
                    title={step.id !== "capital" && noBasketSelected ? "Select at least one stock first." : undefined}
                    onClick={() => setActiveStep(step.id)}
                  >
                    <span className="num">{index < activeStepIndex ? <Check className="h-3 w-3" /> : index + 1}</span>
                    <span className="lbl">{step.label}</span>
                  </button>
                ))}
              </div>

              <div className="space-y-4">
                {activeStep === "capital" ? (
                  <StockUniverseSelector
                    rows={universe ?? []}
                    selectedSymbols={config.portfolio.universe.basket}
                    activeSymbol={activeSymbol}
                    loading={universeLoading}
                    errorMessage={universeError instanceof Error ? universeError.message : null}
                    isStaticFallback={universeIsStaticFallback}
                    sectorFilter={config.portfolio.universe.sector_filter}
                    sortBy={config.portfolio.universe.sort_by}
                    sortDir={config.portfolio.universe.sort_dir}
                    title="Stock Universe"
                    description="Pick stocks, choose any technical indicators, then keep the default entry, exit, and risk rules or adjust them below."
                    onSectorFilterChange={(sector_filter) => updatePortfolioUniverse({ sector_filter })}
                    onSortChange={(patch) => updatePortfolioUniverse(patch)}
                    onSelectedChange={setBasketSymbolSelected}
                    onActiveSymbolChange={setActiveSymbol}
                    onClearSelection={clearBasket}
                  />
                ) : null}

                {activeStep === "signal" && currentStock && activeSymbol ? (
                  <Card>
                    <CardHeader>
                      <CardTitle>Indicators - {activeSymbol}</CardTitle>
                      <CardDescription>Enable the technical setups you want. Each active setup becomes a score available to the rules below.</CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      {signalPreview?.active_scores?.length ? (
                        <div className="flex flex-wrap gap-2">
                          {signalPreview.active_scores.map((score) => (
                            <div key={score.score_key} className="rounded-full border bg-background px-3 py-1.5 text-[11px]">
                              <span className="text-muted-foreground">{score.label}</span>
                              <span className="ml-2 font-medium">{score.score == null ? "--" : score.score.toFixed(1)}</span>
                              {score.signal_label ? <span className="ml-2 text-muted-foreground">{score.signal_label}</span> : null}
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {signalPreviewError instanceof Error ? (
                        <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                          Signal preview unavailable while the API is offline. Indicator selections are still saved in the draft.
                        </div>
                      ) : null}
                      <div className="grid gap-3 xl:grid-cols-2">
                        {INDICATOR_FAMILY_META.map((meta) => {
                          const familyId = meta.key as FamilyId
                          const family = currentStock.signal_construction.families[familyId]
                          const row = family?.rows[0] ?? defaultIndicatorRowConfig(familyId, 0)
                          const enabled = Boolean(family?.enabled)
                          return (
                            <div key={familyId} className={cn("rounded-lg border p-3", enabled && "border-primary/40 bg-primary/5")}>
                              <div className="flex items-start gap-3">
                                <Checkbox checked={enabled} onCheckedChange={(checked) => setSimpleIndicatorEnabled(familyId, Boolean(checked))} className="mt-1" />
                                <div className="min-w-0 flex-1">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <p className="text-sm font-semibold">{meta.shortLabel}</p>
                                    <Badge variant="outline">{meta.category}</Badge>
                                    {enabled ? <Badge>Active</Badge> : null}
                                  </div>
                                  <p className="mt-1 text-xs text-muted-foreground">{meta.description}</p>
                                  {enabled ? (
                                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                                      {meta.params.map((param) => {
                                        const rowKey = familyId === "sma" && param.key === "period" ? "window" : param.key
                                        const value = row.params[rowKey]?.value ?? meta.defaults[param.key] ?? 0
                                        return (
                                          <Label key={`${familyId}-${param.key}`} className="space-y-1 text-xs">
                                            <span>{param.label}</span>
                                            <Input
                                              type="number"
                                              min={param.min}
                                              max={param.max}
                                              step={param.step}
                                              value={value}
                                              onChange={(event) => setSimpleIndicatorParam(familyId, param.key, Number(event.target.value))}
                                              className="h-8"
                                            />
                                          </Label>
                                        )
                                      })}
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </CardContent>
                  </Card>
                ) : null}

                {activeStep === "entry" && currentStock && activeSymbol ? (
                  <SimpleIndicatorRuleCard
                    kind="entry"
                    horizon={horizon as HorizonKey}
                    stock={currentStock}
                    rules={currentStock.entry_rules}
                    preview={entryPreview}
                    errorMessage={entryPreviewError instanceof Error ? entryPreviewError.message : null}
                    onIndicatorChange={(familyId) => setSimpleRuleIndicator("entry", familyId)}
                    onParamChange={setSimpleIndicatorParam}
                    onConditionChange={(patch) => setSimpleRuleCondition("entry", patch)}
                  />
                ) : null}

                {activeStep === "exit" && currentStock && activeSymbol ? (
                  <SimpleIndicatorRuleCard
                    kind="exit"
                    horizon={horizon as HorizonKey}
                    stock={currentStock}
                    rules={currentStock.exit_rules}
                    preview={exitPreview}
                    errorMessage={exitPreviewError instanceof Error ? exitPreviewError.message : null}
                    onIndicatorChange={(familyId) => setSimpleRuleIndicator("exit", familyId)}
                    onParamChange={setSimpleIndicatorParam}
                    onConditionChange={(patch) => setSimpleRuleCondition("exit", patch)}
                  />
                ) : null}

                {activeStep === "risk" && currentStock && activeSymbol ? (
                  <RiskTab horizon={horizon as HorizonKey} risk={currentStock.risk} preview={riskPreview} errorMessage={riskPreviewError instanceof Error ? riskPreviewError.message : null} onChange={(next: RiskConfigV2) => updateStock(activeSymbol, (stock) => ({ ...stock, risk: next }))} />
                ) : null}

                {activeStep === "review" && currentStock && activeSymbol ? (
                  <ReviewTab symbol={activeSymbol} stockConfig={currentStock} review={reviewPreview} directCompatibilityMessage={backtestBlockedReason} />
                ) : null}

                {!currentStock && activeStep !== "capital" ? (
                  <Card>
                    <CardContent className="p-8 text-center text-sm text-muted-foreground">
                      Select at least one stock from Stock Universe to configure indicators and rules.
                    </CardContent>
                  </Card>
                ) : null}
              </div>

              <div className="mt-4 flex items-center justify-between gap-3">
                <Button type="button" variant="outline" onClick={() => goToStepOffset(-1)} disabled={activeStepIndex <= 0} className="gap-2">
                  <ChevronLeft className="h-4 w-4" />
                  Retour
                </Button>
                <div className="flex gap-2">
                  <Button type="button" variant="ghost" onClick={save} disabled={isSaving}>
                    Sauvegarder le brouillon
                  </Button>
                  <Button type="button" onClick={() => goToStepOffset(1)} disabled={activeStepIndex >= activeSteps.length - 1 || Boolean(nextStepBlockedReason)} title={nextStepBlockedReason ?? undefined} className="gap-2">
                    Continuer
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </>
          ) : null}

          {workflowMode === "advanced" ? (
            <>
          <div className="wizard">
            {activeSteps.map((step, index) => (
              <button
                key={step.id}
                type="button"
                className={cn("step", index < activeStepIndex && "done", step.id === activeStep && "active")}
                disabled={step.id !== "capital" && noBasketSelected}
                title={step.id !== "capital" && noBasketSelected ? "Select at least one stock first." : undefined}
                onClick={() => setActiveStep(step.id)}
              >
                <span className="num">{index < activeStepIndex ? <Check className="h-3 w-3" /> : index + 1}</span>
                <span className="lbl">{step.label}</span>
              </button>
            ))}
          </div>

          {activeStep === "capital" ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <CircleDollarSign className="h-4 w-4 text-muted-foreground" />
                    <CardTitle>Capital & Universe</CardTitle>
                  </div>
                  <CardDescription>Configure portfolio capital, HRP allocation, and the eligible stock universe.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="form-grid">
                    <div className="field">
                      <span className="lbl">Total capital (MAD)</span>
                      <Input type="text" inputMode="numeric" value={fmtMoney(config.portfolio.total_capital_mad)} onChange={(event) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, total_capital_mad: parseIntSafe(event.target.value) } })); markModified() }} />
                      <span className="hint">Capital deployed across selected titles.</span>
                    </div>
                    <div className="field">
                      <span className="lbl">HRP lookback</span>
                      <Input type="number" value={config.portfolio.allocation.hrp_lookback_bars} min={20} max={2000} step={5} onChange={(event) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, allocation: { ...prev.portfolio.allocation, hrp_lookback_bars: Number(event.target.value) } } })); markModified() }} />
                      <span className="hint">Historical bars used for allocation weights.</span>
                    </div>
                  </div>
                </CardContent>
              </Card>
              <StockUniverseSelector
                rows={universe ?? []}
                selectedSymbols={config.portfolio.universe.basket}
                activeSymbol={activeSymbol}
                loading={universeLoading}
                errorMessage={universeError instanceof Error ? universeError.message : null}
                isStaticFallback={universeIsStaticFallback}
                sectorFilter={config.portfolio.universe.sector_filter}
                sortBy={config.portfolio.universe.sort_by}
                sortDir={config.portfolio.universe.sort_dir}
                title="Stock Universe"
                description="Choose the stocks that belong in the strategy basket."
                onSectorFilterChange={(sector_filter) => updatePortfolioUniverse({ sector_filter })}
                onSortChange={(patch) => updatePortfolioUniverse(patch)}
                onSelectedChange={setBasketSymbolSelected}
                onActiveSymbolChange={setActiveSymbol}
                onClearSelection={clearBasket}
              />
            </div>
          ) : null}

          {activeStep === "type" ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle>Strategy Type</CardTitle>
                  <CardDescription>Choisissez l'archetype directionnel.</CardDescription>
                </CardHeader>
                <CardContent>
                  {currentStock && activeSymbol ? (
                    <div className="type-grid">
                      <button type="button" onClick={() => updateStock(activeSymbol, (stock) => applyStarterPresetToStock(stock, "trend_following", horizon))} className={cn("type-card", currentStock.strategy_type === "trend_following" && "selected")}>
                        <h4>Trend Following</h4>
                        <p>Favor sustained moves and confirmation. Buy strength, sell weakness; signals fire on breakouts and EMA crossovers.</p>
                        <div className="meta">EMA - Donchian - MACD - ADX</div>
                      </button>
                      <button type="button" onClick={() => updateStock(activeSymbol, (stock) => applyStarterPresetToStock(stock, "mean_reversion", horizon))} className={cn("type-card", currentStock.strategy_type === "mean_reversion" && "selected")}>
                        <h4>Mean Reversion</h4>
                        <p>Favor stretch and normalization. Fade extremes back to a moving anchor; signals fire on Z-score and RSI extremes.</p>
                        <div className="meta">RSI - Bollinger - Z-score - ATR</div>
                      </button>
                      <button type="button" className="type-card" disabled>
                        <h4>Pair / Spread</h4>
                        <p>Long one, short the cointegrated other. Reserved for long/short strategy templates.</p>
                        <div className="meta">Cointegration - OU half-life - spread</div>
                      </button>
                      <button type="button" className="type-card" disabled>
                        <h4>Multi-Factor Composite</h4>
                        <p>Blend trend, momentum, oscillation, and volume families into a composite decision layer.</p>
                        <div className="meta">HRP - z-blend - IC weighting</div>
                      </button>
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-line p-8 text-center text-sm text-muted-foreground">Select stocks in Stock Universe to configure a strategy type.</div>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <CardTitle>Per-stock setup - {activeSymbol ?? "No stock"}</CardTitle>
                      <CardDescription>{config.portfolio.universe.basket.length} selectionnes - parametres par defaut {currentStock?.strategy_type === "mean_reversion" ? "Mean Reversion" : "Trend"}</CardDescription>
                    </div>
                    <Button type="button" variant="outline" size="sm" onClick={applyToAll} disabled={!activeSymbol} className="gap-2">
                      <CopyPlus className="h-4 w-4" />
                      Apply To All
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {config.portfolio.universe.basket.length > 0 ? (
                    <div className="space-y-4">
                      <div className="flex flex-wrap gap-2">
                        {config.portfolio.universe.basket.map((symbol) => {
                          const row = rowBySymbol.get(symbol)
                          const review = reviewPreview?.stocks.find((item) => item.symbol === symbol)
                          return (
                            <button key={symbol} type="button" onClick={() => setActiveSymbol(symbol)} className={cn("claude-chip", symbol === activeSymbol && "active")}>
                              <span className="font-mono">{symbol}</span>
                              <span>{row?.source === "manual" ? "Manual" : "HRP"}</span>
                              <span>{review?.ready ? "Ready" : "Review"}</span>
                            </button>
                          )
                        })}
                      </div>
                      {currentStock && activeSymbol ? (
                        <div className="form-grid">
                          <div className="field">
                            <span className="lbl">Lookback (jours)</span>
                            <div className="slider-row">
                              <input type="range" min={20} max={2000} value={config.portfolio.allocation.hrp_lookback_bars} onChange={(event) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, allocation: { ...prev.portfolio.allocation, hrp_lookback_bars: Number(event.target.value) } } })); markModified() }} />
                              <span className="v">{config.portfolio.allocation.hrp_lookback_bars} j</span>
                            </div>
                            <span className="hint">Allocation HRP historical window.</span>
                          </div>
                          <div className="field">
                            <span className="lbl">Position sizing</span>
                            <Select value={config.portfolio.allocation.method} onValueChange={(value) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, allocation: { ...prev.portfolio.allocation, method: value as StrategyConfigV2["portfolio"]["allocation"]["method"] } } })); markModified() }}>
                              <SelectTrigger><SelectValue /></SelectTrigger>
                              <SelectContent>
                                <SelectItem value="hrp">HRP</SelectItem>
                              </SelectContent>
                            </Select>
                            <span className="hint">Manual overrides remain per stock.</span>
                          </div>
                          <div className="field">
                            <span className="lbl">Max position</span>
                            <div className="slider-row">
                              <input type="range" min={2} max={40} value={currentStock.risk.max_position_pct} onChange={(event) => updateStock(activeSymbol, (stock) => ({ ...stock, risk: { ...stock.risk, max_position_pct: Number(event.target.value) } }))} />
                              <span className="v">{currentStock.risk.max_position_pct}%</span>
                            </div>
                            <span className="hint">Cap concentration by title.</span>
                          </div>
                          <div className="field">
                            <span className="lbl">Cash buffer minimum</span>
                            <div className="slider-row">
                              <input type="range" min={0} max={100} value={Math.round(((allocationPreview?.remaining_capital_mad ?? 0) / Math.max(1, config.portfolio.total_capital_mad)) * 100)} readOnly />
                              <span className="v">{fmtPct(((allocationPreview?.remaining_capital_mad ?? 0) / Math.max(1, config.portfolio.total_capital_mad)) * 100, 0)}</span>
                            </div>
                            <span className="hint">Derived from allocated vs total capital.</span>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-line p-8 text-center text-sm text-muted-foreground">Select stocks in the universe to open rules-based strategy tabs.</div>
                  )}
                </CardContent>
              </Card>
            </div>
          ) : null}

          {activeStep === "signal" && currentStock && activeSymbol ? (
            <SignalConstructionTab horizon={horizon as HorizonKey} onHorizonChange={(value) => { setHorizon(value); setConfig((prev) => ensureBasketStocks(prev, value)); markModified() }} stockConfig={currentStock} activeScores={signalPreview?.active_scores} zoneChart={signalPreview?.zone_chart} isLoading={signalPreviewLoading} isRefreshing={signalPreviewPending || (signalPreviewValidating && Boolean(signalPreview))} previewRenderKey={signalPreviewRenderKey} errorMessage={signalPreviewError instanceof Error ? signalPreviewError.message : null} familyHistoryMode={familyHistoryMode} onFamilyHistoryModeChange={setFamilyHistoryMode} onChange={(next) => updateStock(activeSymbol, (stock) => ({ ...stock, signal_construction: next }))} />
          ) : null}

          {activeStep === "entry" && currentStock && activeSymbol ? (
            <EntryRulesTab horizon={horizon as HorizonKey} rules={currentStock.entry_rules} scoreOptions={currentScoreOptions} preview={entryPreview} errorMessage={entryPreviewError instanceof Error ? entryPreviewError.message : null} onChange={(next) => updateStock(activeSymbol, (stock) => ({ ...stock, entry_rules: next }))} />
          ) : null}

          {activeStep === "exit" && currentStock && activeSymbol ? (
            <ExitRulesTab horizon={horizon as HorizonKey} rules={currentStock.exit_rules} scoreOptions={currentScoreOptions} preview={exitPreview} errorMessage={exitPreviewError instanceof Error ? exitPreviewError.message : null} onChange={(next) => updateStock(activeSymbol, (stock) => ({ ...stock, exit_rules: next }))} />
          ) : null}

          {activeStep === "risk" && currentStock && activeSymbol ? (
            <div className="space-y-4">
              <AllocationCard symbol={activeSymbol} totalCapital={config.portfolio.total_capital_mad} row={currentAllocationRow} override={currentOverride} onChange={(next) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, allocation: { ...prev.portfolio.allocation, manual_overrides_by_symbol: { ...prev.portfolio.allocation.manual_overrides_by_symbol, [activeSymbol]: next } } } })); markModified() }} />
              <RiskTab horizon={horizon as HorizonKey} risk={currentStock.risk} preview={riskPreview} errorMessage={riskPreviewError instanceof Error ? riskPreviewError.message : null} onChange={(next: RiskConfigV2) => updateStock(activeSymbol, (stock) => ({ ...stock, risk: next }))} />
            </div>
          ) : null}

          {activeStep === "review" && currentStock && activeSymbol ? (
            <ReviewTab symbol={activeSymbol} stockConfig={currentStock} review={reviewPreview} directCompatibilityMessage={backtestBlockedReason} />
          ) : null}

          {!currentStock && activeStep !== "capital" ? (
            <Card>
              <CardContent className="space-y-3 p-8 text-center text-sm text-muted-foreground">
                <p>Select at least one stock from Stock Universe to continue.</p>
                <Button type="button" variant="outline" size="sm" onClick={() => setActiveStep("capital")}>Open universe</Button>
              </CardContent>
            </Card>
          ) : null}

          <div className="mt-4 flex items-center justify-between gap-3">
            <Button type="button" variant="outline" onClick={() => goToStepOffset(-1)} disabled={activeStepIndex <= 0} className="gap-2">
              <ChevronLeft className="h-4 w-4" />
              Retour
            </Button>
            <div className="flex gap-2">
              <Button type="button" variant="ghost" onClick={save} disabled={isSaving}>
                Sauvegarder le brouillon
              </Button>
              <Button type="button" onClick={() => goToStepOffset(1)} disabled={activeStepIndex >= activeSteps.length - 1 || Boolean(nextStepBlockedReason)} title={nextStepBlockedReason ?? undefined} className="gap-2">
                Continuer
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  )

}

export default function StrategyPage() {
  return <Suspense fallback={<div className="space-y-4"><Skeleton className="h-32 rounded-xl" /><Skeleton className="h-80 rounded-xl" /></div>}><StrategyPageContent /></Suspense>
}
