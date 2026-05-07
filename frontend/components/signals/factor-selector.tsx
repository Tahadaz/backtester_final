"use client"

import { useCallback, useEffect, useState } from "react"
import { RefreshCw, Zap } from "lucide-react"
import { type FactorConfigItem, getFactorConfig, updateFactorConfig } from "@/lib/api"

type Props = {
  symbol: string
  onConfigChange?: () => void
}

export function FactorSelector({ symbol, onConfigChange }: Props) {
  const [factors, setFactors] = useState<FactorConfigItem[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const cfg = await getFactorConfig(symbol)
      setFactors(cfg.factors)
    } catch {
      // silently ignore fetch errors
    } finally {
      setLoading(false)
    }
  }, [symbol])

  useEffect(() => {
    load()
  }, [load])

  const toggle = async (ticker: string, enabled: boolean) => {
    const next = factors.map((f) =>
      f.factor_ticker === ticker ? { ...f, enabled } : f
    )
    setFactors(next)
    setSaving(true)
    try {
      await updateFactorConfig(symbol, next)
      onConfigChange?.()
    } catch {
      // revert on error
      load()
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <RefreshCw className="h-3 w-3 animate-spin" />
        Chargement des facteurs…
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
        <Zap className="h-3 w-3" />
        Facteurs actifs :
      </span>
      {factors.map((f) => (
        <button
          key={f.factor_ticker}
          onClick={() => toggle(f.factor_ticker, !f.enabled)}
          disabled={saving}
          className={[
            "rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
            f.enabled
              ? "border-blue-300 bg-blue-50 text-blue-700 hover:bg-blue-100"
              : "border-border bg-muted text-muted-foreground hover:bg-accent",
          ].join(" ")}
          title={f.label}
        >
          {f.factor_ticker}
        </button>
      ))}
      {saving && <RefreshCw className="h-3 w-3 animate-spin text-muted-foreground" />}
    </div>
  )
}
