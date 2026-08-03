import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CrossAssetClass } from "@/lib/api"

export function RunRecord({ assetClass, inputs = {}, warnings = [] }: { assetClass: CrossAssetClass; inputs?: Record<string, unknown>; warnings?: string[] }) {
  return <Card><CardHeader><CardTitle>Run record — {assetClass.toUpperCase()}</CardTitle></CardHeader><CardContent className="space-y-4"><dl className="grid gap-3 md:grid-cols-2">{Object.entries(inputs).map(([key, value]) => <div key={key} className="rounded-lg border p-3"><dt className="text-xs text-muted-foreground">{key}</dt><dd className="mt-1 break-all font-mono text-xs">{value == null ? "null" : typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>{warnings.length ? <div className="space-y-2">{warnings.map((warning) => <div key={warning} className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200">{warning}</div>)}</div> : <p className="text-sm text-muted-foreground">Aucun warning déclaré.</p>}</CardContent></Card>
}
