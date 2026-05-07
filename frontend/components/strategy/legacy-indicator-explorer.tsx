"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useStockOhlcvHistory } from "@/hooks/use-api"
import { fetchIndicatorSeries, type IndicatorSeriesResponse } from "@/lib/api"
import { LegacyIndicatorChart } from "@/components/strategy/legacy-indicator-chart"
import { LegacyIndicatorSidebar } from "@/components/strategy/legacy-indicator-sidebar"
import { SignalEngineGlobalTriggerCard } from "@/components/strategy/signal-engine-global-trigger-card"

export type LegacyIndicatorFamilyKey = "sma" | "rsi" | "macd" | "obv"

export type LegacyIndicatorFamilyState = {
  enabled: boolean
  params: Record<string, number>
  data: IndicatorSeriesResponse | null
  loading: boolean
  error: string | null
}

export type LegacyIndicatorExplorerState = Record<LegacyIndicatorFamilyKey, LegacyIndicatorFamilyState>

export type LegacyIndicatorPriceSeries = {
  dates: string[]
  close: Array<number | null | undefined>
}

const FAMILY_ORDER: LegacyIndicatorFamilyKey[] = ["sma", "rsi", "macd", "obv"]

function createInitialState(): LegacyIndicatorExplorerState {
  return {
    sma: { enabled: false, params: { period: 20 }, data: null, loading: false, error: null },
    rsi: {
      enabled: false,
      params: { period: 14, oversold: 30, overbought: 70 },
      data: null,
      loading: false,
      error: null,
    },
    macd: {
      enabled: false,
      params: { fast: 12, slow: 26, signal: 9 },
      data: null,
      loading: false,
      error: null,
    },
    obv: { enabled: false, params: { ema_period: 20 }, data: null, loading: false, error: null },
  }
}

function extractErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return "Erreur lors du chargement de l'indicateur"
}

export function LegacyIndicatorExplorer({ symbol }: { symbol: string }) {
  const [families, setFamilies] = useState<LegacyIndicatorExplorerState>(() => createInitialState())
  const priceHistory = useStockOhlcvHistory(symbol, { timeframe: "1D" })
  const requestTokenRef = useRef(0)

  useEffect(() => {
    setFamilies((prev) => {
      const next = { ...prev }
      for (const family of FAMILY_ORDER) {
        next[family] = {
          ...next[family],
          data: null,
          loading: false,
          error: null,
        }
      }
      return next
    })
  }, [symbol])

  const requestTargets = useMemo(
    () =>
      FAMILY_ORDER.filter((family) => families[family].enabled).map((family) => ({
        family,
        params: families[family].params,
      })),
    [families],
  )

  const requestSignature = useMemo(() => JSON.stringify(requestTargets), [requestTargets])

  useEffect(() => {
    if (!symbol || requestTargets.length === 0) return

    const token = ++requestTokenRef.current
    const timeoutId = window.setTimeout(async () => {
      setFamilies((prev) => {
        const next = { ...prev }
        for (const { family } of requestTargets) {
          next[family] = {
            ...next[family],
            loading: true,
            error: null,
          }
        }
        return next
      })

      const results = await Promise.allSettled(
        requestTargets.map(({ family, params }) =>
          fetchIndicatorSeries({
            symbol,
            indicator: family,
            params,
            timeframe: "1D",
          }),
        ),
      )

      if (requestTokenRef.current !== token) return

      setFamilies((prev) => {
        const next = { ...prev }

        requestTargets.forEach(({ family, params }, index) => {
          const current = next[family]
          if (!current.enabled || JSON.stringify(current.params) !== JSON.stringify(params)) {
            return
          }

          const result = results[index]
          if (result.status === "fulfilled") {
            next[family] = {
              ...current,
              data: result.value,
              loading: false,
              error: null,
            }
          } else {
            next[family] = {
              ...current,
              data: null,
              loading: false,
              error: extractErrorMessage(result.reason),
            }
          }
        })

        return next
      })
    }, 300)

    return () => {
      window.clearTimeout(timeoutId)
    }
  }, [requestSignature, symbol])

  const priceSeries = useMemo<LegacyIndicatorPriceSeries | null>(() => {
    if (priceHistory.data?.bars?.length) {
      return {
        dates: priceHistory.data.bars.map((bar) => bar.date),
        close: priceHistory.data.bars.map((bar) => bar.close),
      }
    }

    const fallback = FAMILY_ORDER.map((family) => families[family].data).find(Boolean)
    if (!fallback) return null

    return {
      dates: fallback.dates,
      close: fallback.close,
    }
  }, [families, priceHistory.data])

  const setFamilyEnabled = (family: LegacyIndicatorFamilyKey, enabled: boolean) => {
    setFamilies((prev) => ({
      ...prev,
      [family]: {
        ...prev[family],
        enabled,
        data: enabled ? prev[family].data : null,
        loading: false,
        error: null,
      },
    }))
  }

  const setFamilyParam = (family: LegacyIndicatorFamilyKey, key: string, rawValue: number) => {
    setFamilies((prev) => {
      const current = prev[family]
      const nextParams = { ...current.params }

      if (family === "sma" || family === "obv") {
        nextParams[key] = Math.round(rawValue)
      } else if (family === "rsi") {
        const oversold = key === "oversold" ? Math.round(rawValue) : Math.round(nextParams.oversold ?? 30)
        const overbought = key === "overbought" ? Math.round(rawValue) : Math.round(nextParams.overbought ?? 70)
        nextParams.period = key === "period" ? Math.round(rawValue) : Math.round(nextParams.period ?? 14)
        nextParams.oversold = Math.min(oversold, overbought - 1)
        nextParams.overbought = Math.max(overbought, nextParams.oversold + 1)
      } else {
        const fast = key === "fast" ? Math.round(rawValue) : Math.round(nextParams.fast ?? 12)
        const slow = key === "slow" ? Math.round(rawValue) : Math.round(nextParams.slow ?? 26)
        const signal = key === "signal" ? Math.round(rawValue) : Math.round(nextParams.signal ?? 9)

        if (key === "fast") {
          nextParams.fast = Math.min(fast, slow - 1)
          nextParams.slow = slow
        } else if (key === "slow") {
          nextParams.fast = fast
          nextParams.slow = Math.max(slow, fast + 1)
        } else {
          nextParams.fast = fast
          nextParams.slow = slow
        }

        nextParams.signal = signal
      }

      return {
        ...prev,
        [family]: {
          ...current,
          params: nextParams,
          error: null,
        },
      }
    })
  }

  return (
    <div className="space-y-4">
      <SignalEngineGlobalTriggerCard />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0">
          <LegacyIndicatorChart
            priceSeries={priceSeries}
            priceLoading={priceHistory.isLoading}
            priceError={priceHistory.error instanceof Error ? priceHistory.error.message : null}
            families={families}
          />
        </div>
        <div className="min-w-0">
          <LegacyIndicatorSidebar
            families={families}
            onToggle={setFamilyEnabled}
            onParamChange={setFamilyParam}
          />
        </div>
      </div>
    </div>
  )
}
