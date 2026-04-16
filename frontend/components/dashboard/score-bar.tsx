import { cn } from "@/lib/utils"
import { scoreBarColor } from "@/lib/dashboard-constants"

interface ScoreBarProps {
  score: number | null
  className?: string
}

export function ScoreBar({ score, className }: ScoreBarProps) {
  if (score == null) {
    return <div className={cn("h-2 w-full rounded-full bg-muted", className)} />
  }

  const clamped = Math.max(-100, Math.min(100, score))
  const widthPct = (Math.abs(clamped) / 100) * 50
  const isPositive = clamped >= 0

  return (
    <div className={cn("relative h-2 w-full rounded-full bg-muted", className)}>
      <div className="absolute left-1/2 top-0 h-full w-px bg-border" />
      <div
        className={cn("absolute top-0 h-full rounded-full", scoreBarColor(clamped))}
        style={{
          left: isPositive ? "50%" : `${50 - widthPct}%`,
          width: `${widthPct}%`,
        }}
      />
    </div>
  )
}
