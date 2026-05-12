"use client"

import { useEffect, useMemo, useState, type ReactNode } from "react"
import Link from "next/link"
import { Activity, BookOpen, Download, Gauge, Layers3, Settings } from "lucide-react"
import { StockSidebar } from "@/components/strategy/stock-sidebar"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useMarketCatalog, usePersistedSignalEngineSummaries, useStockOhlcvHistory } from "@/hooks/use-api"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

export type SignalsPageView =
  | "legacy"
  | "expanded"
  | "factor_x_ta"
  | "legacy_ta_simple"
  | "expanded_ta_simple"
  | "legacy_factor_x_ta_simple"
  | "expanded_factor_x_ta_simple"
  | "legacy_ta_combo"
  | "expanded_ta_combo"
  | "legacy_factor_x_ta_combo"
  | "expanded_factor_x_ta_combo"

export type LegacySignalsPageView = Extract<
  SignalsPageView,
  "legacy" | "legacy_ta_simple" | "legacy_factor_x_ta_simple" | "legacy_ta_combo" | "legacy_factor_x_ta_combo"
>

export type ExpandedSignalsPageView = Exclude<SignalsPageView, LegacySignalsPageView>

type SignalsViewLayoutProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  variant: SignalsPageView
  onHorizonChange: (value: string) => void
  cooldownBars: number
  onCooldownBarsChange: (value: number) => void
  topbarContent?: ReactNode
  proofContent?: ReactNode
  defaultTab?: "technique" | "evidence" | "indicateurs" | "wfo" | "backtest"
  techniqueContent: ReactNode
  evidenceContent: ReactNode
  indicatorsContent: ReactNode
  wfoContent: ReactNode
  backtestContent: ReactNode
}

function displayVariant(variant: SignalsPageView): string {
  if (variant.startsWith("legacy_factor_x_ta")) return variant.endsWith("_combo") ? "Legacy FX Combo" : "Legacy FX"
  if (variant.startsWith("expanded_factor_x_ta") || variant === "factor_x_ta") {
    return variant.endsWith("_combo") ? "Expanded FX Combo" : "Expanded FX"
  }
  if (variant.startsWith("legacy") || variant === "legacy") return variant.endsWith("_combo") ? "Legacy Combo" : "Legacy TA"
  return variant.endsWith("_combo") ? "Expanded Combo" : "Expanded TA"
}

function modeChips(variant: SignalsPageView): string[] {
  const universe = variant === "legacy" || variant.startsWith("legacy_") ? "Legacy" : "Expanded"
  const source = variant === "factor_x_ta" || variant.includes("factor_x_ta") ? "Factor x TA" : "Pure TA"
  const mode = variant.endsWith("_combo") ? "Strict AND" : "Simple"
  return [universe, source, mode]
}

function signalTone(label: string | null | undefined): string {
  const value = String(label ?? "").toLowerCase()
  if (value.includes("fort") && (value.includes("achat") || value.includes("haussier"))) {
    return "tb"
  }
  if (value.includes("achat") || value.includes("haussier") || value.includes("accum")) {
    return "b"
  }
  if (value.includes("vente") || value.includes("baissier") || value.includes("distrib")) {
    return value.includes("fort") ? "tr" : "r"
  }
  return "n"
}

function SignalPill({ label }: { label: string | null | undefined }) {
  if (!label) return <span className="text-muted-foreground">--</span>
  const tone = signalTone(label)
  return (
    <span
      className={cn(
        "inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold leading-normal",
        tone === "tb" && "bg-[oklch(0.96_0.07_165_/_0.40)] text-[oklch(0.36_0.15_165)]",
        tone === "b" && "bg-[oklch(0.96_0.07_165_/_0.20)] text-[oklch(0.45_0.13_165)]",
        tone === "n" && "bg-[oklch(0.55_0.01_250_/_0.10)] text-[oklch(0.45_0.01_250)]",
        tone === "r" && "bg-[oklch(0.65_0.18_25_/_0.12)] text-[oklch(0.50_0.20_25)]",
        tone === "tr" && "bg-[oklch(0.65_0.18_25_/_0.22)] text-[oklch(0.42_0.22_25)]",
      )}
    >
      {label}
    </span>
  )
}

function compactDate(value: string | null | undefined): string {
  if (!value) return "--"
  const normalized = value.includes("T") ? value : `${value}T00:00:00`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString(undefined, {
    month: "2-digit",
    day: "2-digit",
    year: "2-digit",
  })
}

function average(values: number[]): number | null {
  if (values.length === 0) return null
  return values.reduce((sum, value) => sum + value, 0) / values.length
}

function SignalSymbolStrip({
  selectedSymbol,
  horizon,
  variant,
}: {
  selectedSymbol: string | null
  horizon: string
  variant: SignalsPageView
}) {
  const { data: catalog } = useMarketCatalog()
  const { data: history } = useStockOhlcvHistory(selectedSymbol, { timeframe: "1D" })
  const { data: summaries } = usePersistedSignalEngineSummaries(
    selectedSymbol ? [selectedSymbol] : [],
    horizon,
    variant,
  )
  const { data: wfoSummary } = useWfoSummary(selectedSymbol, horizon, variant)

  const catalogRow = useMemo(
    () => catalog?.find((row) => row.symbol === selectedSymbol) ?? null,
    [catalog, selectedSymbol],
  )
  const bars = history?.bars ?? []
  const latest = bars.at(-1)
  const previous = bars.length > 1 ? bars.at(-2) : null
  const latestClose = typeof latest?.close === "number" ? latest.close : null
  const previousClose = typeof previous?.close === "number" ? previous.close : null
  const change = latestClose != null && previousClose != null ? latestClose - previousClose : null
  const changePct =
    change != null && previousClose != null && previousClose !== 0
      ? change / previousClose
      : null
  const adv20 = average(
    bars
      .slice(-20)
      .map((bar) =>
        typeof bar.close === "number" && typeof bar.volume === "number"
          ? bar.close * bar.volume
          : null,
      )
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value)),
  )
  const signalEngine = summaries?.[0] ?? null
  const wfoGlobal = wfoSummary?.global_signal ?? null
  const market = [catalogRow?.sector, catalogRow?.market_region ?? catalogRow?.market]
    .filter(Boolean)
    .join(" / ")

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-card px-3.5 py-2.5">
      <span className="font-sans text-xl font-bold tracking-normal">
        {selectedSymbol ?? "Signaux"}
      </span>
      <span className="text-xs text-muted-foreground">
        {selectedSymbol
          ? `${catalogRow?.display_name ?? selectedSymbol}${market ? ` / ${market}` : ""}`
          : "Selectionnez un titre dans la liste"}
      </span>
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-xl font-bold">
          {formatNumber(latestClose, 2)}
        </span>
        {change != null && changePct != null ? (
          <span
            className={cn(
              "font-mono text-xs font-semibold",
              change >= 0 ? "text-[oklch(0.50_0.13_165)]" : "text-[oklch(0.52_0.20_25)]",
            )}
          >
            {change >= 0 ? "+" : ""}
            {formatNumber(change, 2)} ({changePct >= 0 ? "+" : ""}
            {(changePct * 100).toFixed(2)}%)
          </span>
        ) : null}
        <span className="font-mono text-[10px] text-muted-foreground">
          MAD / {compactDate(latest?.date ?? history?.data_as_of)}
        </span>
      </div>

      <div className="ml-auto flex flex-wrap items-center gap-x-3.5 gap-y-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">ADV20 MAD</span>
          <span className="font-mono text-[13px] font-semibold">{formatNumber(adv20, 0)}</span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Score</span>
          <span
            className={cn(
              "font-mono text-[13px] font-semibold",
              (signalEngine?.aggregate_score_pct ?? 0) >= 0
                ? "text-[oklch(0.50_0.13_165)]"
                : "text-[oklch(0.52_0.20_25)]",
            )}
          >
            {signalEngine?.aggregate_score_pct != null
              ? `${signalEngine.aggregate_score_pct >= 0 ? "+" : ""}${signalEngine.aggregate_score_pct.toFixed(0)}`
              : "--"}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Signal SE</span>
          <SignalPill label={signalEngine?.aggregate_signal_label} />
        </div>
        <div className="flex flex-col gap-0.5">
          <span className="text-[9px] font-bold uppercase tracking-[0.08em] text-muted-foreground">Signal WFO</span>
          <SignalPill label={wfoGlobal?.signal_label ?? wfoGlobal?.recommendation} />
        </div>
      </div>
    </div>
  )
}

function ActiveModeChips({ variant }: { variant: SignalsPageView }) {
  return (
    <span className="hidden min-w-0 flex-wrap items-center gap-1.5 xl:flex">
      <span className="text-[11px] text-muted-foreground">Mode actif:</span>
      {modeChips(variant).map((chip) => (
        <span
          key={chip}
          className="inline-flex h-[22px] items-center rounded-full border border-[oklch(0.80_0.06_260)] bg-[oklch(0.94_0.04_260_/_0.4)] px-2 text-[11px] font-semibold text-[oklch(0.30_0.14_260)]"
        >
          {chip}
        </span>
      ))}
    </span>
  )
}

export function SignalsViewLayout({
  selectedSymbol,
  onSelectSymbol,
  horizon,
  variant,
  onHorizonChange,
  cooldownBars,
  onCooldownBarsChange,
  topbarContent,
  proofContent,
  defaultTab,
  techniqueContent,
  evidenceContent,
  indicatorsContent,
  wfoContent,
  backtestContent,
}: SignalsViewLayoutProps) {
  const [activeTab, setActiveTab] = useState(defaultTab ?? "technique")

  useEffect(() => {
    setActiveTab(defaultTab ?? "technique")
  }, [defaultTab, selectedSymbol])

  return (
    <div className="flex h-full overflow-hidden bg-background">
      <StockSidebar
        selectedSymbol={selectedSymbol}
        onSelect={onSelectSymbol}
        horizon={horizon}
        onHorizonChange={onHorizonChange}
        variant={variant}
        cooldownBars={cooldownBars}
        className="w-[240px] shrink-0"
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <div className="flex shrink-0 items-center gap-2.5 border-b border-line bg-bg2 px-3.5 py-2">
          {topbarContent}
          <Badge variant="outline" className="h-[22px] rounded px-1.5 text-[10px] text-muted-foreground">
            {displayVariant(variant)}
          </Badge>
          <ActiveModeChips variant={variant} />
          <span className="ml-auto flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Cooldown:</span>
            <input
              type="number"
              min={0}
              step={1}
              value={cooldownBars}
              onChange={(event) =>
                onCooldownBarsChange(Math.max(0, Number(event.target.value) || 0))
              }
              className="h-[26px] w-12 rounded-md border border-line bg-card px-1.5 text-xs font-mono outline-none"
            />
            <span className="text-xs text-muted-foreground">bars</span>
            <Button type="button" variant="outline" size="sm" className="h-[26px] gap-1.5 px-2 text-xs">
              <Download className="h-3.5 w-3.5" />
              Export
            </Button>
            <Button asChild variant="ghost" size="sm" className="h-[26px] gap-1.5 px-2 text-xs text-muted-foreground">
              <Link href="/glossary#signals">
                <BookOpen className="h-3.5 w-3.5" />
                Glossaire
              </Link>
            </Button>
          </span>
        </div>

        <SignalSymbolStrip selectedSymbol={selectedSymbol} horizon={horizon} variant={variant} />

        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as typeof activeTab)} className="flex min-h-0 flex-1 flex-col gap-0">
          <TabsList className="h-9 w-full justify-start rounded-none border-b border-line bg-bg2 p-0">
            <TabsTrigger value="technique" className="h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3.5 text-xs shadow-none data-[state=active]:border-primary data-[state=active]:bg-card data-[state=active]:shadow-none">
              <Activity className="h-3.5 w-3.5" />
              Technique
            </TabsTrigger>
            <TabsTrigger value="evidence" disabled={!selectedSymbol} className="h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3.5 text-xs shadow-none data-[state=active]:border-primary data-[state=active]:bg-card data-[state=active]:shadow-none">
              <Gauge className="h-3.5 w-3.5" />
              Signal Evidence
            </TabsTrigger>
            <TabsTrigger value="indicateurs" disabled={!selectedSymbol} className="h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3.5 text-xs shadow-none data-[state=active]:border-primary data-[state=active]:bg-card data-[state=active]:shadow-none">
              <Layers3 className="h-3.5 w-3.5" />
              Indicateurs
            </TabsTrigger>
            <TabsTrigger value="wfo" disabled={!selectedSymbol} className="h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3.5 text-xs shadow-none data-[state=active]:border-primary data-[state=active]:bg-card data-[state=active]:shadow-none">
              <Settings className="h-3.5 w-3.5" />
              WFO
            </TabsTrigger>
            <TabsTrigger value="backtest" disabled={!selectedSymbol} className="h-9 flex-none rounded-none border-0 border-b-2 border-transparent bg-transparent px-3.5 text-xs shadow-none data-[state=active]:border-primary data-[state=active]:bg-card data-[state=active]:shadow-none">
              <Gauge className="h-3.5 w-3.5" />
              Backtest MC
            </TabsTrigger>
          </TabsList>

          <TabsContent value="technique" className="min-h-0 flex-1 overflow-y-auto p-3.5 signals-scrollbar">
            <div className="space-y-3.5">
              {proofContent}
              {techniqueContent}
            </div>
          </TabsContent>

          <TabsContent value="evidence" className="min-h-0 flex-1 overflow-y-auto p-3.5 signals-scrollbar">
            {evidenceContent}
          </TabsContent>

          <TabsContent value="indicateurs" className="min-h-0 flex-1 overflow-y-auto p-3.5 signals-scrollbar">
            {indicatorsContent}
          </TabsContent>

          <TabsContent value="wfo" className="min-h-0 flex-1 overflow-y-auto p-3.5 signals-scrollbar">
            {wfoContent}
          </TabsContent>

          <TabsContent value="backtest" className="min-h-0 flex-1 overflow-y-auto p-3.5 signals-scrollbar">
            {backtestContent}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  )
}
