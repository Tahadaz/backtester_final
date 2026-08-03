import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CrossAssetClass } from "@/lib/api"

export function CurrentSignal({ assetClass, signal = {} }: { assetClass: CrossAssetClass; signal?: Record<string, unknown> }) {
  return <Card><CardHeader><CardTitle>Signal courant — {assetClass.toUpperCase()}</CardTitle></CardHeader><CardContent className="space-y-4"><div className="grid gap-3 md:grid-cols-3"><Field label="Signal" value={signal.latest_signal}/><Field label="Position visée" value={signal.intended_position}/><Field label="Position précédente" value={signal.previous_position}/><Field label="Data timestamp" value={signal.data_timestamp}/><Field label="Staleness" value={signal.staleness} unit="jours"/><Field label="Prochain rebalance" value={signal.next_rebalance}/></div><Field label="Drivers" value={signal.drivers}/><Field label="Conditions de reversal" value={signal.reversal_conditions}/><Alert><AlertTitle>Monitoring, pas une promesse</AlertTitle><AlertDescription>{String(signal.disclaimer ?? "Research output only; it does not guarantee profit and is not investment advice.")}</AlertDescription></Alert></CardContent></Card>
}

function Field({ label, value, unit }: { label: string; value: unknown; unit?: string }) { return <div className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="mt-1 break-words text-sm">{value == null ? "Indisponible" : typeof value === "object" ? JSON.stringify(value) : String(value)} {value != null && unit ? unit : ""}</div></div> }
