"use client"

import { useState, type ReactNode } from "react"
import { Activity, Gauge, Layers3, Settings, TrendingUp } from "lucide-react"
import { SignalsViewLayout } from "@/components/strategy/signals-view-layout"
import { SignalTechniqueDashboard } from "@/components/strategy/signal-technique-dashboard"
import { SignalEngineResultsPanel } from "@/components/strategy/signal-engine-results-panel"
import { SignalEvidenceTab } from "@/components/strategy/signal-evidence-tab"
import { WfoEvidenceTab } from "@/components/strategy/wfo-evidence-tab"
import { BacktestMCPanel } from "@/components/signals/backtest-mc-panel"
import type { LegacySignalsPageView } from "@/components/strategy/signals-view-layout"

type LegacySignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
  topbarContent?: ReactNode
  variant?: LegacySignalsPageView
  evidenceVariant?: string
  defaultTab?: "technique" | "evidence" | "indicateurs" | "wfo" | "backtest"
  evidenceSource?: "auto" | "signal_engine" | "wfo"
  selectedVariantId?: string | null
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
  topbarContent,
  variant = "legacy_ta_simple",
  evidenceVariant = variant,
  defaultTab,
  evidenceSource = "auto",
  selectedVariantId = null,
}: LegacySignalsViewProps) {
  const [cooldownBars, setCooldownBars] = useState(0)

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
      techniqueContent={
        selectedSymbol ? (
          <SignalTechniqueDashboard
            symbol={selectedSymbol}
            horizon={horizon}
            variant={variant}
            cooldownBars={cooldownBars}
          />
        ) : (
          <EmptyState
            icon={Activity}
            message="Selectionnez un titre pour afficher l'analyse."
          />
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
          <EmptyState
            icon={Gauge}
            message="Selectionnez un titre pour afficher la preuve du signal."
          />
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
          <EmptyState
            icon={Layers3}
            message="Selectionnez un titre pour afficher les indicateurs."
          />
        )
      }
      wfoContent={
        selectedSymbol ? (
          <WfoEvidenceTab symbol={selectedSymbol} horizon={horizon} variant={variant} />
        ) : (
          <EmptyState
            icon={Settings}
            message="Selectionnez un titre pour configurer le WFO."
          />
        )
      }
      backtestContent={
        selectedSymbol ? (
          <BacktestMCPanel symbol={selectedSymbol} horizon={horizon} variant={variant} cooldownBars={cooldownBars} />
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
