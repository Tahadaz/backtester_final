"use client"

import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import type { RulePreview } from "@/lib/api"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { WfoParamInput } from "@/components/strategy/wfo-param-input"
import {
  ruleThresholdDefaultSearchSpaces,
  directRuleSizingDefaultSearchSpaces,
  kellyModifierDefaultSearchSpaces,
  normalizeWfoParam,
  defaultExitRule,
  defaultRuleCondition,
  summarizeCondition,
  type HorizonKey,
  type ExitRuleV2,
  type RuleConditionV2,
} from "@/lib/strategy-v2"

const OPERATOR_OPTIONS = [">", ">=", "<", "<="] as const

interface ExitRulesTabProps {
  horizon: HorizonKey
  rules: ExitRuleV2[]
  scoreOptions: Array<{ value: string; label: string; missing?: boolean }>
  preview?: RulePreview
  errorMessage?: string | null
  onChange: (next: ExitRuleV2[]) => void
}

function ExitConditionEditor({
  condition,
  horizon,
  scoreOptions,
  onChange,
  onRemove,
}: {
  condition: RuleConditionV2
  horizon: HorizonKey
  scoreOptions: Array<{ value: string; label: string; missing?: boolean }>
  onChange: (next: RuleConditionV2) => void
  onRemove: () => void
}) {
  return (
    <div className="space-y-3 rounded-lg border bg-muted/20 p-3">
      <div className="grid gap-3 md:grid-cols-[1fr_120px]">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">Variable</Label>
            <Select value={condition.variable} onValueChange={(value) => onChange({ ...condition, variable: value as RuleConditionV2["variable"] })}>
              <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {scoreOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Operator</Label>
            <Select value={condition.operator} onValueChange={(value) => onChange({ ...condition, operator: value as RuleConditionV2["operator"] })}>
              <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
              <SelectContent>
                {OPERATOR_OPTIONS.map((option) => (
                  <SelectItem key={option} value={option}>{option}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <Button type="button" variant="outline" size="sm" className="mt-auto gap-1" onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
          Remove
        </Button>
      </div>
      <WfoParamInput
        label="Threshold"
        horizon={horizon}
        param={condition.threshold}
        step={0.1}
        defaultSpaces={ruleThresholdDefaultSearchSpaces(condition.variable, condition.operator, condition.threshold.value)}
        onChange={(nextThreshold) => onChange({ ...condition, threshold: nextThreshold })}
      />
      <p className="text-[11px] text-muted-foreground">{summarizeCondition(condition, horizon)}</p>
    </div>
  )
}

export function ExitRulesTab({ horizon, rules, scoreOptions, preview, errorMessage, onChange }: ExitRulesTabProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Exit Rules</CardTitle>
        <CardDescription>
          Define thesis-based reductions or closures. Risk remains the safety net; exits express strategy logic.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {preview ? (
          <div className="rounded-xl border bg-muted/20 p-4">
            <div className="flex flex-wrap items-center gap-2">
              {Object.entries(preview.score_snapshot).map(([key, value]) => (
                <div key={key} className="rounded-full border bg-background px-2.5 py-1 text-[11px]">
                  <span className="text-muted-foreground">{key}</span>
                  <span className="ml-2 font-medium">{value == null ? "--" : value.toFixed(1)}</span>
                </div>
              ))}
            </div>
            {preview.rules.length > 0 ? (
              <div className="mt-3 space-y-2">
                {preview.rules.map((row) => (
                  <div key={row.id} className="rounded-lg border bg-background px-3 py-2 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium">{row.label}</span>
                      <span className={row.triggered ? "text-green-700" : "text-muted-foreground"}>
                        {row.triggered ? "Triggered" : "Idle"}
                      </span>
                    </div>
                    {row.conditions.length > 0 ? (
                      <p className="mt-1 text-xs text-muted-foreground">{row.conditions.join(" AND ")}</p>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {errorMessage ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            Preview unavailable: {errorMessage}
          </div>
        ) : null}

        {rules.length === 0 ? (
          <div className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
            No exit rules yet. This is allowed, but the strategy will rely entirely on risk controls for exits.
          </div>
        ) : null}

        {rules.map((rule, ruleIndex) => (
          <div key={rule.id} className="space-y-4 rounded-xl border p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="grid flex-1 gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <Label className="text-xs">Label</Label>
                  <Input
                    className="h-8 text-sm"
                    value={rule.label}
                    onChange={(event) => onChange(rules.map((item, index) => index === ruleIndex ? { ...item, label: event.target.value } : item))}
                  />
                </div>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="gap-1"
                onClick={() => onChange(rules.filter((_, index) => index !== ruleIndex))}
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete rule
              </Button>
            </div>

            {rule.rule_expression ? (
              <div className="rounded-lg border bg-muted/20 px-3 py-2 text-sm">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Template expression</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {preview?.rules.find((row) => row.id === rule.id)?.conditions.join(" AND ") || "Advanced price and indicator expression"}
                </div>
              </div>
            ) : null}

            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Conditions</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="gap-1"
                  onClick={() =>
                    onChange(
                      rules.map((item, index) =>
                        index === ruleIndex
                          ? {
                              ...item,
                              rule_expression: null,
                              conditions: [...item.conditions, defaultRuleCondition(item.conditions.length)],
                            }
                          : item,
                      ),
                    )
                  }
                >
                  <Plus className="h-3.5 w-3.5" />
                  Add condition
                </Button>
              </div>

              {rule.conditions.map((condition, conditionIndex) => (
                <ExitConditionEditor
                  key={condition.id}
                  condition={condition}
                  horizon={horizon}
                  scoreOptions={scoreOptions}
                  onChange={(nextCondition) =>
                    onChange(
                      rules.map((item, index) =>
                        index === ruleIndex
                          ? {
                              ...item,
                              conditions: item.conditions.map((current, currentIndex) =>
                                currentIndex === conditionIndex ? nextCondition : current,
                              ),
                            }
                          : item,
                      ),
                    )
                  }
                  onRemove={() =>
                    onChange(
                      rules.map((item, index) =>
                        index === ruleIndex
                          ? {
                              ...item,
                              conditions: item.conditions.filter((_, currentIndex) => currentIndex !== conditionIndex),
                            }
                          : item,
                      ),
                    )
                  }
                />
              ))}
            </div>

            <div className="grid gap-3 lg:grid-cols-2">
              <div className="space-y-1">
                <Label className="text-xs">Sizing mode</Label>
                <Select
                  value={rule.sizing.mode}
                  onValueChange={(value) =>
                    onChange(
                      rules.map((item, index) =>
                        index === ruleIndex
                          ? {
                              ...item,
                              sizing: {
                                ...item.sizing,
                                mode: value as ExitRuleV2["sizing"]["mode"],
                                reduction_pct:
                                  value === "wfo"
                                    ? item.sizing.reduction_pct ?? normalizeWfoParam(
                                        { mode: "wfo", value: item.sizing.manual_pct ?? 100 },
                                        item.sizing.manual_pct ?? 100,
                                        horizon,
                                        directRuleSizingDefaultSearchSpaces(item.sizing.manual_pct ?? 100),
                                      )
                                    : item.sizing.reduction_pct ?? null,
                                kelly_modifier:
                                  value === "kelly_wfo"
                                    ? item.sizing.kelly_modifier ?? normalizeWfoParam(
                                        { mode: "manual", value: 0.5 },
                                        0.5,
                                        horizon,
                                        kellyModifierDefaultSearchSpaces(0.5),
                                      )
                                    : item.sizing.kelly_modifier ?? null,
                              },
                            }
                          : item,
                      ),
                    )
                  }
                >
                  <SelectTrigger className="h-8 text-sm"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manual">Manual % reduction</SelectItem>
                    <SelectItem value="kelly_wfo">Kelly from WFO</SelectItem>
                    <SelectItem value="wfo">WFO reduction</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {rule.sizing.mode === "manual" ? (
                <div className="space-y-1">
                  <Label className="text-xs">Manual reduction (%)</Label>
                  <Input
                    type="number"
                    className="h-8 text-sm"
                    value={rule.sizing.manual_pct ?? 100}
                    min={0}
                    max={100}
                    step={1}
                    onChange={(event) =>
                      onChange(
                        rules.map((item, index) =>
                          index === ruleIndex
                            ? {
                                ...item,
                                sizing: {
                                  ...item.sizing,
                                  manual_pct: Number(event.target.value),
                                },
                              }
                            : item,
                        ),
                      )
                    }
                  />
                </div>
              ) : rule.sizing.mode === "wfo" ? (
                <WfoParamInput
                  label="Reduction (%)"
                  horizon={horizon}
                  param={rule.sizing.reduction_pct ?? normalizeWfoParam(
                    { mode: "wfo", value: rule.sizing.manual_pct ?? 100 },
                    rule.sizing.manual_pct ?? 100,
                    horizon,
                    directRuleSizingDefaultSearchSpaces(rule.sizing.manual_pct ?? 100),
                  )}
                  step={1}
                  min={0}
                  max={100}
                  defaultSpaces={directRuleSizingDefaultSearchSpaces(rule.sizing.manual_pct ?? 100)}
                  onChange={(nextParam) =>
                    onChange(
                      rules.map((item, index) =>
                        index === ruleIndex
                          ? {
                              ...item,
                              sizing: {
                                ...item.sizing,
                                reduction_pct: nextParam,
                              },
                            }
                          : item,
                      ),
                    )
                  }
                />
              ) : (
                <div className="grid gap-3 lg:grid-cols-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Fallback reduction (%)</Label>
                    <Input
                      type="number"
                      className="h-8 text-sm"
                      value={rule.sizing.manual_pct ?? 100}
                      min={0}
                      max={100}
                      step={1}
                      onChange={(event) =>
                        onChange(
                          rules.map((item, index) =>
                            index === ruleIndex
                              ? {
                                  ...item,
                                  sizing: {
                                    ...item.sizing,
                                    manual_pct: Number(event.target.value),
                                  },
                                }
                              : item,
                          ),
                        )
                      }
                    />
                  </div>
                  <WfoParamInput
                    label="Kelly modifier"
                    horizon={horizon}
                    param={rule.sizing.kelly_modifier ?? normalizeWfoParam(
                      { mode: "manual", value: 0.5 },
                      0.5,
                      horizon,
                      kellyModifierDefaultSearchSpaces(0.5),
                    )}
                    step={0.1}
                    min={0}
                    defaultSpaces={kellyModifierDefaultSearchSpaces(rule.sizing.kelly_modifier?.value ?? 0.5)}
                    onChange={(nextParam) =>
                      onChange(
                        rules.map((item, index) =>
                          index === ruleIndex
                            ? {
                                ...item,
                                sizing: {
                                  ...item.sizing,
                                  kelly_modifier: nextParam,
                                },
                              }
                            : item,
                        ),
                      )
                    }
                  />
                </div>
              )}
            </div>
          </div>
        ))}

        <Button
          type="button"
          variant="outline"
          className="gap-2"
          onClick={() => onChange([...rules, defaultExitRule(rules.length)])}
        >
          <Plus className="h-4 w-4" />
          Add exit rule
        </Button>
      </CardContent>
    </Card>
  )
}
