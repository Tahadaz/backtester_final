"use client"

import { useRouter } from "next/navigation"
import type { FamilyCombinedSignal, SignalRepresentative } from "@/lib/api"
import { SignalBadge } from "@/components/signal-badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ArrowLeft } from "lucide-react"

function repLabel(rep: SignalRepresentative): string {
  const p = rep.params as Record<string, unknown>
  if (rep.archetype === "price_vs_sma") return `SMA-${p.window ?? "?"}`
  if (rep.archetype === "price_vs_ema") return `EMA-${p.window ?? "?"}`
  if (rep.archetype === "sma_cross") return `SMA(${p.fast},${p.slow})`
  if (rep.archetype === "ema_cross") return `EMA(${p.fast},${p.slow})`
  if (rep.archetype === "slope_confirmed") return `SMA-${p.window} Slope`
  if (rep.archetype === "ichi_cloud") return `Ichimoku(${p.tenkan},${p.kijun},${p.senkou_b})`
  if (rep.archetype === "psar_trend") return `PSAR(${p.af_step},${p.af_max})`
  if (rep.archetype === "rsi_level") return `RSI(${p.period},${p.oversold}/${p.overbought})`
  if (rep.archetype === "macd_cross") return `MACD(${p.fast},${p.slow},${p.signal})`
  if (rep.archetype === "roc_zero") return `ROC-${p.period}`
  if (rep.archetype === "trix_zero") return `TRIX-${p.period}`
  if (rep.archetype === "adx_trend") return `ADX(${p.period},${p.adx_threshold})`
  if (rep.archetype === "tsi_zero") return `TSI(${p.long_period},${p.short_period})`
  if (rep.archetype === "stoch_level") return `Stoch(${p.k_period},${p.d_period})`
  if (rep.archetype === "cci_level") return `CCI-${p.period}`
  if (rep.archetype === "mfi_level") return `MFI(${p.period},${p.oversold}/${p.overbought})`
  if (rep.archetype === "uo_level") return `UO(${p.period_1},${p.period_2},${p.period_3})`
  if (rep.archetype === "obv_trend") return `OBV-EMA-${p.ema_period}`
  if (rep.archetype === "cmf_flow") return `CMF-${p.period}`
  if (rep.archetype === "ad_trend") return `AD-EMA-${p.ema_period}`
  if (rep.archetype === "vwap_dev") return `VWAP(${p.period},${p.threshold_pct}%)`
  if (rep.archetype === "fi_trend") return `FI-${p.period}`
  return rep.variant_id.slice(0, 12)
}

export function SmaFamilyDrilldown({
  data,
  family,
  cooldownBars,
  onBack,
}: {
  data: FamilyCombinedSignal
  family?: string
  cooldownBars?: number
  onBack: () => void
}) {
  const router = useRouter()
  const familyLabel = (family ?? data.family ?? "sma").toUpperCase()
  const renderVariantGrid = (variants: SignalRepresentative[]) => (
    <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
      {variants.map((rep) => (
        <Card
          key={rep.variant_id}
          className="cursor-pointer hover:border-primary/50 transition-colors"
          onClick={() =>
            router.push(
              `/signals/variant/${rep.variant_id}?symbol=${encodeURIComponent(data.symbol)}&horizon=${data.horizon}&cooldown=${cooldownBars ?? 0}`
            )
          }
        >
          <CardContent className="p-3 flex flex-col items-center gap-1.5">
            <SignalBadge value={rep.signal} size="sm" />
            <div className="text-xs font-mono font-bold">
              {repLabel(rep)}
            </div>
            <div className="text-[10px] text-muted-foreground capitalize text-center">
              {(rep.archetype || "").replace(/_/g, " ")}
            </div>
            {rep.selection_status && rep.selection_status !== "selected" && (
              <Badge variant="outline" className="text-[9px]">
                Provisoire
              </Badge>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  )

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour
        </Button>
        <h3 className="text-sm font-bold">Famille {familyLabel} — Detail</h3>
      </div>

      {/* Funnel stats */}
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Entonnoir de selection</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="flex items-center gap-4 text-center">
            {[
              { label: "Testees", value: data.tested_count },
              { label: "Viables", value: data.viable_count },
              { label: "Competitives", value: data.competitive_count },
              { label: "Representatives", value: data.representative_count },
            ].map((step, i) => (
              <div key={step.label} className="flex items-center gap-2">
                {i > 0 && (
                  <span className="text-muted-foreground/40 text-lg">{"\u2192"}</span>
                )}
                <div>
                  <div className="text-lg font-bold">{step.value}</div>
                  <div className="text-[10px] text-muted-foreground">
                    {step.label}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Score explanation */}
      <div className="text-xs text-muted-foreground rounded-md border p-3 bg-muted/30">
        {data.score_explanation}
      </div>

      {data.is_provisional && data.warning_message && (
        <Card className="border-amber-300 bg-amber-50/60">
          <CardContent className="py-3 text-xs text-amber-900">
            <div className="font-semibold mb-1">Signal provisoire</div>
            <p>{data.warning_message}</p>
          </CardContent>
        </Card>
      )}

      {/* Representatives grid */}
      <div>
        <h4 className="text-xs font-semibold mb-3">
          Variantes representatives
          <Badge variant="outline" className="ml-2 text-[10px]">
            {data.representative_count}
          </Badge>
        </h4>
        {data.representative_count === 0 && data.fallback_variants.length === 0 ? (
          <Card>
            <CardContent className="py-6 text-center space-y-3">
              <p className="text-sm text-muted-foreground">
                Aucune variante representative stricte apres filtrage.
              </p>
              <p className="text-xs text-muted-foreground">{data.score_explanation}</p>
              {data.best_variant_id && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() =>
                    router.push(
                      `/signals/variant/${data.best_variant_id}?symbol=${encodeURIComponent(data.symbol)}&horizon=${data.horizon}&cooldown=${cooldownBars ?? 0}`
                    )
                  }
                >
                  Voir toutes les variantes
                </Button>
              )}
            </CardContent>
          </Card>
        ) : data.representative_count > 0 ? (
          renderVariantGrid(data.representatives)
        ) : null}
      </div>

      {data.fallback_variants.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold mb-3">
            Variantes provisoires
            <Badge variant="outline" className="ml-2 text-[10px] border-amber-300 text-amber-800">
              {data.fallback_variants.length}
            </Badge>
          </h4>
          <div className="text-[11px] text-muted-foreground mb-3">
            Ces variantes sont affichees avec les donnees disponibles, mais elles ne doivent pas etre traitees comme des representants robustes.
          </div>
          {renderVariantGrid(data.fallback_variants)}
        </div>
      )}
    </div>
  )
}
