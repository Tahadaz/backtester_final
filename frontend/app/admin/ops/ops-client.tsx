"use client"

import { useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Database,
  Loader2,
  Play,
  RefreshCw,
  Server,
  Settings,
} from "lucide-react"
import { toast } from "sonner"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useOpsSchedulerStatus } from "@/hooks/use-api"
import { backfillOpsSignals, runOpsSchedule, type OpsQueueStatus, type OpsSchedule } from "@/lib/api"
import { cn } from "@/lib/utils"

type OpsClientProps = {
  adminEmail: string
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat().format(Number(value ?? 0))
}

function pctComplete(expected: number, stale: number): number {
  if (!expected || expected <= 0) return 0
  return Math.max(0, Math.min(100, ((expected - stale) / expected) * 100))
}

function unknownText(value: unknown): string {
  if (value === null || value === undefined) return "-"
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  return JSON.stringify(value)
}

function statusTone(status: string | null | undefined): string {
  const normalized = String(status ?? "").toLowerCase()
  if (normalized === "succeeded" || normalized === "online") {
    return "border-emerald-200 bg-emerald-50 text-emerald-700"
  }
  if (normalized === "failed" || normalized === "offline") {
    return "border-red-200 bg-red-50 text-red-700"
  }
  if (normalized === "running" || normalized === "queued" || normalized === "partial") {
    return "border-amber-200 bg-amber-50 text-amber-800"
  }
  return "border-slate-200 bg-slate-50 text-slate-700"
}

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  tone,
}: {
  title: string
  value: string
  subtitle: string
  icon: typeof Server
  tone?: string
}) {
  return (
    <Card className="rounded-lg py-4">
      <CardContent className="flex items-start justify-between gap-4 px-4">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase text-muted-foreground">{title}</p>
          <p className="mt-2 truncate text-2xl font-semibold tracking-tight">{value}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{subtitle}</p>
        </div>
        <div className={cn("rounded-md border p-2", tone ?? "bg-muted text-muted-foreground")}>
          <Icon className="h-4 w-4" />
        </div>
      </CardContent>
    </Card>
  )
}

function CoverageRow({ label, expected, stale }: { label: string; expected: number; stale: number }) {
  const pct = pctComplete(expected, stale)
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">
          {formatNumber(expected - stale)} / {formatNumber(expected)}
        </span>
      </div>
      <Progress value={pct} className="h-2" />
      <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <span>{pct.toFixed(1)}% current</span>
        <span>{formatNumber(stale)} stale tuples</span>
      </div>
    </div>
  )
}

function ScheduleTable({
  schedules,
  runningAction,
  onRun,
}: {
  schedules: OpsSchedule[]
  runningAction: string | null
  onRun: (schedule: OpsSchedule) => void
}) {
  if (!schedules.length) {
    return <p className="text-sm text-muted-foreground">No schedule records.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="min-w-[230px]">Schedule</TableHead>
          <TableHead>Queue</TableHead>
          <TableHead>Cron</TableHead>
          <TableHead className="min-w-[160px]">Next run</TableHead>
          <TableHead className="min-w-[190px]">Last dispatch</TableHead>
          <TableHead className="text-right">Action</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {schedules.map((schedule) => {
          const actionId = `run:${schedule.id}`
          const lastRun = schedule.last_run
          const isRunning = runningAction === actionId
          return (
            <TableRow key={schedule.id}>
              <TableCell className="max-w-[320px] whitespace-normal">
                <div className="font-medium">{schedule.label}</div>
                <div className="mt-1 text-xs text-muted-foreground">{schedule.description}</div>
                <div className="mt-2 font-mono text-[11px] text-muted-foreground">{schedule.id}</div>
              </TableCell>
              <TableCell>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {schedule.queue}
                </Badge>
              </TableCell>
              <TableCell className="font-mono text-xs">
                <div>{schedule.cron}</div>
                <div className="mt-1 text-muted-foreground">{schedule.timezone}</div>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">{formatDate(schedule.next_run_at)}</TableCell>
              <TableCell>
                {lastRun ? (
                  <div className="space-y-1">
                    <Badge variant="outline" className={cn("text-[10px]", statusTone(lastRun.status))}>
                      {lastRun.status}
                    </Badge>
                    <div className="text-xs text-muted-foreground">{formatDate(lastRun.started_at)}</div>
                    <div className="text-xs text-muted-foreground">
                      {formatNumber(lastRun.enqueued_jobs)} jobs via {lastRun.trigger_source ?? "-"}
                    </div>
                    {lastRun.error_message ? (
                      <div className="max-w-[260px] whitespace-normal text-xs text-red-600">{lastRun.error_message}</div>
                    ) : null}
                  </div>
                ) : (
                  <span className="text-xs text-muted-foreground">No runs yet</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <Button variant="outline" size="sm" onClick={() => onRun(schedule)} disabled={Boolean(runningAction)}>
                  {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  Run
                </Button>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

function QueueTable({ queues }: { queues: OpsQueueStatus[] }) {
  if (!queues.length) {
    return <p className="text-sm text-muted-foreground">No queue measurements.</p>
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Queue</TableHead>
          <TableHead className="text-right">Queued</TableHead>
          <TableHead className="text-right">Workers</TableHead>
          <TableHead className="text-right">Failed</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {queues.map((queue) => (
          <TableRow key={queue.name}>
            <TableCell className="font-mono text-xs">{queue.name}</TableCell>
            <TableCell className="text-right">{formatNumber(queue.queued)}</TableCell>
            <TableCell className="text-right">{formatNumber(queue.workers)}</TableCell>
            <TableCell className={cn("text-right", queue.failed > 0 ? "font-medium text-red-600" : "")}>
              {formatNumber(queue.failed)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export function OpsClient({ adminEmail }: OpsClientProps) {
  const { data, error, isLoading, mutate } = useOpsSchedulerStatus()
  const [runningAction, setRunningAction] = useState<string | null>(null)

  const totals = useMemo(() => {
    const queues = data?.queues ?? []
    return {
      queued: queues.reduce((sum, queue) => sum + queue.queued, 0),
      failed: queues.reduce((sum, queue) => sum + queue.failed, 0),
      workers: queues.reduce((sum, queue) => sum + queue.workers, 0),
    }
  }, [data?.queues])

  async function refresh() {
    await mutate()
  }

  async function runSchedule(schedule: OpsSchedule) {
    const actionId = `run:${schedule.id}`
    setRunningAction(actionId)
    try {
      const result = await runOpsSchedule(schedule.id)
      if (result.status === "failed") {
        toast.error(result.error ?? `${schedule.label} failed`)
      } else {
        toast.success(`${schedule.label}: ${formatNumber(result.enqueued_jobs)} jobs enqueued`)
      }
      await mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Scheduler dispatch failed")
    } finally {
      setRunningAction(null)
    }
  }

  async function runSignalBackfill() {
    setRunningAction("backfill")
    try {
      const result = await backfillOpsSignals()
      if (result.status === "failed") {
        toast.error(result.error ?? "Signal backfill failed")
      } else {
        toast.success(`Signal backfill: ${formatNumber(result.enqueued_jobs)} jobs enqueued`)
      }
      await mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Signal backfill failed")
    } finally {
      setRunningAction(null)
    }
  }

  const coverage = data?.signal_coverage
  const expected = coverage?.expected_tuples ?? 0
  const heartbeat = data?.scheduler.heartbeat
  const heartbeatJobs = heartbeat?.jobs ?? []
  const schedulerOnline = Boolean(data?.scheduler.online)
  const legacyEntries = data?.legacy_rq_scheduler_entries ?? []
  const wfoSchedule = data?.schedules.find((schedule) => schedule.id === "weekly_wfo_dispatch")

  return (
    <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">Scheduler audit</h1>
            <Badge variant="outline" className={cn("gap-1", statusTone(schedulerOnline ? "online" : "offline"))}>
              {schedulerOnline ? <CheckCircle2 className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
              {schedulerOnline ? "Online" : "No heartbeat"}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Observer: {adminEmail}. Last heartbeat: {formatDate(heartbeat?.heartbeat_at)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" onClick={refresh} disabled={isLoading}>
            <RefreshCw className={cn("h-4 w-4", isLoading ? "animate-spin" : "")} />
            Refresh
          </Button>
          <Button onClick={runSignalBackfill} disabled={Boolean(runningAction)}>
            {runningAction === "backfill" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            Backfill signals
          </Button>
        </div>
      </div>

      {error ? (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{error instanceof Error ? error.message : "Failed to load scheduler status."}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Scheduler"
          value={schedulerOnline ? "Online" : "Offline"}
          subtitle={heartbeat?.scheduler_id ?? "No process heartbeat"}
          icon={Server}
          tone={schedulerOnline ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}
        />
        <StatCard
          title="Signal universe"
          value={formatNumber(coverage?.symbols_total)}
          subtitle={`${formatNumber(coverage?.masi_symbols)} MASI, ${formatNumber(coverage?.non_masi_symbols)} non-MASI`}
          icon={Database}
          tone="border-sky-200 bg-sky-50 text-sky-700"
        />
        <StatCard
          title="Queue load"
          value={formatNumber(totals.queued)}
          subtitle={`${formatNumber(totals.workers)} workers, ${formatNumber(totals.failed)} failed jobs`}
          icon={Settings}
          tone={totals.failed > 0 ? "border-red-200 bg-red-50 text-red-700" : "border-indigo-200 bg-indigo-50 text-indigo-700"}
        />
        <StatCard
          title="Schedule records"
          value={formatNumber(data?.schedules.length)}
          subtitle={`${formatNumber(heartbeatJobs.length)} jobs in heartbeat`}
          icon={Clock}
          tone="border-amber-200 bg-amber-50 text-amber-800"
        />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(360px,0.6fr)]">
        <Card className="rounded-lg">
          <CardHeader>
            <CardTitle>Observed signal coverage</CardTitle>
            <CardDescription>
              {formatNumber(expected)} expected tuples across {formatNumber(coverage?.horizons.length)} horizons and{" "}
              {formatNumber(coverage?.variants.length)} variants.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            <CoverageRow label="Signal Engine" expected={expected} stale={coverage?.signal_engine_stale_tuples ?? 0} />
            <CoverageRow label="WFO" expected={expected} stale={coverage?.wfo_stale_tuples ?? 0} />
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <p className="text-sm font-medium">Non-MASI symbols</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(coverage?.non_masi_symbols_sample ?? []).slice(0, 24).map((symbol) => (
                    <Badge key={symbol} variant="outline" className="font-mono text-[10px]">
                      {symbol}
                    </Badge>
                  ))}
                  {coverage?.non_masi_symbols_sample.length ? null : (
                    <span className="text-sm text-muted-foreground">No non-MASI symbols found.</span>
                  )}
                </div>
              </div>
              <div>
                <p className="text-sm font-medium">Stale symbols sample</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(coverage?.stale_symbols_sample ?? []).slice(0, 24).map((symbol) => (
                    <Badge key={symbol} variant="outline" className="font-mono text-[10px]">
                      {symbol}
                    </Badge>
                  ))}
                  {coverage?.stale_symbols_sample.length ? null : (
                    <span className="text-sm text-muted-foreground">No stale symbols.</span>
                  )}
                </div>
              </div>
            </div>
            {(coverage?.wfo_failing_symbols_count ?? 0) > 0 ? (
              <div>
                <p className="text-sm font-medium text-red-700">
                  WFO chronically failing ({formatNumber(coverage?.wfo_failing_symbols_count)})
                </p>
                <p className="text-xs text-muted-foreground">
                  These symbols errored on their most recent WFO attempt and will keep
                  re-enqueueing weekly without fresh folds until fixed.
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(coverage?.wfo_failing_symbols_sample ?? []).map((symbol) => (
                    <Badge key={symbol} variant="outline" className="border-red-200 bg-red-50 font-mono text-[10px] text-red-700">
                      {symbol}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="rounded-lg">
          <CardHeader>
            <CardTitle>Controlled dispatch</CardTitle>
            <CardDescription>Only stale tuples are queued.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button className="w-full justify-start" onClick={runSignalBackfill} disabled={Boolean(runningAction)}>
              {runningAction === "backfill" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Backfill Signal Engine and WFO
            </Button>
            <Button
              variant="outline"
              className="w-full justify-start"
              onClick={() => wfoSchedule && runSchedule(wfoSchedule)}
              disabled={Boolean(runningAction) || !wfoSchedule}
            >
              {runningAction === "run:weekly_wfo_dispatch" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Run WFO dispatch
            </Button>
            <div className="rounded-lg border bg-muted/30 p-3 text-xs text-muted-foreground">
              <div className="font-medium text-foreground">Heartbeat jobs</div>
              <div className="mt-2 space-y-1">
                {heartbeatJobs.length ? (
                  heartbeatJobs.map((job) => (
                    <div key={job.id} className="flex items-center justify-between gap-3">
                      <span className="truncate font-mono">{job.id}</span>
                      <span className="shrink-0">{formatDate(job.next_run_at)}</span>
                    </div>
                  ))
                ) : (
                  <span>No heartbeat jobs reported.</span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-lg">
        <CardHeader>
          <CardTitle>Schedule records</CardTitle>
          <CardDescription>Recurring jobs measured from the dedicated scheduler process.</CardDescription>
        </CardHeader>
        <CardContent>
          <ScheduleTable schedules={data?.schedules ?? []} runningAction={runningAction} onRun={runSchedule} />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(360px,0.6fr)_minmax(0,1.4fr)]">
        <Card className="rounded-lg">
          <CardHeader>
            <CardTitle>Queues</CardTitle>
            <CardDescription>RQ queues used by market refresh, WFO, and Signal Engine work.</CardDescription>
          </CardHeader>
          <CardContent>
            <QueueTable queues={data?.queues ?? []} />
          </CardContent>
        </Card>

        <Card className="rounded-lg">
          <CardHeader>
            <CardTitle>Legacy rq-scheduler entries</CardTitle>
            <CardDescription>These should stay empty after the dedicated scheduler starts.</CardDescription>
          </CardHeader>
          <CardContent>
            {legacyEntries.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>ID</TableHead>
                    <TableHead>Function</TableHead>
                    <TableHead>Origin</TableHead>
                    <TableHead>Scheduled at</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {legacyEntries.map((entry, index) => (
                    <TableRow key={`${unknownText(entry.id)}-${index}`}>
                      <TableCell className="font-mono text-xs">{unknownText(entry.id)}</TableCell>
                      <TableCell className="font-mono text-xs">{unknownText(entry.func_name)}</TableCell>
                      <TableCell className="font-mono text-xs">{unknownText(entry.origin)}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{unknownText(entry.scheduled_at)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                No legacy entries observed.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
