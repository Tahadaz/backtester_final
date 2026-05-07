"use client"

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
import { FactorLeaderboardPanel } from "@/components/analytics/factor-leaderboard-panel"
import { BarChart2, Database, TrendingUp, Search, Trophy, Eye, ListOrdered } from "lucide-react"

const ADV_THRESHOLD = 1000

type Tab = "signals" | "macro" | "factors"
type SubTab = "top" | "par-action"
type FactorSubTab = "leaderboard" | "par-action"
type EngineHorizon = "short" | "medium" | "long"
type Source = "engine_legacy" | "engine_expanded" | "wfo" | "factor_x_ta"

function AnalyticsPageInner() {
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
    <div className="container mx-auto max-w-7xl px-4 py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight flex items-center gap-2">
            <BarChart2 className="h-5 w-5 text-blue-600" />
            Analytics — Capacité prédictive des signaux
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Information Coefficient global + matrice bucket × horizon par action.
          </p>
        </div>
        <RecomputeControls scope="all" />
      </div>

      <RecomputeStatusCard />

      <div className="flex gap-1 border-b">
        {(["signals", "macro", "factors"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t
                ? "border-blue-600 text-blue-700"
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
            ) : (
              <span className="flex items-center gap-1.5">
                <TrendingUp className="h-3.5 w-3.5" /> Facteurs Macro
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "signals" && (
        <div className="space-y-4">
          {/* Lookback period selector */}
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => setLookbackEnabled((v) => !v)}
              className={`inline-flex items-center gap-2 rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
                lookbackEnabled
                  ? "border-amber-300 bg-amber-50 text-amber-800"
                  : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
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
                  className="w-14 h-7 rounded-md border border-input bg-background px-2 text-xs text-center focus:outline-none focus:ring-1 focus:ring-ring"
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
          <div className="flex gap-1 border-b">
            <button
              onClick={() => setSubTab("top")}
              className={`px-3 py-1.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                subTab === "top"
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <Trophy className="h-3.5 w-3.5" /> Top signaux
            </button>
            <button
              onClick={() => setSubTab("par-action")}
              className={`px-3 py-1.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                subTab === "par-action"
                  ? "border-blue-600 text-blue-700"
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
            <div className="flex gap-4">
              <div className="w-44 shrink-0 space-y-2">
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
                  className={`w-full inline-flex items-center gap-2 rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
                    liquidityFilter
                      ? "border-amber-300 bg-amber-50 text-amber-800"
                      : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${liquidityFilter ? "bg-amber-500" : "bg-slate-300"}`} />
                  {liquidityFilter ? `ADV ≥ ${ADV_THRESHOLD.toLocaleString("fr-FR")}` : "Liquidité"}
                </button>
                <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide px-1">
                  Actions ({filteredSymbols.length})
                </div>
                {isLoading ? (
                  <div className="space-y-1">
                    {[...Array(10)].map((_, i) => (
                      <Skeleton key={i} className="h-7 w-full" />
                    ))}
                  </div>
                ) : (
                  <div className="border rounded-md overflow-y-auto max-h-[640px]">
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
                            ? "bg-blue-50 text-blue-700 font-semibold dark:bg-blue-950/30"
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
                  <div className="flex h-64 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                    Sélectionnez une action pour voir sa capacité prédictive.
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className="text-base font-semibold font-mono">{selectedSymbol}</span>
                      <RecomputeControls
                        scope="symbol"
                        symbol={selectedSymbol}
                        horizon={presetHorizon ?? "short"}
                      />
                    </div>
                    <PredictiveAbilityPanel
                      symbol={selectedSymbol}
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
        <Card>
          <CardHeader className="px-5 pb-2 pt-4">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Database className="h-4 w-4 text-blue-600" />
              Séries Macro — VIX, SP500, Brent, DXY, EURUSD, US10Y
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            <MacroCatalogTable />
          </CardContent>
        </Card>
      )}

      {tab === "factors" && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-muted-foreground">Horizon:</span>
              {(["short", "medium", "long"] as EngineHorizon[]).map((h) => (
                <button
                  key={h}
                  onClick={() => setFactorHorizon(h)}
                  className={`px-2 py-0.5 rounded text-xs font-mono border transition-colors ${
                    factorHorizon === h
                      ? "border-blue-400 bg-blue-50 text-blue-700"
                      : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                  }`}
                >
                  {h}
                </button>
              ))}
            </div>
          </div>

          {/* Sub-tabs */}
          <div className="flex gap-1 border-b">
            <button
              onClick={() => setFactorSubTab("leaderboard")}
              className={`px-3 py-1.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                factorSubTab === "leaderboard"
                  ? "border-blue-600 text-blue-700"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              <ListOrdered className="h-3.5 w-3.5" /> Classement
            </button>
            <button
              onClick={() => setFactorSubTab("par-action")}
              className={`px-3 py-1.5 text-sm font-medium border-b-2 transition-colors flex items-center gap-1.5 ${
                factorSubTab === "par-action"
                  ? "border-blue-600 text-blue-700"
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
            <div className="flex gap-4">
              <div className="w-44 shrink-0 space-y-2">
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    placeholder="Filtrer…"
                    value={factorFilter}
                    onChange={(e) => setFactorFilter(e.target.value)}
                    className="h-8 pl-7 text-xs"
                  />
                </div>
                <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide px-1">
                  Actions ({filteredFactorSymbols.length})
                </div>
                {isLoading ? (
                  <div className="space-y-1">
                    {[...Array(10)].map((_, i) => (
                      <Skeleton key={i} className="h-7 w-full" />
                    ))}
                  </div>
                ) : (
                  <div className="border rounded-md overflow-y-auto max-h-[640px]">
                    {filteredFactorSymbols.map((sym) => (
                      <button
                        key={sym}
                        onClick={() => setFactorSymbol(sym)}
                        className={`w-full text-left px-3 py-1.5 text-xs font-mono transition-colors hover:bg-muted/60 ${
                          factorSymbol === sym
                            ? "bg-blue-50 text-blue-700 font-semibold dark:bg-blue-950/30"
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
                  <div className="flex h-64 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
                    Sélectionnez une action pour voir sa pertinence factorielle.
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <span className="text-base font-semibold font-mono">{factorSymbol}</span>
                      <RecomputeControls scope="symbol" symbol={factorSymbol} />
                    </div>
                    <Card>
                      <CardHeader className="px-5 pb-2 pt-4">
                        <CardTitle className="text-sm font-semibold flex items-center gap-2">
                          <TrendingUp className="h-4 w-4 text-blue-600" />
                          Diagnostic factoriel par horizon — {factorSymbol}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="p-4">
                        <FactorRelevancePanel
                          symbol={factorSymbol}
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
