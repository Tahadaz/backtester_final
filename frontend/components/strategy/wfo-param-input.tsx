"use client"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import {
  resolveWfoSearchSpace,
  ensureWfoSearchSpaces,
  type HorizonKey,
  type WFOParam,
  type WFOParamSearchSpace,
} from "@/lib/strategy-v2"

interface WfoParamInputProps {
  label: string
  horizon: HorizonKey
  param: WFOParam<number>
  step?: number
  min?: number
  max?: number
  defaultSpaces?: Partial<Record<HorizonKey, WFOParamSearchSpace<number>>>
  onChange: (next: WFOParam<number>) => void
}

export function WfoParamInput({
  label,
  horizon,
  param,
  step = 1,
  min,
  max,
  defaultSpaces,
  onChange,
}: WfoParamInputProps) {
  const isWfo = param.mode === "wfo"
  const space = resolveWfoSearchSpace(param, horizon, step, defaultSpaces)

  function setMode(wfo: boolean) {
    onChange({
      ...param,
      mode: wfo ? "wfo" : "manual",
      search_spaces_by_horizon: ensureWfoSearchSpaces(param, step, defaultSpaces),
    })
  }

  function setValue(raw: string) {
    const value = Number(raw)
    if (!isNaN(value)) onChange({ ...param, value })
  }

  function setSpace(field: keyof WFOParamSearchSpace<number>, raw: string) {
    const num = Number(raw)
    if (isNaN(num)) return
    const spaces = ensureWfoSearchSpaces(param, step, defaultSpaces)
    onChange({
      ...param,
      search_spaces_by_horizon: {
        ...spaces,
        [horizon]: { ...spaces[horizon], [field]: num },
      },
    })
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <Label className="text-xs">{label}</Label>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-muted-foreground">WFO</span>
          <Switch checked={isWfo} onCheckedChange={setMode} />
        </div>
      </div>

      <div className={`grid gap-2 ${isWfo ? "grid-cols-4" : "grid-cols-1"}`}>
        <div>
          <Input
            type="number"
            className="h-7 text-xs"
            value={param.value}
            step={step}
            min={min}
            max={max}
            onChange={(e) => setValue(e.target.value)}
          />
        </div>
        {isWfo && (
          <>
            {(["scan_min", "scan_max", "scan_step"] as const).map((field) => (
              <div key={field}>
                <Label className="text-[10px] text-muted-foreground">
                  {field === "scan_min" ? "Min" : field === "scan_max" ? "Max" : "Pas"}
                </Label>
                <Input
                  type="number"
                  className="h-7 text-xs"
                  value={space[field]}
                  step={step}
                  min={field === "scan_step" ? 0 : min}
                  max={field === "scan_step" ? undefined : max}
                  onChange={(e) => setSpace(field, e.target.value)}
                />
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
