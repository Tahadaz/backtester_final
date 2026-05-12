"use client"

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { Activity, Archive, BookOpen, Check, ChevronLeft, ChevronRight, CircleDollarSign, CopyPlus, Eye, Gauge, Globe, ListChecks, Plus, Save, ShieldCheck, Star, TrendingUp } from "lucide-react"
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
  useSignalCandidates,
  useUniverse,
} from "@/hooks/use-api"
import { archiveStrategy, createStrategy, duplicateStrategy, updateStrategy, type SignalCandidate, type StrategyAllocationRow, type UniverseStock } from "@/lib/api"
import { applyStarterPresetToStock, buildEdgeCandidateStockStrategyConfig, cloneStockStrategyConfig, defaultIndicatorRowConfig, defaultStrategyConfigV2, ensureBasketStocks, manualParam, migrateStrategyConfigV2, normalizeSignalCandidateRef, scoreVariableOptions, type FamilyId, type HorizonKey, type RiskConfigV2, type SignalCandidateRef, type SortBy, type SortDir, type StrategyConfigV2 } from "@/lib/strategy-v2"
import { cn } from "@/lib/utils"

const fmtMoney = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "-" : v.toLocaleString("fr-FR", { maximumFractionDigits: 0 }))
const fmtPct = (v: number | null | undefined, d = 1) => (v == null || Number.isNaN(v) ? "-" : `${v.toFixed(d)}%`)
const fmtDecimalPct = (v: number | null | undefined, d = 2) => (v == null || Number.isNaN(v) ? "-" : `${(v * 100).toFixed(d)}%`)
const parseIntSafe = (v: string) => { const n = Number(String(v).replace(/\s/g, "").replace(/,/g, "")); return Number.isFinite(n) ? n : 0 }
const LOCAL_STRATEGY_DRAFT_KEY = "strategy.simple.localDraft.v1"
type StrategyStep = "capital" | "type" | "signal" | "entry" | "exit" | "risk" | "review"
type WorkflowMode = "simple" | "advanced"
const STRATEGY_STEPS: Array<{ id: StrategyStep; label: string }> = [
  { id: "capital", label: "Signal Universe" },
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

function normalizeSectorValue(value: string | null | undefined): string {
  return (value ?? "").normalize("NFC").trim().toLocaleLowerCase("fr-FR")
}

function candidateTone(candidate: Pick<SignalCandidate, "triage" | "direction"> | SignalCandidateRef): "default" | "destructive" | "secondary" {
  if (String(candidate.triage ?? "").toLowerCase() === "proven") return "default"
  if (String(candidate.direction ?? "").toLowerCase() === "short") return "destructive"
  return "secondary"
}

function candidateRefFromRow(candidate: SignalCandidate): SignalCandidateRef {
  return normalizeSignalCandidateRef(candidate) ?? {
    candidate_id: candidate.candidate_id,
    symbol: candidate.symbol.toUpperCase(),
    source: candidate.source,
    variant: candidate.variant,
    label: candidate.label,
  }
}

function candidateMethodText(candidate: Pick<SignalCandidate, "source" | "variant" | "label"> | SignalCandidateRef) {
  return candidate.label || `${candidate.source} / ${candidate.variant}`
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
  const [candidateMode, setCandidateMode] = useState<"best" | "all">("best")
  const searchStrategyId = searchParams.get("strategyId")

  const { data: strategies, isLoading: strategiesLoading, mutate: mutateStrategies } = useStrategies()
  const { data: loadedStrategy } = useStrategy(activeId)
  const { data: universe, isLoading: universeLoading, error: universeError } = useUniverse(horizon, { min_abs_signal: config.portfolio.universe.min_abs_signal, min_adv20: config.portfolio.universe.min_adv20, sort_by: config.portfolio.universe.sort_by, sort_dir: config.portfolio.universe.sort_dir })
  const { data: signalCandidates, isLoading: signalCandidatesLoading, error: signalCandidatesError } = useSignalCandidates(horizon, { mode: candidateMode, min_bars: 252, min_adv20: config.portfolio.universe.min_adv20, sector_filter: config.portfolio.universe.sector_filter, triage_filter: ["proven", "watch"], sort_by: "edge_score", sort_dir: "desc" })
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
  const selectedSignalCandidates = config.portfolio.universe.selected_signal_candidates ?? []
  const selectedSignalIds = useMemo(() => new Set(selectedSignalCandidates.map((item) => item.candidate_id)), [selectedSignalCandidates])
  const selectedSignalBySymbol = useMemo(() => {
    const out = new Map<string, SignalCandidateRef[]>()
    for (const candidate of selectedSignalCandidates) {
      const symbol = candidate.symbol.toUpperCase()
      out.set(symbol, [...(out.get(symbol) ?? []), candidate])
    }
    return out
  }, [selectedSignalCandidates])
  const sectors = useMemo(() => Array.from(new Set((universe ?? []).map((row) => row.sector?.trim()).filter(Boolean) as string[])).sort((a, b) => a.localeCompare(b, "fr")), [universe])
  const selectedSectorKeys = useMemo(
    () => config.portfolio.universe.sector_filter.map(normalizeSectorValue).filter(Boolean),
    [config.portfolio.universe.sector_filter],
  )
  const visibleUniverse = useMemo(() => {
    const rows = universe ?? []
    if (selectedSectorKeys.length === 0) return rows
    const selected = new Set(selectedSectorKeys)
    const filtered = rows.filter((stock) => selected.has(normalizeSectorValue(stock.sector)))
    return filtered.length > 0 ? filtered : rows
  }, [selectedSectorKeys, universe])
  const sectorFilterHasNoMatches = Boolean(
    (universe?.length ?? 0) > 0
    && selectedSectorKeys.length > 0
    && !(universe ?? []).some((stock) => selectedSectorKeys.includes(normalizeSectorValue(stock.sector))),
  )
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

  const markModified = useCallback(() => setStatus((prev) => prev === "saved" ? "modified" : prev), [])
  const updatePortfolioUniverse = useCallback((patch: Partial<StrategyConfigV2["portfolio"]["universe"]>) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, universe: { ...prev.portfolio.universe, ...patch } } })); markModified() }, [markModified])
  const updateStock = useCallback((symbol: string, updater: (stock: StrategyConfigV2["stocks"][string]) => StrategyConfigV2["stocks"][string]) => { setConfig((prev) => ({ ...prev, stocks: { ...prev.stocks, [symbol]: updater(cloneStockStrategyConfig(prev.stocks[symbol], horizon)) } })); markModified() }, [horizon, markModified])

  const toggleBasketSymbol = useCallback((symbol: string) => { setConfig((prev) => ensureBasketStocks({ ...prev, portfolio: { ...prev.portfolio, universe: { ...prev.portfolio.universe, basket: prev.portfolio.universe.basket.includes(symbol) ? prev.portfolio.universe.basket.filter((item) => item !== symbol) : [...prev.portfolio.universe.basket, symbol] } } }, horizon)); setActiveSymbol((prev) => prev ?? symbol); markModified() }, [horizon, markModified])
  const toggleSignalCandidate = useCallback((candidate: SignalCandidate) => {
    const ref = candidateRefFromRow(candidate)
    setConfig((prev) => {
      const currentRefs = prev.portfolio.universe.selected_signal_candidates ?? []
      const exists = currentRefs.some((item) => item.candidate_id === ref.candidate_id)
      const nextRefs = exists
        ? currentRefs.filter((item) => item.candidate_id !== ref.candidate_id)
        : [...currentRefs.filter((item) => item.symbol.toUpperCase() !== ref.symbol), ref]
      const basket = prev.portfolio.universe.basket.includes(ref.symbol)
        ? prev.portfolio.universe.basket
        : [...prev.portfolio.universe.basket, ref.symbol]
      const nextStocks = { ...prev.stocks }
      if (!exists) {
        nextStocks[ref.symbol] = buildEdgeCandidateStockStrategyConfig(horizon, ref, prev.stocks[ref.symbol])
      } else if (nextStocks[ref.symbol]?.signal_construction.selected_signal_candidate?.candidate_id === ref.candidate_id) {
        nextStocks[ref.symbol] = {
          ...nextStocks[ref.symbol],
          signal_construction: {
            ...nextStocks[ref.symbol].signal_construction,
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
            selection_mode: nextRefs.length > 0 ? "edge_candidates" : "manual",
            selected_signal_candidates: nextRefs,
            min_abs_signal: 0,
          },
        },
        stocks: nextStocks,
      }, horizon)
    })
    setActiveSymbol(ref.symbol)
    markModified()
  }, [horizon, markModified])
  const removeSignalCandidate = useCallback((candidateId: string) => {
    setConfig((prev) => {
      const currentRefs = prev.portfolio.universe.selected_signal_candidates ?? []
      const removed = currentRefs.find((item) => item.candidate_id === candidateId)
      const nextRefs = currentRefs.filter((item) => item.candidate_id !== candidateId)
      const nextStocks = { ...prev.stocks }
      if (removed && nextStocks[removed.symbol]?.signal_construction.selected_signal_candidate?.candidate_id === candidateId) {
        nextStocks[removed.symbol] = {
          ...nextStocks[removed.symbol],
          signal_construction: {
            ...nextStocks[removed.symbol].signal_construction,
            source_mode: "manual",
            selected_signal_candidate: null,
          },
        }
      }
      return {
        ...prev,
        portfolio: {
          ...prev.portfolio,
          universe: {
            ...prev.portfolio.universe,
            selection_mode: nextRefs.length > 0 ? "edge_candidates" : "manual",
            selected_signal_candidates: nextRefs,
          },
        },
        stocks: nextStocks,
      }
    })
    markModified()
  }, [markModified])
  const toggleSector = useCallback((sector: string) => updatePortfolioUniverse({ sector_filter: config.portfolio.universe.sector_filter.includes(sector) ? config.portfolio.universe.sector_filter.filter((item) => item !== sector) : [...config.portfolio.universe.sector_filter, sector] }), [config.portfolio.universe.sector_filter, updatePortfolioUniverse])
  const applyToAll = useCallback(() => { if (!activeSymbol || !stockConfig) return; setConfig((prev) => ({ ...prev, stocks: Object.fromEntries(prev.portfolio.universe.basket.map((symbol) => { const current = cloneStockStrategyConfig(prev.stocks[symbol], horizon); const source = cloneStockStrategyConfig(stockConfig, horizon); source.risk.max_position_pct = current.risk.max_position_pct; source.risk.max_sector_pct = current.risk.max_sector_pct; return [symbol, source] })) })); markModified() }, [activeSymbol, horizon, markModified, stockConfig])
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
  const activeStepIndex = STRATEGY_STEPS.findIndex((step) => step.id === activeStep)
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
    const next = STRATEGY_STEPS[activeStepIndex + offset]
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
          <div className="lbl">Edge signals</div>
          <div className="val">{selectedSignalCandidates.length}</div>
          <div className="sub">{config.portfolio.universe.selection_mode === "edge_candidates" ? "proof-driven" : "manual universe"}</div>
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
            <div className="ch"><h4>Universe</h4></div>
            <ul>
              <li className="active">
                <span>MASI - {universe?.length ?? 0} titres</span>
              </li>
              <li>
                <span>Basket - {config.portfolio.universe.basket.length}</span>
              </li>
              <li>
                <span>{config.portfolio.universe.sector_filter.length || "Tous"} secteurs</span>
              </li>
            </ul>
          </div>

          <div className="savd">
            <div className="ch"><h4>Edge Basket</h4></div>
            <ul>
              {selectedSignalCandidates.length === 0 ? (
                <li><span>No edge signals selected</span></li>
              ) : selectedSignalCandidates.slice(0, 8).map((candidate) => (
                <li key={candidate.candidate_id} className={cn(candidate.symbol === activeSymbol && "active")} onClick={() => setActiveSymbol(candidate.symbol)}>
                  <span className="min-w-0 truncate font-mono">{candidate.symbol}</span>
                  <span className="ts">{candidate.triage === "proven" ? "proven" : "watch"}</span>
                </li>
              ))}
            </ul>
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
                  <SelectItem value="short">Short</SelectItem>
                  <SelectItem value="medium">Medium</SelectItem>
                  <SelectItem value="long">Long</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {workflowMode === "simple" ? (
            <div className="space-y-4">
              {universeIsStaticFallback ? (
                <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  API offline: using bundled sample universe data. Saving stores a local draft until the API is available again.
                </div>
              ) : null}
              {universeError instanceof Error ? (
                <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  Universe API unavailable. Start the local API, or keep working from bundled sample data when fallback is available.
                </div>
              ) : null}

              <Card>
                <CardHeader>
                  <CardTitle>Simple Strategy</CardTitle>
                  <CardDescription>Pick stocks, choose any technical indicators, then keep the default entry, exit, and risk rules or adjust them below.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <SummaryStat label="Universe" value={universeLoading ? "..." : visibleUniverse.length} sub={universeIsStaticFallback ? "static sample" : "API"} />
                    <SummaryStat label="Basket" value={config.portfolio.universe.basket.length} sub="selected stocks" primary={config.portfolio.universe.basket.length > 0} />
                    <SummaryStat label="Active stock" value={activeSymbol ?? "-"} sub={currentStock ? `${Object.values(currentStock.signal_construction.families).filter((family) => family.enabled).length} indicators` : "select a stock"} />
                  </div>

                  <div className="overflow-x-auto rounded-md border border-line">
                    <table className="claude-table min-w-[720px]">
                      <thead>
                        <tr><th className="w-8" /><th>Ticker</th><th>Sector</th><th className="r">ADV20 MAD</th><th className="r">Signal</th><th className="r">Action</th></tr>
                      </thead>
                      <tbody>
                        {universeLoading ? Array.from({ length: 6 }).map((_, index) => (
                          <tr key={index}><td colSpan={6} className="px-3 py-2"><Skeleton className="h-8 w-full" /></td></tr>
                        )) : visibleUniverse.length === 0 ? (
                          <tr><td colSpan={6} className="px-3 py-8 text-center text-sm text-muted-foreground">No stocks returned by the universe source.</td></tr>
                        ) : visibleUniverse.slice(0, 20).map((stock: UniverseStock) => {
                          const selected = config.portfolio.universe.basket.includes(stock.symbol)
                          return (
                            <tr key={stock.symbol} className={cn("cursor-pointer", selected && "bg-primary/5", !stock.eligible && "opacity-70")} title={stock.exclusion_reason ?? undefined} onClick={() => toggleBasketSymbol(stock.symbol)}>
                              <td><Checkbox checked={selected} onClick={(event) => event.stopPropagation()} onCheckedChange={() => toggleBasketSymbol(stock.symbol)} /></td>
                              <td className="font-mono font-medium">{stock.symbol}</td>
                              <td className="text-muted-foreground">{stock.sector ?? "-"}</td>
                              <td className="r font-mono">{stock.adv20 != null ? fmtMoney(stock.adv20) : "-"}</td>
                              <td className="r font-mono">{stock.signal_score != null ? stock.signal_score.toFixed(1) : "-"}</td>
                              <td className="r"><Badge variant={selected ? "default" : "outline"}>{selected ? "Selected" : "Use"}</Badge></td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>

                  {config.portfolio.universe.basket.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {config.portfolio.universe.basket.map((symbol) => (
                        <button key={symbol} type="button" onClick={() => setActiveSymbol(symbol)} className={cn("claude-chip", symbol === activeSymbol && "active")}>
                          <span className="font-mono">{symbol}</span>
                          <span>{symbol === activeSymbol ? "Editing" : "Open"}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </CardContent>
              </Card>

              {currentStock && activeSymbol ? (
                <>
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

                  <EntryRulesTab horizon={horizon as HorizonKey} rules={currentStock.entry_rules} scoreOptions={currentScoreOptions} preview={entryPreview} errorMessage={entryPreviewError instanceof Error ? entryPreviewError.message : null} onChange={(next) => updateStock(activeSymbol, (stock) => ({ ...stock, entry_rules: next }))} />
                  <ExitRulesTab horizon={horizon as HorizonKey} rules={currentStock.exit_rules} scoreOptions={currentScoreOptions} preview={exitPreview} errorMessage={exitPreviewError instanceof Error ? exitPreviewError.message : null} onChange={(next) => updateStock(activeSymbol, (stock) => ({ ...stock, exit_rules: next }))} />
                  <RiskTab horizon={horizon as HorizonKey} risk={currentStock.risk} preview={riskPreview} errorMessage={riskPreviewError instanceof Error ? riskPreviewError.message : null} onChange={(next: RiskConfigV2) => updateStock(activeSymbol, (stock) => ({ ...stock, risk: next }))} />
                  <ReviewTab symbol={activeSymbol} stockConfig={currentStock} review={reviewPreview} directCompatibilityMessage={backtestBlockedReason} />
                </>
              ) : (
                <Card>
                  <CardContent className="p-8 text-center text-sm text-muted-foreground">
                    Select at least one stock above to configure indicators and rules.
                  </CardContent>
                </Card>
              )}
            </div>
          ) : null}

          {workflowMode === "advanced" ? (
            <>
          <div className="wizard">
            {STRATEGY_STEPS.map((step, index) => (
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
                    <CardTitle>Capital & Univers</CardTitle>
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
                    <div className="field">
                      <span className="lbl">Manual score gate</span>
                      <Input type="number" value={config.portfolio.universe.min_abs_signal} onChange={(event) => updatePortfolioUniverse({ min_abs_signal: Number(event.target.value) })} />
                      <span className="hint">Optional raw-score filter; edge candidates do not need it.</span>
                    </div>
                    <div className="field">
                      <span className="lbl">Min ADV20 MAD</span>
                      <Input type="number" value={config.portfolio.universe.min_adv20} onChange={(event) => updatePortfolioUniverse({ min_adv20: Number(event.target.value) })} />
                      <span className="hint">Liquidity gate for tradable names.</span>
                    </div>
                    <div className="field">
                      <span className="lbl">Sort by</span>
                      <Select value={config.portfolio.universe.sort_by} onValueChange={(value: SortBy) => updatePortfolioUniverse({ sort_by: value })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="adv20">ADV20 MAD</SelectItem>
                          <SelectItem value="signal_score">Signal strength</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="field">
                      <span className="lbl">Direction</span>
                      <Select value={config.portfolio.universe.sort_dir} onValueChange={(value: SortDir) => updatePortfolioUniverse({ sort_dir: value })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="desc">Descending</SelectItem>
                          <SelectItem value="asc">Ascending</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  {sectors.length > 0 ? (
                    <div className="field">
                      <span className="lbl">Sector filter</span>
                      <div className="flex flex-wrap gap-2">
                        {sectors.map((sector) => (
                          <button key={sector} type="button" onClick={() => toggleSector(sector)} className={cn("claude-chip", config.portfolio.universe.sector_filter.includes(sector) && "active")}>
                            {sector}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <Star className="h-4 w-4 text-muted-foreground" />
                        <CardTitle>Signal Universe</CardTitle>
                      </div>
                      <CardDescription>Select dashboard signals that already have proven or watchlist edge. A selected signal creates the stock setup automatically.</CardDescription>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button type="button" variant={candidateMode === "best" ? "default" : "outline"} size="sm" onClick={() => setCandidateMode("best")} className="gap-2">
                        <ShieldCheck className="h-4 w-4" />
                        Best per stock
                      </Button>
                      <Button type="button" variant={candidateMode === "all" ? "default" : "outline"} size="sm" onClick={() => setCandidateMode("all")} className="gap-2">
                        <ListChecks className="h-4 w-4" />
                        All candidates
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid gap-3 md:grid-cols-3">
                    <SummaryStat label="Qualified rows" value={signalCandidates?.length ?? (signalCandidatesLoading ? "..." : 0)} sub="proven + watch" />
                    <SummaryStat label="Selected edge signals" value={selectedSignalCandidates.length} sub="stored with proof metrics" primary={selectedSignalCandidates.length > 0} />
                    <SummaryStat label="Threshold gate" value={config.portfolio.universe.min_abs_signal === 0 ? "Off" : `+${config.portfolio.universe.min_abs_signal}`} sub="edge proof drives selection" />
                  </div>

                  {selectedSignalCandidates.length > 0 ? (
                    <div className="rounded-md border border-line bg-bg2 p-3">
                      <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        <Activity className="h-3.5 w-3.5" />
                        Selected signals
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {selectedSignalCandidates.map((candidate) => (
                          <button key={candidate.candidate_id} type="button" onClick={() => setActiveSymbol(candidate.symbol)} className={cn("claude-chip", candidate.symbol === activeSymbol && "active")}>
                            <span className="font-mono">{candidate.symbol}</span>
                            <span>{candidate.triage === "proven" ? "Proven" : "Watch"}</span>
                            <span>{candidate.direction ?? "-"}</span>
                            <span onClick={(event) => { event.stopPropagation(); removeSignalCandidate(candidate.candidate_id) }} className="pl-1 text-muted-foreground hover:text-foreground">x</span>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {signalCandidatesError instanceof Error ? (
                    <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                      Signal candidates unavailable: {signalCandidatesError.message}
                    </div>
                  ) : null}

                  <div className="overflow-x-auto rounded-md border border-line">
                    <table className="claude-table min-w-[980px]">
                      <thead>
                        <tr>
                          <th className="w-8" />
                          <th>Ticker</th>
                          <th>Method</th>
                          <th>Triage</th>
                          <th>Signal</th>
                          <th className="r">Edge score</th>
                          <th className="r">Net ER</th>
                          <th className="r">Hit rate</th>
                          <th className="r">Proof</th>
                          <th className="r">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {signalCandidatesLoading ? Array.from({ length: 8 }).map((_, index) => (
                          <tr key={index}><td colSpan={10} className="px-3 py-2"><Skeleton className="h-8 w-full" /></td></tr>
                        )) : (signalCandidates ?? []).length === 0 ? (
                          <tr>
                            <td colSpan={10} className="px-3 py-8 text-center text-sm text-muted-foreground">
                              No edge-qualified candidates returned for this horizon and filter set.
                            </td>
                          </tr>
                        ) : (signalCandidates ?? []).map((candidate) => {
                          const selected = selectedSignalIds.has(candidate.candidate_id)
                          return (
                            <tr
                              key={candidate.candidate_id}
                              className={cn(candidate.eligible && "cursor-pointer", selected && "bg-primary/5", !candidate.eligible && "opacity-60")}
                              title={candidate.exclusion_reason ?? undefined}
                              onClick={() => candidate.eligible && toggleSignalCandidate(candidate)}
                            >
                              <td>
                                <Checkbox checked={selected} disabled={!candidate.eligible} onClick={(event) => event.stopPropagation()} onCheckedChange={() => candidate.eligible && toggleSignalCandidate(candidate)} />
                              </td>
                              <td>
                                <div className="font-mono font-medium">{candidate.symbol}</div>
                                <div className="text-xs text-muted-foreground">{candidate.sector ?? "-"}</div>
                              </td>
                              <td>
                                <div className="max-w-[280px] truncate font-medium">{candidateMethodText(candidate)}</div>
                                <div className="text-xs text-muted-foreground">{candidate.source} / {candidate.variant}</div>
                              </td>
                              <td><Badge variant={candidateTone(candidate)}>{candidate.triage === "proven" ? "Proven" : "Watch"}</Badge></td>
                              <td>
                                <div className="flex items-center gap-2">
                                  <TrendingUp className={cn("h-4 w-4", candidate.direction === "short" ? "text-red-600" : "text-emerald-600")} />
                                  <span>{candidate.signal_label ?? candidate.bucket ?? "-"}</span>
                                </div>
                              </td>
                              <td className="r font-mono">{candidate.score != null ? candidate.score.toFixed(4) : "-"}</td>
                              <td className="r font-mono">{fmtDecimalPct(candidate.action_expected_return_net, 2)}</td>
                              <td className="r font-mono">{fmtDecimalPct(candidate.hit_rate, 1)}</td>
                              <td className="r">
                                <div className="font-mono">{candidate.proof_n ?? candidate.n ?? "-"}</div>
                                <div className="text-xs text-muted-foreground">{candidate.proof_window_start ?? candidate.data_as_of ?? "-"}</div>
                              </td>
                              <td className="r">
                                <Button type="button" variant={selected ? "default" : "outline"} size="sm" disabled={!candidate.eligible} onClick={(event) => { event.stopPropagation(); toggleSignalCandidate(candidate) }}>
                                  {selected ? "Selected" : "Use"}
                                </Button>
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <Globe className="h-4 w-4 text-muted-foreground" />
                    <CardTitle>Advanced Manual Universe</CardTitle>
                  </div>
                  <CardDescription>Use this when you want a raw stock basket instead of importing edge-qualified dashboard signals.</CardDescription>
                </CardHeader>
                <CardContent>
                  {universeError instanceof Error ? (
                    <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                      Universe API unavailable. Start the local API to load live strategy data.
                    </div>
                  ) : null}
                  {sectorFilterHasNoMatches ? (
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                      <span>No stocks match the saved sector filter. Showing the full universe.</span>
                      <Button type="button" variant="outline" size="sm" onClick={() => updatePortfolioUniverse({ sector_filter: [] })}>
                        Clear sector filter
                      </Button>
                    </div>
                  ) : null}
                  <div className="overflow-x-auto rounded-md border border-line">
                    <table className="claude-table min-w-[680px]">
                      <thead>
                        <tr><th className="w-8" /><th>Ticker</th><th>Sector</th><th className="r">ADV20 MAD</th><th className="r">Signal</th><th className="r">Status</th></tr>
                      </thead>
                      <tbody>
                        {universeLoading ? Array.from({ length: 8 }).map((_, index) => (
                          <tr key={index}><td colSpan={6} className="px-3 py-2"><Skeleton className="h-8 w-full" /></td></tr>
                        )) : visibleUniverse.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="px-3 py-8 text-center text-sm text-muted-foreground">
                              No stocks returned by the universe API.
                            </td>
                          </tr>
                        ) : visibleUniverse.map((stock) => (
                            <tr key={stock.symbol} className={cn("cursor-pointer", config.portfolio.universe.basket.includes(stock.symbol) && "bg-primary/5")} onClick={() => toggleBasketSymbol(stock.symbol)}>
                              <td><Checkbox checked={config.portfolio.universe.basket.includes(stock.symbol)} onClick={(event) => event.stopPropagation()} onCheckedChange={() => toggleBasketSymbol(stock.symbol)} /></td>
                              <td className="font-mono font-medium">{stock.symbol}</td>
                              <td className="text-muted-foreground">{stock.sector ?? "-"}</td>
                              <td className="r font-mono">{stock.adv20 != null ? fmtMoney(stock.adv20) : "-"}</td>
                              <td className="r font-mono">{stock.signal_score != null ? stock.signal_score.toFixed(1) : "-"}</td>
                              <td className="r"><Badge variant={stock.eligible ? "outline" : "secondary"}>{stock.eligible ? "Eligible" : "Filtered"}</Badge></td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
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
                    <div className="rounded-lg border border-dashed border-line p-8 text-center text-sm text-muted-foreground">Select stocks in Capital & Univers to configure a strategy type.</div>
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
                          const edgeCount = selectedSignalBySymbol.get(symbol)?.length ?? 0
                          return (
                            <button key={symbol} type="button" onClick={() => setActiveSymbol(symbol)} className={cn("claude-chip", symbol === activeSymbol && "active")}>
                              <span className="font-mono">{symbol}</span>
                              {edgeCount > 0 ? <span>Edge</span> : null}
                              <span>{row?.source === "manual" ? "Manual" : "HRP"}</span>
                              <span>{review?.ready ? "Ready" : "Review"}</span>
                            </button>
                          )
                        })}
                      </div>
                      {currentStock && activeSymbol ? (
                        <div className="form-grid">
                          <div className="field">
                            <span className="lbl">Sector filter</span>
                            <div className="flex flex-wrap gap-2">
                              {sectors.slice(0, 8).map((sector) => (
                                <button key={sector} type="button" onClick={() => toggleSector(sector)} className={cn("claude-chip", config.portfolio.universe.sector_filter.includes(sector) && "active")}>{sector}</button>
                              ))}
                            </div>
                            <span className="hint">{config.portfolio.universe.sector_filter.length || "Tous"} secteurs actifs</span>
                          </div>
                          <div className="field">
                            <span className="lbl">Lookback (jours)</span>
                            <div className="slider-row">
                              <input type="range" min={20} max={2000} value={config.portfolio.allocation.hrp_lookback_bars} onChange={(event) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, allocation: { ...prev.portfolio.allocation, hrp_lookback_bars: Number(event.target.value) } } })); markModified() }} />
                              <span className="v">{config.portfolio.allocation.hrp_lookback_bars} j</span>
                            </div>
                            <span className="hint">Allocation HRP historical window.</span>
                          </div>
                          <div className="field">
                            <span className="lbl">Advanced score gate</span>
                            <div className="slider-row">
                              <input type="range" min={0} max={100} value={config.portfolio.universe.min_abs_signal} onChange={(event) => updatePortfolioUniverse({ min_abs_signal: Number(event.target.value) })} />
                              <span className="v">+{config.portfolio.universe.min_abs_signal}</span>
                            </div>
                            <span className="hint">Only affects manual raw-universe selection.</span>
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
                <p>Select at least one stock from Capital & Univers to continue.</p>
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
              <Button type="button" onClick={() => goToStepOffset(1)} disabled={activeStepIndex >= STRATEGY_STEPS.length - 1 || Boolean(nextStepBlockedReason)} title={nextStepBlockedReason ?? undefined} className="gap-2">
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
