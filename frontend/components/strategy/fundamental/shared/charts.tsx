"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { asNumber, fmtMoney, formatProjectionValue } from "../lib/formatters"
import { ProjectionView, SeriesPoint } from "../lib/types"
import { historicalSeriesFromDriver, projectedValue, projectedYears, projectionSeriesFromDriver, seriesFromRaw, seriesPath, seriesPointPosition, valuationMethods } from "../lib/view-models"

export function FootballField({
  methods,
  currentPrice,
  targetPrice,
}: {
  methods: ReturnType<typeof valuationMethods>
  currentPrice: number | null
  targetPrice: number | null
}) {
  if (!methods.length || currentPrice == null || targetPrice == null) {
    return <div className="fund-empty-small">No usable valuation range.</div>
  }
  const width = 720
  const padLeft = 132
  const padRight = 82
  const rowHeight = 30
  const height = methods.length * rowHeight + 70
  const allValues = methods.flatMap((method) => [method.low, method.high]).concat([currentPrice, targetPrice])
  const minValue = Math.min(...allValues) * 0.94
  const maxValue = Math.max(...allValues) * 1.06
  const x = (value: number) => padLeft + ((value - minValue) / Math.max(1e-9, maxValue - minValue)) * (width - padLeft - padRight)
  const ticks = Array.from({ length: 5 }, (_, index) => minValue + ((maxValue - minValue) / 4) * index)

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="ff-svg" preserveAspectRatio="xMidYMid meet">
      {ticks.map((tick) => (
        <line key={tick} x1={x(tick)} x2={x(tick)} y1={18} y2={height - 32} stroke="var(--line)" strokeWidth="0.5" />
      ))}
      {methods.map((method, index) => {
        const centerY = 28 + index * rowHeight + rowHeight / 2
        const isEnsemble = method.key === "ensemble"
        const color = isEnsemble ? "var(--primary)" : "oklch(0.62 0.08 250)"
        return (
          <g key={method.key}>
            <text x={padLeft - 10} y={centerY + 4} fill="var(--fg2)" fontSize="11" textAnchor="end" fontWeight={isEnsemble ? 700 : 500}>
              {method.method}
            </text>
            <line x1={x(method.low)} x2={x(method.high)} y1={centerY} y2={centerY} stroke={color} strokeWidth={isEnsemble ? 12 : 9} strokeLinecap="round" opacity={isEnsemble ? 0.72 : 0.45} />
            <circle cx={x(method.mid)} cy={centerY} r={isEnsemble ? 5 : 4} fill={color} stroke="var(--card)" strokeWidth="1.5" />
            <text x={x(method.low) - 5} y={centerY + 4} textAnchor="end" fontSize="10" fill="var(--fg3)" fontFamily="var(--font-mono)">
              {fmtMoney(method.low, 0)}
            </text>
            <text x={x(method.high) + 5} y={centerY + 4} textAnchor="start" fontSize="10" fill="var(--fg3)" fontFamily="var(--font-mono)">
              {fmtMoney(method.high, 0)}
            </text>
          </g>
        )
      })}
      <line x1={x(currentPrice)} x2={x(currentPrice)} y1={18} y2={height - 32} stroke="var(--neg)" strokeWidth="1.5" strokeDasharray="4 3" opacity="0.85" />
      <text x={x(currentPrice)} y={14} textAnchor="middle" fontSize="10" fill="var(--neg)" fontWeight="700">
        CP - {fmtMoney(currentPrice, 1)}
      </text>
      <line x1={x(targetPrice)} x2={x(targetPrice)} y1={18} y2={height - 32} stroke="var(--pos)" strokeWidth="2" />
      <text x={x(targetPrice)} y={height - 10} textAnchor="middle" fontSize="10" fill="var(--pos)" fontWeight="700">
        Cible - {fmtMoney(targetPrice, 1)}
      </text>
      {ticks.map((tick) => (
        <text key={`tick-${tick}`} x={x(tick)} y={height - 22} textAnchor="middle" fontSize="9" fill="var(--fg3)" fontFamily="var(--font-mono)">
          {fmtMoney(tick, 0)}
        </text>
      ))}
    </svg>
  )
}


function MiniSeriesChart({
  historical,
  projected,
  format,
}: {
  historical: SeriesPoint[]
  projected: SeriesPoint[]
  format: "pct" | "money" | "number"
}) {
  const width = 320
  const height = 110
  const allPoints = [...historical, ...projected]
  if (!allPoints.length) return <div className="fund-empty-small">Serie indisponible.</div>
  const historicalPath = seriesPath(historical, width, height)
  const projectedPath = seriesPath(projected, width, height)
  const latest = allPoints[allPoints.length - 1]
  return (
    <div className="mini-series">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historique et projection">
        <line x1="8" x2={width - 8} y1={height - 8} y2={height - 8} stroke="var(--line)" />
        {historicalPath ? <path d={historicalPath} fill="none" stroke="var(--fg3)" strokeWidth="2" /> : null}
        {projectedPath ? <path d={projectedPath} fill="none" stroke="var(--primary)" strokeWidth="2.5" strokeDasharray="4 3" /> : null}
        {allPoints.map((point) => {
          const position = seriesPointPosition(point, allPoints, width, height)
          return <circle key={`${point.kind}-${point.year}-${point.value}`} cx={position.x} cy={position.y} r="2.8" fill={point.kind === "projected" ? "var(--primary)" : "var(--fg3)"} />
        })}
      </svg>
      <div className="mini-series-foot">
        <span>Dernier point</span>
        <strong>{formatProjectionValue(latest.value, format)}</strong>
      </div>
    </div>
  )
}


export function DriverEvidenceChart({
  driver,
  label,
  format,
}: {
  driver: Record<string, unknown> | undefined
  label: string
  format: "pct" | "money" | "number"
}) {
  if (!driver || Object.keys(driver).length === 0) return null
  const historical = historicalSeriesFromDriver(driver)
  const projected = projectionSeriesFromDriver(driver)
  const warning = typeof driver.warning === "string" ? driver.warning : null
  const method = typeof driver.method === "string" ? driver.method : ""
  const anchor = asNumber(driver.anchor_value)
  const divergence = asNumber(driver.divergence)
  return (
    <div className="driver-evidence-card">
      <div className="driver-evidence-head">
        <div>
          <span className="valuation-mini-title">{label}</span>
          <p>{method || "Methode non renseignee."}</p>
        </div>
        <span className={cn("signal-conf-badge", warning ? "medium" : "high")}>{warning ? "Alerte" : "OK"}</span>
      </div>
      <MiniSeriesChart historical={historical} projected={projected} format={format} />
      <div className="driver-evidence-stats">
        <span>Ancrage <strong>{formatProjectionValue(anchor, format)}</strong></span>
        <span>Ecart <strong>{formatProjectionValue(divergence, format)}</strong></span>
      </div>
      {warning ? <span className="fund-warning-chip">{warning}</span> : null}
    </div>
  )
}


export function GrowthDecompositionChart({ projection }: { projection: ProjectionView }) {
  const growth = projection.growthDecomposition
  const rows = [
    ["revenue_growth", "CA"],
    ["ebit_growth", "EBIT"],
    ["net_income_growth", "RN"],
    ["fcf_growth", "FCF"],
  ] as const
  const projected = seriesFromRaw(growth.projected_revenue_growth, "projected")
  const hasAny = rows.some(([key]) => seriesFromRaw(growth[key]).length > 0) || projected.length > 0
  if (!hasAny) return null
  return (
    <div className="growth-decomp-grid">
      {rows.map(([key, label]) => {
        const historical = seriesFromRaw(growth[key])
        return (
          <div key={key} className="growth-decomp-item">
            <div className="driver-evidence-head compact">
              <span className="valuation-mini-title">{label}</span>
              <span>{historical.length ? `${historical.length} pts` : "n/a"}</span>
            </div>
            <MiniSeriesChart historical={historical} projected={key === "revenue_growth" ? projected : []} format="pct" />
          </div>
        )
      })}
    </div>
  )
}


export function FcfBridge({ projection, mode }: { projection: ProjectionView; mode: "fcff" | "fcfe" }) {
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  if (!projection.statements.length) return null
  const years = projectedYears(projection)
  const activeYear = selectedYear && years.includes(selectedYear) ? selectedYear : years[0]
  const statement = projection.statements.find((item) => projectedValue(item, "fiscal_year") === activeYear) ?? projection.statements[0]
  const targetKey = mode === "fcfe" ? "fcfe" : "fcff"
  const bridgeRows = [
    ["revenue", "Chiffre d'affaires", projectedValue(statement, "revenue")],
    ["ebit", "EBIT", projectedValue(statement, "ebit")],
    ["nopat", "NOPAT", projectedValue(statement, "nopat")],
    ["reinvestment", "Reinvestissement", projectedValue(statement, "reinvestment")],
    [targetKey, mode.toUpperCase(), projectedValue(statement, targetKey)],
  ] as const
  const maxAbs = Math.max(1, ...bridgeRows.map(([, , value]) => Math.abs(value ?? 0)))
  return (
    <div className="fcf-bridge">
      <div className="driver-evidence-head">
        <div>
          <span className="valuation-mini-title">Pont cash-flow</span>
          <p>{mode === "fcff" ? "CA -> EBIT -> NOPAT - reinvestissement = FCFF." : "CA -> EBIT -> NOPAT - reinvestissement - interets apres impot = FCFE."}</p>
        </div>
        <div className="seg compact">
          {years.map((year) => (
            <button key={year} type="button" className={activeYear === year ? "active" : ""} onClick={() => setSelectedYear(year)}>
              {year}
            </button>
          ))}
        </div>
      </div>
      <div className="fcf-bridge-bars">
        {bridgeRows.map(([key, label, value]) => {
          const width = `${Math.max(4, (Math.abs(value ?? 0) / maxAbs) * 100)}%`
          return (
            <div key={key} className="fcf-bridge-row">
              <span>{label}</span>
              <div className="fcf-bridge-track">
                <div className={cn("fcf-bridge-fill", (value ?? 0) < 0 && "neg")} style={{ width }} />
              </div>
              <strong>{fmtMoney(value, 0)}</strong>
            </div>
          )
        })}
      </div>
    </div>
  )
}

