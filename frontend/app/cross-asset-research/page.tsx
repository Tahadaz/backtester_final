"use client"

import { useEffect, useMemo, useState } from "react"
import { AlertTriangle, Loader2, Play } from "lucide-react"
import { AssetClassTabs } from "@/components/cross-asset/asset-class-tabs"
import { BacktestResults } from "@/components/cross-asset/backtest-results"
import { CurrentSignal } from "@/components/cross-asset/current-signal"
import { MethodologyChain } from "@/components/cross-asset/methodology-chain"
import { RobustnessPanel } from "@/components/cross-asset/robustness-panel"
import { RunRecord } from "@/components/cross-asset/run-record"
import { StrategyOverview } from "@/components/cross-asset/strategy-overview"
import { Button } from "@/components/ui/button"
import type { CrossAssetClass, CrossAssetEnvelope } from "@/lib/api"
import { createCrossAssetRun, createCrossAssetStrategy, getCrossAssetCurrentSignal, getCrossAssetRobustness, getCrossAssetRun, getCrossAssetStages, listCrossAssetStrategies } from "@/lib/api"

const VIEWS = ["Overview", "Methodology", "Backtest", "Robustness", "Current signal", "Run record"] as const
type View = typeof VIEWS[number]

const FX_TSM_SPEC = {
  identity: { name: "G10 FX Time-Series Momentum", version: 1, description: "G10 currencies versus USD" },
  universe: { instruments: ["EURUSD", "USDJPY", "GBPUSD", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD", "USDNOK", "USDSEK"], base_currency: "USD" },
  research_source: { title: "Moskowitz, Ooi & Pedersen", citation: "Adapted systematic FX replication", replication_fidelity: "adapted" },
  data: { fields: ["spot", "r_base", "r_quote", "carry"], source: "yfinance+fred", frequency: "daily" },
  signal: { kind: "time_series_momentum", lookback_months: 12, lag: 1, carry_field: "carry" },
  position: { method: "vol_target", target_vol_annual: 0.10, vol_halflife: 20, max_weight: 0.30, max_gross: 2.0 },
  execution: { lag: 1, rebalance: "monthly", half_spread_bps: 1, slippage_bps: 0.5, commission_bps: 0 },
  returns: { kind: "fx_excess", daycount: 1 / 12, parameters: {} },
  validation: { n_variants: 4, bootstrap_samples: 1000 },
  disclosures: { assumptions: ["Rates are decimal annualized policy-rate proxies.", "Positions rebalance monthly."], warnings: ["Proxy short rates are not tradable forward points.", "Adapted monthly rebalance styling."] },
}

function object(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {} }
function array(value: unknown): Array<Record<string, unknown>> { return Array.isArray(value) ? value.filter((item) => item && typeof item === "object") as Array<Record<string, unknown>> : [] }

export default function CrossAssetResearchPage() {
  const [assetClass, setAssetClass] = useState<CrossAssetClass>("fx")
  const [view, setView] = useState<View>("Overview")
  const [strategy, setStrategy] = useState<Record<string, unknown> | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [run, setRun] = useState<CrossAssetEnvelope | null>(null)
  const [stages, setStages] = useState<CrossAssetEnvelope | null>(null)
  const [robustness, setRobustness] = useState<CrossAssetEnvelope | null>(null)
  const [currentSignal, setCurrentSignal] = useState<CrossAssetEnvelope | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { listCrossAssetStrategies().then((response) => { const rows = array(response.results); const match = rows.find((row) => row.name === FX_TSM_SPEC.identity.name); if (match) setStrategy(match) }).catch(() => undefined) }, [])
  useEffect(() => {
    if (!runId) return
    let stopped = false
    const poll = async () => {
      try {
        const response = await getCrossAssetRun(runId)
        if (stopped) return
        setRun(response)
        const status = String(object(response.results).status ?? "")
        if (status === "succeeded") {
          const strategyId = String(strategy?.id ?? "")
          const [stageResponse, robustResponse, signalResponse] = await Promise.all([getCrossAssetStages(runId), getCrossAssetRobustness(runId), getCrossAssetCurrentSignal(strategyId)])
          if (!stopped) { setStages(stageResponse); setRobustness(robustResponse); setCurrentSignal(signalResponse); setBusy(false) }
          return
        }
        if (status === "failed") { setError(String(object(response.results).error ?? "Run failed")); setBusy(false); return }
        window.setTimeout(poll, 2000)
      } catch (caught) { if (!stopped) { setError(caught instanceof Error ? caught.message : "Polling failed"); setBusy(false) } }
    }
    void poll()
    return () => { stopped = true }
  }, [runId, strategy?.id])

  const warnings = useMemo(() => Array.from(new Set([...(run?.warnings ?? []), ...(stages?.warnings ?? []), ...(robustness?.warnings ?? []), ...(currentSignal?.warnings ?? [])])), [run, stages, robustness, currentSignal])
  const launch = async () => {
    setBusy(true); setError(null); setRun(null); setStages(null); setRobustness(null); setCurrentSignal(null)
    try {
      let selected = strategy
      if (!selected) { const created = await createCrossAssetStrategy(FX_TSM_SPEC); selected = object(created.results); setStrategy(selected) }
      const queued = await createCrossAssetRun(String(selected.id), 42)
      setRun(queued); setRunId(String(object(queued.results).run_id))
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Impossible de lancer le run"); setBusy(false) }
  }

  const runResults = object(run?.results)
  const metrics = object(runResults.metrics)
  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 px-4 py-8 md:px-8">
      <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between"><div><p className="text-sm font-medium text-primary">Research lab reproductible</p><h1 className="text-3xl font-semibold tracking-tight">Cross-Asset Research</h1><p className="mt-2 max-w-3xl text-sm text-muted-foreground">Bonds, commodities et FX dans un moteur commun: returns tradables, signal laggé, positions, coûts, validation et monitoring.</p></div><Button onClick={launch} disabled={busy || assetClass !== "fx"}>{busy ? <Loader2 className="mr-2 size-4 animate-spin"/> : <Play className="mr-2 size-4"/>}Lancer G10 TSM</Button></header>
      <AssetClassTabs value={assetClass} onChange={setAssetClass}/>
      {warnings.map((warning) => <div key={warning} className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-950 dark:text-amber-100"><AlertTriangle className="mt-0.5 size-4 shrink-0"/>{warning}</div>)}
      {error && <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}
      <div className="flex flex-wrap gap-2 border-b pb-3">{VIEWS.map((item) => <button key={item} onClick={() => setView(item)} className={`rounded-md px-3 py-2 text-sm ${view === item ? "bg-secondary font-medium text-foreground" : "text-muted-foreground"}`}>{item}</button>)}</div>
      {view === "Overview" && <StrategyOverview assetClass={assetClass} strategy={strategy}/>}
      {view === "Methodology" && <MethodologyChain assetClass={assetClass} stages={array(stages?.results)}/>}
      {view === "Backtest" && <BacktestResults assetClass={assetClass} metrics={metrics}/>}
      {view === "Robustness" && <RobustnessPanel assetClass={assetClass} results={object(robustness?.results)}/>}
      {view === "Current signal" && <CurrentSignal assetClass={assetClass} signal={object(currentSignal?.results)}/>}
      {view === "Run record" && <RunRecord assetClass={assetClass} inputs={run?.inputs ?? { status: runResults.status ?? null }} warnings={warnings}/>}
    </main>
  )
}
