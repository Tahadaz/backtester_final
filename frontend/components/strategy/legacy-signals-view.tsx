"use client"

import { useState } from "react"
import { Activity, LineChart, Settings, TrendingUp } from "lucide-react"
import { LegacyIndicatorExplorer } from "@/components/strategy/legacy-indicator-explorer"
import { LegacyTechnicalAnalysisPanel } from "@/components/strategy/legacy-technical-analysis-panel"
import { SignalsViewLayout } from "@/components/strategy/signals-view-layout"
import { WfoMethodologyTab } from "@/components/strategy/wfo-methodology-tab"
import { BacktestMCPanel } from "@/components/signals/backtest-mc-panel"

type LegacySignalsViewProps = {
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

export function LegacySignalsView({
  selectedSymbol,
  onSelectSymbol,
  horizon,
  onHorizonChange,
}: LegacySignalsViewProps) {
  const [cooldownBars, setCooldownBars] = useState(0)

  return (
    <SignalsViewLayout
      selectedSymbol={selectedSymbol}
      onSelectSymbol={onSelectSymbol}
      horizon={horizon}
      variant="legacy"
      onHorizonChange={onHorizonChange}
      cooldownBars={cooldownBars}
      onCooldownBarsChange={setCooldownBars}
      techniqueContent={
        selectedSymbol ? (
          <LegacyTechnicalAnalysisPanel
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
          <LegacyIndicatorExplorer symbol={selectedSymbol} />
        ) : (
          <EmptyState
            icon={LineChart}
            message="Selectionnez un titre pour afficher les indicateurs."
          />
        )
      }
      wfoContent={
        selectedSymbol ? (
          <WfoMethodologyTab symbol={selectedSymbol} horizon={horizon} variant="legacy" />
        ) : (
          <EmptyState
            icon={Settings}
            message="Selectionnez un titre pour configurer le WFO."
          />
        )
      }
      backtestContent={
        selectedSymbol ? (
          <BacktestMCPanel symbol={selectedSymbol} horizon={horizon} variant="legacy" />
        ) : (
          <EmptyState
            icon={TrendingUp}
            message="Selectionnez un titre pour afficher le backtest."
          />
        )
      }
    />
  )
}
