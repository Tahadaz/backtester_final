"use client"

import Link from "next/link"
import { useState, useMemo, useEffect, Suspense } from "react"
import { useSearchParams } from "next/navigation"
import { useAnalyticsSignalsOverview } from "@/hooks/use-api"
import { useDashboardData } from "@/hooks/use-dashboard"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { MacroCatalogTable } from "@/components/analytics/macro-catalog-table"
import { FactorRelevancePanel } from "@/components/analytics/factor-relevance-panel"
import { RecomputeControls } from "@/components/analytics/recompute-controls"
import { RecomputeStatusCard } from "@/components/analytics/recompute-status-card"
import { PredictiveAbilityPanel } from "@/components/analytics/predictive-ability-panel"
import { TopSignauxLeaderboard } from "@/components/analytics/top-signaux-leaderboard"
import { MethodEvaluationPanel } from "@/components/analytics/method-evaluation-panel"
import { FactorLeaderboardPanel } from "@/components/analytics/factor-leaderboard-panel"
import { StatArbPanel } from "@/components/analytics/stat-arb-panel"
import { Activity, BarChart2, BookOpen, CheckCircle2, Database, Download, GitCompareArrows, Globe, Layers3, RefreshCw, Search, TrendingUp, Trophy, Eye, ListOrdered } from "lucide-react"

const ADV_THRESHOLD = 1_000_000
const fmtIc = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) return "--"
  return `${value >= 0 ? "+" : ""}${value.toFixed(3)}`
}

type Tab = "signals" | "macro" | "factors" | "stat-arb"
type SubTab = "top" | "methodes" | "par-action"
type FactorSubTab = "leaderboard" | "par-action"
type EngineHorizon = "short" | "medium" | "long"
type Source = string

export function AnalyticsPageInner() {
  const [tab, setTab] = useState<Tab>("signals")
  const [subTab, setSubTab] = useState<SubTab>("top")
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [presetSource, setPresetSource] = useState<Source | null>(null)
  const [presetHorizon, setPresetHorizon] = useState<EngineHorizon | null>(null)
  const [filter, setFilter] = useState("")
  const [factorSymbol, setFactorSymbol] = useState<string | null>(null)
  const [factorFilter, setFactorFilter] = useState("")
  const [factorSubTab, setFactorSubTab] = useState<FactorSubTab>("leaderboard")
  const [factorHorizon, setFactorHorizon] = useState<EngineHorizon>("short")
  const [liquidityFilter, setLiquidityFilter] = useState(false)
  const [lookbackEnabled, setLookbackEnabled] = useState(false)
  const [lookbackNum, setLookbackNum] = useState(3)
  const [lookbackUnit, setLookbackUnit] = useState<"months" | "years">("months")
  const [selectedSignalId, setSelectedSignalId] = useState<string | null>(null)
  const lookbackDays = lookbackEnabled ? lookbackNum * (lookbackUnit === "months" ? 21 : 252) : 0
  const searchParams = useSearchParams()

  useEffect(() => {
    const sym = searchParams.get("symbol")
    if (sym) {
      setSelectedSymbol(sym.toUpperCase())
      setSubTab("par-action")
    }
    const factorSym = searchParams.get("factor_symbol")
    if (factorSym) {
      setFactorSymbol(factorSym.toUpperCase())
      setTab("factors")
    }
  }, [])

  const { data: allRows, isLoading } = useAnalyticsSignalsOverview()
  const { data: dashData } = useDashboardData("short")

  const symbolList = useMemo(
    () => [...new Set((allRows ?? []).map((r) => r.symbol))].sort(),
    [allRows],
  )

  const advBySymbol = useMemo(() => {
    const map = new Map<string, number>()
    for (const s of dashData?.stocks ?? []) {
      if (s.adv != null) map.set(s.symbol, s.adv)
    }
    return map
  }, [dashData])

  const filteredSymbols = useMemo(() => {
    let list = symbolList
    if (liquidityFilter) list = list.filter((s) => (advBySymbol.get(s) ?? 0) >= ADV_THRESHOLD)
    if (!filter.trim()) return list
    const q = filter.trim().toUpperCase()
    return list.filter((s) => s.toUpperCase().includes(q))
  }, [symbolList, filter, liquidityFilter, advBySymbol])

  const filteredFactorSymbols = useMemo(() => {
    if (!factorFilter.trim()) return symbolList
    const q = factorFilter.trim().toUpperCase()
    return symbolList.filter((s) => s.toUpperCase().includes(q))
  }, [symbolList, factorFilter])

  const topSignals = useMemo(() => {
    const grouped = new Map<string, { signal_id: string; category: string; sum: number; count: number; symbols: Set<string> }>()
    for (const row of allRows ?? []) {
      const ic = typeof row.ic_h1 === "number" && Number.isFinite(row.ic_h1) ? row.ic_h1 : null
      if (ic == null) continue
      const existing = grouped.get(row.signal_id) ?? {
        signal_id: row.signal_id,
        category: row.category,
        sum: 0,
        count: 0,
        symbols: new Set<string>(),
      }
      existing.sum += ic
      existing.count += 1
      existing.symbols.add(row.symbol)
      grouped.set(row.signal_id, existing)
    }
    return Array.from(grouped.values())
      .map((item) => ({
        signal_id: item.signal_id,
        category: item.category,
        meanIc: item.count > 0 ? item.sum / item.count : null,
        count: item.count,
        symbols: item.symbols.size,
      }))
      .sort((a, b) => Math.abs(b.meanIc ?? 0) - Math.abs(a.meanIc ?? 0))
      .slice(0, 20)
  }, [allRows])

  const signalStats = useMemo(() => {
    const rows = allRows ?? []
    const icRows = rows.filter((row) => typeof row.ic_h1 === "number" && Number.isFinite(row.ic_h1))
    const avgIc = icRows.length > 0 ? icRows.reduce((sum, row) => sum + (row.ic_h1 ?? 0), 0) / icRows.length : null
    const significantPct = rows.length > 0 ? (rows.filter((row) => row.fdr_pass).length / rows.length) * 100 : null
    return {
      avgIc,
      significantPct,
      best: topSignals[0] ?? null,
    }
  }, [allRows, topSignals])

  useEffect(() => {
    if (!selectedSignalId && topSignals[0]) setSelectedSignalId(topSignals[0].signal_id)
  }, [selectedSignalId, topSignals])

  const handleSelectFromLeaderboard = (
    symbol: string,
    source: string,
    engineHorizon: EngineHorizon,
  ) => {
    setSelectedSymbol(symbol)
    setPresetSource(source as Source)
    setPresetHorizon(engineHorizon)
    setSubTab("par-action")
  }

  return (
    <div className="claude-analytics-shell">
      <aside className="lb-sidebar">
        <div className="lsh">
          <h4>Top Signaux</h4>
          <div className="eyebrow mb-1">Classement IC - Moyen terme</div>
          <div className="method-pills">
            <button type="button" className="method-pill">C-C</button>
            <button type="button" className="method-pill active">C-O</button>
            <button type="button" className="method-pill">O-O</button>
            <button type="button" className="method-pill">O-C</button>
          </div>
        </div>
        <div className="lb-list">
          {isLoading && topSignals.length === 0 ? (
            <div className="space-y-1 p-1">
              {Array.from({ length: 12 }).map((_, index) => <Skeleton key={index} className="h-9 w-full" />)}
            </div>
          ) : topSignals.length === 0 ? (
            <div className="px-3 py-6 text-xs text-muted-foreground">No signal history yet.</div>
          ) : (
            topSignals.map((signal, index) => (
              <button
                key={signal.signal_id}
                type="button"
                className={`lb-item ${selectedSignalId === signal.signal_id ? "active" : ""}`}
                onClick={() => {
                  setSelectedSignalId(signal.signal_id)
                  setTab("signals")
                  setSubTab("top")
                }}
              >
                <span className="rank">{index + 1}</span>
                <span className="nm truncate">
                  {signal.signal_id}
                  <br />
                  <span className="text-[10px] text-muted-foreground">{signal.category}</span>
                </span>
                <span className={`ic-v ${(signal.meanIc ?? 0) >= 0 ? "t-pos" : "t-neg"}`}>{fmtIc(signal.meanIc)}</span>
              </button>
            ))
          )}
        </div>
      </aside>

      <section className="analytics-main">
        <div className="atabs">
          <button type="button" onClick={() => setTab("signals")} className={tab === "signals" ? "active" : ""}>
            <Activity className="h-3.5 w-3.5" />
            Signaux
          </button>
          <button type="button" onClick={() => setTab("macro")} className={tab === "macro" ? "active" : ""}>
            <Globe className="h-3.5 w-3.5" />
            Macro
          </button>
          <button type="button" onClick={() => setTab("factors")} className={tab === "factors" ? "active" : ""}>
            <Layers3 className="h-3.5 w-3.5" />
            Facteurs
          </button>
          <button type="button" onClick={() => setTab("stat-arb")} className={tab === "stat-arb" ? "active" : ""}>
            <GitCompareArrows className="h-3.5 w-3.5" />
            Stat-arb
          </button>
        </div>

        <div className="ctrl-bar">
          <span className="ctrl-field">
            <label>Methode OOS</label>
            <select className="select" defaultValue="close_to_open">
              <option value="close_to_open">C-O (Close to Open)</option>
              <option value="close_to_close">C-C</option>
              <option value="open_to_open">O-O</option>
              <option value="open_to_close">O-C</option>
            </select>
          </span>
          <span className="ctrl-field">
            <label>Horizon</label>
            {tab === "factors" ? (
              <select className="select" value={factorHorizon} onChange={(event) => setFactorHorizon(event.target.value as EngineHorizon)}>
                <option value="short">5 j (court terme)</option>
                <option value="medium">21 j (moyen terme)</option>
                <option value="long">63 j (long terme)</option>
              </select>
            ) : (
              <select className="select" defaultValue="medium">
                <option value="medium">21 j (moyen terme)</option>
                <option value="short">5 j (court terme)</option>
                <option value="long">63 j (long terme)</option>
              </select>
            )}
          </span>
          <span className="ctrl-field">
            <label>Lookback</label>
            <select
              className="select"
              value={lookbackEnabled ? `${lookbackNum}-${lookbackUnit}` : "all"}
              onChange={(event) => {
                const value = event.target.value
                if (value === "all") {
                  setLookbackEnabled(false)
                  return
                }
                const [num, unit] = value.split("-")
                setLookbackEnabled(true)
                setLookbackNum(Number(num))
                setLookbackUnit(unit as "months" | "years")
              }}
            >
              <option value="all">Historique complet</option>
              <option value="3-months">3 mois</option>
              <option value="1-years">1 an</option>
              <option value="3-years">3 ans</option>
              <option value="5-years">5 ans</option>
            </select>
          </span>
          <span className="ctrl-field">
            <label>Liquidite</label>
            <select className="select" value={liquidityFilter ? "advValue" : "all"} onChange={(event) => setLiquidityFilter(event.target.value !== "all")}>
              <option value="advValue">ADV &gt;= 1 000 000 MAD</option>
              <option value="all">Tous</option>
            </select>
          </span>
          <div className="ml-auto flex gap-2">
            <Link href="/glossary#analytics" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-card px-3 text-xs font-medium text-muted-foreground hover:bg-bg3 hover:text-foreground">
              <BookOpen className="h-3.5 w-3.5" />
              Glossaire
            </Link>
            <RecomputeControls scope="all" />
            <button type="button" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line bg-card px-3 text-xs font-medium text-muted-foreground">
              <Download className="h-3.5 w-3.5" />
              Export
            </button>
          </div>
        </div>

        <div className="content">
          <div className="recompute-card">
            <div className="icon-wrap"><CheckCircle2 className="h-5 w-5" /></div>
            <div className="min-w-0">
              <div className="text-xs font-semibold">Scores a jour</div>
              <p>{symbolList.length} symbols - lookback {lookbackDays > 0 ? `${lookbackDays}j` : "complet"} - top signal {signalStats.best?.signal_id ?? "--"}</p>
            </div>
            <div className="actions">
              <button type="button" className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground">
                <RefreshCw className="h-3.5 w-3.5" />
                Forcer le recalcul
              </button>
            </div>
          </div>
          <RecomputeStatusCard />

          {tab === "signals" ? (
            <>
              <div className="three-col">
                <div className="claude-stat">
                  <div className="lbl">IC moyen (univers)</div>
                  <div className={`val ${(signalStats.avgIc ?? 0) >= 0 ? "t-pos" : "t-neg"}`}>{fmtIc(signalStats.avgIc)}</div>
                  <div className="sub">C-O - 21j - {symbolList.length} titres</div>
                </div>
                <div className="claude-stat">
                  <div className="lbl">% signaux significatifs</div>
                  <div className="val">{signalStats.significantPct == null ? "--" : `${signalStats.significantPct.toFixed(1)}%`}</div>
                  <div className="sub">FDR pass</div>
                </div>
                <div className="claude-stat">
                  <div className="lbl">Meilleur signal</div>
                  <div className="val !text-sm">{signalStats.best?.signal_id ?? "--"}</div>
                  <div className="sub">{signalStats.best ? `IC ${fmtIc(signalStats.best.meanIc)} - ${signalStats.best.symbols} actions` : "No data"}</div>
                </div>
              </div>

              <div className="flex items-center justify-between gap-3">
                <div className="seg">
                  <button type="button" className={subTab === "top" ? "active" : ""} onClick={() => setSubTab("top")}>Top signaux</button>
                  <button type="button" className={subTab === "methodes" ? "active" : ""} onClick={() => setSubTab("methodes")}>Methodes</button>
                  <button type="button" className={subTab === "par-action" ? "active" : ""} onClick={() => setSubTab("par-action")}>Par action</button>
                </div>
                {selectedSignalId ? <span className="text-xs text-muted-foreground">Signal actif: <span className="font-mono">{selectedSignalId}</span></span> : null}
              </div>

              {subTab === "top" ? (
                <div className="two-col">
                  <Card>
                    <CardHeader>
                      <CardTitle>Capacite predictive par indicateur</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <TopSignauxLeaderboard
                        onSelectSymbol={handleSelectFromLeaderboard}
                        advBySymbol={advBySymbol}
                        liquidityFilter={liquidityFilter}
                        advThreshold={ADV_THRESHOLD}
                        lookback_days={lookbackDays}
                      />
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader>
                      <CardTitle>Relevance facteurs x actions selectionnees</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <FactorLeaderboardPanel
                        lookbackDays={lookbackDays}
                        returnMethod="close_to_close"
                        onSelectSymbol={(sym) => {
                          setFactorSymbol(sym)
                          setTab("factors")
                          setFactorSubTab("par-action")
                        }}
                      />
                    </CardContent>
                  </Card>
                </div>
              ) : subTab === "methodes" ? (
                <Card>
                  <CardHeader>
                    <CardTitle>Evaluation des methodes</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <MethodEvaluationPanel />
                  </CardContent>
                </Card>
              ) : (
                <div className="two-col">
                  <Card>
                    <CardHeader>
                      <CardTitle>Actions</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2">
                      <div className="relative">
                        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                        <Input placeholder="Filtrer..." value={filter} onChange={(event) => setFilter(event.target.value)} className="h-8 pl-7 text-xs" />
                      </div>
                      <div className="max-h-[520px] overflow-y-auto rounded-md border border-line">
                        {filteredSymbols.map((sym) => (
                          <button
                            key={sym}
                            type="button"
                            onClick={() => {
                              setSelectedSymbol(sym)
                              setPresetSource(null)
                              setPresetHorizon(null)
                            }}
                            className={`w-full px-3 py-2 text-left font-mono text-xs hover:bg-muted/60 ${selectedSymbol === sym ? "bg-[oklch(0.94_0.04_260_/_0.55)] font-semibold text-[oklch(0.30_0.14_260)]" : ""}`}
                          >
                            {sym}
                          </button>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                  <div>
                    {!selectedSymbol ? (
                      <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-line bg-card text-sm text-muted-foreground">
                        Selectionnez une action pour voir sa capacite predictive.
                      </div>
                    ) : (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-base font-semibold">{selectedSymbol}</span>
                          <RecomputeControls scope="symbol" symbol={selectedSymbol} horizon={presetHorizon ?? "short"} />
                        </div>
                        <PredictiveAbilityPanel symbol={selectedSymbol} initialSource={presetSource ?? undefined} initialHorizon={presetHorizon ?? undefined} lookback_days={lookbackDays} />
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : null}

          {tab === "macro" ? (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-4 w-4 text-primary" />
                  Series Macro - VIX, SP500, Brent, DXY, EURUSD, US10Y
                </CardTitle>
              </CardHeader>
              <CardContent>
                <MacroCatalogTable />
              </CardContent>
            </Card>
          ) : null}

          {tab === "stat-arb" ? <StatArbPanel /> : null}

          {tab === "factors" ? (
            <>
              <div className="seg w-fit">
                <button type="button" className={factorSubTab === "leaderboard" ? "active" : ""} onClick={() => setFactorSubTab("leaderboard")}>Classement</button>
                <button type="button" className={factorSubTab === "par-action" ? "active" : ""} onClick={() => setFactorSubTab("par-action")}>Par action</button>
              </div>
              {factorSubTab === "leaderboard" ? (
                <Card>
                  <CardHeader><CardTitle>Factor Leaderboard</CardTitle></CardHeader>
                  <CardContent>
                    <FactorLeaderboardPanel
                      lookbackDays={lookbackDays}
                      returnMethod="close_to_close"
                      onSelectSymbol={(sym) => {
                        setFactorSymbol(sym)
                        setFactorSubTab("par-action")
                      }}
                    />
                  </CardContent>
                </Card>
              ) : (
                <div className="two-col">
                  <Card>
                    <CardHeader><CardTitle>Actions</CardTitle></CardHeader>
                    <CardContent className="space-y-2">
                      <div className="relative">
                        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                        <Input placeholder="Filtrer..." value={factorFilter} onChange={(event) => setFactorFilter(event.target.value)} className="h-8 pl-7 text-xs" />
                      </div>
                      <div className="max-h-[520px] overflow-y-auto rounded-md border border-line">
                        {filteredFactorSymbols.map((sym) => (
                          <button key={sym} type="button" onClick={() => setFactorSymbol(sym)} className={`w-full px-3 py-2 text-left font-mono text-xs hover:bg-muted/60 ${factorSymbol === sym ? "bg-[oklch(0.94_0.04_260_/_0.55)] font-semibold text-[oklch(0.30_0.14_260)]" : ""}`}>
                            {sym}
                          </button>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                  <div>
                    {!factorSymbol ? (
                      <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-line bg-card text-sm text-muted-foreground">
                        Selectionnez une action pour voir sa pertinence factorielle.
                      </div>
                    ) : (
                      <Card>
                        <CardHeader>
                          <CardTitle className="flex items-center gap-2">
                            <TrendingUp className="h-4 w-4 text-primary" />
                            Diagnostic factoriel - {factorSymbol}
                          </CardTitle>
                        </CardHeader>
                        <CardContent>
                          <FactorRelevancePanel symbol={factorSymbol} horizon={factorHorizon} />
                        </CardContent>
                      </Card>
                    )}
                  </div>
                </div>
              )}
            </>
          ) : null}
        </div>
      </section>
    </div>
  )

  return (
    <div className="claude-page space-y-4">
      <div className="claude-page-h">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <BarChart2 className="h-5 w-5 text-primary" />
            Analytics — Capacité prédictive des signaux
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Information Coefficient global + matrice bucket × horizon par action.
          </p>
        </div>
        <RecomputeControls scope="all" />
      </div>

      <RecomputeStatusCard />

      <div className="flex border-b border-line bg-bg2">
        {(["signals", "macro", "factors", "stat-arb"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`inline-flex h-10 items-center gap-1.5 border-b-2 px-4 text-sm font-medium transition-colors ${
              tab === t
                ? "border-primary bg-card text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t === "signals" ? (
              <span className="flex items-center gap-1.5">
                <BarChart2 className="h-3.5 w-3.5" /> Signaux TA
              </span>
            ) : t === "macro" ? (
              <span className="flex items-center gap-1.5">
                <Database className="h-3.5 w-3.5" /> Données Macro
              </span>
            ) : t === "factors" ? (
              <span className="flex items-center gap-1.5">
                <TrendingUp className="h-3.5 w-3.5" /> Facteurs Macro
              </span>
            ) : (
              <span className="flex items-center gap-1.5">
                <GitCompareArrows className="h-3.5 w-3.5" /> Stat-arb
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "signals" && (
        <div className="space-y-4">
          {/* Lookback period selector */}
          <div className="claude-control-bar">
            <button
              onClick={() => setLookbackEnabled((v) => !v)}
              className={`claude-chip transition-colors ${
                lookbackEnabled
                  ? "amber"
                  : "hover:bg-bg3"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${lookbackEnabled ? "bg-amber-500" : "bg-slate-300"}`} />
              {lookbackEnabled ? "Fenêtre OOS" : "Historique complet"}
            </button>
            {lookbackEnabled && (
              <>
                <input
                  type="number"
                  min={1}
                  max={600}
                  value={lookbackNum}
                  onChange={(e) => setLookbackNum(Math.max(1, Number(e.target.value)))}
                  className="h-7 w-14 rounded-md border border-input bg-background px-2 text-center text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                />
                <select
                  value={lookbackUnit}
                  onChange={(e) => setLookbackUnit(e.target.value as "months" | "years")}
                  className="h-7 rounded-md border border-input bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="months">mois</option>
                  <option value="years">ans</option>
                </select>
                <span className="text-xs text-muted-foreground">≈ {lookbackDays}j</span>
              </>
            )}
          </div>
          {/* Sub-tabs */}
          <div className="flex gap-1 border-b border-line">
            <button
              onClick={() => setSubTab("top")}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm font-medium transition-colors ${
                subTab === "top"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Trophy className="h-3.5 w-3.5" /> Top signaux
            </button>
            <button
              onClick={() => setSubTab("par-action")}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm font-medium transition-colors ${
                subTab === "par-action"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Eye className="h-3.5 w-3.5" /> Par action
            </button>
          </div>

          {subTab === "top" && (
            <TopSignauxLeaderboard
              onSelectSymbol={handleSelectFromLeaderboard}
              advBySymbol={advBySymbol}
              liquidityFilter={liquidityFilter}
              advThreshold={ADV_THRESHOLD}
              lookback_days={lookbackDays}
            />
          )}

          {subTab === "par-action" && (
            <div className="flex flex-col gap-4 lg:flex-row">
              <div className="shrink-0 space-y-2 rounded-lg border border-line bg-card p-2 shadow-xs lg:w-56">
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    placeholder="Filtrer…"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    className="h-8 pl-7 text-xs"
                  />
                </div>
                <button
                  onClick={() => setLiquidityFilter((v) => !v)}
                  className={`claude-chip w-full justify-start transition-colors ${
                    liquidityFilter
                      ? "amber"
                      : "hover:bg-bg3"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${liquidityFilter ? "bg-amber-500" : "bg-slate-300"}`} />
                  {liquidityFilter ? `ADV ≥ ${ADV_THRESHOLD.toLocaleString("fr-FR")} MAD` : "Liquidité"}
                </button>
                <div className="px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Actions ({filteredSymbols.length})
                </div>
                {isLoading ? (
                  <div className="space-y-1">
                    {[...Array(10)].map((_, i) => (
                      <Skeleton key={i} className="h-7 w-full" />
                    ))}
                  </div>
                ) : (
                  <div className="max-h-[640px] overflow-y-auto rounded-md border border-line">
                    {filteredSymbols.map((sym) => (
                      <button
                        key={sym}
                        onClick={() => {
                          setSelectedSymbol(sym)
                          setPresetSource(null)
                          setPresetHorizon(null)
                        }}
                        className={`w-full text-left px-3 py-1.5 text-xs font-mono transition-colors hover:bg-muted/60 ${
                          selectedSymbol === sym
                            ? "bg-[oklch(0.94_0.04_260_/_0.55)] text-[oklch(0.30_0.14_260)] font-semibold"
                            : "text-foreground"
                        }`}
                      >
                        {sym}
                      </button>
                    ))}
                    {filteredSymbols.length === 0 && (
                      <div className="px-3 py-4 text-xs text-muted-foreground text-center">
                        Aucune action
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex-1 min-w-0">
                {!selectedSymbol ? (
                  <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-line text-sm text-muted-foreground">
                    Sélectionnez une action pour voir sa capacité prédictive.
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className="text-base font-semibold font-mono">{selectedSymbol}</span>
                      <RecomputeControls
                        scope="symbol"
                        symbol={selectedSymbol ?? undefined}
                        horizon={presetHorizon ?? "short"}
                      />
                    </div>
                    <PredictiveAbilityPanel
                      symbol={selectedSymbol as string}
                      initialSource={presetSource ?? undefined}
                      initialHorizon={presetHorizon ?? undefined}
                      lookback_days={lookbackDays}
                    />
                    <p className="text-xs text-muted-foreground">
                      Mean = expected return de la bande, intervalle 95% via stationary bootstrap (Politis-Romano).
                      Hit rate = % de cas où la direction du forward return matche la direction du bucket
                      (Strong Buy/Buy → positifs ; Strong Sell/Sell → négatifs), CI Wilson.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {tab === "macro" && (
        <Card className="claude-card">
          <CardHeader className="px-5 pb-2 pt-4">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Database className="h-4 w-4 text-primary" />
              Séries Macro — VIX, SP500, Brent, DXY, EURUSD, US10Y
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <MacroCatalogTable />
          </CardContent>
        </Card>
      )}

      {tab === "stat-arb" && <StatArbPanel />}

      {tab === "factors" && (
        <div className="space-y-4">
          <div className="claude-control-bar">
            <div className="flex items-center gap-1.5">
              <span className="claude-field-label">Horizon</span>
              {(["short", "medium", "long"] as EngineHorizon[]).map((h) => (
                <button
                  key={h}
                  onClick={() => setFactorHorizon(h)}
                  className={`rounded border px-2 py-0.5 font-mono text-xs transition-colors ${
                    factorHorizon === h
                      ? "border-[oklch(0.80_0.06_260)] bg-[oklch(0.94_0.04_260_/_0.4)] text-[oklch(0.30_0.14_260)]"
                      : "border-line bg-card text-muted-foreground hover:bg-bg3"
                  }`}
                >
                  {h}
                </button>
              ))}
            </div>
          </div>

          {/* Sub-tabs */}
          <div className="flex gap-1 border-b border-line">
            <button
              onClick={() => setFactorSubTab("leaderboard")}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm font-medium transition-colors ${
                factorSubTab === "leaderboard"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <ListOrdered className="h-3.5 w-3.5" /> Classement
            </button>
            <button
              onClick={() => setFactorSubTab("par-action")}
              className={`flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-sm font-medium transition-colors ${
                factorSubTab === "par-action"
                  ? "border-primary text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Eye className="h-3.5 w-3.5" /> Par action
            </button>
          </div>

          {factorSubTab === "leaderboard" && (
            <FactorLeaderboardPanel
              lookbackDays={0}
              returnMethod="close_to_close"
              onSelectSymbol={(sym) => {
                setFactorSymbol(sym)
                setFactorSubTab("par-action")
              }}
            />
          )}

          {factorSubTab === "par-action" && (
            <div className="flex flex-col gap-4 lg:flex-row">
              <div className="shrink-0 space-y-2 rounded-lg border border-line bg-card p-2 shadow-xs lg:w-56">
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    placeholder="Filtrer…"
                    value={factorFilter}
                    onChange={(e) => setFactorFilter(e.target.value)}
                    className="h-8 pl-7 text-xs"
                  />
                </div>
                <div className="px-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Actions ({filteredFactorSymbols.length})
                </div>
                {isLoading ? (
                  <div className="space-y-1">
                    {[...Array(10)].map((_, i) => (
                      <Skeleton key={i} className="h-7 w-full" />
                    ))}
                  </div>
                ) : (
                  <div className="max-h-[640px] overflow-y-auto rounded-md border border-line">
                    {filteredFactorSymbols.map((sym) => (
                      <button
                        key={sym}
                        onClick={() => setFactorSymbol(sym)}
                        className={`w-full text-left px-3 py-1.5 text-xs font-mono transition-colors hover:bg-muted/60 ${
                          factorSymbol === sym
                            ? "bg-[oklch(0.94_0.04_260_/_0.55)] text-[oklch(0.30_0.14_260)] font-semibold"
                            : "text-foreground"
                        }`}
                      >
                        {sym}
                      </button>
                    ))}
                    {filteredFactorSymbols.length === 0 && (
                      <div className="px-3 py-4 text-xs text-muted-foreground text-center">
                        Aucune action
                      </div>
                    )}
                  </div>
                )}
              </div>

              <div className="flex-1 min-w-0">
                {!factorSymbol ? (
                  <div className="flex h-64 items-center justify-center rounded-lg border border-dashed border-line text-sm text-muted-foreground">
                    Sélectionnez une action pour voir sa pertinence factorielle.
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className="text-base font-semibold font-mono">{factorSymbol}</span>
                      <RecomputeControls scope="symbol" symbol={factorSymbol ?? undefined} />
                    </div>
                    <Card className="claude-card">
                      <CardHeader className="px-5 pb-2 pt-4">
                        <CardTitle className="text-sm font-semibold flex items-center gap-2">
                          <TrendingUp className="h-4 w-4 text-primary" />
                          Diagnostic factoriel par horizon — {factorSymbol}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="p-4">
                        <FactorRelevancePanel
                          symbol={factorSymbol as string}
                          horizon={factorHorizon}
                        />
                      </CardContent>
                    </Card>
                    <p className="text-xs text-muted-foreground">
                      Surface diagnostique en lecture seule: facteurs actifs, survivants Stage 1, régime courant,
                      statut CUSUM et métadonnées de recalibrage.
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function AnalyticsPage() {
  return (
    <Suspense>
      <AnalyticsPageInner />
    </Suspense>
  )
}
