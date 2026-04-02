"use client"

import Link from "next/link"
import { useState } from "react"
import { Archive, ChartColumnIncreasing, Copy, Save } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { HorizonSelector } from "@/components/strategy/horizon-selector"

const STATUS_LABELS: Record<string, { label: string; variant: "default" | "secondary" | "outline" }> = {
  draft: { label: "Draft", variant: "secondary" },
  modified: { label: "Modified", variant: "outline" },
  saved: { label: "Saved", variant: "default" },
  archived: { label: "Archived", variant: "secondary" },
}

interface CoreStrategyHeaderProps {
  name: string
  onNameChange: (name: string) => void
  sidePolicy: string
  onSidePolicyChange: (policy: string) => void
  horizon: string
  onHorizonChange: (horizon: string) => void
  status: string
  focusedStock: string | null
  basket: string[]
  onFocusedStockChange: (symbol: string) => void
  onSave: () => void
  onDuplicate: () => void
  onArchive: () => void
  backtestHref?: string | null
  isSaving?: boolean
}

export function CoreStrategyHeader({
  name,
  onNameChange,
  sidePolicy,
  onSidePolicyChange,
  horizon,
  onHorizonChange,
  status,
  focusedStock,
  basket,
  onFocusedStockChange,
  onSave,
  onDuplicate,
  onArchive,
  backtestHref,
  isSaving,
}: CoreStrategyHeaderProps) {
  const [editing, setEditing] = useState(false)
  const statusInfo = STATUS_LABELS[status] ?? STATUS_LABELS.draft

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          {editing ? (
            <input
              autoFocus
              className="min-w-[200px] border-b border-primary bg-transparent text-lg font-bold tracking-tight outline-none"
              value={name}
              onChange={(e) => onNameChange(e.target.value)}
              onBlur={() => setEditing(false)}
              onKeyDown={(e) => e.key === "Enter" && setEditing(false)}
            />
          ) : (
            <h1
              className="cursor-pointer truncate text-lg font-bold tracking-tight transition-colors hover:text-primary"
              onClick={() => setEditing(true)}
              title="Click to rename"
            >
              {name || "New strategy"}
            </h1>
          )}
          <Badge variant={statusInfo.variant} className="shrink-0 text-[10px]">
            {statusInfo.label}
          </Badge>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <Button size="sm" variant="default" onClick={onSave} disabled={isSaving} className="h-7 gap-1 text-xs">
            <Save className="h-3 w-3" />
            Save
          </Button>
          {backtestHref ? (
            <Button size="sm" variant="outline" asChild className="h-7 gap-1 text-xs">
              <Link href={backtestHref}>
                <ChartColumnIncreasing className="h-3 w-3" />
                Backtest
              </Link>
            </Button>
          ) : null}
          <Button size="sm" variant="outline" onClick={onDuplicate} className="h-7 gap-1 text-xs">
            <Copy className="h-3 w-3" />
            Duplicate
          </Button>
          <Button size="sm" variant="ghost" onClick={onArchive} className="h-7 gap-1 text-xs text-muted-foreground">
            <Archive className="h-3 w-3" />
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        <ToggleGroup
          type="single"
          value={sidePolicy}
          onValueChange={(v) => v && onSidePolicyChange(v)}
          className="rounded-lg border p-0.5"
        >
          <ToggleGroupItem
            value="long_only"
            size="sm"
            className="px-3 text-xs data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >
            Long Only
          </ToggleGroupItem>
          <ToggleGroupItem
            value="long_short"
            size="sm"
            className="px-3 text-xs data-[state=on]:bg-primary data-[state=on]:text-primary-foreground"
          >
            Long / Short
          </ToggleGroupItem>
        </ToggleGroup>

        <HorizonSelector value={horizon} onChange={onHorizonChange} />

        {basket.length > 0 ? (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Stock:</span>
            <select
              value={focusedStock ?? ""}
              onChange={(e) => onFocusedStockChange(e.target.value)}
              className="rounded border border-border bg-background px-2 py-1 font-mono text-xs"
            >
              {!focusedStock ? <option value="">Select...</option> : null}
              {basket.map((symbol) => (
                <option key={symbol} value={symbol}>
                  {symbol}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
    </div>
  )
}
