"use client"

import { useEffect, useMemo, useState } from "react"
import {
  useBloombergBatches,
  useBloombergBridges,
  useBloombergJobs,
  useBloombergSeries,
  useMarketCatalog,
  useTrackedStocks,
  useMasiTickers,
  useMacroCatalog,
} from "@/hooks/use-api"
import {
  ApiError,
  refreshAllStocks,
  addTrackedStock,
  refreshSingleStock,
  enqueueAllMacroIngest,
  enqueueMacroIngest,
  createBloombergJob,
} from "@/lib/api"
import type {
  BloombergBatch,
  BloombergBridgeStatus,
  BloombergJob,
  BloombergJobCreateInput,
  BloombergSeries,
  MarketCatalogRow,
  MasiTicker,
} from "@/lib/api"
import { PublicDataPage } from "@/components/data/public-data-page"
import { StockDetailPanel } from "@/components/data/stock-detail-panel"
import { ExcelUploadDialog } from "@/components/data/excel-upload-dialog"
import { RefreshStatusBar } from "@/components/data/refresh-status-bar"
import { FreshnessBadge } from "@/components/data/freshness-badge"
import { CategoryEditDialog } from "@/components/data/category-edit-dialog"
import { AddFactorDialog } from "@/components/data/add-factor-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import {
  CheckCircle2,
  Coins,
  Database,
  Download,
  Eye,
  FileSpreadsheet,
  Globe,
  Landmark,
  Package,
  Pencil,
  Plus,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  TrendingUp,
  Wifi,
  type LucideIcon,
} from "lucide-react"
import { toast } from "sonner"

type CategoryTab = "equity" | "commodity" | "forex" | "bond" | "crypto" | "bloomberg"
type SubcategoryTab = "all" | "masi" | "us" | "european" | "asian"

const CATEGORY_TABS: { key: CategoryTab; label: string; icon: LucideIcon }[] = [
  { key: "equity", label: "Actions", icon: TrendingUp },
  { key: "commodity", label: "Matieres premieres", icon: Package },
  { key: "forex", label: "Devises", icon: Globe },
  { key: "bond", label: "Obligations", icon: Landmark },
  { key: "crypto", label: "Crypto", icon: Coins },
  { key: "bloomberg", label: "Bloomberg", icon: Database },
]

const SUBCATEGORY_TABS: { key: SubcategoryTab; label: string }[] = [
  { key: "all", label: "Tous" },
  { key: "masi", label: "MASI" },
  { key: "us", label: "US" },
  { key: "european", label: "Europe" },
  { key: "asian", label: "Asie" },
]

const MASI20_SYMBOLS = [
  "ADH",
  "ADI",
  "AKT",
  "ATW",
  "BCP",
  "BOA",
  "CDM",
  "CFG",
  "CMA",
  "CMG",
  "CSR",
  "IAM",
  "JET",
  "LBV",
  "LHM",
  "MSA",
  "RDS",
  "SID",
  "TGC",
  "TQM",
]

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const DATA_PAGE_HIDDEN_STOCKS = new Set(["MAJ", "MAJJ", "WORKSHEET", "INSTRUMENT"])
const PRE_CLOSE_REFRESH_MESSAGE =
  "La derniere seance Bourse disponible est deja chargee. Prochaine mise a jour intraday apres 17:00 (Africa/Casablanca)."

function normalizeStockIdentity(value: string | null | undefined) {
  return (value ?? "")
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
}

function isHiddenOnDataPage(symbol?: string | null, displayName?: string | null) {
  return (
    DATA_PAGE_HIDDEN_STOCKS.has(normalizeStockIdentity(symbol)) ||
    DATA_PAGE_HIDDEN_STOCKS.has(normalizeStockIdentity(displayName))
  )
}

function formatCount(value: number | null | undefined) {
  return value == null ? "-" : value.toLocaleString("fr-FR")
}

function dateOnly(value: string | null | undefined) {
  return value ? value.slice(0, 10) : null
}

function parseListInput(value: string) {
  return value
    .split(/[\n,;]/g)
    .map((item) => item.trim())
    .filter(Boolean)
}

function asText(value: unknown) {
  if (value == null) return "-"
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value)
  return "-"
}

function getCategoryLabel(tab: CategoryTab | string | null | undefined) {
  switch (tab) {
    case "equity":
      return "Actions"
    case "commodity":
      return "Matieres premieres"
    case "forex":
      return "Devises"
    case "bond":
      return "Obligations"
    case "crypto":
      return "Crypto"
    case "bloomberg":
      return "Bloomberg"
    default:
      return tab || "Autre"
  }
}

function getSubcategoryLabel(tab: SubcategoryTab | string | null | undefined) {
  switch (tab) {
    case "all":
      return "Tous"
    case "masi":
      return "MASI"
    case "us":
      return "US"
    case "european":
      return "Europe"
    case "asian":
      return "Asie"
    default:
      return tab || "Tous"
  }
}

function getSourceLabel(row: MarketCatalogRow) {
  if (row.source_provider === "bmce_excel") return "Excel"
  if (row.source_provider === "yahoo" || row.track_source === "yahoo") return "Yahoo"
  if (row.source_provider === "bourse_direct" || row.track_source === "bourse_direct") return "Bourse"
  if (row.source_provider) return row.source_provider
  return "-"
}

function rowMatchesQuery(row: MarketCatalogRow, query: string) {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [
    row.symbol,
    row.isin,
    row.display_name,
    row.sector,
    row.notes,
    row.asset_type,
    row.market_region,
    row.source_provider,
    row.track_source,
  ].some((value) => (value ?? "").toLowerCase().includes(q))
}

function PrivateDataPage() {
  const { data: catalog, error: catalogError, isLoading, mutate: mutateCatalog } = useMarketCatalog()
  const { mutate: mutateTracked } = useTrackedStocks()
  const { data: masiTickers } = useMasiTickers()
  const { data: macroCatalog, mutate: mutateMacroCatalog } = useMacroCatalog()
  const {
    data: bloombergBatches,
    error: bloombergBatchesError,
  } = useBloombergBatches()
  const {
    data: bloombergSeries,
    error: bloombergSeriesError,
    mutate: mutateBloombergSeries,
  } = useBloombergSeries()
  const {
    data: bloombergBridges,
    error: bloombergBridgesError,
    mutate: mutateBloombergBridges,
  } = useBloombergBridges()
  const {
    data: bloombergJobs,
    error: bloombergJobsError,
    mutate: mutateBloombergJobs,
  } = useBloombergJobs()

  const [categoryTab, setCategoryTab] = useState<CategoryTab>("equity")
  const [subcategoryTab, setSubcategoryTab] = useState<SubcategoryTab>("all")
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [editCategoryRow, setEditCategoryRow] = useState<MarketCatalogRow | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [addStockOpen, setAddStockOpen] = useState(false)
  const [addFactorOpen, setAddFactorOpen] = useState(false)
  const [downloadOpen, setDownloadOpen] = useState(false)
  const [activeRefreshId, setActiveRefreshId] = useState<string | null>(null)
  const [refreshingAll, setRefreshingAll] = useState(false)
  const [refreshingSymbol, setRefreshingSymbol] = useState<string | null>(null)
  const [isDownloading, setIsDownloading] = useState(false)
  const [searchQuery, setSearchQuery] = useState("")

  const visibleCatalog = useMemo(
    () =>
      (catalog ?? []).filter(
        (row) => !isHiddenOnDataPage(row.symbol, row.display_name),
      ),
    [catalog],
  )
  const visibleMasiTickers = useMemo(
    () =>
      (masiTickers ?? []).filter(
        (ticker) => !isHiddenOnDataPage(ticker.symbol, ticker.display_name),
      ),
    [masiTickers],
  )

  const trackedSet = new Set(visibleCatalog.filter((r) => r.is_tracked).map((r) => r.symbol))
  const macroFactorSet = useMemo(
    () => new Set((macroCatalog ?? []).map((row) => row.canonical_id)),
    [macroCatalog],
  )
  const selectedRow: MarketCatalogRow | null =
    visibleCatalog.find((r) => r.symbol === selectedSymbol) ?? null

  // Counts per category for tab badges
  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const r of visibleCatalog) {
      counts[r.asset_type ?? "equity"] = (counts[r.asset_type ?? "equity"] ?? 0) + 1
    }
    counts.bloomberg = bloombergSeries?.length ?? 0
    return counts
  }, [visibleCatalog, bloombergSeries])

  const activeRows = useMemo(() => {
    const byType = visibleCatalog.filter((r) => (r.asset_type ?? "equity") === categoryTab)
    if (subcategoryTab === "all") return byType
    return byType.filter((r) => r.market_region === subcategoryTab)
  }, [visibleCatalog, categoryTab, subcategoryTab])

  const filteredRows = useMemo(
    () => activeRows.filter((row) => rowMatchesQuery(row, searchQuery)),
    [activeRows, searchQuery],
  )

  const subcategoryCounts = useMemo(() => {
    if (categoryTab !== "equity") return {}
    const equityRows = visibleCatalog.filter((r) => (r.asset_type ?? "equity") === "equity")
    const counts: Record<string, number> = { all: equityRows.length }
    for (const r of equityRows) {
      if (r.market_region) {
        counts[r.market_region] = (counts[r.market_region] ?? 0) + 1
      }
    }
    return counts
  }, [visibleCatalog, categoryTab])

  function mutateAll() {
    mutateCatalog()
    mutateTracked()
    mutateMacroCatalog()
  }

  function isYahooRow(row: MarketCatalogRow) {
    return row.source_provider === "yahoo" || row.track_source === "yahoo"
  }

  function isYahooMacroRow(row: MarketCatalogRow) {
    return isYahooRow(row) && (macroFactorSet.has(row.symbol) || row.asset_type !== "equity")
  }

  async function handleDownloadExcel(symbols?: string[], preset?: string) {
    setIsDownloading(true)
    try {
      const params = new URLSearchParams()
      const selectedSymbols = (symbols ?? []).map((symbol) => symbol.trim().toUpperCase()).filter(Boolean)
      if (selectedSymbols.length > 0) {
        for (const symbol of selectedSymbols) params.append("symbols", symbol)
        if (preset) params.set("preset", preset)
      } else {
        params.set("asset_type", categoryTab)
        if (subcategoryTab !== "all") params.set("market_region", subcategoryTab)
      }
      const qs = params.toString()
      const res = await fetch(`/api/market-data/download-excel${qs ? `?${qs}` : ""}`)
      if (!res.ok) throw new Error("Download failed")
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      const parts =
        selectedSymbols.length > 0
          ? [preset === "masi20" ? "masi20" : "selected"]
          : [categoryTab, subcategoryTab !== "all" ? subcategoryTab : ""]
      a.download = `${parts.filter(Boolean).join("-")}-data.xlsx`
      a.click()
      URL.revokeObjectURL(url)
      setDownloadOpen(false)
    } catch {
      toast.error("Echec du telechargement Excel")
    } finally {
      setIsDownloading(false)
    }
  }

  async function handleRefreshAll() {
    setRefreshingAll(true)
    try {
      const [stockRefresh, macroRefresh] = await Promise.all([
        refreshAllStocks(),
        enqueueAllMacroIngest("2010-01-01"),
      ])
      setActiveRefreshId(stockRefresh.refresh_run_id)
      toast.success(
        `Mise a jour lancee: Bourse/titres suivis + ${macroRefresh.enqueued.length} series Yahoo`,
      )
      setTimeout(mutateAll, 10_000)
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(PRE_CLOSE_REFRESH_MESSAGE)
      } else {
        toast.error("Impossible de lancer la mise a jour")
      }
    } finally {
      setRefreshingAll(false)
    }
  }

  async function handleRowRefresh(row: MarketCatalogRow) {
    setRefreshingSymbol(row.symbol)
    try {
      if (isYahooMacroRow(row)) {
        await enqueueMacroIngest(row.symbol, "2010-01-01")
        toast.success(`Ingestion Yahoo lancee pour ${row.symbol}`)
        setTimeout(mutateAll, 8_000)
        return
      }

      if (isYahooRow(row)) {
        const res = await refreshSingleStock(row.symbol, { source_override: "yahoo" })
        setActiveRefreshId(res.refresh_run_id)
        toast.success(`Mise a jour Yahoo lancee pour ${row.symbol}`)
        return
      }

      if (!trackedSet.has(row.symbol)) {
        try {
          await addTrackedStock({ symbol: row.symbol, track_source: "bourse_direct" })
          mutateTracked()
        } catch (error: unknown) {
          if (!(error instanceof Error && error.message.includes("409"))) throw error
        }
      }
      const res = await refreshSingleStock(row.symbol)
      setActiveRefreshId(res.refresh_run_id)
      toast.success(`Mise a jour Bourse lancee pour ${row.symbol}`)
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(PRE_CLOSE_REFRESH_MESSAGE)
      } else {
        toast.error(`Echec: ${err instanceof Error ? err.message : "Erreur"}`)
      }
    } finally {
      setRefreshingSymbol(null)
    }
  }

  async function handleAddStock(ticker: MasiTicker) {
    try {
      await addTrackedStock({
        symbol: ticker.symbol,
        track_source: "bourse_direct",
      })
      mutateAll()
      setAddStockOpen(false)
      toast.success(`${ticker.symbol} — ${ticker.display_name} ajoute`)
    } catch (err: unknown) {
      if (err instanceof Error && err.message.includes("409")) {
        toast.error(`${ticker.symbol} est deja dans le catalogue`)
      } else {
        toast.error(`Echec: ${err instanceof Error ? err.message : "Erreur"}`)
      }
    }
  }

  const countWithData = activeRows.filter((r) => r.has_canonical_data).length
  const filteredCountWithData = filteredRows.filter((r) => r.has_canonical_data).length
  const totalBars = activeRows.reduce((sum, row) => sum + (row.row_count ?? 0), 0)
  const staleCount = activeRows.filter((row) => row.is_stale).length
  const neverIngestedCount = activeRows.filter((row) => !row.has_canonical_data).length
  const freshCount = activeRows.length - staleCount - neverIngestedCount
  const firstBarDate =
    activeRows
      .map((row) => dateOnly(row.start_ts))
      .filter((value): value is string => Boolean(value))
      .sort()[0] ?? null
  const latestDataDate =
    activeRows
      .map((row) => dateOnly(row.data_as_of ?? row.end_ts))
      .filter((value): value is string => Boolean(value))
      .sort()
      .at(-1) ?? null
  const activeScopeLabel =
    categoryTab === "equity" && subcategoryTab !== "all"
      ? `${getCategoryLabel(categoryTab)} / ${getSubcategoryLabel(subcategoryTab)}`
      : getCategoryLabel(categoryTab)
  const defaultDownloadSymbols = useMemo(
    () => filteredRows.map((row) => row.symbol),
    [filteredRows],
  )

  return (
    <div className="claude-page space-y-4">
      <div className="claude-page-h flex-col items-start sm:flex-row sm:items-end">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Donnees de marche</h1>
          <p className="text-sm text-muted-foreground">
            Univers canonique pour les imports Excel et les mises a jour Bourse.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {categoryTab === "equity" && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setAddStockOpen(true)}
            >
              <Plus className="h-3.5 w-3.5" />
              Ajouter un titre
            </Button>
          )}
          {categoryTab !== "bloomberg" && (
            <>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 border-purple-600 text-purple-700 hover:bg-purple-50 hover:text-purple-800"
                onClick={() => setAddFactorOpen(true)}
              >
                <Plus className="h-3.5 w-3.5" />
                Ajouter un facteur
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 border-green-600 text-green-700 hover:bg-green-50 hover:text-green-800"
                onClick={() => setUploadOpen(true)}
              >
                <FileSpreadsheet className="h-3.5 w-3.5" />
                Importer Excel
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => setDownloadOpen(true)}
                disabled={isDownloading}
              >
                <Download className={`h-3.5 w-3.5 ${isDownloading ? "animate-pulse" : ""}`} />
                {isDownloading ? "Telechargement..." : "Telecharger"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 border-blue-600 text-blue-700 hover:bg-blue-50 hover:text-blue-800"
                onClick={handleRefreshAll}
                disabled={refreshingAll}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${refreshingAll ? "animate-spin" : ""}`} />
                Mettre a jour
              </Button>
            </>
          )}
        </div>
      </div>

      {activeRefreshId && <RefreshStatusBar refreshRunId={activeRefreshId} />}

      {/* Level 1 — Category tabs */}
      <div className="inline-flex w-fit max-w-full flex-wrap gap-1 rounded-md border border-line bg-bg2 p-1">
        {CATEGORY_TABS.map((t) => {
          const count = categoryCounts[t.key] ?? 0
          const Icon = t.icon
          return (
            <button
              key={t.key}
              onClick={() => {
                setCategoryTab(t.key)
                setSubcategoryTab("all")
              }}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-[6px] px-3 text-sm font-medium text-fg2 transition-colors hover:text-fg1",
                categoryTab === t.key && "bg-card text-fg1 shadow-xs",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{t.label}</span>
              {count > 0 && <span className="font-mono text-[11px] text-fg3">{count}</span>}
            </button>
          )
        })}
      </div>

      {/* Level 2 — Subcategory tabs (equity only) */}
      {categoryTab === "equity" && (
        <div className="flex gap-0.5 border-b border-dashed border-line">
          {SUBCATEGORY_TABS.map((t) => {
            const count = subcategoryCounts[t.key] ?? 0
            return (
              <button
                key={t.key}
                onClick={() => setSubcategoryTab(t.key)}
                className={cn(
                  "-mb-px border-b-2 border-transparent px-3 py-2 text-xs font-medium text-fg2 transition-colors hover:text-fg1",
                  subcategoryTab === t.key && "border-primary text-fg1",
                )}
              >
                {t.label}
                {t.key !== "all" && <span className="ml-1 font-mono text-[10px] text-fg3">{count}</span>}
              </button>
            )
          })}
        </div>
      )}

      {/* Indices data page content — kept for reference, tab no longer shown */}
      {/* IndicesTabContent removed: indices now surface in Actions/MASI subtab */}

      {categoryTab === "bloomberg" ? (
        <BloombergBridgePanel
          batches={bloombergBatches}
          bridges={bloombergBridges}
          jobs={bloombergJobs}
          series={bloombergSeries}
          masiTickers={visibleMasiTickers}
          onJobCreated={() => {
            mutateBloombergJobs()
            mutateBloombergBridges()
            mutateBloombergSeries()
          }}
          error={bloombergBatchesError ?? bloombergSeriesError ?? bloombergBridgesError ?? bloombergJobsError}
        />
      ) : (
        <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="claude-stat primary">
          <div className="lbl">Symbols</div>
          <div className="val">{formatCount(activeRows.length)}</div>
          <div className="sub">{activeScopeLabel}</div>
        </div>
        <div className="claude-stat">
          <div className="lbl">Daily bars</div>
          <div className="val">{formatCount(totalBars)}</div>
          <div className="sub">{firstBarDate ? `depuis ${firstBarDate}` : "aucun historique"}</div>
        </div>
        <div className="claude-stat">
          <div className="lbl">Avec donnees</div>
          <div className="val">
            {activeRows.length > 0 ? `${Math.round((countWithData / activeRows.length) * 100)}%` : "-"}
          </div>
          <div className="sub">
            {formatCount(countWithData)} / {formatCount(activeRows.length)} instruments
          </div>
        </div>
        <div className="claude-stat">
          <div className="lbl">Dernier bar</div>
          <div className="val">{latestDataDate ?? "-"}</div>
          <div className="sub">
            {staleCount > 0 || neverIngestedCount > 0
              ? `${formatCount(staleCount)} stale / ${formatCount(neverIngestedCount)} sans data`
              : "catalogue a jour"}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex h-8 min-w-[240px] max-w-sm flex-1 items-center gap-2 rounded-md border border-line bg-card px-2.5 text-sm text-fg2">
          <Search className="h-3.5 w-3.5 text-fg3" />
          <input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Rechercher un ticker, ISIN, nom, secteur..."
            className="min-w-0 flex-1 bg-transparent text-sm text-fg1 outline-none placeholder:text-fg3"
          />
        </label>
        <span className="claude-chip">
          <span className="dot" />
          Categorie - {getCategoryLabel(categoryTab)}
        </span>
        {categoryTab === "equity" && (
          <span className="claude-chip">
            <span className="dot" />
            Region - {getSubcategoryLabel(subcategoryTab)}
          </span>
        )}
        <span className="claude-chip active">
          <span className="dot" />
          Actif uniquement
        </span>
        <span className="ml-auto font-mono text-[11px] text-fg3">
          <span className="mr-1 inline-block h-2 w-2 rounded-full bg-success align-middle" />
          {formatCount(freshCount)} / {formatCount(activeRows.length)} sync
          {latestDataDate ? ` - ${latestDataDate}` : ""}
        </span>
      </div>

      {filteredRows.length >= 0 && (
        <Card className="claude-card">
          <CardHeader className="px-5 pb-3 pt-4">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              {getCategoryLabel(categoryTab)}
              {subcategoryTab !== "all" && (
                <Badge variant="secondary" className="text-[10px]">
                  {subcategoryTab.toUpperCase()}
                </Badge>
              )}
              {!isLoading && (
                <span className="font-normal text-muted-foreground">
                  ({filteredCountWithData} avec donnees
                  {filteredRows.length > filteredCountWithData ? `, ${filteredRows.length - filteredCountWithData} sans` : ""}
                  )
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="!p-0">
            {isLoading ? (
              <div className="space-y-2 p-5">
                {[...Array(6)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : catalogError ? (
              <div className="flex min-h-32 flex-col items-center justify-center gap-2 px-5 py-8 text-center">
                <p className="text-sm font-medium text-destructive">
                  Impossible de charger les donnees du catalogue.
                </p>
                <p className="max-w-xl text-sm text-muted-foreground">
                  {catalogError instanceof Error ? catalogError.message : "Erreur proxy/API inconnue."}
                </p>
              </div>
            ) : filteredRows.length === 0 ? (
              <div className="flex h-32 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
                {categoryTab === "equity" && subcategoryTab === "all" ? (
                  <>
                    <span>Aucune action. Ajoutez-en une pour commencer.</span>
                    <Button variant="outline" size="sm" onClick={() => setAddStockOpen(true)} className="gap-1.5">
                      <Plus className="h-3.5 w-3.5" />
                      Ajouter un titre MASI
                    </Button>
                  </>
                ) : (
                  <span>Aucun actif dans cette catégorie.</span>
                )}
              </div>
            ) : (
              <TooltipProvider delayDuration={300}>
                <Table className="claude-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-20">Ticker</TableHead>
                      <TableHead className="hidden lg:table-cell">ISIN</TableHead>
                      <TableHead>Nom</TableHead>
                      <TableHead>Secteur</TableHead>
                      <TableHead className="hidden text-right lg:table-cell">Premier bar</TableHead>
                      <TableHead className="text-right">Dernier bar</TableHead>
                      <TableHead className="hidden text-right md:table-cell">Barres</TableHead>
                      <TableHead className="hidden md:table-cell">Source</TableHead>
                      <TableHead>Statut</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredRows.map((row) => {
                      const startDate = dateOnly(row.start_ts)
                      const endDate = dateOnly(row.end_ts)
                      const sourceLabel = getSourceLabel(row)
                      const isRefreshing = refreshingSymbol === row.symbol
                      const isWaitingForYahooCatalog = isYahooRow(row) && macroCatalog === undefined
                      const rowRefreshLabel = isYahooRow(row)
                        ? "Yahoo"
                        : row.source_provider === "bmce_excel"
                        ? "Excel"
                        : "Bourse"
                      return (
                        <TableRow
                          key={row.symbol}
                          className="cursor-pointer hover:bg-slate-50"
                          onClick={() => setSelectedSymbol(row.symbol)}
                        >
                          <TableCell className="font-mono font-semibold">{row.symbol}</TableCell>

                          <TableCell className="hidden font-mono text-[11px] text-fg3 lg:table-cell">
                            {row.isin ?? "-"}
                          </TableCell>

                          <TableCell className="text-sm text-muted-foreground">
                            {row.display_name ?? "—"}
                          </TableCell>

                          <TableCell className="text-sm text-muted-foreground">
                            {row.sector ?? "—"}
                          </TableCell>

                          <TableCell className="hidden text-right text-xs text-muted-foreground lg:table-cell">
                            {startDate ?? "—"}
                          </TableCell>

                          <TableCell className="text-right text-xs text-muted-foreground">
                            {endDate ?? "—"}
                          </TableCell>

                          <TableCell className="hidden text-right text-xs text-muted-foreground md:table-cell">
                            {formatCount(row.row_count)}
                          </TableCell>

                          <TableCell className="hidden md:table-cell">
                            {sourceLabel !== "-" ? (
                              <Badge variant="outline" className="gap-0.5 text-[10px]">
                                {sourceLabel === "Excel" ? (
                                  <FileSpreadsheet className="h-2.5 w-2.5 text-green-600" />
                                ) : sourceLabel === "Yahoo" ? (
                                  <Globe className="h-2.5 w-2.5 text-purple-600" />
                                ) : (
                                  <RefreshCw className="h-2.5 w-2.5 text-blue-600" />
                                )}
                                {sourceLabel}
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground">-</span>
                            )}
                          </TableCell>

                          <TableCell>
                            {endDate ? (
                              <FreshnessBadge dataAsOf={endDate} />
                            ) : (
                              <Badge variant="outline" className="text-[10px] text-muted-foreground">
                                Non ingere
                              </Badge>
                            )}
                          </TableCell>

                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0 text-fg2 hover:bg-bg3 hover:text-fg1"
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      setSelectedSymbol(row.symbol)
                                    }}
                                  >
                                    <Eye className="h-3.5 w-3.5" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Graphique &amp; calendrier</TooltipContent>
                              </Tooltip>

                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0 text-slate-500 hover:bg-slate-100 hover:text-slate-700"
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      setEditCategoryRow(row)
                                    }}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Modifier la catégorie</TooltipContent>
                              </Tooltip>

                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 w-7 p-0 text-green-600 hover:bg-green-50 hover:text-green-700"
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      setUploadOpen(true)
                                    }}
                                  >
                                    <FileSpreadsheet className="h-3.5 w-3.5" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Importer Excel</TooltipContent>
                              </Tooltip>

                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-7 gap-1 px-2 text-[11px] text-blue-600 border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                                    disabled={isRefreshing || isWaitingForYahooCatalog}
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      handleRowRefresh(row)
                                    }}
                                  >
                                    <RefreshCw
                                      className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`}
                                    />
                                    <span>{rowRefreshLabel}</span>
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>
                                  {isWaitingForYahooCatalog
                                    ? "Chargement du catalogue Yahoo"
                                    : `Mettre à jour via ${isYahooRow(row) ? "Yahoo" : "Bourse"}`}
                                </TooltipContent>
                              </Tooltip>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </TooltipProvider>
            )}
          </CardContent>
        </Card>
      )}

      {filteredRows.length >= 0 && (
        <>
          <StockDetailPanel
            row={selectedRow}
            open={selectedSymbol !== null}
            onClose={() => setSelectedSymbol(null)}
            onSaved={mutateAll}
          />

          <ExcelUploadDialog
            open={uploadOpen}
            onClose={() => setUploadOpen(false)}
            onUploaded={() => {
              setUploadOpen(false)
              mutateAll()
            }}
          />

          <DownloadSelectionDialog
            open={downloadOpen}
            onClose={() => setDownloadOpen(false)}
            rows={activeRows}
            isDownloading={isDownloading}
            defaultSymbols={defaultDownloadSymbols}
            onDownload={handleDownloadExcel}
          />

          <AddFactorDialog
            open={addFactorOpen}
            onClose={() => setAddFactorOpen(false)}
            onAdded={() => {
              setAddFactorOpen(false)
              mutateAll()
            }}
          />

          <AddStockDialog
            open={addStockOpen}
            onClose={() => setAddStockOpen(false)}
            tickers={visibleMasiTickers}
            existingSymbols={new Set(visibleCatalog.map((r) => r.symbol))}
            onSelect={handleAddStock}
          />

          {editCategoryRow && (
            <CategoryEditDialog
              row={editCategoryRow}
              open={editCategoryRow !== null}
              onClose={() => setEditCategoryRow(null)}
              onSaved={() => {
                setEditCategoryRow(null)
                mutateAll()
              }}
            />
          )}
        </>
      )}
        </>
      )}
    </div>
  )
}

function BloombergBridgePanel({
  batches,
  bridges,
  jobs,
  series,
  masiTickers,
  onJobCreated,
  error,
}: {
  batches: BloombergBatch[] | undefined
  bridges: BloombergBridgeStatus[] | undefined
  jobs: BloombergJob[] | undefined
  series: BloombergSeries[] | undefined
  masiTickers: MasiTicker[]
  onJobCreated: () => void
  error: unknown
}) {
  const [jobType, setJobType] = useState<BloombergJobCreateInput["job_type"]>("discovery")
  const [universe, setUniverse] = useState<BloombergJobCreateInput["universe"]>("masi")
  const [frequency, setFrequency] = useState<BloombergJobCreateInput["frequency"]>("daily")
  const [mode, setMode] = useState<BloombergJobCreateInput["mode"]>("discovery_only")
  const [symbolsText, setSymbolsText] = useState("")
  const [fieldsText, setFieldsText] = useState("PX_LAST\nVOLUME")
  const [startDate, setStartDate] = useState("2010-01-01")
  const [endDate, setEndDate] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const totalRows = (batches ?? []).reduce((sum, batch) => sum + batch.row_count, 0)
  const latestBatch = (batches ?? [])[0]
  const latestDate = latestBatch ? dateOnly(latestBatch.created_at) : null
  const uniqueSecurities = new Set((series ?? []).map((row) => row.security)).size
  const uniqueFields = new Set((series ?? []).map((row) => row.field)).size
  const onlineBridge = (bridges ?? []).find((bridge) => !bridge.is_stale && bridge.status !== "offline")
  const activeJobs = (jobs ?? []).filter((job) => ["queued", "leased", "running"].includes(job.status))
  const masiSymbols = masiTickers.map((ticker) => ticker.symbol).filter(Boolean)

  async function submitBloombergJob(override?: Partial<BloombergJobCreateInput>) {
    const selectedSymbols =
      universe === "masi"
        ? []
        : parseListInput(symbolsText).map((symbol) => symbol.toUpperCase())
    const fields = parseListInput(fieldsText).map((field) => field.toUpperCase())
    const payload: BloombergJobCreateInput = {
      job_type: override?.job_type ?? jobType,
      universe: override?.universe ?? universe,
      mode: override?.mode ?? mode,
      frequency: override?.frequency ?? frequency,
      symbols: override?.symbols ?? selectedSymbols,
      fields: override?.fields ?? fields,
      start_date: override?.start_date ?? (startDate || null),
      end_date: override?.end_date ?? (endDate || null),
      apply_to_market_data: false,
      options: {
        requested_from: "data_page",
      },
    }
    setIsSubmitting(true)
    try {
      const job = await createBloombergJob(payload)
      toast.success(`Bloomberg job queued: ${job.job_type}`)
      onJobCreated()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Bloomberg job failed")
    } finally {
      setIsSubmitting(false)
    }
  }

  function runPreflight() {
    submitBloombergJob({
      job_type: "preflight",
      universe: "selected",
      mode: "discovery_only",
      frequency: "daily",
      symbols: masiSymbols.includes("ATW") ? ["ATW"] : masiSymbols.slice(0, 1),
      fields: ["PX_LAST"],
      start_date: null,
      end_date: null,
    })
  }

  if (error) {
    return (
      <Card className="claude-card">
        <CardContent className="flex min-h-32 flex-col items-center justify-center gap-2 px-5 py-8 text-center">
          <p className="text-sm font-medium text-destructive">Impossible de charger les donnees Bloomberg.</p>
          <p className="max-w-xl text-sm text-muted-foreground">
            {error instanceof Error ? error.message : "Erreur proxy/API inconnue."}
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card className="claude-card">
        <CardHeader className="px-5 pb-3 pt-4">
          <CardTitle className="flex items-center justify-between gap-3 text-sm font-semibold">
            <span className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" />
              Bloomberg control
            </span>
            <Badge variant={onlineBridge ? "default" : "outline"} className="gap-1 text-[10px]">
              <Wifi className="h-3 w-3" />
              {onlineBridge ? `${onlineBridge.bridge_id}` : "Bridge offline"}
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 px-5 pb-5">
          <div className="grid gap-3 md:grid-cols-4">
            <div className="space-y-1.5">
              <Label className="text-xs">Job</Label>
              <Select value={jobType} onValueChange={(value) => setJobType(value as BloombergJobCreateInput["job_type"])}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="discovery">Discovery</SelectItem>
                  <SelectItem value="backfill">Backfill</SelectItem>
                  <SelectItem value="refresh">Refresh latest</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Universe</Label>
              <Select value={universe} onValueChange={(value) => setUniverse(value as BloombergJobCreateInput["universe"])}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="masi">MASI all</SelectItem>
                  <SelectItem value="selected">Selected stocks</SelectItem>
                  <SelectItem value="custom">Custom tickers</SelectItem>
                  <SelectItem value="bonds">Bonds</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Frequency</Label>
              <Select value={frequency} onValueChange={(value) => setFrequency(value as BloombergJobCreateInput["frequency"])}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="daily">Daily</SelectItem>
                  <SelectItem value="hourly">Hourly</SelectItem>
                  <SelectItem value="minute">1 minute</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Mode</Label>
              <Select value={mode} onValueChange={(value) => setMode(value as BloombergJobCreateInput["mode"])}>
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="discover_then_backfill">Discover then backfill</SelectItem>
                  <SelectItem value="discovery_only">Discovery only</SelectItem>
                  <SelectItem value="backfill_missing">Backfill missing</SelectItem>
                  <SelectItem value="refresh_latest">Refresh latest</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-[1fr_1fr_160px_160px]">
            <div className="space-y-1.5">
              <Label className="text-xs">Symbols</Label>
              <Textarea
                value={symbolsText}
                onChange={(event) => setSymbolsText(event.target.value)}
                placeholder={universe === "masi" ? `${formatCount(masiSymbols.length)} MASI symbols` : "ATW, BCP, IAM"}
                disabled={universe === "masi"}
                className="min-h-20 font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Fields</Label>
              <Textarea
                value={fieldsText}
                onChange={(event) => setFieldsText(event.target.value)}
                className="min-h-20 font-mono text-xs"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Start</Label>
              <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">End</Label>
              <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} />
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="outline" onClick={runPreflight} disabled={isSubmitting}>
                <ShieldCheck className="h-4 w-4" />
                Preflight
              </Button>
              <Button type="button" size="sm" onClick={() => submitBloombergJob()} disabled={isSubmitting}>
                <Play className="h-4 w-4" />
                Queue job
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="outline" className="text-[10px]">
                {formatCount(activeJobs.length)} active
              </Badge>
              {jobs?.[0] && (
                <span className="font-mono">
                  last {jobs[0].job_type}/{jobs[0].status}
                </span>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="claude-stat primary">
          <div className="lbl">Batches</div>
          <div className="val">{formatCount(batches?.length)}</div>
          <div className="sub">{latestDate ? `dernier ${latestDate}` : "aucun upload"}</div>
        </div>
        <div className="claude-stat">
          <div className="lbl">Series indexees</div>
          <div className="val">{formatCount(series?.length)}</div>
          <div className="sub">{formatCount(uniqueSecurities)} titres</div>
        </div>
        <div className="claude-stat">
          <div className="lbl">Champs</div>
          <div className="val">{formatCount(uniqueFields)}</div>
          <div className="sub">Bloomberg fields</div>
        </div>
        <div className="claude-stat">
          <div className="lbl">Lignes brutes</div>
          <div className="val">{formatCount(totalRows)}</div>
          <div className="sub">uploads stockes</div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="claude-card">
          <CardHeader className="px-5 pb-3 pt-4">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <Wifi className="h-4 w-4" />
              Bridges
            </CardTitle>
          </CardHeader>
          <CardContent className="!p-0">
            {!bridges ? (
              <div className="space-y-2 p-5">
                {[...Array(3)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : bridges.length === 0 ? (
              <div className="flex h-28 items-center justify-center text-sm text-muted-foreground">
                Aucun bridge connecte.
              </div>
            ) : (
              <Table className="claude-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Bridge</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Last seen</TableHead>
                    <TableHead className="text-right">Bloomberg</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {bridges.slice(0, 6).map((bridge) => (
                    <TableRow key={bridge.bridge_id}>
                      <TableCell className="font-mono text-xs font-semibold">{bridge.bridge_id}</TableCell>
                      <TableCell>
                        <Badge variant={bridge.is_stale ? "outline" : "default"} className="text-[10px]">
                          {bridge.is_stale ? "stale" : bridge.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {dateOnly(bridge.last_seen_at) ?? "-"}
                      </TableCell>
                      <TableCell className="text-right text-xs">
                        {asText(bridge.capabilities_json.xbbg)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="claude-card">
          <CardHeader className="px-5 pb-3 pt-4">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <RefreshCw className="h-4 w-4" />
              Jobs
            </CardTitle>
          </CardHeader>
          <CardContent className="!p-0">
            {!jobs ? (
              <div className="space-y-2 p-5">
                {[...Array(3)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : jobs.length === 0 ? (
              <div className="flex h-28 items-center justify-center text-sm text-muted-foreground">
                Aucun job Bloomberg.
              </div>
            ) : (
              <Table className="claude-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Type</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Stage</TableHead>
                    <TableHead className="text-right">Created</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {jobs.slice(0, 8).map((job) => (
                    <TableRow key={job.id}>
                      <TableCell>
                        <div className="font-mono text-xs font-semibold">{job.job_type}</div>
                        <div className="font-mono text-[10px] text-muted-foreground">
                          {asText(job.spec_json.frequency)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={job.status === "failed" ? "destructive" : "outline"} className="text-[10px]">
                          {job.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {asText(job.progress_json.stage)}
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {dateOnly(job.created_at) ?? "-"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="claude-card">
          <CardHeader className="px-5 pb-3 pt-4">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <Database className="h-4 w-4" />
              Recent batches
            </CardTitle>
          </CardHeader>
          <CardContent className="!p-0">
            {!batches ? (
              <div className="space-y-2 p-5">
                {[...Array(4)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : batches.length === 0 ? (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                Aucun batch Bloomberg recu.
              </div>
            ) : (
              <Table className="claude-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Bridge</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead className="text-right">Lignes</TableHead>
                    <TableHead className="text-right">Series</TableHead>
                    <TableHead className="text-right">Date</TableHead>
                    <TableHead className="text-right">Fichiers</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {batches.slice(0, 12).map((batch) => (
                    <TableRow key={batch.id}>
                      <TableCell>
                        <div className="font-mono text-xs font-semibold">{batch.bridge_id}</div>
                        <div className="max-w-[180px] truncate font-mono text-[10px] text-muted-foreground">
                          {batch.request_id}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]">
                          {batch.bloomberg_source}/{batch.kind}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {formatCount(batch.row_count)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {formatCount(batch.series_count)}
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {dateOnly(batch.created_at) ?? "-"}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1 px-2 text-[11px]"
                            onClick={() => window.open(`/api/bloomberg/batches/${batch.id}/raw`, "_blank")}
                          >
                            <Download className="h-3.5 w-3.5" />
                            Raw
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 gap-1 px-2 text-[11px]"
                            disabled={!batch.normalized_object_key}
                            onClick={() => window.open(`/api/bloomberg/batches/${batch.id}/normalized`, "_blank")}
                          >
                            <Download className="h-3.5 w-3.5" />
                            Parquet
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card className="claude-card">
          <CardHeader className="px-5 pb-3 pt-4">
            <CardTitle className="flex items-center gap-2 text-sm font-semibold">
              <TrendingUp className="h-4 w-4" />
              Indexed series
            </CardTitle>
          </CardHeader>
          <CardContent className="!p-0">
            {!series ? (
              <div className="space-y-2 p-5">
                {[...Array(4)].map((_, i) => (
                  <Skeleton key={i} className="h-10 w-full" />
                ))}
              </div>
            ) : series.length === 0 ? (
              <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                Aucune serie indexee.
              </div>
            ) : (
              <Table className="claude-table">
                <TableHeader>
                  <TableRow>
                    <TableHead>Security</TableHead>
                    <TableHead>Field</TableHead>
                    <TableHead className="text-right">Debut</TableHead>
                    <TableHead className="text-right">Fin</TableHead>
                    <TableHead className="text-right">Points</TableHead>
                    <TableHead className="text-right">Fichier</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {series.slice(0, 12).map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="font-mono text-xs font-semibold">{row.security}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]">
                          {row.field}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {dateOnly(row.start_ts) ?? "-"}
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {dateOnly(row.end_ts) ?? "-"}
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">{formatCount(row.row_count)}</TableCell>
                      <TableCell className="text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 gap-1 px-2 text-[11px]"
                          onClick={() => window.open(`/api/bloomberg/series/${row.id}/download`, "_blank")}
                        >
                          <Download className="h-3.5 w-3.5" />
                          Parquet
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default function DataPage() {
  if (isPublicDashboardOnly) {
    return <PublicDataPage />
  }
  return <PrivateDataPage />
}

/* ── Add Stock Dialog (MASI autocomplete) ─────────────────────────────────── */

function DownloadSelectionDialog({
  open,
  onClose,
  rows,
  defaultSymbols,
  isDownloading,
  onDownload,
}: {
  open: boolean
  onClose: () => void
  rows: MarketCatalogRow[]
  defaultSymbols: string[]
  isDownloading: boolean
  onDownload: (symbols: string[], preset?: string) => void
}) {
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const downloadableRows = useMemo(
    () => rows.filter((row) => row.has_canonical_data),
    [rows],
  )
  const downloadableSet = useMemo(
    () => new Set(downloadableRows.map((row) => row.symbol)),
    [downloadableRows],
  )
  const selectedSet = useMemo(() => new Set(selectedSymbols), [selectedSymbols])
  const masi20Available = useMemo(
    () => MASI20_SYMBOLS.filter((symbol) => downloadableSet.has(symbol)),
    [downloadableSet],
  )

  useEffect(() => {
    if (!open) return
    const initial = defaultSymbols.filter((symbol) => downloadableSet.has(symbol))
    setSelectedSymbols(initial.length > 0 ? initial : downloadableRows.map((row) => row.symbol))
  }, [defaultSymbols, downloadableRows, downloadableSet, open])

  function toggleSymbol(symbol: string) {
    setSelectedSymbols((current) =>
      current.includes(symbol)
        ? current.filter((item) => item !== symbol)
        : [...current, symbol],
    )
  }

  function selectAll() {
    setSelectedSymbols(downloadableRows.map((row) => row.symbol))
  }

  function selectMasi20() {
    setSelectedSymbols(masi20Available)
  }

  const isMasi20Selection =
    selectedSymbols.length > 0 &&
    selectedSymbols.length === masi20Available.length &&
    selectedSymbols.every((symbol) => masi20Available.includes(symbol))

  return (
    <Dialog open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Telecharger les donnees</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={selectAll}>
              Tout selectionner
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={selectMasi20}
              disabled={masi20Available.length === 0}
            >
              Selection MASI 20
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setSelectedSymbols([])}>
              Effacer
            </Button>
            <span className="ml-auto font-mono text-xs text-muted-foreground">
              {selectedSymbols.length} / {downloadableRows.length}
            </span>
          </div>

          <div className="max-h-80 overflow-y-auto rounded-md border border-line">
            {downloadableRows.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                Aucun instrument telechargeable dans ce filtre.
              </div>
            ) : (
              downloadableRows.map((row) => {
                const checked = selectedSet.has(row.symbol)
                return (
                  <button
                    key={row.symbol}
                    type="button"
                    onClick={() => toggleSymbol(row.symbol)}
                    className={cn(
                      "flex w-full items-center gap-3 border-b border-line px-3 py-2 text-left text-sm last:border-b-0 hover:bg-bg3",
                      checked && "bg-primary/5",
                    )}
                  >
                    <span
                      className={cn(
                        "grid h-4 w-4 flex-none place-items-center rounded border border-line text-[10px]",
                        checked && "border-primary bg-primary text-primary-foreground",
                      )}
                    >
                      {checked ? "x" : ""}
                    </span>
                    <span className="w-14 flex-none font-mono font-semibold">{row.symbol}</span>
                    <span className="min-w-0 flex-1 truncate text-muted-foreground">
                      {row.display_name ?? row.sector ?? "-"}
                    </span>
                    <span className="hidden font-mono text-xs text-fg3 sm:inline">
                      {dateOnly(row.end_ts) ?? "-"}
                    </span>
                  </button>
                )
              })
            )}
          </div>

          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={onClose}>
              Annuler
            </Button>
            <Button
              type="button"
              onClick={() => onDownload(selectedSymbols, isMasi20Selection ? "masi20" : undefined)}
              disabled={isDownloading || selectedSymbols.length === 0}
            >
              <Download className={`h-4 w-4 ${isDownloading ? "animate-pulse" : ""}`} />
              {isDownloading ? "Telechargement..." : "Telecharger Excel"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function AddStockDialog({
  open,
  onClose,
  tickers,
  existingSymbols,
  onSelect,
}: {
  open: boolean
  onClose: () => void
  tickers: MasiTicker[]
  existingSymbols: Set<string>
  onSelect: (ticker: MasiTicker) => void
}) {
  const [search, setSearch] = useState("")

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return tickers
    return tickers.filter(
      (t) =>
        t.symbol.toLowerCase().includes(q) ||
        t.display_name.toLowerCase().includes(q) ||
        t.sector.toLowerCase().includes(q)
    )
  }, [tickers, search])

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Ajouter un titre MASI</DialogTitle>
        </DialogHeader>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            placeholder="Rechercher par ticker, nom ou secteur..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border bg-background py-2.5 pl-10 pr-4 text-sm outline-none focus:ring-2 focus:ring-primary/20"
            autoFocus
          />
        </div>
        <div className="max-h-80 overflow-y-auto -mx-1">
          {filtered.length === 0 ? (
            <div className="py-8 text-center text-sm text-muted-foreground">
              Aucun ticker MASI correspondant.
            </div>
          ) : (
            filtered.map((t) => {
              const exists = existingSymbols.has(t.symbol)
              return (
                <button
                  key={t.symbol}
                  disabled={exists}
                  onClick={() => onSelect(t)}
                  className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors ${
                    exists
                      ? "opacity-40 cursor-not-allowed"
                      : "hover:bg-slate-50 cursor-pointer"
                  }`}
                >
                  <span className="font-mono text-sm font-bold w-12">{t.symbol}</span>
                  <span className="flex-1 text-sm">{t.display_name}</span>
                  <Badge variant="outline" className="text-[10px]">{t.sector}</Badge>
                  {exists && (
                    <CheckCircle2 className="h-4 w-4 text-green-600 shrink-0" />
                  )}
                </button>
              )
            })
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
