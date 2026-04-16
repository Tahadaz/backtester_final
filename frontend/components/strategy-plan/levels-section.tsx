"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { ChevronDown, Layers } from "lucide-react"
import { cn } from "@/lib/utils"
import { useState } from "react"
import type { LevelsResult, SRLevel } from "@/lib/api"

interface LevelsSectionProps {
  symbol: string
  levels: LevelsResult | undefined
  isLoading: boolean
}

function LevelRow({ level, type }: { level: SRLevel; type: "support" | "resistance" }) {
  const color = type === "support" ? "text-green-600" : "text-red-600"
  const bgColor = type === "support" ? "bg-green-50" : "bg-red-50"
  return (
    <TableRow className={bgColor}>
      <TableCell className={cn("text-xs font-mono font-semibold py-1.5", color)}>
        {level.price.toFixed(2)}
      </TableCell>
      <TableCell className="text-xs py-1.5 capitalize">
        {type === "support" ? "Support" : "Résistance"}
      </TableCell>
      <TableCell className="text-xs py-1.5 text-muted-foreground">
        {level.date ?? "—"}
      </TableCell>
      <TableCell className="text-xs text-center py-1.5">
        <Badge variant="outline" className="text-[10px] font-mono px-1.5 py-0">
          {level.strength}
        </Badge>
      </TableCell>
    </TableRow>
  )
}

export function LevelsSection({ symbol, levels, isLoading }: LevelsSectionProps) {
  const [open, setOpen] = useState(true)

  const allLevels = [
    ...(levels?.resistances.map((r) => ({ ...r, type: "resistance" as const })) ?? []),
    ...(levels?.supports.map((s) => ({ ...s, type: "support" as const })) ?? []),
  ].sort((a, b) => b.price - a.price)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CollapsibleTrigger className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
              <Layers className="h-3.5 w-3.5 text-muted-foreground" />
              <CardTitle className="text-xs font-semibold">
                Supports & Résistances — {symbol}
              </CardTitle>
              {levels && (
                <Badge variant="secondary" className="text-[10px] font-mono">
                  {levels.supports.length}S / {levels.resistances.length}R
                </Badge>
              )}
            </div>
            <ChevronDown
              className={cn(
                "h-4 w-4 text-muted-foreground transition-transform",
                open && "rotate-180"
              )}
            />
          </CollapsibleTrigger>
        </CardHeader>

        <CollapsibleContent>
          <CardContent className="px-4 pb-4">
            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : levels ? (
              <div className="space-y-4">
                {/* Current price + ATR */}
                <div className="flex items-center gap-4 text-xs">
                  <span>
                    <span className="text-muted-foreground">Cours actuel:</span>{" "}
                    <span className="font-mono font-semibold">
                      {levels.current_close.toFixed(2)}
                    </span>
                  </span>
                  {levels.atr_14 != null && (
                    <span>
                      <span className="text-muted-foreground">ATR(14):</span>{" "}
                      <span className="font-mono">
                        {levels.atr_14.toFixed(2)} ({((levels.atr_pct ?? 0) * 100).toFixed(2)}%)
                      </span>
                    </span>
                  )}
                </div>

                {/* Levels table */}
                {allLevels.length > 0 ? (
                  <div className="rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-[10px] w-[100px]">Prix</TableHead>
                          <TableHead className="text-[10px]">Type</TableHead>
                          <TableHead className="text-[10px]">Date</TableHead>
                          <TableHead className="text-[10px] text-center">Force</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {allLevels.map((level, i) => (
                          <LevelRow key={i} level={level} type={level.type} />
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Aucun niveau S/R détecté sur la période analysée.
                  </p>
                )}

                {/* Pivot points */}
                {levels.pivot && (
                  <div className="space-y-1">
                    <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                      Pivots (session précédente)
                    </span>
                    <div className="flex flex-wrap gap-3 text-xs">
                      <span>
                        <span className="text-red-500">R2:</span>{" "}
                        <span className="font-mono">{levels.pivot.r2.toFixed(2)}</span>
                      </span>
                      <span>
                        <span className="text-red-400">R1:</span>{" "}
                        <span className="font-mono">{levels.pivot.r1.toFixed(2)}</span>
                      </span>
                      <span>
                        <span className="text-muted-foreground">PP:</span>{" "}
                        <span className="font-mono font-semibold">{levels.pivot.pp.toFixed(2)}</span>
                      </span>
                      <span>
                        <span className="text-green-400">S1:</span>{" "}
                        <span className="font-mono">{levels.pivot.s1.toFixed(2)}</span>
                      </span>
                      <span>
                        <span className="text-green-500">S2:</span>{" "}
                        <span className="font-mono">{levels.pivot.s2.toFixed(2)}</span>
                      </span>
                    </div>
                  </div>
                )}

                {/* Explanation */}
                {levels.explain && (
                  <p className="text-[10px] text-muted-foreground italic">
                    {levels.explain}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Sélectionnez un titre pour voir les niveaux.
              </p>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
