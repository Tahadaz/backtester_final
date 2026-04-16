"use client"

import { Activity, AlertCircle, BarChart3, TrendingUp } from "lucide-react"
import { formatNumber } from "@/lib/format"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import {
  INDICATOR_FAMILY_META,
  type IndicatorFamilyKey,
} from "./indicator-config"
import type { IndicatorExplorerState } from "./indicator-explorer"

type IndicatorSidebarProps = {
  families: IndicatorExplorerState
  onToggle: (family: IndicatorFamilyKey, enabled: boolean) => void
  onParamChange: (family: IndicatorFamilyKey, key: string, value: number) => void
}

const CATEGORY_ICON = {
  tendance: TrendingUp,
  momentum: Activity,
  oscillation: Activity,
  volume: BarChart3,
} as const

function labelBadgeClass(label: string): string {
  const lower = label.toLowerCase()
  if (
    lower.includes("haussier") ||
    lower.includes("survendu") ||
    lower.includes("accumulation")
  ) {
    return "border-green-300 text-green-700"
  }
  if (
    lower.includes("baissier") ||
    lower.includes("surachet") ||
    lower.includes("distribution")
  ) {
    return "border-red-300 text-red-700"
  }
  return "text-muted-foreground"
}

export function IndicatorSidebar({
  families,
  onToggle,
  onParamChange,
}: IndicatorSidebarProps) {
  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Indicateurs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Accordion
          type="multiple"
          defaultValue={INDICATOR_FAMILY_META.map((family) => family.key)}
          className="w-full"
        >
          {INDICATOR_FAMILY_META.map((family) => {
            const Icon = CATEGORY_ICON[family.category]
            const state = families[family.key]
            return (
              <AccordionItem value={family.key} key={family.key}>
                <AccordionTrigger className="py-3">
                  <div className="flex min-w-0 items-start gap-2 text-left">
                    <Icon className="mt-0.5 h-4 w-4 text-muted-foreground" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <span>{family.title}</span>
                        <Badge variant="outline" className="text-[10px]">
                          {family.category}
                        </Badge>
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
                          <span className="font-mono text-muted-foreground">
                            {param.step < 1 ? formatNumber(value, 3) : value}
                          </span>
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
