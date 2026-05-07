"use client"

import { cn } from "@/lib/utils"

interface ICBadgeProps {
  value: number
  showSign?: boolean
  className?: string
}

export function ICBadge({ value, showSign = true, className }: ICBadgeProps) {
  if (!isFinite(value) || isNaN(value)) {
    return <span className={cn("text-xs tabular-nums text-muted-foreground", className)}>—</span>
  }

  const pct = Math.round(value * 100)
  const color =
    value > 0.05
      ? "text-emerald-600"
      : value < -0.05
      ? "text-red-500"
      : "text-muted-foreground"

  return (
    <span className={cn("text-xs tabular-nums font-mono", color, className)}>
      {showSign && value > 0 ? "+" : ""}
      {pct}%
    </span>
  )
}
