"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import useSWR, { useSWRConfig } from "swr"
import { AlertTriangle, Landmark } from "lucide-react"
import {
  getFundamentalMethodology,
  getFundamentalSensitivity,
  getFundamentalStockDetail,
  getFundamentalUniverse,
  updateFundamentalAssumptions,
  updateFundamentalDeskAssumptions,
  type FundamentalMethodology,
  type FundamentalSensitivity,
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { FUND_TABS, FUND_TAB_PURPOSE } from "./lib/constants"
import { asNumber } from "./lib/formatters"
import { useOptionalSelectedComparableView } from "./panels/comparables"
import { ResearchTicket } from "./research-ticket"
import { ComparableModelSummary, DetailTab, FundamentalHorizon, Scenario, SignalFundamentalViewProps, ValuationSelectionSummary, WeightMode } from "./lib/types"
import { EstimatesAssumptionsTab } from "./tabs/estimates-tab"
import { ComparablesQualityTab } from "./tabs/quality-tab"
import { SyntheseTab } from "./tabs/synthese-tab"
import { ValuationTab } from "./tabs/valuation-tab"
import { UniverseScreen } from "./universe-screen"
import { applyRatioDraftToValuationRows, buildValuationSelectionSummary, comparableModelSummary, editableAssumptionDraft, emptyComparableModelSummary, enabledRelativeValuationMetricsForDraft, horizonFromQuery, isLiquidFundamentalRow, isMasiFundamentalRow, parseExcludedModelIds, readValuationExclusionsBySymbol, scenarioFromQuery, sortValuationRows, tabFromQuery, valuationSymbolKey, weightModeFromQuery, writeValuationExclusionsBySymbol } from "./lib/view-models"

export function SignalFundamentalView({
  selectedSymbol,
  onSelectSymbol,
  searchParams,
  updateSearchParams,
}: SignalFundamentalViewProps) {
  const { mutate: mutateGlobal } = useSWRConfig()
  const scenarioParam = searchParams.get("scenario")
  const scenario = scenarioFromQuery(scenarioParam)
  const apiScenario = scenarioParam ? scenario : "base"
  const activeTab = tabFromQuery(searchParams.get("fund_tab"))
  const selectedHorizon = horizonFromQuery(searchParams.get("fund_horizon"))
  const selectedComparableBenchmarkId = searchParams.get("fund_benchmark") || "sector"
  const excludedValuationModelsParam = searchParams.get("fund_excluded_models")
  const weightModeParam = searchParams.get("fund_weight_mode")
  const weightMode = weightModeFromQuery(weightModeParam)
  const selectedSymbolKey = valuationSymbolKey(selectedSymbol)
  const [valuationExclusionsBySymbol, setValuationExclusionsBySymbol] = useState<Record<string, string>>(() => readValuationExclusionsBySymbol())
  const hydratedExclusionSymbolsRef = useRef(new Set<string>())
  const isFirstSymbolRef = useRef(true)
  const [assumptionDraft, setAssumptionDraft] = useState<Record<string, number>>({})
  const [isSaving, setIsSaving] = useState(false)
  const [isDeskSaving, setIsDeskSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [liquidityFilter, setLiquidityFilter] = useState(true)

  const {
    data: universeRows,
    error: universeError,
    isLoading: isUniverseLoading,
    isValidating: isUniverseValidating,
    mutate: mutateUniverse,
  } = useSWR<FundamentalUniverseRow[]>(["fundamentals-universe", apiScenario], () => getFundamentalUniverse({ scenario: apiScenario }), {
    keepPreviousData: true,
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  })

  const { data: methodology } = useSWR<FundamentalMethodology>("fundamentals-methodology", getFundamentalMethodology, {
    revalidateOnFocus: false,
    dedupingInterval: 300_000,
  })

  const rows = useMemo(() => (universeRows ?? []).filter(isMasiFundamentalRow), [universeRows])
  const visibleUniverseRows = useMemo(
    () => (liquidityFilter ? rows.filter(isLiquidFundamentalRow) : rows),
    [liquidityFilter, rows],
  )

  // One-directional hydration: URL → storage only on genuine first load / deep-link.
  // Never reverts user actions. Subsequent symbol switches are seeded by handleSelectSymbol.
  useEffect(() => {
    if (!selectedSymbolKey) return
    if (hydratedExclusionSymbolsRef.current.has(selectedSymbolKey)) return
    hydratedExclusionSymbolsRef.current.add(selectedSymbolKey)

    // Only hydrate from URL for the very first symbol (page load with deep-link).
    // For subsequent symbols the URL was already seeded from storage by handleSelectSymbol.
    if (!isFirstSymbolRef.current) return
    isFirstSymbolRef.current = false

    const urlValue = excludedValuationModelsParam?.trim() || null
    if (!urlValue) return

    const storedValue = valuationExclusionsBySymbol[selectedSymbolKey] ?? null
    if (storedValue === urlValue) return

    const next = { ...valuationExclusionsBySymbol, [selectedSymbolKey]: urlValue }
    setValuationExclusionsBySymbol(next)
    writeValuationExclusionsBySymbol(next)
  }, [excludedValuationModelsParam, selectedSymbolKey, valuationExclusionsBySymbol])

  useEffect(() => {
    if (visibleUniverseRows.length === 0) return
    if (!selectedSymbol) {
      onSelectSymbol(visibleUniverseRows[0].symbol)
    }
  }, [onSelectSymbol, selectedSymbol, visibleUniverseRows])

  const selectedRow = useMemo(() => rows.find((row) => row.symbol === selectedSymbol) ?? null, [rows, selectedSymbol])
  const selectedSymbolHiddenByLiquidity = Boolean(
    selectedSymbol &&
      liquidityFilter &&
      rows.some((row) => row.symbol === selectedSymbol) &&
      !visibleUniverseRows.some((row) => row.symbol === selectedSymbol),
  )

  const {
    data: detailRaw,
    error: detailError,
    isLoading: isDetailLoading,
    isValidating: isDetailValidating,
    mutate: mutateDetail,
  } = useSWR<FundamentalStockDetail>(selectedSymbol ? ["fundamental-detail", selectedSymbol, apiScenario] : null, () => getFundamentalStockDetail(selectedSymbol as string, apiScenario), {
    keepPreviousData: true,
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  })

  const detail = detailRaw?.symbol === selectedSymbol ? detailRaw : null
  const resolvedScenario = scenarioParam ? scenario : scenarioFromQuery(detail?.viewed_scenario ?? detail?.ensemble?.scenario ?? "base")
  const sensitivityScenario = scenarioParam ? scenario : detail ? resolvedScenario : null

  const {
    data: sensitivity,
    isLoading: isSensitivityLoading,
    mutate: mutateSensitivity,
  } = useSWR<FundamentalSensitivity>(
    selectedSymbol && activeTab === "valuation" && sensitivityScenario ? ["fundamental-sensitivity", selectedSymbol, sensitivityScenario] : null,
    () => getFundamentalSensitivity(selectedSymbol as string, sensitivityScenario as Scenario),
    {
      keepPreviousData: true,
      revalidateOnFocus: false,
      dedupingInterval: 60_000,
    },
  )

  const visibleValuations = useMemo(
    () => detail ? sortValuationRows(applyRatioDraftToValuationRows(detail.valuations, detail, assumptionDraft)) : [],
    [assumptionDraft, detail],
  )
  const excludedValuationModelsForSelected = selectedSymbolKey ? valuationExclusionsBySymbol[selectedSymbolKey] ?? null : null
  const excludedValuationModelIds = useMemo(() => parseExcludedModelIds(excludedValuationModelsForSelected), [excludedValuationModelsForSelected])
  const selectedCurrentPrice = detail ? detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price) : null
  const {
    comparables: selectedComparableView,
    isLoading: isValuationComparableLoading,
  } = useOptionalSelectedComparableView(detail, selectedRow, rows, selectedComparableBenchmarkId)
  const relativeValuationMetricKeys = useMemo(() => enabledRelativeValuationMetricsForDraft(detail, assumptionDraft), [assumptionDraft, detail])
  const valuationComparableSummary = useMemo<ComparableModelSummary>(
    () => selectedComparableView
      ? comparableModelSummary(selectedComparableView, selectedCurrentPrice, relativeValuationMetricKeys)
      : emptyComparableModelSummary(),
    [relativeValuationMetricKeys, selectedComparableView, selectedCurrentPrice],
  )
  const valuationSelectionSummary = useMemo<ValuationSelectionSummary>(
    () => detail
      ? buildValuationSelectionSummary({
        rows: visibleValuations,
        excludedModelIds: excludedValuationModelIds,
        comparableSummary: valuationComparableSummary,
        currentPrice: selectedCurrentPrice,
        weightMode,
      })
      : {
        fairValue: null,
        low: null,
        high: null,
        upside: null,
        includedCount: 0,
        usableCount: 0,
        weightSource: "ic fallback",
        effectiveWeights: new Map(),
      },
    [detail, excludedValuationModelIds, selectedCurrentPrice, valuationComparableSummary, visibleValuations, weightMode],
  )
  useEffect(() => {
    setAssumptionDraft({})
  }, [detail?.symbol, resolvedScenario])

  function setScenario(next: Scenario) {
    updateSearchParams({ scenario: next })
  }

  function setActiveTab(next: DetailTab) {
    updateSearchParams({ fund_tab: next === "synthese" ? null : next })
  }

  function handleSyntheseNavigate(next: DetailTab, anchor?: string) {
    setActiveTab(next)
    if (!anchor) return
    window.setTimeout(() => {
      document.getElementById(anchor)?.scrollIntoView({ behavior: "smooth", block: "start" })
    }, 60)
  }

  function setWeightMode(next: WeightMode) {
    updateSearchParams({ fund_weight_mode: next === "ic" ? null : next })
  }

  function setFundamentalHorizon(next: FundamentalHorizon) {
    updateSearchParams({ fund_horizon: next === "year" ? null : next })
  }

  const setSelectedComparableBenchmarkId = useCallback(
    (next: string) => {
      updateSearchParams({ fund_benchmark: next === "sector" ? null : next })
    },
    [updateSearchParams],
  )

  const setExcludedValuationModelsParam = useCallback(
    (next: string | null) => {
      if (!selectedSymbolKey) return
      setValuationExclusionsBySymbol((current) => {
        const updated = { ...current }
        if (next) updated[selectedSymbolKey] = next
        else delete updated[selectedSymbolKey]
        writeValuationExclusionsBySymbol(updated)
        return updated
      })
      updateSearchParams({ fund_excluded_models: next })
    },
    [selectedSymbolKey, updateSearchParams],
  )

  function handleSelectSymbol(symbol: string) {
    const nextSymbolKey = valuationSymbolKey(symbol)
    const nextExcludedModels = nextSymbolKey ? valuationExclusionsBySymbol[nextSymbolKey] ?? null : null
    onSelectSymbol(symbol)
    // fund_tab is intentionally left alone here so the active tab survives symbol switches (brief 57 §3.2).
    updateSearchParams({ scenario: null, fund_excluded_models: nextExcludedModels })
  }

  async function saveAssumptions() {
    if (!selectedSymbol || !detail) return
    const payload = editableAssumptionDraft(methodology, assumptionDraft)
    if (!Object.keys(payload).length) return
    setIsSaving(true)
    setSaveError(null)
    try {
      await updateFundamentalAssumptions(selectedSymbol, resolvedScenario, payload)
      setAssumptionDraft({})
      await Promise.all([mutateDetail(), mutateUniverse(), mutateSensitivity(), mutateGlobal(["fundamental-resolved-assumptions", selectedSymbol])])
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Echec de l'enregistrement des hypotheses")
    } finally {
      setIsSaving(false)
    }
  }

  async function saveDeskAssumptions() {
    const payload = editableAssumptionDraft(methodology, assumptionDraft)
    if (!Object.keys(payload).length) return
    setIsDeskSaving(true)
    setSaveError(null)
    try {
      await updateFundamentalDeskAssumptions(resolvedScenario, payload)
      setAssumptionDraft({})
      await Promise.all([mutateDetail(), mutateUniverse(), mutateSensitivity(), selectedSymbol ? mutateGlobal(["fundamental-resolved-assumptions", selectedSymbol]) : Promise.resolve()])
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Echec de l'enregistrement desk")
    } finally {
      setIsDeskSaving(false)
    }
  }

  const displayError = universeError ?? detailError

  return (
    <ResizablePanelGroup
      direction="horizontal"
      autoSaveId="signals-fundamental-main-layout-v2"
      className="signal-fund-layout max-xl:block max-xl:h-auto"
    >
      <ResizablePanel defaultSize={28} minSize={18} maxSize={45} className="min-w-0 max-xl:!h-auto">
        <UniverseScreen
          rows={visibleUniverseRows}
          totalRows={rows.length}
          liquidityFilter={liquidityFilter}
          selectedSymbol={selectedSymbol}
          isLoading={isUniverseLoading}
          onSelect={handleSelectSymbol}
          onLiquidityFilterChange={setLiquidityFilter}
        />
      </ResizablePanel>

      <ResizableHandle withHandle className="max-xl:hidden" />

      <ResizablePanel defaultSize={72} minSize={45} className="min-w-0 max-xl:!h-auto">
        <section className="signal-fund-detail">
          {displayError ? (
            <div className="m-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{displayError instanceof Error ? displayError.message : "Fundamentals unavailable."}</span>
            </div>
          ) : null}

          {selectedSymbolHiddenByLiquidity ? (
            <div className="m-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{selectedSymbol} is selected but hidden from the left universe by the ADV20 liquidity filter.</span>
            </div>
          ) : null}

          {!selectedSymbol ? (
            <div className="signal-fund-empty">
              <Landmark className="h-10 w-10 opacity-[0.15]" />
              Selectionnez un titre pour afficher la recherche fondamentale.
            </div>
          ) : (
            <div className="signal-fund-detail-shell">
              <ResearchTicket
                row={selectedRow}
                detail={detail}
                isRefreshing={isDetailValidating || isUniverseValidating}
                selectedHorizon={selectedHorizon}
                onHorizonChange={setFundamentalHorizon}
              />

              <div className="signal-fund-tab-pane">
                <div className="signal-fund-tabs">
                  {FUND_TABS.map((item) => (
                    <button key={item.value} type="button" className={cn("signal-fund-tab", activeTab === item.value && "active")} onClick={() => setActiveTab(item.value)}>
                      {item.label}
                    </button>
                  ))}
                </div>

                <p className="signal-fund-purpose">{FUND_TAB_PURPOSE[activeTab]}</p>

                <div className="signal-fund-body">
                  {isDetailLoading && !detail ? (
                    <div className="space-y-3">
                      <Skeleton className="h-28 w-full" />
                      <Skeleton className="h-52 w-full" />
                    </div>
                  ) : !detail ? (
                    <div className="signal-fund-empty">
                      <Landmark className="h-10 w-10 opacity-[0.15]" />
                      No detail available for {selectedSymbol}.
                    </div>
                  ) : (
                    <>
                      {saveError ? <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">{saveError}</div> : null}
                      {activeTab === "synthese" ? (
                        <SyntheseTab detail={detail} row={selectedRow} rows={rows} onNavigate={handleSyntheseNavigate} />
                      ) : null}
                      {activeTab === "valuation" ? (
                        <div id="valorisation-section">
                          <ValuationTab
                            detail={detail}
                            row={selectedRow}
                            rows={rows}
                            scenario={resolvedScenario}
                            sensitivity={sensitivity}
                            isSensitivityLoading={isSensitivityLoading}
                            onScenarioChange={setScenario}
                            assumptionDraft={assumptionDraft}
                            onAssumptionDraftChange={setAssumptionDraft}
                            onSaveAssumptions={() => void saveAssumptions()}
                            isSaving={isSaving}
                            selectedComparatorId={selectedComparableBenchmarkId}
                            onSelectedComparatorIdChange={setSelectedComparableBenchmarkId}
                            onExcludedModelParamChange={setExcludedValuationModelsParam}
                            visibleValuations={visibleValuations}
                            excludedModelIds={excludedValuationModelIds}
                            comparableSummary={valuationComparableSummary}
                            isComparableSummaryLoading={isValuationComparableLoading}
                            selectionSummary={valuationSelectionSummary}
                            weightMode={weightMode}
                            onWeightModeChange={setWeightMode}
                            onNavigate={handleSyntheseNavigate}
                          />
                        </div>
                      ) : null}
                      {activeTab === "estimates" ? (
                        <EstimatesAssumptionsTab
                          detail={detail}
                          row={selectedRow}
                          methodology={methodology}
                          scenario={resolvedScenario}
                          draft={assumptionDraft}
                          onDraftChange={setAssumptionDraft}
                          onSaveSymbol={() => void saveAssumptions()}
                          onSaveDesk={() => void saveDeskAssumptions()}
                          isSaving={isSaving}
                          isDeskSaving={isDeskSaving}
                        />
                      ) : null}
                      {activeTab === "quality" ? (
                        <ComparablesQualityTab
                          detail={detail}
                          row={selectedRow}
                          rows={rows}
                          selectedComparatorId={selectedComparableBenchmarkId}
                          onSelectedComparatorIdChange={setSelectedComparableBenchmarkId}
                        />
                      ) : null}
                    </>
                  )}
                </div>
              </div>
            </div>
          )}
        </section>
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}

