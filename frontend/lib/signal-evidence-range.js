function asText(value) {
  return typeof value === "string" ? value.trim() : ""
}

function asNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function dateKey(value) {
  const text = asText(value)
  if (!text) return null
  const key = text.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(key) ? key : null
}

function mean(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  if (finite.length === 0) return null
  return finite.reduce((sum, value) => sum + value, 0) / finite.length
}

function std(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  if (finite.length < 2) return null
  const avg = mean(finite) ?? 0
  const variance = finite.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (finite.length - 1)
  return Math.sqrt(variance)
}

function sharpe(values, dates) {
  const finite = values.filter((value) => Number.isFinite(value))
  if (finite.length < 2) return null
  const avg = mean(finite) ?? 0
  const sigma = std(finite) ?? 0
  if (sigma <= 0) return null
  const years = Math.max(Array.isArray(dates) ? dates.length : 0, 1) / 252
  return (avg / sigma) * Math.sqrt(finite.length / years)
}

function pathReturns(equity) {
  const returns = []
  for (let i = 1; i < equity.length; i += 1) {
    const prev = asNumber(equity[i - 1])
    const curr = asNumber(equity[i])
    if (prev != null && curr != null && prev > 0) returns.push(curr / prev - 1)
  }
  return returns
}

function pathReturnsWithFirstFlat(equity) {
  if (!Array.isArray(equity) || equity.length === 0) return []
  const returns = [0]
  for (let i = 1; i < equity.length; i += 1) {
    const prev = asNumber(equity[i - 1])
    const curr = asNumber(equity[i])
    returns.push(prev != null && curr != null && prev > 0 ? curr / prev - 1 : null)
  }
  return returns
}

function pathSharpe(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  if (finite.length < 2) return null
  const sigma = std(finite) ?? 0
  return sigma > 0 ? ((mean(finite) ?? 0) / sigma) * Math.sqrt(252) : null
}

function sortino(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  const downside = finite.filter((value) => value < 0)
  if (finite.length < 2 || downside.length < 2) return null
  const semiStd = std(downside) ?? 0
  return semiStd > 0 ? ((mean(finite) ?? 0) / semiStd) * Math.sqrt(252) : null
}

function annualizedVolatility(values) {
  const sigma = std(values)
  return sigma == null ? null : sigma * Math.sqrt(252)
}

function downsideVolatility(values) {
  const downside = values.filter((value) => Number.isFinite(value) && value < 0)
  const sigma = std(downside)
  return sigma == null ? null : sigma * Math.sqrt(252)
}

function maxDrawdown(equity) {
  let peak = null
  let max = 0
  for (const value of equity) {
    if (!Number.isFinite(value)) continue
    peak = peak == null ? value : Math.max(peak, value)
    if (peak > 0) max = Math.max(max, 1 - value / peak)
  }
  return max
}

function percentile(values, pct) {
  const finite = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (finite.length === 0) return null
  const rank = (pct / 100) * (finite.length - 1)
  const lo = Math.floor(rank)
  const hi = Math.ceil(rank)
  if (lo === hi) return finite[lo]
  const weight = rank - lo
  return finite[lo] * (1 - weight) + finite[hi] * weight
}

function marketModel(stratRet, benchRet, periodsPerYear = 252, minObs = 20) {
  if (!Array.isArray(benchRet)) {
    return { beta: null, alpha_annualized: null, alpha_r2: null, alpha_n_obs: 0, alpha_reason: "benchmark_unavailable" }
  }
  const pairs = []
  for (let i = 0; i < Math.min(stratRet.length, benchRet.length); i += 1) {
    const strat = asNumber(stratRet[i])
    const bench = asNumber(benchRet[i])
    if (strat != null && bench != null) pairs.push([strat, bench])
  }
  const nObs = pairs.length
  const nonzero = pairs.filter(([strat]) => Math.abs(strat) > 1e-12).length
  if (nObs < minObs || nonzero < 10) {
    return { beta: null, alpha_annualized: null, alpha_r2: null, alpha_n_obs: nObs, alpha_reason: "insufficient_overlap" }
  }
  const y = pairs.map(([strat]) => strat)
  const x = pairs.map(([, bench]) => bench)
  const xMean = mean(x) ?? 0
  const yMean = mean(y) ?? 0
  let denom = 0
  let cov = 0
  for (let i = 0; i < pairs.length; i += 1) {
    const dx = x[i] - xMean
    denom += dx * dx
    cov += dx * (y[i] - yMean)
  }
  if (denom <= 0) {
    return { beta: null, alpha_annualized: null, alpha_r2: null, alpha_n_obs: nObs, alpha_reason: "insufficient_overlap" }
  }
  const beta = cov / denom
  const intercept = yMean - beta * xMean
  const fitted = x.map((value) => intercept + beta * value)
  let total = 0
  let resid = 0
  for (let i = 0; i < y.length; i += 1) {
    total += (y[i] - yMean) ** 2
    resid += (y[i] - fitted[i]) ** 2
  }
  const r2 = total > 0 ? Math.max(0, Math.min(1, 1 - resid / total)) : null
  return { beta, alpha_annualized: intercept * periodsPerYear, alpha_r2: r2, alpha_n_obs: nObs, alpha_reason: "ok" }
}

function distributionMetrics(netReturns, equity, dates, benchmarkReturns, benchmarkSymbol) {
  const finite = netReturns.filter((value) => Number.isFinite(value))
  const wins = finite.filter((value) => value > 0)
  const losses = finite.filter((value) => value < 0)
  const grossProfit = wins.reduce((sum, value) => sum + value, 0)
  const grossLoss = Math.abs(losses.reduce((sum, value) => sum + value, 0))
  const avgWin = mean(wins)
  const avgLoss = mean(losses)
  const drawdown = maxDrawdown(equity)
  const totalReturn = equity.length ? equity[equity.length - 1] - 1 : 0
  const years = Math.max(dates.length, 1) / 252
  const cagr = totalReturn > -1 ? (1 + totalReturn) ** (1 / years) - 1 : -1
  const path = pathReturns(equity)
  const alpha = marketModel(pathReturnsWithFirstFlat(equity), benchmarkReturns)
  return {
    profit_factor_net:
      grossLoss > 0 ? grossProfit / grossLoss : null,
    avg_win_net: avgWin,
    avg_loss_net: avgLoss,
    payoff_ratio_net: avgWin != null && avgLoss != null && avgLoss !== 0 ? avgWin / Math.abs(avgLoss) : null,
    median_return_net: percentile(finite, 50),
    p05_return_net: percentile(finite, 5),
    p95_return_net: percentile(finite, 95),
    sortino: sortino(path),
    sharpe_path: pathSharpe(path),
    calmar: drawdown > 0 ? cagr / Math.abs(drawdown) : null,
    annualized_volatility: annualizedVolatility(path),
    downside_volatility: downsideVolatility(path),
    beta: alpha.beta,
    alpha_annualized: alpha.alpha_annualized,
    alpha_r2: alpha.alpha_r2,
    alpha_n_obs: alpha.alpha_n_obs,
    alpha_reason: alpha.alpha_reason,
    benchmark_symbol: benchmarkSymbol ?? null,
    sample_start: dates.length ? dateKey(dates[0]) : null,
    sample_end: dates.length ? dateKey(dates[dates.length - 1]) : null,
    sample_days: dates.length,
    min_sample_pass: finite.length >= 30,
    metric_basis: "stitched_wfo_oos",
  }
}

function priceKindRank(row) {
  const priceKind = asText(row.price_kind).toLowerCase()
  if (priceKind === "open") return 0
  if (priceKind === "close") return 1
  const eventType = asText(row.event_type).toLowerCase()
  return eventType === "entry" ? 0 : 1
}

function explicitTransactionIndex(row) {
  return asNumber(row.transaction_index)
}

export function sortEvidenceLedgerRows(rows) {
  if (!Array.isArray(rows)) return []
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const leftDate = dateKey(left.row?.date) ?? ""
      const rightDate = dateKey(right.row?.date) ?? ""
      if (leftDate < rightDate) return -1
      if (leftDate > rightDate) return 1

      const leftTxn = explicitTransactionIndex(left.row)
      const rightTxn = explicitTransactionIndex(right.row)
      if (leftTxn != null && rightTxn != null && leftTxn !== rightTxn) return leftTxn - rightTxn

      const leftPrice = priceKindRank(left.row)
      const rightPrice = priceKindRank(right.row)
      if (leftPrice !== rightPrice) return leftPrice - rightPrice

      const leftSequence = asNumber(left.row?.trade_sequence)
      const rightSequence = asNumber(right.row?.trade_sequence)
      if (leftSequence != null && rightSequence != null && leftSequence !== rightSequence) {
        return leftSequence - rightSequence
      }

      return left.index - right.index
    })
    .map((item) => item.row)
}

function inRange(date, startDate, endDate) {
  if (!date) return false
  if (startDate && date < startDate) return false
  if (endDate && date > endDate) return false
  return true
}

function evidenceReturns(trades, key) {
  return trades.map((trade) => asNumber(trade?.[key])).filter((value) => value != null)
}

function isActionableTrade(trade) {
  const direction = asText(trade?.direction).toLowerCase()
  return direction === "long" || direction === "short"
}

function tradeQuantity(trade) {
  for (const key of ["quantity", "qty", "shares", "units"]) {
    const value = asNumber(trade?.[key])
    if (value != null && value > 0) return value
  }
  return 1
}

function tradeKey(row) {
  const id = asText(row?.trade_id)
  if (id) return `id:${id}`
  const sequence = asNumber(row?.trade_sequence)
  return sequence == null ? null : `seq:${sequence}`
}

function selectedTradeKeys(trades, startDate, endDate) {
  const keys = new Set()
  const ordered = [...trades].sort((left, right) => {
    const leftEntry = dateKey(left?.entry_date) ?? ""
    const rightEntry = dateKey(right?.entry_date) ?? ""
    if (leftEntry < rightEntry) return -1
    if (leftEntry > rightEntry) return 1
    const leftExit = dateKey(left?.exit_date) ?? ""
    const rightExit = dateKey(right?.exit_date) ?? ""
    if (leftExit < rightExit) return -1
    if (leftExit > rightExit) return 1
    return asText(left?.trade_id).localeCompare(asText(right?.trade_id))
  })
  ordered.forEach((trade, index) => {
    if (!inRange(dateKey(trade?.entry_date), startDate, endDate)) return
    const key = tradeKey(trade)
    if (key) keys.add(key)
    keys.add(`seq:${index + 1}`)
  })
  return keys
}

function openedNotionalForTrades(trades, ledger) {
  const tradeNotional = trades.reduce((sum, trade) => {
    const entryPrice = asNumber(trade?.entry_price)
    return entryPrice == null ? sum : sum + entryPrice * tradeQuantity(trade)
  }, 0)
  if (tradeNotional > 0) return tradeNotional

  return ledger.reduce((sum, row) => {
    const explicit = asNumber(row?.notional_ouvert)
    if (explicit != null && explicit > 0) return sum + explicit
    const eventType = asText(row?.event_type).toLowerCase()
    if (eventType && eventType !== "entry") return sum
    const label = asText(row?.marker_label).toLowerCase()
    const isOpening = eventType === "entry" || label.includes("buy") || label.includes("achat") || label.includes("short")
    if (!isOpening || positionDelta(row) === 0) return sum
    const price = asNumber(row?.prix_execution)
    const quantity = asNumber(row?.quantity) ?? 1
    return price == null ? sum : sum + Math.abs(price * quantity)
  }, 0)
}

function equityForOpenedTrades(dates, trades, ledger) {
  const realizedByDate = new Map()
  for (const row of ledger) {
    const key = dateKey(row?.date)
    const pnl = asNumber(row?.pnl_realise)
    if (!key || pnl == null) continue
    realizedByDate.set(key, (realizedByDate.get(key) ?? 0) + pnl)
  }

  const equity = []
  let realized = 0
  const openedNotional = openedNotionalForTrades(trades, ledger)
  for (const date of dates) {
    realized += realizedByDate.get(dateKey(date)) ?? 0
    equity.push(openedNotional > 0 ? 1 + realized / openedNotional : 1)
  }
  return equity
}

function positionDelta(row) {
  const label = asText(row?.marker_label).toLowerCase()
  if (label.includes("short")) return -1
  if (label.includes("cover")) return 1
  if (label.includes("buy") || label.includes("achat")) return 1
  if (label.includes("sell") || label.includes("vente")) return -1
  const eventType = asText(row?.event_type).toLowerCase()
  const side = asText(row?.side).toLowerCase()
  if (eventType === "entry") return side.includes("vente") || side.includes("short") ? -1 : 1
  if (eventType === "exit") return side.includes("achat") || side.includes("cover") ? 1 : -1
  return 0
}

function positionForLedger(dates, ledger) {
  const rowsByDate = new Map()
  for (const row of ledger) {
    const key = dateKey(row?.date)
    if (!key) continue
    const rows = rowsByDate.get(key) ?? []
    rows.push(row)
    rowsByDate.set(key, rows)
  }
  const position = []
  let current = 0
  for (const date of dates) {
    for (const row of rowsByDate.get(dateKey(date)) ?? []) {
      current += positionDelta(row)
    }
    position.push(current)
  }
  return position
}

function ledgerWithLocalPositions(ledger) {
  let current = 0
  return ledger.map((row) => {
    current += positionDelta(row)
    return { ...row, position: current }
  })
}

export function buildSignalEvidenceRangeView(stitched, startDate) {
  const empty = {
    startIndex: 0,
    startDate: startDate ?? null,
    endDate: null,
    dates: [],
    open: [],
    high: [],
    low: [],
    close: [],
    benchmark_returns: [],
    benchmark_symbol: null,
    equity: [],
    position: [],
    ledger: [],
    chartMarkers: [],
    trades: [],
    sampleTrades: [],
    metrics: {
      total_return: 0,
      cagr: 0,
      sharpe: null,
      max_drawdown: 0,
      win_rate: null,
      hit_rate: null,
      n_trades: 0,
      expected_return_gross: null,
      expected_return_net: null,
      stock_expected_return: null,
      profit_factor_net: null,
      avg_win_net: null,
      avg_loss_net: null,
      payoff_ratio_net: null,
      median_return_net: null,
      p05_return_net: null,
      p95_return_net: null,
      sortino: null,
      sharpe_path: null,
      calmar: null,
      annualized_volatility: null,
      downside_volatility: null,
      beta: null,
      alpha_annualized: null,
      alpha_r2: null,
      alpha_n_obs: 0,
      alpha_reason: "benchmark_unavailable",
      benchmark_symbol: null,
      sample_start: null,
      sample_end: null,
      sample_days: 0,
      min_sample_pass: false,
      metric_basis: "stitched_wfo_oos",
    },
  }
  if (!stitched || !Array.isArray(stitched.dates)) return empty

  const firstIndex = startDate
    ? stitched.dates.findIndex((date) => {
      const key = dateKey(date)
      return key != null && key >= startDate
    })
    : 0
  const startIndex = firstIndex >= 0 ? firstIndex : Math.max(0, stitched.dates.length - 1)
  const dates = stitched.dates.slice(startIndex)
  const endDate = dateKey(dates[dates.length - 1])
  const open = Array.isArray(stitched.open_series) ? stitched.open_series.slice(startIndex) : []
  const high = Array.isArray(stitched.high_series) ? stitched.high_series.slice(startIndex) : []
  const low = Array.isArray(stitched.low_series) ? stitched.low_series.slice(startIndex) : []
  const close = Array.isArray(stitched.close_series) ? stitched.close_series.slice(startIndex) : []
  const benchmarkReturns = Array.isArray(stitched.benchmark_returns)
    ? stitched.benchmark_returns.slice(startIndex)
    : null
  const benchmarkSymbol = asText(stitched.benchmark_symbol) || null
  const allTrades = Array.isArray(stitched.trades) ? stitched.trades : []
  const sampleTrades = allTrades
    ? allTrades.filter((trade) => inRange(dateKey(trade?.entry_date), startDate, endDate))
    : []
  const trades = sampleTrades.filter(isActionableTrade)
  const selectedKeys = selectedTradeKeys(allTrades.filter(isActionableTrade), startDate, endDate)
  const ledger = ledgerWithLocalPositions(
    sortEvidenceLedgerRows(stitched.trade_ledger)
      .filter((row) => selectedKeys.has(tradeKey(row)))
      .filter((row) => inRange(dateKey(row?.date), startDate, endDate)),
  )
  const position = positionForLedger(dates, ledger)
  const netReturns = evidenceReturns(trades, "action_return_net")
  const grossReturns = evidenceReturns(trades, "action_return_gross")
  const stockReturns = evidenceReturns(sampleTrades, "stock_return")
  const equity = equityForOpenedTrades(dates, trades, ledger)
  const totalReturn = equity.length ? equity[equity.length - 1] - 1 : 0
  const years = Math.max(dates.length, 1) / 252
  const cagr = totalReturn > -1 ? (1 + totalReturn) ** (1 / years) - 1 : -1
  const hitRate = grossReturns.length
    ? grossReturns.filter((value) => value > 0).length / grossReturns.length
    : null
  const extraMetrics = distributionMetrics(netReturns, equity, dates, benchmarkReturns, benchmarkSymbol)

  return {
    startIndex,
    startDate: startDate ?? null,
    endDate,
    dates,
    open,
    high,
    low,
    close,
    benchmark_returns: benchmarkReturns ?? [],
    benchmark_symbol: benchmarkSymbol,
    equity,
    position,
    ledger,
    chartMarkers: ledger,
    trades,
    sampleTrades,
    metrics: {
      total_return: totalReturn,
      cagr,
      sharpe: netReturns.length ? sharpe(netReturns, dates) : null,
      max_drawdown: maxDrawdown(equity),
      win_rate: hitRate,
      hit_rate: hitRate,
      n_trades: trades.length,
      expected_return_gross: mean(grossReturns),
      expected_return_net: mean(netReturns),
      stock_expected_return: mean(stockReturns),
      ...extraMetrics,
    },
  }
}
