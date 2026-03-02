import { cn } from "@/lib/utils"
import { signalLabel, signalType } from "@/lib/format"

const signalStyles = {
  buy: "bg-[oklch(0.92_0.06_165)] text-[oklch(0.45_0.15_165)] border-[oklch(0.85_0.08_165)]",
  sell: "bg-[oklch(0.92_0.06_25)] text-[oklch(0.50_0.20_25)] border-[oklch(0.85_0.08_25)]",
  hold: "bg-muted text-muted-foreground border-border",
}

export function SignalBadge({
  value,
  size = "sm",
}: {
  value: number | null | undefined
  size?: "sm" | "md" | "lg"
}) {
  const type = signalType(value)
  const label = signalLabel(value)

  const sizeClasses = {
    sm: "px-2 py-0.5 text-xs",
    md: "px-3 py-1 text-sm",
    lg: "px-4 py-1.5 text-base",
  }

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border font-bold tracking-wide uppercase",
        signalStyles[type],
        sizeClasses[size]
      )}
    >
      {label}
    </span>
  )
}
