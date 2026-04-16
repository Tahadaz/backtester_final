"use client"

import { Activity, AlertCircle, BarChart3, TrendingUp } from "lucide-react"
import { formatNumber } from "@/lib/format"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import type {
  LegacyIndicatorExplorerState,
  LegacyIndicatorFamilyKey,
} from "@/components/strategy/legacy-indicator-explorer"

type LegacyIndicatorSidebarProps = {
  families: LegacyIndicatorExplorerState
  onToggle: (family: LegacyIndicatorFamilyKey, enabled: boolean) => void
  onParamChange: (family: LegacyIndicatorFamilyKey, key: string, value: number) => void
}

type FamilyMeta = {
  key: LegacyIndicatorFamilyKey
  title: string
  description: string
  icon: typeof TrendingUp
  params: Array<{
    key: string
    label: string
    min: number
    max: number
    step: number
  }>
}

const FAMILY_META: FamilyMeta[] = [
  {
    key: "sma",
    title: "Tendance (SMA)",
    description: "Distance normalisee au-dessus ou en dessous de la moyenne mobile.",
    icon: TrendingUp,
    params: [{ key: "period", label: "Periode", min: 5, max: 500, step: 1 }],
  },
  {
    key: "macd",
    title: "Momentum (MACD)",
    description: "Acceleration du mouvement a travers l'histogramme MACD.",
    icon: Activity,
    params: [
      { key: "fast", label: "Fast", min: 2, max: 100, step: 1 },
      { key: "slow", label: "Slow", min: 5, max: 200, step: 1 },
      { key: "signal", label: "Signal", min: 2, max: 50, step: 1 },
    ],
  },
  {
    key: "rsi",
    title: "Oscillation (RSI)",
    description: "Lecture directe de l'oscillateur de Wilder entre 0 et 100.",
    icon: Activity,
    params: [
      { key: "period", label: "Periode", min: 2, max: 200, step: 1 },
      { key: "oversold", label: "Survendu", min: 0, max: 50, step: 1 },
      { key: "overbought", label: "Surachete", min: 50, max: 100, step: 1 },
    ],
  },
  {
    key: "obv",
    title: "Volume (OBV)",
    description: "Deviation de l'OBV par rapport a sa moyenne exponentielle.",
    icon: BarChart3,
    params: [{ key: "ema_period", label: "EMA", min: 5, max: 100, step: 1 }],
  },
]

function labelBadgeClass(label: string): string {
  const lower = label.toLowerCase()
  if (lower.includes("haussier") || lower.includes("survendu") || lower.includes("accumulation")) {
    return "border-green-300 text-green-700"
  }
  if (lower.includes("baissier") || lower.includes("surachet") || lower.includes("distribution")) {
    return "border-red-300 text-red-700"
  }
  return "text-muted-foreground"
}

export function LegacyIndicatorSidebar({
  families,
  onToggle,
  onParamChange,
}: LegacyIndicatorSidebarProps) {
  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Indicateurs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Accordion
          type="multiple"
          defaultValue={FAMILY_META.map((family) => family.key)}
          className="w-full"
        >
          {FAMILY_META.map((family) => {
            const Icon = family.icon
            const state = families[family.key]
            return (
              <AccordionItem value={family.key} key={family.key}>
                <AccordionTrigger className="py-3">
                  <div className="flex min-w-0 items-start gap-2 text-left">
                    <Icon className="mt-0.5 h-4 w-4 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <span>{family.title}</span>
                        {state.enabled ? (
                          <Badge variant="outline" className="text-[10px]">
                            Actif
                          </Badge>
                        ) : null}
                      </div>
                      <p className="mt-1 text-xs font-normal text-muted-foreground">
                        {family.description}
                      </p>
                    </div>
                  </div>
                </AccordionTrigger>
                <AccordionContent className="space-y-4">
                  <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                    <div>
                      <p className="text-sm font-medium">Afficher</p>
                      <p className="text-xs text-muted-foreground">
                        Active ou masque cet indicateur
                      </p>
                    </div>
                    <Switch
                      checked={state.enabled}
                      onCheckedChange={(checked) => onToggle(family.key, checked)}
                    />
                  </div>

                  {family.params.map((param) => {
                    const value = Number(state.params[param.key] ?? param.min)
                    return (
                      <div key={param.key} className="space-y-2">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-medium">{param.label}</span>
                          <span className="font-mono text-muted-foreground">{value}</span>
                        </div>
                        <Slider
                          min={param.min}
                          max={param.max}
                          step={param.step}
                          value={[value]}
                          onValueChange={(values) =>
                            onParamChange(family.key, param.key, values[0] ?? value)
                          }
                        />
                      </div>
                    )
                  })}

                  {state.enabled && state.data ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="font-mono">
                        {formatNumber(state.data.current_score, 2)}
                      </Badge>
                      <Badge variant="outline" className={labelBadgeClass(state.data.current_label)}>
                        {state.data.current_label}
                      </Badge>
                    </div>
                  ) : null}

                  {state.loading ? (
                    <p className="text-xs text-muted-foreground">Actualisation de l'indicateur...</p>
                  ) : null}

                  {state.error ? (
                    <Alert variant="destructive">
                      <AlertCircle className="h-4 w-4" />
                      <AlertDescription>{state.error}</AlertDescription>
                    </Alert>
                  ) : null}
                </AccordionContent>
              </AccordionItem>
            )
          })}
        </Accordion>
      </CardContent>
    </Card>
  )
}
