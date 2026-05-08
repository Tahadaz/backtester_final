"use client"

import useSWR from "swr"
import type { DashboardData, DashboardHorizonAlias } from "@/lib/dashboard-types"
import { resolveHorizonPreset } from "@/lib/horizon"

function normalizeDashboardHorizon(horizon: DashboardHorizonAlias) {
  return resolveHorizonPreset(horizon).value
}

// Per-horizon ETag cache so If-None-Match can short-circuit refetches.
const _etags: Record<string, string> = {}

async function fetchDashboardData(horizon: DashboardHorizonAlias): Promise<DashboardData> {
  const normalized = normalizeDashboardHorizon(horizon)
  const headers: HeadersInit = {}
  const etag = _etags[normalized]
  if (etag) {
    headers["If-None-Match"] = etag
  }

  const res = await fetch(`/api/dashboard/data/${normalized}`, { headers })

  if (res.status === 304) {
    // Server confirmed the cached data is still fresh; useSWR will keep the
    // previous value because we throw here (useSWR ignores throws on 304 when
    // data already exists — so we return a sentinel instead).
    throw new Error("304 Not Modified")
  }

  if (!res.ok) {
    throw new Error(`Failed to load dashboard data: ${res.status}`)
  }

  const newEtag = res.headers.get("etag")
  if (newEtag) {
    _etags[normalized] = newEtag
  }

  const payload = (await res.json()) as DashboardData
  return {
    ...payload,
    custom_index_definitions: payload.custom_index_definitions ?? [],
  }
}

export function useDashboardData(horizon: DashboardHorizonAlias) {
  const normalized = normalizeDashboardHorizon(horizon)
  return useSWR<DashboardData>(
    `dashboard-${normalized}`,
    () => fetchDashboardData(horizon),
    {
      revalidateOnFocus: false,
      // On 304 the fetcher throws; keep previous data so UI doesn't flash.
      onError: () => {},
    }
  )
}
