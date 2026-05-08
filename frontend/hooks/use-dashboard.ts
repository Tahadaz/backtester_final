"use client"

import useSWR from "swr"
import type { DashboardData, DashboardHorizonAlias } from "@/lib/dashboard-types"
import { resolveHorizonPreset } from "@/lib/horizon"

function normalizeDashboardHorizon(horizon: DashboardHorizonAlias) {
  return resolveHorizonPreset(horizon).value
}

async function fetchDashboardData(horizon: DashboardHorizonAlias): Promise<DashboardData> {
  const normalized = normalizeDashboardHorizon(horizon)
  const res = await fetch(`/api/dashboard/data/${normalized}`, { cache: "no-store" })
  if (!res.ok) {
    throw new Error(`Failed to load dashboard data: ${res.status}`)
  }
  const payload = (await res.json()) as DashboardData
  return {
    ...payload,
    custom_index_definitions: payload.custom_index_definitions ?? [],
  }
}

export function useDashboardData(horizon: DashboardHorizonAlias) {
  const normalized = normalizeDashboardHorizon(horizon)
  return useSWR<DashboardData>(`dashboard-${normalized}`, () => fetchDashboardData(horizon), {
    revalidateOnFocus: false,
  })
}
