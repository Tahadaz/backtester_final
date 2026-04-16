"use client"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useSizing } from "@/hooks/use-api"
import { Info } from "lucide-react"
import { cn } from "@/lib/utils"

interface SizingConfig {
  account_equity: number
  kelly_modifier: number
  allocation_method: string
  max_position_pct: number
  max_sector_pct: number
  win_rate: number
  avg_wl_ratio: number
}

interface StockInput {
  symbol: string
  entry_price: number
  stop_price: number
  atr_pct?: number
  consensus?: number
  sector?: string
  status?: string
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  entry_zone: { label: "Actif", cls: "bg-green-600 text-white" },
  watching: { label: "Sous seuil", cls: "bg-amber-500 text-white" },
  no_setup: { label: "Inactif", cls: "" },
  unfavorable_rr: { label: "R:R-", cls: "bg-red-100 text-red-700" },
}

function fmtNum(n: number | undefined | null, decimals = 0): string {
  if (n == null) return "—"
  return n.toLocaleString("fr-FR", { maximumFractionDigits: decimals })
}

export function SizingSection({
  focusedStock,
  basketStocks,
  sizingConfig,
  onConfigChange,
}: {
  focusedStock: string | null
  basketStocks: StockInput[]
  sizingConfig: SizingConfig
  onConfigChange: (patch: Partial<SizingConfig>) => void
}) {
  const sizingParams = basketStocks.length > 0
    ? {
        stocks: basketStocks,
        account_equity: sizingConfig.account_equity,
        kelly_modifier: sizingConfig.kelly_modifier,
        allocation_method: sizingConfig.allocation_method,
        max_position_pct: sizingConfig.max_position_pct,
        max_sector_pct: sizingConfig.max_sector_pct,
        win_rate: sizingConfig.win_rate,
        avg_wl_ratio: sizingConfig.avg_wl_ratio,
        focused_symbol: focusedStock,
      }
    : null

  const { data: sizing, isLoading } = useSizing(sizingParams)

  if (basketStocks.length === 0) {
    return (
      <div className="flex items-center gap-2 py-6 justify-center text-muted-foreground">
        <Info className="h-4 w-4 opacity-40" />
        <span className="text-xs">
          Ajoutez des titres au panier pour calculer le dimensionnement
        </span>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Methodology note */}
      <div className="rounded-md border bg-muted/20 p-3 space-y-1">
        <p className="text-[10px] text-muted-foreground">
          <span className="font-semibold text-foreground">Plafond individuel</span> — Kelly fractionnel limite la taille maximale par position selon l'edge estimé.
        </p>
        <p className="text-[10px] text-muted-foreground">
          <span className="font-semibold text-foreground">Allocation collective</span> — Le capital est réparti selon la méthode choisie (équipondéré, vol. inverse, signal).
        </p>
        <p className="text-[10px] text-muted-foreground">
          <span className="font-semibold text-foreground">Taille finale</span> — min(plafond Kelly, allocation du portefeuille).
        </p>
      </div>

      {/* Focused Kelly panel */}
      {focusedStock && sizing?.focused_kelly && (
        <div className="space-y-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Kelly — {focusedStock}
          </span>
          {isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <div className="grid grid-cols-3 gap-2 rounded-md border p-3">
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground">Kelly modifie</p>
                <p className="text-sm font-mono font-bold">
                  {sizing.focused_kelly.modified_kelly_pct.toFixed(1)}%
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground">Actions</p>
                <p className="text-sm font-mono font-bold">
                  {fmtNum(sizing.focused_kelly.position_size_shares)}
                </p>
              </div>
              <div className="text-center">
                <p className="text-[10px] text-muted-foreground">Risque</p>
                <p className="text-sm font-mono font-bold text-red-600">
                  {fmtNum(sizing.focused_kelly.trade_risk)} ({sizing.focused_kelly.pct_of_account_risked.toFixed(1)}%)
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Allocation config */}
      <div className="space-y-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Configuration
        </span>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1">
            <Label className="text-[10px]">Capital (MAD)</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={sizingConfig.account_equity}
              onChange={(e) => onConfigChange({ account_equity: Number(e.target.value) })}
              min={0}
              step={100000}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Methode</Label>
            <Select
              value={sizingConfig.allocation_method}
              onValueChange={(v) => onConfigChange({ allocation_method: v })}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="equal_weight">Equipondere</SelectItem>
                <SelectItem value="inverse_volatility">Vol. inverse</SelectItem>
                <SelectItem value="signal_weighted">Signal</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Kelly</Label>
            <Select
              value={String(sizingConfig.kelly_modifier)}
              onValueChange={(v) => onConfigChange({ kelly_modifier: Number(v) })}
            >
              <SelectTrigger className="h-7 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="1">Full (100%)</SelectItem>
                <SelectItem value="0.5">Demi (50%)</SelectItem>
                <SelectItem value="0.25">Quart (25%)</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Max position (%)</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={sizingConfig.max_position_pct}
              onChange={(e) => onConfigChange({ max_position_pct: Number(e.target.value) })}
              min={1}
              max={100}
              step={5}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-[10px]">Max secteur (%)</Label>
            <Input
              type="number"
              className="h-7 text-xs"
              value={sizingConfig.max_sector_pct}
              onChange={(e) => onConfigChange({ max_sector_pct: Number(e.target.value) })}
              min={1}
              max={100}
              step={5}
            />
          </div>
          <div className="col-span-2 grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <Label className="text-[10px]">Win rate (a calibrer)</Label>
              <Input
                type="number"
                className="h-7 text-xs"
                value={sizingConfig.win_rate}
                onChange={(e) => onConfigChange({ win_rate: Number(e.target.value) })}
                min={0.01}
                max={0.99}
                step={0.05}
              />
            </div>
            <div className="space-y-1">
              <Label className="text-[10px]">Ratio W/L (a calibrer)</Label>
              <Input
                type="number"
                className="h-7 text-xs"
                value={sizingConfig.avg_wl_ratio}
                onChange={(e) => onConfigChange({ avg_wl_ratio: Number(e.target.value) })}
                min={0.01}
                step={0.1}
              />
            </div>
          </div>
          <p className="col-span-2 text-[9px] text-muted-foreground italic">
            Valeurs par defaut — a ajuster apres backtest
          </p>
        </div>
      </div>

      {/* Portfolio table */}
      {isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : sizing && sizing.portfolio_table.length > 0 ? (
        <div className="space-y-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            Portefeuille
          </span>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[10px]">Ticker</TableHead>
                  <TableHead className="text-[10px] text-right">Poids</TableHead>
                  <TableHead className="text-[10px] text-right">Actions</TableHead>
                  <TableHead className="text-[10px] text-right">Valeur</TableHead>
                  <TableHead className="text-[10px] text-right">Risque</TableHead>
                  <TableHead className="text-[10px] text-center">Statut</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sizing.portfolio_table.map((row) => {
                  const cfg = STATUS_BADGE[row.status] ?? STATUS_BADGE.no_setup
                  return (
                    <TableRow
                      key={row.symbol}
                      className={cn(
                        row.status !== "entry_zone" && "opacity-50"
                      )}
                    >
                      <TableCell className="text-xs font-mono font-medium py-1.5">
                        {row.symbol}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-right py-1.5">
                        {row.weight_pct.toFixed(1)}%
                      </TableCell>
                      <TableCell className="text-xs font-mono text-right py-1.5">
                        {fmtNum(row.shares)}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-right py-1.5">
                        {fmtNum(row.position_value)}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-right py-1.5 text-red-600">
                        {fmtNum(row.trade_risk)}
                      </TableCell>
                      <TableCell className="text-center py-1.5">
                        <Badge
                          variant={row.status === "entry_zone" ? "default" : "outline"}
                          className={cn("text-[9px] px-1.5 py-0", cfg.cls)}
                        >
                          {cfg.label}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>

          {/* Summary row */}
          <div className="flex items-center justify-between text-xs rounded-md bg-muted/50 px-3 py-2">
            <span className="text-muted-foreground">Total</span>
            <div className="flex items-center gap-4 font-mono">
              <span>Exposition: <strong>{sizing.total_exposure_pct.toFixed(1)}%</strong></span>
              <span className="text-red-600">Risque: <strong>{sizing.total_risk_pct.toFixed(1)}%</strong></span>
              <span>Capital: <strong>{fmtNum(sizing.capital_deployed)}</strong></span>
            </div>
          </div>
        </div>
      ) : null}

      {/* Explain */}
      {!isLoading && sizing?.explain && (
        <p className="text-[10px] text-muted-foreground italic">
          {sizing.explain}
        </p>
      )}
    </div>
  )
}
