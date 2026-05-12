"use client"

import type { ReactNode } from "react"
import { SharedSignalsView } from "@/components/strategy/shared-signals-view"
import type { ExpandedSignalsPageView } from "@/components/strategy/signals-view-layout"

type FactorXTaSignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
  topbarContent?: ReactNode
  variant?: ExpandedSignalsPageView
}

export function FactorXTaSignalsView(props: FactorXTaSignalsViewProps) {
  return <SharedSignalsView {...props} variant={props.variant ?? "expanded_factor_x_ta_simple"} />
}
