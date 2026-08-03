import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { CrossAssetClass } from "@/lib/api"

const METRICS: Array<[string, string, string]> = [
  ["gross_total_return", "Return brut", "%"], ["net_total_return", "Return net", "%"], ["ann_vol", "Vol annualisée", "%"],
  ["sharpe", "Sharpe", "ratio"], ["max_drawdown", "Max drawdown", "%"], ["turnover", "Turnover", "x"],
  ["gross_leverage", "Exposition brute", "x"], ["net_exposure", "Exposition nette", "x"], ["total_costs", "Coûts", "%"],
]

export function BacktestResults({ assetClass, metrics = {} }: { assetClass: CrossAssetClass; metrics?: Record<string, unknown> }) {
  return <Card><CardHeader><CardTitle>Backtest — {assetClass.toUpperCase()}</CardTitle></CardHeader><CardContent><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
    {METRICS.map(([key, label, unit]) => { const raw = metrics[key]; const value = typeof raw === "number" ? (unit === "%" ? raw * 100 : raw) : null; return <div key={key} className="rounded-lg border p-3"><div className="text-xs text-muted-foreground">{label}</div><div className="text-xl font-semibold tabular-nums">{value === null ? "—" : value.toFixed(2)} <span className="text-xs font-normal text-muted-foreground">{unit}</span></div></div> })}
  </div><p className="mt-4 text-xs text-muted-foreground">Gross et net sont toujours affichés côte à côte; le net déduit spread, slippage et commission du turnover exécuté.</p></CardContent></Card>
}
