"use client"

import { cn } from "@/lib/utils"
import { fmtNumber, formatStoryValue } from "../lib/formatters"
import { StatTile } from "../shared/cards"
import { ModelStory, ModelStoryMetric, ModelStoryStep, ModelStoryTableCell } from "../lib/types"

function StoryMetricGrid({ metrics }: { metrics: ModelStoryMetric[] | undefined }) {
  const visible = (metrics ?? []).filter((metric) => metric.value != null)
  if (!visible.length) return null
  return (
    <div className="model-story-metric-grid">
      {visible.map((metric) => (
        <StatTile
          key={metric.label}
          label={metric.label}
          value={formatStoryValue(metric.value, metric.format)}
          sub={metric.source == null ? undefined : String(metric.source)}
        />
      ))}
    </div>
  )
}


function storyCellKey(cell: ModelStoryTableCell, index: number): string {
  if (cell && typeof cell === "object") return `${index}-${String(cell.value ?? "")}`
  return `${index}-${String(cell ?? "")}`
}


function StoryTable({ table }: { table: ModelStoryStep["table"] }) {
  if (!table || !table.rows.length) return null
  return (
    <div className="model-story-table-wrap">
      <table className="claude-table model-story-table">
        <thead>
          <tr>
            {table.columns.map((column, index) => (
              <th key={`${column}-${index}`} className={index === 0 ? undefined : "r"}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={row.map(storyCellKey).join("|") || rowIndex}>
              {row.map((cell, cellIndex) => {
                const isObject = cell && typeof cell === "object"
                const text = isObject ? formatStoryValue(cell.value, cell.format, cell.digits) : typeof cell === "number" ? fmtNumber(cell, Math.abs(cell) < 10 ? 2 : 0) : cell == null || cell === "" ? "-" : String(cell)
                return (
                  <td key={storyCellKey(cell, cellIndex)} className={cn(cellIndex === 0 ? undefined : "r", cellIndex > 0 && "font-mono")}>
                    {text}
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


export function ModelStoryPanel({ story }: { story: ModelStory }) {
  return (
    <div className="model-story-panel">
      <div className="model-story-head">
        <div>
          <div className="valuation-mini-title">{story.title}</div>
          <p>{story.summary}</p>
        </div>
        <div className="dcf-chip-row">
          {story.checks.map((check) => (
            <span key={check.label} className={cn("dcf-check-chip", check.ok ? "ok" : "warn")}>{check.label}</span>
          ))}
        </div>
      </div>
      <div className="model-story-steps">
        {story.steps.map((step, index) => (
          <div key={`${step.title}-${index}`} className="model-story-step">
            <div className="dcf-step-head">
              <span>{index + 1}</span>
              <div>
                <div className="valuation-mini-title">{step.title}</div>
                <p>{step.description}</p>
              </div>
            </div>
            {step.formula ? (
              <div className="valuation-formula-panel model-story-formula">
                <div className="valuation-formula-eyebrow">Formule</div>
                <div className="valuation-formula-line">{step.formula}</div>
              </div>
            ) : null}
            <StoryMetricGrid metrics={step.metrics} />
            <StoryTable table={step.table} />
          </div>
        ))}
      </div>
    </div>
  )
}

