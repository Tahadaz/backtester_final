"use client"

import type { CrossAssetClass } from "@/lib/api"

const LABELS: Record<CrossAssetClass, string> = { fx: "FX", commodity: "Commodities", rates: "Rates & Bonds" }

export function AssetClassTabs({ value, onChange }: { value: CrossAssetClass; onChange: (value: CrossAssetClass) => void }) {
  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="Classe d'actifs">
      {(Object.keys(LABELS) as CrossAssetClass[]).map((item) => (
        <button key={item} role="tab" aria-selected={value === item} onClick={() => onChange(item)} className={`rounded-full border px-4 py-2 text-sm font-medium ${value === item ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card text-muted-foreground"}`}>
          {LABELS[item]}
        </button>
      ))}
    </div>
  )
}
