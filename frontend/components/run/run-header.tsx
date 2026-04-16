"use client"

import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { StatusBadge } from "@/components/status-badge"
import { formatDateTime } from "@/lib/format"
import { Play, RefreshCw, Loader2, ArrowLeft, Copy, Ban, Trash2 } from "lucide-react"
import { toast } from "sonner"
import type { Run } from "@/lib/api"
import Link from "next/link"

export function RunHeader({
  run,
  onStart,
  onCancel,
  onDelete,
  onRefresh,
  starting,
  canceling,
  deleting,
}: {
  run: Run
  onStart: () => void
  onCancel: () => void
  onDelete: () => void
  onRefresh: () => void
  starting: boolean
  canceling: boolean
  deleting: boolean
}) {
  const isActive =
    run.status === "created" ||
    run.status === "queued" ||
    run.status === "running"
  const canCancel = run.status === "queued" || run.status === "running" || run.status === "cancel_requested"
  const canDelete = run.status !== "queued" && run.status !== "running" && run.status !== "cancel_requested"

  async function handleCopyRunId() {
    try {
      await navigator.clipboard.writeText(run.run_id)
      toast.success("Run ID copied")
    } catch {
      toast.error("Unable to copy Run ID")
    }
  }

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Button variant="ghost" size="icon" asChild className="h-8 w-8 shrink-0">
              <Link href="/">
                <ArrowLeft className="h-4 w-4" />
                <span className="sr-only">Back to dashboard</span>
              </Link>
            </Button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-foreground">
                  Run Detail
                </h1>
                <StatusBadge status={run.status} />
                <span className="rounded-md bg-secondary px-2 py-0.5 text-xs font-semibold text-secondary-foreground">
                  {run.run_type}
                </span>
              </div>
              <button
                type="button"
                onClick={handleCopyRunId}
                className="mt-1 flex items-center gap-1 text-xs text-muted-foreground font-mono hover:text-foreground transition-colors"
              >
                {run.run_id}
                <Copy className="h-3 w-3" />
              </button>
              {run.dataset_id && (
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Dataset: {run.dataset_id}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {run.status === "created" && (
              <Button
                size="sm"
                onClick={onStart}
                disabled={starting}
                className="gap-1.5"
              >
                {starting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Play className="h-3.5 w-3.5" />
                )}
                {starting ? "Starting..." : "Start Run"}
              </Button>
            )}
            {canCancel && (
              <Button
                variant="destructive"
                size="sm"
                onClick={onCancel}
                disabled={canceling}
                className="gap-1.5"
              >
                {canceling ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Ban className="h-3.5 w-3.5" />
                )}
                {run.status === "cancel_requested" ? "Cancel requested" : "Cancel"}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={onDelete}
              disabled={deleting || !canDelete}
              className="gap-1.5 text-destructive hover:text-destructive"
              title={canDelete ? "Delete run" : "Cancel active run before deleting"}
            >
              {deleting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              Delete
            </Button>

            <Button
              variant="outline"
              size="sm"
              onClick={onRefresh}
              className="gap-1.5"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${isActive ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-3 gap-4 rounded-lg border border-border bg-secondary/50 p-3">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Created
            </p>
            <p className="text-xs font-medium text-foreground">
              {formatDateTime(run.created_at)}
            </p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Started
            </p>
            <p className="text-xs font-medium text-foreground">
              {formatDateTime(run.started_at)}
            </p>
          </div>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Finished
            </p>
            <p className="text-xs font-medium text-foreground">
              {formatDateTime(run.finished_at)}
            </p>
          </div>
        </div>
        {(run.status === "queued" || run.status === "running" || run.status === "cancel_requested") && (
          <div className="mt-3 space-y-1">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">
                {run.progress_stage ?? "working"}
                {run.progress_message ? ` — ${run.progress_message}` : ""}
              </span>
              <span className="font-mono text-muted-foreground">
                {run.progress_pct !== null && run.progress_pct !== undefined ? `${Math.round(run.progress_pct)}%` : "--"}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-secondary">
              <div
                className="h-2 rounded-full bg-primary transition-all"
                style={{
                  width:
                    run.progress_pct !== null && run.progress_pct !== undefined
                      ? `${Math.max(0, Math.min(100, run.progress_pct))}%`
                      : "10%",
                }}
              />
            </div>
          </div>
        )}


        {run.error_message && (
          <pre className="mt-3 max-h-32 overflow-auto rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-xs text-destructive">
            {run.error_message}
          </pre>
        )}
      </CardContent>
    </Card>
  )
}
