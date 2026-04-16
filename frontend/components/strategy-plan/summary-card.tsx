"use client"

import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { SignalScoreBar } from "@/components/strategy/signal-score-bar"
import type { UniverseStock, LevelsResult } from "@/lib/api"

interface SummaryCardProps {
  universe: UniverseStock[] | undefined
  selectedSymbol: string | null
  levels: LevelsResult | undefined
}

export function SummaryCard({ universe, selectedSymbol, levels }: SummaryCardProps) {
  const eligible = universe?.filter((s) => s.eligible) ?? []
  const total = universe?.length ?? 0
  const selectedStock = universe?.find((s) => s.symbol === selectedSymbol)

  return (
    <Card>
      <CardContent className="flex items-center gap-6 py-3 px-4">
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Univers:</span>
          <Badge variant="secondary" className="text-xs font-mono">
            {eligible.length}/{total}
          </Badge>
          <span className="text-[10px] text-muted-foreground">éligibles</span>
        </div>

        {selectedStock && selectedStock.signal_score != null && (
          <>
            <div className="h-6 w-px bg-border" />
            <div className="flex items-center gap-2 flex-1 max-w-xs">
              <span className="text-xs font-semibold">{selectedSymbol}</span>
              <SignalScoreBar
                value={selectedStock.signal_score}
                size="sm"
              />
            </div>
          </>
        )}

        {levels && (
          <>
            <div className="h-6 w-px bg-border" />
            <div className="flex items-center gap-3 text-xs">
              {levels.nearest_support != null && (
                <span>
                  <span className="text-muted-foreground">S:</span>{" "}
                  <span className="font-mono text-green-600">{levels.nearest_support.toFixed(2)}</span>
                </span>
              )}
              {levels.nearest_resistance != null && (
                <span>
                  <span className="text-muted-foreground">R:</span>{" "}
                  <span className="font-mono text-red-600">{levels.nearest_resistance.toFixed(2)}</span>
                </span>
              )}
              {levels.atr_14 != null && (
                <span>
                  <span className="text-muted-foreground">ATR:</span>{" "}
                  <span className="font-mono">{levels.atr_14.toFixed(2)}</span>
                </span>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
