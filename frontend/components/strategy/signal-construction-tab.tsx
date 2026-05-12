"use client"

import { Plus, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { HorizonSelector } from "@/components/strategy/horizon-selector"
import { INDICATOR_FAMILY_ORDER, INDICATOR_META_BY_KEY } from "@/components/strategy/indicator-config"
import { SignalZoneChart } from "@/components/strategy/signal-zone-chart"
import { WfoParamInput } from "@/components/strategy/wfo-param-input"
import type { ActiveScoreChip, ConstructedSignalChart } from "@/lib/api"
import {
  FAMILY_SCORE_KEYS,
  defaultIndicatorRowConfig,
  nextScoreKey,
  signalConstructionDefaultSearchSpaces,
  type FamilyId,
  type FamilyConfigV2,
  type HorizonKey,
  type IndicatorRowConfigV2,
  type StockStrategyConfigV2,
} from "@/lib/strategy-v2"

interface SignalConstructionTabProps {
  horizon: HorizonKey
  onHorizonChange: (horizon: HorizonKey) => void
  stockConfig: StockStrategyConfigV2
  activeScores?: ActiveScoreChip[]
  zoneChart?: ConstructedSignalChart | null
  isLoading?: boolean
  isRefreshing?: boolean
  previewRenderKey?: string
  errorMessage?: string | null
  familyHistoryMode?: "static_current_reps" | "dynamic_point_in_time"
  onFamilyHistoryModeChange?: (mode: "static_current_reps" | "dynamic_point_in_time") => void
  onChange: (next: StockStrategyConfigV2["signal_construction"]) => void
}

function SourceModePill({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={active
        ? "rounded-full border border-primary bg-primary px-3 py-1 text-[11px] font-medium text-primary-foreground"
        : "rounded-full border bg-background px-3 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground"}
    >
      {children}
    </button>
  )
}

function IndicatorRowEditor({
  familyId,
  row,
  rowIndex,
  horizon,
  onChange,
  onRemove,
}: {
  familyId: FamilyId
  row: IndicatorRowConfigV2
  rowIndex: number
  horizon: HorizonKey
  onChange: (next: IndicatorRowConfigV2) => void
  onRemove: () => void
}) {
  const meta = INDICATOR_META_BY_KEY[familyId]
  return (
    <div className="space-y-3 rounded-xl border bg-muted/10 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <Checkbox
            checked={row.enabled}
            onCheckedChange={(checked) => onChange({ ...row, enabled: Boolean(checked) })}
            className="mt-1"
          />
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className="font-mono text-[10px]">{row.score_key}</Badge>
              <span className="text-xs text-muted-foreground">Row {rowIndex + 1}</span>
            </div>
            <Input
              className="h-8 w-[220px] text-sm"
              value={row.label}
              onChange={(event) => onChange({ ...row, label: event.target.value })}
            />
          </div>
        </div>
        <Button type="button" variant="outline" size="sm" className="gap-1" onClick={onRemove}>
          <Trash2 className="h-3.5 w-3.5" />
          Remove
        </Button>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        {Object.entries(row.params).map(([paramName, param]) => {
          const paramMeta = meta.params.find((item) =>
            item.key === paramName || (familyId === "sma" && item.key === "period" && paramName === "window")
          )
          return (
            <WfoParamInput
              key={`${row.id}-${paramName}`}
              label={paramMeta?.label ?? paramName}
              horizon={horizon}
              param={param}
              step={paramMeta?.step ?? (Number.isInteger(param.value) ? 1 : 0.1)}
              defaultSpaces={signalConstructionDefaultSearchSpaces(familyId, paramName, param.value)}
              onChange={(nextParam) =>
                onChange({
                  ...row,
                  params: {
                    ...row.params,
                    [paramName]: nextParam,
                  },
                })
              }
            />
          )
        })}
      </div>
    </div>
  )
}

export function SignalConstructionTab({
  horizon,
  onHorizonChange,
  stockConfig,
  activeScores,
  zoneChart,
  isLoading,
  isRefreshing,
  previewRenderKey,
  errorMessage,
  familyHistoryMode = "static_current_reps",
  onFamilyHistoryModeChange,
  onChange,
}: SignalConstructionTabProps) {
  const families = stockConfig.signal_construction.families
  const familyIds = INDICATOR_FAMILY_ORDER.filter((familyId) => Boolean(families[familyId]))
  const chartSources = zoneChart?.sources ?? []

  function updateFamily(familyId: FamilyId, patch: Partial<FamilyConfigV2>) {
    onChange({
      families: {
        ...families,
        [familyId]: {
          ...families[familyId],
          ...patch,
        },
      },
    })
  }

  function updateRow(familyId: FamilyId, rowId: string, updater: (row: IndicatorRowConfigV2) => IndicatorRowConfigV2) {
    const family = families[familyId]
    updateFamily(familyId, {
      rows: family.rows.map((row) => row.id === rowId ? updater(row) : row),
    })
  }

  function addRow(familyId: FamilyId) {
    const family = families[familyId]
    const existingKeys = family.rows.map((row) => row.score_key)
    const scoreKey = nextScoreKey(familyId, existingKeys)
    const row = defaultIndicatorRowConfig(familyId, family.rows.length, scoreKey)
    row.id = `${familyId}_row_${family.rows.length + 1}_${Date.now()}`
    row.label = scoreKey === row.score_key ? row.label : scoreKey.replace(/_/g, " ")
    updateFamily(familyId, { source_mode: "indicator_rows", rows: [...family.rows, row] })
  }

  function removeRow(familyId: FamilyId, rowId: string) {
    const family = families[familyId]
    updateFamily(familyId, { rows: family.rows.filter((row) => row.id !== rowId) })
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-base">Signal Construction</CardTitle>
            <CardDescription>
              Choose whether each family uses the Signals-page family score or a specific parameterized setup. The chart previews the active sources only.
            </CardDescription>
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Strategy horizon</Label>
            <HorizonSelector value={horizon} onChange={(value) => onHorizonChange(value as HorizonKey)} />
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {activeScores && activeScores.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            {activeScores.map((item) => (
              <div key={item.score_key} className="rounded-full border bg-background px-3 py-1.5 text-[11px]">
                <span className="text-muted-foreground">{item.label}</span>
                <span className="ml-2 font-medium">{item.score == null ? "--" : item.score.toFixed(1)}</span>
                {item.signal_label ? <span className="ml-2 text-muted-foreground">{item.signal_label}</span> : null}
              </div>
            ))}
          </div>
        ) : null}

        <div className="rounded-xl border bg-muted/10 px-3 py-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-medium">Family History Mode</p>
              <p className="text-[11px] text-muted-foreground">
                Static reuses today's representative set for all past bars; point-in-time reselects representatives at each close.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <SourceModePill
                active={familyHistoryMode === "static_current_reps"}
                onClick={() => onFamilyHistoryModeChange?.("static_current_reps")}
              >
                Static reps
              </SourceModePill>
              <SourceModePill
                active={familyHistoryMode === "dynamic_point_in_time"}
                onClick={() => onFamilyHistoryModeChange?.("dynamic_point_in_time")}
              >
                Point-in-time reps
              </SourceModePill>
            </div>
          </div>
        </div>

        <SignalZoneChart
          key={previewRenderKey ?? `${stockConfig.strategy_type}-${horizon}`}
          data={zoneChart}
          enabledFamilies={(Object.keys(families) as FamilyId[]).filter((familyId) => Boolean(families[familyId]?.enabled))}
          isLoading={Boolean(isLoading)}
          isRefreshing={Boolean(isRefreshing)}
          errorMessage={errorMessage}
          height={340}
        />

        <div className="grid gap-4">
          {familyIds.map((familyId) => {
            const family = families[familyId]
            const meta = INDICATOR_META_BY_KEY[familyId]
            const enabledRows = family.rows.filter((row) => row.enabled)
            const activeScoreKeys = family.source_mode === "family_ensemble"
              ? [FAMILY_SCORE_KEYS[familyId]]
              : enabledRows.map((row) => row.score_key)
            const familyChartSources = chartSources.filter((source) => source.family === familyId)
            const familyWfoActive = family.source_mode === "indicator_rows" && (
              familyChartSources.some((source) => source.wfo_range_active)
                || enabledRows.some((row) => Object.values(row.params).some((param) => param.mode === "wfo"))
            )
            const sourceModeLabel = familyChartSources[0]?.source_mode_label
              ?? (family.source_mode === "family_ensemble" ? "Family score" : familyWfoActive ? "WFO range" : "Specific setup")
            const sourceSummary = familyChartSources.length > 0
              ? familyChartSources.map((source) => {
                if (source.source_kind === "family_ensemble") {
                  const topReps = source.representatives.slice(0, 3).map((rep) => `${rep.label} (${(rep.weight * 100).toFixed(0)}%)`)
                  return topReps.length > 0 ? `Representatives: ${topReps.join(" · ")}` : "Representatives will render from the family ensemble."
                }
                if (source.wfo_range_active) {
                  const startName = String(source.wfo_start_indicator?.name ?? "Start")
                  const endName = String(source.wfo_end_indicator?.name ?? "End")
                  return `WFO range: ${startName} -> ${endName}`
                }
                return source.indicator?.name ? `Indicator: ${String(source.indicator.name)}` : "Indicator preview follows the active row."
              }).join(" | ")
              : family.source_mode === "family_ensemble"
                ? "Preview renders the representative family variants for this stock and horizon."
                : familyWfoActive
                  ? "Preview renders the WFO start/end variants with a light range band."
                  : "Preview renders the active indicator row with its current parameters."
            return (
              <div key={familyId} className="rounded-xl border p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <Checkbox
                      checked={family.enabled}
                      onCheckedChange={(checked) => updateFamily(familyId, { enabled: Boolean(checked) })}
                      className="mt-1"
                    />
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-semibold">{meta.shortLabel}</p>
                        <Badge variant={family.enabled ? "default" : "outline"}>
                          {family.enabled ? "Active" : "Off"}
                        </Badge>
                        <Badge variant="outline">{meta.category}</Badge>
                        <Badge variant="outline">{sourceModeLabel}</Badge>
                        {familyWfoActive ? <Badge variant="outline">WFO preview</Badge> : null}
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">{meta.description}</p>
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        <span className="text-[11px] text-muted-foreground">Rule score keys:</span>
                        {activeScoreKeys.length > 0 ? activeScoreKeys.map((scoreKey) => (
                          <Badge key={`${familyId}-${scoreKey}`} variant="secondary" className="font-mono text-[10px]">
                            {scoreKey}
                          </Badge>
                        )) : (
                          <span className="text-[11px] text-muted-foreground">No active score key</span>
                        )}
                      </div>
                      <p className="mt-2 text-[11px] text-muted-foreground">{sourceSummary}</p>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <SourceModePill
                      active={family.source_mode === "family_ensemble"}
                      onClick={() => updateFamily(familyId, { source_mode: "family_ensemble" })}
                    >
                      Family score
                    </SourceModePill>
                    <SourceModePill
                      active={family.source_mode === "indicator_rows"}
                      onClick={() => updateFamily(familyId, { source_mode: "indicator_rows" })}
                    >
                      Specific setup
                    </SourceModePill>
                  </div>
                </div>

                {family.source_mode === "family_ensemble" ? (
                  <div className="mt-4 rounded-xl border bg-muted/10 p-4 text-sm text-muted-foreground">
                    This family uses the Signals-page family ensemble score directly, and rules read from the base family score key shown above.
                  </div>
                ) : (
                  <div className="mt-4 space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Indicator Rows</p>
                      <Button type="button" variant="outline" size="sm" className="gap-1" onClick={() => addRow(familyId)}>
                        <Plus className="h-3.5 w-3.5" />
                        Add row
                      </Button>
                    </div>
                    {family.rows.length === 0 ? (
                      <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                        No rows yet. Add a setup to create a score for this family.
                      </div>
                    ) : (
                      family.rows.map((row, index) => (
                        <IndicatorRowEditor
                          key={row.id}
                          familyId={familyId}
                          row={row}
                          rowIndex={index}
                          horizon={horizon}
                          onChange={(nextRow) => updateRow(familyId, row.id, () => nextRow)}
                          onRemove={() => removeRow(familyId, row.id)}
                        />
                      ))
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
