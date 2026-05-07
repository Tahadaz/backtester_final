"use client"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import {
  ensureWfoSearchSpaces,
  resolveWfoSearchSpace,
  type HorizonKey,
  type WFOParam,
  type WFOParamSearchSpace,
} from "@/lib/strategy-v2"

interface WfoParamInputProps {
  label: string
  horizon: HorizonKey
  param: WFOParam<number>
  onChange: (next: WFOParam<number>) => void
  step?: number
  min?: number
  max?: number
  className?: string
  defaultSpaces?: Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>
}

export function WfoParamInput({
  label,
  horizon,
  param,
  onChange,
  step = 1,
  min,
  max,
  className,
  defaultSpaces,
}: WfoParamInputProps) {
  const isWfo = param.mode === "wfo"
  const spaces = ensureWfoSearchSpaces(param, step, defaultSpaces)
  const active = resolveWfoSearchSpace(param, horizon, step, defaultSpaces)

  function buildParam(nextMode: "manual" | "wfo", patch?: Partial<WFOParam<number>>): WFOParam<number> {
    const nextSpaces = ensureWfoSearchSpaces({ ...param, ...patch, value: patch?.value ?? param.value }, step, defaultSpaces)
    const nextActive = nextSpaces[horizon] ?? active
    return {
      ...param,
      ...patch,
      mode: nextMode,
      scan_min: nextActive.scan_min,
      scan_max: nextActive.scan_max,
      scan_step: nextActive.scan_step,
      search_spaces_by_horizon: nextSpaces,
      value: patch?.value ?? param.value,
    }
  }

  function updateActiveSpace(patch: Partial<WFOParamSearchSpace<number>>) {
    const nextSpaces = {
      ...spaces,
      [horizon]: {
        ...active,
        ...patch,
      },
    }
    onChange({
      ...buildParam("wfo"),
      search_spaces_by_horizon: nextSpaces,
      scan_min: nextSpaces[horizon]?.scan_min ?? active.scan_min,
      scan_max: nextSpaces[horizon]?.scan_max ?? active.scan_max,
      scan_step: nextSpaces[horizon]?.scan_step ?? active.scan_step,
    })
  }

  return (
    <div className={cn("space-y-2 rounded-lg border bg-background p-3", className)}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <Label className="text-xs">{label}</Label>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {isWfo ? "Optimized by walk-forward" : "Fixed manually"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground">WFO</span>
          <Switch
            checked={isWfo}
            onCheckedChange={(checked) =>
              onChange(
                checked
                  ? buildParam("wfo")
                  : buildParam("manual"),
              )
            }
          />
        </div>
      </div>

      {!isWfo ? (
        <div className="space-y-1">
          <Label className="text-[11px] text-muted-foreground">Value</Label>
          <Input
            type="number"
            className="h-8 text-sm"
            value={param.value}
            min={min}
            max={max}
            step={step}
            onChange={(event) =>
              onChange(buildParam("manual", { value: Number(event.target.value) }))
            }
          />
        </div>
      ) : (
        <div className="space-y-3">
          <div className="rounded-md border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
            Editing the <span className="font-medium text-foreground">{horizon}</span> preset. The other horizon presets are kept and will appear when you switch the strategy horizon.
          </div>
          <div className="grid gap-2 sm:grid-cols-4">
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Seed</Label>
            <Input
              type="number"
              className="h-8 text-sm"
              value={param.value}
              min={min}
              max={max}
              step={step}
              onChange={(event) => onChange(buildParam("wfo", { value: Number(event.target.value) }))}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Min</Label>
            <Input
              type="number"
              className="h-8 text-sm"
              value={active.scan_min}
              min={min}
              max={max}
              step={step}
              onChange={(event) => updateActiveSpace({ scan_min: Number(event.target.value) })}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Max</Label>
            <Input
              type="number"
              className="h-8 text-sm"
              value={active.scan_max}
              min={min}
              max={max}
              step={step}
              onChange={(event) => updateActiveSpace({ scan_max: Number(event.target.value) })}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[11px] text-muted-foreground">Step</Label>
            <Input
              type="number"
              className="h-8 text-sm"
              value={active.scan_step}
              min={step}
              step={step}
              onChange={(event) => updateActiveSpace({ scan_step: Number(event.target.value) })}
            />
          </div>
        </div>
        </div>
      )}
    </div>
  )
}
