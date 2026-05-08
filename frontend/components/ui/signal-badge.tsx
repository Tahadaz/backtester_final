import { cn } from "@/lib/utils"
import { SIGNAL_BADGE_COLORS, SIGNAL_BADGE_FALLBACK } from "@/lib/dashboard-constants"

interface SignalBadgeProps {
  label: string | null
  className?: string
}

const MOMENTUM_LABEL_ALIAS: Record<string, string> = {
  "Fort momentum haussier": "Tres haussier",
  "Momentum haussier": "Haussier",
  "Pas de momentum": "Neutre",
  "Momentum baissier": "Baissier",
  "Fort momentum baissier": "Tres baissier",
}

export function SignalBadge({ label, className }: SignalBadgeProps) {
  if (!label) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-[6px] px-2 py-0.5 text-[11px] font-semibold leading-5",
          SIGNAL_BADGE_FALLBACK,
          className,
        )}
      >
        -
      </span>
    )
  }

  const trimmed = label.trim()
  const normalizedLabel = MOMENTUM_LABEL_ALIAS[trimmed] ?? trimmed
  const colorClass = SIGNAL_BADGE_COLORS[normalizedLabel] ?? SIGNAL_BADGE_FALLBACK

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[6px] px-2 py-0.5 text-[11px] font-semibold leading-5",
        colorClass,
        className,
      )}
    >
      {normalizedLabel}
    </span>
  )
}
