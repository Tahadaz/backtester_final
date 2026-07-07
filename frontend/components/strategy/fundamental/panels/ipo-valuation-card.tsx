"use client"

import { useEffect, useMemo, useState } from "react"
import type { CSSProperties, ReactNode } from "react"
import { cn } from "@/lib/utils"
import { fmtMoney, fmtNumber, fmtPct, fmtRatio } from "../lib/formatters"
import { FundCard, StatTile } from "../shared/cards"
import { IPO_T2S } from "../lib/ipo-data"
import {
  buildBaseInputs,
  buildScenarioInputs,
  compsEvEbeFairValue,
  compsPeFairValue,
  computeDcf,
  sensitivityGrid,
  type IpoDcfInputs,
  type IpoDcfResult,
  type IpoScenarioKey,
  type SensitivityAxis,
} from "../lib/ipo-model"

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

function pctDisplay(value: number, digits = 2): number {
  return Number.isFinite(value) ? Number((value * 100).toFixed(digits)) : 0
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

function NumberField({ value, onChange, step = 1 }: { value: number; onChange: (v: number) => void; step?: number }) {
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
      className="h-8 w-full rounded-md border border-line bg-card px-2 text-right text-[11px] font-mono outline-none focus-visible:ring-1 focus-visible:ring-ring"
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[10px] text-muted-foreground">
      <span>{label}</span>
      {children}
    </label>
  )
}

// ---------------------------------------------------------------------------
// Driver / advanced tables
// ---------------------------------------------------------------------------

function DriverTable({
  inputs,
  dcf,
  onArrayChange,
}: {
  inputs: IpoDcfInputs
  dcf: IpoDcfResult
  onArrayChange: (field: ArrayField, index: number, value: number) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="claude-table">
        <thead>
          <tr>
            <th>Poste</th>
            {inputs.years.map((year) => (
              <th key={year} className="r">{year}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Croissance CA (%)</td>
            {inputs.revenueGrowth.map((g, i) => (
              <td key={inputs.years[i]} className="r">
                <PercentInput value={g} onChange={(v) => onArrayChange("revenueGrowth", i, v)} />
              </td>
            ))}
          </tr>
          <tr>
            <td>Marge d&apos;EBE (%)</td>
            {inputs.ebeMargin.map((m, i) => (
              <td key={inputs.years[i]} className="r">
                <PercentInput value={m} onChange={(v) => onArrayChange("ebeMargin", i, v)} />
              </td>
            ))}
          </tr>
          <tr className="text-muted-foreground">
            <td>CA (MMAD)</td>
            {dcf.rows.map((row) => (
              <td key={row.year} className="r font-mono">{fmtMoney(row.revenue, 0)}</td>
            ))}
          </tr>
          <tr className="text-muted-foreground">
            <td>FCFF (MMAD)</td>
            {dcf.rows.map((row) => (
              <td key={row.year} className={cn("r font-mono", row.fcff < 0 && "t-neg")}>{fmtMoney(row.fcff, 0)}</td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function AdvancedTable({
  inputs,
  onArrayChange,
  onScalarChange,
}: {
  inputs: IpoDcfInputs
  onArrayChange: (field: ArrayField, index: number, value: number) => void
  onScalarChange: <K extends keyof IpoDcfInputs>(field: K, value: IpoDcfInputs[K]) => void
}) {
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
              <td>Impot (IS theorique)</td>
              {inputs.taxPctRev.map((v, i) => (
                <td key={inputs.years[i]} className="r">
                  <PercentInput value={v} onChange={(next) => onArrayChange("taxPctRev", i, next)} />
                </td>
              ))}
            </tr>
            <tr>
              <td>Variation BFR</td>
              {inputs.bfrPctRev.map((v, i) => (
                <td key={inputs.years[i]} className="r">
                  <PercentInput value={v} onChange={(next) => onArrayChange("bfrPctRev", i, next)} />
                </td>
              ))}
            </tr>
            <tr>
              <td>Capex</td>
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
        <Field label="Impot terminal (% CA)">
          <PercentInput value={inputs.terminalTaxPctRev} onChange={(v) => onScalarChange("terminalTaxPctRev", v)} />
        </Field>
        <Field label="Delta BFR terminal (% CA)">
          <PercentInput value={inputs.terminalBfrPctRev} onChange={(v) => onScalarChange("terminalBfrPctRev", v)} />
        </Field>
        <Field label="Capex terminal (% CA)">
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

function PeerTable() {
  const { peers, peerStats } = IPO_T2S
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
          </tr>
        </thead>
        <tbody>
          {peers.map((peer) => (
            <tr key={peer.name}>
              <td className={cn(peer.isLocal && "font-bold")}>
                {peer.name}
                {peer.isLocal ? <span className="ml-1.5 rounded bg-primary/10 px-1 py-0.5 text-[9px] font-semibold text-primary">local</span> : null}
              </td>
              <td>{peer.country}</td>
              <td className="r font-mono">{fmtNumber(peer.marketCapMusd, 0)}</td>
              <td className="r font-mono">{fmtRatio(peer.evEbe2026e, 1)}</td>
              <td className="r font-mono">{fmtRatio(peer.evEbe2027p, 1)}</td>
              <td className="r font-mono">{fmtRatio(peer.pe2026e, 1)}</td>
              <td className="r font-mono">{fmtRatio(peer.pe2027p, 1)}</td>
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
          </tr>
          <tr>
            <td colSpan={2} className="font-semibold">Mediane</td>
            <td className="r font-mono">-</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.evEbe2026e, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.evEbe2027p, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.pe2026e, 1)}</td>
            <td className="r font-mono">{fmtRatio(peerStats.median.pe2027p, 1)}</td>
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

export function IpoValuationCard() {
  const { meta } = IPO_T2S

  const [scenario, setScenario] = useState<IpoScenarioKey>("base")
  const [inputs, setInputs] = useState<IpoDcfInputs>(() => buildBaseInputs())
  const [evEbeMultiple, setEvEbeMultiple] = useState<number>(IPO_T2S.peerStats.mean.evEbe2026e)
  const [peMultiple, setPeMultiple] = useState<number>(IPO_T2S.peerStats.mean.pe2026e)
  const [sensX, setSensX] = useState<SensitivityAxis>("wacc")
  const [sensY, setSensY] = useState<SensitivityAxis>("terminalGrowth")
  const [sensMetric, setSensMetric] = useState<"perShare" | "upside">("perShare")

  const dcf = useMemo(() => computeDcf(inputs), [inputs])
  const baseDcf = useMemo(() => computeDcf(buildBaseInputs()), [])

  const evEbeResult = useMemo(
    () => compsEvEbeFairValue({ multiple: evEbeMultiple, ebe: 434, netDebt: inputs.netDebt, otherAdjustments: 102, shares: inputs.shares }),
    [evEbeMultiple, inputs.netDebt, inputs.shares],
  )
  const peResult = useMemo(() => compsPeFairValue({ multiple: peMultiple, netIncome: 241, shares: inputs.shares }), [peMultiple, inputs.shares])

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
    setInputs(buildBaseInputs())
    setEvEbeMultiple(IPO_T2S.peerStats.mean.evEbe2026e)
    setPeMultiple(IPO_T2S.peerStats.mean.pe2026e)
  }

  function handleArrayChange(field: ArrayField, index: number, value: number) {
    setInputs((cur) => withArrayValue(cur, field, index, value))
  }

  function handleScalarChange<K extends keyof IpoDcfInputs>(field: K, value: IpoDcfInputs[K]) {
    setInputs((cur) => withScalar(cur, field, value))
  }

  const deltaVsProspectus = dcf.fairValuePerShare - baseDcf.fairValuePerShare

  const markers: LiveMarker[] = [
    { key: "offer", label: "Offre", value: meta.offerPrice, kind: "offer" },
    { key: "dcf", label: "DCF (vous)", value: dcf.fairValuePerShare, kind: "dcf" },
    { key: "evEbe", label: "EV/EBE", value: evEbeResult.perShare, kind: "evEbe" },
    { key: "pe", label: "P/E", value: peResult.perShare, kind: "pe" },
    { key: "base", label: "Prospectus", value: baseDcf.fairValuePerShare, kind: "base" },
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
              </div>
              <div className="text-xs text-muted-foreground">{meta.sector}</div>
              <div className="text-[10px] text-muted-foreground">{meta.subSectors}</div>
            </div>
            <div className="text-right text-[10px] text-muted-foreground">{meta.prospectusRef}</div>
          </div>

          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <StatTile label="Prix d'offre" value={`${fmtMoney(meta.offerPrice, 0)} MAD`} />
            <StatTile label="Premiere cotation" value={meta.firstQuote} />
            <StatTile label="Capitalisation post-money" value={`${fmtMoney(meta.postMoneyEquityMmad, 0)} MMAD`} />
            <StatTile label="Reference" value={meta.prospectusRef} tone="text-muted-foreground" />
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <div className="seg">
              {(Object.keys(SCENARIO_LABELS) as IpoScenarioKey[]).map((key) => (
                <button key={key} type="button" className={scenario === key ? "active" : ""} onClick={() => handleScenario(key)}>
                  {SCENARIO_LABELS[key]}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={handleReset}
              className="rounded-md border border-line px-2.5 py-1 text-[11px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              Reinitialiser (prospectus)
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
              {fmtPct(dcf.upsideVsOffer, 1)} vs offre 223 MAD
            </div>
            <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">
              {Number.isFinite(deltaVsProspectus) ? `${deltaVsProspectus >= 0 ? "+" : ""}${fmtMoney(deltaVsProspectus, 0)} MAD vs prospectus (301 MAD)` : "-"}
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
          <Field label="WACC">
            <PercentInput value={inputs.wacc} onChange={(v) => handleScalarChange("wacc", v)} />
          </Field>
          <Field label="Croissance terminale (g)">
            <PercentInput value={inputs.terminalGrowth} onChange={(v) => handleScalarChange("terminalGrowth", v)} step={0.05} />
          </Field>
          <Field label="Marge d'EBE terminale">
            <PercentInput value={inputs.terminalEbeMargin} onChange={(v) => handleScalarChange("terminalEbeMargin", v)} />
          </Field>
          <Field label="Dette nette (MMAD)">
            <NumberField value={inputs.netDebt} onChange={(v) => handleScalarChange("netDebt", v)} step={5} />
          </Field>
          <Field label="Actions (M)">
            <NumberField value={inputs.shares} onChange={(v) => handleScalarChange("shares", v)} step={0.1} />
          </Field>
        </div>

        <div className="mt-4">
          <div className="valuation-mini-title mb-1">Trajectoire explicite (2026e-2030p)</div>
          <DriverTable inputs={inputs} dcf={dcf} onArrayChange={handleArrayChange} />
        </div>

        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold text-muted-foreground hover:text-foreground">Hypotheses avancees</summary>
          <AdvancedTable inputs={inputs} onArrayChange={handleArrayChange} onScalarChange={handleScalarChange} />
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
          Repere en pointille : valeur DCF du prospectus (301 MAD). Toutes les autres valeurs refletent VOS hypotheses, pas celles de l&apos;emetteur.
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
                onClick={() => setEvEbeMultiple(IPO_T2S.peerStats.mean.evEbe2026e)}
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
                onClick={() => setPeMultiple(IPO_T2S.peerStats.mean.pe2026e)}
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
          </div>
        </div>
        <div className="mt-3">
          <div className="valuation-mini-title mb-1">Echantillon de comparables (Capital IQ, 25/06/2026)</div>
          <PeerTable />
        </div>
      </FundCard>

      {/* 6. Sensitivity */}
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

      {/* 7. Context (collapsible reference) */}
      <FundCard title="Contexte (reference prospectus)">
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
      </FundCard>

      <p className="text-[10px] text-muted-foreground">
        Donnees seedees depuis le prospectus vise par l&apos;AMMC ({meta.prospectusRef}). Le scenario "base" reproduit la valeur du prospectus (301 MAD) ; tous
        les autres resultats refletent VOS propres hypotheses, pas celles du moteur ou de l&apos;emetteur. T2S n&apos;est pas encore cote : ni backtest ni
        signal disponibles avant la premiere cotation.
      </p>
    </div>
  )
}
