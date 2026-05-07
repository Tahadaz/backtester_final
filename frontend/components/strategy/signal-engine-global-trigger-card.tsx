"use client"

import { useEffect, useRef, useState } from "react"
import { Play, RefreshCw } from "lucide-react"
import { fetchSignalEngineGlobalBatchStatus, triggerAllSignalEngine } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { cn } from "@/lib/utils"

type GlobalBatchStatus = {
  batch_id: string | null
  total: number
  succeeded: number
  running: number
  failed: number
  pending: number
  partial: number
}

const POLL_INTERVAL_MS = 5000

function _errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message
  return "Impossible de lancer le calcul global du Signal Engine."
}

export function SignalEngineGlobalTriggerCard() {
  const [isTriggering, setIsTriggering] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [batchStatus, setBatchStatus] = useState<GlobalBatchStatus | null>(null)
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = () => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const pollStatus = async (batchId?: string | null): Promise<GlobalBatchStatus | null> => {
    try {
      const status = await fetchSignalEngineGlobalBatchStatus(batchId || undefined)
      setBatchStatus(status)
      if (status.batch_id) {
        setActiveBatchId(status.batch_id)
      }
      if (status.running <= 0 && status.pending <= 0) {
        stopPolling()
      }
      return status
    } catch (err) {
      setError(_errorMessage(err))
      return null
    }
  }

  const startPolling = (batchId?: string | null) => {
    if (pollRef.current !== null) return
    pollRef.current = setInterval(() => {
      void pollStatus(batchId ?? activeBatchId)
    }, POLL_INTERVAL_MS)
  }

  const handleTriggerAll = async () => {
    setIsTriggering(true)
    setError(null)
    try {
      const trigger = await triggerAllSignalEngine({ variants: ["legacy", "expanded"] })
      setActiveBatchId(trigger.batch_id)
      const status = await pollStatus(trigger.batch_id)
      if (status && (status.running > 0 || status.pending > 0)) {
        startPolling(trigger.batch_id)
      }
    } catch (err) {
      setError(_errorMessage(err))
    } finally {
      setIsTriggering(false)
    }
  }

  const handleRefresh = async () => {
    setIsRefreshing(true)
    setError(null)
    try {
      const status = await pollStatus(activeBatchId)
      if (status && (status.running > 0 || status.pending > 0)) {
        startPolling(status.batch_id)
      }
    } finally {
      setIsRefreshing(false)
    }
  }

  useEffect(() => {
    void pollStatus(activeBatchId)
    return () => stopPolling()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const runningOrPending = (batchStatus?.running ?? 0) > 0 || (batchStatus?.pending ?? 0) > 0
  const completedCount = (batchStatus?.succeeded ?? 0) + (batchStatus?.failed ?? 0) + (batchStatus?.partial ?? 0)
  const progressPct = batchStatus && batchStatus.total > 0 ? Math.min(100, (completedCount / batchStatus.total) * 100) : 0

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardContent className="space-y-3 py-4">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold">Signal Engine global</p>
            <p className="text-[10px] text-muted-foreground">
              Lance tous les titres, tous les horizons, variantes legacy + expanded.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="text-xs"
              disabled={isRefreshing}
              onClick={handleRefresh}
            >
              <RefreshCw className={cn("mr-1 h-3 w-3", isRefreshing && "animate-spin")} />
              Rafraichir
            </Button>
            <Button
              size="sm"
              className="text-xs"
              disabled={isTriggering || runningOrPending}
              onClick={handleTriggerAll}
            >
              <Play className="mr-1 h-3 w-3" />
              Lancer Signal Engine global (tous les titres)
            </Button>
          </div>
        </div>

        {error ? <p className="text-[10px] text-destructive">{error}</p> : null}

        {batchStatus ? (
          <div className="space-y-1">
            <p className="text-[10px] text-muted-foreground">
              {completedCount}/{batchStatus.total} termines
              {batchStatus.running > 0 ? ` · ${batchStatus.running} en cours` : ""}
              {batchStatus.pending > 0 ? ` · ${batchStatus.pending} en attente` : ""}
              {batchStatus.partial > 0 ? ` · ${batchStatus.partial} partiels` : ""}
              {batchStatus.failed > 0 ? ` · ${batchStatus.failed} echoues` : ""}
            </p>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full bg-primary transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

