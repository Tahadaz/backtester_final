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

type UploadScope = "masi" | "other"
type Phase = "idle" | "running" | "done"
type FileUploadStatus = "queued" | "uploading" | "processing" | "done" | "error"

type FileUploadResult = {
  fileName: string
  status: FileUploadStatus
  result?: IngestStatusResponse
  error?: string
}

export function ExcelUploadDialog({
  open,
  onClose,
  onUploaded,
  uploadScope,
}: {
  open: boolean
  onClose: () => void
  onUploaded: () => void
  uploadScope: UploadScope
}) {
  const [phase, setPhase] = useState<Phase>("idle")
  const [fileResults, setFileResults] = useState<FileUploadResult[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const { data: uploadReference } = useUploadFormatReference()

  function handleClose() {
    if (phase === "running") return
    setPhase("idle")
    setFileResults([])
    onClose()
  }

  function updateFileResult(index: number, patch: Partial<FileUploadResult>) {
    setFileResults((prev) =>
      prev.map((item, currentIndex) => (currentIndex === index ? { ...item, ...patch } : item))
    )
  }

  async function handleUpload(files: File[]) {
    if (files.length === 0) return

    setPhase("running")
    setFileResults(files.map((file) => ({ fileName: file.name, status: "queued" })))

    let acceptedCount = 0
    let rejectedCount = 0
    let failedFiles = 0
    let timedOutFiles = 0

    for (let index = 0; index < files.length; index += 1) {
      const file = files[index]
      updateFileResult(index, { status: "uploading", error: undefined, result: undefined })

      try {
        const { dataset_id } = await uploadExcelFile(file, { uploadScope })

        updateFileResult(index, { status: "processing" })
        const response = await waitForIngestCompletion(dataset_id)
        updateFileResult(index, { status: "done", result: response })

        if (response.status === "done" && response.report) {
          const symbols = Object.entries(response.report.symbols)
          acceptedCount += symbols.filter(([, info]) => info.status !== "error").length
          rejectedCount += symbols.filter(([, info]) => info.status === "error").length
        } else {
          timedOutFiles += 1
        }
      } catch (err: unknown) {
        failedFiles += 1
        updateFileResult(index, {
          status: "error",
          error: err instanceof Error ? err.message : "Erreur",
        })
      }
    }

    setPhase("done")

    if (acceptedCount > 0 || rejectedCount > 0) {
      if (rejectedCount === 0) {
        toast.success(`${acceptedCount} symbole(s) accepte(s)`)
      } else if (acceptedCount > 0) {
        toast.warning(`${acceptedCount} accepte(s), ${rejectedCount} refuse(s)`)
      } else {
        toast.error(`${rejectedCount} symbole(s) refuse(s)`)
      }
    }
    if (timedOutFiles > 0) {
      toast.info(`${timedOutFiles} fichier(s) encore en traitement`)
    }
    if (failedFiles > 0) {
      toast.error(`${failedFiles} fichier(s) en echec d'envoi`)
    }

    onUploaded()
  }

  const completedFiles = fileResults.filter((item) => item.status === "done" || item.status === "error").length

  return (
    <Dialog open={open} onOpenChange={(value) => !value && handleClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-green-600" />
            Importer des fichiers Excel
          </DialogTitle>
          <DialogDescription>
            Les alias de colonnes sont interchangeables pour tout titre, en nouvel import
            comme en mise a jour.
            {uploadScope === "masi" &&
              " Depuis l'onglet MASI, seuls les symboles MASI sont acceptes (les autres sont refuses)."}
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
                          <span> - suffixes volume: {format.volume_suffixes.join(", ")}</span>
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
            multiple
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? [])
              if (files.length > 0) {
                void handleUpload(files)
              }
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
              Choisir des fichiers
            </Button>
          )}

          {phase === "running" && (
            <div className="flex items-center gap-2 text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Traitement des fichiers... ({completedFiles}/{fileResults.length})
            </div>
          )}

          {fileResults.length > 0 && (
            <div className="w-full space-y-3">
              {fileResults.map((entry, index) => (
                <FileResultCard key={`${entry.fileName}-${index}`} entry={entry} />
              ))}
            </div>
          )}

          {phase === "done" && (
            <div className="flex w-full justify-end pt-2">
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

function FileResultCard({ entry }: { entry: FileUploadResult }) {
  const statusText =
    entry.status === "queued"
      ? "En attente"
      : entry.status === "uploading"
      ? "Envoi..."
      : entry.status === "processing"
      ? "Traitement..."
      : entry.status === "done"
      ? "Termine"
      : "Echec"

  const symbols =
    entry.result?.status === "done" && entry.result.report
      ? Object.entries(entry.result.report.symbols)
      : []

  return (
    <div className="rounded border p-3">
      <div className="flex items-center gap-2">
        <span className="truncate text-sm font-medium">{entry.fileName}</span>
        <span className="ml-auto text-xs text-muted-foreground">{statusText}</span>
      </div>

      {entry.status === "error" && (
        <div className="mt-2 flex items-start gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
          <p className="text-xs text-red-600">{entry.error}</p>
        </div>
      )}

      {entry.status === "done" && symbols.length > 0 && (
        <div className="mt-2 space-y-2">
          {symbols.map(([symbol, info]) => (
            <SymbolResultRow key={`${entry.fileName}-${symbol}`} symbol={symbol} info={info} />
          ))}
        </div>
      )}

      {entry.status === "done" && symbols.length === 0 && (
        <div className="mt-2 flex items-center gap-2 rounded border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm">
          <AlertCircle className="h-4 w-4 text-yellow-500" />
          <p className="text-xs text-yellow-700">
            {entry.result?.status === "processing"
              ? "Le traitement est toujours en cours."
              : "Aucun symbole detecte dans ce fichier."}
          </p>
        </div>
      )}
    </div>
  )
}

function SymbolResultRow({ symbol, info }: { symbol: string; info: IngestSymbolResult }) {
  if (info.status === "error") {
    const errorMessage =
      info.error ??
      (info.error_code === "non_masi_symbol_rejected"
        ? "Symbole refuse: hors univers MASI."
        : "Symbole refuse.")
    return (
      <div className="flex items-start gap-2 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm">
        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
        <div>
          <span className="font-medium">{symbol}</span>
          <p className="mt-0.5 text-xs text-red-600">{errorMessage}</p>
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
