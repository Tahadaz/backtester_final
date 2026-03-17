"use client"

import { useState } from "react"
import { useSmaEnsemble } from "@/hooks/use-api"
import type { SignalRepresentative } from "@/lib/api"
import { Speedometer } from "./speedometer"
import { SmaFamilyDrilldown } from "./sma-family-drilldown"
import { VariantDetailSheet } from "./variant-detail-sheet"
import { MethodologyModal } from "./methodology-modal"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Info } from "lucide-react"
import { toast } from "sonner"

const FAMILIES = [
  { id: "sma", label: "SMA", live: true },
  { id: "rsi", label: "RSI", live: false },
  { id: "macd", label: "MACD", live: false },
  { id: "obv", label: "OBV", live: false },
]

export function TechnicalAnalysisPanel({
  symbol,
  horizon,
}: {
  symbol: string
  horizon: string
}) {
  const { data: smaData, isLoading, error } = useSmaEnsemble(symbol, horizon)

  // Drill-down state: 0=overview, 1=families, 2=sma-drilldown, 3=variant
  const [level, setLevel] = useState(0)
  const [selectedVariant, setSelectedVariant] = useState<SignalRepresentative | null>(null)
  const [methodologyOpen, setMethodologyOpen] = useState(false)

  // Reset level when symbol/horizon changes
  const [lastKey, setLastKey] = useState(`${symbol}-${horizon}`)
  const currentKey = `${symbol}-${horizon}`
  if (currentKey !== lastKey) {
    setLastKey(currentKey)
    setLevel(0)
    setSelectedVariant(null)
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <div className="grid grid-cols-2 gap-3">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <Card className="border-destructive/50">
        <CardContent className="py-8 text-center">
          <p className="text-sm text-destructive font-medium">
            Erreur lors du chargement du signal
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            {error instanceof Error ? error.message : "Erreur inconnue"}
          </p>
        </CardContent>
      </Card>
    )
  }

  const aggregateScore = smaData?.family_score_pct ?? null

  // Levels 2-3: SMA family drill-down (+ variant sheet overlay)
  if ((level === 2 || level === 3) && smaData) {
    return (
      <>
        <SmaFamilyDrilldown
          data={smaData}
          onBack={() => setLevel(1)}
          onSelectVariant={(v) => {
            setSelectedVariant(v)
            setLevel(3)
          }}
        />
        <VariantDetailSheet
          variant={selectedVariant}
          open={level === 3}
          onClose={() => {
            setLevel(2)
            setSelectedVariant(null)
          }}
        />
      </>
    )
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
            <Speedometer value={aggregateScore} size="lg" label="Score agrégé — Analyse Technique" />
            <div className="flex items-center gap-2 mt-2">
              <Badge variant="outline" className="text-[10px]">
                SMA uniquement
              </Badge>
              {smaData && (
                <Badge variant="outline" className="text-[10px] text-muted-foreground">
                  {smaData.as_of}
                </Badge>
              )}
            </div>
            <p className="text-[10px] text-muted-foreground mt-1">
              Cliquez pour voir le détail par famille
            </p>
          </CardContent>
        </Card>
      )}

      {/* Level 1: Family cards */}
      {level === 1 && (
        <>
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setLevel(0)}
              className="text-xs"
            >
              ← Vue d&apos;ensemble
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setMethodologyOpen(true)}
              className="gap-1 text-xs"
            >
              <Info className="h-3 w-3" />
              Méthodologie
            </Button>
          </div>

          <div className="grid grid-cols-2 gap-3">
            {FAMILIES.map((fam) => {
              if (fam.live && smaData) {
                return (
                  <Card
                    key={fam.id}
                    className="cursor-pointer hover:border-primary/50 transition-colors"
                    onClick={() => setLevel(2)}
                  >
                    <CardHeader className="pb-1 pt-3 px-4">
                      <CardTitle className="text-xs font-semibold flex items-center gap-2">
                        {fam.label}
                        <Badge
                          variant="outline"
                          className={`text-[9px] ${
                            smaData.family_signal_label === "BUY"
                              ? "text-green-700 border-green-300"
                              : smaData.family_signal_label === "SELL"
                                ? "text-red-700 border-red-300"
                                : "text-muted-foreground"
                          }`}
                        >
                          {smaData.family_signal_label}
                        </Badge>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="flex justify-center pb-3 px-4">
                      <Speedometer value={smaData.family_score_pct} size="sm" />
                    </CardContent>
                  </Card>
                )
              }

              // Grayed-out placeholder for non-live families
              return (
                <Card
                  key={fam.id}
                  className="opacity-50 cursor-not-allowed"
                  onClick={() =>
                    toast.info(`${fam.label} — Bientôt disponible`)
                  }
                >
                  <CardHeader className="pb-1 pt-3 px-4">
                    <CardTitle className="text-xs font-semibold flex items-center gap-2">
                      {fam.label}
                      <Badge
                        variant="outline"
                        className="text-[9px] text-muted-foreground"
                      >
                        N/A
                      </Badge>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="flex justify-center pb-3 px-4">
                    <Speedometer value={null} size="sm" />
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
