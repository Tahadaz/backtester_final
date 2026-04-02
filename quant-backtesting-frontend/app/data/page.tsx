"use client"

import { useState, useMemo } from "react"
import { useMarketCatalog, useTrackedStocks, useMasiTickers } from "@/hooks/use-api"
import { refreshAllStocks, addTrackedStock, refreshSingleStock, deleteMarketSymbol } from "@/lib/api"
import type { MarketCatalogRow, MasiTicker } from "@/lib/api"
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
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ExternalLink, FileSpreadsheet, RefreshCw, Eye, CheckCircle2, Circle, Trash2, Plus, Search } from "lucide-react"
import { toast } from "sonner"

type MarketTab = "masi" | "other"

export default function DataPage() {
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
  const [deleteTarget, setDeleteTarget] = useState<MarketCatalogRow | null>(null)
  const [deletingSymbol, setDeletingSymbol] = useState<string | null>(null)

  const trackedSet = new Set((catalog ?? []).filter((r) => r.is_tracked).map((r) => r.symbol))
  const selectedRow: MarketCatalogRow | null =
    (catalog ?? []).find((r) => r.symbol === selectedSymbol) ?? null

  const allRows = catalog ?? []
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
    } catch {
      toast.error("Impossible de lancer la mise a jour")
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
      toast.error(`Echec: ${err instanceof Error ? err.message : "Erreur"}`)
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

  async function handleDeleteSymbol() {
    if (!deleteTarget) return
    const symbol = deleteTarget.symbol
    setDeletingSymbol(symbol)
    try {
      await deleteMarketSymbol(symbol)
      if (selectedSymbol === symbol) {
        setSelectedSymbol(null)
      }
      setDeleteTarget(null)
      mutateAll()
      toast.success(`${symbol} supprime du catalogue`)
    } catch (err: unknown) {
      toast.error(`Echec de suppression: ${err instanceof Error ? err.message : "Erreur"}`)
    } finally {
      setDeletingSymbol(null)
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
            size="sm"
            className="gap-1.5 bg-blue-600 text-white hover:bg-blue-700"
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
                    <TableHead className="hidden sm:table-cell">Nom</TableHead>
                    <TableHead className="hidden lg:table-cell">Secteur</TableHead>
                    <TableHead>Debut</TableHead>
                    <TableHead>Fin</TableHead>
                    <TableHead className="hidden md:table-cell text-right">Barres</TableHead>
                    <TableHead className="hidden md:table-cell">Source</TableHead>
                    <TableHead>Fraicheur</TableHead>
                    <TableHead className="hidden lg:table-cell">Bourse</TableHead>
                    <TableHead className="hidden lg:table-cell text-center">Suivi</TableHead>
                    <TableHead className="w-[220px] text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const startDate = row.start_ts?.slice(0, 10) ?? null
                    const endDate = row.end_ts?.slice(0, 10) ?? null
                    const isRefreshing = refreshingSymbol === row.symbol
                    const isDeleting = deletingSymbol === row.symbol
                    return (
                      <TableRow
                        key={row.symbol}
                        className="cursor-pointer hover:bg-slate-50"
                        onClick={() => setSelectedSymbol(row.symbol)}
                      >
                        <TableCell className="font-mono font-semibold">{row.symbol}</TableCell>

                        <TableCell className="hidden text-sm text-muted-foreground sm:table-cell">
                          {row.display_name ?? "\u2014"}
                        </TableCell>

                        <TableCell className="hidden text-sm text-muted-foreground lg:table-cell">
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

                        <TableCell className="hidden lg:table-cell">
                          {row.bourse_url ? (
                            <a
                              href={row.bourse_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <ExternalLink className="h-3 w-3" />
                              Bourse
                            </a>
                          ) : (
                            <span className="text-xs text-muted-foreground">{"\u2014"}</span>
                          )}
                        </TableCell>

                        <TableCell className="hidden text-center lg:table-cell">
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <span className="inline-flex justify-center">
                                {row.is_tracked ? (
                                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                                ) : (
                                  <Circle className="h-4 w-4 text-muted-foreground/40" />
                                )}
                              </span>
                            </TooltipTrigger>
                            <TooltipContent>
                              {row.is_tracked ? "Suivi (stock_master)" : "Non suivi"}
                            </TooltipContent>
                          </Tooltip>
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
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0 text-blue-600 hover:bg-blue-50 hover:text-blue-700"
                                  disabled={isRefreshing || isDeleting}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    handleBourseRefresh(row.symbol)
                                  }}
                                >
                                  <RefreshCw
                                    className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`}
                                  />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Mettre a jour via Bourse</TooltipContent>
                            </Tooltip>

                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0 text-red-600 hover:bg-red-50 hover:text-red-700"
                                  disabled={isDeleting}
                                  onClick={(event) => {
                                    event.stopPropagation()
                                    setDeleteTarget(row)
                                  }}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Supprimer du catalogue</TooltipContent>
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
        tickers={masiTickers ?? []}
        existingSymbols={new Set(allRows.map((r) => r.symbol))}
        onSelect={handleAddStock}
      />

      <AlertDialog open={!!deleteTarget} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Supprimer ce symbole ?</AlertDialogTitle>
            <AlertDialogDescription>
              {deleteTarget ? (
                <>
                  Cette action supprimera <strong>{deleteTarget.symbol}</strong> du catalogue canonique,
                  son historique OHLCV et son suivi.
                </>
              ) : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={!!deletingSymbol}>Annuler</AlertDialogCancel>
            <AlertDialogAction
              disabled={!!deletingSymbol}
              onClick={(event) => {
                event.preventDefault()
                void handleDeleteSymbol()
              }}
              className="bg-red-600 hover:bg-red-700"
            >
              {deletingSymbol ? "Suppression..." : "Supprimer"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
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
