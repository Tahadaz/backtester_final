import { cn } from "@/lib/utils"
import { SIGNAL_BADGE_COLORS, SIGNAL_BADGE_FALLBACK } from "@/lib/dashboard-constants"

interface SignalBadgeProps {
  label: string | null
  className?: string
}

const MOMENTUM_LABEL_ALIAS: Record<string, string> = {
  "Fort momentum haussier": "Très haussier",
  "Momentum haussier": "Haussier",
  "Pas de momentum": "Neutre",
  "Momentum baissier": "Baissier",
  "Fort momentum baissier": "Très baissier",
  "Fort momentum haussier ": "Très haussier",
  "Momentum haussier ": "Haussier",
  "Pas de momentum ": "Neutre",
  "Momentum baissier ": "Baissier",
  "Fort momentum baissier ": "Très baissier",
}

export function SignalBadge({ label, className }: SignalBadgeProps) {
  if (!label) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
          SIGNAL_BADGE_FALLBACK,
          className,
        )}
      >
        -
      </span>
    )
  }

  const normalizedLabel = MOMENTUM_LABEL_ALIAS[label.trim()] ?? label
  const colorClass = SIGNAL_BADGE_COLORS[normalizedLabel] ?? SIGNAL_BADGE_FALLBACK

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        colorClass,
        className,
      )}
    >
      {normalizedLabel}
    </span>
  )
}
