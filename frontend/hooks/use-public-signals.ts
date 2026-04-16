"use client"

import useSWR from "swr"
import type { Horizon } from "@/lib/dashboard-types"
import type { PublicSignalsSnapshot } from "@/lib/public-signals-types"

async function fetchPublicSignals(horizon: Horizon): Promise<PublicSignalsSnapshot> {
  const base = process.env.NEXT_PUBLIC_BASE_PATH || ""
  const res = await fetch(`${base}/data/signals-${horizon}.json`, { cache: "no-store" })
  if (!res.ok) {
    throw new Error(`Failed to load public signals data: ${res.status}`)
  }
  return (await res.json()) as PublicSignalsSnapshot
}

export function usePublicSignals(horizon: Horizon) {
  return useSWR<PublicSignalsSnapshot>(`public-signals-${horizon}`, () => fetchPublicSignals(horizon), {
    revalidateOnFocus: false,
  })
}
