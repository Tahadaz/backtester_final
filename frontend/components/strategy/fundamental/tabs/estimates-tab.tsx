"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import { Loader2, Save } from "lucide-react"
import {
  getFundamentalResolvedAssumptions,
  type FundamentalMethodology,
  type FundamentalStockDetail,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { buildFundamentalEstimateTable } from "@/lib/fundamental-estimates-utils.js"
import { cn } from "@/lib/utils"
import { ESTIMATION_ASSUMPTION_FALLBACK_META, ESTIMATION_ASSUMPTION_KEYS, ESTIMATION_ASSUMPTION_KEY_SET, ESTIMATION_HISTORICAL_ALIASES, ESTIMATION_STATEMENT_KEYS, HISTORICAL_DEPRECIATION_AMORTIZATION_ALIASES, HISTORICAL_PAYOUT_ALIASES, HISTORICAL_REVENUE_GROWTH_ALIASES, HISTORICAL_TAX_ALIASES, HISTORICAL_TAX_RATE_ALIASES, MODEL_FORMULA_META, MODEL_LABELS, MODEL_ORDER, SCENARIOS, WORKING_CAPITAL_HISTORICAL_ALIASES } from "../lib/constants"
import { asNumber, asRatio, asRecord, assumptionRangeLabel, fmtAssumptionValue, fmtMoney, fmtNumber, fmtPct, fmtRatio, formatProjectionValue } from "../lib/formatters"
import { firstAnnualMetric } from "../panels/comparables"
import { CostOfCapitalBuildUp, costOfCapitalBuildUp } from "../panels/cost-of-capital"
import { FundCard, StatTile } from "../shared/cards"
import { DriverEvidenceChart, GrowthDecompositionChart } from "../shared/charts"
import { Scenario } from "../lib/types"
import { driverProjectedValue, editableAssumptionDraft, fairValueForValuationRow, historicalSeriesFromDriver, projectedValue, projectedYears, projectionDriverRows, projectionFromDetail, projectionStatementRows } from "../lib/view-models"

function ModellingMapPanel({ detail }: { detail: FundamentalStockDetail }) {
  const projection = projectionFromDetail(detail)
  const build = costOfCapitalBuildUp(detail)
  const projectionChecks = detail.integrity?.projection_checks ?? []
  const alertChecks = projectionChecks.filter((check) => check.status === "warn" || check.status === "fail")
  const plugValues = (detail.integrity?.projected_statements ?? [])
    .map((statement) => asNumber(asRecord(statement).balance_sheet_plug))
    .filter((value): value is number => value != null)
  const maxPlug = plugValues.length ? Math.max(...plugValues.map((value) => Math.abs(value))) : null
  const modelRows = detail.valuations.filter((row) => row.family !== "diagnostic")
  return (
    <FundCard title="Carte de modelisation" aside="Flux complet">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <StatTile label="Inputs" value={`${detail.annual.length} annees`} sub={detail.data_source ?? detail.as_of_date ?? "-"} />
        <StatTile label="Capital" value={fmtPct(asNumber(detail.assumptions.wacc), 2, false)} sub={`beta ${fmtRatio(asNumber(build.beta), 2)}`} />
        <StatTile label="Projection" value={projection ? `${projectedYears(projection).length} ans` : "-"} sub={`${projectionDriverRows(projection ?? { statements: [], drivers: {}, fcff: [], fcfe: [], dividends: [], bookValues: [], growthDecomposition: {}, warnings: [] }).length} drivers`} />
        <StatTile label="Modeles" value={`${modelRows.filter((row) => fairValueForValuationRow(row, null) != null).length}/${modelRows.length}`} sub="fair values" />
        <StatTile label="Ensemble" value={fmtMoney(detail.ensemble?.fair_value_base, 1)} sub={fmtPct(detail.ensemble?.confidence_score, 1, false)} />
        <StatTile label="Integrite" value={alertChecks.length ? `${alertChecks.length} alertes` : "OK"} sub={maxPlug != null ? `plug max ${fmtMoney(maxPlug, 0)}` : "plug -"} tone={alertChecks.length ? "t-neg" : "t-pos"} />
      </div>
      {alertChecks.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {alertChecks.slice(0, 8).map((check) => (
            <span key={check.name} className={cn("signal-conf-badge", check.status === "fail" ? "low" : "medium")}>
              {check.name.replace("projection_", "")}: {check.status}
            </span>
          ))}
        </div>
      ) : null}
    </FundCard>
  )
}


export function DecisionStrip({ detail }: { detail: FundamentalStockDetail }) {
  const build = costOfCapitalBuildUp(detail)
  const riskFree = asNumber(detail.assumptions.risk_free_rate)
  const baseErp = asNumber(build.base_equity_risk_premium) ?? asNumber(detail.assumptions.equity_risk_premium) ?? 0
  const countryRiskPremium = asNumber(build.country_risk_premium) ?? asNumber(detail.assumptions.country_risk_premium) ?? 0
  const scenarioErpAddon = asNumber(build.scenario_erp_addon) ?? asNumber(detail.assumptions.scenario_erp_addon) ?? 0
  const erp = asNumber(build.effective_equity_risk_premium) ?? baseErp + countryRiskPremium + scenarioErpAddon
  const beta = asNumber(build.beta) ?? asNumber(detail.assumptions.beta)
  const betaSource = String(build.beta_source ?? "-")
  const betaR2 = asNumber(build.beta_r2)
  const usesDefaultBeta = betaSource === "default_beta"
  const ke = asNumber(build.cost_of_equity) ?? asNumber(detail.assumptions.cost_of_equity)
  const wacc = asNumber(build.wacc) ?? asNumber(detail.assumptions.wacc)
  const g = asNumber(detail.assumptions.terminal_growth_firm) ?? asNumber(detail.assumptions.terminal_growth)
  const spread = wacc != null && g != null ? wacc - g : null
  return (
    <FundCard title="Hypotheses cles" aside="Scenario actif">
      <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-7">
        <StatTile label="Taux sans risque" value={fmtPct(riskFree, 2, false)} sub="rf - input marche" />
        <StatTile label="Prime de risque" value={fmtPct(erp, 2, false)} sub={`ERP + pays ${fmtPct(countryRiskPremium, 2, false)}`} />
        <StatTile label="Beta" value={fmtRatio(beta, 2)} sub={usesDefaultBeta ? "defaut 1.0" : betaR2 != null ? `${betaSource} R2 ${fmtNumber(betaR2, 2)}` : betaSource} tone={usesDefaultBeta ? "t-neg" : undefined} />
        <StatTile label="Cout equity" value={fmtPct(ke, 2, false)} sub="Ke (CAPM)" />
        <StatTile label="WACC" value={fmtPct(wacc, 2, false)} sub="taux d'actualisation" />
        <StatTile label="Croissance terminale" value={fmtPct(g, 2, false)} sub="g (perpetuite)" />
        <StatTile label="Spread WACC - g" value={fmtPct(spread, 2, false)} sub="moteur valeur terminale" tone={spread != null && spread < 0.01 ? "t-neg" : undefined} />
      </div>
    </FundCard>
  )
}


export function AssumptionsTab({
  detail,
  scenario,
  methodology,
  draft,
  onDraftChange,
  onSaveSymbol,
  onSaveDesk,
  isSaving,
  isDeskSaving,
}: {
  detail: FundamentalStockDetail
  scenario: Scenario
  methodology?: FundamentalMethodology
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSaveSymbol: () => void
  onSaveDesk: () => void
  isSaving: boolean
  isDeskSaving: boolean
}) {
  const provenance = asRecord(detail.assumption_provenance?.[scenario])
  const registry = methodology?.assumptions ?? {}
  const entries = Object.entries(registry).sort(([keyA, metaA], [keyB, metaB]) => {
    const group = String(metaA.group ?? "").localeCompare(String(metaB.group ?? ""))
    return group || String(metaA.label ?? keyA).localeCompare(String(metaB.label ?? keyB))
  })
  const sectionDefs = useMemo(() => {
    const entryByKey = new Map(entries)
    const rowsForKeys = (keys: string[]) => keys.map((key) => entryByKey.get(key) ? [key, entryByKey.get(key)!] as (typeof entries)[number] : null).filter((row): row is (typeof entries)[number] => row != null)
    const rowsForGroups = (groups: string[]) => entries.filter(([, meta]) => groups.includes(String(meta.group ?? "general")))
    const emptyRows: typeof entries = []
    return [
      { id: "cost_of_capital", label: "Cost of capital", rows: rowsForGroups(["cost_of_capital", "beta"]), advancedRows: emptyRows, model: null as string | null },
      {
        id: "projection",
        label: "Projection",
        rows: rowsForKeys([
          "revenue_growth",
          "ebit_margin",
          "tax_rate",
          "terminal_growth_firm",
          "terminal_growth_equity",
        ]),
        advancedRows: rowsForKeys([
          "capex_pct",
          "working_capital_pct",
          "depreciation_amortization_pct",
          "payout_ratio",
          "terminal_growth",
          "terminal_growth_floor",
          "terminal_growth_discount_buffer",
          "terminal_growth_ceiling_source",
          "forecast_years",
          "growth_cap",
          "mid_year_discounting",
          "mid_year_terminal",
        ]),
        model: null as string | null,
      },
      ...MODEL_ORDER.map((model) => ({
        id: `model:${model}`,
        label: MODEL_LABELS[model] ?? model,
        rows: rowsForKeys(MODEL_FORMULA_META[model]?.assumptionKeys ?? []),
        advancedRows: emptyRows,
        model,
      })),
      { id: "ensemble_weights", label: "Ponderation de l'ensemble", rows: rowsForGroups(["ensemble_weights"]), advancedRows: emptyRows, model: null as string | null },
    ].filter((section) => section.rows.length > 0 || section.advancedRows.length > 0)
  }, [entries])
  const [activeSectionId, setActiveSectionId] = useState(sectionDefs[0]?.id ?? "cost_of_capital")
  const [applyScope, setApplyScope] = useState<"stock" | "desk">("stock")
  const [showAdvanced, setShowAdvanced] = useState(false)
  const activeSection = sectionDefs.find((section) => section.id === activeSectionId) ?? sectionDefs[0]
  const activeFormula = activeSection?.model ? MODEL_FORMULA_META[activeSection.model] : null
  const { data: scenarioAssumptionRows } = useSWR(
    detail.symbol ? ["fundamental-resolved-assumptions", detail.symbol] : null,
    async () => Promise.all(SCENARIOS.map(async (item) => [item, await getFundamentalResolvedAssumptions(detail.symbol, item)] as const)),
  )
  const scenarioAssumptions = new Map(scenarioAssumptionRows ?? [])
  const draftPayload = editableAssumptionDraft(methodology, draft)
  const hasDraftChanges = Object.keys(draftPayload).length > 0
  const activeSavePending = applyScope === "stock" ? isSaving : isDeskSaving

  function saveActiveScope() {
    if (!hasDraftChanges) return
    if (applyScope === "desk") {
      if (window.confirm(`Ceci modifie les hypotheses pour toutes les valeurs du scenario ${scenario}. Continuer ?`)) {
        onSaveDesk()
      }
      return
    }
    onSaveSymbol()
  }

  function setDraftValue(key: string, rawValue: string) {
    const next = { ...draft }
    if (rawValue.trim() === "") delete next[key]
    else {
      const value = Number(rawValue)
      if (Number.isFinite(value)) next[key] = value
    }
    onDraftChange(next)
  }

  function renderAssumptionRow([key, meta]: (typeof entries)[number]) {
    const currentValue = detail.assumptions[key] ?? meta.value
    const editable = meta.editable !== false
    // For ensemble weight keys, show the current auto weight as placeholder so the desk
    // sees what they are overriding. Auto weight is 0 when the model is not in the
    // official ensemble (e.g. not usable for this symbol).
    let inputPlaceholder = fmtAssumptionValue(currentValue, meta.unit)
    if (key.startsWith("ensemble_weight_") && (currentValue == null || currentValue === 0)) {
      const modelName = key.slice("ensemble_weight_".length)
      const autoWeight = (detail.ensemble?.model_weights as Record<string, number> | null | undefined)?.[modelName]
      inputPlaceholder = autoWeight != null && autoWeight > 0
        ? `${(autoWeight * 100).toFixed(1)}% (auto)`
        : "0 (auto)"
    }
    return (
      <tr key={key}>
        <td>
          <div className="font-semibold">{meta.label}</div>
          <div className="font-mono text-[10px] text-muted-foreground">{key}</div>
        </td>
        <td className="font-mono">{fmtAssumptionValue(currentValue, meta.unit)}</td>
        <td>
          <span className="rounded border border-line px-2 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground">
            {String(provenance[key] ?? "default")}
          </span>
        </td>
        <td className="font-mono">{assumptionRangeLabel(meta.plausible_range, meta.unit)}</td>
        <td>{meta.source ?? "-"}</td>
        <td>{meta.derivation ?? "-"}</td>
        <td>
          {editable ? (
            <div className="flex items-center gap-2">
              <Input
                type="number"
                step={meta.unit === "percent" ? "0.0025" : meta.unit === "flag" ? "1" : "0.01"}
                min={meta.unit === "flag" || meta.group === "ensemble_weights" ? 0 : undefined}
                max={meta.unit === "flag" ? 1 : meta.group === "ensemble_weights" ? 1 : undefined}
                value={draft[key] ?? ""}
                placeholder={inputPlaceholder}
                onChange={(event) => setDraftValue(key, event.target.value)}
                className="h-8 w-28"
              />
              {draft[key] != null ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    const next = { ...draft }
                    delete next[key]
                    onDraftChange(next)
                  }}
                >
                  Annuler
                </Button>
              ) : null}
            </div>
          ) : (
            <span className="text-[11px] text-muted-foreground">Calcule</span>
          )}
        </td>
      </tr>
    )
  }

  return (
    <div className="fund-gap">
      <ModellingMapPanel detail={detail} />

      <DecisionStrip detail={detail} />

      <details>
        <summary className="cursor-pointer text-[11px] font-semibold text-muted-foreground">Comparer les scenarios (bas / base / haut)</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {SCENARIOS.map((item) => {
            const resolved = scenarioAssumptions.get(item)
            const assumptions = (resolved?.assumptions ?? (item === scenario ? detail.assumptions : {})) as Record<string, unknown>
            return (
              <div key={item} className={cn("rounded-md border border-line bg-bg p-3", item === scenario && "border-primary/40 bg-bg2")}>
                <div className="mb-2 text-[11px] font-bold uppercase text-muted-foreground">{item}</div>
                <div className="grid grid-cols-3 gap-2">
                  <StatTile label="WACC" value={fmtPct(asNumber(assumptions.wacc), 2, false)} />
                  <StatTile label="g firm" value={fmtPct(asNumber(assumptions.terminal_growth_firm ?? assumptions.terminal_growth), 2, false)} />
                  <StatTile label="g equity" value={fmtPct(asNumber(assumptions.terminal_growth_equity ?? assumptions.terminal_growth), 2, false)} />
                </div>
              </div>
            )
          })}
        </div>
      </details>

      <CostOfCapitalBuildUp detail={detail} />

      <FundCard id="assumptions-editor" title="Registre des hypotheses" aside={`Scenario ${scenario}`}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex rounded-md border border-line bg-bg p-0.5">
            <button
              type="button"
              className={cn("rounded px-3 py-1.5 text-[12px] font-semibold text-muted-foreground", applyScope === "stock" && "bg-bg2 text-fg")}
              onClick={() => setApplyScope("stock")}
            >
              Appliquer au titre
            </button>
            <button
              type="button"
              className={cn("rounded px-3 py-1.5 text-[12px] font-semibold text-muted-foreground", applyScope === "desk" && "bg-bg2 text-fg")}
              onClick={() => setApplyScope("desk")}
            >
              Appliquer au desk
            </button>
          </div>
          <div className="text-[11px] font-semibold uppercase text-muted-foreground">{Object.keys(draftPayload).length} modifs</div>
        </div>
        <div className="grid gap-4 lg:grid-cols-[210px_minmax(0,1fr)]">
          <div className="flex gap-2 overflow-x-auto lg:block lg:overflow-visible">
            {sectionDefs.map((section) => (
              <button
                key={section.id}
                type="button"
                className={cn(
                  "mb-2 whitespace-nowrap rounded-md border border-line px-3 py-2 text-left text-[12px] font-semibold text-muted-foreground lg:block lg:w-full",
                  activeSection?.id === section.id && "border-primary/40 bg-bg2 text-fg",
                )}
                onClick={() => setActiveSectionId(section.id)}
              >
                {section.label}
              </button>
            ))}
          </div>
          <div className="min-w-0">
            {activeFormula ? (
              <div className="mb-3 rounded-md border border-line bg-bg2 p-3 text-sm">
                <div className="font-mono text-[12px] text-fg">{activeFormula.formula}</div>
                {activeFormula.secondaryFormula ? <div className="mt-1 font-mono text-[11px] text-muted-foreground">{activeFormula.secondaryFormula}</div> : null}
                <p className="mt-2 text-[12px] text-muted-foreground">{activeFormula.explanation}</p>
              </div>
            ) : null}
            {activeSectionId === "ensemble_weights" ? (() => {
              const ensembleWarnings = detail.ensemble?.warnings ?? []
              const isUserDefined = ensembleWarnings.includes("ensemble_user_defined_weights")
              const isIcFallback = ensembleWarnings.includes("ic_weight_fallback_no_coverage")
              const modeBadgeLabel = isUserDefined
                ? "Defini par l'utilisateur"
                : isIcFallback
                  ? "Auto (fiabilite)"
                  : "Auto (IC)"
              const modeBadgeClass = isUserDefined
                ? "bg-primary/10 text-primary border-primary/30"
                : "bg-bg2 text-muted-foreground border-line"
              const ensembleWeightDraftKeys = Object.keys(draft).filter(k => k.startsWith("ensemble_weight_"))
              const draftTotal = ensembleWeightDraftKeys.reduce((sum, k) => sum + Math.max(0, draft[k] ?? 0), 0)
              return (
                <div className="mb-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-semibold text-muted-foreground uppercase">Mode actif :</span>
                    <span className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${modeBadgeClass}`}>{modeBadgeLabel}</span>
                  </div>
                  {draftTotal > 0 ? (
                    <div className="rounded-md border border-line bg-bg2 p-2 text-[11px]">
                      <div className="mb-1 font-semibold text-muted-foreground">Apercu normalise (apres enregistrement) :</div>
                      <div className="flex flex-wrap gap-2">
                        {ensembleWeightDraftKeys
                          .filter(k => (draft[k] ?? 0) > 0)
                          .map(k => {
                            const model = k.slice("ensemble_weight_".length)
                            const pct = ((draft[k] ?? 0) / draftTotal * 100).toFixed(1)
                            return (
                              <span key={k} className="font-mono">
                                {MODEL_LABELS[model] ?? model}: <strong>{pct}%</strong>
                              </span>
                            )
                          })}
                      </div>
                    </div>
                  ) : null}
                  <p className="text-[11px] text-muted-foreground">
                    Entrez des poids entre 0 et 1. Laisser a 0 = automatique pour ce modele. Les poids sont renormalises sur les modeles utilisables apres enregistrement.
                  </p>
                </div>
              )
            })() : null}
            <div className="overflow-x-auto">
              <table className="claude-table min-w-[980px]">
                <thead>
                  <tr>
                    <th>Hypothese</th>
                    <th>Valeur</th>
                    <th>Provenance</th>
                    <th>Plage</th>
                    <th>Source</th>
                    <th>Regle</th>
                    <th>Edition</th>
                  </tr>
                </thead>
                <tbody>
                  {activeSection?.rows.length ? activeSection.rows.map(renderAssumptionRow) : (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-sm text-muted-foreground">Registre indisponible.</td>
                    </tr>
                  )}
                  {activeSection?.advancedRows.length ? (
                    <>
                      <tr>
                        <td colSpan={7} className="bg-bg2/40 py-2">
                          <button
                            type="button"
                            className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground hover:text-fg"
                            onClick={() => setShowAdvanced((value) => !value)}
                          >
                            {showAdvanced ? "Masquer" : "Afficher"} les hypotheses avancees ({activeSection.advancedRows.length})
                          </button>
                        </td>
                      </tr>
                      {showAdvanced ? activeSection.advancedRows.map(renderAssumptionRow) : null}
                    </>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={saveActiveScope} disabled={!hasDraftChanges || isSaving || isDeskSaving}>
            {activeSavePending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {activeSavePending ? "Enregistrement" : applyScope === "stock" ? "Enregistrer titre" : "Enregistrer desk"}
          </Button>
          {Object.keys(draft).length ? (
            <Button type="button" size="sm" variant="ghost" onClick={() => onDraftChange({})} disabled={isSaving || isDeskSaving}>
              Annuler tout
            </Button>
          ) : null}
        </div>
      </FundCard>
    </div>
  )
}


function formatEstimate(value: number | null, format: string): string {
  if (format === "pct") return fmtPct(value, 1, false)
  return fmtMoney(value, 0)
}


function estimateDraftPayload(methodology: FundamentalMethodology | undefined, draft: Record<string, number>): Record<string, number> {
  return Object.fromEntries(
    Object.entries(editableAssumptionDraft(methodology, draft)).filter(([key]) => ESTIMATION_ASSUMPTION_KEY_SET.has(key)),
  )
}


function estimationAssumptionRows(detail: FundamentalStockDetail, methodology?: FundamentalMethodology) {
  const registry = methodology?.assumptions ?? {}
  return ESTIMATION_ASSUMPTION_KEYS.map((key) => {
    const meta = registry[key] ?? ESTIMATION_ASSUMPTION_FALLBACK_META[key]
    return {
      key,
      meta,
      currentValue: detail.assumptions[key] ?? meta.value,
      editable: meta.editable !== false,
    }
  })
}


function assumptionInputStep(unit?: string | null): string {
  if (unit === "percent") return "0.0025"
  if (unit === "years" || unit === "count" || unit === "flag") return "1"
  return "0.01"
}


function estimationActualYears(detail: FundamentalStockDetail, firstForecastYear: number | null): number[] {
  const years = [...new Set(
    detail.annual
      .map((row) => asNumber(row.statement_year))
      .filter((year): year is number => year != null && (firstForecastYear == null || year < firstForecastYear)),
  )]
  return years.sort((a, b) => a - b).slice(-3)
}


function annualMetricsForYear(detail: FundamentalStockDetail, year: number): Record<string, number | null> | null {
  return detail.annual.find((row) => row.statement_year === year)?.metrics ?? null
}


function historicalWorkingCapital(detail: FundamentalStockDetail, year: number): number | null {
  const metrics = annualMetricsForYear(detail, year)
  return metrics ? firstAnnualMetric(metrics, WORKING_CAPITAL_HISTORICAL_ALIASES) : null
}


function historicalNopat(detail: FundamentalStockDetail, metrics: Record<string, number | null>): number | null {
  const direct = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.nopat)
  if (direct != null) return direct
  const ebit = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.ebit)
  if (ebit == null) return null
  const taxExpense = firstAnnualMetric(metrics, HISTORICAL_TAX_ALIASES)
  const netIncome = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.net_income)
  if (taxExpense != null && netIncome != null) {
    const pretax = netIncome + Math.abs(taxExpense)
    if (pretax > 0) return ebit * (1 - Math.max(0, Math.min(0.6, Math.abs(taxExpense) / pretax)))
  }
  const assumedTaxRate = asNumber(detail.assumptions.tax_rate) ?? 0.35
  return ebit * (1 - Math.max(0, Math.min(0.6, assumedTaxRate)))
}


function historicalEstimationValue(detail: FundamentalStockDetail, year: number, key: string): number | null {
  const metrics = annualMetricsForYear(detail, year)
  if (!metrics) return null
  if (key === "nopat") return historicalNopat(detail, metrics)
  if (key === "delta_working_capital") {
    const direct = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.delta_working_capital)
    if (direct != null) return direct
    const current = historicalWorkingCapital(detail, year)
    const previous = historicalWorkingCapital(detail, year - 1)
    return current != null && previous != null ? current - previous : null
  }
  const value = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES[key] ?? [])
  if (value == null) return null
  if (key === "capex" || key === "dividends") return Math.abs(value)
  return value
}


function safeRatio(numerator: number | null, denominator: number | null): number | null {
  return denominator != null && denominator !== 0 && numerator != null ? numerator / denominator : null
}


function historicalDriverValue(detail: FundamentalStockDetail, year: number, key: string): number | null {
  const metrics = annualMetricsForYear(detail, year)
  if (!metrics) return null
  const revenue = historicalEstimationValue(detail, year, "revenue")
  if (key === "revenue_growth") {
    const direct = asRatio(firstAnnualMetric(metrics, HISTORICAL_REVENUE_GROWTH_ALIASES))
    if (direct != null) return direct
    const previousRevenue = historicalEstimationValue(detail, year - 1, "revenue")
    return revenue != null && previousRevenue != null && previousRevenue > 0 ? revenue / previousRevenue - 1 : null
  }
  if (key === "ebit_margin") return safeRatio(historicalEstimationValue(detail, year, "ebit"), revenue)
  if (key === "tax_rate") {
    const direct = asRatio(firstAnnualMetric(metrics, HISTORICAL_TAX_RATE_ALIASES))
    if (direct != null) return direct
    const taxExpense = firstAnnualMetric(metrics, HISTORICAL_TAX_ALIASES)
    const netIncome = historicalEstimationValue(detail, year, "net_income")
    const pretax = taxExpense != null && netIncome != null ? netIncome + Math.abs(taxExpense) : null
    return pretax != null && pretax > 0 && taxExpense != null ? Math.abs(taxExpense) / pretax : null
  }
  if (key === "capex_pct") return safeRatio(historicalEstimationValue(detail, year, "capex"), revenue)
  if (key === "working_capital_pct") return safeRatio(historicalWorkingCapital(detail, year), revenue)
  if (key === "depreciation_amortization_pct") {
    return safeRatio(firstAnnualMetric(metrics, HISTORICAL_DEPRECIATION_AMORTIZATION_ALIASES), revenue)
  }
  if (key === "payout_ratio") {
    const direct = asRatio(firstAnnualMetric(metrics, HISTORICAL_PAYOUT_ALIASES))
    if (direct != null) return direct
    const dividends = historicalEstimationValue(detail, year, "dividends")
    const netIncome = historicalEstimationValue(detail, year, "net_income")
    return netIncome != null && netIncome > 0 && dividends != null ? Math.abs(dividends) / netIncome : null
  }
  return null
}


function driverHistoricalValue(detail: FundamentalStockDetail, row: { key: string; driver: Record<string, unknown> }, year: number): number | null {
  return historicalSeriesFromDriver(row.driver).find((point) => point.year === year)?.value ?? historicalDriverValue(detail, year, row.key)
}


function driverHistoricalVariation(detail: FundamentalStockDetail, row: { key: string; driver: Record<string, unknown> }, actualYears: number[]): number | null {
  const values = actualYears
    .map((year) => driverHistoricalValue(detail, row, year))
    .filter((value): value is number => value != null)
  return values.length >= 2 ? values[values.length - 1] - values[0] : null
}


function formatDriverVariation(value: number | null, format: "pct" | "number"): string {
  if (format === "pct") return fmtPct(value, 1, true)
  if (value == null) return "-"
  return `${value >= 0 ? "+" : ""}${fmtNumber(value, 2)}`
}


function ProjectionAssumptionEditor({
  detail,
  methodology,
  draft,
  onDraftChange,
  onSave,
  isSaving,
}: {
  detail: FundamentalStockDetail
  methodology?: FundamentalMethodology
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSave: () => void
  isSaving: boolean
}) {
  const rows = estimationAssumptionRows(detail, methodology)
  const payload = estimateDraftPayload(methodology, draft)
  const hasChanges = Object.keys(payload).length > 0
  const setDraftValue = (key: string, rawValue: string) => {
    const next = { ...draft }
    if (rawValue.trim() === "") delete next[key]
    else {
      const value = Number(rawValue)
      if (Number.isFinite(value)) next[key] = value
    }
    onDraftChange(next)
  }
  return (
    <FundCard title="Hypotheses de projection" aside={`${Object.keys(payload).length} modifs`}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {rows.map(({ key, meta, currentValue, editable }) => (
          <label key={key} className="space-y-1 rounded-md border border-line bg-bg2 p-2">
            <span className="block text-[10px] font-bold uppercase text-muted-foreground">{meta.label}</span>
            <span className="block font-mono text-[12px] text-fg">{fmtAssumptionValue(currentValue, meta.unit)}</span>
            <Input
              type="number"
              step={assumptionInputStep(meta.unit)}
              min={meta.unit === "flag" ? 0 : undefined}
              max={meta.unit === "flag" ? 1 : undefined}
              value={draft[key] ?? ""}
              placeholder={fmtAssumptionValue(currentValue, meta.unit)}
              disabled={!editable || isSaving}
              onChange={(event) => setDraftValue(key, event.target.value)}
              className="h-8"
            />
            <span className="block text-[10px] text-muted-foreground">{assumptionRangeLabel(meta.plausible_range, meta.unit)}</span>
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" onClick={onSave} disabled={!hasChanges || isSaving}>
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {isSaving ? "Enregistrement" : "Enregistrer"}
        </Button>
        {hasChanges ? (
          <Button type="button" size="sm" variant="ghost" onClick={() => onDraftChange({})} disabled={isSaving}>
            Annuler
          </Button>
        ) : null}
      </div>
    </FundCard>
  )
}


function LegacyEstimateTable({ detail }: { detail: FundamentalStockDetail }) {
  const table = buildFundamentalEstimateTable(detail)
  return (
    <FundCard
      title="P&L detaille - reel + estimations"
      aside={
        <span className="flex gap-2">
          <span className="estimate-chip">Actuel</span>
          <span className="estimate-chip est">Estime</span>
        </span>
      }
    >
      <div className="overflow-x-auto">
        <table className="claude-table min-w-[720px] estimates-table">
          <thead>
            <tr>
              <th>Metrique</th>
              {table.years.map((year) => (
                <th key={year} className={cn("r", year.endsWith("E") && "estimated")}>{year}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.label}>
                <td className="font-semibold">{row.label}</td>
                {row.values.map((value, index) => (
                  <td key={`${row.label}-${index}`} className={cn("r font-mono", table.years[index]?.endsWith("E") && "estimated")}>
                    {formatEstimate(value, row.format)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </FundCard>
  )
}


export function EstimatesTab({
  detail,
  methodology,
  draft,
  onDraftChange,
  onSave,
  isSaving,
  editable = true,
}: {
  detail: FundamentalStockDetail
  methodology?: FundamentalMethodology
  draft?: Record<string, number>
  onDraftChange?: (draft: Record<string, number>) => void
  onSave?: () => void
  isSaving?: boolean
  editable?: boolean
}) {
  const projection = projectionFromDetail(detail)
  if (!projection) {
    return (
      <div className="fund-gap">
        {editable && draft && onDraftChange && onSave ? (
          <ProjectionAssumptionEditor detail={detail} methodology={methodology} draft={draft} onDraftChange={onDraftChange} onSave={onSave} isSaving={Boolean(isSaving)} />
        ) : null}
        <LegacyEstimateTable detail={detail} />
      </div>
    )
  }
  const years = projectedYears(projection)
  const actualYears = estimationActualYears(detail, years[0] ?? null)
  const driverRows = projectionDriverRows(projection)
  const statementRows = projectionStatementRows().filter((row) => ESTIMATION_STATEMENT_KEYS.has(row.key))
  return (
    <div className="fund-gap">
      {editable && draft && onDraftChange && onSave ? (
        <ProjectionAssumptionEditor detail={detail} methodology={methodology} draft={draft} onDraftChange={onDraftChange} onSave={onSave} isSaving={Boolean(isSaving)} />
      ) : null}

      <FundCard title="Synthese projection maison" aside={`${years.length} ans explicites`}>
        <div className="grid gap-3 md:grid-cols-4">
          <StatTile label="Horizon" value={fmtNumber(asNumber(detail.assumptions.forecast_years), 0)} sub={years.length ? `${years[0]}-${years[years.length - 1]}` : "-"} />
          <StatTile label="g firm" value={fmtPct(asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth), 2, false)} sub="fade final" />
          <StatTile label="Cap croissance" value={fmtPct(asNumber(detail.assumptions.growth_cap), 2, false)} sub="borne" />
          <StatTile label="Taux IS" value={fmtPct(asNumber(detail.assumptions.tax_rate), 2, false)} sub="NOPAT" />
        </div>
        {projection.warnings.length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {projection.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{warning}</span>)}
          </div>
        ) : null}
      </FundCard>

      <FundCard title="Trajectoire de croissance" aside="Drivers">
        <GrowthDecompositionChart projection={projection} />
        <div className="driver-evidence-grid">
          {driverRows.slice(0, 4).map((row) => (
            <DriverEvidenceChart key={row.key} driver={row.driver} label={row.label} format={row.format} />
          ))}
        </div>
      </FundCard>

      <FundCard title="Drivers par annee" aside="Historique + hypotheses">
        <div className="projection-table-wrap">
          <table className="claude-table projection-table estimates-table min-w-[980px]">
            <thead>
              <tr>
                <th>Driver</th>
                {actualYears.map((year) => <th key={`${year}-actual`} className="r">{year}A</th>)}
                {actualYears.length ? <th className="r">Var. hist.</th> : null}
                {years.map((year) => <th key={year} className="r estimated">{year}E</th>)}
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {driverRows.map((row) => {
                const method = typeof row.driver.method === "string" ? row.driver.method : ""
                const warning = typeof row.driver.warning === "string" ? row.driver.warning : null
                const variation = driverHistoricalVariation(detail, row, actualYears)
                return (
                  <tr key={row.key}>
                    <td className="font-semibold">{row.label}</td>
                    {actualYears.map((year) => (
                      <td key={`${row.key}-${year}-actual`} className="r font-mono" title={method}>
                        {formatProjectionValue(driverHistoricalValue(detail, row, year), row.format)}
                      </td>
                    ))}
                    {actualYears.length ? (
                      <td className="r font-mono font-semibold" title="Variation entre le premier et le dernier point historique affiche">
                        {formatDriverVariation(variation, row.format)}
                      </td>
                    ) : null}
                    {years.map((year) => (
                      <td key={year} className="r font-mono estimated" title={method}>
                        {formatProjectionValue(driverProjectedValue(row.driver, year), row.format)}
                      </td>
                    ))}
                    <td>
                      <span className={cn("signal-conf-badge", warning ? "medium" : "high")}>
                        {warning ? "Alerte" : "Historique"}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </FundCard>

      <FundCard
        title="P&L et cash-flow - historique + projection"
        aside={
          <span className="flex gap-2">
            <span className="estimate-chip">Actuel</span>
            <span className="estimate-chip est">Estime</span>
          </span>
        }
      >
        <div className="projection-table-wrap">
          <table className="claude-table projection-table estimates-table min-w-[820px]">
            <thead>
              <tr>
                <th>Ligne</th>
                {actualYears.map((year) => <th key={`${year}-actual`} className="r">{year}A</th>)}
                {years.map((year) => <th key={year} className="r estimated">{year}E</th>)}
              </tr>
            </thead>
            <tbody>
              {statementRows.map((row) => (
                <tr key={row.key}>
                  <td className="font-semibold">{row.label}</td>
                  {actualYears.map((year) => (
                    <td key={`${row.key}-${year}-actual`} className="r font-mono">
                      {formatProjectionValue(historicalEstimationValue(detail, year, row.key), row.format)}
                    </td>
                  ))}
                  {projection.statements.map((statement, index) => (
                    <td key={`${row.key}-${index}`} className="r font-mono estimated">
                      {formatProjectionValue(projectedValue(statement, row.key), row.format)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </FundCard>
    </div>
  )
}

