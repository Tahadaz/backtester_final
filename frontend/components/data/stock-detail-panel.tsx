"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import type {
  AvailabilityCalendar,
  MarketCatalogRow,
  OhlcvHistory,
} from "@/lib/api"
import { upsertOhlcvRow, deleteOhlcvRows } from "@/lib/api"
import {
  useStockAvailabilityCalendar,
  useStockOhlcvHistory,
  useStockOhlcvPreview,
} from "@/hooks/use-api"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { OhlcvHistoryChart } from "@/components/data/ohlcv-history-chart"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Check, ChevronLeft, ChevronRight, Pencil, Plus, Trash2, X } from "lucide-react"
import { toast } from "sonner"

type CalendarDay = AvailabilityCalendar["days"][number]

function formatCompactNumber(value?: number | null) {
  if (value == null) return "-"
  return value.toLocaleString()
}

function formatPrice(value?: number | null) {
  if (value == null) return "-"
  return value.toFixed(2)
}

function parseLocalDate(value: string) {
  const [year, month, day] = value.split("-").map(Number)
  return new Date(year, month - 1, day, 12, 0, 0, 0)
}

function formatDateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")}`
}

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
}

function buildMonthsInRange(firstDate?: string | null, lastDate?: string | null) {
  if (!firstDate || !lastDate) return []
  const first = parseLocalDate(firstDate)
  const last = parseLocalDate(lastDate)
  const months: string[] = []
  const cursor = new Date(first.getFullYear(), first.getMonth(), 1, 12)
  const end = new Date(last.getFullYear(), last.getMonth(), 1, 12)
  while (cursor <= end) {
    months.push(monthKey(cursor))
    cursor.setMonth(cursor.getMonth() + 1)
  }
  return months
}

function formatMonthLabel(value: string, locale: string = "fr-MA") {
  const [year, month] = value.split("-").map(Number)
  return new Date(year, month - 1, 1, 12).toLocaleString(locale, {
    month: "long",
    year: "numeric",
  })
}

function stateClasses(state: string) {
  switch (state) {
    case "present_data":
      return "border-emerald-300 bg-emerald-100 text-emerald-950"
    case "missing_expected_day":
      return "border-amber-400 bg-amber-100 text-amber-950"
    case "market_holiday":
      return "border-sky-300 bg-sky-100 text-sky-950"
    case "tentative_market_holiday":
      return "border-fuchsia-300 bg-fuchsia-100 text-fuchsia-950"
    case "weekend":
      return "border-slate-300 bg-slate-100 text-slate-700"
    default:
      return "border-dashed border-slate-200 bg-white text-slate-400"
  }
}

function stateLabel(day: CalendarDay) {
  if (day.holiday_name) {
    return day.holiday_certainty === "tentative" ? `Tentatif: ${day.holiday_name}` : day.holiday_name
  }
  if (day.state === "present_data") {
    if (day.missing_fields && day.missing_fields.length > 0) {
      return `Partiel: -${day.missing_fields.join(", -")}`
    }
    return "OHLCV"
  }
  if (day.state === "missing_expected_day") return "Manquant"
  if (day.state === "weekend") return "Weekend"
  return ""
}

function CalendarLegend() {
  const items = [
    { label: "Donnees presentes", classes: "bg-emerald-100 border-emerald-300" },
    { label: "Donnees partielles", classes: "bg-yellow-50 border-yellow-400" },
    { label: "Jour de bourse manquant", classes: "bg-amber-100 border-amber-400" },
    { label: "Weekend", classes: "bg-slate-100 border-slate-300" },
    { label: "Ferie confirme", classes: "bg-sky-100 border-sky-300" },
    { label: "Ferie tentatif", classes: "bg-fuchsia-100 border-fuchsia-300" },
    { label: "Hors plage", classes: "bg-white border-dashed border-slate-300" },
  ]

  return (
    <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5">
          <span className={`inline-flex h-3.5 w-3.5 rounded border ${item.classes}`} />
          <span>{item.label}</span>
        </div>
      ))}
    </div>
  )
}

function buildMonthSummaries(calendar: AvailabilityCalendar) {
  const summaries = new Map<
    string,
    {
      present: number
      partial: number
      missing: number
      holidays: number
      tentative: number
      weekend: number
    }
  >()

  for (const day of calendar.days) {
    const key = day.date.slice(0, 7)
    if (!summaries.has(key)) {
      summaries.set(key, {
        present: 0,
        partial: 0,
        missing: 0,
        holidays: 0,
        tentative: 0,
        weekend: 0,
      })
    }
    const summary = summaries.get(key)!
    if (day.state === "present_data") {
      summary.present += 1
      if (day.missing_fields && day.missing_fields.length > 0) summary.partial += 1
    }
    if (day.state === "missing_expected_day") summary.missing += 1
    if (day.state === "market_holiday") summary.holidays += 1
    if (day.state === "tentative_market_holiday") summary.tentative += 1
    if (day.state === "weekend") summary.weekend += 1
  }

  return summaries
}

function YearStripOverview({
  calendar,
  selectedMonth,
  onMonthChange,
}: {
  calendar: AvailabilityCalendar
  selectedMonth: string
  onMonthChange: (value: string) => void
}) {
  const months = useMemo(
    () => buildMonthsInRange(calendar.first_date, calendar.last_date),
    [calendar.first_date, calendar.last_date]
  )
  const summaries = useMemo(() => buildMonthSummaries(calendar), [calendar])
  const years = useMemo(
    () => Array.from(new Set(months.map((value) => value.slice(0, 4)))),
    [months]
  )
  const selectedYear = selectedMonth.slice(0, 4)
  const visibleMonths = months.filter((value) => value.startsWith(`${selectedYear}-`))

  function toneForMonth(value: string) {
    const summary = summaries.get(value)
    if (!summary) return "border-slate-200 text-slate-500"
    if (summary.missing > 0) return "border-amber-400 bg-amber-50 text-amber-950"
    if (summary.holidays > 0 || summary.tentative > 0) {
      return "border-sky-300 bg-sky-50 text-sky-950"
    }
    if (summary.present > 0) return "border-emerald-300 bg-emerald-50 text-emerald-950"
    return "border-slate-200 text-slate-500"
  }

  return (
    <div className="space-y-3 rounded-2xl border bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-sm font-semibold">Vue annuelle</h4>
          <p className="text-xs text-muted-foreground">
            Sautez d&apos;un mois a l&apos;autre pour reperer rapidement les trous.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {years.map((year) => {
            const yearMonths = months.filter((value) => value.startsWith(`${year}-`))
            const target = yearMonths[yearMonths.length - 1]
            return (
              <Button
                key={year}
                type="button"
                variant={year === selectedYear ? "default" : "outline"}
                size="sm"
                className="h-8"
                onClick={() => target && onMonthChange(target)}
              >
                {year}
              </Button>
            )
          })}
        </div>
      </div>

      <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
        {visibleMonths.map((value) => {
          const summary = summaries.get(value)
          return (
            <button
              key={value}
              type="button"
              onClick={() => onMonthChange(value)}
              className={[
                "rounded-xl border px-2 py-2 text-left transition hover:shadow-sm",
                value === selectedMonth ? "ring-2 ring-slate-900/10" : "",
                toneForMonth(value),
              ].join(" ")}
            >
              <div className="text-xs font-semibold capitalize">
                {formatMonthLabel(value, "fr-MA")}
              </div>
              <div className="mt-2 flex items-center gap-3 text-[11px]">
                <span>{summary?.present ?? 0} jrs</span>
                <span className="text-amber-800">{summary?.missing ?? 0} gap</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function AvailabilityCalendarView({
  calendar,
  selectedMonth,
  onMonthChange,
}: {
  calendar: AvailabilityCalendar
  selectedMonth: string
  onMonthChange: (value: string) => void
}) {
  const months = useMemo(
    () => buildMonthsInRange(calendar.first_date, calendar.last_date),
    [calendar.first_date, calendar.last_date]
  )
  const dayLookup = useMemo(
    () => new Map(calendar.days.map((day) => [day.date, day])),
    [calendar.days]
  )
  const monthSummaries = useMemo(() => buildMonthSummaries(calendar), [calendar])

  const [year, month] = selectedMonth.split("-").map(Number)
  const firstOfMonth = new Date(year, month - 1, 1, 12)
  const lastOfMonth = new Date(year, month, 0, 12)
  const startOffset = (firstOfMonth.getDay() + 6) % 7
  const endOffset = 6 - ((lastOfMonth.getDay() + 6) % 7)
  const gridStart = new Date(firstOfMonth)
  gridStart.setDate(firstOfMonth.getDate() - startOffset)
  const gridEnd = new Date(lastOfMonth)
  gridEnd.setDate(lastOfMonth.getDate() + endOffset)

  const cells: CalendarDay[] = []
  const cursor = new Date(gridStart)
  while (cursor <= gridEnd) {
    const key = formatDateKey(cursor)
    cells.push(
      dayLookup.get(key) ?? {
        date: key,
        state: "outside_series_range",
        has_data: false,
        holiday_name: null,
        holiday_certainty: null,
        missing_fields: [],
      }
    )
    cursor.setDate(cursor.getDate() + 1)
  }

  const monthIndex = months.indexOf(selectedMonth)
  const canGoPrev = monthIndex > 0
  const canGoNext = monthIndex >= 0 && monthIndex < months.length - 1
  const summary = monthSummaries.get(selectedMonth)

  return (
    <div className="space-y-4 rounded-2xl border bg-white p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h4 className="text-sm font-semibold">Calendrier de disponibilite</h4>
          <p className="text-xs text-muted-foreground">
            Les jours manquants attendus sont separes des weekends et fermetures de marche.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-8 w-8"
            onClick={() => canGoPrev && onMonthChange(months[monthIndex - 1])}
            disabled={!canGoPrev}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-44 text-center text-sm font-semibold capitalize">
            {formatMonthLabel(selectedMonth, "fr-MA")}
          </div>
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-8 w-8"
            onClick={() => canGoNext && onMonthChange(months[monthIndex + 1])}
            disabled={!canGoNext}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        <div className="rounded-xl border bg-slate-50 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">OHLCV</div>
          <div className="text-sm font-semibold">{summary?.present ?? 0}</div>
        </div>
        {(summary?.partial ?? 0) > 0 && (
          <div className="rounded-xl border border-yellow-300 bg-yellow-50 px-3 py-2">
            <div className="text-[11px] uppercase tracking-wide text-yellow-800">Partiels</div>
            <div className="text-sm font-semibold text-yellow-950">{summary?.partial ?? 0}</div>
          </div>
        )}
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-amber-800">Manquants</div>
          <div className="text-sm font-semibold text-amber-950">{summary?.missing ?? 0}</div>
        </div>
        <div className="rounded-xl border bg-slate-50 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Weekend</div>
          <div className="text-sm font-semibold">{summary?.weekend ?? 0}</div>
        </div>
        <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-sky-800">Feries</div>
          <div className="text-sm font-semibold text-sky-950">{summary?.holidays ?? 0}</div>
        </div>
        <div className="rounded-xl border border-fuchsia-200 bg-fuchsia-50 px-3 py-2">
          <div className="text-[11px] uppercase tracking-wide text-fuchsia-800">Tentatifs</div>
          <div className="text-sm font-semibold text-fuchsia-950">{summary?.tentative ?? 0}</div>
        </div>
      </div>

      <table className="w-full border-collapse text-[11px]">
        <thead>
          <tr>
            {["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"].map((name) => (
              <th key={name} className="border border-slate-200 bg-slate-50 px-1 py-1.5 text-center font-semibold text-muted-foreground">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: cells.length / 7 }, (_, w) => (
            <tr key={w}>
              {cells.slice(w * 7, w * 7 + 7).map((day) => {
                const current = parseLocalDate(day.date)
                const inMonth = current.getMonth() === firstOfMonth.getMonth()
                const isPartial = day.state === "present_data" && day.missing_fields && day.missing_fields.length > 0
                const titleParts = [day.date, day.state.replaceAll("_", " ")]
                if (isPartial) titleParts.push(`manque: ${day.missing_fields.join(", ")}`)
                if (day.holiday_name) titleParts.push(day.holiday_name)
                return (
                  <td
                    key={day.date}
                    title={titleParts.join(" | ")}
                    className={[
                      "h-12 border border-slate-200 p-1 align-top",
                      isPartial ? "bg-yellow-50 text-yellow-950" : stateClasses(day.state),
                      inMonth ? "" : "opacity-40",
                    ].join(" ")}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-semibold">{current.getDate()}</span>
                      {day.state === "missing_expected_day" && (
                        <span className="rounded-full bg-amber-500 px-1 text-[8px] font-semibold text-white">
                          GAP
                        </span>
                      )}
                      {isPartial && (
                        <span className="rounded-full bg-yellow-500 px-1 text-[8px] font-semibold text-white">
                          !
                        </span>
                      )}
                    </div>
                    <div className="mt-0.5 line-clamp-1 text-[9px] leading-3">{stateLabel(day)}</div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <CalendarLegend />
    </div>
  )
}

type DateRange = { from: string; to: string } | string

function collapseToRanges(
  dates: string[],
  calendarDays: AvailabilityCalendar["days"],
): DateRange[] {
  if (dates.length === 0) return []

  const nonTradingDays = new Set(
    calendarDays
      .filter((d) =>
        ["weekend", "market_holiday", "tentative_market_holiday"].includes(
          d.state,
        ),
      )
      .map((d) => d.date.slice(0, 10)),
  )

  const addDays = (iso: string, n: number) => {
    const d = new Date(iso + "T00:00:00")
    d.setDate(d.getDate() + n)
    return d.toISOString().slice(0, 10)
  }

  const isConsecutive = (a: string, b: string) => {
    let cursor = addDays(a, 1)
    while (cursor < b) {
      if (!nonTradingDays.has(cursor)) return false
      cursor = addDays(cursor, 1)
    }
    return cursor === b
  }

  const ranges: DateRange[] = []
  let rangeStart = dates[0]
  let rangeEnd = dates[0]

  for (let i = 1; i < dates.length; i++) {
    if (isConsecutive(rangeEnd, dates[i])) {
      rangeEnd = dates[i]
    } else {
      ranges.push(rangeStart === rangeEnd ? rangeStart : { from: rangeStart, to: rangeEnd })
      rangeStart = dates[i]
      rangeEnd = dates[i]
    }
  }
  ranges.push(rangeStart === rangeEnd ? rangeStart : { from: rangeStart, to: rangeEnd })
  return ranges
}

function formatRanges(ranges: DateRange[], limit: number): string {
  const parts = ranges.map((r) =>
    typeof r === "string" ? r : `du ${r.from} au ${r.to}`,
  )
  if (parts.length <= limit) return parts.join(", ")
  return `${parts.slice(0, limit).join(", ")} … et ${parts.length - limit} autres`
}

function DataQualityReport({ calendar, onFocusDates }: { calendar: AvailabilityCalendar; onFocusDates?: (dates: string[]) => void }) {
  const fieldGaps: Record<string, string[]> = {}
  const missingDays: string[] = []

  for (const day of calendar.days) {
    if (day.has_data && day.missing_fields && day.missing_fields.length > 0) {
      for (const field of day.missing_fields) {
        ;(fieldGaps[field] ??= []).push(day.date.slice(0, 10))
      }
    }
    if (day.state === "missing_expected_day") {
      missingDays.push(day.date.slice(0, 10))
    }
  }

  const fieldEntries = Object.entries(fieldGaps).sort((a, b) => b[1].length - a[1].length)
  const totalPartialDays = new Set(Object.values(fieldGaps).flat()).size
  const hasIssues = fieldEntries.length > 0 || missingDays.length > 0

  const [expanded, setExpanded] = useState(true)

  if (!hasIssues) {
    return (
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50/50 p-5">
        <h3 className="text-sm font-semibold text-emerald-900">
          Diagnostic qualite des donnees
        </h3>
        <p className="mt-1 text-sm text-emerald-700">
          Aucun probleme detecte — toutes les seances ont des donnees OHLCV completes.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-amber-200 bg-amber-50/30 p-5">
      <button
        className="flex w-full items-center justify-between text-left"
        onClick={() => setExpanded(!expanded)}
      >
        <h3 className="text-sm font-semibold text-amber-900">
          Diagnostic qualite des donnees
        </h3>
        <span className="text-xs text-amber-600">
          {expanded ? "Reduire" : "Developper"}
        </span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-4">
          {fieldEntries.length > 0 && (
            <div>
              <p className="text-sm font-medium text-amber-800">
                {totalPartialDays} seance{totalPartialDays > 1 ? "s" : ""} avec donnees
                partielles
              </p>
              <div className="mt-2 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-amber-200 text-left text-xs uppercase tracking-wide text-amber-700">
                      <th className="pb-2 pr-4">Champ manquant</th>
                      <th className="pb-2 pr-4">Nb</th>
                      <th className="pb-2">Dates</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fieldEntries.map(([field, dates]) => (
                      <tr key={field} className="border-b border-amber-100">
                        <td className="py-2 pr-4 font-medium capitalize">{field}</td>
                        <td className="py-2 pr-4 text-amber-700">{dates.length}</td>
                        <td className="py-2 text-xs text-amber-700">
                          {formatRanges(collapseToRanges(dates, calendar.days), 10)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {onFocusDates && (
                <button
                  className="mt-2 text-xs font-medium text-amber-700 underline hover:text-amber-900"
                  onClick={() => onFocusDates([...new Set(Object.values(fieldGaps).flat())])}
                >
                  Corriger dans le tableau
                </button>
              )}
            </div>
          )}

          {missingDays.length > 0 && (
            <div>
              <p className="text-sm font-medium text-amber-800">
                {missingDays.length} jour{missingDays.length > 1 ? "s" : ""} de bourse
                manquant{missingDays.length > 1 ? "s" : ""}
              </p>
              <p className="mt-1 text-xs text-amber-700">
                {formatRanges(collapseToRanges(missingDays, calendar.days), 10)}
              </p>
              {onFocusDates && (
                <button
                  className="mt-2 text-xs font-medium text-amber-700 underline hover:text-amber-900"
                  onClick={() => onFocusDates(missingDays)}
                >
                  Corriger dans le tableau
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function QuickFacts({ row, history }: { row: MarketCatalogRow; history?: OhlcvHistory }) {
  return (
    <div className="rounded-2xl border bg-slate-50/70 p-4">
      <h4 className="text-sm font-semibold">Resume</h4>
      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Debut</div>
          <div className="font-medium">{row.start_ts?.slice(0, 10) ?? "-"}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Fin</div>
          <div className="font-medium">{row.end_ts?.slice(0, 10) ?? "-"}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Barres</div>
          <div className="font-medium">{row.row_count?.toLocaleString() ?? "-"}</div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground">Source</div>
          <div className="font-medium">{history?.source_provider ?? row.source_provider ?? "-"}</div>
        </div>
      </div>
    </div>
  )
}

export function StockDetailPanel({
  row,
  open,
  onClose,
  onSaved,
}: {
  row: MarketCatalogRow | null
  open: boolean
  onClose: () => void
  onSaved: () => void
}) {
  const symbol = row?.symbol ?? null
  const { data: preview, isLoading: previewLoading, mutate: mutatePreview } = useStockOhlcvPreview(open ? symbol : null, {
    limit: 10,
  })
  const { data: history, isLoading: historyLoading, mutate: mutateHistory } = useStockOhlcvHistory(open ? symbol : null)
  const { data: calendar, isLoading: calendarLoading, mutate: mutateCalendar } = useStockAvailabilityCalendar(
    open ? symbol : null
  )

  const [editMode, setEditMode] = useState(false)
  const [editRow, setEditRow] = useState<Record<string, string> | null>(null)
  const [addingRow, setAddingRow] = useState(false)
  const [newRow, setNewRow] = useState({ date: "", open: "", high: "", low: "", close: "", volume: "" })
  const [focusDates, setFocusDates] = useState<string[] | null>(null)

  const refreshAll = useCallback(() => {
    mutatePreview(); mutateHistory(); mutateCalendar(); onSaved()
  }, [mutatePreview, mutateHistory, mutateCalendar, onSaved])

  const handleFocusDates = useCallback((dates: string[]) => {
    setFocusDates(dates)
    setEditMode(true)
    setEditRow(null)
    setAddingRow(false)
  }, [])

  type Bar = { date: string; open?: number | null; high?: number | null; low?: number | null; close?: number | null; volume?: number | null }
  const displayBars: Bar[] = useMemo(() => {
    if (!focusDates) return preview?.bars.slice(0, 10) ?? []
    const focusSet = new Set(focusDates)
    const histBars = history?.bars ?? []
    // Build date→index map for neighbor lookup
    const dateIdx = new Map(histBars.map((b, i) => [b.date.slice(0, 10), i]))
    const resultSet = new Map<string, Bar>()
    for (const d of focusDates) {
      const idx = dateIdx.get(d)
      if (idx !== undefined) {
        // Add bar + neighbors
        if (idx > 0) { const b = histBars[idx - 1]; resultSet.set(b.date.slice(0, 10), b) }
        resultSet.set(d, histBars[idx])
        if (idx < histBars.length - 1) { const b = histBars[idx + 1]; resultSet.set(b.date.slice(0, 10), b) }
      } else {
        // Missing day — create placeholder
        resultSet.set(d, { date: d, open: null, high: null, low: null, close: null, volume: null })
        // Find nearest neighbor for context
        const sorted = histBars.map((b) => b.date.slice(0, 10))
        let insertIdx = sorted.findIndex((s) => s > d)
        if (insertIdx === -1) insertIdx = sorted.length
        if (insertIdx > 0) { const b = histBars[insertIdx - 1]; resultSet.set(b.date.slice(0, 10), b) }
        if (insertIdx < histBars.length) { const b = histBars[insertIdx]; resultSet.set(b.date.slice(0, 10), b) }
      }
    }
    return [...resultSet.values()]
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(0, 30)
  }, [focusDates, preview, history])

  const focusDateSet = useMemo(() => new Set(focusDates ?? []), [focusDates])
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null)

  useEffect(() => {
    if (!calendar) return
    const defaultMonth = calendar.default_month?.slice(0, 7)
    const lastMonth = calendar.last_date?.slice(0, 7)
    setSelectedMonth(defaultMonth ?? lastMonth ?? null)
  }, [calendar?.symbol, calendar?.default_month, calendar?.last_date])

  return (
    <Sheet open={open} onOpenChange={(value) => !value && onClose()}>
      <SheetContent side="right" className="w-full max-w-5xl gap-0 overflow-hidden p-0">
        {row && (
          <>
            <div className="shrink-0 border-b bg-slate-50/80 px-6 py-5">
              <SheetHeader className="gap-3 p-0 text-left">
                <div className="flex flex-wrap items-center gap-3">
                  <SheetTitle className="text-2xl font-semibold tracking-tight">
                    {row.symbol}
                  </SheetTitle>
                  {row.is_tracked && <Badge variant="outline">Tracked</Badge>}
                  {row.source_provider && (
                    <Badge variant="secondary" className="capitalize">
                      {row.source_provider}
                    </Badge>
                  )}
                </div>
                <SheetDescription className="max-w-3xl text-sm">
                  Historique complet OHLCV avec chandelier, volume et calendrier de disponibilite
                  des seances.
                </SheetDescription>
              </SheetHeader>

              <div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
                <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
                  <div>
                    <span className="font-medium text-slate-900">Derniere barre:</span>{" "}
                    {history?.data_as_of ?? row.end_ts?.slice(0, 10) ?? "-"}
                  </div>
                  <div>
                    <span className="font-medium text-slate-900">Historique:</span>{" "}
                    {history?.row_count?.toLocaleString() ?? row.row_count?.toLocaleString() ?? "-"}
                  </div>
                </div>
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto bg-slate-100/60 px-6 py-6">
              <div className="mx-auto max-w-[1500px] space-y-6">
                <QuickFacts row={row} history={history} />

                <div className="rounded-2xl border bg-white p-5">
                  <div className="mb-4">
                    <h3 className="text-sm font-semibold">Chandelier complet</h3>
                    <p className="text-xs text-muted-foreground">
                      Vue initiale sur les 12 derniers mois avec zoom libre sur tout l&apos;historique.
                    </p>
                  </div>
                  {historyLoading ? (
                    <Skeleton className="h-[520px] w-full" />
                  ) : history && history.bars.length > 0 ? (
                    <OhlcvHistoryChart history={history} />
                  ) : (
                    <p className="text-sm text-muted-foreground">Aucun historique OHLCV disponible.</p>
                  )}
                </div>

                {calendarLoading ? (
                  <Skeleton className="h-[680px] w-full rounded-2xl" />
                ) : calendar && selectedMonth ? (
                  <div className="space-y-4">
                    <YearStripOverview
                      calendar={calendar}
                      selectedMonth={selectedMonth}
                      onMonthChange={setSelectedMonth}
                    />
                    <AvailabilityCalendarView
                      calendar={calendar}
                      selectedMonth={selectedMonth}
                      onMonthChange={setSelectedMonth}
                    />
                  </div>
                ) : (
                  <div className="rounded-2xl border bg-white p-5">
                    <p className="text-sm text-muted-foreground">
                      Aucun calendrier de disponibilite disponible.
                    </p>
                  </div>
                )}

                {calendar && <DataQualityReport calendar={calendar} onFocusDates={handleFocusDates} />}

                <div className="rounded-2xl border bg-white p-5">
                  <div className="mb-4 flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold">
                        {focusDates ? "Donnees a corriger" : "Dernieres barres OHLCV"}
                      </h3>
                      <p className="text-xs text-muted-foreground">
                        {focusDates
                          ? `${focusDates.length} date${focusDates.length > 1 ? "s" : ""} avec problemes`
                          : "Tableau de controle pour verifier rapidement les dernieres seances."}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {focusDates && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => { setFocusDates(null); setEditMode(false); setEditRow(null); setAddingRow(false) }}
                        >
                          Retour
                        </Button>
                      )}
                      {(preview?.bars.length ?? 0) > 0 && (
                        <Button
                          variant={editMode ? "default" : "outline"}
                          size="sm"
                          onClick={() => { setEditMode(!editMode); setEditRow(null); setAddingRow(false) }}
                        >
                          <Pencil className="mr-1 h-3 w-3" />
                          {editMode ? "Terminer" : "Editer"}
                        </Button>
                      )}
                    </div>
                  </div>
                  {previewLoading ? (
                    <div className="space-y-2">
                      {[...Array(5)].map((_, i) => (
                        <Skeleton key={i} className="h-8 w-full" />
                      ))}
                    </div>
                  ) : displayBars.length > 0 ? (
                    <>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Date</TableHead>
                          <TableHead className="text-right">O</TableHead>
                          <TableHead className="text-right">H</TableHead>
                          <TableHead className="text-right">L</TableHead>
                          <TableHead className="text-right">C</TableHead>
                          <TableHead className="text-right">Vol</TableHead>
                          {editMode && <TableHead className="w-20" />}
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {displayBars.map((bar) => {
                          const dateKey = bar.date.slice(0, 10)
                          const isEditing = editRow?.date === dateKey
                          if (isEditing) {
                            return (
                              <TableRow key={dateKey} className="bg-blue-50/50">
                                <TableCell className="font-medium">{dateKey}</TableCell>
                                {["open", "high", "low", "close", "volume"].map((f) => (
                                  <TableCell key={f} className="p-1">
                                    <input
                                      type="number"
                                      step="any"
                                      className="w-full rounded border px-2 py-1 text-right text-sm"
                                      value={editRow[f] ?? ""}
                                      onChange={(e) => setEditRow({ ...editRow, [f]: e.target.value })}
                                    />
                                  </TableCell>
                                ))}
                                <TableCell className="flex gap-1 p-1">
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7 text-emerald-600"
                                    onClick={async () => {
                                      if (!symbol) return
                                      try {
                                        await upsertOhlcvRow(symbol, {
                                          date: dateKey,
                                          open: editRow.open ? Number(editRow.open) : undefined,
                                          high: editRow.high ? Number(editRow.high) : undefined,
                                          low: editRow.low ? Number(editRow.low) : undefined,
                                          close: editRow.close ? Number(editRow.close) : undefined,
                                          volume: editRow.volume ? Number(editRow.volume) : undefined,
                                        })
                                        toast.success(`${dateKey} mis a jour`)
                                        setEditRow(null)
                                        refreshAll()
                                      } catch (err: unknown) {
                                        toast.error(`Echec: ${err instanceof Error ? err.message : "Erreur"}`)
                                      }
                                    }}
                                  >
                                    <Check className="h-4 w-4" />
                                  </Button>
                                  <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setEditRow(null)}>
                                    <X className="h-4 w-4" />
                                  </Button>
                                </TableCell>
                              </TableRow>
                            )
                          }
                          const isFocused = focusDateSet.has(dateKey)
                          const isPlaceholder = bar.open == null && bar.high == null && bar.low == null && bar.close == null
                          return (
                            <TableRow key={dateKey} className={isFocused ? (isPlaceholder ? "bg-red-50" : "bg-amber-50") : ""}>
                              <TableCell className={isFocused ? "font-medium" : ""}>{dateKey}</TableCell>
                              <TableCell className="text-right">{formatPrice(bar.open)}</TableCell>
                              <TableCell className="text-right">{formatPrice(bar.high)}</TableCell>
                              <TableCell className="text-right">{formatPrice(bar.low)}</TableCell>
                              <TableCell className="text-right">{formatPrice(bar.close)}</TableCell>
                              <TableCell className="text-right">{formatCompactNumber(bar.volume)}</TableCell>
                              {editMode && (
                                <TableCell className="flex gap-1 p-1">
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7"
                                    onClick={() =>
                                      setEditRow({
                                        date: dateKey,
                                        open: bar.open != null ? String(bar.open) : "",
                                        high: bar.high != null ? String(bar.high) : "",
                                        low: bar.low != null ? String(bar.low) : "",
                                        close: bar.close != null ? String(bar.close) : "",
                                        volume: bar.volume != null ? String(bar.volume) : "",
                                      })
                                    }
                                  >
                                    <Pencil className="h-3 w-3" />
                                  </Button>
                                  <Button
                                    size="icon"
                                    variant="ghost"
                                    className="h-7 w-7 text-red-500"
                                    onClick={async () => {
                                      if (!symbol || !confirm(`Supprimer la barre du ${dateKey} ?`)) return
                                      try {
                                        await deleteOhlcvRows(symbol, [dateKey])
                                        toast.success(`${dateKey} supprime`)
                                        refreshAll()
                                      } catch (err: unknown) {
                                        toast.error(`Echec: ${err instanceof Error ? err.message : "Erreur"}`)
                                      }
                                    }}
                                  >
                                    <Trash2 className="h-3 w-3" />
                                  </Button>
                                </TableCell>
                              )}
                            </TableRow>
                          )
                        })}
                        {editMode && addingRow && (
                          <TableRow className="bg-emerald-50/50">
                            <TableCell className="p-1">
                              <input
                                type="date"
                                className="w-full rounded border px-2 py-1 text-sm"
                                value={newRow.date}
                                onChange={(e) => setNewRow({ ...newRow, date: e.target.value })}
                              />
                            </TableCell>
                            {(["open", "high", "low", "close", "volume"] as const).map((f) => (
                              <TableCell key={f} className="p-1">
                                <input
                                  type="number"
                                  step="any"
                                  placeholder={f === "close" ? "requis" : ""}
                                  className="w-full rounded border px-2 py-1 text-right text-sm"
                                  value={newRow[f]}
                                  onChange={(e) => setNewRow({ ...newRow, [f]: e.target.value })}
                                />
                              </TableCell>
                            ))}
                            <TableCell className="flex gap-1 p-1">
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-7 w-7 text-emerald-600"
                                onClick={async () => {
                                  if (!symbol || !newRow.date) return
                                  try {
                                    await upsertOhlcvRow(symbol, {
                                      date: newRow.date,
                                      open: newRow.open ? Number(newRow.open) : undefined,
                                      high: newRow.high ? Number(newRow.high) : undefined,
                                      low: newRow.low ? Number(newRow.low) : undefined,
                                      close: newRow.close ? Number(newRow.close) : undefined,
                                      volume: newRow.volume ? Number(newRow.volume) : undefined,
                                    })
                                    toast.success(`Barre ${newRow.date} ajoutee`)
                                    setNewRow({ date: "", open: "", high: "", low: "", close: "", volume: "" })
                                    setAddingRow(false)
                                    refreshAll()
                                  } catch (err: unknown) {
                                    toast.error(`Echec: ${err instanceof Error ? err.message : "Erreur"}`)
                                  }
                                }}
                              >
                                <Check className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="h-7 w-7"
                                onClick={() => {
                                  setAddingRow(false)
                                  setNewRow({ date: "", open: "", high: "", low: "", close: "", volume: "" })
                                }}
                              >
                                <X className="h-4 w-4" />
                              </Button>
                            </TableCell>
                          </TableRow>
                        )}
                      </TableBody>
                    </Table>
                    {editMode && !addingRow && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="mt-3"
                        onClick={() => setAddingRow(true)}
                      >
                        <Plus className="mr-1 h-3 w-3" />
                        Ajouter une barre
                      </Button>
                    )}
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">Aucune barre OHLCV disponible.</p>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
