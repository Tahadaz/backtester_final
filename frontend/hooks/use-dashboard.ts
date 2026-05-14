"use client"

import useSWR from "swr"
import type { DashboardData, DashboardHorizonAlias } from "@/lib/dashboard-types"
import { resolveHorizonPreset } from "@/lib/horizon"

function normalizeDashboardHorizon(horizon: DashboardHorizonAlias) {
  return resolveHorizonPreset(horizon).value
}

// Per-horizon caches so If-None-Match can short-circuit refetches without
// surfacing HTTP 304 as a UI error.
const _etags: Record<string, string> = {}
const _payloads: Record<string, DashboardData> = {}

function normalizePayload(payload: DashboardData): DashboardData {
  return {
    ...payload,
    custom_index_definitions: payload.custom_index_definitions ?? [],
  }
}

async function requestDashboardData(normalized: string, headers?: HeadersInit): Promise<Response> {
  return fetch(`/api/dashboard/data/${normalized}`, { headers, cache: "no-store" })
}

async function fetchDashboardData(horizon: DashboardHorizonAlias): Promise<DashboardData> {
  const normalized = normalizeDashboardHorizon(horizon)
  const headers: HeadersInit = {}
  const etag = _etags[normalized]
  if (etag) {
    headers["If-None-Match"] = etag
  }

  let res = await requestDashboardData(normalized, headers)

  if (res.status === 304) {
    const cached = _payloads[normalized]
    if (cached) return cached

    // A 304 without an in-memory payload can happen after hot reload or remount.
    delete _etags[normalized]
    res = await requestDashboardData(normalized)
  }

  if (!res.ok) {
    throw new Error(`Failed to load dashboard data: ${res.status}`)
  }

  const newEtag = res.headers.get("etag")
  if (newEtag) {
    _etags[normalized] = newEtag
  }

  const payload = normalizePayload((await res.json()) as DashboardData)
  _payloads[normalized] = payload
  return payload
}

export function useDashboardData(horizon: DashboardHorizonAlias) {
  const normalized = normalizeDashboardHorizon(horizon)
  return useSWR<DashboardData>(
    `dashboard-${normalized}`,
    () => fetchDashboardData(horizon),
    {
      refreshInterval: 60_000,
      revalidateOnFocus: true,
    },
  )
}
