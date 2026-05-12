"use client"

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const horizons = [
  { value: "weekly", label: "Court terme" },
  { value: "monthly", label: "Moyen terme" },
  { value: "quarterly", label: "Long terme" },
]

export function HorizonSelector({
  value,
  onChange,
  compact = false,
}: {
  value: string
  onChange: (horizon: string) => void
  compact?: boolean
}) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v)}
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
          {compact ? h.label.replace(" terme", "") : h.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
