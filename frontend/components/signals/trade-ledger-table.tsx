"use client"

import { formatNumber, formatPercent } from "@/lib/format"
import { ledgerRowsWithDisplayPositions } from "@/lib/trade-ledger-position"

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

interface AccountingTrade {
  date?: string
  side?: string
  marker_label?: string
  trade_sequence?: number
  event_type?: string
  prix_execution?: number
  open_t_plus_1?: number
  close_du_jour?: number
  cmp?: number
  position?: number
  pnl_realise?: number
  pnl_realise_cumule?: number
  pnl_latent?: number
  cout?: number
  [key: string]: unknown
}

function fmt(v: number | null | undefined, isPct = false) {
  if (v == null) return "--"
  return isPct ? formatPercent(v) : v.toFixed(2)
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function fmtNumber(value: unknown, decimals = 2): string {
  const numberValue = asNumber(value)
  return numberValue == null ? "--" : formatNumber(numberValue, decimals)
}

function pnlClass(value: unknown): string {
  const numberValue = asNumber(value)
  if (numberValue == null || numberValue === 0) return "text-muted-foreground"
  return numberValue > 0 ? "text-green-600 dark:text-green-400" : "text-destructive"
}

export function TradeLedgerTable({ trades }: { trades: Trade[] | null | undefined }) {
  if (trades == null) {
    return (
      <p className="text-xs text-muted-foreground border rounded p-2 bg-muted/20">
        Donnees de trades non disponibles - relancez le backtest pour voir le detail.
      </p>
    )
  }
  if (trades.length === 0) {
    return (
      <p className="text-xs text-muted-foreground border rounded p-2 bg-muted/20">
        Aucun trade genere pour cette periode.
      </p>
    )
  }

  return (
    <div className="overflow-x-auto max-h-64 overflow-y-auto rounded border">
      <table className="w-full text-xs min-w-[520px]">
        <thead className="bg-muted/50 sticky top-0">
          <tr>
            <th className="text-left py-1.5 px-2 font-medium">Entree</th>
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
                <td className="py-1 px-2 font-mono">{t.open_date ?? "--"}</td>
                <td className="py-1 px-2 font-mono">{t.close_date ?? "--"}</td>
                <td className="py-1 px-2 text-center">
                  <span className={`font-semibold ${isLong ? "text-green-600 dark:text-green-400" : "text-red-500"}`}>
                    {isLong ? "Long" : "Short"}
                  </span>
                </td>
                <td className="py-1 px-2 text-right font-mono">{fmt(t.open_price)}</td>
                <td className="py-1 px-2 text-right font-mono">{fmt(t.close_price)}</td>
                <td className="py-1 px-2 text-right font-mono">{t.bars_held ?? "--"}</td>
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

export function AccountingTradeLedgerTable({ trades }: { trades: AccountingTrade[] | null | undefined }) {
  if (trades == null) {
    return (
      <p className="text-xs text-muted-foreground border rounded p-2 bg-muted/20">
        Donnees de ledger non disponibles - le backtest OOS detaille est requis.
      </p>
    )
  }
  if (trades.length === 0) {
    return (
      <p className="text-xs text-muted-foreground border rounded p-2 bg-muted/20">
        Aucun mouvement genere pour cette periode.
      </p>
    )
  }

  return (
    <div className="max-h-[360px] overflow-auto rounded border">
      <table className="w-full min-w-[900px] text-xs">
        <thead className="sticky top-0 bg-muted/50">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">Date</th>
            <th className="px-2 py-1.5 text-left font-medium">Sens</th>
            <th className="px-2 py-1.5 text-right font-medium">Prix execution</th>
            <th className="px-2 py-1.5 text-right font-medium">CMP</th>
            <th className="px-2 py-1.5 text-right font-medium">Position</th>
            <th className="px-2 py-1.5 text-right font-medium">PnL realise</th>
            <th className="px-2 py-1.5 text-right font-medium">PnL realise cumule</th>
            <th className="px-2 py-1.5 text-right font-medium">PnL latent</th>
            <th className="px-2 py-1.5 text-right font-medium">Close du jour</th>
            <th className="px-2 py-1.5 text-right font-medium">Cout</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {ledgerRowsWithDisplayPositions(trades).map(({ row: trade, displayPosition }, index) => {
            const side = String(trade.side ?? "")
            const label = String(trade.marker_label ?? side)
            const labelLower = label.toLowerCase()
            const isBuy = labelLower.includes("achat") || labelLower.includes("buy") || labelLower.includes("cover")
            const executionPrice = trade.prix_execution ?? trade.open_t_plus_1
            return (
              <tr key={`${trade.date ?? "trade"}-${index}`} className="hover:bg-muted/20">
                <td className="px-2 py-1 font-mono">{String(trade.date ?? "").slice(0, 10) || "--"}</td>
                <td className="px-2 py-1">
                  <span className={isBuy ? "font-semibold text-green-600 dark:text-green-400" : "font-semibold text-red-500"}>
                    {label || "--"}
                  </span>
                </td>
                <td className="px-2 py-1 text-right font-mono">{fmtNumber(executionPrice)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmtNumber(trade.cmp)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmtNumber(displayPosition, 0)}</td>
                <td className={`px-2 py-1 text-right font-mono font-semibold ${pnlClass(trade.pnl_realise)}`}>
                  {fmtNumber(trade.pnl_realise)}
                </td>
                <td className={`px-2 py-1 text-right font-mono font-semibold ${pnlClass(trade.pnl_realise_cumule)}`}>
                  {fmtNumber(trade.pnl_realise_cumule)}
                </td>
                <td className={`px-2 py-1 text-right font-mono font-semibold ${pnlClass(trade.pnl_latent)}`}>
                  {fmtNumber(trade.pnl_latent)}
                </td>
                <td className="px-2 py-1 text-right font-mono">{fmtNumber(trade.close_du_jour)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmtNumber(trade.cout)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
