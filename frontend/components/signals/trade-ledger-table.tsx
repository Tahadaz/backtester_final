"use client"

import { formatPercent } from "@/lib/format"

interface Trade {
  open_date?: string
  close_date?: string
  direction?: number
  open_price?: number
  close_price?: number
  pnl_return?: number
  bars_held?: number
  [key: string]: unknown
}

function fmt(v: number | null | undefined, isPct = false) {
  if (v == null) return "—"
  return isPct ? formatPercent(v) : v.toFixed(2)
}

export function TradeLedgerTable({ trades }: { trades: Trade[] | null | undefined }) {
  if (trades == null) {
    return (
      <p className="text-xs text-muted-foreground border rounded p-2 bg-muted/20">
        Données de trades non disponibles — re-lancez le backtest pour voir le détail.
      </p>
    )
  }
  if (trades.length === 0) {
    return (
      <p className="text-xs text-muted-foreground border rounded p-2 bg-muted/20">
        Aucun trade généré pour cette période.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto max-h-64 overflow-y-auto rounded border">
      <table className="w-full text-xs min-w-[520px]">
        <thead className="bg-muted/50 sticky top-0">
          <tr>
            <th className="text-left py-1.5 px-2 font-medium">Entrée</th>
            <th className="text-left py-1.5 px-2 font-medium">Sortie</th>
            <th className="text-center py-1.5 px-2 font-medium">Sens</th>
            <th className="text-right py-1.5 px-2 font-medium">Prix E.</th>
            <th className="text-right py-1.5 px-2 font-medium">Prix S.</th>
            <th className="text-right py-1.5 px-2 font-medium">Barres</th>
            <th className="text-right py-1.5 px-2 font-medium">PnL%</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {trades.map((t, i) => {
            const isLong = (t.direction ?? 1) >= 0
            const pnl = t.pnl_return ?? null
            return (
              <tr key={i} className="hover:bg-muted/20">
                <td className="py-1 px-2 font-mono">{t.open_date ?? "—"}</td>
                <td className="py-1 px-2 font-mono">{t.close_date ?? "—"}</td>
                <td className="py-1 px-2 text-center">
                  <span className={`font-semibold ${isLong ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                    {isLong ? "↑ Long" : "↓ Short"}
                  </span>
                </td>
                <td className="py-1 px-2 text-right font-mono">{fmt(t.open_price)}</td>
                <td className="py-1 px-2 text-right font-mono">{fmt(t.close_price)}</td>
                <td className="py-1 px-2 text-right font-mono">{t.bars_held ?? "—"}</td>
                <td className={`py-1 px-2 text-right font-mono font-semibold ${pnl != null && pnl >= 0 ? "text-green-600 dark:text-green-400" : "text-destructive"}`}>
                  {fmt(pnl, true)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
