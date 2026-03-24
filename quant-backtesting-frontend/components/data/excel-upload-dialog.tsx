"use client"

import { useRef, useState } from "react"
import { useUploadFormatReference } from "@/hooks/use-api"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { AlertCircle, CheckCircle2, FileSpreadsheet, Loader2, Upload, XCircle } from "lucide-react"
import { toast } from "sonner"
import {
  uploadExcelFile,
  waitForIngestCompletion,
  type IngestStatusResponse,
  type IngestSymbolResult,
} from "@/lib/api"

type Phase = "idle" | "uploading" | "processing" | "done"

export function ExcelUploadDialog({
  open,
  onClose,
  onUploaded,
}: {
  open: boolean
  onClose: () => void
  onUploaded: () => void
}) {
  const [phase, setPhase] = useState<Phase>("idle")
  const [result, setResult] = useState<IngestStatusResponse | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const { data: uploadReference } = useUploadFormatReference()

  function handleClose() {
    if (phase === "uploading" || phase === "processing") return
    setPhase("idle")
    setResult(null)
    onClose()
  }

  async function handleUpload(file: File) {
    setPhase("uploading")
    setResult(null)
    try {
      const { dataset_id } = await uploadExcelFile(file)

      setPhase("processing")
      const response = await waitForIngestCompletion(dataset_id)
      setResult(response)
      setPhase("done")

      if (response.status === "done" && response.report) {
        const symbols = Object.entries(response.report.symbols)
        const errors = symbols.filter(([, info]) => info.status === "error")
        const successes = symbols.filter(([, info]) => info.status !== "error")

        if (errors.length === 0 && successes.length > 0) {
          toast.success(`${successes.length} symbole(s) importes avec succes`)
        } else if (errors.length > 0 && successes.length > 0) {
          toast.warning(`${successes.length} importes, ${errors.length} en erreur`)
        } else if (errors.length > 0 && successes.length === 0) {
          toast.error("Aucun symbole importe - voir les details")
        }
      } else {
        toast.info("Traitement en cours - les donnees apparaitront sous peu")
      }

      onUploaded()
    } catch (err: unknown) {
      setPhase("idle")
      toast.error(`Echec: ${err instanceof Error ? err.message : "Erreur"}`)
    }
  }

  const symbols =
    result?.status === "done" && result.report
      ? Object.entries(result.report.symbols)
      : []

  return (
    <Dialog open={open} onOpenChange={(value) => !value && handleClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-green-600" />
            Importer un fichier Excel
          </DialogTitle>
          <DialogDescription>
            Les alias de colonnes sont interchangeables pour tout titre, en nouvel import
            comme en mise a jour.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col items-center gap-4 py-4">
          {uploadReference && (
            <div className="w-full rounded-md border bg-muted/30 p-3 text-xs">
              <div className="space-y-3">
                <div>
                  <p className="font-medium">Noms de colonnes acceptes</p>
                  <div className="mt-2 space-y-1.5 text-muted-foreground">
                    {uploadReference.canonical_fields.map((field) => {
                      const aliases = Array.from(
                        new Set(
                          uploadReference.formats.flatMap((format) => format.aliases[field] ?? [])
                        )
                      )
                      return (
                        <div key={field}>
                          <span className="font-medium text-foreground">{field}:</span>{" "}
                          {aliases.join(", ")}
                        </div>
                      )
                    })}
                  </div>
                </div>

                <div>
                  <p className="font-medium">Formats numeriques acceptes</p>
                  <div className="mt-2 space-y-1 text-muted-foreground">
                    {uploadReference.formats.map((format) => (
                      <div key={format.format_id}>
                        <span className="font-medium text-foreground">{format.label}:</span>{" "}
                        {format.numeric_examples.join(", ")}
                        {format.volume_suffixes.length > 0 && (
                          <span> · suffixes volume: {format.volume_suffixes.join(", ")}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>

                <p className="text-muted-foreground">{uploadReference.validation.note}</p>
              </div>
            </div>
          )}

          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xls"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) handleUpload(file)
              if (inputRef.current) inputRef.current.value = ""
            }}
          />

          {phase === "idle" && (
            <Button
              variant="outline"
              size="lg"
              className="gap-2"
              onClick={() => inputRef.current?.click()}
            >
              <Upload className="h-4 w-4" />
              Choisir un fichier
            </Button>
          )}

          {phase === "uploading" && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Envoi du fichier...
            </div>
          )}

          {phase === "processing" && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Traitement des donnees...
            </div>
          )}

          {phase === "done" && symbols.length > 0 && (
            <div className="w-full space-y-2">
              {symbols.map(([symbol, info]) => (
                <SymbolResultRow key={symbol} symbol={symbol} info={info} />
              ))}
              <div className="flex justify-end pt-2">
                <Button variant="outline" size="sm" onClick={handleClose}>
                  Fermer
                </Button>
              </div>
            </div>
          )}

          {phase === "done" && symbols.length === 0 && (
            <div className="flex flex-col items-center gap-2">
              <AlertCircle className="h-5 w-5 text-yellow-500" />
              <p className="text-sm text-muted-foreground">
                {result?.status === "processing"
                  ? "Le traitement est toujours en cours. Les donnees apparaitront sous peu."
                  : "Aucun symbole detecte dans le fichier."}
              </p>
              <Button variant="outline" size="sm" onClick={handleClose}>
                Fermer
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function SymbolResultRow({ symbol, info }: { symbol: string; info: IngestSymbolResult }) {
  if (info.status === "error") {
    return (
      <div className="flex items-start gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm">
        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        <div>
          <span className="font-medium">{symbol}</span>
          <p className="mt-0.5 text-xs text-red-600">{info.error}</p>
        </div>
      </div>
    )
  }

  const label =
    info.status === "created"
      ? "Cree"
      : info.status === "updated"
        ? "Mis a jour"
        : "Inchange"

  return (
    <div className="flex items-center gap-2 rounded border px-3 py-2 text-sm">
      <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
      <span className="font-medium">{info.canonical_symbol || symbol}</span>
      <span className="ml-auto text-muted-foreground">
        {label}
        {info.row_count != null && ` (${info.row_count} lignes)`}
      </span>
    </div>
  )
}
