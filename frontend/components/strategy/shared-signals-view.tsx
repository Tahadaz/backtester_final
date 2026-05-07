"use client"

import { useState } from "react"
import { Activity, LineChart, Settings, TrendingUp } from "lucide-react"
import { IndicatorExplorer } from "@/components/strategy/indicator-explorer"
import { SignalsViewLayout, type SignalsPageView } from "@/components/strategy/signals-view-layout"
import { TechnicalAnalysisPanel } from "@/components/strategy/technical-analysis-panel"
import { WfoMethodologyTab } from "@/components/strategy/wfo-methodology-tab"
import { BacktestMCPanel } from "@/components/signals/backtest-mc-panel"

type SharedSignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
  variant: Extract<SignalsPageView, "expanded" | "factor_x_ta">
}

const EMPTY_COPY = {
  expanded: {
    technique: "Selectionnez un titre pour afficher l'analyse.",
    indicators: "Selectionnez un titre pour afficher les indicateurs.",
    wfo: "Selectionnez un titre pour configurer le WFO.",
    backtest: "Selectionnez un titre pour afficher le backtest.",
  },
  factor_x_ta: {
    technique: "Selectionnez un titre pour afficher l'analyse Factor x TA.",
    indicators: "Selectionnez un titre pour afficher les indicateurs.",
    wfo: "Selectionnez un titre pour configurer le WFO Factor x TA.",
    backtest: "Selectionnez un titre pour afficher le backtest Factor x TA.",
  },
} as const

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

export function SharedSignalsView({
  selectedSymbol,
  onSelectSymbol,
  horizon,
  onHorizonChange,
  variant,
}: SharedSignalsViewProps) {
  const [cooldownBars, setCooldownBars] = useState(0)
  const copy = EMPTY_COPY[variant]

  return (
    <SignalsViewLayout
      selectedSymbol={selectedSymbol}
      onSelectSymbol={onSelectSymbol}
      horizon={horizon}
      variant={variant}
      onHorizonChange={onHorizonChange}
      cooldownBars={cooldownBars}
      onCooldownBarsChange={setCooldownBars}
      techniqueContent={
        selectedSymbol ? (
          <TechnicalAnalysisPanel
            symbol={selectedSymbol}
            horizon={horizon}
            cooldownBars={cooldownBars}
            variant={variant}
          />
        ) : (
          <EmptyState icon={Activity} message={copy.technique} />
        )
      }
      indicatorsContent={
        selectedSymbol ? (
          <IndicatorExplorer symbol={selectedSymbol} />
        ) : (
          <EmptyState icon={LineChart} message={copy.indicators} />
        )
      }
      wfoContent={
        selectedSymbol ? (
          <WfoMethodologyTab symbol={selectedSymbol} horizon={horizon} variant={variant} />
        ) : (
          <EmptyState icon={Settings} message={copy.wfo} />
        )
      }
      backtestContent={
        selectedSymbol ? (
          <BacktestMCPanel symbol={selectedSymbol} horizon={horizon} variant={variant} />
        ) : (
          <EmptyState icon={TrendingUp} message={copy.backtest} />
        )
      }
    />
  )
}
