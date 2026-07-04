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

function sharpe(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  if (finite.length < 2) return 0
  const avg = mean(finite) ?? 0
  const variance = finite.reduce((sum, value) => sum + (value - avg) ** 2, 0) / (finite.length - 1)
  const sigma = Math.sqrt(variance)
  return sigma > 0 ? (avg / sigma) * Math.sqrt(252) : 0
}

function quantile(values, q) {
  const finite = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b)
  if (finite.length === 0) return null
  const clamped = Math.max(0, Math.min(1, q))
  const position = (finite.length - 1) * clamped
  const lower = Math.floor(position)
  const upper = Math.ceil(position)
  if (lower === upper) return finite[lower]
  const weight = position - lower
  return finite[lower] * (1 - weight) + finite[upper] * weight
}

function tailRisk(values) {
  const finite = values.filter((value) => Number.isFinite(value))
  if (finite.length < 5) return { var95: null, cvar95: null }
  const var95 = quantile(finite, 0.05)
  if (var95 == null) return { var95: null, cvar95: null }
  const tail = finite.filter((value) => value <= var95)
  return {
    var95,
    cvar95: tail.length ? mean(tail) : var95,
  }
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
      var95: null,
      cvar95: null,
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
  const historicalRisk = tailRisk(netReturns)

  return {
    startIndex,
    startDate: startDate ?? null,
    endDate,
    dates,
    open,
    high,
    low,
    close,
    equity,
    position,
    ledger,
    chartMarkers: ledger,
    trades,
    sampleTrades,
    metrics: {
      total_return: totalReturn,
      cagr,
      sharpe: netReturns.length ? sharpe(netReturns) : null,
      max_drawdown: maxDrawdown(equity),
      win_rate: hitRate,
      hit_rate: hitRate,
      n_trades: trades.length,
      expected_return_gross: mean(grossReturns),
      expected_return_net: mean(netReturns),
      stock_expected_return: mean(stockReturns),
      var95: historicalRisk.var95,
      cvar95: historicalRisk.cvar95,
    },
  }
}
