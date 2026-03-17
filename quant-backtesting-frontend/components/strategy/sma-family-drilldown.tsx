"use client"

import type { FamilyCombinedSignal, SignalRepresentative } from "@/lib/api"
import { Speedometer } from "./speedometer"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ArrowLeft } from "lucide-react"

export function SmaFamilyDrilldown({
  data,
  onBack,
  onSelectVariant,
}: {
  data: FamilyCombinedSignal
  onBack: () => void
  onSelectVariant: (v: SignalRepresentative) => void
}) {
  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour
        </Button>
        <h3 className="text-sm font-bold">Famille SMA — Détail</h3>
      </div>

      {/* Funnel stats */}
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CardTitle className="text-xs font-semibold">Entonnoir de sélection</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="flex items-center gap-4 text-center">
            {[
              { label: "Testées", value: data.tested_count },
              { label: "Viables", value: data.viable_count },
              { label: "Compétitives", value: data.competitive_count },
              { label: "Représentatives", value: data.representative_count },
            ].map((step, i) => (
              <div key={step.label} className="flex items-center gap-2">
                {i > 0 && (
                  <span className="text-muted-foreground/40 text-lg">→</span>
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

      {/* Representatives grid */}
      <div>
        <h4 className="text-xs font-semibold mb-3">
          Variantes représentatives
          <Badge variant="outline" className="ml-2 text-[10px]">
            {data.representative_count}
          </Badge>
        </h4>
        <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
          {data.representatives.map((rep) => {
            const pct =
              rep.signal > 0
                ? 50 + rep.contribution * 50
                : rep.signal < 0
                  ? 50 - rep.contribution * 50
                  : 50
            return (
              <Card
                key={rep.variant_id}
                className="cursor-pointer hover:border-primary/50 transition-colors"
                onClick={() => onSelectVariant(rep)}
              >
                <CardContent className="p-3 flex flex-col items-center gap-2">
                  <Speedometer value={pct} size="sm" />
                  <div className="text-center">
                    <div className="text-[10px] font-mono font-semibold truncate max-w-[120px]">
                      {rep.variant_id}
                    </div>
                    <Badge
                      variant="outline"
                      className={`text-[9px] mt-1 ${
                        rep.signal > 0
                          ? "text-green-700 border-green-300"
                          : rep.signal < 0
                            ? "text-red-700 border-red-300"
                            : "text-muted-foreground"
                      }`}
                    >
                      {rep.signal_label}
                    </Badge>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      </div>
    </div>
  )
}
