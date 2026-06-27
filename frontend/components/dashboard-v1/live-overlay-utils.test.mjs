import test from "node:test"
import assert from "node:assert/strict"

import { applyDashboardLiveOverlays } from "./live-overlay-utils.mjs"

const baseStock = {
  symbol: "AAA",
  display_name: "AAA",
  sector: "Banques",
  last_price: 100,
  prev_close: 98,
  var1j_pct: 2.04,
  performance: {
    one_day: { pct: 2.04, start_price: 98, end_price: 100, source: "official_close" },
    mtd: { pct: 5, start_price: 95, end_price: 100, source: "official_close" },
  },
  best_signal: { signal_label: "Achat", score: 40 },
  best_technical_signal: { signal_label: "Achat", score_pct: 35 },
  classic_technical_signal: { signal_label: "Neutre", score_pct: 0 },
}

test("quote polling updates displayed price without replacing signals", () => {
  const liveQuote = {
    symbol: "AAA",
    is_fresh: true,
    last_price: 111,
    prev_close: 100,
  }

  const [stock] = applyDashboardLiveOverlays(
    [baseStock],
    {},
    { AAA: liveQuote },
    { AAA: { asset_class: "equity", asset_type: "equity", market_region: "masi" } },
  )

  assert.equal(stock.last_price, 111)
  assert.equal(stock.live_quote, liveQuote)
  assert.deepEqual(stock.best_signal, baseStock.best_signal)
  assert.deepEqual(stock.best_technical_signal, baseStock.best_technical_signal)
  assert.deepEqual(stock.classic_technical_signal, baseStock.classic_technical_signal)
  assert.equal(stock.market_region, "masi")
})

test("live refresh overlay replaces price and signal fields together", () => {
  const overlay = {
    symbol: "AAA",
    live_quote: {
      symbol: "AAA",
      is_fresh: true,
      last_price: 120,
      prev_close: 100,
    },
    last_price: 120,
    prev_close: 100,
    var1j_pct: 20,
    performance: {
      one_day: { pct: 20, start_price: 100, end_price: 120, source: "live_quote" },
      open_to_now: { pct: 14.29, start_price: 105, end_price: 120, source: "live_quote" },
    },
    best_signal: { signal_label: "Vente", score: -75, live_adjusted: true },
    best_technical_signal: { signal_label: "Vente forte", score_pct: -82, live_adjusted: true },
    classic_technical_signal: { signal_label: "Vente", score_pct: -50, live_adjusted: true },
  }

  const [stock] = applyDashboardLiveOverlays([baseStock], { AAA: overlay })

  assert.equal(stock.last_price, 120)
  assert.equal(stock.prev_close, 100)
  assert.equal(stock.var1j_pct, 20)
  assert.deepEqual(stock.performance.one_day, overlay.performance.one_day)
  assert.deepEqual(stock.performance.open_to_now, overlay.performance.open_to_now)
  assert.deepEqual(stock.performance.mtd, baseStock.performance.mtd)
  assert.deepEqual(stock.best_signal, overlay.best_signal)
  assert.deepEqual(stock.best_technical_signal, overlay.best_technical_signal)
  assert.deepEqual(stock.classic_technical_signal, overlay.classic_technical_signal)
})

test("explicit null signal overlay clears stale displayed signals", () => {
  const [stock] = applyDashboardLiveOverlays(
    [baseStock],
    {
      AAA: {
        symbol: "AAA",
        last_price: 101,
        best_signal: null,
      },
    },
  )

  assert.equal(stock.last_price, 101)
  assert.equal(stock.best_signal, null)
  assert.deepEqual(stock.best_technical_signal, baseStock.best_technical_signal)
})
