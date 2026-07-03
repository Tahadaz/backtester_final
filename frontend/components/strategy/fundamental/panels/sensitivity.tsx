"use client"

import {
  type FundamentalSensitivity,
  type FundamentalStockDetail,
  type FundamentalValuationResult,
} from "@/lib/api"
import { Skeleton } from "@/components/ui/skeleton"
import { MODEL_FORMULA_META, MODEL_LABELS } from "../lib/constants"
import { asNumber, asRecord, fmtMoney, fmtPct } from "../lib/formatters"
import { FundCard } from "../shared/cards"
import { SensitivityGridView } from "../lib/types"

function sensitivityGridFromUnknown(value: unknown): SensitivityGridView | null {
  const record = asRecord(value)
  const xs = Array.isArray(record.xs) ? record.xs.map(asNumber).filter((item): item is number => item != null) : []
  const ys = Array.isArray(record.ys) ? record.ys.map(asNumber).filter((item): item is number => item != null) : []
  const matrix = Array.isArray(record.matrix)
    ? record.matrix.map((row) => (Array.isArray(row) ? row.map((item) => asNumber(item)) : []))
    : []
  if (!xs.length || !ys.length || !matrix.length) return null
  return {
    axis_x: typeof record.axis_x === "string" ? record.axis_x : "wacc",
    axis_y: typeof record.axis_y === "string" ? record.axis_y : "terminal_growth",
    xs,
    ys,
    matrix,
    model: typeof record.model === "string" ? record.model : null,
  }
}


function sensitivityGridFromResponse(sensitivity: FundamentalSensitivity | undefined): SensitivityGridView | null {
  return sensitivityGridFromUnknown(sensitivity)
}


function modelUsesSensitivityAxis(row: FundamentalValuationResult, axis: string): boolean {
  const meta = MODEL_FORMULA_META[row.model]
  const keys = new Set(meta?.assumptionKeys ?? Object.keys(asRecord(row.inputs)))
  switch (axis) {
    case "terminal_growth":
      return keys.has("terminal_growth") || keys.has("terminal_growth_firm") || keys.has("terminal_growth_equity")
    case "wacc":
      return keys.has("wacc")
    case "cost_of_equity":
      return keys.has("cost_of_equity")
    case "growth_cap":
      return keys.has("growth_cap")
    default:
      return keys.has(axis)
  }
}


function sensitivityGridHasVariation(grid: SensitivityGridView): boolean {
  const values = grid.matrix.flat().filter((value): value is number => value != null && Number.isFinite(value))
  if (!values.length) return false
  const first = values[0] ?? 0
  return values.some((value) => Math.abs(value - first) > Math.max(1e-6, Math.abs(first) * 1e-8))
}


function sensitivityGridAppliesToModel(row: FundamentalValuationResult, grid: SensitivityGridView): boolean {
  const axes = Array.from(new Set([grid.axis_x, grid.axis_y]))
  return axes.every((axis) => modelUsesSensitivityAxis(row, axis)) && sensitivityGridHasVariation(grid)
}


function modelSensitivityGrid(sensitivity: FundamentalSensitivity | undefined, row: FundamentalValuationResult): SensitivityGridView | null {
  if (!sensitivity) return null
  const grid = sensitivityGridFromUnknown(asRecord(sensitivity.model_grids)[row.model])
  return grid && sensitivityGridAppliesToModel(row, grid) ? grid : null
}


function axisDisplayLabel(axis: string): string {
  switch (axis) {
    case "wacc":
      return "WACC"
    case "terminal_growth":
      return "g terminal"
    case "growth_cap":
      return "plafond croissance"
    case "cost_of_equity":
      return "cout equity"
    default:
      return axis.replaceAll("_", " ")
  }
}


function SensitivityMatrix({ grid, assumptions }: { grid: SensitivityGridView; assumptions: Record<string, unknown> }) {
  const values = grid.matrix.flat().filter((value): value is number => value != null && Number.isFinite(value))
  const min = values.length ? Math.min(...values) : 0
  const max = values.length ? Math.max(...values) : 1
  const baseX = asNumber(assumptions[grid.axis_x])
  const baseY = asNumber(assumptions[grid.axis_y])
  const closestX = baseX == null ? -1 : grid.xs.reduce((best, value, index) => (Math.abs(value - baseX) < Math.abs(grid.xs[best] - baseX) ? index : best), 0)
  const closestY = baseY == null ? -1 : grid.ys.reduce((best, value, index) => (Math.abs(value - baseY) < Math.abs(grid.ys[best] - baseY) ? index : best), 0)

  return (
    <div className="overflow-x-auto">
      <table className="claude-table min-w-[560px]">
        <thead>
          <tr>
            <th>{axisDisplayLabel(grid.axis_y)} \ {axisDisplayLabel(grid.axis_x)}</th>
            {grid.xs.map((x) => (
              <th key={x} className="r">{fmtPct(x, 1, false)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.ys.map((y, rowIndex) => (
            <tr key={y}>
              <td className="font-mono font-semibold">{fmtPct(y, 1, false)}</td>
              {grid.matrix[rowIndex]?.map((value, colIndex) => {
                const pct = value == null || max === min ? 0.5 : (value - min) / (max - min)
                const isBase = rowIndex === closestY && colIndex === closestX
                const bg = isBase ? "oklch(0.94 0.04 260 / 0.55)" : `oklch(${0.55 + pct * 0.18} ${0.04 + pct * 0.14} ${pct >= 0.5 ? 165 : 25} / ${0.08 + pct * 0.30})`
                return (
                  <td key={`${rowIndex}-${colIndex}`} className="r font-mono" style={{ background: bg, color: isBase ? "var(--pri-dim)" : undefined, fontWeight: isBase ? 700 : 500, outline: isBase ? "1.5px solid var(--primary)" : undefined }}>
                    {fmtMoney(value)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


export function SensitivityHeatmap({
  sensitivity,
  grid,
  assumptions,
  isLoading,
  title = "Sensibilite - juste valeur",
}: {
  sensitivity: FundamentalSensitivity | undefined
  grid?: SensitivityGridView | null
  assumptions: Record<string, unknown>
  isLoading: boolean
  title?: string
}) {
  const activeGrid = grid ?? sensitivityGridFromResponse(sensitivity)
  if (isLoading && !activeGrid) {
    return (
      <FundCard title="Sensibilite">
        <div className="grid grid-cols-6 gap-1">
          {Array.from({ length: 36 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      </FundCard>
    )
  }
  if (!activeGrid) return null
  return (
    <div data-capture="sensitivity">
      <FundCard title={title} aside={`${axisDisplayLabel(activeGrid.axis_y)} x ${axisDisplayLabel(activeGrid.axis_x)}`}>
        <SensitivityMatrix grid={activeGrid} assumptions={assumptions} />
      </FundCard>
    </div>
  )
}


export function ModelSensitivityPanel({
  row,
  detail,
  sensitivity,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  sensitivity: FundamentalSensitivity | undefined
}) {
  const grid = modelSensitivityGrid(sensitivity, row)
  if (!grid) return null
  return (
    <div className="model-sensitivity-panel valuation-mini-block" data-capture="sensitivity">
      <div className="driver-evidence-head">
        <span className="valuation-mini-title">Sensibilite modele - {MODEL_LABELS[row.model] ?? row.model}</span>
        <span>{axisDisplayLabel(grid.axis_y)} x {axisDisplayLabel(grid.axis_x)}</span>
      </div>
      <SensitivityMatrix grid={grid} assumptions={detail.assumptions} />
    </div>
  )
}

