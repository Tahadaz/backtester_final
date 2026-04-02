"use client"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { LogIn, Pause, LogOut } from "lucide-react"
import { cn } from "@/lib/utils"

// Three-phase trade logic model
const TRADE_PHASES = [
  {
    icon: LogIn,
    title: "Entrée",
    borderColor: "border-green-500",
    iconColor: "text-green-600",
    points: [
      "Tendance existante et positive",
      "Momentum confirme l'accélération",
      "Mouvement non excessivement étiré",
      "Consensus \u2265 seuil d'entrée",
    ],
  },
  {
    icon: Pause,
    title: "Maintien",
    borderColor: "border-blue-500",
    iconColor: "text-blue-600",
    points: [
      "Thèse toujours valide",
      "Conviction au-dessus du seuil de maintien",
      "Le signal peut fluctuer sans déclencher la sortie",
    ],
  },
  {
    icon: LogOut,
    title: "Sortie",
    borderColor: "border-amber-500",
    iconColor: "text-amber-600",
    points: [
      "Détérioration de la conviction",
      "Consensus < seuil de maintien",
      "Pas besoin d'un retournement complet",
      "Invalidation de la thèse = sortie",
    ],
  },
]

function getPhaseStatus(
  consensus: number | null,
  entryThreshold: number,
  holdingThreshold: number,
): { label: string; color: string; bgColor: string } {
  if (consensus == null) return { label: "Pas de données", color: "text-muted-foreground", bgColor: "bg-muted/50" }
  const abs = Math.abs(consensus)
  if (abs >= entryThreshold) return { label: "Entrée possible", color: "text-green-700 dark:text-green-400", bgColor: "bg-green-50 dark:bg-green-950/30" }
  if (abs >= holdingThreshold) return { label: "Maintien", color: "text-blue-700 dark:text-blue-400", bgColor: "bg-blue-50 dark:bg-blue-950/30" }
  return { label: "Sortie / Pas de position", color: "text-amber-700 dark:text-amber-400", bgColor: "bg-amber-50 dark:bg-amber-950/30" }
}

export function ExecutionSection({
  focusedStock,
  consensusValue,
  executionConfig,
  onConfigChange,
}: {
  focusedStock: string | null
  consensusValue?: number | null
  executionConfig: {
    holding_bars: number
    entry_threshold: number
    holding_threshold: number
    atr_multiplier: number
    buffer_pct: number
    min_rr: number
  }
  onConfigChange: (patch: Partial<{
    holding_bars: number
    entry_threshold: number
    holding_threshold: number
    atr_multiplier: number
    buffer_pct: number
    min_rr: number
  }>) => void
}) {
  const phase = focusedStock
    ? getPhaseStatus(consensusValue ?? null, executionConfig.entry_threshold, executionConfig.holding_threshold)
    : null

  return (
    <div className="space-y-4">
      {/* Three-phase trade logic model — always visible */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {TRADE_PHASES.map((p) => (
          <div
            key={p.title}
            className={cn(
              "rounded-md border border-t-2 p-2.5 space-y-1.5",
              p.borderColor
            )}
          >
            <div className="flex items-center gap-1.5">
              <p.icon className={cn("h-3.5 w-3.5", p.iconColor)} />
              <span className="text-xs font-semibold">{p.title}</span>
            </div>
            <ul className="space-y-0.5">
              {p.points.map((point, i) => (
                <li key={i} className="text-[10px] text-muted-foreground leading-snug">
                  • {point}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <p className="text-[10px] italic text-muted-foreground">
        Le seuil de maintien est inférieur au seuil d'entrée — la position reste ouverte tant que la conviction ne chute pas trop (hystérésis).
      </p>

      {/* Live phase status — only when stock focused */}
      {focusedStock && phase && (
        <div className={cn("rounded-md border p-3 flex items-center justify-between", phase.bgColor)}>
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">{focusedStock}</span>
            <span className="text-[10px] font-mono text-muted-foreground">
              Consensus : {consensusValue != null ? consensusValue.toFixed(1) : "—"}
            </span>
          </div>
          <Badge variant="outline" className={cn("text-[10px] font-semibold", phase.color)}>
            {phase.label}
          </Badge>
        </div>
      )}

      {/* Parameters — always visible */}
      <div className="space-y-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Paramètres
        </span>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-[10px]">Horizon (barres)</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={executionConfig.holding_bars}
              onChange={(e) => onConfigChange({ holding_bars: Number(e.target.value) })}
              min={2}
              max={252}
              step={1}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Seuil entrée</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={executionConfig.entry_threshold}
              onChange={(e) => onConfigChange({ entry_threshold: Number(e.target.value) })}
              min={0}
              max={100}
              step={5}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Seuil maintien</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={executionConfig.holding_threshold}
              onChange={(e) => onConfigChange({ holding_threshold: Number(e.target.value) })}
              min={0}
              max={100}
              step={5}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Multiplicateur ATR</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={executionConfig.atr_multiplier}
              onChange={(e) => onConfigChange({ atr_multiplier: Number(e.target.value) })}
              min={0.1}
              max={10}
              step={0.1}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">R:R minimum</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={executionConfig.min_rr}
              onChange={(e) => onConfigChange({ min_rr: Number(e.target.value) })}
              min={0.1}
              max={20}
              step={0.1}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Buffer stop (%)</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={(executionConfig.buffer_pct * 100).toFixed(1)}
              onChange={(e) => onConfigChange({ buffer_pct: Number(e.target.value) / 100 })}
              min={0}
              max={10}
              step={0.1}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
