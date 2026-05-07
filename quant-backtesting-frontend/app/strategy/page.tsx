"use client"

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "next/navigation"
import { ArrowRightLeft, ChartColumnIncreasing, CircleDollarSign, CopyPlus, Globe } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CoreStrategyHeader } from "@/components/strategy/core-strategy-header"
import { EntryRulesTab } from "@/components/strategy/entry-rules-tab"
import { ExitRulesTab } from "@/components/strategy/exit-rules-tab"
import { ReviewTab } from "@/components/strategy/review-tab"
import { RiskTab } from "@/components/strategy/risk-tab"
import { SignalConstructionTab } from "@/components/strategy/signal-construction-tab"
import { RetractableSavedSidebar } from "@/components/layout/retractable-saved-sidebar"
import { StrategyRail } from "@/components/strategy-plan/strategy-rail"
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
import { cloneStockStrategyConfig, defaultStrategyConfigV2, ensureBasketStocks, migrateStrategyConfigV2, scoreVariableOptions, type HorizonKey, type RiskConfigV2, type SortBy, type SortDir, type StrategyConfigV2 } from "@/lib/strategy-v2"
import { cn } from "@/lib/utils"

const fmtMoney = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "-" : v.toLocaleString("fr-FR", { maximumFractionDigits: 0 }))
const fmtPct = (v: number | null | undefined, d = 1) => (v == null || Number.isNaN(v) ? "-" : `${v.toFixed(d)}%`)
const parseIntSafe = (v: string) => { const n = Number(String(v).replace(/\s/g, "").replace(/,/g, "")); return Number.isFinite(n) ? n : 0 }

function manualOverridesForApi(config: StrategyConfigV2) {
  const out: Record<string, number> = {}
  for (const symbol of config.portfolio.universe.basket) {
    const value = config.portfolio.allocation.manual_overrides_by_symbol[symbol]
    if (value?.enabled && value.capital_mad > 0) out[symbol] = value.capital_mad
  }
  return out
}

function hasWfoValues(value: unknown): boolean {
  if (!value || typeof value !== "object") return false
  if (Array.isArray(value)) return value.some(hasWfoValues)
  const record = value as Record<string, unknown>
  if (String(record.mode ?? "").toLowerCase() === "wfo") return true
  return Object.values(record).some(hasWfoValues)
}

function directCompatibility(config: StrategyConfigV2): string | null {
  const basket = config.portfolio.universe.basket
  const stocks = basket.map((s) => config.stocks[s]).filter(Boolean)
  if (stocks.length === 0) return null
  const hasRules = stocks.some((s) => s.entry_rules.length > 0 || s.exit_rules.length > 0)
  const hasWfo = stocks.some((s) => hasWfoValues(s))
  if (hasRules) return "Direct backtest now executes manual entry and exit rules. Any WFO-marked fields still use their current seed values until the full WFO executor is wired in."
  if (hasWfo) return "Direct backtest can still run, but any WFO-tunable fields are treated as their current seed values. Full optimization requires WFO."
  return null
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

function StrategyTypeCard({ value, onChange }: { value: StrategyConfigV2["stocks"][string]["strategy_type"]; onChange: (next: StrategyConfigV2["stocks"][string]["strategy_type"]) => void }) {
  return (
    <Card><CardHeader><CardTitle className="text-base">Strategy Type</CardTitle><CardDescription>Choose the high-level behavior before tuning signals and rules.</CardDescription></CardHeader><CardContent className="grid gap-3 md:grid-cols-2">
      <button type="button" onClick={() => onChange("trend_following")} className={cn("rounded-xl border p-4 text-left", value === "trend_following" ? "border-primary bg-primary/5" : "hover:bg-muted/30")}><p className="font-semibold">Trend Following</p><p className="mt-1 text-sm text-muted-foreground">Favor sustained moves and confirmation.</p></button>
      <button type="button" onClick={() => onChange("mean_reversion")} className={cn("rounded-xl border p-4 text-left", value === "mean_reversion" ? "border-primary bg-primary/5" : "hover:bg-muted/30")}><p className="font-semibold">Mean Reversion</p><p className="mt-1 text-sm text-muted-foreground">Favor stretch and normalization.</p></button>
    </CardContent></Card>
  )
}

function AllocationCard({ symbol, totalCapital, row, override, onChange }: { symbol: string; totalCapital: number; row: StrategyAllocationRow | null; override: { enabled: boolean; capital_mad: number }; onChange: (next: { enabled: boolean; capital_mad: number }) => void }) {
  const hrpCapital = totalCapital * ((row?.hrp_weight_pct ?? 0) / 100)
  return (
    <Card><CardHeader><CardTitle className="text-base">Allocation</CardTitle><CardDescription>Allocation stays stock-specific even when copying the logic template to the full basket.</CardDescription></CardHeader><CardContent className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border bg-background p-3"><p className="text-[11px] uppercase tracking-wide text-muted-foreground">Source</p><p className="mt-1 text-sm font-semibold">{row?.source === "manual" ? "Manual override" : "HRP baseline"}</p></div>
        <div className="rounded-lg border bg-background p-3"><p className="text-[11px] uppercase tracking-wide text-muted-foreground">HRP suggested</p><p className="mt-1 text-sm font-semibold">{fmtPct(row?.hrp_weight_pct ?? 0, 2)}</p><p className="mt-1 text-xs text-muted-foreground">{fmtMoney(hrpCapital)} MAD</p></div>
        <div className="rounded-lg border bg-background p-3"><p className="text-[11px] uppercase tracking-wide text-muted-foreground">Allocated</p><p className="mt-1 text-sm font-semibold">{fmtPct(row?.weight_pct ?? 0, 2)}</p><p className="mt-1 text-xs text-muted-foreground">{fmtMoney(row?.capital_mad ?? 0)} MAD</p></div>
      </div>
      <div className="rounded-xl border bg-muted/20 p-4"><div className="flex items-center justify-between gap-4"><div><p className="text-sm font-medium">Manual override</p><p className="text-xs text-muted-foreground">Override the HRP baseline only for {symbol}.</p></div><Switch checked={override.enabled} onCheckedChange={(checked) => onChange({ ...override, enabled: checked })} /></div><div className="mt-4 space-y-1"><Label className="text-xs">Manual capital (MAD)</Label><Input type="number" className="h-8 text-sm" value={override.capital_mad} min={0} step={1000} disabled={!override.enabled} onChange={(e) => onChange({ ...override, capital_mad: Number(e.target.value) })} /></div></div>
    </CardContent></Card>
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
  const searchStrategyId = searchParams.get("strategyId")

  const { data: strategies, isLoading: strategiesLoading, mutate: mutateStrategies } = useStrategies()
  const { data: loadedStrategy } = useStrategy(activeId)
  const { data: universe, isLoading: universeLoading } = useUniverse(horizon, { min_abs_signal: config.portfolio.universe.min_abs_signal, min_adv20: config.portfolio.universe.min_adv20, sector_filter: config.portfolio.universe.sector_filter.length > 0 ? config.portfolio.universe.sector_filter : undefined, sort_by: config.portfolio.universe.sort_by, sort_dir: config.portfolio.universe.sort_dir })
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
  const { data: entryPreview } = useEntryRulesPreview(activeSymbol, horizon, activeStockConfig)
  const { data: exitPreview } = useExitRulesPreview(activeSymbol, horizon, activeStockConfig)
  const { data: riskPreview } = useRiskPreview(activeSymbol, horizon, activeStockConfig)
  const rowBySymbol = useMemo(() => new Map((allocationPreview?.rows ?? []).map((row) => [row.symbol, row])), [allocationPreview?.rows])
  const sectors = useMemo(() => Array.from(new Set((universe ?? []).map((row) => row.sector?.trim()).filter(Boolean) as string[])).sort((a, b) => a.localeCompare(b, "fr")), [universe])

  useEffect(() => { if (searchStrategyId && strategies?.some((s) => s.id === searchStrategyId) && searchStrategyId !== activeId) setActiveId(searchStrategyId) }, [activeId, searchStrategyId, strategies])
  useEffect(() => { if (!loadedStrategy) return; const next = ensureBasketStocks(migrateStrategyConfigV2(loadedStrategy.config_json, loadedStrategy.horizon), loadedStrategy.horizon); setName(loadedStrategy.name); setSidePolicy(loadedStrategy.side_policy); setHorizon(loadedStrategy.horizon); setStatus(loadedStrategy.status); setConfig(next); setActiveSymbol(next.portfolio.universe.basket[0] ?? null) }, [loadedStrategy])
  useEffect(() => { const basket = config.portfolio.universe.basket; if (basket.length === 0) setActiveSymbol(null); else if (!activeSymbol || !basket.includes(activeSymbol)) setActiveSymbol(basket[0]) }, [activeSymbol, config.portfolio.universe.basket])

  const markModified = useCallback(() => setStatus((prev) => prev === "saved" ? "modified" : prev), [])
  const updatePortfolioUniverse = useCallback((patch: Partial<StrategyConfigV2["portfolio"]["universe"]>) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, universe: { ...prev.portfolio.universe, ...patch } } })); markModified() }, [markModified])
  const updateStock = useCallback((symbol: string, updater: (stock: StrategyConfigV2["stocks"][string]) => StrategyConfigV2["stocks"][string]) => { setConfig((prev) => ({ ...prev, stocks: { ...prev.stocks, [symbol]: updater(cloneStockStrategyConfig(prev.stocks[symbol], horizon)) } })); markModified() }, [horizon, markModified])

  const toggleBasketSymbol = useCallback((symbol: string) => { setConfig((prev) => ensureBasketStocks({ ...prev, portfolio: { ...prev.portfolio, universe: { ...prev.portfolio.universe, basket: prev.portfolio.universe.basket.includes(symbol) ? prev.portfolio.universe.basket.filter((item) => item !== symbol) : [...prev.portfolio.universe.basket, symbol] } } }, horizon)); setActiveSymbol((prev) => prev ?? symbol); markModified() }, [horizon, markModified])
  const toggleSector = useCallback((sector: string) => updatePortfolioUniverse({ sector_filter: config.portfolio.universe.sector_filter.includes(sector) ? config.portfolio.universe.sector_filter.filter((item) => item !== sector) : [...config.portfolio.universe.sector_filter, sector] }), [config.portfolio.universe.sector_filter, updatePortfolioUniverse])
  const applyToAll = useCallback(() => { if (!activeSymbol || !stockConfig) return; setConfig((prev) => ({ ...prev, stocks: Object.fromEntries(prev.portfolio.universe.basket.map((symbol) => { const current = cloneStockStrategyConfig(prev.stocks[symbol], horizon); const source = cloneStockStrategyConfig(stockConfig, horizon); source.risk.max_position_pct = current.risk.max_position_pct; source.risk.max_sector_pct = current.risk.max_sector_pct; return [symbol, source] })) })); markModified() }, [activeSymbol, horizon, markModified, stockConfig])

  const save = useCallback(async () => { const payload = { name, side_policy: sidePolicy, horizon, config_json: ensureBasketStocks(config, horizon) as unknown as Record<string, unknown>, status: "saved" }; setIsSaving(true); try { if (!activeId) { const created = await createStrategy({ name, side_policy: sidePolicy, horizon }); setActiveId(created.id); await updateStrategy(created.id, payload) } else await updateStrategy(activeId, payload); setStatus("saved"); mutateStrategies() } finally { setIsSaving(false) } }, [activeId, config, horizon, mutateStrategies, name, sidePolicy])
  const create = useCallback(async () => { const created = await createStrategy({ name: "New strategy", side_policy: "long_only", horizon: "short" }); setActiveId(created.id); setName(created.name); setSidePolicy(created.side_policy); setHorizon(created.horizon); setStatus(created.status); setConfig(defaultStrategyConfigV2(created.horizon)); setActiveSymbol(null); mutateStrategies() }, [mutateStrategies])
  const duplicate = useCallback(async () => { if (!activeId) return; const copy = await duplicateStrategy(activeId); mutateStrategies(); setActiveId(copy.id) }, [activeId, mutateStrategies])
  const archive = useCallback(async () => { if (!activeId) return; await archiveStrategy(activeId); setActiveId(null); setName("New strategy"); setSidePolicy("long_only"); setHorizon("short"); setStatus("draft"); setConfig(defaultStrategyConfigV2("short")); setActiveSymbol(null); mutateStrategies() }, [activeId, mutateStrategies])
  const compat = useMemo(() => directCompatibility(config), [config])

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] overflow-hidden">
      <RetractableSavedSidebar storageKey="strategySavedSidebar" label="Strategies" expandedWidth={260} className="h-full">
        <StrategyRail strategies={strategies} isLoading={strategiesLoading} activeId={activeId} onSelect={setActiveId} onCreate={create} className="h-full" />
      </RetractableSavedSidebar>
      <div className="flex-1 overflow-y-auto p-5"><div className="mx-auto max-w-7xl space-y-4">
        <CoreStrategyHeader name={name} onNameChange={(value) => { setName(value); markModified() }} sidePolicy={sidePolicy} onSidePolicyChange={(value) => { setSidePolicy(value); markModified() }} status={status} focusedStock={activeSymbol} basket={config.portfolio.universe.basket} onFocusedStockChange={setActiveSymbol} onSave={save} onDuplicate={duplicate} onArchive={archive} backtestHref={activeId && status === "saved" && reviewPreview?.ready ? `/backtest?strategyId=${activeId}` : null} isSaving={isSaving} />
        <div className="grid gap-4 xl:grid-cols-[1.1fr_1.3fr]">
          <Card><CardHeader><div className="flex items-center gap-2"><CircleDollarSign className="h-4 w-4 text-muted-foreground" /><CardTitle className="text-base">Capital</CardTitle></div><CardDescription>Set portfolio capital and allocation settings once for the whole saved strategy.</CardDescription></CardHeader><CardContent className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2"><div className="space-y-1"><Label className="text-xs">Total capital (MAD)</Label><Input type="text" inputMode="numeric" className="h-9 text-sm" value={fmtMoney(config.portfolio.total_capital_mad)} onChange={(e) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, total_capital_mad: parseIntSafe(e.target.value) } })); markModified() }} /></div><div className="space-y-1"><Label className="text-xs">HRP lookback</Label><Input type="number" className="h-9 text-sm" value={config.portfolio.allocation.hrp_lookback_bars} min={20} max={2000} step={5} onChange={(e) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, allocation: { ...prev.portfolio.allocation, hrp_lookback_bars: Number(e.target.value) } } })); markModified() }} /></div></div>
            <div className="grid gap-3 sm:grid-cols-3"><div className="rounded-lg border bg-background p-3"><p className="text-[11px] uppercase tracking-wide text-muted-foreground">Allocated</p><p className="mt-1 text-sm font-semibold">{fmtMoney(allocationPreview?.allocated_capital_mad ?? 0)} MAD</p></div><div className="rounded-lg border bg-background p-3"><p className="text-[11px] uppercase tracking-wide text-muted-foreground">Remaining</p><p className="mt-1 text-sm font-semibold">{fmtMoney(allocationPreview?.remaining_capital_mad ?? config.portfolio.total_capital_mad)} MAD</p></div><div className="rounded-lg border bg-background p-3"><p className="text-[11px] uppercase tracking-wide text-muted-foreground">Method</p><p className="mt-1 text-sm font-semibold">HRP + manual overrides</p></div></div>
          </CardContent></Card>
          <Card><CardHeader><div className="flex items-center gap-2"><Globe className="h-4 w-4 text-muted-foreground" /><CardTitle className="text-base">Universe</CardTitle></div><CardDescription>Filter, rank, and select the stocks that deserve their own rules-based tab.</CardDescription></CardHeader><CardContent className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-4"><div className="space-y-1"><Label className="text-xs">Min abs signal</Label><Input type="number" className="h-8 text-sm" value={config.portfolio.universe.min_abs_signal} onChange={(e) => updatePortfolioUniverse({ min_abs_signal: Number(e.target.value) })} /></div><div className="space-y-1"><Label className="text-xs">Min ADV20</Label><Input type="number" className="h-8 text-sm" value={config.portfolio.universe.min_adv20} onChange={(e) => updatePortfolioUniverse({ min_adv20: Number(e.target.value) })} /></div><div className="space-y-1"><Label className="text-xs">Sort by</Label><Select value={config.portfolio.universe.sort_by} onValueChange={(value: SortBy) => updatePortfolioUniverse({ sort_by: value })}><SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="adv20">ADV20</SelectItem><SelectItem value="signal_score">Signal strength</SelectItem></SelectContent></Select></div><div className="space-y-1"><Label className="text-xs">Direction</Label><Select value={config.portfolio.universe.sort_dir} onValueChange={(value: SortDir) => updatePortfolioUniverse({ sort_dir: value })}><SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="desc">Descending</SelectItem><SelectItem value="asc">Ascending</SelectItem></SelectContent></Select></div></div>
            {sectors.length > 0 ? <div className="rounded-lg border bg-muted/20 p-3"><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-medium text-muted-foreground">Sector filter</span>{sectors.map((sector) => <button key={sector} type="button" onClick={() => toggleSector(sector)} className={cn("rounded-full border px-2.5 py-1 text-[11px] transition-colors", config.portfolio.universe.sector_filter.includes(sector) ? "border-primary bg-primary text-primary-foreground" : "border-border bg-background text-muted-foreground hover:text-foreground")}>{sector}</button>)}</div></div> : null}
            <div className="overflow-hidden rounded-lg border"><table className="w-full text-xs"><thead className="bg-muted/50"><tr><th className="w-8 px-2 py-2" /><th className="px-2 py-2 text-left font-medium">Ticker</th><th className="px-2 py-2 text-left font-medium">Sector</th><th className="px-2 py-2 text-right font-medium">ADV20</th><th className="px-2 py-2 text-right font-medium">Signal</th><th className="px-2 py-2 text-right font-medium">Status</th></tr></thead><tbody>{universeLoading ? Array.from({ length: 6 }).map((_, index) => <tr key={index} className="border-t"><td colSpan={6} className="px-3 py-2"><Skeleton className="h-8 w-full" /></td></tr>) : (universe ?? []).filter((stock) => config.portfolio.universe.sector_filter.length === 0 || config.portfolio.universe.sector_filter.includes(stock.sector ?? "")).map((stock) => <tr key={stock.symbol} className={cn("border-t transition-colors", config.portfolio.universe.basket.includes(stock.symbol) ? "bg-primary/5" : "hover:bg-muted/40")}><td className="px-2 py-2"><Checkbox checked={config.portfolio.universe.basket.includes(stock.symbol)} onCheckedChange={() => toggleBasketSymbol(stock.symbol)} /></td><td className="px-2 py-2 font-mono font-medium">{stock.symbol}</td><td className="px-2 py-2 text-muted-foreground">{stock.sector ?? "-"}</td><td className="px-2 py-2 text-right font-mono">{stock.adv20 != null ? fmtMoney(stock.adv20) : "-"}</td><td className="px-2 py-2 text-right font-mono">{stock.signal_score != null ? stock.signal_score.toFixed(1) : "-"}</td><td className="px-2 py-2 text-right"><Badge variant={stock.eligible ? "outline" : "secondary"}>{stock.eligible ? "Eligible" : "Filtered"}</Badge></td></tr>)}</tbody></table></div>
          </CardContent></Card>
        </div>
          <Card><CardHeader><div className="flex items-center justify-between gap-3"><div><div className="flex items-center gap-2"><ChartColumnIncreasing className="h-4 w-4 text-muted-foreground" /><CardTitle className="text-base">Stock Tabs</CardTitle></div><CardDescription>Each stock gets Strategy Type, Signal Construction, Entry Rules, Exit Rules, Risk, and Review.</CardDescription></div><Button type="button" variant="outline" size="sm" className="gap-2" disabled={!activeSymbol} onClick={applyToAll}><CopyPlus className="h-4 w-4" />Apply To All</Button></div></CardHeader><CardContent>{config.portfolio.universe.basket.length === 0 ? <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">Select stocks in the universe to open rules-based strategy tabs.</div> : <Tabs value={activeSymbol ?? config.portfolio.universe.basket[0]} onValueChange={setActiveSymbol} className="gap-4"><TabsList className="h-auto w-full flex-wrap justify-start">{config.portfolio.universe.basket.map((symbol) => { const review = reviewPreview?.stocks.find((item) => item.symbol === symbol); const row = rowBySymbol.get(symbol) ?? null; return <TabsTrigger key={symbol} value={symbol} className="flex-none gap-2"><span>{symbol}</span><Badge variant="secondary" className="text-[10px]">{row?.source === "manual" ? "Manual" : "HRP"}</Badge><Badge variant={review?.ready ? "default" : "outline"} className="text-[10px]">{review?.ready ? "Ready" : "Review"}</Badge></TabsTrigger> })}</TabsList>{config.portfolio.universe.basket.map((symbol) => { const current = config.stocks[symbol]; const row = rowBySymbol.get(symbol) ?? null; const override = config.portfolio.allocation.manual_overrides_by_symbol[symbol] ?? { enabled: false, capital_mad: 0 }; const activeFamilies = Object.entries(current.signal_construction.families).filter(([, family]) => family.enabled).map(([id]) => id); const scoreOptions = scoreVariableOptions(current, [...current.entry_rules.flatMap((rule) => rule.conditions.map((condition) => condition.variable)), ...current.exit_rules.flatMap((rule) => rule.conditions.map((condition) => condition.variable))]); return <TabsContent key={symbol} value={symbol} className="space-y-4 pt-2"><AllocationCard symbol={symbol} totalCapital={config.portfolio.total_capital_mad} row={row} override={override} onChange={(next) => { setConfig((prev) => ({ ...prev, portfolio: { ...prev.portfolio, allocation: { ...prev.portfolio.allocation, manual_overrides_by_symbol: { ...prev.portfolio.allocation.manual_overrides_by_symbol, [symbol]: next } } } })); markModified() }} /><StrategyTypeCard value={current.strategy_type} onChange={(next) => updateStock(symbol, (stock) => ({ ...stock, strategy_type: next }))} /><SignalConstructionTab horizon={horizon as HorizonKey} onHorizonChange={(value) => { setHorizon(value); setConfig((prev) => ensureBasketStocks(prev, value)); markModified() }} stockConfig={current} activeScores={symbol === activeSymbol ? signalPreview?.active_scores : undefined} zoneChart={symbol === activeSymbol ? signalPreview?.zone_chart : undefined} isLoading={symbol === activeSymbol ? signalPreviewLoading : false} isRefreshing={symbol === activeSymbol ? signalPreviewPending || (signalPreviewValidating && Boolean(signalPreview)) : false} previewRenderKey={symbol === activeSymbol ? signalPreviewRenderKey : `${symbol}:${horizon}:inactive`} errorMessage={symbol === activeSymbol && signalPreviewError instanceof Error ? signalPreviewError.message : null} familyHistoryMode={familyHistoryMode} onFamilyHistoryModeChange={setFamilyHistoryMode} onChange={(next) => updateStock(symbol, (stock) => ({ ...stock, signal_construction: next }))} /><EntryRulesTab horizon={horizon as HorizonKey} rules={current.entry_rules} scoreOptions={scoreOptions} preview={symbol === activeSymbol ? entryPreview : undefined} onChange={(next) => updateStock(symbol, (stock) => ({ ...stock, entry_rules: next }))} /><ExitRulesTab horizon={horizon as HorizonKey} rules={current.exit_rules} scoreOptions={scoreOptions} preview={symbol === activeSymbol ? exitPreview : undefined} onChange={(next) => updateStock(symbol, (stock) => ({ ...stock, exit_rules: next }))} /><RiskTab horizon={horizon as HorizonKey} risk={current.risk} preview={symbol === activeSymbol ? riskPreview : undefined} onChange={(next: RiskConfigV2) => updateStock(symbol, (stock) => ({ ...stock, risk: next }))} /><ReviewTab symbol={symbol} stockConfig={current} review={reviewPreview} directCompatibilityMessage={symbol === activeSymbol && activeFamilies.length > 0 ? compat : null} /></TabsContent> })}</Tabs>}</CardContent></Card>
        {compat ? <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"><div className="flex items-start gap-2"><ArrowRightLeft className="mt-0.5 h-4 w-4" /><div><p className="font-medium">Direct Backtest Compatibility</p><p className="mt-1">{compat}</p></div></div></div> : null}
      </div></div>
    </div>
  )
}

export default function StrategyPage() {
  return <Suspense fallback={<div className="space-y-4"><Skeleton className="h-32 rounded-xl" /><Skeleton className="h-80 rounded-xl" /></div>}><StrategyPageContent /></Suspense>
}
