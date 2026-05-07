"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { WfoParamInput } from "@/components/strategy/wfo-param-input"
import type { RiskPreview } from "@/lib/api"
import {
  atrMultiplierDefaultSearchSpaces,
  cooldownBarsDefaultSearchSpaces,
  rrRatioDefaultSearchSpaces,
  timeStopBarsDefaultSearchSpaces,
  type HorizonKey,
  type RiskConfigV2,
} from "@/lib/strategy-v2"

interface RiskTabProps {
  horizon: HorizonKey
  risk: RiskConfigV2
  preview?: RiskPreview
  onChange: (next: RiskConfigV2) => void
}

export function RiskTab({ horizon, risk, preview, onChange }: RiskTabProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Risk</CardTitle>
        <CardDescription>
          Safety rails are defined here. These are portfolio and trade protections, not substitutes for exit rules.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {preview ? (
          <div className="grid gap-3 md:grid-cols-3">
            <div className="rounded-lg border bg-muted/20 p-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Current close</p>
              <p className="mt-1 text-sm font-semibold">{preview.current_close == null ? "--" : preview.current_close.toFixed(2)}</p>
            </div>
            <div className="rounded-lg border bg-muted/20 p-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">ATR 14</p>
              <p className="mt-1 text-sm font-semibold">{preview.atr_14 == null ? "--" : preview.atr_14.toFixed(2)}</p>
            </div>
            <div className="rounded-lg border bg-muted/20 p-3">
              <p className="text-[11px] uppercase tracking-wide text-muted-foreground">Preview</p>
              <p className="mt-1 text-xs text-muted-foreground">{preview.explain}</p>
            </div>
          </div>
        ) : null}

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="space-y-3 rounded-xl border p-4">
            <div className="space-y-1">
              <Label className="text-xs">Stop loss mode</Label>
              <Select
                value={risk.stop_loss.mode}
                onValueChange={(value) =>
                  onChange({
                    ...risk,
                    stop_loss: {
                      ...risk.stop_loss,
                      mode: value as RiskConfigV2["stop_loss"]["mode"],
                    },
                  })
                }
              >
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual_pct">Manual %</SelectItem>
                  <SelectItem value="atr_based">ATR-based</SelectItem>
                  <SelectItem value="wfo">WFO</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {risk.stop_loss.mode === "manual_pct" ? (
              <div className="space-y-1">
                <Label className="text-xs">Manual stop (%)</Label>
                <Input
                  type="number"
                  className="h-8 text-sm"
                  value={risk.stop_loss.manual_pct ?? 0.02}
                  step={0.01}
                  min={0}
                  onChange={(event) =>
                    onChange({
                      ...risk,
                      stop_loss: {
                        ...risk.stop_loss,
                        manual_pct: Number(event.target.value),
                      },
                    })
                  }
                />
              </div>
            ) : (
              <WfoParamInput
                label="ATR multiplier"
                horizon={horizon}
                param={risk.stop_loss.atr_multiplier ?? { mode: "manual", value: 1.5 }}
                step={0.1}
                min={0.1}
                defaultSpaces={atrMultiplierDefaultSearchSpaces(risk.stop_loss.atr_multiplier?.value ?? 1.5)}
                onChange={(nextParam) =>
                  onChange({
                    ...risk,
                    stop_loss: {
                      ...risk.stop_loss,
                      atr_multiplier: nextParam,
                    },
                  })
                }
              />
            )}
          </div>

          <div className="space-y-3 rounded-xl border p-4">
            <div className="space-y-1">
              <Label className="text-xs">Take profit mode</Label>
              <Select
                value={risk.take_profit.mode}
                onValueChange={(value) =>
                  onChange({
                    ...risk,
                    take_profit: {
                      ...risk.take_profit,
                      mode: value as RiskConfigV2["take_profit"]["mode"],
                    },
                  })
                }
              >
                <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="manual_pct">Manual %</SelectItem>
                  <SelectItem value="rr_target">R:R target</SelectItem>
                  <SelectItem value="wfo">WFO</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {risk.take_profit.mode === "manual_pct" ? (
              <div className="space-y-1">
                <Label className="text-xs">Manual target (%)</Label>
                <Input
                  type="number"
                  className="h-8 text-sm"
                  value={risk.take_profit.manual_pct ?? 0.03}
                  step={0.01}
                  min={0}
                  onChange={(event) =>
                    onChange({
                      ...risk,
                      take_profit: {
                        ...risk.take_profit,
                        manual_pct: Number(event.target.value),
                      },
                    })
                  }
                />
              </div>
            ) : (
              <WfoParamInput
                label="R:R ratio"
                horizon={horizon}
                param={risk.take_profit.rr_ratio ?? { mode: "manual", value: 1.5 }}
                step={0.1}
                min={0.1}
                defaultSpaces={rrRatioDefaultSearchSpaces(risk.take_profit.rr_ratio?.value ?? 1.5)}
                onChange={(nextParam) =>
                  onChange({
                    ...risk,
                    take_profit: {
                      ...risk.take_profit,
                      rr_ratio: nextParam,
                    },
                  })
                }
              />
            )}
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <WfoParamInput
            label="Cooldown bars"
            horizon={horizon}
            param={risk.cooldown_bars}
            step={1}
            min={0}
            defaultSpaces={cooldownBarsDefaultSearchSpaces(risk.cooldown_bars.value)}
            onChange={(nextParam) => onChange({ ...risk, cooldown_bars: nextParam })}
          />

          <div className="space-y-3 rounded-xl border p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">Time stop</p>
                <p className="text-xs text-muted-foreground">Maximum holding period before a forced exit.</p>
              </div>
              <Switch
                checked={risk.time_stop.enabled}
                onCheckedChange={(checked) =>
                  onChange({
                    ...risk,
                    time_stop: {
                      ...risk.time_stop,
                      enabled: checked,
                    },
                  })
                }
              />
            </div>
            <WfoParamInput
              label="Max bars"
              horizon={horizon}
              param={risk.time_stop.bars}
              step={1}
              min={1}
              defaultSpaces={timeStopBarsDefaultSearchSpaces(risk.time_stop.bars.value)}
              onChange={(nextParam) =>
                onChange({
                  ...risk,
                  time_stop: {
                    ...risk.time_stop,
                    bars: nextParam,
                  },
                })
              }
            />
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">Trailing stop</p>
              <p className="text-xs text-muted-foreground">Stored as a strategic toggle for later execution support.</p>
            </div>
            <Switch
              checked={risk.trailing_stop_enabled}
              onCheckedChange={(checked) => onChange({ ...risk, trailing_stop_enabled: checked })}
            />
          </div>
          <div className="space-y-1 rounded-lg border p-3">
            <Label className="text-xs">Max position %</Label>
            <Input
              type="number"
              className="h-8 text-sm"
              value={risk.max_position_pct}
              step={1}
              min={0}
              max={100}
              onChange={(event) => onChange({ ...risk, max_position_pct: Number(event.target.value) })}
            />
          </div>
          <div className="space-y-1 rounded-lg border p-3">
            <Label className="text-xs">Max sector %</Label>
            <Input
              type="number"
              className="h-8 text-sm"
              value={risk.max_sector_pct}
              step={1}
              min={0}
              max={100}
              onChange={(event) => onChange({ ...risk, max_sector_pct: Number(event.target.value) })}
            />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
