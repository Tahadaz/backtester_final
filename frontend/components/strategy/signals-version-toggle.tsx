"use client"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import type { SignalsPageView } from "@/components/strategy/signals-view-layout"

type SignalsVersionToggleProps = {
  value: SignalsPageView
  onChange: (value: SignalsPageView) => void
}

const OPTIONS: Array<{ value: SignalsPageView; label: string; description: string }> = [
  {
    value: "expanded",
    label: "Expanded",
    description: "Version 20 familles",
  },
  {
    value: "legacy",
    label: "Legacy",
    description: "Version pre-expansion",
  },
  {
    value: "factor_x_ta",
    label: "Factor × TA",
    description: "Econometric selection",
  },
]

export function SignalsVersionToggle({
  value,
  onChange,
}: SignalsVersionToggleProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          Signal Page Version
        </p>
        <p className="text-sm text-muted-foreground">
          Bascule entre la vue legacy, expanded et Factor × TA.
        </p>
      </div>

      <div className="inline-flex rounded-lg border bg-muted/40 p-1">
        {OPTIONS.map((option) => {
          const active = option.value === value
          return (
            <Button
              key={option.value}
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onChange(option.value)}
              className={cn(
                "h-auto rounded-md px-3 py-2 text-left transition-colors",
                active
                  ? "bg-background text-foreground shadow-sm hover:bg-background"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="flex flex-col items-start">
                <span className="text-sm font-semibold">{option.label}</span>
                <span className="text-[11px] font-normal">{option.description}</span>
              </span>
            </Button>
          )
        })}
      </div>
    </div>
  )
}
