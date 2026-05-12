"use client"

import useSWR from "swr"
import { fetchDashboardIndices } from "@/lib/api"
import type { DashboardCustomIndex } from "@/lib/api"
import type { DashboardHorizonAlias } from "@/lib/dashboard-types"
import { resolveHorizonPreset } from "@/lib/horizon"

export function useDashboardIndices(enabled: boolean, horizon: DashboardHorizonAlias) {
  const normalized = resolveHorizonPreset(horizon).value
  return useSWR<DashboardCustomIndex[]>(
    enabled ? ["dashboard-indices", normalized] : null,
    () => fetchDashboardIndices({ horizon: normalized, include_edge: true }),
    { revalidateOnFocus: false },
  )
}

