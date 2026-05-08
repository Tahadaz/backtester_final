"use client"

import * as React from "react"
import useSWR from "swr"
import { BarChart, Bar, CartesianGrid, ReferenceLine, XAxis, YAxis } from "recharts"
import { ExternalLink } from "lucide-react"
import { fetchEdge, type EdgeMetrics } from "@/lib/api"
import { formatPercent } from "@/lib/format"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Segmented } from "@/components/ui/segmented"
import { Eyebrow } from "@/components/ui/eyebrow"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { ChartContainer } from "@/components/ui/chart"
import { SignalBadge } from "@/components/ui/signal-badge"

type TradingHorizon = "weekly" | "monthly" | "quarterly"
type EdgeSource = "signal_engine" | "wfo"
type EdgeMode = "gross" | "net"

interface EdgePanelProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  symbol: string | null
  horizon: TradingHorizon
  initialSource: EdgeSource
  mode: EdgeMode
  onModeChange: (mode: EdgeMode) => void
  costBps: number
  initialEdge?: EdgeMetrics | null
}

function formatSigned(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  const sign = value > 0 ? "+" : ""
  return `${sign}${value.toFixed(digits)}`
}

function GateRow({ ok, label, value }: { ok: boolean; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={ok ? "text-emerald-600" : "text-red-600"}>{ok ? "OK" : "KO"}</span>
        <span className="text-sm">{label}</span>
      </div>
      <span className="dashboard-mono text-xs text-muted-foreground">{value}</span>
    </div>
  )
}

function StatBox({
  label,
  value,
  sub,
}: {
  label: string
  value: React.ReactNode
  sub?: React.ReactNode
}) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-3">
      <Eyebrow className="text-[10px]">{label}</Eyebrow>
      <div className="mt-1.5 text-xl font-semibold tracking-tight">{value}</div>
      {sub ? <p className="mt-0.5 text-[11px] text-muted-foreground">{sub}</p> : null}
    </div>
  )
}

function MetricCard({
  label,
  rows,
}: {
  label: string
  rows: Array<{ name: string; value: React.ReactNode }>
}) {
  return (
    <div className="rounded-md border border-border bg-card px-3 py-3">
      <Eyebrow className="text-[10px]">{label}</Eyebrow>
      <div className="mt-2.5 grid gap-1.5 text-sm">
        {rows.map((row) => (
          <div key={row.name} className="flex items-center justify-between gap-3">
            <span>{row.name}</span>
            <span className="dashboard-mono">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function EdgePanel({
  open,
  onOpenChange,
  symbol,
  horizon,
  initialSource,
  mode,
  onModeChange,
  costBps,
  initialEdge,
}: EdgePanelProps) {
  const sourceOptions = [
    { value: "signal_engine" as const, label: "Signal Engine" },
    { value: "wfo" as const, label: "WFO" },
  ]
  const modeOptions = [
    { value: "net" as const, label: "Couts inclus" },
    { value: "gross" as const, label: "Couts exclus" },
  ]
  const [source, setSource] = React.useState<EdgeSource>(initialSource)

  React.useEffect(() => {
    setSource(initialSource)
  }, [initialSource, symbol, horizon])

  const { data: edge, isLoading } = useSWR<EdgeMetrics | null>(
    open && symbol ? `edge-panel-${symbol}-${horizon}-${source}-${costBps}` : null,
    () => fetchEdge(symbol!, horizon, source, costBps).catch(() => null),
    { fallbackData: initialEdge ?? null, revalidateOnFocus: false },
  )

  const selected = edge
    ? {
        expectedReturn: mode === "net" ? edge.expected_return_net : edge.expected_return_gross,
        edgeRatio: mode === "net" ? edge.edge_ratio_net : edge.edge_ratio_gross,
        profitFactor: mode === "net" ? edge.profit_factor_net : edge.profit_factor_gross,
        mcPvalue: mode === "net" ? edge.mc_luck_pvalue_net : edge.mc_luck_pvalue_gross,
        proven: mode === "net" ? edge.proven_edge_net : edge.proven_edge_gross,
        mcGate: mode === "net" ? edge.gates.mc_net : edge.gates.mc_gross,
      }
    : null

  const chartData = edge
    ? [
        { metric: "ER", gross: (edge.expected_return_gross ?? 0) * 100, net: (edge.expected_return_net ?? 0) * 100 },
        { metric: "Edge", gross: edge.edge_ratio_gross ?? 0, net: edge.edge_ratio_net ?? 0 },
        { metric: "PF", gross: edge.profit_factor_gross ?? 0, net: edge.profit_factor_net ?? 0 },
      ]
    : []

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader className="border-b border-border pb-4">
          <SheetTitle className="font-semibold tracking-tight">{symbol ?? "Edge"}</SheetTitle>
          <SheetDescription>
            {horizon} - {source === "signal_engine" ? "Signal Engine" : "WFO"}
          </SheetDescription>
        </SheetHeader>

        <div className="dashboard-claude space-y-4 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <Segmented value={source} options={sourceOptions} onChange={setSource} />
            <Segmented value={mode} options={modeOptions} onChange={onModeChange} />
            {edge ? <SignalBadge label={edge.bucket.replaceAll("_", " ")} /> : null}
          </div>

          {isLoading ? (
            <div className="h-40 animate-pulse rounded-md border border-border bg-muted/30" />
          ) : !edge || !selected ? (
            <div className="rounded-md border border-dashed border-border bg-muted/20 px-4 py-6 text-sm text-muted-foreground">
              Cache Edge froid ou donnees indisponibles.
            </div>
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-2">
                <StatBox
                  label="Mode actif"
                  value={selected.proven ? "Edge prouve" : edge.n < 30 ? "Insuffisant" : "A surveiller"}
                  sub={`Cout par cote: ${edge.cost_bps_per_side} bps`}
                />
                <StatBox
                  label="Fenetre"
                  value={<span className="dashboard-mono">{edge.n} obs</span>}
                  sub={`${edge.window_start ?? "--"} -> ${edge.window_end ?? "--"}`}
                />
              </div>

              <div className="space-y-2">
                <Eyebrow className="text-[10px]">3 gates</Eyebrow>
                <GateRow ok={selected.mcGate} label="Test de chance MC" value={`p=${selected.mcPvalue?.toFixed(3) ?? "--"}`} />
                <GateRow ok={edge.gates.wilson} label="Wilson LB" value={`${edge.hit_ci_lower?.toFixed(2) ?? "--"} > 0.50`} />
                <GateRow ok={edge.gates.n} label="Echantillon" value={`${edge.n} >= 30`} />
              </div>

              <StatBox
                label="Label shuffle"
                value={
                  <span className="dashboard-mono">
                    {mode === "net"
                      ? `p=${edge.label_shuffle_pvalue_net?.toFixed(3) ?? "--"}`
                      : `p=${edge.label_shuffle_pvalue_gross?.toFixed(3) ?? "--"}`}
                  </span>
                }
                sub="Test complementaire de la valeur informative du bucket."
              />

              {edge.source === "wfo" ? (
                <StatBox
                  label="Fragilite locale"
                  value={edge.fragility_label.replaceAll("_", " ")}
                  sub={`${edge.fragility_fold_count} folds classes en cache`}
                />
              ) : null}

              <div className="grid gap-4 lg:grid-cols-2">
                <MetricCard
                  label="Brut"
                  rows={[
                    { name: "ER", value: formatPercent(edge.expected_return_gross) },
                    { name: "Edge ratio", value: formatSigned(edge.edge_ratio_gross) },
                    { name: "Profit factor", value: formatSigned(edge.profit_factor_gross) },
                    { name: "Expectance", value: formatPercent(edge.expectancy_gross?.expectancy) },
                  ]}
                />
                <MetricCard
                  label="Net"
                  rows={[
                    { name: "ER", value: formatPercent(edge.expected_return_net) },
                    { name: "Edge ratio", value: formatSigned(edge.edge_ratio_net) },
                    { name: "Profit factor", value: formatSigned(edge.profit_factor_net) },
                    { name: "Expectance", value: formatPercent(edge.expectancy_net?.expectancy) },
                  ]}
                />
              </div>

              <div className="rounded-md border border-border bg-card px-3 py-3">
                <Eyebrow className="text-[10px]">Decomposition de l expectance</Eyebrow>
                <div className="mt-3 grid gap-4 md:grid-cols-2">
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between"><span>P(gain)</span><span className="dashboard-mono">{edge.expectancy_gross?.p_win?.toFixed(2) ?? "--"}</span></div>
                    <div className="flex justify-between"><span>avg_gain</span><span className="dashboard-mono">{formatPercent(edge.expectancy_gross?.avg_win)}</span></div>
                    <div className="flex justify-between"><span>P(perte)</span><span className="dashboard-mono">{edge.expectancy_gross?.p_loss?.toFixed(2) ?? "--"}</span></div>
                    <div className="flex justify-between"><span>avg_perte</span><span className="dashboard-mono">{formatPercent(edge.expectancy_gross?.avg_loss)}</span></div>
                  </div>
                  <div className="space-y-1 text-sm">
                    <div className="flex justify-between"><span>P(gain)</span><span className="dashboard-mono">{edge.expectancy_net?.p_win?.toFixed(2) ?? "--"}</span></div>
                    <div className="flex justify-between"><span>avg_gain</span><span className="dashboard-mono">{formatPercent(edge.expectancy_net?.avg_win)}</span></div>
                    <div className="flex justify-between"><span>P(perte)</span><span className="dashboard-mono">{edge.expectancy_net?.p_loss?.toFixed(2) ?? "--"}</span></div>
                    <div className="flex justify-between"><span>avg_perte</span><span className="dashboard-mono">{formatPercent(edge.expectancy_net?.avg_loss)}</span></div>
                  </div>
                </div>
              </div>

              <div className="rounded-md border border-border bg-card px-3 py-3">
                <Eyebrow className="text-[10px]">Comparaison brut / net</Eyebrow>
                <ChartContainer
                  className="mt-3 h-64 w-full"
                  config={{
                    gross: { label: "Brut", color: "#2563eb" },
                    net: { label: "Net", color: "#16a34a" },
                  }}
                >
                  <BarChart data={chartData}>
                    <CartesianGrid vertical={false} />
                    <XAxis dataKey="metric" />
                    <YAxis />
                    <ReferenceLine y={0} stroke="#94a3b8" />
                    <Bar dataKey="gross" fill="var(--color-gross)" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="net" fill="var(--color-net)" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ChartContainer>
              </div>

              <Accordion type="single" collapsible className="rounded-md border border-border bg-card px-3">
                <AccordionItem value="method">
                  <AccordionTrigger>Methodologie / limites</AccordionTrigger>
                  <AccordionContent className="space-y-2 text-sm text-muted-foreground">
                    <p>Le badge repose sur 3 gates: MC, Wilson et taille d echantillon.</p>
                    <p>En mode net, un aller-retour retire 2 x le cout configure avant calcul d ER, d expectance, d edge ratio et de profit factor.</p>
                    <p>Pour WFO, la fragilite locale est pre-calculee par fold et sert au triage, pas au calcul des 3 gates.</p>
                    <p>Le hit rate ne depend pas des couts. Les p-values restent des diagnostics, pas une garantie de regime stable.</p>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>

              {symbol ? (
                <a
                  href={`/analytics?symbol=${encodeURIComponent(symbol)}&horizon=${encodeURIComponent(horizon)}`}
                  className="inline-flex items-center gap-2 text-sm font-medium text-primary hover:underline"
                >
                  Voir la matrice predictive complete
                  <ExternalLink className="h-4 w-4" />
                </a>
              ) : null}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
