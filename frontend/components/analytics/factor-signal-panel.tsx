"use client"

import { useFactorSignalEval } from "@/hooks/use-api"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { ICBadge } from "./ic-badge"
import { DSRBadge } from "./dsr-badge"

const SIGNAL_RULES: Record<string, string> = {
  vix_zscore: "z20<-1→+1 ; z20>+2→-1",
  dxy_momentum: "mom20<0→+1 ; else -1",
  brent_direction: "mom5>0→+1 ; else -1",
  sp500_vix_confirmation: "mom5>0 & VIXz<1→+1 ; else 0",
  us10y_shock: "Δ5d>20bp→-1 ; else 0",
  eurusd_momentum: "mom20>0→+1 ; else -1",
}

function FdrBadge({ pass }: { pass: boolean }) {
  return pass ? (
    <Badge variant="outline" className="text-[9px] text-emerald-700 border-emerald-300 bg-emerald-50">
      ✓
    </Badge>
  ) : (
    <span className="text-muted-foreground text-[10px]">—</span>
  )
}

interface FactorSignalPanelProps {
  symbol: string
  returnMethod?: string
  lookbackDays?: number
}

export function FactorSignalPanel({ symbol, returnMethod, lookbackDays }: FactorSignalPanelProps) {
  const { data, isLoading, error } = useFactorSignalEval(symbol, { returnMethod, lookbackDays })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-9 w-full" />)}
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-sm text-destructive py-4 text-center">
        Erreur — vérifiez que les séries macro ont été ingérées
        (<code className="text-xs">POST /analytics/macro/ingest-all</code>).
      </div>
    )
  }

  if (!data || data.length === 0 || data.every((r) => r.n_obs === 0)) {
    return (
      <div className="text-sm text-muted-foreground py-4 text-center">
        Aucun facteur ingéré — lancez d&apos;abord{" "}
        <code className="text-xs">POST /analytics/macro/ingest-all</code>.
      </div>
    )
  }

  const sorted = [...data].sort((a, b) => Math.abs(b.dsr) - Math.abs(a.dsr))

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Évaluation OOS — signaux pré-enregistrés (Phase 1) — BH-FDR q=0.10
      </p>
      <Table>
        <TableHeader>
          <TableRow className="text-xs">
            <TableHead className="w-24">Facteur</TableHead>
            <TableHead className="w-36">Règle</TableHead>
            <TableHead className="w-16 text-right">IC d1</TableHead>
            <TableHead className="w-16 text-right">IC d5</TableHead>
            <TableHead className="w-20 text-right">Sharpe (net)</TableHead>
            <TableHead className="w-16 text-right">DSR</TableHead>
            <TableHead className="w-12 text-right">FDR</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sorted.map((row) => (
            <TableRow
              key={row.signal_name}
              className={row.fdr_pass ? "bg-emerald-50/50 text-xs" : "text-xs"}
            >
              <TableCell className="font-mono font-semibold">
                {row.factor_id}
              </TableCell>
              <TableCell className="font-mono text-[10px] text-muted-foreground">
                {SIGNAL_RULES[row.signal_name] ?? row.signal_name}
              </TableCell>
              <TableCell className="text-right">
                <ICBadge value={row.ic_h1} />
              </TableCell>
              <TableCell className="text-right">
                <ICBadge value={row.ic_h5} />
              </TableCell>
              <TableCell className="text-right tabular-nums font-mono text-xs">
                {row.n_obs > 0 ? row.after_cost_sharpe.toFixed(2) : "—"}
              </TableCell>
              <TableCell className="text-right">
                {row.n_obs > 0 ? <DSRBadge dsr={row.dsr} psr={row.psr} /> : <span className="text-muted-foreground text-[10px]">—</span>}
              </TableCell>
              <TableCell className="text-right">
                {row.n_obs > 0 ? <FdrBadge pass={row.fdr_pass} /> : <span className="text-muted-foreground text-[10px]">—</span>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-[10px] text-muted-foreground">
        FDR ✓ = rejet au seuil BH q=0.10 après correction pour comparaisons multiples.
        DSR &gt; 0.95 = Sharpe significatif après correction pour tests multiples (Harvey-Liu-Zhu).
      </p>
    </div>
  )
}
