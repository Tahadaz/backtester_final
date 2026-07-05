"use client"

import type { ReactNode } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { asNumber, fmtNumber, fmtPct, formatModelScalar, formatNestedModelValue, recommendationClass, recommendationLabel, scoreClass, valueLabel } from "../lib/formatters"
import { ModelValueItem, Recommendation, StatementEvidenceGroup } from "../lib/types"

export function revisionArrow(direction: string | null | undefined): ReactNode {
  if (direction === "up") return <span className="t-pos">^</span>
  if (direction === "down") return <span className="t-neg">v</span>
  return <span className="text-muted-foreground">-</span>
}


function thresholdLabel(value: unknown, fallback: string): string {
  const numberValue = asNumber(value)
  return numberValue == null ? fallback : fmtPct(numberValue, 0, true)
}


export function recommendationTooltip(assumptions?: Record<string, unknown> | null): string {
  const buy = thresholdLabel(assumptions?.rating_buy_excess_return, "-")
  const accumulate = thresholdLabel(assumptions?.rating_accumulate_excess_return, "-")
  const reduce = thresholdLabel(assumptions?.rating_reduce_excess_return, "-")
  const sell = thresholdLabel(assumptions?.rating_sell_excess_return, "-")
  return `Rendement excédentaire vs coût des fonds propres : ≥ ${buy} Acheter, ≥ ${accumulate} Accumuler, ≥ ${reduce} Conserver, ≥ ${sell} Alléger, sinon Vendre. NR si la couverture, la confiance, l'accord des modèles ou la vérification des données ne passent pas.`
}


export function RecChip({ value, assumptions }: { value: Recommendation | null | undefined; assumptions?: Record<string, unknown> | null }) {
  return (
    <span className={cn("fund-rec-chip", recommendationClass(value))} title={recommendationTooltip(assumptions)}>
      {recommendationLabel(value)}
    </span>
  )
}


export function ScoreChip({ value }: { value: number | null | undefined }) {
  return <span className={cn("font-mono text-[11px] font-bold", scoreClass(value))}>{fmtNumber(value, 0)}</span>
}


export function ScorePair({ valueScore, qualityScore }: { valueScore: number | null | undefined; qualityScore: number | null | undefined }) {
  return (
    <span className="inline-flex justify-end gap-1 font-mono text-[10px] font-bold">
      <span className={scoreClass(valueScore)}>V {fmtNumber(valueScore, 0)}</span>
      <span className={scoreClass(qualityScore)}>Q {fmtNumber(qualityScore, 0)}</span>
    </span>
  )
}


export function LoadingRows() {
  return (
    <>
      {Array.from({ length: 10 }).map((_, index) => (
        <tr key={index}>
          <td colSpan={5}>
            <Skeleton className="h-7 w-full" />
          </td>
        </tr>
      ))}
    </>
  )
}


export function FundCard({ title, aside, children, className, id }: { title: ReactNode; aside?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <div id={id} className={cn("fund-card", className)}>
      <div className="fund-card-hdr">
        <span className="fund-card-title">{title}</span>
        {aside ? <span className="fund-card-aside">{aside}</span> : null}
      </div>
      <div className="fund-card-body">{children}</div>
    </div>
  )
}


export function StatTile({ label, value, sub, tone }: { label: ReactNode; value: string; sub?: ReactNode; tone?: string }) {
  return (
    <div className="fund-stat">
      <span className="lbl">{label}</span>
      <span className={cn("val", tone)}>{value}</span>
      {sub ? <span className="sub">{sub}</span> : null}
    </div>
  )
}


function ValuePreview({ itemKey, value }: { itemKey: string; value: unknown }) {
  if (value == null) return <span className="text-muted-foreground">-</span>
  if (typeof value === "number") return <span className="font-mono">{formatModelScalar(itemKey, value)}</span>
  if (typeof value === "string" || typeof value === "boolean") return <span>{String(value)}</span>
  if (Array.isArray(value)) {
    const preview = value.slice(0, 5).map((item, index) => {
      if (typeof item === "number") return `Y${index + 1} ${formatModelScalar(itemKey, item)}`
      if (item && typeof item === "object") return JSON.stringify(item)
      return String(item)
    })
    return (
      <code className="fund-code">
        {preview.join(" | ")}
        {value.length > preview.length ? " | ..." : ""}
      </code>
    )
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).slice(0, 5)
    return (
      <span className="valuation-object-preview">
        {entries.map(([key, item]) => (
          <span key={key} className="valuation-object-chip">
            <strong>{valueLabel(key)}</strong>
            <em>{formatNestedModelValue(key, item)}</em>
          </span>
        ))}
        {Object.keys(value as Record<string, unknown>).length > entries.length ? " | ..." : ""}
      </span>
    )
  }
  return <span>{String(value)}</span>
}


export function ModelValueGrid({ title, items, empty }: { title: string; items: ModelValueItem[]; empty: string }) {
  return (
    <div className="valuation-mini-block">
      <div className="valuation-mini-title">{title}</div>
      {items.length ? (
        <div className="valuation-kv-list">
          {items.map((item) => (
            <div key={item.key} className="valuation-kv-row">
              <span className="valuation-kv-label">
                {item.label}
                {item.source ? <em>{item.source}</em> : null}
              </span>
              <span className="valuation-kv-value">
                <ValuePreview itemKey={item.key} value={item.value} />
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="valuation-empty-line">{empty}</div>
      )}
    </div>
  )
}


export function StatementEvidenceCard({ group }: { group: StatementEvidenceGroup }) {
  return (
    <div className="valuation-statement-card">
      <div className="valuation-statement-title">{group.title}</div>
      {group.items.length ? (
        <div className="valuation-statement-list">
          {group.items.map((item) => (
            <div key={item.key} className="valuation-statement-row">
              <span>
                <strong>{item.label}</strong>
                <em>{item.sourceMetric ? `${item.sourceMetric} - ${item.periodLabel}` : item.periodLabel}</em>
              </span>
              <b>{item.formatted}</b>
            </div>
          ))}
        </div>
      ) : (
        <div className="valuation-empty-line">No usable statement line.</div>
      )}
    </div>
  )
}
