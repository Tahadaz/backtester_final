"use client"

import useSWR from "swr"
import type {
  Artifact,
  FillRow,
  LeaderboardRow,
  MeanReversionReport,
  MetricRow,
  PositionRow,
  Run,
  RunIntegrity,
  RunRisk,
  RunSignificanceRow,
  RunWalkForward,
  StrategyDecision,
} from "@/lib/api"

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
