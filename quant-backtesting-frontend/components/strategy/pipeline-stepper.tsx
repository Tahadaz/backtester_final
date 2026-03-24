"use client"

import { cn } from "@/lib/utils"
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip"

const STEPS = [
  {
    key: "tested",
    label: "TESTEES",
    color: "bg-slate-500 border-slate-400 text-white",
    activeColor: "ring-2 ring-slate-400 ring-offset-2",
  },
  {
    key: "viable",
    label: "VIABLES",
    color: "bg-blue-500 border-blue-400 text-white",
    activeColor: "ring-2 ring-blue-400 ring-offset-2",
  },
  {
    key: "competitive",
    label: "COMPETITIFS",
    color: "bg-indigo-500 border-indigo-400 text-white",
    activeColor: "ring-2 ring-indigo-400 ring-offset-2",
  },
  {
    key: "representative",
    label: "REPRESENTATIFS",
    color: "bg-emerald-500 border-emerald-400 text-white",
    activeColor: "ring-2 ring-emerald-400 ring-offset-2",
  },
] as const

const FILTER_LABELS = [
  "\u226540% fenetres positives, \u22653 fenetres valides",
  "Top 60% par score de fiabilite (min 0.25)",
  "|Correlation Pearson| < 0.85",
]

const METHODOLOGY = [
  "Score de fiabilite = Sharpe (35%) + Stabilite (30%) + Consistance (20%) + Drawdown (15%). Seuil: au moins 40% des fenetres OOS avec Sharpe positif et minimum 3 fenetres valides.",
  "Filtre percentile: seul le top 60% par score de fiabilite sont gardes. Score minimum absolu: 0.25.",
  "Reduction de redondance: selection gloutonne par score decroissant. Si la correlation Pearson |r| > 0.85 avec un variant deja selectionne, il est elimine. Maximum 10 representatifs.",
]

export function PipelineStepper({
  tested,
  viable,
  competitive,
  representative,
  activeStage,
  onStageClick,
}: {
  tested: number
  viable: number
  competitive: number
  representative: number
  activeStage?: string | null
  onStageClick?: (stage: string | null) => void
}) {
  const counts = [tested, viable, competitive, representative]

  return (
    <div className="flex flex-wrap items-start gap-y-3">
      {STEPS.map((step, i) => {
        const eliminated = i > 0 ? counts[i - 1] - counts[i] : 0
        const isActive = activeStage === step.key
        const isClickable = !!onStageClick

        return (
          <div key={step.key} className="flex items-start">
            {/* Connector + filter label */}
            {i > 0 && (
              <div className="flex flex-col items-center mx-2 mt-1">
                <div className="h-px w-8 border-t border-dashed border-muted-foreground/40" />
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="text-[9px] text-muted-foreground mt-1 max-w-[120px] text-center leading-tight cursor-help">
                      {FILTER_LABELS[i - 1]}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-[280px]">
                    <p className="text-xs leading-relaxed">{METHODOLOGY[i - 1]}</p>
                  </TooltipContent>
                </Tooltip>
                <span className="text-[9px] text-muted-foreground/60 font-mono">
                  (-{eliminated})
                </span>
              </div>
            )}

            {/* Step circle + label */}
            <div className="flex flex-col items-center">
              <button
                type="button"
                onClick={() => {
                  if (!onStageClick) return
                  onStageClick(isActive ? null : step.key)
                }}
                className={cn(
                  "flex h-9 w-9 items-center justify-center rounded-full border-2 text-sm font-bold transition-all",
                  step.color,
                  isClickable && "cursor-pointer hover:scale-110",
                  isActive && step.activeColor,
                )}
              >
                {counts[i]}
              </button>
              <span className="text-[10px] uppercase tracking-wider text-muted-foreground mt-1.5 text-center">
                {step.label}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
