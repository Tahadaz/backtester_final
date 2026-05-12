"use client"

import { cn } from "@/lib/utils"
import type { SignalsPageView } from "@/components/strategy/signals-view-layout"

type SignalsVersionToggleProps = {
  value: SignalsPageView
  onChange: (value: SignalsPageView) => void
}

type SignalUniverse = "expanded" | "legacy"
type SignalSource = "ta" | "factor_x_ta"
type SignalComplexity = "simple" | "combo"

type SignalModeAxes = {
  universe: SignalUniverse
  source: SignalSource
  complexity: SignalComplexity
}

function parseView(value: SignalsPageView): SignalModeAxes {
  return {
    universe: value === "legacy" || value.startsWith("legacy_") ? "legacy" : "expanded",
    source: value === "factor_x_ta" || value.includes("factor_x_ta") ? "factor_x_ta" : "ta",
    complexity: value.endsWith("_combo") ? "combo" : "simple",
  }
}

function buildView({ universe, source, complexity }: SignalModeAxes): SignalsPageView {
  return `${universe}_${source}_${complexity}` as SignalsPageView
}

function Segment<TValue extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: TValue
  options: Array<{ value: TValue; label: string; title?: string }>
  onChange: (value: TValue) => void
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
        {label}
      </span>
      <div className="inline-flex rounded-md border border-line bg-card p-0.5">
        {options.map((option) => {
          const active = option.value === value
          return (
            <button
              key={option.value}
              type="button"
              title={option.title}
              aria-pressed={active}
              onClick={() => onChange(option.value)}
              className={cn(
                "h-[26px] rounded-[5px] px-2.5 text-[11px] font-medium text-muted-foreground transition-colors",
                active && "bg-bg3 font-semibold text-foreground",
              )}
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function SignalsVersionToggle({
  value,
  onChange,
}: SignalsVersionToggleProps) {
  const axes = parseView(value)
  const updateAxis = <TKey extends keyof SignalModeAxes>(
    key: TKey,
    nextValue: SignalModeAxes[TKey],
  ) => {
    onChange(buildView({ ...axes, [key]: nextValue }))
  }

  return (
    <div className="flex max-w-full flex-wrap items-center gap-1.5">
      <Segment
        label="Universe"
        value={axes.universe}
        onChange={(nextValue) => updateAxis("universe", nextValue)}
        options={[
          { value: "expanded", label: "Expanded", title: "Expanded indicator universe" },
          { value: "legacy", label: "Legacy", title: "Legacy indicator universe" },
        ]}
      />
      <Segment
        label="Source"
        value={axes.source}
        onChange={(nextValue) => updateAxis("source", nextValue)}
        options={[
          { value: "ta", label: "Pure TA", title: "Technical indicators only" },
          { value: "factor_x_ta", label: "Factor x TA", title: "Factor-conditioned technical indicators" },
        ]}
      />
      <Segment
        label="Mode"
        value={axes.complexity}
        onChange={(nextValue) => updateAxis("complexity", nextValue)}
        options={[
          { value: "simple", label: "Simple", title: "Single-family representatives" },
          { value: "combo", label: "Combo", title: "Strict AND combo representatives" },
        ]}
      />
    </div>
  )
}
