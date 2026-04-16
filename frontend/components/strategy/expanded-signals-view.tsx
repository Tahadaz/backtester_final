"use client"

import { useState } from "react"
import { Activity, LineChart, Settings } from "lucide-react"
import { IndicatorExplorer } from "@/components/strategy/indicator-explorer"
import { SignalsViewLayout } from "@/components/strategy/signals-view-layout"
import { TechnicalAnalysisPanel } from "@/components/strategy/technical-analysis-panel"
import { WfoMethodologyTab } from "@/components/strategy/wfo-methodology-tab"

type ExpandedSignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
}

function EmptyState({
  icon: Icon,
  message,
}: {
  icon: typeof Activity
  message: string
}) {
  return (
    <div className="flex h-[300px] items-center justify-center">
      <div className="space-y-2 text-center">
        <Icon className="mx-auto h-10 w-10 text-muted-foreground/30" />
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
    </div>
  )
}

export function ExpandedSignalsView({
  selectedSymbol,
  onSelectSymbol,
  horizon,
  onHorizonChange,
}: ExpandedSignalsViewProps) {
  const [cooldownBars, setCooldownBars] = useState(0)

  return (
    <SignalsViewLayout
      selectedSymbol={selectedSymbol}
      onSelectSymbol={onSelectSymbol}
      horizon={horizon}
      onHorizonChange={onHorizonChange}
      cooldownBars={cooldownBars}
      onCooldownBarsChange={setCooldownBars}
      techniqueContent={
        selectedSymbol ? (
          <TechnicalAnalysisPanel
            symbol={selectedSymbol}
            horizon={horizon}
            cooldownBars={cooldownBars}
          />
        ) : (
          <EmptyState
            icon={Activity}
            message="Selectionnez un titre pour afficher l'analyse."
          />
        )
      }
      indicatorsContent={
        selectedSymbol ? (
          <IndicatorExplorer symbol={selectedSymbol} />
        ) : (
          <EmptyState
            icon={LineChart}
            message="Selectionnez un titre pour afficher les indicateurs."
          />
        )
      }
      wfoContent={
        selectedSymbol ? (
          <WfoMethodologyTab symbol={selectedSymbol} horizon={horizon} />
        ) : (
          <EmptyState
            icon={Settings}
            message="Selectionnez un titre pour configurer le WFO."
          />
        )
      }
    />
  )
}
