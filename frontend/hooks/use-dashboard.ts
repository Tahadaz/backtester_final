"use client"

import useSWR from "swr"
import type { DashboardData, Horizon } from "@/lib/dashboard-types"

async function fetchDashboardData(horizon: Horizon): Promise<DashboardData> {
  const base = process.env.NEXT_PUBLIC_BASE_PATH || ""
  const res = await fetch(`${base}/data/scores-${horizon}.json`, { cache: "no-store" })
  if (!res.ok) {
    throw new Error(`Failed to load dashboard data: ${res.status}`)
  }
  const payload = (await res.json()) as DashboardData
  return {
    ...payload,
    custom_index_definitions: payload.custom_index_definitions ?? [],
  }
}

export function useDashboardData(horizon: Horizon) {
  return useSWR<DashboardData>(`dashboard-${horizon}`, () => fetchDashboardData(horizon), {
    revalidateOnFocus: false,
  })
}
