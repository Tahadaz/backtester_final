"use client"

import useSWR from "swr"
import { fetchDashboardIndices } from "@/lib/api"
import type { DashboardCustomIndex } from "@/lib/api"

export function useDashboardIndices(enabled: boolean) {
  return useSWR<DashboardCustomIndex[]>(
    enabled ? "/dashboard/indices" : null,
    () => fetchDashboardIndices(),
    { revalidateOnFocus: false },
  )
}

