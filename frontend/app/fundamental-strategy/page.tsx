"use client"

import Link from "next/link"
import useSWR from "swr"
import { AlertTriangle, ArrowRight, CheckCircle2, Database, ShieldCheck, XCircle } from "lucide-react"
import { ValueStrategyPanel } from "@/components/dashboard-v1/value-strategy-panel"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { fetchValueStrategySnapshot, type ValueStrategySnapshotResponse } from "@/lib/api"
import { cn } from "@/lib/utils"

const ARCHITECTURE_LABELS: Record<string, string> = {
  S1_bm: "Book-to-market",
  S2_cfp: "Cash-flow-to-price",
  S4_sleeves: "Separate 50/50 sleeves",
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function pct(value: unknown, digits = 2): string {
  const number = finite(value)
  return number == null ? "Unavailable" : `${number >= 0 ? "+" : ""}${(number * 100).toFixed(digits)}%`
}

function number(value: unknown, digits = 2): string {
  const parsed = finite(value)
  return parsed == null ? "Unavailable" : parsed.toFixed(digits)
}

function integer(value: unknown): string {
  const parsed = finite(value)
  return parsed == null ? "Unavailable" : Math.round(parsed).toLocaleString("en-US")
}

function decisionLabel(value: string): string {
  if (value === "retained_candidate") return "Retained candidate"
  if (value === "insufficient_data") return "Insufficient data"
  if (value === "diagnostic_candidate") return "Diagnostic candidate"
  return "Diagnostic only"
}

function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-4 shadow-sm">
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{label}</p>
      <p className="mt-2 font-mono text-2xl font-semibold tracking-tight">{value}</p>
      {note ? <p className="mt-1 text-xs text-muted-foreground">{note}</p> : null}
    </div>
  )
}

function SectionHeading({ step, title, description }: { step: string; title: string; description: string }) {
  return (
    <div className="mb-4 flex gap-3">
      <div className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary font-mono text-xs font-bold text-primary-foreground">{step}</div>
      <div>
        <h2 className="text-xl font-semibold tracking-tight">{title}</h2>
        <p className="mt-1 max-w-4xl text-sm leading-6 text-muted-foreground">{description}</p>
      </div>
    </div>
  )
}

function LoadingState() {
  return <main className="mx-auto max-w-[1500px] px-4 py-10 text-sm text-muted-foreground">Loading the persisted strategy record…</main>
}

function ErrorState({ error }: { error: unknown }) {
  return (
    <main className="mx-auto max-w-[1500px] px-4 py-10">
      <div className="rounded-xl border border-red-300 bg-red-50 p-5 text-sm text-red-900">
        <p className="font-semibold">The fundamental strategy snapshot could not be loaded.</p>
        <p className="mt-1">{error instanceof Error ? error.message : "Unknown API error"}</p>
      </div>
    </main>
  )
}

export default function FundamentalStrategyPage() {
  const { data, error, isLoading } = useSWR<ValueStrategySnapshotResponse>(
    "value-strategy-snapshot",
    fetchValueStrategySnapshot,
    { revalidateOnFocus: false },
  )

  if (isLoading) return <LoadingState />
  if (error || !data) return <ErrorState error={error} />

  const selected = data.strategy_metrics[data.recommended_architecture] ?? {}
  const periods = finite(selected.periods) ?? data.equity_curve.length
  const firstDate = data.equity_curve.at(0)?.date ?? null
  const lastDate = data.equity_curve.at(-1)?.date ?? null
  const universe = data.universe_summary
  const capacity = data.capacity_summary
  const requested = finite(capacity.requested_notional_mad)
  const filled = finite(capacity.filled_notional_mad)
  const fillRate = requested && filled != null ? filled / requested : null
  const gates = data.production_readiness?.gates ?? []
  const passedGates = gates.filter((gate) => gate.passed).length

  return (
    <main className="mx-auto w-full max-w-[1500px] space-y-8 px-4 py-6 sm:px-6 lg:px-8">
      <header className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl">
        <div className="grid gap-6 px-6 py-7 lg:grid-cols-[1fr_auto] lg:items-end">
          <div>
            <div className="mb-3 flex flex-wrap gap-2">
              <Badge className="border-amber-400/30 bg-amber-400/10 text-amber-200 hover:bg-amber-400/10">{data.research_status}</Badge>
              <Badge className="border-white/15 bg-white/5 text-slate-200 hover:bg-white/5">{data.model_version}</Badge>
              <Badge className="border-white/15 bg-white/5 text-slate-200 hover:bg-white/5">Config {data.config_hash}</Badge>
            </div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-300">Fundamental strategy · desk review record</p>
            <h1 className="mt-2 max-w-4xl text-3xl font-semibold tracking-tight sm:text-4xl">From accounting data to an executable value portfolio</h1>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300">
              One auditable workspace for source lineage, PIT controls, factor selection, portfolio construction, capacity, costs, sequential backtest results and release blockers.
            </p>
          </div>
          <div className="flex flex-col gap-2 text-xs text-slate-300 lg:text-right">
            <span>Signal date: <strong className="text-white">{data.as_of_date ?? "Unavailable"}</strong></span>
            <span>Computed: <strong className="text-white">{data.computed_at?.slice(0, 16).replace("T", " ") ?? "Unavailable"} UTC</strong></span>
            <span>Method: <strong className="text-white">{data.methodology_version || "Unavailable"}</strong></span>
          </div>
        </div>
        <div className="border-t border-white/10 bg-red-500/10 px-6 py-3 text-sm text-red-100">
          <span className="font-semibold">Live-capital decision: NO-GO.</span> The mechanics run, but {integer(periods)} monthly observations do not validate alpha and {gates.length - passedGates} release gates remain blocked.
        </div>
      </header>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <Metric label="Observed months" value={integer(periods)} note={firstDate && lastDate ? `${firstDate} → ${lastDate}` : "No invested period"} />
        <Metric label="Net cumulative return" value={pct(selected.cumulative_return)} note="After reported costs" />
        <Metric label="Annualized Sharpe" value={number(selected.sharpe)} note="Not reliable with this sample" />
        <Metric label="Maximum drawdown" value={pct(selected.max_drawdown)} note="Observed sample only" />
        <Metric label="Latest B/M coverage" value={universe ? `${universe.eligible_bm_count}/${universe.total_names}` : "Unavailable"} note="After PIT + liquidity gates" />
        <Metric label="Notional fill rate" value={fillRate == null ? "Unavailable" : pct(fillRate)} note={`${integer(capacity.orders)} orders simulated`} />
      </section>

      <nav className="sticky top-16 z-20 flex gap-1 overflow-x-auto rounded-xl border border-border bg-background/95 p-1.5 shadow-sm backdrop-blur" aria-label="Research process">
        {[
          ["data-model", "1 · Data"], ["factor-research", "2 · Factors"], ["construction", "3 · Construction"],
          ["backtest-results", "4 · Backtest"], ["release-gates", "5 · Readiness"],
        ].map(([href, label]) => <a key={href} href={`#${href}`} className="whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium text-muted-foreground hover:bg-muted hover:text-foreground">{label}</a>)}
      </nav>

      <section id="data-model" className="scroll-mt-32 rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-6">
        <SectionHeading step="1" title="Fundamental data model and point-in-time reconstruction" description="What entered the model, how issuer-specific statements were normalized, and what the strategy knew on each historical decision date." />
        <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="overflow-hidden rounded-xl border border-border">
            <Table>
              <TableHeader><TableRow><TableHead>Layer</TableHead><TableHead>Source</TableHead><TableHead>Current evidence status</TableHead></TableRow></TableHeader>
              <TableBody>{data.data_sources.map((source) => (
                <TableRow key={source.layer}><TableCell className="font-mono text-xs">{source.layer}</TableCell><TableCell className="font-medium">{source.source}</TableCell><TableCell className="text-xs text-muted-foreground">{source.status}</TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </div>
          <div className="space-y-3">
            {data.research_pipeline.slice(0, 2).map((item) => (
              <div key={item.step} className="rounded-xl border border-border bg-muted/30 p-4">
                <p className="text-sm font-semibold">{item.step}. {item.title}</p>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.detail}</p>
                <p className="mt-2 border-l-2 border-primary pl-3 text-xs leading-5">Evidence: {item.evidence}</p>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <Metric label="Latest universe" value={universe ? integer(universe.total_names) : "Unavailable"} />
          <Metric label="B/M eligible" value={universe ? integer(universe.eligible_bm_count) : "Unavailable"} />
          <Metric label="CF/P eligible" value={universe ? integer(universe.eligible_cfp_count) : "Unavailable"} />
        </div>
      </section>

      <section id="factor-research" className="scroll-mt-32 rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-6">
        <SectionHeading step="2" title="Factor research and architecture decision" description="The factors are kept separate so the desk can see the formula, eligible population and realized evidence for each candidate. No random production variable or opaque ensemble weight is used." />
        <div className="grid gap-4 lg:grid-cols-3">
          {data.factor_research.map((factor) => {
            const metric = factor.metrics
            const insufficient = factor.decision === "insufficient_data"
            return (
              <article key={factor.factor_id} className={cn("rounded-xl border p-4", factor.factor_id === data.recommended_architecture ? "border-emerald-500/50 bg-emerald-500/5" : "border-border") }>
                <div className="flex items-start justify-between gap-3">
                  <div><p className="font-mono text-[10px] text-muted-foreground">{factor.factor_id}</p><h3 className="mt-1 font-semibold">{factor.label}</h3></div>
                  <Badge variant="outline" className={cn("text-[10px]", insufficient ? "border-amber-400 text-amber-800" : factor.factor_id === data.recommended_architecture ? "border-emerald-500 text-emerald-700" : "")}>{decisionLabel(factor.decision)}</Badge>
                </div>
                <p className="mt-4 rounded-lg bg-muted px-3 py-2 font-mono text-[11px] leading-5">{factor.formula}</p>
                <p className="mt-3 text-xs leading-5 text-muted-foreground">{factor.applicability}</p>
                <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-border pt-4 text-xs">
                  <div><dt className="text-muted-foreground">Periods</dt><dd className="mt-1 font-mono font-semibold">{integer(metric.periods)}</dd></div>
                  <div><dt className="text-muted-foreground">Latest eligible</dt><dd className="mt-1 font-mono font-semibold">{integer(factor.latest_eligible_count)}</dd></div>
                  <div><dt className="text-muted-foreground">Net return</dt><dd className="mt-1 font-mono font-semibold">{pct(metric.cumulative_return)}</dd></div>
                  <div><dt className="text-muted-foreground">Sharpe</dt><dd className="mt-1 font-mono font-semibold">{number(metric.sharpe)}</dd></div>
                  <div><dt className="text-muted-foreground">Hit rate</dt><dd className="mt-1 font-mono font-semibold">{pct(metric.hit_rate)}</dd></div>
                  <div><dt className="text-muted-foreground">Max drawdown</dt><dd className="mt-1 font-mono font-semibold">{pct(metric.max_drawdown)}</dd></div>
                </dl>
              </article>
            )
          })}
        </div>
        <div className="mt-4 flex gap-2 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p><strong>Interpretation discipline:</strong> these are sequential portfolio statistics, not proof of factor significance. The current four-month B/M sample is shown because it is real, but it is not a solid out-of-sample validation.</p>
        </div>
      </section>

      <section id="construction" className="scroll-mt-32 rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-6">
        <SectionHeading step="3" title="Portfolio construction, liquidity and cost model" description="How factor ranks become positions, how historical capacity constrains fills, and where the simulator still differs from an executable order workflow." />
        <div className="grid gap-4 lg:grid-cols-3">
          {data.research_pipeline.slice(3, 5).map((item) => (
            <div key={item.step} className="rounded-xl border border-border p-4"><p className="font-semibold">{item.title}</p><p className="mt-2 text-sm leading-6 text-muted-foreground">{item.detail}</p><p className="mt-3 text-xs leading-5">{item.evidence}</p></div>
          ))}
          <div className="rounded-xl border border-border p-4">
            <p className="font-semibold">Current configuration</p>
            <dl className="mt-3 space-y-2 text-xs">
              <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Portfolio NAV</dt><dd className="font-mono">MAD {integer(data.liquidity_settings.portfolio_nav_mad)}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Minimum order</dt><dd className="font-mono">MAD {integer(data.liquidity_settings.min_order_mad)}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Minimum ADTV</dt><dd className="font-mono">MAD {integer(data.liquidity_settings.min_adv_mad)}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Maximum participation</dt><dd className="font-mono">{pct(data.liquidity_settings.max_participation_rate, 0)}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-muted-foreground">ADTV window</dt><dd className="font-mono">{data.liquidity_settings.adv_window_days} sessions</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-muted-foreground">Transaction cost</dt><dd className="font-mono">{data.transaction_cost_bps == null ? "Unavailable" : `${data.transaction_cost_bps} bps / side`}</dd></div>
            </dl>
          </div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Metric label="Requested notional" value={`MAD ${integer(capacity.requested_notional_mad)}`} />
          <Metric label="Filled notional" value={`MAD ${integer(capacity.filled_notional_mad)}`} />
          <Metric label="Unfilled notional" value={`MAD ${integer(capacity.unfilled_notional_mad)}`} />
          <Metric label="Final simulated NAV" value={`MAD ${integer(capacity.portfolio_nav_final_mad)}`} />
        </div>
      </section>

      <section id="backtest-results" className="scroll-mt-32 space-y-4">
        <SectionHeading step="4" title="Final backtest and execution record" description="The complete persisted result is shown below: editable liquidity assumptions, net performance, benchmark overlays, every simulated fill/rejection and current holdings." />
        <ValueStrategyPanel />
      </section>

      <section id="release-gates" className="scroll-mt-32 rounded-2xl border border-border bg-card p-5 shadow-sm sm:p-6">
        <SectionHeading step="5" title="Production-readiness gates" description="Live authorization is a conjunction: one failed gate is enough to block orders. Evidence and required remediation are presented together for desk challenge." />
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <Metric label="Passed gates" value={`${passedGates}/${gates.length}`} />
          <Metric label="Blocking gates" value={integer(gates.length - passedGates)} />
          <Metric label="Live authorization" value={data.live_trading_authorized ? "AUTHORIZED" : "BLOCKED"} />
        </div>
        <div className="space-y-2">
          {gates.map((gate) => (
            <details key={gate.gate_id} className="group rounded-xl border border-border p-4" open={!gate.passed}>
              <summary className="flex cursor-pointer list-none items-center gap-3">
                {gate.passed ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : <XCircle className="h-4 w-4 text-red-600" />}
                <span className="font-mono text-xs">{gate.gate_id}</span>
                <Badge variant="outline" className="ml-auto text-[10px]">{gate.passed ? "PASSED" : "BLOCKED"}</Badge>
              </summary>
              <div className="mt-3 grid gap-3 border-t border-border pt-3 text-sm lg:grid-cols-3">
                <div><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Requirement</p><p className="mt-1 leading-6">{gate.requirement}</p></div>
                <div><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Evidence</p><p className="mt-1 leading-6">{gate.evidence}</p></div>
                <div><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">Remediation</p><p className="mt-1 leading-6">{gate.remediation}</p></div>
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="grid gap-4 rounded-2xl border border-slate-800 bg-slate-950 p-6 text-white lg:grid-cols-[1fr_auto] lg:items-center">
        <div className="flex gap-3"><ShieldCheck className="mt-1 h-5 w-5 text-emerald-300" /><div><h2 className="font-semibold">Desk conclusion</h2><p className="mt-1 max-w-4xl text-sm leading-6 text-slate-300">The app now exposes the complete research chain and a reproducible result. The correct presentation is a transparent reconstruction candidate—not an implementation-ready alpha claim—until the blocked gates are independently closed.</p></div></div>
        <Button asChild variant="secondary"><Link href="/fundamentals"><Database className="mr-2 h-4 w-4" />Inspect issuer data<ArrowRight className="ml-2 h-4 w-4" /></Link></Button>
      </section>
    </main>
  )
}
