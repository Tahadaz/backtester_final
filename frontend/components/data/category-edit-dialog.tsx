"use client"

import { useState } from "react"
import { patchAssetCategory } from "@/lib/api"
import type { MarketCatalogRow } from "@/lib/api"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { toast } from "sonner"

const ASSET_TYPES = [
  { value: "equity", label: "Actions (Equity)" },
  { value: "commodity", label: "Matières premières (Commodity)" },
  { value: "forex", label: "Devises (Forex)" },
  { value: "bond", label: "Obligations (Bond)" },
] as const

const MARKET_REGIONS = [
  { value: "masi", label: "MASI (Maroc)" },
  { value: "us", label: "États-Unis (US)" },
  { value: "european", label: "Europe" },
  { value: "asian", label: "Asie" },
] as const

interface Props {
  row: MarketCatalogRow
  open: boolean
  onClose: () => void
  onSaved: (updated: MarketCatalogRow) => void
}

export function CategoryEditDialog({ row, open, onClose, onSaved }: Props) {
  const [assetType, setAssetType] = useState(row.asset_type ?? "equity")
  const [marketRegion, setMarketRegion] = useState<string | null>(row.market_region ?? null)
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    setSaving(true)
    try {
      const updated = await patchAssetCategory(row.symbol, {
        asset_type: assetType,
        market_region: assetType === "equity" ? marketRegion : null,
      })
      toast.success(`Catégorie de ${row.symbol} mise à jour`)
      onSaved(updated)
      onClose()
    } catch {
      toast.error("Impossible de mettre à jour la catégorie")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>
            Catégorie — <span className="font-mono">{row.symbol}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Type d&apos;actif</label>
            <select
              value={assetType}
              onChange={(e) => {
                setAssetType(e.target.value)
                if (e.target.value !== "equity") setMarketRegion(null)
              }}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
            >
              {ASSET_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </div>

          {assetType === "equity" && (
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Marché / Région</label>
              <select
                value={marketRegion ?? ""}
                onChange={(e) => setMarketRegion(e.target.value || null)}
                className="w-full rounded-md border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
              >
                <option value="">— Non défini —</option>
                {MARKET_REGIONS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            Annuler
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "Enregistrement..." : "Enregistrer"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
