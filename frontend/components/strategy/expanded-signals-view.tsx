"use client"

import { SharedSignalsView } from "@/components/strategy/shared-signals-view"

type ExpandedSignalsViewProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
}

export function ExpandedSignalsView(props: ExpandedSignalsViewProps) {
  return <SharedSignalsView {...props} variant="expanded" />
}
