import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

function formatNumber(n: number): string {
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (Math.abs(n) >= 1e3) return `${(n / 1e3).toFixed(1)}k`
  if (Number.isInteger(n)) return n.toLocaleString()
  return n.toFixed(2)
}

function formatTradePrice(n: number): string {
  return n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })
}

function formatPercent(n: number): string {
  return `${(n * 100).toFixed(2)}%`
}

export function TradesTable({ trades }: { trades: Record<string, unknown>[] }) {
  if (trades.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-xs text-muted-foreground">
          Aucun trade pour cette fenetre.
        </CardContent>
      </Card>
    )
  }
  return <TradeLedgerTable trades={trades} />
}

export function TradeLedgerTable({ trades }: { trades: Record<string, unknown>[] }) {
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <div className="border-b bg-secondary/20 px-3 py-2 text-[11px] text-muted-foreground">
          <span className="font-medium text-foreground">Audit:</span>{" "}
          <span>`PnL (100k) = 100000 × Return cumule`.</span>{" "}
          <span>`PnL realise cumule (1 unite)` suit separement le ledger des trades unitaires.</span>
        </div>
        <table className="w-full text-xs whitespace-nowrap">
          <thead>
            <tr className="border-b bg-secondary/30">
              {["Date", "Sens", "Open (t+1)", "CMP", "Position", "Return Cumule (%)", "PnL Realise Cumule (1 unite)"].map((heading) => (
                <th key={heading} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-muted-foreground">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {trades.map((row, index) => {
              const returnCumule = row.return_cumule != null ? Number(row.return_cumule) : NaN
              const pnlRealiseCumule = row.pnl_realise_cumule != null ? Number(row.pnl_realise_cumule) : NaN
              const side = String(row.side ?? "")
              return (
                <tr key={index} className="border-b border-border/40 hover:bg-secondary/20">
                  <td className="px-3 py-1.5 font-mono">{String(row.date ?? "").slice(0, 10)}</td>
                  <td className="px-3 py-1.5">
                    <span className={cn("font-semibold", side === "ACHAT" ? "text-emerald-600" : "text-red-600")}>
                      {side || "—"}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {row.open_t_plus_1 != null || row.prix_execution != null
                      ? formatTradePrice(Number(row.open_t_plus_1 ?? row.prix_execution))
                      : "—"}
                  </td>
                  <td className="px-3 py-1.5 tabular-nums">
                    {row.cmp != null || row.close_du_jour != null
                      ? formatTradePrice(Number(row.cmp ?? row.close_du_jour))
                      : "—"}
                  </td>
                  <td className={cn(
                    "px-3 py-1.5 tabular-nums font-semibold text-center",
                    Number(row.position ?? 0) > 0
                      ? "text-emerald-600"
                      : Number(row.position ?? 0) < 0
                        ? "text-red-600"
                        : "text-muted-foreground",
                  )}>
                    {row.position != null
                      ? Number(row.position) > 0
                        ? "+1"
                        : Number(row.position) < 0
                          ? "-1"
                          : "0"
                      : "—"}
                  </td>
                  <td className={cn(
                    "px-3 py-1.5 tabular-nums font-semibold",
                    returnCumule > 0 ? "text-emerald-600" : returnCumule < 0 ? "text-red-600" : "text-muted-foreground",
                  )}>
                    {Number.isFinite(returnCumule) ? formatPercent(returnCumule) : "—"}
                  </td>
                  <td className={cn(
                    "px-3 py-1.5 tabular-nums font-semibold",
                    pnlRealiseCumule > 0 ? "text-emerald-600" : pnlRealiseCumule < 0 ? "text-red-600" : "text-muted-foreground",
                  )}>
                    {Number.isFinite(pnlRealiseCumule) ? formatNumber(pnlRealiseCumule) : "—"}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}
