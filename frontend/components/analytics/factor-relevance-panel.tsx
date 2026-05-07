"use client"

import { useMemo } from "react"
import { useFactorSelectionActive, useFactorSelectionStage1 } from "@/hooks/use-api"
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

const HORIZON_LABELS: Record<string, string> = {
  short: "Court",
  mid: "Moyen",
  medium: "Moyen",
  long: "Long",
}

function fmtNumber(value: number | null | undefined, digits = 3) {
  if (value == null || Number.isNaN(value)) return "—"
  return value.toFixed(digits)
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "valid"
      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
      : "border-red-200 bg-red-50 text-red-700"
  return <Badge variant="outline" className={cls}>{status}</Badge>
}

interface FactorRelevancePanelProps {
  symbol: string
  horizon?: string
}

export function FactorRelevancePanel({
  symbol,
  horizon = "medium",
}: FactorRelevancePanelProps) {
  const { data: active, isLoading: loadingActive, error: activeError } = useFactorSelectionActive(symbol, horizon)
  const { data: stage1, isLoading: loadingStage1, error: stage1Error } = useFactorSelectionStage1(symbol, horizon)

  const survivors = useMemo(
    () =>
      (stage1 ?? [])
        .filter((row) => row.selected_reason === "normal" || row.selected_reason === "low_confidence" || row.passed_fdr)
        .slice(0, 12),
    [stage1],
  )

  if (loadingActive || loadingStage1) {
    return (
      <div className="space-y-2">
        {[...Array(6)].map((_, i) => <Skeleton key={i} className="h-10 w-full" />)}
      </div>
    )
  }

  if (activeError || stage1Error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        Impossible de charger le diagnostic factoriel pour {symbol}.
      </div>
    )
  }

  const firstStage1 = stage1?.[0]
  const firstActive = active?.[0]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">{symbol}</Badge>
        <Badge variant="outline">{HORIZON_LABELS[horizon] ?? horizon}</Badge>
        {firstActive?.history_n_days != null && (
          <Badge variant="outline">Historique {firstActive.history_n_days}j</Badge>
        )}
        {firstActive?.low_confidence && (
          <Badge variant="outline" className="border-amber-200 bg-amber-50 text-amber-800">
            Low confidence
          </Badge>
        )}
        {firstActive?.next_forced_recal && (
          <Badge variant="outline">Recal forcé {firstActive.next_forced_recal.slice(0, 10)}</Badge>
        )}
        {firstStage1?.regime_start && (
          <Badge variant="outline">Régime depuis {firstStage1.regime_start}</Badge>
        )}
      </div>

      <div className="space-y-2">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Facteurs actifs
        </div>
        {!active || active.length === 0 ? (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            Aucun facteur actif pour cet horizon.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="text-xs">
                <TableHead>Rang</TableHead>
                <TableHead>Facteur</TableHead>
                <TableHead className="text-right">Spearman</TableHead>
                <TableHead className="text-right">Pearson</TableHead>
                <TableHead className="text-right">t-stat</TableHead>
                <TableHead className="text-right">Score</TableHead>
                <TableHead className="text-right">Obs</TableHead>
                <TableHead className="text-right">Raison</TableHead>
                <TableHead className="text-right">CUSUM</TableHead>
                <TableHead className="text-right">Statut</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {active.map((row) => (
                <TableRow key={`${row.horizon}-${row.factor_canonical_id}`} className="text-xs">
                  <TableCell>{row.rank ?? "—"}</TableCell>
                  <TableCell className="font-mono font-semibold">{row.factor_canonical_id}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.spearman_ic ?? row.ic)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.pearson_corr)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.ic_t_stat, 2)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.relevance_score)}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.n_obs ?? "—"}</TableCell>
                  <TableCell className="text-right">{row.selected_reason ?? "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.cusum_drift_score, 2)}</TableCell>
                  <TableCell className="text-right"><StatusBadge status={row.cusum_status} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      <div className="space-y-2">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Survivants Stage 1
        </div>
        {!survivors || survivors.length === 0 ? (
          <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
            Aucun facteur sélectionné par le score IC composite.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="text-xs">
                <TableHead>Facteur</TableHead>
                <TableHead className="text-right">Spearman</TableHead>
                <TableHead className="text-right">Pearson</TableHead>
                <TableHead className="text-right">t-stat</TableHead>
                <TableHead className="text-right">Score</TableHead>
                <TableHead className="text-right">Obs</TableHead>
                <TableHead className="text-right">Raison</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {survivors.map((row) => (
                <TableRow key={`${row.horizon}-${row.factor_canonical_id}`} className="text-xs">
                  <TableCell className="font-mono">{row.factor_canonical_id}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.spearman_ic ?? row.ic_mean)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.pearson_corr)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.ic_tstat, 2)}</TableCell>
                  <TableCell className="text-right tabular-nums">{fmtNumber(row.relevance_score)}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.n_obs ?? "—"}</TableCell>
                  <TableCell className="text-right">{row.selected_reason ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  )
}
