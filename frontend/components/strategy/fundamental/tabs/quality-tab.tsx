"use client"

import type { ReactNode } from "react"
import {
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { asNumber, asRatio, asRecord, fmtMoney, fmtNumber, fmtPct, fmtRatio, recordNumber, scoreClass } from "../lib/formatters"
import { ComparableBenchmarkPanel } from "../panels/comparables"
import { FundCard, ScoreChip, StatTile } from "../shared/cards"
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


function peerScopeLabel(scope: string, cohortSize: number | null, sector: string | null | undefined): string {
  const n = cohortSize != null ? ` (n=${fmtNumber(cohortSize, 0)})` : ""
  if (scope === "sector") return `Secteur${sector ? ` ${sector}` : ""}${n}`
  if (scope === "market") return `Marche${n}`
  return "Echantillon insuffisant"
}


function peerDeviationLabel(zScore: number | null, pctDeviation: number | null): string | null {
  if (zScore != null) return `${zScore > 0 ? "+" : ""}${fmtNumber(zScore, 1)} sigma`
  if (pctDeviation != null) return `${fmtPct(pctDeviation, 0)} vs mediane`
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
        return (
          <div key={metric} className="peer-row">
            <div className="peer-label">
              <span>{label}</span>
              <span className={cn("peer-scope-badge", scope === "sector" && "peer-scope-badge-sector", insufficient && "peer-scope-badge-muted")}>
                {peerScopeLabel(scope, cohortSize, detail.sector)}
              </span>
            </div>
            <div className="peer-bar-wrap">
              {insufficient ? (
                <div className="peer-bar-empty">{own == null ? "donnee indisponible" : "cohorte trop petite (n<3)"}</div>
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
              <small>Mediane</small>
              <strong className="font-mono text-muted-foreground">{peerText}</strong>
            </span>
          </div>
        )
      })}
    </div>
  )
}


const ALTMAN_TERM_DEFS = [
  ["wc_ta", "X1", "Fonds de roulement / Actif total", "liquidite court terme", 6.56],
  ["re_ta", "X2", "Reserves (report a nouveau) / Actif total", "rentabilite cumulee / age", 3.26],
  ["ebit_ta", "X3", "Resultat d'exploitation (EBIT) / Actif total", "productivite operationnelle", 6.72],
  ["equity_tl", "X4", "Capitaux propres comptables / Total des dettes", "solvabilite", 1.05],
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
    }
  })
}


function waccSourceLabel(source: unknown): string {
  if (source === "firm_build_up") return "WACC build-up firme"
  if (source === "assumption") return "WACC hypotheses"
  if (source === "default") return "WACC defaut univers"
  return "WACC source non precisee"
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


export function QualityTab({ detail, row }: { detail: FundamentalStockDetail; row: FundamentalUniverseRow | null }) {
  const diagnostics = detail.diagnostics
  const dupont = asRecord(diagnostics.dupont)
  const metricBreakdown = asRecord(diagnostics.metric_breakdown)
  const qualityComponents = asRecord(detail.scores.quality_components)
  const screens = screensFor(detail, row)
  const altman = screenRecord(screens, "altman_z")
  const evaScreen = screenRecord(screens, "eva")
  const altmanWarnings = screenWarnings(altman)
  const evaWarnings = screenWarnings(evaScreen)
  const altmanZ = recordNumber(altman, "z_value")
  const altmanApplicable = altman.applicable !== false
  const evaApplicable = evaScreen.applicable !== false
  const evaRoic = recordNumber(evaScreen, "roic")
  const evaWacc = recordNumber(evaScreen, "wacc_used")
  const evaSpread = recordNumber(evaScreen, "roic_spread")
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
    ["Couverture interets", "Interest_Coverage", "x", "pos"],
    ["Dette / equity", "Debt_to_Equity", "x", "neg"],
  ] as const satisfies readonly PeerMetricRow[]

  return (
    <div className="fund-gap" data-capture="scoring">
      <div className="grid gap-3 md:grid-cols-2">
        <StatTile label="Score Value" value={fmtNumber(valueScore, 0)} tone={scoreClass(valueScore)} sub="Cheapness percentile vs peers" />
        <StatTile label="Score Quality" value={fmtNumber(qualityScore, 0)} tone={scoreClass(qualityScore)} sub="Profitability + accounting discipline" />
      </div>

      <FundCard title="Score Value - multiples vs peers" aside={<ScoreChip value={valueScore} />}>
        <div className="quality-card-note">
          Rang centile du titre face a sa cohorte de pairs. Pour les multiples, plus bas = meilleur; pour les yields, plus haut = meilleur. Cohorte = secteur si au moins 3 pairs, sinon marche.
        </div>
        <PeerMetricRows rows={valuePeerRows} metricBreakdown={metricBreakdown} detail={detail} />
      </FundCard>

      <FundCard title="Score Quality - rentabilite, cash et bilan" aside={<ScoreChip value={qualityScore} />}>
        <div className="quality-card-note">
          Score headline = profitabilite relative, discipline comptable et qualite des cash-flows. Levier, liquidite et couverture restent des diagnostics de red flag, pas des piliers separes.
        </div>
        <PeerMetricRows rows={qualityPeerRows} metricBreakdown={metricBreakdown} detail={detail} />
        <div className="mt-3 grid gap-3 md:grid-cols-5">
          <StatTile label="Profitabilite" value={fmtNumber(recordNumber(qualityComponents, "raw_percentile"), 0)} tone={scoreClass(recordNumber(qualityComponents, "raw_percentile"))} sub="ROE, ROA, marges" />
          <StatTile label="Discipline" value={fmtNumber(recordNumber(qualityComponents, "accounting_discipline"), 0)} tone={scoreClass(recordNumber(qualityComponents, "accounting_discipline"))} sub="DuPont + Piotroski" />
          <StatTile label="DuPont" value={fmtNumber(recordNumber(qualityComponents, "dupont_bridge") ?? recordNumber(dupont, "score"), 0)} tone={scoreClass(recordNumber(qualityComponents, "dupont_bridge") ?? recordNumber(dupont, "score"))} sub="coherence ROE" />
          <StatTile label="Piotroski" value={fmtNumber(recordNumber(qualityComponents, "piotroski_lite"), 0)} tone={scoreClass(recordNumber(qualityComponents, "piotroski_lite"))} sub="checks fondamentaux" />
          <StatTile label="Accruals" value={fmtNumber(recordNumber(qualityComponents, "accrual_quality") ?? recordNumber(accrualQuality, "score"), 0)} tone={scoreClass(recordNumber(qualityComponents, "accrual_quality") ?? recordNumber(accrualQuality, "score"))} sub={`cash ${fmtRatio(recordNumber(accrualQuality, "cash_conversion"), 2)}`} />
        </div>
      </FundCard>

      <div data-capture="diagnostics">
        <FundCard title={`Decomposition DuPont - ROE ${detail.latest_statement_year ?? ""}`} aside="ROE = marge x rotation x levier">
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
            <strong className="text-foreground">Lecture :</strong> l'ecart entre ROE reporte et ROE implique mesure la coherence comptable du pont DuPont. Score DuPont: <span className="font-mono text-foreground">{fmtNumber(recordNumber(dupont, "score"), 0)}</span>.
          </div>
        </FundCard>
      </div>

      <FundCard title="Risque de defaut - Altman Z-score" aside={altmanApplicable ? String(altman.zone ?? "N/A") : "Non applicable"}>
        {!altmanApplicable ? (
          <ScreenUnavailable message="Altman Z n'est pas applique aux secteurs financiers." warnings={altmanWarnings} />
        ) : altmanZ == null ? (
          <ScreenUnavailable message="Altman Z indisponible: donnees bilan, EBIT, chiffre d'affaires ou capitalisation manquantes." warnings={altmanWarnings} />
        ) : (
          <>
            <ZoneGauge zValue={altmanZ} zone={typeof altman.zone === "string" ? altman.zone : null} />
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <StatTile label="Z-score" value={fmtNumber(altmanZ, 2)} sub={String(altman.variant ?? "Altman Z")} />
              <StatTile label="Score" value={fmtNumber(recordNumber(altman, "score"), 0)} sub="0-100 derive de Z, clippe" />
              <StatTile label="Zone" value={String(altman.zone ?? "N/A")} />
            </div>
            <div className="quality-card-note mt-3">
              Score = 25 + (Z - 1,1) / (2,6 - 1,1) x 50, clippe entre 0 et 100. Seuils: Safe &gt; 2,6; zone grise 1,1-2,6; detresse &lt; 1,1. Variante: {String(altman.variant ?? "Z''_EM")}.
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
                        <span className="font-semibold text-foreground">{term.term}</span> {term.label}
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
                    <td className="font-mono text-muted-foreground">Z publie: {fmtNumber(altmanZ, 3)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="quality-methodology">{String(altman.methodology ?? "Altman Z'' emerging-market: 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4.")}</div>
            <ScreenWarningChips warnings={altmanWarnings} />
          </>
        )}
      </FundCard>

      <FundCard title="Creation de valeur - ROIC vs WACC" aside={!evaApplicable ? "Non applicable" : fmtPct(evaSpread, 2)}>
        {!evaApplicable ? (
          <ScreenUnavailable message="EVA n'est pas applique aux secteurs financiers." warnings={evaWarnings} />
        ) : evaRoic == null || evaWacc == null ? (
          <ScreenUnavailable message="EVA indisponible: EBIT, WACC ou capital investi manquant." warnings={evaWarnings} />
        ) : (
          <div className="space-y-3">
            <div className="quality-card-note">
              La societe {(evaSpread ?? 0) >= 0 ? "cree" : "detruit"} de la valeur quand son rendement sur capital investi (ROIC) {(evaSpread ?? 0) >= 0 ? "depasse" : "reste sous"} son cout du capital (WACC).
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


function ScreenSummaryCard({ title, screen, children }: { title: string; screen: Record<string, unknown>; children?: ReactNode }) {
  const score = recordNumber(screen, "score")
  const warnings = Array.isArray(screen.warnings) ? screen.warnings : []
  return (
    <FundCard title={title} aside={<ScoreChip value={score} />}>
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


export function ComparablesTab({
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
        <ScreenSummaryCard title="Magic Formula - Greenblatt" screen={magic}>
          <div className="space-y-2">
            <StatTile label="ROC" value={fmtPct(recordNumber(magic, "roc"), 1, false)} sub={`Rank ${fmtNumber(recordNumber(magic, "roc_rank"), 0)}`} />
            <StatTile label="Earnings yield" value={fmtPct(recordNumber(magic, "earnings_yield"), 1, false)} sub={`Rank ${fmtNumber(recordNumber(magic, "ey_rank"), 0)}`} />
          </div>
        </ScreenSummaryCard>
        <ScreenSummaryCard title="PEG - GARP" screen={peg}>
          <div className="grid gap-3 md:grid-cols-3">
            <StatTile label="PEG" value={fmtNumber(recordNumber(peg, "peg"), 2)} sub={String(peg.zone ?? "-")} />
            <StatTile label="P/E" value={fmtRatio(recordNumber(peg, "per"), 1)} />
            <StatTile label="Growth" value={fmtPct(recordNumber(peg, "growth_used"), 1, false)} />
          </div>
        </ScreenSummaryCard>
      </div>

      <ScreenSummaryCard title="Multiples ajustes par regression" screen={regression}>
        <div className="reg-grid">
          {Object.entries(richness).map(([metric, value]) => {
            const item = asRecord(value)
            const z = recordNumber(item, "richness_z")
            return (
              <div key={metric} className="reg-row">
                <span>{metric}</span>
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

