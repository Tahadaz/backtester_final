"use client"

import Link from "next/link"
import { ArrowUpRight } from "lucide-react"
import { ValueStrategyPanel } from "@/components/dashboard-v1/value-strategy-panel"
import { Button } from "@/components/ui/button"

/**
 * The B/M+CF/P six-vintage strategy backtest/state, moved here from the Dashboard's
 * fundamental view per user feedback (2026-07-07) -- it belongs alongside the rest of the
 * per-symbol fundamental research, not mixed into the Dashboard's stock ranking table.
 * Reuses ValueStrategyPanel directly (same component, same data source) rather than
 * duplicating the fetch/render logic.
 */
export function StrategieValeurTab() {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        <span>The complete data → factor research → portfolio → backtest audit is available in its dedicated workspace.</span>
        <Button asChild variant="outline" size="sm" className="ml-3 h-7 shrink-0">
          <Link href="/fundamental-strategy">Open Fundamental Lab <ArrowUpRight className="ml-1 h-3 w-3" /></Link>
        </Button>
      </div>
      <ValueStrategyPanel />
    </div>
  )
}
