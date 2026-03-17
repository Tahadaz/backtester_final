"use client"

import { useState } from "react"
import { StockSidebar } from "@/components/strategy/stock-sidebar"
import { HorizonSelector } from "@/components/strategy/horizon-selector"
import { TechnicalAnalysisPanel } from "@/components/strategy/technical-analysis-panel"
import { PlaceholderTab } from "@/components/strategy/placeholder-tab"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Activity, BarChart3, Brain, User } from "lucide-react"

export default function SignalsPage() {
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [horizon, setHorizon] = useState("medium")

  return (
    <div className="flex h-[calc(100vh-3.5rem-3rem)]">
      {/* Left sidebar — stock list */}
      <StockSidebar
        selectedSymbol={selectedSymbol}
        onSelect={setSelectedSymbol}
        className="w-[280px] shrink-0"
      />

      {/* Main content */}
      <div className="flex-1 overflow-y-auto p-5">
        {!selectedSymbol ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center space-y-2">
              <Activity className="h-10 w-10 text-muted-foreground/30 mx-auto" />
              <h2 className="text-sm font-semibold text-muted-foreground">
                Sélectionnez un titre
              </h2>
              <p className="text-xs text-muted-foreground/60">
                Choisissez un titre dans la liste pour afficher les signaux
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {/* Header row: symbol + horizon */}
            <div className="flex items-center justify-between">
              <h1 className="text-lg font-bold tracking-tight">
                {selectedSymbol}
              </h1>
              <HorizonSelector value={horizon} onChange={setHorizon} />
            </div>

            {/* Analysis tabs */}
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
                <TechnicalAnalysisPanel symbol={selectedSymbol} horizon={horizon} />
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
        )}
      </div>
    </div>
  )
}
