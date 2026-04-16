import type { DashboardBreadth, DashboardIndex } from "@/lib/dashboard-types"
import { FAMILY_LABELS, FAMILY_ORDER, formatScore } from "@/lib/dashboard-constants"
import { FamilyCell } from "./family-cell"
import { SignalBadge } from "./signal-badge"
import { ScoreBar } from "./score-bar"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

interface IndexSummaryProps {
  index: DashboardIndex
}

export function IndexSummary({ index }: IndexSummaryProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">MASI - Indice Global</CardTitle>
            <p className="text-sm text-muted-foreground">{index.stock_count} actions analysees</p>
          </div>
          <div className="flex items-center gap-3">
            <SignalBadge label={index.aggregate_signal_label} />
            <span className="text-lg font-mono font-bold">{formatScore(index.aggregate_score_pct)}</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {FAMILY_ORDER.map((family) => (
            <div key={family} className="space-y-2">
              <p className="text-sm font-medium">{FAMILY_LABELS[family]}</p>
              <ScoreBar score={index.per_family[family]?.score_pct ?? null} />
              <FamilyCell score={index.per_family[family]} />
            </div>
          ))}
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium">Largeur de marche</p>
          <BreadthBar breadth={index.breadth} total={index.stock_count} />
        </div>
      </CardContent>
    </Card>
  )
}

function BreadthBar({ breadth, total }: { breadth: DashboardBreadth; total: number }) {
  const pctAchat = total > 0 ? (breadth.achat / total) * 100 : 0
  const pctNeutre = total > 0 ? (breadth.neutre / total) * 100 : 0
  const pctVente = total > 0 ? (breadth.vente / total) * 100 : 0
  const pctIndisponible = total > 0 ? (breadth.indisponible / total) * 100 : 0

  return (
    <div className="space-y-1">
      <div className="flex h-3 w-full overflow-hidden rounded-full">
        {pctAchat > 0 && <div className="bg-emerald-500" style={{ width: `${pctAchat}%` }} />}
        {pctNeutre > 0 && <div className="bg-zinc-400" style={{ width: `${pctNeutre}%` }} />}
        {pctVente > 0 && <div className="bg-red-500" style={{ width: `${pctVente}%` }} />}
        {pctIndisponible > 0 && <div className="bg-slate-300" style={{ width: `${pctIndisponible}%` }} />}
      </div>

      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          {breadth.achat} Achat ({pctAchat.toFixed(0)}%)
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-zinc-400" />
          {breadth.neutre} Neutre ({pctNeutre.toFixed(0)}%)
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-full bg-red-500" />
          {breadth.vente} Vente ({pctVente.toFixed(0)}%)
        </span>
        {breadth.indisponible > 0 && (
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded-full bg-slate-300" />
            {breadth.indisponible} Indisponible ({pctIndisponible.toFixed(0)}%)
          </span>
        )}
      </div>
    </div>
  )
}
