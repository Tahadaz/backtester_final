"use client"

import { useWfoBatchStatus, useSignalEngineBatchStatus, usePredictiveHistoryBatchStatus } from "@/hooks/use-api"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Loader2 } from "lucide-react"

interface BatchRowProps {
  label: string
  total: number
  succeeded: number
  running: number
  failed: number
  pending: number
  insufficientData?: number
}

function BatchRow({ label, total, succeeded, running, failed, pending, insufficientData = 0 }: BatchRowProps) {
  // For progress: treat insufficient_data as terminal (ineligible), not as failure
  const terminal = succeeded + insufficientData
  const pct = total > 0 ? Math.round((terminal / total) * 100) : 0
  const isActive = pending > 0 || running > 0

  return (
    <div className="flex items-center gap-3">
      <span className="w-32 text-xs font-medium shrink-0 flex items-center gap-1.5">
        {isActive && <Loader2 className="h-3 w-3 animate-spin text-blue-500" />}
        {label}
      </span>
      <div className="flex-1 min-w-0">
        <Progress value={pct} className="h-1.5" />
      </div>
      <span className="text-xs tabular-nums text-muted-foreground w-28 text-right shrink-0">
        {succeeded}/{total}
        {insufficientData > 0 && (
          <span className="text-muted-foreground/60"> +{insufficientData} insuffisant</span>
        )}
      </span>
      <div className="flex items-center gap-1 shrink-0">
        {running > 0 && (
          <Badge variant="outline" className="text-[10px] h-4 px-1 text-blue-600 border-blue-300">
            {running} run
          </Badge>
        )}
        {pending > 0 && (
          <Badge variant="outline" className="text-[10px] h-4 px-1 text-yellow-700 border-yellow-300">
            {pending} en attente
          </Badge>
        )}
        {failed > 0 && (
          <Badge variant="destructive" className="text-[10px] h-4 px-1">
            {failed} échoués
          </Badge>
        )}
        {!isActive && total > 0 && failed === 0 && (
          <Badge variant="outline" className="text-[10px] h-4 px-1 text-emerald-700 border-emerald-300">
            terminé
          </Badge>
        )}
      </div>
    </div>
  )
}

export function RecomputeStatusCard() {
  const { data: wfo } = useWfoBatchStatus()
  const { data: engine } = useSignalEngineBatchStatus()
  const { data: history } = usePredictiveHistoryBatchStatus()

  const wfoActive = wfo && ((wfo.pending ?? 0) + (wfo.running ?? 0) > 0)
  const engineActive = engine && ((engine.pending ?? 0) + (engine.running ?? 0) > 0)
  const historyActive = history && ((history.pending ?? 0) + (history.running ?? 0) > 0)
  const wfoHasData = wfo && wfo.total > 0
  const engineHasData = engine && engine.total > 0
  const historyHasData = history && history.total > 0

  if (!wfoHasData && !engineHasData && !historyHasData) return null

  return (
    <Card className="border-blue-100 bg-blue-50/40 dark:bg-blue-950/20 dark:border-blue-900">
      <CardContent className="px-4 py-3 space-y-2">
        <p className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
          Progression des calculs
        </p>
        {wfoHasData && (
          <BatchRow
            label="WFO"
            total={wfo.total}
            succeeded={wfo.succeeded}
            running={wfo.running}
            failed={wfo.failed}
            pending={wfo.pending}
            insufficientData={wfo.insufficient_data ?? 0}
          />
        )}
        {engineHasData && (
          <BatchRow
            label="Signal Engine"
            total={engine.total}
            succeeded={engine.succeeded}
            running={engine.running}
            failed={engine.failed}
            pending={engine.pending ?? 0}
          />
        )}
        {historyHasData && (
          <BatchRow
            label="Historique scores"
            total={history.total}
            succeeded={history.succeeded}
            running={history.running}
            failed={history.failed}
            pending={history.pending ?? 0}
          />
        )}
        {(wfoActive || engineActive || historyActive) && (
          <p className="text-[10px] text-muted-foreground">
            Mise à jour toutes les 5 s automatiquement.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
