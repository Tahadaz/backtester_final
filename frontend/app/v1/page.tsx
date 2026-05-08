"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import useSWR from "swr"
import { AlertCircle, BookOpen, Download, Filter, RefreshCw } from "lucide-react"
import { useDashboardData } from "@/hooks/use-dashboard"
import { useDashboardIndices } from "@/hooks/use-dashboard-indices"
import { useMarketCatalog } from "@/hooks/use-api"
import { fetchEdge, type EdgeMetrics } from "@/lib/api"
import type { DashboardScoreSource, DashboardStock, DashboardView, Horizon } from "@/lib/dashboard-types"
import { createDashboardIndex, deleteDashboardIndex, updateDashboardIndex } from "@/lib/api"
import { resolveHorizonPreset } from "@/lib/horizon"
import { recomputeDashboardSectors } from "@/lib/static-expanded-preferences"
import { StockTable } from "@/components/dashboard-v1/stock-table"
import { SetupStep } from "@/components/dashboard/setup-step"
import { KpiTile } from "@/components/dashboard/kpi-tile"
import { EdgePanel } from "@/components/dashboard/edge-panel"
import { Eyebrow } from "@/components/ui/eyebrow"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const edgeEnabled = process.env.NEXT_PUBLIC_EDGE_ENABLED !== "false"
const EDGE_COST_BPS = 33
const ADV_THRESHOLD = 1000
const DASHBOARD_HORIZONS = [
  { value: "weekly" as const, label: "Court" },
  { value: "monthly" as const, label: "Moyen" },
  { value: "quarterly" as const, label: "Long" },
]
const STOCK_ONLY_VIEW = [{ value: "stocks" as const, label: "Actions" }]
const SOURCE_OPTIONS = [
  { value: "signal_engine" as const, label: "Signal Engine" },
  { value: "wfo" as const, label: "WFO" },
  { value: "both" as const, label: "Les deux" },
]
const CATEGORY_OPTIONS = [
  { value: "all" as const, label: "Toutes" },
  { value: "liquid" as const, label: "Très liq." },
  { value: "mid" as const, label: "Mid" },
]
const SR_OPTIONS = [
  { value: "off" as const, label: "Off" },
  { value: "on" as const, label: "Auto" },
  { value: "manual" as const, label: "Manuel" },
]

type EdgeMode = "gross" | "net"

function median(values: number[]) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[mid]
  return (sorted[mid - 1] + sorted[mid]) / 2
}

function scoreLabelForCounts(stock: DashboardStock, scoreSource: DashboardScoreSource, signalView: "legacy" | "expanded" | "factor_x_ta") {
  if (scoreSource === "wfo") {
    return stock.scores.wfo?.aggregate_signal_label ?? null
  }
  if (scoreSource === "both") {
    return stock.scores.wfo?.aggregate_signal_label ?? stock.scores.signal_engine.aggregate_signal_label
  }
  return signalView === "expanded"
    ? stock.scores.signal_engine.expanded_aggregate_signal_label ?? stock.scores.signal_engine.aggregate_signal_label
    : stock.scores.signal_engine.aggregate_signal_label
}

function downloadStocksCsv(stocks: DashboardStock[]) {
  const lines = [
    ["symbol", "display_name", "sector", "asset_type", "market_region", "adv"].join(","),
    ...stocks.map((stock) =>
      [
        stock.symbol,
        stock.display_name ?? "",
        stock.sector ?? "",
        stock.asset_type ?? "",
        stock.market_region ?? "",
        stock.adv ?? "",
      ]
        .map((value) => {
          const raw = String(value)
          const escaped = raw.replaceAll("\"", "\"\"")
          return /[",\n\r]/.test(raw) ? `"${escaped}"` : escaped
        })
        .join(","),
    ),
  ]
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = "dashboard-v1.csv"
  link.click()
  URL.revokeObjectURL(url)
}

export default function DashboardV1Page() {
  const [horizon, setHorizon] = useState<Horizon>("monthly")
  const [view] = useState<DashboardView>("stocks")
  const [indexActionError, setIndexActionError] = useState<string | null>(null)
  const [showFilters, setShowFilters] = useState(true)
  const [liquidityFilter, setLiquidityFilter] = useState(false)
  const [signalView, setSignalView] = useState<"legacy" | "expanded" | "factor_x_ta">("expanded")
  const [scoreSource, setScoreSource] = useState<DashboardScoreSource>("wfo")
  const [showTechnicalLevels, setShowTechnicalLevels] = useState(false)
  const [hideDetails, setHideDetails] = useState(true)
  const [edgeOnly, setEdgeOnly] = useState(false)
  const [edgeMode, setEdgeMode] = useState<EdgeMode>("net")
  const [search, setSearch] = useState("")
  const [sectorFilter, setSectorFilter] = useState<string>("all")
  const [categoryFilter, setCategoryFilter] = useState<"all" | "liquid" | "mid">("all")
  const [selectedStock, setSelectedStock] = useState<DashboardStock | null>(null)

  const { data, error, isLoading, mutate } = useDashboardData(horizon)
  const { data: persistedIndices, error: indicesError, mutate: mutateIndices } = useDashboardIndices(!isPublicDashboardOnly)
  const { data: catalogData } = useMarketCatalog()

  const taxonomyMap = useMemo(() => {
    const out: Record<string, { asset_type: string; market_region: string | null }> = {}
    for (const row of catalogData ?? []) {
      out[row.symbol] = { asset_type: row.asset_type ?? "equity", market_region: row.market_region ?? null }
    }
    return out
  }, [catalogData])

  const allStocks = useMemo(
    () =>
      (data?.stocks ?? []).map((stock) => ({
        ...stock,
        asset_type: stock.asset_type ?? taxonomyMap[stock.symbol]?.asset_type ?? "equity",
        market_region: stock.market_region ?? taxonomyMap[stock.symbol]?.market_region ?? null,
      })),
    [data?.stocks, taxonomyMap],
  )

  const masiStocks = useMemo(
    () =>
      allStocks.filter(
        (stock) => (stock.asset_type ?? "equity") === "equity" && (stock.market_region ?? "masi") === "masi",
      ),
    [allStocks],
  )

  const edgeSource = scoreSource === "signal_engine" ? "signal_engine" : "wfo"
  const edgeHorizon = resolveHorizonPreset(horizon).value

  const stocksBeforeEdge = useMemo(() => {
    const query = search.trim().toLowerCase()
    return masiStocks
      .filter((stock) => !liquidityFilter || (stock.adv ?? ADV_THRESHOLD) >= ADV_THRESHOLD)
      .filter((stock) => categoryFilter !== "liquid" || (stock.adv ?? 0) >= ADV_THRESHOLD)
      .filter((stock) => categoryFilter !== "mid" || (stock.adv ?? 0) < ADV_THRESHOLD)
      .filter((stock) => sectorFilter === "all" || stock.sector === sectorFilter)
      .filter((stock) => {
        if (!query) return true
        return stock.symbol.toLowerCase().includes(query) || (stock.display_name ?? "").toLowerCase().includes(query)
      })
  }, [masiStocks, liquidityFilter, categoryFilter, sectorFilter, search])

  const { data: edgeEntries = [] } = useSWR<[string, EdgeMetrics | null][]>(
    edgeEnabled && view === "stocks" && stocksBeforeEdge.length
      ? `dashboard-edge-${edgeHorizon}-${edgeSource}-${edgeMode}-${stocksBeforeEdge.map((stock) => stock.symbol).join(",")}`
      : null,
    async () =>
      Promise.all(
        stocksBeforeEdge.map(async (stock) => [
          stock.symbol,
          await fetchEdge(stock.symbol, edgeHorizon, edgeSource, EDGE_COST_BPS).catch(() => null),
        ] as [string, EdgeMetrics | null]),
      ),
    { revalidateOnFocus: false },
  )

  const edgeMap = useMemo(() => Object.fromEntries(edgeEntries), [edgeEntries]) as Record<string, EdgeMetrics | null | undefined>

  const filteredStocks = useMemo(() => {
    if (!edgeEnabled || !edgeOnly || view !== "stocks") {
      return stocksBeforeEdge
    }
    return stocksBeforeEdge.filter((stock) => {
      const edge = edgeMap[stock.symbol]
      return edgeMode === "net" ? edge?.proven_edge_net : edge?.proven_edge_gross
    })
  }, [stocksBeforeEdge, edgeEnabled, edgeOnly, view, edgeMap, edgeMode])

  const sectorsInput = liquidityFilter ? filteredStocks : masiStocks
  const filteredSectors = useMemo(
    () => recomputeDashboardSectors(sectorsInput, scoreSource),
    [sectorsInput, scoreSource],
  )

  const sectorOptions = useMemo(() => {
    const set = new Set(filteredStocks.map((stock) => stock.sector).filter((sector): sector is string => Boolean(sector)))
    return ["all", ...Array.from(set).sort()]
  }, [filteredStocks])

  const kpiBullish = filteredStocks.filter((stock) => (scoreLabelForCounts(stock, scoreSource, signalView) ?? "").includes("Achat")).length
  const kpiBearish = filteredStocks.filter((stock) => (scoreLabelForCounts(stock, scoreSource, signalView) ?? "").includes("Vente")).length
  const kpiMedianEdge = median(
    filteredStocks
      .map((stock) => edgeMap[stock.symbol])
      .filter((edge): edge is EdgeMetrics => Boolean(edge))
      .filter((edge) => (edgeMode === "net" ? edge.proven_edge_net : edge.proven_edge_gross))
      .map((edge) => edgeMode === "net" ? edge.expected_return_net : edge.expected_return_gross)
      .filter((value): value is number => typeof value === "number"),
  )

  return (
    <div className="dashboard-claude space-y-4">
      <div className="flex flex-col gap-4 border-b border-border pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <Eyebrow>Dashboard</Eyebrow>
          <div>
            <h1 className="text-[22px] font-semibold tracking-tight">Tableau de Bord V1</h1>
            <p className="text-[12px] text-muted-foreground">
              Signaux techniques · <span className="font-medium text-foreground">Marché MASI · Actions</span>
              {data ? <span className="dashboard-meta ml-2">Maj {new Date(data.generated_at).toLocaleDateString("fr-FR")}</span> : null}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" className="h-8 rounded-md px-3 text-[13px]" onClick={() => setShowFilters((value) => !value)}>
            <Filter className="h-3.5 w-3.5" />
            Filtres
          </Button>
          <Button variant="outline" size="sm" className="h-8 rounded-md px-3 text-[13px]" onClick={() => downloadStocksCsv(filteredStocks)} disabled={view !== "stocks"}>
            <Download className="h-3.5 w-3.5" />
            Exporter
          </Button>
          <Button variant="default" size="sm" className="h-8 rounded-md px-3 text-[13px]" onClick={() => void mutate()}>
            <RefreshCw className="h-3.5 w-3.5" />
            Recalculer
          </Button>
        </div>
      </div>

      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        <KpiTile label="Univers actif" value={filteredStocks.length.toLocaleString("fr-FR")} sub="titres après filtres" />
        <KpiTile label="Signaux haussiers" value={kpiBullish.toLocaleString("fr-FR")} tone="positive" sub="score composite > +15" />
        <KpiTile label="Signaux baissiers" value={kpiBearish.toLocaleString("fr-FR")} tone="negative" sub="score composite < -15" />
        <KpiTile label="E[R] médian (opt.)" value={edgeEnabled ? formatPercent(kpiMedianEdge) : "--"} sub={edgeEnabled ? `mode ${edgeMode === "net" ? "net" : "brut"}` : "edge désactivé"} />
      </div>

      {showFilters ? (
        <div className="space-y-3">
          <div className="grid gap-2 xl:grid-cols-5">
            <SetupStep index={1} title="Horizon" value={horizon} onChange={setHorizon} options={DASHBOARD_HORIZONS} />
            <SetupStep index={2} title="Univers" value={view} onChange={() => undefined} options={STOCK_ONLY_VIEW} hint={`${masiStocks.length} titres MASI`} />
            <SetupStep
              index={3}
              title="Source"
              value={scoreSource}
              onChange={setScoreSource}
              options={SOURCE_OPTIONS}
              hint="Composite 4 familles"
            />
            <SetupStep
              index={4}
              title="Categorie"
              value={categoryFilter}
              onChange={setCategoryFilter}
              options={CATEGORY_OPTIONS}
              hint="Filtre liquidité"
            />
            <SetupStep
              index={5}
              title="S/R"
              value={showTechnicalLevels ? "on" : "off"}
              onChange={(next) => setShowTechnicalLevels(next !== "off")}
              options={SR_OPTIONS}
              hint="Supports / résistances"
            />
          </div>

          <div className="flex flex-wrap gap-1.5">
            {[
              { label: "Actions", active: true },
              { label: "Matières premières", active: false },
              { label: "Obligations", active: false },
              { label: "Devises", active: false },
            ].map((option) => (
              <button
                key={option.label}
                type="button"
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-md border px-3 text-[12px] transition",
                  option.active
                    ? "border-primary/25 bg-primary/10 font-semibold text-primary"
                    : "cursor-default border-border bg-card text-muted-foreground",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap gap-0.5 border-b border-dashed border-border pb-2">
            {[
              { label: "MASI (Maroc)", active: true },
              { label: "US", active: false },
              { label: "Europe", active: false },
              { label: "Asie", active: false },
            ].map((option) => (
              <button
                key={option.label}
                type="button"
                className={cn(
                  "border-b-2 px-2.5 py-1.5 text-[12px] text-muted-foreground transition",
                  option.active ? "border-primary font-semibold text-foreground" : "cursor-default border-transparent",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="dashboard-panel flex flex-col gap-3 px-3 py-3 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex flex-1 flex-wrap items-center gap-2">
              {liquidityFilter ? (
                <span className="dashboard-chip dashboard-chip-amber">
                  <span className="dashboard-chip-dot bg-[var(--warning)]" />
                  Liquidite {"\u003e="} {ADV_THRESHOLD}
                </span>
              ) : null}
              <span className={cn("dashboard-chip", sectorFilter !== "all" && "dashboard-chip-active")}>
                <span className="dashboard-chip-dot" />
                Secteur - {sectorFilter === "all" ? "Tous" : sectorFilter}
              </span>
              <div className="flex h-8 min-w-[220px] flex-1 items-center gap-2 rounded-md border border-input bg-background px-2.5">
                <Input
                  className="h-auto border-0 bg-transparent px-0 text-[12px] shadow-none focus-visible:ring-0"
                  placeholder="Rechercher..."
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </div>
              <select
                value={sectorFilter}
                onChange={(event) => setSectorFilter(event.target.value)}
                className="h-8 min-w-[180px] rounded-md border border-input bg-background px-2.5 text-[12px]"
              >
                <option value="all">Tous les secteurs</option>
                {sectorOptions.filter((option) => option !== "all").map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
              <Button variant="ghost" size="sm" className="ml-auto h-7 rounded-md px-2 text-[12px] text-muted-foreground" asChild>
                <Link href="/glossary">
                  <BookOpen className="h-3.5 w-3.5" />
                  Glossaire
                </Link>
              </Button>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                <Switch checked={liquidityFilter} onCheckedChange={setLiquidityFilter} />
                <span>Liquidite</span>
              </div>
              <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
                <Switch checked={hideDetails} onCheckedChange={setHideDetails} />
                <span>Masquer les details</span>
              </div>
              {edgeEnabled ? (
                <>
                  <div className="inline-flex rounded-md border border-border bg-muted/40 p-0.5">
                    <button
                      type="button"
                      onClick={() => setEdgeMode("net")}
                      className={cn(
                        "rounded-[6px] px-2 py-1 text-[11px] font-medium",
                        edgeMode === "net" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
                      )}
                    >
                      Couts inclus
                    </button>
                    <button
                      type="button"
                      onClick={() => setEdgeMode("gross")}
                      className={cn(
                        "rounded-[6px] px-2 py-1 text-[11px] font-medium",
                        edgeMode === "gross" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground",
                      )}
                    >
                      Couts exclus
                    </button>
                  </div>
                  <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
                    <Checkbox checked={edgeOnly} onCheckedChange={(checked) => setEdgeOnly(checked === true)} />
                    Edge prouvé seulement
                  </label>
                </>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {isLoading && <LoadingSkeleton />}
      {error && <ErrorCard message={error.message} />}

      {data ? (
        <StockTable
          stocks={filteredStocks}
          horizon={horizon}
          signalView={signalView}
          scoreSource={scoreSource}
          hideDetails={hideDetails}
          showTechnicalLevels={showTechnicalLevels}
          edgeEnabled={edgeEnabled}
          edgeMode={edgeMode}
          edgeSource={edgeSource}
          edgeMap={edgeMap}
          onOpenEdge={setSelectedStock}
        />
      ) : null}

      {data && data.stocks.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            {isPublicDashboardOnly ? (
              <p className="text-muted-foreground">Aucune donnee disponible.</p>
            ) : (
              <p className="text-muted-foreground">
                Aucune donnee disponible. Chargez des donnees de marche depuis la page <Link href="/data" className="underline">Data</Link>.
              </p>
            )}
          </CardContent>
        </Card>
      ) : null}

      {edgeEnabled ? (
        <EdgePanel
          open={Boolean(selectedStock)}
          onOpenChange={(open) => {
            if (!open) setSelectedStock(null)
          }}
          symbol={selectedStock?.symbol ?? null}
          horizon={edgeHorizon}
          initialSource={edgeSource}
          mode={edgeMode}
          onModeChange={setEdgeMode}
          costBps={EDGE_COST_BPS}
          initialEdge={selectedStock ? edgeMap[selectedStock.symbol] ?? null : null}
        />
      ) : null}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-3">
      <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20 rounded-md" />
        ))}
      </div>
      <Skeleton className="h-28 rounded-md" />
      <Skeleton className="h-[480px] rounded-md" />
    </div>
  )
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card className="border-destructive">
      <CardContent className="flex items-center gap-3 py-6">
        <AlertCircle className="h-5 w-5 text-destructive" />
        <div>
          <p className="font-medium text-destructive">Erreur de chargement</p>
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      </CardContent>
    </Card>
  )
}
