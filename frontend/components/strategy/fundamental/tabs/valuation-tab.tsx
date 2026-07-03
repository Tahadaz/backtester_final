"use client"

import { Fragment, useCallback, useMemo, useState } from "react"
import { ChevronDown, ChevronRight, Loader2, Save } from "lucide-react"
import {
  type FundamentalSensitivity,
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
  type FundamentalValuationResult,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { buildValuationModelStory } from "@/lib/fundamental-valuation-story-utils.js"
import { cn } from "@/lib/utils"
import { TriangulationBand } from "@/components/strategy/triangulation-band"
import { ASSUMPTION_FIELDS, JUSTIFIED_MULTIPLE_RATIOS, JUSTIFIED_MULTIPLE_RATIO_DEFAULT_MASK, JUSTIFIED_MULTIPLE_RATIO_MASK_KEY, MODEL_LABELS, MODEL_ORDER, RELATIVE_MULTIPLE_RATIOS, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK, RELATIVE_MULTIPLE_RATIO_MASK_KEY, SCENARIOS } from "../lib/constants"
import { asNumber, asRecord, boundedMask, comparableMetricLabel, confidenceClass, fmtMoney, fmtNumber, fmtPct, fmtRatio, formatProjectionValue } from "../lib/formatters"
import { ComparableBenchmarkPanel } from "../panels/comparables"
import { CostOfCapitalBuildUp } from "../panels/cost-of-capital"
import { DcfMethodView } from "../panels/dcf-method-view"
import { ModelStoryPanel } from "../panels/model-story"
import { CoverageRatingPanel } from "../panels/coverage-rating"
import { ModelSensitivityPanel, SensitivityHeatmap } from "../panels/sensitivity"
import { FundCard, ModelValueGrid, StatTile, StatementEvidenceCard } from "../shared/cards"
import { DriverEvidenceChart, FootballField, GrowthDecompositionChart } from "../shared/charts"
import { ComparableModelSummary, ModelStory, MultipleRatioDefinition, Scenario, ValuationSelectionSummary, WeightMode } from "../lib/types"
import { EstimatesTab } from "../tabs/estimates-tab"
import { currentPriceForValuationRow, dcfModeForModel, detailRatioMask, driverProjectedValue, enabledRatioKeys, fairValueForValuationRow, instantiatedFormula, outputItems, projectedValue, projectedYears, projectionDriverRows, projectionFromDetail, projectionStatementRows, serializeExcludedModelIds, sortValuationRows, statementEvidence, technicalInputItems, upsideForFairValue, valuationAssumptionItems, valuationFormulaMeta, valuationMethods } from "../lib/view-models"

function ComparableValuationCells({
  currentPrice,
  summary,
  isLoading,
}: {
  currentPrice: number | null | undefined
  summary: ComparableModelSummary
  isLoading: boolean
}) {
  const current = asNumber(currentPrice)
  const upside = summary.fairValue != null && current != null && current > 0 ? summary.fairValue / current - 1 : summary.upside
  return (
    <>
      <td className="r font-mono">{isLoading && summary.fairValue == null ? "..." : fmtMoney(summary.fairValue, 1)}</td>
      <td className="r font-mono">{fmtMoney(currentPrice, 1)}</td>
      <td className={cn("r font-mono font-semibold", (upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>
        {isLoading && upside == null ? "..." : fmtPct(upside)}
      </td>
    </>
  )
}


function ReverseDcfSummaryCells({ row, detail }: { row: FundamentalValuationResult; detail: FundamentalStockDetail }) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const impliedGrowth = asNumber(outputs.implied_perpetual_growth)
  const terminalGrowth = asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth)
  const spread = impliedGrowth != null && terminalGrowth != null ? impliedGrowth - terminalGrowth : null
  return (
    <>
      <td className="r font-mono font-semibold" title="Reverse DCF output: implied perpetual-growth assumption, not fair value">
        g {fmtPct(impliedGrowth, 2, false)}
      </td>
      <td className="r font-mono" title="Input used by the diagnostic">
        WACC {fmtPct(asNumber(inputs.wacc), 2, false)}
      </td>
      <td className={cn("r font-mono font-semibold", (spread ?? 0) > 0 ? "t-neg" : "t-pos")} title="Gap versus model terminal growth assumption">
        vs g {fmtPct(spread, 2, false)}
      </td>
    </>
  )
}


function ComparableValuationTiles({
  detail,
  currentPrice,
  weight,
  summary,
  isLoading,
  isIncluded,
}: {
  detail: FundamentalStockDetail
  currentPrice: number | null | undefined
  weight: number | null | undefined
  summary: ComparableModelSummary
  isLoading: boolean
  isIncluded: boolean
}) {
  const current = asNumber(currentPrice)
  const upside = summary.fairValue != null && current != null && current > 0 ? summary.fairValue / current - 1 : summary.upside
  const currency = detail.ensemble?.currency ?? "MAD"
  return (
    <div className="valuation-method-metrics">
      <StatTile
        label="Model FV"
        value={isLoading && summary.fairValue == null ? "..." : `${fmtMoney(summary.fairValue, 1)} ${currency}`}
        sub={summary.peerCount ? `${summary.peerCount} comparables` : `${summary.count} multiples`}
      />
      {summary.impliedPrices.map((item) => (
        <StatTile
          key={item.metric}
          label={`FV ${comparableMetricLabel(item.metric)}`}
          value={`${fmtMoney(item.fairValue, 1)} ${currency}`}
          sub={`pairs ${fmtRatio(item.benchmark, 1)} / titre ${fmtRatio(item.selectedValue, 1)}`}
        />
      ))}
      <StatTile label="Current" value={currentPrice != null ? `${fmtMoney(currentPrice, 1)} ${currency}` : "-"} />
      <StatTile label="Upside" value={isLoading && upside == null ? "..." : fmtPct(upside)} tone={(upside ?? 0) >= 0 ? "t-pos" : "t-neg"} />
      <StatTile label="Weight" value={!isIncluded ? "Excluded" : weight == null ? "-" : `${(weight * 100).toFixed(0)}%`} />
    </div>
  )
}


function ReverseDcfDiagnosticTiles({
  row,
  detail,
  effectiveWeight,
  isIncluded,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  effectiveWeight: number | null
  isIncluded: boolean
}) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const impliedGrowth = asNumber(outputs.implied_perpetual_growth)
  const terminalGrowth = asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth)
  const spread = impliedGrowth != null && terminalGrowth != null ? impliedGrowth - terminalGrowth : null
  return (
    <div className="valuation-method-metrics reverse-dcf-metrics">
      <StatTile label="Resultat" value={fmtPct(impliedGrowth, 2, false)} sub="g implicite, pas un prix" />
      <StatTile label="WACC" value={fmtPct(asNumber(inputs.wacc), 2, false)} sub="hypothese" />
      <StatTile label="FCF yield" value={fmtPct(asNumber(inputs.fcf_yield), 2, false)} sub="input marche" />
      <StatTile label="Ecart vs g modele" value={fmtPct(spread, 2, false)} tone={(spread ?? 0) > 0 ? "t-neg" : "t-pos"} sub={!isIncluded && row.family !== "diagnostic" ? "Excluded" : effectiveWeight == null ? "diagnostic" : `${(effectiveWeight * 100).toFixed(0)}%`} />
    </div>
  )
}


function MultipleRatioSelectionPanel({
  row,
  detail,
  draft,
  onDraftChange,
  onSave,
  isSaving,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSave: () => void
  isSaving: boolean
}) {
  const isJustified = row.model === "justified_multiples"
  const definitions = isJustified ? JUSTIFIED_MULTIPLE_RATIOS : row.model === "relative_multiples" ? RELATIVE_MULTIPLE_RATIOS : []
  if (!definitions.length) return null

  const maskKey = isJustified ? JUSTIFIED_MULTIPLE_RATIO_MASK_KEY : RELATIVE_MULTIPLE_RATIO_MASK_KEY
  const fallback = isJustified ? JUSTIFIED_MULTIPLE_RATIO_DEFAULT_MASK : RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK
  const currentMask = detailRatioMask(detail, {}, maskKey, fallback, fallback)
  const activeMask = detailRatioMask(detail, draft, maskKey, fallback, fallback)
  const selectedCount = enabledRatioKeys(definitions, activeMask).length
  const hasPendingChange = draft[maskKey] != null && activeMask !== currentMask

  const setMask = (nextMask: number) => {
    const bounded = boundedMask(nextMask, fallback, fallback)
    const next = { ...draft }
    if (bounded === currentMask) delete next[maskKey]
    else next[maskKey] = bounded
    onDraftChange(next)
  }

  const toggleRatio = (definition: MultipleRatioDefinition, checked: boolean) => {
    const nextMask = checked ? activeMask | definition.bit : activeMask & ~definition.bit
    setMask(nextMask)
  }

  return (
    <div className="valuation-ratio-selection valuation-mini-block">
      <div className="driver-evidence-head">
        <span className="valuation-mini-title">Ratios retenus dans le modele</span>
        <span>{selectedCount}/{definitions.length} actifs{hasPendingChange ? " - non enregistre" : ""}</span>
      </div>
      <div className="valuation-ratio-toggle-grid">
        {definitions.map((definition) => {
          const checked = (activeMask & definition.bit) !== 0
          return (
            <label key={definition.key} className={cn("valuation-model-toggle", checked && "active")}>
              <input
                type="checkbox"
                checked={checked}
                disabled={isSaving}
                onChange={(event) => toggleRatio(definition, event.target.checked)}
              />
              <span className="valuation-model-toggle-main">
                <strong>{definition.label}</strong>
                <em>{definition.key}</em>
              </span>
              <span className="valuation-model-toggle-weight">{checked ? "On" : "Off"}</span>
            </label>
          )
        })}
      </div>
      <div className="valuation-model-actions">
        <button type="button" onClick={() => setMask(fallback)} disabled={isSaving || activeMask === fallback}>Tous</button>
        <button type="button" onClick={() => setMask(0)} disabled={isSaving || activeMask === 0}>Aucun</button>
        <Button type="button" size="sm" onClick={onSave} disabled={!hasPendingChange || isSaving}>
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {isSaving ? "Enregistrement" : "Enregistrer selection"}
        </Button>
      </div>
    </div>
  )
}


function ValuationMethodCard({
  row,
  detail,
  selectedRow,
  universeRows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
  comparableSummary,
  isComparableSummaryLoading,
  isIncluded,
  effectiveWeight,
  sensitivity,
  assumptionDraft,
  onAssumptionDraftChange,
  onSaveAssumptions,
  isSaving,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  selectedRow: FundamentalUniverseRow | null
  universeRows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  isIncluded: boolean
  effectiveWeight: number | null
  sensitivity?: FundamentalSensitivity
  assumptionDraft: Record<string, number>
  onAssumptionDraftChange: (draft: Record<string, number>) => void
  onSaveAssumptions: () => void
  isSaving: boolean
}) {
  const dcfMode = dcfModeForModel(row.model)
  if (dcfMode) {
    return (
      <DcfMethodView
        row={row}
        detail={detail}
        isIncluded={isIncluded}
        effectiveWeight={effectiveWeight}
        sensitivity={sensitivity}
        dcfMode={dcfMode}
      />
    )
  }

  const meta = valuationFormulaMeta(row.model)
  const statementGroups = statementEvidence(detail, row.model)
  const assumptions = valuationAssumptionItems(row, detail)
  const inputs = technicalInputItems(row)
  const outputs = outputItems(row)
  const formulaValues = instantiatedFormula(row, detail)
  const story = buildValuationModelStory(row, detail) as ModelStory | null
  const isUnavailable = row.confidence === "unavailable"
  const isComparablesModel = row.model === "relative_multiples"
  const isReverseDcfModel = row.model === "reverse_dcf"
  const effectiveFairValue = fairValueForValuationRow(row, isComparablesModel ? comparableSummary : null)
  const fairValue = effectiveFairValue != null ? `${fmtMoney(effectiveFairValue, 1)} ${row.currency ?? detail.ensemble?.currency ?? "MAD"}` : "-"
  const currentPrice = row.current_price != null ? `${fmtMoney(row.current_price, 1)} ${row.currency ?? detail.ensemble?.currency ?? "MAD"}` : "-"
  const displayUpside = upsideForFairValue(effectiveFairValue, currentPriceForValuationRow(row, detail)) ?? row.upside_pct

  return (
    <section className={cn("valuation-method-card", isUnavailable && "unavailable", !isIncluded && row.family !== "diagnostic" && "excluded")}>
      <div className="valuation-method-top">
        <div>
          <div className="valuation-method-title-row">
            <h4>{MODEL_LABELS[row.model] ?? row.model}</h4>
            <span className={cn("signal-conf-badge", confidenceClass(row.confidence))}>
              {row.confidence}
              {row.is_proxy ? " proxy" : ""}
            </span>
          </div>
          <p>{row.methodology ?? meta.explanation}</p>
        </div>
        {isComparablesModel ? (
          <ComparableValuationTiles
            detail={detail}
            currentPrice={row.current_price}
            weight={effectiveWeight}
            summary={comparableSummary}
            isLoading={isComparableSummaryLoading}
            isIncluded={isIncluded}
          />
        ) : isReverseDcfModel ? (
          <ReverseDcfDiagnosticTiles row={row} detail={detail} effectiveWeight={effectiveWeight} isIncluded={isIncluded} />
        ) : (
          <div className="valuation-method-metrics">
            <StatTile label="Fair value" value={fairValue} />
            <StatTile label="Current" value={currentPrice} />
            <StatTile label="Upside" value={fmtPct(displayUpside)} tone={(displayUpside ?? 0) >= 0 ? "t-pos" : "t-neg"} />
            <StatTile label="Weight" value={!isIncluded && row.family !== "diagnostic" ? "Excluded" : effectiveWeight == null ? "-" : `${(effectiveWeight * 100).toFixed(0)}%`} />
          </div>
        )}
      </div>

      <div className="valuation-formula-panel">
        <div className="valuation-formula-eyebrow">Formule utilisee</div>
        <div className="valuation-formula-line">{formulaValues ?? meta.formula}</div>
        {formulaValues ? <div className="valuation-formula-sub">{meta.formula}</div> : null}
        {meta.secondaryFormula ? <div className="valuation-formula-sub">{meta.secondaryFormula}</div> : null}
        <p>{meta.explanation}</p>
      </div>

      <MultipleRatioSelectionPanel
        row={row}
        detail={detail}
        draft={assumptionDraft}
        onDraftChange={onAssumptionDraftChange}
        onSave={onSaveAssumptions}
        isSaving={isSaving}
      />

      {story ? <ModelStoryPanel story={story} /> : null}

      {isComparablesModel ? null : <CostOfCapitalBuildUp detail={detail} row={row} />}

      {isComparablesModel ? (
        <ComparableBenchmarkPanel
          detail={detail}
          row={selectedRow}
          rows={universeRows}
          selectedComparatorId={selectedComparatorId}
          onSelectedComparatorIdChange={onSelectedComparatorIdChange}
          embedded
          title="Comparables - modele principal"
        />
      ) : null}

      <ModelSensitivityPanel row={row} detail={detail} sensitivity={sensitivity} />

      <div className="valuation-method-grid">
        <ModelValueGrid title="Hypotheses du modele" items={assumptions} empty="No scenario assumptions persisted." />
      </div>

      <details className="dcf-raw-disclosure model-raw-disclosure">
        <summary>Donnees brutes (avance)</summary>
        <div className="valuation-method-grid">
          <ModelValueGrid title="Inputs modele" items={inputs} empty="No model inputs persisted." />
          <ModelValueGrid title="Outputs calcules" items={outputs} empty="No additional output persisted." />
        </div>
        <div>
          <div className="valuation-subtitle">Donnees 3 etats utilisees</div>
          <div className="valuation-statement-grid">
            {statementGroups.map((group) => (
              <StatementEvidenceCard key={group.key} group={group} />
            ))}
          </div>
        </div>
      </details>

      <div className="valuation-warning-row">
        <span className="valuation-warning-label">Warnings</span>
        <div className="flex flex-wrap gap-1.5">
          {row.warnings.length ? row.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{warning}</span>) : <span className="text-xs text-muted-foreground">No warnings.</span>}
        </div>
      </div>
    </section>
  )
}


function ValuationMethodRows({
  rows,
  detail,
  selectedRow,
  universeRows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
  excludedModelIds,
  onModelIncludedChange,
  effectiveWeights,
  comparableSummary,
  isComparableSummaryLoading,
  sensitivity,
  assumptionDraft,
  onAssumptionDraftChange,
  onSaveAssumptions,
  isSaving,
}: {
  rows: FundamentalValuationResult[]
  detail: FundamentalStockDetail
  selectedRow: FundamentalUniverseRow | null
  universeRows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
  excludedModelIds: Set<string>
  onModelIncludedChange: (model: string, included: boolean) => void
  effectiveWeights: Map<string, number>
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  sensitivity?: FundamentalSensitivity
  assumptionDraft: Record<string, number>
  onAssumptionDraftChange: (draft: Record<string, number>) => void
  onSaveAssumptions: () => void
  isSaving: boolean
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (key: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (rows.length === 0) {
    return <div className="fund-empty-small">No valuation rows.</div>
  }

  return (
    <div className="valuation-method-table-wrap">
      <table className="claude-table valuation-method-table min-w-[920px]">
        <thead>
          <tr>
            <th className="c">Incl.</th>
            <th>Methode</th>
            <th className="r">FV/result</th>
            <th className="r">Current/input</th>
            <th className="r">Upside/gap</th>
            <th>Conf.</th>
            <th className="r">Poids</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = `${row.model}-${row.scenario}`
            const isExpanded = expanded.has(key)
            const isControllable = row.family !== "diagnostic"
            const isIncluded = isControllable && !excludedModelIds.has(row.model)
            const effectiveWeight = isIncluded ? effectiveWeights.get(row.model) ?? null : null
            const effectiveFairValue = fairValueForValuationRow(row, row.model === "relative_multiples" ? comparableSummary : null)
            const effectiveCurrent = currentPriceForValuationRow(row, detail)
            const effectiveUpside = upsideForFairValue(effectiveFairValue, effectiveCurrent) ?? row.upside_pct
            return (
              <Fragment key={key}>
              <tr
                className={cn("valuation-method-summary-row", !isIncluded && isControllable && "excluded")}
                onClick={() => toggle(key)}
                aria-expanded={isExpanded}
              >
                  <td className="c">
                    {isControllable ? (
                      <input
                        aria-label={`Include ${MODEL_LABELS[row.model] ?? row.model}`}
                        className="valuation-include-checkbox"
                        type="checkbox"
                        checked={isIncluded}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => onModelIncludedChange(row.model, event.target.checked)}
                      />
                    ) : (
                      <span className="valuation-model-static">Info</span>
                    )}
                  </td>
                  <td className="font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                      {MODEL_LABELS[row.model] ?? row.model}
                    </span>
                  </td>
                  {row.model === "relative_multiples" ? (
                    <ComparableValuationCells
                      currentPrice={row.current_price}
                      summary={comparableSummary}
                      isLoading={isComparableSummaryLoading}
                    />
                  ) : row.model === "reverse_dcf" ? (
                    <ReverseDcfSummaryCells row={row} detail={detail} />
                  ) : (
                    <>
                      <td className="r font-mono">{fmtMoney(effectiveFairValue, 1)}</td>
                      <td className="r font-mono">{fmtMoney(row.current_price, 1)}</td>
                      <td className={cn("r font-mono font-semibold", (effectiveUpside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(effectiveUpside)}</td>
                    </>
                  )}
                  <td>
                    <span className={cn("signal-conf-badge", confidenceClass(row.confidence))}>
                    {row.confidence}
                    {row.is_proxy ? " proxy" : ""}
                  </span>
                </td>
                <td className="r font-mono">{!isControllable ? "-" : !isIncluded ? "Exclu" : effectiveWeight == null ? "No FV" : `${(effectiveWeight * 100).toFixed(0)}%`}</td>
              </tr>
              {isExpanded ? (
                <tr className="valuation-method-expanded-row">
                  <td colSpan={7} className="valuation-expanded-cell">
                    <ValuationMethodCard
                      row={row}
                      detail={detail}
                      selectedRow={selectedRow}
                      universeRows={universeRows}
                      selectedComparatorId={selectedComparatorId}
                      onSelectedComparatorIdChange={onSelectedComparatorIdChange}
                      comparableSummary={comparableSummary}
                      isComparableSummaryLoading={isComparableSummaryLoading}
                      isIncluded={isIncluded}
                      effectiveWeight={effectiveWeight}
                      sensitivity={sensitivity}
                      assumptionDraft={assumptionDraft}
                      onAssumptionDraftChange={onAssumptionDraftChange}
                      onSaveAssumptions={onSaveAssumptions}
                      isSaving={isSaving}
                    />
                  </td>
                </tr>
              ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


function AssumptionStrip({
  detail,
  draft,
  onDraftChange,
  onSave,
  isSaving,
}: {
  detail: FundamentalStockDetail
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSave: () => void
  isSaving: boolean
}) {
  return (
    <FundCard title="Hypotheses cles - DCF" aside="Scenario actif">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {ASSUMPTION_FIELDS.map(([key, label]) => {
          const value = asNumber(detail.assumptions[key])
          return <StatTile key={key} label={label} value={key.includes("year") ? fmtNumber(value, 0) : fmtPct(value, 1, false)} sub={key} />
        })}
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] font-semibold text-muted-foreground">Modifier les hypotheses</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {ASSUMPTION_FIELDS.map(([key, label]) => (
            <label key={key} className="space-y-1">
              <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">{label}</span>
              <Input type="number" step="0.005" value={draft[key] ?? ""} onChange={(event) => onDraftChange({ ...draft, [key]: Number(event.target.value) })} />
            </label>
          ))}
          <div className="flex items-end">
            <Button type="button" size="sm" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {isSaving ? "Enregistrement" : "Enregistrer"}
            </Button>
          </div>
        </div>
      </details>
    </FundCard>
  )
}


function ValuationModelControls({
  rows,
  excludedModelIds,
  onModelIncludedChange,
  onIncludeAll,
  onExcludeAll,
  effectiveWeights,
  selectionSummary,
  comparableSummary,
  isComparableSummaryLoading,
  originalTarget,
  currency,
  weightMode,
  onWeightModeChange,
}: {
  rows: FundamentalValuationResult[]
  excludedModelIds: Set<string>
  onModelIncludedChange: (model: string, included: boolean) => void
  onIncludeAll: () => void
  onExcludeAll: () => void
  effectiveWeights: Map<string, number>
  selectionSummary: ValuationSelectionSummary
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  originalTarget: number | null
  currency: string
  weightMode: WeightMode
  onWeightModeChange: (mode: WeightMode) => void
}) {
  const controllableRows = rows.filter((row) => row.family !== "diagnostic")
  if (!controllableRows.length) return null

  return (
    <div className="valuation-model-controls">
      <div className="valuation-model-controls-head">
        <div>
          <span className="valuation-mini-title">Selection de modeles - cible de travail</span>
          <p className="mt-1 text-[11px] text-muted-foreground">
            La recommandation officielle reste basee sur l'ensemble valide par le backend; cette section sert a analyser une cible alternative.
          </p>
        </div>
        <div className="valuation-model-actions">
          <button type="button" onClick={onIncludeAll}>Tout inclure</button>
          <button type="button" onClick={onExcludeAll}>Tout exclure</button>
          <div className="seg compact">
            <button type="button" className={weightMode === "ic" ? "active" : ""} onClick={() => onWeightModeChange("ic")}>IC</button>
            <button type="button" className={weightMode === "equal" ? "active" : ""} onClick={() => onWeightModeChange("equal")}>Egale</button>
          </div>
        </div>
      </div>

      <div className="valuation-model-summary">
        <StatTile
          label="Cible de travail"
          value={selectionSummary.fairValue != null ? `${fmtMoney(selectionSummary.fairValue, 1)} ${currency}` : "-"}
          sub={originalTarget != null ? `Officielle ${fmtMoney(originalTarget, 1)} ${currency}` : undefined}
        />
        <StatTile
          label="Upside"
          value={fmtPct(selectionSummary.upside)}
          tone={(selectionSummary.upside ?? 0) >= 0 ? "t-pos" : "t-neg"}
        />
        <StatTile
          label="Modeles"
          value={`${selectionSummary.usableCount}/${controllableRows.length}`}
          sub={`${selectionSummary.includedCount} coches`}
        />
        <StatTile
          label="Ponderation"
          value={
            selectionSummary.weightSource === "model weights" ? "IC"
            : selectionSummary.weightSource === "ic fallback" ? "IC (repli egale)"
            : "Egale"
          }
        />
      </div>

      <div className="valuation-model-toggle-grid">
        {controllableRows.map((row) => {
          const isIncluded = !excludedModelIds.has(row.model)
          const fairValue = fairValueForValuationRow(row, row.model === "relative_multiples" ? comparableSummary : null)
          const effectiveWeight = isIncluded ? effectiveWeights.get(row.model) ?? null : null
          const isLoadingValue = row.model === "relative_multiples" && isComparableSummaryLoading && fairValue == null
          return (
            <label key={`${row.model}-${row.scenario}`} className={cn("valuation-model-toggle", isIncluded && "active", fairValue == null && "empty")}>
              <input
                type="checkbox"
                checked={isIncluded}
                onChange={(event) => onModelIncludedChange(row.model, event.target.checked)}
              />
              <span className="valuation-model-toggle-main">
                <strong>{MODEL_LABELS[row.model] ?? row.model}</strong>
                <em>{isLoadingValue ? "..." : fairValue != null ? `${fmtMoney(fairValue, 1)} ${currency}` : "No FV"}</em>
              </span>
              <span className="valuation-model-toggle-weight">
                {!isIncluded ? "Off" : effectiveWeight != null ? `${(effectiveWeight * 100).toFixed(0)}%` : "No FV"}
              </span>
            </label>
          )
        })}
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">Objectif = mediane des classes de methodes, pas moyenne des modeles.</p>
    </div>
  )
}


function SharedProjectionPanel({ detail }: { detail: FundamentalStockDetail }) {
  const projection = projectionFromDetail(detail)
  if (!projection) return null
  const years = projectedYears(projection)
  const driverRows = projectionDriverRows(projection)
  const statementRows = projectionStatementRows()
  const integrityChecks = detail.integrity?.projection_checks ?? []
  const failingChecks = integrityChecks.filter((check) => check.status === "fail" || check.status === "warn")
  return (
    <FundCard
      title="Projection operationnelle partagee"
      aside={`${years.length} ans explicites - convention mi-annee`}
    >
      <GrowthDecompositionChart projection={projection} />
      <div className="driver-evidence-grid">
        {projectionDriverRows(projection).slice(0, 4).map((row) => (
          <DriverEvidenceChart key={row.key} driver={row.driver} label={row.label} format={row.format} />
        ))}
      </div>

      <div className="projection-panel-grid">
        <div className="projection-table-wrap">
          <div className="valuation-mini-title">Drivers derives</div>
          <table className="claude-table projection-table min-w-[720px]">
            <thead>
              <tr>
                <th>Driver</th>
                {years.map((year) => <th key={year} className="r">{year}</th>)}
                <th>Preuve</th>
              </tr>
            </thead>
            <tbody>
              {driverRows.map((row) => {
                const method = typeof row.driver.method === "string" ? row.driver.method : ""
                const warning = typeof row.driver.warning === "string" ? row.driver.warning : null
                return (
                  <tr key={row.key}>
                    <td className="font-medium">{row.label}</td>
                    {years.map((year) => (
                      <td key={year} className="r font-mono" title={method}>
                        {formatProjectionValue(driverProjectedValue(row.driver, year), row.format)}
                      </td>
                    ))}
                    <td>
                      <span className={cn("signal-conf-badge", warning ? "low" : "high")}>
                        {warning ? "Divergence" : "Historique"}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="projection-table-wrap">
          <div className="valuation-mini-title">3 etats projetes</div>
          <table className="claude-table projection-table min-w-[760px]">
            <thead>
              <tr>
                <th>Ligne</th>
                {years.map((year) => <th key={year} className="r">{year}</th>)}
              </tr>
            </thead>
            <tbody>
              {statementRows.map((row) => (
                <tr key={row.key}>
                  <td className="font-medium">{row.label}</td>
                  {projection.statements.map((statement, index) => (
                    <td key={`${row.key}-${index}`} className="r font-mono">
                      {formatProjectionValue(projectedValue(statement, row.key), row.format)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="valuation-warning-row">
        <span className="valuation-warning-label">Controles projection</span>
        <div className="flex flex-wrap gap-1.5">
          <span className={cn("signal-conf-badge", failingChecks.length ? "medium" : "high")}>
            {failingChecks.length ? `${failingChecks.length} alertes` : "Tous les liens OK"}
          </span>
          {projection.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{warning}</span>)}
        </div>
      </div>
    </FundCard>
  )
}


export function ValuationTab({
  detail,
  row,
  rows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
  onExcludedModelParamChange,
  visibleValuations,
  excludedModelIds,
  comparableSummary,
  isComparableSummaryLoading,
  selectionSummary,
  scenario,
  sensitivity,
  isSensitivityLoading,
  onScenarioChange,
  assumptionDraft,
  onAssumptionDraftChange,
  onSaveAssumptions,
  isSaving,
  weightMode,
  onWeightModeChange,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
  onExcludedModelParamChange: (value: string | null) => void
  visibleValuations: FundamentalValuationResult[]
  excludedModelIds: Set<string>
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  selectionSummary: ValuationSelectionSummary
  scenario: Scenario
  sensitivity: FundamentalSensitivity | undefined
  isSensitivityLoading: boolean
  onScenarioChange: (scenario: Scenario) => void
  assumptionDraft: Record<string, number>
  onAssumptionDraftChange: (draft: Record<string, number>) => void
  onSaveAssumptions: () => void
  isSaving: boolean
  weightMode: WeightMode
  onWeightModeChange: (mode: WeightMode) => void
}) {
  const [valuationSubTab, setValuationSubTab] = useState<string>("summary")
  const current = detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)
  const currency = detail.ensemble?.currency ?? "MAD"
  const originalTarget = detail.target_price ?? detail.ensemble?.fair_value_base ?? null
  const methods = useMemo(
    () => valuationMethods(
      detail,
      visibleValuations.filter((valuation) => valuation.family !== "diagnostic" && !excludedModelIds.has(valuation.model)),
      comparableSummary,
      selectionSummary,
    ),
    [comparableSummary, detail, excludedModelIds, selectionSummary, visibleValuations],
  )
  const target = originalTarget ?? selectionSummary.fairValue
  const workingTarget = selectionSummary.fairValue
  const setModelIncluded = useCallback(
    (model: string, included: boolean) => {
      const next = new Set(excludedModelIds)
      if (included) next.delete(model)
      else next.add(model)
      onExcludedModelParamChange(serializeExcludedModelIds(next, visibleValuations))
    },
    [excludedModelIds, onExcludedModelParamChange, visibleValuations],
  )
  const includeAllModels = useCallback(() => onExcludedModelParamChange(null), [onExcludedModelParamChange])
  const excludeAllModels = useCallback(() => {
    onExcludedModelParamChange(serializeExcludedModelIds(new Set(visibleValuations.filter((valuation) => valuation.family !== "diagnostic").map((valuation) => valuation.model)), visibleValuations))
  }, [onExcludedModelParamChange, visibleValuations])
  const subTabRows = useMemo(
    () => sortValuationRows(visibleValuations).filter((valuation) => MODEL_ORDER.includes(valuation.model)),
    [visibleValuations],
  )
  const activeModelRow = valuationSubTab === "summary" ? null : subTabRows.find((valuation) => valuation.model === valuationSubTab) ?? null
  const activeSubTab = valuationSubTab === "summary" || activeModelRow ? valuationSubTab : "summary"
  const activeModelIncluded = activeModelRow ? activeModelRow.family !== "diagnostic" && !excludedModelIds.has(activeModelRow.model) : false
  const activeModelWeight = activeModelRow && activeModelIncluded ? selectionSummary.effectiveWeights.get(activeModelRow.model) ?? null : null

  return (
    <div className="fund-gap">
      <div className="flex flex-wrap items-center gap-2">
        <span className="fund-section-label mb-0">Scenario detail</span>
        <div className="seg">
          {SCENARIOS.map((item) => (
            <button key={item} type="button" className={scenario === item ? "active" : ""} onClick={() => onScenarioChange(item)}>
              {item}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-muted-foreground">
          WACC <span className="font-mono text-foreground">{fmtPct(asNumber(detail.assumptions.wacc), 1, false)}</span> - g firm/equity{" "}
          <span className="font-mono text-foreground">
            {fmtPct(asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth), 1, false)} / {fmtPct(asNumber(detail.assumptions.terminal_growth_equity ?? detail.assumptions.terminal_growth), 1, false)}
          </span> - Devise <span className="font-mono text-foreground">{currency}</span>
        </span>
      </div>

      {scenario !== "base" ? (
        <div className="scenario-governance-banner">
          Vous consultez le scenario {scenario} (vue maison) - la recommandation reste ancree au scenario de base.
        </div>
      ) : null}

      <TriangulationBand triangulation={detail.triangulation} />

      <div className="valuation-subtabs">
        <button type="button" className={cn("valuation-subtab", activeSubTab === "summary" && "active")} onClick={() => setValuationSubTab("summary")}>
          Synthese
        </button>
        {subTabRows.map((valuation) => (
          <button key={valuation.model} type="button" className={cn("valuation-subtab", activeSubTab === valuation.model && "active")} onClick={() => setValuationSubTab(valuation.model)}>
            {valuation.model === "relative_multiples" ? "M. relatif" : MODEL_LABELS[valuation.model] ?? valuation.model}
          </button>
        ))}
      </div>

      {activeSubTab === "summary" ? (
        <>
          <div data-capture="valuation-models">
            <FundCard
              title="Football Field - fourchette de valorisation par methode"
              aside={`Cours ${fmtMoney(current, 1)} - Cible officielle ${fmtMoney(target, 1)}${workingTarget != null ? ` - Travail ${fmtMoney(workingTarget, 1)}` : ""}`}
            >
              <ValuationModelControls
                rows={visibleValuations}
                excludedModelIds={excludedModelIds}
                onModelIncludedChange={setModelIncluded}
                onIncludeAll={includeAllModels}
                onExcludeAll={excludeAllModels}
                effectiveWeights={selectionSummary.effectiveWeights}
                selectionSummary={selectionSummary}
                comparableSummary={comparableSummary}
                isComparableSummaryLoading={isComparableSummaryLoading}
                originalTarget={originalTarget}
                currency={currency}
                weightMode={weightMode}
                onWeightModeChange={onWeightModeChange}
              />
              <FootballField methods={methods} currentPrice={current} targetPrice={target} />
            </FundCard>
          </div>

          <div className="grid gap-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(20rem,0.75fr)]">
            <CostOfCapitalBuildUp detail={detail} />
            <CoverageRatingPanel detail={detail} row={row} />
          </div>

          <SharedProjectionPanel detail={detail} />
          <EstimatesTab detail={detail} editable={false} />
          <AssumptionStrip detail={detail} draft={assumptionDraft} onDraftChange={onAssumptionDraftChange} onSave={onSaveAssumptions} isSaving={isSaving} />
          <SensitivityHeatmap sensitivity={sensitivity} assumptions={detail.assumptions} isLoading={isSensitivityLoading} />
        </>
      ) : activeModelRow ? (
        <div className="valuation-method-section">
          <div className="valuation-method-section-header">
            <div>
              <span className="fund-section-label mb-1 block">
                {activeModelRow.model === "relative_multiples" ? "M. relatif" : MODEL_LABELS[activeModelRow.model] ?? activeModelRow.model}
              </span>
              <p>Formule, hypotheses et donnees de reference du modele selectionne.</p>
            </div>
            <span>{activeModelRow.confidence}</span>
          </div>
          <ValuationMethodCard
            row={activeModelRow}
            detail={detail}
            selectedRow={row}
            universeRows={rows}
            selectedComparatorId={selectedComparatorId}
            onSelectedComparatorIdChange={onSelectedComparatorIdChange}
            comparableSummary={comparableSummary}
            isComparableSummaryLoading={isComparableSummaryLoading}
            isIncluded={activeModelIncluded}
            effectiveWeight={activeModelWeight}
            sensitivity={sensitivity}
            assumptionDraft={assumptionDraft}
            onAssumptionDraftChange={onAssumptionDraftChange}
            onSaveAssumptions={onSaveAssumptions}
            isSaving={isSaving}
          />
        </div>
      ) : null}
    </div>
  )
}

