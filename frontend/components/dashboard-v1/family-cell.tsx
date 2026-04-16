import type { FamilyScore } from "@/lib/dashboard-types"
import { SignalBadge } from "./signal-badge"

interface FamilyCellProps {
  score: FamilyScore | undefined | null
}

export function FamilyCell({ score }: FamilyCellProps) {
  if (!score) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  return (
    <div>
      <SignalBadge label={score.label} />
    </div>
  )
}
