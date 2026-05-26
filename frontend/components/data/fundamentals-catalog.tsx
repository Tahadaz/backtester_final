"use client"

import { useMemo, useRef, useState } from "react"
import useSWR from "swr"
import { Eye, FileSpreadsheet, KeyRound, LinkIcon, RefreshCw, Search, TableProperties } from "lucide-react"
import { toast } from "sonner"
import {
  getFundamentalCoverage,
  getFundamentalProviderStatus,
  getFundamentalStockDetail,
  refreshStockanalysisFundamentals,
  refreshTargetedBvcFundamentals,
  refreshYfinanceFundamentals,
  uploadFundamentalsWorkbook,
  type FundamentalAnnualMetric,
  type FundamentalCoverageRow,
  type FundamentalProviderStatus,
  type FundamentalStockDetail,
} from "@/lib/api"
import {
  FINANCIAL_STATEMENT_TABS,
  availableFinancialPeriodTypes,
  buildFinancialStatementTable,
  buildFinancialSummary,
  financialPeriodLabel,
} from "@/lib/fundamental-statement-utils.js"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { FreshnessBadge } from "@/components/data/freshness-badge"

type FundamentalFinancialTab = "summary" | "income" | "balance" | "cashflow" | "ratios" | "dividends" | "earnings"

const FINANCIAL_TABS = FINANCIAL_STATEMENT_TABS as Array<{ value: FundamentalFinancialTab; label: string }>

const REGIONS = [
  { key: "us", label: "Etats-Unis" },
  { key: "european", label: "Europe" },
  { key: "asian", label: "Asie" },
]

function dateOnly(value: string | null | undefined) {
  return value ? value.slice(0, 10) : null
}

function formatCount(value: number | null | undefined) {
  return value == null ? "-" : value.toLocaleString("fr-FR")
}

function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { maximumFractionDigits: digits })
}

function fmtValue(value: unknown): string {
  if (value == null) return "-"
  if (typeof value === "number") return fmtNumber(value, Math.abs(value) >= 1000 ? 0 : 3)
  if (typeof value === "string" || typeof value === "boolean") return String(value)
  return JSON.stringify(value)
}

function sourceLabel(value: string | null | undefined) {
  if (value === "stockanalysis") return "StockAnalysis"
  if (value === "yfinance") return "yfinance"
  if (value === "bvc") return "BVC"
  if (value === "workbook") return "Classeur"
  return value || "-"
}

function periodLabel(period: string) {
  if (period === "latest") return "Snapshot recent"
  if (period === "annual") return "Annuel"
  if (period === "semiannual") return "Semestriel"
  if (period === "quarterly") return "Trimestriel"
  return period
}

function yearRange(years: number[]) {
  if (years.length === 0) return "-"
  const sorted = [...years].sort((a, b) => a - b)
  const first = sorted[0]
  const last = sorted.at(-1)
  return first === last ? String(first) : `${first}-${last}`
}

function rowMatches(row: FundamentalCoverageRow, query: string) {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [
    row.symbol,
    row.display_name,
    row.sector,
    row.market_region,
    row.data_source,
    row.source_universe,
    row.available_periods.join(" "),
  ].some((value) => (value ?? "").toLowerCase().includes(q))
}

function parseListInput(value: string) {
  return value
    .split(/[\n,;]/g)
    .map((item) => item.trim())
    .filter(Boolean)
}

function canTargetBvc(row: FundamentalCoverageRow) {
  if (row.symbol === "INSTRUMENT" || row.symbol === "MAJ") return false
  if (row.market_region && row.market_region !== "masi") return false
  return true
}

function RawDataKpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="claude-stat">
      <div className="lbl">{label}</div>
      <div className="val">{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </div>
  )
}

function DatasetBadges({ row }: { row: FundamentalCoverageRow }) {
  const periods = row.available_periods.length
    ? row.available_periods
    : [
        row.has_snapshot ? "latest" : null,
        row.has_annual ? "annual" : null,
      ].filter((value): value is string => Boolean(value))

  if (periods.length === 0) {
    return <Badge variant="outline" className="text-[10px] text-muted-foreground">Aucune donnee financiere</Badge>
  }

  return (
    <div className="flex flex-wrap gap-1">
      {periods.map((period) => (
        <Badge key={period} variant="outline" className="text-[10px]">
          {periodLabel(period)}
        </Badge>
      ))}
    </div>
  )
}

function metricNamesFromAnnual(annual: FundamentalAnnualMetric[]) {
  const names = new Set<string>()
  for (const row of annual) {
    for (const [metric, value] of Object.entries(row.metrics)) {
      if (value != null) names.add(metric)
    }
  }
  return Array.from(names).sort((a, b) => a.localeCompare(b))
}

function annualRowsWithData(annual: FundamentalAnnualMetric[]) {
  return annual.filter((row) => Object.values(row.metrics).some((value) => value != null))
}

function annualRawRowsWithData(detail: FundamentalStockDetail) {
  return detail.annual_raw.filter((row) => row.metric_value != null)
}

function AnnualRawRowsTable({ detail }: { detail: FundamentalStockDetail }) {
  const rows = useMemo(() => annualRawRowsWithData(detail), [detail])
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <Table className="claude-table min-w-[920px]">
        <TableHeader>
          <TableRow>
            <TableHead>Annee</TableHead>
            <TableHead>Metrique</TableHead>
            <TableHead className="text-right">Valeur</TableHead>
            <TableHead>Libelle brut</TableHead>
            <TableHead>Feuille source</TableHead>
            <TableHead>Champ source</TableHead>
            <TableHead>Proxy</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="py-8 text-center text-sm text-muted-foreground">
                Aucune ligne annuelle detaillee disponible.
              </TableCell>
            </TableRow>
          ) : rows.map((row, index) => (
            <TableRow key={`${row.statement_year}-${row.metric_name}-${index}`}>
              <TableCell className="font-mono">{row.statement_year}</TableCell>
              <TableCell className="font-mono text-xs">{row.metric_name}</TableCell>
              <TableCell className="text-right font-mono">{fmtValue(row.metric_value)}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.raw_metric_name ?? "-"}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.source_sheet ?? "-"}</TableCell>
              <TableCell className="text-xs text-muted-foreground">{row.source_field ?? "-"}</TableCell>
              <TableCell>{row.is_proxy ? "Oui" : "Non"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function fmtFinancialValue(value: number | null | undefined, format?: string) {
  if (value == null || Number.isNaN(value)) return "-"
  if (format === "percent") {
    const pct = Math.abs(value) <= 2 ? value * 100 : value
    return `${fmtNumber(pct, Math.abs(pct) >= 100 ? 1 : 2)}%`
  }
  if (format === "ratio") return `${fmtNumber(value, Math.abs(value) >= 100 ? 1 : 2)}x`
  if (format === "per_share") return fmtNumber(value, 3)
  return fmtNumber(value, Math.abs(value) >= 1000 ? 0 : 2)
}

function FinancialStatementTable({
  table,
  emptyLabel,
}: {
  table: {
    periods: Array<{ key: string; label: string; subLabel?: string | null }>
    rows: Array<{
      key: string
      label: string
      format?: string
      section?: string | null
      values: Array<{ periodKey: string; value: number | null; sourceMetric?: string | null }>
    }>
  }
  emptyLabel: string
}) {
  let previousSection: string | null = null
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <Table className="claude-table min-w-[760px]">
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 bg-card">Ligne</TableHead>
            {table.periods.map((period) => (
              <TableHead key={period.key} className="text-right">
                <div>{period.label}</div>
                {period.subLabel ? <div className="text-[10px] font-normal text-muted-foreground">{period.subLabel}</div> : null}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {table.rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={table.periods.length + 1} className="py-8 text-center text-sm text-muted-foreground">
                {emptyLabel}
              </TableCell>
            </TableRow>
          ) : table.rows.flatMap((row) => {
            const sectionChanged = row.section && row.section !== previousSection
            previousSection = row.section ?? previousSection
            const metricRow = (
              <TableRow key={row.key}>
                <TableCell className="sticky left-0 bg-card font-medium">{row.label}</TableCell>
                {row.values.map((item) => (
                  <TableCell key={`${row.key}-${item.periodKey}`} className="text-right font-mono">
                    {fmtFinancialValue(item.value, row.format)}
                  </TableCell>
                ))}
              </TableRow>
            )
            return sectionChanged
              ? [
                  <TableRow key={`${row.key}-section`} className="bg-bg2">
                    <TableCell colSpan={table.periods.length + 1} className="py-2 text-[11px] font-bold uppercase text-muted-foreground">
                      {row.section}
                    </TableCell>
                  </TableRow>,
                  metricRow,
                ]
              : [metricRow]
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function FinancialSummary({
  detail,
  periodType,
}: {
  detail: FundamentalStockDetail
  periodType: string
}) {
  const summary = useMemo(() => buildFinancialSummary(detail, periodType), [detail, periodType])
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {summary.keyRatios.length === 0 ? (
          <RawDataKpi label="Resume financier" value="-" sub="Aucune metrique de synthese disponible" />
        ) : summary.keyRatios.map((item: { key: string; label: string; value: number | null; format?: string; sourceMetric?: string | null }) => (
          <RawDataKpi
            key={item.key}
            label={item.label}
            value={fmtFinancialValue(item.value, item.format)}
            sub={item.sourceMetric ?? undefined}
          />
        ))}
      </div>
      <div>
        <div className="mb-2 text-sm font-semibold">Points cles des etats financiers</div>
        <FinancialStatementTable table={summary.highlights} emptyLabel="Aucun point cle disponible." />
      </div>
    </div>
  )
}

function StatementContent({
  detail,
  tab,
  periodType,
}: {
  detail: FundamentalStockDetail
  tab: FundamentalFinancialTab
  periodType: string
}) {
  const table = useMemo(() => buildFinancialStatementTable(detail, tab, periodType), [detail, tab, periodType])
  return <FinancialStatementTable table={table} emptyLabel={`Aucune donnee disponible pour ${FINANCIAL_TABS.find((item) => item.value === tab)?.label ?? "les etats financiers"}.`} />
}

function FinancialLineage({ detail }: { detail: FundamentalStockDetail }) {
  const annualRows = annualRowsWithData(detail.annual)
  const rawRows = annualRawRowsWithData(detail)
  const metricNames = metricNamesFromAnnual(annualRows)
  const annualYears = annualRows.map((row) => row.statement_year).sort((a, b) => a - b)
  const latestCount = Object.keys(detail.metrics).length
  const priceAsOf = typeof detail.coverage.price_as_of === "string" ? detail.coverage.price_as_of : null
  const priceSource = typeof detail.coverage.price_source_provider === "string"
    ? detail.coverage.price_source_provider
    : typeof detail.coverage.price_source === "string"
      ? detail.coverage.price_source
      : undefined

  return (
    <details className="rounded-md border border-line bg-bg2 p-3">
      <summary className="cursor-pointer text-sm font-semibold">Diagnostics et lignes source</summary>
      <div className="mt-3 space-y-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <RawDataKpi label="Cours actuel" value={fmtValue(detail.metrics.Current_Price)} sub={priceAsOf ? `au ${priceAsOf}` : priceSource} />
          <RawDataKpi label="Metriques recentes" value={formatCount(latestCount)} sub={`Ex. ${detail.latest_statement_year ?? "-"}`} />
          <RawDataKpi label="Exercices annuels" value={formatCount(annualYears.length)} sub={yearRange(annualYears)} />
          <RawDataKpi label="Lignes source" value={formatCount(rawRows.length)} sub={`${formatCount(metricNames.length)} noms uniques`} />
          <RawDataKpi label="Source" value={sourceLabel(detail.data_source)} sub={dateOnly(detail.imported_at) ?? "Aucune date d'import"} />
        </div>

        {detail.coverage && Object.keys(detail.coverage).length > 0 ? (
          <div className="rounded-md border border-line bg-card p-3">
            <div className="text-sm font-semibold">Metadonnees de couverture</div>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-mono text-[11px] text-muted-foreground">
              {JSON.stringify(detail.coverage, null, 2)}
            </pre>
          </div>
        ) : null}

        <AnnualRawRowsTable detail={detail} />
      </div>
    </details>
  )
}

function FinancialFundamentalDetailContent({
  detail,
  tab,
  onTabChange,
  periodType,
  onPeriodTypeChange,
}: {
  detail: FundamentalStockDetail
  tab: FundamentalFinancialTab
  onTabChange: (tab: FundamentalFinancialTab) => void
  periodType: string
  onPeriodTypeChange: (periodType: string) => void
}) {
  const periodTypes = useMemo(() => availableFinancialPeriodTypes(detail), [detail]) as string[]
  const activePeriodType = periodTypes.includes(periodType) ? periodType : periodTypes[0] ?? "annual"
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="seg w-fit max-w-full overflow-x-auto">
          {FINANCIAL_TABS.map((item) => (
            <button key={item.value} type="button" className={tab === item.value ? "active" : ""} onClick={() => onTabChange(item.value)}>
              {item.label}
            </button>
          ))}
        </div>
        <div className="seg w-fit max-w-full overflow-x-auto">
          {periodTypes.map((item) => (
            <button key={item} type="button" className={activePeriodType === item ? "active" : ""} onClick={() => onPeriodTypeChange(item)}>
              {financialPeriodLabel(item)}
            </button>
          ))}
        </div>
      </div>

      {tab === "summary" ? <FinancialSummary detail={detail} periodType={activePeriodType} /> : <StatementContent detail={detail} tab={tab} periodType={activePeriodType} />}
      <FinancialLineage detail={detail} />
    </div>
  )
}

function FinancialFundamentalDetailSheet({
  symbol,
  detail,
  isLoading,
  error,
  tab,
  onTabChange,
  periodType,
  onPeriodTypeChange,
  onClose,
}: {
  symbol: string | null
  detail: FundamentalStockDetail | null | undefined
  isLoading: boolean
  error: unknown
  tab: FundamentalFinancialTab
  onTabChange: (tab: FundamentalFinancialTab) => void
  periodType: string
  onPeriodTypeChange: (periodType: string) => void
  onClose: () => void
}) {
  const title = detail?.display_name ?? detail?.company_name ?? symbol ?? "Titre"
  const importedAt = dateOnly(detail?.imported_at)

  return (
    <Sheet open={symbol !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full max-w-6xl gap-0 overflow-hidden p-0">
        <SheetHeader className="border-b border-line bg-card px-6 py-5 pr-12">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <SheetTitle className="flex items-center gap-2 text-lg">
                <TableProperties className="h-5 w-5 text-primary" />
                <span className="font-mono">{symbol}</span>
                <span className="text-foreground">{title !== symbol ? title : ""}</span>
              </SheetTitle>
              <SheetDescription>
                Etats financiers - {detail?.sector ?? "Aucun secteur"}
              </SheetDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline" className="text-[10px]">{sourceLabel(detail?.data_source)}</Badge>
              {importedAt ? <FreshnessBadge dataAsOf={importedAt} /> : <Badge variant="outline" className="text-[10px]">Aucun import</Badge>}
            </div>
          </div>
        </SheetHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          {isLoading ? (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-24 w-full" />)}
              </div>
              <Skeleton className="h-80 w-full" />
            </div>
          ) : error ? (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-4 text-sm text-destructive">
              Impossible de charger les donnees financieres de {symbol}.
            </div>
          ) : detail ? (
            <FinancialFundamentalDetailContent
              detail={detail}
              tab={tab}
              onTabChange={onTabChange}
              periodType={periodType}
              onPeriodTypeChange={onPeriodTypeChange}
            />
          ) : (
            <div className="rounded-md border border-line bg-bg2 px-3 py-4 text-sm text-muted-foreground">
              Aucune donnee d'etats financiers disponible.
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

export function FundamentalsCatalog() {
  const { data, error, isLoading, mutate } = useSWR(
    "/fundamentals/coverage",
    getFundamentalCoverage,
    { refreshInterval: 30_000, revalidateOnFocus: true },
  )
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [query, setQuery] = useState("")
  const [refreshOpen, setRefreshOpen] = useState(false)
  const [bvcOpen, setBvcOpen] = useState(false)
  const [regions, setRegions] = useState<string[]>(["us", "european", "asian"])
  const [uploading, setUploading] = useState(false)
  const [refreshing, setRefreshing] = useState<string | null>(null)
  const [inspectedSymbol, setInspectedSymbol] = useState<string | null>(null)
  const [detailSymbol, setDetailSymbol] = useState<string | null>(null)
  const [selectedBackfillSymbols, setSelectedBackfillSymbols] = useState<Set<string>>(() => new Set())
  const [detailTab, setDetailTab] = useState<FundamentalFinancialTab>("summary")
  const [detailPeriodType, setDetailPeriodType] = useState("annual")
  const [bvcSourceUrls, setBvcSourceUrls] = useState("")
  const [bvcSymbols, setBvcSymbols] = useState("")
  const [bvcSectors, setBvcSectors] = useState<string[]>([])
  const [bvcPeriodTypes, setBvcPeriodTypes] = useState<string[]>(["annual"])
  const [bvcStartYear, setBvcStartYear] = useState("")
  const [bvcEndYear, setBvcEndYear] = useState("")
  const [bvcDryRun, setBvcDryRun] = useState(false)
  const [bvcForce, setBvcForce] = useState(false)

  const {
    data: selectedDetail,
    error: selectedDetailError,
    isLoading: isSelectedDetailLoading,
    mutate: mutateSelectedDetail,
  } = useSWR<FundamentalStockDetail | null>(
    detailSymbol ? `/fundamentals/stocks/${detailSymbol}` : null,
    () => (detailSymbol ? getFundamentalStockDetail(detailSymbol) : Promise.resolve(null)),
    { revalidateOnFocus: true },
  )
  const { data: providerStatus } = useSWR<FundamentalProviderStatus | null>(
    bvcOpen ? "/fundamentals/providers/status" : null,
    () => getFundamentalProviderStatus(),
    { revalidateOnFocus: true },
  )

  const rows = useMemo(
    () =>
      (data ?? [])
        .filter((row) => rowMatches(row, query))
        .sort((a, b) => {
          const importDelta = (dateOnly(b.last_imported_at) ?? "").localeCompare(dateOnly(a.last_imported_at) ?? "")
          if (importDelta !== 0) return importDelta
          return a.symbol.localeCompare(b.symbol)
        }),
    [data, query],
  )

  const stats = useMemo(() => {
    const sourceRows = data ?? []
    const latestSnapshots = sourceRows.filter((row) => row.has_snapshot).length
    const annualSymbols = sourceRows.filter((row) => row.has_annual).length
    const annualMetrics = sourceRows.reduce((sum, row) => sum + row.annual_metric_count, 0)
    const periodMetrics = sourceRows.reduce((sum, row) => sum + row.period_metric_count, 0)
    const latestMetrics = sourceRows.reduce((sum, row) => sum + row.latest_metric_count, 0)
    return {
      symbols: sourceRows.length,
      latestSnapshots,
      annualSymbols,
      rawPoints: Math.max(annualMetrics, periodMetrics) + latestMetrics,
    }
  }, [data])

  const targetableRows = useMemo(() => rows.filter(canTargetBvc), [rows])
  const allTargetableSelected = targetableRows.length > 0 && targetableRows.every((row) => selectedBackfillSymbols.has(row.symbol))
  const inspectedRow = useMemo(
    () => rows.find((row) => row.symbol === inspectedSymbol) ?? null,
    [rows, inspectedSymbol],
  )
  const sectorOptions = useMemo(
    () => Array.from(new Set((data ?? []).map((row) => row.sector).filter((value): value is string => Boolean(value)))).sort(),
    [data],
  )

  async function refreshCatalog() {
    await Promise.all([mutate(), mutateSelectedDetail()])
  }

  async function handleUpload(file: File | undefined) {
    if (!file) return
    setUploading(true)
    try {
      await uploadFundamentalsWorkbook(file)
      toast.success("Import fondamental lance")
      await refreshCatalog()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Echec de l'import fondamental")
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ""
    }
  }

  async function handleRefreshNonMasi() {
    setRefreshing("batch")
    try {
      const result = await refreshYfinanceFundamentals({ market_regions: regions })
      toast.success(`${result.enqueued_count} symbole(s) yfinance en file`)
      setRefreshOpen(false)
      await refreshCatalog()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Echec du rafraichissement yfinance")
    } finally {
      setRefreshing(null)
    }
  }

  async function handleRefreshSymbol(symbol: string) {
    setRefreshing(symbol)
    try {
      await refreshYfinanceFundamentals({ symbols: [symbol] })
      toast.success(`Rafraichissement fondamental lance pour ${symbol}`)
      await refreshCatalog()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Echec du rafraichissement yfinance")
    } finally {
      setRefreshing(null)
    }
  }

  async function handleRefreshMasi() {
    const symbols = Array.from(selectedBackfillSymbols).sort()
    setRefreshing("stockanalysis")
    try {
      const result = await refreshStockanalysisFundamentals({
        symbols: symbols.length ? symbols : undefined,
        missing_only: false,
      })
      toast.success(`${result.enqueued_count} titre(s) MASI en file`)
      setSelectedBackfillSymbols(new Set())
      await refreshCatalog()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Echec du rafraichissement StockAnalysis")
    } finally {
      setRefreshing(null)
    }
  }

  function openBvcDialog(symbols?: string[]) {
    const selected = symbols !== undefined ? symbols : Array.from(selectedBackfillSymbols).sort()
    setBvcSymbols(selected.join("\n"))
    setBvcPeriodTypes(selected.length === 0 ? ["annual", "semiannual", "quarterly"] : ["annual"])
    setBvcOpen(true)
  }

  async function handleTargetedBvcBackfill() {
    const symbols = parseListInput(bvcSymbols).map((item) => item.toUpperCase())
    const sourceUrls = parseListInput(bvcSourceUrls)
    const startYear = bvcStartYear.trim().length === 4 ? Number(bvcStartYear) : null
    const endYear = bvcEndYear.trim().length === 4 ? Number(bvcEndYear) : null
    const broadScan = symbols.length === 0 && sourceUrls.length === 0 && bvcSectors.length === 0
    const periodTypes = bvcPeriodTypes
    setRefreshing("targeted-bvc")
    try {
      const result = await refreshTargetedBvcFundamentals({
        symbols,
        source_urls: sourceUrls,
        sectors: bvcSectors,
        period_types: periodTypes,
        start_year: startYear,
        end_year: endYear,
        dry_run: bvcDryRun,
        only_unseen: !bvcForce,
        force: bvcForce,
      })
      if (result.dry_run) {
        toast.success(broadScan ? "Apercu du scan BVC complet pret" : `${result.selected_count} cible(s) BVC trouvee(s)`)
      } else {
        toast.success(broadScan ? "Scan BVC complet mis en file" : `${result.selected_count} cible(s) BVC mise(s) en file`)
        setSelectedBackfillSymbols(new Set())
        setBvcOpen(false)
        await refreshCatalog()
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Echec de l'extraction BVC")
    } finally {
      setRefreshing(null)
    }
  }

  function toggleBackfillSymbol(symbol: string, checked: boolean) {
    setSelectedBackfillSymbols((current) => {
      const next = new Set(current)
      if (checked) next.add(symbol)
      else next.delete(symbol)
      return next
    })
  }

  function toggleAllTargetable(checked: boolean) {
    setSelectedBackfillSymbols((current) => {
      const next = new Set(current)
      for (const row of targetableRows) {
        if (checked) next.add(row.symbol)
        else next.delete(row.symbol)
      }
      return next
    })
  }

  function openDetail(symbol: string) {
    setInspectedSymbol(symbol)
    setDetailSymbol(symbol)
    setDetailTab("summary")
    setDetailPeriodType("annual")
  }

  function toggleBvcPeriod(period: string, checked: boolean) {
    setBvcPeriodTypes((current) => {
      const next = checked ? [...new Set([...current, period])] : current.filter((item) => item !== period)
      return next.length ? next : ["annual"]
    })
  }

  function toggleBvcSector(sector: string, checked: boolean) {
    setBvcSectors((current) =>
      checked ? [...new Set([...current, sector])] : current.filter((item) => item !== sector),
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <RawDataKpi label="Symboles" value={formatCount(stats.symbols)} sub="univers fondamental" />
        <RawDataKpi label="Snapshots recents" value={formatCount(stats.latestSnapshots)} sub="metriques courantes normalisees" />
        <RawDataKpi label="Historiques annuels" value={formatCount(stats.annualSymbols)} sub="symboles avec lignes annuelles" />
        <RawDataKpi label="Points financiers" value={formatCount(stats.rawPoints)} sub="metriques recentes + etats" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex h-8 min-w-[240px] max-w-sm flex-1 items-center gap-2 rounded-md border border-line bg-card px-2.5 text-sm text-fg2">
          <Search className="h-3.5 w-3.5 text-fg3" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Rechercher un ticker, nom, secteur, source..."
            className="min-w-0 flex-1 bg-transparent text-sm text-fg1 outline-none placeholder:text-fg3"
          />
        </label>
        <input
          ref={fileInputRef}
          type="file"
          accept=".xlsx,.xls"
          className="hidden"
          onChange={(event) => handleUpload(event.currentTarget.files?.[0])}
        />
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={uploading}
          onClick={() => fileInputRef.current?.click()}
        >
          <FileSpreadsheet className="h-3.5 w-3.5" />
          {uploading ? "Import..." : "Importer Excel"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={refreshing === "stockanalysis"}
          onClick={handleRefreshMasi}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing === "stockanalysis" && "animate-spin")} />
          {selectedBackfillSymbols.size > 0 ? `Rafraichir MASI (${selectedBackfillSymbols.size})` : "Rafraichir MASI"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => setRefreshOpen(true)}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Rafraichir non-MASI
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          disabled={selectedBackfillSymbols.size === 0 || refreshing === "targeted-bvc"}
          onClick={() => openBvcDialog()}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing === "targeted-bvc" && "animate-spin")} />
          BVC selection {selectedBackfillSymbols.size > 0 ? `(${selectedBackfillSymbols.size})` : ""}
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="gap-1.5"
          onClick={() => openBvcDialog([])}
        >
          <LinkIcon className="h-3.5 w-3.5" />
          Extraire BVC
        </Button>
      </div>

      {inspectedRow ? (
        <div className="rounded-md border border-line bg-card p-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-semibold">{inspectedRow.symbol}</span>
                <span className="text-sm font-medium">{inspectedRow.display_name ?? "Titre selectionne"}</span>
                <Badge variant="outline" className="text-[10px]">{sourceLabel(inspectedRow.data_source)}</Badge>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {inspectedRow.sector ?? "Aucun secteur"} - jeu de donnees {periodLabel(inspectedRow.available_periods.at(-1) ?? "annual").toLowerCase()} selectionne
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => openDetail(inspectedRow.symbol)}>
                <Eye className="h-3.5 w-3.5" />
                Etats financiers
              </Button>
              <Button variant="outline" size="sm" className="gap-1.5" onClick={() => openBvcDialog([inspectedRow.symbol])}>
                <RefreshCw className="h-3.5 w-3.5" />
                Extraire BVC
              </Button>
            </div>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-4">
            <RawDataKpi label="Cours actuel" value={fmtValue(inspectedRow.current_price)} sub={dateOnly(inspectedRow.price_as_of) ?? inspectedRow.price_source_provider ?? undefined} />
            <RawDataKpi label="Metriques recentes" value={formatCount(inspectedRow.latest_metric_count)} sub={`Ex. ${inspectedRow.latest_statement_year ?? "-"}`} />
            <RawDataKpi label="Lignes d'etats" value={formatCount(inspectedRow.period_metric_count || inspectedRow.annual_metric_count)} sub={inspectedRow.period_types.map(periodLabel).join(", ") || "Annuel"} />
            <RawDataKpi label="Annees" value={formatCount(inspectedRow.annual_year_count)} sub={yearRange(inspectedRow.annual_years)} />
          </div>
        </div>
      ) : null}

      <div className="rounded-md border border-line bg-card">
        <Table className="claude-table">
          <TableHeader>
            <TableRow>
              <TableHead className="w-10">
                <Checkbox
                  checked={allTargetableSelected}
                  disabled={targetableRows.length === 0}
                  onCheckedChange={(checked) => toggleAllTargetable(checked === true)}
                />
              </TableHead>
              <TableHead className="w-24">Symbole</TableHead>
              <TableHead>Nom</TableHead>
              <TableHead className="hidden lg:table-cell">Secteur</TableHead>
              <TableHead>Donnees financieres disponibles</TableHead>
              <TableHead className="text-right">Cours actuel</TableHead>
              <TableHead className="hidden lg:table-cell">Cours au</TableHead>
              <TableHead className="text-right">Metriques recentes</TableHead>
              <TableHead className="text-right">Lignes d'etats</TableHead>
              <TableHead>Annees</TableHead>
              <TableHead className="hidden md:table-cell">Source</TableHead>
              <TableHead>Dernier import</TableHead>
              <TableHead className="hidden xl:table-cell">Champs manquants</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 8 }).map((_, index) => (
                <TableRow key={index}>
                  <TableCell colSpan={14}><Skeleton className="h-8 w-full" /></TableCell>
                </TableRow>
              ))
            ) : error ? (
              <TableRow>
                <TableCell colSpan={14} className="py-8 text-center text-sm text-destructive">
                  Impossible de charger la couverture fondamentale.
                </TableCell>
              </TableRow>
            ) : rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={14} className="py-8 text-center text-sm text-muted-foreground">
                  Aucune donnee fondamentale disponible.
                </TableCell>
              </TableRow>
            ) : rows.map((row) => {
              const last = dateOnly(row.last_imported_at)
              const canRefresh = row.market_region && row.market_region !== "masi"
              const isRefreshing = refreshing === row.symbol
              const missingPreview = row.missing_metrics.slice(0, 3).join(", ")
              const targetable = canTargetBvc(row)
              const selected = selectedBackfillSymbols.has(row.symbol)
              const inspected = inspectedSymbol === row.symbol
              return (
                <TableRow
                  key={row.symbol}
                  className={cn("cursor-pointer hover:bg-slate-50", inspected && "bg-slate-50")}
                  onClick={() => openDetail(row.symbol)}
                >
                  <TableCell onClick={(event) => event.stopPropagation()}>
                    <Checkbox
                      checked={selected}
                      disabled={!targetable}
                      onCheckedChange={(checked) => toggleBackfillSymbol(row.symbol, checked === true)}
                    />
                  </TableCell>
                  <TableCell className="font-mono font-semibold">{row.symbol}</TableCell>
                  <TableCell>
                    <div className="max-w-[260px] truncate text-sm">{row.display_name ?? "-"}</div>
                    <div className="text-xs text-muted-foreground">{row.market_region ?? "-"}</div>
                  </TableCell>
                  <TableCell className="hidden text-sm text-muted-foreground lg:table-cell">{row.sector ?? "-"}</TableCell>
                  <TableCell><DatasetBadges row={row} /></TableCell>
                  <TableCell className="text-right font-mono">{fmtValue(row.current_price)}</TableCell>
                  <TableCell className="hidden font-mono text-xs text-muted-foreground lg:table-cell">{dateOnly(row.price_as_of) ?? "-"}</TableCell>
                  <TableCell className="text-right font-mono">{formatCount(row.latest_metric_count)}</TableCell>
                  <TableCell className="text-right font-mono">{formatCount(row.period_metric_count || row.annual_metric_count)}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{yearRange(row.annual_years)}</TableCell>
                  <TableCell className="hidden md:table-cell">
                    <Badge variant="outline" className="text-[10px]">{sourceLabel(row.data_source)}</Badge>
                  </TableCell>
                  <TableCell>
                    {last ? <FreshnessBadge dataAsOf={last} /> : <Badge variant="outline" className="text-[10px]">Aucune donnee</Badge>}
                  </TableCell>
                  <TableCell className="hidden max-w-[240px] truncate text-xs text-muted-foreground xl:table-cell">
                    {row.missing_metrics.length ? `${missingPreview}${row.missing_metrics.length > 3 ? "..." : ""}` : "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 w-7 p-0"
                        onClick={(event) => {
                          event.stopPropagation()
                          openDetail(row.symbol)
                        }}
                      >
                        <Eye className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 gap-1 px-2 text-[11px]"
                        disabled={!canRefresh || isRefreshing}
                        onClick={(event) => {
                          event.stopPropagation()
                          handleRefreshSymbol(row.symbol)
                        }}
                      >
                        <RefreshCw className={cn("h-3.5 w-3.5", isRefreshing && "animate-spin")} />
                        yfinance
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>

      <FinancialFundamentalDetailSheet
        symbol={detailSymbol}
        detail={selectedDetail}
        isLoading={isSelectedDetailLoading}
        error={selectedDetailError}
        tab={detailTab}
        onTabChange={setDetailTab}
        periodType={detailPeriodType}
        onPeriodTypeChange={setDetailPeriodType}
        onClose={() => setDetailSymbol(null)}
      />

      <Dialog open={bvcOpen} onOpenChange={setBvcOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>Extraire les fondamentaux BVC</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg2 p-2 text-xs">
              <KeyRound className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="font-medium">{providerStatus?.llm.provider ?? "LLM"}</span>
              <Badge variant={providerStatus?.llm.configured ? "default" : "outline"} className="text-[10px]">
                {providerStatus?.llm.configured ? `${providerStatus.llm.key_count} cle(s)` : "Aucune cle"}
              </Badge>
              {providerStatus?.llm.model ? <span className="text-muted-foreground">{providerStatus.llm.model}</span> : null}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1 text-sm font-medium">
                <span>URLs BVC</span>
                <textarea
                  value={bvcSourceUrls}
                  onChange={(event) => setBvcSourceUrls(event.target.value)}
                  className="min-h-28 w-full rounded-md border border-line bg-card px-3 py-2 font-mono text-xs outline-none focus:border-primary"
                  placeholder="https://..."
                />
              </label>
              <label className="space-y-1 text-sm font-medium">
                <span>Titres</span>
                <textarea
                  value={bvcSymbols}
                  onChange={(event) => setBvcSymbols(event.target.value.toUpperCase())}
                  className="min-h-28 w-full rounded-md border border-line bg-card px-3 py-2 font-mono text-xs outline-none focus:border-primary"
                  placeholder={"ATW\nBCP"}
                />
              </label>
            </div>

            <div className="grid gap-3 md:grid-cols-[1fr_220px]">
              <div className="space-y-2">
                <div className="text-sm font-medium">Secteurs</div>
                <div className="flex max-h-28 flex-wrap gap-2 overflow-auto rounded-md border border-line bg-card p-2">
                  {sectorOptions.length === 0 ? (
                    <span className="text-xs text-muted-foreground">Aucune liste de secteurs</span>
                  ) : sectorOptions.map((sector) => (
                    <label key={sector} className="flex items-center gap-1.5 rounded-sm border border-line px-2 py-1 text-xs">
                      <Checkbox
                        checked={bvcSectors.includes(sector)}
                        onCheckedChange={(checked) => toggleBvcSector(sector, checked === true)}
                      />
                      {sector}
                    </label>
                  ))}
                </div>
              </div>
              <div className="space-y-2">
                <div className="text-sm font-medium">Annees</div>
                <div className="grid grid-cols-2 gap-2">
                  <input
                    value={bvcStartYear}
                    onChange={(event) => setBvcStartYear(event.target.value.replace(/[^0-9]/g, "").slice(0, 4))}
                    className="h-9 rounded-md border border-line bg-card px-2 text-sm outline-none focus:border-primary"
                    placeholder="Annee"
                  />
                  <input
                    value={bvcEndYear}
                    onChange={(event) => setBvcEndYear(event.target.value.replace(/[^0-9]/g, "").slice(0, 4))}
                    className="h-9 rounded-md border border-line bg-card px-2 text-sm outline-none focus:border-primary"
                    placeholder="A"
                  />
                </div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {(["annual", "semiannual", "quarterly"] as const).map((period) => (
                <label key={period} className="flex items-center gap-1.5 rounded-sm border border-line px-2 py-1 text-xs">
                  <Checkbox
                    checked={bvcPeriodTypes.includes(period)}
                    onCheckedChange={(checked) => toggleBvcPeriod(period, checked === true)}
                  />
                  {periodLabel(period)}
                </label>
              ))}
            </div>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
              <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={bvcDryRun} onCheckedChange={(checked) => setBvcDryRun(checked === true)} />
                  Simulation
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <Checkbox checked={bvcForce} onCheckedChange={(checked) => setBvcForce(checked === true)} />
                  Forcer
                </label>
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setBvcOpen(false)}>Annuler</Button>
                <Button
                  onClick={handleTargetedBvcBackfill}
                  disabled={refreshing === "targeted-bvc" || (!bvcDryRun && providerStatus?.llm.configured === false)}
                >
                  {refreshing === "targeted-bvc" ? "Mise en file..." : bvcDryRun ? "Apercu" : "Mettre en file"}
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={refreshOpen} onOpenChange={setRefreshOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rafraichir les fondamentaux yfinance</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {REGIONS.map((region) => (
              <label key={region.key} className="flex items-center gap-2 text-sm">
                <Checkbox
                  checked={regions.includes(region.key)}
                  onCheckedChange={(checked) => {
                    const isChecked = checked === true
                    setRegions((current) =>
                      isChecked
                        ? [...new Set([...current, region.key])]
                        : current.filter((item) => item !== region.key),
                    )
                  }}
                />
                {region.label}
              </label>
            ))}
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="outline" onClick={() => setRefreshOpen(false)}>Annuler</Button>
              <Button onClick={handleRefreshNonMasi} disabled={refreshing === "batch" || regions.length === 0}>
                {refreshing === "batch" ? "Mise en file..." : "Mettre le rafraichissement en file"}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
