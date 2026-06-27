const INDICATOR_FAMILIES = new Set([
  "sma",
  "ema",
  "ema_cross",
  "ichimoku",
  "psar",
  "macd",
  "roc",
  "trix",
  "adx",
  "tsi",
  "rsi",
  "stochastic",
  "cci",
  "mfi",
  "uo",
  "obv",
  "cmf",
  "ad",
  "vwap",
  "fi",
])

export const INDICATOR_CATEGORY_BY_FAMILY = {
  sma: "tendance",
  ema: "tendance",
  ema_cross: "tendance",
  ichimoku: "tendance",
  psar: "tendance",
  vwap: "volume",
  macd: "momentum",
  roc: "momentum",
  trix: "momentum",
  adx: "momentum",
  tsi: "momentum",
  rsi: "oscillation",
  stochastic: "oscillation",
  cci: "oscillation",
  mfi: "oscillation",
  uo: "oscillation",
  obv: "volume",
  cmf: "volume",
  ad: "volume",
  fi: "volume",
}

export function asRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : null
}

export function asText(value) {
  return typeof value === "string" ? value.trim() : ""
}

export function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

export function dateKey(value) {
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toISOString().slice(0, 10)
  }
  const text = asText(value)
  if (!text) return null
  const direct = text.slice(0, 10)
  if (/^\d{4}-\d{2}-\d{2}$/.test(direct)) return direct
  const parsed = new Date(text)
  if (!Number.isFinite(parsed.getTime())) return null
  return parsed.toISOString().slice(0, 10)
}

export function chartTimeKey(value) {
  if (value instanceof Date && Number.isFinite(value.getTime())) {
    return value.toISOString().replace(".000Z", "Z")
  }
  const text = asText(value)
  if (!text) return null
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text
  const parsed = new Date(text)
  if (!Number.isFinite(parsed.getTime())) return dateKey(text)
  return parsed.toISOString().replace(".000Z", "Z")
}

export function numericParamsFrom(raw) {
  const params = {}
  const record = asRecord(raw) ?? {}
  for (const [key, value] of Object.entries(record)) {
    const numberValue = asNumber(value)
    if (numberValue != null) params[key] = numberValue
  }
  return params
}

export function chartFamilyFromSignalFamily(value) {
  const text = asText(value).toLowerCase()
  if (!text) return null
  const baseFamily = text.endsWith("@fx") ? text.slice(0, -3) : text
  return INDICATOR_FAMILIES.has(baseFamily) ? baseFamily : null
}

export function liveBarFromQuote(quote) {
  if (!quote || quote.is_fresh !== true) return null

  const close = asNumber(quote.last_price)
  if (close == null || close <= 0) return null

  const date = dateKey(quote.session_date) ?? dateKey(quote.quote_timestamp) ?? dateKey(quote.updated_at)
  if (!date) return null

  const open = asNumber(quote.open_price) ?? asNumber(quote.prev_close) ?? close
  const highSeed = asNumber(quote.high_price)
  const lowSeed = asNumber(quote.low_price)
  const high = Math.max(...[highSeed, open, close].filter((value) => value != null))
  const low = Math.min(...[lowSeed, open, close].filter((value) => value != null))
  const volume = asNumber(quote.volume)

  return {
    date,
    open,
    high,
    low,
    close,
    volume: volume != null && volume >= 0 ? volume : null,
    quote_timestamp: asText(quote.quote_timestamp) || null,
    source: asText(quote.source_provider) || "live_quote",
  }
}

function mergedLiveBar(existing, liveBar, sameDate) {
  const close = asNumber(liveBar?.close)
  const date = dateKey(liveBar?.date)
  if (close == null || close <= 0 || !date) return null

  const open = asNumber(liveBar.open) ?? asNumber(existing?.open) ?? close
  const highSeed = asNumber(liveBar.high) ?? (sameDate ? asNumber(existing?.high) : null)
  const lowSeed = asNumber(liveBar.low) ?? (sameDate ? asNumber(existing?.low) : null)
  const high = Math.max(...[highSeed, open, close].filter((value) => value != null))
  const low = Math.min(...[lowSeed, open, close].filter((value) => value != null))
  const liveVolume = asNumber(liveBar.volume)
  const volume = liveVolume != null && liveVolume >= 0
    ? liveVolume
    : sameDate
      ? asNumber(existing?.volume)
      : null

  return {
    ...(existing ?? {}),
    date,
    open,
    high,
    low,
    close,
    volume,
  }
}

export function mergeLiveBarIntoBars(bars, liveBar) {
  const baseBars = Array.isArray(bars) ? bars.map((bar) => ({ ...bar })) : []
  const liveDate = dateKey(liveBar?.date)
  const liveClose = asNumber(liveBar?.close)
  if (!liveDate || liveClose == null || liveClose <= 0 || baseBars.length === 0) {
    return { bars: baseBars, applied: false }
  }

  const lastIndex = baseBars.length - 1
  const lastDate = dateKey(baseBars[lastIndex]?.date)
  if (!lastDate || liveDate < lastDate) return { bars: baseBars, applied: false }

  if (liveDate === lastDate) {
    const merged = mergedLiveBar(baseBars[lastIndex], liveBar, true)
    if (!merged) return { bars: baseBars, applied: false }
    baseBars[lastIndex] = merged
    return { bars: baseBars, applied: true }
  }

  const merged = mergedLiveBar(null, liveBar, false)
  if (!merged) return { bars: baseBars, applied: false }
  return { bars: [...baseBars, merged], applied: true }
}

function normalizedDirection(value) {
  const direction = asText(value).toLowerCase()
  if (direction === "long" || direction === "short") return direction
  return "none"
}

function isActionableTradeSignal(signal) {
  if (!signal) return false
  const direction = normalizedDirection(signal.direction)
  if (direction === "none" || signal.bucket === "hold") return false
  if (signal.bucket === "buy" || signal.bucket === "strong_buy") return direction === "long"
  if (signal.bucket === "sell" || signal.bucket === "strong_sell") return direction === "short"
  return direction === "long" || direction === "short"
}

export function resolveDashboardSignalDescriptor(stock, displayMode, technicalDirectionMode = "best") {
  if (!stock) return null

  if (displayMode === "technical_directions") {
    const signal = technicalDirectionMode === "classic"
      ? stock.classic_technical_signal
      : stock.best_technical_signal
    const score = asNumber(signal?.score_pct)
    if (!signal || score == null) return null
    return {
      kind: "technical",
      source: signal.source ?? "signal_engine",
      variant: signal.variant ?? null,
      scope: signal.scope ?? "global",
      scope_key: signal.scope_key ?? "global",
      scope_label: signal.scope_label ?? "Global",
      direction: normalizedDirection(signal.direction),
      label: signal.label ?? signal.signal_label ?? "Technical signal",
      signal_label: signal.signal_label ?? null,
      score_pct: score,
    }
  }

  const signal = stock.best_signal
  if (!signal || signal.source !== "wfo" || !isActionableTradeSignal(signal)) return null
  return {
    kind: "trade",
    source: signal.source,
    variant: signal.variant ?? null,
    direction: normalizedDirection(signal.direction),
    label: signal.label ?? signal.signal_label ?? "Trade signal",
    signal_label: signal.signal_label ?? null,
    score_pct: asNumber(signal.score),
    expected_return_net: asNumber(signal.action_expected_return_net),
    hit_rate: asNumber(signal.hit_rate),
  }
}
