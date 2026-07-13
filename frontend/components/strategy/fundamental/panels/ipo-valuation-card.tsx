"use client"

import { useEffect, useMemo, useState } from "react"
import type { CSSProperties, ReactNode } from "react"
import { cn } from "@/lib/utils"
import { fmtMoney, fmtNumber, fmtPct, fmtRatio } from "../lib/formatters"
import { FundCard, StatTile } from "../shared/cards"
import { IPO_T2S, type IpoPeer } from "../lib/ipo-data"
import type { IpoProfile, IpoProfileMeta, IpoSubscriptionSettings } from "../lib/ipo-store"
import {
  buildScenarioInputs,
  compsEvEbeFairValue,
  compsPeFairValue,
  computeDcf,
  recomputeIpoPeerStats,
  sensitivityGrid,
  type IpoDcfInputs,
  type IpoDcfResult,
  type IpoScenarioKey,
  type SensitivityAxis,
} from "../lib/ipo-model"
import { IPO_JOINT_PRESETS } from "../lib/ipo-subscription"
import { IpoSubscriptionPanel } from "./ipo-subscription-panel"

// ---------------------------------------------------------------------------
// Pure helpers: immutable updates + percent<->decimal parsing for inputs.
// ---------------------------------------------------------------------------

type ArrayField = "revenueGrowth" | "ebeMargin" | "taxPctRev" | "bfrPctRev" | "capexPctRev"

function withArrayValue(inputs: IpoDcfInputs, field: ArrayField, index: number, value: number): IpoDcfInputs {
  const next = inputs[field].slice()
  next[index] = value
  return { ...inputs, [field]: next }
}

function withScalar<K extends keyof IpoDcfInputs>(inputs: IpoDcfInputs, field: K, value: IpoDcfInputs[K]): IpoDcfInputs {
  return { ...inputs, [field]: value }
}

function parsePercent(raw: string): number {
  if (raw.trim() === "") return 0
  const n = Number(raw)
  return Number.isFinite(n) ? n / 100 : 0
}

function parseNumberInput(raw: string): number {
  if (raw.trim() === "") return 0
  const n = Number(raw)
  return Number.isFinite(n) ? n : 0
}

function parseNullableNumberInput(raw: string): number | null {
  if (raw.trim() === "") return null
  const n = Number(raw)
  return Number.isFinite(n) ? n : null
}

function pctDisplay(value: number, digits = 2): number {
  return Number.isFinite(value) ? Number((value * 100).toFixed(digits)) : 0
}

function clonePeers(rows: readonly IpoPeer[]): IpoPeer[] {
  return rows.map((row) => ({ ...row }))
}

function createBlankPeer(): IpoPeer {
  return {
    name: "Nouveau peer",
    country: "",
    marketCapMusd: 0,
    evEbe2026e: null,
    evEbe2027p: null,
    pe2026e: null,
    pe2027p: null,
    category: "custom",
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function buildDefaultSubscriptionSettings(): IpoSubscriptionSettings {
  return {
    version: 5,
    capitalMad: 500_000,
    tranche: "retail",
    financingRate: 0.03,
    blockedDays: IPO_T2S.meta.defaultBlockedDays,
    retailCoverageRate: 1.0,
    institCoverageRate: 0.0,
    exitDays: 5,
    scenarios: IPO_JOINT_PRESETS.map((scenario) => ({ ...scenario, pops: scenario.pops.map((pop) => ({ ...pop })) })),
  }
}

const SCENARIO_LABELS: Record<IpoScenarioKey, string> = {
  bear: "Prudent",
  base: "Base prospectus",
  bull: "Optimiste",
}

const AXIS_LABELS: Record<SensitivityAxis, string> = {
  wacc: "WACC",
  terminalGrowth: "Croissance terminale (g)",
  terminalEbeMargin: "Marge EBE terminale",
  revenueGrowthShift: "Decalage croissance CA",
}

const AXIS_OPTIONS: SensitivityAxis[] = ["wacc", "terminalGrowth", "terminalEbeMargin", "revenueGrowthShift"]

const DEFAULT_EV_EBE_MULTIPLE = IPO_T2S.peerStats.mean.evEbe2026e ?? 0
const DEFAULT_PE_MULTIPLE = IPO_T2S.peerStats.mean.pe2026e ?? 0

function axisBaseValue(inputs: IpoDcfInputs, axis: SensitivityAxis): number {
  if (axis === "revenueGrowthShift") return 0
  return inputs[axis]
}

function axisRange(inputs: IpoDcfInputs, axis: SensitivityAxis): number[] {
  const base = axisBaseValue(inputs, axis)
  if (axis === "wacc") return [-1, -0.5, 0, 0.5, 1].map((d) => base + d / 100)
  if (axis === "terminalGrowth") return [-0.5, -0.25, 0, 0.25, 0.5].map((d) => base + d / 100)
  if (axis === "terminalEbeMargin") return [-2, -1, 0, 1, 2].map((d) => base + d / 100)
  return [-4, -2, 0, 2, 4].map((d) => d / 100)
}

function axisFormat(axis: SensitivityAxis, value: number): string {
  if (!Number.isFinite(value)) return "-"
  if (axis === "revenueGrowthShift") return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}pp`
  const digits = axis === "wacc" || axis === "terminalGrowth" ? 2 : 1
  return fmtPct(value, digits, false)
}

function sensCellStyle(upside: number): CSSProperties {
  if (!Number.isFinite(upside)) return {}
  const magnitude = Math.min(1, Math.abs(upside) / 0.5)
  const alpha = 0.08 + magnitude * 0.22
  return upside >= 0 ? { backgroundColor: `rgba(34,197,94,${alpha})` } : { backgroundColor: `rgba(239,68,68,${alpha})` }
}

// ---------------------------------------------------------------------------
// Small input primitives
// ---------------------------------------------------------------------------

function PercentInput({ value, onChange, step = 0.1 }: { value: number; onChange: (v: number) => void; step?: number }) {
  const display = String(pctDisplay(value))
  const [draft, setDraft] = useState(display)
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    if (!focused) setDraft(display)
  }, [display, focused])

  return (
    <div className="relative">
      <input
        type="number"
        step={step}
        className="h-8 w-full rounded-md border border-line bg-card px-2 pr-4 text-right text-[11px] font-mono outline-none focus-visible:ring-1 focus-visible:ring-ring"
        value={focused ? draft : display}
        onFocus={() => {
          setFocused(true)
          setDraft(display)
        }}
        onChange={(event) => {
          const next = event.target.value
          setDraft(next)
          if (next.trim() !== "") onChange(parsePercent(next))
        }}
        onBlur={() => {
          setFocused(false)
          setDraft(display)
        }}
      />
      <span className="pointer-events-none absolute right-1 top-1/2 -translate-y-1/2 text-[9px] text-muted-foreground">%</span>
    </div>
  )
}

function NumberField({
  value,
  onChange,
  step = 1,
  className,
}: {
  value: number
  onChange: (v: number) => void
  step?: number
  className?: string
}) {
  const display = Number.isFinite(value) ? String(value) : "0"
  const [draft, setDraft] = useState(display)
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    if (!focused) setDraft(display)
  }, [display, focused])

  return (
    <input
      type="number"
      step={step}
      className={cn(
        "h-8 w-full rounded-md border border-line bg-card px-2 text-right text-[11px] font-mono outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
      value={focused ? draft : display}
      onFocus={() => {
        setFocused(true)
        setDraft(display)
      }}
      onChange={(event) => {
        const next = event.target.value
        setDraft(next)
        if (next.trim() !== "") onChange(parseNumberInput(next))
      }}
      onBlur={() => {
        setFocused(false)
        setDraft(display)
      }}
    />
  )
}

function NullableNumberField({
  value,
  onChange,
  step = 1,
  className,
}: {
  value: number | null
  onChange: (v: number | null) => void
  step?: number
  className?: string
}) {
  const display = value == null ? "" : String(value)
  const [draft, setDraft] = useState(display)
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    if (!focused) setDraft(display)
  }, [display, focused])

  return (
    <input
      type="number"
      step={step}
      className={cn(
        "h-8 w-full rounded-md border border-line bg-card px-2 text-right text-[11px] font-mono outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
      value={focused ? draft : display}
      onFocus={() => {
        setFocused(true)
        setDraft(display)
      }}
      onChange={(event) => {
        const next = event.target.value
        setDraft(next)
        onChange(parseNullableNumberInput(next))
      }}
      onBlur={() => {
        setFocused(false)
        setDraft(display)
      }}
    />
  )
}

function TextField({ value, onChange, className }: { value: string; onChange: (v: string) => void; className?: string }) {
  return (
    <input
      type="text"
      className={cn("h-8 w-full rounded-md border border-line bg-card px-2 text-[11px] outline-none focus-visible:ring-1 focus-visible:ring-ring", className)}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function isDirtyNum(a: number, b: number, eps = 1e-9): boolean {
  return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) > eps
}

function ResetIcon({ onClick, title = "Reinitialiser ce champ" }: { onClick: () => void; title?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full border border-amber-400/60 bg-amber-500/10 text-[8px] leading-none text-amber-600 hover:bg-amber-500/25 dark:text-amber-400"
    >
      ↺
    </button>
  )
}

function Field({
  label,
  children,
  dirty,
  onReset,
}: {
  label: string
  children: ReactNode
  dirty?: boolean
  onReset?: () => void
}) {
  return (
    <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
      <span className="flex items-center gap-1">
        {label}
        {dirty && onReset ? <ResetIcon onClick={onReset} /> : null}
      </span>
      {children}
    </label>
  )
}

// ---------------------------------------------------------------------------
// Driver / advanced tables
// ---------------------------------------------------------------------------

function AnchorRevenueInput({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const display = Number.isFinite(value) ? String(value) : "0"
  const [draft, setDraft] = useState(display)
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    if (!focused) setDraft(display)
  }, [display, focused])

  return (
    <input
      type="number"
      step={1}
      className="h-8 w-24 rounded-md border-2 border-primary/40 bg-primary/5 px-2 text-right text-[11px] font-mono font-semibold text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
      value={focused ? draft : display}
      onFocus={() => {
        setFocused(true)
        setDraft(display)
      }}
      onChange={(event) => {
        const next = event.target.value
        setDraft(next)
        if (next.trim() !== "") {
          const n = Number(next)
          if (Number.isFinite(n)) onChange(n)
        }
      }}
      onBlur={() => {
        setFocused(false)
        setDraft(display)
      }}
    />
  )
}

function DriverTable({
  inputs,
  baseline,
  dcf,
  meta,
  historicalRevenue,
  baselineHistoricalRevenue,
  onArrayChange,
  onRevenueBaseChange,
  onHistoricalRevenueChange,
  onResetArrayField,
  onResetHistoricalAndAnchor,
}: {
  inputs: IpoDcfInputs
  baseline: IpoDcfInputs
  dcf: IpoDcfResult
  meta: IpoProfileMeta
  historicalRevenue: number[]
  baselineHistoricalRevenue: number[]
  onArrayChange: (field: ArrayField, index: number, value: number) => void
  onRevenueBaseChange: (value: number) => void
  onHistoricalRevenueChange: (index: number, value: number) => void
  onResetArrayField: (field: ArrayField) => void
  onResetHistoricalAndAnchor: () => void
}) {
  const anchorEbeMarginText =
    meta.lastActualEbe != null && meta.lastActualRevenue > 0 ? fmtPct(meta.lastActualEbe / meta.lastActualRevenue, 1, false) : "n.d."
  const revenueGrowthDirty = inputs.revenueGrowth.some((v, i) => isDirtyNum(v, baseline.revenueGrowth[i]))
  const ebeMarginDirty = inputs.ebeMargin.some((v, i) => isDirtyNum(v, baseline.ebeMargin[i]))
  // Full CA chain: historical actuals (oldest first) followed by the last-actual-year anchor.
  // Growth for a given column is derived from the previous column's revenue - editing either
  // the growth cell or the CA cell keeps the chain consistent (no separately stored growth state).
  const chainRevenues = [...historicalRevenue, inputs.revenueBase]
  const chainDirty =
    historicalRevenue.some((v, i) => isDirtyNum(v, baselineHistoricalRevenue[i])) || isDirtyNum(inputs.revenueBase, baseline.revenueBase)

  function setChainRevenue(index: number, value: number) {
    if (index === chainRevenues.length - 1) onRevenueBaseChange(value)
    else onHistoricalRevenueChange(index, value)
  }

  return (
    <div className="overflow-x-auto">
      <table className="claude-table">
        <thead>
          <tr>
            <th>Poste</th>
            {meta.priorActualYears.map((py) => (
              <th key={py.year} className="r text-muted-foreground">{py.year} (reel)</th>
            ))}
            <th className="r">{meta.lastActualYear} (reel)</th>
            {inputs.years.map((year) => (
              <th key={year} className="r">{year}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <span className="inline-flex items-center gap-1">
                Croissance CA (%)
                {revenueGrowthDirty ? <ResetIcon onClick={() => onResetArrayField("revenueGrowth")} title="Reinitialiser cette ligne" /> : null}
              </span>
            </td>
            {chainRevenues.map((rev, i) => {
              if (i === 0) return <td key={`chain-g-${i}`} className="r text-muted-foreground">-</td>
              const prev = chainRevenues[i - 1]
              const growth = prev > 0 ? rev / prev - 1 : NaN
              return (
                <td key={`chain-g-${i}`} className="r">
                  <PercentInput
                    value={Number.isFinite(growth) ? growth : 0}
                    onChange={(g) => setChainRevenue(i, prev * (1 + g))}
                  />
                </td>
              )
            })}
            {inputs.revenueGrowth.map((g, i) => (
              <td key={inputs.years[i]} className="r">
                <PercentInput value={g} onChange={(v) => onArrayChange("revenueGrowth", i, v)} />
              </td>
            ))}
          </tr>
          <tr>
            <td>
              <span className="inline-flex items-center gap-1">
                Marge d&apos;EBE (%)
                {ebeMarginDirty ? <ResetIcon onClick={() => onResetArrayField("ebeMargin")} title="Reinitialiser cette ligne" /> : null}
              </span>
            </td>
            {meta.priorActualYears.map((py) => (
              <td key={py.year} className="r text-muted-foreground">
                {py.ebe != null && py.revenue > 0 ? fmtPct(py.ebe / py.revenue, 1, false) : "n.d."}
              </td>
            ))}
            <td className="r text-muted-foreground">{anchorEbeMarginText}</td>
            {inputs.ebeMargin.map((m, i) => (
              <td key={inputs.years[i]} className="r">
                <PercentInput value={m} onChange={(v) => onArrayChange("ebeMargin", i, v)} />
              </td>
            ))}
          </tr>
          <tr className="text-muted-foreground">
            <td>
              <span className="inline-flex items-center gap-1">
                CA (MMAD)
                {chainDirty ? <ResetIcon onClick={onResetHistoricalAndAnchor} title="Reinitialiser l'historique et l'exercice de reference" /> : null}
              </span>
            </td>
            {chainRevenues.map((rev, i) => (
              <td key={`chain-ca-${i}`} className="r">
                <AnchorRevenueInput value={rev} onChange={(v) => setChainRevenue(i, v)} />
              </td>
            ))}
            {dcf.rows.map((row) => (
              <td key={row.year} className="r font-mono">{fmtMoney(row.revenue, 0)}</td>
            ))}
          </tr>
          <tr className="text-muted-foreground">
            <td>FCFF (MMAD)</td>
            {meta.priorActualYears.map((py) => (
              <td
                key={py.year}
                className="r font-mono"
                title={py.fcff == null ? "Non détaillé à ce niveau de granularité pour cet exercice" : undefined}
              >
                {py.fcff != null ? fmtMoney(py.fcff, 0) : "n.d."}
              </td>
            ))}
            <td
              className="r font-mono"
              title={meta.lastActualFcff == null ? "Non détaillé à ce niveau de granularité pour l'exercice de référence" : undefined}
            >
              {meta.lastActualFcff != null ? fmtMoney(meta.lastActualFcff, 0) : "n.d."}
            </td>
            {dcf.rows.map((row) => (
              <td key={row.year} className={cn("r font-mono", row.fcff < 0 && "t-neg")}>{fmtMoney(row.fcff, 0)}</td>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="mt-1.5 text-[10px] text-muted-foreground">
        Chaque exercice reel ({meta.priorActualYears[0]?.year ?? meta.lastActualYear} a {meta.lastActualYear}) est modifiable directement en CA, ou via sa croissance
        (qui recalcule alors le CA de cet exercice a partir du precedent). L&apos;exercice de reference {meta.lastActualYear} alimente ensuite toute la trajectoire
        prevue ({inputs.years[0] ?? ""}+) par croissance multiplicative.
      </p>
    </div>
  )
}

function AdvancedTable({
  inputs,
  baseline,
  onArrayChange,
  onScalarChange,
  onResetArrayField,
}: {
  inputs: IpoDcfInputs
  baseline: IpoDcfInputs
  onArrayChange: (field: ArrayField, index: number, value: number) => void
  onScalarChange: <K extends keyof IpoDcfInputs>(field: K, value: IpoDcfInputs[K]) => void
  onResetArrayField: (field: ArrayField) => void
}) {
  const taxDirty = inputs.taxPctRev.some((v, i) => isDirtyNum(v, baseline.taxPctRev[i]))
  const bfrDirty = inputs.bfrPctRev.some((v, i) => isDirtyNum(v, baseline.bfrPctRev[i]))
  const capexDirty = inputs.capexPctRev.some((v, i) => isDirtyNum(v, baseline.capexPctRev[i]))
  return (
    <div className="mt-3 flex flex-col gap-3">
      <div className="overflow-x-auto">
        <table className="claude-table">
          <thead>
            <tr>
              <th>Poste (% CA)</th>
              {inputs.years.map((year) => (
                <th key={year} className="r">{year}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <span className="inline-flex items-center gap-1">
                  Impot (IS theorique)
                  {taxDirty ? <ResetIcon onClick={() => onResetArrayField("taxPctRev")} title="Reinitialiser cette ligne" /> : null}
                </span>
              </td>
              {inputs.taxPctRev.map((v, i) => (
                <td key={inputs.years[i]} className="r">
                  <PercentInput value={v} onChange={(next) => onArrayChange("taxPctRev", i, next)} />
                </td>
              ))}
            </tr>
            <tr>
              <td>
                <span className="inline-flex items-center gap-1">
                  Variation BFR
                  {bfrDirty ? <ResetIcon onClick={() => onResetArrayField("bfrPctRev")} title="Reinitialiser cette ligne" /> : null}
                </span>
              </td>
              {inputs.bfrPctRev.map((v, i) => (
                <td key={inputs.years[i]} className="r">
                  <PercentInput value={v} onChange={(next) => onArrayChange("bfrPctRev", i, next)} />
                </td>
              ))}
            </tr>
            <tr>
              <td>
                <span className="inline-flex items-center gap-1">
                  Capex
                  {capexDirty ? <ResetIcon onClick={() => onResetArrayField("capexPctRev")} title="Reinitialiser cette ligne" /> : null}
                </span>
              </td>
              {inputs.capexPctRev.map((v, i) => (
                <td key={inputs.years[i]} className="r">
                  <PercentInput value={v} onChange={(next) => onArrayChange("capexPctRev", i, next)} />
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label="Impot terminal (% CA)"
          dirty={isDirtyNum(inputs.terminalTaxPctRev, baseline.terminalTaxPctRev)}
          onReset={() => onScalarChange("terminalTaxPctRev", baseline.terminalTaxPctRev)}
        >
          <PercentInput value={inputs.terminalTaxPctRev} onChange={(v) => onScalarChange("terminalTaxPctRev", v)} />
        </Field>
        <Field
          label="Delta BFR terminal (% CA)"
          dirty={isDirtyNum(inputs.terminalBfrPctRev, baseline.terminalBfrPctRev)}
          onReset={() => onScalarChange("terminalBfrPctRev", baseline.terminalBfrPctRev)}
        >
          <PercentInput value={inputs.terminalBfrPctRev} onChange={(v) => onScalarChange("terminalBfrPctRev", v)} />
        </Field>
        <Field
          label="Capex terminal (% CA)"
          dirty={isDirtyNum(inputs.terminalCapexPctRev, baseline.terminalCapexPctRev)}
          onReset={() => onScalarChange("terminalCapexPctRev", baseline.terminalCapexPctRev)}
        >
          <PercentInput value={inputs.terminalCapexPctRev} onChange={(v) => onScalarChange("terminalCapexPctRev", v)} />
        </Field>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Triangulation (live)
// ---------------------------------------------------------------------------

type LiveMarker = { key: string; label: string; value: number; kind: "offer" | "dcf" | "evEbe" | "pe" | "base" }

function LiveFootballField({ markers }: { markers: LiveMarker[] }) {
  const finiteValues = markers.map((m) => m.value).filter((v) => Number.isFinite(v))
  const scaleMin = finiteValues.length ? Math.min(...finiteValues) * 0.94 : 0
  const scaleMax = finiteValues.length ? Math.max(...finiteValues) * 1.06 : 1
  const span = scaleMax - scaleMin
  const pctOf = (value: number) => {
    if (!Number.isFinite(value) || span <= 0) return 50
    return Math.min(100, Math.max(0, ((value - scaleMin) / span) * 100))
  }
  const dotClass: Record<LiveMarker["kind"], string> = {
    offer: "h-3 w-3 border-2 border-background bg-amber-500",
    dcf: "h-2.5 w-2.5 bg-primary",
    evEbe: "h-2.5 w-2.5 bg-sky-500",
    pe: "h-2.5 w-2.5 bg-violet-500",
    base: "h-2 w-2 border border-dashed border-muted-foreground bg-transparent",
  }
  return (
    <div className="relative my-8 h-2 rounded-full bg-muted">
      {markers.map((marker) => (
        <div key={marker.key} className="absolute top-1/2 -translate-y-1/2" style={{ left: `${pctOf(marker.value)}%` }}>
          <div className={cn("-translate-x-1/2 rounded-full", dotClass[marker.kind])} />
          <div
            className={cn(
              "absolute top-3 -translate-x-1/2 whitespace-nowrap text-[9px]",
              marker.kind === "offer" ? "font-bold text-amber-600 dark:text-amber-400" : "text-muted-foreground",
              marker.kind === "dcf" && "font-semibold text-foreground",
            )}
          >
            {marker.label} {Number.isFinite(marker.value) ? fmtMoney(marker.value, 0) : "-"}
          </div>
        </div>
      ))}
    </div>
  )
}

function LiveTriangulationTable({ offerPrice, rows }: { offerPrice: number; rows: Array<{ label: string; value: number }> }) {
  const upsideVs = (value: number) => (offerPrice > 0 && Number.isFinite(value) ? value / offerPrice - 1 : NaN)
  return (
    <table className="claude-table">
      <thead>
        <tr>
          <th>Methode</th>
          <th className="r">Valeur / action</th>
          <th className="r">Upside vs offre</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.label}>
            <td>{row.label}</td>
            <td className="r font-mono font-semibold">{Number.isFinite(row.value) ? `${fmtMoney(row.value, 0)} MAD` : "-"}</td>
            <td className={cn("r font-mono", Number.isFinite(upsideVs(row.value)) && (upsideVs(row.value) >= 0 ? "t-pos" : "t-neg"))}>
              {fmtPct(upsideVs(row.value), 1)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ---------------------------------------------------------------------------
// Reference tables (unchanged, editorial data)
// ---------------------------------------------------------------------------

function PeerTable({
  peers,
  peerStats,
  onChangePeer,
  onRemovePeer,
}: {
  peers: IpoPeer[]
  peerStats: ReturnType<typeof recomputeIpoPeerStats>
  onChangePeer: (index: number, patch: Partial<IpoPeer>) => void
  onRemovePeer: (index: number) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="claude-table">
        <thead>
          <tr>
            <th>Societe</th>
            <th>Pays</th>
            <th className="r">Cap. (MUSD)</th>
            <th className="r">EV/EBE 26e</th>
            <th className="r">EV/EBE 27p</th>
            <th className="r">P/E 26e</th>
            <th className="r">P/E 27p</th>
            <th>Note</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {peers.map((peer, index) => (
            <tr key={`${peer.name}-${index}`}>
              <td className={cn(peer.isLocal && "font-bold")}>
                <TextField value={peer.name} onChange={(value) => onChangePeer(index, { name: value })} />
                {peer.isLocal ? <span className="ml-1.5 rounded bg-primary/10 px-1 py-0.5 text-[9px] font-semibold text-primary">local</span> : null}
              </td>
              <td><TextField value={peer.country} onChange={(value) => onChangePeer(index, { country: value })} /></td>
              <td className="r"><NumberField value={peer.marketCapMusd} onChange={(value) => onChangePeer(index, { marketCapMusd: value })} step={1} /></td>
              <td className="r"><NullableNumberField value={peer.evEbe2026e} onChange={(value) => onChangePeer(index, { evEbe2026e: value })} step={0.1} /></td>
              <td className="r"><NullableNumberField value={peer.evEbe2027p} onChange={(value) => onChangePeer(index, { evEbe2027p: value })} step={0.1} /></td>
              <td className="r"><NullableNumberField value={peer.pe2026e} onChange={(value) => onChangePeer(index, { pe2026e: value })} step={0.1} /></td>
              <td className="r"><NullableNumberField value={peer.pe2027p} onChange={(value) => onChangePeer(index, { pe2027p: value })} step={0.1} /></td>
              <td><TextField value={peer.note ?? ""} onChange={(value) => onChangePeer(index, { note: value })} /></td>
              <td className="r">
                <button type="button" className="text-[10px] text-red-600 hover:underline dark:text-red-400" onClick={() => onRemovePeer(index)}>
                  Suppr.
                </button>
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={2} className="font-semibold">Moyenne</td>
            <td className="r font-mono">-</td>
            <td className="r font-mono">{fmtRatio(peerStats.mean.evEbe2026e, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.mean.evEbe2027p, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.mean.pe2026e, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.mean.pe2027p, 1)}</td>
            <td colSpan={2} />
          </tr>
          <tr>
            <td colSpan={2} className="font-semibold">Mediane</td>
            <td className="r font-mono">-</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.evEbe2026e, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.evEbe2027p, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.pe2026e, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.pe2027p, 1)}</td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function WaccBlock() {
  return (
    <div className="valuation-kv-list">
      {IPO_T2S.wacc.map((row) => (
        <div key={row.label} className="valuation-kv-row">
          <span className="valuation-kv-label">{row.label}</span>
          <span className="valuation-kv-value font-mono font-semibold">{row.value}</span>
        </div>
      ))}
    </div>
  )
}

function BusinessPlanTable() {
  return (
    <div className="overflow-x-auto">
      <table className="claude-table">
        <thead>
          <tr>
            <th>Agregat (MMAD)</th>
            {IPO_T2S.bpYears.map((year) => (
              <th key={year} className="r">{year}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {IPO_T2S.bp.map((row) => (
            <tr key={row.key}>
              <td>{row.label}</td>
              {row.values.map((value, index) => (
                <td key={`${row.key}-${IPO_T2S.bpYears[index]}`} className="r font-mono">
                  {row.format === "pct" ? fmtPct(value, 1, false) : fmtMoney(value, 0)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function IpoValuationCard({
  profile,
  onSaveProfile,
  onDeleteProfile,
  onBack,
}: {
  profile: IpoProfile
  onSaveProfile: (p: IpoProfile) => void
  onDeleteProfile?: () => void
  onBack: () => void
}) {
  const { meta } = profile
  const [scenario, setScenario] = useState<IpoScenarioKey>("base")
  const [inputs, setInputs] = useState<IpoDcfInputs>(profile.inputs)
  const [historicalRevenue, setHistoricalRevenue] = useState<number[]>(() => meta.priorActualYears.map((p) => p.revenue))
  const [evEbeMultiple, setEvEbeMultiple] = useState<number>(DEFAULT_EV_EBE_MULTIPLE)
  const [peMultiple, setPeMultiple] = useState<number>(DEFAULT_PE_MULTIPLE)
  const [peers, setPeers] = useState<IpoPeer[]>(() => (profile.customPeers?.length ? clonePeers(profile.customPeers) : clonePeers(IPO_T2S.peers)))
  const [subscriptionSettings, setSubscriptionSettings] = useState<IpoSubscriptionSettings>(() => profile.subscriptionSettings ?? buildDefaultSubscriptionSettings())
  const [sensX, setSensX] = useState<SensitivityAxis>("wacc")
  const [sensY, setSensY] = useState<SensitivityAxis>("terminalGrowth")
  const [sensMetric, setSensMetric] = useState<"perShare" | "upside">("perShare")

  // Switching to a different profile resets the workbench to that profile's
  // own saved/prospectus inputs - edits to one profile never bleed into another.
  useEffect(() => {
    setInputs(profile.inputs)
    setHistoricalRevenue(meta.priorActualYears.map((p) => p.revenue))
    setScenario("base")
    setPeers(profile.customPeers?.length ? clonePeers(profile.customPeers) : clonePeers(IPO_T2S.peers))
    const nextSettings = profile.subscriptionSettings ?? buildDefaultSubscriptionSettings()
    setSubscriptionSettings(nextSettings)
    setEvEbeMultiple(IPO_T2S.peerStats.mean.evEbe2026e ?? DEFAULT_EV_EBE_MULTIPLE)
    setPeMultiple(IPO_T2S.peerStats.mean.pe2026e ?? DEFAULT_PE_MULTIPLE)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile.meta.id])

  const dcf = useMemo(() => computeDcf(inputs), [inputs])
  const baseDcf = useMemo(() => computeDcf(profile.inputs), [profile.inputs])
  const peerStats = useMemo(() => recomputeIpoPeerStats(peers), [peers])

  const lastExplicitRow = dcf.rows[dcf.rows.length - 1]
  const ebeSeed = meta.hasProspectusContext ? 434 : lastExplicitRow?.ebe ?? 0
  const netIncomeSeed = meta.hasProspectusContext ? 241 : (lastExplicitRow?.ebe ?? 0) * 0.55

  const evEbeResult = useMemo(
    () =>
      compsEvEbeFairValue({
        multiple: evEbeMultiple,
        ebe: ebeSeed,
        netDebt: inputs.netDebt,
        otherAdjustments: meta.hasProspectusContext ? 102 : 0,
        shares: inputs.shares,
      }),
    [evEbeMultiple, ebeSeed, inputs.netDebt, inputs.shares, meta.hasProspectusContext],
  )
  const peResult = useMemo(
    () => compsPeFairValue({ multiple: peMultiple, netIncome: netIncomeSeed, shares: inputs.shares }),
    [peMultiple, netIncomeSeed, inputs.shares],
  )
  // Debounced autosave: settings/peers edits are frequent (typing in number
  // inputs) - coalesce them instead of firing onSaveProfile on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      onSaveProfile({ ...profile, subscriptionSettings, customPeers: peers })
    }, 600)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onSaveProfile, profile.meta.id, subscriptionSettings, peers])

  const xs = useMemo(() => axisRange(inputs, sensX), [inputs, sensX])
  const ys = useMemo(() => axisRange(inputs, sensY), [inputs, sensY])
  const sensValueGrid = useMemo(
    () => sensitivityGrid({ inputs, xAxis: sensX, yAxis: sensY, xs, ys, metric: sensMetric }),
    [inputs, sensX, sensY, xs, ys, sensMetric],
  )
  const sensUpsideGrid = useMemo(
    () => (sensMetric === "upside" ? sensValueGrid : sensitivityGrid({ inputs, xAxis: sensX, yAxis: sensY, xs, ys, metric: "upside" })),
    [inputs, sensX, sensY, xs, ys, sensMetric, sensValueGrid],
  )

  function handleScenario(next: IpoScenarioKey) {
    setScenario(next)
    setInputs(buildScenarioInputs(next))
  }

  function handleReset() {
    setScenario("base")
    setInputs(profile.inputs)
    setHistoricalRevenue(meta.priorActualYears.map((p) => p.revenue))
    const resetPeers = clonePeers(IPO_T2S.peers)
    const resetPeerStats = recomputeIpoPeerStats(resetPeers)
    setPeers(resetPeers)
    setSubscriptionSettings(profile.subscriptionSettings ?? buildDefaultSubscriptionSettings())
    setEvEbeMultiple(resetPeerStats.mean.evEbe2026e ?? DEFAULT_EV_EBE_MULTIPLE)
    setPeMultiple(resetPeerStats.mean.pe2026e ?? DEFAULT_PE_MULTIPLE)
  }

  function handleResetArrayField(field: ArrayField) {
    setInputs((cur) => ({ ...cur, [field]: profile.inputs[field].slice() }))
  }

  function handleHistoricalRevenueChange(index: number, value: number) {
    setHistoricalRevenue((cur) => {
      const next = cur.slice()
      next[index] = value
      return next
    })
  }

  function handleResetHistoricalAndAnchor() {
    setHistoricalRevenue(meta.priorActualYears.map((p) => p.revenue))
    handleScalarChange("revenueBase", profile.inputs.revenueBase)
  }

  function handleSave() {
    onSaveProfile({ ...profile, inputs, subscriptionSettings, customPeers: peers })
  }

  function handleDelete() {
    if (!onDeleteProfile) return
    if (window.confirm(`Supprimer le profil ${meta.name} ? Cette action est irreversible.`)) onDeleteProfile()
  }

  function handleArrayChange(field: ArrayField, index: number, value: number) {
    setInputs((cur) => withArrayValue(cur, field, index, value))
  }

  function handleScalarChange<K extends keyof IpoDcfInputs>(field: K, value: IpoDcfInputs[K]) {
    setInputs((cur) => withScalar(cur, field, value))
  }

  function handlePeerChange(index: number, patch: Partial<IpoPeer>) {
    setPeers((current) => current.map((peer, currentIndex) => (currentIndex === index ? { ...peer, ...patch } : peer)))
  }

  function handleAddPeer() {
    setPeers((current) => [...current, createBlankPeer()])
  }

  function handleAddLocalAnchorPeer() {
    const anchor = IPO_T2S.localAnchorPeers[0]
    if (!anchor) return
    setPeers((current) => (current.some((peer) => peer.name === anchor.name) ? current : [...current, { ...anchor }]))
  }

  function handleRemovePeer(index: number) {
    setPeers((current) => current.filter((_, currentIndex) => currentIndex !== index))
  }

  const deltaVsBase = dcf.fairValuePerShare - baseDcf.fairValuePerShare
  const postMoneyEquityMmad = inputs.shares * meta.offerPrice

  const markers: LiveMarker[] = [
    { key: "offer", label: "Offre", value: meta.offerPrice, kind: "offer" },
    { key: "dcf", label: "DCF (vous)", value: dcf.fairValuePerShare, kind: "dcf" },
    { key: "evEbe", label: "EV/EBE", value: evEbeResult.perShare, kind: "evEbe" },
    { key: "pe", label: "P/E", value: peResult.perShare, kind: "pe" },
    { key: "base", label: "Profil de base", value: baseDcf.fairValuePerShare, kind: "base" },
  ]

  return (
    <div className="flex flex-col gap-4">
      {/* 1. Header */}
      <div className="fund-card">
        <div className="fund-card-body">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold">{meta.name}</h3>
                <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-600 dark:text-amber-400">
                  IPO - Marche primaire - Modele interactif
                </span>
                {!meta.isBuiltin ? (
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground">perso</span>
                ) : null}
              </div>
              <div className="text-xs text-muted-foreground">{meta.sector || "Secteur non renseigné"}</div>
              {meta.isBuiltin ? <div className="text-[10px] text-muted-foreground">{IPO_T2S.meta.subSectors}</div> : null}
            </div>
            <div className="text-right text-[10px] text-muted-foreground">
              {meta.hasProspectusContext ? (
                IPO_T2S.meta.prospectusRef
              ) : (
                <span className="rounded bg-muted px-1.5 py-0.5 font-semibold">Profil personnalisé</span>
              )}
            </div>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Prix d'offre" value={`${fmtMoney(meta.offerPrice, 0)} MAD`} />
            <StatTile label="Premiere cotation" value={meta.firstQuote} />
            <StatTile label="Capitalisation (offre)" value={`${fmtMoney(postMoneyEquityMmad, 0)} MMAD`} />
            <StatTile label="Dernier exercice réel" value={String(meta.lastActualYear)} tone="text-muted-foreground" />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {meta.isBuiltin ? (
              <div className="seg">
                {(Object.keys(SCENARIO_LABELS) as IpoScenarioKey[]).map((key) => (
                  <button key={key} type="button" className={scenario === key ? "active" : ""} onClick={() => handleScenario(key)}>
                    {SCENARIO_LABELS[key]}
                  </button>
                ))}
              </div>
            ) : null}
            <button
              type="button"
              onClick={handleReset}
              className="rounded-md border border-line px-2.5 py-1 text-[11px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              {meta.hasProspectusContext ? "Reinitialiser (prospectus)" : "Reinitialiser (profil enregistré)"}
            </button>
            {!meta.isBuiltin ? (
              <button
                type="button"
                onClick={handleSave}
                className="rounded-md border border-primary/40 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary hover:bg-primary/20"
              >
                Enregistrer les modifications
              </button>
            ) : null}
            {onDeleteProfile ? (
              <button
                type="button"
                onClick={handleDelete}
                className="rounded-md border border-red-300 px-2.5 py-1 text-[11px] font-medium text-red-600 hover:bg-red-500/10 dark:border-red-800 dark:text-red-400"
              >
                Supprimer
              </button>
            ) : null}
            <button
              type="button"
              onClick={onBack}
              className="ml-auto rounded-md border border-line px-2.5 py-1 text-[11px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              Retour
            </button>
          </div>
        </div>
      </div>

      {/* 2. Live result strip */}
      <FundCard title="Resultat (live)" aside="recalcule a chaque hypothese">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Valeur / action (DCF)</div>
            <div className="font-mono text-2xl font-bold">{Number.isFinite(dcf.fairValuePerShare) ? `${fmtMoney(dcf.fairValuePerShare, 0)} MAD` : "-"}</div>
            <div className={cn("font-mono text-xs font-semibold", Number.isFinite(dcf.upsideVsOffer) && (dcf.upsideVsOffer >= 0 ? "t-pos" : "t-neg"))}>
              {fmtPct(dcf.upsideVsOffer, 1)} vs offre {fmtMoney(meta.offerPrice, 0)} MAD
            </div>
            <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
              {Number.isFinite(deltaVsBase)
                ? `${deltaVsBase >= 0 ? "+" : ""}${fmtMoney(deltaVsBase, 0)} MAD vs profil de base (${fmtMoney(baseDcf.fairValuePerShare, 0)} MAD)`
                : "-"}
            </div>
          </div>
          <div className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Valeur d'entreprise" value={`${fmtMoney(dcf.enterpriseValue, 0)} MMAD`} />
            <StatTile label="Valeur des fonds propres" value={`${fmtMoney(dcf.equityValue, 0)} MMAD`} />
            <StatTile label="TCAM CA" value={fmtPct(dcf.revenueCagr, 1, false)} />
            <StatTile label="Poids valeur terminale" value={fmtPct(dcf.terminalPvPct, 0, false)} />
          </div>
        </div>
        {!dcf.valid ? (
          <p className="mt-3 rounded-md bg-amber-500/10 px-2.5 py-1.5 text-[11px] text-amber-600 dark:text-amber-400">
            WACC inferieur ou egal a la croissance terminale (g) : la valeur terminale de Gordon-Shapiro n&apos;est pas definie.
          </p>
        ) : null}
      </FundCard>

      {/* 3. Editable assumptions */}
      <FundCard title="Vos hypotheses" aside="modifiez librement - le scenario reste affiche a titre indicatif">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field
            label="WACC"
            dirty={isDirtyNum(inputs.wacc, profile.inputs.wacc)}
            onReset={() => handleScalarChange("wacc", profile.inputs.wacc)}
          >
            <PercentInput value={inputs.wacc} onChange={(v) => handleScalarChange("wacc", v)} />
          </Field>
          <Field
            label="Croissance terminale (g)"
            dirty={isDirtyNum(inputs.terminalGrowth, profile.inputs.terminalGrowth)}
            onReset={() => handleScalarChange("terminalGrowth", profile.inputs.terminalGrowth)}
          >
            <PercentInput value={inputs.terminalGrowth} onChange={(v) => handleScalarChange("terminalGrowth", v)} step={0.05} />
          </Field>
          <Field
            label="Marge d'EBE terminale"
            dirty={isDirtyNum(inputs.terminalEbeMargin, profile.inputs.terminalEbeMargin)}
            onReset={() => handleScalarChange("terminalEbeMargin", profile.inputs.terminalEbeMargin)}
          >
            <PercentInput value={inputs.terminalEbeMargin} onChange={(v) => handleScalarChange("terminalEbeMargin", v)} />
          </Field>
          <Field
            label="Dette nette (MMAD)"
            dirty={isDirtyNum(inputs.netDebt, profile.inputs.netDebt)}
            onReset={() => handleScalarChange("netDebt", profile.inputs.netDebt)}
          >
            <NumberField value={inputs.netDebt} onChange={(v) => handleScalarChange("netDebt", v)} step={5} />
          </Field>
          <Field
            label="Actions (M)"
            dirty={isDirtyNum(inputs.shares, profile.inputs.shares)}
            onReset={() => handleScalarChange("shares", profile.inputs.shares)}
          >
            <NumberField value={inputs.shares} onChange={(v) => handleScalarChange("shares", v)} step={0.1} />
          </Field>
        </div>

        <div className="mt-4">
          <div className="valuation-mini-title mb-1">
            Trajectoire ({meta.priorActualYears[0]?.year ?? meta.lastActualYear} - {inputs.years[inputs.years.length - 1] ?? ""})
          </div>
          <DriverTable
            inputs={inputs}
            baseline={profile.inputs}
            dcf={dcf}
            meta={meta}
            historicalRevenue={historicalRevenue}
            baselineHistoricalRevenue={meta.priorActualYears.map((p) => p.revenue)}
            onArrayChange={handleArrayChange}
            onRevenueBaseChange={(v) => handleScalarChange("revenueBase", v)}
            onHistoricalRevenueChange={handleHistoricalRevenueChange}
            onResetArrayField={handleResetArrayField}
            onResetHistoricalAndAnchor={handleResetHistoricalAndAnchor}
          />
        </div>

        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold text-muted-foreground hover:text-foreground">Hypotheses avancees</summary>
          <AdvancedTable
            inputs={inputs}
            baseline={profile.inputs}
            onArrayChange={handleArrayChange}
            onScalarChange={handleScalarChange}
            onResetArrayField={handleResetArrayField}
          />
        </details>
      </FundCard>

      {/* 4. Live triangulation */}
      <FundCard title="Triangulation de valorisation (live)">
        <LiveFootballField markers={markers} />
        <LiveTriangulationTable
          offerPrice={meta.offerPrice}
          rows={[
            { label: "DCF (vos hypotheses)", value: dcf.fairValuePerShare },
            { label: "Comparables EV/EBE", value: evEbeResult.perShare },
            { label: "Comparables P/E", value: peResult.perShare },
          ]}
        />
        <p className="mt-2 text-xs text-muted-foreground">
          Repere en pointille : valeur DCF du profil de base ({fmtMoney(baseDcf.fairValuePerShare, 0)} MAD). Toutes les autres valeurs refletent VOS
          hypotheses, pas celles de l&apos;emetteur.
        </p>
      </FundCard>

      {/* 5. Comparables (editable) */}
      <FundCard title="Comparables (editable)">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-md border border-line p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold">EV/EBE applique</span>
              <button
                type="button"
                className="text-[10px] text-primary hover:underline"
                onClick={() => setEvEbeMultiple(peerStats.mean.evEbe2026e ?? DEFAULT_EV_EBE_MULTIPLE)}
              >
                Utiliser la moyenne
              </button>
            </div>
            <div className="mt-1.5 w-24">
              <NumberField value={evEbeMultiple} onChange={setEvEbeMultiple} step={0.1} />
            </div>
            <div className="mt-2 font-mono text-lg font-bold">
              {Number.isFinite(evEbeResult.perShare) ? `${fmtMoney(evEbeResult.perShare, 0)} MAD` : "-"}
            </div>
            <div className={cn("font-mono text-xs", meta.offerPrice > 0 && evEbeResult.perShare / meta.offerPrice - 1 >= 0 ? "t-pos" : "t-neg")}>
              {fmtPct(meta.offerPrice > 0 ? evEbeResult.perShare / meta.offerPrice - 1 : NaN, 1)} vs offre
            </div>
          </div>
          <div className="rounded-md border border-line p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold">P/E applique</span>
              <button
                type="button"
                className="text-[10px] text-primary hover:underline"
                onClick={() => setPeMultiple(peerStats.mean.pe2026e ?? DEFAULT_PE_MULTIPLE)}
              >
                Utiliser la moyenne
              </button>
            </div>
            <div className="mt-1.5 w-24">
              <NumberField value={peMultiple} onChange={setPeMultiple} step={0.1} />
            </div>
            <div className="mt-2 font-mono text-lg font-bold">
              {Number.isFinite(peResult.perShare) ? `${fmtMoney(peResult.perShare, 0)} MAD` : "-"}
            </div>
            <div className={cn("font-mono text-xs", meta.offerPrice > 0 && peResult.perShare / meta.offerPrice - 1 >= 0 ? "t-pos" : "t-neg")}>
              {fmtPct(meta.offerPrice > 0 ? peResult.perShare / meta.offerPrice - 1 : NaN, 1)} vs offre
            </div>
            {!meta.hasProspectusContext ? (
              <p className="mt-1 text-[9px] text-muted-foreground">
                Résultat net approximé (proxy 55% de l&apos;EBE) — pas de donnée prospectus pour ce profil.
              </p>
            ) : null}
          </div>
        </div>
        <div className="mt-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <div className="valuation-mini-title">Echantillon de comparables (editable)</div>
            <button type="button" className="rounded-md border border-line px-2 py-1 text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground" onClick={handleAddPeer}>
              Ajouter une ligne
            </button>
            <button type="button" className="rounded-md border border-line px-2 py-1 text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground" onClick={handleAddLocalAnchorPeer}>
              Ajouter Akdital
            </button>
            <button
              type="button"
              className="rounded-md border border-line px-2 py-1 text-[10px] text-muted-foreground hover:bg-accent hover:text-foreground"
              onClick={() => {
                const resetPeers = clonePeers(IPO_T2S.peers)
                const resetPeerStats = recomputeIpoPeerStats(resetPeers)
                setPeers(resetPeers)
                setEvEbeMultiple(resetPeerStats.mean.evEbe2026e ?? DEFAULT_EV_EBE_MULTIPLE)
                setPeMultiple(resetPeerStats.mean.pe2026e ?? DEFAULT_PE_MULTIPLE)
              }}
            >
              Reset prospectus
            </button>
          </div>
          <PeerTable peers={peers} peerStats={peerStats} onChangePeer={handlePeerChange} onRemovePeer={handleRemovePeer} />
        </div>
      </FundCard>

      {/* 6. Subscription sizing */}
      <IpoSubscriptionPanel
        settings={subscriptionSettings}
        offerPrice={meta.offerPrice}
        retailTrancheShares={IPO_T2S.meta.trancheRetailShares}
        institutionalTrancheShares={IPO_T2S.meta.trancheInstitutionalShares}
        institutionalMinShares={IPO_T2S.meta.trancheInstitutionalMinShares}
        retailBlockSize={IPO_T2S.meta.retailBlockSize}
        subscriptionCapShares={IPO_T2S.meta.subscriptionCapShares}
        baseRateRows={IPO_T2S.casablancaBaseRates}
        onChange={setSubscriptionSettings}
      />

      {/* 7. Sensitivity */}
      <FundCard title="Sensibilite (live)">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Axe X">
            <select
              className="h-8 rounded-md border border-line bg-card px-2 text-[11px] outline-none"
              value={sensX}
              onChange={(event) => setSensX(event.target.value as SensitivityAxis)}
            >
              {AXIS_OPTIONS.map((axis) => (
                <option key={axis} value={axis}>{AXIS_LABELS[axis]}</option>
              ))}
            </select>
          </Field>
          <Field label="Axe Y">
            <select
              className="h-8 rounded-md border border-line bg-card px-2 text-[11px] outline-none"
              value={sensY}
              onChange={(event) => setSensY(event.target.value as SensitivityAxis)}
            >
              {AXIS_OPTIONS.map((axis) => (
                <option key={axis} value={axis}>{AXIS_LABELS[axis]}</option>
              ))}
            </select>
          </Field>
          <div className="seg">
            <button type="button" className={sensMetric === "perShare" ? "active" : ""} onClick={() => setSensMetric("perShare")}>
              Valeur/action
            </button>
            <button type="button" className={sensMetric === "upside" ? "active" : ""} onClick={() => setSensMetric("upside")}>
              Upside
            </button>
          </div>
        </div>

        <div className="mt-3 overflow-x-auto">
          <table className="claude-table">
            <thead>
              <tr>
                <th>{AXIS_LABELS[sensY]} / {AXIS_LABELS[sensX]}</th>
                {xs.map((x, xi) => (
                  <th key={xi} className={cn("r", xi === 2 && "font-bold")}>{axisFormat(sensX, x)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ys.map((y, yi) => (
                <tr key={yi}>
                  <td className={cn(yi === 2 && "font-bold")}>{axisFormat(sensY, y)}</td>
                  {xs.map((x, xi) => {
                    const value = sensValueGrid[yi]?.[xi] ?? NaN
                    const upside = sensUpsideGrid[yi]?.[xi] ?? NaN
                    return (
                      <td
                        key={xi}
                        className={cn("r font-mono", xi === 2 && yi === 2 && "ring-1 ring-inset ring-primary")}
                        style={sensCellStyle(upside)}
                      >
                        {sensMetric === "perShare" ? (Number.isFinite(value) ? `${fmtMoney(value, 0)} MAD` : "-") : fmtPct(value, 1)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground">
          Cellule encadree = vos hypotheses actuelles. Grille centree sur les valeurs courantes des axes selectionnes.
        </p>
      </FundCard>

      {/* 8. Context (collapsible reference) */}
      <FundCard title={meta.hasProspectusContext ? "Contexte (reference prospectus)" : "Contexte"}>
        {meta.hasProspectusContext ? (
          <details>
            <summary className="cursor-pointer text-xs font-semibold text-muted-foreground hover:text-foreground">
              CMPC, business plan pre-money, upsides &amp; risques
            </summary>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <div>
                <div className="valuation-mini-title mb-1">Cout moyen pondere du capital (prospectus)</div>
                <WaccBlock />
              </div>
              <div>
                <div className="valuation-mini-title mb-1">Upsides non integres</div>
                <ul className="space-y-1.5 text-xs">
                  {IPO_T2S.upsides.map((item) => (
                    <li key={item} className="flex gap-1.5 t-pos">
                      <span>+</span>
                      <span className="text-foreground">{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="mt-3">
              <div className="valuation-mini-title mb-1">Business plan pre-money (MMAD) - TCAM CA 2026e-2030p {fmtPct(IPO_T2S.bpCagr.revenue2630, 1, true)}</div>
              <BusinessPlanTable />
            </div>
            <div className="mt-3">
              <div className="valuation-mini-title mb-1">Facteurs de risque</div>
              <ul className="space-y-1.5 text-xs">
                {IPO_T2S.risks.map((item) => (
                  <li key={item} className="flex gap-1.5 text-amber-600 dark:text-amber-400">
                    <span>!</span>
                    <span className="text-muted-foreground">{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          </details>
        ) : (
          <p className="text-xs text-muted-foreground">
            Pas de document de référence pour ce profil personnalisé — hypothèses saisies manuellement.
          </p>
        )}
      </FundCard>

      <p className="text-[10px] text-muted-foreground">
        {meta.hasProspectusContext ? (
          <>
            Donnees seedees depuis le prospectus vise par l&apos;AMMC ({IPO_T2S.meta.prospectusRef}). Le scenario "base" reproduit la valeur du prospectus
            ({fmtMoney(baseDcf.fairValuePerShare, 0)} MAD) ; tous les autres resultats refletent VOS propres hypotheses, pas celles du moteur ou de
            l&apos;emetteur.{" "}
          </>
        ) : (
          "Hypothèses saisies manuellement par l'utilisateur — aucune source externe validée. "
        )}
        {meta.ticker} n&apos;est pas encore cote : ni backtest ni signal disponibles avant la premiere cotation ({meta.firstQuote}).
      </p>
    </div>
  )
}
