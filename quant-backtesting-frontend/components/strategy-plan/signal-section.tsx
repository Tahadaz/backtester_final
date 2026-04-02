"use client"

import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalScoreBar } from "@/components/strategy/signal-score-bar"
import { SignalZoneChart } from "@/components/strategy/signal-zone-chart"
import { useSignalConsensus, useSignalZoneChart } from "@/hooks/use-api"
import { Info } from "lucide-react"

// Signal formation tiers
const FORMATION_TIERS = [
  "Les variants représentatifs votent au sein de chaque famille",
  "Chaque famille produit un signal par consensus pondéré",
  "Les signaux de famille sont agrégés en signal global",
]

// Family → category mapping
const FAMILY_CATEGORIES = [
  {
    name: "Tendance",
    families: [
      { id: "sma", label: "SMA (Moy. mobiles)", role: "Existence et direction du trend" },
    ],
  },
  {
    name: "Momentum",
    families: [{ id: "macd", label: "MACD", role: "Confirmation de l'accélération" }],
  },
  {
    name: "Oscillation",
    families: [{ id: "rsi", label: "RSI", role: "Filtre d'excès / étirement" }],
  },
  {
    name: "Volume",
    families: [{ id: "obv", label: "OBV", role: "Confirmation de l'accumulation" }],
  },
]

export function SignalSection({
  focusedStock,
  horizon,
  enabledFamilies,
  onToggleFamily,
}: {
  focusedStock: string | null
  horizon: string
  enabledFamilies: string[]
  onToggleFamily: (family: string) => void
}) {
  const { data: consensus, isLoading } = useSignalConsensus(
    focusedStock,
    horizon,
    enabledFamilies,
  )
  const { data: zoneChart, isLoading: zoneLoading } = useSignalZoneChart(
    focusedStock,
    horizon,
    enabledFamilies,
  )

  return (
    <div className="space-y-4">
      {/* Signal formation methodology — always visible */}
      <div className="rounded-md border bg-muted/20 p-3 space-y-1.5">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Formation du signal
        </span>
        {FORMATION_TIERS.map((tier, i) => (
          <div key={i} className="flex items-start gap-2">
            <Badge variant="secondary" className="text-[9px] px-1.5 py-0 shrink-0 mt-0.5 font-mono">
              {i + 1}
            </Badge>
            <span className="text-[11px] text-muted-foreground">{tier}</span>
          </div>
        ))}
      </div>

      {/* Consensus bar — only when stock focused */}
      {focusedStock ? (
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              Consensus — {focusedStock}
            </span>
            <Badge variant="secondary" className="text-[10px]">
              Politique : Consensus
            </Badge>
          </div>
          {isLoading ? (
            <Skeleton className="h-12 w-full" />
          ) : (
            <SignalScoreBar
              value={consensus?.final_consensus ?? null}
              size="lg"
            />
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2 py-3 justify-center text-muted-foreground rounded-md bg-muted/30">
          <Info className="h-3.5 w-3.5 opacity-40" />
          <span className="text-[11px]">
            Sélectionnez un titre pour voir les scores
          </span>
        </div>
      )}

      {/* Zone chart — only when stock focused */}
      {focusedStock && (
        <SignalZoneChart
          data={zoneChart}
          enabledFamilies={enabledFamilies}
          isLoading={zoneLoading}
        />
      )}

      {/* Family categories — always visible */}
      <div className="space-y-3">
        {FAMILY_CATEGORIES.map((cat) => (
          <div key={cat.name} className="space-y-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              {cat.name}
            </span>
            <div className="space-y-1">
              {cat.families.map((fam) => {
                const enabled = enabledFamilies.includes(fam.id)
                const famData = consensus?.per_family?.[fam.id]
                const weight = consensus?.family_weights?.[fam.id]

                return (
                  <div
                    key={fam.id}
                    className={`flex items-center gap-3 rounded-md px-2 py-1.5 transition-opacity ${
                      enabled ? "opacity-100" : "opacity-40"
                    }`}
                  >
                    {/* Toggle */}
                    <Checkbox
                      checked={enabled}
                      onCheckedChange={() => onToggleFamily(fam.id)}
                      className="h-3.5 w-3.5"
                    />

                    {/* Family name + role */}
                    <div className="w-[180px] shrink-0">
                      <span className="text-xs font-medium">{fam.label}</span>
                      <p className="text-[10px] text-muted-foreground leading-tight">{fam.role}</p>
                    </div>

                    {/* Score bar — only when stock focused */}
                    <div className="flex-1 min-w-0">
                      {enabled && focusedStock ? (
                        isLoading ? (
                          <Skeleton className="h-5 w-full" />
                        ) : (
                          <SignalScoreBar
                            value={famData?.score_pct ?? null}
                            size="sm"
                          />
                        )
                      ) : (
                        <div className="h-5" />
                      )}
                    </div>

                    {/* Weight */}
                    <span className="text-[10px] font-mono text-muted-foreground w-[40px] text-right shrink-0">
                      {enabled && focusedStock && weight != null
                        ? `${(weight * 100).toFixed(0)}%`
                        : "—"}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Warning when all disabled */}
      {enabledFamilies.length === 0 && (
        <div className="flex items-center gap-2 py-2 justify-center rounded-md bg-amber-50 dark:bg-amber-950/20">
          <Info className="h-3.5 w-3.5 text-amber-600" />
          <span className="text-xs text-amber-700 dark:text-amber-400">
            Aucune famille active — le consensus est indisponible
          </span>
        </div>
      )}

      {/* Synthesis — always visible */}
      <p className="text-[10px] italic text-muted-foreground">
        La stratégie recherche des tendances exploitables, puis les valide par le momentum, la rationalité et le soutien des flux.
      </p>
    </div>
  )
}
