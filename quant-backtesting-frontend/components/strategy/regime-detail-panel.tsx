"use client"

import type { RegimeConsensus } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { SignalScoreBar } from "./signal-score-bar"
import { ArrowLeft } from "lucide-react"

function regimeLabelFr(label: string): string {
  if (label === "trending") return "Tendance"
  if (label === "ranging") return "Range"
  if (label === "mixed") return "Mixte"
  if (label === "inactive") return "Inactif"
  return "Donnees insuffisantes"
}

function regimeBadgeClass(label: string): string {
  if (label === "trending") return "border-blue-300 text-blue-700 bg-blue-50"
  if (label === "ranging") return "border-orange-300 text-orange-700 bg-orange-50"
  if (label === "mixed") return "border-purple-300 text-purple-700 bg-purple-50"
  return "border-muted text-muted-foreground"
}

function weightBar(weight: number, color: string) {
  return (
    <div className="flex items-center gap-2 w-full">
      <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${color}`}
          style={{ width: `${Math.round(weight * 100)}%` }}
        />
      </div>
      <span className="text-[10px] font-mono w-10 text-right">
        {(weight * 100).toFixed(0)}%
      </span>
    </div>
  )
}

const FAMILY_COLORS: Record<string, string> = {
  sma: "bg-blue-500",
  macd: "bg-indigo-500",
  rsi: "bg-orange-500",
  obv: "bg-emerald-500",
}

export function RegimeDetailPanel({
  data,
  onBack,
}: {
  data: RegimeConsensus
  onBack: () => void
}) {
  const families = Object.keys(data.family_weights).sort()
  const hasWindows = data.window_results.length > 0

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour
        </Button>
        <h3 className="text-sm font-bold">Detection de Regime — Detail</h3>
        <Badge variant="outline" className={regimeBadgeClass(data.regime_label)}>
          {regimeLabelFr(data.regime_label)}
        </Badge>
      </div>

      {/* Consensus comparison */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-[11px] text-muted-foreground font-normal">
              Consensus regime
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <SignalScoreBar
              value={data.final_consensus}
              size="md"
              className="w-full"
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-[11px] text-muted-foreground font-normal">
              Consensus egal (reference)
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <SignalScoreBar
              value={data.equal_consensus}
              size="md"
              className="w-full"
            />
          </CardContent>
        </Card>
      </div>

      {/* Regime summary stats */}
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Kaufman Efficiency Ratio</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="flex items-center gap-6 text-center">
            <div>
              <div className="text-lg font-bold font-mono">
                {data.er_value != null ? data.er_value.toFixed(3) : "N/A"}
              </div>
              <div className="text-[10px] text-muted-foreground">ER actuel</div>
            </div>
            <div>
              <div className="text-sm font-mono">
                [{data.tercile_bounds[0]?.toFixed(3)}, {data.tercile_bounds[1]?.toFixed(3)}]
              </div>
              <div className="text-[10px] text-muted-foreground">Bornes terciles</div>
            </div>
            <div>
              <div className={`text-lg font-bold font-mono ${data.improvement > 0 ? "text-green-700" : "text-red-600"}`}>
                {data.improvement > 0 ? "+" : ""}{data.improvement.toFixed(4)}
              </div>
              <div className="text-[10px] text-muted-foreground">Amelioration OOS</div>
            </div>
            <div>
              <div className="text-lg font-bold font-mono">
                {data.folds_regime_wins}/{data.n_folds}
              </div>
              <div className="text-[10px] text-muted-foreground">Folds gagnes</div>
            </div>
          </div>
          {/* ER scale bar */}
          {data.er_value != null && (
            <div className="mt-4">
              <div className="relative h-3 rounded-full overflow-hidden"
                style={{ background: "linear-gradient(to right, #f97316, #a3a3a3, #3b82f6)" }}>
                {/* Tercile markers */}
                <div
                  className="absolute top-0 h-full w-px bg-black/40"
                  style={{ left: `${data.tercile_bounds[0] * 100}%` }}
                />
                <div
                  className="absolute top-0 h-full w-px bg-black/40"
                  style={{ left: `${data.tercile_bounds[1] * 100}%` }}
                />
                {/* Current ER dot */}
                <div
                  className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 border-black shadow"
                  style={{ left: `calc(${Math.min(data.er_value, 1) * 100}% - 6px)` }}
                />
              </div>
              <div className="flex justify-between text-[9px] text-muted-foreground mt-0.5">
                <span>0 (Range)</span>
                <span>1 (Tendance)</span>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Family weights comparison */}
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Poids par famille</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Regime weights */}
            <div>
              <div className="text-[10px] text-muted-foreground mb-2 font-medium">
                {data.regime_active ? "Poids regime (actifs)" : "Poids egaux (regime inactif)"}
              </div>
              <div className="space-y-1.5">
                {families.map((f) => (
                  <div key={f} className="flex items-center gap-2">
                    <span className="text-[11px] font-mono w-10 uppercase">{f}</span>
                    {weightBar(data.family_weights[f] ?? 0, FAMILY_COLORS[f] ?? "bg-gray-400")}
                  </div>
                ))}
              </div>
            </div>
            {/* Equal weights reference */}
            <div>
              <div className="text-[10px] text-muted-foreground mb-2 font-medium">
                Reference (1/N egal)
              </div>
              <div className="space-y-1.5">
                {families.map((f) => (
                  <div key={f} className="flex items-center gap-2">
                    <span className="text-[11px] font-mono w-10 uppercase">{f}</span>
                    {weightBar(1 / families.length, "bg-gray-400")}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Top variant per family (used for regime validation) */}
      {Object.keys(data.top_variants).length > 0 && (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold">
              Variantes utilisees pour la validation
              <span className="font-normal text-muted-foreground ml-1">(top fiabilite par famille)</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {Object.entries(data.top_variants).map(([family, tv]) => (
                <div key={family} className="border rounded-md p-2.5 text-center">
                  <div className="text-[10px] text-muted-foreground uppercase mb-1">{family}</div>
                  <div className="text-xs font-mono font-bold">{tv.label}</div>
                  <div className="text-[10px] text-muted-foreground capitalize">
                    {tv.archetype.replace(/_/g, " ")}
                  </div>
                  <div className="text-[10px] text-muted-foreground mt-0.5">
                    Fiabilite: {(tv.reliability_score * 100).toFixed(0)}%
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* OOS fold-by-fold comparison */}
      {hasWindows && (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold">
              Validation OOS — Fold par fold
              <Badge variant="outline" className="ml-2 text-[10px]">
                {data.n_folds} folds
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4 overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="text-left py-1.5 pr-2">#</th>
                  <th className="text-left py-1.5 pr-2">Periode test</th>
                  <th className="text-right py-1.5 pr-2">ER bas</th>
                  <th className="text-right py-1.5 pr-2">ER haut</th>
                  <th className="text-right py-1.5 pr-2">Sharpe regime</th>
                  <th className="text-right py-1.5 pr-2">Sharpe egal</th>
                  <th className="text-right py-1.5">Delta</th>
                </tr>
              </thead>
              <tbody>
                {data.window_results.map((w, i) => (
                  <tr key={i} className="border-b border-muted/50">
                    <td className="py-1.5 pr-2 font-mono">{i + 1}</td>
                    <td className="py-1.5 pr-2 text-muted-foreground">
                      {w.test_start_date ?? w.test_start} — {w.test_end_date ?? w.test_end}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono">{w.er_low.toFixed(3)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{w.er_high.toFixed(3)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{w.regime_sharpe.toFixed(3)}</td>
                    <td className="py-1.5 pr-2 text-right font-mono">{w.equal_sharpe.toFixed(3)}</td>
                    <td className={`py-1.5 text-right font-mono font-medium ${w.delta > 0 ? "text-green-700" : w.delta < 0 ? "text-red-600" : ""}`}>
                      {w.delta > 0 ? "+" : ""}{w.delta.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
              {data.n_folds > 0 && (
                <tfoot>
                  <tr className="font-medium border-t-2">
                    <td colSpan={4} className="py-1.5 pr-2">Moyenne</td>
                    <td className="py-1.5 pr-2 text-right font-mono">
                      {(data.window_results.reduce((s, w) => s + w.regime_sharpe, 0) / data.n_folds).toFixed(3)}
                    </td>
                    <td className="py-1.5 pr-2 text-right font-mono">
                      {(data.window_results.reduce((s, w) => s + w.equal_sharpe, 0) / data.n_folds).toFixed(3)}
                    </td>
                    <td className={`py-1.5 text-right font-mono font-bold ${data.improvement > 0 ? "text-green-700" : "text-red-600"}`}>
                      {data.improvement > 0 ? "+" : ""}{data.improvement.toFixed(3)}
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </CardContent>
        </Card>
      )}

      {/* Per-fold weight detail (expandable) */}
      {hasWindows && (
        <Card>
          <CardHeader className="pb-2 pt-3 px-4">
            <CardTitle className="text-xs font-semibold">
              Poids par regime — Dernier fold
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            {(() => {
              const lastFold = data.window_results[data.window_results.length - 1]
              if (!lastFold) return null
              return (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <div className="text-[10px] text-muted-foreground mb-2 flex items-center gap-1">
                      <span className="inline-block w-2 h-2 rounded-full bg-blue-500" />
                      Poids en tendance (ER &gt; {lastFold.er_high.toFixed(3)})
                    </div>
                    <div className="space-y-1.5">
                      {Object.entries(lastFold.trending_weights).sort().map(([f, w]) => (
                        <div key={f} className="flex items-center gap-2">
                          <span className="text-[11px] font-mono w-10 uppercase">{f}</span>
                          {weightBar(w, FAMILY_COLORS[f] ?? "bg-blue-400")}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="text-[10px] text-muted-foreground mb-2 flex items-center gap-1">
                      <span className="inline-block w-2 h-2 rounded-full bg-orange-500" />
                      Poids en range (ER &lt; {lastFold.er_low.toFixed(3)})
                    </div>
                    <div className="space-y-1.5">
                      {Object.entries(lastFold.ranging_weights).sort().map(([f, w]) => (
                        <div key={f} className="flex items-center gap-2">
                          <span className="text-[11px] font-mono w-10 uppercase">{f}</span>
                          {weightBar(w, FAMILY_COLORS[f] ?? "bg-orange-400")}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })()}
          </CardContent>
        </Card>
      )}

      {/* Explanation */}
      <div className="text-xs text-muted-foreground rounded-md border p-3 bg-muted/30 space-y-1">
        <p>
          <strong>Methode:</strong> Le Kaufman Efficiency Ratio (ER, fenetre=20) mesure le ratio
          direction/volatilite. ER proche de 1 = tendance forte, ER proche de 0 = range.
        </p>
        <p>
          <strong>Validation:</strong> Walk-forward OOS utilisant les memes fenetres que le pipeline A→G.
          Sur chaque fold, les poids regime sont calibres sur la fenetre d&apos;entrainement, puis testes
          hors-echantillon. Le regime n&apos;est active que s&apos;il bat la ponderation egale en moyenne sur tous les folds.
        </p>
        <p>
          <strong>Sources:</strong> Kaufman (1995), Pardo (2008), Ang &amp; Timmermann (2012), De Prado (2018).
        </p>
      </div>
    </div>
  )
}
