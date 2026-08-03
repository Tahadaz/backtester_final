"use client"

import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { getCommodityCurve, type CrossAssetClass } from "@/lib/api"

const CURVE_DATE = "2025-01-02"
const COMMODITY_CURVE = [
  { instrument_id: "GC", date: CURVE_DATE, field: "settle", value: 2650, currency: "USD", contract_expiry: "2025-02-25", source: "fixture", volume: 1200 },
  { instrument_id: "GC", date: CURVE_DATE, field: "settle", value: 2642, currency: "USD", contract_expiry: "2025-04-25", source: "fixture", volume: 900 },
  { instrument_id: "GC", date: CURVE_DATE, field: "settle", value: 2638, currency: "USD", contract_expiry: "2025-06-25", source: "fixture", volume: 600 },
  { instrument_id: "GC", date: CURVE_DATE, field: "settle", value: 2630, currency: "USD", contract_expiry: "2025-08-25", source: "fixture", volume: 350 },
]

export function StrategyOverview({ assetClass, strategy }: { assetClass: CrossAssetClass; strategy?: Record<string, unknown> | null }) {
  const [curve, setCurve] = useState<Record<string, unknown> | null>(null)
  const [curveWarning, setCurveWarning] = useState<string | null>(null)
  useEffect(() => {
    if (assetClass !== "commodity") return
    getCommodityCurve(COMMODITY_CURVE, CURVE_DATE).then((response) => {
      setCurve(response.results && typeof response.results === "object" ? response.results as Record<string, unknown> : null)
      setCurveWarning(response.warnings[0] ?? null)
    }).catch((error) => setCurveWarning(error instanceof Error ? error.message : "Curve unavailable"))
  }, [assetClass])
  if (assetClass === "commodity") {
    const contracts = Array.isArray(curve?.contracts) ? curve.contracts as Array<Record<string, unknown>> : []
    const carry = curve?.carry && typeof curve.carry === "object" ? curve.carry as Record<string, unknown> : {}
    return <Card><CardHeader><CardTitle>Curve explorer — Commodities</CardTitle></CardHeader><CardContent className="space-y-4"><div className="flex gap-2"><Badge variant="outline">fixture</Badge><Badge variant="outline">raw, unadjusted</Badge><Badge variant="outline">non-tradable</Badge></div>{curveWarning && <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">{curveWarning}</div>}<PlotlyChart figure={{ data: [{ type: "scatter", mode: "lines+markers", x: contracts.map((item) => String(item.contract_expiry)), y: contracts.map((item) => Number(item.settle)), name: "Settle (USD/contract)" }, { type: "bar", x: COMMODITY_CURVE.map((item) => item.contract_expiry), y: COMMODITY_CURVE.map((item) => item.volume), name: "Volume (contracts)", yaxis: "y2", opacity: 0.25 }], layout: { xaxis: { title: { text: "Contract expiry" } }, yaxis: { title: { text: "USD/contract" } }, yaxis2: { title: { text: "contracts" }, overlaying: "y", side: "right" } } }}/><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-lg border p-3 text-sm">Front/second carry: {typeof carry.front_second === "number" ? `${(carry.front_second * 100).toFixed(2)}% annualisé` : "—"}</div><div className="rounded-lg border p-3 text-sm">Front/fourth carry: {typeof carry.front_fourth === "number" ? `${(carry.front_fourth * 100).toFixed(2)}% annualisé` : "—"}</div></div><p className="text-xs text-muted-foreground">Le carry est un forecast feature. Le P&amp;L réalisé vient uniquement des contrats effectivement détenus et roulés.</p></CardContent></Card>
  }
  if (assetClass === "rates") return <Card><CardHeader><CardTitle>Rates &amp; Bonds</CardTitle></CardHeader><CardContent className="space-y-3 text-sm"><div className="flex gap-2"><Badge variant="outline">FRED DGS2/5/10/30</Badge><Badge variant="outline">adapted</Badge><Badge variant="outline">model return</Badge></div><p>TSM et carry sur des constant-maturity par yields. Chaque return recompute modified duration et convexity à t−1 via le calculateur obligataire.</p><p className="text-muted-foreground">Le return est duration-approximated; il ne provient pas de prix de bonds ou futures effectivement tradés.</p></CardContent></Card>
  if (assetClass !== "fx") return <Empty assetClass={assetClass} />
  const fidelity = String(strategy?.replication_fidelity ?? "adapted")
  return (
    <Card><CardHeader><CardTitle>Thèse et source de recherche</CardTitle></CardHeader><CardContent className="space-y-3 text-sm">
      <div className="flex gap-2"><Badge>G10 vs USD</Badge><Badge variant="outline">{fidelity}</Badge><Badge variant="outline">Données réelles</Badge></div>
      <p>Deux réplications systématiques: Time-Series Momentum 12 mois et carry cross-sectionnel, ciblant 10% de volatilité annuelle.</p>
      <p className="text-muted-foreground">MOP / Koijen et al. — adaptation mensuelle avec taux directeurs FRED comme proxies. Les proxies ne sont pas des forwards tradables.</p>
    </CardContent></Card>
  )
}

function Empty({ assetClass }: { assetClass: CrossAssetClass }) {
  return <Card><CardContent className="py-12 text-center text-sm text-muted-foreground">{assetClass === "commodity" ? "Commodities" : "Rates & Bonds"}: activation prévue par le même composant, sans nouveau dossier UI.</CardContent></Card>
}
