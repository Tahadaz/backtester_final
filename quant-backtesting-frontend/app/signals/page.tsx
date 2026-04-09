"use client"

import { useState } from "react"
import { StockSidebar } from "@/components/strategy/stock-sidebar"
import { HorizonSelector } from "@/components/strategy/horizon-selector"
import { IndicatorExplorer } from "@/components/strategy/indicator-explorer"
import { TechnicalAnalysisPanel } from "@/components/strategy/technical-analysis-panel"
import { PlaceholderTab } from "@/components/strategy/placeholder-tab"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Activity, BarChart3, Brain, LineChart, User } from "lucide-react"

export default function SignalsPage() {
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [horizon, setHorizon] = useState("short")
  const [cooldownBars, setCooldownBars] = useState(0)

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)] overflow-hidden">
      {/* Left sidebar — stock list */}
      <StockSidebar
        selectedSymbol={selectedSymbol}
        onSelect={setSelectedSymbol}
        horizon={horizon}
        cooldownBars={cooldownBars}
        className="w-[280px] shrink-0"
      />

      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-5">
        <div className="space-y-4">
          {/* Header row: symbol + horizon */}
          <div className="flex items-center justify-between">
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
                  onChange={(e) => setCooldownBars(Math.max(0, Number(e.target.value) || 0))}
                  className="w-14 rounded border border-border bg-background px-2 py-1 text-xs font-mono"
                />
                <span className="text-xs text-muted-foreground">bars</span>
              </div>
              <HorizonSelector value={horizon} onChange={setHorizon} />
            </div>
          </div>

          {/* Analysis tabs — always visible */}
          <Tabs defaultValue="technique">
            <TabsList>
              <TabsTrigger value="technique" className="gap-1.5 text-xs">
                <Activity className="h-3.5 w-3.5" />
                Analyse Technique
              </TabsTrigger>
              <TabsTrigger value="indicateurs" className="gap-1.5 text-xs" disabled={!selectedSymbol}>
                <LineChart className="h-3.5 w-3.5" />
                Indicateurs
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
              {selectedSymbol ? (
                <TechnicalAnalysisPanel symbol={selectedSymbol} horizon={horizon} cooldownBars={cooldownBars} />
              ) : (
                <div className="flex h-[300px] items-center justify-center">
                  <div className="text-center space-y-2">
                    <Activity className="h-10 w-10 text-muted-foreground/30 mx-auto" />
                    <p className="text-sm text-muted-foreground">
                      Selectionnez un titre pour afficher l&apos;analyse
                    </p>
                  </div>
                </div>
              )}
            </TabsContent>

            <TabsContent value="indicateurs" className="mt-4">
              {selectedSymbol ? (
                <IndicatorExplorer symbol={selectedSymbol} />
              ) : (
                <div className="flex h-[300px] items-center justify-center">
                  <div className="text-center space-y-2">
                    <LineChart className="h-10 w-10 text-muted-foreground/30 mx-auto" />
                    <p className="text-sm text-muted-foreground">
                      Selectionnez un titre pour afficher les indicateurs
                    </p>
                  </div>
                </div>
              )}
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
