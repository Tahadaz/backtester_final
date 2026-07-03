"use client"

import {
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import { TriangulationBand } from "@/components/strategy/triangulation-band"
import {
  FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD,
  MODEL_GLOSSARY_IDS,
  MODEL_LABELS,
  MODEL_ORDER,
  SCENARIOS,
  SEVERE_VALUATION_WARNINGS,
  SEVERE_VALUATION_WARNING_LABELS_FR,
} from "../lib/constants"
import { asNumber, fmtCompactMad, fmtMoney, fmtNumber, fmtPct, scoreClass } from "../lib/formatters"
import { FundCard, RecChip } from "../shared/cards"
import { FootballField } from "../shared/charts"
import { VerdictChip, type VerdictTone } from "../shared/verdict-chip"
import { DetailTab, Scenario } from "../lib/types"
import {
  buildValuationSelectionSummary,
  comparableModelSummary,
  enabledRelativeValuationMetrics,
  rowAdv20,
  rowUpside,
  screenRecord,
  screensFor,
  sortValuationRows,
  valuationMethods,
} from "../lib/view-models"
import { useOptionalSelectedComparableView } from "../panels/comparables"

function scenarioProbability(detail: FundamentalStockDetail, scenario: Scenario): number {
  const fromPayload = asNumber(detail.scenario_probabilities?.[scenario])
  if (fromPayload != null) return fromPayload
  const fromAssumptions = asNumber(detail.assumptions[`scenario_probability_${scenario}`])
  if (fromAssumptions != null) return fromAssumptions
  return 1 / SCENARIOS.length
}


function buildScenarios(detail: FundamentalStockDetail, targetOverride?: number | null) {
  const ensembleFor = (key: Scenario) => detail.ensembles?.[key]
  const current =
    detail.ensemble?.current_price ??
    ensembleFor("base")?.current_price ??
    ensembleFor("bear")?.current_price ??
    ensembleFor("bull")?.current_price ??
    asNumber(detail.metrics.Current_Price)
  const hasOverride = targetOverride !== undefined
  const selectedFairValue = detail.ensemble?.fair_value_base ?? detail.target_price ?? null
  const base = hasOverride
    ? targetOverride
    : ensembleFor("base")?.fair_value_base ?? (detail.ensemble?.scenario === "base" ? selectedFairValue : null) ?? detail.target_price ?? null
  const bear = hasOverride
    ? (base != null ? base * 0.85 : null)
    : ensembleFor("bear")?.fair_value_base ??
      (detail.ensemble?.scenario === "bear" ? selectedFairValue : null) ??
      detail.ensemble?.fair_value_low ??
      detail.ensemble?.monte_carlo_low ??
      (base != null ? base * 0.85 : null)
  const bull = hasOverride
    ? (base != null ? base * 1.15 : null)
    : ensembleFor("bull")?.fair_value_base ??
      (detail.ensemble?.scenario === "bull" ? selectedFairValue : null) ??
      detail.ensemble?.fair_value_high ??
      detail.ensemble?.monte_carlo_high ??
      (base != null ? base * 1.15 : null)
  return [
    {
      key: "bear",
      label: "Bear - downside",
      probability: scenarioProbability(detail, "bear"),
      price: bear,
      tone: "bear",
      drivers: ["Marge sous pression", "Multiples sectoriels en contraction", "Hausse du coût du capital"],
    },
    {
      key: "base",
      label: "Base - central",
      probability: scenarioProbability(detail, "base"),
      price: base,
      tone: "base",
      drivers: ["Exécution conforme aux tendances historiques", "Pondération multi-modèles active", "Qualité des données intégrée"],
    },
    {
      key: "bull",
      label: "Bull - upside",
      probability: scenarioProbability(detail, "bull"),
      price: bull,
      tone: "bull",
      drivers: ["Expansion des marges", "Re-rating de multiples", "Conversion cash meilleure que prévu"],
    },
  ].map((scenario) => ({
    ...scenario,
    upside: scenario.price != null && current != null && current > 0 ? scenario.price / current - 1 : null,
  }))
}


// tone derived directly from scoreClass's three bands, so "reuse scoreClass" is literal.
function toneFromScoreClass(value: number | null | undefined): VerdictTone {
  const cls = scoreClass(value)
  if (cls === "t-pos") return "good"
  if (cls === "t-neg") return "serious"
  if (value == null) return "neutral"
  return "neutral"
}

function scoreBandLabel(value: number | null | undefined): string {
  if (value == null) return ""
  if (value >= 70) return "élevé"
  if (value <= 35) return "faible"
  return "moyen"
}

type RiskRow = { key: string; tone: VerdictTone; label: string; text: string }

function VerdictStripChip({
  tone,
  label,
  glossaryId,
  onNavigate,
  tab,
  anchor,
}: {
  tone: VerdictTone
  label: string
  glossaryId?: string
  onNavigate?: (tab: DetailTab, anchor?: string) => void
  tab?: DetailTab
  anchor?: string
}) {
  return (
    <VerdictChip
      tone={tone}
      label={label}
      glossaryId={glossaryId}
      onClick={onNavigate && tab ? () => onNavigate(tab, anchor) : undefined}
    />
  )
}

export function SyntheseTab({
  detail,
  row,
  rows,
  onNavigate,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  onNavigate: (tab: DetailTab, anchor?: string) => void
}) {
  const scenarios = buildScenarios(detail)
  const expected = scenarios.some((scenario) => scenario.price != null) ? scenarios.reduce((sum, scenario) => sum + (scenario.price ?? 0) * scenario.probability, 0) : null
  const recommendation = detail.recommendation ?? row?.recommendation ?? null
  const fairValue = detail.target_price ?? (recommendation !== "NR" ? detail.ensemble?.fair_value_base : null)
  const upside = detail.ensemble?.upside_pct ?? rowUpside(row)
  const screens = screensFor(detail, row)
  const altman = screenRecord(screens, "altman_z")
  const evaScreen = screenRecord(screens, "eva")
  const currentPrice = detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)

  // --- Comparables view (default "sector" benchmark, same view-model as Valorisation/Comparables). ---
  const { comparables, isLoading: isComparablesLoading } = useOptionalSelectedComparableView(detail, row, rows, "sector")
  const relativeMetricKeys = enabledRelativeValuationMetrics(detail)
  const comparableSummary = comparables ? comparableModelSummary(comparables, currentPrice, relativeMetricKeys) : null

  // --- Football field: same building blocks as Valorisation's summary block. ---
  const selectionSummary = buildValuationSelectionSummary({
    rows: sortValuationRows(detail.valuations),
    excludedModelIds: new Set(),
    comparableSummary,
    currentPrice,
    weightMode: "ic",
  })
  const methods = valuationMethods(detail, detail.valuations, comparableSummary, selectionSummary)
  const footballTarget = selectionSummary.fairValue ?? detail.target_price ?? detail.ensemble?.fair_value_base ?? null
  const footballModels = MODEL_ORDER.filter((model) => methods.some((method) => method.key === model))

  // --- Verdict strip ---
  const valorisationTone: VerdictTone = upside == null ? "neutral" : upside >= 0.10 ? "good" : upside <= -0.10 ? "serious" : "neutral"
  const valorisationLabel =
    upside == null
      ? "Non renseigné"
      : upside >= 0.10
        ? `Décoté de ${fmtPct(Math.abs(upside), 0, false)}`
        : upside <= -0.10
          ? `Cher de ${fmtPct(Math.abs(upside), 0, false)}`
          : "Proche de sa valeur"

  const valueScore = asNumber(detail.scores.value) ?? row?.value_score ?? null
  const qualityScore = asNumber(detail.scores.quality) ?? row?.quality_score ?? null

  const altmanZoneRaw = typeof altman.zone === "string" ? altman.zone : null
  const altmanApplicable = altman.applicable !== false
  const altmanTone: VerdictTone = !altmanApplicable || altmanZoneRaw == null
    ? "neutral"
    : altmanZoneRaw === "safe"
      ? "good"
      : altmanZoneRaw === "grey"
        ? "warning"
        : "serious"
  const altmanLabel = !altmanApplicable
    ? "Non applicable (financier)"
    : altmanZoneRaw == null
      ? "Non renseigné"
      : altmanZoneRaw === "safe"
        ? "Zone saine"
        : altmanZoneRaw === "grey"
          ? "Zone grise"
          : "Zone de fragilité"

  const evaApplicable = evaScreen.applicable !== false
  const evaRoic = asNumber(evaScreen.roic)
  const evaWacc = asNumber(evaScreen.wacc_used)
  const evaSpread = asNumber(evaScreen.roic_spread) ?? (evaRoic != null && evaWacc != null ? evaRoic - evaWacc : null)
  const evaTone: VerdictTone = !evaApplicable ? "neutral" : evaSpread == null ? "neutral" : evaSpread >= 0 ? "good" : "serious"
  const evaLabel = !evaApplicable
    ? "Non applicable (financier)"
    : evaSpread == null
      ? "Non renseigné"
      : evaSpread >= 0
        ? `Crée de la valeur (+${fmtPct(Math.abs(evaSpread), 1, false)})`
        : `Détruit de la valeur (${fmtPct(evaSpread, 1, false)})`

  const vsPairsUpside = comparableSummary?.upside ?? null
  const vsPairsTone: VerdictTone = vsPairsUpside == null ? "neutral" : vsPairsUpside >= 0.10 ? "good" : vsPairsUpside <= -0.10 ? "serious" : "neutral"
  const vsPairsLabel =
    vsPairsUpside == null
      ? "Non renseigné"
      : vsPairsUpside >= 0.10
        ? `Décoté de ${fmtPct(Math.abs(vsPairsUpside), 0, false)} vs pairs`
        : vsPairsUpside <= -0.10
          ? `Prime de ${fmtPct(Math.abs(vsPairsUpside), 0, false)} vs pairs`
          : "Proche des pairs"

  const adv20 = asNumber(detail.metrics?.ADV20) ?? rowAdv20(row)
  const liquidityTone: VerdictTone = adv20 == null ? "neutral" : adv20 >= FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD ? "good" : "warning"
  const liquidityLabel = adv20 == null ? "Non renseigné" : adv20 >= FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD ? "Liquide" : "Liquidité faible"

  // --- Catalysts & risks (real-data-only, brief 57 §4.1.6). ---
  // No earnings/report-date field exists yet on FundamentalStockDetail, so catalysts
  // always render the empty state until a real calendar is wired up (tracked out of scope).
  const riskRows: RiskRow[] = []
  if (altmanApplicable && (altmanZoneRaw === "grey" || altmanZoneRaw === "distress")) {
    riskRows.push({
      key: "altman",
      tone: altmanZoneRaw === "distress" ? "serious" : "warning",
      label: "Bilan",
      text: `Zone Altman : ${altmanLabel.toLowerCase()}.`,
    })
  }
  const triggeredSevereWarnings = new Map<string, string[]>()
  for (const valuation of detail.valuations) {
    for (const warning of valuation.warnings ?? []) {
      if (!SEVERE_VALUATION_WARNINGS.has(warning)) continue
      const models = triggeredSevereWarnings.get(warning) ?? []
      models.push(valuation.model)
      triggeredSevereWarnings.set(warning, models)
    }
  }
  for (const [warning, models] of triggeredSevereWarnings) {
    riskRows.push({
      key: `warning-${warning}`,
      tone: "serious",
      label: "Valorisation",
      text: `${SEVERE_VALUATION_WARNING_LABELS_FR[warning] ?? warning} (${models.join(", ")}).`,
    })
  }
  if (adv20 != null && adv20 < FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD) {
    riskRows.push({
      key: "liquidity",
      tone: "warning",
      label: "Liquidité",
      text: `ADV20 (${fmtCompactMad(adv20)} MAD) sous le seuil de ${fmtCompactMad(FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD)} MAD.`,
    })
  }

  return (
    <div className="fund-gap">
      <div className="flex flex-wrap gap-1.5">
        <VerdictStripChip tone={valorisationTone} label={valorisationLabel} glossaryId="upside" onNavigate={onNavigate} tab="valuation" anchor="valorisation-section" />
        <VerdictStripChip
          tone={toneFromScoreClass(valueScore)}
          label={valueScore == null ? "Non renseigné" : `Value ${fmtNumber(valueScore, 0)} — ${scoreBandLabel(valueScore)}`}
          glossaryId="score-composite"
          onNavigate={onNavigate}
          tab="quality"
          anchor="qualite-section"
        />
        <VerdictStripChip
          tone={toneFromScoreClass(qualityScore)}
          label={qualityScore == null ? "Non renseigné" : `Qualité ${fmtNumber(qualityScore, 0)} — ${scoreBandLabel(qualityScore)}`}
          glossaryId="score-composite"
          onNavigate={onNavigate}
          tab="quality"
          anchor="qualite-section"
        />
        <VerdictStripChip tone={altmanTone} label={altmanLabel} glossaryId="altman-z" onNavigate={onNavigate} tab="quality" anchor="qualite-section" />
        <VerdictStripChip tone={evaTone} label={evaLabel} glossaryId="eva" onNavigate={onNavigate} tab="quality" anchor="qualite-section" />
        <VerdictStripChip
          tone={vsPairsTone}
          label={isComparablesLoading && vsPairsUpside == null ? "..." : vsPairsLabel}
          glossaryId="relative-multiples"
          onNavigate={onNavigate}
          tab="quality"
          anchor="comparables-section"
        />
        <VerdictStripChip tone={liquidityTone} label={liquidityLabel} glossaryId="adv20" />
      </div>

      <div>
        <FundCard title="Football field — fourchettes de juste valeur par modèle">
          <FootballField methods={methods} currentPrice={currentPrice} targetPrice={footballTarget} />
          {footballModels.length ? (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
              {footballModels.map((model) => (
                <span key={model}>
                  <GlossaryTerm id={MODEL_GLOSSARY_IDS[model] ?? "dcf"}>{modelLabel(model)}</GlossaryTerm>
                </span>
              ))}
            </div>
          ) : null}
          <div className="mt-2 text-[11px] text-muted-foreground">
            Fourchettes de juste valeur par modèle ; la ligne verticale est le cours actuel.
          </div>
        </FundCard>
      </div>

      <div data-capture="scenarios">
        <div className="fund-section-label">Scénarios à 12 mois — fourchette bear/base/bull</div>
        <div className="scn-grid">
          {scenarios.map((scenario) => (
            <div key={scenario.key} className={cn("scn-card", scenario.tone)}>
              <div className="scn-hdr">
                <span className={cn("scn-lbl", scenario.tone)}>{scenario.label} - {(scenario.probability * 100).toFixed(0)}%</span>
                <span className="scn-prob">P={scenario.probability.toFixed(2)}</span>
              </div>
              <span className={cn("scn-price", scenario.key === "bear" ? "t-neg" : scenario.key === "bull" ? "t-pos" : "text-[oklch(0.30_0.14_260)]")}>{fmtMoney(scenario.price, 1)} MAD</span>
              <span className={cn("scn-up", (scenario.upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(scenario.upside)}</span>
              <ul className="scn-drivers">
                {scenario.drivers.map((driver) => (
                  <li key={driver}>{driver}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-2 text-right text-[11px] text-muted-foreground">
          Valeur pondérée par scénario (probabilités maison) = <strong className="text-foreground">{fmtMoney(expected, 1)} MAD</strong>
        </div>
      </div>

      <TriangulationBand triangulation={detail.triangulation} />

      <div className="fund-thesis">
        <div className="fund-eyebrow">Thèse d'investissement</div>
        {recommendation ? (
          <p>
            {detail.symbol} ressort à <RecChip value={recommendation} /> avec un objectif 12 mois de <strong>{fmtMoney(fairValue, 2)} {detail.ensemble?.currency ?? "MAD"}</strong>, soit un potentiel de{" "}
            <strong className={(upside ?? 0) >= 0 ? "t-pos" : "t-neg"}>{fmtPct(upside)}</strong>. La recommandation combine la juste valeur issue des modèles, la confiance de l'ensemble et l'étendue des modèles utilisables.
          </p>
        ) : (
          <p>
            {detail.symbol} n'a pas de recommandation valorisation exploitable. Les scores fondamentaux restent disponibles, mais l'objectif 12 mois attend un ensemble de modèles avec prix cible et confiance calculés.
          </p>
        )}
      </div>

      <FundCard title="Catalyseurs & Risques">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <div className="fund-section-label">Catalyseurs</div>
            <div className="fund-empty-small">Aucun catalyseur renseigné pour ce titre.</div>
          </div>
          <div>
            <div className="fund-section-label">Risques</div>
            {riskRows.length === 0 ? (
              <div className="fund-empty-small">Aucun signal de risque déclenché par les écrans.</div>
            ) : (
              <div className="space-y-2">
                {riskRows.map((riskRow) => (
                  <div key={riskRow.key} className="flex flex-col gap-1 border-b border-line pb-2 last:border-0 last:pb-0">
                    <VerdictChip tone={riskRow.tone} label={riskRow.label} />
                    <span className="text-[12px] text-muted-foreground">{riskRow.text}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </FundCard>
    </div>
  )
}

function modelLabel(model: string): string {
  return MODEL_LABELS[model] ?? model
}
