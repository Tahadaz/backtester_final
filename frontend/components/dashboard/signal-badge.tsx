import { cn } from "@/lib/utils"
import { SIGNAL_BADGE_COLORS, SIGNAL_BADGE_FALLBACK } from "@/lib/dashboard-constants"

interface SignalBadgeProps {
  label: string | null
  className?: string
  size?: "sm" | "md"
}

export function SignalBadge({ label, className, size = "md" }: SignalBadgeProps) {
  if (!label) {
    return (
      <span
        className={cn(
          "inline-flex items-center rounded-md px-2.5 py-1 text-xs font-semibold",
          SIGNAL_BADGE_FALLBACK,
          className,
        )}
      >
        -
      </span>
    )
  }

  const colorClass = SIGNAL_BADGE_COLORS[label] ?? SIGNAL_BADGE_FALLBACK

  return (
    <span
      className={cn(
        "inline-flex items-center font-semibold",
        size === "sm" ? "rounded-md px-2 py-0.5 text-xs" : "rounded-md px-2.5 py-1 text-sm",
        colorClass,
        className,
      )}
    >
      {label}
    </span>
  )
}
