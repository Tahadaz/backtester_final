import type { ReactNode } from "react"
import { Eyebrow } from "@/components/ui/eyebrow"
import { cn } from "@/lib/utils"

interface KpiTileProps {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: "default" | "positive" | "negative"
}

export function KpiTile({ label, value, sub, tone = "default" }: KpiTileProps) {
  return (
    <div className="rounded-md border border-border bg-bg2 px-3 py-2.5">
      <Eyebrow className="text-[10px]">{label}</Eyebrow>
      <div
        className={cn(
          "dashboard-mono mt-1 text-[18px] font-semibold tracking-tight",
          tone === "positive" && "dashboard-text-positive",
          tone === "negative" && "dashboard-text-negative",
        )}
      >
        {value}
      </div>
      {sub ? <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p> : null}
    </div>
  )
}
