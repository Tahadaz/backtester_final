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
import { ChevronDown, Filter } from "lucide-react"
import { cn } from "@/lib/utils"
import { useState } from "react"
import type { UniverseStock } from "@/lib/api"

interface UniverseSectionProps {
  stocks: UniverseStock[] | undefined
  isLoading: boolean
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
}

export function UniverseSection({
  stocks,
  isLoading,
  selectedSymbol,
  onSelect,
}: UniverseSectionProps) {
  const [open, setOpen] = useState(true)

  const eligible = stocks?.filter((s) => s.eligible) ?? []
  const total = stocks?.length ?? 0

  // Extract unique sectors
  const sectors = [...new Set(stocks?.map((s) => s.sector).filter(Boolean) ?? [])]

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card>
        <CardHeader className="pb-2 pt-3 px-4">
          <CollapsibleTrigger className="flex items-center justify-between w-full">
            <div className="flex items-center gap-2">
              <Filter className="h-3.5 w-3.5 text-muted-foreground" />
              <CardTitle className="text-xs font-semibold">
                Univers d&apos;investissement
              </CardTitle>
              <Badge variant="secondary" className="text-[10px] font-mono">
                {eligible.length}/{total}
              </Badge>
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
            {/* Sector chips */}
            {sectors.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-3">
                {sectors.map((sector) => (
                  <Badge
                    key={sector}
                    variant="outline"
                    className="text-[10px] cursor-default"
                  >
                    {sector}
                  </Badge>
                ))}
              </div>
            )}

            {isLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full" />
                ))}
              </div>
            ) : (
              <div className="rounded-md border max-h-[400px] overflow-y-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-[10px] w-[80px]">Ticker</TableHead>
                      <TableHead className="text-[10px]">Nom</TableHead>
                      <TableHead className="text-[10px] hidden md:table-cell">Secteur</TableHead>
                      <TableHead className="text-[10px] text-right">Score</TableHead>
                      <TableHead className="text-[10px] text-center">Statut</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stocks?.map((stock) => (
                      <TableRow
                        key={stock.symbol}
                        className={cn(
                          "cursor-pointer",
                          selectedSymbol === stock.symbol && "bg-primary/5",
                          !stock.eligible && "opacity-50"
                        )}
                        onClick={() => onSelect(stock.symbol)}
                      >
                        <TableCell className="text-xs font-mono font-bold py-1.5">
                          {stock.symbol}
                        </TableCell>
                        <TableCell className="text-xs py-1.5 truncate max-w-[120px]">
                          {stock.display_name ?? "—"}
                        </TableCell>
                        <TableCell className="text-xs py-1.5 hidden md:table-cell text-muted-foreground">
                          {stock.sector ?? "—"}
                        </TableCell>
                        <TableCell className="text-xs font-mono text-right py-1.5">
                          {stock.signal_score != null
                            ? `${stock.signal_score > 0 ? "+" : ""}${stock.signal_score.toFixed(1)}`
                            : "—"}
                        </TableCell>
                        <TableCell className="text-center py-1.5">
                          {stock.eligible ? (
                            <Badge className="bg-green-100 text-green-700 text-[9px] px-1.5 py-0">
                              Éligible
                            </Badge>
                          ) : (
                            <Badge className="bg-gray-100 text-gray-500 text-[9px] px-1.5 py-0">
                              Exclu
                            </Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
