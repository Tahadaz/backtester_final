"use client"

import { useState, useMemo } from "react"
import { useMarketCatalog, useTrackedStocks, useMasiTickers, useMacroCatalog } from "@/hooks/use-api"
import {
  ApiError,
  refreshAllStocks,
  addTrackedStock,
  refreshSingleStock,
  enqueueAllMacroIngest,
  enqueueMacroIngest,
} from "@/lib/api"
import type { MarketCatalogRow, MasiTicker } from "@/lib/api"
import { PublicDataPage } from "@/components/data/public-data-page"
import { StockDetailPanel } from "@/components/data/stock-detail-panel"
import { ExcelUploadDialog } from "@/components/data/excel-upload-dialog"
import { RefreshStatusBar } from "@/components/data/refresh-status-bar"
import { FreshnessBadge } from "@/components/data/freshness-badge"
import { CategoryEditDialog } from "@/components/data/category-edit-dialog"
import { AddFactorDialog } from "@/components/data/add-factor-dialog"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
import { FileSpreadsheet, Globe, RefreshCw, Eye, CheckCircle2, Plus, Search, Download, Pencil } from "lucide-react"
import { toast } from "sonner"

type CategoryTab = "equity" | "commodity" | "forex" | "bond" | "crypto"
type SubcategoryTab = "all" | "masi" | "us" | "european" | "asian"

const CATEGORY_TABS: { key: CategoryTab; label: string }[] = [
  { key: "equity", label: "Actions" },
  { key: "commodity", label: "Matières premières" },
  { key: "forex", label: "Devises" },
  { key: "bond", label: "Obligations" },
  { key: "crypto", label: "Crypto" },
]

const SUBCATEGORY_TABS: { key: SubcategoryTab; label: string }[] = [
  { key: "all", label: "Tous" },
  { key: "masi", label: "MASI" },
  { key: "us", label: "US" },
  { key: "european", label: "Europe" },
  { key: "asian", label: "Asie" },
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

function PrivateDataPage() {
  const { data: catalog, error: catalogError, isLoading, mutate: mutateCatalog } = useMarketCatalog()
  const { mutate: mutateTracked } = useTrackedStocks()
  const { data: masiTickers } = useMasiTickers()
  const { data: macroCatalog, mutate: mutateMacroCatalog } = useMacroCatalog()

  const [categoryTab, setCategoryTab] = useState<CategoryTab>("equity")
  const [subcategoryTab, setSubcategoryTab] = useState<SubcategoryTab>("all")
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [editCategoryRow, setEditCategoryRow] = useState<MarketCatalogRow | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [addStockOpen, setAddStockOpen] = useState(false)
  const [addFactorOpen, setAddFactorOpen] = useState(false)
  const [activeRefreshId, setActiveRefreshId] = useState<string | null>(null)
  const [refreshingAll, setRefreshingAll] = useState(false)
  const [refreshingSymbol, setRefreshingSymbol] = useState<string | null>(null)
  const [isDownloading, setIsDownloading] = useState(false)

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
    return counts
  }, [visibleCatalog])

  // Rows for active category + subcategory
  const filteredRows = useMemo(() => {
    const byType = visibleCatalog.filter((r) => (r.asset_type ?? "equity") === categoryTab)
    if (subcategoryTab === "all") return byType
    return byType.filter((r) => r.market_region === subcategoryTab)
  }, [visibleCatalog, categoryTab, subcategoryTab])

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

  async function handleDownloadExcel() {
    setIsDownloading(true)
    try {
      const params = new URLSearchParams()
      params.set("asset_type", categoryTab)
      if (subcategoryTab !== "all") params.set("market_region", subcategoryTab)
      const qs = params.toString()
      const res = await fetch(`/api/market-data/download-excel${qs ? `?${qs}` : ""}`)
      if (!res.ok) throw new Error("Download failed")
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      const parts = [categoryTab, subcategoryTab !== "all" ? subcategoryTab : ""]
      a.download = `${parts.filter(Boolean).join("-")}-data.xlsx`
      a.click()
      URL.revokeObjectURL(url)
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

  const isIndicesTab = false
  const countWithData = filteredRows.filter((r) => r.has_canonical_data).length

  function getCategoryLabel(tab: CategoryTab) {
    switch (tab) {
      case "equity": return "Actions"
      case "commodity": return "Matières premières"
      case "forex": return "Devises"
      case "bond": return "Obligations"
      case "crypto": return "Crypto"
      default: return tab
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Donnees de marche</h1>
          <p className="text-sm text-muted-foreground">
            Univers canonique pour les imports Excel et les mises a jour Bourse.
          </p>
        </div>
        {!isIndicesTab && (
          <div className="flex items-center gap-2">
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
              onClick={handleDownloadExcel}
              disabled={isDownloading}
            >
              <Download className={`h-3.5 w-3.5 ${isDownloading ? "animate-pulse" : ""}`} />
              {isDownloading ? "Telechargement..." : `Telecharger (${getCategoryLabel(categoryTab)}${subcategoryTab !== "all" ? ` / ${subcategoryTab.toUpperCase()}` : ""})`}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 border-blue-600 text-blue-700 hover:bg-blue-50 hover:text-blue-800"
              onClick={handleRefreshAll}
              disabled={refreshingAll}
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshingAll ? "animate-spin" : ""}`} />
              Mettre à jour
            </Button>
          </div>
        )}
      </div>

      {activeRefreshId && <RefreshStatusBar refreshRunId={activeRefreshId} />}

      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <FileSpreadsheet className="h-3 w-3 text-green-600" />
          Importer un fichier Excel
        </span>
        <span className="text-border">&middot;</span>
        <span className="flex items-center gap-1">
          <RefreshCw className="h-3 w-3 text-blue-600" />
          Mettre a jour via Bourse de Casablanca
        </span>
        <span className="text-border">&middot;</span>
        <span>Cliquer sur une ligne ouvre le graphique et le calendrier.</span>
      </div>

      {/* Level 1 — Category tabs */}
      <div className="flex gap-1 border-b">
        {CATEGORY_TABS.map((t) => {
          const count = categoryCounts[t.key] ?? 0
          return (
            <button
              key={t.key}
              onClick={() => {
                setCategoryTab(t.key)
                setSubcategoryTab("all")
              }}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                categoryTab === t.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}{count > 0 ? ` (${count})` : ""}
            </button>
          )
        })}
      </div>

      {/* Level 2 — Subcategory tabs (equity only) */}
      {categoryTab === "equity" && (
        <div className="flex gap-1 border-b border-dashed">
          {SUBCATEGORY_TABS.map((t) => {
            const count = subcategoryCounts[t.key] ?? 0
            return (
              <button
                key={t.key}
                onClick={() => setSubcategoryTab(t.key)}
                className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                  subcategoryTab === t.key
                    ? "border-primary text-primary"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                }`}
              >
                {t.label}{t.key !== "all" ? ` (${count})` : ""}
              </button>
            )
          })}
        </div>
      )}

      {/* Indices data page content — kept for reference, tab no longer shown */}
      {/* IndicesTabContent removed: indices now surface in Actions/MASI subtab */}

      {filteredRows.length >= 0 && (
        <Card>
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
                  ({countWithData} avec donnees
                  {filteredRows.length > countWithData ? `, ${filteredRows.length - countWithData} sans` : ""}
                  )
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 pb-2">
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
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-20">Ticker</TableHead>
                      <TableHead>Nom</TableHead>
                      <TableHead>Secteur</TableHead>
                      <TableHead>Début</TableHead>
                      <TableHead>Fin</TableHead>
                      <TableHead className="hidden md:table-cell text-right">Barres</TableHead>
                      <TableHead className="hidden md:table-cell">Source</TableHead>
                      <TableHead>Fraîcheur</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredRows.map((row) => {
                      const startDate = row.start_ts?.slice(0, 10) ?? null
                      const endDate = row.end_ts?.slice(0, 10) ?? null
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

                          <TableCell className="text-sm text-muted-foreground">
                            {row.display_name ?? "—"}
                          </TableCell>

                          <TableCell className="text-sm text-muted-foreground">
                            {row.sector ?? "—"}
                          </TableCell>

                          <TableCell className="text-xs text-muted-foreground">
                            {startDate ?? "—"}
                          </TableCell>

                          <TableCell className="text-xs text-muted-foreground">
                            {endDate ?? "—"}
                          </TableCell>

                          <TableCell className="hidden text-right text-xs text-muted-foreground md:table-cell">
                            {row.row_count?.toLocaleString() ?? "—"}
                          </TableCell>

                          <TableCell className="hidden md:table-cell">
                            {row.source_provider ? (
                              <Badge variant="outline" className="gap-0.5 text-[10px]">
                                {row.source_provider === "bmce_excel" ? (
                                  <>
                                    <FileSpreadsheet className="h-2.5 w-2.5 text-green-600" />
                                    Excel
                                  </>
                                ) : row.source_provider === "yahoo" ? (
                                  <>
                                    <Globe className="h-2.5 w-2.5 text-purple-600" />
                                    Yahoo
                                  </>
                                ) : (
                                  <>
                                    <RefreshCw className="h-2.5 w-2.5 text-blue-600" />
                                    {row.source_provider === "bourse_direct" ? "Bourse" : row.source_provider}
                                  </>
                                )}
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground">{"—"}</span>
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
                                    variant="outline"
                                    size="sm"
                                    className="h-7 gap-1 px-2 text-[11px]"
                                    onClick={(event) => {
                                      event.stopPropagation()
                                      setSelectedSymbol(row.symbol)
                                    }}
                                  >
                                    <Eye className="h-3.5 w-3.5" />
                                    <span>Graphique</span>
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
