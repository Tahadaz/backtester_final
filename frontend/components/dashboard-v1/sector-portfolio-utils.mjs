const PORTFOLIO_BUY_THRESHOLD = 15
const PORTFOLIO_STRONG_THRESHOLD = 50

export function asFiniteNumber(value) {
  if (value == null || value === "") return null
  const parsed = Number(String(value).replace(",", "."))
  return Number.isFinite(parsed) ? parsed : null
}

export function normalizeShareQuantity(value) {
  const parsed = asFiniteNumber(value)
  if (parsed == null || parsed <= 0) return 0
  return parsed
}

export function stockPriceForWeight(stock) {
  return (
    asFiniteNumber(stock?.last_price) ??
    asFiniteNumber(stock?.scores?.signal_engine?.technical_levels?.close_used) ??
    asFiniteNumber(stock?.prev_close)
  )
}

function isActionableBestSignal(signal) {
  if (!signal) return false
  if (signal.direction === "none" || signal.bucket === "hold") return false
  if (signal.bucket === "buy" || signal.bucket === "strong_buy") return signal.direction === "long"
  if (signal.bucket === "sell" || signal.bucket === "strong_sell") return signal.direction === "short"
  return false
}

export function directionForWeightedSignal(stock, displayMode = "trade_opportunities", technicalDirectionMode = "best") {
  if (displayMode === "technical_directions") {
    const signal = technicalDirectionMode === "classic"
      ? stock?.classic_technical_signal
      : stock?.best_technical_signal
    return signal?.direction === "long" || signal?.direction === "short" ? signal.direction : "none"
  }
  const signal = stock?.best_signal
  if (signal?.source !== "wfo") return "none"
  return isActionableBestSignal(signal) ? signal.direction : "none"
}

export function expectedReturnForWeightedSignal(stock) {
  if (stock?.best_signal?.source !== "wfo") return null
  const value = asFiniteNumber(stock?.best_signal?.action_expected_return_net)
  return value == null ? null : value
}

export function signalLabelFromNetWeight(netWeightPct) {
  if (netWeightPct > PORTFOLIO_STRONG_THRESHOLD) return "Achat fort"
  if (netWeightPct > PORTFOLIO_BUY_THRESHOLD) return "Achat"
  if (netWeightPct >= -PORTFOLIO_BUY_THRESHOLD) return "Neutre"
  if (netWeightPct >= -PORTFOLIO_STRONG_THRESHOLD) return "Vente"
  return "Vente forte"
}

export function buildPortfolioWeightRows(stocks, sharesBySymbol, options = {}) {
  const displayMode = options.displayMode ?? "trade_opportunities"
  const technicalDirectionMode = options.technicalDirectionMode ?? "best"
  const rows = []
  let totalMarketValue = 0

  for (const stock of Array.isArray(stocks) ? stocks : []) {
    const symbol = String(stock?.symbol ?? "").trim().toUpperCase()
    if (!symbol) continue
    const shares = normalizeShareQuantity(sharesBySymbol?.[symbol])
    if (shares <= 0) continue

    const price = stockPriceForWeight(stock)
    const marketValue = price == null || price <= 0 ? 0 : shares * price
    totalMarketValue += marketValue
    rows.push({
      symbol,
      sector: stock?.sector ?? "Autre",
      shares,
      price,
      marketValue,
      weightFraction: 0,
      weightPct: 0,
      direction: directionForWeightedSignal(stock, displayMode, technicalDirectionMode),
      expectedReturnNet: expectedReturnForWeightedSignal(stock),
      stock,
    })
  }

  const weightedRows = rows.map((row) => {
    const weightFraction = totalMarketValue > 0 && row.marketValue > 0
      ? row.marketValue / totalMarketValue
      : 0
    return {
      ...row,
      weightFraction,
      weightPct: weightFraction * 100,
    }
  })

  return {
    rows: weightedRows,
    totalMarketValue,
    enteredCount: rows.length,
    investedCount: weightedRows.filter((row) => row.weightFraction > 0).length,
    missingPriceCount: weightedRows.filter((row) => row.shares > 0 && row.weightFraction === 0).length,
  }
}

export function summarizeWeightRows(rows) {
  const usable = (Array.isArray(rows) ? rows : []).filter((row) => row.weightFraction > 0)
  const totalWeightFraction = usable.reduce((sum, row) => sum + row.weightFraction, 0)
  const longWeightFraction = usable
    .filter((row) => row.direction === "long")
    .reduce((sum, row) => sum + row.weightFraction, 0)
  const shortWeightFraction = usable
    .filter((row) => row.direction === "short")
    .reduce((sum, row) => sum + row.weightFraction, 0)
  const neutralWeightFraction = Math.max(0, totalWeightFraction - longWeightFraction - shortWeightFraction)
  const weightedExpectedReturnNet = usable.reduce((sum, row) => {
    return row.expectedReturnNet == null ? sum : sum + row.expectedReturnNet * row.weightFraction
  }, 0)
  const expectedReturnWeight = usable.reduce((sum, row) => {
    return row.expectedReturnNet == null ? sum : sum + row.weightFraction
  }, 0)
  const netSignalPct = (longWeightFraction - shortWeightFraction) * 100

  return {
    totalWeightFraction,
    totalWeightPct: totalWeightFraction * 100,
    longWeightPct: longWeightFraction * 100,
    shortWeightPct: shortWeightFraction * 100,
    neutralWeightPct: neutralWeightFraction * 100,
    activeWeightPct: (longWeightFraction + shortWeightFraction) * 100,
    netSignalPct,
    signalLabel: totalWeightFraction > 0 ? signalLabelFromNetWeight(netSignalPct) : "Indisponible",
    investedCount: usable.length,
    weightedExpectedReturnNet: expectedReturnWeight > 0 ? weightedExpectedReturnNet : null,
    weightedAverageExpectedReturnNet: expectedReturnWeight > 0
      ? weightedExpectedReturnNet / expectedReturnWeight
      : null,
  }
}

export function portfolioRowsBySymbol(rows) {
  const out = {}
  for (const row of Array.isArray(rows) ? rows : []) {
    out[row.symbol] = row
  }
  return out
}
