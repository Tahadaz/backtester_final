"use client"

import { Suspense, useEffect, useMemo, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { ExpandedSignalsView } from "@/components/strategy/expanded-signals-view"
import { LegacySignalsView } from "@/components/strategy/legacy-signals-view"
import { PublicSignalsPage } from "@/components/strategy/public-signals-page"
import { SignalsVersionToggle } from "@/components/strategy/signals-version-toggle"
import { signalPageHorizon } from "@/lib/signal-evidence-url"
import type { ExpandedSignalsPageView, LegacySignalsPageView, SignalsPageView } from "@/components/strategy/signals-view-layout"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"

const viewAliases: Record<string, SignalsPageView> = {
  legacy: "legacy_ta_simple",
  expanded: "expanded_ta_simple",
  factor_x_ta: "expanded_factor_x_ta_simple",
}
const validViews = new Set<SignalsPageView>([
  "legacy_ta_simple",
  "expanded_ta_simple",
  "legacy_factor_x_ta_simple",
  "expanded_factor_x_ta_simple",
  "legacy_ta_combo",
  "expanded_ta_combo",
  "legacy_factor_x_ta_combo",
  "expanded_factor_x_ta_combo",
])
type SignalsTab = "technique" | "evidence" | "indicateurs" | "wfo" | "backtest"
const validTabs = new Set<SignalsTab>(["technique", "evidence", "indicateurs", "wfo", "backtest"])
const sourceAliases: Record<string, "auto" | "signal_engine" | "wfo"> = {
  auto: "auto",
  best: "auto",
  engine: "signal_engine",
  signal_engine: "signal_engine",
  wfo: "wfo",
}

function signalModeFromQuery(value: string | null): SignalsPageView | null {
  const token = String(value ?? "").trim().toLowerCase()
  if (!token) return null
  const normalized = viewAliases[token] ?? token
  return validViews.has(normalized as SignalsPageView) ? (normalized as SignalsPageView) : null
}

function selectedSignalVariantIdFromQuery(value: string | null): string | null {
  const token = String(value ?? "").trim()
  if (!token) return null
  if (signalModeFromQuery(token)) return null
  return token
}

function isLegacyView(view: SignalsPageView): view is LegacySignalsPageView {
  return view === "legacy" || view.startsWith("legacy_")
}

function PrivateSignalsPage() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const symbolFromQuery = (searchParams.get("symbol") ?? "").trim().toUpperCase()
  const horizonFromQuery = (searchParams.get("horizon") ?? "").trim().toLowerCase()
  const viewFromQuery = (searchParams.get("view") ?? "").trim().toLowerCase()
  const tabFromQuery = (searchParams.get("tab") ?? "").trim().toLowerCase()
  const sourceFromQuery = (searchParams.get("source") ?? "").trim().toLowerCase()
  const selectedVariantId = selectedSignalVariantIdFromQuery(searchParams.get("variant"))
  const evidenceVariant = signalModeFromQuery(searchParams.get("evidence_variant"))
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [horizon, setHorizon] = useState("weekly")

  const view = useMemo<SignalsPageView>(
    () => {
      return (
        signalModeFromQuery(viewFromQuery) ??
        signalModeFromQuery(searchParams.get("evidence_variant")) ??
        signalModeFromQuery(searchParams.get("variant")) ??
        "expanded_ta_simple"
      )
    },
    [searchParams, viewFromQuery],
  )
  const defaultTab = validTabs.has(tabFromQuery as SignalsTab) ? (tabFromQuery as SignalsTab) : undefined
  const evidenceSource = sourceAliases[sourceFromQuery] ?? "auto"

  useEffect(() => {
    if (symbolFromQuery) {
      setSelectedSymbol(symbolFromQuery)
    }
  }, [symbolFromQuery])

  useEffect(() => {
    if (horizonFromQuery) {
      setHorizon(signalPageHorizon(horizonFromQuery))
    }
  }, [horizonFromQuery])

  const handleViewChange = (nextView: SignalsPageView) => {
    if (nextView === view) return
    const nextParams = new URLSearchParams(searchParams.toString())
    nextParams.set("view", nextView)
    nextParams.delete("evidence_variant")
    nextParams.delete("variant")
    const query = nextParams.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }

  const topbarContent = (
    <SignalsVersionToggle value={view} onChange={handleViewChange} />
  )

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="min-h-0 flex-1">
        {isLegacyView(view) ? (
          <LegacySignalsView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            horizon={horizon}
            onHorizonChange={setHorizon}
            topbarContent={topbarContent}
            variant={view}
            defaultTab={defaultTab}
            evidenceSource={evidenceSource}
            evidenceVariant={evidenceVariant}
            selectedVariantId={selectedVariantId}
          />
        ) : (
          <ExpandedSignalsView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={setSelectedSymbol}
            horizon={horizon}
            onHorizonChange={setHorizon}
            topbarContent={topbarContent}
            variant={view as ExpandedSignalsPageView}
            defaultTab={defaultTab}
            evidenceSource={evidenceSource}
            evidenceVariant={evidenceVariant}
            selectedVariantId={selectedVariantId}
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
