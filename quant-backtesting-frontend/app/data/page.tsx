"use client"

import { useState } from "react"
import { useMarketCatalog, useTrackedStocks } from "@/hooks/use-api"
import { refreshAllStocks, addTrackedStock, refreshSingleStock } from "@/lib/api"
import type { MarketCatalogRow } from "@/lib/api"
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
import { ExternalLink, FileSpreadsheet, RefreshCw, Eye, CheckCircle2, Circle } from "lucide-react"
import { toast } from "sonner"

export default function DataPage() {
  const { data: catalog, isLoading, mutate: mutateCatalog } = useMarketCatalog()
  // useTrackedStocks is used only to know which symbols are tracked for the refresh action
  const { mutate: mutateTracked } = useTrackedStocks()

  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [activeRefreshId, setActiveRefreshId] = useState<string | null>(null)
  const [refreshingAll, setRefreshingAll] = useState(false)
  const [refreshingSymbol, setRefreshingSymbol] = useState<string | null>(null)

  const trackedSet = new Set(
    (catalog ?? []).filter((r) => r.is_tracked).map((r) => r.symbol)
  )

  // Find the selected catalog row to pass to the detail panel
  const selectedRow: MarketCatalogRow | null =
    (catalog ?? []).find((r) => r.symbol === selectedSymbol) ?? null

  function mutateAll() {
    mutateCatalog()
    mutateTracked()
  }

  async function handleRefreshAll() {
    setRefreshingAll(true)
    try {
      const res = await refreshAllStocks()
      setActiveRefreshId(res.refresh_run_id)
      toast.success("Mise à jour Bourse lancée pour tous les titres suivis")
    } catch {
      toast.error("Impossible de lancer la mise à jour")
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
        } catch (e: unknown) {
          if (!(e instanceof Error && e.message.includes("409"))) throw e
        }
      }
      const res = await refreshSingleStock(symbol)
      setActiveRefreshId(res.refresh_run_id)
      toast.success(`Mise à jour Bourse lancée pour ${symbol}`)
    } catch (err: unknown) {
      toast.error(`Échec: ${err instanceof Error ? err.message : "Erreur"}`)
    } finally {
      setRefreshingSymbol(null)
    }
  }

  const rows = catalog ?? []
  const countWithData = rows.filter((r) => r.has_canonical_data).length

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Données de marché</h1>
          <p className="text-sm text-muted-foreground">
            Univers canonique — imports Excel et données Bourse de Casablanca
          </p>
        </div>
        <div className="flex items-center gap-2">
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
            className="gap-1.5 bg-blue-600 hover:bg-blue-700 text-white"
            onClick={handleRefreshAll}
            disabled={refreshingAll}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshingAll ? "animate-spin" : ""}`} />
            Mettre à jour via Bourse
          </Button>
        </div>
      </div>

      {/* Refresh progress bar */}
      {activeRefreshId && <RefreshStatusBar refreshRunId={activeRefreshId} />}

      {/* Legend */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1">
          <FileSpreadsheet className="h-3 w-3 text-green-600" />
          Importer un fichier Excel (format BMCE / Casablanca)
        </span>
        <span className="text-border">·</span>
        <span className="flex items-center gap-1">
          <RefreshCw className="h-3 w-3 text-blue-600" />
          Mettre à jour via Bourse de Casablanca
        </span>
      </div>

      {/* Main catalog table */}
      <Card>
        <CardHeader className="pb-3 pt-4 px-5">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            Univers de données
            {!isLoading && (
              <span className="font-normal text-muted-foreground">
                ({countWithData} avec données
                {rows.length > countWithData
                  ? `, ${rows.length - countWithData} sans`
                  : ""}
                )
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 pb-2">
          {isLoading ? (
            <div className="p-5 space-y-2">
              {[...Array(6)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
              Aucune donnée. Importez un fichier Excel pour commencer.
            </div>
          ) : (
            <TooltipProvider delayDuration={300}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-20">Ticker</TableHead>
                    <TableHead className="hidden sm:table-cell">Nom</TableHead>
                    <TableHead>Début</TableHead>
                    <TableHead>Fin</TableHead>
                    <TableHead className="hidden md:table-cell text-right">Barres</TableHead>
                    <TableHead className="hidden md:table-cell">Source</TableHead>
                    <TableHead>Fraîcheur</TableHead>
                    <TableHead className="hidden lg:table-cell">Bourse</TableHead>
                    <TableHead className="hidden lg:table-cell text-center">Suivi</TableHead>
                    <TableHead className="text-right w-28">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((row) => {
                    const startDate = row.start_ts?.slice(0, 10) ?? null
                    const endDate = row.end_ts?.slice(0, 10) ?? null
                    const isRefreshing = refreshingSymbol === row.symbol
                    return (
                      <TableRow key={row.symbol}>
                        <TableCell className="font-mono font-semibold">
                          {row.symbol}
                        </TableCell>

                        <TableCell className="hidden sm:table-cell text-sm text-muted-foreground">
                          {row.display_name ?? "—"}
                        </TableCell>

                        {/* Début — always visible, full canonical range from market_data_store */}
                        <TableCell className="text-xs text-muted-foreground">
                          {startDate ?? "—"}
                        </TableCell>

                        {/* Fin — always visible, full canonical range from market_data_store */}
                        <TableCell className="text-xs text-muted-foreground">
                          {endDate ?? "—"}
                        </TableCell>

                        <TableCell className="hidden md:table-cell text-right text-xs text-muted-foreground">
                          {row.row_count?.toLocaleString() ?? "—"}
                        </TableCell>

                        <TableCell className="hidden md:table-cell">
                          {row.source_provider ? (
                            <Badge variant="outline" className="text-[10px] gap-0.5">
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
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>

                        <TableCell>
                          {endDate ? (
                            <FreshnessBadge dataAsOf={endDate} />
                          ) : (
                            <Badge
                              variant="outline"
                              className="text-[10px] text-muted-foreground"
                            >
                              Non ingéré
                            </Badge>
                          )}
                        </TableCell>

                        {/* Bourse de Casablanca link */}
                        <TableCell className="hidden lg:table-cell">
                          {row.bourse_url ? (
                            <a
                              href={row.bourse_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                            >
                              <ExternalLink className="h-3 w-3" />
                              Bourse
                            </a>
                          ) : (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </TableCell>

                        {/* Tracked status */}
                        <TableCell className="hidden lg:table-cell text-center">
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
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0"
                                  onClick={() => setSelectedSymbol(row.symbol)}
                                >
                                  <Eye className="h-3.5 w-3.5" />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>Détails &amp; modifier</TooltipContent>
                            </Tooltip>

                            <Tooltip>
                              <TooltipTrigger asChild>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 w-7 p-0 text-green-600 hover:text-green-700 hover:bg-green-50"
                                  onClick={() => setUploadOpen(true)}
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
                                  className="h-7 w-7 p-0 text-blue-600 hover:text-blue-700 hover:bg-blue-50"
                                  disabled={isRefreshing}
                                  onClick={() => handleBourseRefresh(row.symbol)}
                                >
                                  <RefreshCw
                                    className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`}
                                  />
                                </Button>
                              </TooltipTrigger>
                              <TooltipContent>
                                Mettre à jour via Bourse de Casablanca
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

      {/* Detail / edit panel — passes the catalog row; panel reads symbol for OHLCV preview */}
      <StockDetailPanel
        row={selectedRow}
        open={selectedSymbol !== null}
        onClose={() => setSelectedSymbol(null)}
        onSaved={mutateAll}
      />

      {/* Excel upload dialog */}
      <ExcelUploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={() => {
          // Delay to let the ingest worker complete before refreshing
          setTimeout(() => mutateCatalog(), 4000)
        }}
      />
    </div>
  )
}
