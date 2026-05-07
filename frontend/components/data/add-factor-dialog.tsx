"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Loader2 } from "lucide-react"

import { addMacroFactor, ApiError } from "@/lib/api"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

export function AddFactorDialog({
  open,
  onClose,
  onAdded,
}: {
  open: boolean
  onClose: () => void
  onAdded: () => void
}) {
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [canonicalId, setCanonicalId] = useState("")
  const [yahooTicker, setYahooTicker] = useState("")
  const [displayName, setDisplayName] = useState("")
  const [assetType, setAssetType] = useState<string>("equity")
  const [marketRegion, setMarketRegion] = useState<string>("us")
  const [notes, setNotes] = useState("")

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!canonicalId.trim() || !yahooTicker.trim() || !displayName.trim()) {
      toast.error("Veuillez remplir tous les champs obligatoires")
      return
    }

    setIsSubmitting(true)
    try {
      await addMacroFactor({
        canonical_id: canonicalId.trim().toUpperCase(),
        yahoo_ticker: yahooTicker.trim(),
        display_name: displayName.trim(),
        asset_type: assetType,
        market_region: assetType === "equity" ? marketRegion : null,
        notes: notes.trim() || null,
      })
      toast.success("Facteur ajouté avec succès. Synchronisation en cours...")
      onAdded()
      setCanonicalId("")
      setYahooTicker("")
      setDisplayName("")
      setNotes("")
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        toast.error(`Erreur: ${err.message}`)
      } else {
        toast.error("Une erreur inattendue s'est produite")
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Ajouter un facteur macro</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="canonicalId">ID Canonical <span className="text-red-500">*</span></Label>
              <Input
                id="canonicalId"
                placeholder="ex: DAX"
                value={canonicalId}
                onChange={(e) => setCanonicalId(e.target.value)}
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="yahooTicker">Ticker Yahoo <span className="text-red-500">*</span></Label>
              <Input
                id="yahooTicker"
                placeholder="ex: ^GDAXI"
                value={yahooTicker}
                onChange={(e) => setYahooTicker(e.target.value)}
              />
            </div>
          </div>
          
          <div className="space-y-1.5">
            <Label htmlFor="displayName">Nom d'affichage <span className="text-red-500">*</span></Label>
            <Input
              id="displayName"
              placeholder="ex: DAX Performance-Index"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>Catégorie</Label>
              <Select value={assetType} onValueChange={setAssetType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="equity">Actions</SelectItem>
                  <SelectItem value="commodity">Matières premières</SelectItem>
                  <SelectItem value="forex">Devises</SelectItem>
                  <SelectItem value="bond">Obligations</SelectItem>
                  <SelectItem value="crypto">Crypto</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {assetType === "equity" && (
              <div className="space-y-1.5">
                <Label>Région (Actions)</Label>
                <Select value={marketRegion} onValueChange={setMarketRegion}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="us">États-Unis (US)</SelectItem>
                    <SelectItem value="european">Europe</SelectItem>
                    <SelectItem value="asian">Asie</SelectItem>
                    <SelectItem value="masi">Maroc (MASI)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="notes">Notes (Optionnel)</Label>
            <Textarea
              id="notes"
              placeholder="Informations supplémentaires..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="resize-none h-20"
            />
          </div>

          <DialogFooter className="pt-4">
            <Button type="button" variant="ghost" onClick={onClose} disabled={isSubmitting}>
              Annuler
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Ajout...
                </>
              ) : (
                "Ajouter le facteur"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
