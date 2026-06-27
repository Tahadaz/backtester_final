"use client"

import { useState, type ReactNode } from "react"
import { Activity, Gauge, Layers3, Settings, TrendingUp } from "lucide-react"
import { SignalsViewLayout, type ExpandedSignalsPageView } from "@/components/strategy/signals-view-layout"
import { SignalTechniqueDashboard } from "@/components/strategy/signal-technique-dashboard"
import { SignalEvidenceTab } from "@/components/strategy/signal-evidence-tab"
import { SignalEngineResultsPanel } from "@/components/strategy/signal-engine-results-panel"
import { WfoEvidenceTab } from "@/components/strategy/wfo-evidence-tab"
import { BacktestMCPanel } from "@/components/signals/backtest-mc-panel"
import { PortfolioBacktestPanel } from "@/components/signals/portfolio-backtest-panel"

type SharedSignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
  variant: ExpandedSignalsPageView
  topbarContent?: ReactNode
  defaultTab?: "technique" | "evidence" | "indicateurs" | "wfo" | "backtest" | "portfolio"
  onTabChange?: (tab: string) => void
  evidenceSource?: "auto" | "signal_engine" | "wfo"
  evidenceVariant?: string | null
  selectedVariantId?: string | null
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

function emptyCopyForVariant(variant: string) {
  return variant.includes("factor_x_ta") ? EMPTY_COPY.factor_x_ta : EMPTY_COPY.expanded
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

export function SharedSignalsView({
  selectedSymbol,
  onSelectSymbol,
  horizon,
  onHorizonChange,
  variant,
  topbarContent,
  defaultTab,
  onTabChange,
  evidenceSource = "auto",
  evidenceVariant = null,
  selectedVariantId = null,
}: SharedSignalsViewProps) {
  const [cooldownBars, setCooldownBars] = useState(0)
  const copy = emptyCopyForVariant(variant)

  return (
    <SignalsViewLayout
      selectedSymbol={selectedSymbol}
      onSelectSymbol={onSelectSymbol}
      horizon={horizon}
      variant={variant}
      onHorizonChange={onHorizonChange}
      cooldownBars={cooldownBars}
      onCooldownBarsChange={setCooldownBars}
      topbarContent={topbarContent}
      defaultTab={defaultTab}
      onTabChange={onTabChange}
      techniqueContent={
        selectedSymbol ? (
          <SignalTechniqueDashboard
            symbol={selectedSymbol}
            horizon={horizon}
            variant={variant}
            cooldownBars={cooldownBars}
          />
        ) : (
          <EmptyState icon={Activity} message={copy.technique} />
        )
      }
      evidenceContent={
        selectedSymbol ? (
          <SignalEvidenceTab
            symbol={selectedSymbol}
            horizon={horizon}
            variant={evidenceVariant}
            source={evidenceSource}
            selectedVariantId={selectedVariantId}
            cooldownBars={cooldownBars}
          />
        ) : (
          <EmptyState icon={Gauge} message="Selectionnez un titre pour afficher la preuve du signal." />
        )
      }
      indicatorsContent={
        selectedSymbol ? (
          <SignalEngineResultsPanel
            symbol={selectedSymbol}
            horizon={horizon}
            variant={variant}
            cooldownBars={cooldownBars}
          />
        ) : (
          <EmptyState icon={Layers3} message={copy.indicators} />
        )
      }
      wfoContent={
        selectedSymbol ? (
          <WfoEvidenceTab symbol={selectedSymbol} horizon={horizon} variant={variant} cooldownBars={cooldownBars} />
        ) : (
          <EmptyState icon={Settings} message={copy.wfo} />
        )
      }
      backtestContent={
        selectedSymbol ? (
          <BacktestMCPanel symbol={selectedSymbol} horizon={horizon} variant={variant} cooldownBars={cooldownBars} />
        ) : (
          <EmptyState icon={TrendingUp} message={copy.backtest} />
        )
      }
      portfolioContent={<PortfolioBacktestPanel horizon={horizon} />}
    />
  )
}
