"use client"

import { AlertTriangle } from "lucide-react"
import {
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"
import { SCORE_SCOPE_LABELS } from "../lib/constants"
import { asNumber, asRecord, fmtMoney, fmtNumber, fmtPct, fmtRatio } from "../lib/formatters"
import { StatTile } from "../shared/cards"
import { compactFlagLabel, ensembleForFlags, ensembleWarningsFor, overallCoveragePct, ratingFlagsFor } from "../lib/view-models"

export function CoverageRatingPanel({ detail, row }: { detail: FundamentalStockDetail; row: FundamentalUniverseRow | null }) {
  const ensemble = ensembleForFlags(detail, row)
  const coveragePct = overallCoveragePct(detail, row)
  const dispersionCv = asNumber(ensemble?.model_dispersion_cv)
  const dispersionFactor = asNumber(ensemble?.dispersion_factor)
  const fairMean = asNumber(ensemble?.fair_value_mean)
  const flags = ratingFlagsFor(detail, row)
  const warnings = ensembleWarningsFor(detail, row)
  const scoreScopes = asRecord(asRecord(detail.diagnostics).score_scopes)
  const scopes = SCORE_SCOPE_LABELS.map(([key, label]) => {
    const rawScope = scoreScopes[key]
    const scope = asRecord(rawScope)
    const scopeLabel = typeof rawScope === "string" ? rawScope : typeof scope.scope === "string" ? scope.scope : typeof scope.status === "string" ? scope.status : "-"
    const count = asNumber(scope.count) ?? asNumber(scope.n) ?? asNumber(scope.eligible_count)
    return { key, label, scope: scopeLabel, count }
  })

  return (
    <div className="coverage-rating-panel">
      <div className="driver-evidence-head">
        <div>
          <span className="valuation-mini-title">Couverture & rating</span>
          <p>Gates affiches sur la tear sheet: BUY si upside &gt; 12% et confiance &gt;= 45%; SELL si upside &lt; -10% et confiance &gt;= 45%; NR si cible withheld ou donnees insuffisantes.</p>
        </div>
        {flags.length ? <AlertTriangle className="h-4 w-4 text-amber-700" /> : null}
      </div>
      <div className="coverage-rating-grid">
        <StatTile label="Couverture score" value={fmtPct(coveragePct, 0, false)} tone={coveragePct != null && coveragePct < 0.5 ? "t-neg" : coveragePct != null && coveragePct >= 0.7 ? "t-pos" : undefined} />
        <StatTile label="Dispersion CV" value={fmtRatio(dispersionCv, 2)} tone={dispersionCv != null && dispersionCv > 1 ? "t-neg" : undefined} />
        <StatTile label="Haircut disp." value={fmtPct(dispersionFactor, 0, false)} sub="facteur confiance" />
        <StatTile label="Mean vs median" value={fairMean == null || ensemble?.fair_value_base == null ? "-" : fmtMoney(fairMean - ensemble.fair_value_base, 1)} sub={`mean ${fmtMoney(fairMean, 1)}`} />
      </div>
      <div className="score-scope-strip">
        {scopes.map((item) => (
          <span key={item.key} className={cn("score-scope-chip", item.scope === "insufficient" && "low")}>
            {item.label}: {item.scope}{item.count != null ? ` (${fmtNumber(item.count, 0)})` : ""}
          </span>
        ))}
      </div>
      {flags.length || warnings.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {[...flags, ...warnings.map(compactFlagLabel)].slice(0, 10).map((flag) => (
            <span key={flag} className="fund-warning-chip">{flag}</span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

