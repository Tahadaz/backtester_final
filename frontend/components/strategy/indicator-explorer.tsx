"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { useStockOhlcvHistory } from "@/hooks/use-api"
import { fetchIndicatorSeries, type IndicatorSeriesResponse } from "@/lib/api"
import {
  INDICATOR_FAMILY_ORDER,
  INDICATOR_META_BY_KEY,
  normalizeIndicatorParams,
  type IndicatorFamilyKey,
} from "./indicator-config"
import { IndicatorChart } from "./indicator-chart"
import { IndicatorSidebar } from "./indicator-sidebar"
import { SignalEngineGlobalTriggerCard } from "@/components/strategy/signal-engine-global-trigger-card"

export type { IndicatorFamilyKey } from "./indicator-config"

export type IndicatorFamilyState = {
  enabled: boolean
  params: Record<string, number>
  data: IndicatorSeriesResponse | null
  loading: boolean
  error: string | null
}

export type IndicatorExplorerState = Record<IndicatorFamilyKey, IndicatorFamilyState>

export type IndicatorPriceSeries = {
  dates: string[]
  close: Array<number | null | undefined>
}

function createInitialState(): IndicatorExplorerState {
  return Object.fromEntries(
    INDICATOR_FAMILY_ORDER.map((family) => [
      family,
      {
        enabled: false,
        params: { ...INDICATOR_META_BY_KEY[family].defaults },
        data: null,
        loading: false,
        error: null,
      },
    ]),
  ) as IndicatorExplorerState
}

function extractErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return "Erreur lors du chargement de l'indicateur"
}

export function IndicatorExplorer({ symbol }: { symbol: string }) {
  const [families, setFamilies] = useState<IndicatorExplorerState>(() => createInitialState())
  const priceHistory = useStockOhlcvHistory(symbol, { timeframe: "1D" })
  const requestTokenRef = useRef(0)

  useEffect(() => {
    setFamilies((prev) => {
      const next = { ...prev }
      for (const family of INDICATOR_FAMILY_ORDER) {
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
      INDICATOR_FAMILY_ORDER
        .filter((family) => families[family].enabled)
        .map((family) => ({
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

  const priceSeries = useMemo<IndicatorPriceSeries | null>(() => {
    if (priceHistory.data?.bars?.length) {
      return {
        dates: priceHistory.data.bars.map((bar) => bar.date),
        close: priceHistory.data.bars.map((bar) => bar.close),
      }
    }

    const fallback = INDICATOR_FAMILY_ORDER.map((family) => families[family].data).find(Boolean)
    if (!fallback) return null

    return {
      dates: fallback.dates,
      close: fallback.close,
    }
  }, [families, priceHistory.data])

  const setFamilyEnabled = (family: IndicatorFamilyKey, enabled: boolean) => {
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

  const setFamilyParam = (family: IndicatorFamilyKey, key: string, rawValue: number) => {
    setFamilies((prev) => {
      const current = prev[family]
      return {
        ...prev,
        [family]: {
          ...current,
          params: normalizeIndicatorParams(family, key, rawValue, current.params),
          error: null,
        },
      }
    })
  }

  return (
    <div className="space-y-4">
      <SignalEngineGlobalTriggerCard />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <IndicatorChart
            priceSeries={priceSeries}
            priceLoading={priceHistory.isLoading}
            priceError={priceHistory.error instanceof Error ? priceHistory.error.message : null}
            families={families}
          />
        </div>
        <div className="min-w-0">
          <IndicatorSidebar
            families={families}
            onToggle={setFamilyEnabled}
            onParamChange={setFamilyParam}
          />
        </div>
      </div>
    </div>
  )
}
