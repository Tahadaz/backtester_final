"use client"

import { useState } from "react"
import { BondAnalyticsPanel } from "@/components/offshore/bond-analytics-panel"
import { BondForm, type BondRequest } from "@/components/offshore/bond-form"
import { CashflowTable } from "@/components/offshore/cashflow-table"
import { InterpretationBlock } from "@/components/offshore/interpretation-block"
import { ShockScenarioTable } from "@/components/offshore/shock-scenario-table"
import { calculateBondAnalytics, calculateBondScenarios, type OffshoreLabEnvelope } from "@/lib/api"

function records(value: unknown): Array<Record<string, unknown>> { return Array.isArray(value) ? value.filter((item)=>item && typeof item === "object") as Array<Record<string, unknown>> : [] }

export default function OffshoreLabPage() {
  const [analytics,setAnalytics]=useState<OffshoreLabEnvelope|null>(null)
  const [scenarios,setScenarios]=useState<OffshoreLabEnvelope|null>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState<string|null>(null)
  const submit=async(request:BondRequest)=>{setLoading(true);setError(null);try{const [a,s]=await Promise.all([calculateBondAnalytics(request as unknown as Record<string,unknown>),calculateBondScenarios({...request,shocks_bp:[-100,-50,-25,0,25,50,100],holding_period_days:30} as unknown as Record<string,unknown>)]);setAnalytics(a);setScenarios(s)}catch(caught){setError(caught instanceof Error?caught.message:"Calcul impossible")}finally{setLoading(false)}}
  const results=analytics?.results??{}
  const scenarioResults=scenarios?.results??{}
  return <main className="mx-auto max-w-7xl space-y-6 px-4 py-8 md:px-8"><header><p className="text-sm font-medium text-primary">Offshore Markets Lab</p><h1 className="text-3xl font-semibold">Calculateur obligataire</h1><p className="mt-2 text-sm text-muted-foreground">Fixed-rate bullet bond — price, YTM, duration, convexity, DV01, cash flows, shocks et carry.</p></header>{error&&<div className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</div>}<BondForm onSubmit={submit} loading={loading}/><BondAnalyticsPanel results={results}/><div className="grid gap-6 lg:grid-cols-2"><CashflowTable rows={records(results.cashflows)}/><ShockScenarioTable rows={records(scenarioResults.shock_table ?? results.shock_table)}/></div><InterpretationBlock methodology={analytics?.methodology} assumptions={analytics?.assumptions} warnings={analytics?.warnings} interpretation={analytics?.interpretation}/></main>
}
