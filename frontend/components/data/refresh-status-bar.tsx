"use client"

import { useRefreshRun } from "@/hooks/use-api"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import { RefreshCw, CheckCircle2, AlertCircle } from "lucide-react"

export function RefreshStatusBar({ refreshRunId }: { refreshRunId: string }) {
  const { data: run } = useRefreshRun(refreshRunId)

  if (!run) return null

  const total = run.symbols_total ?? 0
  const done = run.symbols_done ?? 0
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  const isDone = run.status === "succeeded" || run.status === "completed"
  const isFailed = run.status === "failed"
  const isRunning = run.status === "running" || run.status === "queued"

  return (
    <div className="flex items-center gap-3 rounded-lg border bg-card p-3">
      {isRunning && <RefreshCw className="h-4 w-4 animate-spin text-blue-600" />}
      {isDone && <CheckCircle2 className="h-4 w-4 text-green-600" />}
      {isFailed && <AlertCircle className="h-4 w-4 text-red-600" />}

      <div className="flex-1 space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className="font-medium">
            {isRunning
              ? `Mise à jour en cours… ${done}/${total}`
              : isDone
                ? "Mise à jour terminée"
                : run.error_message ?? "Erreur"}
          </span>
          <Badge variant="outline" className="text-[10px]">
            {run.status}
          </Badge>
        </div>
        {isRunning && <Progress value={pct} className="h-1.5" />}
      </div>
    </div>
  )
}
