"use client"

import { useState } from "react"
import type { MarketCatalogRow } from "@/lib/api"
import { updateTrackedStock } from "@/lib/api"
import { useStockOhlcvPreview } from "@/hooks/use-api"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
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
import { toast } from "sonner"

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
  const { data: preview, isLoading: previewLoading } = useStockOhlcvPreview(
    open ? symbol : null,
    { limit: 10 }
  )

  const [displayName, setDisplayName] = useState("")
  const [saving, setSaving] = useState(false)

  // Reset form when row changes
  const currentSymbol = row?.symbol
  const [lastSymbol, setLastSymbol] = useState<string | null>(null)
  if (currentSymbol && currentSymbol !== lastSymbol) {
    setLastSymbol(currentSymbol)
    setDisplayName(row?.display_name ?? "")
  }

  async function handleSave() {
    if (!symbol) return
    setSaving(true)
    try {
      await updateTrackedStock(symbol, { display_name: displayName || undefined })
      toast.success(`${symbol} mis à jour`)
      onSaved()
    } catch (err: unknown) {
      toast.error(`Échec: ${err instanceof Error ? err.message : "Erreur"}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent className="sm:max-w-lg overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            {symbol}
            {row?.is_tracked && (
              <Badge variant="outline" className="text-[10px]">
                Suivi
              </Badge>
            )}
          </SheetTitle>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Edit section */}
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="displayName" className="text-xs">Nom affiché</Label>
              <Input
                id="displayName"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={symbol ?? ""}
                className="h-8 text-sm"
              />
            </div>
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? "Enregistrement…" : "Enregistrer"}
            </Button>
          </div>

          {/* Info */}
          {row && (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">Début:</span>{" "}
                {row.start_ts?.slice(0, 10) ?? "—"}
              </div>
              <div>
                <span className="text-muted-foreground">Fin:</span>{" "}
                {row.end_ts?.slice(0, 10) ?? "—"}
              </div>
              <div>
                <span className="text-muted-foreground">Barres:</span>{" "}
                {row.row_count?.toLocaleString() ?? "—"}
              </div>
              <div>
                <span className="text-muted-foreground">Source:</span>{" "}
                {row.source_provider ?? "—"}
              </div>
            </div>
          )}

          {/* OHLCV preview */}
          <div>
            <h4 className="text-xs font-semibold mb-2">Dernières barres OHLCV</h4>
            {previewLoading ? (
              <div className="space-y-1">
                {[...Array(5)].map((_, i) => (
                  <Skeleton key={i} className="h-6 w-full" />
                ))}
              </div>
            ) : preview && preview.bars.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="text-[10px]">Date</TableHead>
                    <TableHead className="text-[10px] text-right">O</TableHead>
                    <TableHead className="text-[10px] text-right">H</TableHead>
                    <TableHead className="text-[10px] text-right">L</TableHead>
                    <TableHead className="text-[10px] text-right">C</TableHead>
                    <TableHead className="text-[10px] text-right">Vol</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.bars.slice(0, 10).map((bar) => (
                    <TableRow key={bar.date}>
                      <TableCell className="text-[10px]">{bar.date.slice(0, 10)}</TableCell>
                      <TableCell className="text-[10px] text-right">{bar.open?.toFixed(2) ?? "—"}</TableCell>
                      <TableCell className="text-[10px] text-right">{bar.high?.toFixed(2) ?? "—"}</TableCell>
                      <TableCell className="text-[10px] text-right">{bar.low?.toFixed(2) ?? "—"}</TableCell>
                      <TableCell className="text-[10px] text-right">{bar.close?.toFixed(2) ?? "—"}</TableCell>
                      <TableCell className="text-[10px] text-right">{bar.volume?.toLocaleString() ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-xs text-muted-foreground">Aucune donnée OHLCV disponible.</p>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
