"use client"

import type { ReactNode } from "react"
import { SharedSignalsView } from "@/components/strategy/shared-signals-view"
import type { ExpandedSignalsPageView } from "@/components/strategy/signals-view-layout"

type ExpandedSignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
  topbarContent?: ReactNode
  variant?: ExpandedSignalsPageView
  defaultTab?: "technique" | "evidence" | "indicateurs" | "wfo" | "backtest"
  evidenceSource?: "auto" | "signal_engine" | "wfo"
  evidenceVariant?: string | null
  selectedVariantId?: string | null
}

export function ExpandedSignalsView(props: ExpandedSignalsViewProps) {
  return <SharedSignalsView {...props} variant={props.variant ?? "expanded_ta_simple"} />
}
