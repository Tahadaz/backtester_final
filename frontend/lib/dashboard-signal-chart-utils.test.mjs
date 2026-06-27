import test from "node:test"
import assert from "node:assert/strict"

import {
  chartTimeKey,
  liveBarFromQuote,
  mergeLiveBarIntoBars,
  resolveDashboardSignalDescriptor,
} from "./dashboard-signal-chart-utils.js"

const bars = [
  { date: "2026-05-12", open: 100, high: 103, low: 99, close: 102, volume: 1000 },
  { date: "2026-05-13", open: 102, high: 105, low: 101, close: 104, volume: 1100 },
]

test("mergeLiveBarIntoBars replaces the same session bar", () => {
  const result = mergeLiveBarIntoBars(bars, {
    date: "2026-05-13",
    open: 104,
    high: 106,
    low: 103,
    close: 105,
    volume: 1200,
  })

  assert.equal(result.applied, true)
  assert.equal(result.bars.length, 2)
  assert.deepEqual(result.bars.at(-1), {
    date: "2026-05-13",
    open: 104,
    high: 106,
    low: 103,
    close: 105,
    volume: 1200,
  })
})

test("mergeLiveBarIntoBars appends a newer session bar", () => {
  const result = mergeLiveBarIntoBars(bars, {
    date: "2026-05-14",
    open: 104,
    high: 106,
    low: 103,
    close: 105,
    volume: 1200,
  })

  assert.equal(result.applied, true)
  assert.equal(result.bars.length, 3)
  assert.equal(result.bars.at(-1).date, "2026-05-14")
  assert.equal(result.bars.at(-1).close, 105)
})

test("liveBarFromQuote ignores stale or incomplete quotes", () => {
  assert.equal(liveBarFromQuote({ is_fresh: false, session_date: "2026-05-14", last_price: 105 }), null)
  assert.equal(liveBarFromQuote({ is_fresh: true, session_date: "2026-05-14", last_price: null }), null)
  assert.equal(liveBarFromQuote({ is_fresh: true, last_price: 105 }), null)
})

test("mergeLiveBarIntoBars ignores stale live bars", () => {
  const result = mergeLiveBarIntoBars(bars, { date: "2026-05-12", close: 150 })

  assert.equal(result.applied, false)
  assert.equal(result.bars.at(-1).close, 104)
})

test("chartTimeKey preserves intraday ISO timestamps", () => {
  assert.equal(chartTimeKey("2026-06-03T10:30:00Z"), "2026-06-03T10:30:00Z")
  assert.equal(chartTimeKey("2026-06-03"), "2026-06-03")
})

test("live bar high and low include the live close", () => {
  const liveBar = liveBarFromQuote({
    is_fresh: true,
    session_date: "2026-05-14",
    open_price: 104,
    high_price: 105,
    low_price: 103,
    last_price: 108,
    volume: 1200,
  })
  const result = mergeLiveBarIntoBars(bars, liveBar)

  assert.equal(result.applied, true)
  assert.equal(result.bars.at(-1).high, 108)
  assert.equal(result.bars.at(-1).low, 103)
})

test("resolveDashboardSignalDescriptor follows dashboard mode", () => {
  const stock = {
    symbol: "AAA",
    best_signal: {
      source: "wfo",
      variant: "expanded",
      label: "WFO edge",
      signal_label: "Achat",
      direction: "long",
      bucket: "buy",
      action_expected_return_net: 0.04,
      hit_rate: 0.61,
    },
    best_technical_signal: {
      source: "wfo",
      variant: "factor_x_ta",
      label: "Best technical",
      signal_label: "Haussier",
      direction: "long",
      score_pct: 32,
    },
    classic_technical_signal: {
      source: "signal_engine",
      variant: "classic_ta",
      label: "Classic",
      signal_label: "Neutre",
      direction: "none",
      score_pct: 2,
    },
  }

  assert.equal(resolveDashboardSignalDescriptor(stock, "trade_opportunities").kind, "trade")
  assert.equal(resolveDashboardSignalDescriptor(stock, "technical_directions", "best").variant, "factor_x_ta")
  assert.equal(resolveDashboardSignalDescriptor(stock, "technical_directions", "classic").variant, "classic_ta")
})
