"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ExpandedSignalsView } from "@/components/strategy/expanded-signals-view"
import { LegacySignalsView } from "@/components/strategy/legacy-signals-view"
import { FactorXTaSignalsView } from "@/components/strategy/factor-x-ta-signals-view"
import { PublicSignalsPage } from "@/components/strategy/public-signals-page"
import { SignalsVersionToggle } from "@/components/strategy/signals-version-toggle"
import type { SignalsPageView } from "@/components/strategy/signals-view-layout"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"

const validHorizons = new Set(["short", "medium", "long"])
const validViews = new Set<SignalsPageView>(["expanded", "legacy", "factor_x_ta"])

function PrivateSignalsPage() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const symbolFromQuery = (searchParams.get("symbol") ?? "").trim().toUpperCase()
  const horizonFromQuery = (searchParams.get("horizon") ?? "").trim().toLowerCase()
  const viewFromQuery = (searchParams.get("view") ?? "").trim().toLowerCase()
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [horizon, setHorizon] = useState("short")

  const view = useMemo<SignalsPageView>(
    () =>
      validViews.has(viewFromQuery as SignalsPageView)
        ? (viewFromQuery as SignalsPageView)
        : "legacy",
    [viewFromQuery],
  )

  useEffect(() => {
    if (symbolFromQuery) {
      setSelectedSymbol(symbolFromQuery)
    }
  }, [symbolFromQuery])

  useEffect(() => {
    if (validHorizons.has(horizonFromQuery)) {
      setHorizon(horizonFromQuery)
    }
  }, [horizonFromQuery])

  const handleViewChange = (nextView: SignalsPageView) => {
    if (nextView === view) return
    const nextParams = new URLSearchParams(searchParams.toString())
    nextParams.set("view", nextView)
    const query = nextParams.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] flex-col overflow-hidden">
      <div className="border-b bg-background/95 px-5 py-3 backdrop-blur supports-[backdrop-filter]:bg-background/75">
        <SignalsVersionToggle value={view} onChange={handleViewChange} />
      </div>

      <div className="min-h-0 flex-1">
        {view === "legacy" ? (
          <LegacySignalsView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            horizon={horizon}
            onHorizonChange={setHorizon}
          />
        ) : view === "factor_x_ta" ? (
          <FactorXTaSignalsView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            horizon={horizon}
            onHorizonChange={setHorizon}
          />
        ) : (
          <ExpandedSignalsView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            horizon={horizon}
            onHorizonChange={setHorizon}
          />
        )}
      </div>
    </div>
  )
}

export default function SignalsPage() {
  return (
    <Suspense fallback={<div className="p-5 text-sm text-muted-foreground">Chargement...</div>}>
      {isPublicDashboardOnly ? <PublicSignalsPage /> : <PrivateSignalsPage />}
    </Suspense>
  )
}
