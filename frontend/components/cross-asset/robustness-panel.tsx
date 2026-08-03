import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { PlotlyHeatmap } from "@/components/run/plotly-heatmap"
import type { CrossAssetClass } from "@/lib/api"

export function RobustnessPanel({ assetClass, results = {} }: { assetClass: CrossAssetClass; results?: Record<string, unknown> }) {
  const dsr = typeof results.deflated_sharpe === "number" ? results.deflated_sharpe : null
  const variants = typeof results.variant_count === "number" ? results.variant_count : null
  return <div className="grid gap-4 lg:grid-cols-2"><Card><CardHeader><CardTitle>Robustesse — {assetClass.toUpperCase()}</CardTitle></CardHeader><CardContent className="space-y-3"><div className="grid grid-cols-2 gap-3"><Metric label="Deflated Sharpe" value={dsr} unit="probabilité"/><Metric label="Variants comparés" value={variants} unit="count"/></div><p className="text-sm text-muted-foreground">WFO, sous-périodes, coûts 0×–3×, leave-one-out et bootstrap CI sont conservés dans le record de validation. Un Sharpe élevé ne constitue pas une preuve.</p></CardContent></Card><Card><CardContent className="pt-4"><PlotlyHeatmap x={[1,3,6,12]} y={["10% vol"]} z={[[null,null,null,dsr]]} title="Sharpe déflaté par lookback" /></CardContent></Card></div>
}

function Metric({ label, value, unit }: { label: string; value: number | null; unit: string }) { return <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="text-xl font-semibold">{value === null ? "—" : value.toFixed(3)}</div><div className="text-xs text-muted-foreground">{unit}</div></div> }
