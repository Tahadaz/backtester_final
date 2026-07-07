"use client"

import { ValueStrategyPanel } from "@/components/dashboard-v1/value-strategy-panel"

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
      <ValueStrategyPanel />
    </div>
  )
}
