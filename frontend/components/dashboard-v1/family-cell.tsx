import type { FactorDependency, FamilyScore } from "@/lib/dashboard-types"
import { SignalBadge } from "./signal-badge"

interface FamilyCellProps {
  score: FamilyScore | undefined | null
  factorDependencies?: FactorDependency[]
}

export function FamilyCell({ score, factorDependencies = [] }: FamilyCellProps) {
  if (!score) {
    return <span className="text-xs text-muted-foreground">-</span>
  }

  return (
    <div className="space-y-1">
      <SignalBadge label={score.label} />
      {factorDependencies.length > 0 ? (
        <div className="flex max-w-[150px] flex-wrap gap-1">
          {factorDependencies.slice(0, 2).map((dependency) => (
            <span
              key={`${dependency.factor_ticker}:${dependency.condition_id}`}
              className="inline-flex max-w-full items-center rounded border border-border bg-muted/35 px-1.5 py-0.5 text-[9px] font-semibold text-muted-foreground"
              title={`${dependency.canonical_id} ${dependency.rule}`}
            >
              <span className="truncate">{dependency.canonical_id}</span>
              <span className="ml-1 font-mono font-normal">{dependency.rule}</span>
            </span>
          ))}
          {factorDependencies.length > 2 ? (
            <span className="text-[9px] text-muted-foreground">+{factorDependencies.length - 2}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
