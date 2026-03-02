"use client"

import { useState } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PlusCircle, RefreshCw, Activity, CheckCircle2, XCircle, Clock, Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"
import { useRuns } from "@/hooks/use-api"
import { StatusBadge } from "@/components/status-badge"
import { formatDateTime, relativeTime } from "@/lib/format"
import { deleteRun, type Run } from "@/lib/api"

function StatsCards({ runs }: { runs: Run[] }) {
  const total = runs.length
  const succeeded = runs.filter((r) => r.status === "succeeded").length
  const failed = runs.filter((r) => r.status === "failed").length
  const active = runs.filter(
    (r) => r.status === "running" || r.status === "queued"
  ).length

  const stats = [
    {
      label: "Total Runs",
      value: total,
      icon: Activity,
      accent: "text-primary",
    },
    {
      label: "Succeeded",
      value: succeeded,
      icon: CheckCircle2,
      accent: "text-[oklch(0.45_0.15_165)]",
    },
    {
      label: "Failed",
      value: failed,
      icon: XCircle,
      accent: "text-destructive",
    },
    {
      label: "Active",
      value: active,
      icon: Clock,
      accent: "text-[oklch(0.45_0.12_80)]",
    },
  ]

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {stats.map((s) => (
        <Card key={s.label}>
          <CardContent className="flex items-center gap-3 p-4">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-secondary">
              <s.icon className={`h-5 w-5 ${s.accent}`} />
            </div>
            <div>
              <p className="text-2xl font-bold text-foreground">{s.value}</p>
              <p className="text-xs text-muted-foreground">{s.label}</p>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}

function RunsTable({
  runs,
  deletingRunId,
  onDelete,
}: {
  runs: Run[]
  deletingRunId: string | null
  onDelete: (run: Run) => void
}) {
  if (!runs.length) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center">
        <Activity className="mb-4 h-12 w-12 text-muted-foreground/40" />
        <h3 className="text-lg font-semibold text-foreground">No runs yet</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Create your first backtest run to get started
        </p>
        <Button asChild className="mt-4" size="sm">
          <Link href="/new-run">
            <PlusCircle className="mr-1.5 h-3.5 w-3.5" />
            Create Run
          </Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Run ID
            </th>
            <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Type
            </th>
            <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Status
            </th>
            <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Created
            </th>
            <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Started
            </th>
            <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Finished
            </th>
            <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const isDeleting = deletingRunId === run.run_id
            const canDelete =
              run.status !== "queued" &&
              run.status !== "running" &&
              run.status !== "cancel_requested"

            return (
              <tr
                key={run.run_id}
                className="border-b border-border/50 transition-colors hover:bg-secondary/50"
              >
                <td className="px-3 py-3">
                  <Link
                    href={`/runs/${run.run_id}`}
                    className="font-mono text-xs font-semibold text-primary underline-offset-2 hover:underline"
                  >
                    {run.run_id.slice(0, 8)}...
                  </Link>
                </td>
                <td className="px-3 py-3">
                  <span className="inline-flex items-center rounded-md bg-secondary px-2 py-0.5 text-xs font-semibold text-secondary-foreground">
                    {run.run_type}
                  </span>
                </td>
                <td className="px-3 py-3">
                  <StatusBadge status={run.status} />
                </td>
                <td className="px-3 py-3 text-xs text-muted-foreground">
                  <span title={formatDateTime(run.created_at)}>
                    {relativeTime(run.created_at)}
                  </span>
                </td>
                <td className="px-3 py-3 text-xs text-muted-foreground">
                  {formatDateTime(run.started_at)}
                </td>
                <td className="px-3 py-3 text-xs text-muted-foreground">
                  {formatDateTime(run.finished_at)}
                </td>
                <td className="px-3 py-3 text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-1.5 text-destructive hover:text-destructive"
                    onClick={() => onDelete(run)}
                    disabled={isDeleting || !canDelete}
                    title={canDelete ? "Delete run" : "Cancel active run before deleting"}
                  >
                    {isDeleting ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                    Delete
                  </Button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-80 rounded-xl" />
    </div>
  )
}

export default function DashboardPage() {
  const { data: runs, error, isLoading, mutate } = useRuns({ limit: 50 })
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null)

  async function handleDeleteRun(run: Run) {
    if (run.status === "queued" || run.status === "running" || run.status === "cancel_requested") {
      toast.error("Cancel this active run before deleting it")
      return
    }

    const confirmed = window.confirm(
      `Delete run ${run.run_id.slice(0, 8)}...? This removes its saved results.`
    )
    if (!confirmed) return

    setDeletingRunId(run.run_id)
    try {
      await deleteRun(run.run_id)
      toast.success("Run deleted")
      await mutate()
    } catch (err) {
      toast.error(`Failed to delete run: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setDeletingRunId(null)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground text-balance">
            Dashboard
          </h1>
          <p className="text-sm text-muted-foreground">
            Manage and monitor your backtest runs
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => mutate()}
            className="gap-1.5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button asChild size="sm" className="gap-1.5">
            <Link href="/new-run">
              <PlusCircle className="h-3.5 w-3.5" />
              Create Run
            </Link>
          </Button>
        </div>
      </div>

      {isLoading ? (
        <DashboardSkeleton />
      ) : error ? (
        <Card>
          <CardContent className="py-12 text-center">
            <XCircle className="mx-auto mb-3 h-8 w-8 text-destructive" />
            <h3 className="font-semibold text-foreground">
              Could not connect to API
            </h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Make sure the Next.js proxy is configured (`UPSTREAM_API_BASE` or `API_URL`) and backend is running.
            </p>
            <p className="mt-2 font-mono text-xs text-muted-foreground">
              {String(error?.message || error)}
            </p>
          </CardContent>
        </Card>
      ) : (
        <>
          <StatsCards runs={runs ?? []} />
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Recent Runs</CardTitle>
            </CardHeader>
            <CardContent className="px-0 pb-0">
              <RunsTable
                runs={runs ?? []}
                deletingRunId={deletingRunId}
                onDelete={handleDeleteRun}
              />
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
