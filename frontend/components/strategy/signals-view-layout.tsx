"use client"

import type { ReactNode } from "react"
import { Activity, BarChart3, Brain, LineChart, Settings, User } from "lucide-react"
import { HorizonSelector } from "@/components/strategy/horizon-selector"
import { PlaceholderTab } from "@/components/strategy/placeholder-tab"
import { StockSidebar } from "@/components/strategy/stock-sidebar"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

type SignalsViewLayoutProps = {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
  cooldownBars: number
  onCooldownBarsChange: (value: number) => void
  techniqueContent: ReactNode
  indicatorsContent: ReactNode
  wfoContent: ReactNode
}

export function SignalsViewLayout({
  selectedSymbol,
  onSelectSymbol,
  horizon,
  onHorizonChange,
  cooldownBars,
  onCooldownBarsChange,
  techniqueContent,
  indicatorsContent,
  wfoContent,
}: SignalsViewLayoutProps) {
  return (
    <div className="flex h-full overflow-hidden">
      <StockSidebar
        selectedSymbol={selectedSymbol}
        onSelect={onSelectSymbol}
        horizon={horizon}
        cooldownBars={cooldownBars}
        className="w-[280px] shrink-0"
      />

      <div className="flex-1 overflow-y-auto p-5">
        <div className="space-y-4">
          <div className="flex items-center justify-between gap-4">
            <h1 className="text-lg font-bold tracking-tight">
              {selectedSymbol ?? "Signaux"}
            </h1>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">Cooldown:</span>
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={cooldownBars}
                  onChange={(event) =>
                    onCooldownBarsChange(Math.max(0, Number(event.target.value) || 0))
                  }
                  className="w-14 rounded border border-border bg-background px-2 py-1 text-xs font-mono"
                />
                <span className="text-xs text-muted-foreground">bars</span>
              </div>
              <HorizonSelector value={horizon} onChange={onHorizonChange} />
            </div>
          </div>

          <Tabs defaultValue="technique">
            <TabsList>
              <TabsTrigger value="technique" className="gap-1.5 text-xs">
                <Activity className="h-3.5 w-3.5" />
                Analyse Technique
              </TabsTrigger>
              <TabsTrigger value="fondamentale" className="gap-1.5 text-xs" disabled>
                <BarChart3 className="h-3.5 w-3.5" />
                Fondamentale
              </TabsTrigger>
              <TabsTrigger value="quantitative" className="gap-1.5 text-xs" disabled>
                <Brain className="h-3.5 w-3.5" />
                Quantitative
              </TabsTrigger>
              <TabsTrigger value="personnelle" className="gap-1.5 text-xs" disabled>
                <User className="h-3.5 w-3.5" />
                Personnelle
              </TabsTrigger>
            </TabsList>

            <TabsContent value="technique" className="mt-4">
              <Tabs defaultValue="signaux">
                <TabsList className="h-8">
                  <TabsTrigger value="signaux" className="gap-1.5 text-xs h-7">
                    <Activity className="h-3 w-3" />
                    Signaux
                  </TabsTrigger>
                  <TabsTrigger
                    value="indicateurs"
                    className="gap-1.5 text-xs h-7"
                    disabled={!selectedSymbol}
                  >
                    <LineChart className="h-3 w-3" />
                    Indicateurs
                  </TabsTrigger>
                  <TabsTrigger
                    value="wfo"
                    className="gap-1.5 text-xs h-7"
                    disabled={!selectedSymbol}
                  >
                    <Settings className="h-3 w-3" />
                    WFO
                  </TabsTrigger>
                </TabsList>

                <TabsContent value="signaux" className="mt-3">
                  {techniqueContent}
                </TabsContent>

                <TabsContent value="indicateurs" className="mt-3">
                  {indicatorsContent}
                </TabsContent>

                <TabsContent value="wfo" className="mt-3">
                  {wfoContent}
                </TabsContent>
              </Tabs>
            </TabsContent>

            <TabsContent value="fondamentale" className="mt-4">
              <PlaceholderTab title="Analyse Fondamentale" />
            </TabsContent>

            <TabsContent value="quantitative" className="mt-4">
              <PlaceholderTab title="Analyse Quantitative" />
            </TabsContent>

            <TabsContent value="personnelle" className="mt-4">
              <PlaceholderTab title="Analyse Personnelle" />
            </TabsContent>
          </Tabs>
        </div>
      </div>
    </div>
  )
}
