"use client"

import { useMemo } from "react"
import {
  type FundamentalSensitivity,
  type FundamentalStockDetail,
  type FundamentalValuationResult,
} from "@/lib/api"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import { buildDcfViewModel } from "@/lib/fundamental-dcf-utils.js"
import { cn } from "@/lib/utils"
import { MODEL_LABELS, valuationWarningLabel } from "../lib/constants"
import { asNumber, confidenceClass, fmtMoney, fmtNumber, fmtPct, fmtRatio, formatDcfStepValue } from "../lib/formatters"
import { CostOfCapitalBuildUp } from "../panels/cost-of-capital"
import { ModelSensitivityPanel } from "../panels/sensitivity"
import { ModelValueGrid, StatTile, StatementEvidenceCard } from "../shared/cards"
import { DriverEvidenceChart, FcfBridge } from "../shared/charts"
import { DcfAvailableViewModel, DcfMode, DcfViewModel, FundamentalHorizon, ProjectionView } from "../lib/types"
import { currentPriceForValuationRow, dcfVerdict, fairValueForValuationRow, historicalSeriesFromDriver, instantiatedFormula, outputItems, projectionFromDetail, statementEvidence, technicalInputItems, upsideForFairValue, valuationAssumptionItems, valuationFormulaMeta } from "../lib/view-models"

function terminalBasisLine(dcf: DcfAvailableViewModel): string {
  const basis = dcf.terminalBasis
  const source = typeof basis.source === "string" ? basis.source.replaceAll("_", " ") : "hypothese modele"
  const binding = typeof basis.binding_constraint === "string" ? basis.binding_constraint.replaceAll("_", " ") : null
  const raw = asNumber(basis.raw_growth)
  const ceiling = asNumber(basis.ceiling)
  const floor = asNumber(basis.floor)
  const capText = [
    raw != null ? `brut ${fmtPct(raw, 2, false)}` : null,
    ceiling != null ? `plafond ${fmtPct(ceiling, 2, false)}` : null,
    floor != null ? `plancher ${fmtPct(floor, 2, false)}` : null,
    binding ? `contrainte ${binding}` : null,
  ].filter(Boolean).join(" | ")
  if (dcf.mode === "fcff") {
    const reinvestment = asNumber(basis.reinvestment_rate)
    const roic = asNumber(basis.roic)
    if (reinvestment != null && roic != null) {
      return `g firm = reinvestissement ${fmtPct(reinvestment, 2, false)} x ROIC ${fmtPct(roic, 2, false)} = ${fmtPct(dcf.terminalGrowth, 2, false)}${capText ? ` (${capText})` : ""}`
    }
  } else {
    const retention = asNumber(basis.retention)
    const roe = asNumber(basis.roe)
    if (retention != null && roe != null) {
      return `g equity = retention ${fmtPct(retention, 2, false)} x ROE ${fmtPct(roe, 2, false)} = ${fmtPct(dcf.terminalGrowth, 2, false)}${capText ? ` (${capText})` : ""}`
    }
  }
  return `g terminal = ${fmtPct(dcf.terminalGrowth, 2, false)} (${source}${capText ? ` | ${capText}` : ""})`
}


function DcfPvTable({ dcf }: { dcf: DcfAvailableViewModel }) {
  const cashFlowGlossaryId = dcf.mode === "fcff" ? "fcff" : "fcfe"
  return (
    <div className="dcf-table-wrap">
      <table className="claude-table dcf-pv-table">
        <thead>
          <tr>
            <th>Annee</th>
            <th className="r"><GlossaryTerm id={cashFlowGlossaryId}>{dcf.cashFlowLabel}</GlossaryTerm></th>
            <th className="r">Croissance</th>
            <th className="r"><GlossaryTerm id="discount-period">t</GlossaryTerm></th>
            <th className="r"><GlossaryTerm id="discount-factor">Facteur</GlossaryTerm></th>
            <th className="r"><GlossaryTerm id="present-value">PV</GlossaryTerm></th>
          </tr>
        </thead>
        <tbody>
          {dcf.pvRows.map((item) => (
            <tr key={item.index}>
              <td>Y{item.index}</td>
              <td className="r font-mono">{fmtMoney(item.cashFlow, 0)}</td>
              <td className="r font-mono">{fmtPct(item.growth, 1, false)}</td>
              <td className="r font-mono">{fmtNumber(item.period, 2)}</td>
              <td className="r font-mono">{fmtNumber(item.discountFactor, 4)}</td>
              <td className="r font-mono font-semibold">{fmtMoney(item.pv, 0)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={5}>Somme PV explicite</td>
            <td className="r font-mono font-semibold">{fmtMoney(dcf.explicitPv, 0)}</td>
          </tr>
        </tfoot>
      </table>
      <p className="dcf-table-legend">
        <strong>t</strong> = nombre d'annees avant le flux. <strong>Facteur</strong> = 1 / (1 + {dcf.rateLabel})<sup>t</sup>, toujours entre 0 et 1.{" "}
        <strong>PV</strong> = flux x facteur, soit sa valeur d'aujourd'hui. Chaque terme renvoie au glossaire.
      </p>
    </div>
  )
}


function DcfHistoryStrip({ projection, mode, cashFlowLabel }: { projection: ProjectionView; mode: DcfMode; cashFlowLabel: string }) {
  const history = useMemo(() => {
    const driver = projection.drivers[mode]
    return driver ? historicalSeriesFromDriver(driver).slice(-5) : []
  }, [projection, mode])
  if (history.length < 2) return null
  const cashFlowGlossaryId = mode === "fcff" ? "fcff" : "fcfe"
  return (
    <div className="dcf-history-strip">
      <div className="dcf-history-head">
        <span className="valuation-mini-title">
          Historique <GlossaryTerm id={cashFlowGlossaryId}>{cashFlowLabel}</GlossaryTerm> (realise)
        </span>
        <span>{history.length} exercices avant projection</span>
      </div>
      <div className="dcf-history-row">
        {history.map((point) => (
          <div key={point.year} className="dcf-history-cell">
            <div className="dcf-history-year">{point.year}</div>
            <div className="dcf-history-value">{fmtMoney(point.value, 0)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}


function DcfTerminalBlock({ dcf }: { dcf: DcfAvailableViewModel }) {
  return (
    <div className="dcf-terminal-block">
      <div className="valuation-formula-panel">
        <div className="valuation-formula-eyebrow">Valeur terminale</div>
        <div className="valuation-formula-line">
          TV = {dcf.cashFlowLabel}_n {fmtMoney(dcf.pvRows.at(-1)?.cashFlow, 0)} x (1 + g {fmtPct(dcf.terminalGrowth, 2, false)}) / ({dcf.rateLabel} {fmtPct(dcf.discountRate, 2, false)} - g) = {fmtMoney(dcf.terminalValue, 0)}
        </div>
        <div className="valuation-formula-sub">{terminalBasisLine(dcf)}</div>
      </div>
      <div className="dcf-terminal-grid">
        <StatTile label="g terminal" value={fmtPct(dcf.terminalGrowth, 2, false)} sub={String(dcf.terminalBasis.binding_constraint ?? "modele")} />
        <StatTile label="TV nominale" value={fmtMoney(dcf.terminalValue, 0)} />
        <StatTile label="Facteur TV" value={fmtNumber(dcf.terminalDiscountFactor, 4)} sub={`t ${fmtNumber(dcf.terminalPeriod, 2)}`} />
        <StatTile label="PV(TV)" value={fmtMoney(dcf.terminalPv, 0)} />
        <StatTile label="Poids TV" value={fmtPct(dcf.terminalValuePct, 1, false)} tone={dcf.flags.terminalHeavy ? "t-neg" : undefined} />
        {dcf.mode === "fcff" ? <StatTile label="Exit EV/EBITDA" value={fmtRatio(dcf.impliedExitEvToEbitda, 2)} /> : null}
      </div>
    </div>
  )
}


function DcfValueWaterfall({ dcf }: { dcf: DcfAvailableViewModel }) {
  const maxAbs = Math.max(1, ...dcf.bridgeSteps.map((step) => Math.abs(step.value ?? 0)))
  return (
    <div className="dcf-waterfall">
      {dcf.bridgeSteps.map((step) => {
        const width = `${Math.max(5, (Math.abs(step.value ?? 0) / maxAbs) * 100)}%`
        return (
          <div key={step.key} className={cn("dcf-waterfall-row", step.kind)}>
            <span>{step.label}</span>
            <div className="dcf-waterfall-track">
              <div className={cn("dcf-waterfall-fill", step.kind, (step.value ?? 0) < 0 && "neg")} style={{ width }} />
            </div>
            <strong>{formatDcfStepValue(step)}</strong>
          </div>
        )
      })}
    </div>
  )
}


function DcfCoherenceChips({ dcf, row }: { dcf: DcfAvailableViewModel; row: FundamentalValuationResult }) {
  const chips = [
    { key: "g_lt_r", label: `g < ${dcf.rateLabel}`, ok: dcf.flags.gBelowRate },
    { key: "tv_weight", label: "TV < 75%", ok: !dcf.flags.terminalHeavy },
    { key: "proxy", label: row.is_proxy ? "Proxy" : "Non proxy", ok: !row.is_proxy },
    { key: "mid_year", label: dcf.midYearDiscounting ? "Mid-year ON" : "Mid-year OFF", ok: true },
    { key: "terminal", label: dcf.midYearTerminal ? "TV mid-year" : "TV full-year", ok: true },
    ...dcf.reconciliations.map((item) => ({ key: item.key, label: item.ok ? `${item.label} OK` : `${item.label} ecart`, ok: item.ok })),
  ]
  return (
    <div className="dcf-chip-row">
      {chips.map((chip) => (
        <span key={chip.key} className={cn("dcf-check-chip", chip.ok ? "ok" : "warn")}>{chip.label}</span>
      ))}
    </div>
  )
}


export function DcfMethodView({
  row,
  detail,
  isIncluded,
  effectiveWeight,
  sensitivity,
  dcfMode,
  selectedHorizon,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  isIncluded: boolean
  effectiveWeight: number | null
  sensitivity?: FundamentalSensitivity
  dcfMode: DcfMode
  selectedHorizon: FundamentalHorizon
}) {
  const meta = valuationFormulaMeta(row.model)
  const dcf = buildDcfViewModel(row, detail, dcfMode) as DcfViewModel
  const projection = projectionFromDetail(detail, selectedHorizon)
  const statementGroups = statementEvidence(detail, row.model, selectedHorizon)
  const assumptions = valuationAssumptionItems(row, detail)
  const inputs = technicalInputItems(row)
  const outputs = outputItems(row)
  const formulaValues = instantiatedFormula(row, detail)
  const isUnavailable = row.confidence === "unavailable" || !dcf.available
  const effectiveFairValue = fairValueForValuationRow(row, null)
  const currency = row.currency ?? detail.ensemble?.currency ?? "MAD"
  const fairValue = effectiveFairValue != null ? `${fmtMoney(effectiveFairValue, 1)} ${currency}` : "-"
  const current = currentPriceForValuationRow(row, detail)
  const currentPrice = current != null ? `${fmtMoney(current, 1)} ${currency}` : "-"
  const displayUpside = upsideForFairValue(effectiveFairValue, current) ?? row.upside_pct

  return (
    <section className={cn("valuation-method-card dcf-method-card", isUnavailable && "unavailable", !isIncluded && row.family !== "diagnostic" && "excluded")}>
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
          <div className={cn("dcf-verdict", (displayUpside ?? 0) >= 0 ? "positive" : "negative")}>{dcfVerdict(displayUpside, dcfMode)}</div>
        </div>
        <div className="valuation-method-metrics">
          <StatTile label="Fair value" value={fairValue} />
          <StatTile label="Current" value={currentPrice} />
          <StatTile label="Upside" value={fmtPct(displayUpside)} tone={(displayUpside ?? 0) >= 0 ? "t-pos" : "t-neg"} />
          <StatTile label="Weight" value={!isIncluded && row.family !== "diagnostic" ? "Excluded" : effectiveWeight == null ? "-" : `${(effectiveWeight * 100).toFixed(0)}%`} />
        </div>
      </div>

      <div className="valuation-formula-panel">
        <div className="valuation-formula-eyebrow">Formule utilisee</div>
        <div className="valuation-formula-line">{formulaValues ?? meta.formula}</div>
        {formulaValues ? <div className="valuation-formula-sub">{meta.formula}</div> : null}
        {meta.secondaryFormula ? <div className="valuation-formula-sub">{meta.secondaryFormula}</div> : null}
        <p>{meta.explanation}</p>
      </div>

      {!dcf.available ? (
        <>
          <CostOfCapitalBuildUp detail={detail} row={row} />
          <div className="fund-empty-small">{dcf.reason}</div>
        </>
      ) : (
        <>
          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>1</span>
              <div>
                <div className="valuation-mini-title">Taux d'actualisation</div>
                <p>
                  {dcf.mode === "fcff" ? (
                    <>
                      <GlossaryTerm id="fcff">FCFF</GlossaryTerm> = flux a tous les apporteurs de capital, actualise au{" "}
                      <GlossaryTerm id="wacc">WACC</GlossaryTerm>.
                    </>
                  ) : (
                    <>
                      <GlossaryTerm id="fcfe">FCFE</GlossaryTerm> = flux aux actionnaires, actualise au{" "}
                      <GlossaryTerm id="cost-of-equity">cout des fonds propres</GlossaryTerm>.
                    </>
                  )}
                </p>
              </div>
            </div>
            <CostOfCapitalBuildUp detail={detail} row={row} />
          </div>

          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>2</span>
              <div>
                <div className="valuation-mini-title">Flux projetes et actualisation</div>
                <p>
                  Chaque flux projete est actualise avec {dcf.rateLabel} {fmtPct(dcf.discountRate, 2, false)} et sa periode{" "}
                  <GlossaryTerm id="discount-period">t</GlossaryTerm>. L'historique realise situe le point de depart des projections.
                </p>
              </div>
            </div>
            {projection ? <DcfHistoryStrip projection={projection} mode={dcf.mode} cashFlowLabel={dcf.cashFlowLabel} /> : null}
            <DcfPvTable dcf={dcf} />
          </div>

          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>3</span>
              <div>
                <div className="valuation-mini-title"><GlossaryTerm id="terminal-value">Valeur terminale</GlossaryTerm></div>
                <p>
                  Perpetuite Gordon avec le <GlossaryTerm id="terminal-growth">g terminal</GlossaryTerm> du modele: elle resume
                  tous les flux au-dela de l'horizon explicite.
                </p>
              </div>
            </div>
            <DcfTerminalBlock dcf={dcf} />
          </div>

          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>4</span>
              <div>
                <div className="valuation-mini-title"><GlossaryTerm id="net-debt-bridge">Pont vers la valeur par action</GlossaryTerm></div>
                <p>
                  {dcf.mode === "fcff" ? (
                    <>EV moins dette nette ({dcf.netDebtSource ?? "source non renseignee"}) puis division par les actions.</>
                  ) : (
                    <>FCFE est deja un flux aux actionnaires: aucun pont dette nette.</>
                  )}
                </p>
              </div>
            </div>
            <div className="dcf-value-grid">
              <DcfValueWaterfall dcf={dcf} />
              <ModelValueGrid
                title="Reconciliation"
                items={dcf.bridgeSteps.map((step) => ({ key: step.key, label: step.label, value: step.value, source: step.kind }))}
                empty="No bridge rows."
              />
            </div>
          </div>

          <ModelSensitivityPanel row={row} detail={detail} sensitivity={sensitivity} />

          {projection ? (
            <div>
              <div className="valuation-subtitle">Construction du flux</div>
              <div className="driver-evidence-grid">
                <DriverEvidenceChart driver={projection.drivers[dcf.mode]} label={dcf.cashFlowLabel} format="money" />
                <FcfBridge projection={projection} mode={dcf.mode} />
              </div>
            </div>
          ) : null}

          <div className="valuation-method-grid">
            <ModelValueGrid title="Hypotheses du modele" items={assumptions} empty="No scenario assumptions persisted." />
          </div>

          <DcfCoherenceChips dcf={dcf} row={row} />

          <details className="dcf-raw-disclosure">
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
        </>
      )}

      <div className="valuation-warning-row">
        <span className="valuation-warning-label">Provenance</span>
        <div className="flex flex-wrap gap-1.5">
          {row.warnings.length ? row.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{valuationWarningLabel(warning)}</span>) : <span className="text-xs text-muted-foreground">Aucun avertissement.</span>}
        </div>
      </div>
    </section>
  )
}
