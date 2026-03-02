"use client"

import { useEffect, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import { Checkbox } from "@/components/ui/checkbox"
import {
  ArrowLeft,
  ArrowRight,
  Loader2,
  Zap,
  Target,
  BarChart3,
  Settings2,
  Send,
  Search,
  Trash2,
} from "lucide-react"
import {
  STRATEGY_CATALOG,
  PARAM_DEFAULTS,
  createRun,
  computeSpecHash,
  listDatasets,
  listMarketSymbols,
  uploadDataset,
  deleteDataset,
  type Dataset,
  type MarketSymbolRow,
} from "@/lib/api"
import { cn } from "@/lib/utils"

import { STRAT_PARAM_KEYS, PORTF_KEYS } from "@/lib/strategy-registry"
type RunMode = "single" | "optimize"
type EndDatePolicy = "latest" | "fixed"

const initialParamUI: Record<string, ParamUI> = {}
for (const [k, v] of Object.entries(PARAM_DEFAULTS)) {
  initialParamUI[k] = {
    enabled: true,
    mode: "list",
    list: v,
    start: "",
    end: "",
    step: "",
  }
}

function dedupeById<T extends { id: string }>(items: T[]): T[] {
  return Array.from(new Map(items.map((x) => [x.id, x])).values())
}

function normalizeSymbol(raw: string): string {
  let symbol = String(raw ?? "").trim().toUpperCase()
  if (!symbol) return ""
  symbol = symbol.replace(/\s*\([^)]+\)\s*$/, "").trim()
  return symbol
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

function parseSymbolsInput(raw: string): string[] {
  const chunks = String(raw ?? "")
    .split(/[,\n;]+/)
    .map((x) => x.trim())
    .filter(Boolean)
  return normalizeSymbols(chunks)
}

interface WizardState {
  dataSource: "dataset" | "yfinance"
  datasetId: string | null
  mode: RunMode
  symbols: string
  strategies: string[]
  paramGrid: string
  singleParams: Record<string, string>
  initialCash: number
  costModel: {
    brokerage_bps: number
    comm_bourse_bps: number
    reg_liv_bps: number
    slippage_bps: number
    tva_rate: number
  }
  cooldownEnabled: boolean
  cooldownBars: number
  sizingEnabled: boolean
  buyPctCash: number
  sellPctShares: number
  minReturnBeforeSell: number
  // Volume gate
  volumeGateEnabled: boolean
  volumeGateKind: "min_abs" | "min_ratio_adv"
  volumeGateMinAbs: number
  volumeGateMinRatioAdv: number
  volumeGateAdvWindow: number
  // Participation cap
  participationCapEnabled: boolean
  participationRate: number
  participationAdvWindow: number
  optimizePortfolio: boolean
  optMethod: "random" | "grid"
  nTrials: number
  topK: number
  seed: number
  paramUI: Record<string, ParamUI>
  singleStartDate: string
  singleEndDate: string
  walkForwardEnabled: boolean
  walkForwardMode: "preset" | "custom"
  walkForwardObjective: "pnl" | "sharpe"
  walkForwardEndDatePolicy: EndDatePolicy
  walkForwardEndDate: string
  walkForwardStartDate: string
  walkForwardCustomTrain: number
  walkForwardCustomTest: number
  walkForwardCustomStep: number
}

const STEPS = [
  { id: 1, label: "Mode", icon: Target },
  { id: 2, label: "Data", icon: BarChart3 },
  { id: 3, label: "Strategies", icon: Zap },
  { id: 4, label: "Parameters", icon: Settings2 },
  { id: 5, label: "Portfolio", icon: Settings2 },
]

function StepIndicator({
  current,
  steps,
}: {
  current: number
  steps: typeof STEPS
}) {
  return (
    <nav className="flex items-center gap-1" aria-label="Wizard steps">
      {steps.map((step, idx) => (
        <div key={step.id} className="flex items-center gap-1">
          <div
            className={cn(
              "flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition-colors",
              current === step.id
                ? "bg-primary text-primary-foreground"
                : current > step.id
                  ? "bg-secondary text-secondary-foreground"
                  : "text-muted-foreground"
            )}
          >
            <step.icon className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">{step.label}</span>
          </div>
          {idx < steps.length - 1 && (
            <div className="h-px w-4 bg-border" />
          )}
        </div>
      ))}
    </nav>
  )
}
type ParamMode = "list" | "range"

type ParamUI = {
  enabled: boolean
  mode: ParamMode
  // list mode
  list: string
  // range mode
  start: string
  end: string
  step: string
}
function buildDomainsByKind(
  strategies: string[],
  optimizePortfolio: boolean,
  paramUI: Record<string, ParamUI>
) {
  const domainsByKind: Record<string, any[]> = {}

  const parseList = (s: string) =>
    s
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean)
      .map((x) => {
        const n = Number(x)
        return Number.isFinite(n) ? n : x
      })

  for (const kindRaw of strategies) {
    const kind = kindRaw.toLowerCase()
    const keys = [...(STRAT_PARAM_KEYS[kind] ?? [])]
    if (optimizePortfolio) keys.push(...PORTF_KEYS)

    const items: any[] = []

    for (const key of keys) {
      const ui = paramUI[key]
      if (!ui || !ui.enabled) continue

      if (ui.mode === "range") {
        const lo = Number(ui.start)
        const hi = Number(ui.end)
        const step = Number(ui.step)
        if (
          !Number.isFinite(lo) ||
          !Number.isFinite(hi) ||
          !Number.isFinite(step) ||
          step <= 0
        )
          continue

        const allInt =
          Number.isInteger(lo) && Number.isInteger(hi) && Number.isInteger(step)

        items.push({
          key,
          kind: allInt ? "int" : "float",
          domain: [lo, hi, step],
          enabled: true,
        })
      } else {
        const vals = parseList(ui.list || PARAM_DEFAULTS[key] || "")
        if (vals.length === 0) continue
        items.push({ key, kind: "choice", domain: vals, enabled: true })
      }
    }

    domainsByKind[kind] = items
  }

  return domainsByKind
}
function getSelectedParamKeys(
  strategies: string[],
  optimizePortfolio: boolean
): string[] {
  const set = new Set<string>()
  for (const s of strategies) {
    const kind = s.toLowerCase()
    for (const k of STRAT_PARAM_KEYS[kind] ?? []) set.add(k)
  }
  if (optimizePortfolio) for (const k of PORTF_KEYS) set.add(k)
  return Array.from(set)
}

function ensureParamUI(
  paramUI: Record<string, ParamUI>,
  keys: string[]
): Record<string, ParamUI> {
  const next = { ...paramUI }
  for (const k of keys) {
    if (!next[k]) {
      next[k] = {
        enabled: true,
        mode: "list",
        list: PARAM_DEFAULTS[k] ?? "",
        start: "",
        end: "",
        step: "",
      }
    }
  }
  return next
}
function visibleParamKeys(strategies: string[], optimizePortfolio: boolean) {
  const s = new Set<string>()
  for (const kindRaw of strategies) {
    const kind = kindRaw.toLowerCase()
    for (const k of STRAT_PARAM_KEYS[kind] ?? []) s.add(k)
  }
  if (optimizePortfolio) for (const k of PORTF_KEYS) s.add(k)
  return Array.from(s)
}
function ParamRow({
  k, ui, setUI, disabled,
}: {
  k: string
  ui: ParamUI
  setUI: (next: ParamUI) => void
  disabled?: boolean
}) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-sm font-semibold">{k}</p>
          <p className="text-xs text-muted-foreground">
            Default: <span className="font-mono">{PARAM_DEFAULTS[k] ?? "—"}</span>
          </p>
        </div>

        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Enable</span>
            <Switch
              checked={ui.enabled}
              onCheckedChange={(v) => setUI({ ...ui, enabled: v })}
            />
          </label>

          <select
            className="rounded-md border border-border bg-background p-2 text-xs"
            value={ui.mode}
            onChange={(e) => setUI({ ...ui, mode: e.target.value as ParamMode })}
            disabled={disabled || !ui.enabled}
          >
            <option value="list">List</option>
            <option value="range">Range</option>
          </select>
        </div>
      </div>

      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {ui.mode === "list" ? (
          <div className="sm:col-span-3">
            <Label className="text-xs text-muted-foreground">Values (comma-separated)</Label>
            <Input
              value={ui.list}
              onChange={(e) => setUI({ ...ui, list: e.target.value })}
              disabled={disabled || !ui.enabled}
              className="mt-1 font-mono text-xs"
              placeholder={PARAM_DEFAULTS[k] ?? "e.g. 0.1,0.25,0.5"}
            />
          </div>
        ) : (
          <>
            <div>
              <Label className="text-xs text-muted-foreground">Start</Label>
              <Input
                value={ui.start}
                onChange={(e) => setUI({ ...ui, start: e.target.value })}
                disabled={disabled || !ui.enabled}
                className="mt-1 font-mono text-xs"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">End</Label>
              <Input
                value={ui.end}
                onChange={(e) => setUI({ ...ui, end: e.target.value })}
                disabled={disabled || !ui.enabled}
                className="mt-1 font-mono text-xs"
              />
            </div>
            <div>
              <Label className="text-xs text-muted-foreground">Step</Label>
              <Input
                value={ui.step}
                onChange={(e) => setUI({ ...ui, step: e.target.value })}
                disabled={disabled || !ui.enabled}
                className="mt-1 font-mono text-xs"
              />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function NewRunPage() {
  const router = useRouter()
  const [step, setStep] = useState(1)
  const [submitting, setSubmitting] = useState(false)

  const [state, setState] = useState<WizardState>({
    dataSource: "dataset",
    datasetId: null,
    mode: "optimize",
    symbols: "IAM",
    strategies: [],
    paramGrid: Object.entries(PARAM_DEFAULTS)
      .map(([k, v]) => `${k}: ${v}`)
      .join("\n"),
    singleParams: {},
    initialCash: 100000,
    costModel: {
      brokerage_bps: 0.2,
      comm_bourse_bps: 0.1,
      reg_liv_bps: 0.0,
      slippage_bps: 0.0,
      tva_rate: 0.1
    },
    cooldownEnabled: true,
    cooldownBars: 10,
    sizingEnabled: true,
    buyPctCash: 0.5,
    sellPctShares: 0.5,
    minReturnBeforeSell: 0.02,
    volumeGateEnabled: false,
    volumeGateKind: "min_ratio_adv",
    volumeGateMinAbs: 0,
    volumeGateMinRatioAdv: 0.1,
    volumeGateAdvWindow: 20,
    participationCapEnabled: false,
    participationRate: 0.05,
    participationAdvWindow: 20,
    optimizePortfolio: true,
    optMethod: "grid",
    nTrials: 300,
    topK: 30,
    seed: 42,
    paramUI: initialParamUI,
    singleStartDate: "",
    singleEndDate: "",
    walkForwardEnabled: true,
    walkForwardMode: "preset",
    walkForwardObjective: "pnl",
    walkForwardEndDatePolicy: "latest",
    walkForwardEndDate: "",
    walkForwardStartDate: "",
    walkForwardCustomTrain: 252,
    walkForwardCustomTest: 63,
    walkForwardCustomStep: 21,
  })

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [marketSymbols, setMarketSymbols] = useState<MarketSymbolRow[]>([])
  const [tickerSearch, setTickerSearch] = useState("")
  const selectedSymbols = useMemo(() => parseSymbolsInput(state.symbols), [state.symbols])

  // All available tickers: union of market-data store + all dataset symbols
  const allAvailableSymbols = useMemo(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const m of marketSymbols) {
      const s = normalizeSymbol(m.symbol)
      if (s && !seen.has(s)) { seen.add(s); out.push(s) }
    }
    for (const ds of datasets) {
      for (const sym of getDatasetSymbols(ds)) {
        const s = normalizeSymbol(sym)
        if (s && !seen.has(s)) { seen.add(s); out.push(s) }
      }
    }
    return out.sort()
  }, [marketSymbols, datasets])

  useEffect(() => {
    const keys = getSelectedParamKeys(state.strategies, state.optimizePortfolio)
    setState((prev) => ({
      ...prev,
      paramUI: ensureParamUI(prev.paramUI, keys),
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.strategies.join("|"), state.optimizePortfolio])

  useEffect(() => {
    ;(async () => {
      setDatasetsLoading(true)
      try {
        const [d, mkt] = await Promise.allSettled([listDatasets(), listMarketSymbols()])
        if (d.status === "fulfilled") {
          const loaded = dedupeById(d.value)
          setDatasets(loaded)
          // Auto-select: use first dataset as primary, combine symbols from all
          if (loaded.length > 0) {
            const primaryId = loaded[0].id
            const allSymbols = normalizeSymbols(
              loaded.flatMap((ds) => getDatasetSymbols(ds))
            )
            setState((prev) => ({
              ...prev,
              datasetId: prev.datasetId ?? primaryId,
              symbols: prev.symbols === "IAM" && allSymbols.length > 0
                ? allSymbols.join(",")
                : prev.symbols,
            }))
          }
        }
        if (mkt.status === "fulfilled") setMarketSymbols(mkt.value)
      } catch {
        // not fatal
      } finally {
        setDatasetsLoading(false)
      }
    })()
  }, [])

  async function handleUploadDataset() {
    if (!uploadFile) return
    setUploading(true)
    try {
      const out = await uploadDataset(uploadFile)
      toast.success(`Uploaded: ${out.filename}`)
      update("datasetId", out.dataset_id)


      const detected = out.meta?.detected_symbols as string[] | undefined
      const normalizedDetected = normalizeSymbols(detected ?? []).filter(
        (sym) => !isPlaceholderSheetTicker(sym)
      )
      if (normalizedDetected.length) {
        update("symbols", normalizedDetected.join(","))
        toast.message(`Detected symbols: ${normalizedDetected.join(", ")}`)
      }


      // refresh list
      const d = await listDatasets()
      setDatasets(dedupeById(d))
    } catch (err) {
      toast.error(`Upload failed: ${err instanceof Error ? err.message : "Unknown error"}`)
    } finally {
      setUploading(false)
    }
  }


  async function handleDeleteDataset(datasetId: string) {
    try {
      await deleteDataset(datasetId)
      toast.success("Dataset deleted")
      const updated = await listDatasets()
      setDatasets(dedupeById(updated))
      if (state.datasetId === datasetId) {
        update("datasetId", updated[0]?.id ?? null)
      }
    } catch (err) {
      toast.error(`Delete failed: ${err instanceof Error ? err.message : "Unknown error"}`)
    }
  }

  function update<K extends keyof WizardState>(
    key: K,
    value: WizardState[K]
  ) {
    setState((prev) => ({ ...prev, [key]: value }))
  }

  function toggleStrategy(id: string) {
    setState((prev) => ({
      ...prev,
      strategies: prev.strategies.includes(id)
        ? prev.strategies.filter((s) => s !== id)
        : [...prev.strategies, id],
    }))
  }

  function toggleDetectedSymbol(symbol: string) {
    setState((prev) => {
      const current = parseSymbolsInput(prev.symbols)
      const next = current.includes(symbol)
        ? current.filter((s) => s !== symbol)
        : [...current, symbol]
      return { ...prev, symbols: next.join(",") }
    })
  }

  const canNext = () => {
    switch (step) {
      case 1:
        if (state.mode !== "optimize" || !state.walkForwardEnabled) return true
        if (state.walkForwardEndDatePolicy === "fixed" && !state.walkForwardEndDate) return false
        return true
      case 2:
        return parseSymbolsInput(state.symbols).length > 0
      case 3:
        return state.strategies.length > 0
      case 4:
        return true
      case 5:
        return state.initialCash > 0
      default:
        return false
    }
  }

  async function handleSubmit() {
    setSubmitting(true)
    try {
      const symbolsList = parseSymbolsInput(state.symbols)

      // Auto-fallback: if no dataset selected yet but one is available, pick the first
      if (state.dataSource === "dataset" && !state.datasetId && datasets.length > 0) {
        update("datasetId", datasets[0].id)
      }
      if (state.dataSource === "dataset" && !state.datasetId && datasets.length === 0) {
        toast.error("No datasets available. Upload a dataset first.")
        setSubmitting(false)
        return
      }

      const interval = "1d"

      // For now: single run uses first selected strategy as the active strategy
      const primaryKind = (state.strategies[0] ?? "buy_hold").toLowerCase()

      const domainsByKind =
        state.mode === "optimize"
          ? buildDomainsByKind(state.strategies, state.optimizePortfolio, state.paramUI)
          : {}

      const walkForwardEnabled = state.mode === "optimize" && state.walkForwardEnabled
      const walkForwardEnd = state.walkForwardEndDate || null
      const isCustomWfo = state.walkForwardMode === "custom"

      if (walkForwardEnabled) {
        if (state.walkForwardEndDatePolicy === "fixed" && !state.walkForwardEndDate) {
          toast.error("Fixed end-date policy requires a walk-forward end date.")
          setSubmitting(false)
          return
        }
        if (isCustomWfo && (state.walkForwardCustomTrain <= 0 || state.walkForwardCustomTest <= 0 || state.walkForwardCustomStep <= 0)) {
          toast.error("Train/test/step must be positive.")
          setSubmitting(false)
          return
        }
      }

      const specJson: any = {
        app_version: "next_v1",
        source_key: state.dataSource === "dataset" ? "bmce" : "yfinance",
        symbols: symbolsList,
        data: {
          source: state.dataSource === "dataset" ? "bmce" : "yfinance",
          start: state.mode === "single" ? (state.singleStartDate || null) : null,
          end: state.mode === "single" ? (state.singleEndDate || null) : null,
          interval,
          include_windows: [],
          exclude_windows: [],
          // leave bmce_paths empty; worker must fill it
          bmce_paths: null,
        },


        // SINGLE: backend expects strategy.kind/params
        strategy: {
          kind: primaryKind,
          params: {}, // we will wire exact params next
        },

        // OPTIMIZATION: backend expects optimization block
        optimization: {
          rank_metric: "pnl",
          kinds: state.mode === "optimize" ? state.strategies.map(s => s.toLowerCase()) : [],
          method: state.optMethod,
          n_trials: state.mode === "optimize" ? state.nTrials : 0,
          top_k: state.mode === "optimize" ? state.topK : 1,
          seed: state.seed,
          batch_per_symbol: state.mode === "optimize",
          domains_by_kind: domainsByKind,
          ...(walkForwardEnabled
            ? isCustomWfo
              ? {
                  walk_forward: {
                    enabled: true,
                    multi_horizon: false,
                    horizon: "medium",
                    anchored: false,
                    objective: state.walkForwardObjective,
                    train: { value: state.walkForwardCustomTrain, unit: "days" },
                    test: { value: state.walkForwardCustomTest, unit: "days" },
                    step: { value: state.walkForwardCustomStep, unit: "days" },
                    wf_train_len: state.walkForwardCustomTrain,
                    wf_test_len: state.walkForwardCustomTest,
                    wf_step: state.walkForwardCustomStep,
                    start_date: state.walkForwardStartDate || null,
                    end_date: walkForwardEnd,
                    end_date_policy: state.walkForwardEndDatePolicy,
                  },
                }
              : {
                  ui_mode: "simple_wfo_multi_horizon",
                  walk_forward: {
                    enabled: true,
                    multi_horizon: true,
                    horizons: ["short", "medium", "long"],
                    horizon: "medium",
                    anchored: false,
                    objective: state.walkForwardObjective,
                    end_date: walkForwardEnd,
                    end_date_policy: state.walkForwardEndDatePolicy,
                  },
                }
            : {
                walk_forward: {
                  enabled: false,
                },
              }),
        },

        portfolio: {
          allow_short: false,
          initial_cash: state.initialCash,

          // FIXED BASELINE VALUES (optimizer will override when included in domains)
          buy_pct_cash: state.buyPctCash,
          sell_pct_shares: state.sellPctShares,
          cooldown_bars: state.cooldownEnabled ? state.cooldownBars : 0,

          min_return_before_sell: state.minReturnBeforeSell,

          cost_model: {
            brokerage_bps: state.costModel.brokerage_bps,
            comm_bourse_bps: state.costModel.comm_bourse_bps,
            reg_liv_bps: state.costModel.reg_liv_bps,
            slippage_bps: state.costModel.slippage_bps,
            tva_rate: state.costModel.tva_rate,
          },

          volume_gate: {
            enabled: state.volumeGateEnabled,
            kind: state.volumeGateKind,
            min_volume_abs: state.volumeGateMinAbs,
            min_volume_ratio_adv: state.volumeGateMinRatioAdv,
            adv_window: state.volumeGateAdvWindow,
          },
          participation_cap: {
            enabled: state.participationCapEnabled,
            rate: state.participationRate,
            basis: "adv",
            adv_window: state.participationAdvWindow,
          },
        },
      }

      // For single backtest: populate strategy.params from singleParams
      if (state.mode === "single") {
        const stratParams: Record<string, number | string> = {}
        const primaryKeys = STRAT_PARAM_KEYS[primaryKind] ?? []
        for (const fullKey of primaryKeys) {
          const shortKey = fullKey.startsWith("strategy.") ? fullKey.slice("strategy.".length) : fullKey
          const raw = state.singleParams[fullKey]
          if (raw !== undefined && raw !== "") {
            const n = Number(raw)
            stratParams[shortKey] = Number.isFinite(n) ? n : raw
          }
        }
        specJson.strategy = { kind: primaryKind, params: stratParams }
      }



      const specHash = await computeSpecHash(specJson)
      const result = await createRun({
        spec_hash: specHash,
        spec_json: specJson,
        dataset_id: state.dataSource === "dataset" ? state.datasetId : null,
      })


      toast.success("Run created successfully")
      router.push(`/runs/${result.run_id}`)
    } catch (err) {
      toast.error(
        `Failed to create run: ${err instanceof Error ? err.message : "Unknown error"}`
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground text-balance">
            Create New Run
          </h1>
          <p className="text-sm text-muted-foreground">
            Configure and launch a backtest or optimization
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => router.push("/")}
          className="gap-1.5"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back
        </Button>
      </div>

      <StepIndicator current={step} steps={STEPS} />

      {/* Step 1: Mode */}
      {step === 1 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Choose Run Mode</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              {(
                [
                  {
                    value: "single" as RunMode,
                    title: "Single Backtest",
                    desc: "Run one strategy with fixed parameters",
                    icon: Target,
                  },
                  {
                    value: "optimize" as RunMode,
                    title: "Optimize per Symbol",
                    desc: "Grid search over parameter combinations",
                    icon: Zap,
                  },
                ] as const
              ).map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => update("mode", opt.value)}
                  className={cn(
                    "flex flex-col items-start gap-2 rounded-xl border p-4 text-left transition-all",
                    state.mode === opt.value
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border hover:border-primary/30 hover:bg-secondary/50"
                  )}
                >
                  <opt.icon
                    className={cn(
                      "h-5 w-5",
                      state.mode === opt.value
                        ? "text-primary"
                        : "text-muted-foreground"
                    )}
                  />
                  <div>
                    <p className="font-semibold text-foreground">{opt.title}</p>
                    <p className="text-xs text-muted-foreground">{opt.desc}</p>
                  </div>
                </button>
              ))}
            </div>

          </CardContent>
        </Card>
      )}

      {/* Step 2: Data */}
      {step === 2 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Data Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label className="text-sm font-semibold">Data Source</Label>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant={state.dataSource === "dataset" ? "default" : "outline"}
                  onClick={() => update("dataSource", "dataset")}
                >
                  Dataset (BMCE/Upload)
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={state.dataSource === "yfinance" ? "default" : "outline"}
                  onClick={() => update("dataSource", "yfinance")}
                >
                  yfinance (dev)
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">
                Production-safe default is Dataset. yfinance requires the worker image to include yfinance.
              </p>
            </div>

            {state.dataSource === "dataset" && (
              <div className="space-y-3 rounded-xl border border-border p-4">
                <div>
                  <Label className="text-sm font-semibold">Detected datasets</Label>
                  {datasetsLoading ? (
                    <p className="mt-1.5 text-xs text-muted-foreground">Loading datasets…</p>
                  ) : datasets.length === 0 ? (
                    <p className="mt-1.5 text-xs text-muted-foreground">No datasets found — upload one below.</p>
                  ) : (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {datasets.map((d) => (
                        <span
                          key={d.id}
                          className="inline-flex items-center gap-1 rounded-full bg-secondary border border-border px-2.5 py-0.5 text-xs font-mono"
                          title={d.id}
                        >
                          {d.filename ?? d.id}
                          {getDatasetSymbols(d).length > 0 && (
                            <span className="text-muted-foreground">· {getDatasetSymbols(d).length} tickers</span>
                          )}
                          <button
                            type="button"
                            onClick={() => handleDeleteDataset(d.id)}
                            className="ml-1 text-muted-foreground hover:text-destructive transition-colors"
                            title="Delete dataset"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
                  <div>
                    <Label className="text-sm font-semibold">Upload new dataset</Label>
                    <Input
                      type="file"
                      accept=".xlsx,.xls,.csv"
                      onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                      className="mt-1.5"
                    />
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    onClick={handleUploadDataset}
                    disabled={!uploadFile || uploading}
                  >
                    {uploading ? "Uploading…" : "Upload"}
                  </Button>
                </div>
              </div>
            )}

            {/* ── Ticker Picker ── */}
            <div className="space-y-3 rounded-xl border border-border p-4">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <Label className="text-sm font-semibold">Tickers</Label>
                  <p className="text-xs text-muted-foreground">
                    {selectedSymbols.length} of {allAvailableSymbols.length} selected
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button" size="sm" variant="outline"
                    onClick={() => update("symbols", allAvailableSymbols.join(","))}
                    disabled={allAvailableSymbols.length === 0}
                  >
                    All
                  </Button>
                  <Button
                    type="button" size="sm" variant="outline"
                    onClick={() => update("symbols", "")}
                    disabled={selectedSymbols.length === 0}
                  >
                    Clear
                  </Button>
                </div>
              </div>

              {allAvailableSymbols.length > 0 ? (
                <>
                  <div className="relative">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      placeholder="Filter tickers…"
                      className="pl-8 h-8 text-sm"
                      value={tickerSearch}
                      onChange={(e) => setTickerSearch(e.target.value)}
                    />
                  </div>
                  <div className="grid gap-1.5 sm:grid-cols-4 max-h-48 overflow-y-auto pr-1">
                    {allAvailableSymbols
                      .filter((s) => !tickerSearch || s.toLowerCase().includes(tickerSearch.toLowerCase()))
                      .map((symbol) => {
                        const checked = selectedSymbols.includes(symbol)
                        return (
                          <label
                            key={symbol}
                            className={cn(
                              "flex cursor-pointer items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs transition-colors",
                              checked ? "border-primary bg-primary/5 text-primary" : "border-border hover:bg-secondary/40"
                            )}
                          >
                            <Checkbox checked={checked} onCheckedChange={() => toggleDetectedSymbol(symbol)} />
                            <span className="font-mono font-medium truncate">{symbol}</span>
                          </label>
                        )
                      })}
                  </div>
                </>
              ) : (
                <p className="text-xs text-muted-foreground">No tickers available — upload a dataset above.</p>
              )}
            </div>

            <div className="space-y-3 rounded-xl border border-border p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-semibold">Walk-forward optimization</p>
                  <p className="text-xs text-muted-foreground">
                    Run per-fold out-of-sample validation windows.
                  </p>
                </div>
                <Switch
                  checked={state.walkForwardEnabled}
                  onCheckedChange={(v) => update("walkForwardEnabled", v)}
                  disabled={state.mode !== "optimize"}
                />
              </div>

              {state.mode !== "optimize" ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label className="text-xs text-muted-foreground">Start date (optional)</Label>
                    <Input
                      type="date"
                      value={state.singleStartDate}
                      onChange={(e) => update("singleStartDate", e.target.value)}
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground">End date (optional)</Label>
                    <Input
                      type="date"
                      value={state.singleEndDate}
                      onChange={(e) => update("singleEndDate", e.target.value)}
                      className="mt-1"
                    />
                  </div>
                </div>
              ) : state.walkForwardEnabled ? (
                <>
                  <div className="flex gap-2">
                    {(["preset", "custom"] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        onClick={() => update("walkForwardMode", m)}
                        className={cn(
                          "flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-colors",
                          state.walkForwardMode === m
                            ? "border-primary bg-primary/5 text-primary"
                            : "border-border text-muted-foreground hover:border-primary/30"
                        )}
                      >
                        {m === "preset" ? "Presets par horizon" : "Personnalisé"}
                      </button>
                    ))}
                  </div>

                  {state.walkForwardMode === "preset" ? (
                    <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-1">
                      <p className="text-xs font-medium text-foreground">3 horizons calculés automatiquement</p>
                      <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                        <div><span className="font-medium text-foreground">Court terme</span><br />Train 252j · Test 63j · 5 ans</div>
                        <div><span className="font-medium text-foreground">Moyen terme</span><br />Train 504j · Test 126j · 10 ans</div>
                        <div><span className="font-medium text-foreground">Long terme</span><br />Train 756j · Test 252j · 20 ans</div>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="grid gap-3 sm:grid-cols-3">
                        <div>
                          <Label className="text-xs text-muted-foreground">Train (jours)</Label>
                          <Input
                            type="number"
                            min={1}
                            value={state.walkForwardCustomTrain}
                            onChange={(e) => update("walkForwardCustomTrain", Number(e.target.value))}
                            className="mt-1 font-mono"
                          />
                        </div>
                        <div>
                          <Label className="text-xs text-muted-foreground">Test (jours)</Label>
                          <Input
                            type="number"
                            min={1}
                            value={state.walkForwardCustomTest}
                            onChange={(e) => update("walkForwardCustomTest", Number(e.target.value))}
                            className="mt-1 font-mono"
                          />
                        </div>
                        <div>
                          <Label className="text-xs text-muted-foreground">Step (jours)</Label>
                          <Input
                            type="number"
                            min={1}
                            value={state.walkForwardCustomStep}
                            onChange={(e) => update("walkForwardCustomStep", Number(e.target.value))}
                            className="mt-1 font-mono"
                          />
                        </div>
                      </div>
                      <div>
                        <Label className="text-xs text-muted-foreground">Date de début (optionnel)</Label>
                        <Input
                          type="date"
                          value={state.walkForwardStartDate}
                          onChange={(e) => update("walkForwardStartDate", e.target.value)}
                          className="mt-1"
                        />
                      </div>
                    </>
                  )}

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <Label className="text-xs text-muted-foreground">Objectif</Label>
                      <select
                        className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
                        value={state.walkForwardObjective}
                        onChange={(e) => update("walkForwardObjective", e.target.value as "pnl" | "sharpe")}
                      >
                        <option value="pnl">PnL</option>
                        <option value="sharpe">Sharpe</option>
                      </select>
                    </div>
                    <div>
                      <Label className="text-xs text-muted-foreground">Date de fin</Label>
                      <select
                        className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm"
                        value={state.walkForwardEndDatePolicy}
                        onChange={(e) => update("walkForwardEndDatePolicy", e.target.value as EndDatePolicy)}
                      >
                        <option value="latest">Dernière date disponible</option>
                        <option value="fixed">Date fixe</option>
                      </select>
                    </div>
                  </div>

                  {state.walkForwardEndDatePolicy === "fixed" && (
                    <div>
                      <Label className="text-xs text-muted-foreground">Date de fin fixe</Label>
                      <Input
                        type="date"
                        value={state.walkForwardEndDate}
                        onChange={(e) => update("walkForwardEndDate", e.target.value)}
                        className="mt-1"
                      />
                    </div>
                  )}
                </>
              ) : null}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3: Strategies */}
      {step === 3 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Select Strategies</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 sm:grid-cols-2">
              {STRATEGY_CATALOG.map((s) => (
                <label
                  key={s.id}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition-all",
                    state.strategies.includes(s.id)
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/30 hover:bg-secondary/50"
                  )}
                >
                  <Checkbox
                    checked={state.strategies.includes(s.id)}
                    onCheckedChange={() => toggleStrategy(s.id)}
                    className="mt-0.5"
                  />
                  <div>
                    <p className="text-sm font-semibold text-foreground">
                      {s.label}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {s.description}
                    </p>
                  </div>
                </label>
              ))}
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() =>
                update(
                  "strategies",
                  state.strategies.length === STRATEGY_CATALOG.length
                    ? []
                    : STRATEGY_CATALOG.map((s) => s.id)
                )
              }
            >
              {state.strategies.length === STRATEGY_CATALOG.length
                ? "Deselect All"
                : "Select All"}
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Step 4: Parameters */}
      {step === 4 && (
        <CardContent className="space-y-4">
          {state.mode !== "optimize" ? (
            /* ── Single-backtest mode: one fixed value per parameter ── */
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Strategy Parameters</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {state.strategies.length === 0 ? (
                  <p className="text-sm text-muted-foreground">Select a strategy in the previous step first.</p>
                ) : (
                  state.strategies.slice(0, 1).map((s) => {
                    const kind = s.toLowerCase()
                    const keys = STRAT_PARAM_KEYS[kind] ?? []
                    return (
                      <div key={kind} className="space-y-3">
                        <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wide">{kind}</p>
                        {keys.length === 0 ? (
                          <p className="text-xs text-muted-foreground">No parameters for this strategy.</p>
                        ) : (
                          keys.map((fullKey) => {
                            const shortKey = fullKey.startsWith("strategy.") ? fullKey.slice(9) : fullKey
                            const defaultVal = (PARAM_DEFAULTS[fullKey] ?? "").split(",")[0]?.trim() ?? ""
                            const current = state.singleParams[fullKey] ?? defaultVal
                            return (
                              <div key={fullKey}>
                                <Label className="text-xs text-muted-foreground font-mono">{shortKey}</Label>
                                <Input
                                  className="mt-1 font-mono text-sm"
                                  value={current}
                                  placeholder={defaultVal}
                                  onChange={(e) =>
                                    setState((prev) => ({
                                      ...prev,
                                      singleParams: { ...prev.singleParams, [fullKey]: e.target.value },
                                    }))
                                  }
                                />
                              </div>
                            )
                          })
                        )}
                      </div>
                    )
                  })
                )}
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="flex items-center justify-between rounded-xl border border-border p-4">
                <div>
                  <p className="text-sm font-semibold">Include portfolio params in optimization</p>
                  <p className="text-xs text-muted-foreground">
                    When enabled, cooldown/sizing/etc appear as tunable parameters and are included in domains_by_kind.
                  </p>
                </div>
                <Switch
                  checked={state.optimizePortfolio}
                  onCheckedChange={(v) => update("optimizePortfolio", v)}
                />
              </div>

              <div className="space-y-3">
                {state.strategies.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Select at least one strategy to configure its parameter domains.
                  </p>
                ) : (
                  state.strategies.map((s) => {
                    const kind = s.toLowerCase()
                    const keys = STRAT_PARAM_KEYS[kind] ?? []
                    if (keys.length === 0) {
                      return (
                        <div key={kind} className="rounded-xl border border-border p-4">
                          <p className="text-sm font-semibold">{kind}</p>
                          <p className="text-xs text-muted-foreground">No tunable parameters registered.</p>
                        </div>
                      )
                    }

                    return (
                      <div key={kind} className="rounded-xl border border-border p-4">
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm font-semibold">{kind}</p>
                            <p className="text-xs text-muted-foreground">
                              Configure domains (list or range) for this strategy.
                            </p>
                          </div>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              // quick enable all params for this strategy
                              setState((prev) => {
                                const next = { ...prev.paramUI }
                                for (const k of keys) {
                                  next[k] = next[k] ?? {
                                    enabled: true, mode: "list", list: PARAM_DEFAULTS[k] ?? "",
                                    start: "", end: "", step: ""
                                  }
                                  next[k] = { ...next[k], enabled: true }
                                }
                                return { ...prev, paramUI: next }
                              })
                            }}
                          >
                            Enable all
                          </Button>
                        </div>

                        <div className="mt-4 space-y-3">
                          {keys.map((k) => {
                            const ui = state.paramUI[k] ?? {
                              enabled: true,
                              mode: "list" as const,
                              list: PARAM_DEFAULTS[k] ?? "",
                              start: "",
                              end: "",
                              step: "",
                            }

                            return (
                              <div key={`${kind}-${k}`} className="rounded-lg border border-border p-3">
                                <div className="flex items-start justify-between gap-4">
                                  <div className="min-w-0">
                                    <p className="font-mono text-sm font-semibold">{k}</p>
                                    <p className="text-xs text-muted-foreground">
                                      Default: <span className="font-mono">{PARAM_DEFAULTS[k] ?? "—"}</span>
                                    </p>
                                  </div>

                                  <div className="flex items-center gap-3">
                                    <label className="flex items-center gap-2 text-xs">
                                      <span className="text-muted-foreground">Enable</span>
                                      <Switch
                                        checked={ui.enabled}
                                        onCheckedChange={(v) => {
                                          setState((prev) => ({
                                            ...prev,
                                            paramUI: { ...prev.paramUI, [k]: { ...ui, enabled: v } },
                                          }))
                                        }}
                                      />
                                    </label>

                                    <select
                                      className="rounded-md border border-border bg-background p-2 text-xs"
                                      value={ui.mode}
                                      onChange={(e) => {
                                        const mode = e.target.value as ParamMode
                                        setState((prev) => ({
                                          ...prev,
                                          paramUI: { ...prev.paramUI, [k]: { ...ui, mode } },
                                        }))
                                      }}
                                      disabled={!ui.enabled}
                                    >
                                      <option value="list">List</option>
                                      <option value="range">Range</option>
                                    </select>
                                  </div>
                                </div>

                                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                                  {ui.mode === "list" ? (
                                    <div className="sm:col-span-3">
                                      <Label className="text-xs text-muted-foreground">Values (comma-separated)</Label>
                                      <Input
                                        value={ui.list}
                                        onChange={(e) => {
                                          const list = e.target.value
                                          setState((prev) => ({
                                            ...prev,
                                            paramUI: { ...prev.paramUI, [k]: { ...ui, list } },
                                          }))
                                        }}
                                        disabled={!ui.enabled}
                                        className="mt-1 font-mono text-xs"
                                        placeholder={PARAM_DEFAULTS[k] ?? "e.g. 7,10,14"}
                                      />
                                    </div>
                                  ) : (
                                    <>
                                      <div>
                                        <Label className="text-xs text-muted-foreground">Start</Label>
                                        <Input
                                          value={ui.start}
                                          onChange={(e) => {
                                            const start = e.target.value
                                            setState((prev) => ({
                                              ...prev,
                                              paramUI: { ...prev.paramUI, [k]: { ...ui, start } },
                                            }))
                                          }}
                                          disabled={!ui.enabled}
                                          className="mt-1 font-mono text-xs"
                                          placeholder="e.g. 5"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-xs text-muted-foreground">End</Label>
                                        <Input
                                          value={ui.end}
                                          onChange={(e) => {
                                            const end = e.target.value
                                            setState((prev) => ({
                                              ...prev,
                                              paramUI: { ...prev.paramUI, [k]: { ...ui, end } },
                                            }))
                                          }}
                                          disabled={!ui.enabled}
                                          className="mt-1 font-mono text-xs"
                                          placeholder="e.g. 30"
                                        />
                                      </div>
                                      <div>
                                        <Label className="text-xs text-muted-foreground">Step</Label>
                                        <Input
                                          value={ui.step}
                                          onChange={(e) => {
                                            const step = e.target.value
                                            setState((prev) => ({
                                              ...prev,
                                              paramUI: { ...prev.paramUI, [k]: { ...ui, step } },
                                            }))
                                          }}
                                          disabled={!ui.enabled}
                                          className="mt-1 font-mono text-xs"
                                          placeholder="e.g. 1"
                                        />
                                      </div>
                                    </>
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })
                )}

                {state.optimizePortfolio && PORTF_KEYS.length > 0 && (
                  <div className="rounded-xl border border-border p-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-semibold">Portfolio parameter domains</p>
                        <p className="text-xs text-muted-foreground">
                          These apply to every strategy during optimization.
                        </p>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setState((prev) => {
                            const next = { ...prev.paramUI }
                            for (const k of PORTF_KEYS) {
                              next[k] = next[k] ?? {
                                enabled: true,
                                mode: "list",
                                list: PARAM_DEFAULTS[k] ?? "",
                                start: "",
                                end: "",
                                step: "",
                              }
                              next[k] = { ...next[k], enabled: true }
                            }
                            return { ...prev, paramUI: next }
                          })
                        }}
                      >
                        Enable all
                      </Button>
                    </div>

                    <div className="mt-4 space-y-3">
                      {PORTF_KEYS.map((k) => {
                        const ui = state.paramUI[k] ?? {
                          enabled: true,
                          mode: "list" as const,
                          list: PARAM_DEFAULTS[k] ?? "",
                          start: "",
                          end: "",
                          step: "",
                        }

                        return (
                          <div key={`portf-${k}`} className="rounded-lg border border-border p-3">
                            <div className="flex items-start justify-between gap-4">
                              <div className="min-w-0">
                                <p className="font-mono text-sm font-semibold">{k}</p>
                                <p className="text-xs text-muted-foreground">
                                  Default: <span className="font-mono">{PARAM_DEFAULTS[k] ?? "—"}</span>
                                </p>
                              </div>

                              <div className="flex items-center gap-3">
                                <label className="flex items-center gap-2 text-xs">
                                  <span className="text-muted-foreground">Enable</span>
                                  <Switch
                                    checked={ui.enabled}
                                    onCheckedChange={(v) => {
                                      setState((prev) => ({
                                        ...prev,
                                        paramUI: { ...prev.paramUI, [k]: { ...ui, enabled: v } },
                                      }))
                                    }}
                                  />
                                </label>

                                <select
                                  className="rounded-md border border-border bg-background p-2 text-xs"
                                  value={ui.mode}
                                  onChange={(e) => {
                                    const mode = e.target.value as ParamMode
                                    setState((prev) => ({
                                      ...prev,
                                      paramUI: { ...prev.paramUI, [k]: { ...ui, mode } },
                                    }))
                                  }}
                                  disabled={!ui.enabled}
                                >
                                  <option value="list">List</option>
                                  <option value="range">Range</option>
                                </select>
                              </div>
                            </div>

                            <div className="mt-3 grid gap-3 sm:grid-cols-3">
                              {ui.mode === "list" ? (
                                <div className="sm:col-span-3">
                                  <Label className="text-xs text-muted-foreground">Values (comma-separated)</Label>
                                  <Input
                                    value={ui.list}
                                    onChange={(e) => {
                                      const list = e.target.value
                                      setState((prev) => ({
                                        ...prev,
                                        paramUI: { ...prev.paramUI, [k]: { ...ui, list } },
                                      }))
                                    }}
                                    disabled={!ui.enabled}
                                    className="mt-1 font-mono text-xs"
                                    placeholder={PARAM_DEFAULTS[k] ?? "e.g. 0.25,0.5,1"}
                                  />
                                </div>
                              ) : (
                                <>
                                  <div>
                                    <Label className="text-xs text-muted-foreground">Start</Label>
                                    <Input
                                      value={ui.start}
                                      onChange={(e) => {
                                        const start = e.target.value
                                        setState((prev) => ({
                                          ...prev,
                                          paramUI: { ...prev.paramUI, [k]: { ...ui, start } },
                                        }))
                                      }}
                                      disabled={!ui.enabled}
                                      className="mt-1 font-mono text-xs"
                                    />
                                  </div>
                                  <div>
                                    <Label className="text-xs text-muted-foreground">End</Label>
                                    <Input
                                      value={ui.end}
                                      onChange={(e) => {
                                        const end = e.target.value
                                        setState((prev) => ({
                                          ...prev,
                                          paramUI: { ...prev.paramUI, [k]: { ...ui, end } },
                                        }))
                                      }}
                                      disabled={!ui.enabled}
                                      className="mt-1 font-mono text-xs"
                                    />
                                  </div>
                                  <div>
                                    <Label className="text-xs text-muted-foreground">Step</Label>
                                    <Input
                                      value={ui.step}
                                      onChange={(e) => {
                                        const step = e.target.value
                                        setState((prev) => ({
                                          ...prev,
                                          paramUI: { ...prev.paramUI, [k]: { ...ui, step } },
                                        }))
                                      }}
                                      disabled={!ui.enabled}
                                      className="mt-1 font-mono text-xs"
                                    />
                                  </div>
                                </>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </CardContent>
      )}

      {/* Step 5: Portfolio */}
      {step === 5 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Portfolio Settings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label className="text-sm font-semibold">Initial Cash</Label>
                <Input
                  type="number"
                  value={state.initialCash}
                  onChange={(e) =>
                    update("initialCash", Number(e.target.value))
                  }
                  className="mt-1.5 font-mono"
                />
              </div>
              <div className="space-y-3 rounded-xl border border-border p-4">
                <div>
                  <p className="text-sm font-semibold">Cost Model</p>
                  <p className="text-xs text-muted-foreground">
                    Define each cost component (bps) + TVA.
                  </p>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label className="text-xs text-muted-foreground">Brokerage (bps)</Label>
                    <Input
                      type="number"
                      value={state.costModel.brokerage_bps}
                      onChange={(e) =>
                        update("costModel", { ...state.costModel, brokerage_bps: Number(e.target.value) })
                      }
                      className="mt-1 font-mono"
                    />
                  </div>

                  <div>
                    <Label className="text-xs text-muted-foreground">Bourse commission (bps)</Label>
                    <Input
                      type="number"
                      value={state.costModel.comm_bourse_bps}
                      onChange={(e) =>
                        update("costModel", { ...state.costModel, comm_bourse_bps: Number(e.target.value) })
                      }
                      className="mt-1 font-mono"
                    />
                  </div>

                  <div>
                    <Label className="text-xs text-muted-foreground">Reg/Liv (bps)</Label>
                    <Input
                      type="number"
                      value={state.costModel.reg_liv_bps}
                      onChange={(e) =>
                        update("costModel", { ...state.costModel, reg_liv_bps: Number(e.target.value) })
                      }
                      className="mt-1 font-mono"
                    />
                  </div>

                  <div>
                    <Label className="text-xs text-muted-foreground">Slippage (bps)</Label>
                    <Input
                      type="number"
                      value={state.costModel.slippage_bps}
                      onChange={(e) =>
                        update("costModel", { ...state.costModel, slippage_bps: Number(e.target.value) })
                      }
                      className="mt-1 font-mono"
                    />
                  </div>

                  <div className="sm:col-span-2">
                    <Label className="text-xs text-muted-foreground">TVA rate (0–1)</Label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      value={state.costModel.tva_rate}
                      onChange={(e) =>
                        update("costModel", { ...state.costModel, tva_rate: Number(e.target.value) })
                      }
                      className="mt-1 font-mono"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="space-y-3 rounded-xl border border-border p-4">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-semibold">Cooldown</Label>
                <Switch
                  checked={state.cooldownEnabled}
                  onCheckedChange={(v) => update("cooldownEnabled", v)}
                />
              </div>
              {state.cooldownEnabled && (
                <div>
                  <Label className="text-xs text-muted-foreground">
                    Cooldown Bars
                  </Label>
                  <Input
                    type="number"
                    value={state.cooldownBars}
                    onChange={(e) =>
                      update("cooldownBars", Number(e.target.value))
                    }
                    className="mt-1 font-mono"
                  />
                </div>
              )}
            </div>

            <div className="space-y-3 rounded-xl border border-border p-4">
              <div className="flex items-center justify-between">
                <Label className="text-sm font-semibold">
                  Position Sizing
                </Label>
                <Switch
                  checked={state.sizingEnabled}
                  onCheckedChange={(v) => update("sizingEnabled", v)}
                />
              </div>
              {state.sizingEnabled && (
                <div className="grid gap-3 sm:grid-cols-3">
                  <div>
                    <Label className="text-xs text-muted-foreground">
                      Buy % Cash
                    </Label>
                    <Input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      value={state.buyPctCash}
                      onChange={(e) =>
                        update("buyPctCash", Number(e.target.value))
                      }
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground">
                      Sell % Shares
                    </Label>
                    <Input
                      type="number"
                      step="0.05"
                      min="0"
                      max="1"
                      value={state.sellPctShares}
                      onChange={(e) =>
                        update("sellPctShares", Number(e.target.value))
                      }
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground">
                      Min Return Before Sell
                    </Label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      value={state.minReturnBeforeSell}
                      onChange={(e) =>
                        update("minReturnBeforeSell", Number(e.target.value))
                      }
                      className="mt-1 font-mono"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Volume Gate */}
            <div className="space-y-3 rounded-xl border border-border p-4">
              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-sm font-semibold">Volume Gate</Label>
                  <p className="text-xs text-muted-foreground">Skip orders when volume is too thin.</p>
                </div>
                <Switch
                  checked={state.volumeGateEnabled}
                  onCheckedChange={(v) => update("volumeGateEnabled", v)}
                />
              </div>
              {state.volumeGateEnabled && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="sm:col-span-2">
                    <Label className="text-xs text-muted-foreground">Gate Kind</Label>
                    <select
                      className="mt-1 w-full rounded-md border border-border bg-background p-2 text-sm font-mono"
                      value={state.volumeGateKind}
                      onChange={(e) => update("volumeGateKind", e.target.value as "min_abs" | "min_ratio_adv")}
                    >
                      <option value="min_ratio_adv">Min ratio of ADV (recommended)</option>
                      <option value="min_abs">Min absolute volume</option>
                    </select>
                  </div>
                  {state.volumeGateKind === "min_abs" ? (
                    <div className="sm:col-span-2">
                      <Label className="text-xs text-muted-foreground">Min Volume (absolute shares)</Label>
                      <Input
                        type="number"
                        min="0"
                        value={state.volumeGateMinAbs}
                        onChange={(e) => update("volumeGateMinAbs", Number(e.target.value))}
                        className="mt-1 font-mono"
                      />
                    </div>
                  ) : (
                    <>
                      <div>
                        <Label className="text-xs text-muted-foreground">Min Ratio of ADV (0–1)</Label>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          max="1"
                          value={state.volumeGateMinRatioAdv}
                          onChange={(e) => update("volumeGateMinRatioAdv", Number(e.target.value))}
                          className="mt-1 font-mono"
                        />
                      </div>
                      <div>
                        <Label className="text-xs text-muted-foreground">ADV Window (days)</Label>
                        <Input
                          type="number"
                          min="1"
                          value={state.volumeGateAdvWindow}
                          onChange={(e) => update("volumeGateAdvWindow", Number(e.target.value))}
                          className="mt-1 font-mono"
                        />
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Participation Cap */}
            <div className="space-y-3 rounded-xl border border-border p-4">
              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-sm font-semibold">Participation Cap</Label>
                  <p className="text-xs text-muted-foreground">Limit order size to a fraction of daily volume.</p>
                </div>
                <Switch
                  checked={state.participationCapEnabled}
                  onCheckedChange={(v) => update("participationCapEnabled", v)}
                />
              </div>
              {state.participationCapEnabled && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label className="text-xs text-muted-foreground">Max Participation Rate (0–1)</Label>
                    <Input
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      value={state.participationRate}
                      onChange={(e) => update("participationRate", Number(e.target.value))}
                      className="mt-1 font-mono"
                    />
                  </div>
                  <div>
                    <Label className="text-xs text-muted-foreground">ADV Window (days)</Label>
                    <Input
                      type="number"
                      min="1"
                      value={state.participationAdvWindow}
                      onChange={(e) => update("participationAdvWindow", Number(e.target.value))}
                      className="mt-1 font-mono"
                    />
                  </div>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Navigation */}
      <div className="flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setStep((s) => Math.max(1, s - 1))}
          disabled={step === 1}
          className="gap-1.5"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Back
        </Button>

        {step < 5 ? (
          <Button
            size="sm"
            onClick={() => setStep((s) => s + 1)}
            disabled={!canNext()}
            className="gap-1.5"
          >
            Next
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={handleSubmit}
            disabled={submitting || !canNext()}
            className="gap-1.5"
          >
            {submitting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            {submitting ? "Creating..." : "Create Run"}
          </Button>
        )}
      </div>
    </div>
  )
}
