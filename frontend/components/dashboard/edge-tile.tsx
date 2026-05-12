import { Star, StarOff } from "lucide-react"
import type { EdgeMetrics } from "@/lib/api"
import { formatPercent } from "@/lib/format"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { cn } from "@/lib/utils"

export type EdgeMode = "gross" | "net"

interface EdgeTileProps {
  edge: EdgeMetrics | null | undefined
  loading?: boolean
  mode: EdgeMode
  sourceLabel: string
  onOpen?: () => void
}

function formatSigned(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}`
}

function formatObsWindow(edge: EdgeMetrics) {
  if (!edge.window_start || !edge.window_end) return `${edge.n} obs OOS`
  const start = new Date(edge.window_start)
  const end = new Date(edge.window_end)
  const months = Math.max(
    1,
    (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth()) + 1,
  )
  return `${edge.n} obs OOS - ${months} mois`
}

function actionExpectedReturn(edge: EdgeMetrics, mode: EdgeMode) {
  if (mode === "net") return edge.action_expected_return_net ?? edge.expected_return_net
  return edge.action_expected_return_gross ?? edge.expected_return_gross
}

function actionLabel(edge: EdgeMetrics) {
  if (edge.direction === "long") return "Long"
  if (edge.direction === "short") return "Short"
  return "No trade"
}

export function EdgeTile({ edge, loading = false, mode, sourceLabel, onOpen }: EdgeTileProps) {
  if (loading) {
    return <div className="h-14 animate-pulse rounded-md border border-border bg-muted/30" />
  }

  if (!edge) {
    return (
      <div className="rounded-md border border-dashed border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
        Edge en attente
      </div>
    )
  }

  if (edge.direction === "none" || edge.bucket === "hold") {
    return (
      <button
        type="button"
        onClick={onOpen}
        className="w-full rounded-md border border-border bg-muted/25 px-2.5 py-2 text-left text-[11px] text-muted-foreground"
      >
        <div className="flex items-center justify-between gap-3">
          <span className="font-medium">Hold</span>
          <span className="dashboard-mono text-[10px] uppercase tracking-[0.12em]">{sourceLabel}</span>
        </div>
      </button>
    )
  }

  const proven = mode === "net" ? edge.proven_edge_net : edge.proven_edge_gross
  const edgeRatio = mode === "net" ? edge.edge_ratio_net : edge.edge_ratio_gross
  const expectedReturn = actionExpectedReturn(edge, mode)
  const profitFactor = mode === "net" ? edge.profit_factor_net : edge.profit_factor_gross
  const insufficient = edge.n < 30

  const content = (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "w-full rounded-md border px-2.5 py-2 text-left transition hover:border-foreground/20 hover:bg-muted/20",
        proven ? "border-emerald-300 bg-emerald-50/40" : "border-border bg-card",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Edge
          </div>
          <div className="dashboard-mono mt-0.5 text-base font-semibold tracking-tight">{formatSigned(edgeRatio)}</div>
        </div>
        <div className="flex items-center gap-1.5">
          {proven ? <Star className="h-3.5 w-3.5 fill-current text-emerald-600" /> : <StarOff className="h-3.5 w-3.5 text-muted-foreground" />}
          <span className="dashboard-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">{sourceLabel}</span>
        </div>
      </div>
      <div className="dashboard-mono mt-1.5 text-[11px] text-muted-foreground">
        {actionLabel(edge)} {formatPercent(expectedReturn)} - {formatPercent(edge.hit_rate)} - hold {edge.fwd_horizon_bars ?? "--"}j - PF {formatSigned(profitFactor)} - n={edge.n}
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">{formatObsWindow(edge)}</div>
    </button>
  )

  if (!insufficient) {
    return content
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>{content}</TooltipTrigger>
      <TooltipContent>Echantillon &lt; 30 obs OOS</TooltipContent>
    </Tooltip>
  )
}
