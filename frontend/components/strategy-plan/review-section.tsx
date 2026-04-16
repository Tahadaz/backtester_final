"use client"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { CheckCircle2, AlertTriangle, Info } from "lucide-react"
import { cn } from "@/lib/utils"

type CheckStatus = "ok" | "warning" | "info"

interface CheckItem {
  section: string
  status: CheckStatus
  message: string
}

function computeChecklist({
  basket,
  enabledFamilies,
  focusedStock,
  executionStatus,
  accountEquity,
  winRate,
  avgWlRatio,
  strategyStatus,
}: {
  basket: string[]
  enabledFamilies: string[]
  focusedStock: string | null
  executionStatus: string | null
  accountEquity: number
  winRate: number
  avgWlRatio: number
  strategyStatus: string
}): CheckItem[] {
  const items: CheckItem[] = []

  // Univers
  if (basket.length === 0) {
    items.push({ section: "Univers", status: "warning", message: "Aucun titre dans le panier" })
  } else {
    items.push({ section: "Univers", status: "ok", message: `${basket.length} titre(s) dans le panier` })
  }

  // Signal
  if (enabledFamilies.length === 0) {
    items.push({ section: "Signal", status: "warning", message: "Toutes les familles sont desactivees" })
  } else {
    items.push({ section: "Signal", status: "ok", message: `${enabledFamilies.length}/4 familles actives` })
  }

  // Execution
  if (!focusedStock) {
    items.push({ section: "Execution", status: "warning", message: "Aucun titre selectionne" })
  } else if (executionStatus === "entry_zone") {
    items.push({ section: "Execution", status: "ok", message: `Setup actif pour ${focusedStock}` })
  } else if (executionStatus === "watching") {
    items.push({ section: "Execution", status: "info", message: `En attente pour ${focusedStock}` })
  } else {
    items.push({ section: "Execution", status: "warning", message: `Pas de setup pour ${focusedStock}` })
  }

  // Dimensionnement
  if (accountEquity <= 0) {
    items.push({ section: "Dimensionnement", status: "warning", message: "Capital non defini" })
  } else if (winRate === 0.55 && avgWlRatio === 1.5) {
    items.push({ section: "Dimensionnement", status: "info", message: "Metriques Kelly par defaut — a calibrer apres backtest" })
  } else {
    items.push({ section: "Dimensionnement", status: "ok", message: `Capital ${accountEquity.toLocaleString("fr-FR")} MAD` })
  }

  // General
  if (strategyStatus !== "saved") {
    items.push({ section: "General", status: "info", message: "Strategie non sauvegardee" })
  } else {
    items.push({ section: "General", status: "ok", message: "Strategie sauvegardee" })
  }

  return items
}

const STATUS_ICON = {
  ok: { Icon: CheckCircle2, cls: "text-green-600" },
  warning: { Icon: AlertTriangle, cls: "text-amber-500" },
  info: { Icon: Info, cls: "text-blue-500" },
}

export function ReviewSection({
  basket,
  enabledFamilies,
  focusedStock,
  executionStatus,
  accountEquity,
  winRate,
  avgWlRatio,
  strategyStatus,
}: {
  basket: string[]
  enabledFamilies: string[]
  focusedStock: string | null
  executionStatus: string | null
  accountEquity: number
  winRate: number
  avgWlRatio: number
  strategyStatus: string
}) {
  const items = computeChecklist({
    basket,
    enabledFamilies,
    focusedStock,
    executionStatus,
    accountEquity,
    winRate,
    avgWlRatio,
    strategyStatus,
  })

  const okCount = items.filter((i) => i.status === "ok").length
  const warningCount = items.filter((i) => i.status === "warning").length

  return (
    <div className="space-y-3">
      {/* Checklist */}
      <div className="space-y-1.5">
        {items.map((item) => {
          const { Icon, cls } = STATUS_ICON[item.status]
          return (
            <div
              key={item.section}
              className="flex items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-muted/50 transition-colors"
            >
              <Icon className={cn("h-3.5 w-3.5 shrink-0", cls)} />
              <span className="text-xs font-medium w-[120px] shrink-0">
                {item.section}
              </span>
              <span className="text-xs text-muted-foreground">
                {item.message}
              </span>
            </div>
          )
        })}
      </div>

      {/* Summary */}
      <div className="flex items-center justify-between rounded-md bg-muted/50 px-3 py-2">
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-[10px] font-mono">
            {okCount}/{items.length} prets
          </Badge>
          {warningCount > 0 && (
            <Badge variant="outline" className="text-[10px] font-mono text-amber-600 border-amber-300">
              {warningCount} avertissement(s)
            </Badge>
          )}
        </div>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button size="sm" variant="outline" className="text-xs h-7" disabled>
                Ouvrir dans Backtest
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              <p className="text-xs">Bientot disponible</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  )
}
