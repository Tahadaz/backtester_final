"use client"

import { SharedSignalsView } from "@/components/strategy/shared-signals-view"

type FactorXTaSignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
}

export function FactorXTaSignalsView(props: FactorXTaSignalsViewProps) {
  return <SharedSignalsView {...props} variant="factor_x_ta" />
}
