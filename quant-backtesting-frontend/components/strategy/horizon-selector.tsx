"use client"

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"

const horizons = [
  { value: "short", label: "Court terme" },
  { value: "medium", label: "Moyen terme" },
  { value: "long", label: "Long terme" },
]

export function HorizonSelector({
  value,
  onChange,
}: {
  value: string
  onChange: (horizon: string) => void
}) {
  return (
    <ToggleGroup
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v)}
      className="border rounded-lg p-0.5"
    >
      {horizons.map((h) => (
        <ToggleGroupItem
          key={h.value}
          value={h.value}
          size="sm"
          className="text-xs px-3 data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
        >
          {h.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  )
}
