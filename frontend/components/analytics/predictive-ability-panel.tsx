"use client"

import { useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { usePredictiveAbility, useCategoryCombinations } from "@/hooks/use-api"
import { triggerPredictiveHistory } from "@/lib/api"
import { horizonLabel, horizonLabelWithDays } from "@/lib/horizon"
import { useToast } from "@/hooks/use-toast"
import { BucketMatrix } from "./bucket-matrix"

const SOURCES = [
  { value: "engine_legacy", label: "Engine — Legacy" },
  { value: "engine_expanded", label: "Engine — Expanded" },
  { value: "factor_x_ta", label: "Factor×TA" },
  { value: "wfo", label: "WFO" },
] as const

const SOURCE_KINDS = [
  { value: "engine", label: "Engine" },
  { value: "wfo", label: "WFO" },
] as const

const SIGNAL_MODES = [
  { value: "legacy_ta_simple", label: "L TA" },
  { value: "expanded_ta_simple", label: "E TA" },
  { value: "legacy_factor_x_ta_simple", label: "L FX" },
  { value: "expanded_factor_x_ta_simple", label: "E FX" },
  { value: "legacy_ta_combo", label: "L TA Combo" },
  { value: "expanded_ta_combo", label: "E TA Combo" },
  { value: "legacy_factor_x_ta_combo", label: "L FX Combo" },
  { value: "expanded_factor_x_ta_combo", label: "E FX Combo" },
] as const

type SourceKind = (typeof SOURCE_KINDS)[number]["value"]
type SignalMode = (typeof SIGNAL_MODES)[number]["value"]

function parseInitialSource(value?: string): { sourceKind: SourceKind; mode: SignalMode } {
  if (!value) return { sourceKind: "engine", mode: "expanded_ta_simple" }
  const token = value.toLowerCase()
  if (token.includes(":")) {
    const [axis, rawMode] = token.split(":", 2)
    const mode = SIGNAL_MODES.some((m) => m.value === rawMode) ? (rawMode as SignalMode) : "expanded_ta_simple"
    return { sourceKind: axis === "wfo" ? "wfo" : "engine", mode }
  }
  if (token === "engine_legacy" || token === "legacy") return { sourceKind: "engine", mode: "legacy_ta_simple" }
  if (token === "factor_x_ta") return { sourceKind: "engine", mode: "expanded_factor_x_ta_simple" }
  if (token === "wfo") return { sourceKind: "wfo", mode: "expanded_ta_simple" }
  const mode = SIGNAL_MODES.some((m) => m.value === token) ? (token as SignalMode) : "expanded_ta_simple"
  return { sourceKind: "engine", mode }
}

const HORIZONS = [
  { value: "short", label: horizonLabelWithDays("short") },
  { value: "medium", label: horizonLabelWithDays("medium") },
  { value: "long", label: horizonLabelWithDays("long") },
] as const

const CATEGORIES = ["tendance", "momentum", "oscillation", "volume"] as const
type CategoryKey = (typeof CATEGORIES)[number]

const FWD_BY_HORIZON: Record<string, number[]> = {
  short: [1, 2, 3, 4, 5],
  medium: [6, 10, 15, 21],
  long: [30, 60, 120, 200],
}

const BUCKET_BADGE_CLASS: Record<string, string> = {
  strong_buy: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  buy: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  hold: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  sell: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
  strong_sell: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
}

const BUCKET_DISPLAY: Record<string, string> = {
  strong_buy: "Strong Buy",
  buy: "Buy",
  hold: "Hold",
  sell: "Sell",
  strong_sell: "Strong Sell",
}

const RETURN_METHODS = [
  { value: "open_to_open", label: "O to O" },
  { value: "open_to_close", label: "O to C" },
] as const

interface Props {
  symbol: string
  initialSource?: string
  initialHorizon?: "short" | "medium" | "long"
  lookback_days?: number
}

export function PredictiveAbilityPanel({ symbol, initialSource, initialHorizon, lookback_days }: Props) {
  const { toast } = useToast()
  const initial = parseInitialSource(initialSource)
  const [sourceKind, setSourceKind] = useState<SourceKind>(initial.sourceKind)
  const [mode, setMode] = useState<SignalMode>(initial.mode)
  const source = `${sourceKind}:${mode}`
  const [horizon, setHorizon] = useState<"short" | "medium" | "long">(
    initialHorizon ?? "short",
  )
  const [returnCalcMethod, setReturnCalcMethod] = useState<string>("open_to_open")
  const [selectedCats, setSelectedCats] = useState<CategoryKey[]>([...CATEGORIES])
  const [showAllFwd, setShowAllFwd] = useState(false)

  const fwdHorizons = showAllFwd
    ? [1, 2, 3, 4, 5, 6, 10, 15, 21, 30, 60, 120, 200]
    : FWD_BY_HORIZON[horizon]

  const { data: matrix, error, isLoading } = usePredictiveAbility({
    symbol,
    source,
    horizon,
    categories: selectedCats,
    fwdHorizons,
    lookback_days,
    return_calc_method: returnCalcMethod,
  })

  const { data: combos } = useCategoryCombinations({
    symbol,
    source,
    horizon,
    fwd_h: fwdHorizons[Math.floor(fwdHorizons.length / 2)],
    lookback_days,
    return_calc_method: returnCalcMethod,
  })

  function toggleCat(cat: CategoryKey) {
    setSelectedCats((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    )
  }

  async function handleRecompute() {
    try {
      await triggerPredictiveHistory(symbol)
      toast({ title: "Recompute lancé", description: `Historique pour ${symbol}.` })
    } catch (e) {
      toast({ title: "Erreur", description: String(e), variant: "destructive" })
    }
  }

  return (
    <div className="space-y-4">
      {/* Selectors */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/30 p-3">
        <div className="flex flex-col gap-1">
          <Label className="text-[10px] uppercase text-muted-foreground">Source</Label>
          <div className="flex rounded-md border bg-background">
            {SOURCE_KINDS.map((s) => (
              <button
                key={s.value}
                onClick={() => setSourceKind(s.value)}
                className={`px-3 py-1 text-xs ${
                  sourceKind === s.value ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-[10px] uppercase text-muted-foreground">Mode</Label>
          <div className="flex max-w-[520px] flex-wrap rounded-md border bg-background">
            {SIGNAL_MODES.map((m) => (
              <button
                key={m.value}
                onClick={() => setMode(m.value)}
                className={`px-2 py-1 text-xs ${
                  mode === m.value ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-[10px] uppercase text-muted-foreground">Horizon</Label>
          <div className="flex rounded-md border bg-background">
            {HORIZONS.map((h) => (
              <button
                key={h.value}
                onClick={() => setHorizon(h.value)}
                className={`px-3 py-1 text-xs ${
                  horizon === h.value ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                }`}
              >
                {h.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-[10px] uppercase text-muted-foreground">Rendement</Label>
          <div className="flex rounded-md border bg-background">
            {RETURN_METHODS.map((rm) => (
              <button
                key={rm.value}
                onClick={() => setReturnCalcMethod(rm.value)}
                className={`px-3 py-1 text-xs ${
                  returnCalcMethod === rm.value ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                }`}
              >
                {rm.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-[10px] uppercase text-muted-foreground">Catégories</Label>
          <div className="flex flex-wrap gap-2">
            {CATEGORIES.map((cat) => (
              <label key={cat} className="flex items-center gap-1.5 text-xs">
                <Checkbox
                  checked={selectedCats.includes(cat)}
                  onCheckedChange={() => toggleCat(cat)}
                />
                {cat}
              </label>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-[10px] uppercase text-muted-foreground">Horizons fwd</Label>
          <label className="flex items-center gap-1.5 text-xs">
            <Checkbox checked={showAllFwd} onCheckedChange={(v) => setShowAllFwd(!!v)} />
            Tous (1-200j)
          </label>
        </div>
      </div>

      {/* Matrix */}
      {isLoading && (
        <div className="rounded-md border p-6 text-center text-sm text-muted-foreground">
          Chargement…
        </div>
      )}
      {error && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm">
          <div className="font-medium text-red-500">Erreur</div>
          <div className="text-xs text-muted-foreground mt-1">{String(error)}</div>
        </div>
      )}
      {matrix && !matrix.available && (
        <div className="rounded-md border bg-muted/30 p-6 text-sm">
          <div className="font-medium">Aucun historique de scores pour {symbol}</div>
          <div className="text-xs text-muted-foreground mt-1">
            {matrix.message ?? "Lancez d'abord un recompute de l'historique de scores."}
          </div>
          <Button size="sm" className="mt-3" onClick={handleRecompute}>
            Recompute predictive history
          </Button>
        </div>
      )}
      {matrix && matrix.available && (
        <>
          <div className="flex items-center gap-2 flex-wrap text-xs text-muted-foreground">
            <Badge variant="outline">n_obs = {matrix.n_obs}</Badge>
            <span>
              {symbol} · {source} · {horizonLabel(horizon)} ·{" "}
              {matrix.categories.length === CATEGORIES.length
                ? "toutes catégories"
                : matrix.categories.join(" + ")}
            </span>
            {matrix.current_bucket && (
              <>
                <span>·</span>
                <span>Signal aujourd&apos;hui :</span>
                <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${BUCKET_BADGE_CLASS[matrix.current_bucket] ?? ""}`}>
                  {BUCKET_DISPLAY[matrix.current_bucket] ?? matrix.current_bucket}
                </span>
                {matrix.current_score != null && (
                  <span className="font-mono text-muted-foreground">({matrix.current_score.toFixed(1)})</span>
                )}
              </>
            )}
          </div>
          <BucketMatrix matrix={matrix} />
        </>
      )}

      {/* Combinations strip */}
      {combos && combos.rows.length > 0 && (
        <div className="rounded-md border">
          <div className="bg-muted/40 px-3 py-2 text-xs font-medium">
            Top combinaisons de catégories (par monotonicité Strong Buy − Strong Sell, h={combos.fwd_h}j)
          </div>
          <div className="divide-y">
            {combos.rows.slice(0, 8).map((row, i) => {
              const same =
                row.categories.length === selectedCats.length &&
                row.categories.every((c) => selectedCats.includes(c as CategoryKey))
              return (
                <button
                  key={i}
                  onClick={() => setSelectedCats(row.categories as CategoryKey[])}
                  className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs hover:bg-muted/50 ${
                    same ? "bg-primary/10" : ""
                  }`}
                >
                  <div className="flex flex-wrap gap-1">
                    {row.categories.map((c) => (
                      <Badge key={c} variant="secondary" className="text-[10px]">
                        {c}
                      </Badge>
                    ))}
                  </div>
                  <div className="flex items-center gap-3 font-mono text-[11px] tabular-nums">
                    <span className={`${(row.monotonicity_score ?? 0) > 0 ? "text-emerald-600" : "text-red-500"}`}>
                      Δ ={" "}
                      {row.monotonicity_score == null
                        ? "—"
                        : `${(row.monotonicity_score * 100).toFixed(2)}%`}
                    </span>
                    <span className="text-muted-foreground">
                      SB n={row.n_strong_buy} · SS n={row.n_strong_sell}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
