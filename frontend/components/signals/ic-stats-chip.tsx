"use client"

import { useAnalyticsSignalsOverview } from "@/hooks/use-api"
import { ICBadge } from "@/components/analytics/ic-badge"
import { DSRBadge } from "@/components/analytics/dsr-badge"
import { cn } from "@/lib/utils"

const ARCHETYPE_TO_CATEGORY: Record<string, string> = {
  sma: "tendance", ema: "tendance", ema_cross: "tendance", ichimoku: "tendance", psar: "tendance",
  macd: "momentum", roc: "momentum", trix: "momentum", adx: "momentum", tsi: "momentum",
  rsi: "oscillation", stochastic: "oscillation", cci: "oscillation", mfi: "oscillation", uo: "oscillation",
  obv: "volume", cmf: "volume", ad: "volume", vwap: "volume", fi: "volume",
}

interface ICStatsChipProps {
  symbol: string
  horizon: string
  archetype?: string
  className?: string
}

export function ICStatsChip({ symbol, horizon, archetype, className }: ICStatsChipProps) {
  const category = archetype ? ARCHETYPE_TO_CATEGORY[archetype.toLowerCase()] : undefined
  const { data: rows } = useAnalyticsSignalsOverview(symbol, horizon)

  if (!rows || rows.length === 0) return null

  const row = category ? rows.find((r) => r.category === category) ?? null : rows[0] ?? null
  if (!row) return null

  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <ICBadge value={row.ic_h1 ?? Number.NaN} />
      <DSRBadge dsr={row.dsr ?? Number.NaN} psr={row.psr ?? Number.NaN} />
    </span>
  )
}
