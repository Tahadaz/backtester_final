"use client"

import { useState, useMemo } from "react"
import { useMarketCatalog, useTrackedStocks, useMasiTickers } from "@/hooks/use-api"
import { ApiError, refreshAllStocks, addTrackedStock, refreshSingleStock } from "@/lib/api"
import type { MarketCatalogRow, MasiTicker } from "@/lib/api"
import { PublicDataPage } from "@/components/data/public-data-page"
import { StockDetailPanel } from "@/components/data/stock-detail-panel"
import { ExcelUploadDialog } from "@/components/data/excel-upload-dialog"
import { RefreshStatusBar } from "@/components/data/refresh-status-bar"
import { FreshnessBadge } from "@/components/data/freshness-badge"
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
import { FileSpreadsheet, RefreshCw, Eye, CheckCircle2, Plus, Search } from "lucide-react"
import { toast } from "sonner"

type MarketTab = "masi" | "other"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"
const DATA_PAGE_HIDDEN_STOCKS = new Set([ "TGCC", "MAJ", "MAJJ", "WORKSHEET", "INSTRUMENT"])
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
  const { data: catalog, isLoading, mutate: mutateCatalog } = useMarketCatalog()
  const { mutate: mutateTracked } = useTrackedStocks()
  const { data: masiTickers } = useMasiTickers()

  const [marketTab, setMarketTab] = useState<MarketTab>("masi")
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [addStockOpen, setAddStockOpen] = useState(false)
  const [activeRefreshId, setActiveRefreshId] = useState<string | null>(null)
  const [refreshingAll, setRefreshingAll] = useState(false)
  const [refreshingSymbol, setRefreshingSymbol] = useState<string | null>(null)

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
  const selectedRow: MarketCatalogRow | null =
    visibleCatalog.find((r) => r.symbol === selectedSymbol) ?? null

  const allRows = visibleCatalog
  const masiRows = useMemo(() => allRows.filter((r) => r.market === "masi"), [allRows])
  const otherRows = useMemo(() => allRows.filter((r) => r.market !== "masi"), [allRows])
  const rows = marketTab === "masi" ? masiRows : otherRows

  function mutateAll() {
    mutateCatalog()
    mutateTracked()
  }

  async function handleRefreshAll() {
    setRefreshingAll(true)
    try {
      const res = await refreshAllStocks()
      setActiveRefreshId(res.refresh_run_id)
      toast.success("Mise a jour Bourse lancee pour tous les titres suivis")
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

  async function handleBourseRefresh(symbol: string) {
    setRefreshingSymbol(symbol)
    try {
      if (!trackedSet.has(symbol)) {
        try {
          await addTrackedStock({ symbol, track_source: "bourse_direct" })
          mutateTracked()
        } catch (error: unknown) {
          if (!(error instanceof Error && error.message.includes("409"))) throw error
        }
      }
      const res = await refreshSingleStock(symbol)
      setActiveRefreshId(res.refresh_run_id)
      toast.success(`Mise a jour Bourse lancee pour ${symbol}`)
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


  const countWithData = rows.filter((r) => r.has_canonical_data).length

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Donnees de marche</h1>
          <p className="text-sm text-muted-foreground">
            Univers canonique pour les imports Excel et les mises a jour Bourse.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => setAddStockOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            Ajouter un titre
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
            className="gap-1.5 border-blue-600 text-blue-700 hover:bg-blue-50 hover:text-blue-800"
            onClick={handleRefreshAll}
            disabled={refreshingAll}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshingAll ? "animate-spin" : ""}`} />
            Mettre a jour via Bourse
          </Button>
        </div>
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

      {/* Market tabs */}
      <div className="flex gap-1 border-b">
        {([
          { key: "masi" as MarketTab, label: "MASI", count: masiRows.length },
          { key: "other" as MarketTab, label: "Autres", count: otherRows.length },
        ]).map((t) => (
          <button
            key={t.key}
            onClick={() => setMarketTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              marketTab === t.key
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label} ({t.count})
          </button>
        ))}
      </div>

      <Card>
        <CardHeader className="px-5 pb-3 pt-4">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold">
            {marketTab === "masi" ? "Actions MASI" : "Autres actifs"}
            {!isLoading && (
              <span className="font-normal text-muted-foreground">
                ({countWithData} avec donnees
                {rows.length > countWithData ? `, ${rows.length - countWithData} sans` : ""}
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
          ) : rows.length === 0 ? (
            <div className="flex h-32 flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              {marketTab === "masi" ? (
                <>
                  <span>Aucun titre MASI. Ajoutez-en un pour commencer.</span>
                  <Button variant="outline" size="sm" onClick={() => setAddStockOpen(true)} className="gap-1.5">
                    <Plus className="h-3.5 w-3.5" />
                    Ajouter un titre MASI
                  </Button>
                </>
              ) : (
                <span>Aucun actif non-MASI pour le moment.</span>
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
                    <TableHead>Debut</TableHead>
                    <TableHead>Fin</TableHead>
                    <TableHead className="hidden md:table-cell text-right">Barres</TableHead>
                    <TableHead className="hidden md:table-cell">Source</TableHead>
                    <TableHead>Fraicheur</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const startDate = row.start_ts?.slice(0, 10) ?? null
                    const endDate = row.end_ts?.slice(0, 10) ?? null
                    const isRefreshing = refreshingSymbol === row.symbol
                    return (
                      <TableRow
                        key={row.symbol}
                        className="cursor-pointer hover:bg-slate-50"
                        onClick={() => setSelectedSymbol(row.symbol)}
                      >
                        <TableCell className="font-mono font-semibold">{row.symbol}</TableCell>

                        <TableCell className="text-sm text-muted-foreground">
                          {row.display_name ?? "\u2014"}
                        </TableCell>

                        <TableCell className="text-sm text-muted-foreground">
                          {row.sector ?? "\u2014"}
                        </TableCell>

                        <TableCell className="text-xs text-muted-foreground">
                          {startDate ?? "\u2014"}
                        </TableCell>

                        <TableCell className="text-xs text-muted-foreground">
                          {endDate ?? "\u2014"}
                        </TableCell>

                        <TableCell className="hidden text-right text-xs text-muted-foreground md:table-cell">
                          {row.row_count?.toLocaleString() ?? "\u2014"}
                        </TableCell>

                        <TableCell className="hidden md:table-cell">
                          {row.source_provider ? (
                            <Badge variant="outline" className="gap-0.5 text-[10px]">
                              {row.source_provider === "bmce_excel" ? (
                                <>
                                  <FileSpreadsheet className="h-2.5 w-2.5 text-green-600" />
                                  Excel
                                </>
                              ) : (
                                <>
                                  <RefreshCw className="h-2.5 w-2.5 text-blue-600" />
                                  {row.source_provider}
                                </>
                              )}
                            </Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground">{"\u2014"}</span>
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
                                  disabled={isRefreshing}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    handleBourseRefresh(row.symbol)
                                  }}
                                >
                                  <RefreshCw
                                    className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`}
                                  />
                                  <span>Bourse</span>
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Mettre a jour via Bourse</TooltipContent>
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

      <AddStockDialog
        open={addStockOpen}
        onClose={() => setAddStockOpen(false)}
        tickers={visibleMasiTickers}
        existingSymbols={new Set(allRows.map((r) => r.symbol))}
        onSelect={handleAddStock}
      />

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

