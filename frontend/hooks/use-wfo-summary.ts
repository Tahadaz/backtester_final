"use client"

import { useEffect, useState } from "react"
import { fetchWfoSummary, type WfoSummaryResponse } from "@/lib/api"

export function useWfoSummary(symbol: string | null, horizon: string, variant: string = "expanded") {
  const [data, setData] = useState<WfoSummaryResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!symbol) {
      setData(null)
      return
    }

    let cancelled = false
    setIsLoading(true)
    setError(null)

    fetchWfoSummary(symbol, horizon, variant)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [symbol, horizon, variant])

  const refresh = async () => {
    if (!symbol) return
    setIsLoading(true)
    try {
      const res = await fetchWfoSummary(symbol, horizon, variant)
      setData(res)
      setError(null)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setIsLoading(false)
    }
  }

  return { data, isLoading, error, refresh }
}
