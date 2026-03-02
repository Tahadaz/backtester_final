"use client"

import { useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchArtifactJson,
  fetchArtifactText,
  getArtifacts,
  toArtifactProxyUrl,
  type Artifact,
  type PlotlyFigure,
} from "@/lib/api"
import { BarChart3, Download, FileJson, FileText, FolderOpen } from "lucide-react"
import { PlotlyChart } from "@/components/run/plotly-chart"

type SelectedArtifact = {
  artifact: Artifact
  strategyKind: string
}

function strategyKindFromName(name: string): string {
  const [kind] = name.split(".")
  return (kind || "unknown").toLowerCase()
}

export function ArtifactsPanel({
  runId,
  symbol,
}: {
  runId: string
  symbol?: string
}) {
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [selected, setSelected] = useState<SelectedArtifact | null>(null)
  const [plotFigure, setPlotFigure] = useState<PlotlyFigure | null>(null)
  const [textPreview, setTextPreview] = useState<string | null>(null)
  const [contentLoading, setContentLoading] = useState(false)
  const [contentError, setContentError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const rows = await getArtifacts(runId, symbol ? { symbol } : undefined)
        if (!cancelled) setArtifacts(rows)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load artifacts")
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [runId, symbol])

  const entries = useMemo(
    () =>
      artifacts.map((artifact) => ({
        artifact,
        strategyKind: strategyKindFromName(artifact.name),
      })),
    [artifacts]
  )

  useEffect(() => {
    if (!selected) {
      setPlotFigure(null)
      setTextPreview(null)
      setContentError(null)
      return
    }
    const selectedArtifact = selected.artifact

    let cancelled = false
    async function loadSelected() {
      setContentLoading(true)
      setContentError(null)
      setPlotFigure(null)
      setTextPreview(null)

      try {
        if (selectedArtifact.artifact_type === "strategy_plotly_json") {
          const fig = await fetchArtifactJson(
            selectedArtifact.url,
            selectedArtifact.object_key
          )
          if (!cancelled) setPlotFigure(fig)
        } else {
          const text = await fetchArtifactText(
            selectedArtifact.url,
            selectedArtifact.object_key
          )
          if (!cancelled) setTextPreview(text.split(/\r?\n/).slice(0, 60).join("\n"))
        }
      } catch (err) {
        if (!cancelled) {
          setContentError(err instanceof Error ? err.message : "Failed to load artifact content")
        }
      } finally {
        if (!cancelled) setContentLoading(false)
      }
    }

    loadSelected()
    return () => {
      cancelled = true
    }
  }, [selected])

  if (loading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Artifacts</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 6 }).map((_, idx) => (
            <Skeleton key={idx} className="h-10 rounded-lg" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Artifacts</CardTitle>
        </CardHeader>
        <CardContent className="py-8 text-sm text-muted-foreground">
          Failed to load artifacts ({error})
        </CardContent>
      </Card>
    )
  }

  if (!entries.length) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Artifacts</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <FolderOpen className="mb-3 h-10 w-10 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">
              No artifacts available for this run.
            </p>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Artifacts ({entries.length})</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {entries.map(({ artifact, strategyKind }) => {
              const key = `${artifact.id}`
              const active = selected?.artifact.id === artifact.id
              const isPlot = artifact.artifact_type === "strategy_plotly_json"
              return (
                <div
                  key={key}
                  className={`flex items-center gap-2.5 rounded-lg border p-3 text-left transition-all ${
                    active
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border hover:border-primary/30 hover:bg-secondary/50"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() =>
                      setSelected(active ? null : { artifact, strategyKind })
                    }
                    className="flex min-w-0 flex-1 items-center gap-2.5"
                  >
                    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-secondary">
                      {isPlot ? (
                        <BarChart3 className="h-4 w-4 text-muted-foreground" />
                      ) : (
                        <FileText className="h-4 w-4 text-muted-foreground" />
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-xs font-semibold text-foreground">
                        {artifact.symbol ?? "__ALL__"} / {strategyKind}
                      </p>
                      <p className="truncate text-[10px] text-muted-foreground">
                        {artifact.artifact_type}
                      </p>
                    </div>
                  </button>
                  <a
                    href={toArtifactProxyUrl(artifact.url)}
                    download={artifact.name}
                    className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <Download className="h-3.5 w-3.5" />
                    <span className="sr-only">Download artifact</span>
                  </a>
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {selected && (
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                {selected.artifact.symbol ?? "__ALL__"} / {selected.strategyKind}
              </CardTitle>
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {selected.artifact.artifact_type === "strategy_plotly_json" ? (
                  <FileJson className="h-3.5 w-3.5" />
                ) : (
                  <FileText className="h-3.5 w-3.5" />
                )}
                {selected.artifact.name}
              </div>
            </div>
          </CardHeader>
          <CardContent>
            {contentLoading ? (
              <Skeleton className="h-72 rounded-lg" />
            ) : contentError ? (
              <div className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
                Artifact not available ({contentError})
              </div>
            ) : plotFigure ? (
              <PlotlyChart figure={plotFigure} />
            ) : textPreview ? (
              <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-secondary/20 p-3 text-xs">
                {textPreview}
              </pre>
            ) : (
              <p className="text-sm text-muted-foreground">No preview available.</p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
