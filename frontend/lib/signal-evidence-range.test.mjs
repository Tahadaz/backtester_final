import test from "node:test"
import assert from "node:assert/strict"

import {
  buildSignalEvidenceRangeView,
  sortEvidenceLedgerRows,
} from "./signal-evidence-range.js"

test("buildSignalEvidenceRangeView recalculates metrics from opened-in-range trades", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
    open_series: [99, 100, 101, 102, 103],
    high_series: [101, 102, 103, 104, 105],
    low_series: [98, 99, 100, 101, 102],
    close_series: [100, 101, 102, 103, 104],
    position_series: [1, 1, 0, 1, 0],
    trades: [
      {
        trade_id: "first",
        direction: "long",
        entry_date: "2026-01-01",
        exit_date: "2026-01-03",
        entry_price: 100,
        action_return_net: 0.1,
        action_return_gross: 0.12,
        stock_return: 0.05,
      },
      {
        trade_id: "second",
        direction: "long",
        entry_date: "2026-01-04",
        exit_date: "2026-01-05",
        entry_price: 100,
        action_return_net: -0.05,
        action_return_gross: -0.04,
        stock_return: -0.01,
      },
    ],
    trade_ledger: [
      { trade_id: "second", date: "2026-01-05", marker_label: "Sell 2", transaction_index: 4, price_kind: "close", pnl_realise: -5 },
      { trade_id: "first", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 2, price_kind: "close", pnl_realise: 10 },
      { trade_id: "second", date: "2026-01-04", marker_label: "Buy 2", transaction_index: 3, price_kind: "open", pnl_realise: 0 },
      { trade_id: "first", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, "2026-01-04")

  assert.deepEqual(view.dates, ["2026-01-04", "2026-01-05"])
  assert.deepEqual(view.open, [102, 103])
  assert.deepEqual(view.high, [104, 105])
  assert.deepEqual(view.low, [101, 102])
  assert.deepEqual(view.close, [103, 104])
  assert.equal(view.metrics.n_trades, 1)
  assert.equal(view.metrics.expected_return_net, -0.05)
  assert.equal(view.metrics.hit_rate, 0)
  assert.equal(view.metrics.total_return, -0.050000000000000044)
  assert.deepEqual(view.equity, [1, 0.95])
  assert.deepEqual(view.position, [1, 0])
  assert.deepEqual(view.ledger.map((row) => row.position), [1, 0])
  assert.deepEqual(view.ledger.map((row) => row.marker_label), ["Buy 2", "Sell 2"])
})

test("buildSignalEvidenceRangeView excludes transactions for trades opened before the selected range", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"],
    close_series: [100, 101, 102, 103, 104],
    position_series: [1, 1, 0, 1, 0],
    trades: [
      { trade_id: "first", direction: "long", entry_date: "2026-01-01", exit_date: "2026-01-03", entry_price: 100, action_return_net: 0.1, action_return_gross: 0.12 },
      { trade_id: "second", direction: "long", entry_date: "2026-01-04", exit_date: "2026-01-05", entry_price: 100, action_return_net: -0.05, action_return_gross: -0.04 },
    ],
    trade_ledger: [
      { trade_id: "first", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
      { trade_id: "first", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 2, price_kind: "close", pnl_realise: 10 },
      { trade_id: "second", date: "2026-01-04", marker_label: "Buy 2", transaction_index: 3, price_kind: "open", pnl_realise: 0 },
      { trade_id: "second", date: "2026-01-05", marker_label: "Sell 2", transaction_index: 4, price_kind: "close", pnl_realise: -5 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, "2026-01-02")

  assert.equal(view.metrics.n_trades, 1)
  assert.equal(view.metrics.expected_return_net, -0.05)
  assert.deepEqual(view.ledger.map((row) => row.marker_label), ["Buy 2", "Sell 2"])
  assert.deepEqual(view.ledger.map((row) => row.position), [1, 0])
  assert.deepEqual(view.position, [0, 0, 1, 0])
})

test("buildSignalEvidenceRangeView uses realized PnL over opened notional instead of compounding returns", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03"],
    close_series: [100, 100, 200],
    trades: [
      { trade_id: "first", direction: "long", entry_date: "2026-01-01", exit_date: "2026-01-03", entry_price: 100, action_return_net: 1, action_return_gross: 1 },
      { trade_id: "second", direction: "long", entry_date: "2026-01-02", exit_date: "2026-01-03", entry_price: 100, action_return_net: 1, action_return_gross: 1 },
    ],
    trade_ledger: [
      { trade_id: "first", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
      { trade_id: "second", date: "2026-01-02", marker_label: "Buy 2", transaction_index: 2, price_kind: "open", pnl_realise: 0 },
      { trade_id: "first", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 3, price_kind: "close", pnl_realise: 100 },
      { trade_id: "second", date: "2026-01-03", marker_label: "Sell 2", transaction_index: 4, price_kind: "close", pnl_realise: 100 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, null)

  assert.equal(view.metrics.total_return, 1)
  assert.deepEqual(view.equity, [1, 1, 2])
})

test("buildSignalEvidenceRangeView treats neutral samples as no action trades", () => {
  const stitched = {
    dates: ["2026-01-01", "2026-01-02", "2026-01-03"],
    close_series: [100, 101, 102],
    trades: [
      {
        trade_id: "neutral-one",
        direction: "none",
        entry_date: "2026-01-01",
        exit_date: "2026-01-03",
        entry_price: 100,
        action_return_net: null,
        action_return_gross: null,
        stock_return: 0.04,
      },
      {
        trade_id: "neutral-two",
        direction: "none",
        entry_date: "2026-01-02",
        exit_date: "2026-01-03",
        entry_price: 100,
        action_return_net: null,
        action_return_gross: null,
        stock_return: 0.02,
      },
    ],
    trade_ledger: [
      { trade_id: "neutral-one", date: "2026-01-01", marker_label: "Buy 1", transaction_index: 1, price_kind: "open", pnl_realise: 0 },
      { trade_id: "neutral-one", date: "2026-01-03", marker_label: "Sell 1", transaction_index: 2, price_kind: "close", pnl_realise: 4 },
    ],
  }

  const view = buildSignalEvidenceRangeView(stitched, null)

  assert.equal(view.metrics.n_trades, 0)
  assert.equal(view.metrics.expected_return_net, null)
  assert.equal(view.metrics.hit_rate, null)
  assert.equal(view.metrics.sharpe, null)
  assert.equal(Math.abs(view.metrics.stock_expected_return - 0.03) < 1e-12, true)
  assert.deepEqual(view.trades, [])
  assert.equal(view.sampleTrades.length, 2)
  assert.deepEqual(view.ledger, [])
  assert.deepEqual(view.position, [0, 0, 0])
})

test("sortEvidenceLedgerRows falls back to date then execution timing when transaction indexes are absent", () => {
  const sorted = sortEvidenceLedgerRows([
    { date: "2026-01-02", marker_label: "Sell 1", price_kind: "close", trade_sequence: 1 },
    { date: "2026-01-02", marker_label: "Buy 2", price_kind: "open", trade_sequence: 2 },
    { date: "2026-01-01", marker_label: "Buy 1", price_kind: "open", trade_sequence: 1 },
  ])

  assert.deepEqual(sorted.map((row) => row.marker_label), ["Buy 1", "Buy 2", "Sell 1"])
})
