"use client"

import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react"
import { useMethodEvaluation } from "@/hooks/use-api"
import type { MethodEvaluationRow } from "@/lib/api"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type EngineHorizon = "short" | "medium" | "long"
type Universe = "all" | "masi" | "liquid_masi"
type SortKey = "verdict" | "coverage_pct" | "median_ic" | "median_sharpe" | "median_hit_rate" | "median_n" | "evidence_score"

const HORIZONS: { value: EngineHorizon; label: string }[] = [
  { value: "short", label: "Hebdomadaire" },
  { value: "medium", label: "Mensuel" },
  { value: "long", label: "Trimestriel" },
]

const UNIVERSES: { value: Universe; label: string }[] = [
  { value: "liquid_masi", label: "MASI liquide" },
  { value: "masi", label: "MASI" },
  { value: "all", label: "Tous" },
]

const RETURN_METHODS = [
  { value: "open_to_open", label: "O to O" },
  { value: "open_to_close", label: "O to C" },
] as const

function fmtNumber(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  return value.toFixed(digits)
}

function fmtPct(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${value.toFixed(1)}%`
}

function fmtHit(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${(value * 100).toFixed(1)}%`
}

function verdictRank(value: string) {
  if (value === "keep") return 4
  if (value === "watch") return 3
  if (value === "discard") return 2
  return 1
}

function verdictLabel(value: string) {
  if (value === "keep") return "Garder"
  if (value === "watch") return "Surveiller"
  if (value === "discard") return "Ecarter"
  return "No data"
}

function verdictClass(value: string) {
  if (value === "keep") return "border-emerald-200 bg-emerald-50 text-emerald-800"
  if (value === "watch") return "border-amber-200 bg-amber-50 text-amber-800"
  if (value === "discard") return "border-red-200 bg-red-50 text-red-800"
  return "border-line bg-muted text-muted-foreground"
}

function reasonLabel(reason: string) {
  const labels: Record<string, string> = {
    enough_positive_rows: "assez de lignes positives",
    sparse_eligible_rows: "peu de lignes eligibles",
    low_sample: "echantillon faible",
    negative_ic: "IC negatif",
    negative_sharpe: "Sharpe negatif",
    weak_hit_rate: "hit rate faible",
    no_history: "pas d'historique",
  }
  return labels[reason] ?? reason.replaceAll("_", " ")
}

export function MethodEvaluationPanel() {
  const [engineHorizon, setEngineHorizon] = useState<EngineHorizon>("medium")
  const [universe, setUniverse] = useState<Universe>("liquid_masi")
  const [returnCalcMethod, setReturnCalcMethod] = useState<(typeof RETURN_METHODS)[number]["value"]>("open_to_open")
  const [sortKey, setSortKey] = useState<SortKey>("evidence_score")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const { data, isLoading, error } = useMethodEvaluation(engineHorizon, universe, 0, returnCalcMethod)

  const rows = useMemo(() => {
    const list = [...(data?.rows ?? [])]
    list.sort((a, b) => {
      const av = sortKey === "verdict" ? verdictRank(a.verdict) : a[sortKey] ?? Number.NEGATIVE_INFINITY
      const bv = sortKey === "verdict" ? verdictRank(b.verdict) : b[sortKey] ?? Number.NEGATIVE_INFINITY
      const delta = av - bv
      if (delta !== 0) return sortDir === "asc" ? delta : -delta
      return a.label.localeCompare(b.label)
    })
    return list
  }, [data?.rows, sortKey, sortDir])

  const counts = useMemo(() => {
    const out = { keep: 0, watch: 0, discard: 0, no_data: 0 }
    for (const row of data?.rows ?? []) {
      if (row.verdict === "keep") out.keep += 1
      else if (row.verdict === "watch") out.watch += 1
      else if (row.verdict === "discard") out.discard += 1
      else out.no_data += 1
    }
    return out
  }, [data?.rows])

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir("desc")
    }
  }

  const SortIcon = ({ column }: { column: SortKey }) => {
    if (column !== sortKey) return <ArrowUpDown className="h-3 w-3 opacity-40" />
    return sortDir === "desc" ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Segment label="Horizon" value={engineHorizon} options={HORIZONS} onChange={setEngineHorizon} />
        <Segment label="Univers" value={universe} options={UNIVERSES} onChange={setUniverse} />
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Rendement</span>
        <div className="inline-flex rounded-md border border-line bg-bg2 p-0.5">
          {RETURN_METHODS.map((method) => (
            <button
              key={method.value}
              type="button"
              onClick={() => setReturnCalcMethod(method.value)}
              className={cn(
                "rounded px-3 py-1 text-xs font-medium transition-colors",
                returnCalcMethod === method.value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {method.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-4">
        <SummaryCard label="A garder" value={counts.keep} tone="positive" />
        <SummaryCard label="A surveiller" value={counts.watch} tone="warning" />
        <SummaryCard label="A ecarter" value={counts.discard} tone="negative" />
        <SummaryCard label="Sans data" value={counts.no_data} />
      </div>

      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          Method evaluation failed: {String((error as Error).message ?? error)}
        </div>
      ) : null}

      {isLoading && !data ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, index) => <Skeleton key={index} className="h-10 w-full" />)}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line">
          <table className="claude-table">
            <thead>
              <tr>
                <Th>Methode</Th>
                <Th onClick={() => toggleSort("verdict")}>
                  <span className="flex items-center gap-1">Decision <SortIcon column="verdict" /></span>
                </Th>
                <Th onClick={() => toggleSort("coverage_pct")} className="r">
                  <span className="flex items-center justify-end gap-1">Elig. <SortIcon column="coverage_pct" /></span>
                </Th>
                <Th onClick={() => toggleSort("median_ic")} className="r">
                  <span className="flex items-center justify-end gap-1">IC med. <SortIcon column="median_ic" /></span>
                </Th>
                <Th onClick={() => toggleSort("median_sharpe")} className="r">
                  <span className="flex items-center justify-end gap-1">Sharpe <SortIcon column="median_sharpe" /></span>
                </Th>
                <Th onClick={() => toggleSort("median_hit_rate")} className="r">
                  <span className="flex items-center justify-end gap-1">Hit% <SortIcon column="median_hit_rate" /></span>
                </Th>
                <Th onClick={() => toggleSort("median_n")} className="r">
                  <span className="flex items-center justify-end gap-1">Obs <SortIcon column="median_n" /></span>
                </Th>
                <Th onClick={() => toggleSort("evidence_score")} className="r">
                  <span className="flex items-center justify-end gap-1">Score preuve <SortIcon column="evidence_score" /></span>
                </Th>
                <Th>Raison</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => <MethodRow key={row.source} row={row} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Segment<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
}) {
  return (
    <>
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
      <div className="inline-flex rounded-md border border-line bg-bg2 p-0.5">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={cn(
              "rounded px-3 py-1 text-xs font-medium transition-colors",
              value === option.value ? "bg-card text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        ))}
      </div>
    </>
  )
}

function SummaryCard({ label, value, tone }: { label: string; value: number; tone?: "positive" | "warning" | "negative" }) {
  return (
    <div className="rounded-md border border-line bg-card px-3 py-2">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn(
        "mt-1 font-mono text-xl font-semibold",
        tone === "positive" && "text-emerald-700",
        tone === "warning" && "text-amber-700",
        tone === "negative" && "text-red-700",
      )}>
        {value}
      </div>
    </div>
  )
}

function Th({ children, onClick, className = "" }: { children: React.ReactNode; onClick?: () => void; className?: string }) {
  return (
    <th onClick={onClick} className={cn(onClick && "cursor-pointer select-none hover:bg-muted/60", className)}>
      {children}
    </th>
  )
}

function MethodRow({ row }: { row: MethodEvaluationRow }) {
  return (
    <tr>
      <td>
        <div className="font-medium">{row.label}</div>
        <div className="font-mono text-[10px] text-muted-foreground">{row.source}</div>
      </td>
      <td>
        <span className={cn("inline-flex rounded border px-2 py-0.5 text-[11px] font-semibold", verdictClass(row.verdict))}>
          {verdictLabel(row.verdict)}
        </span>
      </td>
      <td className="r font-mono tabular-nums">
        {row.eligible_count}/{row.tested_count} <span className="text-muted-foreground">({fmtPct(row.coverage_pct)})</span>
      </td>
      <td className={cn("r font-mono tabular-nums", (row.median_ic ?? 0) > 0 ? "text-emerald-700" : (row.median_ic ?? 0) < 0 ? "text-red-700" : "text-muted-foreground")}>
        {fmtNumber(row.median_ic, 3)}
      </td>
      <td className={cn("r font-mono tabular-nums", (row.median_sharpe ?? 0) > 0 ? "text-emerald-700" : (row.median_sharpe ?? 0) < 0 ? "text-red-700" : "text-muted-foreground")}>
        {fmtNumber(row.median_sharpe, 2)}
      </td>
      <td className="r font-mono tabular-nums">{fmtHit(row.median_hit_rate)}</td>
      <td className="r font-mono tabular-nums text-muted-foreground">{fmtNumber(row.median_n, 0)}</td>
      <td className="r font-mono tabular-nums">{fmtNumber(row.evidence_score, 5)}</td>
      <td className="max-w-[320px] text-xs text-muted-foreground">
        {row.reason_codes.length ? row.reason_codes.map(reasonLabel).join(", ") : "--"}
      </td>
    </tr>
  )
}
