"use client"

import { useMemo } from "react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  AlertTriangle, ArrowUpRight, ArrowDownRight, Minus,
  TrendingUp, TrendingDown, Target, Shield, Zap, BookOpen,
} from "lucide-react"
import type { DecisionDashboard, StrategyDecision } from "@/lib/api"
import { formatNumber } from "@/lib/format"

// ─── helpers ─────────────────────────────────────────────────

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function fmt(value: unknown, digits = 2): string {
  const num = toNumber(value)
  if (num !== null) return formatNumber(num, digits)
  if (typeof value === "boolean") return value ? "OUI" : "NON"
  if (value === null || value === undefined) return "—"
  if (typeof value === "string") return value || "—"
  try { return JSON.stringify(value) } catch { return String(value) }
}

function fmtPct(value: unknown): string {
  const num = toNumber(value)
  if (num === null) return "—"
  return `${formatNumber(num * 100, 2)}%`
}

// ─── sub-components ───────────────────────────────────────────

function ScoreBar({ score, label, color }: { score: number | null | undefined; label: string; color: string }) {
  const v = Math.min(100, Math.max(0, score ?? 0))
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-semibold">{score != null ? formatNumber(score, 1) : "—"} / 100</span>
      </div>
      <div className="h-2 rounded-full bg-secondary overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${v}%` }} />
      </div>
    </div>
  )
}

function DecisionBadge({ direction }: { direction: string }) {
  const d = direction.toLowerCase()
  const map: Record<string, { label: string; className: string; Icon: React.ElementType }> = {
    long:    { label: "ACHAT",   className: "bg-emerald-100 text-emerald-800 border-emerald-200", Icon: ArrowUpRight },
    short:   { label: "VENTE",   className: "bg-rose-100    text-rose-800    border-rose-200",    Icon: ArrowDownRight },
    neutral: { label: "NEUTRE",  className: "bg-slate-100   text-slate-700   border-slate-200",   Icon: Minus },
    observe: { label: "OBSERVE", className: "bg-amber-100   text-amber-800   border-amber-200",   Icon: Target },
  }
  const cfg = map[d] ?? map.neutral
  return (
    <Badge className={`flex items-center gap-1.5 text-sm font-bold px-3 py-1 border ${cfg.className}`}>
      <cfg.Icon className="h-4 w-4" />
      {cfg.label}
    </Badge>
  )
}

function StatusBadge({ status }: { status: string }) {
  const s = status.toLowerCase()
  const cfg =
    s === "trade" ? { label: "TRADE", className: "bg-emerald-100 text-emerald-800 border-emerald-200" } :
    s === "watch" ? { label: "SURVEILLER", className: "bg-amber-100 text-amber-800 border-amber-200" } :
    { label: s.toUpperCase(), className: "bg-slate-100 text-slate-700 border-slate-200" }
  return <Badge className={`text-xs font-semibold border ${cfg.className}`}>{cfg.label}</Badge>
}

function LevelRow({ label, value, color }: { label: string; value: unknown; color?: string }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`font-mono text-sm font-semibold ${color ?? ""}`}>{fmt(value, 2)}</span>
    </div>
  )
}

// ─── main component ───────────────────────────────────────────

type Props = {
  decision: StrategyDecision
  dashboard: DecisionDashboard | null
  loading: boolean
}

export function DecisionDashboardView({ decision, dashboard, loading }: Props) {
  const levels = (dashboard?.levels ?? {}) as Record<string, unknown>
  const reasons = (dashboard?.decision_summary?.reasons as Array<Record<string, unknown>>) ?? []
  const confidenceLayers = (dashboard?.confidence_layers ?? []) as Array<Record<string, unknown>>
  const regimeChecks = (dashboard?.regime?.rule_checks as Array<Record<string, unknown>>) ?? []
  const frameworks = ((dashboard?.framework_comparison?.frameworks as Array<Record<string, unknown>>) ?? [])

  const direction = String(dashboard?.decision_summary?.direction ?? decision.decision_page?.direction ?? "neutral")
  const status = String(dashboard?.decision_summary?.status ?? decision.status ?? "watch")
  const rr = toNumber(dashboard?.decision_summary?.rr ?? decision.decision_page?.risk?.rr)
  const invalidation = String(decision.decision_page?.invalidation ?? dashboard?.decision_summary?.invalidation ?? "")
  const whenToAct = Array.isArray(decision.decision_page?.when_to_act) ? decision.decision_page.when_to_act : []
  const regimeLabel = String(dashboard?.regime?.label ?? "—")
  const horizonLabel = String(decision.decision_page?.trial_id ?? "").includes("medium")
    ? "Mensuel" : String(decision.decision_page?.trial_id ?? "").includes("long")
    ? "Trimestriel" : "Hebdomadaire"

  const chartData = useMemo(() => {
    if (!dashboard) return []
    const ts = dashboard.timeseries
    return ts.t.map((t, i) => ({
      t: t.slice(0, 10),
      close: toNumber(ts.close[i]),
      smaRef: toNumber(ts.sma_ref[i]),
      sma200: toNumber(ts.sma200[i]),
    }))
  }, [dashboard])

  // Scenario si/alors built from levels and direction
  const scenarioIfThen = useMemo(() => {
    const entry = toNumber(levels.entry)
    const stop = toNumber(levels.stop)
    const target = toNumber(levels.target)
    const sup = toNumber(levels.support)
    const res = toNumber(levels.resistance)
    const parts: string[] = []
    if (direction === "long" && entry) {
      parts.push(`Si le cours franchit ${fmt(entry, 2)} à la hausse → objectif ${fmt(target, 2)}, stop ${fmt(stop, 2)}.`)
    } else if (direction === "short" && entry) {
      parts.push(`Si le cours casse ${fmt(entry, 2)} à la baisse → objectif ${fmt(target, 2)}, stop ${fmt(stop, 2)}.`)
    }
    if (sup && res) {
      parts.push(`Support clé : ${fmt(sup, 2)} — Résistance : ${fmt(res, 2)}.`)
    }
    if (invalidation) {
      parts.push(`Invalidation : ${invalidation}.`)
    }
    return parts
  }, [levels, direction, invalidation])

  if (loading && !dashboard) {
    return (
      <Card className="border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Page de Décision</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (!dashboard) {
    return (
      <Card className="border-border">
        <CardContent className="py-8 text-sm text-muted-foreground">
          Données de décision non disponibles.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* ── SECTION A — Decision Box ───────────────────────────── */}
      <Card className="border-2 border-primary/20">
        <CardHeader className="pb-3 pt-4 px-4">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
            <Target className="h-3.5 w-3.5" />
            Section A — Décision
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-4">
          {/* Row 1: Decision + Status + Horizon */}
          <div className="flex items-center gap-3 flex-wrap">
            <DecisionBadge direction={direction} />
            <StatusBadge status={status} />
            <Badge variant="outline" className="text-xs">{horizonLabel}</Badge>
            <Badge variant="outline" className="text-xs font-normal">Régime : {regimeLabel}</Badge>
          </div>

          {/* Row 2: scores */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <ScoreBar
                score={toNumber(dashboard.decision_summary.opportunity) ?? decision.opportunity_score}
                label="Score d'opportunité"
                color="bg-amber-400"
              />
              <ScoreBar
                score={toNumber(dashboard.decision_summary.confidence) ?? decision.confidence_score}
                label="Score de confiance"
                color="bg-blue-400"
              />
            </div>
            <div className="rounded-lg border border-border p-3 space-y-1">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Ratio R/R</p>
              <p className="text-2xl font-bold font-mono">{rr != null ? formatNumber(rr, 2) : "—"}</p>
              {rr != null && (
                <p className={`text-xs font-medium ${rr >= 2 ? "text-emerald-600" : rr >= 1 ? "text-amber-600" : "text-red-600"}`}>
                  {rr >= 2 ? "Favorable" : rr >= 1 ? "Acceptable" : "Défavorable"}
                </p>
              )}
            </div>
          </div>

          {/* Row 3: Condition d'entrée + Invalidation */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <p className="text-[10px] font-bold uppercase tracking-wide text-emerald-700 mb-1">Condition d&apos;entrée</p>
              {whenToAct.length > 0 ? (
                <ul className="space-y-0.5">
                  {whenToAct.map((cond, i) => (
                    <li key={i} className="text-xs text-emerald-900">• {cond}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-emerald-800">
                  {direction === "long" ? "Signal haussier confirmé" : direction === "short" ? "Signal baissier confirmé" : "Pas de signal actif"}
                </p>
              )}
            </div>
            <div className="rounded-lg border border-red-200 bg-red-50 p-3">
              <p className="text-[10px] font-bold uppercase tracking-wide text-red-700 mb-1 flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" /> Invalidation
              </p>
              <p className="text-xs text-red-900">{invalidation || "—"}</p>
            </div>
          </div>

          {/* Row 4: Niveaux */}
          <div className="rounded-lg border border-border p-3">
            <p className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground mb-2">Niveaux clés</p>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {[
                { label: "Entrée", key: "entry", color: "text-amber-600" },
                { label: "Objectif", key: "target", color: "text-emerald-600" },
                { label: "Stop", key: "stop", color: "text-red-600" },
                { label: "Support", key: "support", color: "text-blue-600" },
                { label: "Résistance", key: "resistance", color: "text-orange-600" },
              ].map(({ label, key, color }) => (
                <div key={key} className="text-center rounded bg-secondary/40 p-2">
                  <p className="text-[10px] text-muted-foreground">{label}</p>
                  <p className={`font-mono text-sm font-bold ${color}`}>{fmt(levels[key], 2)}</p>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── SECTION B — Justification ─────────────────────────── */}
      <Card>
        <CardHeader className="pb-3 pt-4 px-4">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
            <BookOpen className="h-3.5 w-3.5" />
            Section B — Justification
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-3">
          {/* Top reasons */}
          {reasons.length > 0 ? (
            <div className="space-y-2">
              {reasons.slice(0, 5).map((r, idx) => {
                const score = toNumber(r.score)
                const isPositive = score != null && score > 0
                return (
                  <div key={idx} className="flex items-start gap-3 rounded-lg border border-border p-3">
                    <div className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                      isPositive ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"
                    }`}>
                      {isPositive ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-semibold">{fmt(r.name, 0)}</p>
                        <span className={`shrink-0 text-xs font-mono font-bold ${isPositive ? "text-emerald-600" : "text-slate-500"}`}>
                          {score != null ? (score > 0 ? "+" : "") + formatNumber(score, 1) : ""}
                        </span>
                      </div>
                      {Boolean(r.detail) && <p className="mt-0.5 text-xs text-muted-foreground">{fmt(r.detail, 0)}</p>}
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground italic">Justification automatique non disponible.</p>
          )}

          {/* Confidence layers decomposition */}
          {confidenceLayers.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1">
                <Shield className="h-3 w-3" /> Décomposition de la confiance
              </p>
              <div className="grid grid-cols-2 gap-2">
                {confidenceLayers.map((layer, idx) => {
                  const score = toNumber(layer.score)
                  return (
                    <div key={idx} className="rounded border border-border bg-secondary/20 p-2">
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="font-medium">{fmt(layer.name, 0)}</span>
                        <span className="font-mono font-bold">{score != null ? formatNumber(score, 1) : "—"}</span>
                      </div>
                      <div className="h-1.5 rounded-full bg-secondary overflow-hidden">
                        <div
                          className="h-full rounded-full bg-blue-400"
                          style={{ width: `${Math.min(100, Math.max(0, score ?? 0))}%` }}
                        />
                      </div>
                      {Boolean(layer.impact) && <p className="mt-1 text-[10px] text-muted-foreground">{fmt(layer.impact, 0)}</p>}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── SECTION C — Niveaux & Scénario ───────────────────── */}
      <Card>
        <CardHeader className="pb-3 pt-4 px-4">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
            <Zap className="h-3.5 w-3.5" />
            Section C — Niveaux &amp; Scénario
          </div>
        </CardHeader>
        <CardContent className="px-4 pb-4 space-y-4">
          {/* Levels detail */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground mb-2">Supports &amp; Résistances</p>
              <div className="rounded-lg border border-border divide-y divide-border">
                <LevelRow label="Résistance" value={levels.resistance} color="text-orange-600" />
                <LevelRow label="Entrée visée" value={levels.entry} color="text-amber-600" />
                <LevelRow label="Support" value={levels.support} color="text-blue-600" />
              </div>
            </div>
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground mb-2">Gestion du risque</p>
              <div className="rounded-lg border border-border divide-y divide-border">
                <LevelRow label="Objectif 1" value={levels.target} color="text-emerald-600" />
                <LevelRow label="Stop-loss" value={levels.stop} color="text-red-600" />
                <LevelRow label="R/R" value={rr} color={rr != null && rr >= 2 ? "text-emerald-600" : "text-amber-600"} />
              </div>
            </div>
          </div>

          {/* Regime checks */}
          {regimeChecks.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground mb-2">Contexte de marché (régime)</p>
              <div className="rounded-lg border border-border overflow-hidden">
                {regimeChecks.map((check, idx) => (
                  <div key={idx} className={`flex items-center justify-between px-3 py-2 text-xs border-b border-border/40 last:border-0 ${
                    check.pass ? "bg-emerald-50/50" : "bg-red-50/50"
                  }`}>
                    <span className="font-medium">{fmt(check.name, 0)}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-muted-foreground">{fmt(check.value)} vs {fmt(check.threshold)}</span>
                      <span>{check.pass ? "✅" : "❌"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Si/Alors scenario */}
          <div>
            <p className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground mb-2">Scénario si / alors</p>
            <div className="rounded-lg border border-border bg-secondary/20 p-3 space-y-2">
              {scenarioIfThen.length > 0 ? (
                scenarioIfThen.map((line, i) => (
                  <p key={i} className="text-xs leading-relaxed">{line}</p>
                ))
              ) : (
                <p className="text-xs text-muted-foreground italic">Scénario non disponible.</p>
              )}
            </div>
          </div>

          {/* Frameworks comparison */}
          {frameworks.length > 0 && (
            <div>
              <p className="text-[10px] font-bold uppercase tracking-wide text-muted-foreground mb-2">Comparaison des frameworks</p>
              <div className="rounded-lg border border-border overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-secondary/30">
                      <th className="px-3 py-2 text-left font-semibold">Stratégie</th>
                      <th className="px-3 py-2 text-left font-semibold">Direction</th>
                      <th className="px-3 py-2 text-right font-semibold">Opportunité</th>
                      <th className="px-3 py-2 text-right font-semibold">Confiance</th>
                      <th className="px-3 py-2 text-right font-semibold">R/R</th>
                    </tr>
                  </thead>
                  <tbody>
                    {frameworks.map((row, idx) => (
                      <tr key={idx} className="border-b border-border/40 hover:bg-secondary/20">
                        <td className="px-3 py-2">{fmt(row.strategy_kind, 0)}</td>
                        <td className="px-3 py-2 font-semibold">
                          <span className={
                            String(row.direction).toLowerCase() === "long" ? "text-emerald-600" :
                            String(row.direction).toLowerCase() === "short" ? "text-red-600" :
                            "text-muted-foreground"
                          }>{fmt(row.direction, 0).toUpperCase()}</span>
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{fmt(row.opportunity, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmt(row.confidence, 1)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmt(row.rr, 2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Strategy params (moved from old tab B) */}
      {dashboard.strategy_params?.length > 0 && (
        <Card>
          <CardHeader className="pb-3 pt-4 px-4">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Paramètres de stratégie
            </div>
          </CardHeader>
          <CardContent className="px-4 pb-4">
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {dashboard.strategy_params.map((row) => (
                <div key={row.key} className="rounded-lg border border-border bg-secondary/20 p-2">
                  <p className="font-mono text-xs font-semibold">{row.key}</p>
                  <p className="font-mono text-sm font-bold mt-0.5">{fmt(row.value)}</p>
                  {row.description && <p className="text-[10px] text-muted-foreground mt-1">{row.description}</p>}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
