"use client"

import { useState } from "react"
import { useFamilyEnsemble, useRegimeConsensus } from "@/hooks/use-api"
import type { FamilyCombinedSignal } from "@/lib/api"
import { SignalScoreBar } from "./signal-score-bar"
import { SmaFamilyDrilldown } from "./sma-family-drilldown"
import { MethodologyModal } from "./methodology-modal"
import { RegimeDetailPanel } from "./regime-detail-panel"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { formatNumber } from "@/lib/format"
import { Info, TrendingUp, Activity, BarChart3 } from "lucide-react"

// Category structure for signal families shown in the UI.
const CATEGORIES = [
  {
    id: "tendance",
    label: "Tendance",
    description: "Direction du marche",
    icon: TrendingUp,
    families: [
      { id: "sma", label: "SMA" },
    ],
  },
  {
    id: "momentum",
    label: "Momentum",
    description: "Dynamique du marche",
    icon: Activity,
    families: [
      { id: "macd", label: "MACD" },
    ],
  },
  {
    id: "oscillation",
    label: "Oscillation",
    description: "Conditions de marche",
    icon: Activity,
    families: [
      { id: "rsi", label: "RSI" },
    ],
  },
  {
    id: "volume",
    label: "Volume",
    description: "Confirmation par le volume",
    icon: BarChart3,
    families: [
      { id: "obv", label: "OBV" },
    ],
  },
]

// Flat list for loading/error checks
const ALL_FAMILIES = CATEGORIES.flatMap((c) => c.families)

// Label -> badge color mapping (type-specific labels)
function labelBadgeClass(label: string): string {
  const l = label.toLowerCase()
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

export function TechnicalAnalysisPanel({
  symbol,
  horizon,
  cooldownBars,
}: {
  symbol: string
  horizon: string
  cooldownBars?: number
}) {
  const sma = useFamilyEnsemble("sma", symbol, horizon, undefined, cooldownBars)
  const rsi = useFamilyEnsemble("rsi", symbol, horizon, undefined, cooldownBars)
  const macd = useFamilyEnsemble("macd", symbol, horizon, undefined, cooldownBars)
  const obv = useFamilyEnsemble("obv", symbol, horizon, undefined, cooldownBars)
  const regime = useRegimeConsensus(symbol, horizon, cooldownBars)

  const familyData: Record<string, { data?: FamilyCombinedSignal; isLoading: boolean; error: unknown }> = {
    sma, rsi, macd, obv,
  }

  // Drill-down state: 0=overview, 1=categories, 2=family-drilldown, 3=regime detail
  const [level, setLevel] = useState(0)
  const [selectedFamily, setSelectedFamily] = useState<string | null>(null)
  const [methodologyOpen, setMethodologyOpen] = useState(false)

  // Reset level when symbol/horizon changes
  const [lastKey, setLastKey] = useState(`${symbol}-${horizon}`)
  const currentKey = `${symbol}-${horizon}`
  if (currentKey !== lastKey) {
    setLastKey(currentKey)
    setLevel(0)
    setSelectedFamily(null)
  }

  const loadedFamilies = ALL_FAMILIES.filter((f) => familyData[f.id].data)
  const anyLoading = ALL_FAMILIES.some((f) => familyData[f.id].isLoading)
  const allError = ALL_FAMILIES.every((f) => familyData[f.id].error)

  if (anyLoading && loadedFamilies.length === 0) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-28 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (allError) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="py-8 text-center">
          <p className="text-sm text-destructive font-medium">
            Erreur lors du chargement du signal
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {sma.error instanceof Error ? sma.error.message : "Erreur inconnue"}
          </p>
        </CardContent>
      </Card>
    )
  }

  // Aggregate score: equal-weight across loaded families.
  const aggregateScore =
    loadedFamilies.length > 0
      ? loadedFamilies.reduce((sum, f) => sum + (familyData[f.id].data?.family_score_pct ?? 0), 0) /
        loadedFamilies.length
      : null
  const aggregateIsProvisional = loadedFamilies.some((f) => familyData[f.id].data?.is_provisional)
  const aggregateMeta =
    sma.data ??
    rsi.data ??
    macd.data ??
    obv.data

  // Level 2: Family drill-down
  if (level === 2 && selectedFamily && familyData[selectedFamily]?.data) {
    return (
      <SmaFamilyDrilldown
        data={familyData[selectedFamily].data!}
        family={selectedFamily}
        cooldownBars={cooldownBars}
        onBack={() => setLevel(1)}
      />
    )
  }

  if (level === 3 && regime.data) {
    return <RegimeDetailPanel data={regime.data} onBack={() => setLevel(1)} />
  }

  return (
    <div className="space-y-5">
      {/* Level 0: Aggregate speedometer */}
      {level === 0 && (
        <Card
          className="cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() => setLevel(1)}
        >
          <CardContent className="flex flex-col items-center py-6 gap-2">
            <SignalScoreBar
              value={aggregateScore}
              size="lg"
              label="Consensus des signaux - Analyse Technique"
              className="w-full max-w-xs"
            />
            <div className="flex items-center gap-2 mt-2 flex-wrap justify-center">
              <Badge variant="outline" className="text-[10px]">
                {loadedFamilies.length}/{ALL_FAMILIES.length} familles
              </Badge>
              {aggregateIsProvisional && (
                <Badge variant="outline" className="text-[10px] border-amber-300 text-amber-800">
                  Provisoire
                </Badge>
              )}
              {aggregateMeta?.latest_close != null && (
                <Badge variant="outline" className="text-[10px] text-muted-foreground">
                  Cloture {formatNumber(aggregateMeta.latest_close)}
                </Badge>
              )}
              {aggregateMeta && (
                <Badge variant="outline" className="text-[10px] text-muted-foreground">
                  {aggregateMeta.as_of}
                </Badge>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              Cliquez pour voir le detail par categorie
            </p>
          </CardContent>
        </Card>
      )}

      {/* Level 1: Category sections (Tendance / Momentum / Oscillation / Volume) */}
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

          <div className="space-y-4">
            {CATEGORIES.map((cat) => {
              const Icon = cat.icon
              const catFamilyData = cat.families.map((f) => ({
                ...f,
                fd: familyData[f.id],
              }))
              const loadedCatFamilies = catFamilyData.filter((f) => f.fd.data)
              const catScore =
                loadedCatFamilies.length > 0
                  ? loadedCatFamilies.reduce(
                      (sum, f) => sum + (f.fd.data?.family_score_pct ?? 0),
                      0,
                    ) / loadedCatFamilies.length
                  : null
              const anyCatLoading = catFamilyData.some((f) => f.fd.isLoading)
              const catIsProvisional = loadedCatFamilies.some((f) => f.fd.data?.is_provisional)

              return (
                <Card key={cat.id}>
                  <CardHeader className="pb-2 pt-3 px-4">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-xs font-semibold flex items-center gap-1.5">
                        <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                        {cat.label}
                        <span className="text-[10px] font-normal text-muted-foreground ml-1">
                          {cat.description}
                        </span>
                      </CardTitle>
                      {catScore !== null && (
                        <div className="flex items-center gap-2">
                          {catIsProvisional && (
                            <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-800">
                              Provisoire
                            </Badge>
                          )}
                          <span className="text-xs font-mono font-medium">
                            {catScore >= 0 ? "+" : ""}
                            {catScore.toFixed(1)}%
                          </span>
                        </div>
                      )}
                    </div>
                    {catScore !== null && (
                      <SignalScoreBar value={catScore} size="sm" className="w-full mt-1" />
                    )}
                    {catScore === null && anyCatLoading && (
                      <Skeleton className="h-6 w-full mt-1" />
                    )}
                  </CardHeader>
                  <CardContent className="pb-3 px-4 pt-0">
                    <div className="space-y-1.5">
                      {catFamilyData.map((fam) => {
                        if (fam.fd.data) {
                          return (
                            <div
                              key={fam.id}
                              className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-muted/50 cursor-pointer transition-colors"
                              onClick={() => {
                                setSelectedFamily(fam.id)
                                setLevel(2)
                              }}
                            >
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-medium w-12">
                                  {fam.label}
                                </span>
                                <Badge
                                  variant="outline"
                                  className={`text-[9px] ${labelBadgeClass(
                                    fam.fd.data.family_signal_label,
                                  )}`}
                                >
                                  {fam.fd.data.family_signal_label}
                                </Badge>
                                {fam.fd.data.is_provisional && (
                                  <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-800">
                                    Provisoire
                                  </Badge>
                                )}
                              </div>
                              <div className="flex items-center gap-2">
                                <span className="text-xs font-mono text-muted-foreground">
                                  {fam.fd.data.family_score_pct >= 0 ? "+" : ""}
                                  {fam.fd.data.family_score_pct.toFixed(1)}%
                                </span>
                                <span className="text-[10px] text-muted-foreground">
                                  &rarr;
                                </span>
                              </div>
                            </div>
                          )
                        }

                        return (
                          <div
                            key={fam.id}
                            className="flex items-center justify-between py-1.5 px-2 opacity-50"
                          >
                            <span className="text-xs font-medium w-12">
                              {fam.label}
                            </span>
                            {fam.fd.isLoading ? (
                              <Skeleton className="h-4 w-20" />
                            ) : (
                              <span className="text-[10px] text-muted-foreground">
                                N/A
                              </span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
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
