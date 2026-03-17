"use client"

import useSWR from "swr"
import type {
  Artifact,
  Dataset,
  FamilyCombinedSignal,
  FillRow,
  LeaderboardRow,
  MarketCatalogRow,
  MarketHealth,
  MarketRefreshRun,
  MarketSymbolRow,
  MeanReversionReport,
  MetricRow,
  OhlcvPreview,
  PositionRow,
  Run,
  RunIntegrity,
  RunRisk,
  RunSignificanceRow,
  RunWalkForward,
  StockMaster,
  StrategyDecision,
} from "@/lib/api"
import { fetchSmaEnsemble } from "@/lib/api"

const API_BASE = "/api"

async function apiFetcher<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Accept": "application/json" },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error")
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json() as Promise<T>
}

export function useRuns(params?: {
  status?: string
  run_type?: string
  limit?: number
  offset?: number
}) {
  const qs = new URLSearchParams()
  if (params?.status) qs.set("status", params.status)
  if (params?.run_type) qs.set("run_type", params.run_type)
  if (params?.limit) qs.set("limit", String(params.limit))
  if (params?.offset) qs.set("offset", String(params.offset))
  const q = qs.toString()

  return useSWR<Run[]>(`/runs${q ? `?${q}` : ""}`, apiFetcher, {
    refreshInterval: 5000,
    revalidateOnFocus: true,
  })
}

export function useRun(runId: string | null) {
  const shouldPoll = (data: Run | undefined) => {
    if (!data) return 2000
    const status = data.status
    if (status === "created" || status === "queued" || status === "running") {
      return 2000
    }
    return 0
  }

  return useSWR<Run>(
    runId ? `/runs/${runId}` : null,
    apiFetcher,
    {
      refreshInterval: shouldPoll,
      revalidateOnFocus: true,
    }
  )
}

export function useLeaderboard(
  runId: string | null,
  params?: { symbol?: string; best_only?: boolean }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.best_only !== undefined)
    qs.set("best_only", String(params.best_only))
  const q = qs.toString()

  return useSWR<LeaderboardRow[]>(
    runId ? `/runs/${runId}/leaderboard${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useRunDecisions(
  runId: string | null,
  params?: { symbol?: string; best_only?: boolean }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.best_only !== undefined) qs.set("best_only", String(params.best_only))
  const q = qs.toString()

  return useSWR<StrategyDecision[]>(
    runId ? `/runs/${runId}/decisions${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useMetrics(runId: string | null) {
  return useSWR<MetricRow[]>(
    runId ? `/runs/${runId}/metrics` : null,
    apiFetcher
  )
}

export function useFills(
  runId: string | null,
  params?: { symbol?: string; limit?: number; cursor?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.limit) qs.set("limit", String(params.limit))
  if (params?.cursor) qs.set("cursor", params.cursor)
  const q = qs.toString()

  return useSWR<FillRow[]>(
    runId ? `/runs/${runId}/fills${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function usePositionLedger(
  runId: string | null,
  params?: { symbol?: string; limit?: number; cursor?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  if (params?.limit) qs.set("limit", String(params.limit))
  if (params?.cursor) qs.set("cursor", params.cursor)
  const q = qs.toString()

  return useSWR<PositionRow[]>(
    runId ? `/runs/${runId}/position-ledger${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useArtifacts(
  runId: string | null,
  params?: { symbol?: string }
) {
  const qs = new URLSearchParams()
  if (params?.symbol) qs.set("symbol", params.symbol)
  const q = qs.toString()

  return useSWR<Artifact[]>(
    runId ? `/runs/${runId}/artifacts${q ? `?${q}` : ""}` : null,
    apiFetcher,
    {
      refreshInterval: 120000,
      revalidateOnFocus: true,
    }
  )
}

export function useRunIntegrity(runId: string | null) {
  return useSWR<RunIntegrity>(
    runId ? `/runs/${runId}/integrity` : null,
    apiFetcher
  )
}

export function useRunWalkForward(runId: string | null) {
  return useSWR<RunWalkForward>(
    runId ? `/runs/${runId}/walk-forward` : null,
    apiFetcher
  )
}

export function useRunSignificance(runId: string | null) {
  return useSWR<RunSignificanceRow[]>(
    runId ? `/runs/${runId}/significance` : null,
    apiFetcher
  )
}

export function useRunRisk(runId: string | null) {
  return useSWR<RunRisk>(
    runId ? `/runs/${runId}/risk` : null,
    apiFetcher
  )
}

export function useRunMeanReversion(runId: string | null) {
  return useSWR<MeanReversionReport>(
    runId ? `/runs/${runId}/mean-reversion` : null,
    apiFetcher
  )
}

export function useDatasets() {
  return useSWR<Dataset[]>("/datasets", apiFetcher, {
    refreshInterval: 15000,
    revalidateOnFocus: true,
  })
}

export function useMarketCatalog() {
  return useSWR<MarketCatalogRow[]>(
    "/market-data/catalog",
    apiFetcher,
    { refreshInterval: 30000, revalidateOnFocus: true }
  )
}

export function useMarketSymbols(params?: { timeframe?: string }) {
  const qs = new URLSearchParams()
  if (params?.timeframe) qs.set("timeframe", params.timeframe)
  const q = qs.toString()

  return useSWR<MarketSymbolRow[]>(
    `/market-data/symbols${q ? `?${q}` : ""}`,
    apiFetcher,
    { refreshInterval: 30000, revalidateOnFocus: true }
  )
}

export function useTrackedStocks(params?: { is_active?: boolean }) {
  const qs = new URLSearchParams()
  if (params?.is_active !== undefined) qs.set("is_active", String(params.is_active))
  const q = qs.toString()

  return useSWR<StockMaster[]>(
    `/market-data/stocks${q ? `?${q}` : ""}`,
    apiFetcher,
    { refreshInterval: 60000, revalidateOnFocus: true }
  )
}

export function useRefreshRun(refreshRunId: string | null) {
  const shouldPoll = (data: MarketRefreshRun | undefined) => {
    if (!data) return 2000
    if (data.status === "queued" || data.status === "running") return 2000
    return 0
  }

  return useSWR<MarketRefreshRun>(
    refreshRunId ? `/market-data/refresh/${refreshRunId}` : null,
    apiFetcher,
    { refreshInterval: shouldPoll, revalidateOnFocus: true }
  )
}

export function useMarketHealth() {
  return useSWR<MarketHealth>(
    "/market-data/health",
    apiFetcher,
    { refreshInterval: 30000, revalidateOnFocus: true }
  )
}

export function useStockOhlcvPreview(symbol: string | null, params?: { limit?: number }) {
  const qs = new URLSearchParams()
  if (params?.limit) qs.set("limit", String(params.limit))
  const q = qs.toString()

  return useSWR<OhlcvPreview>(
    symbol ? `/market-data/stocks/${symbol}/ohlcv-preview${q ? `?${q}` : ""}` : null,
    apiFetcher
  )
}

export function useSmaEnsemble(symbol: string | null, horizon: string | null) {
  const key =
    symbol && horizon
      ? `/strategy/signal/sma-ensemble?s=${symbol}&h=${horizon}`
      : null
  return useSWR<FamilyCombinedSignal>(
    key,
    () => fetchSmaEnsemble({ symbol: symbol!, horizon: horizon! }),
    { revalidateOnFocus: false }
  )
}
