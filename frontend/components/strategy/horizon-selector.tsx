"use client"

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { HORIZON_OPTIONS, legacyHorizonKey, resolveHorizonPreset } from "@/lib/horizon"

const horizons = HORIZON_OPTIONS
type HorizonOutputMode = "canonical" | "legacy"

export function HorizonSelector({
  value,
  onChange,
  compact = false,
  outputMode = "canonical",
}: {
  value: string
  onChange: (horizon: string) => void
  compact?: boolean
  outputMode?: HorizonOutputMode
}) {
  const activeValue = resolveHorizonPreset(value).value

  return (
    <ToggleGroup
      type="single"
      value={activeValue}
      onValueChange={(v) => {
        if (!v) return
        onChange(outputMode === "legacy" ? legacyHorizonKey(v) : v)
      }}
      className={compact ? "w-full rounded-md border border-line bg-bg2 p-0.5" : "rounded-lg border p-0.5"}
    >
      {horizons.map((h) => (
        <ToggleGroupItem
          key={h.value}
          value={h.value}
          size="sm"
          className={
            compact
              ? "h-6 flex-1 rounded-[4px] px-1 text-[11px] data-[state=on]:bg-card data-[state=on]:text-foreground"
              : "px-3 text-xs data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          }
        >
          {h.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
