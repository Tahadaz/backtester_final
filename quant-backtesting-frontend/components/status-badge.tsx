import { cn } from "@/lib/utils"
import type { RunStatus } from "@/lib/api"

const statusConfig: Record<
  RunStatus,
  { label: string; className: string }
> = {
  created: {
    label: "Created",
    className: "bg-muted text-muted-foreground",
  },
  queued: {
    label: "Queued",
    className: "bg-[oklch(0.90_0.08_260)] text-[oklch(0.42_0.14_260)]",
  },
  running: {
    label: "Running",
    className:
      "bg-[oklch(0.92_0.06_80)] text-[oklch(0.45_0.12_80)] animate-pulse",
  },
  cancel_requested: {
    label: "Cancel Requested",
    className: "bg-[oklch(0.93_0.03_80)] text-[oklch(0.42_0.10_80)]",
  },
  canceled: {
    label: "Canceled",
    className: "bg-[oklch(0.92_0.03_250)] text-[oklch(0.44_0.02_250)]",
  },
  succeeded: {
    label: "Succeeded",
    className: "bg-[oklch(0.92_0.06_165)] text-[oklch(0.45_0.15_165)]",
  },
  failed: {
    label: "Failed",
    className: "bg-[oklch(0.92_0.06_25)] text-[oklch(0.50_0.20_25)]",
  },
}

export function StatusBadge({ status }: { status: RunStatus }) {
  const config = statusConfig[status] ?? statusConfig.created
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-bold tracking-wide uppercase",
        config.className
      )}
    >
      {config.label}
    </span>
  )
}
