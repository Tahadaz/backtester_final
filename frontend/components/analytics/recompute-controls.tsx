"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { useToast } from "@/hooks/use-toast"
import {
  triggerAllWfo,
  triggerWfoComputation,
  triggerAllSignalEngine,
  triggerSignalEngine,
  triggerAllPredictiveHistory,
  triggerPredictiveHistory,
} from "@/lib/api"
import { RefreshCw } from "lucide-react"

interface RecomputeControlsProps {
  scope: "all" | "symbol"
  symbol?: string
  horizon?: string
  variant?: string
}

export function RecomputeControls({ scope, symbol, horizon = "short", variant = "legacy" }: RecomputeControlsProps) {
  const { toast } = useToast()
  const [wfoLoading, setWfoLoading] = useState(false)
  const [engineLoading, setEngineLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)

  async function handleHistory() {
    setHistoryLoading(true)
    try {
      if (scope === "all") {
        const res = await triggerAllPredictiveHistory()
        toast({ title: "Historique de scores lancé", description: `${res.triggered} symboles enqueued.` })
      } else if (symbol) {
        await triggerPredictiveHistory(symbol)
        toast({ title: "Historique de scores lancé", description: symbol })
      }
    } catch (e) {
      toast({ title: "Erreur Historique", description: String(e), variant: "destructive" })
    } finally {
      setHistoryLoading(false)
    }
  }

  async function handleWfo() {
    setWfoLoading(true)
    try {
      if (scope === "all") {
        const res = await triggerAllWfo({})
        toast({ title: "WFO lancé", description: `${res.total_jobs} jobs enqueued.` })
      } else if (symbol) {
        await triggerWfoComputation({ symbol, horizon })
        toast({ title: "WFO lancé", description: `${symbol} / ${horizon}` })
      }
    } catch (e) {
      toast({ title: "Erreur WFO", description: String(e), variant: "destructive" })
    } finally {
      setWfoLoading(false)
    }
  }

  async function handleEngine() {
    setEngineLoading(true)
    try {
      if (scope === "all") {
        const res = await triggerAllSignalEngine({})
        toast({ title: "Signal Engine lancé", description: `${res.total_jobs} jobs enqueued.` })
      } else if (symbol) {
        await triggerSignalEngine({ symbol, horizon, variant })
        toast({ title: "Signal Engine lancé", description: `${symbol} / ${horizon}` })
      }
    } catch (e) {
      toast({ title: "Erreur Signal Engine", description: String(e), variant: "destructive" })
    } finally {
      setEngineLoading(false)
    }
  }

  const wfoLabel = scope === "all" ? "Recompute All WFO" : "Recompute WFO"
  const engineLabel = scope === "all" ? "Recompute All Signal Engine" : "Recompute Signal Engine"
  const historyLabel = scope === "all" ? "Recompute All Predictive History" : "Recompute Predictive History"
  const historyConfirmBody = scope === "all"
    ? "Reconstruit les séries de scores per-bar pour tous les symboles. Doit être lancé après les recomputes WFO et Signal Engine. Durée estimée : 15–30 min."
    : `Reconstruit la série de scores per-bar pour ${symbol}. Durée : ~30s.`

  const wfoConfirmBody = scope === "all"
    ? "Lance ~600 jobs WFO (toutes symboles × horizons). Durée estimée : 1–3 hrs."
    : `Lance le calcul WFO pour ${symbol} / ${horizon}.`

  const engineConfirmBody = scope === "all"
    ? "Lance ~600 jobs Signal Engine (toutes symboles × horizons). Durée estimée : 30–60 min avec le pool dédié."
    : `Lance le calcul Signal Engine pour ${symbol} / ${horizon}.`

  return (
    <div className="flex items-center gap-2">
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            disabled={wfoLoading}
            className="h-7 text-xs gap-1.5"
          >
            <RefreshCw className={`h-3 w-3 ${wfoLoading ? "animate-spin" : ""}`} />
            {wfoLabel}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{wfoLabel}</AlertDialogTitle>
            <AlertDialogDescription>{wfoConfirmBody}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction onClick={handleWfo}>Lancer</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            disabled={engineLoading}
            className="h-7 text-xs gap-1.5"
          >
            <RefreshCw className={`h-3 w-3 ${engineLoading ? "animate-spin" : ""}`} />
            {engineLabel}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{engineLabel}</AlertDialogTitle>
            <AlertDialogDescription>{engineConfirmBody}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction onClick={handleEngine}>Lancer</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button
            size="sm"
            variant="outline"
            disabled={historyLoading}
            className="h-7 text-xs gap-1.5"
          >
            <RefreshCw className={`h-3 w-3 ${historyLoading ? "animate-spin" : ""}`} />
            {historyLabel}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{historyLabel}</AlertDialogTitle>
            <AlertDialogDescription>{historyConfirmBody}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction onClick={handleHistory}>Lancer</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
