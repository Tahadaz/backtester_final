"use client"

import { useEffect, useMemo, useState } from "react"
import { useSearchParams } from "next/navigation"
import { HorizonSelector } from "@/components/strategy/horizon-selector"
import { SignalBadge } from "@/components/dashboard-v1/signal-badge"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { usePublicSignals } from "@/hooks/use-public-signals"
import { formatScore } from "@/lib/dashboard-constants"
import type { Horizon } from "@/lib/dashboard-types"
import { signalVariantLabel } from "@/lib/signal-variant-label"
import { SignalEvidenceTab } from "@/components/strategy/signal-evidence-tab"
import type {
  PublicFamilySignalDetail,
  PublicSignalRepresentative,
  PublicSupportResistanceDetail,
} from "@/lib/public-signals-types"
import { Activity, Gauge, LineChart } from "lucide-react"

const HORIZON_VALUES = new Set<Horizon>(["short", "medium", "long"])
type PublicSignalsTab = "technique" | "evidence" | "indicateurs"
type EvidenceSource = "auto" | "signal_engine" | "wfo"
type PublicSignalView = "legacy" | "expanded" | "factor_x_ta"

const sourceAliases: Record<string, EvidenceSource> = {
  auto: "auto",
  best: "auto",
  engine: "signal_engine",
  signal_engine: "signal_engine",
  wfo: "wfo",
}
const FAMILY_ORDER = ["trend", "momentum", "oscillation", "volume"] as const
const FAMILY_LABELS: Record<string, string> = {
  trend: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}

const LEGACY_CATEGORY_FAMILIES: Record<string, string[]> = {
  trend: ["sma"],
  momentum: ["macd"],
  oscillation: ["rsi"],
  volume: ["obv"],
}

const EXPANDED_CATEGORY_FAMILIES: Record<string, string[]> = {
  trend: ["sma", "ema", "ema_cross", "ichimoku", "psar"],
  momentum: ["macd", "roc", "trix", "adx", "tsi"],
  oscillation: ["rsi", "stochastic", "cci", "mfi", "uo"],
  volume: ["obv", "cmf", "ad", "vwap", "fi"],
}

function parseHorizon(value: string | null): Horizon {
  if (value && HORIZON_VALUES.has(value as Horizon)) {
    return value as Horizon
  }
  if (value === "weekly") return "short"
  if (value === "monthly") return "medium"
  if (value === "quarterly") return "long"
  return "short"
}

function parseTab(value: string | null): PublicSignalsTab {
  return value === "evidence" || value === "indicateurs" ? value : "technique"
}

function parseEvidenceSource(value: string | null): EvidenceSource {
  return sourceAliases[String(value ?? "").trim().toLowerCase()] ?? "auto"
}

function parseSignalView(value: string | null): PublicSignalView {
  const token = String(value ?? "").trim().toLowerCase()
  if (token === "legacy" || token.startsWith("legacy_")) return "legacy"
  if (token === "factor_x_ta" || token.includes("factor_x_ta")) return "factor_x_ta"
  return "expanded"
}

function evidenceVariantFromQuery(value: string | null, fallbackView: string | null, legacyVariant: string | null): string {
  const token = String(value ?? "").trim().toLowerCase()
  const legacyToken = String(legacyVariant ?? "").trim().toLowerCase()
  const fallbackToken = String(fallbackView ?? "").trim().toLowerCase()
  const aliases: Record<string, string> = {
    legacy: "legacy_ta_simple",
    expanded: "expanded_ta_simple",
    factor_x_ta: "expanded_factor_x_ta_simple",
  }
  const validModes = new Set([
    "legacy_ta_simple",
    "expanded_ta_simple",
    "legacy_factor_x_ta_simple",
    "expanded_factor_x_ta_simple",
    "legacy_ta_combo",
    "expanded_ta_combo",
    "legacy_factor_x_ta_combo",
    "expanded_factor_x_ta_combo",
  ])
  for (const candidate of [token, legacyToken, fallbackToken]) {
    if (aliases[candidate]) return aliases[candidate]
    if (validModes.has(candidate)) return candidate
  }
  return "expanded_ta_simple"
}

function selectedSignalVariantIdFromQuery(value: string | null): string | null {
  const token = String(value ?? "").trim()
  const normalized = token.toLowerCase()
  if (!token) return null
  if (
    normalized === "legacy" ||
    normalized === "expanded" ||
    normalized === "factor_x_ta" ||
    normalized === "legacy_ta_simple" ||
    normalized === "expanded_ta_simple" ||
    normalized === "legacy_factor_x_ta_simple" ||
    normalized === "expanded_factor_x_ta_simple" ||
    normalized === "legacy_ta_combo" ||
    normalized === "expanded_ta_combo" ||
    normalized === "legacy_factor_x_ta_combo" ||
    normalized === "expanded_factor_x_ta_combo"
  ) {
    return null
  }
  return token
}

function representativeLabel(rep: PublicSignalRepresentative): string {
  return signalVariantLabel(rep)
}

function fmtLevel(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return value.toFixed(2)
}

function FamilyDetailCard({
  familyDetail,
}: {
  familyDetail: PublicFamilySignalDetail
}) {
  const available = familyDetail.representative_count > 0
  return (
    <Card>
      <CardHeader className="pb-2 pt-3">
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="text-sm">
            {FAMILY_LABELS[familyDetail.family] ?? familyDetail.family.toUpperCase()}
          </CardTitle>
          <div className="flex items-center gap-2">
            <SignalBadge label={familyDetail.family_signal_label} />
            <span className="font-mono text-xs text-muted-foreground">
              {available ? formatScore(familyDetail.family_score_pct) : "-"}
            </span>
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          Testees: {familyDetail.tested_count} | Viables: {familyDetail.viable_count} | Competitives:{" "}
          {familyDetail.competitive_count} | Representatives: {familyDetail.representative_count}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <p className="rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground">
          {familyDetail.score_explanation || "Aucune explication disponible."}
        </p>

        {familyDetail.representatives.length > 0 ? (
          <div className="space-y-2">
            {familyDetail.representatives.map((rep) => (
              <div key={rep.variant_id} className="rounded-md border p-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold">{representativeLabel(rep)}</p>
                  <SignalBadge label={rep.signal_label} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{rep.explanation}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Aucun representant disponible.</p>
        )}

        {familyDetail.fallback_variants.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold text-muted-foreground">Variantes provisoires</p>
            {familyDetail.fallback_variants.map((rep) => (
              <div key={rep.variant_id} className="rounded-md border border-amber-300 bg-amber-50/60 p-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold">{representativeLabel(rep)}</p>
                  <SignalBadge label={rep.signal_label} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{rep.explanation}</p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function SupportResistanceDetailCard({ detail }: { detail: PublicSupportResistanceDetail }) {
  return (
    <Card>
      <CardHeader className="pb-2 pt-3">
        <div className="flex items-center justify-between gap-2">
          <CardTitle className="text-sm">Support et resistance</CardTitle>
          <Badge variant="outline" className="text-[10px] text-muted-foreground">
            {detail.as_of || "--"}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground">{detail.summary_explanation || "Aucun detail disponible."}</p>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-md border bg-muted/20 p-2.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Tendance</p>
            <p className="text-xs font-semibold">{detail.trend_label || "--"}</p>
          </div>
          <div className="rounded-md border bg-emerald-50/60 p-2.5">
            <p className="text-[10px] uppercase tracking-wide text-emerald-700">Support final</p>
            <p className="font-mono text-sm font-semibold text-emerald-700">{fmtLevel(detail.final_support)}</p>
            <p className="text-[10px] text-emerald-700/80">{detail.selected_support_method_id ?? "--"}</p>
          </div>
          <div className="rounded-md border bg-red-50/60 p-2.5">
            <p className="text-[10px] uppercase tracking-wide text-red-700">Resistance finale</p>
            <p className="font-mono text-sm font-semibold text-red-700">{fmtLevel(detail.final_resistance)}</p>
            <p className="text-[10px] text-red-700/80">{detail.selected_resistance_method_id ?? "--"}</p>
          </div>
        </div>

        {detail.used_variant && (
          <div className="rounded-md border p-2">
            <p className="text-[11px] font-semibold">Variante retenue</p>
            <p className="text-xs text-muted-foreground">{detail.used_variant.description}</p>
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">{detail.used_variant.variant_id}</p>
          </div>
        )}

        {detail.used_methods.length > 0 && (
          <div className="space-y-2">
            <p className="text-xs font-semibold text-muted-foreground">Methodes retenues</p>
            {detail.used_methods.map((method) => (
              <div key={method.id} className="rounded-md border p-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold">{method.label}</p>
                  <Badge variant="outline" className="text-[10px]">{method.status}</Badge>
                </div>
                <div className="mt-1 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                  <p>Support: <span className="font-mono text-foreground">{fmtLevel(method.support)}</span></p>
                  <p>Resistance: <span className="font-mono text-foreground">{fmtLevel(method.resistance)}</span></p>
                </div>
                {method.explanation && <p className="mt-1 text-[11px] text-muted-foreground">{method.explanation}</p>}
              </div>
            ))}
          </div>
        )}

        {detail.warning_message && (
          <p className="rounded-md border border-amber-300 bg-amber-50/70 p-2 text-xs text-amber-900">
            {detail.warning_message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

export function PublicSignalsPage() {
  const searchParams = useSearchParams()
  const requestedSymbol = (searchParams.get("symbol") ?? "").toUpperCase()
  const requestedHorizon = parseHorizon(searchParams.get("horizon"))
  const requestedView = parseSignalView(searchParams.get("view"))
  const viewParam = searchParams.get("view")
  const requestedEvidenceVariant = evidenceVariantFromQuery(
    viewParam ?? searchParams.get("evidence_variant"),
    viewParam,
    searchParams.get("variant"),
  )
  const requestedSelectedVariantId = selectedSignalVariantIdFromQuery(searchParams.get("variant"))
  const requestedTab = parseTab(searchParams.get("tab"))
  const requestedSource = parseEvidenceSource(searchParams.get("source"))

  const [horizon, setHorizon] = useState<Horizon>(requestedHorizon)
  const [search, setSearch] = useState("")
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(requestedSymbol || null)
  const [signalView, setSignalView] = useState<PublicSignalView>(requestedView)
  const [activeTab, setActiveTab] = useState<PublicSignalsTab>(requestedTab)

  const { data, error, isLoading } = usePublicSignals(horizon)

  useEffect(() => {
    setHorizon(requestedHorizon)
  }, [requestedHorizon])

  useEffect(() => {
    setSignalView(requestedView)
  }, [requestedView])

  useEffect(() => {
    setActiveTab(requestedTab)
  }, [requestedTab, requestedSymbol])

  useEffect(() => {
    if (requestedSymbol) {
      setSelectedSymbol(requestedSymbol)
    }
  }, [requestedSymbol])

  const stocks = data?.stocks ?? []
  const filteredStocks = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return stocks
    return stocks.filter((stock) => {
      return (
        stock.symbol.toLowerCase().includes(query) ||
        (stock.display_name ?? "").toLowerCase().includes(query)
      )
    })
  }, [stocks, search])

  useEffect(() => {
    if (stocks.length === 0) {
      setSelectedSymbol(null)
      return
    }

    if (selectedSymbol && stocks.some((stock) => stock.symbol === selectedSymbol)) {
      return
    }

    if (requestedSymbol && stocks.some((stock) => stock.symbol === requestedSymbol)) {
      setSelectedSymbol(requestedSymbol)
      return
    }

    setSelectedSymbol(stocks[0].symbol)
  }, [requestedSymbol, selectedSymbol, stocks])

  const selectedStock = useMemo(
    () => stocks.find((stock) => stock.symbol === selectedSymbol) ?? null,
    [stocks, selectedSymbol],
  )

  const displayedAggregateScore = signalView === "expanded"
    ? selectedStock?.expanded_aggregate_score_pct ?? selectedStock?.aggregate_score_pct ?? null
    : selectedStock?.aggregate_score_pct ?? null
  const displayedAggregateLabel = signalView === "expanded"
    ? selectedStock?.expanded_aggregate_signal_label ?? selectedStock?.aggregate_signal_label ?? null
    : selectedStock?.aggregate_signal_label ?? null

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] overflow-hidden">
      <aside className="flex w-[300px] shrink-0 flex-col border-r bg-card">
        <div className="border-b p-3">
          <Input
            placeholder="Rechercher un titre..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="h-8 text-xs"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-1">
          {isLoading ? (
            <div className="space-y-2 p-2">
              {Array.from({ length: 12 }).map((_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
          ) : filteredStocks.length === 0 ? (
            <p className="p-3 text-xs text-muted-foreground">Aucun titre trouve.</p>
          ) : (
            filteredStocks.map((stock) => (
              <button
                key={stock.symbol}
                onClick={() => setSelectedSymbol(stock.symbol)}
                className={`mb-1 w-full rounded-md px-3 py-2 text-left transition-colors ${
                  selectedSymbol === stock.symbol ? "bg-accent" : "hover:bg-accent/60"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <p className="font-mono text-xs font-bold">{stock.symbol}</p>
                  <SignalBadge
                    label={
                      signalView === "expanded"
                        ? (stock.expanded_aggregate_signal_label ?? stock.aggregate_signal_label)
                        : stock.aggregate_signal_label
                    }
                  />
                </div>
                {stock.display_name && (
                  <p className="truncate text-[10px] text-muted-foreground">{stock.display_name}</p>
                )}
              </button>
            ))
          )}
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto p-5">
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h1 className="text-lg font-bold tracking-tight">{selectedStock?.symbol ?? "Signaux"}</h1>
              <p className="text-xs text-muted-foreground">
                Snapshot statique public
                {data && ` - Mis a jour le ${new Date(data.generated_at).toLocaleDateString("fr-FR")}`}
              </p>
            </div>
            <HorizonSelector value={horizon} onChange={(value) => setHorizon(parseHorizon(value))} />
          </div>

          <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as PublicSignalsTab)}>
            <TabsList>
              <TabsTrigger value="technique" className="gap-1.5 text-xs">
                <Activity className="h-3.5 w-3.5" />
                Analyse technique
              </TabsTrigger>
              <TabsTrigger value="evidence" className="gap-1.5 text-xs" disabled={!selectedStock}>
                <Gauge className="h-3.5 w-3.5" />
                Signal Evidence
              </TabsTrigger>
              <TabsTrigger value="indicateurs" className="gap-1.5 text-xs" disabled>
                <LineChart className="h-3.5 w-3.5" />
                Indicateurs
              </TabsTrigger>
            </TabsList>

            <p className="mt-2 text-xs text-muted-foreground">
              Signal Evidence audite le signal du jour avec le backend; Indicateurs reste reserve au mode prive complet.
            </p>

            <TabsContent value="technique" className="mt-4">
              {error && (
                <Card className="border-destructive">
                  <CardContent className="py-4 text-sm text-destructive">{error.message}</CardContent>
                </Card>
              )}

              {!error && !selectedStock && (
                <div className="flex h-[300px] items-center justify-center">
                  <p className="text-sm text-muted-foreground">
                    Selectionnez un titre pour afficher les justifications.
                  </p>
                </div>
              )}

              {!error && selectedStock && (
                <div className="space-y-4">
                  <Card>
                    <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
                      <div>
                        <p className="text-sm font-semibold">Signal technique global</p>
                        <p className="text-xs text-muted-foreground">
                          {selectedStock.display_name ?? selectedStock.symbol}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <SignalBadge label={displayedAggregateLabel} />
                        {displayedAggregateScore != null && (
                          <span className="font-mono text-sm font-semibold">
                            {formatScore(displayedAggregateScore)}
                          </span>
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  {selectedStock.support_resistance && (
                    <SupportResistanceDetailCard detail={selectedStock.support_resistance} />
                  )}

                  {FAMILY_ORDER.map((category) => {
                    const categoryFamily = FAMILY_LABELS[category]
                    const indicatorKeys = signalView === "expanded"
                      ? EXPANDED_CATEGORY_FAMILIES[category]
                      : LEGACY_CATEGORY_FAMILIES[category]

                    return (
                      <div key={`${selectedStock.symbol}-${category}`}>
                        {signalView === "expanded" && (
                          <h3 className="mb-3 mt-4 text-sm font-semibold text-muted-foreground">
                            {categoryFamily}
                          </h3>
                        )}
                        {indicatorKeys.map((indicator) => {
                          const familyDetail = selectedStock.families?.[indicator]
                          if (!familyDetail) return null
                          return (
                            <FamilyDetailCard
                              key={`${selectedStock.symbol}-${indicator}`}
                              familyDetail={familyDetail}
                            />
                          )
                        })}
                      </div>
                    )
                  })}
                </div>
              )}
            </TabsContent>

            <TabsContent value="evidence" className="mt-4">
              {selectedStock ? (
                <SignalEvidenceTab
                  symbol={selectedStock.symbol}
                  horizon={horizon}
                  variant={requestedEvidenceVariant}
                  source={requestedSource}
                  selectedVariantId={requestedSelectedVariantId}
                />
              ) : (
                <Card>
                  <CardContent className="py-4 text-sm text-muted-foreground">
                    Selectionnez un titre pour afficher la preuve OOS du signal.
                  </CardContent>
                </Card>
              )}
            </TabsContent>
          </Tabs>
        </div>
      </main>
    </div>
  )
}
