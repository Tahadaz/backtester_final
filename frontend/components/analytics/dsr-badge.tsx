"use client"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

interface DSRBadgeProps {
  dsr: number
  psr: number
  className?: string
}

function pct(v: number) {
  return Math.round(v * 100)
}

export function DSRBadge({ dsr, psr, className }: DSRBadgeProps) {
  if (!isFinite(dsr) || isNaN(dsr)) {
    return <Badge variant="outline" className={cn("text-[10px] text-muted-foreground", className)}>n/a</Badge>
  }

  const variant = dsr >= 0.9 ? "default" : dsr >= 0.7 ? "secondary" : "outline"
  const color =
    dsr >= 0.9
      ? "bg-emerald-100 text-emerald-800 border-emerald-300"
      : dsr >= 0.7
      ? "bg-yellow-50 text-yellow-800 border-yellow-300"
      : "text-muted-foreground"

  return (
    <Badge variant="outline" className={cn("text-[10px] tabular-nums", color, className)}>
      DSR {pct(dsr)}%
    </Badge>
  )
}
