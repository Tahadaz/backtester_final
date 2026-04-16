export type IndicatorFamilyKey =
  | "sma" | "ema" | "ema_cross" | "ichimoku" | "psar"
  | "macd" | "roc" | "trix" | "adx" | "tsi"
  | "rsi" | "stochastic" | "cci" | "mfi" | "uo"
  | "obv" | "cmf" | "ad" | "vwap" | "fi"

export type IndicatorFamilyMeta = {
  key: IndicatorFamilyKey
  title: string
  shortLabel: string
  description: string
  category: "tendance" | "momentum" | "oscillation" | "volume"
  params: Array<{
    key: string
    label: string
    min: number
    max: number
    step: number
  }>
  defaults: Record<string, number>
}

export const INDICATOR_FAMILY_ORDER: IndicatorFamilyKey[] = [
  "sma", "ema", "ema_cross", "ichimoku", "psar",
  "macd", "roc", "trix", "adx", "tsi",
  "rsi", "stochastic", "cci", "mfi", "uo",
  "obv", "cmf", "ad", "vwap", "fi",
]

export const INDICATOR_FAMILY_META: IndicatorFamilyMeta[] = [
  {
    key: "sma",
    title: "Tendance (SMA)",
    shortLabel: "SMA",
    description: "Distance normalisee entre le prix et sa moyenne mobile simple.",
    category: "tendance",
    params: [{ key: "period", label: "Periode", min: 5, max: 500, step: 1 }],
    defaults: { period: 21 },
  },
  {
    key: "ema",
    title: "Tendance (EMA)",
    shortLabel: "EMA",
    description: "Lecture plus reactive de la tendance via moyenne exponentielle.",
    category: "tendance",
    params: [{ key: "window", label: "Fenetre", min: 2, max: 500, step: 1 }],
    defaults: { window: 21 },
  },
  {
    key: "ema_cross",
    title: "Tendance (EMA Cross)",
    shortLabel: "EMA Cross",
    description: "Croisement entre EMA rapide et lente.",
    category: "tendance",
    params: [
      { key: "fast", label: "Fast", min: 2, max: 200, step: 1 },
      { key: "slow", label: "Slow", min: 3, max: 500, step: 1 },
    ],
    defaults: { fast: 12, slow: 26 },
  },
  {
    key: "ichimoku",
    title: "Tendance (Ichimoku)",
    shortLabel: "Ichimoku",
    description: "Nuage, lignes de conversion et ligne de base pour lire la structure.",
    category: "tendance",
    params: [
      { key: "tenkan", label: "Tenkan", min: 2, max: 100, step: 1 },
      { key: "kijun", label: "Kijun", min: 3, max: 200, step: 1 },
      { key: "senkou_b", label: "Senkou B", min: 5, max: 400, step: 1 },
    ],
    defaults: { tenkan: 9, kijun: 26, senkou_b: 52 },
  },
  {
    key: "psar",
    title: "Tendance (Parabolic SAR)",
    shortLabel: "PSAR",
    description: "Points de suivi de tendance et retournements de Wilder.",
    category: "tendance",
    params: [
      { key: "af_step", label: "AF Step", min: 0.005, max: 0.05, step: 0.005 },
      { key: "af_max", label: "AF Max", min: 0.1, max: 0.5, step: 0.01 },
    ],
    defaults: { af_step: 0.02, af_max: 0.2 },
  },
  {
    key: "macd",
    title: "Momentum (MACD)",
    shortLabel: "MACD",
    description: "Croisement MACD et histogramme de momentum.",
    category: "momentum",
    params: [
      { key: "fast", label: "Fast", min: 2, max: 100, step: 1 },
      { key: "slow", label: "Slow", min: 5, max: 200, step: 1 },
      { key: "signal", label: "Signal", min: 2, max: 50, step: 1 },
    ],
    defaults: { fast: 12, slow: 26, signal: 9 },
  },
  {
    key: "roc",
    title: "Momentum (ROC)",
    shortLabel: "ROC",
    description: "Variation en pourcentage sur N periodes.",
    category: "momentum",
    params: [{ key: "period", label: "Periode", min: 1, max: 400, step: 1 }],
    defaults: { period: 60 },
  },
  {
    key: "trix",
    title: "Momentum (TRIX)",
    shortLabel: "TRIX",
    description: "Taux de variation de la triple EMA.",
    category: "momentum",
    params: [{ key: "period", label: "Periode", min: 2, max: 400, step: 1 }],
    defaults: { period: 15 },
  },
  {
    key: "adx",
    title: "Momentum (ADX)",
    shortLabel: "ADX",
    description: "Force de tendance avec +DI et -DI.",
    category: "momentum",
    params: [
      { key: "period", label: "Periode", min: 2, max: 200, step: 1 },
      { key: "adx_threshold", label: "Seuil ADX", min: 5, max: 50, step: 1 },
    ],
    defaults: { period: 21, adx_threshold: 25 },
  },
  {
    key: "tsi",
    title: "Momentum (TSI)",
    shortLabel: "TSI",
    description: "Momentum doublement lisse, centre sur zero.",
    category: "momentum",
    params: [
      { key: "long_period", label: "Long", min: 2, max: 200, step: 1 },
      { key: "short_period", label: "Short", min: 1, max: 100, step: 1 },
    ],
    defaults: { long_period: 25, short_period: 13 },
  },
  {
    key: "rsi",
    title: "Oscillation (RSI)",
    shortLabel: "RSI",
    description: "Oscillateur de Wilder entre 0 et 100.",
    category: "oscillation",
    params: [
      { key: "period", label: "Periode", min: 2, max: 200, step: 1 },
      { key: "oversold", label: "Survendu", min: 0, max: 50, step: 1 },
      { key: "overbought", label: "Surachete", min: 50, max: 100, step: 1 },
    ],
    defaults: { period: 21, oversold: 30, overbought: 70 },
  },
  {
    key: "stochastic",
    title: "Oscillation (Stochastic)",
    shortLabel: "Stochastic",
    description: "Position du cours dans son range recent avec %K et %D.",
    category: "oscillation",
    params: [
      { key: "k_period", label: "%K", min: 2, max: 200, step: 1 },
      { key: "d_period", label: "%D", min: 1, max: 50, step: 1 },
    ],
    defaults: { k_period: 14, d_period: 3 },
  },
  {
    key: "cci",
    title: "Oscillation (CCI)",
    shortLabel: "CCI",
    description: "Deviation du prix typique autour de sa moyenne.",
    category: "oscillation",
    params: [{ key: "period", label: "Periode", min: 2, max: 400, step: 1 }],
    defaults: { period: 22 },
  },
  {
    key: "mfi",
    title: "Oscillation (MFI)",
    shortLabel: "MFI",
    description: "RSI volume-weighted sur la pression acheteuse/vendeuse.",
    category: "oscillation",
    params: [
      { key: "period", label: "Periode", min: 2, max: 200, step: 1 },
      { key: "oversold", label: "Survendu", min: 0, max: 50, step: 1 },
      { key: "overbought", label: "Surachete", min: 50, max: 100, step: 1 },
    ],
    defaults: { period: 14, oversold: 20, overbought: 80 },
  },
  {
    key: "uo",
    title: "Oscillation (Ultimate Osc.)",
    shortLabel: "UO",
    description: "Oscillateur multi-horizon de Larry Williams.",
    category: "oscillation",
    params: [
      { key: "period_1", label: "Periode 1", min: 1, max: 100, step: 1 },
      { key: "period_2", label: "Periode 2", min: 2, max: 200, step: 1 },
      { key: "period_3", label: "Periode 3", min: 3, max: 400, step: 1 },
    ],
    defaults: { period_1: 7, period_2: 14, period_3: 28 },
  },
  {
    key: "obv",
    title: "Volume (OBV)",
    shortLabel: "OBV",
    description: "On-Balance Volume compare a sa moyenne exponentielle.",
    category: "volume",
    params: [{ key: "ema_period", label: "EMA", min: 2, max: 200, step: 1 }],
    defaults: { ema_period: 21 },
  },
  {
    key: "cmf",
    title: "Volume (CMF)",
    shortLabel: "CMF",
    description: "Chaikin Money Flow, centre sur zero.",
    category: "volume",
    params: [{ key: "period", label: "Periode", min: 2, max: 400, step: 1 }],
    defaults: { period: 22 },
  },
  {
    key: "ad",
    title: "Volume (A/D Line)",
    shortLabel: "A/D Line",
    description: "Ligne d'accumulation/distribution comparee a son EMA.",
    category: "volume",
    params: [{ key: "ema_period", label: "EMA", min: 2, max: 200, step: 1 }],
    defaults: { ema_period: 21 },
  },
  {
    key: "vwap",
    title: "Volume (VWAP)",
    shortLabel: "VWAP",
    description: "Deviation du prix autour du VWAP roulant.",
    category: "volume",
    params: [
      { key: "period", label: "Periode", min: 2, max: 300, step: 1 },
      { key: "threshold_pct", label: "Seuil %", min: 0.1, max: 10, step: 0.1 },
    ],
    defaults: { period: 22, threshold_pct: 1 },
  },
  {
    key: "fi",
    title: "Volume (Force Index)",
    shortLabel: "Force Index",
    description: "Force du mouvement lissee par le volume.",
    category: "volume",
    params: [{ key: "period", label: "Periode", min: 2, max: 200, step: 1 }],
    defaults: { period: 21 },
  },
]

export const INDICATOR_META_BY_KEY: Record<IndicatorFamilyKey, IndicatorFamilyMeta> =
  Object.fromEntries(INDICATOR_FAMILY_META.map((meta) => [meta.key, meta])) as Record<IndicatorFamilyKey, IndicatorFamilyMeta>

export function normalizeIndicatorParams(
  family: IndicatorFamilyKey,
  key: string,
  rawValue: number,
  params: Record<string, number>,
): Record<string, number> {
  const next = { ...params }
  const rounded = Number.isInteger(rawValue) ? Math.round(rawValue) : Number(rawValue.toFixed(4))

  switch (family) {
    case "psar": {
      const afStep = key === "af_step" ? rounded : Number(next.af_step ?? 0.02)
      const afMax = key === "af_max" ? rounded : Number(next.af_max ?? 0.2)
      next.af_step = Math.min(afStep, afMax - 0.001)
      next.af_max = Math.max(afMax, next.af_step + 0.001)
      return next
    }
    case "ema_cross":
    case "macd": {
      const fast = key === "fast" ? Math.round(rawValue) : Math.round(next.fast ?? 12)
      const slow = key === "slow" ? Math.round(rawValue) : Math.round(next.slow ?? 26)
      next.fast = Math.min(fast, slow - 1)
      next.slow = Math.max(slow, next.fast + 1)
      if (family === "macd") {
        next.signal = key === "signal" ? Math.round(rawValue) : Math.round(next.signal ?? 9)
      }
      return next
    }
    case "ichimoku": {
      let tenkan = key === "tenkan" ? Math.round(rawValue) : Math.round(next.tenkan ?? 9)
      let kijun = key === "kijun" ? Math.round(rawValue) : Math.round(next.kijun ?? 26)
      let senkouB = key === "senkou_b" ? Math.round(rawValue) : Math.round(next.senkou_b ?? 52)
      tenkan = Math.min(tenkan, kijun - 1)
      kijun = Math.max(kijun, tenkan + 1)
      kijun = Math.min(kijun, senkouB - 1)
      senkouB = Math.max(senkouB, kijun + 1)
      next.tenkan = tenkan
      next.kijun = kijun
      next.senkou_b = senkouB
      return next
    }
    case "tsi": {
      const longPeriod = key === "long_period" ? Math.round(rawValue) : Math.round(next.long_period ?? 25)
      const shortPeriod = key === "short_period" ? Math.round(rawValue) : Math.round(next.short_period ?? 13)
      next.long_period = Math.max(longPeriod, shortPeriod + 1)
      next.short_period = Math.min(shortPeriod, next.long_period - 1)
      return next
    }
    case "mfi": {
      const oversold = key === "oversold" ? Math.round(rawValue) : Math.round(next.oversold ?? 20)
      const overbought = key === "overbought" ? Math.round(rawValue) : Math.round(next.overbought ?? 80)
      next.period = key === "period" ? Math.round(rawValue) : Math.round(next.period ?? 14)
      next.oversold = Math.min(oversold, overbought - 1)
      next.overbought = Math.max(overbought, next.oversold + 1)
      return next
    }
    case "rsi": {
      const oversold = key === "oversold" ? Math.round(rawValue) : Math.round(next.oversold ?? 30)
      const overbought = key === "overbought" ? Math.round(rawValue) : Math.round(next.overbought ?? 70)
      next.period = key === "period" ? Math.round(rawValue) : Math.round(next.period ?? 21)
      next.oversold = Math.min(oversold, overbought - 1)
      next.overbought = Math.max(overbought, next.oversold + 1)
      return next
    }
    case "uo": {
      let p1 = key === "period_1" ? Math.round(rawValue) : Math.round(next.period_1 ?? 7)
      let p2 = key === "period_2" ? Math.round(rawValue) : Math.round(next.period_2 ?? 14)
      let p3 = key === "period_3" ? Math.round(rawValue) : Math.round(next.period_3 ?? 28)
      p1 = Math.min(p1, p2 - 1)
      p2 = Math.max(p2, p1 + 1)
      p2 = Math.min(p2, p3 - 1)
      p3 = Math.max(p3, p2 + 1)
      next.period_1 = p1
      next.period_2 = p2
      next.period_3 = p3
      return next
    }
    default:
      next[key] = Math.round(rawValue)
      if (family === "vwap" && key === "threshold_pct") {
        next[key] = Number(rawValue.toFixed(2))
      }
      return next
  }
}
