"use client"

import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { SignalBadge } from "@/components/signal-badge"
import {
  PARAM_DEFAULTS,
  listDatasets,
  listMarketSymbols,
  technicalStudySma,
  type Dataset,
  type SmaTechnicalStudyResponse,
} from "@/lib/api"
import { formatDateTime, formatNumber } from "@/lib/format"

function normalizeSymbol(raw: string): string {
  return raw.trim().toUpperCase()
}

function normalizeSymbols(raw: string[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of raw) {
    const symbol = normalizeSymbol(item)
    if (!symbol || seen.has(symbol)) continue
    seen.add(symbol)
    out.push(symbol)
  }
  return out
}

function isPlaceholderSheetTicker(raw: string): boolean {
  const sym = normalizeSymbol(raw)
  if (!sym) return true
  if (sym === "UPLOAD" || sym === "DATASET") return true
  if (/^FEUIL(?:LE)?\d*$/.test(sym)) return true
  if (/^SHEET\d*$/.test(sym)) return true
  return false
}

function getDatasetSymbols(dataset: Dataset): string[] {
  const direct = Array.isArray(dataset.detected_symbols) ? dataset.detected_symbols : []
  const fromMeta =
    dataset.meta && typeof dataset.meta === "object" && !Array.isArray(dataset.meta)
      ? (dataset.meta as { detected_symbols?: unknown }).detected_symbols
      : undefined
  const fallback = Array.isArray(fromMeta) ? fromMeta.map((x) => String(x)) : []
  const source = direct.length > 0 ? direct : fallback
  return normalizeSymbols(source).filter((sym) => !isPlaceholderSheetTicker(sym))
}

function parseWindows(raw: string): number[] {
  const out: number[] = []
  const seen = new Set<number>()
  for (const chunk of raw.split(",")) {
    const n = Number(chunk.trim())
    if (!Number.isInteger(n) || n <= 0 || seen.has(n)) continue
    seen.add(n)
    out.push(n)
  }
  return out.sort((a, b) => a - b)
}

function signalClass(signal: string): string {
  const normalized = signal.trim().toUpperCase()
  if (normalized === "BUY") return "text-emerald-600"
  if (normalized === "SELL") return "text-red-600"
  return "text-muted-foreground"
}

export default function TechnicalStudyPage() {
  const [allSymbols, setAllSymbols] = useState<string[]>([])
  const [symbolsLoading, setSymbolsLoading] = useState(false)
  const [query, setQuery] = useState("")
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>([])
  const [strategy, setStrategy] = useState("sma_price")
  const [windowsCsv, setWindowsCsv] = useState(PARAM_DEFAULTS["strategy.sma_window"] ?? "5,10,20,50")
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<SmaTechnicalStudyResponse | null>(null)

  useEffect(() => {
    ;(async () => {
      setSymbolsLoading(true)
      try {
        const [marketRows, datasets] = await Promise.all([
          listMarketSymbols({ timeframe: "1D" }).catch(() => []),
          listDatasets().catch(() => []),
        ])
        const marketSymbols = normalizeSymbols(marketRows.map((row) => row.symbol))
        const datasetSymbols = normalizeSymbols(datasets.flatMap(getDatasetSymbols))
        setAllSymbols(normalizeSymbols([...marketSymbols, ...datasetSymbols]))
      } catch (error) {
        toast.error(`Failed to load symbols: ${error instanceof Error ? error.message : "Unknown error"}`)
      } finally {
        setSymbolsLoading(false)
      }
    })()
  }, [])

  const selectedSet = useMemo(() => new Set(selectedSymbols.map(normalizeSymbol)), [selectedSymbols])
  const filteredSymbols = useMemo(() => {
    const q = query.trim().toUpperCase()
    if (!q) return allSymbols
    return allSymbols.filter((symbol) => symbol.includes(q))
  }, [allSymbols, query])

  const windows = useMemo(() => parseWindows(windowsCsv), [windowsCsv])

  function toggleSymbol(symbol: string, checked: boolean) {
    const normalized = normalizeSymbol(symbol)
    if (!normalized) return
    if (checked) {
      setSelectedSymbols((prev) => normalizeSymbols([...prev, normalized]))
      return
    }
    setSelectedSymbols((prev) => prev.filter((item) => normalizeSymbol(item) !== normalized))
  }

  function selectFiltered() {
    setSelectedSymbols((prev) => normalizeSymbols([...prev, ...filteredSymbols]))
  }

  function clearSelection() {
    setSelectedSymbols([])
  }

  async function runStudy() {
    if (strategy !== "sma_price") {
      toast.error("Only SMA strategy is available for now.")
      return
    }
    if (!selectedSymbols.length) {
      toast.error("Select at least one stock.")
      return
    }
    if (!windows.length) {
      toast.error("Enter at least one valid SMA window.")
      return
    }

    setRunning(true)
    try {
      const payload = await technicalStudySma({
        symbols: selectedSymbols,
        windows,
        timeframe: "1D",
      })
      setResult(payload)
    } catch (error) {
      toast.error(`Technical study failed: ${error instanceof Error ? error.message : "Unknown error"}`)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">Technical Study</h1>
        <p className="text-sm text-muted-foreground">
          Analyze SMA consensus across multiple window variations and multiple stocks.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Study Configuration</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="strategy">Strategy</Label>
              <select
                id="strategy"
                value={strategy}
                onChange={(event) => setStrategy(event.target.value)}
                className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              >
                <option value="sma_price">SMA Price</option>
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="sma-windows">SMA Windows (comma-separated)</Label>
              <Input
                id="sma-windows"
                value={windowsCsv}
                onChange={(event) => setWindowsCsv(event.target.value)}
                placeholder="5,10,14,20,30,50,100,200"
              />
              <p className="text-xs text-muted-foreground">
                Parsed windows: {windows.length ? windows.join(", ") : "none"}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <Label htmlFor="symbol-search">
                Stocks ({selectedSymbols.length} selected / {allSymbols.length} available)
              </Label>
              <div className="flex gap-2">
                <Button type="button" size="sm" variant="outline" onClick={selectFiltered} disabled={!filteredSymbols.length}>
                  Select Filtered
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={clearSelection} disabled={!selectedSymbols.length}>
                  Clear
                </Button>
              </div>
            </div>
            <Input
              id="symbol-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search symbol..."
            />

            <div className="max-h-72 overflow-auto rounded-lg border border-border p-2">
              {symbolsLoading ? (
                <p className="p-2 text-sm text-muted-foreground">Loading symbols...</p>
              ) : filteredSymbols.length === 0 ? (
                <p className="p-2 text-sm text-muted-foreground">No symbols found.</p>
              ) : (
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {filteredSymbols.map((symbol) => (
                    <label
                      key={symbol}
                      className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-2 py-1.5 text-sm hover:bg-secondary/50"
                    >
                      <Checkbox
                        checked={selectedSet.has(symbol)}
                        onCheckedChange={(checked) => toggleSymbol(symbol, Boolean(checked))}
                      />
                      <span className="font-mono">{symbol}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </div>

          <Button onClick={runStudy} disabled={running || !selectedSymbols.length || !windows.length}>
            {running ? "Running..." : "Run Technical Study"}
          </Button>
        </CardContent>
      </Card>

      {result && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Results</CardTitle>
            <p className="text-xs text-muted-foreground">{result.score_basis}</p>
          </CardHeader>
          <CardContent className="space-y-4">
            {result.results.map((row) => (
              <div key={row.symbol} className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-base font-semibold text-foreground">{row.symbol}</p>
                    <p className="text-xs text-muted-foreground">
                      As of: {formatDateTime(row.as_of ?? null)} | Timeframe: {row.timeframe}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <SignalBadge value={row.consensus_value} />
                    <span className="text-sm font-semibold">{formatNumber(row.score_pct, 2)}%</span>
                  </div>
                </div>

                {row.status !== "ok" ? (
                  <p className="mt-2 text-sm text-red-600">{row.error ?? "Unknown error"}</p>
                ) : (
                  <>
                    <div className="mt-2 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                      <p>Latest close: {formatNumber(row.latest_close, 4)}</p>
                      <p>Directional windows: {row.directional_windows}</p>
                      <p>
                        Agreement: {row.agreement_count}/{row.directional_windows}
                      </p>
                      <p className={signalClass("BUY")}>BUY: {row.buy_count}</p>
                      <p className={signalClass("SELL")}>SELL: {row.sell_count}</p>
                      <p>HOLD/Skipped: {row.hold_count}</p>
                    </div>

                    <div className="mt-3 overflow-x-auto rounded-md border border-border">
                      <table className="w-full min-w-[540px] text-sm">
                        <thead className="bg-secondary/50 text-xs uppercase text-muted-foreground">
                          <tr>
                            <th className="px-2 py-2 text-left">Window</th>
                            <th className="px-2 py-2 text-left">Signal</th>
                            <th className="px-2 py-2 text-right">SMA</th>
                            <th className="px-2 py-2 text-right">Close</th>
                            <th className="px-2 py-2 text-right">Data</th>
                          </tr>
                        </thead>
                        <tbody>
                          {row.variations.map((variation) => (
                            <tr key={`${row.symbol}-${variation.window}`} className="border-t border-border/60">
                              <td className="px-2 py-2 font-mono">{variation.window}</td>
                              <td className={`px-2 py-2 font-semibold ${signalClass(variation.signal)}`}>
                                {variation.signal}
                              </td>
                              <td className="px-2 py-2 text-right">{formatNumber(variation.sma_value ?? null, 4)}</td>
                              <td className="px-2 py-2 text-right">{formatNumber(variation.close_value ?? null, 4)}</td>
                              <td className="px-2 py-2 text-right">{variation.sufficient_data ? "OK" : "N/A"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
