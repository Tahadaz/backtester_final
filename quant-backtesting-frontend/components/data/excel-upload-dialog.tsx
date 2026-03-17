"use client"

import { useState, useRef } from "react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { FileSpreadsheet, Upload } from "lucide-react"
import { toast } from "sonner"

const API_BASE = "/api"

export function ExcelUploadDialog({
  open,
  onClose,
  onUploaded,
}: {
  open: boolean
  onClose: () => void
  onUploaded: () => void
}) {
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  async function handleUpload(file: File) {
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append("file", file)
      const res = await fetch(`${API_BASE}/market-data/upload-excel`, {
        method: "POST",
        body: formData,
      })
      if (!res.ok) {
        const text = await res.text().catch(() => "Erreur inconnue")
        throw new Error(text)
      }
      toast.success("Fichier Excel importé avec succès")
      onUploaded()
      onClose()
    } catch (err: unknown) {
      toast.error(`Échec: ${err instanceof Error ? err.message : "Erreur"}`)
    } finally {
      setUploading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-green-600" />
            Importer un fichier Excel
          </DialogTitle>
          <DialogDescription>
            Format attendu : fichier Excel BMCE / Bourse de Casablanca avec colonnes Date, Ouverture, Plus Haut, Plus Bas, Clôture, Volume.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col items-center gap-4 py-4">
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) handleUpload(f)
            }}
          />
          <Button
            variant="outline"
            size="lg"
            className="gap-2"
            disabled={uploading}
            onClick={() => inputRef.current?.click()}
          >
            <Upload className="h-4 w-4" />
            {uploading ? "Import en cours…" : "Choisir un fichier"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
