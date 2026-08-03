import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CrossAssetClass } from "@/lib/api"

const DEFAULT_ORDER = ["raw", "tradable_returns", "signal", "position", "executed_position", "gross_return", "costs", "net_return"]
const COMMODITY_ORDER = ["raw_contracts", "held_contract", "outright", "roll", "collateral", "fx", "signal", "executed_position", "costs", "net_return"]

export function MethodologyChain({ assetClass, stages = [] }: { assetClass: CrossAssetClass; stages?: Array<Record<string, unknown>> }) {
  const available = new Set(stages.map((item) => String(item.name)))
  const order = assetClass === "commodity" ? COMMODITY_ORDER : DEFAULT_ORDER
  return <Card><CardHeader><CardTitle>Chaîne méthodologique — {assetClass.toUpperCase()}</CardTitle></CardHeader><CardContent><div className="grid gap-2 md:grid-cols-4">
    {order.map((stage, index) => <div key={stage} className={`rounded-lg border p-3 ${available.has(stage) ? "border-emerald-500/50 bg-emerald-500/5" : "border-border"}`}><div className="text-xs text-muted-foreground">Étape {index + 1}</div><div className="font-mono text-sm">{stage}</div><div className="mt-1 text-xs">{available.has(stage) ? "Artifact disponible" : "Inspecter cette jambe"}</div></div>)}
  </div></CardContent></Card>
}
