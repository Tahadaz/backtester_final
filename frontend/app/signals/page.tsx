"use client"

import { Suspense, useCallback, useEffect, useMemo, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { Activity, ChartColumnIncreasing, Landmark } from "lucide-react"
import { ExpandedSignalsView } from "@/components/strategy/expanded-signals-view"
import { LegacySignalsView } from "@/components/strategy/legacy-signals-view"
import { PublicSignalsPage } from "@/components/strategy/public-signals-page"
import { SignalQuantitativeView } from "@/components/strategy/signal-quantitative-view"
import { SignalFundamentalView } from "@/components/strategy/signal-fundamental-view"
import { SignalsVersionToggle } from "@/components/strategy/signals-version-toggle"
import { signalPageHorizon } from "@/lib/signal-evidence-url"
import { cn } from "@/lib/utils"
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
type SignalsTab = "technique" | "evidence" | "indicateurs" | "wfo" | "backtest" | "portfolio"
const validTabs = new Set<SignalsTab>(["technique", "evidence", "indicateurs", "wfo", "portfolio"])
const sourceAliases: Record<string, "auto" | "signal_engine" | "wfo"> = {
  auto: "auto",
  best: "auto",
  engine: "signal_engine",
  signal_engine: "signal_engine",
  wfo: "wfo",
}
type SignalsAnalysisMode = "technical" | "fundamental" | "quantitative"

const analysisModeAliases: Record<string, SignalsAnalysisMode> = {
  ta: "technical",
  tech: "technical",
  technical: "technical",
  technique: "technical",
  fundamental: "fundamental",
  fundamentals: "fundamental",
  fondamental: "fundamental",
  fondamentale: "fundamental",
  fa: "fundamental",
  quantitative: "quantitative",
  quant: "quantitative",
  qa: "quantitative",
}

const analysisModes: Array<{
  value: SignalsAnalysisMode
  title: string
  description: string
  icon: typeof Activity
}> = [
  {
    value: "technical",
    title: "Analyse Technique",
    description: "Signaux TA, evidence, WFO",
    icon: Activity,
  },
  {
    value: "fundamental",
    title: "Analyse Fondamentale",
    description: "Valorisation, qualite, financiers",
    icon: Landmark,
  },
  {
    value: "quantitative",
    title: "Analyse Quantitative",
    description: "IC, facteurs, macro, stat-arb",
    icon: ChartColumnIncreasing,
  },
]

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

function analysisModeFromQuery(value: string | null): SignalsAnalysisMode {
  const token = String(value ?? "").trim().toLowerCase()
  return analysisModeAliases[token] ?? "technical"
}

function isLegacyView(view: SignalsPageView): view is LegacySignalsPageView {
  return view === "legacy" || view.startsWith("legacy_")
}

function SignalsAnalysisModeSwitcher({
  value,
  onChange,
}: {
  value: SignalsAnalysisMode
  onChange: (value: SignalsAnalysisMode) => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-2 overflow-x-auto border-b border-line bg-card px-4 py-2 max-md:px-3">
      <span className="mr-1 shrink-0 text-[10px] font-bold uppercase tracking-[0.09em] text-muted-foreground">
        Analyse
      </span>
      {analysisModes.map((mode) => {
        const Icon = mode.icon
        const active = value === mode.value
        return (
          <button
            key={mode.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(mode.value)}
            className={cn(
              "flex min-w-[190px] shrink-0 items-center gap-2.5 rounded-[10px] border px-2 py-1.5 pr-3 text-left text-muted-foreground transition-colors hover:bg-bg3 hover:text-foreground",
              active &&
                "border-[oklch(0.72_0.09_260)] bg-[oklch(0.94_0.04_260_/_0.45)] text-[oklch(0.30_0.14_260)]",
            )}
          >
            <span
              className={cn(
                "grid h-7 w-7 shrink-0 place-items-center rounded-md bg-bg2",
                active && "bg-primary text-primary-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
            </span>
            <span className="min-w-0">
              <span className="block truncate text-xs font-semibold leading-tight">{mode.title}</span>
              <span
                className={cn(
                  "mt-0.5 block truncate text-[10px] leading-tight text-muted-foreground",
                  active && "text-[oklch(0.45_0.10_260)]",
                )}
              >
                {mode.description}
              </span>
            </span>
          </button>
        )
      })}
    </div>
  )
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
  const analysisMode = analysisModeFromQuery(searchParams.get("mode"))

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

  const handleAnalysisModeChange = (nextMode: SignalsAnalysisMode) => {
    if (nextMode === analysisMode) return
    const nextParams = new URLSearchParams(searchParams.toString())
    if (nextMode === "technical") {
      nextParams.delete("mode")
    } else {
      nextParams.set("mode", nextMode)
    }
    const query = nextParams.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }

  const updateSearchParams = useCallback(
    (updates: Record<string, string | null>) => {
      const nextParams = new URLSearchParams(searchParams.toString())
      for (const [key, value] of Object.entries(updates)) {
        if (value == null || value === "") {
          nextParams.delete(key)
        } else {
          nextParams.set(key, value)
        }
      }
      const query = nextParams.toString()
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  const handleSelectSymbol = useCallback((symbol: string) => {
    setSelectedSymbol(symbol)
    updateSearchParams({ symbol })
  }, [updateSearchParams])

  const handleTabChange = useCallback((tab: string) => {
    updateSearchParams({ tab: tab === "technique" ? null : tab })
  }, [updateSearchParams])

  const topbarContent = (
    <SignalsVersionToggle value={view} onChange={handleViewChange} />
  )

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <SignalsAnalysisModeSwitcher value={analysisMode} onChange={handleAnalysisModeChange} />

      <div className="min-h-0 flex-1 overflow-hidden">
        {analysisMode === "technical" && isLegacyView(view) ? (
          <LegacySignalsView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={handleSelectSymbol}
            horizon={horizon}
            onHorizonChange={setHorizon}
            topbarContent={topbarContent}
            variant={view}
            defaultTab={defaultTab}
            onTabChange={handleTabChange}
            evidenceSource={evidenceSource}
            evidenceVariant={evidenceVariant}
            selectedVariantId={selectedVariantId}
          />
        ) : null}

        {analysisMode === "technical" && !isLegacyView(view) ? (
          <ExpandedSignalsView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={handleSelectSymbol}
            horizon={horizon}
            onHorizonChange={setHorizon}
            topbarContent={topbarContent}
            variant={view as ExpandedSignalsPageView}
            defaultTab={defaultTab}
            onTabChange={handleTabChange}
            evidenceSource={evidenceSource}
            evidenceVariant={evidenceVariant}
            selectedVariantId={selectedVariantId}
          />
        ) : null}

        {analysisMode === "fundamental" ? (
          <SignalFundamentalView
            selectedSymbol={selectedSymbol}
            onSelectSymbol={handleSelectSymbol}
            searchParams={searchParams}
            updateSearchParams={updateSearchParams}
          />
        ) : null}

        {analysisMode === "quantitative" ? (
          <SignalQuantitativeView selectedSymbol={selectedSymbol} onSelectSymbol={handleSelectSymbol} />
        ) : null}
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
