"use client"

import type { ReactNode } from "react"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import {
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { COMPARABLE_METRIC_GLOSSARY_IDS } from "../lib/constants"
import { asNumber, asRatio, asRecord, fmtMoney, fmtNumber, fmtPct, fmtRatio, recordNumber, scoreClass } from "../lib/formatters"
import { ComparableBenchmarkPanel } from "../panels/comparables"
import { FundCard, ScoreChip, StatTile } from "../shared/cards"
import { VerdictChip, type VerdictTone } from "../shared/verdict-chip"
import { screenRecord, screensFor } from "../lib/view-models"

function DupontBox({ label, value, sub, result }: { label: string; value: string; sub?: string; result?: boolean }) {
  return (
    <div className={cn("dp-box", result && "result")}>
      <span className="dp-lbl">{label}</span>
      <span className="dp-val">{value}</span>
      {sub ? <span className="dp-peer">{sub}</span> : null}
      <div className="dp-bar-bg">
        <div className="dp-bar-fill" style={{ width: "68%", background: result ? "var(--pri-dim)" : "var(--primary)" }} />
      </div>
    </div>
  )
}


function screenWarnings(screen: Record<string, unknown>): string[] {
  return Array.isArray(screen.warnings) ? screen.warnings.map((warning) => String(warning)) : []
}


function ScreenWarningChips({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {warnings.map((warning) => (
        <span key={warning} className="fund-warning-chip">{warning}</span>
      ))}
    </div>
  )
}


function ScreenUnavailable({ message, warnings }: { message: string; warnings: string[] }) {
  return (
    <>
      <div className="fund-empty-small">{message}</div>
      <ScreenWarningChips warnings={warnings} />
    </>
  )
}


function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map((item) => asRecord(item)).filter((item) => Object.keys(item).length > 0) : []
}


function rawMetricLabel(item: Record<string, unknown>): string {
  const metric = String(item.metric_name ?? "-")
  const year = item.statement_year == null ? "" : ` FY${String(item.statement_year)}`
  return `${metric}${year}: ${fmtMoney(recordNumber(item, "value"), 0)}`
}


function rawRatioTitle(raw: Record<string, unknown>): string {
  const numerator = asRecord(raw.numerator)
  const denominator = asRecord(raw.denominator)
  const numeratorMetrics = asRecordArray(numerator.metrics)
  const numeratorLabel = String(numerator.label ?? "Numérateur")
  const denominatorLabel = String(denominator.label ?? "Dénominateur")
  const numeratorText = numeratorMetrics.length
    ? numeratorMetrics.map(rawMetricLabel).join(" ; ")
    : `${numeratorLabel}: ${fmtMoney(recordNumber(numerator, "value"), 0)}`
  const denominatorText = `${denominatorLabel} (${String(denominator.metric_name ?? "-")} FY${String(denominator.statement_year ?? "-")}): ${fmtMoney(recordNumber(denominator, "value"), 0)}`
  return `${numeratorLabel}: ${fmtMoney(recordNumber(numerator, "value"), 0)} [${numeratorText}] / ${denominatorText}`
}


function comparisonTitle(comparison: Record<string, unknown>): string {
  const current = asRecord(comparison.current)
  const prior = asRecord(comparison.prior)
  const operator = String(comparison.operator ?? "")
  if (Object.keys(prior).length) return `${rawMetricLabel(current)} ${operator} ${rawMetricLabel(prior)}`
  return `${rawMetricLabel(current)} ${operator}`
}


function RatioBreakdown({ raw, comparison, children }: { raw?: unknown; comparison?: unknown; children: ReactNode }) {
  const rawRecord = asRecord(raw)
  const comparisonRecord = asRecord(comparison)
  const title = Object.keys(rawRecord).length
    ? rawRatioTitle(rawRecord)
    : Object.keys(comparisonRecord).length
      ? comparisonTitle(comparisonRecord)
      : undefined
  return <span title={title}>{children}</span>
}


function peerScopeLabel(scope: string, cohortSize: number | null, sector: string | null | undefined): string {
  const n = cohortSize != null ? ` (n=${fmtNumber(cohortSize, 0)})` : ""
  if (scope === "sector") return `Secteur${sector ? ` ${sector}` : ""}${n}`
  if (scope === "market") return `Marché${n}`
  return "Échantillon insuffisant"
}


function peerDeviationLabel(zScore: number | null, pctDeviation: number | null): string | null {
  if (zScore != null) return `${zScore > 0 ? "+" : ""}${fmtNumber(zScore, 1)} sigma`
  if (pctDeviation != null) return `${fmtPct(pctDeviation, 0)} vs médiane`
  return null
}


function peerBarColor(score: number | null): string {
  if (score == null) return "var(--muted-foreground)"
  if (score >= 70) return "var(--pos)"
  if (score <= 35) return "var(--neg)"
  return "var(--primary)"
}


function peerValueTone(direction: "pos" | "neg", own: number | null, median: number | null): string {
  if (own == null || median == null) return "text-foreground"
  const favorable = direction === "neg" ? own <= median : own >= median
  return favorable ? "t-pos" : "t-neg"
}


type PeerMetricFormat = "pct" | "x" | "number"


type PeerMetricDirection = "pos" | "neg"


type PeerMetricRow = readonly [label: string, metric: string, format: PeerMetricFormat, direction: PeerMetricDirection]


function formatPeerMetricValue(value: number | null, format: PeerMetricFormat): string {
  if (format === "pct") return fmtPct(asRatio(value), 1, false)
  if (format === "x") return fmtRatio(value, 1)
  return fmtNumber(value, 0)
}


function PeerMetricRows({
  rows,
  metricBreakdown,
  detail,
}: {
  rows: readonly PeerMetricRow[]
  metricBreakdown: Record<string, unknown>
  detail: FundamentalStockDetail
}) {
  return (
    <div className="peer-list peer-list-detail">
      {rows.map(([label, metric, format, direction]) => {
        const entry = asRecord(metricBreakdown[metric])
        const score = recordNumber(entry, "score")
        const scope = String(entry.scope ?? "insufficient")
        const cohortSize = recordNumber(entry, "cohort_size")
        const own = recordNumber(entry, "value") ?? asNumber(detail.metrics[metric])
        const median = recordNumber(entry, "median")
        const insufficient = score == null || scope === "insufficient"
        const percentile = Math.max(0, Math.min(100, score ?? 0))
        const deviation = peerDeviationLabel(recordNumber(entry, "z_score"), recordNumber(entry, "pct_deviation_from_median"))
        const ownText = formatPeerMetricValue(own, format)
        const peerText = formatPeerMetricValue(median, format)
        const glossaryId = COMPARABLE_METRIC_GLOSSARY_IDS[metric]
        return (
          <div key={metric} className="peer-row">
            <div className="peer-label">
              <span>{glossaryId ? <GlossaryTerm id={glossaryId}>{label}</GlossaryTerm> : label}</span>
              <span className={cn("peer-scope-badge", scope === "sector" && "peer-scope-badge-sector", insufficient && "peer-scope-badge-muted")}>
                {peerScopeLabel(scope, cohortSize, detail.sector)}
              </span>
            </div>
            <div className="peer-bar-wrap">
              {insufficient ? (
                <div className="peer-bar-empty">{own == null ? "donnée indisponible" : "cohorte trop petite (n<3)"}</div>
              ) : (
                <>
                  <div className="peer-bar">
                    <div className="peer-bar-fill" style={{ width: `${percentile}%`, background: peerBarColor(score) }} />
                    <div className="peer-bar-mark" style={{ left: "50%" }} />
                  </div>
                  <div className="peer-caption">
                    Centile <span className={cn("font-mono font-bold", scoreClass(score))}>{fmtNumber(score, 0)}</span>/100{deviation ? ` - ${deviation}` : ""}
                  </div>
                </>
              )}
            </div>
            <span className="peer-number r">
              <small>Titre</small>
              <strong className={cn("font-mono", peerValueTone(direction, own, median))}>{ownText}</strong>
            </span>
            <span className="peer-number r">
              <small>Médiane</small>
              <strong className="font-mono text-muted-foreground">{peerText}</strong>
            </span>
          </div>
        )
      })}
    </div>
  )
}


const ALTMAN_TERM_DEFS = [
  ["wc_ta", "X1", "Fonds de roulement / Actif total", "liquidité court terme", 6.56],
  ["re_ta", "X2", "Réserves (report à nouveau) / Actif total", "rentabilité cumulée / âge", 3.26],
  ["ebit_ta", "X3", "Résultat d'exploitation (EBIT) / Actif total", "productivité opérationnelle", 6.72],
  ["equity_tl", "X4", "Capitaux propres comptables / Total des dettes", "solvabilité", 1.05],
] as const


function altmanTermRows(altman: Record<string, unknown>) {
  const payloadTerms = asRecordArray(altman.terms)
  if (payloadTerms.length) {
    return payloadTerms.map((term) => {
      const ratio = recordNumber(term, "ratio")
      const coefficient = recordNumber(term, "coefficient")
      return {
        key: String(term.key ?? term.term ?? ""),
        term: String(term.term ?? term.key ?? ""),
        label: String(term.label ?? term.key ?? ""),
        meaning: String(term.meaning ?? ""),
        ratio,
        coefficient,
        contribution: recordNumber(term, "contribution") ?? (ratio != null && coefficient != null ? ratio * coefficient : null),
        raw: term.raw,
      }
    })
  }
  const components = asRecord(altman.components)
  return ALTMAN_TERM_DEFS.map(([key, term, label, meaning, coefficient]) => {
    const ratio = recordNumber(components, key)
    return {
      key,
      term,
      label,
      meaning,
      ratio,
      coefficient,
      contribution: ratio != null ? ratio * coefficient : null,
      raw: {},
    }
  })
}


function waccSourceLabel(source: unknown): string {
  if (source === "firm_build_up") return "WACC build-up firme"
  if (source === "assumption") return "WACC hypothèses"
  if (source === "default") return "WACC défaut univers"
  return "WACC source non précisée"
}


function altmanGaugePct(zValue: number | null): number | null {
  if (zValue == null) return null
  const z = Math.max(0, Math.min(3.5, zValue))
  if (z <= 1.1) return (z / 1.1) * 33
  if (z <= 2.6) return 33 + ((z - 1.1) / (2.6 - 1.1)) * 34
  return 67 + ((z - 2.6) / (3.5 - 2.6)) * 33
}


function ZoneGauge({ zValue, zone }: { zValue: number | null; zone: string | null }) {
  const pct = altmanGaugePct(zValue)
  return (
    <div>
      <div className="zone-gauge">
        <span className="danger" />
        <span className="watch" />
        <span className="safe" />
        {pct == null ? null : <i style={{ left: `${pct}%` }} />}
      </div>
      <div className="mt-2 flex justify-between text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        <span>&lt; 1.1</span>
        <span>{zValue == null ? "N/A" : `Z ${fmtNumber(zValue, 2)} - ${zone ?? "zone ?"}`}</span>
        <span>&gt; 2.6</span>
      </div>
    </div>
  )
}


// Plain-language Altman verdict, mirrored from synthese-tab's altmanTone/altmanLabel (brief 57 §4.1/§4.4).
function altmanVerdict(applicable: boolean, zone: string | null): { tone: VerdictTone; label: string } {
  if (!applicable) return { tone: "neutral", label: "Non applicable (financier)" }
  if (zone == null) return { tone: "neutral", label: "Non renseigné" }
  if (zone === "safe") return { tone: "good", label: "Zone saine" }
  if (zone === "grey") return { tone: "warning", label: "Zone grise" }
  return { tone: "serious", label: "Zone de fragilité" }
}


// Plain-language EVA / value-creation verdict, mirrored from synthese-tab's evaTone/evaLabel.
function evaVerdict(applicable: boolean, spread: number | null): { tone: VerdictTone; label: string } {
  if (!applicable) return { tone: "neutral", label: "Non applicable (financier)" }
  if (spread == null) return { tone: "neutral", label: "Non renseigné" }
  if (spread >= 0) return { tone: "good", label: `Crée de la valeur (ROIC > WACC, +${fmtPct(Math.abs(spread), 1, false)})` }
  return { tone: "serious", label: `Détruit de la valeur (ROIC < WACC, ${fmtPct(spread, 1, false)})` }
}


const PIOTROSKI_LABELS: Record<string, string> = {
  positive_roa: "ROA positif",
  positive_free_cash_flow: "FCF positif",
  roa_improving: "ROA en amélioration",
  cash_flow_exceeds_earnings: "FCF > résultat net",
  leverage_decreasing: "Levier en baisse",
  liquidity_improving: "Liquidité en amélioration",
  operating_margin_improving: "Marge opérationnelle en hausse",
  asset_turnover_improving: "Rotation des actifs en hausse",
  positive_revenue_growth: "Croissance du chiffre d'affaires positive",
}


// Magic Formula combined rank score (0-100) -> plain verdict.
function magicFormulaVerdict(score: number | null): { tone: VerdictTone; label: string } {
  if (score == null) return { tone: "neutral", label: "Non renseigné" }
  if (score >= 70) return { tone: "good", label: "Bon classement Magic Formula" }
  if (score <= 35) return { tone: "serious", label: "Classement Magic Formula faible" }
  return { tone: "neutral", label: "Classement Magic Formula moyen" }
}


const PEG_ZONE_VERDICTS: Record<string, { tone: VerdictTone; label: string }> = {
  very_cheap_growth: { tone: "good", label: "Croissance très bon marché (PEG < 0,75)" },
  cheap_growth: { tone: "good", label: "Croissance bon marché" },
  reasonable_growth: { tone: "neutral", label: "Prix raisonnable pour la croissance" },
  fairly_priced: { tone: "neutral", label: "Valorisation équitable vs croissance" },
  expensive_growth: { tone: "warning", label: "Croissance chère" },
  very_expensive: { tone: "serious", label: "Croissance très chère" },
}


function pegVerdict(zone: unknown): { tone: VerdictTone; label: string } {
  if (typeof zone === "string" && PEG_ZONE_VERDICTS[zone]) return PEG_ZONE_VERDICTS[zone]
  return { tone: "neutral", label: "Non renseigné" }
}


function QualiteScreensSection({ detail, row }: { detail: FundamentalStockDetail; row: FundamentalUniverseRow | null }) {
  const diagnostics = detail.diagnostics
  const dupont = asRecord(diagnostics.dupont)
  const metricBreakdown = asRecord(diagnostics.metric_breakdown)
  const qualityComponents = asRecord(detail.scores.quality_components)
  const screens = screensFor(detail, row)
  const altman = screenRecord(screens, "altman_z")
  const evaScreen = screenRecord(screens, "eva")
  const altmanWarnings = screenWarnings(altman)
  const evaWarnings = screenWarnings(evaScreen)
  const piotroski = asRecord(diagnostics.piotroski_lite)
  const piotroskiChecks = asRecordArray(piotroski.checks)
  const altmanZ = recordNumber(altman, "z_value")
  const altmanApplicable = altman.applicable !== false
  const altmanZone = typeof altman.zone === "string" ? altman.zone : null
  const evaApplicable = evaScreen.applicable !== false
  const evaRoic = recordNumber(evaScreen, "roic")
  const evaWacc = recordNumber(evaScreen, "wacc_used")
  const evaSpread = recordNumber(evaScreen, "roic_spread") ?? (evaRoic != null && evaWacc != null ? evaRoic - evaWacc : null)
  const evaScale = Math.max(0.2, Math.abs(evaRoic ?? 0), Math.abs(evaWacc ?? 0))
  const accrualQuality = asRecord(diagnostics.accrual_quality)
  const altmanTerms = altmanTermRows(altman)
  const altmanContributionSum = altmanTerms.reduce((sum, term) => sum + (term.contribution ?? 0), 0)
  const evaComponents = asRecord(evaScreen.components)
  const evaEbit = recordNumber(evaComponents, "ebit")
  const evaTaxRate = recordNumber(evaComponents, "tax_rate")
  const evaNopat = recordNumber(evaScreen, "nopat")
  const evaDebt = recordNumber(evaComponents, "total_debt")
  const evaBookEquity = recordNumber(evaComponents, "book_equity")
  const evaInvestedCapital = recordNumber(evaScreen, "invested_capital")
  const evaWaccSource = waccSourceLabel(evaScreen.wacc_source)
  const valueScore = asNumber(detail.scores.value) ?? row?.value_score
  const qualityScore = asNumber(detail.scores.quality) ?? row?.quality_score
  const altmanBadge = altmanVerdict(altmanApplicable, altmanZone)
  const evaBadge = evaVerdict(evaApplicable, evaSpread)
  const valuePeerRows = [
    ["P/E", "PER", "x", "neg"],
    ["P/B", "Price_to_Book", "x", "neg"],
    ["P/S", "Price_to_Sales", "x", "neg"],
    ["EV/EBITDA", "EV_to_EBITDA", "x", "neg"],
    ["FCF yield", "FCF_Yield", "pct", "pos"],
    ["Div. yield", "Dividend_Yield", "pct", "pos"],
  ] as const satisfies readonly PeerMetricRow[]
  const qualityPeerRows = [
    ["ROE", "ROE", "pct", "pos"],
    ["ROA", "ROA", "pct", "pos"],
    ["Marge oper.", "Operating_Margin", "pct", "pos"],
    ["Marge nette", "Net_Margin", "pct", "pos"],
    ["FCF margin", "FCF_Margin", "pct", "pos"],
    ["Couverture intérêts", "Interest_Coverage", "x", "pos"],
    ["Dette / equity", "Debt_to_Equity", "x", "neg"],
  ] as const satisfies readonly PeerMetricRow[]

  return (
    <div className="fund-gap" data-capture="scoring">
      <div className="grid gap-3 md:grid-cols-2">
        <StatTile label="Score Value" value={fmtNumber(valueScore, 0)} tone={scoreClass(valueScore)} sub="Centile de cherté vs pairs" />
        <StatTile label="Score Quality" value={fmtNumber(qualityScore, 0)} tone={scoreClass(qualityScore)} sub="Rentabilité + discipline comptable" />
      </div>

      <FundCard title="Score Value - multiples vs pairs" aside={<ScoreChip value={valueScore} />}>
        <div className="quality-card-note">
          Rang centile du titre face à sa cohorte de pairs. Pour les multiples, plus bas = meilleur ; pour les yields, plus haut = meilleur. Cohorte = secteur si au moins 3 pairs, sinon marché.
        </div>
        <PeerMetricRows rows={valuePeerRows} metricBreakdown={metricBreakdown} detail={detail} />
      </FundCard>

      <FundCard id="piotroski-section" title="Score Quality - rentabilité, cash et bilan" aside={<ScoreChip value={qualityScore} />}>
        <div className="quality-card-note">
          Score headline = profitabilité relative, discipline comptable et qualité des cash-flows. Levier, liquidité et couverture restent des diagnostics de red flag, pas des piliers séparés.
        </div>
        <PeerMetricRows rows={qualityPeerRows} metricBreakdown={metricBreakdown} detail={detail} />
        <div className="mt-3 grid gap-3 md:grid-cols-5">
          <StatTile label="Profitabilité" value={fmtNumber(recordNumber(qualityComponents, "raw_percentile"), 0)} tone={scoreClass(recordNumber(qualityComponents, "raw_percentile"))} sub="ROE, ROA, marges" />
          <StatTile label="Discipline" value={fmtNumber(recordNumber(qualityComponents, "accounting_discipline"), 0)} tone={scoreClass(recordNumber(qualityComponents, "accounting_discipline"))} sub="DuPont + Piotroski" />
          <StatTile
            label={<GlossaryTerm id="dupont">DuPont</GlossaryTerm>}
            value={fmtNumber(recordNumber(qualityComponents, "dupont_bridge") ?? recordNumber(dupont, "score"), 0)}
            tone={scoreClass(recordNumber(qualityComponents, "dupont_bridge") ?? recordNumber(dupont, "score"))}
            sub="cohérence ROE"
          />
          <StatTile label="Piotroski" value={fmtNumber(recordNumber(qualityComponents, "piotroski_lite"), 0)} tone={scoreClass(recordNumber(qualityComponents, "piotroski_lite"))} sub="checks fondamentaux" />
          <StatTile label="Accruals" value={fmtNumber(recordNumber(qualityComponents, "accrual_quality") ?? recordNumber(accrualQuality, "score"), 0)} tone={scoreClass(recordNumber(qualityComponents, "accrual_quality") ?? recordNumber(accrualQuality, "score"))} sub={`cash ${fmtRatio(recordNumber(accrualQuality, "cash_conversion"), 2)}`} />
        </div>
        <details className="mt-3">
          <summary className="cursor-pointer text-[12px] font-semibold text-foreground">Détail Piotroski</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="claude-table min-w-[560px]">
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Statut</th>
                  <th>Valeur</th>
                  <th>Comparaison</th>
                </tr>
              </thead>
              <tbody>
                {piotroskiChecks.map((check) => {
                  const name = String(check.name ?? "")
                  const comparison = asRecord(check.comparison)
                  const available = check.available !== false
                  const passed = check.passed === true
                  return (
                    <tr key={name}>
                      <td>{PIOTROSKI_LABELS[name] ?? name}</td>
                      <td><VerdictChip tone={!available ? "neutral" : passed ? "good" : "warning"} label={!available ? "N/A" : passed ? "Pass" : "Fail"} /></td>
                      <td className="r font-mono">{fmtNumber(recordNumber(check, "value"), 3)}</td>
                      <td>
                        <RatioBreakdown comparison={comparison}>
                          <span className="underline decoration-dotted underline-offset-2">{comparisonTitle(comparison)}</span>
                        </RatioBreakdown>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </details>
      </FundCard>

      <div data-capture="diagnostics">
        <FundCard
          title={<><GlossaryTerm id="dupont">Décomposition DuPont</GlossaryTerm> - <GlossaryTerm id="roe">ROE</GlossaryTerm> {detail.latest_statement_year ?? ""}</>}
          aside="ROE = marge x rotation x levier"
        >
          <div className="dp-row">
            <DupontBox label="Marge nette" value={fmtPct(recordNumber(dupont, "net_margin"), 1, false)} />
            <span className="dp-op">x</span>
            <DupontBox label="Rotation actifs" value={fmtRatio(recordNumber(dupont, "asset_turnover"), 2)} />
            <span className="dp-op">x</span>
            <DupontBox label="Levier financier" value={fmtRatio(recordNumber(dupont, "equity_multiplier"), 2)} />
            <span className="dp-op">=</span>
            <DupontBox label="ROE composite" value={fmtPct(recordNumber(dupont, "reported_roe"), 1, false)} result />
          </div>
          <div className="mt-3 rounded-md border border-line bg-bg2 px-3 py-2 text-[11px] leading-5 text-muted-foreground">
            <strong className="text-foreground">Lecture :</strong> l'écart entre ROE reporté et ROE impliqué mesure la cohérence comptable du pont DuPont. Score DuPont: <span className="font-mono text-foreground">{fmtNumber(recordNumber(dupont, "score"), 0)}</span>.
          </div>
        </FundCard>
      </div>

      <FundCard
        id="altman-section"
        title={<><GlossaryTerm id="altman-z">Risque de défaut - Altman Z-score</GlossaryTerm></>}
        aside={<VerdictChip tone={altmanBadge.tone} label={altmanBadge.label} />}
      >
        {!altmanApplicable ? (
          <ScreenUnavailable message="Altman Z n'est pas appliqué aux secteurs financiers." warnings={altmanWarnings} />
        ) : altmanZ == null ? (
          <ScreenUnavailable message="Altman Z indisponible : données bilan, EBIT, chiffre d'affaires ou capitalisation manquantes." warnings={altmanWarnings} />
        ) : (
          <>
            <ZoneGauge zValue={altmanZ} zone={altmanZone} />
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <StatTile label="Z-score" value={fmtNumber(altmanZ, 2)} sub={String(altman.variant ?? "Altman Z")} />
              <StatTile label="Score" value={fmtNumber(recordNumber(altman, "score"), 0)} sub="0-100 dérivé de Z, clippé" />
              <StatTile label="Zone" value={String(altman.zone ?? "N/A")} />
            </div>
            <div className="quality-card-note mt-3">
              Score = 25 + (Z - 1,1) / (2,6 - 1,1) x 50, clippé entre 0 et 100. Seuils : Safe &gt; 2,6 ; zone grise 1,1-2,6 ; détresse &lt; 1,1. Variante : {String(altman.variant ?? "Z''_EM")}.
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="claude-table min-w-[560px]">
                <thead>
                  <tr>
                    <th>Terme</th>
                    <th>Ratio</th>
                    <th>Coeff.</th>
                    <th>Contribution</th>
                    <th>Lecture</th>
                  </tr>
                </thead>
                <tbody>
                  {altmanTerms.map((term) => (
                    <tr key={term.key || term.term}>
                      <td>
                        <RatioBreakdown raw={term.raw}>
                          <span className="font-semibold text-foreground underline decoration-dotted underline-offset-2">{term.term}</span>
                        </RatioBreakdown>{" "}
                        {term.label}
                      </td>
                      <td className="r font-mono">{fmtNumber(term.ratio, 3)}</td>
                      <td className="r font-mono">{fmtNumber(term.coefficient, 2)}</td>
                      <td className="r font-mono">{fmtNumber(term.contribution, 3)}</td>
                      <td>{term.meaning}</td>
                    </tr>
                  ))}
                  <tr>
                    <td className="font-semibold text-foreground">Somme des contributions = Z</td>
                    <td />
                    <td />
                    <td className="r font-mono font-bold">{fmtNumber(altmanContributionSum, 3)}</td>
                    <td className="font-mono text-muted-foreground">Z publié : {fmtNumber(altmanZ, 3)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="quality-methodology">{String(altman.methodology ?? "Altman Z'' emerging-market: 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4.")}</div>
            <ScreenWarningChips warnings={altmanWarnings} />
          </>
        )}
      </FundCard>

      <FundCard
        title={<><GlossaryTerm id="eva">Création de valeur</GlossaryTerm> - <GlossaryTerm id="roic">ROIC</GlossaryTerm> vs WACC</>}
        aside={<VerdictChip tone={evaBadge.tone} label={evaBadge.label} />}
      >
        {!evaApplicable ? (
          <ScreenUnavailable message="EVA n'est pas appliqué aux secteurs financiers." warnings={evaWarnings} />
        ) : evaRoic == null || evaWacc == null ? (
          <ScreenUnavailable message="EVA indisponible : EBIT, WACC ou capital investi manquant." warnings={evaWarnings} />
        ) : (
          <div className="space-y-3">
            <div className="quality-card-note">
              La société {(evaSpread ?? 0) >= 0 ? "crée" : "détruit"} de la valeur quand son rendement sur capital investi (ROIC) {(evaSpread ?? 0) >= 0 ? "dépasse" : "reste sous"} son coût du capital (WACC).
            </div>
            <div className="eva-compare">
              {[
                ["ROIC", evaRoic, "var(--pos)"],
                ["WACC", evaWacc, "var(--primary)"],
              ].map(([label, value, color]) => (
                <div key={label as string} className="eva-row">
                  <span>{label}</span>
                  <div className="peer-bar">
                    <div className="peer-bar-fill" style={{ width: `${Math.max(0, Math.min(100, (Math.abs(Number(value)) / evaScale) * 100))}%`, background: color as string }} />
                  </div>
                  <span className="font-mono font-bold">{fmtPct(value as number | null, 1, false)}</span>
                </div>
              ))}
              <div className="eva-spread-line">
                <span>Spread ROIC &minus; WACC</span>
                <strong className={cn("font-mono", (evaSpread ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(evaSpread, 2)}</strong>
              </div>
            </div>
            <div className="valuation-formula-panel">
              <div className="valuation-formula-eyebrow">Construction ROIC &amp; WACC</div>
              <div className="cost-build-formulas">
                <code>NOPAT = EBIT {fmtMoney(evaEbit, 0)} &times; (1 &minus; IS {fmtPct(evaTaxRate, 1, false)}) = {fmtMoney(evaNopat, 0)}</code>
                <code>Capital investi = dette {fmtMoney(evaDebt, 0)} + capitaux propres {fmtMoney(evaBookEquity, 0)} = {fmtMoney(evaInvestedCapital, 0)}</code>
                <code>ROIC = NOPAT {fmtMoney(evaNopat, 0)} / capital investi {fmtMoney(evaInvestedCapital, 0)} = {fmtPct(evaRoic, 2, false)}</code>
                <code>WACC = {fmtPct(evaWacc, 2, false)} &middot; source : {evaWaccSource}</code>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <StatTile label="EVA" value={fmtMoney(recordNumber(evaScreen, "eva_value"), 0)} sub="spread x capital" />
              <StatTile label="Marge EVA" value={fmtPct(recordNumber(evaScreen, "eva_margin"), 1, false)} />
              <StatTile label="Capital investi" value={fmtMoney(recordNumber(evaScreen, "invested_capital"), 0)} />
            </div>
            <ScreenWarningChips warnings={evaWarnings} />
          </div>
        )}
      </FundCard>
    </div>
  )
}


function ScreenSummaryCard({
  title,
  screen,
  verdict,
  children,
}: {
  title: ReactNode
  screen: Record<string, unknown>
  verdict?: { tone: VerdictTone; label: string }
  children?: ReactNode
}) {
  const score = recordNumber(screen, "score")
  const warnings = Array.isArray(screen.warnings) ? screen.warnings : []
  return (
    <FundCard
      title={title}
      aside={
        <span className="inline-flex items-center gap-2">
          <ScoreChip value={score} />
          {verdict ? <VerdictChip tone={verdict.tone} label={verdict.label} /> : null}
        </span>
      }
    >
      {children}
      {warnings.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {warnings.map((warning) => (
            <span key={String(warning)} className="fund-warning-chip">{String(warning)}</span>
          ))}
        </div>
      ) : null}
    </FundCard>
  )
}


function ComparablesPeerBenchmarkSection({
  detail,
  row,
  rows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
}) {
  const screens = screensFor(detail, row)
  const magic = screenRecord(screens, "magic_formula")
  const peg = screenRecord(screens, "peg_garp")
  const regression = screenRecord(screens, "regression_adj")
  const richness = asRecord(regression.regression_richness)
  const magicBadge = magicFormulaVerdict(recordNumber(magic, "score"))
  const pegBadge = pegVerdict(peg.zone)

  return (
    <div className="fund-gap">
      <ComparableBenchmarkPanel
        detail={detail}
        row={row}
        rows={rows}
        selectedComparatorId={selectedComparatorId}
        onSelectedComparatorIdChange={onSelectedComparatorIdChange}
      />

      <div className="grid gap-3 xl:grid-cols-2">
        <ScreenSummaryCard title={<GlossaryTerm id="magic-formula">Magic Formula - Greenblatt</GlossaryTerm>} screen={magic} verdict={magicBadge}>
          <div className="space-y-2">
            <StatTile label="ROC" value={fmtPct(recordNumber(magic, "roc"), 1, false)} sub={`Rank ${fmtNumber(recordNumber(magic, "roc_rank"), 0)}`} />
            <StatTile label="Earnings yield" value={fmtPct(recordNumber(magic, "earnings_yield"), 1, false)} sub={`Rank ${fmtNumber(recordNumber(magic, "ey_rank"), 0)}`} />
          </div>
        </ScreenSummaryCard>
        <ScreenSummaryCard title={<GlossaryTerm id="peg">PEG - GARP</GlossaryTerm>} screen={peg} verdict={pegBadge}>
          <div className="grid gap-3 md:grid-cols-3">
            <StatTile label="PEG" value={fmtNumber(recordNumber(peg, "peg"), 2)} sub={String(peg.zone ?? "-")} />
            <StatTile label={<GlossaryTerm id="per">P/E</GlossaryTerm>} value={fmtRatio(recordNumber(peg, "per"), 1)} />
            <StatTile label="Growth" value={fmtPct(recordNumber(peg, "growth_used"), 1, false)} />
          </div>
        </ScreenSummaryCard>
      </div>

      <ScreenSummaryCard title="Multiples ajustés par régression" screen={regression}>
        <div className="reg-grid">
          {Object.entries(richness).map(([metric, value]) => {
            const item = asRecord(value)
            const z = recordNumber(item, "richness_z")
            const glossaryId = COMPARABLE_METRIC_GLOSSARY_IDS[metric]
            return (
              <div key={metric} className="reg-row">
                <span>{glossaryId ? <GlossaryTerm id={glossaryId}>{metric}</GlossaryTerm> : metric}</span>
                <div className="reg-track">
                  <i style={{ width: `${Math.min(50, Math.abs(z ?? 0) * 16)}%`, marginLeft: (z ?? 0) < 0 ? `${50 - Math.min(50, Math.abs(z ?? 0) * 16)}%` : "50%", background: (z ?? 0) <= 0 ? "var(--pos)" : "var(--neg)" }} />
                </div>
                <span className="font-mono">{fmtNumber(z, 2)}z</span>
              </div>
            )
          })}
        </div>
      </ScreenSummaryCard>
    </div>
  )
}


const SECTION_NAV_ITEMS = [
  { id: "comparables-section", label: "Comparables" },
  { id: "qualite-section", label: "Qualité & écrans" },
  { id: "piotroski-section", label: "Piotroski" },
  { id: "altman-section", label: "Altman" },
] as const


function SectionNav() {
  function scrollTo(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }
  return (
    <div className="fund-section-nav">
      {SECTION_NAV_ITEMS.map((item) => (
        <button key={item.id} type="button" className="fund-section-nav-pill" onClick={() => scrollTo(item.id)}>
          {item.label}
        </button>
      ))}
    </div>
  )
}


// Merged "Comparables & Qualite" tab (brief 57 §4.4): two anchored sections, always both
// rendered, with a small in-tab nav that scrolls (not sub-tabs). Section ids are reused by
// the Synthese verdict-chip deep links (see synthese-tab.tsx's onNavigate anchors).
export function ComparablesQualityTab({
  detail,
  row,
  rows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
}) {
  return (
    <div className="fund-gap flex flex-col">
      <SectionNav />

      <div id="comparables-section">
        <div className="fund-section-label">Comparables</div>
        <ComparablesPeerBenchmarkSection
          detail={detail}
          row={row}
          rows={rows}
          selectedComparatorId={selectedComparatorId}
          onSelectedComparatorIdChange={onSelectedComparatorIdChange}
        />
      </div>

      <div id="qualite-section">
        <div className="fund-section-label">Qualité &amp; écrans</div>
        <QualiteScreensSection detail={detail} row={row} />
      </div>
    </div>
  )
}
