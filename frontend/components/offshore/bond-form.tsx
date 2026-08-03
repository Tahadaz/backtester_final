"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export type BondRequest = { bond: { face_value: number; currency: string; coupon_rate: number; coupon_frequency: 1 | 2; maturity_date: string; day_count: "30E/360" | "ACT/ACT-ICMA" | "ACT/365F"; redemption: number }; settlement_date: string; quote: { type: "yield" | "clean_price" | "dirty_price"; value: number }; notional: number }

export function BondForm({ onSubmit, loading }: { onSubmit: (request: BondRequest) => void; loading: boolean }) {
  const [request, setRequest] = useState<BondRequest>({ bond: { face_value: 100, currency: "USD", coupon_rate: 0.06, coupon_frequency: 2, maturity_date: "2031-07-15", day_count: "30E/360", redemption: 100 }, settlement_date: "2026-07-15", quote: { type: "yield", value: 0.04 }, notional: 1_000_000 })
  const bond = request.bond
  return <Card><CardHeader><CardTitle>Paramètres de l&apos;obligation</CardTitle></CardHeader><CardContent><form className="grid gap-4 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); onSubmit(request) }}>
    <Field label="Devise (ISO)"><Input value={bond.currency} onChange={(event) => setRequest({ ...request, bond: { ...bond, currency: event.target.value.toUpperCase() } })}/></Field>
    <Field label="Notional (devise)"><Input type="number" value={request.notional} onChange={(event) => setRequest({ ...request, notional: Number(event.target.value) })}/></Field>
    <Field label="Coupon (% p.a.)"><Input type="number" step="0.01" value={bond.coupon_rate * 100} onChange={(event) => setRequest({ ...request, bond: { ...bond, coupon_rate: Number(event.target.value) / 100 } })}/></Field>
    <Field label="Fréquence (paiements/an)"><select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={bond.coupon_frequency} onChange={(event) => setRequest({ ...request, bond: { ...bond, coupon_frequency: Number(event.target.value) as 1 | 2 } })}><option value={1}>1 — annuel</option><option value={2}>2 — semiannuel</option></select></Field>
    <Field label="Maturité"><Input type="date" value={bond.maturity_date} onChange={(event) => setRequest({ ...request, bond: { ...bond, maturity_date: event.target.value } })}/></Field>
    <Field label="Settlement"><Input type="date" value={request.settlement_date} onChange={(event) => setRequest({ ...request, settlement_date: event.target.value })}/></Field>
    <Field label="Day count"><select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={bond.day_count} onChange={(event) => setRequest({ ...request, bond: { ...bond, day_count: event.target.value as BondRequest["bond"]["day_count"] } })}><option>30E/360</option><option>ACT/ACT-ICMA</option><option>ACT/365F</option></select></Field>
    <Field label="Type de quote"><select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={request.quote.type} onChange={(event) => setRequest({ ...request, quote: { ...request.quote, type: event.target.value as BondRequest["quote"]["type"] } })}><option value="yield">Yield</option><option value="clean_price">Clean price</option><option value="dirty_price">Dirty price</option></select></Field>
    <Field label={request.quote.type === "yield" ? "Yield (% p.a.)" : "Prix (par 100)"}><Input type="number" step="0.0001" value={request.quote.type === "yield" ? request.quote.value * 100 : request.quote.value} onChange={(event) => setRequest({ ...request, quote: { ...request.quote, value: request.quote.type === "yield" ? Number(event.target.value) / 100 : Number(event.target.value) } })}/></Field>
    <div className="flex items-end"><Button type="submit" disabled={loading}>{loading ? "Calcul…" : "Calculer analytics et scénarios"}</Button></div>
  </form></CardContent></Card>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) { return <div className="space-y-1.5"><Label>{label}</Label>{children}</div> }
