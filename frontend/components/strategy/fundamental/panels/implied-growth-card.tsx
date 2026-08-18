"use client"

import { type FundamentalStockDetail, type FundamentalValuationResult } from "@/lib/api"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import { buildGrowthComparisonTable, buildImpliedGrowthSentences } from "@/lib/fundamental-implied-growth-utils.js"
import { cn } from "@/lib/utils"
import { valuationWarningLabel } from "../lib/constants"
import { asRecord, fmtPct } from "../lib/formatters"
import { FundamentalHorizon } from "../lib/types"
import { projectionFromDetail } from "../lib/view-models"
import { FundCard, StatTile } from "../shared/cards"

export function ImpliedGrowthCard({
  detail,
  row,
  selectedHorizon,
}: {
  detail: FundamentalStockDetail
  row: FundamentalValuationResult | null
  selectedHorizon: FundamentalHorizon
}) {
  if (!row || row.model !== "justified_multiples") return null
  const outputs = asRecord(row.outputs)
  if (!outputs.market_implied_growth_path) return null

  // House column must be sourced from the ANNUAL projection and interpolated once
  // in buildGrowthComparisonTable, mirroring the market column's semantics. Passing
  // selectedHorizon here would hand quarterly/semiannual statements to a table
  // builder that already sub-annualizes annual rates — q/q growth is seasonal
  // (not a smooth fade) and would get interpolated a second time on top of that.
  const projection = projectionFromDetail(detail, "year")
  const table = buildGrowthComparisonTable(row, detail, projection, selectedHorizon)
  const sentences = buildImpliedGrowthSentences(row, table)
  const { meta } = table

  const deltaFirstYear = meta.gStart != null && meta.houseFirstYear != null ? meta.gStart - meta.houseFirstYear : null
  // Market < house => market undemanding relative to the house model (t-pos); market > house => t-neg.
  const deltaTone = deltaFirstYear == null ? undefined : deltaFirstYear <= 0 ? "t-pos" : "t-neg"
  const hasInterpolatedRows = table.periods.some((period) => period.interpolated)

  return (
    <FundCard
      title="Croissance attendue vs exigée par le marché"
      aside={<GlossaryTerm id="implied-growth-path">Modèle H — croissance implicite</GlossaryTerm>}
    >
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="g exigée an 1" value={fmtPct(meta.gStart, 1, false)} sub={<GlossaryTerm id="implied-growth-path" iconOnly>modèle H</GlossaryTerm>} />
        <StatTile label="g maison an 1" value={fmtPct(meta.houseFirstYear, 1, false)} sub="résultat net projeté" />
        <StatTile label="Écart an 1" value={fmtPct(deltaFirstYear, 1, true)} tone={deltaTone} />
        <StatTile label="g terminale" value={fmtPct(meta.gTerminal, 1, false)} sub={<GlossaryTerm id="terminal-growth" iconOnly>g (perpétuité)</GlossaryTerm>} />
        <StatTile label="Ke" value={fmtPct(meta.ke, 1, false)} sub={<GlossaryTerm id="cost-of-equity" iconOnly>Ke (CAPM)</GlossaryTerm>} />
        <StatTile label="Payout" value={fmtPct(meta.payout, 1, false)} sub={<GlossaryTerm id="payout-ratio" iconOnly>taux de distribution</GlossaryTerm>} />
      </div>

      {table.periods.length ? (
        <div className="mt-3 overflow-x-auto">
          <table className="claude-table">
            <thead>
              <tr>
                <th>Période</th>
                <th className="r">Implicite dans le cours</th>
                <th className="r">Modèle maison</th>
                <th className="r">Écart</th>
              </tr>
            </thead>
            <tbody>
              {table.periods.map((period) => (
                <tr key={period.label}>
                  <td>{period.interpolated ? `≈ ${period.label}` : period.label}</td>
                  <td className="r font-mono">{fmtPct(period.market, 1, false)}</td>
                  <td className="r font-mono">{fmtPct(period.house, 1, false)}</td>
                  <td className={cn("r font-mono", period.delta != null && (period.delta <= 0 ? "t-pos" : "t-neg"))}>
                    {fmtPct(period.delta, 1, true)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {hasInterpolatedRows ? (
            <p className="mt-1 text-[10px] text-muted-foreground">
              Valeurs trimestrielles/semestrielles interpolées à partir de taux annuels.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="fund-empty-small mt-3">Pas de comparaison période par période disponible.</div>
      )}

      <div className="mt-3 space-y-1.5 text-[12px] leading-relaxed text-muted-foreground">
        {sentences.map((sentence, index) => (
          <p key={index}>{sentence}</p>
        ))}
      </div>

      {meta.exceedsKe ? (
        <div className="valuation-warning-row mt-3">
          <span className="valuation-warning-label">Avertissements</span>
          <div className="flex flex-wrap gap-1.5">
            <span className="fund-warning-chip">{valuationWarningLabel("implied_start_growth_exceeds_cost_of_equity")}</span>
          </div>
        </div>
      ) : null}
    </FundCard>
  )
}
