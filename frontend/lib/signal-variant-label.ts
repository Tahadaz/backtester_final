type VariantLabelInput = {
  variant_id: string
  archetype?: string | null
  params?: Record<string, unknown> | null
  description?: string | null
}

function valueOf(params: Record<string, unknown>, key: string): string {
  const value = params[key]
  return value == null || value === "" ? "?" : String(value)
}

export function signalVariantLabel(variant: VariantLabelInput): string {
  const description = String(variant.description ?? "").trim()
  if (description) return description

  const params = (variant.params ?? {}) as Record<string, unknown>
  const archetype = String(variant.archetype ?? "")

  if (archetype === "sr_combo") {
    return `${valueOf(params, "support_method_id")} -> ${valueOf(params, "resistance_method_id")}`
  }
  if (archetype === "price_vs_sma") return `SMA-${valueOf(params, "window")}`
  if (archetype === "price_vs_ema") return `EMA-${valueOf(params, "window")}`
  if (archetype === "sma_cross") return `SMA(${valueOf(params, "fast")},${valueOf(params, "slow")})`
  if (archetype === "ema_cross") return `EMA(${valueOf(params, "fast")},${valueOf(params, "slow")})`
  if (archetype === "slope_confirmed") return `SMA-${valueOf(params, "window")} Slope`
  if (archetype === "ichi_cloud") {
    return `Ichimoku(${valueOf(params, "tenkan")},${valueOf(params, "kijun")},${valueOf(params, "senkou_b")})`
  }
  if (archetype === "psar_trend") return `PSAR(${valueOf(params, "af_step")},${valueOf(params, "af_max")})`
  if (archetype === "rsi_level") {
    return `RSI(${valueOf(params, "period")},${valueOf(params, "oversold")}/${valueOf(params, "overbought")})`
  }
  if (archetype === "macd_cross") {
    return `MACD(${valueOf(params, "fast")},${valueOf(params, "slow")},${valueOf(params, "signal")})`
  }
  if (archetype === "roc_zero") return `ROC-${valueOf(params, "period")}`
  if (archetype === "trix_zero") return `TRIX-${valueOf(params, "period")}`
  if (archetype === "adx_trend") return `ADX(${valueOf(params, "period")},${valueOf(params, "adx_threshold")})`
  if (archetype === "tsi_zero") return `TSI(${valueOf(params, "long_period")},${valueOf(params, "short_period")})`
  if (archetype === "stoch_level") return `Stoch(${valueOf(params, "k_period")},${valueOf(params, "d_period")})`
  if (archetype === "cci_level") return `CCI-${valueOf(params, "period")}`
  if (archetype === "mfi_level") {
    return `MFI(${valueOf(params, "period")},${valueOf(params, "oversold")}/${valueOf(params, "overbought")})`
  }
  if (archetype === "uo_level") {
    return `UO(${valueOf(params, "period_1")},${valueOf(params, "period_2")},${valueOf(params, "period_3")})`
  }
  if (archetype === "obv_trend") return `OBV-EMA-${valueOf(params, "ema_period")}`
  if (archetype === "cmf_flow") return `CMF-${valueOf(params, "period")}`
  if (archetype === "ad_trend") return `AD-EMA-${valueOf(params, "ema_period")}`
  if (archetype === "vwap_dev") return `VWAP(${valueOf(params, "period")},${valueOf(params, "threshold_pct")}%)`
  if (archetype === "fi_trend") return `FI-${valueOf(params, "period")}`

  return variant.variant_id.slice(0, 12)
}
